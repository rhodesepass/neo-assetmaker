"""
基础设置面板 - 简化版配置界面
"""
import os
import shutil
import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout,
    QHBoxLayout, QLabel, QFileDialog, QCompleter
)
from PyQt6.QtCore import pyqtSignal, Qt

from qfluentwidgets import (
    PushButton, PrimaryPushButton,
    LineEdit, ComboBox, SubtitleLabel, StrongBodyLabel,
    SearchLineEdit
)

from gui.widgets.fluent_group_box import FluentGroupBox
from config.epconfig import EPConfig, ScreenType, OverlayType
from config.constants import RESOLUTION_SPECS, OPERATOR_CLASS_PRESETS
from config.operator_db import get_operator_db


class BasicConfigPanel(QWidget):
    """基础设置面板"""

    config_changed = pyqtSignal()
    video_file_selected = pyqtSignal(str)
    validate_requested = pyqtSignal()
    export_requested = pyqtSignal()
    ssh_upload_requested = pyqtSignal()


    def __init__(self, parent=None):
        super().__init__(parent)

        self._config: Optional[EPConfig] = None
        self._base_dir: str = ""
        self._updating = False  # 防止set_config期间循环更新
        self._operator_db = get_operator_db()
        self._is_updating_from_db = False  # 防止循环更新

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """设置UI"""
        # 直接使用垂直布局，不使用滚动区域
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        group_basic = FluentGroupBox("基本信息")
        basic_layout = QFormLayout()

        self.edit_name = LineEdit()
        self.edit_name.setPlaceholderText("素材名称")
        basic_layout.addRow("名称:", self.edit_name)

        self.combo_screen = ComboBox()
        for screen in RESOLUTION_SPECS:
            desc = RESOLUTION_SPECS[screen].get("description", screen)
            self.combo_screen.addItem(desc, userData=screen)
        basic_layout.addRow("分辨率:", self.combo_screen)

        group_basic.addLayout(basic_layout)
        layout.addWidget(group_basic)

        group_video = FluentGroupBox("视频设置")

        loop_layout = QFormLayout()
        self.edit_loop_file = LineEdit()
        self.edit_loop_file.setPlaceholderText("选择循环视频")
        loop_layout.addRow("循环视频:", self.edit_loop_file)

        btn_browse_loop = PushButton("浏览...")
        btn_browse_loop.clicked.connect(lambda: self._browse_file("视频", ["视频文件 (*.mp4 *.avi *.mov)" ]))
        loop_layout.addRow("", btn_browse_loop)

        group_video.addLayout(loop_layout)
        layout.addWidget(group_video)

        group_template = FluentGroupBox("一键模板")
        template_layout = QVBoxLayout()
        template_desc = StrongBodyLabel("选择一个模板，快速创建素材")
        template_layout.addWidget(template_desc)
        self.combo_template = ComboBox()
        self.combo_template.addItems(["默认模板", "明日方舟模板", "自定义模板"])
        template_layout.addWidget(self.combo_template)
        group_template.addLayout(template_layout)
        layout.addWidget(group_template)

        self.group_arknights = FluentGroupBox("明日方舟干员信息")
        form_layout = QFormLayout()
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(8)
        self.edit_ark_name = SearchLineEdit()
        self.edit_ark_name.setPlaceholderText("例如：新约能天使")
        self.edit_ark_name.setToolTip("干员名称，显示在UI顶部\n支持模糊搜索，输入部分名称即可")
        self._update_completer()
        form_layout.addRow("干员名称:", self.edit_ark_name)
        self.combo_ark_class = ComboBox()
        self.combo_ark_class.addItem("无", userData="")
        for class_name, class_value in OPERATOR_CLASS_PRESETS.items():
            self.combo_ark_class.addItem(class_name, userData=class_value)
        self.combo_ark_class.setToolTip("选择干员职业\n输入干员名称后自动匹配")
        form_layout.addRow("职业:", self.combo_ark_class)
        self.group_arknights.addLayout(form_layout)
        self.group_arknights.setVisible(False)
        layout.addWidget(self.group_arknights)

        group_actions = FluentGroupBox("操作")
        actions_layout = QVBoxLayout()

        self.btn_validate = PrimaryPushButton("验证配置")
        actions_layout.addWidget(self.btn_validate)

        self.btn_export = PrimaryPushButton("导出素材")
        actions_layout.addWidget(self.btn_export)

        self.btn_sshUpload = PrimaryPushButton("一键上传")
        actions_layout.addWidget(self.btn_sshUpload)

        group_actions.addLayout(actions_layout)
        layout.addWidget(group_actions)

        layout.addStretch()

    def _connect_signals(self):
        """连接信号"""
        self.edit_name.textChanged.connect(self._on_config_changed)
        self.combo_screen.currentIndexChanged.connect(self._on_config_changed)
        self.edit_loop_file.textChanged.connect(self._on_config_changed)
        self.combo_template.currentIndexChanged.connect(self._on_template_changed)

        self.edit_ark_name.textChanged.connect(self._on_operator_name_changed)
        self.combo_ark_class.currentIndexChanged.connect(self._on_config_changed)

        self.btn_validate.clicked.connect(self.validate_requested.emit)
        self.btn_export.clicked.connect(self.export_requested.emit)
        self.btn_sshUpload.clicked.connect(self.ssh_upload_requested.emit)

    def _on_operator_name_changed(self, text: str):
        """干员名称变更处理"""
        if self._updating or self._is_updating_from_db:
            return

        if not text:
            self.combo_ark_class.setCurrentIndex(0)
            self._on_config_changed()
            return

        results = self._operator_db.search(text, limit=1)
        if results:
            operator_name, similarity = results[0]
            if similarity > 0.5:  # 相似度阈值
                profession = self._operator_db.get_operator_profession(operator_name)
                if profession:
                    index = self.combo_ark_class.findData(profession)
                    if index >= 0:
                        self.combo_ark_class.setCurrentIndex(index)

        self._on_config_changed()

    def set_config(self, config: EPConfig, base_dir: str = ""):
        """设置配置"""
        self._config = config
        self._base_dir = base_dir
        self._updating = True

        try:
            if config:
                self.edit_name.setText(config.name)

                index = self.combo_screen.findData(config.screen.value)
                if index >= 0:
                    self.combo_screen.setCurrentIndex(index)

                self.edit_loop_file.setText(config.loop.file)

                if config.overlay.type == OverlayType.ARKNIGHTS:
                    self.combo_template.setCurrentIndex(1)

                self.group_arknights.setVisible(
                    config.overlay.type == OverlayType.ARKNIGHTS
                )

                if config.overlay.arknights_options:
                    self.edit_ark_name.setText(config.overlay.arknights_options.operator_name)
                    class_icon = config.overlay.arknights_options.operator_class_icon or ""
                    index = self.combo_ark_class.findData(class_icon)
                    if index >= 0:
                        self.combo_ark_class.setCurrentIndex(index)
                    else:
                        self.combo_ark_class.setCurrentIndex(0)

                self._update_completer()
        finally:
            self._updating = False

    def _update_completer(self):
        """更新自动完成列表"""
        # SearchLineEdit没有setCompleter方法，我们需要使用其内置的搜索功能
        # 这里我们只需要确保操作数据库已加载即可
        pass

    def get_config(self) -> Optional[EPConfig]:
        """获取配置"""
        return self._config

    def update_config_from_ui(self):
        """从UI更新配置"""
        if self._config is None:
            return

        self._config.name = self.edit_name.text()

        screen_value = self.combo_screen.currentData()
        self._config.screen = ScreenType.from_string(screen_value)

        # 循环视频文件路径（不修改 loop.is_image，基础面板无此控件，保留高级面板设置的值）
        self._config.loop.file = self.edit_loop_file.text()

        template = self.combo_template.currentText()
        try:
            if template == "明日方舟模板":
                from config.epconfig import OverlayType
                self._config.overlay.type = OverlayType.ARKNIGHTS
                if not self._config.overlay.arknights_options:
                    from config.epconfig import ArknightsOverlayOptions
                    self._config.overlay.arknights_options = ArknightsOverlayOptions(
                        operator_name="OPERATOR",
                        operator_code="ARKNIGHTS - UNK0",
                        barcode_text="OPERATOR - ARKNIGHTS",
                        aux_text="Operator of Rhodes Island",
                        staff_text="STAFF"
                    )

                if self._config.overlay.arknights_options:
                    self._config.overlay.arknights_options.operator_name = self.edit_ark_name.text()
                    class_value = self.combo_ark_class.currentData()
                    if class_value:
                        self._config.overlay.arknights_options.operator_class_icon = f"class_icons/{class_value}.png"
                    else:
                        self._config.overlay.arknights_options.operator_class_icon = ""
            elif template == "自定义模板":
                pass
        except Exception as e:
            print(f"设置模板时出错: {e}")
            import traceback
            traceback.print_exc()

    def _on_config_changed(self):
        """配置变更处理"""
        if self._updating:
            return
        self.update_config_from_ui()
        self.config_changed.emit()

    def _on_template_changed(self):
        """模板变更处理"""
        if self._updating:
            return
        template = self.combo_template.currentText()
        self.group_arknights.setVisible(template == "明日方舟模板")

        if template == "明日方舟模板":
            self._update_completer()

        self._on_config_changed()

    def _browse_file(self, title: str, filters: list):
        """浏览文件"""
        import os
        import pathlib

        if not self._base_dir or not os.path.exists(self._base_dir):
            desktop_dir = str(pathlib.Path.home() / "Desktop")
            initial_dir = desktop_dir
        else:
            initial_dir = self._base_dir

        path, _ = QFileDialog.getOpenFileName(
            self, f"选择{title}", initial_dir,
            ";;".join(filters)
        )
        if path:
            rel_path = self._copy_to_project_dir(path, "loop")
            display_path = rel_path if rel_path else path
            self.edit_loop_file.setText(display_path)
            if self._config:
                self._config.loop.file = display_path
                ext = os.path.splitext(path)[1].lower()
                image_extensions = [".jpg", ".jpeg", ".png", ".bmp", ".gif"]
                self._config.loop.is_image = ext in image_extensions
            # 发送选择信号用于预览（使用原始绝对路径）
            self.video_file_selected.emit(path)

    def _copy_to_project_dir(self, src_path: str, base_name: str) -> str:
        """将文件复制到项目目录

        Args:
            src_path: 源文件路径
            base_name: 目标文件基础名称

        Returns:
            相对路径，失败返回空字符串
        """
        if not self._base_dir:
            return ""

        try:
            _, ext = os.path.splitext(src_path)
            dest_path = os.path.join(self._base_dir, f"{base_name}{ext}")

            counter = 1
            while os.path.exists(dest_path):
                if os.path.samefile(src_path, dest_path):
                    return f"{base_name}{ext}"
                dest_path = os.path.join(self._base_dir, f"{base_name}_{counter}{ext}")
                counter += 1

            shutil.copy2(src_path, dest_path)
            return os.path.basename(dest_path)

        except Exception as e:
            logging.getLogger(__name__).warning(f"复制文件失败: {e}")
            return ""
