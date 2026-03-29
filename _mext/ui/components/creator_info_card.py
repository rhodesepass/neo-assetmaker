"""Creator information card for profile pages.

Displays creator avatar, name, and statistics.
"""

from __future__ import annotations

from typing import Optional

from qfluentwidgets import (
    AvatarWidget,
    CaptionLabel,
    HorizontalSeparator,
    TitleLabel,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from _mext.ui.styles import CREATOR_AVATAR_XL, SPACING_MD, SPACING_SM, SPACING_XS


class CreatorInfoCard(QWidget):
    """Displays creator profile information."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_MD, SPACING_MD, SPACING_MD, SPACING_MD)
        layout.setSpacing(SPACING_MD)

        # Top row: avatar + info
        top_row = QHBoxLayout()
        top_row.setSpacing(SPACING_MD)

        self._avatar = AvatarWidget(self)
        self._avatar.setRadius(CREATOR_AVATAR_XL // 2)
        top_row.addWidget(self._avatar, alignment=Qt.AlignmentFlag.AlignTop)

        info_col = QVBoxLayout()
        info_col.setSpacing(SPACING_XS)

        self._display_name = TitleLabel("", self)
        info_col.addWidget(self._display_name)

        self._username_label = CaptionLabel("", self)
        info_col.addWidget(self._username_label)

        # Stats row
        stats_row = QHBoxLayout()
        stats_row.setSpacing(SPACING_MD)

        self._works_label = CaptionLabel("", self)
        stats_row.addWidget(self._works_label)

        self._downloads_label = CaptionLabel("", self)
        stats_row.addWidget(self._downloads_label)

        stats_row.addStretch()
        info_col.addLayout(stats_row)

        top_row.addLayout(info_col, stretch=1)
        layout.addLayout(top_row)

        layout.addWidget(HorizontalSeparator(self))

    def set_profile(self, data: dict) -> None:
        """Populate the card from a profile response dict."""
        self._display_name.setText(data.get("display_name", data.get("username", "")))
        username = data.get("username", "")
        if username:
            self._username_label.setText(f"@{username}")

        works_count = data.get("materials_count", data.get("works_count", 0))
        total_downloads = data.get("total_downloads", 0)
        self._works_label.setText(f"作品: {works_count}")

        if total_downloads >= 1000:
            self._downloads_label.setText(f"下载: {total_downloads / 1000:.1f}k")
        else:
            self._downloads_label.setText(f"下载: {total_downloads}")

    def set_avatar(self, pixmap: QPixmap) -> None:
        """Update the creator avatar image."""
        if not pixmap.isNull():
            self._avatar.setImage(pixmap)
