"""
主窗口 - 三栏布局
"""
import os
import sys
import logging
import tempfile
import shutil
from typing import Optional

logger = logging.getLogger(__name__)

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QMenuBar, QMenu, QStatusBar,
    QFileDialog, QMessageBox, QLabel, QTabWidget, QPushButton
)
from PyQt6.QtCore import Qt, QSettings, QTimer
from PyQt6.QtGui import QAction, QKeySequence, QIcon

from config.epconfig import EPConfig
from config.constants import APP_NAME, APP_VERSION, get_resolution_spec
from gui.widgets.config_panel import ConfigPanel
from gui.widgets.video_preview import VideoPreviewWidget
from gui.widgets.transition_preview import TransitionPreviewWidget
from gui.widgets.timeline import TimelineWidget
from gui.widgets.json_preview import JsonPreviewWidget


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._config: Optional[EPConfig] = None
        self._project_path: str = ""
        self._base_dir: str = ""
        self._is_modified: bool = False
        self._temp_dir: Optional[str] = None  # 临时项目目录路径，None 表示非临时项目
        self._initializing: bool = True  # 初始化期间防护标志

        # 为每个视频存储独立的入点/出点
        self._loop_in_out: tuple[int, int] = (0, 0)   # 循环视频的(入点, 出点)
        self._intro_in_out: tuple[int, int] = (0, 0)  # 入场视频的(入点, 出点)
        self._timeline_preview: Optional['VideoPreviewWidget'] = None  # 时间轴当前连接的预览器

        self._setup_ui()
        self._setup_menu()
        self._setup_icon()
        self._connect_signals()
        self._load_settings()

        self._update_title()
        self._check_first_run()

        # 自动创建临时项目，用户可立即开始编辑
        if self._config is None:
            self._init_temp_project()

        # 启动时延迟检查更新（2秒后）
        QTimer.singleShot(2000, self._check_update_on_startup)

        logger.info("主窗口初始化完成")
        self._initializing = False  # 初始化完成

    def _setup_icon(self):
        """设置窗口图标"""
        icon_path = os.path.join(
            os.path.dirname(__file__), '..', 'resources', 'icons', 'favicon.ico'
        )
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            logger.debug(f"已加载窗口图标: {icon_path}")
        else:
            logger.warning(f"窗口图标文件不存在: {icon_path}")

    def _setup_ui(self):
        """设置UI"""
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(1200, 800)

        # 中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 三栏分割器
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.splitter)

        # === 左侧: 配置面板 ===
        self.config_panel = ConfigPanel()
        self.splitter.addWidget(self.config_panel)

        # === 中间: 视频预览标签页 + 时间轴 ===
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(5, 5, 5, 5)
        preview_layout.setSpacing(5)

        # 标签页：入场视频 / 截取帧编辑 / 过渡图片 / 循环视频
        self.preview_tabs = QTabWidget()
        self.video_preview = VideoPreviewWidget()  # 循环视频预览
        self.intro_preview = VideoPreviewWidget()  # 入场视频预览
        self.transition_preview = TransitionPreviewWidget()  # 过渡图片预览

        # 截取帧编辑标签页
        frame_capture_widget = QWidget()
        frame_capture_layout = QVBoxLayout(frame_capture_widget)
        frame_capture_layout.setContentsMargins(0, 0, 0, 0)
        frame_capture_layout.setSpacing(5)
        self.frame_capture_preview = VideoPreviewWidget()
        frame_capture_layout.addWidget(self.frame_capture_preview, stretch=1)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_save_icon = QPushButton("保存为图标")
        self.btn_save_icon.setStyleSheet("padding: 6px 16px;")
        btn_layout.addWidget(self.btn_save_icon)
        frame_capture_layout.addLayout(btn_layout)

        self.preview_tabs.addTab(self.intro_preview, "入场视频")         # Tab 0
        self.preview_tabs.addTab(frame_capture_widget, "截取帧编辑")     # Tab 1
        self.preview_tabs.addTab(self.transition_preview, "过渡图片")    # Tab 2
        self.preview_tabs.addTab(self.video_preview, "循环视频")         # Tab 3
        preview_layout.addWidget(self.preview_tabs, stretch=1)

        self.timeline = TimelineWidget()
        preview_layout.addWidget(self.timeline)

        self.splitter.addWidget(preview_container)

        # === 右侧: JSON预览 ===
        self.json_preview = JsonPreviewWidget()
        self.splitter.addWidget(self.json_preview)

        # 设置分割比例
        self.splitter.setSizes([380, 600, 350])
        self.splitter.setStretchFactor(0, 1)   # 左侧允许少量伸缩
        self.splitter.setStretchFactor(1, 10)  # 中间优先伸缩
        self.splitter.setStretchFactor(2, 1)   # 右侧允许少量伸缩

        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

    def _setup_menu(self):
        """设置菜单"""
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")

        self.action_new = QAction("新建项目(&N)", self)
        self.action_new.setShortcut(QKeySequence.StandardKey.New)
        file_menu.addAction(self.action_new)

        self.action_open = QAction("打开项目(&O)...", self)
        self.action_open.setShortcut(QKeySequence.StandardKey.Open)
        file_menu.addAction(self.action_open)

        self.action_save = QAction("保存(&S)", self)
        self.action_save.setShortcut(QKeySequence.StandardKey.Save)
        file_menu.addAction(self.action_save)

        self.action_save_as = QAction("另存为(&A)...", self)
        self.action_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        file_menu.addAction(self.action_save_as)

        file_menu.addSeparator()

        self.action_exit = QAction("退出(&X)", self)
        self.action_exit.setShortcut(QKeySequence.StandardKey.Quit)
        file_menu.addAction(self.action_exit)

        # 工具菜单
        tools_menu = menubar.addMenu("工具(&T)")

        self.action_flasher = QAction("固件烧录(&R)...", self)
        tools_menu.addAction(self.action_flasher)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")

        self.action_shortcuts = QAction("快捷键帮助(&K)", self)
        self.action_shortcuts.setShortcut(QKeySequence("F1"))
        help_menu.addAction(self.action_shortcuts)

        self.action_check_update = QAction("检查更新(&U)...", self)
        help_menu.addAction(self.action_check_update)

        help_menu.addSeparator()

        self.action_about = QAction("关于(&A)", self)
        help_menu.addAction(self.action_about)

    def _connect_signals(self):
        """连接信号"""
        # 菜单动作
        self.action_new.triggered.connect(self._on_new_project)
        self.action_open.triggered.connect(self._on_open_project)
        self.action_save.triggered.connect(self._on_save_project)
        self.action_save_as.triggered.connect(self._on_save_as)
        self.action_exit.triggered.connect(self.close)
        self.action_flasher.triggered.connect(self._on_flasher)
        self.action_shortcuts.triggered.connect(self._on_shortcuts)
        self.action_check_update.triggered.connect(self._on_check_update)
        self.action_about.triggered.connect(self._on_about)

        # 配置面板
        self.config_panel.config_changed.connect(self._on_config_changed)
        self.config_panel.video_file_selected.connect(self._on_video_file_selected)
        self.config_panel.intro_video_selected.connect(self._on_intro_video_selected)
        self.config_panel.loop_image_selected.connect(self._load_loop_image)
        self.config_panel.loop_mode_changed.connect(self._on_loop_mode_changed)
        self.config_panel.validate_requested.connect(self._on_validate)
        self.config_panel.export_requested.connect(self._on_export)
        self.config_panel.capture_frame_requested.connect(self._on_capture_frame)
        self.config_panel.transition_image_changed.connect(self._on_transition_image_changed)

        # 截取帧编辑 - 保存图标按钮
        self.btn_save_icon.clicked.connect(self._on_save_captured_icon)

        # 过渡图片裁切变化
        self.transition_preview.transition_crop_changed.connect(self._on_transition_crop_changed)

        # 标签页切换
        self.preview_tabs.currentChanged.connect(self._on_preview_tab_changed)

        # 循环视频预览
        self.video_preview.video_loaded.connect(self._on_video_loaded)
        self.video_preview.frame_changed.connect(self._on_frame_changed)
        self.video_preview.playback_state_changed.connect(self._on_playback_changed)
        self.video_preview.rotation_changed.connect(self.timeline.set_rotation)

        # 入场视频预览
        self.intro_preview.video_loaded.connect(self._on_intro_video_loaded)
        self.intro_preview.frame_changed.connect(self._on_intro_frame_changed)
        self.intro_preview.playback_state_changed.connect(self._on_intro_playback_changed)
        self.intro_preview.rotation_changed.connect(self._on_intro_rotation_changed)

        # 时间轴（默认连接到入场视频预览）
        self._connect_timeline_to_preview(self.intro_preview)

        # 时间轴模拟器请求
        self.timeline.simulator_requested.connect(self._on_simulator)

        # 入点/出点设置
        self.timeline.set_in_point_clicked.connect(self._on_set_in_point)
        self.timeline.set_out_point_clicked.connect(self._on_set_out_point)

    def _load_settings(self):
        """加载设置"""
        settings = QSettings("ArknightsPassMaker", "MainWindow")
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
            logger.debug("已恢复窗口几何设置")

    def _check_first_run(self):
        """检查是否首次运行"""
        settings = QSettings("ArknightsPassMaker", "MainWindow")
        if not settings.value("first_run_completed", False, type=bool):
            from gui.dialogs.welcome_dialog import WelcomeDialog
            dialog = WelcomeDialog(self)
            dialog.exec()
            if dialog.should_not_show_again():
                settings.setValue("first_run_completed", True)

    def _init_temp_project(self):
        """创建临时项目，用户可立即开始编辑"""
        temp_dir = tempfile.mkdtemp(prefix="neo_assetmaker_")
        self._temp_dir = temp_dir

        self._config = EPConfig()
        self._base_dir = temp_dir
        self._project_path = ""  # 留空，首次保存时触发"另存为"
        self._is_modified = False

        self.config_panel.set_config(self._config, self._base_dir)
        self.json_preview.set_config(self._config, self._base_dir)
        self.video_preview.set_epconfig(self._config)
        self._update_title()
        self.status_bar.showMessage("已创建临时项目，可以开始编辑")
        logger.info(f"已初始化临时项目: {temp_dir}")

    def _cleanup_temp_dir(self):
        """清理临时项目目录"""
        if self._temp_dir and os.path.exists(self._temp_dir):
            try:
                shutil.rmtree(self._temp_dir)
                logger.info(f"已清理临时目录: {self._temp_dir}")
            except Exception as e:
                logger.warning(f"清理临时目录失败: {e}")
        self._temp_dir = None

    def _migrate_temp_to_permanent(self, dest_dir: str):
        """将临时项目中的工作文件迁移到永久目录"""
        if not self._temp_dir or not os.path.exists(self._temp_dir):
            return

        try:
            for filename in os.listdir(self._temp_dir):
                src = os.path.join(self._temp_dir, filename)
                dst = os.path.join(dest_dir, filename)
                if os.path.isfile(src) and not os.path.exists(dst):
                    shutil.copy2(src, dst)
                    logger.debug(f"已迁移文件: {filename}")

            self._cleanup_temp_dir()
            logger.info(f"已将临时项目迁移到: {dest_dir}")
        except Exception as e:
            logger.warning(f"迁移临时项目失败: {e}")
            # 迁移失败时保留临时目录作为备份

    def _on_shortcuts(self):
        """显示快捷键帮助"""
        from gui.dialogs.shortcuts_dialog import ShortcutsDialog
        dialog = ShortcutsDialog(self)
        dialog.exec()

    def _save_settings(self):
        """保存设置"""
        settings = QSettings("ArknightsPassMaker", "MainWindow")
        settings.setValue("geometry", self.saveGeometry())
        logger.debug("已保存窗口几何设置")

    def _update_title(self):
        """更新窗口标题"""
        title = f"{APP_NAME} v{APP_VERSION}"
        if self._project_path:
            title = f"{os.path.basename(self._project_path)} - {title}"
        elif self._temp_dir:
            title = f"临时项目 - {title}"
        if self._is_modified:
            title = f"* {title}"
        self.setWindowTitle(title)

    def _on_new_project(self):
        """新建项目"""
        if not self._check_save():
            return

        # 选择目录
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择项目目录", ""
        )
        if not dir_path:
            return

        # 清理临时项目
        self._cleanup_temp_dir()

        # 创建新配置
        self._config = EPConfig()
        self._base_dir = dir_path
        self._project_path = os.path.join(dir_path, "epconfig.json")
        self._is_modified = True

        # 清空所有预览组件（防止旧项目内容残留）
        self.video_preview.clear()
        self.intro_preview.clear()
        self.frame_capture_preview.clear()
        self.transition_preview.clear_image("in")
        self.transition_preview.clear_image("loop")
        self._loop_image_path = None
        self.timeline.set_total_frames(0)
        self._loop_in_out = (0, 0)
        self._intro_in_out = (0, 0)

        # 更新UI
        self.config_panel.set_config(self._config, self._base_dir)
        self.json_preview.set_config(self._config, self._base_dir)
        self.video_preview.set_epconfig(self._config)
        self._update_title()
        self.status_bar.showMessage(f"新建项目: {dir_path}")

    def _on_open_project(self):
        """打开项目"""
        if not self._check_save():
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "打开配置文件", "",
            "JSON文件 (*.json);;所有文件 (*.*)"
        )
        if not path:
            return

        # 清理临时项目
        self._cleanup_temp_dir()

        try:
            self._config = EPConfig.load_from_file(path)
            self._project_path = path
            self._base_dir = os.path.dirname(path)
            self._is_modified = False

            # 清空所有预览组件（防止旧项目内容残留）
            self.video_preview.clear()
            self.intro_preview.clear()
            self.frame_capture_preview.clear()
            self.transition_preview.clear_image("in")
            self.transition_preview.clear_image("loop")
            self._loop_image_path = None
            self.timeline.set_total_frames(0)
            self._loop_in_out = (0, 0)
            self._intro_in_out = (0, 0)

            # 更新UI
            self.config_panel.set_config(self._config, self._base_dir)
            self.json_preview.set_config(self._config, self._base_dir)
            self.video_preview.set_epconfig(self._config)

            # 尝试加载循环素材（延迟执行，避免阻塞UI）
            if self._config.loop.file:
                file_path = self._config.loop.file
                # 如果是相对路径，转换为绝对路径
                if not os.path.isabs(file_path):
                    file_path = os.path.join(self._base_dir, file_path)

                if os.path.exists(file_path):
                    from PyQt6.QtCore import QTimer
                    if self._config.loop.is_image:
                        # 图片模式：加载图片到预览器
                        logger.info(f"尝试加载循环图片: {file_path}")
                        QTimer.singleShot(100, lambda fp=file_path: self._load_loop_image(fp))
                    else:
                        # 视频模式
                        logger.info(f"尝试加载循环视频: {file_path}")
                        QTimer.singleShot(100, lambda vp=file_path: self.video_preview.load_video(vp))
                else:
                    logger.warning(f"循环素材文件不存在: {file_path}")

            # 尝试加载入场视频
            if self._config.intro.enabled and self._config.intro.file:
                intro_path = self._config.intro.file
                if not os.path.isabs(intro_path):
                    intro_path = os.path.join(self._base_dir, intro_path)
                if os.path.exists(intro_path):
                    from PyQt6.QtCore import QTimer
                    logger.info(f"尝试加载入场视频: {intro_path}")
                    QTimer.singleShot(200, lambda vp=intro_path: self.intro_preview.load_video(vp))

            self._update_title()
            self.status_bar.showMessage(f"已打开: {path}")

        except Exception as e:
            QMessageBox.critical(self, "错误", f"打开文件失败:\n{e}")

    def _on_save_project(self):
        """保存项目"""
        if not self._config:
            return

        if not self._project_path:
            self._on_save_as()
            return

        try:
            self._config.save_to_file(self._project_path)
            self._is_modified = False
            self._update_title()
            self.status_bar.showMessage(f"已保存: {self._project_path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败:\n{e}")

    def _on_save_as(self):
        """另存为"""
        if not self._config:
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "保存配置文件",
            self._project_path or "epconfig.json",
            "JSON文件 (*.json)"
        )
        if not path:
            return

        try:
            new_base_dir = os.path.dirname(path)

            # 从临时项目迁移到永久目录
            if self._temp_dir and self._base_dir == self._temp_dir:
                self._migrate_temp_to_permanent(new_base_dir)

            self._config.save_to_file(path)
            self._project_path = path
            self._base_dir = new_base_dir
            self._is_modified = False

            # 更新面板的 base_dir
            self.config_panel.set_config(self._config, self._base_dir)
            self.json_preview.set_config(self._config, self._base_dir)

            self._update_title()
            self.status_bar.showMessage(f"已保存: {path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败:\n{e}")

    def _on_validate(self):
        """验证配置"""
        if not self._config:
            QMessageBox.information(self, "提示", "请先创建或打开项目")
            return

        from core.validator import EPConfigValidator

        validator = EPConfigValidator(self._base_dir)
        results = validator.validate_config(self._config)

        if not validator.has_errors():
            QMessageBox.information(self, "验证通过", validator.get_summary())
        else:
            errors = validator.get_errors()
            warnings = validator.get_warnings()

            msg = f"{validator.get_summary()}\n\n"
            if errors:
                msg += "错误:\n"
                for r in errors:
                    msg += f"  - {r}\n"
            if warnings:
                msg += "\n警告:\n"
                for r in warnings:
                    msg += f"  - {r}\n"

            QMessageBox.warning(self, "验证结果", msg)

    def _on_export(self):
        """导出素材"""
        if not self._config:
            QMessageBox.information(self, "提示", "请先创建或打开项目")
            return

        # 验证配置
        from core.validator import EPConfigValidator
        validator = EPConfigValidator(self._base_dir)
        validator.validate_config(self._config)

        if validator.has_errors():
            errors = validator.get_errors()
            msg = "配置验证失败，无法导出:\n\n"
            for r in errors:
                msg += f"  - {r}\n"
            QMessageBox.critical(self, "验证失败", msg)
            return

        # 检查循环素材是否已配置
        has_loop_video = self.video_preview.video_path
        has_loop_image = self._config.loop.is_image and hasattr(self, '_loop_image_path') and self._loop_image_path

        if not has_loop_video and not has_loop_image:
            QMessageBox.warning(
                self, "警告",
                "请先加载循环素材\n\n"
                "在配置面板的'视频配置'选项卡中选择循环视频或图片文件"
            )
            return

        # 选择导出目录
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择导出目录", self._base_dir
        )
        if not dir_path:
            return

        # 收集导出数据
        try:
            export_data = self._collect_export_data()
        except Exception as e:
            logger.error(f"收集导出数据失败: {e}")
            QMessageBox.critical(self, "错误", f"收集导出数据失败:\n{e}")
            return

        # 处理arknights叠加的自定义图片
        try:
            self._process_arknights_custom_images(dir_path)
        except Exception as e:
            logger.error(f"处理自定义图片失败: {e}")
            QMessageBox.warning(self, "警告", f"处理自定义图片失败:\n{e}\n\n将继续导出其他内容。")

        # 处理 ImageOverlay 路径
        try:
            self._process_image_overlay(dir_path)
        except Exception as e:
            logger.error(f"处理 ImageOverlay 失败: {e}")

        # 创建导出服务和进度对话框
        from core.export_service import ExportService
        from gui.dialogs.export_progress_dialog import ExportProgressDialog

        self._export_service = ExportService(self)
        self._export_dialog = ExportProgressDialog(self)

        # 连接信号
        self._export_service.progress_updated.connect(
            self._export_dialog.update_progress
        )
        self._export_service.export_completed.connect(
            lambda msg: self._on_export_completed(True, msg)
        )
        self._export_service.export_failed.connect(
            lambda msg: self._on_export_completed(False, msg)
        )
        self._export_dialog.cancel_requested.connect(
            self._export_service.cancel
        )

        # 启动导出
        self._export_service.export_all(
            output_dir=dir_path,
            epconfig=self._config,
            logo_mat=export_data.get('logo_mat'),
            overlay_mat=export_data.get('overlay_mat'),
            loop_video_params=export_data.get('loop_video_params'),
            intro_video_params=export_data.get('intro_video_params'),
            loop_image_path=export_data.get('loop_image_path')
        )

        # 显示进度对话框
        self._export_dialog.exec()

    def _on_simulator(self):
        """打开模拟器预览"""
        import subprocess

        if not self._config:
            QMessageBox.information(self, "提示", "请先创建或打开项目")
            return

        # 检查是否有循环视频
        if not self._config.loop.file:
            QMessageBox.warning(
                self, "警告",
                "请先配置循环视频文件\n\n"
                "在配置面板的'视频配置'选项卡中选择循环视频文件"
            )
            return

        # 查找 Rust 模拟器可执行文件
        # 检测是否为打包后的环境
        if getattr(sys, 'frozen', False):
            # 打包后：exe 所在目录是安装目录
            app_dir = os.path.dirname(sys.executable)
        else:
            # 开发环境：从 gui 目录向上找到项目根目录
            app_dir = os.path.dirname(os.path.dirname(__file__))

        simulator_path = os.path.join(
            app_dir,
            "simulator", "target", "release", "arknights_pass_simulator.exe"
        )

        if not os.path.exists(simulator_path):
            QMessageBox.critical(
                self, "错误",
                f"模拟器未找到\n\n"
                f"请先编译 Rust 模拟器:\n"
                f"cd simulator && cargo build --release\n\n"
                f"路径: {simulator_path}"
            )
            return

        try:
            # 使用项目目录中的 epconfig.json
            config_path = os.path.join(self._base_dir, "epconfig.json")

            # 确保配置已保存（避免内存中的修改与文件不一致）
            if not os.path.exists(config_path):
                QMessageBox.warning(
                    self, "警告",
                    "请先保存项目配置\n\n"
                    "文件 → 保存项目"
                )
                return

            # 获取 cropbox 参数（使用原始坐标系）
            cropbox = self.video_preview.get_cropbox_for_export()
            rotation = self.video_preview.get_rotation()

            # 启动 Rust 模拟器
            popen_kwargs = {}
            if sys.platform == 'win32':
                popen_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

            subprocess.Popen([
                simulator_path,
                "--config", config_path,
                "--base-dir", self._base_dir,
                "--app-dir", app_dir,
                "--cropbox", f"{cropbox[0]},{cropbox[1]},{cropbox[2]},{cropbox[3]}",
                "--rotation", str(rotation)
            ], **popen_kwargs)

            logger.info(f"模拟器已启动: {simulator_path}")

        except Exception as e:
            logger.error(f"启动模拟器失败: {e}")
            QMessageBox.critical(self, "错误", f"启动模拟器失败:\n{e}")

    def _on_flasher(self):
        """启动固件烧录工具"""
        import subprocess

        if sys.platform != 'win32':
            QMessageBox.warning(self, "不支持", "烧录工具目前仅支持 Windows")
            return

        # 打包后: epass_flasher.exe 在 exe 同级目录
        # 开发时: epass_flasher/main.py
        if getattr(sys, 'frozen', False):
            # 打包环境
            app_dir = os.path.dirname(sys.executable)
            flasher_exe = os.path.join(app_dir, "epass_flasher.exe")

            if not os.path.exists(flasher_exe):
                QMessageBox.critical(
                    self, "错误",
                    f"烧录工具未找到\n\n"
                    f"路径: {flasher_exe}\n\n"
                    f"可能的原因:\n"
                    f"1. 安装包构建时未包含烧录工具\n"
                    f"2. 文件被杀毒软件误删\n\n"
                    f"解决方法:\n"
                    f"1. 从 GitHub Releases 重新下载:\n"
                    f"   https://github.com/rhodesepass/neo-assetmaker/releases\n"
                    f"2. 检查杀毒软件隔离区"
                )
                return

            try:
                subprocess.Popen(
                    [flasher_exe],
                    creationflags=subprocess.CREATE_NEW_CONSOLE
                )
                self.status_bar.showMessage("烧录工具已启动")
                logger.info(f"烧录工具已启动: {flasher_exe}")
            except Exception as e:
                logger.error(f"启动烧录工具失败: {e}")
                QMessageBox.critical(self, "错误", f"启动烧录工具失败:\n{e}")
        else:
            # 开发环境
            app_dir = os.path.dirname(os.path.dirname(__file__))
            flasher_dir = os.path.join(app_dir, "epass_flasher")
            flasher_script = os.path.join(flasher_dir, "main.py")

            if not os.path.exists(flasher_script):
                QMessageBox.critical(
                    self, "错误",
                    f"烧录工具未找到\n\n路径: {flasher_script}"
                )
                return

            try:
                subprocess.Popen(
                    [sys.executable, flasher_script],
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                    cwd=flasher_dir
                )
                self.status_bar.showMessage("烧录工具已启动")
                logger.info(f"烧录工具已启动: {flasher_script}")
            except Exception as e:
                logger.error(f"启动烧录工具失败: {e}")
                QMessageBox.critical(self, "错误", f"启动烧录工具失败:\n{e}")

    def _on_about(self):
        """关于"""
        QMessageBox.about(
            self, f"关于 {APP_NAME}",
            f"<h3>{APP_NAME}</h3>"
            f"<p>版本: {APP_VERSION}</p>"
            f"<p>明日方舟通行证素材制作器</p>"
            f"<p>作者: Rafael_ban & 初微弦音</p>"
        )

    def _on_check_update(self):
        """手动检查更新"""
        from gui.dialogs.update_dialog import UpdateDialog
        dialog = UpdateDialog(self, auto_check=True)
        dialog.exec()

    def _check_update_on_startup(self):
        """启动时后台检查更新"""
        from datetime import datetime, timedelta
        from config.constants import UPDATE_CHECK_INTERVAL_HOURS

        settings = QSettings("ArknightsPassMaker", "MainWindow")

        # 检查是否启用自动更新（默认启用）
        auto_check_enabled = settings.value("auto_check_updates", True, type=bool)
        if not auto_check_enabled:
            return

        # 检查上次检查时间（避免频繁检查）
        last_check = settings.value("last_update_check", "")
        if last_check:
            try:
                last_check_time = datetime.fromisoformat(last_check)
                if datetime.now() - last_check_time < timedelta(hours=UPDATE_CHECK_INTERVAL_HOURS):
                    logger.debug("跳过更新检查（24小时内已检查）")
                    return
            except ValueError:
                pass

        # 创建更新服务进行后台检查
        from core.update_service import UpdateService

        self._startup_update_service = UpdateService(APP_VERSION, self)
        self._startup_update_service.check_completed.connect(self._on_startup_update_check_completed)
        self._startup_update_service.check_failed.connect(self._on_startup_update_check_failed)
        self._startup_update_service.check_for_updates()

        # 记录检查时间
        settings.setValue("last_update_check", datetime.now().isoformat())

    def _on_startup_update_check_completed(self, release_info):
        """启动时更新检查完成"""
        if release_info:
            # 发现新版本，弹出提示
            result = QMessageBox.information(
                self, "发现新版本",
                f"发现新版本 v{release_info.version}\n\n"
                f"当前版本: v{APP_VERSION}\n\n"
                f"是否立即查看更新详情？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if result == QMessageBox.StandardButton.Yes:
                self._on_check_update()

        # 清理
        if hasattr(self, '_startup_update_service'):
            self._startup_update_service.deleteLater()
            del self._startup_update_service

    def _on_startup_update_check_failed(self, error_msg: str):
        """启动时更新检查失败（静默失败）"""
        logger.debug(f"启动时更新检查失败: {error_msg}")
        if hasattr(self, '_startup_update_service'):
            self._startup_update_service.deleteLater()
            del self._startup_update_service

    def _on_config_changed(self):
        """配置变更"""
        self._is_modified = True
        self._update_title()

        # 更新JSON预览
        if self._config:
            self.json_preview.set_config(self._config, self._base_dir)
            # 更新视频预览的叠加UI配置
            self.video_preview.set_epconfig(self._config)

    def _on_video_file_selected(self, path: str):
        """视频文件被选择"""
        logger.info(f"视频文件被选择: {path}")
        if path and os.path.exists(path):
            self.video_preview.load_video(path)
            # 切换到循环视频标签页
            self.preview_tabs.setCurrentIndex(3)
        else:
            logger.warning(f"视频文件不存在: {path}")

    def _on_intro_video_selected(self, path: str):
        """入场视频文件被选择"""
        logger.info(f"入场视频文件被选择: {path}")
        if path and os.path.exists(path):
            if self.intro_preview.load_video(path):
                # 切换到入场视频标签页
                self.preview_tabs.setCurrentIndex(0)
        else:
            logger.warning(f"入场视频文件不存在: {path}")

    def _connect_timeline_to_preview(self, preview: VideoPreviewWidget):
        """将时间轴连接到指定预览器"""
        # 断开旧连接（忽略错误，因为可能没有连接）
        try:
            self.timeline.play_pause_clicked.disconnect()
        except TypeError:
            pass
        try:
            self.timeline.seek_requested.disconnect()
        except TypeError:
            pass
        try:
            self.timeline.prev_frame_clicked.disconnect()
        except TypeError:
            pass
        try:
            self.timeline.next_frame_clicked.disconnect()
        except TypeError:
            pass
        try:
            self.timeline.goto_start_clicked.disconnect()
        except TypeError:
            pass
        try:
            self.timeline.goto_end_clicked.disconnect()
        except TypeError:
            pass
        try:
            self.timeline.rotation_clicked.disconnect()
        except TypeError:
            pass

        # 连接新预览器
        self.timeline.play_pause_clicked.connect(preview.toggle_play)
        self.timeline.seek_requested.connect(preview.seek_to_frame)
        self.timeline.prev_frame_clicked.connect(preview.prev_frame)
        self.timeline.next_frame_clicked.connect(preview.next_frame)
        self.timeline.goto_start_clicked.connect(lambda: preview.seek_to_frame(0))
        self.timeline.goto_end_clicked.connect(
            lambda: preview.seek_to_frame(preview.total_frames - 1)
        )
        self.timeline.rotation_clicked.connect(preview.rotate_clockwise)

        # 记录当前连接的预览器
        self._timeline_preview = preview

        # 更新时间轴显示
        if preview.total_frames > 0:
            self.timeline.set_total_frames(preview.total_frames)
            self.timeline.set_fps(preview.video_fps)
            self.timeline.set_current_frame(preview.current_frame_index)
            self.timeline.set_rotation(preview.get_rotation())
            self.timeline.set_playing(preview.is_playing)

    def _on_preview_tab_changed(self, index: int):
        """预览标签页切换"""
        # 保存当前 in/out 到正确的位置（基于当前连接的预览器）
        current_in = self.timeline.get_in_point()
        current_out = self.timeline.get_out_point()
        if self._timeline_preview is self.intro_preview:
            self._intro_in_out = (current_in, current_out)
        elif self._timeline_preview is self.video_preview:
            self._loop_in_out = (current_in, current_out)

        if index == 0:
            # 入场视频
            self._connect_timeline_to_preview(self.intro_preview)
            self.timeline.set_in_point(self._intro_in_out[0])
            self.timeline.set_out_point(self._intro_in_out[1])
            self.timeline.show()
            logger.debug("切换到入场视频预览")
        elif index == 1:
            # 截取帧编辑 - 保持时间轴可见以便导航视频选帧
            self.timeline.show()
            logger.debug("切换到截取帧编辑")
        elif index == 2:
            # 过渡图片（静态，不需要时间轴）
            self.timeline.hide()
            logger.debug("切换到过渡图片预览")
        elif index == 3:
            # 循环视频
            self._connect_timeline_to_preview(self.video_preview)
            self.timeline.set_in_point(self._loop_in_out[0])
            self.timeline.set_out_point(self._loop_in_out[1])
            self.timeline.show()
            logger.debug("切换到循环视频预览")

    def _on_intro_video_loaded(self, total_frames: int, fps: float):
        """入场视频加载完成"""
        # 只在入场视频标签页激活时更新时间轴
        if self.preview_tabs.currentIndex() == 0:
            self.timeline.set_total_frames(total_frames)
            self.timeline.set_fps(fps)
            self.timeline.set_in_point(0)
            self.timeline.set_out_point(total_frames - 1)
        # 更新存储
        self._intro_in_out = (0, total_frames - 1)
        self.status_bar.showMessage(f"入场视频已加载: {total_frames} 帧, {fps:.1f} FPS")

    def _on_intro_frame_changed(self, frame: int):
        """入场视频帧变更"""
        if self.preview_tabs.currentIndex() in (0, 1):
            self.timeline.set_current_frame(frame)

    def _on_intro_playback_changed(self, is_playing: bool):
        """入场视频播放状态变更"""
        if self.preview_tabs.currentIndex() in (0, 1):
            self.timeline.set_playing(is_playing)

    def _on_intro_rotation_changed(self, rotation: int):
        """入场视频旋转变更"""
        if self.preview_tabs.currentIndex() == 0:
            self.timeline.set_rotation(rotation)

    def _on_set_in_point(self):
        """设置入点为当前帧"""
        index = self.preview_tabs.currentIndex()
        if index == 0:
            current_frame = self.intro_preview.current_frame_index
        elif index == 3:
            current_frame = self.video_preview.current_frame_index
        else:
            return  # 截取帧/过渡图片标签页无入点操作

        self.timeline.set_in_point(current_frame)
        logger.debug(f"设置入点: {current_frame}")

    def _on_set_out_point(self):
        """设置出点为当前帧"""
        index = self.preview_tabs.currentIndex()
        if index == 0:
            current_frame = self.intro_preview.current_frame_index
        elif index == 3:
            current_frame = self.video_preview.current_frame_index
        else:
            return  # 截取帧/过渡图片标签页无出点操作

        self.timeline.set_out_point(current_frame)
        logger.debug(f"设置出点: {current_frame}")

    def _load_loop_image(self, path: str):
        """加载循环图片到预览器"""
        import cv2
        from PyQt6.QtGui import QImage, QPixmap

        self._loop_image_path = path
        logger.info(f"加载循环图片: {path}")

        # 加载图片
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if img is None:
            logger.error(f"无法加载图片: {path}")
            self.video_preview.video_label.setText(f"无法加载图片: {path}")
            return

        # 显示图片尺寸信息
        h, w = img.shape[:2]
        self.status_bar.showMessage(f"图片已加载: {w}x{h}")

        # 转换为RGB显示
        if len(img.shape) == 2:
            # 灰度图转换为RGB
            display_img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
        elif img.shape[2] == 4:
            # BGRA转换为RGB
            display_img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGB)
        else:
            # BGR转换为RGB
            display_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # 创建QPixmap并显示
        h, w, ch = display_img.shape
        q_image = QImage(display_img.data, w, h, ch * w, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(q_image)

        # 缩放到预览区域大小
        label_size = self.video_preview.video_label.size()
        scaled_pixmap = pixmap.scaled(
            label_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.video_preview.video_label.setPixmap(scaled_pixmap)

        # 更新信息标签
        self.video_preview.info_label.setText(f"图片模式: {w}x{h}")

    def _on_loop_mode_changed(self, is_image: bool):
        """循环模式切换"""
        # 防止在初始化期间触发
        if self._initializing:
            return

        # 清空预览
        self.video_preview.clear()
        self._loop_image_path = None

        # 清空时间轴
        self.timeline.set_total_frames(0)
        self._loop_in_out = (0, 0)

        logger.info(f"循环模式切换为: {'图片' if is_image else '视频'}")

    def _on_transition_image_changed(self, trans_type: str, abs_path: str):
        """过渡图片变更"""
        self.transition_preview.load_image(trans_type, abs_path)
        # 切换到过渡图片标签页
        self.preview_tabs.setCurrentIndex(2)

    def _on_transition_crop_changed(self, trans_type: str):
        """过渡图片 cropbox 变化 → 裁切原始图片并保存"""
        if not self._base_dir:
            return

        import cv2
        import glob

        # 查找原始图片
        pattern = os.path.join(self._base_dir, f"trans_{trans_type}_src.*")
        matches = glob.glob(pattern)
        if not matches:
            return

        src_path = matches[0]
        original = cv2.imread(src_path, cv2.IMREAD_UNCHANGED)
        if original is None:
            return

        # 获取 cropbox 坐标
        x, y, w, h = self.transition_preview.get_cropbox(trans_type)

        # 边界检查
        img_h, img_w = original.shape[:2]
        x = max(0, min(x, img_w - 1))
        y = max(0, min(y, img_h - 1))
        w = min(w, img_w - x)
        h = min(h, img_h - y)

        if w <= 0 or h <= 0:
            return

        # 裁切
        cropped = original[y:y+h, x:x+w]

        # 缩放到目标分辨率
        target_w, target_h = self._get_target_resolution()
        resized = cv2.resize(cropped, (target_w, target_h), interpolation=cv2.INTER_AREA)

        # 保存为模拟器读取的文件
        out_path = os.path.join(self._base_dir, f"trans_{trans_type}_image.png")
        success, encoded = cv2.imencode('.png', resized)
        if success:
            with open(out_path, 'wb') as f:
                f.write(encoded.tobytes())

    def _get_target_resolution(self):
        """获取当前选择的目标分辨率"""
        if self._config:
            spec = get_resolution_spec(self._config.screen.value)
            if spec:
                return spec['width'], spec['height']
        return 360, 640

    def _on_video_loaded(self, total_frames: int, fps: float):
        """视频加载完成"""
        self.timeline.set_total_frames(total_frames)
        self.timeline.set_fps(fps)
        self.timeline.set_in_point(0)
        self.timeline.set_out_point(total_frames - 1)
        # 更新存储
        self._loop_in_out = (0, total_frames - 1)
        self.status_bar.showMessage(f"视频已加载: {total_frames} 帧, {fps:.1f} FPS")

    def _on_frame_changed(self, frame: int):
        """帧变更"""
        self.timeline.set_current_frame(frame)

    def _on_playback_changed(self, is_playing: bool):
        """播放状态变更"""
        self.timeline.set_playing(is_playing)

    def _on_capture_frame(self):
        """截取当前视频帧 → 加载到截取帧编辑标签页"""
        if not self._base_dir:
            QMessageBox.warning(self, "警告", "请先创建或打开项目")
            return

        # 尝试从当前活跃的视频预览获取帧
        current_tab = self.preview_tabs.currentIndex()
        if current_tab == 3:
            source_preview = self.video_preview
        else:
            source_preview = self.intro_preview

        frame = source_preview.current_frame
        if frame is None:
            # 尝试另一个预览
            other = self.video_preview if source_preview is self.intro_preview else self.intro_preview
            frame = other.current_frame
            if other.current_frame is not None:
                source_preview = other
        if frame is None:
            QMessageBox.warning(self, "警告", "请先加载视频")
            return

        import cv2

        # 应用旋转变换（不裁切，交给用户在截取帧编辑标签页中操作）
        frame = frame.copy()
        rotation = source_preview.get_rotation()
        if rotation == 90:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif rotation == 180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        elif rotation == 270:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

        # 加载到截取帧编辑预览
        self.frame_capture_preview.load_static_image_from_array(frame)
        # 切换到截取帧编辑标签页
        self.preview_tabs.setCurrentIndex(1)
        self.status_bar.showMessage("已截取视频帧，请调整裁切框后点击\"保存为图标\"")

    def _on_save_captured_icon(self):
        """从截取帧编辑的 cropbox 保存图标"""
        if not self._base_dir:
            QMessageBox.warning(self, "警告", "请先创建或打开项目")
            return

        frame = self.frame_capture_preview.current_frame
        if frame is None:
            QMessageBox.warning(self, "警告", "请先截取视频帧")
            return

        import cv2

        x, y, w, h = self.frame_capture_preview.get_cropbox()

        # 边界检查
        frame_h, frame_w = frame.shape[:2]
        x = max(0, min(x, frame_w - 1))
        y = max(0, min(y, frame_h - 1))
        w = min(w, frame_w - x)
        h = min(h, frame_h - y)

        if w <= 0 or h <= 0:
            QMessageBox.warning(self, "错误", "裁切区域无效")
            return

        cropped = frame[y:y+h, x:x+w]

        icon_path = os.path.join(self._base_dir, "icon.png")
        success, encoded = cv2.imencode('.png', cropped)
        if success:
            with open(icon_path, 'wb') as f:
                f.write(encoded.tobytes())
            self.config_panel.edit_icon.setText("icon.png")
            self.status_bar.showMessage("已保存图标")
        else:
            QMessageBox.warning(self, "错误", "保存图标失败")

    def _collect_export_data(self) -> dict:
        """收集导出所需的数据"""
        from core.export_service import VideoExportParams
        from core.image_processor import ImageProcessor

        data = {}

        # 收集 Logo/Icon 图片
        icon_path = self._config.icon
        if icon_path:
            if not os.path.isabs(icon_path):
                icon_path = os.path.join(self._base_dir, icon_path)
            if os.path.exists(icon_path):
                logo_img = ImageProcessor.load_image(icon_path)
                if logo_img is not None:
                    data['logo_mat'] = ImageProcessor.process_for_logo(logo_img)

        # 收集循环素材参数
        if self._config.loop.is_image:
            # 图片模式
            if hasattr(self, '_loop_image_path') and self._loop_image_path:
                data['loop_image_path'] = self._loop_image_path
                data['is_loop_image'] = True
        elif self.video_preview.video_path:
            # 视频模式
            # 使用 get_cropbox_for_export() 获取原始坐标系的 cropbox
            cropbox = self.video_preview.get_cropbox_for_export()
            rotation = self.video_preview.get_rotation()
            in_point = self.timeline.get_in_point()
            out_point = self.timeline.get_out_point()

            data['loop_video_params'] = VideoExportParams(
                video_path=self.video_preview.video_path,
                cropbox=cropbox,
                start_frame=in_point,
                end_frame=out_point,
                fps=self.video_preview.video_fps,
                resolution=self._config.screen.value,
                rotation=rotation
            )

        # 收集入场视频参数 (如果启用)
        if self._config.intro.enabled and self._config.intro.file:
            # 优先使用 intro_preview（如果已加载）
            if self.intro_preview.video_path:
                # 使用 get_cropbox_for_export() 获取原始坐标系的 cropbox
                cropbox = self.intro_preview.get_cropbox_for_export()
                rotation = self.intro_preview.get_rotation()

                data['intro_video_params'] = VideoExportParams(
                    video_path=self.intro_preview.video_path,
                    cropbox=cropbox,
                    start_frame=0,
                    end_frame=self.intro_preview.total_frames,
                    fps=self.intro_preview.video_fps,
                    resolution=self._config.screen.value,
                    rotation=rotation
                )
            else:
                # 回退：直接读取文件信息
                intro_path = self._config.intro.file
                if not os.path.isabs(intro_path):
                    intro_path = os.path.join(self._base_dir, intro_path)

                if os.path.exists(intro_path):
                    import cv2
                    cap = cv2.VideoCapture(intro_path)
                    if cap.isOpened():
                        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
                        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                        cap.release()

                        data['intro_video_params'] = VideoExportParams(
                            video_path=intro_path,
                            cropbox=(0, 0, width, height),
                            start_frame=0,
                            end_frame=total_frames,
                            fps=fps,
                            resolution=self._config.screen.value,
                            rotation=0
                        )

        # 收集 ImageOverlay 图片
        from config.epconfig import OverlayType
        if self._config.overlay.type == OverlayType.IMAGE:
            if self._config.overlay.image_options and self._config.overlay.image_options.image:
                img_path = self._config.overlay.image_options.image
                if not os.path.isabs(img_path):
                    img_path = os.path.join(self._base_dir, img_path)
                if os.path.exists(img_path):
                    overlay_img = ImageProcessor.load_image(img_path)
                    if overlay_img is not None:
                        # 获取目标分辨率
                        spec = get_resolution_spec(self._config.screen.value)
                        target_size = (spec['width'], spec['height'])

                        # 缩放到目标分辨率
                        import cv2
                        overlay_img = cv2.resize(overlay_img, target_size)
                        data['overlay_mat'] = overlay_img

        return data

    def _process_arknights_custom_images(self, output_dir: str):
        """
        处理arknights叠加的自定义图片

        将自定义的logo和operator_class_icon缩放后复制到导出目录

        Args:
            output_dir: 导出目录
        """
        from config.epconfig import OverlayType
        from config.constants import ARK_CLASS_ICON_SIZE, ARK_LOGO_SIZE
        from core.image_processor import ImageProcessor
        import cv2

        if not self._config:
            return

        # 检查是否为arknights类型叠加
        if self._config.overlay.type != OverlayType.ARKNIGHTS:
            return

        ark_opts = self._config.overlay.arknights_options
        if not ark_opts:
            return

        # 处理职业图标 (50x50)
        if ark_opts.operator_class_icon:
            src_path = ark_opts.operator_class_icon
            if not os.path.isabs(src_path):
                src_path = os.path.join(self._base_dir, src_path)

            if os.path.exists(src_path):
                img = ImageProcessor.load_image(src_path)
                if img is not None:
                    # 缩放到目标尺寸
                    img = cv2.resize(img, ARK_CLASS_ICON_SIZE)
                    # 保存到导出目录
                    dst_filename = "class_icon.png"
                    dst_path = os.path.join(output_dir, dst_filename)
                    success, encoded = cv2.imencode('.png', img)
                    if success:
                        with open(dst_path, 'wb') as f:
                            f.write(encoded.tobytes())
                        logger.info(f"已导出职业图标: {dst_path}")

        # 处理Logo (75x35)
        if ark_opts.logo:
            src_path = ark_opts.logo
            if not os.path.isabs(src_path):
                src_path = os.path.join(self._base_dir, src_path)

            if os.path.exists(src_path):
                img = ImageProcessor.load_image(src_path)
                if img is not None:
                    # 缩放到目标尺寸
                    img = cv2.resize(img, ARK_LOGO_SIZE)
                    # 保存到导出目录
                    dst_filename = "ark_logo.png"
                    dst_path = os.path.join(output_dir, dst_filename)
                    success, encoded = cv2.imencode('.png', img)
                    if success:
                        with open(dst_path, 'wb') as f:
                            f.write(encoded.tobytes())
                        logger.info(f"已导出Logo: {dst_path}")

    def _process_image_overlay(self, output_dir: str):
        """处理 ImageOverlay 的图片导出和路径标准化"""
        from config.epconfig import OverlayType
        from core.image_processor import ImageProcessor
        import cv2

        if not self._config:
            return

        if self._config.overlay.type != OverlayType.IMAGE:
            return

        if self._config.overlay.image_options and self._config.overlay.image_options.image:
            src_path = self._config.overlay.image_options.image
            if not os.path.isabs(src_path):
                src_path = os.path.join(self._base_dir, src_path)

            if os.path.exists(src_path):
                img = ImageProcessor.load_image(src_path)
                if img is not None:
                    dst_filename = "overlay.png"
                    dst_path = os.path.join(output_dir, dst_filename)
                    success, encoded = cv2.imencode('.png', img)
                    if success:
                        with open(dst_path, 'wb') as f:
                            f.write(encoded.tobytes())
                        logger.info(f"已导出叠加图片: {dst_path}")

    def _on_export_completed(self, success: bool, message: str):
        """导出完成回调"""
        if hasattr(self, '_export_dialog') and self._export_dialog:
            self._export_dialog.set_completed(success, message)

        if success:
            self.status_bar.showMessage(message)
            logger.info(f"导出成功: {message}")
        else:
            self.status_bar.showMessage("导出失败")
            logger.error(f"导出失败: {message}")

    def _check_save(self) -> bool:
        """检查是否需要保存"""
        if not self._is_modified:
            return True

        result = QMessageBox.question(
            self, "保存更改",
            "当前项目有未保存的更改，是否保存?",
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel
        )

        if result == QMessageBox.StandardButton.Save:
            self._on_save_project()
            return not self._is_modified
        elif result == QMessageBox.StandardButton.Discard:
            return True
        else:
            return False

    def closeEvent(self, event):
        """关闭事件"""
        if self._check_save():
            self._save_settings()
            self._cleanup_temp_dir()
            event.accept()
        else:
            event.ignore()
