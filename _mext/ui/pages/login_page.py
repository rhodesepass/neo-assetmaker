"""Login page for the asset store.

Provides username/password login, DRM (OAuth2) login, FIDO2 security
key authentication, and a registration link. Uses QFluentWidgets
components for a modern Fluent Design appearance.
"""

from __future__ import annotations

import logging
from typing import Optional

from qfluentwidgets import (
    BodyLabel,
    HyperlinkButton,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PasswordLineEdit,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TitleLabel,
)
from qtpy.QtCore import Qt, Signal, Slot
from qtpy.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from _mext.core.service_manager import ServiceManager
from _mext.services.api_client import ApiError
from _mext.ui.dialogs.fido2_touch_dialog import Fido2TouchDialog

logger = logging.getLogger(__name__)


class LoginPage(QWidget):
    """Authentication page with multiple login methods.

    Signals
    -------
    login_successful()
        Emitted when the user is successfully authenticated.
    register_requested()
        Emitted when the user clicks the register link.
    """

    login_successful = Signal()
    register_requested = Signal()

    def __init__(
        self,
        service_manager: ServiceManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._services = service_manager
        self._is_registering = False
        self._pending_fido2 = False

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        """Build the login form layout."""
        outer_layout = QVBoxLayout(self)
        outer_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Centered form container
        form_container = QWidget(self)
        form_container.setFixedWidth(400)
        form_layout = QVBoxLayout(form_container)
        form_layout.setSpacing(16)
        form_layout.setContentsMargins(32, 32, 32, 32)

        # Title
        self._title_label = TitleLabel("素材商城", form_container)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        form_layout.addWidget(self._title_label)

        self._subtitle_label = SubtitleLabel("登录你的账户", form_container)
        self._subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        form_layout.addWidget(self._subtitle_label)

        form_layout.addSpacing(16)

        # Username field
        self._username_edit = LineEdit(form_container)
        self._username_edit.setPlaceholderText("用户名")
        self._username_edit.setClearButtonEnabled(True)
        form_layout.addWidget(self._username_edit)

        # Email field (only for registration)
        self._email_edit = LineEdit(form_container)
        self._email_edit.setPlaceholderText("邮箱地址")
        self._email_edit.setClearButtonEnabled(True)
        self._email_edit.setVisible(False)
        form_layout.addWidget(self._email_edit)

        # Password field
        self._password_edit = PasswordLineEdit(form_container)
        self._password_edit.setPlaceholderText("密码")
        form_layout.addWidget(self._password_edit)

        form_layout.addSpacing(8)

        # Login button
        self._login_btn = PrimaryPushButton("登录", form_container)
        self._login_btn.setFixedHeight(40)
        form_layout.addWidget(self._login_btn)

        # Separator
        separator_layout = QHBoxLayout()
        left_line = QWidget(form_container)
        left_line.setFixedHeight(1)
        left_line.setStyleSheet("background-color: #d0d0d0;")
        or_label = BodyLabel("或", form_container)
        or_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_line = QWidget(form_container)
        right_line.setFixedHeight(1)
        right_line.setStyleSheet("background-color: #d0d0d0;")
        separator_layout.addWidget(left_line)
        separator_layout.addWidget(or_label)
        separator_layout.addWidget(right_line)
        form_layout.addLayout(separator_layout)

        # DRM Login button (OAuth2)
        self._drm_login_btn = PushButton("使用 DRM 登录", form_container)
        self._drm_login_btn.setFixedHeight(40)
        form_layout.addWidget(self._drm_login_btn)

        # FIDO2 Security Key button
        self._fido2_btn = PushButton("使用安全密钥登录", form_container)
        self._fido2_btn.setFixedHeight(40)
        form_layout.addWidget(self._fido2_btn)

        form_layout.addSpacing(16)

        # Register / back to login link
        link_layout = QHBoxLayout()
        link_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._toggle_label = BodyLabel("没有账户？", form_container)
        self._toggle_link = HyperlinkButton("", "注册", form_container)
        link_layout.addWidget(self._toggle_label)
        link_layout.addWidget(self._toggle_link)
        form_layout.addLayout(link_layout)

        outer_layout.addWidget(form_container, alignment=Qt.AlignmentFlag.AlignCenter)

    def _connect_signals(self) -> None:
        """Wire button clicks and auth service signals."""
        self._login_btn.clicked.connect(self._on_login_clicked)
        self._drm_login_btn.clicked.connect(self._on_drm_login_clicked)
        self._fido2_btn.clicked.connect(self._on_fido2_login_clicked)
        self._toggle_link.clicked.connect(self._toggle_register_mode)
        self._password_edit.returnPressed.connect(self._on_login_clicked)

        # Auth service signals
        self._services.auth_service.login_error.connect(self._on_login_error)
        self._services.auth_service.fido2_required.connect(self._on_fido2_required)

    @Slot()
    def _on_login_clicked(self) -> None:
        """Handle the login/register button click."""
        username = self._username_edit.text().strip()
        password = self._password_edit.text()

        if not username:
            self._show_error("请输入用户名。")
            return

        if not password:
            self._show_error("请输入密码。")
            return

        self._set_loading(True)
        self._pending_fido2 = False

        if self._is_registering:
            email = self._email_edit.text().strip()
            if not email:
                self._show_error("请输入邮箱地址。")
                self._set_loading(False)
                return
            success = self._services.auth_service.register(username, email, password)
        else:
            success = self._services.auth_service.login(username, password)

        # Do not reset loading state if FIDO2 flow was initiated; the
        # fido2_required signal handler will manage the loading state.
        if not self._pending_fido2:
            self._set_loading(False)

        if success:
            self._clear_fields()
            self.login_successful.emit()

    @Slot()
    def _on_drm_login_clicked(self) -> None:
        """Start the OAuth2 + PKCE login flow."""
        self._set_loading(True)
        self._services.auth_service.initiate_drm_login()

        InfoBar.info(
            title="浏览器已打开",
            content="请在浏览器中完成登录。",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000,
        )

        # Handle callback in a non-blocking way
        import threading

        def _wait_for_callback() -> None:
            success = self._services.auth_service.handle_callback()
            # Schedule UI update on the main thread
            from qtpy.QtCore import QMetaObject

            if success:
                QMetaObject.invokeMethod(
                    self, "_on_drm_login_success", Qt.ConnectionType.QueuedConnection
                )
            else:
                QMetaObject.invokeMethod(
                    self, "_on_drm_login_failure", Qt.ConnectionType.QueuedConnection
                )

        thread = threading.Thread(target=_wait_for_callback, daemon=True)
        thread.start()

    @Slot()
    def _on_drm_login_success(self) -> None:
        """Handle successful DRM login callback."""
        self._set_loading(False)
        self._clear_fields()
        self.login_successful.emit()

    @Slot()
    def _on_drm_login_failure(self) -> None:
        """Handle failed DRM login callback."""
        self._set_loading(False)

    @Slot()
    def _on_fido2_login_clicked(self) -> None:
        """Start FIDO2 security key authentication (passwordless flow)."""
        self._set_loading(True)
        self._start_fido2_auth(username=None, fido2_token=None)

    @Slot(str, str)
    def _on_fido2_required(self, fido2_token: str, username: str) -> None:
        """Handle FIDO2 second-factor requirement after password login.

        The server indicated the user has FIDO2 enabled and returned a
        fido2_token. We must now complete the FIDO2 challenge.
        """
        self._pending_fido2 = True
        InfoBar.info(
            title="需要安全密钥",
            content="请使用安全密钥完成登录。",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=4000,
        )
        self._start_fido2_auth(username=username, fido2_token=fido2_token)

    def _start_fido2_auth(
        self,
        username: str | None = None,
        fido2_token: str | None = None,
    ) -> None:
        """Common FIDO2 authentication flow for both passwordless and 2FA modes."""
        try:
            # Request challenge from server
            body: dict = {}
            if username:
                body["username"] = username
            challenge_data = self._services.api_client.post(
                "auth/fido2/login/begin",
                json=body,
            )
        except ApiError as exc:
            self._show_error(f"Could not start FIDO2 authentication: {exc.detail}")
            self._set_loading(False)
            return

        # Store fido2_token and state for the completion step
        state_token = challenge_data.get("state", "")

        # Show touch dialog
        touch_dialog = Fido2TouchDialog(self)

        from _mext.services.fido2_worker import Fido2AuthWorker

        worker = Fido2AuthWorker(
            fido2_client=self._services.fido2_client,
            request_options=challenge_data.get("options", challenge_data),
            parent=self,
        )

        worker.touch_required.connect(touch_dialog.show)
        worker.completed.connect(
            lambda result: self._on_fido2_auth_complete(
                result, touch_dialog, state_token, fido2_token
            )
        )
        worker.error.connect(lambda msg: self._on_fido2_auth_error(msg, touch_dialog))

        worker.start()

    def _on_fido2_auth_complete(
        self,
        result: dict,
        dialog: Fido2TouchDialog,
        state_token: str,
        fido2_token: str | None,
    ) -> None:
        """Handle successful FIDO2 authentication."""
        dialog.close()

        try:
            payload = {
                "assertion": result,
                "state": state_token,
            }
            if fido2_token:
                payload["fido2_token"] = fido2_token

            token_data = self._services.api_client.post(
                "auth/fido2/login/complete",
                json=payload,
            )
            self._services.auth_service._handle_token_response(token_data)
            self._set_loading(False)
            self._clear_fields()
            self.login_successful.emit()
        except ApiError as exc:
            self._show_error(f"FIDO2 verification failed: {exc.detail}")
            self._set_loading(False)

    def _on_fido2_auth_error(self, message: str, dialog: Fido2TouchDialog) -> None:
        """Handle FIDO2 authentication error."""
        dialog.close()
        self._show_error(message)
        self._set_loading(False)

    @Slot()
    def _toggle_register_mode(self) -> None:
        """Toggle between login and registration mode."""
        self._is_registering = not self._is_registering

        if self._is_registering:
            self._subtitle_label.setText("创建新账户")
            self._login_btn.setText("注册")
            self._email_edit.setVisible(True)
            self._toggle_label.setText("已有账户？")
            self._toggle_link.setText("登录")
            self._drm_login_btn.setVisible(False)
            self._fido2_btn.setVisible(False)
        else:
            self._subtitle_label.setText("登录你的账户")
            self._login_btn.setText("登录")
            self._email_edit.setVisible(False)
            self._toggle_label.setText("没有账户？")
            self._toggle_link.setText("注册")
            self._drm_login_btn.setVisible(True)
            self._fido2_btn.setVisible(True)

    @Slot(str)
    def _on_login_error(self, message: str) -> None:
        """Display a login error in an InfoBar."""
        self._set_loading(False)
        self._show_error(message)

    def _show_error(self, message: str) -> None:
        """Show an error InfoBar at the top of the page."""
        InfoBar.error(
            title="错误",
            content=message,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000,
        )

    def _set_loading(self, loading: bool) -> None:
        """Enable or disable form elements during async operations."""
        self._login_btn.setEnabled(not loading)
        self._drm_login_btn.setEnabled(not loading)
        self._fido2_btn.setEnabled(not loading)
        self._username_edit.setEnabled(not loading)
        self._password_edit.setEnabled(not loading)
        self._email_edit.setEnabled(not loading)

    def _clear_fields(self) -> None:
        """Clear all input fields."""
        self._username_edit.clear()
        self._password_edit.clear()
        self._email_edit.clear()
