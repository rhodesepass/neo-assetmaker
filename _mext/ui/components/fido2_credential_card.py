"""FIDO2 credential card widget.

Displays information about a registered FIDO2 security key credential
including name, creation date, last usage, and a delete button.
"""

from __future__ import annotations

from typing import Optional

from qfluentwidgets import (
    CaptionLabel,
    CardWidget,
    PushButton,
    SubtitleLabel,
)
from qtpy.QtCore import Signal
from qtpy.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from _mext.models.user import Fido2Credential


class Fido2CredentialCard(CardWidget):
    """Card showing a registered FIDO2 credential with a delete button.

    Signals
    -------
    delete_clicked(str)
        Emitted when the delete button is clicked.
        Payload is the credential ID.
    """

    delete_clicked = Signal(str)

    def __init__(
        self,
        credential: Fido2Credential,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._credential = credential
        self.setFixedHeight(80)
        self._setup_ui()
        self._populate()

    def _setup_ui(self) -> None:
        """Build the card layout."""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(16, 12, 16, 12)
        main_layout.setSpacing(16)

        # Left: credential info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        self._name_label = SubtitleLabel("", self)
        info_layout.addWidget(self._name_label)

        self._details_label = CaptionLabel("", self)
        info_layout.addWidget(self._details_label)

        self._last_used_label = CaptionLabel("", self)
        info_layout.addWidget(self._last_used_label)

        main_layout.addLayout(info_layout, stretch=1)

        # Right: delete button
        self._delete_btn = PushButton("Remove", self)
        self._delete_btn.setFixedWidth(80)
        self._delete_btn.clicked.connect(self._on_delete)
        main_layout.addWidget(self._delete_btn)

    def _populate(self) -> None:
        """Fill card content from the credential model."""
        self._name_label.setText(self._credential.name)

        created = self._credential.created_at.strftime("%B %d, %Y at %H:%M")
        self._details_label.setText(f"Registered: {created}")

        if self._credential.last_used:
            last_used = self._credential.last_used.strftime("%B %d, %Y at %H:%M")
            self._last_used_label.setText(f"Last used: {last_used}")
        else:
            self._last_used_label.setText("Last used: Never")

    def _on_delete(self) -> None:
        """Emit the delete signal with the credential ID."""
        self.delete_clicked.emit(self._credential.credential_id)

    @property
    def credential(self) -> Fido2Credential:
        """Return the associated FIDO2 credential."""
        return self._credential
