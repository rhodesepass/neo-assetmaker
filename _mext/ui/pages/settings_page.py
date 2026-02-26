"""Settings page for application configuration.

Provides SettingCardGroups for general settings, FIDO2 credential
management, download path configuration, and account information.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SubtitleLabel,
    SwitchButton,
    TitleLabel,
)
from qtpy.QtCore import Qt, Signal, Slot
from qtpy.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from _mext.core.service_manager import ServiceManager
from _mext.models.user import Fido2Credential
from _mext.services.api_client import ApiError
from _mext.ui.components.fido2_credential_card import Fido2CredentialCard
from _mext.ui.dialogs.fido2_pin_dialog import Fido2PinDialog
from _mext.ui.dialogs.fido2_touch_dialog import Fido2TouchDialog

logger = logging.getLogger(__name__)

# FIDO2 API endpoint paths (relative, no leading slash -- httpx base_url
# resolution requires relative paths to correctly append to the base URL).
_FIDO2_CREDENTIALS_PATH = "auth/fido2/credentials"
_FIDO2_REGISTER_BEGIN_PATH = "auth/fido2/register/begin"
_FIDO2_REGISTER_COMPLETE_PATH = "auth/fido2/register/complete"


class SettingsPage(QWidget):
    """Application settings with categorized setting card groups.

    Signals
    -------
    settings_changed()
        Emitted when any setting is modified.
    logout_requested()
        Emitted when the user clicks logout.
    """

    settings_changed = Signal()
    logout_requested = Signal()

    def __init__(
        self,
        service_manager: ServiceManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._services = service_manager
        self._credential_cards: list[Fido2CredentialCard] = []

        self._setup_ui()
        self._connect_signals()
        self._load_settings()

    def _setup_ui(self) -> None:
        """Build the settings page layout with card groups."""
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(24)

        # ---- Account section ----
        self._account_title = TitleLabel("账户", content)
        layout.addWidget(self._account_title)

        account_row = QHBoxLayout()
        account_row.setSpacing(12)

        account_info_layout = QVBoxLayout()
        self._username_label = SubtitleLabel("未登录", content)
        account_info_layout.addWidget(self._username_label)
        self._email_label = BodyLabel("", content)
        account_info_layout.addWidget(self._email_label)
        self._role_label = BodyLabel("", content)
        account_info_layout.addWidget(self._role_label)
        account_row.addLayout(account_info_layout, stretch=1)

        self._logout_btn = PushButton("退出登录", content)
        account_row.addWidget(self._logout_btn, alignment=Qt.AlignmentFlag.AlignTop)

        layout.addLayout(account_row)

        # ---- General Settings ----
        self._general_title = TitleLabel("通用", content)
        layout.addWidget(self._general_title)

        # Theme selection
        theme_layout = QHBoxLayout()
        theme_layout.setSpacing(12)
        theme_layout.addWidget(BodyLabel("主题：", content))
        self._theme_combo = ComboBox(content)
        self._theme_combo.addItems(["跟随系统", "浅色", "深色"])
        self._theme_combo.setFixedWidth(200)
        theme_layout.addWidget(self._theme_combo)
        theme_layout.addStretch()
        layout.addLayout(theme_layout)

        # Language selection
        lang_layout = QHBoxLayout()
        lang_layout.setSpacing(12)
        lang_layout.addWidget(BodyLabel("语言：", content))
        self._lang_combo = ComboBox(content)
        self._lang_combo.addItems(["English", "Chinese (Simplified)", "Japanese", "Korean"])
        self._lang_combo.setFixedWidth(200)
        lang_layout.addWidget(self._lang_combo)
        lang_layout.addStretch()
        layout.addLayout(lang_layout)

        # ---- Download Settings ----
        self._download_title = TitleLabel("下载", content)
        layout.addWidget(self._download_title)

        # Download directory
        dir_layout = QHBoxLayout()
        dir_layout.setSpacing(12)
        dir_layout.addWidget(BodyLabel("下载目录：", content))
        self._download_dir_edit = LineEdit(content)
        self._download_dir_edit.setReadOnly(True)
        self._download_dir_edit.setText(str(self._services.config.download_dir))
        dir_layout.addWidget(self._download_dir_edit, stretch=1)
        self._browse_btn = PushButton("浏览...", content)
        dir_layout.addWidget(self._browse_btn)
        layout.addLayout(dir_layout)

        # Max concurrent downloads
        concurrent_layout = QHBoxLayout()
        concurrent_layout.setSpacing(12)
        concurrent_layout.addWidget(BodyLabel("最大并发下载数：", content))
        self._concurrent_combo = ComboBox(content)
        self._concurrent_combo.addItems(["1", "2", "3", "4", "5"])
        self._concurrent_combo.setCurrentText(str(self._services.config.max_concurrent_downloads))
        self._concurrent_combo.setFixedWidth(80)
        concurrent_layout.addWidget(self._concurrent_combo)
        concurrent_layout.addStretch()
        layout.addLayout(concurrent_layout)

        # Auto-verify downloads
        verify_layout = QHBoxLayout()
        verify_layout.setSpacing(12)
        verify_layout.addWidget(BodyLabel("验证下载文件 (SHA-256)：", content))
        self._verify_switch = SwitchButton(content)
        self._verify_switch.setChecked(True)
        verify_layout.addWidget(self._verify_switch)
        verify_layout.addStretch()
        layout.addLayout(verify_layout)

        # ---- FIDO2 Security Keys ----
        self._fido2_title = TitleLabel("安全密钥 (FIDO2)", content)
        layout.addWidget(self._fido2_title)

        self._fido2_description = BodyLabel(
            "管理你的 FIDO2 安全密钥，用于无密码认证。",
            content,
        )
        layout.addWidget(self._fido2_description)

        self._register_key_btn = PrimaryPushButton("注册新安全密钥", content)
        layout.addWidget(self._register_key_btn)

        self._credentials_container = QWidget(content)
        self._credentials_layout = QVBoxLayout(self._credentials_container)
        self._credentials_layout.setContentsMargins(0, 0, 0, 0)
        self._credentials_layout.setSpacing(8)
        layout.addWidget(self._credentials_container)

        self._no_keys_label = BodyLabel("未注册安全密钥。", content)
        layout.addWidget(self._no_keys_label)

        # ---- API Settings ----
        self._api_title = TitleLabel("API", content)
        layout.addWidget(self._api_title)

        api_url_layout = QHBoxLayout()
        api_url_layout.setSpacing(12)
        api_url_layout.addWidget(BodyLabel("服务器地址：", content))
        self._api_url_edit = LineEdit(content)
        self._api_url_edit.setText(self._services.config.api_base_url)
        api_url_layout.addWidget(self._api_url_edit, stretch=1)
        layout.addLayout(api_url_layout)

        layout.addStretch()

        scroll.setWidget(content)
        outer_layout.addWidget(scroll)

    def _connect_signals(self) -> None:
        """Wire settings change signals."""
        self._logout_btn.clicked.connect(self._on_logout)
        self._browse_btn.clicked.connect(self._on_browse_download_dir)
        self._register_key_btn.clicked.connect(self._on_register_fido2_key)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        self._concurrent_combo.currentIndexChanged.connect(self._on_concurrent_changed)
        self._services.auth_state_changed.connect(self._on_auth_changed)

    def _load_settings(self) -> None:
        """Load current settings into the UI."""
        self._update_account_info()
        self._load_fido2_credentials()

    def _update_account_info(self) -> None:
        """Update the account section with current user info."""
        auth = self._services.auth_service
        if auth.is_authenticated and auth.user_info:
            info = auth.user_info
            self._username_label.setText(info.get("username", "未知"))
            self._email_label.setText(info.get("email", ""))
            role = info.get("role", "user")
            self._role_label.setText(f"Role: {role.title()}")
        else:
            self._username_label.setText("未登录")
            self._email_label.setText("")
            self._role_label.setText("")

    @Slot()
    def _on_logout(self) -> None:
        """Handle logout button click."""
        self._services.auth_service.logout()
        self.logout_requested.emit()

    @Slot(bool)
    def _on_auth_changed(self, authenticated: bool) -> None:
        """Update account info when auth state changes."""
        self._update_account_info()

    @Slot()
    def _on_browse_download_dir(self) -> None:
        """Open a directory chooser for the download folder."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择下载目录",
            str(self._services.config.download_dir),
        )
        if directory:
            self._download_dir_edit.setText(directory)
            from pathlib import Path

            self._services.config.download_dir = Path(directory)
            self._services.config.download_dir.mkdir(parents=True, exist_ok=True)
            self.settings_changed.emit()

    @Slot(int)
    def _on_theme_changed(self, index: int) -> None:
        """Handle theme selection change."""
        themes = ["auto", "light", "dark"]
        selected = themes[index] if index < len(themes) else "auto"
        logger.info("Theme changed to: %s", selected)
        self.settings_changed.emit()

    @Slot(int)
    def _on_concurrent_changed(self, index: int) -> None:
        """Handle concurrent downloads setting change."""
        count = index + 1
        self._services.config.max_concurrent_downloads = count
        self.settings_changed.emit()

    def _load_fido2_credentials(self) -> None:
        """Load FIDO2 credentials from the server."""
        # Clear existing cards
        for card in self._credential_cards:
            card.deleteLater()
        self._credential_cards.clear()

        if not self._services.auth_service.is_authenticated:
            self._no_keys_label.setVisible(True)
            return

        try:
            response = self._services.api_client.get(_FIDO2_CREDENTIALS_PATH)
            credentials = [Fido2Credential.from_dict(c) for c in response.get("credentials", [])]

            self._no_keys_label.setVisible(len(credentials) == 0)

            for cred in credentials:
                card = Fido2CredentialCard(cred, parent=self._credentials_container)
                card.delete_clicked.connect(
                    lambda cid=cred.credential_id: self._on_delete_credential(cid)
                )
                self._credential_cards.append(card)
                self._credentials_layout.addWidget(card)

        except ApiError as exc:
            logger.warning("Could not load FIDO2 credentials: %s", exc)
            self._no_keys_label.setVisible(True)
        except Exception as exc:
            logger.warning("Unexpected error loading FIDO2 credentials: %s", exc)
            self._no_keys_label.setVisible(True)

    @Slot()
    def _on_register_fido2_key(self) -> None:
        """Start FIDO2 key registration flow."""
        if not self._services.auth_service.is_authenticated:
            InfoBar.warning(
                title="未认证",
                content="请先登录再注册安全密钥。",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000,
            )
            return

        try:
            response = self._services.api_client.post(_FIDO2_REGISTER_BEGIN_PATH)
        except ApiError as exc:
            InfoBar.error(
                title="注册错误",
                content=f"无法开始注册: {exc.detail}",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=5000,
            )
            return

        # Extract the state token from the server response for the completion step
        state_token = response.get("state", "")

        touch_dialog = Fido2TouchDialog(self)

        from _mext.services.fido2_worker import Fido2RegisterWorker

        worker = Fido2RegisterWorker(
            fido2_client=self._services.fido2_client,
            creation_options=response.get("options", response),
            parent=self,
        )

        worker.touch_required.connect(touch_dialog.show)
        worker.pin_required.connect(lambda retries: self._show_pin_dialog(worker, retries))
        worker.completed.connect(
            lambda result: self._on_register_complete(result, touch_dialog, state_token)
        )
        worker.error.connect(lambda msg: self._on_register_error(msg, touch_dialog))

        worker.start()

    def _show_pin_dialog(self, worker: Any, retries: int) -> None:
        """Show the PIN entry dialog and provide PIN to worker."""
        dialog = Fido2PinDialog(retries, parent=self)
        if dialog.exec():
            pin = dialog.get_pin()
            worker.provide_pin(pin)

    def _on_register_complete(
        self, result: dict, dialog: Fido2TouchDialog, state_token: str
    ) -> None:
        """Handle successful FIDO2 key registration."""
        dialog.close()

        try:
            # Send attestation, state, and a default credential name
            # matching the server's Fido2RegisterCompleteRequest schema
            self._services.api_client.post(
                _FIDO2_REGISTER_COMPLETE_PATH,
                json={
                    "attestation": result,
                    "state": state_token,
                    "credential_name": "Security Key",
                },
            )
            InfoBar.success(
                title="安全密钥已注册",
                content="你的安全密钥已注册成功。",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=4000,
            )
            self._load_fido2_credentials()
        except ApiError as exc:
            InfoBar.error(
                title="注册失败",
                content=f"无法完成注册: {exc.detail}",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=5000,
            )

    def _on_register_error(self, message: str, dialog: Fido2TouchDialog) -> None:
        """Handle FIDO2 registration error."""
        dialog.close()
        InfoBar.error(
            title="注册错误",
            content=message,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000,
        )

    def _on_delete_credential(self, credential_id: str) -> None:
        """Delete a FIDO2 credential."""
        try:
            self._services.api_client.delete(f"{_FIDO2_CREDENTIALS_PATH}/{credential_id}")
            InfoBar.success(
                title="密钥已移除",
                content="安全密钥已移除。",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000,
            )
            self._load_fido2_credentials()
        except ApiError as exc:
            InfoBar.error(
                title="删除失败",
                content=f"无法移除密钥: {exc.detail}",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=5000,
            )
