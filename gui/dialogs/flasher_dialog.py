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
        title_label.setStyleSheet("color: #ff6b8b;")
        layout.addWidget(title_label)
        
        # 版本信息
        version_label = QLabel("Proj0cpy 专用版 v2\n罗德岛工程部 (c)1097")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_label.setStyleSheet("color: #666666;")
        layout.addWidget(version_label)
        
        # 设备信息组
        device_group = QGroupBox("设备信息")
        device_layout = QFormLayout()
        
        # 设备版本
        self.rev_combo = QComboBox()
        self.rev_combo.addItems(["0.2系列", "0.3/0.4系列(0.3/0.3.1/0.4/....)", "0.5系列(0.5/0.5.1)", "0.6系列"])
        device_layout.addRow("设备版本:", self.rev_combo)
        
        # 屏幕类型
        self.screen_combo = QComboBox()
        self.screen_combo.addItems(["京东方/BOE（没法旋转，冠显等商家）", "瀚彩/HSD（金逸晨、鑫睿等商家）", "老五电子买的3块钱的屏幕"])
        device_layout.addRow("屏幕类型:", self.screen_combo)
        
        device_group.setLayout(device_layout)
        layout.addWidget(device_group)
        
        # 烧录版本组
        version_group = QGroupBox("烧录版本")
        version_layout = QVBoxLayout()
        
        # 版本选择下拉框
        version_layout.addWidget(QLabel("可用版本:"))
        self.version_combo = QComboBox()
        self.version_combo.addItem("请先获取版本信息...")
        version_layout.addWidget(self.version_combo)
        
        # 下载源选择
        version_layout.addWidget(QLabel("下载源:"))
        self.mirror_combo = QComboBox()
        self.mirror_combo.addItem("请先获取版本信息...")
        version_layout.addWidget(self.mirror_combo)
        
        version_group.setLayout(version_layout)
        layout.addWidget(version_group)
        
        # 状态显示
        status_group = QGroupBox("烧录状态")
        status_layout = QVBoxLayout()
        
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setStyleSheet("background-color: #f8f9fa;")
        status_layout.addWidget(self.status_text)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        status_layout.addWidget(self.progress_bar)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        # 按钮
        button_layout = QHBoxLayout()
        
        self.install_driver_button = QPushButton("安装驱动")
        self.install_driver_button.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px 20px;")
        self.install_driver_button.clicked.connect(self._on_install_driver)
        
        self.get_version_button = QPushButton("获取版本信息")
        self.get_version_button.setStyleSheet("background-color: #666666; color: white; padding: 10px 20px;")
        self.get_version_button.clicked.connect(self._on_get_version)
        
        self.start_button = QPushButton("开始烧录")
        self.start_button.setStyleSheet("background-color: #ff6b8b; color: white; padding: 10px 20px;")
        self.start_button.clicked.connect(self._on_start)
        
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self._on_cancel)
        
        button_layout.addStretch()
        button_layout.addWidget(self.install_driver_button)
        button_layout.addWidget(self.get_version_button)
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.cancel_button)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        
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
                "如果您需要使用固件烧录功能，请确保项目完整并包含epass_flasher子模块。\n"
                "您可以手动克隆该子模块：\n"
                "git clone https://github.com/rhodesepass/epass_flasher.git epass_flasher"
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
        else:
            self.reject()
    
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
                    "如果您需要使用固件烧录功能，请确保项目完整并包含epass_flasher子模块。\n"
                    "您可以手动克隆该子模块：\n"
                    "git clone https://github.com/rhodesepass/epass_flasher.git epass_flasher"
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
                    "如果您需要使用固件烧录功能，请确保项目完整并包含epass_flasher子模块。\n"
                    "您可以手动克隆该子模块：\n"
                    "git clone https://github.com/rhodesepass/epass_flasher.git epass_flasher"
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

if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    dialog = FlasherDialog()
    dialog.exec()
    sys.exit()
