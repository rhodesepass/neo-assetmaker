"""FIDO2 touch prompt dialog.

A modal dialog with an animated ProgressRing and instruction text,
displayed while waiting for the user to physically touch their
security key.
"""

from __future__ import annotations

from typing import Any, Optional

from qfluentwidgets import (
    BodyLabel,
    IndeterminateProgressRing,
    PushButton,
    SubtitleLabel,
)
from qtpy.QtCore import Qt, QTimer
from qtpy.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QWidget,
)


class Fido2TouchDialog(QDialog):
    """Modal dialog prompting the user to touch their security key.

    Shows an indeterminate progress ring and a message. Automatically
    closes after a configurable timeout (default 60 seconds).

    Parameters
    ----------
    parent : QWidget, optional
        Parent widget.
    timeout_seconds : int
        Automatically close after this many seconds if no touch is received.
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        timeout_seconds: int = 60,
    ) -> None:
        super().__init__(parent)
        self._timeout_seconds = timeout_seconds
        self._setup_ui()
        self._setup_timeout()

    def _setup_ui(self) -> None:
        """Build the dialog layout."""
        self.setWindowTitle("Security Key")
        self.setFixedSize(360, 260)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)
        layout.setContentsMargins(32, 32, 32, 32)

        # Progress ring (animated spinner)
        self._progress_ring = IndeterminateProgressRing(self)
        self._progress_ring.setFixedSize(64, 64)
        layout.addWidget(self._progress_ring, alignment=Qt.AlignmentFlag.AlignCenter)

        # Title
        self._title_label = SubtitleLabel("请触摸你的安全密钥", self)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title_label)

        # Description
        self._description_label = BodyLabel(
            "Please touch your FIDO2 security key\nto complete the operation.",
            self,
        )
        self._description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._description_label)

        # Cancel button
        self._cancel_btn = PushButton("Cancel", self)
        self._cancel_btn.setFixedWidth(120)
        self._cancel_btn.clicked.connect(self.reject)
        layout.addWidget(self._cancel_btn, alignment=Qt.AlignmentFlag.AlignCenter)

    def _setup_timeout(self) -> None:
        """Set up the automatic timeout timer."""
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.setInterval(self._timeout_seconds * 1000)
        self._timeout_timer.timeout.connect(self._on_timeout)

    def showEvent(self, event: Any) -> None:  # noqa: N802
        """Start the timeout timer when the dialog is shown."""
        super().showEvent(event)
        self._timeout_timer.start()

    def hideEvent(self, event: Any) -> None:  # noqa: N802
        """Stop the timeout timer when the dialog is hidden."""
        super().hideEvent(event)
        self._timeout_timer.stop()

    def _on_timeout(self) -> None:
        """Handle timeout: update message and reject."""
        self._description_label.setText("操作超时，请重试")
        self._title_label.setText("已超时")
        self._progress_ring.setVisible(False)
        # Keep dialog open so user sees the message, auto-close after 2s
        QTimer.singleShot(2000, self.reject)

    def set_message(self, title: str, description: str) -> None:
        """Update the dialog title and description text."""
        self._title_label.setText(title)
        self._description_label.setText(description)
