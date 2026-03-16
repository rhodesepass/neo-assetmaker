"""远程管理页面 — SSH 上传管理，使用 QFluentWidgets 组件自动适配主题

之前的实现使用原始 QFrame.StyledPanel 三栏布局，不跟随 QFluentWidgets 主题，
且无实际功能。重写为 ScrollArea + SettingCardGroup 模式，与 settings_page.py
风格一致，自动适配明暗主题。

参考: QFluentWidgets SettingCardGroup 文档
https://qfluentwidgets.com/zh/price/components/settings/settingcardgroup
"""

import os
import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QLabel,
)

from qfluentwidgets import (
    ScrollArea, FluentIcon, SubtitleLabel, LineEdit,
    PrimaryPushButton, PushButton, ProgressBar,
    InfoBar, InfoBarPosition,
    setCustomStyleSheet,
)
from qfluentwidgets.components.settings import (
    SettingCard, SwitchSettingCard,
    PushSettingCard, PrimaryPushSettingCard,
    SettingCardGroup,
)

logger = logging.getLogger(__name__)


class LineEditSettingCard(SettingCard):
    """带行编辑框的设置卡片（复用 settings_page.py 中的模式）"""

    textChanged = pyqtSignal(str)

    def __init__(self, icon, title, content=None,
                 defaultText="", placeholder="", parent=None):
        super().__init__(icon, title, content, parent)
        self.lineEdit = LineEdit(self)
        self.lineEdit.setFixedWidth(200)
        if defaultText:
            self.lineEdit.setText(defaultText)
        if placeholder:
            self.lineEdit.setPlaceholderText(placeholder)
        self.lineEdit.textChanged.connect(self.textChanged.emit)
        l, t, r, b = self.hBoxLayout.getContentsMargins()
        self.hBoxLayout.setContentsMargins(l, t, 12, b)
        self.hBoxLayout.addWidget(self.lineEdit)

    def text(self):
        return self.lineEdit.text()

    def setText(self, text):
        self.lineEdit.setText(text)


