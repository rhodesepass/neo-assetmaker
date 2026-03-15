"""远程页面 — 远程控制和连接功能"""

import os
import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QFrame

from qfluentwidgets import ScrollArea, FluentIcon, SubtitleLabel, LineEdit, PrimaryPushButton, PushButton
from qfluentwidgets.components.settings import (
    SettingCard, SwitchSettingCard,
    PushSettingCard, PrimaryPushSettingCard,
    SettingCardGroup,
)

logger = logging.getLogger(__name__)


class RemotePage(QWidget):
    """远程页面 — 远程控制和连接功能"""

    # 信号定义
    connect_requested = pyqtSignal(dict)  # 连接请求，参数为连接信息
    disconnect_requested = pyqtSignal()  # 断开连接请求
    command_sent = pyqtSignal(str)  # 发送命令信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self._connected = False
        self._init_ui()
        self._connect_signals()

    def _init_ui(self):
        """UI 构建"""
        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(0, 15, 0, 0)

        # 标题
        self.titleLabel = SubtitleLabel("远程控制", self)
        self.titleLabel.setContentsMargins(30, 0, 0, 0)
        self.mainLayout.addWidget(self.titleLabel)
        self.mainLayout.addSpacing(15)

        # 三栏布局
        self.columnsLayout = QHBoxLayout()
        self.columnsLayout.setSpacing(15)
        self.columnsLayout.setContentsMargins(30, 0, 30, 0)

        # 每一栏使用一个 QFrame 包裹，便于未来扩展样式/边框
        self.columns = []
        for _ in range(3):
            frame = QFrame(self)
            frame.setFrameShape(QFrame.StyledPanel)
            frame.setFrameShadow(QFrame.Plain)
            frameLayout = QVBoxLayout(frame)
            frameLayout.setContentsMargins(10, 10, 10, 10)
            frameLayout.setSpacing(10)
            frame.setLayout(frameLayout)
            self.columns.append(frame)
            self.columnsLayout.addWidget(frame)

        self.mainLayout.addLayout(self.columnsLayout)


    # ------------------------------------------------------------------
    # 信号连接
    # ------------------------------------------------------------------
    def _connect_signals(self):
        """连接信号"""
        return

