"""
公共 FluentGroupBox 组件 - 基于 CardWidget 的分组容器
"""
from PyQt6.QtWidgets import QVBoxLayout, QFrame
from qfluentwidgets import CardWidget, StrongBodyLabel


class FluentGroupBox(CardWidget):
    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(15, 15, 15, 15)
        self.main_layout.setSpacing(10)
        if title:
            self.title_label = StrongBodyLabel(title)
            self.main_layout.addWidget(self.title_label)
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setFrameShadow(QFrame.Shadow.Sunken)
            line.setStyleSheet("margin: 5px 0;")
            self.main_layout.addWidget(line)

    def addLayout(self, layout):
        """添加布局"""
        self.main_layout.addLayout(layout)

    def addWidget(self, widget):
        """添加控件"""
        self.main_layout.addWidget(widget)
