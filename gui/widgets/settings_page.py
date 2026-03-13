"""设置页面 — 使用 QFluentWidgets SettingCard 组件，自动适配主题"""

import os
import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

from qfluentwidgets import ScrollArea, FluentIcon, SubtitleLabel
from qfluentwidgets.components.settings import (
    SettingCard, SwitchSettingCard,
    PushSettingCard, PrimaryPushSettingCard,
    SettingCardGroup,
)

from gui.widgets.setting_cards import (
    ComboSettingCard, SpinSettingCard,
    DoubleSpinSettingCard, ColorPickerSettingCard,
    ImagePickerSettingCard,
)

logger = logging.getLogger(__name__)


class SettingsPage(QWidget):
    """设置页面 — 6 组 SettingCardGroup"""

    setting_changed = pyqtSignal(str, object)
    check_update_requested = pyqtSignal()
    show_shortcuts_requested = pyqtSignal()
    show_about_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._init_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _init_ui(self):
        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(0, 15, 0, 0)

        # 标题
        self.titleLabel = SubtitleLabel("设置", self)
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

        # ---------- 1. 应用设置 ----------
        self.appGroup = SettingCardGroup("应用设置", self.scrollWidget)

        self.autoUpdateCard = SwitchSettingCard(
            FluentIcon.UPDATE, "自动检查更新",
            "启动时自动检查新版本", parent=self.appGroup)
        self.updateFreqCard = ComboSettingCard(
            FluentIcon.SYNC, "更新检查频率",
            texts=["每天", "每周", "每月"], parent=self.appGroup)

        self.appGroup.addSettingCards([
            self.autoUpdateCard, self.updateFreqCard])

        # ---------- 2. 界面设置 ----------
        self.uiGroup = SettingCardGroup("界面设置", self.scrollWidget)

        self.themeCard = ComboSettingCard(
            FluentIcon.PALETTE, "主题",
            texts=["默认", "自定义图片"], parent=self.uiGroup)
        self.themeColorCard = ColorPickerSettingCard(
            FluentIcon.PALETTE, "主题颜色",
            content="选择自定义主题颜色", parent=self.uiGroup)
        self.themeImageCard = ImagePickerSettingCard(
            FluentIcon.PHOTO, "主题图片",
            content="选择自定义背景图片", parent=self.uiGroup)
        self.scaleCard = DoubleSpinSettingCard(
            FluentIcon.ZOOM, "界面缩放",
            min_val=0.8, max_val=1.5, step=0.1,
            default=1.0, suffix="x", parent=self.uiGroup)
        self.languageCard = ComboSettingCard(
            FluentIcon.LANGUAGE, "语言",
            content="语言设置需要重启应用生效",
            texts=["简体中文", "English"], parent=self.uiGroup)

        self.uiGroup.addSettingCards([
            self.themeCard, self.themeColorCard,
            self.themeImageCard, self.scaleCard, self.languageCard])

        # ---------- 3. 个性化设置 ----------
        self.personalGroup = SettingCardGroup("个性化设置", self.scrollWidget)

        self.tempProjectCard = SwitchSettingCard(
            FluentIcon.HOME, "启动时自动创建临时项目",
            parent=self.personalGroup)
        self.welcomeCard = SwitchSettingCard(
            FluentIcon.CHAT, "显示欢迎对话框",
            parent=self.personalGroup)
        self.statusBarCard = SwitchSettingCard(
            FluentIcon.INFO, "显示状态栏",
            parent=self.personalGroup)
        self.autoSaveCard = SwitchSettingCard(
            FluentIcon.SAVE, "自动保存项目",
            parent=self.personalGroup)

        self.personalGroup.addSettingCards([
            self.tempProjectCard, self.welcomeCard,
            self.statusBarCard, self.autoSaveCard])

        # ---------- 4. 视频与导出 ----------
        self.videoGroup = SettingCardGroup("视频与导出", self.scrollWidget)

        self.hwAccelCard = SwitchSettingCard(
            FluentIcon.SPEED_HIGH, "硬件加速",
            parent=self.videoGroup)
        self.exportThreadsCard = SpinSettingCard(
            FluentIcon.SETTING, "导出线程数",
            min_val=1, max_val=8, default=1, parent=self.videoGroup)

        self.videoGroup.addSettingCards([
            self.hwAccelCard, self.exportThreadsCard])

        # ---------- 5. 网络设置 ----------
        self.networkGroup = SettingCardGroup("网络设置", self.scrollWidget)

        self.githubAccelCard = SwitchSettingCard(
            FluentIcon.GLOBE, "GitHub 加速",
            parent=self.networkGroup)
        self.proxyCard = SwitchSettingCard(
            FluentIcon.WIFI, "使用代理",
            parent=self.networkGroup)

        self.networkGroup.addSettingCards([
            self.githubAccelCard, self.proxyCard])

        # ---------- 6. 关于 ----------
        self.aboutGroup = SettingCardGroup("关于", self.scrollWidget)

        self.shortcutsCard = PushSettingCard(
            "打开", FluentIcon.HELP, "快捷键帮助",
            content="查看所有键盘快捷键", parent=self.aboutGroup)
        self.updateCard = PrimaryPushSettingCard(
            "检查更新", FluentIcon.UPDATE, "检查更新",
            content="检查是否有新版本可用", parent=self.aboutGroup)

        from config.constants import APP_NAME, APP_VERSION
        self.aboutCard = SettingCard(
            FluentIcon.INFO, f"{APP_NAME} v{APP_VERSION}",
            "明日方舟通行证素材制作器\n"
            "作者: Rafael_ban & 初微弦音 & 涙不在为你而流\n"
            "© 2026 罗德岛工程部",
            parent=self.aboutGroup)

        self.aboutGroup.addSettingCards([
            self.shortcutsCard, self.updateCard, self.aboutCard])

        # ---------- 添加到滚动布局 ----------
        for group in [self.appGroup, self.uiGroup, self.personalGroup,
                      self.videoGroup, self.networkGroup, self.aboutGroup]:
            self.scrollLayout.addWidget(group)

        self.scrollLayout.addStretch(1)
        self.scrollArea.setWidget(self.scrollWidget)
        self.scrollArea.enableTransparentBackground()
        self.mainLayout.addWidget(self.scrollArea)

    # ------------------------------------------------------------------
    # 信号连接
    # ------------------------------------------------------------------
    def _connect_signals(self):
        # 应用设置
        self.autoUpdateCard.checkedChanged.connect(
            lambda v: self._emit('auto_update', v))
        self.updateFreqCard.currentTextChanged.connect(
            lambda v: self._emit('update_freq', v))

        # 界面设置
        self.themeCard.currentTextChanged.connect(
            lambda v: self._emit('theme', v))
        self.themeColorCard.colorChanged.connect(
            lambda v: self._emit('theme_color', v))
        self.themeImageCard.imageSelected.connect(
            lambda v: self._emit('theme_image', v))
        self.scaleCard.valueChanged.connect(
            lambda v: self._emit('scale', v))
        self.languageCard.currentTextChanged.connect(
            lambda v: self._emit('language', v))

        # 个性化设置
        self.tempProjectCard.checkedChanged.connect(
            lambda v: self._emit('auto_create_temp_project', v))
        self.welcomeCard.checkedChanged.connect(
            lambda v: self._emit('show_welcome_dialog', v))
        self.statusBarCard.checkedChanged.connect(
            lambda v: self._emit('show_status_bar', v))
        self.autoSaveCard.checkedChanged.connect(
            lambda v: self._emit('auto_save', v))

        # 视频与导出
        self.hwAccelCard.checkedChanged.connect(
            lambda v: self._emit('hardware_acceleration', v))
        self.exportThreadsCard.valueChanged.connect(
            lambda v: self._emit('export_threads', v))

        # 网络设置
        self.githubAccelCard.checkedChanged.connect(
            lambda v: self._emit('github_acceleration', v))
        self.proxyCard.checkedChanged.connect(
            lambda v: self._emit('use_proxy', v))

        # 关于
        self.shortcutsCard.clicked.connect(self.show_shortcuts_requested)
        self.updateCard.clicked.connect(self.check_update_requested)

    def _emit(self, name: str, value):
        """统一发射信号（加载期间静默）"""
        if not self._loading:
            self.setting_changed.emit(name, value)

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------
    def load_settings(self, settings: dict):
        """从 dict 加载设置到所有卡片（不触发 setting_changed 信号）"""
        self._loading = True
        try:
            self.autoUpdateCard.setChecked(
                settings.get('auto_update', True))
            self.updateFreqCard.setCurrentText(
                settings.get('update_freq', '每天'))

            self.themeCard.setCurrentText(
                settings.get('theme', '默认'))
            self.themeColorCard.setColor(
                settings.get('theme_color', '#ff6b8b'))
            self.themeImageCard.setImagePath(
                settings.get('theme_image', ''))
            self.scaleCard.setValue(
                settings.get('scale', 1.0))
            self.languageCard.setCurrentText(
                settings.get('language', '简体中文'))

            self.tempProjectCard.setChecked(
                settings.get('auto_create_temp_project', True))
            self.welcomeCard.setChecked(
                settings.get('show_welcome_dialog', True))
            self.statusBarCard.setChecked(
                settings.get('show_status_bar', True))
            self.autoSaveCard.setChecked(
                settings.get('auto_save', False))

            self.hwAccelCard.setChecked(
                settings.get('hardware_acceleration', True))
            self.exportThreadsCard.setValue(
                settings.get('export_threads', 1))

            self.githubAccelCard.setChecked(
                settings.get('github_acceleration', True))
            self.proxyCard.setChecked(
                settings.get('use_proxy', False))
        finally:
            self._loading = False