class RemotePage(QWidget):
    """远程管理页面 — SSH 上传管理

    使用 QFluentWidgets ScrollArea + SettingCardGroup 模式，
    自动适配明暗主题，与设置页面风格一致。
    """

    setting_changed = pyqtSignal(str, object)
    upload_requested = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._upload_worker = None
        self._local_file_path = ""
        self._init_ui()
        self._connect_signals()

    def _init_ui(self):
        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(0, 15, 0, 0)

        # 标题
        self.titleLabel = SubtitleLabel("远程管理", self)
        self.titleLabel.setContentsMargins(30, 0, 0, 0)
        self.mainLayout.addWidget(self.titleLabel)
        self.mainLayout.addSpacing(15)

        # 滚动区域
        self.scrollArea = ScrollArea(self)
        self.scrollArea.setWidgetResizable(True)

        self.scrollWidget = QWidget()
        self.scrollLayout = QVBoxLayout(self.scrollWidget)
        self.scrollLayout.setContentsMargins(30, 10, 30, 30)
        self.scrollLayout.setSpacing(20)

        # ---------- 1. SSH 连接配置 ----------
        self.sshGroup = SettingCardGroup("SSH 连接", self.scrollWidget)

        self.hostCard = LineEditSettingCard(
            FluentIcon.GLOBE, "SSH 地址",
            "通行证设备的 IP 地址",
            defaultText="192.168.137.2",
            parent=self.sshGroup)
        self.portCard = LineEditSettingCard(
            FluentIcon.LINK, "SSH 端口",
            defaultText="22",
            parent=self.sshGroup)
        self.userCard = LineEditSettingCard(
            FluentIcon.PEOPLE, "用户名",
            defaultText="root",
            parent=self.sshGroup)
        self.passwordCard = LineEditSettingCard(
            FluentIcon.FINGERPRINT, "密码",
            defaultText="toor",
            parent=self.sshGroup)
        self.remotePathCard = LineEditSettingCard(
            FluentIcon.FOLDER, "远程路径",
            "上传到设备的目标路径",
            defaultText="/assets/",
            parent=self.sshGroup)
        self.autoRestartCard = SwitchSettingCard(
            FluentIcon.SYNC, "上传后自动重启",
            "上传完毕后自动重启通行证程序",
            parent=self.sshGroup)

        self.sshGroup.addSettingCards([
            self.hostCard, self.portCard, self.userCard,
            self.passwordCard, self.remotePathCard, self.autoRestartCard,
        ])

        # ---------- 2. 上传控制 ----------
        self.uploadGroup = SettingCardGroup("上传控制", self.scrollWidget)

        self.selectFileCard = PushSettingCard(
            "选择文件", FluentIcon.FOLDER_ADD, "本地文件",
            content="选择要上传的文件或目录",
            parent=self.uploadGroup)
        self.uploadCard = PrimaryPushSettingCard(
            "开始上传", FluentIcon.SEND, "上传到设备",
            content="将选择的文件通过 SSH 上传到通行证设备",
            parent=self.uploadGroup)

        self.uploadGroup.addSettingCards([
            self.selectFileCard, self.uploadCard,
        ])

        # ---------- 3. 上传状态 ----------
        self.statusGroup = SettingCardGroup("上传状态", self.scrollWidget)

        self.statusCard = SettingCard(
            FluentIcon.INFO, "状态", "就绪",
            parent=self.statusGroup)
        self.progressBar = ProgressBar(self.statusCard)
        self.progressBar.setFixedWidth(200)
        self.progressBar.setValue(0)
        self.progressBar.setVisible(False)
        l, t, r, b = self.statusCard.hBoxLayout.getContentsMargins()
        self.statusCard.hBoxLayout.setContentsMargins(l, t, 12, b)
        self.statusCard.hBoxLayout.addWidget(self.progressBar)

        self.statusGroup.addSettingCards([self.statusCard])

        # ---------- 添加到滚动布局 ----------
        for group in [self.sshGroup, self.uploadGroup, self.statusGroup]:
            self.scrollLayout.addWidget(group)

        self.scrollLayout.addStretch(1)
        self.scrollArea.setWidget(self.scrollWidget)
        self.scrollArea.enableTransparentBackground()
        self.mainLayout.addWidget(self.scrollArea)

    def _connect_signals(self):
        # SSH 设置变更
        self.hostCard.textChanged.connect(
            lambda v: self.setting_changed.emit('ssh_ip_address', v))
        self.portCard.textChanged.connect(
            lambda v: self.setting_changed.emit('ssh_port', v))
        self.userCard.textChanged.connect(
            lambda v: self.setting_changed.emit('ssh_user', v))
        self.passwordCard.textChanged.connect(
            lambda v: self.setting_changed.emit('ssh_password', v))
        self.remotePathCard.textChanged.connect(
            lambda v: self.setting_changed.emit('ssh_default_upload_path', v))
        self.autoRestartCard.checkedChanged.connect(
            lambda v: self.setting_changed.emit('ssh_auto_restart_program', v))

        # 上传操作
        self.selectFileCard.clicked.connect(self._on_select_file)
        self.uploadCard.clicked.connect(self._on_start_upload)

    def _on_select_file(self):
        """选择本地文件"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择要上传的文件", "",
            "所有文件 (*.*)")
        if path:
            self._local_file_path = path
            self.selectFileCard.setContent(os.path.basename(path))
            logger.info(f"已选择上传文件: {path}")

    def _on_start_upload(self):
        """开始 SSH 上传"""
        if not self._local_file_path:
            InfoBar.warning(
                "提示", "请先选择要上传的文件",
                parent=self, position=InfoBarPosition.TOP,
                duration=3000)
            return

        if self._upload_worker and self._upload_worker.isRunning():
            InfoBar.warning(
                "提示", "上传正在进行中",
                parent=self, position=InfoBarPosition.TOP,
                duration=3000)
            return

        # 收集参数
        host = self.hostCard.text()
        try:
            port = int(self.portCard.text())
        except ValueError:
            port = 22
        user = self.userCard.text()
        password = self.passwordCard.text()
        remote_path = self.remotePathCard.text()
        enable_restart = self.autoRestartCard.isChecked()

        # 创建上传工作线程
        from core.ssh_upload_service import SshUploadWorker

        self._upload_worker = SshUploadWorker(parent=self)
        self._upload_worker.setup(
            host, port, user, password,
            self._local_file_path, remote_path, enable_restart)
        self._upload_worker.progress_updated.connect(self._on_progress)
        self._upload_worker.upload_completed.connect(self._on_upload_done)
        self._upload_worker.upload_failed.connect(self._on_upload_failed)

        # 更新 UI 状态
        self.progressBar.setVisible(True)
        self.progressBar.setValue(0)
        self.statusCard.setContent("上传中...")
        self.uploadCard.button.setEnabled(False)

        self._upload_worker.start()
        logger.info(f"开始 SSH 上传: {self._local_file_path} → {host}:{remote_path}")

    def _on_progress(self, percent: int, message: str):
        """上传进度更新"""
        self.progressBar.setValue(percent)
        self.statusCard.setContent(message)

    def _on_upload_done(self, message: str):
        """上传完成"""
        self.progressBar.setValue(100)
        self.statusCard.setContent(message)
        self.uploadCard.button.setEnabled(True)
        InfoBar.success(
            "上传成功", message,
            parent=self, position=InfoBarPosition.TOP,
            duration=5000)
        logger.info(f"SSH 上传完成: {message}")

    def _on_upload_failed(self, error: str):
        """上传失败"""
        self.progressBar.setVisible(False)
        self.statusCard.setContent(f"失败: {error}")
        self.uploadCard.button.setEnabled(True)
        InfoBar.error(
            "上传失败", error,
            parent=self, position=InfoBarPosition.TOP,
            duration=5000)
        logger.error(f"SSH 上传失败: {error}")

    def load_settings(self, settings: dict):
        """从 dict 加载设置"""
        self.hostCard.setText(
            settings.get('ssh_ip_address', '192.168.137.2'))
        self.portCard.setText(
            str(settings.get('ssh_port', '22')))
        self.userCard.setText(
            settings.get('ssh_user', 'root'))
        self.passwordCard.setText(
            settings.get('ssh_password', 'toor'))
        self.remotePathCard.setText(
            settings.get('ssh_default_upload_path', '/assets/'))
        self.autoRestartCard.setChecked(
            settings.get('ssh_auto_restart_program', False))

    def shutdown(self):
        """关闭页面，取消正在进行的上传"""
        if self._upload_worker and self._upload_worker.isRunning():
            self._upload_worker.cancel()
            self._upload_worker.wait(3000)
