"""Modal login dialog for on-demand authentication.

Wraps the existing LoginPage in a QDialog so it can be shown as a
modal popup when an operation requires authentication.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import pyqtSignal as Signal
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QWidget

from _mext.core.service_manager import ServiceManager


class LoginDialog(QDialog):
    """Modal login dialog wrapping LoginPage for on-demand authentication."""

    login_successful = Signal()

    def __init__(
        self,
        service_manager: ServiceManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("登录")
        self.setFixedSize(480, 560)
        self.setModal(True)

        from _mext.ui.pages.login_page import LoginPage

        self._login_page = LoginPage(service_manager, parent=self)
        self._login_page.login_successful.connect(self._on_success)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._login_page)

    def _on_success(self) -> None:
        self.login_successful.emit()
        self.accept()
