"""主窗口 - 三栏布局"""
from core.error_handler import ErrorHandler, show_error
from core.crash_recovery_service import CrashRecoveryService
from core.auto_save_service import AutoSaveService, AutoSaveConfig
from gui.widgets.json_preview import JsonPreviewWidget
from gui.widgets.timeline import TimelineWidget
from gui.widgets.transition_preview import TransitionPreviewWidget
from gui.widgets.video_preview import VideoPreviewWidget
from gui.widgets.config_panel import ConfigPanel
from config.constants import APP_NAME, APP_VERSION, get_resolution_spec
from config.epconfig import EPConfig
from qfluentwidgets import (
    PushButton, PrimaryPushButton, ToolButton,
    TabWidget, SegmentedWidget,
    SubtitleLabel,
    ComboBox, SpinBox,
    DoubleSpinBox, CheckBox, LineEdit,
    ScrollArea, FluentIcon,
    setCustomStyleSheet, isDarkTheme
)
from PyQt6.QtGui import QAction, QKeySequence, QIcon
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QMenuBar, QMenu, QStatusBar,
    QFileDialog, QMessageBox, QLabel, QScrollArea,
    QGroupBox, QCheckBox, QComboBox, QDoubleSpinBox,
    QSpinBox, QLineEdit, QTabWidget
)
from PyQt6.QtCore import Qt, QSettings, QTimer, QUrl, QCoreApplication
import os
import sys
import logging
import tempfile
import shutil
from typing import Optional

logger = logging.getLogger(__name__)


# Fluent Widgets导入

# 确保在创建应用程序实例之前设置Qt.AA_ShareOpenGLContexts
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

