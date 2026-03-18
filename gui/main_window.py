#超 级 多 的 屎 山 ciallo~ 啊哈哈.....
#我就是那个大笨蛋....啊哈哈哈....
#呜呜呜....果然还是被抛弃了嘛....啊哈哈哈....
"""
主窗口 - 三栏布局
"""
from core.error_handler import ErrorHandler, show_error
from core.crash_recovery_service import CrashRecoveryService
from core.auto_save_service import AutoSaveService, AutoSaveConfig
from gui.widgets.json_preview import JsonPreviewWidget
from gui.widgets.timeline import TimelineWidget
from gui.widgets.transition_preview import TransitionPreviewWidget
from gui.widgets.video_preview import VideoPreviewWidget
from gui.widgets.config_panel import ConfigPanel
from config.constants import (
    APP_NAME, APP_VERSION, get_resolution_spec,
    SUPPORTED_VIDEO_FORMATS, SUPPORTED_IMAGE_FORMATS
)
from gui.widgets.drop_overlay import DropOverlayWidget
from gui.styles import COLOR_TEXT_PRIMARY, COLOR_BG_ELEVATED, COLOR_BORDER
from config.epconfig import EPConfig, CONFIG_FILENAME
from qfluentwidgets import (
    PushButton, PrimaryPushButton, ToolButton,
    TabWidget, SegmentedWidget,
    SubtitleLabel,
    ComboBox, SpinBox,
    DoubleSpinBox, CheckBox, LineEdit,
    ScrollArea, FluentIcon,
    setCustomStyleSheet, isDarkTheme
)
from PyQt6.QtGui import QAction, QKeySequence, QIcon, QShortcut
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QMenuBar, QMenu, QStatusBar,
    QFileDialog, QMessageBox, QLabel, QScrollArea,
    QGroupBox, QCheckBox, QComboBox, QDoubleSpinBox,
    QSpinBox, QLineEdit, QTabWidget, QDialog
)
from PyQt6.QtCore import Qt, QSettings, QTimer, QUrl, QCoreApplication
import os
import sys
import logging
import tempfile
import shutil
from typing import Optional

logger = logging.getLogger(__name__)

QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self, parent=None):
        super().__init__(parent)

        from utils.file_utils import get_app_dir
        self._app_dir = get_app_dir()

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

        self._auto_save_service = AutoSaveService()
        self._crash_recovery_service = CrashRecoveryService()
        self._crash_recovery_service.initialize(
            os.path.join(self._app_dir, ".recovery"))

        self._error_handler = ErrorHandler()
        self._error_handler.error_occurred.connect(self._on_error_occurred)

        self._undo_stack = []
        self._redo_stack = []
        self._max_history = 50  # 最大历史记录数

        self._recent_files = []
        self._max_recent_files = 10  # 最多保留10个最近文件

        # 页面切换时记录正在播放的视频预览器，以便返回素材页时恢复
        self._videos_were_playing: list = []

        self._setup_ui()
        self._setup_menu()
        self._setup_shortcuts()
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
            config_dir = os.path.join(self._app_dir, "config")
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

        QTimer.singleShot(2000, self._check_update_on_startup)
        QTimer.singleShot(3000, self._check_crash_recovery)

        logger.info("主窗口初始化完成")
        self._initializing = False  # 初始化完成

        # QSS 热重载（QSS_DEV=1 时激活）
        from gui.qss_hot_reload import QSSHotReloader
        self._qss_reloader = QSSHotReloader.try_attach(self)

    def _setup_icon(self):
        """设置窗口图标"""
        icon_path = os.path.join(
            self._app_dir,
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
        self.menuBar().setVisible(False)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowMinMaxButtonsHint | Qt.WindowType.WindowCloseButtonHint)
        # 启用透明背景 — CSS border-radius 仅影响绘制不裁剪窗口形状，
        # 必须配合 WA_TranslucentBackground + paintEvent 实现真正的圆角裁剪
        # https://doc.qt.io/qt-6/qt.html#WidgetAttribute-enum
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._light_bg_color = "#f0f4f9"
        self._dark_bg_color = "#202020"
        self._bg_color = self._dark_bg_color if isDarkTheme() else self._light_bg_color
        self._bg_pixmap = None
        self._corner_radius = 16.0
        self._is_dragging = False
        self._drag_start_pos = None
        self._is_resizing = False
        self._resize_direction = None
        self._resize_start_pos = None
        self._resize_start_geometry = None
        self._resize_margin = 8

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # === 顶部标题栏 ===
        self.header_bar = QWidget()
        self.header_bar.setObjectName("header_bar")
        _header_default_qss = "QWidget { background-color: rgba(40, 40, 40, 0.7); color: white; border-top-left-radius: 16px; border-top-right-radius: 16px; } QLabel { font-weight: bold; font-size: 16px; }"
        setCustomStyleSheet(self.header_bar, _header_default_qss, _header_default_qss)
        header_layout = QHBoxLayout(self.header_bar)
        header_layout.setContentsMargins(20, 8, 20, 8)
        header_layout.setSpacing(24)

        logo_label = QLabel("PRTS")
        _logo_qss = "QLabel { background-color: white; color: #ff6b8b; border-radius: 16px; padding: 8px 12px; font-size: 14px; font-weight: bold; }"
        setCustomStyleSheet(logo_label, _logo_qss, _logo_qss)
        header_layout.addWidget(logo_label)

        title_label = QLabel(APP_NAME)
        setCustomStyleSheet(title_label, "font-size: 16px; font-weight: bold;", "font-size: 16px; font-weight: bold;")
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        control_layout = QHBoxLayout()
        control_layout.setSpacing(5)

        # 窗口控制按钮通用样式（始终在主题色 header 上，文字白色）
        _ctrl_btn_qss = "QPushButton { background-color: transparent; color: white; border: none; border-radius: 18px; font-size: 20px; font-weight: bold; padding: 0; margin: 0; } QPushButton:hover { background-color: rgba(255, 255, 255, 0.2); } QPushButton:pressed { background-color: rgba(255, 255, 255, 0.3); }"
        _max_btn_qss = "QPushButton { background-color: transparent; color: white; border: none; border-radius: 18px; font-size: 16px; font-weight: bold; padding: 0; margin: 0; } QPushButton:hover { background-color: rgba(255, 255, 255, 0.2); } QPushButton:pressed { background-color: rgba(255, 255, 255, 0.3); }"
        _close_btn_qss = "QPushButton { background-color: transparent; color: white; border: none; border-radius: 18px; font-size: 20px; font-weight: bold; padding: 0; margin: 0; } QPushButton:hover { background-color: rgba(255, 0, 0, 0.3); color: white; } QPushButton:pressed { background-color: rgba(255, 0, 0, 0.4); }"

        self.btn_minimize = PushButton("−")
        self.btn_minimize.setFixedSize(36, 36)
        setCustomStyleSheet(self.btn_minimize, _ctrl_btn_qss, _ctrl_btn_qss)
        self.btn_minimize.clicked.connect(self.showMinimized)
        control_layout.addWidget(self.btn_minimize)

        self.btn_maximize = PushButton("□")
        self.btn_maximize.setFixedSize(36, 36)
        setCustomStyleSheet(self.btn_maximize, _max_btn_qss, _max_btn_qss)
        self.btn_maximize.clicked.connect(self._on_maximize)
        control_layout.addWidget(self.btn_maximize)

        self.btn_close = PushButton("×")
        self.btn_close.setFixedSize(36, 36)
        setCustomStyleSheet(self.btn_close, _close_btn_qss, _close_btn_qss)
        self.btn_close.clicked.connect(self.close)
        control_layout.addWidget(self.btn_close)

        header_layout.addLayout(control_layout)

        self.header_bar.setMouseTracking(True)
        self.header_bar.mousePressEvent = self._on_header_mouse_press
        self.header_bar.mouseMoveEvent = self._on_header_mouse_move
        self.header_bar.mouseReleaseEvent = self._on_header_mouse_release

        main_layout.addWidget(self.header_bar)

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

        self.btn_firmware = ToolButton(FluentIcon.ROBOT, self.sidebar)
        self.btn_firmware.setCheckable(True)
        self.btn_firmware.setToolTip("固件烧录")
        self.btn_firmware.setFixedSize(50, 50)

        self.btn_material = ToolButton(FluentIcon.PALETTE, self.sidebar)
        self.btn_material.setCheckable(True)
        self.btn_material.setChecked(True)
        self.btn_material.setToolTip("素材制作")
        self.btn_material.setFixedSize(50, 50)

        self.btn_forum = ToolButton(FluentIcon.PEOPLE if hasattr(FluentIcon, 'PEOPLE') else FluentIcon.CHAT, self.sidebar)
        self.btn_forum.setCheckable(True)
        self.btn_forum.setToolTip("素材论坛")
        self.btn_forum.setFixedSize(50, 50)

        self.btn_about = ToolButton(FluentIcon.INFO, self.sidebar)
        self.btn_about.setCheckable(True)
        self.btn_about.setToolTip("项目介绍")
        self.btn_about.setFixedSize(50, 50)

        self.btn_remote = ToolButton(FluentIcon.WIFI, self.sidebar)
        self.btn_remote.setCheckable(True)
        self.btn_remote.setToolTip("远程管理")
        self.btn_remote.setFixedSize(50, 50)

        buttons_container = QWidget()
        buttons_layout = QVBoxLayout(buttons_container)
        buttons_layout.setContentsMargins(0, 20, 0, 0)
        buttons_layout.setSpacing(15)
        buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        buttons_layout.addWidget(self.btn_firmware)
        buttons_layout.addWidget(self.btn_material)
        buttons_layout.addWidget(self.btn_forum)
        buttons_layout.addWidget(self.btn_about)
        buttons_layout.addWidget(self.btn_remote)

        sidebar_layout.addWidget(buttons_container)
        sidebar_layout.addStretch()

        self.btn_settings = ToolButton(FluentIcon.SETTING, self.sidebar)
        self.btn_settings.setCheckable(True)
        self.btn_settings.setToolTip("设置")
        self.btn_settings.setFixedSize(50, 50)
        sidebar_layout.addWidget(
            self.btn_settings,
            alignment=Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addSpacing(20)

        self.sidebar.setFixedWidth(80)
        content_layout.addWidget(self.sidebar)

        # === 右侧: 内容区域 ===
        self.content_stack = QWidget()
        self.content_stack.setObjectName("content_stack")
        self.content_layout = QVBoxLayout(self.content_stack)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        # === 左侧: 配置面板 ===
        from gui.widgets.basic_config_panel import BasicConfigPanel

        self.config_container = QWidget()
        self.config_layout = QVBoxLayout(self.config_container)

        from qfluentwidgets import (
            ComboBox as FluentComboBox,
            DropDownPushButton, RoundMenu, Action
        )

        toolbar_layout = QHBoxLayout()
        toolbar_layout.setContentsMargins(10, 10, 10, 4)
        toolbar_layout.setSpacing(8)

        self.btn_operations = DropDownPushButton(FluentIcon.MENU, "操作")
        self.btn_operations.setFixedHeight(34)

        operations_menu = RoundMenu(parent=self)
        # Ensure the menu is wide enough so long shortcut labels aren't truncated
        operations_menu.setFixedWidth(500)

        operations_menu.addAction(
            Action(
                FluentIcon.DOCUMENT,
                "新建项目",
                shortcut="Ctrl+N",
                triggered=self._on_new_project
            )
        )
        operations_menu.addAction(
            Action(
                FluentIcon.FOLDER,
                "打开项目",
                shortcut="Ctrl+O",
                triggered=self._on_open_project
            )
        )
        operations_menu.addAction(
            Action(
                FluentIcon.SAVE,
                "保存",
                shortcut="Ctrl+S",
                triggered=self._on_save_project
            )
        )
        operations_menu.addAction(
            Action(
                FluentIcon.SAVE_AS,
                "另存为",
                shortcut="Ctrl+Shift+S",
                triggered=self._on_save_as
            )
        )

        operations_menu.addSeparator()

        self.menu_action_undo = Action(
            FluentIcon.RETURN,
            "撤销",
            shortcut="Ctrl+Z",
            triggered=self._on_undo
        )
        self.menu_action_undo.setEnabled(False)
        operations_menu.addAction(self.menu_action_undo)

        self.menu_action_redo = Action(
            FluentIcon.RIGHT_ARROW,
            "重做",
            shortcut="Ctrl+Shift+Z",
            triggered=self._on_redo
        )
        self.menu_action_redo.setEnabled(False)
        operations_menu.addAction(self.menu_action_redo)
        operations_menu.addSeparator()

        operations_menu.addAction(
            Action(
                FluentIcon.HELP,
                "快捷键帮助",
                shortcut="F1",
                triggered=self._on_shortcuts
            )
        )
        operations_menu.addSeparator()

        operations_menu.addAction(
            Action(
                FluentIcon.POWER_BUTTON,
                "退出",
                shortcut="Ctrl+Q",
                triggered=self.close
            )
        )
        self.btn_operations.setMenu(operations_menu)
        toolbar_layout.addWidget(self.btn_operations)

        self.settings_mode_combo = FluentComboBox()
        self.settings_mode_combo.addItem("基础设置", userData="basic")
        self.settings_mode_combo.addItem("高级设置", userData="advanced")
        self.settings_mode_combo.setFixedHeight(34)
        self.settings_mode_combo.currentIndexChanged.connect(
            self._on_settings_mode_combo_changed)
        toolbar_layout.addWidget(self.settings_mode_combo)

        toolbar_layout.addStretch()
        self.config_layout.addLayout(toolbar_layout)

        self.advanced_config_panel = ConfigPanel()
        self.basic_config_panel = BasicConfigPanel()

        self.config_layout.addWidget(self.advanced_config_panel)
        self.config_layout.addWidget(self.basic_config_panel)
        self.advanced_config_panel.setVisible(False)
        self.basic_config_panel.setVisible(True)

        # 基础模式下，只显示循环视频标签页
        self._show_loop_tab_only()

        self.splitter.addWidget(self.config_container)

        # === 中间: 视频预览标签页 + 时间轴（深色预览区，剪映风格）===
        self.preview_container = QWidget()
        preview_container = self.preview_container
        preview_container.setObjectName("preview_container")
        setCustomStyleSheet(
            preview_container,
            "QWidget#preview_container { background-color: #1a1a1a; border-radius: 8px; }",
            "QWidget#preview_container { background-color: #0a0a0a; border-radius: 8px; }"
        )
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(5, 5, 5, 5)
        preview_layout.setSpacing(5)

        self.preview_tabs = TabWidget()
        self.preview_tabs.setTabsClosable(False)  # 禁用关闭按钮
        self.preview_tabs.setMovable(False)  # 禁用标签移动
        # 标签页文字在深色预览背景上需要浅色
        setCustomStyleSheet(
            self.preview_tabs,
            "TabWidget > QTabBar::tab { color: #ccc; } TabWidget > QTabBar::tab:selected { color: #fff; }",
            "TabWidget > QTabBar::tab { color: #aaa; } TabWidget > QTabBar::tab:selected { color: #eee; }"
        )
        self.video_preview = VideoPreviewWidget()  # 循环视频预览
        self.intro_preview = VideoPreviewWidget()  # 入场视频预览
        self.transition_preview = TransitionPreviewWidget()  # 过渡图片预览

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

        self._show_loop_tab_only()

        self.timeline = TimelineWidget()
        preview_layout.addWidget(self.timeline)

        self.splitter.addWidget(preview_container)

        # === 右侧: JSON预览 ===
        self.json_preview = JsonPreviewWidget()
        self.splitter.addWidget(self.json_preview)

        self.splitter.setSizes([350, 800, 300])
        self.splitter.setStretchFactor(0, 1)   # 左侧允许少量伸缩
        self.splitter.setStretchFactor(1, 20)  # 中间优先伸缩，权重更大
        self.splitter.setStretchFactor(2, 1)   # 右侧允许少量伸缩

        self.content_layout.addWidget(self.splitter)
        content_layout.addWidget(self.content_stack)

        main_layout.addWidget(content_container)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

        self._setup_drop_support()

    def _setup_menu(self):
        """设置菜单"""
        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件(&F)")

        self.action_new = QAction("新建项目(&N)", self)
        file_menu.addAction(self.action_new)

        self.action_open = QAction("打开项目(&O)...", self)
        file_menu.addAction(self.action_open)

        self.recent_menu = file_menu.addMenu("最近打开(&R)")
        self._update_recent_menu()

        file_menu.addSeparator()

        self.action_save = QAction("保存(&S)", self)
        file_menu.addAction(self.action_save)

        self.action_save_as = QAction("另存为(&A)...", self)
        file_menu.addAction(self.action_save_as)

        file_menu.addSeparator()

        self.action_exit = QAction("退出(&X)", self)
        file_menu.addAction(self.action_exit)

        edit_menu = menubar.addMenu("编辑(&E)")

        self.action_undo = QAction("撤销(&U)", self)
        self.action_undo.setEnabled(False)
        edit_menu.addAction(self.action_undo)

        self.action_redo = QAction("重做(&R)", self)
        self.action_redo.setEnabled(False)
        edit_menu.addAction(self.action_redo)

        tools_menu = menubar.addMenu("工具(&T)")

        self.action_flasher = QAction("固件烧录(&R)...", self)
        tools_menu.addAction(self.action_flasher)

        help_menu = menubar.addMenu("帮助(&H)")

        self.action_shortcuts = QAction("快捷键帮助(&K)", self)
        help_menu.addAction(self.action_shortcuts)

        self.action_check_update = QAction("检查更新(&U)...", self)
        help_menu.addAction(self.action_check_update)

        help_menu.addSeparator()

        self.action_about = QAction("关于(&A)", self)
        help_menu.addAction(self.action_about)

    def _setup_shortcuts(self):
        """设置全局快捷键 - 统一注册到 MainWindow 上，不受子面板可见性影响"""
        QShortcut(QKeySequence.StandardKey.New, self).activated.connect(self._on_new_project)
        QShortcut(QKeySequence.StandardKey.Open, self).activated.connect(self._on_open_project)
        QShortcut(QKeySequence.StandardKey.Save, self).activated.connect(self._on_save_project)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self).activated.connect(self._on_save_as)
        QShortcut(QKeySequence.StandardKey.Quit, self).activated.connect(self.close)

        self._shortcut_undo = QShortcut(QKeySequence.StandardKey.Undo, self)
        self._shortcut_undo.setEnabled(False)
        self._shortcut_undo.activated.connect(self._on_undo)
        self._shortcut_redo = QShortcut(QKeySequence.StandardKey.Redo, self)
        self._shortcut_redo.setEnabled(False)
        self._shortcut_redo.activated.connect(self._on_redo)

        QShortcut(QKeySequence("Ctrl+T"), self).activated.connect(self._on_validate)
        QShortcut(QKeySequence("Ctrl+E"), self).activated.connect(self._on_export)

        QShortcut(QKeySequence("F1"), self).activated.connect(self._on_shortcuts)

    def _connect_signals(self):
        """连接信号"""
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
        self.advanced_config_panel.ssh_upload_requested.connect(self._on_ssh_upload)
        
        self.basic_config_panel.config_changed.connect(self._on_config_changed)
        self.basic_config_panel.video_file_selected.connect(
            self._on_video_file_selected)
        self.basic_config_panel.validate_requested.connect(self._on_validate)
        self.basic_config_panel.export_requested.connect(self._on_export)
        self.basic_config_panel.ssh_upload_requested.connect(self._on_ssh_upload)
        self.btn_save_icon.clicked.connect(self._on_save_captured_icon)

        self.transition_preview.transition_crop_changed.connect(
            self._on_transition_crop_changed)

        self.preview_tabs.currentChanged.connect(self._on_preview_tab_changed)

        self.video_preview.video_loaded.connect(self._on_video_loaded)
        self.video_preview.frame_changed.connect(self._on_frame_changed)
        self.video_preview.playback_state_changed.connect(
            self._on_playback_changed)
        self.video_preview.rotation_changed.connect(self.timeline.set_rotation)

        self.btn_firmware.clicked.connect(self._on_sidebar_firmware)
        self.btn_material.clicked.connect(self._on_sidebar_material)
        self.btn_forum.clicked.connect(self._on_sidebar_forum)
        self.btn_about.clicked.connect(self._on_sidebar_about)
        self.btn_remote.clicked.connect(self._on_sidebar_remote)
        self.btn_settings.clicked.connect(self._on_sidebar_settings)

        self.intro_preview.video_loaded.connect(self._on_intro_video_loaded)
        self.intro_preview.frame_changed.connect(self._on_intro_frame_changed)
        self.intro_preview.playback_state_changed.connect(
            self._on_intro_playback_changed)
        self.intro_preview.rotation_changed.connect(
            self._on_intro_rotation_changed)

        self._connect_timeline_to_preview(self.intro_preview)

        self.timeline.simulator_requested.connect(self._on_simulator)

        self.timeline.set_in_point_clicked.connect(self._on_set_in_point)
        self.timeline.set_out_point_clicked.connect(self._on_set_out_point)

        from qfluentwidgets.common.config import qconfig
        qconfig.themeChanged.connect(self._on_system_theme_changed)

    def _on_system_theme_changed(self):
        """系统亮/暗主题切换时，刷新窗口背景为对应中性色"""
        self._bg_color = self._dark_bg_color if isDarkTheme() else self._light_bg_color
        self.update()

    def _on_ssh_upload(self):
        """SSH 上传"""
        try:
            result = self._on_export()
            if not result:
                return
            export_dialog, dir_path = result

            if not getattr(export_dialog, '_is_completed', False) or \
                    export_dialog.label_status.text() != "导出完成!":
                print("导出失败，取消SSH上传")
                return

            if not os.path.exists(dir_path):
                print("导出目录不存在，取消SSH上传")
                return

            settings = self._read_user_settings()
            host = settings.get('ssh_ip_address', "192.168.137.2")
            port = settings.get('ssh_port', 22)
            user = settings.get('ssh_user', "root")
            password = settings.get('ssh_password', "toor")
            remote_path = settings.get('ssh_default_upload_path', "/assets/")
            enableRestart = settings.get('ssh_auto_restart_program', True)

            from core.ssh_upload_service import SshUploadWorker
            from gui.dialogs.ssh_upload_progress_dialog import SshUploadProgressDialog

            self._ssh_upload_worker = SshUploadWorker(self)
            self._ssh_upload_dialog = SshUploadProgressDialog(self)

            self._ssh_upload_worker.progress_updated.connect(
                self._ssh_upload_dialog.update_progress
            )
            self._ssh_upload_worker.upload_completed.connect(
                lambda msg: self._on_ssh_upload_completed(True, msg)
            )
            self._ssh_upload_worker.upload_failed.connect(
                lambda msg: self._on_ssh_upload_completed(False, msg)
            )
            self._ssh_upload_dialog.cancel_requested.connect(
                self._ssh_upload_worker.cancel
            )

            self._ssh_upload_worker.setup(
                host=host,
                port=port,
                user=user,
                password=password,
                local_path=dir_path,
                remote_path=remote_path,
                enable_restart=enableRestart,
            )
            self._ssh_upload_worker.start()

            self._ssh_upload_dialog.exec()

            # 如果用户取消了对话框，让后台线程尽快结束
            if self._ssh_upload_worker.isRunning():
                self._ssh_upload_worker.cancel()
                self._ssh_upload_worker.wait(2000)

        except Exception as e:
            print("发生错误:", e)
            return
        return

    def _load_settings(self):
        """加载设置"""
        settings = QSettings("ArknightsPassMaker", "MainWindow")
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
            logger.debug("已恢复窗口几何设置")

    def _load_user_settings(self):
        """加载用户设置（启动时调用）"""
        try:
            import json
            config_dir = os.path.join(self._app_dir, "config")
            config_file = os.path.join(config_dir, "user_settings.json")

            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    settings = json.load(f)

                theme_name = settings.get('theme', '默认')
                self._apply_theme_change(theme_name)

                hw_accel = settings.get('hardware_acceleration', True)
                if not hw_accel:
                    self._apply_instant_settings(
                        'hardware_acceleration', False)

                auto_save = settings.get('auto_save', True)
                if not auto_save:
                    self._auto_save_service.config.enabled = False

                logger.info("已加载用户设置")
        except Exception as e:
            logger.error(f"加载用户设置失败: {e}")

    def _read_user_settings(self) -> dict:
        """读取 user_settings.json 并返回 dict"""
        try:
            import json
            config_dir = os.path.join(self._app_dir, "config")
            config_file = os.path.join(config_dir, "user_settings.json")
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            return {}
        except Exception as e:
            logger.error(f"读取用户设置失败: {e}")
            return {}

    def _load_settings_to_page(self):
        """将 user_settings.json 的值加载到设置页面"""
        try:
            settings = self._read_user_settings()
            self._settings_page.load_settings(settings)
        except Exception as e:
            logger.error(f"加载设置到页面失败: {e}")

    def _check_first_run(self):
        """检查是否首次运行"""
        settings = QSettings("ArknightsPassMaker", "MainWindow")
        if not settings.value("first_run_completed", False, type=bool):
            show_welcome = True
            try:
                import json
                config_dir = os.path.join(self._app_dir, "config")
                config_file = os.path.join(config_dir, "user_settings.json")
                if os.path.exists(config_file):
                    with open(config_file, "r", encoding="utf-8") as f:
                        user_settings = json.load(f)
                        show_welcome = user_settings.get(
                            'show_welcome_dialog', True)
            except Exception:
                pass

            if show_welcome:
                self._show_splash_announcement()
                settings.setValue("first_run_completed", True)
        else:
            # 每次启动都显示开屏公告（可选择不再显示）
            self._show_splash_announcement()

    def _show_splash_announcement(self):
        """显示开屏公告"""
        settings = QSettings("ArknightsPassMaker", "MainWindow")
        if not settings.value("show_announcement", True, type=bool):
            return

        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextBrowser, QCheckBox
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QIcon

        dialog = QDialog(self)
        dialog.setWindowTitle("软件使用指南")
        dialog.setMinimumSize(800, 600)
        dialog.setWindowIcon(
            QIcon(
                os.path.join(
                    self._app_dir,
                    'resources',
                    'icons',
                    'favicon.ico')))

        main_layout = QVBoxLayout(dialog)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        title_label = QLabel("欢迎使用明日方舟通行证素材制作器 v2.0")
        setCustomStyleSheet(
            title_label,
            "font-size: 20px; font-weight: bold; color: #ff6b8b; text-align: center;",
            "font-size: 20px; font-weight: bold; color: #ff6b8b; text-align: center;"
        )
        main_layout.addWidget(title_label)

        content_browser = QTextBrowser()
        setCustomStyleSheet(
            content_browser,
            "font-size: 14px; line-height: 1.5;",
            "font-size: 14px; line-height: 1.5;"
        )

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

        <h4>3. 素材论坛</h4>
        <p>内置素材论坛客户端，提供完整的素材浏览和管理功能。</p>
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
            <li><strong>视频设置</strong>：设置硬件加速</li>
            <li><strong>导出设置</strong>：调整导出线程数</li>
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

        bottom_layout = QHBoxLayout()

        self.show_announcement_check = QCheckBox("下次启动时不再显示")
        bottom_layout.addWidget(self.show_announcement_check)

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        ok_button = PrimaryPushButton("我知道了")
        ok_button.clicked.connect(dialog.accept)

        button_layout.addWidget(ok_button)
        bottom_layout.addLayout(button_layout)

        main_layout.addLayout(bottom_layout)

        dialog.exec()

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

        dir_path = QFileDialog.getExistingDirectory(
            self, "选择项目目录", ""
        )
        if not dir_path:
            return

        self._cleanup_temp_dir()

        self._config = EPConfig()
        self._base_dir = dir_path
        self._project_path = os.path.join(dir_path, CONFIG_FILENAME)
        self._is_modified = True

        self.video_preview.clear()
        self.intro_preview.clear()
        self.frame_capture_preview.clear()
        self.transition_preview.clear_image("in")
        self.transition_preview.clear_image("loop")
        self._loop_image_path = None
        self.timeline.set_total_frames(0)
        self._loop_in_out = (0, 0)
        self._intro_in_out = (0, 0)

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

        self._cleanup_temp_dir()
        self.ReadProjectFromJson(path)

    def ReadProjectFromJson(self, path: str):
        try:
            self._config = EPConfig.load_from_file(path)
            self._project_path = path
            self._base_dir = os.path.dirname(path)
            self._is_modified = False

            self.video_preview.clear()
            self.intro_preview.clear()
            self.frame_capture_preview.clear()
            self.transition_preview.clear_image("in")
            self.transition_preview.clear_image("loop")
            self._loop_image_path = None
            self.timeline.set_total_frames(0)
            self._loop_in_out = (0, 0)
            self._intro_in_out = (0, 0)

            self.advanced_config_panel.set_config(self._config, self._base_dir)
            self.basic_config_panel.set_config(self._config, self._base_dir)
            self.json_preview.set_config(self._config, self._base_dir)
            self.video_preview.set_epconfig(self._config)

            target_w, target_h = self._get_target_resolution()
            self.video_preview.set_target_resolution(target_w, target_h)
            self.intro_preview.set_target_resolution(target_w, target_h)

            if self._config.loop.file:
                file_path = self._config.loop.file
                if not os.path.isabs(file_path):
                    file_path = os.path.join(self._base_dir, file_path)

                if os.path.exists(file_path):
                    from PyQt6.QtCore import QTimer
                    if self._config.loop.is_image:
                        logger.info(f"尝试加载循环图片: {file_path}")
                        QTimer.singleShot(
                            100, lambda fp=file_path: self._load_loop_image(fp))
                    else:
                        logger.info(f"尝试加载循环视频: {file_path}")
                        QTimer.singleShot(
                            100, lambda vp=file_path: self.video_preview.load_video(vp))
                else:
                    logger.warning(f"循环素材文件不存在: {file_path}")

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

            self._add_recent_file(path)

            self._auto_save_service.start(
                self._config, self._project_path, self._base_dir)

        except Exception as e:
            show_error(e, "打开文件", self)



    def _load_project(self, path: str):
        """加载指定路径的项目文件（供最近打开和崩溃恢复调用）"""
        if not os.path.exists(path):
            QMessageBox.warning(self, "文件不存在", f"文件不存在:\n{path}")
            return

        if not self._check_save():
            return

        self._cleanup_temp_dir()

        try:
            self._config = EPConfig.load_from_file(path)
            self._project_path = path
            self._base_dir = os.path.dirname(path)
            self._is_modified = False

            self.video_preview.clear()
            self.intro_preview.clear()
            self.frame_capture_preview.clear()
            self.transition_preview.clear_image("in")
            self.transition_preview.clear_image("loop")
            self._loop_image_path = None
            self.timeline.set_total_frames(0)
            self._loop_in_out = (0, 0)
            self._intro_in_out = (0, 0)

            self.advanced_config_panel.set_config(self._config, self._base_dir)
            self.basic_config_panel.set_config(self._config, self._base_dir)
            self.json_preview.set_config(self._config, self._base_dir)
            self.video_preview.set_epconfig(self._config)

            target_w, target_h = self._get_target_resolution()
            self.video_preview.set_target_resolution(target_w, target_h)
            self.intro_preview.set_target_resolution(target_w, target_h)

            if self._config.loop.file:
                file_path = self._config.loop.file
                if not os.path.isabs(file_path):
                    file_path = os.path.join(self._base_dir, file_path)
                if os.path.exists(file_path):
                    if self._config.loop.is_image:
                        QTimer.singleShot(
                            100, lambda fp=file_path: self._load_loop_image(fp))
                    else:
                        QTimer.singleShot(
                            100, lambda vp=file_path: self.video_preview.load_video(vp))

            if self._config.intro.enabled and self._config.intro.file:
                intro_path = self._config.intro.file
                if not os.path.isabs(intro_path):
                    intro_path = os.path.join(self._base_dir, intro_path)
                if os.path.exists(intro_path):
                    QTimer.singleShot(
                        200, lambda vp=intro_path: self.intro_preview.load_video(vp))

            self._update_title()
            self.status_bar.showMessage(f"已打开: {path}")
            self._add_recent_file(path)
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
            self._project_path or CONFIG_FILENAME,
            "JSON文件 (*.json)"
        )
        if not path:
            return

        # 校验文件名，防止用户误改
        if os.path.basename(path) != CONFIG_FILENAME:
            corrected = os.path.join(os.path.dirname(path), CONFIG_FILENAME)
            ret = QMessageBox.question(
                self, "文件名修正",
                f"配置文件名应为\u201c{CONFIG_FILENAME}\u201d，否则模拟器等功能将无法正常工作。\n\n"
                f"是否将文件名修正为\u201c{CONFIG_FILENAME}\u201d？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if ret == QMessageBox.StandardButton.Yes:
                path = corrected

        try:
            new_base_dir = os.path.dirname(path)

            if self._temp_dir and self._base_dir == self._temp_dir:
                self._migrate_temp_to_permanent(new_base_dir)

            self._config.save_to_file(path)
            self._project_path = path
            self._base_dir = new_base_dir
            self._is_modified = False

            self.advanced_config_panel.set_config(self._config, self._base_dir)
            self.basic_config_panel.set_config(self._config, self._base_dir)
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

        dir_path = QFileDialog.getExistingDirectory(
            self, "选择导出目录", self._base_dir
        )
        if not dir_path:
            return

        try:
            export_data = self._collect_export_data()
        except Exception as e:
            logger.error(f"收集导出数据失败: {e}")
            show_error(e, "收集导出数据", self)
            return

        try:
            self._process_arknights_custom_images(dir_path)
        except Exception as e:
            logger.error(f"处理自定义图片失败: {e}")
            show_error(e, "处理自定义图片", self)

        try:
            self._process_image_overlay(dir_path)
        except Exception as e:
            logger.error(f"处理 ImageOverlay 失败: {e}")

        from core.export_service import ExportService
        from gui.dialogs.export_progress_dialog import ExportProgressDialog

        self._export_service = ExportService(self)
        self._export_dialog = ExportProgressDialog(self)

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

        self._export_service.export_all(
            output_dir=dir_path,
            epconfig=self._config,
            logo_mat=export_data.get('logo_mat'),
            overlay_mat=export_data.get('overlay_mat'),
            loop_video_params=export_data.get('loop_video_params'),
            intro_video_params=export_data.get('intro_video_params'),
            loop_image_path=export_data.get('loop_image_path'),
        )

        self._export_dialog.exec()
        return self._export_dialog, dir_path

    def _on_simulator(self):
        """打开模拟器预览"""
        import subprocess

        if not self._config:
            QMessageBox.information(self, "提示", "请先创建或打开项目")
            return

        if not self._config.loop.file:
            QMessageBox.warning(
                self, "警告",
                "请先配置循环视频文件\n\n"
                "在配置面板的'视频配置'选项卡中选择循环视频文件"
            )
            return

        simulator_path = os.path.join(
            self._app_dir,
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
            # 启动模拟器前自动保存，确保磁盘配置与 GUI 状态一致
            # 模拟器从磁盘读取 epconfig.json（不共享 GUI 内存），
            # 而导出直接使用 video_preview.video_path（内存中的当前视频）。
            # 如果用户修改了视频但未保存，模拟器会打开旧视频 → 画面完全不同。
            if self._is_modified:
                if self._project_path:
                    try:
                        self._config.save_to_file(self._project_path)
                        self._is_modified = False
                        self._update_title()
                        logger.info(
                            f"模拟器启动前自动保存: {self._project_path}")
                    except Exception as e:
                        logger.warning(f"自动保存失败: {e}")
                        QMessageBox.warning(
                            self, "警告",
                            f"自动保存失败，模拟器预览可能不准确\n\n{e}"
                        )
                        return
                else:
                    QMessageBox.warning(
                        self, "警告",
                        "请先保存项目配置\n\n"
                        "文件 → 保存项目"
                    )
                    return

            config_path = self._project_path

            if not os.path.exists(config_path):
                QMessageBox.warning(
                    self, "警告",
                    "请先保存项目配置\n\n"
                    "文件 → 保存项目"
                )
                return

            cropbox = self.video_preview.get_cropbox_in_rotated_space()
            rotation = self.video_preview.get_rotation()

            logger.info(
                f"启动模拟器: cropbox={cropbox}, rotation={rotation}, "
                f"config_video={self._config.loop.file}, "
                f"gui_video={self.video_preview.video_path}")

            popen_kwargs = {}
            if sys.platform == 'win32':
                popen_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

            # 设置工作目录为应用根目录，确保模拟器能找到 FFmpeg DLL
            # Windows DLL 搜索顺序：exe 所在目录 → system32 → PATH
            # 模拟器 exe 在 simulator/target/release/ 子目录，无法找到根目录的 DLL
            popen_kwargs['cwd'] = self._app_dir

            # 双保险：将 app_dir 加入 PATH 环境变量
            env = os.environ.copy()
            env['PATH'] = self._app_dir + os.pathsep + env.get('PATH', '')
            popen_kwargs['env'] = env

            proc = subprocess.Popen([
                simulator_path,
                "--config", config_path,
                "--base-dir", self._base_dir,
                "--app-dir", self._app_dir,
                "--cropbox", f"{cropbox[0]},{cropbox[1]},{cropbox[2]},{cropbox[3]}",
                "--rotation", str(rotation)
            ], **popen_kwargs)

            logger.info(f"模拟器已启动: {simulator_path}")

            # 1秒后检查进程是否崩溃
            def _check_simulator():
                retcode = proc.poll()
                if retcode is not None and retcode != 0:
                    QMessageBox.warning(
                        self, "模拟器错误",
                        f"模拟器启动后立即退出（返回码: {retcode}）\n\n"
                        f"可能原因：\n"
                        f"• FFmpeg DLL 缺失或版本不匹配\n"
                        f"• 配置文件格式错误\n\n"
                        f"路径: {simulator_path}"
                    )
            QTimer.singleShot(1000, _check_simulator)

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

        prev_state = self._undo_stack.pop()

        current_state = self._config.to_dict() if self._config else {}
        self._redo_stack.append(current_state)

        if prev_state:
            self._config = EPConfig.from_dict(prev_state)
            self._update_ui_from_config()

        self.action_undo.setEnabled(len(self._undo_stack) > 0)
        self.action_redo.setEnabled(len(self._redo_stack) > 0)
        self.menu_action_undo.setEnabled(len(self._undo_stack) > 0)
        self.menu_action_redo.setEnabled(len(self._redo_stack) > 0)
        self._shortcut_undo.setEnabled(len(self._undo_stack) > 0)
        self._shortcut_redo.setEnabled(len(self._redo_stack) > 0)

        self.status_bar.showMessage("已撤销", 2000)

    def _on_redo(self):
        """重做操作"""
        if not self._redo_stack:
            return

        next_state = self._redo_stack.pop()

        current_state = self._config.to_dict() if self._config else {}
        self._undo_stack.append(current_state)

        if next_state:
            self._config = EPConfig.from_dict(next_state)
            self._update_ui_from_config()

        self.action_undo.setEnabled(len(self._undo_stack) > 0)
        self.action_redo.setEnabled(len(self._redo_stack) > 0)
        self.menu_action_undo.setEnabled(len(self._undo_stack) > 0)
        self.menu_action_redo.setEnabled(len(self._redo_stack) > 0)
        self._shortcut_undo.setEnabled(len(self._undo_stack) > 0)
        self._shortcut_redo.setEnabled(len(self._redo_stack) > 0)

        self.status_bar.showMessage("已重做", 2000)

    def _save_state(self):
        """保存当前状态到撤销栈"""
        if not self._config:
            return

        current_state = self._config.to_dict()
        self._undo_stack.append(current_state)

        if len(self._undo_stack) > self._max_history:
            self._undo_stack.pop(0)

        self._redo_stack.clear()

        self.action_undo.setEnabled(len(self._undo_stack) > 0)
        self.action_redo.setEnabled(False)
        self.menu_action_undo.setEnabled(len(self._undo_stack) > 0)
        self.menu_action_redo.setEnabled(False)
        self._shortcut_undo.setEnabled(len(self._undo_stack) > 0)
        self._shortcut_redo.setEnabled(False)

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

    def _pause_all_videos(self):
        """暂停所有正在播放的视频预览，记录播放状态以便返回时恢复"""
        self._videos_were_playing = []
        all_previews = [
            self.video_preview,
            self.intro_preview,
            self.frame_capture_preview,
            self.transition_preview.preview_in,
            self.transition_preview.preview_loop,
        ]
        for p in all_previews:
            if p.is_playing:
                self._videos_were_playing.append(p)
                p.pause()

    def _resume_videos(self):
        """恢复之前暂停的视频播放"""
        for p in self._videos_were_playing:
            p.play()
        self._videos_were_playing = []

    def _on_sidebar_firmware(self):
        """侧边栏：固件烧录"""
        self.btn_firmware.setChecked(True)
        self.btn_material.setChecked(False)
        self.btn_forum.setChecked(False)
        self.btn_about.setChecked(False)
        self.btn_remote.setChecked(False)
        self.btn_settings.setChecked(False)

        self._pause_all_videos()

        self.splitter.setVisible(False)
        if hasattr(self, '_forum_widget'):
            self._forum_widget.setVisible(False)
        if hasattr(self, '_settings_page'):
            self._settings_page.setVisible(False)
        if hasattr(self, '_about_widget'):
            self._about_widget.setVisible(False)
        if hasattr(self, '_remote_page'):
            self._remote_page.setVisible(False)

        if not hasattr(self, '_flasher_widget'):
            from gui.dialogs.flasher_dialog import FlasherDialog

            self._flasher_widget = QWidget()
            self._flasher_widget_layout = QVBoxLayout(self._flasher_widget)

            self._flasher_dialog = FlasherDialog(self)
            self._flasher_dialog.setWindowFlags(Qt.WindowType.Widget)
            self._flasher_widget_layout.addWidget(self._flasher_dialog)
            self.content_layout.addWidget(self._flasher_widget)

        self._flasher_widget.setVisible(True)
        self.status_bar.showMessage("固件烧录模式")

    def _on_sidebar_material(self):
        """侧边栏：素材制作"""
        self.btn_firmware.setChecked(False)
        self.btn_material.setChecked(True)
        self.btn_forum.setChecked(False)
        self.btn_about.setChecked(False)
        self.btn_remote.setChecked(False)
        self.btn_settings.setChecked(False)

        if hasattr(self, '_forum_widget'):
            self._forum_widget.setVisible(False)
        if hasattr(self, '_settings_page'):
            self._settings_page.setVisible(False)
        if hasattr(self, '_about_widget'):
            self._about_widget.setVisible(False)
        if hasattr(self, '_flasher_widget'):
            self._flasher_widget.setVisible(False)
        if hasattr(self, '_remote_page'):
            self._remote_page.setVisible(False)

        self.splitter.setVisible(True)
        self.status_bar.showMessage("素材制作模式")

        self._resume_videos()

    def _on_sidebar_forum(self):
        """侧边栏：素材论坛"""
        self.btn_firmware.setChecked(False)
        self.btn_material.setChecked(False)
        self.btn_forum.setChecked(True)
        self.btn_about.setChecked(False)
        self.btn_remote.setChecked(False)
        self.btn_settings.setChecked(False)

        self._pause_all_videos()

        self.splitter.setVisible(False)
        if hasattr(self, '_settings_page'):
            self._settings_page.setVisible(False)
        if hasattr(self, '_about_widget'):
            self._about_widget.setVisible(False)
        if hasattr(self, '_flasher_widget'):
            self._flasher_widget.setVisible(False)
        if hasattr(self, '_remote_page'):
            self._remote_page.setVisible(False)

        if not hasattr(self, '_forum_widget'):
            try:
                from _mext.ui.widget import MaterialForumWidget
                self._forum_widget = MaterialForumWidget(parent=self)
                self.content_layout.addWidget(self._forum_widget)
            except ImportError as exc:
                logger.error("素材论坛模块加载失败，缺少必要依赖", exc_info=True)
                missing_pkg = getattr(exc, 'name', None) or str(exc)
                QMessageBox.warning(
                    self, "模块加载失败",
                    f"素材论坛所需的依赖库缺失，请检查安装是否完整。\n\n"
                    f"缺少的包: {missing_pkg}\n\n"
                    "可能需要: httpx, keyring, platformdirs, fido2, pyusb 等。")
                self._on_sidebar_material()
                return
            except Exception as exc:
                logger.error("素材论坛初始化失败: %s", exc, exc_info=True)
                QMessageBox.warning(
                    self, "初始化失败",
                    f"素材论坛初始化时发生错误:\n{type(exc).__name__}: {exc}\n\n"
                    "请查看日志文件获取详细信息。")
                self._on_sidebar_material()
                return

        self._forum_widget.setVisible(True)
        self.status_bar.showMessage("素材论坛模式")

    def _on_sidebar_about(self):
        """侧边栏：项目介绍"""
        self.btn_firmware.setChecked(False)
        self.btn_material.setChecked(False)
        self.btn_forum.setChecked(False)
        self.btn_about.setChecked(True)
        self.btn_remote.setChecked(False)
        self.btn_settings.setChecked(False)

        self._pause_all_videos()

        self.splitter.setVisible(False)
        if hasattr(self, '_forum_widget'):
            self._forum_widget.setVisible(False)
        if hasattr(self, '_settings_page'):
            self._settings_page.setVisible(False)
        if hasattr(self, '_flasher_widget'):
            self._flasher_widget.setVisible(False)
        if hasattr(self, '_remote_page'):
            self._remote_page.setVisible(False)

        if not hasattr(self, '_about_widget'):
            from PyQt6.QtWidgets import QLabel, QVBoxLayout, QTextBrowser

            self._about_widget = QWidget()
            self._about_widget.setVisible(False)

            about_layout = QVBoxLayout(self._about_widget)
            about_layout.setContentsMargins(20, 10, 20, 10)  # 减小上下边距
            about_layout.setSpacing(15)

            title_label = QLabel("项目介绍")
            setCustomStyleSheet(
                title_label,
                "font-size: 18px; font-weight: bold; color: #333;",
                "font-size: 18px; font-weight: bold; color: #eee;"
            )
            about_layout.addWidget(title_label)

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

                url_label = QLabel(
                    f"网站链接: <a href='https://ep.iccmc.cc'>https://ep.iccmc.cc</a>")
                url_label.setOpenExternalLinks(True)
                setCustomStyleSheet(
                    url_label,
                    "color: #ff6b8b; text-decoration: underline;",
                    "color: #ff6b8b; text-decoration: underline;"
                )
                about_layout.addWidget(url_label)

            except Exception as e:
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

                url_label = QLabel(
                    f"网站链接: <a href='https://ep.iccmc.cc'>https://ep.iccmc.cc</a>")
                url_label.setOpenExternalLinks(True)
                setCustomStyleSheet(
                    url_label,
                    "color: #ff6b8b; text-decoration: underline;",
                    "color: #ff6b8b; text-decoration: underline;"
                )
                about_layout.addWidget(url_label)

            self.content_layout.addWidget(self._about_widget)

        self._about_widget.setVisible(True)

        self.status_bar.showMessage("项目介绍")

    def _on_settings_mode_combo_changed(self, index: int):
        """下拉框切换设置模式"""
        mode = self.settings_mode_combo.currentData()
        self._on_settings_mode_changed(mode)

    def _show_loop_tab_only(self):
        """基础模式：仅显示循环视频标签页"""
        if not hasattr(self, 'preview_tabs'):
            return

        tab_bar = self.preview_tabs.tabBar
        # 阻塞 tabBar 信号，防止 setTabVisible 内部
        # 发射虚假 currentChanged 导致 stackedWidget 索引被污染
        tab_bar.blockSignals(True)
        try:
            if 3 < self.preview_tabs.count():
                self.preview_tabs.setTabVisible(3, True)
            for i in [0, 1, 2]:
                if i < self.preview_tabs.count():
                    self.preview_tabs.setTabVisible(i, False)
        finally:
            tab_bar.blockSignals(False)

        # 手动设置正确状态
        self._fix_tab_selected_state(3)
        self.preview_tabs.stackedWidget.setCurrentIndex(3)
        if hasattr(self, 'timeline'):
            self._on_preview_tab_changed(3)

    def _show_all_tabs(self):
        """高级模式：显示所有标签页"""
        if not hasattr(self, 'preview_tabs'):
            return

        tab_bar = self.preview_tabs.tabBar
        current = tab_bar._currentIndex

        tab_bar.blockSignals(True)
        try:
            for i in range(self.preview_tabs.count()):
                self.preview_tabs.setTabVisible(i, True)
        finally:
            tab_bar.blockSignals(False)

        self._fix_tab_selected_state(current)
        self.preview_tabs.stackedWidget.setCurrentIndex(current)
        if hasattr(self, 'timeline'):
            self._on_preview_tab_changed(current)

    def _fix_tab_selected_state(self, active_index: int):
        """强制清理 TabBar 所有 item 的 isSelected，仅保留指定索引"""
        tab_bar = self.preview_tabs.tabBar
        for idx, item in enumerate(tab_bar.items):
            item.setSelected(idx == active_index)
        tab_bar._currentIndex = active_index

    def _on_settings_mode_changed(self, mode):
        """设置模式切换"""
        try:
            if mode == "basic":
                # 切换前先同步，避免丢失高级面板的修改
                if self.advanced_config_panel.isVisible():
                    self.advanced_config_panel.update_config_from_ui()

                self.advanced_config_panel.setVisible(False)
                self.basic_config_panel.setVisible(True)

                if self._config:
                    self.basic_config_panel.set_config(self._config, self._base_dir)

                self.status_bar.showMessage("基础设置模式 - 简化界面")
                self._show_loop_tab_only()
            elif mode == "advanced":
                # 切换前先同步，避免丢失基础面板的修改
                if self.basic_config_panel.isVisible():
                    self.basic_config_panel.update_config_from_ui()

                self.advanced_config_panel.setVisible(True)
                self.basic_config_panel.setVisible(False)

                if self._config:
                    self.advanced_config_panel.set_config(self._config, self._base_dir)

                self.status_bar.showMessage("高级设置模式 - 完整界面")
                self._show_all_tabs()
        except Exception as e:
            logger.error(f"设置模式切换错误: {e}")

    def _on_sidebar_remote(self):
        """侧边栏：远程管理"""
        self.btn_firmware.setChecked(False)
        self.btn_material.setChecked(False)
        self.btn_forum.setChecked(False)
        self.btn_about.setChecked(False)
        self.btn_remote.setChecked(True)
        self.btn_settings.setChecked(False)

        self._pause_all_videos()

        self.splitter.setVisible(False)
        if hasattr(self, '_forum_widget'):
            self._forum_widget.setVisible(False)
        if hasattr(self, '_settings_page'):
            self._settings_page.setVisible(False)
        if hasattr(self, '_about_widget'):
            self._about_widget.setVisible(False)
        if hasattr(self, '_flasher_widget'):
            self._flasher_widget.setVisible(False)

        if not hasattr(self, '_remote_page'):
            from gui.widgets.remote_page import RemotePage
            self._remote_page = RemotePage(parent=self)
            self.content_layout.addWidget(self._remote_page)

            try:
                import json
                config_file = os.path.join(self._app_dir, "config",
                                           "user_settings.json")
                if os.path.exists(config_file):
                    with open(config_file, "r", encoding="utf-8") as f:
                        settings = json.load(f)
                    self._remote_page.load_settings(settings)
            except Exception:
                pass

        self._remote_page.setVisible(True)
        self.status_bar.showMessage("远程管理模式")

    def _on_sidebar_settings(self):
        """侧边栏：设置"""
        self.btn_firmware.setChecked(False)
        self.btn_material.setChecked(False)
        self.btn_forum.setChecked(False)
        self.btn_about.setChecked(False)
        self.btn_remote.setChecked(False)
        self.btn_settings.setChecked(True)

        self._pause_all_videos()

        if hasattr(self, '_forum_widget'):
            self._forum_widget.setVisible(False)
        self.splitter.setVisible(False)
        if hasattr(self, '_about_widget'):
            self._about_widget.setVisible(False)
        if hasattr(self, '_flasher_widget'):
            self._flasher_widget.setVisible(False)
        if hasattr(self, '_remote_page'):
            self._remote_page.setVisible(False)

        if not hasattr(self, '_settings_page'):
            from gui.widgets.settings_page import SettingsPage
            self._settings_page = SettingsPage(parent=self)
            self._settings_page.setting_changed.connect(
                self._on_setting_changed)
            self._settings_page.check_update_requested.connect(
                self._on_check_update)
            self._settings_page.show_shortcuts_requested.connect(
                self._on_shortcuts)
            self.content_layout.addWidget(self._settings_page)

        self._load_settings_to_page()
        self._settings_page.setVisible(True)

        self.status_bar.showMessage("设置模式")

    def _on_nav_file(self):
        """顶部导航：文件"""
        from PyQt6.QtWidgets import QMenu, QMessageBox
        from PyQt6.QtGui import QAction

        try:
            file_menu = QMenu(self)

            new_action = QAction("新建项目", self)
            new_action.triggered.connect(self._on_new_project)
            file_menu.addAction(new_action)

            open_action = QAction("打开项目", self)
            open_action.triggered.connect(self._on_open_project)
            file_menu.addAction(open_action)

            save_action = QAction("保存项目", self)
            save_action.triggered.connect(self._on_save_project)
            file_menu.addAction(save_action)

            save_as_action = QAction("另存为", self)
            save_as_action.triggered.connect(self._on_save_as)
            file_menu.addAction(save_as_action)

            pos = self.btn_nav_file.mapToGlobal(
                self.btn_nav_file.rect().bottomLeft())
            file_menu.exec(pos)
        except Exception as e:
            logger.error(f"文件菜单错误: {e}")
            show_error(e, "文件菜单", self)

    def _on_nav_basic(self):
        """顶部导航：基础设置"""
        try:
            self._on_sidebar_material()

            if hasattr(
                    self,
                    'advanced_config_panel') and hasattr(
                    self,
                    'basic_config_panel'):
                self.advanced_config_panel.setVisible(False)
                self.basic_config_panel.setVisible(True)
                self.status_bar.showMessage("基础设置模式 - 简化界面")

            self._show_loop_tab_only()
        except Exception as e:
            logger.error(f"基础设置切换错误: {e}")

    def _on_nav_advanced(self):
        """顶部导航：高级设置"""
        try:
            self._on_sidebar_material()

            if hasattr(
                    self,
                    'advanced_config_panel') and hasattr(
                    self,
                    'basic_config_panel'):
                self.advanced_config_panel.setVisible(True)
                self.basic_config_panel.setVisible(False)
                self.status_bar.showMessage("高级设置模式 - 完整界面")

            self._show_all_tabs()
        except Exception as e:
            logger.error(f"高级设置切换错误: {e}")

    def _on_nav_help(self):
        """顶部导航：帮助"""
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction

        try:
            help_menu = QMenu(self)

            shortcuts_action = QAction("快捷键帮助", self)
            shortcuts_action.triggered.connect(self._on_shortcuts)
            help_menu.addAction(shortcuts_action)

            update_action = QAction("检查更新", self)
            update_action.triggered.connect(self._on_check_update)
            help_menu.addAction(update_action)

            about_action = QAction("关于", self)
            about_action.triggered.connect(self._on_about)
            help_menu.addAction(about_action)

            pos = self.btn_nav_help.mapToGlobal(
                self.btn_nav_help.rect().bottomLeft())
            help_menu.exec(pos)
        except Exception as e:
            logger.error(f"帮助菜单错误: {e}")
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "错误", f"帮助菜单加载失败: {str(e)}")

    def _on_check_update(self):
        """手动检查更新"""
        from gui.dialogs.update_dialog import UpdateDialog
        dialog = UpdateDialog(self, auto_check=True)
        dialog.exec()

    def _check_update_on_startup(self):
        """启动时后台检查更新"""
        try:
            from datetime import datetime, timedelta
            from config.constants import UPDATE_CHECK_INTERVAL_HOURS

            settings = QSettings("ArknightsPassMaker", "MainWindow")

            auto_check_enabled = settings.value(
                "auto_check_updates", True, type=bool)

            try:
                import json
                config_dir = os.path.join(self._app_dir, "config")
                config_file = os.path.join(config_dir, "user_settings.json")
                if os.path.exists(config_file):
                    with open(config_file, "r", encoding="utf-8") as f:
                        user_settings = json.load(f)
                        auto_check_enabled = user_settings.get(
                            'auto_update', True)
            except Exception:
                pass

            if not auto_check_enabled:
                return

            # 检查上次检查时间（避免频繁检查）
            last_check = settings.value("last_update_check", "")
            if last_check:
                try:
                    last_check_time = datetime.fromisoformat(last_check)
                    if datetime.now() - last_check_time < timedelta(
                            hours=UPDATE_CHECK_INTERVAL_HOURS):
                        logger.debug("跳过更新检查（24小时内已检查）")
                        return
                except ValueError:
                    pass

            from core.update_service import UpdateService

            self._startup_update_service = UpdateService(APP_VERSION, self)
            self._startup_update_service.check_completed.connect(
                self._on_startup_update_check_completed)
            self._startup_update_service.check_failed.connect(
                self._on_startup_update_check_failed)
            self._startup_update_service.check_for_updates()

            settings.setValue(
                "last_update_check", datetime.now().isoformat())

        except Exception as e:
            logger.error(f"启动时更新检查失败: {e}", exc_info=True)

    def _check_crash_recovery(self):
        """启动时检查崩溃恢复"""
        try:
            recovery_list = self._crash_recovery_service.check_crash_recovery()

            if not recovery_list:
                logger.info("没有发现可恢复的项目")
                return

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
            self._load_project(target_path)
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
            result = QMessageBox.information(
                self, "发现新版本",
                f"发现新版本 v{release_info.version}\n\n"
                f"当前版本: v{APP_VERSION}\n\n"
                f"是否立即查看更新详情？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if result == QMessageBox.StandardButton.Yes:
                self._on_check_update()

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

        if self._config:
            self.json_preview.set_config(self._config, self._base_dir)
            self.video_preview.set_epconfig(self._config)
            target_w, target_h = self._get_target_resolution()
            self.video_preview.set_target_resolution(target_w, target_h)
            self.intro_preview.set_target_resolution(target_w, target_h)

    def _on_video_file_selected(self, path: str):
        """视频文件被选择"""
        logger.info(f"视频文件被选择: {path}")

        import os
        path_exists = os.path.exists(path)
        logger.info(f"路径存在检查: {path_exists}")

        try:
            path_exists_raw = os.path.exists(path)
            logger.info(f"原始路径检查: {path_exists_raw}")

            if isinstance(path, str):
                path_exists_unicode = os.path.exists(path)
                logger.info(f"Unicode 路径检查: {path_exists_unicode}")
        except Exception as e:
            logger.error(f"路径检查出错: {e}")

        if path:
            logger.info("尝试加载文件...")
            try:
                ext = os.path.splitext(path)[1].lower()
                image_extensions = [".jpg", ".jpeg", ".png", ".bmp", ".gif"]

                if ext in image_extensions:
                    logger.info("加载图片文件...")
                    self.video_preview.load_static_image_from_file(path)
                else:
                    logger.info("加载视频文件...")
                    self.video_preview.load_video(path)

                logger.info("将时间轴连接到video_preview")
                self._connect_timeline_to_preview(self.video_preview)

                if hasattr(
                        self,
                        'basic_config_panel') and self.basic_config_panel.isVisible():
                    logger.info("基础模式下，不自动切换标签页")
                else:
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
                self.preview_tabs.setCurrentIndex(0)
        else:
            logger.warning(f"入场视频文件不存在: {path}")

    def _on_setting_changed(self, setting_name: str, value):
        """SettingsPage 发射的统一设置变更处理器"""
        logger.info(f"应用设置: {setting_name} = {value}")

        try:
            import json
            config_dir = os.path.join(
                self._app_dir, "config")
            config_file = os.path.join(config_dir, "user_settings.json")

            settings = {}
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    settings = json.load(f)

            settings[setting_name] = value

            if setting_name == 'theme_image' and value:
                settings['theme'] = '自定义图片'

            os.makedirs(config_dir, exist_ok=True)
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)

            self._apply_instant_settings(setting_name, value)

            self.status_bar.showMessage(f"设置已应用: {setting_name}")

        except Exception as e:
            logger.error(f"应用设置失败: {e}")
            self.status_bar.showMessage(f"应用设置失败: {str(e)}")

    def _apply_instant_settings(self, setting_name, value):
        """应用即时生效的设置"""
        if setting_name == 'show_status_bar':
            self.statusBar().setVisible(value)

        elif setting_name == 'theme':
            self._apply_theme_change(value)

        elif setting_name == 'theme_color':
            self._apply_theme_color(value)

        elif setting_name == 'theme_image':
            if value:
                self._apply_theme_image(value)

        elif setting_name == 'hardware_acceleration':
            for preview in [self.video_preview, self.intro_preview,
                            self.frame_capture_preview]:
                if hasattr(preview, 'set_use_gl'):
                    preview.set_use_gl(bool(value))

        elif setting_name == 'scale':
            logger.info(f"界面缩放已设置为: {value}")

        elif setting_name.startswith('ssh_'):
            # SSH 设置变更后同步到 RemotePage 的内存缓存
            if hasattr(self, '_remote_page'):
                self._remote_page._ssh_config[setting_name] = value

        elif setting_name == 'auto_save':
            if value:
                self._auto_save_service.config.enabled = True
                # 如果有项目打开，重启定时器
                if self._config and self._project_path:
                    self._auto_save_service.start(
                        self._config, self._project_path, self._base_dir)
            else:
                self._auto_save_service.config.enabled = False
                self._auto_save_service.stop()

    def _apply_theme_change(self, theme_name):
        """应用主题变化"""
        logger.info(f"应用主题: {theme_name}")

        try:
            import json
            config_dir = os.path.join(
                self._app_dir, "config")
            config_file = os.path.join(config_dir, "user_settings.json")

            settings = {}
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    settings = json.load(f)

            if theme_name == '默认':
                self._apply_default_theme()
            elif theme_name == '自定义':
                theme_color = settings.get('theme_color', '#ff6b8b')
                self._apply_theme_color(theme_color)
            elif theme_name == '自定义图片':
                theme_color = settings.get('theme_color', '#ff6b8b')
                self._apply_theme_color(theme_color)
                theme_image = settings.get('theme_image', '')
                if theme_image:
                    self._apply_theme_image(theme_image)

        except Exception as e:
            logger.error(f"应用主题失败: {e}")

    def _apply_default_theme(self):
        """应用默认主题"""
        self._apply_theme_color('#ff6b8b')

    def _apply_light_theme(self):
        """应用浅色主题"""
        self._apply_theme_color('#4CAF50')

    def _apply_dark_theme(self):
        """应用深色主题"""
        self._apply_theme_color('#2196F3')

    def _apply_theme_color(self, color_hex):
        """应用主题颜色到界面"""
        self._bg_color = self._dark_bg_color if isDarkTheme() else self._light_bg_color
        self._bg_pixmap = None
        self.setStyleSheet("")  # 清除 _apply_theme_image 残留的全局 QSS
        self.update()

        if hasattr(self, 'header_bar'):
            header_qss = f"QWidget {{ background-color: {color_hex}; color: white; border-top-left-radius: 16px; border-top-right-radius: 16px; }} QLabel {{ font-weight: bold; font-size: 16px; }}"
            setCustomStyleSheet(self.header_bar, header_qss, header_qss)

        if hasattr(self, 'sidebar'):
            sidebar_qss = f"QWidget {{ background-color: {color_hex}; border-bottom-right-radius: 16px; }}"
            setCustomStyleSheet(self.sidebar, sidebar_qss, sidebar_qss)

        if hasattr(self, 'content_stack'):
            content_light = "#content_stack { background-color: rgba(255, 255, 255, 0.95); }"
            content_dark = "#content_stack { background-color: rgba(30, 30, 30, 0.95); }"
            setCustomStyleSheet(self.content_stack, content_light, content_dark)

        nav_buttons = [
            'btn_nav_file',
            'btn_nav_basic',
            'btn_nav_advanced',
            'btn_nav_help']
        for btn_name in nav_buttons:
            if hasattr(self, btn_name):
                btn = getattr(self, btn_name)
                nav_qss = "QPushButton { background-color: transparent; color: white; border: none; padding: 10px 20px; font-size: 14px; border-radius: 6px; } QPushButton:hover { background-color: rgba(255, 255, 255, 0.2); } QPushButton:pressed, QPushButton:checked { background-color: rgba(255, 255, 255, 0.3); }"
                setCustomStyleSheet(btn, nav_qss, nav_qss)

        for btn in [
                self.btn_firmware,
                self.btn_material,
                self.btn_forum,
                self.btn_about,
                self.btn_remote,
                self.btn_settings]:
            light_qss = (
                f"QToolButton {{ background-color: {COLOR_BG_ELEVATED[0]}; color: {COLOR_TEXT_PRIMARY[0]}; "
                f"border: 1px solid #e9ecef; border-radius: 10px; padding: 14px 20px; "
                f"text-align: left; font-size: 15px; margin: 8px; }} "
                f"QToolButton:hover {{ background-color: {color_hex}20; border-color: {color_hex}; }} "
                f"QToolButton:pressed, QToolButton:checked {{ background-color: {color_hex}; color: white; border-color: {color_hex}; }}"
            )
            dark_qss = (
                f"QToolButton {{ background-color: {COLOR_BG_ELEVATED[1]}; color: {COLOR_TEXT_PRIMARY[1]}; "
                f"border: 1px solid {COLOR_BORDER[1]}; border-radius: 10px; padding: 14px 20px; "
                f"text-align: left; font-size: 15px; margin: 8px; }} "
                f"QToolButton:hover {{ background-color: {color_hex}30; border-color: {color_hex}; }} "
                f"QToolButton:pressed, QToolButton:checked {{ background-color: {color_hex}; color: white; border-color: {color_hex}; }}"
            )
            setCustomStyleSheet(btn, light_qss, dark_qss)

        logger.info(f"应用主题颜色: {color_hex}")

    def _apply_theme_image(self, image_path):
        """应用主题图片到界面（带有毛玻璃效果）"""
        logger.info(f"应用主题图片: {image_path}")

        theme_color = "#ff6b8b"
        try:
            import json
            config_dir = os.path.join(
                self._app_dir, "config")
            config_file = os.path.join(config_dir, "user_settings.json")
            
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                    theme_color = settings.get('theme_color', '#ff6b8b')
        except Exception as e:
            logger.error(f"加载主题颜色失败: {e}")

        # 将背景图片加载到 _bg_pixmap，由 paintEvent 绘制（支持圆角裁剪）
        # 不再使用 QSS background-image（QSS 不裁剪窗口形状）
        from PyQt6.QtGui import QPixmap
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            self._bg_pixmap = pixmap
        else:
            logger.warning(f"主题图片加载失败: {image_path}")
            self._bg_pixmap = None

        # 设置子 widget 样式（QMainWindow 背景由 paintEvent 绘制）
        try:
            is_dark = isDarkTheme()

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

            style = """
                QWidget#content_stack {
                    background-color: %s;
                }

                QWidget#header_bar {
                    background-color: %s;
                    border-top-left-radius: 16px;
                    border-top-right-radius: 16px;
                }

                QWidget#sidebar {
                    background-color: %s;
                    border-top-right-radius: 0px;
                    border-bottom-left-radius: 0px;
                    border-bottom-right-radius: 16px;
                }

                QStatusBar {
                    background-color: %s;
                    color: %s;
                    border-top: 1px solid %s;
                }

                QStatusBar::item {
                    border: none;
                }
            """

            self.setStyleSheet(style % (content_bg, theme_color, theme_color, status_bg, status_color, status_border))
            self.update()  # 触发 paintEvent 重绘

            logger.info("主题图片已应用，带有半透明效果")
        except Exception as e:
            logger.error(f"应用主题图片失败: {e}")

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
            self.timeline.rotation_value_changed.disconnect()
        except TypeError:
            pass

        self.timeline.play_pause_clicked.connect(preview.toggle_play)
        self.timeline.seek_requested.connect(preview.seek_to_frame)
        self.timeline.prev_frame_clicked.connect(preview.prev_frame)
        self.timeline.next_frame_clicked.connect(preview.next_frame)
        self.timeline.goto_start_clicked.connect(
            lambda: preview.seek_to_frame(0))
        self.timeline.goto_end_clicked.connect(
            lambda: preview.seek_to_frame(preview.total_frames - 1)
        )
        self.timeline.rotation_value_changed.connect(preview.set_rotation)

        self._timeline_preview = preview

        if hasattr(preview, 'total_frames') and preview.total_frames > 0:
            self.timeline.set_total_frames(preview.total_frames)
            if hasattr(preview, 'video_fps'):
                self.timeline.set_fps(preview.video_fps)
            if hasattr(preview, 'current_frame_index'):
                self.timeline.set_current_frame(preview.current_frame_index)
            self.timeline.set_rotation(preview.get_rotation())
            if hasattr(preview, 'is_playing'):
                self.timeline.set_playing(preview.is_playing)

        try:
            preview.frame_changed.disconnect(self._on_video_frame_changed)
        except TypeError:
            pass
        preview.frame_changed.connect(self._on_video_frame_changed)

    def _on_video_frame_changed(self, frame):
        """视频帧变更时更新截取帧编辑页面"""
        if self.preview_tabs.currentIndex() == 1 and hasattr(self,
                                                             '_current_video_preview'):
            source_preview = self._current_video_preview
            frame = source_preview.current_frame
            if frame is not None:
                from gui.widgets.video_preview import VideoPreviewWidget
                frame = frame.copy()
                rotation = source_preview.get_rotation()
                frame = VideoPreviewWidget.apply_rotation_to_frame(frame, rotation)
                self.frame_capture_preview.update_static_frame(frame)
                logger.info(
                    f"更新截取帧编辑页面，帧: {source_preview.current_frame_index}")

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
            self._connect_timeline_to_preview(self.intro_preview)
            self.timeline.set_in_point(self._intro_in_out[0])
            self.timeline.set_out_point(self._intro_in_out[1])
            self.timeline.show()
            logger.debug("切换到入场视频预览")
        elif index == 1:
            if hasattr(
                    self,
                    '_current_video_preview') and self._current_video_preview:
                logger.debug("连接时间轴到保存的视频预览器")
                self._connect_timeline_to_preview(self._current_video_preview)
            else:
                logger.debug("连接时间轴到默认视频预览器")
                self._connect_timeline_to_preview(self.video_preview)
            self.timeline.show()
            logger.debug("切换到截取帧编辑")
        elif index == 2:
            self.timeline.hide()
            logger.debug("切换到过渡图片预览")
        elif index == 3:
            self._connect_timeline_to_preview(self.video_preview)
            self.timeline.set_in_point(self._loop_in_out[0])
            self.timeline.set_out_point(self._loop_in_out[1])
            self.timeline.show()
            logger.debug("切换到循环视频预览")

        if hasattr(self, '_drop_overlay'):
            self._update_drop_context()

    def _on_intro_video_loaded(self, total_frames: int, fps: float):
        """入场视频加载完成"""
        if self.preview_tabs.currentIndex() == 0:
            self.timeline.set_total_frames(total_frames)
            self.timeline.set_fps(fps)
            self.timeline.set_in_point(0)
            self.timeline.set_out_point(total_frames - 1)
        self._intro_in_out = (0, total_frames - 1)
        self.status_bar.showMessage(
            f"入场视频已加载: {total_frames} 帧, {fps:.1f} FPS")

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
        """加载循环图片到预览器（以循环视频方式预览）"""
        self._loop_image_path = path
        logger.info(f"加载循环图片: {path}")

        if self.video_preview.load_image_as_loop(path):
            self.status_bar.showMessage(
                f"图片已加载为循环视频: "
                f"{self.video_preview.video_width}x"
                f"{self.video_preview.video_height}"
            )
            self._connect_timeline_to_preview(self.video_preview)
        else:
            logger.error(f"无法加载图片: {path}")
            self.video_preview.video_label.setText(f"无法加载图片: {path}")

    def _on_loop_mode_changed(self, is_image: bool):
        """循环模式切换"""
        if self._initializing:
            return

        self.video_preview.clear()
        self._loop_image_path = None

        self.timeline.set_total_frames(0)
        self._loop_in_out = (0, 0)

        logger.info(f"循环模式切换为: {'图片' if is_image else '视频'}")

        if hasattr(self, '_drop_overlay'):
            self._update_drop_context()

    def _get_active_config_panel(self):
        """获取当前活动的配置面板（基础或高级）"""
        if hasattr(self, 'basic_config_panel') and \
                self.basic_config_panel.isVisible():
            return self.basic_config_panel
        return self.advanced_config_panel

    # ---- 拖放支持 ----

    def _setup_drop_support(self):
        """初始化拖放支持"""
        self._drop_overlay = DropOverlayWidget(self.preview_container)
        self._drop_overlay.file_dropped.connect(self._on_file_dropped)
        self._update_drop_context()

        self.json_preview.json_file_dropped.connect(self._on_json_file_dropped)

    def _update_drop_context(self):
        """根据当前标签页更新拖放接受的文件类型和提示文字"""
        tab_index = self.preview_tabs.currentIndex()

        if tab_index == 3:  # 循环视频/图片 — 始终接受两种格式
            self._drop_overlay.set_context(
                SUPPORTED_VIDEO_FORMATS + SUPPORTED_IMAGE_FORMATS,
                "释放以导入循环素材"
            )
        elif tab_index == 0:  # 入场视频
            self._drop_overlay.set_context(
                SUPPORTED_VIDEO_FORMATS,
                "释放以导入入场视频"
            )
        elif tab_index == 2:  # 过渡图片
            self._drop_overlay.set_context(
                SUPPORTED_IMAGE_FORMATS,
                "释放以导入过渡图片"
            )
        else:  # Tab 1 截取帧编辑等
            self._drop_overlay.set_context(
                SUPPORTED_VIDEO_FORMATS + SUPPORTED_IMAGE_FORMATS,
                "释放以导入文件"
            )

    def _on_json_file_dropped(self, file_path: str):
        """处理拖放到JSON预览面板的配置文件"""
        logger.info(f"JSON配置文件拖放导入: {file_path}")
        self._load_project(file_path)

    def _on_file_dropped(self, file_path: str, drop_pos):
        """处理拖放文件 — 根据上下文分发到对应处理逻辑"""
        tab_index = self.preview_tabs.currentIndex()
        logger.info(f"文件拖放: {file_path}, 标签页: {tab_index}")

        if tab_index == 3:  # 循环视频/图片
            self._handle_drop_loop(file_path)
        elif tab_index == 0:  # 入场视频
            self._handle_drop_intro(file_path)
        elif tab_index == 2:  # 过渡图片
            self._handle_drop_transition(file_path, drop_pos)
        else:
            self._handle_drop_loop(file_path)

    def _handle_drop_loop(self, file_path: str):
        """处理拖放到循环视频/图片标签页"""
        ext = os.path.splitext(file_path)[1].lower()
        is_image = ext in SUPPORTED_IMAGE_FORMATS

        config_panel = self._get_active_config_panel()

        # 自动切换循环模式以匹配拖放文件类型
        if hasattr(config_panel, 'radio_loop_image'):
            if is_image and not config_panel.radio_loop_image.isChecked():
                config_panel.radio_loop_image.setChecked(True)
            elif not is_image and hasattr(
                    config_panel, 'radio_loop_video'
            ) and not config_panel.radio_loop_video.isChecked():
                config_panel.radio_loop_video.setChecked(True)

        rel_path = config_panel._copy_to_project_dir(file_path, "loop")
        config_panel.edit_loop_file.setText(rel_path or file_path)

        if is_image and hasattr(config_panel, 'loop_image_selected'):
            config_panel.loop_image_selected.emit(file_path)
        else:
            # 基础模式无 loop_image_selected，图片也走 video_file_selected
            config_panel.video_file_selected.emit(file_path)

    def _handle_drop_intro(self, file_path: str):
        """处理拖放到入场视频标签页"""
        config_panel = self.advanced_config_panel
        rel_path = config_panel._copy_to_project_dir(file_path, "intro")
        config_panel.edit_intro_file.setText(rel_path or file_path)
        config_panel.intro_video_selected.emit(file_path)

    def _handle_drop_transition(self, file_path: str, drop_pos):
        """处理拖放到过渡图片标签页"""
        # 根据鼠标释放位置判断是进入过渡(左半)还是循环过渡(右半)
        mapped_pos = self.transition_preview.mapFrom(
            self.preview_container, drop_pos)
        mid_x = self.transition_preview.width() // 2
        trans_type = "in" if mapped_pos.x() < mid_x else "loop"
        logger.info(f"过渡图片拖放: type={trans_type}, pos={mapped_pos.x()}")
        self.advanced_config_panel._process_transition_image(
            file_path, trans_type)

    def _on_transition_image_changed(self, trans_type: str, abs_path: str):
        """过渡图片变更"""
        self.transition_preview.load_image(trans_type, abs_path)
        self.preview_tabs.setCurrentIndex(2)

    def _on_transition_crop_changed(self, trans_type: str):
        """过渡图片 cropbox 变化 → 裁切原始图片并保存"""
        if not self._base_dir:
            return

        import cv2
        import glob

        pattern = os.path.join(self._base_dir, f"trans_{trans_type}_src.*")
        matches = glob.glob(pattern)
        if not matches:
            return

        src_path = matches[0]
        original = cv2.imread(src_path, cv2.IMREAD_UNCHANGED)
        if original is None:
            return

        x, y, w, h = self.transition_preview.get_cropbox(trans_type)

        img_h, img_w = original.shape[:2]
        x = max(0, min(x, img_w - 1))
        y = max(0, min(y, img_h - 1))
        w = min(w, img_w - x)
        h = min(h, img_h - y)

        if w <= 0 or h <= 0:
            return

        cropped = original[y:y + h, x:x + w]

        target_w, target_h = self._get_target_resolution()
        resized = cv2.resize(cropped, (target_w, target_h),
                             interpolation=cv2.INTER_AREA)

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

        from gui.widgets.video_preview import VideoPreviewWidget

        frame = frame.copy()
        rotation = source_preview.get_rotation()
        logger.info(f"旋转变换: {rotation}度")
        frame = VideoPreviewWidget.apply_rotation_to_frame(frame, rotation)

        logger.info(f"加载到截取帧编辑预览，帧尺寸: {frame.shape}")
        self.frame_capture_preview.load_static_image_from_array(frame)

        self._current_video_preview = source_preview

        logger.info("连接时间轴到原始视频预览器")
        self._connect_timeline_to_preview(source_preview)

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

            cropbox = self.frame_capture_preview.get_cropbox()
            logger.info(f"裁剪框: {cropbox}")

            if len(cropbox) != 4:
                logger.error(f"裁剪框格式错误: {cropbox}")
                QMessageBox.warning(self, "错误", "裁剪框格式错误")
                return

            x, y, w, h = cropbox

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

            logger.info("开始裁剪帧")
            cropped = frame[y:y + h, x:x + w]
            logger.info(f"裁剪后的尺寸: {cropped.shape}")

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

        icon_path = self._config.icon
        if icon_path:
            if not os.path.isabs(icon_path):
                icon_path = os.path.join(self._base_dir, icon_path)
            if os.path.exists(icon_path):
                logo_img = ImageProcessor.load_image(icon_path)
                if logo_img is not None:
                    data['logo_mat'] = ImageProcessor.process_for_logo(
                        logo_img)

        if self._config.loop.is_image:
            if hasattr(self, '_loop_image_path') and self._loop_image_path:
                data['loop_image_path'] = self._loop_image_path
                data['is_loop_image'] = True
        elif self.video_preview.video_path:
            cropbox = self.video_preview.get_cropbox_in_rotated_space()
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

        if self._config.intro.enabled and self._config.intro.file:
            if self.intro_preview.video_path:
                cropbox = self.intro_preview.get_cropbox_in_rotated_space()
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
                intro_path = self._config.intro.file
                if not os.path.isabs(intro_path):
                    intro_path = os.path.join(self._base_dir, intro_path)

                if os.path.exists(intro_path):
                    try:
                        import av
                    except ImportError:
                        logger.warning("PyAV 不可用，跳过片头视频元数据读取")
                        av = None

                    try:
                        if av is None:
                            raise RuntimeError("PyAV unavailable")
                        container = av.open(intro_path)
                        stream = container.streams.video[0]
                        fps = float(stream.average_rate) if stream.average_rate else 30.0
                        width = stream.width
                        height = stream.height
                        total_frames = stream.frames
                        if total_frames == 0 and stream.duration and stream.time_base:
                            total_frames = max(1, int(
                                float(stream.duration * stream.time_base) * fps))
                        if total_frames == 0:
                            total_frames = 1
                        container.close()

                        data['intro_video_params'] = VideoExportParams(
                            video_path=intro_path,
                            cropbox=(0, 0, width, height),
                            start_frame=0,
                            end_frame=total_frames,
                            fps=fps,
                            resolution=self._config.screen.value,
                            rotation=0
                        )
                    except Exception as e:
                        logger.warning(f"无法读取片头视频元数据: {e}")

        from config.epconfig import OverlayType
        if self._config.overlay.type == OverlayType.IMAGE:
            if self._config.overlay.image_options and self._config.overlay.image_options.image:
                img_path = self._config.overlay.image_options.image
                if not os.path.isabs(img_path):
                    img_path = os.path.join(self._base_dir, img_path)
                if os.path.exists(img_path):
                    overlay_img = ImageProcessor.load_image(img_path)
                    if overlay_img is not None:
                        spec = get_resolution_spec(self._config.screen.value)
                        target_size = (spec['width'], spec['height'])

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

        if self._config.overlay.type != OverlayType.ARKNIGHTS:
            return

        ark_opts = self._config.overlay.arknights_options
        if not ark_opts:
            return

        if ark_opts.operator_class_icon:
            src_path = ark_opts.operator_class_icon
            if not os.path.isabs(src_path):
                src_path = os.path.join(self._base_dir, src_path)

            if os.path.exists(src_path):
                img = ImageProcessor.load_image(src_path)
                if img is not None:
                    img = cv2.resize(img, ARK_CLASS_ICON_SIZE)
                    dst_filename = "class_icon.png"
                    dst_path = os.path.join(output_dir, dst_filename)
                    success, encoded = cv2.imencode('.png', img)
                    if success:
                        with open(dst_path, 'wb') as f:
                            f.write(encoded.tobytes())
                        logger.info(f"已导出职业图标: {dst_path}")

        if ark_opts.logo:
            src_path = ark_opts.logo
            if not os.path.isabs(src_path):
                src_path = os.path.join(self._base_dir, src_path)

            if os.path.exists(src_path):
                img = ImageProcessor.load_image(src_path)
                if img is not None:
                    img = cv2.resize(img, ARK_LOGO_SIZE)
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

    def _on_ssh_upload_completed(self, success: bool, message: str):
        """SSH 上传完成回调"""
        if hasattr(self, '_ssh_upload_dialog') and self._ssh_upload_dialog:
            self._ssh_upload_dialog.set_completed(success, message)

        if success:
            self.status_bar.showMessage(message)
            logger.info(f"SSH 上传成功: {message}")
        else:
            self.status_bar.showMessage("SSH 上传失败")
            logger.error(f"SSH 上传失败: {message}")

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

    def paintEvent(self, event):
        """绘制圆角窗口背景

        CSS border-radius 仅影响绘制不裁剪窗口形状（Qt 文档：
        "Stylesheets only affect painting. They do not change the widget's
        geometry, mask, or hit-testing."）。
        必须配合 WA_TranslucentBackground + QPainterPath 实现真正裁剪。
        """
        from PyQt6.QtGui import QPainter, QPainterPath, QColor
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 最大化时不圆角
        radius = 0.0 if self.isMaximized() else self._corner_radius
        rect = self.rect().toRectF()

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(path)

        if self._bg_pixmap:
            scaled = self._bg_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation)
            x = (scaled.width() - self.width()) // 2
            y = (scaled.height() - self.height()) // 2
            painter.drawPixmap(0, 0, scaled, x, y,
                               self.width(), self.height())
        else:
            painter.fillRect(rect, QColor(self._bg_color))

        painter.end()

    def showEvent(self, event):
        """窗口显示时设置 DWM 圆角（Windows 11）"""
        super().showEvent(event)
        if sys.platform == 'win32' and not getattr(self, '_dwm_corner_set', False):
            self._dwm_corner_set = True
            try:
                ver = sys.getwindowsversion()
                if ver.build >= 22000:  # Windows 11
                    from ctypes import windll, byref, c_int
                    DWMWA_WINDOW_CORNER_PREFERENCE = 33
                    DWMWCP_ROUND = 2
                    windll.dwmapi.DwmSetWindowAttribute(
                        int(self.winId()),
                        DWMWA_WINDOW_CORNER_PREFERENCE,
                        byref(c_int(DWMWCP_ROUND)), 4
                    )
            except Exception:
                pass

    def closeEvent(self, event):
        """关闭事件"""
        if self._check_save():
            self._save_settings()
            self._cleanup_temp_dir()

            self._auto_save_service.stop()

            if hasattr(self, '_forum_widget'):
                self._forum_widget.shutdown()

            if hasattr(self, '_remote_page'):
                self._remote_page.shutdown()

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
            cursor, direction = self.cursorAtPosition(event.pos())
            if direction:
                self._is_resizing = True
                self._resize_direction = direction
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geometry = self.geometry()

    def mouseMoveEvent(self, event):
        """鼠标移动事件，执行窗口大小调整或更新光标"""
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
            cursor, _ = self.cursorAtPosition(event.pos())
            self.setCursor(cursor)

    def mouseReleaseEvent(self, event):
        """鼠标释放事件，结束窗口大小调整"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_resizing = False
            self._resize_direction = None
