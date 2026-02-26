"""FIDO2 PIN entry dialog.

A modal dialog for entering the authenticator PIN, shown when the
FIDO2 device requires PIN verification for an operation.
"""

from __future__ import annotations

from typing import Optional

from qfluentwidgets import (
    BodyLabel,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
)
from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QWidget,
)


class Fido2PinDialog(QDialog):
    """Modal dialog for FIDO2 authenticator PIN entry.

    Parameters
    ----------
    retries_remaining : int
        Number of PIN attempts remaining. Displayed as a hint.
    parent : QWidget, optional
        Parent widget.
    """

    def __init__(
        self,
        retries_remaining: int = 8,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._retries = retries_remaining
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the PIN entry dialog layout."""
        self.setWindowTitle("Security Key PIN")
        self.setFixedSize(360, 240)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(32, 24, 32, 24)

        # Title
        self._title_label = SubtitleLabel("输入 PIN", self)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title_label)

        # Description
        self._description_label = BodyLabel(
            "Enter the PIN for your security key.",
            self,
        )
        self._description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._description_label)

        # Retries hint
        if self._retries < 8:
            self._retries_label = BodyLabel(
                f"Attempts remaining: {self._retries}",
                self,
            )
            self._retries_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._retries_label.setStyleSheet("color: #e74c3c;")
            layout.addWidget(self._retries_label)

        # PIN input
        self._pin_edit = LineEdit(self)
        self._pin_edit.setPlaceholderText("PIN")
        self._pin_edit.setEchoMode(LineEdit.EchoMode.Password)
        self._pin_edit.setFixedHeight(36)
        self._pin_edit.setClearButtonEnabled(True)
        layout.addWidget(self._pin_edit)

        layout.addSpacing(8)

        # Buttons
        self._ok_btn = PrimaryPushButton("Verify", self)
        self._ok_btn.setFixedHeight(36)
        self._ok_btn.clicked.connect(self._on_verify)
        layout.addWidget(self._ok_btn)

        self._cancel_btn = PushButton("Cancel", self)
        self._cancel_btn.setFixedHeight(36)
        self._cancel_btn.clicked.connect(self.reject)
        layout.addWidget(self._cancel_btn)

        # Enter key submits
        self._pin_edit.returnPressed.connect(self._on_verify)

        # Focus the PIN input
        self._pin_edit.setFocus()

    def _on_verify(self) -> None:
        """Validate and accept the entered PIN."""
        pin = self._pin_edit.text()
        if not pin:
            self._description_label.setText("请输入你的 PIN。")
            self._description_label.setStyleSheet("color: #e74c3c;")
            return

        if len(pin) < 4:
            self._description_label.setText("PIN 至少需要 4 个字符。")
            self._description_label.setStyleSheet("color: #e74c3c;")
            return

        self.accept()

    def get_pin(self) -> str:
        """Return the entered PIN string.

        Should be called after ``exec()`` returns ``QDialog.Accepted``.
        """
        return self._pin_edit.text()