# 导入QtWebEngineWidgets


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
        # 时间轴当前连接的预览器
        self._timeline_preview: Optional['VideoPreviewWidget'] = None

        # 初始化自动保存和崩溃恢复服务
        self._auto_save_service = AutoSaveService()
        self._crash_recovery_service = CrashRecoveryService()
        self._crash_recovery_service.initialize(
            os.path.join(os.path.dirname(__file__), "..", ".recovery"))

        # 初始化错误处理器
        self._error_handler = ErrorHandler()
        self._error_handler.error_occurred.connect(self._on_error_occurred)

        # 撤销/重做历史
        self._undo_stack = []
        self._redo_stack = []
        self._max_history = 50  # 最大历史记录数

        # 最近打开的文件列表
        self._recent_files = []
        self._max_recent_files = 10  # 最多保留10个最近文件

        self._setup_ui()
        self._setup_menu()
        self._setup_icon()
        self._connect_signals()
        self._load_settings()
        self._load_user_settings()

        self._update_title()
        self._check_first_run()

        # 根据用户设置决定是否自动创建临时项目
        auto_create = True
        try:
            import json
            config_dir = os.path.join(
                os.path.dirname(__file__), "..", "config")
            config_file = os.path.join(config_dir, "user_settings.json")
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    user_settings = json.load(f)
                    auto_create = user_settings.get(
                        'auto_create_temp_project', True)
        except Exception:
            pass

        if self._config is None and auto_create:
            self._init_temp_project()

        # 启动时延迟检查更新（2秒后）
        QTimer.singleShot(2000, self._check_update_on_startup)

        # 启动时检查崩溃恢复（3秒后）
        QTimer.singleShot(3000, self._check_crash_recovery)

        logger.info("主窗口初始化完成")
        self._initializing = False  # 初始化完成

    def _setup_icon(self):
        """设置窗口图标"""
        icon_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'resources',
            'icons',
            'favicon.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            logger.debug(f"已加载窗口图标: {icon_path}")
        else:
            logger.warning(f"窗口图标文件不存在: {icon_path}")

    def _setup_ui(self):
        """设置UI"""
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(1200, 900)  # 增大最小高度，确保内容完全显示
        # 隐藏标准菜单栏
        self.menuBar().setVisible(False)
        # 设置窗口标志，去掉默认标题栏，使用自定义标题栏
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowMinMaxButtonsHint | Qt.WindowType.WindowCloseButtonHint)
        # 初始化窗口拖动变量
        self._is_dragging = False
        self._drag_start_pos = None
        # 初始化窗口大小调整变量
        self._is_resizing = False
        self._resize_direction = None
        self._resize_start_pos = None
        self._resize_start_geometry = None
        # 窗口边缘的拖拽区域宽度
        self._resize_margin = 8

        # 中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # === 顶部标题栏 ===
        self.header_bar = QWidget()
        self.header_bar.setObjectName("header_bar")
        self.header_bar.setStyleSheet("""
            QWidget { background-color: rgba(40, 40, 40, 0.7); color: white; border-bottom-right-radius: 16px; }
            QLabel { font-weight: bold; font-size: 16px; }
        """)
        header_layout = QHBoxLayout(self.header_bar)
        header_layout.setContentsMargins(20, 8, 20, 8)
        header_layout.setSpacing(24)

        # Logo
        logo_label = QLabel("AK")
        logo_label.setStyleSheet("""
            QLabel {
                background-color: white;
                color: #ff6b8b;
                border-radius: 16px;
                padding: 8px 12px;
                font-size: 14px;
                font-weight: bold;
            }
        """)
        header_layout.addWidget(logo_label)

        # 标题
        title_label = QLabel(APP_NAME)
        title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        # 添加窗口控制按钮
        control_layout = QHBoxLayout()
        control_layout.setSpacing(5)

        # 最小化按钮
        self.btn_minimize = PushButton("−")
        self.btn_minimize.setFixedSize(36, 36)
        self.btn_minimize.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: white;
                border: none;
                border-radius: 18px;
                font-size: 20px;
                font-weight: bold;
                padding: 0;
                margin: 0;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.2);
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.3);
            }
        """)
        self.btn_minimize.clicked.connect(self.showMinimized)
        control_layout.addWidget(self.btn_minimize)

        # 最大化按钮
        self.btn_maximize = PushButton("□")
        self.btn_maximize.setFixedSize(36, 36)
        self.btn_maximize.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: white;
                border: none;
                border-radius: 18px;
                font-size: 16px;
                font-weight: bold;
                padding: 0;
                margin: 0;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.2);
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.3);
            }
        """)
        self.btn_maximize.clicked.connect(self._on_maximize)
        control_layout.addWidget(self.btn_maximize)

        # 关闭按钮
        self.btn_close = PushButton("×")
        self.btn_close.setFixedSize(36, 36)
        self.btn_close.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: white;
                border: none;
                border-radius: 18px;
                font-size: 20px;
                font-weight: bold;
                padding: 0;
                margin: 0;
            }
            QPushButton:hover {
                background-color: rgba(255, 0, 0, 0.3);
                color: white;
            }
            QPushButton:pressed {
                background-color: rgba(255, 0, 0, 0.4);
            }
        """)
        self.btn_close.clicked.connect(self.close)
        control_layout.addWidget(self.btn_close)

        header_layout.addLayout(control_layout)

        # 为header_bar添加鼠标事件处理
        self.header_bar.setMouseTracking(True)
        self.header_bar.mousePressEvent = self._on_header_mouse_press
        self.header_bar.mouseMoveEvent = self._on_header_mouse_move
        self.header_bar.mouseReleaseEvent = self._on_header_mouse_release

        main_layout.addWidget(self.header_bar)

        # === 内容区域布局 ===
        content_container = QWidget()
        content_layout = QHBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # === 左侧: 侧边栏导航 ===
        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
        sidebar_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 侧边栏按钮 - 使用Fluent ToolButton和图标
        self.btn_firmware = ToolButton(FluentIcon.ROBOT, self.sidebar)
        self.btn_firmware.setCheckable(True)
        self.btn_firmware.setToolTip("固件烧录")
        self.btn_firmware.setFixedSize(50, 50)

        self.btn_material = ToolButton(FluentIcon.PALETTE, self.sidebar)
        self.btn_material.setCheckable(True)
        self.btn_material.setChecked(True)
        self.btn_material.setToolTip("素材制作")
        self.btn_material.setFixedSize(50, 50)

        self.btn_market = ToolButton(FluentIcon.SHOPPING_CART, self.sidebar)
        self.btn_market.setCheckable(True)
        self.btn_market.setToolTip("素材商城")
        self.btn_market.setFixedSize(50, 50)

        self.btn_about = ToolButton(FluentIcon.INFO, self.sidebar)
        self.btn_about.setCheckable(True)
        self.btn_about.setToolTip("项目介绍")
        self.btn_about.setFixedSize(50, 50)

        # 创建按钮容器，居中显示
        buttons_container = QWidget()
        buttons_layout = QVBoxLayout(buttons_container)
        buttons_layout.setContentsMargins(0, 20, 0, 0)
        buttons_layout.setSpacing(15)
        buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        buttons_layout.addWidget(self.btn_firmware)
        buttons_layout.addWidget(self.btn_material)
        buttons_layout.addWidget(self.btn_market)
        buttons_layout.addWidget(self.btn_about)

        sidebar_layout.addWidget(buttons_container)
        sidebar_layout.addStretch()

        # 设置按钮单独放在底部
        self.btn_settings = ToolButton(FluentIcon.SETTING, self.sidebar)
        self.btn_settings.setCheckable(True)
        self.btn_settings.setToolTip("设置")
        self.btn_settings.setFixedSize(50, 50)
        sidebar_layout.addWidget(
            self.btn_settings,
            alignment=Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addSpacing(20)

        # 设置侧边栏固定宽度
        self.sidebar.setFixedWidth(80)
        content_layout.addWidget(self.sidebar)

        # === 右侧: 内容区域 ===
        self.content_stack = QWidget()
        self.content_stack.setObjectName("content_stack")
        self.content_layout = QVBoxLayout(self.content_stack)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)

        # 三栏分割器（素材制作界面）
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        # === 左侧: 配置面板 ===
        from gui.widgets.basic_config_panel import BasicConfigPanel

        # 创建配置面板容器
        self.config_container = QWidget()
        self.config_layout = QVBoxLayout(self.config_container)

        # 添加设置模式切换按钮
        from qfluentwidgets import SegmentedWidget
        self.settings_mode_switch = SegmentedWidget()
        self.settings_mode_switch.addItem("basic", "基础设置")
        self.settings_mode_switch.addItem("advanced", "高级设置")
        self.settings_mode_switch.setCurrentItem("basic")
        self.settings_mode_switch.setFixedHeight(40)
        self.settings_mode_switch.setStyleSheet("margin: 10px;")
        self.settings_mode_switch.currentItemChanged.connect(
            self._on_settings_mode_changed)
        self.config_layout.addWidget(self.settings_mode_switch)

        # 高级配置面板
        self.advanced_config_panel = ConfigPanel()

        # 基础配置面板
        self.basic_config_panel = BasicConfigPanel()

        # 默认显示基础配置面板
        self.config_layout.addWidget(self.advanced_config_panel)
        self.config_layout.addWidget(self.basic_config_panel)
        self.advanced_config_panel.setVisible(False)
        self.basic_config_panel.setVisible(True)

        # 基础模式下，只显示循环视频标签页
        if hasattr(self, 'preview_tabs'):
            # 隐藏不需要的标签页
            for i in [0, 1, 2]:  # 0:入场视频, 1:截取帧编辑, 2:过渡图片
                if i < self.preview_tabs.count():
                    self.preview_tabs.setTabVisible(i, False)
            # 显示循环视频标签页
            if 3 < self.preview_tabs.count():
                self.preview_tabs.setTabVisible(3, True)
            # 切换到循环视频标签页
            self.preview_tabs.setCurrentIndex(3)

        self.splitter.addWidget(self.config_container)

        # === 中间: 视频预览标签页 + 时间轴 ===
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(5, 5, 5, 5)
        preview_layout.setSpacing(5)

        # 标签页：入场视频 / 截取帧编辑 / 过渡图片 / 循环视频 - 使用Fluent TabWidget
        self.preview_tabs = TabWidget()
        self.preview_tabs.setTabsClosable(False)  # 禁用关闭按钮
        self.preview_tabs.setMovable(False)  # 禁用标签移动
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
        self.btn_save_icon = PrimaryPushButton("保存为图标")
        btn_layout.addWidget(self.btn_save_icon)
        frame_capture_layout.addLayout(btn_layout)

        self.preview_tabs.addTab(self.intro_preview, "入场视频")         # Tab 0
        self.preview_tabs.addTab(frame_capture_widget, "截取帧编辑")     # Tab 1
        self.preview_tabs.addTab(self.transition_preview, "过渡图片")    # Tab 2
        self.preview_tabs.addTab(self.video_preview, "循环视频")         # Tab 3
        preview_layout.addWidget(self.preview_tabs, stretch=1)

        # 默认应用基础设置模式的标签页显示逻辑
        # 隐藏不需要的标签页
        for i in [0, 1, 2]:  # 0:入场视频, 1:截取帧编辑, 2:过渡图片
            if i < self.preview_tabs.count():
                self.preview_tabs.setTabVisible(i, False)
        # 显示循环视频标签页
        if 3 < self.preview_tabs.count():
            self.preview_tabs.setTabVisible(3, True)
        # 切换到循环视频标签页
        self.preview_tabs.setCurrentIndex(3)

        self.timeline = TimelineWidget()
        preview_layout.addWidget(self.timeline)

        self.splitter.addWidget(preview_container)

        # === 右侧: JSON预览 ===
        self.json_preview = JsonPreviewWidget()
        self.splitter.addWidget(self.json_preview)

        # 设置分割比例，增加中间预览区域的空间
        self.splitter.setSizes([350, 800, 300])
        self.splitter.setStretchFactor(0, 1)   # 左侧允许少量伸缩
        self.splitter.setStretchFactor(1, 20)  # 中间优先伸缩，权重更大
        self.splitter.setStretchFactor(2, 1)   # 右侧允许少量伸缩

        self.content_layout.addWidget(self.splitter)
        content_layout.addWidget(self.content_stack)

        main_layout.addWidget(content_container)

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

        # 最近打开的文件
        self.recent_menu = file_menu.addMenu("最近打开(&R)")
        self._update_recent_menu()

        file_menu.addSeparator()

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

        # 编辑菜单
        edit_menu = menubar.addMenu("编辑(&E)")

        self.action_undo = QAction("撤销(&U)", self)
        self.action_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.action_undo.setEnabled(False)
        edit_menu.addAction(self.action_undo)

        self.action_redo = QAction("重做(&R)", self)
        self.action_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self.action_redo.setEnabled(False)
        edit_menu.addAction(self.action_redo)

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
        self.action_undo.triggered.connect(self._on_undo)
        self.action_redo.triggered.connect(self._on_redo)
        self.action_flasher.triggered.connect(self._on_flasher)
        self.action_shortcuts.triggered.connect(self._on_shortcuts)
        self.action_check_update.triggered.connect(self._on_check_update)
        self.action_about.triggered.connect(self._on_about)

        # 高级配置面板信号
        self.advanced_config_panel.config_changed.connect(
            self._on_config_changed)
        self.advanced_config_panel.video_file_selected.connect(
            self._on_video_file_selected)
        self.advanced_config_panel.intro_video_selected.connect(
            self._on_intro_video_selected)
        self.advanced_config_panel.loop_image_selected.connect(
            self._load_loop_image)
        self.advanced_config_panel.loop_mode_changed.connect(
            self._on_loop_mode_changed)
        self.advanced_config_panel.validate_requested.connect(
            self._on_validate)
        self.advanced_config_panel.export_requested.connect(self._on_export)
        self.advanced_config_panel.capture_frame_requested.connect(
            self._on_capture_frame)
        self.advanced_config_panel.transition_image_changed.connect(
            self._on_transition_image_changed)

        # 基础配置面板信号
        self.basic_config_panel.config_changed.connect(self._on_config_changed)
        self.basic_config_panel.video_file_selected.connect(
            self._on_video_file_selected)
        self.basic_config_panel.validate_requested.connect(self._on_validate)
        self.basic_config_panel.export_requested.connect(self._on_export)

        # 截取帧编辑 - 保存图标按钮
        self.btn_save_icon.clicked.connect(self._on_save_captured_icon)

        # 过渡图片裁切变化
        self.transition_preview.transition_crop_changed.connect(
            self._on_transition_crop_changed)

        # 标签页切换
        self.preview_tabs.currentChanged.connect(self._on_preview_tab_changed)

        # 循环视频预览
        self.video_preview.video_loaded.connect(self._on_video_loaded)
        self.video_preview.frame_changed.connect(self._on_frame_changed)
        self.video_preview.playback_state_changed.connect(
            self._on_playback_changed)
        self.video_preview.rotation_changed.connect(self.timeline.set_rotation)

        # 侧边栏导航
        self.btn_firmware.clicked.connect(self._on_sidebar_firmware)
        self.btn_material.clicked.connect(self._on_sidebar_material)
        self.btn_market.clicked.connect(self._on_sidebar_market)
        self.btn_about.clicked.connect(self._on_sidebar_about)
        self.btn_settings.clicked.connect(self._on_sidebar_settings)

        # 入场视频预览
        self.intro_preview.video_loaded.connect(self._on_intro_video_loaded)
        self.intro_preview.frame_changed.connect(self._on_intro_frame_changed)
        self.intro_preview.playback_state_changed.connect(
            self._on_intro_playback_changed)
        self.intro_preview.rotation_changed.connect(
            self._on_intro_rotation_changed)

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

    def _load_user_settings(self):
        """加载用户设置"""
        try:
            import json
            config_dir = os.path.join(
                os.path.dirname(__file__), "..", "config")
            config_file = os.path.join(config_dir, "user_settings.json")

            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    settings = json.load(f)

                # 应用设置到相应的控件
                if hasattr(self, 'auto_update_check'):
                    self.auto_update_check.setChecked(
                        settings.get('auto_update', True))
                if hasattr(self, 'update_freq_combo'):
                    self.update_freq_combo.setCurrentText(
                        settings.get('update_freq', '每天'))
                if hasattr(self, 'font_size_combo'):
                    self.font_size_combo.setCurrentText(
                        settings.get('font_size', '中'))
                if hasattr(self, 'theme_combo'):
                    self.theme_combo.setCurrentText(
                        settings.get('theme', '默认'))
                if hasattr(self, 'color_button'):
                    theme_color = settings.get('theme_color', '#ff6b8b')
                    self.color_button.setStyleSheet(
                        f"background-color: {theme_color}; border: 1px solid #ddd; border-radius: 4px;")
                if hasattr(self, 'image_path_label'):
                    theme_image = settings.get('theme_image', '')
                    if theme_image:
                        self.image_path_label.setText(
                            os.path.basename(theme_image))
                if hasattr(self, 'scale_spin'):
                    self.scale_spin.setValue(settings.get('scale', 1.0))
                if hasattr(self, 'lang_combo'):
                    self.lang_combo.setCurrentText(
                        settings.get('language', '简体中文'))
                if hasattr(self, 'temp_project_check'):
                    self.temp_project_check.setChecked(
                        settings.get('auto_create_temp_project', True))
                if hasattr(self, 'welcome_check'):
                    self.welcome_check.setChecked(
                        settings.get('show_welcome_dialog', True))
                if hasattr(self, 'status_check'):
                    self.status_check.setChecked(
                        settings.get('show_status_bar', True))
                if hasattr(self, 'autosave_check'):
                    self.autosave_check.setChecked(
                        settings.get('auto_save', False))
                if hasattr(self, 'preview_combo'):
                    self.preview_combo.setCurrentText(
                        settings.get('preview_quality', '中'))
                if hasattr(self, 'hwaccel_check'):
                    self.hwaccel_check.setChecked(
                        settings.get('hardware_acceleration', True))
                if hasattr(self, 'export_quality_combo'):
                    self.export_quality_combo.setCurrentText(
                        settings.get('export_quality', '高'))
                if hasattr(self, 'export_thread_spin'):
                    self.export_thread_spin.setValue(
                        settings.get('export_threads', 4))
                if hasattr(self, 'github_accel_check'):
                    self.github_accel_check.setChecked(
                        settings.get('github_acceleration', True))
                if hasattr(self, 'proxy_check'):
                    self.proxy_check.setChecked(
                        settings.get('use_proxy', False))

                # 应用主题设置
                theme_name = settings.get('theme', '默认')
                self._apply_theme_change(theme_name)

                logger.info("已加载用户设置")
        except Exception as e:
            logger.error(f"加载用户设置失败: {e}")

    def _check_first_run(self):
        """检查是否首次运行"""
        settings = QSettings("ArknightsPassMaker", "MainWindow")
        if not settings.value("first_run_completed", False, type=bool):
            # 检查用户设置是否允许显示欢迎对话框
            show_welcome = True
            try:
                import json
                config_dir = os.path.join(
                    os.path.dirname(__file__), "..", "config")
                config_file = os.path.join(config_dir, "user_settings.json")
                if os.path.exists(config_file):
                    with open(config_file, "r", encoding="utf-8") as f:
                        user_settings = json.load(f)
                        show_welcome = user_settings.get(
                            'show_welcome_dialog', True)
            except Exception:
                pass

            if show_welcome:
                # 显示开屏公告
                self._show_splash_announcement()
                settings.setValue("first_run_completed", True)
        else:
            # 每次启动都显示开屏公告（可选择不再显示）
            self._show_splash_announcement()

    def _show_splash_announcement(self):
        """显示开屏公告"""
        # 检查是否需要显示公告
        settings = QSettings("ArknightsPassMaker", "MainWindow")
        if not settings.value("show_announcement", True, type=bool):
            return

        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextBrowser, QCheckBox
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QIcon

        # 创建公告对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("软件使用指南")
        dialog.setMinimumSize(800, 600)
        dialog.setWindowIcon(
            QIcon(
                os.path.join(
                    os.path.dirname(__file__),
                    '..',
                    'resources',
                    'icons',
                    'favicon.ico')))

        # 主布局
        main_layout = QVBoxLayout(dialog)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # 标题
        title_label = QLabel("欢迎使用明日方舟通行证素材制作器 v2.0")
        title_label.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #ff6b8b; text-align: center;")
        main_layout.addWidget(title_label)

        # 内容区域
        content_browser = QTextBrowser()
        content_browser.setStyleSheet("font-size: 14px; line-height: 1.5;")

        # 公告内容
        announcement_content = """
        <h2>软件使用指南</h2>

        <h3>一、软件简介</h3>
        <p>明日方舟通行证素材制作器是一款专门用于创建和编辑明日方舟电子通行证素材的工具，支持视频、图片等多种素材类型的处理和导出。</p>

        <h3>二、主要模块</h3>

        <h4>1. 固件烧录</h4>
        <p>用于为迷你Linux手持开发板烧录固件，支持FEL模式和DFU模式。</p>
        <ul>
            <li><strong>自动检测设备</strong>：软件会自动检测连接的设备类型</li>
            <li><strong>多版本选择</strong>：可选择不同版本的固件进行烧录</li>
            <li><strong>驱动安装</strong>：内置驱动安装功能，确保设备正常识别</li>
        </ul>

        <h4>2. 素材制作</h4>
        <p>软件的核心功能，用于创建和编辑通行证素材。</p>
        <ul>
            <li><strong>基础设置</strong>：简化的界面，适合快速创建素材</li>
            <li><strong>高级设置</strong>：完整的功能界面，支持详细的参数调整</li>
            <li><strong>视频预览</strong>：实时预览视频效果</li>
            <li><strong>过渡效果</strong>：支持自定义过渡图片</li>
            <li><strong>时间轴编辑</strong>：精确控制视频片段</li>
            <li><strong>JSON预览</strong>：实时查看生成的配置文件</li>
        </ul>

        <h4>3. 素材商城</h4>
        <p>内置素材商城客户端，提供完整的素材浏览和管理功能。</p>
        <ul>
            <li><strong>素材浏览</strong>：搜索、筛选和排序素材资源</li>
            <li><strong>下载管理</strong>：多任务下载，支持暂停和续传</li>
            <li><strong>素材库</strong>：管理已下载的素材文件</li>
            <li><strong>USB 传输</strong>：直接将素材传输到设备</li>
        </ul>

        <h4>4. 项目介绍</h4>
        <p>查看项目的详细介绍和最新动态。</p>
        <ul>
            <li><strong>官方网站</strong>：直接访问项目官网获取最新信息</li>
            <li><strong>项目特性</strong>：了解开发板的主要功能和规格</li>
        </ul>

        <h4>5. 设置</h4>
        <p>自定义软件的各项设置。</p>
        <ul>
            <li><strong>主题设置</strong>：可选择默认主题或自定义主题图片</li>
            <li><strong>界面设置</strong>：调整字体大小、界面缩放等</li>
            <li><strong>视频设置</strong>：设置预览质量和硬件加速</li>
            <li><strong>导出设置</strong>：调整导出质量和线程数</li>
            <li><strong>网络设置</strong>：配置GitHub加速等网络选项</li>
        </ul>

        <h3>三、使用流程</h3>
        <ol>
            <li><strong>准备素材</strong>：收集需要的视频、图片等素材文件</li>
            <li><strong>创建项目</strong>：点击"文件"菜单选择"新建项目"</li>
            <li><strong>编辑素材</strong>：在素材制作模块中调整各项参数</li>
            <li><strong>预览效果</strong>：使用预览功能查看效果</li>
            <li><strong>导出素材</strong>：点击"导出"按钮生成最终素材</li>
            <li><strong>烧录固件</strong>：使用固件烧录模块将素材烧录到设备</li>
        </ol>

        <h3>四、注意事项</h3>
        <ul>
            <li>确保使用兼容的视频格式（建议使用MP4格式）</li>
            <li>视频分辨率建议与设备屏幕分辨率匹配（360×640）</li>
            <li>使用高质量素材以获得最佳显示效果</li>
            <li>定期检查更新以获取最新功能和 bug 修复</li>
            <li>如遇到问题，请参考帮助文档或联系开发者</li>
        </ul>

        <h3>五、快捷键</h3>
        <ul>
            <li><strong>Ctrl+N</strong>：新建项目</li>
            <li><strong>Ctrl+O</strong>：打开项目</li>
            <li><strong>Ctrl+S</strong>：保存项目</li>
            <li><strong>F1</strong>：查看快捷键帮助</li>
        </ul>

        <h3>六、常见问题</h3>
        <h4>Q: 软件启动时提示缺少模块？</h4>
        <p>A: 请确保已安装所有必要的依赖包，可使用 pip 安装缺少的模块。</p>

        <h4>Q: 固件烧录失败？</h4>
        <p>A: 请检查设备连接是否正常，驱动是否安装正确，尝试更换USB端口或线缆。</p>

        <h4>Q: 导出的素材在设备上显示异常？</h4>
        <p>A: 请检查素材格式是否正确，分辨率是否匹配设备屏幕。</p>

        <h3>七、联系我们</h3>
        <p>如果您在使用过程中遇到任何问题，或有任何建议和反馈，欢迎联系我们。</p>
        <p>项目地址：<a href="https://github.com/rhodesepass/neo-assetmaker">https://github.com/rhodesepass/neo-assetmaker</a></p>
        <p>官方网站：<a href="https://ep.iccmc.cc">https://ep.iccmc.cc</a></p>

        <p style="text-align: center; color: #666; margin-top: 30px;">
            祝您使用愉快！
        </p>
        """

        content_browser.setHtml(announcement_content)
        main_layout.addWidget(content_browser)

        # 底部布局
        bottom_layout = QHBoxLayout()

        # 不再显示复选框
        self.show_announcement_check = QCheckBox("下次启动时不再显示")
        bottom_layout.addWidget(self.show_announcement_check)

        # 按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        ok_button = PrimaryPushButton("我知道了")
        ok_button.clicked.connect(dialog.accept)

        button_layout.addWidget(ok_button)
        bottom_layout.addLayout(button_layout)

        main_layout.addLayout(bottom_layout)

        # 显示对话框
        dialog.exec()

        # 如果用户选择不再显示，保存设置
        if self.show_announcement_check.isChecked():
            settings = QSettings("ArknightsPassMaker", "MainWindow")
            settings.setValue("show_announcement", False)

    def _init_temp_project(self):
        """创建临时项目，用户可立即开始编辑"""
        temp_dir = tempfile.mkdtemp(prefix="neo_assetmaker_")
        self._temp_dir = temp_dir

        self._config = EPConfig()
        self._base_dir = temp_dir
        self._project_path = ""  # 留空，首次保存时触发"另存为"
        self._is_modified = False

        self.advanced_config_panel.set_config(self._config, self._base_dir)
        self.basic_config_panel.set_config(self._config, self._base_dir)
        self.json_preview.set_config(self._config, self._base_dir)
        self.video_preview.set_epconfig(self._config)
        self._update_title()
        self.status_bar.showMessage("已创建临时项目，可以开始编辑")
        logger.info(f"已初始化临时项目: {temp_dir}")

        # 启动自动保存服务（临时项目也支持自动保存）
        self._auto_save_service.start(
            self._config, self._project_path, self._base_dir)

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
        self.advanced_config_panel.set_config(self._config, self._base_dir)
        self.basic_config_panel.set_config(self._config, self._base_dir)
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
            self.advanced_config_panel.set_config(self._config, self._base_dir)
            self.basic_config_panel.set_config(self._config, self._base_dir)
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
                        QTimer.singleShot(
                            100, lambda fp=file_path: self._load_loop_image(fp))
                    else:
                        # 视频模式
                        logger.info(f"尝试加载循环视频: {file_path}")
                        QTimer.singleShot(
                            100, lambda vp=file_path: self.video_preview.load_video(vp))
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
                    QTimer.singleShot(
                        200, lambda vp=intro_path: self.intro_preview.load_video(vp))

            self._update_title()
            self.status_bar.showMessage(f"已打开: {path}")

            # 添加到最近文件列表
            self._add_recent_file(path)

            # 启动自动保存服务
            self._auto_save_service.start(
                self._config, self._project_path, self._base_dir)

        except Exception as e:
            show_error(e, "打开文件", self)

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
            show_error(e, "保存项目", self)

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
            self.advanced_config_panel.set_config(self._config, self._base_dir)
            self.json_preview.set_config(self._config, self._base_dir)

            self._update_title()
            self.status_bar.showMessage(f"已保存: {path}")
        except Exception as e:
            show_error(e, "另存为", self)

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
        has_loop_image = self._config.loop.is_image and hasattr(
            self, '_loop_image_path') and self._loop_image_path

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
            show_error(e, "收集导出数据", self)
            return

        # 处理arknights叠加的自定义图片
        try:
            self._process_arknights_custom_images(dir_path)
        except Exception as e:
            logger.error(f"处理自定义图片失败: {e}")
            show_error(e, "处理自定义图片", self)

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
            QMessageBox.information(
                self, "提示",
                f"模拟器未找到\n\n"
                f"模拟器功能需要先编译 Rust 模拟器:\n"
                f"cd simulator && cargo build --release\n\n"
                f"路径: {simulator_path}\n\n"
                f"如果您不需要使用模拟器预览功能，可以忽略此提示。"
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
            show_error(e, "启动模拟器", self)

    def _on_flasher(self):
        """启动固件烧录工具"""
        if sys.platform != 'win32':
            QMessageBox.warning(self, "不支持", "烧录工具目前仅支持 Windows")
            return

        try:
            from gui.dialogs.flasher_dialog import FlasherDialog
            dialog = FlasherDialog(self)
            dialog.exec()
            self.status_bar.showMessage("烧录工具已启动")
            logger.info("固件烧录对话框已启动")
        except Exception as e:
            logger.error(f"启动烧录工具失败: {e}")
            show_error(e, "启动烧录工具", self)

    def _on_about(self):
        """关于"""
        QMessageBox.about(
            self, f"关于 {APP_NAME}",
            f"<h3>{APP_NAME}</h3>"
            f"<p>版本: {APP_VERSION}</p>"
            f"<p>明日方舟通行证素材制作器</p>"
            f"<p>作者: Rafael_ban & 初微弦音 & 涙不在为你而流</p>"
        )

    def _update_recent_menu(self):
        """更新最近打开的文件菜单"""
        self.recent_menu.clear()

        if not self._recent_files:
            action = QAction("无最近文件", self)
            action.setEnabled(False)
            self.recent_menu.addAction(action)
            return

        for i, file_path in enumerate(self._recent_files):
            action = QAction(f"{i + 1}. {file_path}", self)
            action.setData(file_path)
            action.triggered.connect(
                lambda checked,
                path=file_path: self._on_open_recent_file(path))
            self.recent_menu.addAction(action)

        self.recent_menu.addSeparator()

        clear_action = QAction("清空最近文件", self)
        clear_action.triggered.connect(self._clear_recent_files)
        self.recent_menu.addAction(clear_action)

    def _on_open_recent_file(self, file_path: str):
        """打开最近文件"""
        if os.path.exists(file_path):
            self._load_project(file_path)
        else:
            QMessageBox.warning(
                self,
                "文件不存在",
                f"文件不存在:\n{file_path}\n\n将从最近文件列表中移除。"
            )
            self._recent_files.remove(file_path)
            self._update_recent_menu()

    def _clear_recent_files(self):
        """清空最近文件列表"""
        self._recent_files.clear()
        self._update_recent_menu()

    def _add_recent_file(self, file_path: str):
        """添加文件到最近打开列表"""
        if file_path in self._recent_files:
            self._recent_files.remove(file_path)

        self._recent_files.insert(0, file_path)

        if len(self._recent_files) > self._max_recent_files:
            self._recent_files.pop()

        self._update_recent_menu()

    def _on_undo(self):
        """撤销操作"""
        if not self._undo_stack:
            return

        # 获取上一个状态
        prev_state = self._undo_stack.pop()

        # 保存当前状态到重做栈
        current_state = self._config.to_dict() if self._config else {}
        self._redo_stack.append(current_state)

        # 恢复上一个状态
        if prev_state:
            self._config = EPConfig.from_dict(prev_state)
            self._update_ui_from_config()

        # 更新按钮状态
        self.action_undo.setEnabled(len(self._undo_stack) > 0)
        self.action_redo.setEnabled(len(self._redo_stack) > 0)

        self.status_bar.showMessage("已撤销", 2000)

    def _on_redo(self):
        """重做操作"""
        if not self._redo_stack:
            return

        # 获取下一个状态
        next_state = self._redo_stack.pop()

        # 保存当前状态到撤销栈
        current_state = self._config.to_dict() if self._config else {}
        self._undo_stack.append(current_state)

        # 恢复下一个状态
        if next_state:
            self._config = EPConfig.from_dict(next_state)
            self._update_ui_from_config()

        # 更新按钮状态
        self.action_undo.setEnabled(len(self._undo_stack) > 0)
        self.action_redo.setEnabled(len(self._redo_stack) > 0)

        self.status_bar.showMessage("已重做", 2000)

    def _save_state(self):
        """保存当前状态到撤销栈"""
        if not self._config:
            return

        current_state = self._config.to_dict()
        self._undo_stack.append(current_state)

        # 限制历史记录数量
        if len(self._undo_stack) > self._max_history:
            self._undo_stack.pop(0)

        # 清空重做栈
        self._redo_stack.clear()

        # 更新按钮状态
        self.action_undo.setEnabled(len(self._undo_stack) > 0)
        self.action_redo.setEnabled(False)

    def _update_ui_from_config(self):
        """从配置更新UI"""
        if not self._config:
            return

        self.advanced_config_panel.set_config(self._config, self._base_dir)
        self.basic_config_panel.set_config(self._config, self._base_dir)
        self.json_preview.set_config(self._config, self._base_dir)
        self.video_preview.set_epconfig(self._config)

        self._is_modified = True
        self._update_title()

    def _on_sidebar_firmware(self):
        """侧边栏：固件烧录"""
        # 重置所有按钮状态
        self.btn_firmware.setChecked(True)
        self.btn_material.setChecked(False)
        self.btn_market.setChecked(False)
        self.btn_about.setChecked(False)
        self.btn_settings.setChecked(False)

        # 隐藏其他视图
        self.splitter.setVisible(False)
        if hasattr(self, '_market_widget'):
            self._market_widget.setVisible(False)
        if hasattr(self, '_settings_widget'):
            self._settings_widget.setVisible(False)
        if hasattr(self, '_about_widget'):
            self._about_widget.setVisible(False)

        # 检查是否已经创建了烧录界面
        if not hasattr(self, '_flasher_widget'):
            from gui.dialogs.flasher_dialog import FlasherDialog

            # 创建烧录界面widget
            self._flasher_widget = QWidget()
            self._flasher_widget_layout = QVBoxLayout(self._flasher_widget)

            # 创建FlasherDialog实例，但不显示为对话框
            self._flasher_dialog = FlasherDialog(self)

            # 移除对话框的窗口装饰
            self._flasher_dialog.setWindowFlags(Qt.WindowType.Widget)

            # 将FlasherDialog添加到widget中
            self._flasher_widget_layout.addWidget(self._flasher_dialog)

            # 添加到内容布局
            self.content_layout.addWidget(self._flasher_widget)

        # 显示烧录界面
        self._flasher_widget.setVisible(True)
        self.status_bar.showMessage("固件烧录模式")

    def _on_sidebar_material(self):
        """侧边栏：素材制作"""
        # 重置所有按钮状态
        self.btn_firmware.setChecked(False)
        self.btn_material.setChecked(True)
        self.btn_market.setChecked(False)
        self.btn_about.setChecked(False)
        self.btn_settings.setChecked(False)

        # 隐藏市场视图（如果存在）
        if hasattr(self, '_market_widget'):
            self._market_widget.setVisible(False)

        # 隐藏设置视图（如果存在）
        if hasattr(self, '_settings_widget'):
            self._settings_widget.setVisible(False)

        # 隐藏项目介绍视图（如果存在）
        if hasattr(self, '_about_widget'):
            self._about_widget.setVisible(False)

        # 隐藏烧录界面（如果存在）
        if hasattr(self, '_flasher_widget'):
            self._flasher_widget.setVisible(False)

        # 显示素材制作界面
        self.splitter.setVisible(True)
        self.status_bar.showMessage("素材制作模式")

    def _on_sidebar_market(self):
        """侧边栏：素材商城"""
        self.btn_firmware.setChecked(False)
        self.btn_material.setChecked(False)
        self.btn_market.setChecked(True)
        self.btn_about.setChecked(False)
        self.btn_settings.setChecked(False)

        self.splitter.setVisible(False)
        if hasattr(self, '_settings_widget'):
            self._settings_widget.setVisible(False)
        if hasattr(self, '_about_widget'):
            self._about_widget.setVisible(False)
        if hasattr(self, '_flasher_widget'):
            self._flasher_widget.setVisible(False)

        if not hasattr(self, '_market_widget'):
            from _mext.ui.widget import MaterialMarketWidget
            self._market_widget = MaterialMarketWidget(parent=self)
            self.content_layout.addWidget(self._market_widget)

        self._market_widget.setVisible(True)
        self.status_bar.showMessage("素材商城模式")

    def _on_sidebar_about(self):
        """侧边栏：项目介绍"""
        # 重置所有按钮状态
        self.btn_firmware.setChecked(False)
        self.btn_material.setChecked(False)
        self.btn_market.setChecked(False)
        self.btn_about.setChecked(True)
        self.btn_settings.setChecked(False)

        # 隐藏其他视图
        self.splitter.setVisible(False)
        if hasattr(self, '_market_widget'):
            self._market_widget.setVisible(False)
        if hasattr(self, '_settings_widget'):
            self._settings_widget.setVisible(False)
        if hasattr(self, '_flasher_widget'):
            self._flasher_widget.setVisible(False)

        # 预创建项目介绍视图（如果尚未创建）
        if not hasattr(self, '_about_widget'):
            from PyQt6.QtWidgets import QLabel, QVBoxLayout, QTextBrowser

            # 创建项目介绍视图
            self._about_widget = QWidget()
            self._about_widget.setVisible(False)  # 初始设置为不可见

            about_layout = QVBoxLayout(self._about_widget)
            about_layout.setContentsMargins(20, 10, 20, 10)  # 减小上下边距
            about_layout.setSpacing(15)  # 设置间距

            # 标题
            title_label = QLabel("项目介绍")
            setCustomStyleSheet(
                title_label,
                "font-size: 18px; font-weight: bold; color: #333;",
                "font-size: 18px; font-weight: bold; color: #eee;"
            )
            about_layout.addWidget(title_label)

            # 创建WebEngineView
            try:
                from PyQt6.QtWebEngineWidgets import QWebEngineView
                web_view = QWebEngineView()
                web_view.setUrl(QUrl("https://ep.iccmc.cc"))
                setCustomStyleSheet(
                    web_view,
                    "border: 1px solid #e9ecef; border-radius: 8px;",
                    "border: 1px solid #555; border-radius: 8px;"
                )
                about_layout.addWidget(web_view)

                # 添加网站链接
                url_label = QLabel(
                    f"网站链接: <a href='https://ep.iccmc.cc'>https://ep.iccmc.cc</a>")
                url_label.setOpenExternalLinks(True)
                url_label.setStyleSheet(
                    "color: #ff6b8b; text-decoration: underline;")
                about_layout.addWidget(url_label)

            except Exception as e:
                # 如果无法加载WebEngine，显示错误信息
                text_browser = QTextBrowser()
                text_browser.setOpenExternalLinks(True)
                setCustomStyleSheet(
                    text_browser,
                    "border: 1px solid #e9ecef; border-radius: 8px;",
                    "border: 1px solid #555; border-radius: 8px;"
                )
                error_html = f"""
                <div style="color: #ff6b8b; padding: 10px;">
                    <h3>无法加载网页视图</h3>
                    <p>错误信息: {str(e)}</p>
                    <p>请直接访问: <a href='https://ep.iccmc.cc'>https://ep.iccmc.cc</a></p>
                    <h3>项目简介</h3>
                    <p>迷你Linux手持开发板基于F1C200S的开源硬件项目一款面向折腾与二次开发的迷你 Linux 手持开发板</p>
                    <h4>主要特性</h4>
                    <ul>
                        <li>高性能主控基于F1C200S (ARM926EJ-S)，默认408MHz，支持超频至720MHz，内置64MB RAM</li>
                        <li>高清竖屏显示3.0英寸 360×640 高分辨率竖屏，ST7701S驱动，支持H.264硬件解码</li>
                        <li>完善供电方案1500mAh锂电池，TP4056充电管理，续航持久（大概）</li>
                        <li>丰富扩展接口I²C、UART×2、SPI、GPIO×3、ADC，满足各种硬件实验需求</li>
                        <li>主线Linux支持Buildroot构建系统，Linux主线5.4.77内核，完整Linux生态</li>
                        <li>完全开源硬件/软件资料完全开源，欢迎社区共同完善</li>
                    </ul>
                    <h4>最新版本</h4>
                    <p>当前版本：Ver.0.6</p>
                </div>
                """
                text_browser.setHtml(error_html)
                about_layout.addWidget(text_browser)

                # 添加网站链接
                url_label = QLabel(
                    f"网站链接: <a href='https://ep.iccmc.cc'>https://ep.iccmc.cc</a>")
                url_label.setOpenExternalLinks(True)
                url_label.setStyleSheet(
                    "color: #ff6b8b; text-decoration: underline;")
                about_layout.addWidget(url_label)

            # 一次性添加到内容布局
            self.content_layout.addWidget(self._about_widget)

        # 显示项目介绍视图
        self._about_widget.setVisible(True)

        self.status_bar.showMessage("项目介绍")

    def _on_settings_mode_changed(self, mode):
        """设置模式切换"""
        try:
            if mode == "basic":
                # 显示基础设置界面
                self.advanced_config_panel.setVisible(False)
                self.basic_config_panel.setVisible(True)
                self.status_bar.showMessage("基础设置模式 - 简化界面")

                # 基础模式下，只显示循环视频标签页
                if hasattr(self, 'preview_tabs'):
                    # 隐藏不需要的标签页
                    for i in [0, 1, 2]:  # 0:入场视频, 1:截取帧编辑, 2:过渡图片
                        if i < self.preview_tabs.count():
                            self.preview_tabs.setTabVisible(i, False)
                    # 显示循环视频标签页
                    if 3 < self.preview_tabs.count():
                        self.preview_tabs.setTabVisible(3, True)
                    # 切换到循环视频标签页
                    self.preview_tabs.setCurrentIndex(3)
            elif mode == "advanced":
                # 显示高级设置界面
                self.advanced_config_panel.setVisible(True)
                self.basic_config_panel.setVisible(False)
                self.status_bar.showMessage("高级设置模式 - 完整界面")

                # 高级模式下，显示所有标签页
                if hasattr(self, 'preview_tabs'):
                    for i in range(self.preview_tabs.count()):
                        self.preview_tabs.setTabVisible(i, True)
        except Exception as e:
            logger.error(f"设置模式切换错误: {e}")

    def _on_sidebar_settings(self):
        """侧边栏：设置"""
        # 重置所有按钮状态
        self.btn_firmware.setChecked(False)
        self.btn_material.setChecked(False)
        self.btn_market.setChecked(False)
        self.btn_about.setChecked(False)
        self.btn_settings.setChecked(True)

        # 隐藏市场视图（如果存在）
        if hasattr(self, '_market_widget'):
            self._market_widget.setVisible(False)

        # 隐藏素材制作界面
        self.splitter.setVisible(False)

        # 隐藏项目介绍视图（如果存在）
        if hasattr(self, '_about_widget'):
            self._about_widget.setVisible(False)

        # 隐藏烧录界面（如果存在）
        if hasattr(self, '_flasher_widget'):
            self._flasher_widget.setVisible(False)

        # 每次都重新创建设置视图，确保应用新的样式
        if hasattr(self, '_settings_widget'):
            # 移除旧的设置视图
            self.content_layout.removeWidget(self._settings_widget)
            self._settings_widget.deleteLater()
        # 创建设置视图
        self._settings_widget = QWidget()
        settings_layout = QVBoxLayout(self._settings_widget)

        # 标题
        title_label = QLabel("设置")
        setCustomStyleSheet(
            title_label,
            "font-size: 18px; font-weight: bold; color: #333; margin: 10px 0;",
            "font-size: 18px; font-weight: bold; color: #eee; margin: 10px 0;"
        )
        settings_layout.addWidget(title_label)

        # 滚动区域
        scroll_area = QScrollArea()
        scroll_area.setStyleSheet("border: none;")
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(30, 20, 30, 30)
        scroll_layout.setSpacing(20)

        # 应用设置卡片
        app_card = QWidget()
        app_card_layout = QVBoxLayout(app_card)
        setCustomStyleSheet(
            app_card,
            "QWidget { background-color: #f8f9fa; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08); }",
            "QWidget { background-color: #2a2a2a; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3); }"
        )
        app_card_layout.setSpacing(16)
        app_card_layout.setContentsMargins(0, 0, 0, 0)

        # 应用设置标题
        app_title = QLabel("应用设置")
        setCustomStyleSheet(
            app_title,
            "font-size: 16px; font-weight: bold; color: #333; margin-bottom: 10px;",
            "font-size: 16px; font-weight: bold; color: #eee; margin-bottom: 10px;"
        )
        app_card_layout.addWidget(app_title)

        # 版本信息
        version_label = QLabel(f"当前版本: {APP_VERSION}")
        setCustomStyleSheet(
            version_label,
            "padding: 5px; color: #666;",
            "padding: 5px; color: #aaa;"
        )
        app_card_layout.addWidget(version_label)

        # 更新设置
        update_layout = QHBoxLayout()
        update_layout.setSpacing(16)
        update_label = QLabel("自动检查更新:")
        update_label.setFixedWidth(120)
        update_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.auto_update_check = QCheckBox()
        self.auto_update_check.setChecked(True)
        setCustomStyleSheet(
            self.auto_update_check,
            """QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 40px;
                height: 20px;
                border-radius: 10px;
                background-color: #ddd;
            }
            QCheckBox::indicator:checked {
                background-color: #ff6b8b;
            }
            QCheckBox::indicator::text {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                background-color: white;
                margin: 2px;
            }
            QCheckBox::indicator:checked::text {
                margin-left: 22px;
            }""",
            """QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 40px;
                height: 20px;
                border-radius: 10px;
                background-color: #555;
            }
            QCheckBox::indicator:checked {
                background-color: #ff6b8b;
            }
            QCheckBox::indicator::text {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                background-color: white;
                margin: 2px;
            }
            QCheckBox::indicator:checked::text {
                margin-left: 22px;
            }"""
        )
        update_layout.addWidget(update_label)
        update_layout.addWidget(self.auto_update_check)
        update_layout.addStretch()
        app_card_layout.addLayout(update_layout)

        # 检查更新频率
        update_freq_layout = QHBoxLayout()
        update_freq_layout.setSpacing(16)
        update_freq_label = QLabel("更新检查频率:")
        update_freq_label.setFixedWidth(120)
        update_freq_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.update_freq_combo = QComboBox()
        self.update_freq_combo.addItems(["每天", "每周", "每月"])
        self.update_freq_combo.setCurrentText("每天")
        setCustomStyleSheet(
            self.update_freq_combo,
            """QComboBox {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 120px;
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
            }""",
            """QComboBox {
                background-color: #333;
                color: #ddd;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 120px;
            }
            QComboBox:hover {
                border-color: #ff6b8b;
            }
            QComboBox::drop-down {
                border-left: 1px solid #555;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
            }
            QComboBox QAbstractItemView {
                background-color: #333;
                color: #ddd;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px;
            }"""
        )
        update_freq_layout.addWidget(update_freq_label)
        update_freq_layout.addWidget(self.update_freq_combo)
        update_freq_layout.addStretch()
        app_card_layout.addLayout(update_freq_layout)

        scroll_layout.addWidget(app_card)

        # 界面设置卡片
        ui_card = QWidget()
        ui_card_layout = QVBoxLayout(ui_card)
        setCustomStyleSheet(
            ui_card,
            "QWidget { background-color: #f8f9fa; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08); }",
            "QWidget { background-color: #2a2a2a; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3); }"
        )
        ui_card_layout.setSpacing(16)
        ui_card_layout.setContentsMargins(0, 0, 0, 0)

        # 界面设置标题
        ui_title = QLabel("界面设置")
        setCustomStyleSheet(
            ui_title,
            "font-size: 16px; font-weight: bold; color: #333; margin-bottom: 10px;",
            "font-size: 16px; font-weight: bold; color: #eee; margin-bottom: 10px;"
        )
        ui_card_layout.addWidget(ui_title)

        # 字体大小设置
        font_layout = QHBoxLayout()
        font_layout.setSpacing(16)
        font_label = QLabel("字体大小:")
        font_label.setFixedWidth(80)
        font_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.font_size_combo = QComboBox()
        self.font_size_combo.addItems(["小", "中", "大"])
        self.font_size_combo.setCurrentText("中")
        setCustomStyleSheet(
            self.font_size_combo,
            """QComboBox {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 120px;
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
            }""",
            """QComboBox {
                background-color: #333;
                color: #ddd;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 120px;
            }
            QComboBox:hover {
                border-color: #ff6b8b;
            }
            QComboBox::drop-down {
                border-left: 1px solid #555;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
            }
            QComboBox QAbstractItemView {
                background-color: #333;
                color: #ddd;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px;
            }"""
        )
        font_layout.addWidget(font_label)
        font_layout.addWidget(self.font_size_combo)
        font_layout.addStretch()
        ui_card_layout.addLayout(font_layout)

        # 主题设置
        theme_layout = QHBoxLayout()
        theme_layout.setSpacing(16)
        theme_label = QLabel("主题:")
        theme_label.setFixedWidth(80)
        theme_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["默认", "自定义图片"])
        self.theme_combo.setCurrentText("默认")
        setCustomStyleSheet(
            self.theme_combo,
            """QComboBox {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 120px;
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
            }""",
            """QComboBox {
                background-color: #333;
                color: #ddd;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 120px;
            }
            QComboBox:hover {
                border-color: #ff6b8b;
            }
            QComboBox::drop-down {
                border-left: 1px solid #555;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
            }
            QComboBox QAbstractItemView {
                background-color: #333;
                color: #ddd;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px;
            }"""
        )
        theme_layout.addWidget(theme_label)
        theme_layout.addWidget(self.theme_combo)
        theme_layout.addStretch()
        ui_card_layout.addLayout(theme_layout)

        # 主题颜色自定义
        from PyQt6.QtWidgets import QColorDialog
        from PyQt6.QtGui import QColor

        color_layout = QHBoxLayout()
        color_layout.setSpacing(16)
        color_label = QLabel("主题颜色:")
        color_label.setFixedWidth(80)
        color_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.color_button = PushButton()
        self.color_button.setFixedSize(40, 30)
        self.color_button.clicked.connect(
            lambda: self._open_color_dialog())
        color_layout.addWidget(color_label)
        color_layout.addWidget(self.color_button)
        color_layout.addStretch()
        ui_card_layout.addLayout(color_layout)

        # 主题图片自定义
        image_layout = QHBoxLayout()
        image_layout.setSpacing(16)
        image_label = QLabel("主题图片:")
        image_label.setFixedWidth(80)
        image_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.image_button = PushButton("选择图片")
        self.image_button.setFixedWidth(100)
        self.image_button.clicked.connect(
            lambda: self._open_image_dialog())
        self.image_path_label = QLabel("未选择")
        setCustomStyleSheet(
            self.image_path_label,
            "color: #666; font-size: 12px;",
            "color: #aaa; font-size: 12px;"
        )
        image_layout.addWidget(image_label)
        image_layout.addWidget(self.image_button)
        image_layout.addWidget(self.image_path_label)
        image_layout.addStretch()
        ui_card_layout.addLayout(image_layout)

        # 界面缩放
        scale_layout = QHBoxLayout()
        scale_layout.setSpacing(16)
        scale_label = QLabel("界面缩放:")
        scale_label.setFixedWidth(80)
        scale_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.8, 1.5)
        self.scale_spin.setSingleStep(0.1)
        self.scale_spin.setValue(1.0)
        self.scale_spin.setSuffix("x")
        self.scale_spin.setFixedWidth(100)
        setCustomStyleSheet(
            self.scale_spin,
            """QDoubleSpinBox {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 8px 12px;
            }
            QDoubleSpinBox:hover {
                border-color: #ff6b8b;
            }
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                width: 24px;
                height: 24px;
                border-radius: 4px;
            }
            QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
                background-color: #f0f0f0;
            }""",
            """QDoubleSpinBox {
                background-color: #333;
                color: #ddd;
                border: 1px solid #555;
                border-radius: 8px;
                padding: 8px 12px;
            }
            QDoubleSpinBox:hover {
                border-color: #ff6b8b;
            }
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                width: 24px;
                height: 24px;
                border-radius: 4px;
                background-color: #444;
            }
            QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
                background-color: #555;
            }"""
        )
        scale_layout.addWidget(scale_label)
        scale_layout.addWidget(self.scale_spin)
        scale_layout.addStretch()
        ui_card_layout.addLayout(scale_layout)

        scroll_layout.addWidget(ui_card)

        # 语言设置卡片
        lang_card = QWidget()
        lang_card_layout = QVBoxLayout(lang_card)
        setCustomStyleSheet(
            lang_card,
            "QWidget { background-color: #f8f9fa; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08); }",
            "QWidget { background-color: #2a2a2a; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3); }"
        )
        lang_card_layout.setSpacing(16)
        lang_card_layout.setContentsMargins(0, 0, 0, 0)

        # 语言设置标题
        lang_title = QLabel("语言设置")
        setCustomStyleSheet(
            lang_title,
            "font-size: 16px; font-weight: bold; color: #333; margin-bottom: 10px;",
            "font-size: 16px; font-weight: bold; color: #eee; margin-bottom: 10px;"
        )
        lang_card_layout.addWidget(lang_title)

        # 语言选择
        lang_combo_layout = QHBoxLayout()
        lang_combo_layout.setSpacing(16)
        lang_combo_label = QLabel("语言:")
        lang_combo_label.setFixedWidth(80)
        lang_combo_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["简体中文", "English"])
        self.lang_combo.setCurrentText("简体中文")
        setCustomStyleSheet(
            self.lang_combo,
            """QComboBox {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 120px;
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
            }""",
            """QComboBox {
                background-color: #333;
                color: #ddd;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 120px;
            }
            QComboBox:hover {
                border-color: #ff6b8b;
            }
            QComboBox::drop-down {
                border-left: 1px solid #555;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
            }
            QComboBox QAbstractItemView {
                background-color: #333;
                color: #ddd;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px;
            }"""
        )
        lang_combo_layout.addWidget(lang_combo_label)
        lang_combo_layout.addWidget(self.lang_combo)
        lang_combo_layout.addStretch()
        lang_card_layout.addLayout(lang_combo_layout)

        # 语言提示
        lang_tip = QLabel("* 语言设置需要重启应用生效")
        setCustomStyleSheet(
            lang_tip,
            "color: #999; font-size: 12px;",
            "color: #888; font-size: 12px;"
        )
        lang_card_layout.addWidget(lang_tip)

        scroll_layout.addWidget(lang_card)

        # 帮助设置卡片
        help_card = QWidget()
        help_card_layout = QVBoxLayout(help_card)
        setCustomStyleSheet(
            help_card,
            "QWidget { background-color: #f8f9fa; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08); }",
            "QWidget { background-color: #2a2a2a; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3); }"
        )
        help_card_layout.setSpacing(16)
        help_card_layout.setContentsMargins(0, 0, 0, 0)

        # 帮助设置标题
        help_title = QLabel("帮助")
        setCustomStyleSheet(
            help_title,
            "font-size: 16px; font-weight: bold; color: #333; margin-bottom: 10px;",
            "font-size: 16px; font-weight: bold; color: #eee; margin-bottom: 10px;"
        )
        help_card_layout.addWidget(help_title)

        # 快捷键帮助
        shortcuts_button = PushButton("快捷键帮助")
        setCustomStyleSheet(
            shortcuts_button,
            """QPushButton {
                background-color: #f0f0f0;
                color: #333;
                padding: 8px 16px;
                border: 1px solid #ddd;
                border-radius: 4px;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }""",
            """QPushButton {
                background-color: #404040;
                color: #ddd;
                padding: 8px 16px;
                border: 1px solid #555;
                border-radius: 4px;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
            }"""
        )
        shortcuts_button.clicked.connect(self._on_shortcuts)
        help_card_layout.addWidget(shortcuts_button)

        # 检查更新
        update_button = PushButton("检查更新")
        setCustomStyleSheet(
            update_button,
            """QPushButton {
                background-color: #f0f0f0;
                color: #333;
                padding: 8px 16px;
                border: 1px solid #ddd;
                border-radius: 4px;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }""",
            """QPushButton {
                background-color: #404040;
                color: #ddd;
                padding: 8px 16px;
                border: 1px solid #555;
                border-radius: 4px;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
            }"""
        )
        update_button.clicked.connect(self._on_check_update)
        help_card_layout.addWidget(update_button)

        # 关于
        about_button = PushButton("关于")
        setCustomStyleSheet(
            about_button,
            """QPushButton {
                background-color: #f0f0f0;
                color: #333;
                padding: 8px 16px;
                border: 1px solid #ddd;
                border-radius: 4px;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }""",
            """QPushButton {
                background-color: #404040;
                color: #ddd;
                padding: 8px 16px;
                border: 1px solid #555;
                border-radius: 4px;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
            }"""
        )
        about_button.clicked.connect(self._on_about)
        help_card_layout.addWidget(about_button)

        scroll_layout.addWidget(help_card)

        # 个性化设置卡片
        personal_card = QWidget()
        personal_card_layout = QVBoxLayout(personal_card)
        setCustomStyleSheet(
            personal_card,
            "QWidget { background-color: #f8f9fa; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08); }",
            "QWidget { background-color: #2a2a2a; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3); }"
        )
        personal_card_layout.setSpacing(16)
        personal_card_layout.setContentsMargins(0, 0, 0, 0)

        # 个性化设置标题
        personal_title = QLabel("个性化设置")
        setCustomStyleSheet(
            personal_title,
            "font-size: 16px; font-weight: bold; color: #333; margin-bottom: 10px;",
            "font-size: 16px; font-weight: bold; color: #eee; margin-bottom: 10px;"
        )
        personal_card_layout.addWidget(personal_title)

        # 启动时自动创建临时项目
        temp_project_layout = QHBoxLayout()
        temp_project_layout.setSpacing(16)
        temp_project_label = QLabel("启动时自动创建临时项目:")
        temp_project_label.setFixedWidth(180)
        temp_project_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.temp_project_check = QCheckBox()
        self.temp_project_check.setChecked(True)
        setCustomStyleSheet(
            self.temp_project_check,
            """QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 40px;
                height: 20px;
                border-radius: 10px;
                background-color: #ddd;
            }
            QCheckBox::indicator:checked {
                background-color: #ff6b8b;
            }
            QCheckBox::indicator::text {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                background-color: white;
                margin: 2px;
            }
            QCheckBox::indicator:checked::text {
                margin-left: 22px;
            }""",
            """QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 40px;
                height: 20px;
                border-radius: 10px;
                background-color: #555;
            }
            QCheckBox::indicator:checked {
                background-color: #ff6b8b;
            }
            QCheckBox::indicator::text {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                background-color: white;
                margin: 2px;
            }
            QCheckBox::indicator:checked::text {
                margin-left: 22px;
            }"""
        )
        temp_project_layout.addWidget(temp_project_label)
        temp_project_layout.addWidget(self.temp_project_check)
        temp_project_layout.addStretch()
        personal_card_layout.addLayout(temp_project_layout)

        # 显示欢迎对话框
        welcome_layout = QHBoxLayout()
        welcome_layout.setSpacing(16)
        welcome_label = QLabel("显示欢迎对话框:")
        welcome_label.setFixedWidth(180)
        welcome_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.welcome_check = QCheckBox()
        self.welcome_check.setChecked(True)
        setCustomStyleSheet(
            self.welcome_check,
            """QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 40px;
                height: 20px;
                border-radius: 10px;
                background-color: #ddd;
            }
            QCheckBox::indicator:checked {
                background-color: #ff6b8b;
            }
            QCheckBox::indicator::text {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                background-color: white;
                margin: 2px;
            }
            QCheckBox::indicator:checked::text {
                margin-left: 22px;
            }""",
            """QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 40px;
                height: 20px;
                border-radius: 10px;
                background-color: #555;
            }
            QCheckBox::indicator:checked {
                background-color: #ff6b8b;
            }
            QCheckBox::indicator::text {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                background-color: white;
                margin: 2px;
            }
            QCheckBox::indicator:checked::text {
                margin-left: 22px;
            }"""
        )
        welcome_layout.addWidget(welcome_label)
        welcome_layout.addWidget(self.welcome_check)
        welcome_layout.addStretch()
        personal_card_layout.addLayout(welcome_layout)

        # 显示状态栏
        status_layout = QHBoxLayout()
        status_layout.setSpacing(16)
        status_label = QLabel("显示状态栏:")
        status_label.setFixedWidth(180)
        status_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.status_check = QCheckBox()
        self.status_check.setChecked(True)
        setCustomStyleSheet(
            self.status_check,
            """QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 40px;
                height: 20px;
                border-radius: 10px;
                background-color: #ddd;
            }
            QCheckBox::indicator:checked {
                background-color: #ff6b8b;
            }
            QCheckBox::indicator::text {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                background-color: white;
                margin: 2px;
            }
            QCheckBox::indicator:checked::text {
                margin-left: 22px;
            }""",
            """QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 40px;
                height: 20px;
                border-radius: 10px;
                background-color: #555;
            }
            QCheckBox::indicator:checked {
                background-color: #ff6b8b;
            }
            QCheckBox::indicator::text {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                background-color: white;
                margin: 2px;
            }
            QCheckBox::indicator:checked::text {
                margin-left: 22px;
            }"""
        )
        status_layout.addWidget(status_label)
        status_layout.addWidget(self.status_check)
        status_layout.addStretch()
        personal_card_layout.addLayout(status_layout)

        # 自动保存
        autosave_layout = QHBoxLayout()
        autosave_layout.setSpacing(16)
        autosave_label = QLabel("自动保存项目:")
        autosave_label.setFixedWidth(180)
        autosave_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.autosave_check = QCheckBox()
        self.autosave_check.setChecked(False)
        setCustomStyleSheet(
            self.autosave_check,
            """QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 40px;
                height: 20px;
                border-radius: 10px;
                background-color: #ddd;
            }
            QCheckBox::indicator:checked {
                background-color: #ff6b8b;
            }
            QCheckBox::indicator::text {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                background-color: white;
                margin: 2px;
            }
            QCheckBox::indicator:checked::text {
                margin-left: 22px;
            }""",
            """QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 40px;
                height: 20px;
                border-radius: 10px;
                background-color: #555;
            }
            QCheckBox::indicator:checked {
                background-color: #ff6b8b;
            }
            QCheckBox::indicator::text {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                background-color: white;
                margin: 2px;
            }
            QCheckBox::indicator:checked::text {
                margin-left: 22px;
            }"""
        )
        autosave_layout.addWidget(autosave_label)
        autosave_layout.addWidget(self.autosave_check)
        autosave_layout.addStretch()
        personal_card_layout.addLayout(autosave_layout)

        scroll_layout.addWidget(personal_card)

        # 视频设置卡片
        video_card = QWidget()
        video_card_layout = QVBoxLayout(video_card)
        setCustomStyleSheet(
            video_card,
            "QWidget { background-color: #f8f9fa; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08); }",
            "QWidget { background-color: #2a2a2a; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3); }"
        )
        video_card_layout.setSpacing(16)
        video_card_layout.setContentsMargins(0, 0, 0, 0)

        # 视频设置标题
        video_title = QLabel("视频设置")
        setCustomStyleSheet(
            video_title,
            "font-size: 16px; font-weight: bold; color: #333; margin-bottom: 10px;",
            "font-size: 16px; font-weight: bold; color: #eee; margin-bottom: 10px;"
        )
        video_card_layout.addWidget(video_title)

        # 预览质量
        preview_layout = QHBoxLayout()
        preview_layout.setSpacing(16)
        preview_label = QLabel("预览质量:")
        preview_label.setFixedWidth(80)
        preview_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.preview_combo = QComboBox()
        self.preview_combo.addItems(["低", "中", "高"])
        self.preview_combo.setCurrentText("中")
        setCustomStyleSheet(
            self.preview_combo,
            """QComboBox {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 120px;
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
            }""",
            """QComboBox {
                background-color: #333;
                color: #ddd;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 120px;
            }
            QComboBox:hover {
                border-color: #ff6b8b;
            }
            QComboBox::drop-down {
                border-left: 1px solid #555;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
            }
            QComboBox QAbstractItemView {
                background-color: #333;
                color: #ddd;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px;
            }"""
        )
        preview_layout.addWidget(preview_label)
        preview_layout.addWidget(self.preview_combo)
        preview_layout.addStretch()
        video_card_layout.addLayout(preview_layout)

        # 硬件加速
        hwaccel_layout = QHBoxLayout()
        hwaccel_layout.setSpacing(16)
        hwaccel_label = QLabel("硬件加速:")
        hwaccel_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.hwaccel_check = QCheckBox()
        self.hwaccel_check.setChecked(True)
        setCustomStyleSheet(
            self.hwaccel_check,
            """QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 40px;
                height: 20px;
                border-radius: 10px;
                background-color: #ddd;
            }
            QCheckBox::indicator:checked {
                background-color: #ff6b8b;
            }
            QCheckBox::indicator::text {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                background-color: white;
                margin: 2px;
            }
            QCheckBox::indicator:checked::text {
                margin-left: 22px;
            }""",
            """QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 40px;
                height: 20px;
                border-radius: 10px;
                background-color: #555;
            }
            QCheckBox::indicator:checked {
                background-color: #ff6b8b;
            }
            QCheckBox::indicator::text {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                background-color: white;
                margin: 2px;
            }
            QCheckBox::indicator:checked::text {
                margin-left: 22px;
            }"""
        )
        hwaccel_layout.addWidget(hwaccel_label)
        hwaccel_layout.addWidget(self.hwaccel_check)
        hwaccel_layout.addStretch()
        video_card_layout.addLayout(hwaccel_layout)

        scroll_layout.addWidget(video_card)

        # 导出设置卡片
        export_card = QWidget()
        export_card_layout = QVBoxLayout(export_card)
        setCustomStyleSheet(
            export_card,
            "QWidget { background-color: #f8f9fa; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08); }",
            "QWidget { background-color: #2a2a2a; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3); }"
        )
        export_card_layout.setSpacing(16)
        export_card_layout.setContentsMargins(0, 0, 0, 0)

        # 导出设置标题
        export_title = QLabel("导出设置")
        setCustomStyleSheet(
            export_title,
            "font-size: 16px; font-weight: bold; color: #333; margin-bottom: 10px;",
            "font-size: 16px; font-weight: bold; color: #eee; margin-bottom: 10px;"
        )
        export_card_layout.addWidget(export_title)

        # 导出质量
        export_quality_layout = QHBoxLayout()
        export_quality_layout.setSpacing(16)
        export_quality_label = QLabel("导出质量:")
        export_quality_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.export_quality_combo = QComboBox()
        self.export_quality_combo.addItems(["低", "中", "高"])
        self.export_quality_combo.setCurrentText("高")
        setCustomStyleSheet(
            self.export_quality_combo,
            """QComboBox {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 120px;
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
            }""",
            """QComboBox {
                background-color: #333;
                color: #ddd;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 120px;
            }
            QComboBox:hover {
                border-color: #ff6b8b;
            }
            QComboBox::drop-down {
                border-left: 1px solid #555;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
            }
            QComboBox QAbstractItemView {
                background-color: #333;
                color: #ddd;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px;
            }"""
        )
        export_quality_layout.addWidget(export_quality_label)
        export_quality_layout.addWidget(self.export_quality_combo)
        export_quality_layout.addStretch()
        export_card_layout.addLayout(export_quality_layout)

        # 导出线程数
        export_thread_layout = QHBoxLayout()
        export_thread_layout.setSpacing(16)
        export_thread_label = QLabel("导出线程数:")
        export_thread_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.export_thread_spin = QSpinBox()
        self.export_thread_spin.setRange(1, 8)
        self.export_thread_spin.setValue(4)
        setCustomStyleSheet(
            self.export_thread_spin,
            """QSpinBox {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 8px 12px;
            }
            QSpinBox:hover {
                border-color: #ff6b8b;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                width: 24px;
                height: 24px;
                border-radius: 4px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #f0f0f0;
            }""",
            """QSpinBox {
                background-color: #333;
                color: #ddd;
                border: 1px solid #555;
                border-radius: 8px;
                padding: 8px 12px;
            }
            QSpinBox:hover {
                border-color: #ff6b8b;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                width: 24px;
                height: 24px;
                border-radius: 4px;
                background-color: #444;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #555;
            }"""
        )
        export_thread_layout.addWidget(export_thread_label)
        export_thread_layout.addWidget(self.export_thread_spin)
        export_thread_layout.addStretch()
        export_card_layout.addLayout(export_thread_layout)

        scroll_layout.addWidget(export_card)

        # 网络设置卡片
        network_card = QWidget()
        network_card_layout = QVBoxLayout(network_card)
        setCustomStyleSheet(
            network_card,
            "QWidget { background-color: #f8f9fa; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08); }",
            "QWidget { background-color: #2a2a2a; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3); }"
        )
        network_card_layout.setSpacing(16)
        network_card_layout.setContentsMargins(0, 0, 0, 0)

        # 网络设置标题
        network_title = QLabel("网络设置")
        setCustomStyleSheet(
            network_title,
            "font-size: 16px; font-weight: bold; color: #333; margin-bottom: 10px;",
            "font-size: 16px; font-weight: bold; color: #eee; margin-bottom: 10px;"
        )
        network_card_layout.addWidget(network_title)

        # GitHub 加速
        github_layout = QHBoxLayout()
        github_layout.setSpacing(16)
        github_label = QLabel("GitHub 加速:")
        github_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.github_accel_check = QCheckBox()
        self.github_accel_check.setChecked(True)
        setCustomStyleSheet(
            self.github_accel_check,
            """QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 40px;
                height: 20px;
                border-radius: 10px;
                background-color: #ddd;
            }
            QCheckBox::indicator:checked {
                background-color: #ff6b8b;
            }
            QCheckBox::indicator::text {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                background-color: white;
                margin: 2px;
            }
            QCheckBox::indicator:checked::text {
                margin-left: 22px;
            }""",
            """QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 40px;
                height: 20px;
                border-radius: 10px;
                background-color: #555;
            }
            QCheckBox::indicator:checked {
                background-color: #ff6b8b;
            }
            QCheckBox::indicator::text {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                background-color: white;
                margin: 2px;
            }
            QCheckBox::indicator:checked::text {
                margin-left: 22px;
            }"""
        )
        github_layout.addWidget(github_label)
        github_layout.addWidget(self.github_accel_check)
        github_layout.addStretch()
        network_card_layout.addLayout(github_layout)

        # 代理设置
        proxy_layout = QHBoxLayout()
        proxy_layout.setSpacing(16)
        proxy_label = QLabel("使用代理:")
        proxy_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.proxy_check = QCheckBox()
        self.proxy_check.setChecked(False)
        setCustomStyleSheet(
            self.proxy_check,
            """QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 40px;
                height: 20px;
                border-radius: 10px;
                background-color: #ddd;
            }
            QCheckBox::indicator:checked {
                background-color: #ff6b8b;
            }
            QCheckBox::indicator::text {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                background-color: white;
                margin: 2px;
            }
            QCheckBox::indicator:checked::text {
                margin-left: 22px;
            }""",
            """QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 40px;
                height: 20px;
                border-radius: 10px;
                background-color: #555;
            }
            QCheckBox::indicator:checked {
                background-color: #ff6b8b;
            }
            QCheckBox::indicator::text {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                background-color: white;
                margin: 2px;
            }
            QCheckBox::indicator:checked::text {
                margin-left: 22px;
            }"""
        )
        proxy_layout.addWidget(proxy_label)
        proxy_layout.addWidget(self.proxy_check)
        proxy_layout.addStretch()
        network_card_layout.addLayout(proxy_layout)

        scroll_layout.addWidget(network_card)

        # 关于卡片
        about_card = QWidget()
        about_card_layout = QVBoxLayout(about_card)
        setCustomStyleSheet(
            about_card,
            "QWidget { background-color: #f8f9fa; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08); }",
            "QWidget { background-color: #2a2a2a; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3); }"
        )
        about_card_layout.setSpacing(16)
        about_card_layout.setContentsMargins(0, 0, 0, 0)

        # 关于标题
        about_title = QLabel("关于")
        setCustomStyleSheet(
            about_title,
            "font-size: 16px; font-weight: bold; color: #333; margin-bottom: 10px;",
            "font-size: 16px; font-weight: bold; color: #eee; margin-bottom: 10px;"
        )
        about_card_layout.addWidget(about_title)

        about_info = QLabel(
            f"{APP_NAME} v{APP_VERSION}\n\n明日方舟通行证素材制作器\n作者: Rafael_ban & 初微弦音 & 涙不在为你而流\n\n© 2026 罗德岛工程部")
        about_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        setCustomStyleSheet(
            about_info,
            "padding: 10px; color: #666;",
            "padding: 10px; color: #aaa;"
        )
        about_card_layout.addWidget(about_info)

        # 检查更新按钮
        check_update_button = PrimaryPushButton("检查更新")
        check_update_button.clicked.connect(self._on_check_update)
        about_card_layout.addWidget(
            check_update_button,
            alignment=Qt.AlignmentFlag.AlignCenter)

        scroll_layout.addWidget(about_card)

        # 保存按钮
        save_button = PrimaryPushButton("保存设置")
        save_button.clicked.connect(self._on_save_settings)
        scroll_layout.addWidget(
            save_button, alignment=Qt.AlignmentFlag.AlignCenter)

        # 立即应用设置的提示
        apply_tip = QLabel("* 设置更改会立即生效")
        setCustomStyleSheet(
            apply_tip,
            "color: #999; font-size: 12px;",
            "color: #888; font-size: 12px;"
        )
        scroll_layout.addWidget(
            apply_tip, alignment=Qt.AlignmentFlag.AlignCenter)

        scroll_layout.addStretch()

        # 设置滚动区域
        scroll_area.setWidget(scroll_content)
        scroll_area.setWidgetResizable(True)

        # 添加滚动区域到主布局
        settings_layout.addWidget(scroll_area)

        # 添加到内容布局
        self.content_layout.addWidget(self._settings_widget)

        # 加载用户设置到界面控件
        self._load_user_settings()

        # 连接设置控件的信号，实现立即生效
        self._connect_settings_signals()

        # 显示设置视图
        if hasattr(self, '_settings_widget'):
            self._settings_widget.setVisible(True)

        self.status_bar.showMessage("设置模式")

    def _on_nav_file(self):
        """顶部导航：文件"""
        # 实现文件菜单功能
        from PyQt6.QtWidgets import QMenu, QMessageBox
        from PyQt6.QtGui import QAction

        try:
            # 创建文件菜单
            file_menu = QMenu(self)

            # 新建项目
            new_action = QAction("新建项目", self)
            new_action.triggered.connect(self._on_new_project)
            file_menu.addAction(new_action)

            # 打开项目
            open_action = QAction("打开项目", self)
            open_action.triggered.connect(self._on_open_project)
            file_menu.addAction(open_action)

            # 保存项目
            save_action = QAction("保存项目", self)
            save_action.triggered.connect(self._on_save_project)
            file_menu.addAction(save_action)

            # 另存为
            save_as_action = QAction("另存为", self)
            save_as_action.triggered.connect(self._on_save_as)
            file_menu.addAction(save_as_action)

            # 显示菜单
            pos = self.btn_nav_file.mapToGlobal(
                self.btn_nav_file.rect().bottomLeft())
            file_menu.exec(pos)
        except Exception as e:
            logger.error(f"文件菜单错误: {e}")
            show_error(e, "文件菜单", self)

    def _on_nav_basic(self):
        """顶部导航：基础设置"""
        try:
            # 切换到素材制作模式
            self._on_sidebar_material()

            # 显示简化的基础设置界面
            if hasattr(
                    self,
                    'advanced_config_panel') and hasattr(
                    self,
                    'basic_config_panel'):
                self.advanced_config_panel.setVisible(False)
                self.basic_config_panel.setVisible(True)
                self.status_bar.showMessage("基础设置模式 - 简化界面")

            # 基础模式下，只显示循环视频标签页
            if hasattr(self, 'preview_tabs'):
                # 隐藏不需要的标签页
                for i in [0, 1, 2]:  # 0:入场视频, 1:截取帧编辑, 2:过渡图片
                    if i < self.preview_tabs.count():
                        self.preview_tabs.setTabVisible(i, False)
                # 显示循环视频标签页
                if 3 < self.preview_tabs.count():
                    self.preview_tabs.setTabVisible(3, True)
                # 切换到循环视频标签页
                self.preview_tabs.setCurrentIndex(3)
        except Exception as e:
            logger.error(f"基础设置切换错误: {e}")

    def _on_nav_advanced(self):
        """顶部导航：高级设置"""
        try:
            # 切换到素材制作模式
            self._on_sidebar_material()

            # 显示完整的高级设置界面
            if hasattr(
                    self,
                    'advanced_config_panel') and hasattr(
                    self,
                    'basic_config_panel'):
                self.advanced_config_panel.setVisible(True)
                self.basic_config_panel.setVisible(False)
                self.status_bar.showMessage("高级设置模式 - 完整界面")

            # 高级模式下，显示所有标签页
            if hasattr(self, 'preview_tabs'):
                for i in range(self.preview_tabs.count()):
                    self.preview_tabs.setTabVisible(i, True)
        except Exception as e:
            logger.error(f"高级设置切换错误: {e}")

    def _on_nav_help(self):
        """顶部导航：帮助"""
        # 实现帮助菜单功能
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction

        try:
            # 创建帮助菜单
            help_menu = QMenu(self)

            # 快捷键帮助
            shortcuts_action = QAction("快捷键帮助", self)
            shortcuts_action.triggered.connect(self._on_shortcuts)
            help_menu.addAction(shortcuts_action)

            # 检查更新
            update_action = QAction("检查更新", self)
            update_action.triggered.connect(self._on_check_update)
            help_menu.addAction(update_action)

            # 关于
            about_action = QAction("关于", self)
            about_action.triggered.connect(self._on_about)
            help_menu.addAction(about_action)

            # 显示菜单
            pos = self.btn_nav_help.mapToGlobal(
                self.btn_nav_help.rect().bottomLeft())
            help_menu.exec(pos)
        except Exception as e:
            logger.error(f"帮助菜单错误: {e}")
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "错误", f"帮助菜单加载失败: {str(e)}")

    def _open_color_dialog(self):
        """打开颜色选择器"""
        from PyQt6.QtWidgets import QColorDialog
        from PyQt6.QtGui import QColor

        # 获取当前按钮的背景颜色
        current_style = self.color_button.styleSheet()
        current_color = "#ff6b8b"  # 默认颜色
        if "background-color: " in current_style:
            start = current_style.find(
                "background-color: ") + len("background-color: ")
            # 先尝试查找 "; "（分号加空格）
            end = current_style.find("; ", start)
            # 如果没找到，尝试只查找 ";"（分号）
            if end <= start:
                end = current_style.find(";", start)
            if end > start:
                current_color = current_style[start:end].strip()

        # 打开颜色选择器
        color = QColorDialog.getColor(QColor(current_color), self, "选择主题颜色")
        if color.isValid():
            color_hex = color.name()
            self.color_button.setStyleSheet(
                f"background-color: {color_hex}; border: 1px solid #ddd; border-radius: 4px;")
            # 自动切换到自定义主题
            self.theme_combo.setCurrentText("自定义")

            # 立即应用主题颜色设置
            try:
                import json
                config_dir = os.path.join(
                    os.path.dirname(__file__), "..", "config")
                config_file = os.path.join(config_dir, "user_settings.json")

                settings = {}
                if os.path.exists(config_file):
                    with open(config_file, "r", encoding="utf-8") as f:
                        settings = json.load(f)

                settings['theme_color'] = color_hex
                settings['theme'] = "自定义"

                os.makedirs(config_dir, exist_ok=True)
                with open(config_file, "w", encoding="utf-8") as f:
                    json.dump(settings, f, ensure_ascii=False, indent=2)

                # 立即应用主题颜色到界面
                self._apply_theme_color(color_hex)

                self.status_bar.showMessage(f"主题颜色已应用: {color_hex}")
                logger.info(f"主题颜色已更改为并应用: {color_hex}")
            except Exception as e:
                logger.error(f"应用主题颜色失败: {e}")
                self.status_bar.showMessage(f"应用主题颜色失败: {str(e)}")

    def _on_save_settings(self):
        """保存设置"""
        logger.info("开始保存设置...")
        try:
            # 收集设置
            logger.info("收集设置...")
            # 获取主题颜色
            theme_color = "#ff6b8b"  # 默认颜色
            if hasattr(self, 'color_button'):
                current_style = self.color_button.styleSheet()
                if "background-color: " in current_style:
                    start = current_style.find(
                        "background-color: ") + len("background-color: ")
                    end = current_style.find(";", start)
                    if end > start:
                        theme_color = current_style[start:end].strip()

            # 获取主题图片
            theme_image = ""
            if hasattr(self, 'image_path_label'):
                # 这里我们需要从设置中获取主题图片路径，而不是从标签中
                # 因为标签中只显示文件名，不显示完整路径
                # 所以我们需要从配置文件中读取
                try:
                    import json
                    config_dir = os.path.join(
                        os.path.dirname(__file__), "..", "config")
                    config_file = os.path.join(
                        config_dir, "user_settings.json")
                    if os.path.exists(config_file):
                        with open(config_file, "r", encoding="utf-8") as f:
                            existing_settings = json.load(f)
                            theme_image = existing_settings.get(
                                'theme_image', '')
                except Exception:
                    pass

            settings = {
                "auto_update": self.auto_update_check.isChecked(),
                "update_freq": self.update_freq_combo.currentText(),
                "font_size": self.font_size_combo.currentText(),
                "theme": self.theme_combo.currentText(),
                "theme_color": theme_color,
                "theme_image": theme_image,
                "scale": self.scale_spin.value(),
                "language": self.lang_combo.currentText(),
                "auto_create_temp_project": self.temp_project_check.isChecked(),
                "show_welcome_dialog": self.welcome_check.isChecked(),
                "show_status_bar": self.status_check.isChecked(),
                "auto_save": self.autosave_check.isChecked(),
                "preview_quality": self.preview_combo.currentText(),
                "hardware_acceleration": self.hwaccel_check.isChecked(),
                "export_quality": self.export_quality_combo.currentText(),
                "export_threads": self.export_thread_spin.value(),
                "github_acceleration": self.github_accel_check.isChecked(),
                "use_proxy": self.proxy_check.isChecked()}

            # 保存到配置文件
            logger.info("保存到配置文件...")
            import json
            config_dir = os.path.join(
                os.path.dirname(__file__), "..", "config")
            os.makedirs(config_dir, exist_ok=True)
            config_file = os.path.join(config_dir, "user_settings.json")
            logger.info(f"配置文件路径: {config_file}")

            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)

            # 显示保存成功消息
            logger.info("设置已保存")
            self.status_bar.showMessage("设置已保存")

            # 记录日志
            logger.info("设置已保存")

        except Exception as e:
            # 显示保存失败消息
            logger.error(f"保存设置失败: {e}")
            self.status_bar.showMessage(f"保存设置失败: {str(e)}")
            logger.error(f"保存设置失败: {e}")

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
        auto_check_enabled = settings.value(
            "auto_check_updates", True, type=bool)

        # 从用户设置文件中获取自动更新设置
        try:
            import json
            config_dir = os.path.join(
                os.path.dirname(__file__), "..", "config")
            config_file = os.path.join(config_dir, "user_settings.json")
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    user_settings = json.load(f)
                    auto_check_enabled = user_settings.get('auto_update', True)
        except Exception:
            pass

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
        self._startup_update_service.check_completed.connect(
            self._on_startup_update_check_completed)
        self._startup_update_service.check_failed.connect(
            self._on_startup_update_check_failed)
        self._startup_update_service.check_for_updates()

        # 记录检查时间
        settings.setValue("last_update_check", datetime.now().isoformat())

    def _check_crash_recovery(self):
        """启动时检查崩溃恢复"""
        try:
            # 检查是否有可恢复的项目
            recovery_list = self._crash_recovery_service.check_crash_recovery()

            if not recovery_list:
                logger.info("没有发现可恢复的项目")
                return

            # 显示崩溃恢复对话框
            from gui.dialogs.crash_recovery_dialog import CrashRecoveryDialog

            dialog = CrashRecoveryDialog(self._crash_recovery_service, self)
            dialog.recovery_requested.connect(self._on_recovery_requested)

            result = dialog.exec()

            if result == QDialog.DialogCode.Accepted:
                logger.info("崩溃恢复对话框已关闭")

        except Exception as e:
            logger.error(f"检查崩溃恢复失败: {e}")

    def _on_recovery_requested(self, recovery_info, target_path):
        """恢复项目请求"""
        try:
            # 打开恢复的项目
            self._load_project(target_path)

            # 清理旧的恢复信息
            self._crash_recovery_service.cleanup_old_recoveries(
                max_age_hours=24)

            logger.info(f"项目已恢复: {target_path}")

        except Exception as e:
            logger.error(f"恢复项目失败: {e}")
            show_error(e, "恢复项目", self)

    def _on_error_occurred(self, error_info):
        """错误发生时的处理"""
        self.status_bar.showMessage(f"错误: {error_info.user_message}", 5000)

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

        # 检查路径是否存在
        import os
        path_exists = os.path.exists(path)
        logger.info(f"路径存在检查: {path_exists}")

        # 尝试使用不同的编码方式检查路径
        try:
            # 尝试使用原始路径
            path_exists_raw = os.path.exists(path)
            logger.info(f"原始路径检查: {path_exists_raw}")

            # 尝试使用 Unicode 路径
            if isinstance(path, str):
                path_exists_unicode = os.path.exists(path)
                logger.info(f"Unicode 路径检查: {path_exists_unicode}")
        except Exception as e:
            logger.error(f"路径检查出错: {e}")

        if path:
            # 即使路径检查失败，也尝试加载文件
            logger.info("尝试加载文件...")
            try:
                # 检查文件类型
                ext = os.path.splitext(path)[1].lower()
                image_extensions = [".jpg", ".jpeg", ".png", ".bmp", ".gif"]

                if ext in image_extensions:
                    # 加载图片
                    logger.info("加载图片文件...")
                    self.video_preview.load_static_image_from_file(path)
                else:
                    # 加载视频
                    logger.info("加载视频文件...")
                    self.video_preview.load_video(path)

                # 无论是否在基础模式下，都将时间轴连接到video_preview
                logger.info("将时间轴连接到video_preview")
                self._connect_timeline_to_preview(self.video_preview)

                # 检查是否在基础模式下
                if hasattr(
                        self,
                        'basic_config_panel') and self.basic_config_panel.isVisible():
                    # 基础模式下，不自动切换标签页，保持在当前标签页
                    logger.info("基础模式下，不自动切换标签页")
                else:
                    # 高级模式下，切换到循环视频标签页
                    self.preview_tabs.setCurrentIndex(3)
            except Exception as e:
                logger.error(f"加载文件出错: {e}")
        else:
            logger.warning(f"视频文件路径为空")

    def _on_intro_video_selected(self, path: str):
        """入场视频文件被选择"""
        logger.info(f"入场视频文件被选择: {path}")
        if path and os.path.exists(path):
            if self.intro_preview.load_video(path):
                # 切换到入场视频标签页
                self.preview_tabs.setCurrentIndex(0)
        else:
            logger.warning(f"入场视频文件不存在: {path}")

    def _connect_settings_signals(self):
        """连接设置控件的信号，实现立即生效"""
        logger.info("连接设置控件信号...")

        # 应用设置信号
        if hasattr(self, 'auto_update_check'):
            self.auto_update_check.stateChanged.connect(
                lambda: self._apply_settings(
                    'auto_update', self.auto_update_check.isChecked()))

        if hasattr(self, 'update_freq_combo'):
            self.update_freq_combo.currentTextChanged.connect(
                lambda text: self._apply_settings('update_freq', text))

        if hasattr(self, 'font_size_combo'):
            self.font_size_combo.currentTextChanged.connect(
                lambda text: self._apply_settings('font_size', text))

        if hasattr(self, 'theme_combo'):
            self.theme_combo.currentTextChanged.connect(
                lambda text: self._apply_settings('theme', text))

        if hasattr(self, 'scale_spin'):
            self.scale_spin.valueChanged.connect(
                lambda value: self._apply_settings('scale', value))

        if hasattr(self, 'lang_combo'):
            self.lang_combo.currentTextChanged.connect(
                lambda text: self._apply_settings('language', text))

        if hasattr(self, 'temp_project_check'):
            self.temp_project_check.stateChanged.connect(
                lambda: self._apply_settings(
                    'auto_create_temp_project',
                    self.temp_project_check.isChecked()))

        if hasattr(self, 'welcome_check'):
            self.welcome_check.stateChanged.connect(
                lambda: self._apply_settings(
                    'show_welcome_dialog',
                    self.welcome_check.isChecked()))

        if hasattr(self, 'status_check'):
            self.status_check.stateChanged.connect(
                lambda: self._apply_settings(
                    'show_status_bar',
                    self.status_check.isChecked()))

        if hasattr(self, 'autosave_check'):
            self.autosave_check.stateChanged.connect(
                lambda: self._apply_settings(
                    'auto_save', self.autosave_check.isChecked()))

        if hasattr(self, 'preview_combo'):
            self.preview_combo.currentTextChanged.connect(
                lambda text: self._apply_settings('preview_quality', text))

        if hasattr(self, 'hwaccel_check'):
            self.hwaccel_check.stateChanged.connect(
                lambda: self._apply_settings(
                    'hardware_acceleration',
                    self.hwaccel_check.isChecked()))

        if hasattr(self, 'export_quality_combo'):
            self.export_quality_combo.currentTextChanged.connect(
                lambda text: self._apply_settings('export_quality', text))

        if hasattr(self, 'export_thread_spin'):
            self.export_thread_spin.valueChanged.connect(
                lambda value: self._apply_settings('export_threads', value))

        if hasattr(self, 'github_accel_check'):
            self.github_accel_check.stateChanged.connect(
                lambda: self._apply_settings(
                    'github_acceleration',
                    self.github_accel_check.isChecked()))

        if hasattr(self, 'proxy_check'):
            self.proxy_check.stateChanged.connect(
                lambda: self._apply_settings(
                    'use_proxy', self.proxy_check.isChecked()))

        logger.info("设置控件信号连接完成")

    def _apply_settings(self, setting_name, value):
        """应用设置，实现立即生效"""
        logger.info(f"应用设置: {setting_name} = {value}")

        try:
            # 读取现有设置
            import json
            config_dir = os.path.join(
                os.path.dirname(__file__), "..", "config")
            config_file = os.path.join(config_dir, "user_settings.json")

            settings = {}
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    settings = json.load(f)

            # 更新设置
            settings[setting_name] = value

            # 特殊处理：主题颜色
            if setting_name == 'theme' and value == '自定义' and hasattr(
                    self, 'color_button'):
                current_style = self.color_button.styleSheet()
                if "background-color: " in current_style:
                    start = current_style.find(
                        "background-color: ") + len("background-color: ")
                    end = current_style.find("; ", start)
                    if end > start:
                        theme_color = current_style[start:end].strip()
                        settings['theme_color'] = theme_color

            # 保存到文件
            os.makedirs(config_dir, exist_ok=True)
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)

            # 应用即时生效的设置
            self._apply_instant_settings(setting_name, value)

            # 显示应用成功消息
            self.status_bar.showMessage(f"设置已应用: {setting_name}")

        except Exception as e:
            logger.error(f"应用设置失败: {e}")
            self.status_bar.showMessage(f"应用设置失败: {str(e)}")

    def _apply_instant_settings(self, setting_name, value):
        """应用即时生效的设置"""
        # 状态栏显示设置
        if setting_name == 'show_status_bar':
            self.statusBar().setVisible(value)

        # 主题设置
        if setting_name == 'theme':
            self._apply_theme_change(value)

        # 字体大小设置
        if setting_name == 'font_size':
            logger.info(f"字体大小已设置为: {value}")

        # 界面缩放设置
        if setting_name == 'scale':
            logger.info(f"界面缩放已设置为: {value}")

        # 其他需要即时生效的设置可以在这里添加

    def _apply_theme_change(self, theme_name):
        """应用主题变化"""
        logger.info(f"应用主题: {theme_name}")

        try:
            import json
            config_dir = os.path.join(
                os.path.dirname(__file__), "..", "config")
            config_file = os.path.join(config_dir, "user_settings.json")

            settings = {}
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    settings = json.load(f)

            # 根据主题名称应用不同的主题
            if theme_name == '默认':
                # 应用默认主题
                self._apply_default_theme()
            elif theme_name == '自定义':
                # 应用自定义主题颜色
                theme_color = settings.get('theme_color', '#ff6b8b')
                self._apply_theme_color(theme_color)
            elif theme_name == '自定义图片':
                # 应用自定义主题颜色（先应用颜色）
                theme_color = settings.get('theme_color', '#ff6b8b')
                self._apply_theme_color(theme_color)
                # 然后应用自定义主题图片
                theme_image = settings.get('theme_image', '')
                if theme_image:
                    self._apply_theme_image(theme_image)

        except Exception as e:
            logger.error(f"应用主题失败: {e}")

    def _apply_default_theme(self):
        """应用默认主题"""
        # 应用默认主题颜色
        self._apply_theme_color('#ff6b8b')

    def _apply_light_theme(self):
        """应用浅色主题"""
        # 应用浅色主题颜色
        self._apply_theme_color('#4CAF50')

    def _apply_dark_theme(self):
        """应用深色主题"""
        # 应用深色主题颜色
        self._apply_theme_color('#2196F3')

    def _apply_theme_color(self, color_hex):
        """应用主题颜色到界面"""
        # 应用主题颜色到标题栏（纯色，与颜色选择器保持一致，添加圆角）
        if hasattr(self, 'header_bar'):
            style = f"QWidget {{ background-color: {color_hex}; color: white; border-bottom-right-radius: 16px; }} QLabel {{ font-weight: bold; font-size: 16px; }}"
            self.header_bar.setStyleSheet(style)
        
        # 应用主题颜色到侧边栏（纯色，与顶部栏保持一致）
        if hasattr(self, 'sidebar'):
            sidebar_style = f"QWidget {{ background-color: {color_hex}; }}"
            self.sidebar.setStyleSheet(sidebar_style)

        # 应用主题颜色到导航按钮（如果存在）
        nav_buttons = [
            'btn_nav_file',
            'btn_nav_basic',
            'btn_nav_advanced',
            'btn_nav_help']
        for btn_name in nav_buttons:
            if hasattr(self, btn_name):
                btn = getattr(self, btn_name)
                style = "QPushButton { background-color: transparent; color: white; border: none; padding: 10px 20px; font-size: 14px; border-radius: 6px; } QPushButton:hover { background-color: rgba(255, 255, 255, 0.2); } QPushButton:pressed, QPushButton:checked { background-color: rgba(255, 255, 255, 0.3); }"
                btn.setStyleSheet(style)

        # 应用主题颜色到侧边栏按钮
        for btn in [
                self.btn_firmware,
                self.btn_material,
                self.btn_market,
                self.btn_settings]:
            style = f"QPushButton {{ background-color: white; color: #333333; border: 1px solid #e9ecef; border-radius: 10px; padding: 14px 20px; text-align: left; font-size: 15px; margin: 8px; }} QPushButton:hover {{ background-color: {color_hex}20; border-color: {color_hex}; }} QPushButton:pressed, QPushButton:checked {{ background-color: {color_hex}; color: white; border-color: {color_hex}; }}"
            btn.setStyleSheet(style)

        logger.info(f"应用主题颜色: {color_hex}")

    def _apply_theme_image(self, image_path):
        """应用主题图片到界面（带有毛玻璃效果）"""
        # 应用主题图片到界面并添加毛玻璃效果
        logger.info(f"应用主题图片: {image_path}")

        # 先加载主题颜色
        theme_color = "#ff6b8b"
        try:
            import json
            config_dir = os.path.join(
                os.path.dirname(__file__), "..", "config")
            config_file = os.path.join(config_dir, "user_settings.json")
            
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                    theme_color = settings.get('theme_color', '#ff6b8b')
        except Exception as e:
            logger.error(f"加载主题颜色失败: {e}")

        # 设置主窗口的背景图片
        try:
            # 检查当前是否为深色模式
            is_dark = isDarkTheme()
            
            # 根据主题模式设置不同的背景颜色
            if is_dark:
                content_bg = "rgba(30, 30, 30, 0.7)"
                status_bg = "rgba(30, 30, 30, 0.7)"
                status_color = "white"
                status_border = "rgba(255, 255, 255, 0.1)"
            else:
                content_bg = "rgba(255, 255, 255, 0.7)"
                status_bg = "rgba(248, 249, 250, 0.7)"
                status_color = "#333"
                status_border = "rgba(0, 0, 0, 0.1)"
            
            # 使用样式表设置背景图片，同时设置header_bar和sidebar使用主题颜色
            style = """
                QMainWindow {
                    background-image: url('%s');
                    background-repeat: no-repeat;
                    background-position: center;
                }

                /* 为了让内容区域可见，我们需要为内容区域设置背景色和透明度 */
                QWidget#content_stack {
                    background-color: %s;
                }

                QWidget#header_bar {
                    background-color: %s;
                    border-bottom-right-radius: 16px;
                }

                QWidget#sidebar {
                    background-color: %s;
                    border-top-right-radius: 0px;
                    border-bottom-right-radius: 16px;
                }

                /* 状态栏样式 */
                QStatusBar {
                    background-color: %s;
                    color: %s;
                    border-top: 1px solid %s;
                }
                
                QStatusBar::item {
                    border: none;
                }
            """

            self.setStyleSheet(style % (image_path, content_bg, theme_color, theme_color, status_bg, status_color, status_border))

            logger.info("主题图片已应用，带有半透明效果")
        except Exception as e:
            logger.error(f"应用主题图片失败: {e}")

    def _open_image_dialog(self):
        """打开图片选择对话框"""
        from PyQt6.QtWidgets import QFileDialog

        # 打开文件选择对话框
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择主题图片", "", "图片文件 (*.jpg *.jpeg *.png *.bmp *.gif)"
        )

        if file_path:
            # 更新图片路径标签
            self.image_path_label.setText(os.path.basename(file_path))

            # 自动切换到自定义图片主题
            self.theme_combo.setCurrentText("自定义图片")

            # 立即应用主题图片设置
            try:
                import json
                config_dir = os.path.join(
                    os.path.dirname(__file__), "..", "config")
                config_file = os.path.join(config_dir, "user_settings.json")

                settings = {}
                if os.path.exists(config_file):
                    with open(config_file, "r", encoding="utf-8") as f:
                        settings = json.load(f)

                settings['theme_image'] = file_path
                settings['theme'] = "自定义图片"

                os.makedirs(config_dir, exist_ok=True)
                with open(config_file, "w", encoding="utf-8") as f:
                    json.dump(settings, f, ensure_ascii=False, indent=2)

                # 立即应用主题图片到界面
                self._apply_theme_image(file_path)

                self.status_bar.showMessage(
                    f"主题图片已应用: {os.path.basename(file_path)}")
                logger.info(f"主题图片已更改为并应用: {file_path}")
            except Exception as e:
                logger.error(f"应用主题图片失败: {e}")
                self.status_bar.showMessage(f"应用主题图片失败: {str(e)}")

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
        self.timeline.goto_start_clicked.connect(
            lambda: preview.seek_to_frame(0))
        self.timeline.goto_end_clicked.connect(
            lambda: preview.seek_to_frame(preview.total_frames - 1)
        )
        self.timeline.rotation_clicked.connect(preview.rotate_clockwise)

        # 记录当前连接的预览器
        self._timeline_preview = preview

        # 更新时间轴显示
        if hasattr(preview, 'total_frames') and preview.total_frames > 0:
            self.timeline.set_total_frames(preview.total_frames)
            if hasattr(preview, 'video_fps'):
                self.timeline.set_fps(preview.video_fps)
            if hasattr(preview, 'current_frame_index'):
                self.timeline.set_current_frame(preview.current_frame_index)
            self.timeline.set_rotation(preview.get_rotation())
            if hasattr(preview, 'is_playing'):
                self.timeline.set_playing(preview.is_playing)

        # 连接帧变更信号
        try:
            preview.frame_changed.disconnect(self._on_video_frame_changed)
        except TypeError:
            pass
        preview.frame_changed.connect(self._on_video_frame_changed)

    def _on_video_frame_changed(self, frame):
        """视频帧变更时更新截取帧编辑页面"""
        # 如果当前在截取帧编辑标签页，自动更新图片
        if self.preview_tabs.currentIndex() == 1 and hasattr(self,
                                                             '_current_video_preview'):
            source_preview = self._current_video_preview
            frame = source_preview.current_frame
            if frame is not None:
                import cv2
                # 应用旋转变换
                frame = frame.copy()
                rotation = source_preview.get_rotation()
                if rotation == 90:
                    frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                elif rotation == 180:
                    frame = cv2.rotate(frame, cv2.ROTATE_180)
                elif rotation == 270:
                    frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
                # 更新截取帧编辑页面的图片
                self.frame_capture_preview.load_static_image_from_array(frame)
                logger.info(
                    f"更新截取帧编辑页面，帧: {
                        source_preview.current_frame_index}")

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
            # 截取帧编辑 - 连接时间轴到保存的视频预览器（如果有）
            if hasattr(
                    self,
                    '_current_video_preview') and self._current_video_preview:
                logger.debug("连接时间轴到保存的视频预览器")
                self._connect_timeline_to_preview(self._current_video_preview)
            else:
                # 如果没有保存的预览器，连接到默认的预览器
                logger.debug("连接时间轴到默认视频预览器")
                self._connect_timeline_to_preview(self.video_preview)
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
        self.status_bar.showMessage(
            f"入场视频已加载: {total_frames} 帧, {
                fps:.1f} FPS")

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
        q_image = QImage(display_img.data, w, h, ch *
                         w, QImage.Format.Format_RGB888)
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
        cropped = original[y:y + h, x:x + w]

        # 缩放到目标分辨率
        target_w, target_h = self._get_target_resolution()
        resized = cv2.resize(cropped, (target_w, target_h),
                             interpolation=cv2.INTER_AREA)

        # 保存为模拟器读取的文件
        out_path = os.path.join(
            self._base_dir,
            f"trans_{trans_type}_image.png")
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
        logger.info("开始截取视频帧")

        if not self._base_dir:
            logger.warning("_base_dir 不存在，显示警告")
            QMessageBox.warning(self, "警告", "请先创建或打开项目")
            return

        # 尝试从当前活跃的视频预览获取帧
        current_tab = self.preview_tabs.currentIndex()
        logger.info(f"当前标签页: {current_tab}")

        if current_tab == 3:
            source_preview = self.video_preview
        else:
            source_preview = self.intro_preview

        logger.info(f"选择视频预览器: {type(source_preview).__name__}")

        frame = source_preview.current_frame
        logger.info(f"当前帧: {frame}")

        if frame is None:
            # 尝试另一个预览
            logger.info("当前帧为 None，尝试另一个预览器")
            other = self.video_preview if source_preview is self.intro_preview else self.intro_preview
            frame = other.current_frame
            logger.info(f"另一个预览器的当前帧: {frame}")
            if other.current_frame is not None:
                source_preview = other
                logger.info(f"切换到另一个预览器: {type(source_preview).__name__}")

        if frame is None:
            logger.warning("所有预览器的当前帧都为 None，显示警告")
            QMessageBox.warning(self, "警告", "请先加载视频")
            return

        import cv2

        # 应用旋转变换（不裁切，交给用户在截取帧编辑标签页中操作）
        frame = frame.copy()
        rotation = source_preview.get_rotation()
        logger.info(f"旋转变换: {rotation}度")

        if rotation == 90:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif rotation == 180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        elif rotation == 270:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

        # 加载到截取帧编辑预览
        logger.info(f"加载到截取帧编辑预览，帧尺寸: {frame.shape}")
        self.frame_capture_preview.load_static_image_from_array(frame)

        # 保存当前的视频预览器引用，用于时间轴控制
        self._current_video_preview = source_preview

        # 连接时间轴到原始的视频预览器，而不是静态图片预览器
        logger.info("连接时间轴到原始视频预览器")
        self._connect_timeline_to_preview(source_preview)

        # 切换到截取帧编辑标签页
        logger.info("切换到截取帧编辑标签页")
        self.preview_tabs.setCurrentIndex(1)

        logger.info("截取视频帧完成")
        self.status_bar.showMessage("已截取视频帧，请调整裁切框后点击\"保存为图标\"")

    def _on_save_captured_icon(self):
        """从截取帧编辑的 cropbox 保存图标"""
        logger.info("开始保存图标")

        if not self._base_dir:
            logger.warning("_base_dir 不存在，显示警告")
            QMessageBox.warning(self, "警告", "请先创建或打开项目")
            return

        frame = self.frame_capture_preview.current_frame
        logger.info(f"当前帧: {frame}")

        if frame is None:
            logger.warning("当前帧为 None，显示警告")
            QMessageBox.warning(self, "警告", "请先截取视频帧")
            return

        try:
            import cv2

            # 获取裁剪框
            cropbox = self.frame_capture_preview.get_cropbox()
            logger.info(f"裁剪框: {cropbox}")

            if len(cropbox) != 4:
                logger.error(f"裁剪框格式错误: {cropbox}")
                QMessageBox.warning(self, "错误", "裁剪框格式错误")
                return

            x, y, w, h = cropbox

            # 边界检查
            frame_h, frame_w = frame.shape[:2]
            logger.info(f"帧尺寸: {frame_w}x{frame_h}")

            x = max(0, min(x, frame_w - 1))
            y = max(0, min(y, frame_h - 1))
            w = min(w, frame_w - x)
            h = min(h, frame_h - y)

            logger.info(f"调整后的裁剪框: x={x}, y={y}, w={w}, h={h}")

            if w <= 0 or h <= 0:
                logger.warning("裁切区域无效")
                QMessageBox.warning(self, "错误", "裁切区域无效")
                return

            # 裁剪帧
            logger.info("开始裁剪帧")
            cropped = frame[y:y + h, x:x + w]
            logger.info(f"裁剪后的尺寸: {cropped.shape}")

            # 保存图标
            icon_path = os.path.join(self._base_dir, "icon.png")
            logger.info(f"保存图标到: {icon_path}")

            success, encoded = cv2.imencode('.png', cropped)
            if success:
                with open(icon_path, 'wb') as f:
                    f.write(encoded.tobytes())
                self.advanced_config_panel.edit_icon.setText("icon.png")
                self.status_bar.showMessage("已保存图标")
                logger.info("图标保存成功")
            else:
                logger.error("保存图标失败")
                QMessageBox.warning(self, "错误", "保存图标失败")

        except Exception as e:
            logger.error(f"保存图标时发生错误: {e}", exc_info=True)
            QMessageBox.critical(self, "错误", f"保存图标时发生错误: {str(e)}")

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
                    data['logo_mat'] = ImageProcessor.process_for_logo(
                        logo_img)

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

            # 停止自动保存服务
            self._auto_save_service.stop()

            # 关闭素材商城服务
            if hasattr(self, '_market_widget'):
                self._market_widget.shutdown()

            event.accept()
        else:
            event.ignore()

    def _on_maximize(self):
        """最大化/还原窗口"""
        if self.isMaximized():
            self.showNormal()
            self.btn_maximize.setText("□")
        else:
            self.showMaximized()
            self.btn_maximize.setText("◱")

    def _on_header_mouse_press(self, event):
        """鼠标按下事件，开始拖动窗口"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self._drag_start_pos = event.globalPosition().toPoint() - \
                self.frameGeometry().topLeft()

    def _on_header_mouse_move(self, event):
        """鼠标移动事件，执行窗口拖动"""
        if self._is_dragging and not self.isMaximized():
            self.move(event.globalPosition().toPoint() - self._drag_start_pos)

    def _on_header_mouse_release(self, event):
        """鼠标释放事件，结束窗口拖动"""
        self._is_dragging = False

    def cursorAtPosition(self, pos):
        """根据鼠标位置返回对应的光标类型和调整方向"""
        rect = self.rect()
        margin = self._resize_margin

        # 检查是否在窗口边缘
        if pos.x() < margin and pos.y() < margin:
            return Qt.CursorShape.SizeFDiagCursor, 'top-left'
        elif pos.x() > rect.width() - margin and pos.y() < margin:
            return Qt.CursorShape.SizeBDiagCursor, 'top-right'
        elif pos.x() < margin and pos.y() > rect.height() - margin:
            return Qt.CursorShape.SizeBDiagCursor, 'bottom-left'
        elif pos.x() > rect.width() - margin and pos.y() > rect.height() - margin:
            return Qt.CursorShape.SizeFDiagCursor, 'bottom-right'
        elif pos.x() < margin:
            return Qt.CursorShape.SizeHorCursor, 'left'
        elif pos.x() > rect.width() - margin:
            return Qt.CursorShape.SizeHorCursor, 'right'
        elif pos.y() < margin:
            return Qt.CursorShape.SizeVerCursor, 'top'
        elif pos.y() > rect.height() - margin:
            return Qt.CursorShape.SizeVerCursor, 'bottom'
        else:
            return Qt.CursorShape.ArrowCursor, None

    def mousePressEvent(self, event):
        """鼠标按下事件，开始调整窗口大小"""
        if event.button() == Qt.MouseButton.LeftButton:
            # 检查是否在窗口边缘
            cursor, direction = self.cursorAtPosition(event.pos())
            if direction:
                self._is_resizing = True
                self._resize_direction = direction
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geometry = self.geometry()

    def mouseMoveEvent(self, event):
        """鼠标移动事件，执行窗口大小调整或更新光标"""
        # 如果正在调整大小
        if self._is_resizing:
            delta = event.globalPosition().toPoint() - self._resize_start_pos
            geometry = self._resize_start_geometry

            if self._resize_direction == 'top-left':
                new_width = geometry.width() - delta.x()
                new_height = geometry.height() - delta.y()
                new_x = geometry.x() + delta.x()
                new_y = geometry.y() + delta.y()
                if new_width >= self.minimumWidth() and new_height >= self.minimumHeight():
                    self.setGeometry(new_x, new_y, new_width, new_height)
            elif self._resize_direction == 'top-right':
                new_width = geometry.width() + delta.x()
                new_height = geometry.height() - delta.y()
                new_y = geometry.y() + delta.y()
                if new_width >= self.minimumWidth() and new_height >= self.minimumHeight():
                    self.setGeometry(
                        geometry.x(), new_y, new_width, new_height)
            elif self._resize_direction == 'bottom-left':
                new_width = geometry.width() - delta.x()
                new_height = geometry.height() + delta.y()
                new_x = geometry.x() + delta.x()
                if new_width >= self.minimumWidth() and new_height >= self.minimumHeight():
                    self.setGeometry(
                        new_x, geometry.y(), new_width, new_height)
            elif self._resize_direction == 'bottom-right':
                new_width = geometry.width() + delta.x()
                new_height = geometry.height() + delta.y()
                if new_width >= self.minimumWidth() and new_height >= self.minimumHeight():
                    self.setGeometry(
                        geometry.x(), geometry.y(), new_width, new_height)
            elif self._resize_direction == 'left':
                new_width = geometry.width() - delta.x()
                new_x = geometry.x() + delta.x()
                if new_width >= self.minimumWidth():
                    self.setGeometry(
                        new_x, geometry.y(), new_width, geometry.height())
            elif self._resize_direction == 'right':
                new_width = geometry.width() + delta.x()
                if new_width >= self.minimumWidth():
                    self.setGeometry(
                        geometry.x(),
                        geometry.y(),
                        new_width,
                        geometry.height())
            elif self._resize_direction == 'top':
                new_height = geometry.height() - delta.y()
                new_y = geometry.y() + delta.y()
                if new_height >= self.minimumHeight():
                    self.setGeometry(
                        geometry.x(), new_y, geometry.width(), new_height)
            elif self._resize_direction == 'bottom':
                new_height = geometry.height() + delta.y()
                if new_height >= self.minimumHeight():
                    self.setGeometry(
                        geometry.x(),
                        geometry.y(),
                        geometry.width(),
                        new_height)
        else:
            # 更新光标类型
            cursor, _ = self.cursorAtPosition(event.pos())
            self.setCursor(cursor)

    def mouseReleaseEvent(self, event):
        """鼠标释放事件，结束窗口大小调整"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_resizing = False
            self._resize_direction = None
