"""Material detail page.

Shows a large preview, full metadata, creator info, and related
materials.  Designed to be pushed onto a QStackedWidget when a
card is clicked.
"""

from __future__ import annotations

import logging
from typing import Optional

from qfluentwidgets import (
    AvatarWidget,
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    HorizontalSeparator,
    ImageLabel,
    InfoBar,
    InfoBarPosition,
    PillPushButton,
    PrimaryPushButton,
    ScrollArea,
    SubtitleLabel,
    TitleLabel,
    ToolButton,
    TransparentTogglePushButton,
    isDarkTheme,
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal as Signal, pyqtSlot as Slot
from PyQt6.QtGui import QColor, QFont, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from _mext.core.service_manager import ServiceManager
from _mext.models.material import Material
from _mext.services.api_worker import DownloadUrlWorker, LikeToggleWorker, MaterialDetailWorker, RelatedMaterialsWorker
from _mext.ui.components.comment_section import CommentSection
from _mext.ui.components.gallery_card import GalleryCard
from _mext.ui.components.thumbnail_loader import ThumbnailLoader
from _mext.ui.styles import (
    AVATAR_LG,
    COLOR_PLACEHOLDER_BG,
    DETAIL_IMAGE_MAX_HEIGHT,
    DETAIL_MAX_WIDTH,
    DETAIL_SIDEBAR_WIDTH,
    GALLERY_CARD_BORDER_RADIUS,
    RELATED_CARD_WIDTH,
    RELATED_SECTION_HEIGHT,
    SPACING_LG,
    SPACING_MD,
    SPACING_SM,
    SPACING_XL,
    pick,
)

logger = logging.getLogger(__name__)


class MaterialDetailPage(QWidget):
    """Full material detail view.

    Signals
    -------
    back_requested()
        User clicked the back button.
    download_requested(str)
        Material ID when the download button is clicked.
    creator_clicked(str)
        Creator ID when the creator name is clicked.
    """

    back_requested = Signal()
    download_requested = Signal(str)
    creator_clicked = Signal(str)
    like_state_changed = Signal(str, bool, int)  # (material_id, is_liked, new_count)

    def __init__(
        self,
        service_manager: ServiceManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._services = service_manager
        self._material: Optional[Material] = None
        self._thumb_loader = ThumbnailLoader(max_concurrent=3, parent=self)
        self._thumb_loader.thumbnail_ready.connect(self._on_thumbnail_ready)
        self._related_cards: dict = {}

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top bar ───────────────────────────────────────────
        header = QWidget(self)
        header.setFixedHeight(52)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(SPACING_MD, 0, SPACING_MD, 0)
        header_layout.setSpacing(SPACING_SM)

        self._back_btn = ToolButton(FluentIcon.LEFT_ARROW, header)
        self._back_btn.setFixedSize(36, 36)
        header_layout.addWidget(self._back_btn)

        self._header_title = SubtitleLabel("", header)
        self._header_title.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        header_layout.addWidget(self._header_title, stretch=1)

        self._download_btn = PrimaryPushButton("\u4e0b\u8f7d", header)  # 下载
        self._download_btn.setFixedHeight(34)
        self._download_btn.setIcon(FluentIcon.DOWNLOAD)
        header_layout.addWidget(self._download_btn)

        self._fav_btn = TransparentTogglePushButton(FluentIcon.HEART, header)
        self._fav_btn.setFixedSize(36, 36)
        header_layout.addWidget(self._fav_btn)

        root.addWidget(header)

        # ── Scrollable body ───────────────────────────────────
        self._scroll = ScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body = QWidget()
        body.setMaximumWidth(DETAIL_MAX_WIDTH)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(SPACING_XL, SPACING_LG, SPACING_XL, SPACING_XL)
        body_layout.setSpacing(SPACING_LG)

        # ── Main split: image (60%) | sidebar (40%) ───────────
        split = QHBoxLayout()
        split.setSpacing(SPACING_XL)

        # Left: large preview image
        left = QVBoxLayout()
        self._preview_image = ImageLabel(body)
        self._preview_image.setMinimumHeight(200)
        self._preview_image.setMaximumHeight(DETAIL_IMAGE_MAX_HEIGHT)
        self._preview_image.setBorderRadius(GALLERY_CARD_BORDER_RADIUS)
        self._preview_image.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        left.addWidget(self._preview_image)
        left.addStretch()
        split.addLayout(left, stretch=6)

        # Right: metadata sidebar
        right = QVBoxLayout()
        right.setSpacing(SPACING_MD)

        self._title_label = TitleLabel("", body)
        self._title_label.setWordWrap(True)
        right.addWidget(self._title_label)

        self._creator_row = QHBoxLayout()
        self._creator_row.setSpacing(SPACING_SM)
        by_label = CaptionLabel("by", body)
        self._creator_row.addWidget(by_label)
        self._creator_name = BodyLabel("", body)
        self._creator_name.setCursor(Qt.CursorShape.PointingHandCursor)
        self._creator_row.addWidget(self._creator_name)
        self._creator_row.addStretch()
        right.addLayout(self._creator_row)

        # Meta fields
        self._category_pill = PillPushButton("", body)
        self._category_pill.setFixedHeight(22)
        self._category_pill.setCheckable(False)
        right.addWidget(self._category_pill, alignment=Qt.AlignmentFlag.AlignLeft)

        self._tags_container = QWidget(body)
        self._tags_layout = QHBoxLayout(self._tags_container)
        self._tags_layout.setContentsMargins(0, 0, 0, 0)
        self._tags_layout.setSpacing(6)
        right.addWidget(self._tags_container)

        self._meta_labels: dict[str, CaptionLabel] = {}
        for key, label_text in [
            ("file_size", "\u6587\u4ef6\u5927\u5c0f"),       # 文件大小
            ("downloads", "\u4e0b\u8f7d\u6b21\u6570"),       # 下载次数
            ("created_at", "\u4e0a\u4f20\u65e5\u671f"),      # 上传日期
        ]:
            row = QHBoxLayout()
            row.setSpacing(SPACING_SM)
            name_lbl = CaptionLabel(f"{label_text}:", body)
            name_lbl.setFixedWidth(72)
            row.addWidget(name_lbl)
            value_lbl = CaptionLabel("", body)
            row.addWidget(value_lbl, stretch=1)
            self._meta_labels[key] = value_lbl
            right.addLayout(row)

        right.addSpacerItem(QSpacerItem(0, SPACING_LG))

        # Creator card
        creator_card = QWidget(body)
        creator_card_layout = QHBoxLayout(creator_card)
        creator_card_layout.setContentsMargins(0, 0, 0, 0)
        creator_card_layout.setSpacing(SPACING_MD)

        self._creator_avatar = AvatarWidget(creator_card)
        self._creator_avatar.setRadius(AVATAR_LG // 2)
        creator_card_layout.addWidget(self._creator_avatar)

        creator_info = QVBoxLayout()
        creator_info.setSpacing(2)
        self._creator_card_name = BodyLabel("", creator_card)
        font = self._creator_card_name.font()
        font.setWeight(QFont.Weight.DemiBold)
        self._creator_card_name.setFont(font)
        creator_info.addWidget(self._creator_card_name)
        self._creator_card_sub = CaptionLabel("", creator_card)
        creator_info.addWidget(self._creator_card_sub)
        creator_card_layout.addLayout(creator_info, stretch=1)

        right.addWidget(creator_card)
        right.addStretch()

        split.addLayout(right, stretch=4)
        body_layout.addLayout(split)

        # ── Description ───────────────────────────────────────
        desc_title = SubtitleLabel("\u63cf\u8ff0", body)  # 描述
        body_layout.addWidget(desc_title)

        self._description = BodyLabel("", body)
        self._description.setWordWrap(True)
        body_layout.addWidget(self._description)

        # ── Comment section ──────────────────────────────────────
        body_layout.addWidget(HorizontalSeparator(body))
        self._comment_section = CommentSection(self._services, parent=body)
        self._comment_section.comment_count_changed.connect(self._on_comment_count_changed)
        body_layout.addWidget(self._comment_section)

        # ── Related materials ───────────────────────────────────
        self._related_title = SubtitleLabel("相关素材", body)
        self._related_title.setVisible(False)
        body_layout.addWidget(self._related_title)

        self._related_scroll = ScrollArea(body)
        self._related_scroll.setFixedHeight(RELATED_SECTION_HEIGHT)
        self._related_scroll.setWidgetResizable(True)
        self._related_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._related_scroll.setVisible(False)

        self._related_container = QWidget()
        self._related_layout = QHBoxLayout(self._related_container)
        self._related_layout.setContentsMargins(0, 0, 0, 0)
        self._related_layout.setSpacing(SPACING_MD)
        self._related_layout.addStretch()

        self._related_scroll.setWidget(self._related_container)
        body_layout.addWidget(self._related_scroll)

        body_layout.addStretch()

        # Center the body in the scroll area
        scroll_content = QWidget()
        sc_layout = QHBoxLayout(scroll_content)
        sc_layout.setContentsMargins(0, 0, 0, 0)
        sc_layout.addStretch()
        sc_layout.addWidget(body)
        sc_layout.addStretch()

        self._scroll.setWidget(scroll_content)
        root.addWidget(self._scroll, stretch=1)

    def _connect_signals(self) -> None:
        self._back_btn.clicked.connect(self.back_requested.emit)
        self._download_btn.clicked.connect(self._on_download)
        self._fav_btn.toggled.connect(self._on_like_toggled)
        self._creator_name.mousePressEvent = self._on_creator_clicked

    # ── Public API ────────────────────────────────────────────

    def load_material(self, material: Material) -> None:
        """Populate the detail page with a Material object."""
        self._material = material
        self._populate()
        self._load_detail_from_api(material.id)

    def load_material_by_id(self, material_id: str) -> None:
        """Load material detail from the API by ID."""
        self._load_detail_from_api(material_id)

    # ── Private ───────────────────────────────────────────────

    def _populate(self) -> None:
        m = self._material
        if m is None:
            return

        self._header_title.setText(m.name)
        self._title_label.setText(m.name)
        self._creator_name.setText(m.operator_name or "Unknown")
        self._category_pill.setText(m.category.display_name)

        # Tags
        # Clear existing tag pills
        while self._tags_layout.count():
            item = self._tags_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for tag in m.tags:
            pill = PillPushButton(tag, self._tags_container)
            pill.setFixedHeight(20)
            pill.setCheckable(False)
            self._tags_layout.addWidget(pill)
        self._tags_layout.addStretch()

        # Meta
        self._meta_labels["file_size"].setText(m.file_size_display)
        self._meta_labels["downloads"].setText(f"{m.download_count:,}")
        self._meta_labels["created_at"].setText(m.created_at.strftime("%Y-%m-%d"))

        # Creator card
        self._creator_card_name.setText(m.operator_name or "Unknown")
        self._creator_card_sub.setText(f"ID: {m.creator_id}" if m.creator_id else "")

        # Description
        self._description.setText(m.description or "\u6682\u65e0\u63cf\u8ff0")  # 暂无描述

        # Preview placeholder
        placeholder = QPixmap(600, 400)
        placeholder.fill(QColor(pick(COLOR_PLACEHOLDER_BG)))
        self._preview_image.setPixmap(placeholder)

        # Load preview image
        if m.preview_image_path:
            self._thumb_loader.load(m.preview_image_path, f"detail_{m.id}")

        # Load avatar
        if m.creator_avatar_url:
            self._thumb_loader.load(m.creator_avatar_url, f"avatar_detail_{m.creator_id}")

        # Sync like button state
        self._fav_btn.blockSignals(True)
        self._fav_btn.setChecked(m.is_liked)
        self._fav_btn.blockSignals(False)

        # Load comments
        self._comment_section.load_comments(m.id)

        # Load related materials
        self._load_related(m.id)

    def _load_detail_from_api(self, material_id: str) -> None:
        """Fetch full details from the API (may contain more info than list view)."""
        self._detail_worker = MaterialDetailWorker(
            self._services.api_client, material_id, parent=self
        )
        self._detail_worker.completed.connect(self._on_detail_loaded)
        self._detail_worker.error.connect(self._on_detail_error)
        self._detail_worker.start()

    @Slot(dict)
    def _on_detail_loaded(self, data: dict) -> None:
        """Update page with full API response."""
        self._material = Material.from_dict(data)
        self._populate()

    @Slot(str)
    def _on_detail_error(self, detail: str) -> None:
        logger.warning("Failed to load material detail: %s", detail)

    @Slot(str, QPixmap)
    def _on_thumbnail_ready(self, cache_key: str, pixmap: QPixmap) -> None:
        if self._material is None:
            return
        if cache_key == f"detail_{self._material.id}":
            scaled = pixmap.scaledToWidth(
                min(pixmap.width(), self._preview_image.width() or 600),
                Qt.TransformationMode.SmoothTransformation,
            )
            self._preview_image.setPixmap(scaled)
        elif cache_key.startswith("avatar_detail_"):
            self._creator_avatar.setImage(pixmap)
        elif cache_key.startswith("related_preview_"):
            self._route_related_thumbnail(cache_key, pixmap)

    def _on_download(self) -> None:
        if self._material is None:
            return
        self.download_requested.emit(self._material.id)

    def _on_creator_clicked(self, event) -> None:
        if self._material and self._material.creator_id:
            self.creator_clicked.emit(self._material.creator_id)

    # ── Like toggle ─────────────────────────────────────────

    @Slot(bool)
    def _on_like_toggled(self, checked: bool) -> None:
        if not self._material:
            return
        self._like_worker = LikeToggleWorker(
            self._services.api_client, self._material.id, checked, parent=self
        )
        self._like_worker.completed.connect(self._on_like_completed)
        self._like_worker.error.connect(self._on_like_error)
        self._like_worker.start()

    @Slot(str, bool, int)
    def _on_like_completed(self, mid: str, is_liked: bool, count: int) -> None:
        if self._material and self._material.id == mid:
            self._material.is_liked = is_liked
            self._material.like_count = count
        self.like_state_changed.emit(mid, is_liked, count)

    @Slot(str)
    def _on_like_error(self, detail: str) -> None:
        if self._material:
            self._fav_btn.blockSignals(True)
            self._fav_btn.setChecked(self._material.is_liked)
            self._fav_btn.blockSignals(False)
        InfoBar.warning(
            title="操作失败",
            content=detail,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3000,
        )

    # ── Comment count ─────────────────────────────────────────

    @Slot(str, int)
    def _on_comment_count_changed(self, material_id: str, count: int) -> None:
        if self._material and self._material.id == material_id:
            self._material.comment_count = count

    # ── Related materials ─────────────────────────────────────

    def _load_related(self, material_id: str) -> None:
        self._related_worker = RelatedMaterialsWorker(
            self._services.api_client, material_id, limit=6, parent=self
        )
        self._related_worker.completed.connect(self._on_related_loaded)
        self._related_worker.error.connect(self._on_related_error)
        self._related_worker.start()

    @Slot(list)
    def _on_related_loaded(self, items: list) -> None:
        # Clear existing
        while self._related_layout.count():
            item = self._related_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._related_layout.addStretch()

        if not items:
            self._related_title.setVisible(False)
            self._related_scroll.setVisible(False)
            return

        self._related_title.setVisible(True)
        self._related_scroll.setVisible(True)

        self._related_cards: dict[str, GalleryCard] = {}
        for item_data in items:
            material = Material.from_dict(item_data)
            card = GalleryCard(material, parent=self._related_container)
            card.setFixedWidth(RELATED_CARD_WIDTH)
            card.clicked.connect(lambda mid: self.load_material_by_id(mid))
            idx = self._related_layout.count() - 1
            self._related_layout.insertWidget(idx, card)
            self._related_cards[material.id] = card

            if material.preview_image_path:
                cache_key = f"related_preview_{material.id}"
                cached = self._thumb_loader.load(material.preview_image_path, cache_key)
                if cached:
                    card.set_preview_pixmap(cached)

    @Slot(str)
    def _on_related_error(self, detail: str) -> None:
        logger.debug("Failed to load related materials: %s", detail)
        self._related_title.setVisible(False)
        self._related_scroll.setVisible(False)

    def _route_related_thumbnail(self, cache_key: str, pixmap: QPixmap) -> None:
        mid = cache_key[len("related_preview_"):]
        cards = self._related_cards
        card = cards.get(mid)
        if card:
            card.set_preview_pixmap(pixmap)

    def clear(self) -> None:
        """Reset the page to empty state."""
        self._material = None
        self._header_title.setText("")
        self._title_label.setText("")
        self._description.setText("")
        self._comment_section.clear()
        self._related_title.setVisible(False)
        self._related_scroll.setVisible(False)
