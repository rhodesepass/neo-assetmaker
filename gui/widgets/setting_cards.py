"""
自定义设置卡片 — 不依赖 qconfig，兼容 user_settings.json
"""

from typing import Union

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWidgets import QFileDialog, QLabel

from qfluentwidgets import ComboBox, SpinBox, DoubleSpinBox, FluentIcon
from qfluentwidgets.common.icon import FluentIconBase
from qfluentwidgets.components.settings import SettingCard, ColorPickerButton


class ComboSettingCard(SettingCard):
    """下拉框设置卡片"""

    currentTextChanged = pyqtSignal(str)

    def __init__(self, icon: Union[str, QIcon, FluentIconBase], title: str,
                 content: str = None, texts: list = None, parent=None):
        super().__init__(icon, title, content, parent)
        self.comboBox = ComboBox(self)
        if texts:
            self.comboBox.addItems(texts)
        self.hBoxLayout.addWidget(
            self.comboBox, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.comboBox.currentTextChanged.connect(self.currentTextChanged)

    def setCurrentText(self, text: str):
        self.comboBox.setCurrentText(text)

    def currentText(self) -> str:
        return self.comboBox.currentText()


class SpinSettingCard(SettingCard):
    """整数 SpinBox 设置卡片"""

    valueChanged = pyqtSignal(int)

    def __init__(self, icon: Union[str, QIcon, FluentIconBase], title: str,
                 content: str = None, min_val: int = 1, max_val: int = 8,
                 default: int = 1, parent=None):
        super().__init__(icon, title, content, parent)
        self.spinBox = SpinBox(self)
        self.spinBox.setRange(min_val, max_val)
        self.spinBox.setValue(default)
        self.hBoxLayout.addWidget(
            self.spinBox, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.spinBox.valueChanged.connect(self.valueChanged)

    def setValue(self, value: int):
        self.spinBox.setValue(value)

    def value(self) -> int:
        return self.spinBox.value()


class DoubleSpinSettingCard(SettingCard):
    """浮点 SpinBox 设置卡片（用于界面缩放）"""

    valueChanged = pyqtSignal(float)

    def __init__(self, icon: Union[str, QIcon, FluentIconBase], title: str,
                 content: str = None, min_val: float = 0.8,
                 max_val: float = 1.5, step: float = 0.1,
                 default: float = 1.0, suffix: str = "x", parent=None):
        super().__init__(icon, title, content, parent)
        self.spinBox = DoubleSpinBox(self)
        self.spinBox.setRange(min_val, max_val)
        self.spinBox.setSingleStep(step)
        self.spinBox.setValue(default)
        if suffix:
            self.spinBox.setSuffix(suffix)
        self.hBoxLayout.addWidget(
            self.spinBox, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.spinBox.valueChanged.connect(self.valueChanged)

    def setValue(self, value: float):
        self.spinBox.setValue(value)

    def value(self) -> float:
        return self.spinBox.value()


class ColorPickerSettingCard(SettingCard):
    """颜色选择设置卡片（使用 QFluentWidgets 内置 ColorPickerButton）"""

    colorChanged = pyqtSignal(str)

    def __init__(self, icon: Union[str, QIcon, FluentIconBase], title: str,
                 content: str = None, default_color: str = "#ff6b8b",
                 parent=None):
        super().__init__(icon, title, content, parent)
        self._color_hex = default_color
        self.colorPicker = ColorPickerButton(
            QColor(default_color), title, self)
        self.hBoxLayout.addWidget(
            self.colorPicker, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.colorPicker.colorChanged.connect(self._on_color_changed)

    def _on_color_changed(self, color: QColor):
        self._color_hex = color.name()
        self.colorChanged.emit(self._color_hex)

    def setColor(self, color_hex: str):
        self._color_hex = color_hex
        self.colorPicker.setColor(QColor(color_hex))

    def color(self) -> str:
        return self._color_hex


class ImagePickerSettingCard(SettingCard):
    """图片选择设置卡片"""

    imageSelected = pyqtSignal(str)

    def __init__(self, icon: Union[str, QIcon, FluentIconBase], title: str,
                 content: str = None, parent=None):
        super().__init__(icon, title, content, parent)
        self._image_path = ""

        from qfluentwidgets import PushButton
        self.pathLabel = QLabel("未选择", self)
        self.pathLabel.setObjectName("contentLabel")
        self.pickButton = PushButton("选择图片", self)
        self.pickButton.clicked.connect(self._on_pick)

        self.hBoxLayout.addWidget(
            self.pathLabel, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(8)
        self.hBoxLayout.addWidget(
            self.pickButton, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def _on_pick(self):
        import os
        file_path, _ = QFileDialog.getOpenFileName(
            self.window(), "选择主题图片", "",
            "图片文件 (*.jpg *.jpeg *.png *.bmp *.gif)")
        if file_path:
            self._image_path = file_path
            self.pathLabel.setText(os.path.basename(file_path))
            self.imageSelected.emit(file_path)

    def setImagePath(self, path: str):
        import os
        self._image_path = path
        if path:
            self.pathLabel.setText(os.path.basename(path))
        else:
            self.pathLabel.setText("未选择")

    def imagePath(self) -> str:
        return self._image_path
