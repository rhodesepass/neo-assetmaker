"""
配置面板 - 左侧配置选项卡容器
"""
import os
import shutil
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QScrollArea,
    QGroupBox, QFormLayout, QLineEdit, QTextEdit,
    QComboBox, QSpinBox, QCheckBox, QPushButton,
    QHBoxLayout, QLabel, QFileDialog, QColorDialog
)
from PyQt6.QtCore import pyqtSignal, Qt

from config.epconfig import (
    EPConfig, ScreenType, TransitionType, OverlayType,
    Transition, TransitionOptions, IntroConfig,
    Overlay, ArknightsOverlayOptions, ImageOverlayOptions
)
from config.constants import (
    RESOLUTION_SPECS, TRANSITION_TYPES, OVERLAY_TYPES,
    OPERATOR_CLASS_PRESETS, DEFAULT_TRANSITION_DURATION,
    microseconds_to_seconds, seconds_to_microseconds
)


class ConfigPanel(QWidget):
    """配置面板"""

    config_changed = pyqtSignal()  # 配置变更信号
    video_file_selected = pyqtSignal(str)  # 视频文件选择信号
    validate_requested = pyqtSignal()  # 验证配置请求信号
    export_requested = pyqtSignal()  # 导出素材请求信号
    capture_frame_requested = pyqtSignal()  # 截取视频帧请求信号

    def __init__(self, parent=None):
        super().__init__(parent)

        self._config: Optional[EPConfig] = None
        self._base_dir: str = ""
        self._updating = False  # 防止循环更新

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(0)

        # 选项卡
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        # 基本信息选项卡
        self.tab_basic = self._create_basic_tab()
        self.tab_widget.addTab(self.tab_basic, "基本信息")

        # 视频配置选项卡
        self.tab_video = self._create_video_tab()
        self.tab_widget.addTab(self.tab_video, "视频配置")

        # 过渡效果选项卡
        self.tab_transition = self._create_transition_tab()
        self.tab_widget.addTab(self.tab_transition, "过渡效果")

        # 叠加UI选项卡
        self.tab_overlay = self._create_overlay_tab()
        self.tab_widget.addTab(self.tab_overlay, "叠加UI")

        self.setMinimumWidth(350)
        self.setMaximumWidth(450)

    def _create_scroll_area(self, widget: QWidget) -> QScrollArea:
        """创建滚动区域"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        # 设置内部widget的边距
        widget.layout().setContentsMargins(8, 8, 8, 8)
        return scroll

    def _create_basic_tab(self) -> QWidget:
        """创建基本信息选项卡"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # UUID
        group_uuid = QGroupBox("UUID")
        uuid_layout = QHBoxLayout(group_uuid)
        self.edit_uuid = QLineEdit()
        self.edit_uuid.setReadOnly(True)
        uuid_layout.addWidget(self.edit_uuid)
        self.btn_new_uuid = QPushButton("生成新UUID")
        uuid_layout.addWidget(self.btn_new_uuid)
        layout.addWidget(group_uuid)

        # 基本信息
        group_info = QGroupBox("基本信息")
        info_layout = QFormLayout(group_info)

        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("素材名称")
        info_layout.addRow("名称:", self.edit_name)

        self.edit_description = QTextEdit()
        self.edit_description.setMaximumHeight(80)
        self.edit_description.setPlaceholderText("素材描述")
        info_layout.addRow("描述:", self.edit_description)

        self.combo_screen = QComboBox()
        for screen in RESOLUTION_SPECS:
            desc = RESOLUTION_SPECS[screen].get("description", screen)
            self.combo_screen.addItem(desc, screen)
        info_layout.addRow("分辨率:", self.combo_screen)

        layout.addWidget(group_info)

        # 图标
        group_icon = QGroupBox("图标")
        icon_layout = QHBoxLayout(group_icon)
        self.edit_icon = QLineEdit()
        self.edit_icon.setPlaceholderText("图标文件路径")
        icon_layout.addWidget(self.edit_icon)
        self.btn_browse_icon = QPushButton("浏览...")
        icon_layout.addWidget(self.btn_browse_icon)
        self.btn_capture_frame = QPushButton("截取视频帧")
        icon_layout.addWidget(self.btn_capture_frame)
        layout.addWidget(group_icon)

        layout.addStretch()
        return self._create_scroll_area(widget)

    def _create_video_tab(self) -> QWidget:
        """创建视频配置选项卡"""
        from PyQt6.QtWidgets import QRadioButton, QButtonGroup
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 循环视频
        group_loop = QGroupBox("循环视频 (必选)")
        loop_main_layout = QVBoxLayout(group_loop)

        # 模式选择
        mode_layout = QHBoxLayout()
        self.radio_loop_video = QRadioButton("视频")
        self.radio_loop_image = QRadioButton("图片")
        self.radio_loop_video.setChecked(True)
        self.loop_mode_group = QButtonGroup()
        self.loop_mode_group.addButton(self.radio_loop_video, 0)
        self.loop_mode_group.addButton(self.radio_loop_image, 1)
        mode_layout.addWidget(QLabel("模式:"))
        mode_layout.addWidget(self.radio_loop_video)
        mode_layout.addWidget(self.radio_loop_image)
        mode_layout.addStretch()
        loop_main_layout.addLayout(mode_layout)

        # 文件选择
        file_layout = QHBoxLayout()
        self.edit_loop_file = QLineEdit()
        self.edit_loop_file.setPlaceholderText("loop.mp4")
        file_layout.addWidget(self.edit_loop_file)
        self.btn_browse_loop = QPushButton("浏览...")
        file_layout.addWidget(self.btn_browse_loop)
        loop_main_layout.addLayout(file_layout)

        layout.addWidget(group_loop)

        # 入场视频
        group_intro = QGroupBox("入场视频 (可选)")
        intro_layout = QFormLayout(group_intro)

        self.check_intro_enabled = QCheckBox("启用入场动画")
        intro_layout.addRow(self.check_intro_enabled)

        intro_file_layout = QHBoxLayout()
        self.edit_intro_file = QLineEdit()
        self.edit_intro_file.setPlaceholderText("intro.mp4")
        intro_file_layout.addWidget(self.edit_intro_file)
        self.btn_browse_intro = QPushButton("浏览...")
        intro_file_layout.addWidget(self.btn_browse_intro)
        intro_layout.addRow("文件:", intro_file_layout)

        self.spin_intro_duration = QSpinBox()
        self.spin_intro_duration.setRange(0, 30000000)
        self.spin_intro_duration.setSingleStep(100000)
        self.spin_intro_duration.setSuffix(" 微秒")
        self.spin_intro_duration.setValue(5000000)
        intro_layout.addRow("时长:", self.spin_intro_duration)

        self.label_intro_seconds = QLabel("= 5.0 秒")
        intro_layout.addRow("", self.label_intro_seconds)

        layout.addWidget(group_intro)

        layout.addStretch()
        return self._create_scroll_area(widget)

    def _create_transition_tab(self) -> QWidget:
        """创建过渡效果选项卡"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 进入过渡
        group_in = QGroupBox("进入过渡 (transition_in)")
        in_layout = QFormLayout(group_in)

        self.combo_trans_in_type = QComboBox()
        for t in TRANSITION_TYPES:
            self.combo_trans_in_type.addItem(t, t)
        in_layout.addRow("类型:", self.combo_trans_in_type)

        self.spin_trans_in_duration = QSpinBox()
        self.spin_trans_in_duration.setRange(0, 5000000)
        self.spin_trans_in_duration.setSingleStep(50000)
        self.spin_trans_in_duration.setValue(500000)
        in_layout.addRow("时长(微秒):", self.spin_trans_in_duration)

        color_layout_in = QHBoxLayout()
        self.edit_trans_in_color = QLineEdit("#000000")
        color_layout_in.addWidget(self.edit_trans_in_color)
        self.btn_trans_in_color = QPushButton("选择颜色")
        color_layout_in.addWidget(self.btn_trans_in_color)
        in_layout.addRow("背景色:", color_layout_in)

        # 进入过渡图片
        image_layout_in = QHBoxLayout()
        self.edit_trans_in_image = QLineEdit()
        self.edit_trans_in_image.setPlaceholderText("可选，用于过渡效果的图片")
        image_layout_in.addWidget(self.edit_trans_in_image)
        self.btn_trans_in_image = QPushButton("浏览...")
        self.btn_trans_in_image.clicked.connect(lambda: self._browse_transition_image("in"))
        image_layout_in.addWidget(self.btn_trans_in_image)
        in_layout.addRow("过渡图片:", image_layout_in)

        layout.addWidget(group_in)

        # 循环过渡
        group_loop = QGroupBox("循环过渡 (transition_loop)")
        loop_layout = QFormLayout(group_loop)

        self.combo_trans_loop_type = QComboBox()
        for t in TRANSITION_TYPES:
            self.combo_trans_loop_type.addItem(t, t)
        loop_layout.addRow("类型:", self.combo_trans_loop_type)

        self.spin_trans_loop_duration = QSpinBox()
        self.spin_trans_loop_duration.setRange(0, 5000000)
        self.spin_trans_loop_duration.setSingleStep(50000)
        self.spin_trans_loop_duration.setValue(500000)
        loop_layout.addRow("时长(微秒):", self.spin_trans_loop_duration)

        color_layout_loop = QHBoxLayout()
        self.edit_trans_loop_color = QLineEdit("#000000")
        color_layout_loop.addWidget(self.edit_trans_loop_color)
        self.btn_trans_loop_color = QPushButton("选择颜色")
        color_layout_loop.addWidget(self.btn_trans_loop_color)
        loop_layout.addRow("背景色:", color_layout_loop)

        # 循环过渡图片
        image_layout_loop = QHBoxLayout()
        self.edit_trans_loop_image = QLineEdit()
        self.edit_trans_loop_image.setPlaceholderText("可选，用于过渡效果的图片")
        image_layout_loop.addWidget(self.edit_trans_loop_image)
        self.btn_trans_loop_image = QPushButton("浏览...")
        self.btn_trans_loop_image.clicked.connect(lambda: self._browse_transition_image("loop"))
        image_layout_loop.addWidget(self.btn_trans_loop_image)
        loop_layout.addRow("过渡图片:", image_layout_loop)

        layout.addWidget(group_loop)

        layout.addStretch()
        return self._create_scroll_area(widget)

    def _create_overlay_tab(self) -> QWidget:
        """创建叠加UI选项卡"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 叠加类型
        group_type = QGroupBox("叠加类型")
        type_layout = QFormLayout(group_type)

        self.combo_overlay_type = QComboBox()
        for t in OVERLAY_TYPES:
            self.combo_overlay_type.addItem(t, t)
        type_layout.addRow("类型:", self.combo_overlay_type)

        layout.addWidget(group_type)

        # Arknights选项
        self.group_arknights = QGroupBox("明日方舟模板选项")
        ark_layout = QFormLayout(self.group_arknights)

        self.spin_ark_appear = QSpinBox()
        self.spin_ark_appear.setRange(0, 5000000)
        self.spin_ark_appear.setValue(100000)
        ark_layout.addRow("出现时间(微秒):", self.spin_ark_appear)

        self.edit_ark_name = QLineEdit("OPERATOR")
        ark_layout.addRow("干员名称:", self.edit_ark_name)

        self.edit_ark_code = QLineEdit("ARKNIGHTS - UNK0")
        ark_layout.addRow("干员代号:", self.edit_ark_code)

        self.edit_ark_barcode = QLineEdit("OPERATOR - ARKNIGHTS")
        ark_layout.addRow("条码文本:", self.edit_ark_barcode)

        self.edit_ark_aux = QTextEdit()
        self.edit_ark_aux.setMaximumHeight(60)
        self.edit_ark_aux.setPlainText("Operator of Rhodes Island")
        ark_layout.addRow("辅助文本:", self.edit_ark_aux)

        self.edit_ark_staff = QLineEdit("STAFF")
        ark_layout.addRow("STAFF文本:", self.edit_ark_staff)

        color_layout = QHBoxLayout()
        self.edit_ark_color = QLineEdit("#000000")
        color_layout.addWidget(self.edit_ark_color)
        self.btn_ark_color = QPushButton("选择颜色")
        color_layout.addWidget(self.btn_ark_color)
        ark_layout.addRow("主题颜色:", color_layout)

        # 职业图标
        class_icon_layout = QHBoxLayout()
        self.edit_ark_class_icon = QLineEdit()
        self.edit_ark_class_icon.setPlaceholderText("可选，50x50")
        self.edit_ark_class_icon.setReadOnly(True)
        class_icon_layout.addWidget(self.edit_ark_class_icon)
        self.btn_ark_class_icon = QPushButton("选择...")
        class_icon_layout.addWidget(self.btn_ark_class_icon)
        self.btn_clear_class_icon = QPushButton("清除")
        class_icon_layout.addWidget(self.btn_clear_class_icon)
        ark_layout.addRow("职业图标:", class_icon_layout)

        # Logo
        logo_layout = QHBoxLayout()
        self.edit_ark_logo = QLineEdit()
        self.edit_ark_logo.setPlaceholderText("可选，75x35")
        self.edit_ark_logo.setReadOnly(True)
        logo_layout.addWidget(self.edit_ark_logo)
        self.btn_ark_logo = QPushButton("选择...")
        logo_layout.addWidget(self.btn_ark_logo)
        self.btn_clear_logo = QPushButton("清除")
        logo_layout.addWidget(self.btn_clear_logo)
        ark_layout.addRow("Logo:", logo_layout)

        layout.addWidget(self.group_arknights)

        # Image叠加选项
        self.group_image_overlay = QGroupBox("图片叠加选项")
        img_layout = QFormLayout(self.group_image_overlay)

        self.spin_img_appear = QSpinBox()
        self.spin_img_appear.setRange(0, 5000000)
        self.spin_img_appear.setValue(100000)
        img_layout.addRow("出现时间(微秒):", self.spin_img_appear)

        self.spin_img_duration = QSpinBox()
        self.spin_img_duration.setRange(0, 5000000)
        self.spin_img_duration.setValue(100000)
        img_layout.addRow("持续时间(微秒):", self.spin_img_duration)

        image_layout = QHBoxLayout()
        self.edit_img_overlay = QLineEdit()
        self.edit_img_overlay.setPlaceholderText("overlay.png")
        image_layout.addWidget(self.edit_img_overlay)
        self.btn_img_overlay = QPushButton("浏览...")
        image_layout.addWidget(self.btn_img_overlay)
        img_layout.addRow("叠加图片:", image_layout)

        layout.addWidget(self.group_image_overlay)

        # 操作按钮
        group_actions = QGroupBox("操作")
        actions_layout = QVBoxLayout(group_actions)

        self.btn_validate = QPushButton("验证配置")
        actions_layout.addWidget(self.btn_validate)

        self.btn_export = QPushButton("导出素材")
        actions_layout.addWidget(self.btn_export)

        layout.addWidget(group_actions)

        layout.addStretch()
        return self._create_scroll_area(widget)

    def _connect_signals(self):
        """连接信号"""
        # 基本信息
        self.btn_new_uuid.clicked.connect(self._on_new_uuid)
        self.edit_name.textChanged.connect(self._on_config_changed)
        self.edit_description.textChanged.connect(self._on_config_changed)
        self.combo_screen.currentIndexChanged.connect(self._on_config_changed)
        self.edit_icon.textChanged.connect(self._on_config_changed)
        self.btn_browse_icon.clicked.connect(self._browse_icon)
        self.btn_capture_frame.clicked.connect(self.capture_frame_requested.emit)

        # 视频配置
        self.edit_loop_file.textChanged.connect(self._on_config_changed)
        self.btn_browse_loop.clicked.connect(self._browse_loop)
        self.radio_loop_video.toggled.connect(self._on_loop_mode_changed)
        self.radio_loop_image.toggled.connect(self._on_loop_mode_changed)
        self.check_intro_enabled.stateChanged.connect(self._on_config_changed)
        self.edit_intro_file.textChanged.connect(self._on_config_changed)
        self.btn_browse_intro.clicked.connect(self._browse_intro)
        self.spin_intro_duration.valueChanged.connect(self._on_intro_duration_changed)

        # 过渡效果
        self.combo_trans_in_type.currentIndexChanged.connect(self._on_config_changed)
        self.spin_trans_in_duration.valueChanged.connect(self._on_config_changed)
        self.edit_trans_in_color.textChanged.connect(self._on_config_changed)
        self.btn_trans_in_color.clicked.connect(lambda: self._pick_color(self.edit_trans_in_color))
        self.edit_trans_in_image.textChanged.connect(self._on_config_changed)

        self.combo_trans_loop_type.currentIndexChanged.connect(self._on_config_changed)
        self.spin_trans_loop_duration.valueChanged.connect(self._on_config_changed)
        self.edit_trans_loop_color.textChanged.connect(self._on_config_changed)
        self.btn_trans_loop_color.clicked.connect(lambda: self._pick_color(self.edit_trans_loop_color))
        self.edit_trans_loop_image.textChanged.connect(self._on_config_changed)

        # 叠加UI
        self.combo_overlay_type.currentIndexChanged.connect(self._on_overlay_type_changed)
        self.spin_ark_appear.valueChanged.connect(self._on_config_changed)
        self.edit_ark_name.textChanged.connect(self._on_config_changed)
        self.edit_ark_code.textChanged.connect(self._on_config_changed)
        self.edit_ark_barcode.textChanged.connect(self._on_config_changed)
        self.edit_ark_aux.textChanged.connect(self._on_config_changed)
        self.edit_ark_staff.textChanged.connect(self._on_config_changed)
        self.edit_ark_color.textChanged.connect(self._on_config_changed)
        self.btn_ark_color.clicked.connect(lambda: self._pick_color(self.edit_ark_color))
        self.btn_ark_class_icon.clicked.connect(self._on_select_class_icon)
        self.btn_clear_class_icon.clicked.connect(self._on_clear_class_icon)
        self.btn_ark_logo.clicked.connect(self._on_select_logo)
        self.btn_clear_logo.clicked.connect(self._on_clear_logo)

        # Image叠加信号
        self.spin_img_appear.valueChanged.connect(self._on_config_changed)
        self.spin_img_duration.valueChanged.connect(self._on_config_changed)
        self.edit_img_overlay.textChanged.connect(self._on_config_changed)
        self.btn_img_overlay.clicked.connect(self._on_select_img_overlay)

        # 操作按钮
        self.btn_validate.clicked.connect(self.validate_requested.emit)
        self.btn_export.clicked.connect(self.export_requested.emit)

    def set_config(self, config: EPConfig, base_dir: str = ""):
        """设置配置"""
        self._config = config
        self._base_dir = base_dir
        self._updating = True

        try:
            # 基本信息
            self.edit_uuid.setText(config.uuid)
            self.edit_name.setText(config.name)
            self.edit_description.setPlainText(config.description)
            self.edit_icon.setText(config.icon)

            # 分辨率
            index = self.combo_screen.findData(config.screen.value)
            if index >= 0:
                self.combo_screen.setCurrentIndex(index)

            # 循环视频
            self.edit_loop_file.setText(config.loop.file)
            if config.loop.is_image:
                self.radio_loop_image.setChecked(True)
            else:
                self.radio_loop_video.setChecked(True)

            # 入场视频
            self.check_intro_enabled.setChecked(config.intro.enabled)
            self.edit_intro_file.setText(config.intro.file)
            self.spin_intro_duration.setValue(config.intro.duration)

            # 过渡效果 - 进入
            if config.transition_in.type != TransitionType.NONE:
                index = self.combo_trans_in_type.findData(config.transition_in.type.value)
                if index >= 0:
                    self.combo_trans_in_type.setCurrentIndex(index)
                if config.transition_in.options:
                    self.spin_trans_in_duration.setValue(config.transition_in.options.duration)
                    self.edit_trans_in_color.setText(config.transition_in.options.background_color)
                    self.edit_trans_in_image.setText(config.transition_in.options.image or "")

            # 过渡效果 - 循环
            if config.transition_loop.type != TransitionType.NONE:
                index = self.combo_trans_loop_type.findData(config.transition_loop.type.value)
                if index >= 0:
                    self.combo_trans_loop_type.setCurrentIndex(index)
                if config.transition_loop.options:
                    self.spin_trans_loop_duration.setValue(config.transition_loop.options.duration)
                    self.edit_trans_loop_color.setText(config.transition_loop.options.background_color)
                    self.edit_trans_loop_image.setText(config.transition_loop.options.image or "")

            # 叠加UI
            index = self.combo_overlay_type.findData(config.overlay.type.value)
            if index >= 0:
                self.combo_overlay_type.setCurrentIndex(index)

            if config.overlay.arknights_options:
                opts = config.overlay.arknights_options
                self.spin_ark_appear.setValue(opts.appear_time)
                self.edit_ark_name.setText(opts.operator_name)
                self.edit_ark_code.setText(opts.operator_code)
                self.edit_ark_barcode.setText(opts.barcode_text)
                self.edit_ark_aux.setPlainText(opts.aux_text)
                self.edit_ark_staff.setText(opts.staff_text)
                self.edit_ark_color.setText(opts.color)
                self.edit_ark_class_icon.setText(opts.operator_class_icon or "")
                self.edit_ark_logo.setText(opts.logo or "")

            if config.overlay.image_options:
                opts = config.overlay.image_options
                self.spin_img_appear.setValue(opts.appear_time)
                self.spin_img_duration.setValue(opts.duration)
                self.edit_img_overlay.setText(opts.image or "")

            self._on_overlay_type_changed()

        finally:
            self._updating = False

    def get_config(self) -> Optional[EPConfig]:
        """获取配置"""
        return self._config

    def update_config_from_ui(self):
        """从UI更新配置"""
        if self._config is None:
            return

        # 基本信息
        self._config.name = self.edit_name.text()
        self._config.description = self.edit_description.toPlainText()
        self._config.icon = self.edit_icon.text()

        screen_value = self.combo_screen.currentData()
        self._config.screen = ScreenType.from_string(screen_value)

        # 循环视频
        self._config.loop.file = self.edit_loop_file.text()
        self._config.loop.is_image = self.radio_loop_image.isChecked()

        # 入场视频
        self._config.intro.enabled = self.check_intro_enabled.isChecked()
        self._config.intro.file = self.edit_intro_file.text()
        self._config.intro.duration = self.spin_intro_duration.value()

        # 过渡效果 - 进入
        trans_in_type = TransitionType.from_string(self.combo_trans_in_type.currentData())
        if trans_in_type != TransitionType.NONE:
            self._config.transition_in = Transition(
                type=trans_in_type,
                options=TransitionOptions(
                    duration=self.spin_trans_in_duration.value(),
                    background_color=self.edit_trans_in_color.text(),
                    image=self.edit_trans_in_image.text() or None
                )
            )
        else:
            self._config.transition_in = Transition()

        # 过渡效果 - 循环
        trans_loop_type = TransitionType.from_string(self.combo_trans_loop_type.currentData())
        if trans_loop_type != TransitionType.NONE:
            self._config.transition_loop = Transition(
                type=trans_loop_type,
                options=TransitionOptions(
                    duration=self.spin_trans_loop_duration.value(),
                    background_color=self.edit_trans_loop_color.text(),
                    image=self.edit_trans_loop_image.text() or None
                )
            )
        else:
            self._config.transition_loop = Transition()

        # 叠加UI
        overlay_type = OverlayType.from_string(self.combo_overlay_type.currentData())
        if overlay_type == OverlayType.ARKNIGHTS:
            self._config.overlay = Overlay(
                type=overlay_type,
                arknights_options=ArknightsOverlayOptions(
                    appear_time=self.spin_ark_appear.value(),
                    operator_name=self.edit_ark_name.text(),
                    operator_code=self.edit_ark_code.text(),
                    barcode_text=self.edit_ark_barcode.text(),
                    aux_text=self.edit_ark_aux.toPlainText(),
                    staff_text=self.edit_ark_staff.text(),
                    color=self.edit_ark_color.text(),
                    operator_class_icon=self.edit_ark_class_icon.text(),
                    logo=self.edit_ark_logo.text()
                )
            )
        elif overlay_type == OverlayType.IMAGE:
            self._config.overlay = Overlay(
                type=overlay_type,
                image_options=ImageOverlayOptions(
                    appear_time=self.spin_img_appear.value(),
                    duration=self.spin_img_duration.value(),
                    image=self.edit_img_overlay.text()
                )
            )
        else:
            self._config.overlay = Overlay(type=overlay_type)

    def _on_config_changed(self):
        """配置变更处理"""
        if self._updating:
            return
        self.update_config_from_ui()
        self.config_changed.emit()

    def _on_new_uuid(self):
        """生成新UUID"""
        if self._config:
            self._config.generate_new_uuid()
            self.edit_uuid.setText(self._config.uuid)
            self.config_changed.emit()

    def _on_intro_duration_changed(self, value: int):
        """入场时长变更"""
        seconds = microseconds_to_seconds(value)
        self.label_intro_seconds.setText(f"= {seconds:.1f} 秒")
        self._on_config_changed()

    def _on_overlay_type_changed(self):
        """叠加类型变更"""
        overlay_type = self.combo_overlay_type.currentData()
        self.group_arknights.setVisible(overlay_type == "arknights")
        self.group_image_overlay.setVisible(overlay_type == "image")
        self._on_config_changed()

    def _browse_icon(self):
        """浏览图标文件"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图标", self._base_dir,
            "图片文件 (*.png *.jpg *.jpeg)"
        )
        if path:
            # 如果项目目录已设置，复制文件到项目目录
            if self._base_dir:
                # 生成目标文件名
                filename = os.path.basename(path)
                name, ext = os.path.splitext(filename)
                dest_path = os.path.join(self._base_dir, f"icon{ext}")

                # 如果目标文件已存在且不同，生成唯一文件名
                if os.path.exists(dest_path) and not os.path.samefile(path, dest_path):
                    counter = 1
                    while os.path.exists(dest_path):
                        dest_path = os.path.join(self._base_dir, f"icon_{counter}{ext}")
                        counter += 1

                # 复制文件（如果不是同一文件）
                if not os.path.exists(dest_path) or not os.path.samefile(path, dest_path):
                    try:
                        shutil.copy2(path, dest_path)
                    except Exception as e:
                        # 复制失败时使用原路径
                        self.edit_icon.setText(path)
                        return

                # 使用相对路径
                rel_path = os.path.basename(dest_path)
                self.edit_icon.setText(rel_path)
            else:
                # 没有项目目录时使用原路径
                self.edit_icon.setText(path)

    def _browse_loop(self):
        """浏览循环视频/图片"""
        if self.radio_loop_image.isChecked():
            # 图片模式
            path, _ = QFileDialog.getOpenFileName(
                self, "选择循环图片", self._base_dir,
                "图片文件 (*.png *.jpg *.jpeg)"
            )
        else:
            # 视频模式
            path, _ = QFileDialog.getOpenFileName(
                self, "选择循环视频", self._base_dir,
                "视频文件 (*.mp4 *.avi *.mov)"
            )
        if path:
            self.edit_loop_file.setText(path)
            # 发送视频选择信号用于预览（仅视频模式）
            if not self.radio_loop_image.isChecked():
                self.video_file_selected.emit(path)

    def _on_loop_mode_changed(self):
        """循环模式变更"""
        is_image = self.radio_loop_image.isChecked()
        if is_image:
            self.edit_loop_file.setPlaceholderText("loop.png")
        else:
            self.edit_loop_file.setPlaceholderText("loop.mp4")
        self._on_config_changed()

    def _browse_intro(self):
        """浏览入场视频"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择入场视频", self._base_dir,
            "视频文件 (*.mp4 *.avi *.mov)"
        )
        if path:
            self.edit_intro_file.setText(path)

    def _pick_color(self, edit: QLineEdit):
        """选择颜色"""
        from PyQt6.QtGui import QColor as QC
        current = QC(edit.text())
        color = QColorDialog.getColor(current, self, "选择颜色")
        if color.isValid():
            edit.setText(color.name())

    def _on_select_class_icon(self):
        """选择职业图标"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择职业图标", self._base_dir,
            "图片文件 (*.png *.jpg *.jpeg *.bmp)"
        )
        if file_path:
            # 复制到项目目录并使用相对路径
            rel_path = self._copy_to_project_dir(file_path, "class_icon")
            if rel_path:
                self.edit_ark_class_icon.setText(rel_path)
                self._on_config_changed()

    def _on_clear_class_icon(self):
        """清除职业图标"""
        self.edit_ark_class_icon.clear()
        self._on_config_changed()

    def _on_select_logo(self):
        """选择Logo"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择Logo", self._base_dir,
            "图片文件 (*.png *.jpg *.jpeg *.bmp)"
        )
        if file_path:
            # 复制到项目目录并使用相对路径
            rel_path = self._copy_to_project_dir(file_path, "ark_logo")
            if rel_path:
                self.edit_ark_logo.setText(rel_path)
                self._on_config_changed()

    def _on_clear_logo(self):
        """清除Logo"""
        self.edit_ark_logo.clear()
        self._on_config_changed()

    def _copy_to_project_dir(self, src_path: str, base_name: str) -> str:
        """
        将文件复制到项目目录

        Args:
            src_path: 源文件路径
            base_name: 目标文件基础名称

        Returns:
            相对路径，失败返回空字符串
        """
        if not self._base_dir:
            # 没有项目目录，返回原路径
            return src_path

        try:
            _, ext = os.path.splitext(src_path)
            dest_path = os.path.join(self._base_dir, f"{base_name}{ext}")

            # 如果目标已存在且不同，生成唯一文件名
            counter = 1
            while os.path.exists(dest_path):
                if os.path.samefile(src_path, dest_path):
                    # 同一文件，直接返回相对路径
                    return f"{base_name}{ext}"
                dest_path = os.path.join(self._base_dir, f"{base_name}_{counter}{ext}")
                counter += 1

            # 复制文件
            shutil.copy2(src_path, dest_path)
            return os.path.basename(dest_path)

        except Exception as e:
            # 复制失败，返回原路径
            import logging
            logging.getLogger(__name__).warning(f"复制文件失败: {e}")
            return src_path

    def _browse_transition_image(self, trans_type: str):
        """浏览过渡图片"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择过渡图片", self._base_dir,
            "图片文件 (*.png *.jpg *.jpeg)"
        )
        if file_path and self._base_dir:
            from PyQt6.QtWidgets import QApplication
            from PyQt6.QtCore import Qt
            from core.image_processor import ImageProcessor

            # 显示等待光标
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                # 加载图片
                img = ImageProcessor.load_image(file_path)
                if img is None:
                    return

                # 缩放到 360x640
                img = ImageProcessor.resize_image(img, 360, 640, keep_aspect=True)

                # 保存到项目目录
                base_name = f"trans_{trans_type}_image"
                _, ext = os.path.splitext(file_path)
                dest_path = os.path.join(self._base_dir, f"{base_name}{ext}")

                if ImageProcessor.save_image(img, dest_path):
                    rel_path = os.path.basename(dest_path)
                    if trans_type == "in":
                        self.edit_trans_in_image.setText(rel_path)
                    else:
                        self.edit_trans_loop_image.setText(rel_path)
                    self._on_config_changed()
            finally:
                QApplication.restoreOverrideCursor()

    def _on_select_img_overlay(self):
        """选择叠加图片"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择叠加图片", self._base_dir,
            "图片文件 (*.png *.jpg *.jpeg)"
        )
        if file_path:
            rel_path = self._copy_to_project_dir(file_path, "overlay")
            if rel_path:
                self.edit_img_overlay.setText(rel_path)
                self._on_config_changed()
