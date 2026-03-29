"""Gallery-style material card with variable height.

Designed for use in a WaterfallLayout.  Width is fixed (set by the
layout column width); height adapts to the preview image aspect ratio
and text content.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from qfluentwidgets import (
    AvatarWidget,
    BodyLabel,
    CaptionLabel,
    ElevatedCardWidget,
    FluentIcon,
    ImageLabel,
    PillPushButton,
    ToolButton,
    TransparentTogglePushButton,
    isDarkTheme,
)
from PyQt6.QtCore import (
    QPropertyAnimation,
    QSize,
    Qt,
    pyqtSignal as Signal,
)
from PyQt6.QtGui import QColor, QFont, QPixmap
from PyQt6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from _mext.models.material import Material
from _mext.ui.styles import (
    AVATAR_SM,
    COLOR_PLACEHOLDER_BG,
    GALLERY_CARD_BORDER_RADIUS,
    SPACING_SM,
    SPACING_XS,
    pick,
)


class GalleryCard(ElevatedCardWidget):
    """Variable-height gallery card for waterfall layouts.

    Width is externally controlled (via ``setFixedWidth``).
    Height is determined by ``sizeHint()`` based on the preview image
    aspect ratio and text content.

    Signals
    -------
    clicked(str)
        Material ID when the card body is clicked.
    download_clicked(str)
        Material ID when the download action is triggered.
    favorite_toggled(str, bool)
        (material_id, should_like) when the favorite toggle changes.
    creator_clicked(str)
        Creator ID when the creator name/avatar is clicked.
    """

    clicked = Signal(str)
    download_clicked = Signal(str)
    favorite_toggled = Signal(str, bool)  # (material_id, should_like)
    creator_clicked = Signal(str)

    # Default width — will be overridden by WaterfallLayout
    _DEFAULT_WIDTH = 260

    def __init__(
        self,
        material: Material,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._material = material
        self._image_height = self._compute_image_height(self._DEFAULT_WIDTH)
        self._hover_overlay: Optional[QWidget] = None
        self._hover_anim: Optional[QPropertyAnimation] = None

        self.setFixedWidth(self._DEFAULT_WIDTH)
        self.setBorderRadius(GALLERY_CARD_BORDER_RADIUS)

        self._setup_ui()
        self._populate()
        self._setup_hover_overlay()

    def _compute_image_height(self, width: int) -> int:
        """Compute preview image height from aspect ratio."""
        ratio = self._material.preview_aspect_ratio
        if ratio <= 0:
            ratio = 1.5
        return max(80, int(width / ratio))

    # ── UI setup ──────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, SPACING_SM)
        layout.setSpacing(0)

        # Preview image
        self._image_container = QWidget(self)
        self._image_container.setFixedHeight(self._image_height)
        img_layout = QVBoxLayout(self._image_container)
        img_layout.setContentsMargins(0, 0, 0, 0)

        self._image_label = ImageLabel(self._image_container)
        self._image_label.setBorderRadius(
            GALLERY_CARD_BORDER_RADIUS, GALLERY_CARD_BORDER_RADIUS, 0, 0
        )
        self._image_label.setFixedHeight(self._image_height)
        self._image_label.scaledToWidth(self._DEFAULT_WIDTH)
        img_layout.addWidget(self._image_label)
        layout.addWidget(self._image_container)

        # Info area
        info_widget = QWidget(self)
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(SPACING_SM + 2, SPACING_SM, SPACING_SM + 2, 0)
        info_layout.setSpacing(SPACING_XS)

        # Creator row: [avatar 24px] creator_name ... [fav btn]
        creator_row = QHBoxLayout()
        creator_row.setSpacing(6)

        self._avatar_widget = AvatarWidget(self)
        self._avatar_widget.setRadius(AVATAR_SM // 2)
        self._avatar_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        self._avatar_widget.mousePressEvent = self._on_creator_area_clicked
        creator_row.addWidget(self._avatar_widget)

        self._creator_label = CaptionLabel("", self)
        self._creator_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._creator_label.mousePressEvent = self._on_creator_area_clicked
        creator_row.addWidget(self._creator_label, stretch=1)

        self._fav_btn = TransparentTogglePushButton(FluentIcon.HEART, self)
        self._fav_btn.setFixedSize(24, 24)
        self._fav_btn.setChecked(self._material.is_liked)
        self._fav_btn.toggled.connect(self._on_favorite_toggled)
        creator_row.addWidget(self._fav_btn)

        info_layout.addLayout(creator_row)

        # Title (max 2 lines)
        self._title_label = BodyLabel("", self)
        self._title_label.setWordWrap(True)
        self._title_label.setMaximumHeight(40)  # ~2 lines
        font = self._title_label.font()
        font.setWeight(QFont.Weight.DemiBold)
        self._title_label.setFont(font)
        info_layout.addWidget(self._title_label)

        # Bottom row: [category pill]  ⬇ count
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(6)

        self._category_pill = PillPushButton("", self)
        self._category_pill.setFixedHeight(20)
        self._category_pill.setCheckable(False)
        bottom_row.addWidget(self._category_pill)

        bottom_row.addStretch()

        self._stats_label = CaptionLabel("", self)
        bottom_row.addWidget(self._stats_label)

        info_layout.addLayout(bottom_row)
        layout.addWidget(info_widget)

    def _populate(self) -> None:
        """Fill card content from the material model."""
        m = self._material

        self._title_label.setText(m.name)
        self._title_label.setToolTip(m.name)
        self._creator_label.setText(m.operator_name or "Unknown")
        self._category_pill.setText(m.category.display_name)

        # Stats: downloads
        stats_parts = []
        if m.download_count > 0:
            count = m.download_count
            if count >= 1000:
                stats_parts.append(f"\u2b07{count / 1000:.1f}k")
            else:
                stats_parts.append(f"\u2b07{count}")
        if m.like_count > 0:
            stats_parts.append(f"\u2661{m.like_count}")
        self._stats_label.setText("  ".join(stats_parts))

        # Placeholder preview image
        w = self.width()
        h = self._image_height
        placeholder = QPixmap(w, h)
        bg_hex = pick(COLOR_PLACEHOLDER_BG)
        placeholder.fill(QColor(bg_hex))
        self._image_label.setPixmap(placeholder)

    # ── Hover overlay ─────────────────────────────────────────

    def _setup_hover_overlay(self) -> None:
        """Create a semi-transparent overlay with action buttons."""
        self._hover_overlay = QWidget(self._image_container)
        self._hover_overlay.setGeometry(0, 0, self.width(), self._image_height)
        self._hover_overlay.setStyleSheet(
            f"background: rgba(0,0,0,0.45); "
            f"border-top-left-radius: {GALLERY_CARD_BORDER_RADIUS}px; "
            f"border-top-right-radius: {GALLERY_CARD_BORDER_RADIUS}px;"
        )

        overlay_layout = QHBoxLayout(self._hover_overlay)
        overlay_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overlay_layout.setSpacing(12)

        btn_style = (
            "ToolButton { background: rgba(255,255,255,0.2); border-radius: 16px; }"
            "ToolButton:hover { background: rgba(255,255,255,0.35); }"
        )

        preview_btn = ToolButton(FluentIcon.ZOOM, self._hover_overlay)
        preview_btn.setFixedSize(32, 32)
        preview_btn.setStyleSheet(btn_style)
        preview_btn.clicked.connect(lambda: self.clicked.emit(self._material.id))
        overlay_layout.addWidget(preview_btn)

        download_btn = ToolButton(FluentIcon.DOWNLOAD, self._hover_overlay)
        download_btn.setFixedSize(32, 32)
        download_btn.setStyleSheet(btn_style)
        download_btn.clicked.connect(self._on_download_clicked)
        overlay_layout.addWidget(download_btn)

        fav_btn = ToolButton(FluentIcon.HEART, self._hover_overlay)
        fav_btn.setFixedSize(32, 32)
        fav_btn.setStyleSheet(btn_style)
        fav_btn.clicked.connect(lambda: self._fav_btn.toggle())
        overlay_layout.addWidget(fav_btn)

        # Opacity effect for fade animation
        self._overlay_effect = QGraphicsOpacityEffect(self._hover_overlay)
        self._overlay_effect.setOpacity(0.0)
        self._hover_overlay.setGraphicsEffect(self._overlay_effect)
        self._hover_overlay.setVisible(True)

        self._hover_anim = QPropertyAnimation(self._overlay_effect, b"opacity", self)
        self._hover_anim.setDuration(200)

    def enterEvent(self, event: Any) -> None:  # noqa: N802
        super().enterEvent(event)
        if self._hover_anim:
            self._hover_anim.stop()
            self._hover_anim.setStartValue(self._overlay_effect.opacity())
            self._hover_anim.setEndValue(1.0)
            self._hover_anim.start()

    def leaveEvent(self, event: Any) -> None:  # noqa: N802
        super().leaveEvent(event)
        if self._hover_anim:
            self._hover_anim.stop()
            self._hover_anim.setStartValue(self._overlay_effect.opacity())
            self._hover_anim.setEndValue(0.0)
            self._hover_anim.start()

    # ── Size hint ─────────────────────────────────────────────

    def sizeHint(self) -> QSize:  # noqa: N802
        w = self.width() or self._DEFAULT_WIDTH
        # image + info padding + creator row + title (~2 lines) + bottom row
        info_height = (
            SPACING_SM           # top margin
            + AVATAR_SM + 4      # creator row
            + 40                 # title (2 lines max)
            + 20 + SPACING_SM    # bottom row + bottom margin
        )
        return QSize(w, self._image_height + info_height)

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        new_w = event.size().width()
        if new_w != self._DEFAULT_WIDTH:
            self._image_height = self._compute_image_height(new_w)
            self._image_container.setFixedHeight(self._image_height)
            self._image_label.setFixedHeight(self._image_height)
            if self._hover_overlay:
                self._hover_overlay.setGeometry(0, 0, new_w, self._image_height)

    # ── Signals ───────────────────────────────────────────────

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        self.clicked.emit(self._material.id)

    def _on_download_clicked(self) -> None:
        self.download_clicked.emit(self._material.id)

    def _on_creator_area_clicked(self, event) -> None:
        if self._material.creator_id:
            self.creator_clicked.emit(self._material.creator_id)

    def _on_favorite_toggled(self, checked: bool) -> None:
        self.favorite_toggled.emit(self._material.id, checked)

    # ── Public API ────────────────────────────────────────────

    @property
    def material(self) -> Material:
        return self._material

    def set_preview_pixmap(self, pixmap: QPixmap) -> None:
        """Update the preview image (called by ThumbnailLoader)."""
        if pixmap.isNull():
            return
        scaled = pixmap.scaledToWidth(
            self.width(), Qt.TransformationMode.SmoothTransformation
        )
        self._image_label.setPixmap(scaled)
        # Update image height based on actual image ratio
        if pixmap.width() > 0:
            actual_ratio = pixmap.width() / pixmap.height()
            new_h = max(80, int(self.width() / actual_ratio))
            self._image_height = new_h
            self._image_container.setFixedHeight(new_h)
            self._image_label.setFixedHeight(new_h)
            if self._hover_overlay:
                self._hover_overlay.setGeometry(0, 0, self.width(), new_h)
            self.updateGeometry()

    def set_avatar_pixmap(self, pixmap: QPixmap) -> None:
        """Update the creator avatar image."""
        if pixmap.isNull():
            return
        self._avatar_widget.setImage(pixmap)

    def update_like_state(self, is_liked: bool, like_count: int) -> None:
        """Update like state from external source (Detail <-> Discover sync)."""
        self._material.is_liked = is_liked
        self._material.like_count = like_count
        self._fav_btn.blockSignals(True)
        self._fav_btn.setChecked(is_liked)
        self._fav_btn.blockSignals(False)
        self._refresh_stats()

    def _refresh_stats(self) -> None:
        """Refresh the stats label display."""
        m = self._material
        parts = []
        if m.download_count > 0:
            count = m.download_count
            if count >= 1000:
                parts.append(f"\u2b07{count / 1000:.1f}k")
            else:
                parts.append(f"\u2b07{count}")
        if m.like_count > 0:
            parts.append(f"\u2661{m.like_count}")
        self._stats_label.setText("  ".join(parts))

    @property
    def preview_cache_key(self) -> str:
        """Cache key for the preview thumbnail."""
        return f"preview_{self._material.id}"

    @property
    def avatar_cache_key(self) -> str:
        """Cache key for the creator avatar."""
        return f"avatar_{self._material.creator_id or self._material.operator_name}"
