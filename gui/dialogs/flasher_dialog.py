"""
固件烧录对话框
"""
import os
import sys
import json
import subprocess
import time
import threading
import hashlib
import shutil
import requests
from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QComboBox, QTextEdit, QProgressBar, QMessageBox,
    QWidget, QFormLayout, QGroupBox, QRadioButton, QButtonGroup
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QIcon

from config.constants import APP_NAME

import logging
logger = logging.getLogger(__name__)

# 从原始代码中获取的常量
MANIFEST_URL = "https://epflash.iccmc.cc/{rev}/{screen}/manifest.json"
FLASHER_VERSION = 2

class FlasherWorker(QThread):
    """烧录工作线程"""
    
    progress_updated = pyqtSignal(str, int)
    status_updated = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal()
    
    def __init__(self, flasher_dir: str, rev: str, screen: str, version_info=None, mirror_url=None):
        super().__init__()
        self.flasher_dir = flasher_dir
        self.rev = rev
        self.screen = screen
        self.version_info = version_info  # 用户选择的版本信息
        self.mirror_url = mirror_url  # 用户选择的下载源
        self.bin_path = os.path.join(flasher_dir, "bin")
        # 使用当前用户可访问的缓存目录
        self.cache_path = os.path.join(os.path.dirname(flasher_dir), "cache")
        self.is_running = True
    
    def run(self):
        try:
            # 设置环境变量
            os.environ["PATH"] += os.pathsep + self.bin_path
            
            # 1. 检查驱动
            self.status_updated.emit("检查驱动...")
            self._check_driver()
            
            # 2. 获取烧录文件
            self.status_updated.emit("获取烧录文件...")
            files = self._get_flash_files()
            
            # 3. 等待设备连接
            self.status_updated.emit("等待设备连接...")
            self._wait_for_device()
            
            # 4. 开始烧录
            self.status_updated.emit("开始烧录...")
            self._flash_device(files)
            
            # 5. 完成
            self.status_updated.emit("烧录完成，设备正在重启...")
            self.finished.emit()
            
        except Exception as e:
            self.error_occurred.emit(str(e))
    
    def _check_driver(self):
        # 检查驱动安装状态
        config_dir = os.path.join(os.path.dirname(self.flasher_dir), "config")
        config_file = os.path.join(config_dir, "config.json")
        if not os.path.exists(config_file):
            os.makedirs(config_dir, exist_ok=True)
            with open(config_file, "w") as f:
                json.dump({"driver_installed": False, "eula_accepted": True}, f)
        
        with open(config_file, "r") as f:
            config = json.load(f)
        
        if not config.get("driver_installed", False):
            self.status_updated.emit("安装驱动...")
            drv_bat = os.path.join(self.bin_path, "drv_install.bat")
            if os.path.exists(drv_bat):
                subprocess.run([drv_bat], shell=True)
                
            # 更新配置
            config["driver_installed"] = True
            with open(config_file, "w") as f:
                json.dump(config, f)
        else:
            self.status_updated.emit("驱动已安装，跳过...")
    
    def _get_flash_files(self):
        """从服务器获取烧录文件"""
        # 检查bin目录是否存在必要的烧录文件
        bin_dir = os.path.join(self.flasher_dir, "bin")
        if not os.path.exists(bin_dir):
            raise Exception(f"烧录工具目录不存在: {bin_dir}")
        
        # 检查是否有烧录文件
        test_file = os.path.join(bin_dir, "xfel.exe")
        if not os.path.exists(test_file):
            raise Exception(f"烧录工具不完整，请确保epass_flasher目录包含所有必要文件")
        
        # 检查是否为占位符版本
        try:
            with open(test_file, 'r', encoding='utf-8') as f:
                content = f.read()
                if '占位符版本' in content or 'placeholder' in content.lower():
                    raise Exception(
                        "当前使用的是epass_flasher占位符版本，无法执行实际的烧录操作。\n\n"
                        "如需使用完整的固件烧录功能，请执行以下步骤之一：\n"
                        "1. 手动克隆子模块：git clone https://github.com/rhodesepass/epass_flasher.git epass_flasher\n"
                        "2. 初始化Git子模块：git submodule update --init --recursive\n\n"
                        "详细说明请查看 epass_flasher/README.md"
                    )
        except Exception as e:
            if '占位符版本' in str(e):
                raise
            # 如果读取失败，可能是真正的exe文件，继续执行
        
        # 1. 获取manifest
        self.status_updated.emit("获取固件信息...")
        manifest = self._fetch_manifest()
        
        # 2. 选择版本并下载文件
        self.status_updated.emit("选择固件版本...")
        files = self._download_flash_files(manifest)
        
        return files
    
    def _fetch_manifest(self):
        """获取固件manifest信息"""
        url = MANIFEST_URL.format(rev=self.rev, screen=self.screen)
        self.status_updated.emit(f"请求: {url}")
        
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            manifest = response.json()
            
            # 检查flasher版本
            if manifest.get("flasher", {}).get("latest_version", 0) > FLASHER_VERSION:
                self.status_updated.emit(f"有新版本的刷机程序可用")
            
            return manifest
        except Exception as e:
            raise Exception(f"获取固件信息失败: {str(e)}")
    
    def _download_flash_files(self, manifest):
        """下载烧录文件"""
        # 选择版本
        if self.version_info:
            # 使用用户选择的版本
            version_item = self.version_info
            self.status_updated.emit(f"选择版本: {version_item['type']}:{version_item['title']}")
        else:
            # 默认选择第一个版本
            if not manifest.get("manifest"):
                raise Exception("固件版本列表为空")
            version_item = manifest["manifest"][0]
            self.status_updated.emit(f"选择版本: {version_item['type']}:{version_item['title']} (默认)")
        
        # 检查版本兼容性
        if version_item.get("minimal_flasher_version", 0) > FLASHER_VERSION:
            raise Exception("当前烧录工具版本过低，请更新")
        
        # 准备下载
        version_cache = os.path.join(self.cache_path, version_item["version"])
        os.makedirs(version_cache, exist_ok=True)
        
        # 检查需要下载的文件
        files_to_download = []
        for file_info in version_item["files"]:
            file_path = os.path.join(version_cache, file_info["name"])
            if not os.path.exists(file_path):
                files_to_download.append(file_info)
            else:
                # 验证哈希值
                with open(file_path, "rb") as f:
                    file_hash = hashlib.sha256(f.read()).hexdigest()
                if file_hash != file_info["hash"]:
                    self.status_updated.emit(f"文件{file_info['name']}哈希值不匹配，重新下载")
                    os.remove(file_path)
                    files_to_download.append(file_info)
                else:
                    self.status_updated.emit(f"文件{file_info['name']}已存在且验证通过")
        
        # 下载文件
        if files_to_download:
            # 选择下载源
            if self.mirror_url:
                # 使用用户选择的下载源
                mirror = self.mirror_url
                self.status_updated.emit(f"使用下载源: 用户选择的下载源")
            else:
                # 默认选择第一个下载源
                if not manifest.get("available_mirror"):
                    raise Exception("没有可用的下载源")
                
                # 打印所有可用的下载源
                self.status_updated.emit("可用的下载源:")
                for i, mirror_info in enumerate(manifest["available_mirror"]):
                    self.status_updated.emit(f"{i+1}. {mirror_info['name']}")
                
                selected_mirror = manifest["available_mirror"][0]
                mirror = selected_mirror["url"]
                self.status_updated.emit(f"使用下载源: {selected_mirror['name']} (默认)")
            
            for file_info in files_to_download:
                self.status_updated.emit(f"下载: {file_info['name']}")
                file_path = os.path.join(version_cache, file_info["name"])
                
                # 构建下载URL
                download_url = mirror.replace("${version}", version_item["version"]).replace("${file}", file_info["name"])
                self.status_updated.emit(f"下载地址: {download_url}")
                
                try:
                    # 下载文件
                    self.status_updated.emit(f"开始下载 {file_info['name']}...")
                    response = requests.get(download_url, timeout=60, stream=True)
                    response.raise_for_status()
                    
                    # 获取文件大小
                    total_size = int(response.headers.get('content-length', 0))
                    downloaded_size = 0
                    
                    # 保存文件
                    with open(file_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if not self.is_running:
                                raise Exception("下载被取消")
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            if total_size > 0:
                                progress = int((downloaded_size / total_size) * 100)
                                self.status_updated.emit(f"下载进度: {progress}%")
                    
                    # 验证哈希值
                    self.status_updated.emit(f"验证文件 {file_info['name']}...")
                    with open(file_path, "rb") as f:
                        file_hash = hashlib.sha256(f.read()).hexdigest()
                    if file_hash != file_info["hash"]:
                        os.remove(file_path)
                        raise Exception(f"文件{file_info['name']}哈希值验证失败")
                    
                    self.status_updated.emit(f"完成: {file_info['name']}")
                except Exception as e:
                    raise Exception(f"下载{file_info['name']}失败: {str(e)}")
        
        # 整理返回的文件路径
        result = {"uboot": "", "rootfs": "", "boot": ""}
        for file_info in version_item["files"]:
            file_path = os.path.join(version_cache, file_info["name"])
            if file_info["type"] == "uboot":
                result["uboot"] = file_path
            elif file_info["type"] == "rootfs":
                result["rootfs"] = file_path
            elif file_info["type"] == "boot":
                result["boot"] = file_path
        
        # 检查所有文件是否都已下载
        for key, path in result.items():
            if not path or not os.path.exists(path):
                raise Exception(f"{key}文件未找到或下载失败")
        
        return result
    
    def _wait_for_device(self):
        # 等待设备进入FEL模式
        self.status_updated.emit("请按住FEL按钮并打开设备电源...")
        time.sleep(5)  # 给用户时间操作
        
        # 检查设备连接
        max_attempts = 30
        for attempt in range(max_attempts):
            if not self.is_running:
                break
            
            try:
                result = subprocess.run(
                    [os.path.join(self.bin_path, "xfel.exe"), "spinand"],
                    capture_output=True, text=True, timeout=2
                )
                if "Found spi nand flash" in result.stdout:
                    self.status_updated.emit("设备连接成功！")
                    return
                elif "ERROR: No FEL device found!" in result.stdout:
                    self.status_updated.emit(f"等待设备... ({attempt+1}/{max_attempts})")
                    time.sleep(1)
                else:
                    self.status_updated.emit(f"设备状态: {result.stdout.strip()}")
                    time.sleep(1)
            except Exception as e:
                self.status_updated.emit(f"检查设备失败: {str(e)}")
                time.sleep(1)
        
        raise Exception("设备连接超时，请检查设备连接状态")
    
    def _flash_device(self, files):
        # 创建bootenv.txt在缓存目录中
        bootenv_path = os.path.join(self.cache_path, "bootenv.txt")
        with open(bootenv_path, "wb") as f:
            f.write(f"device_rev={self.rev}\n".encode("utf-8"))
            f.write(f"screen={self.screen}\n".encode("utf-8"))
            f.write(b"\x00")
        
        # 执行烧录命令
        commands = [
            ["xfel.exe", "spinand", "erase", "0x100000", "0xC00000"],
            ["xfel.exe", "spinand", "write", "0", files["uboot"]],
            ["xfel.exe", "spinand", "write", "0xfa000", bootenv_path],
            ["xfel.exe", "reset"]
        ]
        
        for cmd in commands:
            if not self.is_running:
                break
            
            cmd_path = os.path.join(self.bin_path, cmd[0])
            cmd_full = [cmd_path] + cmd[1:]
            
            self.status_updated.emit(f"执行: {' '.join(cmd)}")
            result = subprocess.run(cmd_full, capture_output=True, text=True)
            
            if result.returncode != 0:
                raise Exception(f"命令执行失败: {' '.join(cmd)}\n{result.stderr}")
            
            self.status_updated.emit(f"完成: {' '.join(cmd)}")
        
        # 等待DFU模式
        self.status_updated.emit("等待设备进入DFU模式...")
        time.sleep(3)
        
        # 烧录boot和rootfs
        dfu_commands = [
            ["dfu-util.exe", "-d", "1f3a:1010", "-R", "-a", "boot", "-D", files["boot"]],
            ["dfu-util.exe", "-d", "1f3a:1010", "-R", "-a", "rootfs", "-D", files["rootfs"]]
        ]
        
        for cmd in dfu_commands:
            if not self.is_running:
                break
            
            cmd_path = os.path.join(self.bin_path, cmd[0])
            cmd_full = [cmd_path] + cmd[1:]
            
            self.status_updated.emit(f"执行DFU命令: {' '.join(cmd)}")
            result = subprocess.run(cmd_full, capture_output=True, text=True)
            
            if result.returncode != 0:
                # DFU命令可能需要重试
                self.status_updated.emit(f"DFU命令失败，重试...")
                time.sleep(2)
                result = subprocess.run(cmd_full, capture_output=True, text=True)
                
                if result.returncode != 0:
                    raise Exception(f"DFU命令执行失败: {' '.join(cmd)}\n{result.stderr}")
            
            self.status_updated.emit(f"DFU命令完成: {' '.join(cmd)}")
            time.sleep(2)  # 给设备时间重启
    
    def stop(self):
        self.is_running = False

class FlasherDialog(QDialog):
    """固件烧录对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("固件烧录")
        self.setMinimumSize(600, 400)
        self.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), "..", "..", "resources", "icons", "favicon.ico")))
        
        # 布局
        layout = QVBoxLayout(self)
        
        # 标题
        title_label = QLabel("电子通行证烧录程序")
        title_label.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("color: #ff6b8b; margin: 10px 0;")
        layout.addWidget(title_label)
        
        # 版本信息
        version_label = QLabel("Proj0cpy 专用版 v2\n罗德岛工程部 (c)1097")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_label.setStyleSheet("color: #666666; margin-bottom: 15px;")
        layout.addWidget(version_label)
        
        # 主内容区域 - 水平布局
        main_content_layout = QHBoxLayout()
        
        # 左侧：选项区域
        left_layout = QVBoxLayout()
        
        # 设备信息组
        device_group = QGroupBox("设备信息")
        device_group.setStyleSheet("QGroupBox { font-weight: bold; color: #555; border: 1px solid #ddd; border-radius: 6px; padding: 10px; margin: 5px 0; } QGroupBox::title { subcontrol-position: top left; padding: 0 10px; background-color: #f8f9fa; border-radius: 4px; }")
        device_layout = QFormLayout()
        device_layout.setSpacing(10)
        
        # 设备版本
        self.rev_combo = QComboBox()
        self.rev_combo.addItems(["0.2系列", "0.3/0.4系列(0.3/0.3.1/0.4/....)", "0.5系列(0.5/0.5.1)", "0.6系列"])
        self.rev_combo.setStyleSheet("""
            QComboBox {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 200px;
            }
            QComboBox:hover {
                border-color: #ff6b8b;
            }
            QComboBox::drop-down {
                border-left: 1px solid #ddd;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
            }
            QComboBox QAbstractItemView {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 4px;
            }
        """)
        device_layout.addRow("设备版本:", self.rev_combo)
        
        # 屏幕类型
        self.screen_combo = QComboBox()
        self.screen_combo.addItems(["京东方/BOE（没法旋转，冠显等商家）", "瀚彩/HSD（金逸晨、鑫睿等商家）", "老五电子买的3块钱的屏幕"])
        self.screen_combo.setStyleSheet("""
            QComboBox {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 200px;
            }
            QComboBox:hover {
                border-color: #ff6b8b;
            }
            QComboBox::drop-down {
                border-left: 1px solid #ddd;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
            }
            QComboBox QAbstractItemView {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 4px;
            }
        """)
        device_layout.addRow("屏幕类型:", self.screen_combo)
        
        device_group.setLayout(device_layout)
        left_layout.addWidget(device_group)
        
        # 烧录版本组
        version_group = QGroupBox("烧录版本")
        version_group.setStyleSheet("QGroupBox { font-weight: bold; color: #555; border: 1px solid #ddd; border-radius: 6px; padding: 10px; margin: 5px 0; } QGroupBox::title { subcontrol-position: top left; padding: 0 10px; background-color: #f8f9fa; border-radius: 4px; }")
        version_layout = QVBoxLayout()
        version_layout.setSpacing(10)
        
        # 版本选择下拉框
        version_label = QLabel("可用版本:")
        version_label.setStyleSheet("color: #666;")
        version_layout.addWidget(version_label)
        self.version_combo = QComboBox()
        self.version_combo.addItem("请先获取版本信息...")
        self.version_combo.setStyleSheet("""
            QComboBox {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 200px;
            }
            QComboBox:hover {
                border-color: #ff6b8b;
            }
            QComboBox::drop-down {
                border-left: 1px solid #ddd;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
            }
            QComboBox QAbstractItemView {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 4px;
            }
        """)
        version_layout.addWidget(self.version_combo)
        
        # 下载源选择
        mirror_label = QLabel("下载源:")
        mirror_label.setStyleSheet("color: #666;")
        version_layout.addWidget(mirror_label)
        self.mirror_combo = QComboBox()
        self.mirror_combo.addItem("请先获取版本信息...")
        self.mirror_combo.setStyleSheet("""
            QComboBox {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 200px;
            }
            QComboBox:hover {
                border-color: #ff6b8b;
            }
            QComboBox::drop-down {
                border-left: 1px solid #ddd;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
            }
            QComboBox QAbstractItemView {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 4px;
            }
        """)
        version_layout.addWidget(self.mirror_combo)
        
        version_group.setLayout(version_layout)
        left_layout.addWidget(version_group)
        
        # 按钮组
        button_group = QGroupBox("操作")
        button_group.setStyleSheet("QGroupBox { font-weight: bold; color: #555; border: 1px solid #ddd; border-radius: 6px; padding: 10px; margin: 5px 0; } QGroupBox::title { subcontrol-position: top left; padding: 0 10px; background-color: #f8f9fa; border-radius: 4px; }")
        button_layout = QVBoxLayout()
        button_layout.setSpacing(8)
        
        self.install_driver_button = QPushButton("安装驱动")
        self.install_driver_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 10px 20px;
                border: none;
                border-radius: 4px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        self.install_driver_button.clicked.connect(self._on_install_driver)
        
        self.get_version_button = QPushButton("获取版本信息")
        self.get_version_button.setStyleSheet("""
            QPushButton {
                background-color: #666666;
                color: white;
                padding: 10px 20px;
                border: none;
                border-radius: 4px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #555555;
            }
            QPushButton:pressed {
                background-color: #444444;
            }
        """)
        self.get_version_button.clicked.connect(self._on_get_version)
        
        self.start_button = QPushButton("开始烧录")
        self.start_button.setStyleSheet("""
            QPushButton {
                background-color: #ff6b8b;
                color: white;
                padding: 10px 20px;
                border: none;
                border-radius: 4px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #ff527b;
            }
            QPushButton:pressed {
                background-color: #ff3861;
            }
        """)
        self.start_button.clicked.connect(self._on_start)
        
        self.update_firmware_button = QPushButton("更新固件")
        self.update_firmware_button.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                padding: 10px 20px;
                border: none;
                border-radius: 4px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:pressed {
                background-color: #1565C0;
            }
        """)
        self.update_firmware_button.clicked.connect(self._on_update_firmware)
        
        button_layout.addWidget(self.install_driver_button)
        button_layout.addWidget(self.get_version_button)
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.update_firmware_button)
        
        button_group.setLayout(button_layout)
        left_layout.addWidget(button_group)
        
        left_layout.addStretch()
        
        # 右侧：日志区域
        right_layout = QVBoxLayout()
        
        # 状态显示
        status_group = QGroupBox("烧录状态")
        status_group.setStyleSheet("QGroupBox { font-weight: bold; color: #555; border: 1px solid #ddd; border-radius: 6px; padding: 10px; margin: 5px 0; } QGroupBox::title { subcontrol-position: top left; padding: 0 10px; background-color: #f8f9fa; border-radius: 4px; }")
        status_layout = QVBoxLayout()
        status_layout.setSpacing(10)
        
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 10px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
                line-height: 1.4;
            }
        """)
        status_layout.addWidget(self.status_text)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #f8f9fa;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 2px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #ff6b8b;
                border-radius: 2px;
            }
        """)
        status_layout.addWidget(self.progress_bar)
        
        status_group.setLayout(status_layout)
        right_layout.addWidget(status_group)
        

        
        # 设置左右布局比例
        main_content_layout.addLayout(left_layout, 1)
        main_content_layout.addLayout(right_layout, 2)
        
        layout.addLayout(main_content_layout)
        
        # 工作线程
        self.worker = None
        self.flasher_dir = os.path.join(os.path.dirname(__file__), "..", "..", "epass_flasher")
        self.bin_path = os.path.join(self.flasher_dir, "bin")  # 添加bin_path属性
        
        # 固件信息
        self.manifest = None
        self.selected_version = None
        self.selected_mirror = None
    
    def _on_start(self):
        """开始烧录"""
        # 检查epass_flasher目录
        if not os.path.exists(self.flasher_dir):
            QMessageBox.warning(
                self, 
                "提示", 
                "epass_flasher目录不存在，固件烧录功能暂不可用。\n\n"
                "当前使用的是占位符版本，无法执行实际的烧录操作。\n\n"
                "如需使用完整的固件烧录功能，请执行以下步骤之一：\n"
                "1. 手动克隆子模块：git clone https://github.com/rhodesepass/epass_flasher.git epass_flasher\n"
                "2. 初始化Git子模块：git submodule update --init --recursive\n\n"
                "详细说明请查看 epass_flasher/README.md"
            )
            return
        
        # 获取设备信息
        rev_index = self.rev_combo.currentIndex()
        rev_map = {0: "0.2", 1: "0.3", 2: "0.5", 3: "0.6"}
        rev = rev_map.get(rev_index, "0.3")
        
        screen_index = self.screen_combo.currentIndex()
        screen_map = {0: "boe", 1: "hsd", 2: "laowu"}
        screen = screen_map.get(screen_index, "hsd")
        
        # 显示警告
        warning_msg = """烧录将会清除设备内所有数据，请提前备份好资源文件！
请确认你的设备的版本并选择正确的配置文件！

请按住设备开关旁的按钮（FEL按钮），并打开设备电源，
等待几秒钟后松开FEL按钮，将设备连接上电脑。"""
        
        reply = QMessageBox.warning(
            self, "警告", warning_msg,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
        )
        
        if reply != QMessageBox.StandardButton.Ok:
            return
        
        # 禁用按钮
        self.start_button.setEnabled(False)
        self.cancel_button.setText("停止")
        
        # 清空状态
        self.status_text.clear()
        self.status_text.append("=== 开始烧录流程 ===")
        
        # 获取用户选择的版本和下载源
        version_info = None
        mirror_url = None
        
        if self.version_combo.currentIndex() >= 0:
            version_info = self.version_combo.currentData()
        
        if self.mirror_combo.currentIndex() >= 0:
            mirror_url = self.mirror_combo.currentData()
        
        # 启动工作线程
        self.worker = FlasherWorker(self.flasher_dir, rev, screen, version_info, mirror_url)
        self.worker.status_updated.connect(self._on_status_update)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()
    
    def _on_cancel(self):
        """取消烧录"""
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self, "确认", "正在烧录中，确定要停止吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.worker.stop()
                self.status_text.append("正在停止烧录...")
    
    def _on_status_update(self, message):
        """状态更新"""
        self.status_text.append(message)
        self.status_text.verticalScrollBar().setValue(self.status_text.verticalScrollBar().maximum())
    
    def _on_error(self, error):
        """错误处理"""
        self.status_text.append(f"错误: {error}")
        self.status_text.append("烧录失败")
        self.start_button.setEnabled(True)
        self.cancel_button.setText("取消")
        QMessageBox.critical(self, "错误", f"烧录失败: {error}")
    
    def _on_finished(self):
        """烧录完成"""
        self.status_text.append("=== 烧录完成 ===")
        self.status_text.append("设备正在重启，请耐心等待...")
        self.start_button.setEnabled(True)
        self.cancel_button.setText("关闭")
        QMessageBox.information(self, "完成", "烧录完成！设备正在重启，请耐心等待。")
    
    def _on_get_version(self):
        """获取版本信息"""
        try:
            # 检查epass_flasher目录
            if not os.path.exists(self.flasher_dir):
                QMessageBox.warning(
                    self, 
                    "提示", 
                    "epass_flasher目录不存在，固件烧录功能暂不可用。\n\n"
                    "当前使用的是占位符版本，无法执行实际的烧录操作。\n\n"
                    "如需使用完整的固件烧录功能，请执行以下步骤之一：\n"
                    "1. 手动克隆子模块：git clone https://github.com/rhodesepass/epass_flasher.git epass_flasher\n"
                    "2. 初始化Git子模块：git submodule update --init --recursive\n\n"
                    "详细说明请查看 epass_flasher/README.md"
                )
                return
            
            # 获取设备信息
            rev_index = self.rev_combo.currentIndex()
            rev_map = {0: "0.2", 1: "0.3", 2: "0.5", 3: "0.6"}
            rev = rev_map.get(rev_index, "0.3")
            
            screen_index = self.screen_combo.currentIndex()
            screen_map = {0: "boe", 1: "hsd", 2: "laowu"}
            screen = screen_map.get(screen_index, "hsd")
            
            # 获取版本信息
            self.status_text.append("=== 获取版本信息 ===")
            self.status_text.append(f"设备版本: {rev}")
            self.status_text.append(f"屏幕类型: {screen}")
            
            # 从服务器获取manifest
            url = MANIFEST_URL.format(rev=rev, screen=screen)
            self.status_text.append(f"请求: {url}")
            
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            manifest = response.json()
            
            # 保存manifest
            self.manifest = manifest
            
            # 更新版本选择下拉框
            self.version_combo.clear()
            if not manifest.get("manifest"):
                self.version_combo.addItem("无可用版本")
                raise Exception("固件版本列表为空")
            
            for i, version_item in enumerate(manifest["manifest"]):
                version_name = f"{version_item['type']}:{version_item['title']}"
                if version_item.get("commit"):
                    version_name += f" ({version_item['commit'][:7]})"
                self.version_combo.addItem(version_name, version_item)
            
            # 更新下载源选择下拉框
            self.mirror_combo.clear()
            if not manifest.get("available_mirror"):
                self.mirror_combo.addItem("无可用下载源")
                raise Exception("没有可用的下载源")
            
            for mirror_info in manifest["available_mirror"]:
                self.mirror_combo.addItem(mirror_info["name"], mirror_info["url"])
            
            # 连接版本选择信号
            self.version_combo.currentIndexChanged.connect(self._on_version_selected)
            
            # 默认选择第一个版本
            if self.version_combo.count() > 0:
                self.version_combo.setCurrentIndex(0)
                self._on_version_selected(0)
            
            self.status_text.append("版本信息获取成功！")
            QMessageBox.information(self, "成功", "版本信息获取成功！")
            
        except Exception as e:
            self.status_text.append(f"获取版本信息失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"获取版本信息失败:\n{str(e)}")
    
    def _on_version_selected(self, index):
        """版本选择事件"""
        if not self.manifest or not self.manifest.get("manifest") or index < 0 or index >= len(self.manifest["manifest"]):
            return
        
        version_item = self.manifest["manifest"][index]
        self.selected_version = version_item
    
    def _on_install_driver(self):
        """手动安装驱动"""
        try:
            self.status_text.append("=== 开始安装驱动 ===")
            
            # 检查epass_flasher目录
            if not os.path.exists(self.flasher_dir):
                QMessageBox.warning(
                    self, 
                    "提示", 
                    "epass_flasher目录不存在，固件烧录功能暂不可用。\n\n"
                    "当前使用的是占位符版本，无法执行实际的烧录操作。\n\n"
                    "如需使用完整的固件烧录功能，请执行以下步骤之一：\n"
                    "1. 手动克隆子模块：git clone https://github.com/rhodesepass/epass_flasher.git epass_flasher\n"
                    "2. 初始化Git子模块：git submodule update --init --recursive\n\n"
                    "详细说明请查看 epass_flasher/README.md"
                )
                return
            
            # 检查驱动安装文件
            drv_bat = os.path.join(self.bin_path, "drv_install.bat")
            if not os.path.exists(drv_bat):
                raise Exception(f"驱动安装文件不存在: {drv_bat}")
            
            self.status_text.append("正在安装驱动...")
            
            # 运行驱动安装脚本
            result = subprocess.run([drv_bat], shell=True, capture_output=True, text=True)
            
            if result.returncode == 0:
                self.status_text.append("驱动安装成功！")
                
                # 更新配置
                config_dir = os.path.join(os.path.dirname(self.flasher_dir), "config")
                config_file = os.path.join(config_dir, "config.json")
                os.makedirs(config_dir, exist_ok=True)
                
                config = {"driver_installed": True, "eula_accepted": True}
                with open(config_file, "w") as f:
                    json.dump(config, f)
                
                QMessageBox.information(self, "成功", "驱动安装成功！")
            else:
                self.status_text.append(f"驱动安装失败: {result.stderr}")
                QMessageBox.warning(self, "警告", f"驱动安装可能失败:\n{result.stderr}")
                
        except Exception as e:
            self.status_text.append(f"驱动安装失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"驱动安装失败:\n{str(e)}")
    
    def _on_update_firmware(self):
        """更新固件到最新版本"""
        try:
            # 确认更新
            reply = QMessageBox.question(
                self, 
                "确认更新", 
                "确定要更新固件到最新版本吗？\n\n"
                "更新将从GitHub下载最新的epass_flasher模块。\n"
                "更新过程可能需要几分钟时间，请确保网络连接正常。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply != QMessageBox.StandardButton.Yes:
                return
            
            # 禁用按钮
            self.update_firmware_button.setEnabled(False)
            self.status_text.clear()
            self.status_text.append("=== 开始更新固件 ===")
            
            # 创建更新线程
            self.update_worker = FirmwareUpdateWorker(self.flasher_dir)
            self.update_worker.progress_updated.connect(self._on_update_progress)
            self.update_worker.status_updated.connect(self._on_update_status)
            self.update_worker.error_occurred.connect(self._on_update_error)
            self.update_worker.finished.connect(self._on_update_finished)
            self.update_worker.start()
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"更新失败: {str(e)}")
            self.update_firmware_button.setEnabled(True)
    
    def _on_update_progress(self, message, progress):
        """更新进度"""
        self.status_text.append(message)
        self.progress_bar.setValue(progress)
    
    def _on_update_status(self, message):
        """更新状态"""
        self.status_text.append(message)
        self.status_text.verticalScrollBar().setValue(self.status_text.verticalScrollBar().maximum())
    
    def _on_update_error(self, error):
        """更新错误"""
        self.status_text.append(f"错误: {error}")
        self.status_text.append("更新失败")
        self.update_firmware_button.setEnabled(True)
        QMessageBox.critical(self, "错误", f"更新失败: {error}")
    
    def _on_update_finished(self):
        """更新完成"""
        self.status_text.append("=== 更新完成 ===")
        self.status_text.append("固件已更新到最新版本！")
        self.progress_bar.setValue(100)
        self.update_firmware_button.setEnabled(True)
        QMessageBox.information(self, "完成", "固件已成功更新到最新版本！")

class FirmwareUpdateWorker(QThread):
    """固件更新工作线程"""
    
    progress_updated = pyqtSignal(str, int)
    status_updated = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal()
    
    def __init__(self, flasher_dir: str):
        super().__init__()
        self.flasher_dir = flasher_dir
        self.bin_path = os.path.join(flasher_dir, "bin")
        self.is_running = True
    
    def run(self):
        try:
            self.status_updated.emit("正在检查当前版本...")
            time.sleep(1)
            
            # 备份当前bin目录
            backup_bin = os.path.join(self.flasher_dir, 'bin_backup')
            current_bin = os.path.join(self.flasher_dir, 'bin')
            
            if os.path.exists(current_bin):
                self.status_updated.emit("备份当前版本...")
                if os.path.exists(backup_bin):
                    shutil.rmtree(backup_bin)
                shutil.copytree(current_bin, backup_bin)
                self.progress_updated.emit("备份完成", 20)
            
            # 克隆最新版本（带重试机制）
            self.status_updated.emit("正在从GitHub下载最新版本...")
            temp_path = os.path.join(os.path.dirname(self.flasher_dir), 'epass_flasher_temp')
            
            if os.path.exists(temp_path):
                shutil.rmtree(temp_path)
            
            # 多个镜像源尝试
            mirrors = [
                'https://github.com/rhodesepass/epass_flasher.git',
                'https://hub.nuaa.cf/rhodesepass/epass_flasher.git',
                'https://kkgithub.com/rhodesepass/epass_flasher.git',
                'https://kgithub.com/rhodesepass/epass_flasher.git',
                'https://gitclone.com/github.com/rhodesepass/epass_flasher.git'
            ]
            
            clone_success = False
            last_error = ""
            
            for attempt, mirror_url in enumerate(mirrors):
                if not self.is_running:
                    break
                
                self.status_updated.emit(f"尝试连接镜像源 {attempt + 1}/{len(mirrors)}...")
                
                clone_cmd = [
                    'git', 'clone',
                    '--depth', '1',
                    mirror_url,
                    temp_path
                ]
                
                result = subprocess.run(clone_cmd, capture_output=True, text=True)
                
                if result.returncode == 0:
                    clone_success = True
                    self.status_updated.emit(f"镜像源 {attempt + 1} 连接成功！")
                    break
                else:
                    last_error = result.stderr
                    self.status_updated.emit(f"镜像源 {attempt + 1} 连接失败，尝试下一个...")
                    time.sleep(2)
            
            if not clone_success:
                raise Exception(
                    f"所有镜像源连接失败，请检查网络连接。\n\n"
                    f"最后错误信息: {last_error}\n\n"
                    f"建议解决方案:\n"
                    f"1. 检查网络连接是否正常\n"
                    f"2. 尝试使用VPN或代理\n"
                    f"3. 稍后重试"
                )
            
            self.progress_updated.emit("下载完成", 60)
            
            # 更新bin目录
            self.status_updated.emit("正在更新bin目录...")
            source_bin = os.path.join(temp_path, 'bin')
            
            if os.path.exists(source_bin):
                # 删除旧的bin目录内容
                for item in os.listdir(current_bin):
                    item_path = os.path.join(current_bin, item)
                    try:
                        if os.path.isfile(item_path):
                            os.remove(item_path)
                        else:
                            shutil.rmtree(item_path)
                    except Exception as e:
                        self.status_updated.emit(f"删除失败 {item}: {e}")
                
                # 复制新文件
                for item in os.listdir(source_bin):
                    src = os.path.join(source_bin, item)
                    dst = os.path.join(current_bin, item)
                    
                    if os.path.isfile(src):
                        shutil.copy2(src, dst)
                    else:
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                
                self.progress_updated.emit("bin目录更新完成", 80)
            
            # 更新其他文件
            self.status_updated.emit("正在更新其他文件...")
            for item in os.listdir(temp_path):
                if item in ['bin', '.git']:
                    continue
                    
                src = os.path.join(temp_path, item)
                dst = os.path.join(self.flasher_dir, item)
                
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
                elif os.path.isdir(src):
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst, dirs_exist_ok=True)
            
            self.progress_updated.emit("文件更新完成", 90)
            
            # 清理临时目录（使用多种方法）
            self.status_updated.emit("正在清理临时文件...")
            self._cleanup_temp_directory(temp_path)
            
            # 检查关键文件
            xfel_path = os.path.join(current_bin, 'xfel.exe')
            if not os.path.exists(xfel_path):
                raise Exception("更新后xfel.exe不存在")
            
            self.status_updated.emit("更新成功！")
            self.finished.emit()
            
        except Exception as e:
            self.error_occurred.emit(str(e))
    
    def stop(self):
        self.is_running = False
    
    def _cleanup_temp_directory(self, temp_path):
        """清理临时目录，使用多种方法确保删除成功"""
        if not os.path.exists(temp_path):
            self.progress_updated.emit("清理完成", 100)
            return
        
        cleanup_methods = [
            ("方法1: 标准删除", self._cleanup_standard),
            ("方法2: 强制删除", self._cleanup_force),
            ("方法3: 递归删除", self._cleanup_recursive),
            ("方法4: 命令行删除", self._cleanup_command)
        ]
        
        for method_name, method_func in cleanup_methods:
            if not os.path.exists(temp_path):
                break
                
            try:
                self.status_updated.emit(f"正在清理（{method_name}）...")
                method_func(temp_path)
                
                if not os.path.exists(temp_path):
                    self.status_updated.emit(f"{method_name}成功！")
                    self.progress_updated.emit("清理完成", 100)
                    return
            except Exception as e:
                self.status_updated.emit(f"{method_name}失败: {e}")
                time.sleep(1)
        
        # 如果所有方法都失败，使用计划任务延迟删除
        if os.path.exists(temp_path):
            self.status_updated.emit("所有方法失败，创建延迟删除任务...")
            self._schedule_cleanup(temp_path)
            self.status_updated.emit("临时文件将在下次重启时自动删除")
            self.progress_updated.emit("清理完成", 100)
        else:
            self.progress_updated.emit("清理完成", 100)
    
    def _cleanup_standard(self, temp_path):
        """标准删除方法"""
        shutil.rmtree(temp_path)
    
    def _cleanup_force(self, temp_path):
        """强制删除方法"""
        def remove_readonly(func, path, excinfo):
            os.chmod(path, 0o777)
            func(path)
        
        shutil.rmtree(temp_path, onerror=remove_readonly)
    
    def _cleanup_recursive(self, temp_path):
        """递归删除方法"""
        for root, dirs, files in os.walk(temp_path, topdown=False):
            for name in files:
                file_path = os.path.join(root, name)
                try:
                    os.chmod(file_path, 0o777)
                    os.remove(file_path)
                except Exception:
                    pass
            
            for name in dirs:
                dir_path = os.path.join(root, name)
                try:
                    os.chmod(dir_path, 0o777)
                    os.rmdir(dir_path)
                except Exception:
                    pass
        
        try:
            os.chmod(temp_path, 0o777)
            os.rmdir(temp_path)
        except Exception:
            pass
    
    def _cleanup_command(self, temp_path):
        """使用命令行删除"""
        if sys.platform == 'win32':
            subprocess.run(['cmd', '/c', 'rd', '/s', '/q', temp_path], 
                         capture_output=True, shell=True)
        else:
            subprocess.run(['rm', '-rf', temp_path], 
                         capture_output=True)
    
    def _schedule_cleanup(self, temp_path):
        """创建延迟删除任务"""
        if sys.platform == 'win32':
            # Windows: 创建批处理文件并在启动时删除
            bat_path = os.path.join(os.path.dirname(temp_path), 'cleanup_temp.bat')
            with open(bat_path, 'w', encoding='gbk') as f:
                f.write(f'@echo off\n')
                f.write(f'ping 127.0.0.1 -n 3 > nul\n')
                f.write(f'rd /s /q "{temp_path}"\n')
                f.write(f'del "%~f0"\n')
            
            # 启动批处理文件
            subprocess.Popen([bat_path], shell=True)
        else:
            # Linux/Mac: 使用at命令
            try:
                subprocess.run(['at', 'now', '+', '1', 'minute', 
                              f'rm -rf {temp_path}'], 
                             capture_output=True)
            except Exception:
                pass

if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    dialog = FlasherDialog()
    dialog.exec()
    sys.exit()
