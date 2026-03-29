"""Creator profile page.

Shows creator information and their published works in a
waterfall layout.
"""

from __future__ import annotations

import logging
from typing import Optional

from qfluentwidgets import (
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    ScrollArea,
    SubtitleLabel,
    ToolButton,
)
from PyQt6.QtCore import Qt, pyqtSignal as Signal, pyqtSlot as Slot
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from _mext.core.constants import GALLERY_CARD_COLUMN_WIDTH, MATERIALS_PER_PAGE
from _mext.core.service_manager import ServiceManager
from _mext.models.material import Material
from _mext.services.api_worker import CreatorProfileWorker, CreatorWorksWorker
from _mext.ui.components.creator_info_card import CreatorInfoCard
from _mext.ui.components.gallery_card import GalleryCard
from _mext.ui.components.thumbnail_loader import ThumbnailLoader
from _mext.ui.layouts.waterfall_layout import WaterfallLayout
from _mext.ui.styles import (
    GALLERY_GRID_SPACING,
    SPACING_LG,
    SPACING_MD,
    SPACING_SM,
)

logger = logging.getLogger(__name__)


class CreatorProfilePage(QWidget):
    """Creator profile with info card and works gallery.

    Signals
    -------
    back_requested()
        User clicked the back button.
    material_selected(str)
        Material ID when a work card is clicked.
    download_requested(str)
        Material ID when download is triggered from a card.
    """

    back_requested = Signal()
    material_selected = Signal(str)
    download_requested = Signal(str)

    def __init__(
        self,
        service_manager: ServiceManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._services = service_manager
        self._creator_id: Optional[str] = None
        self._materials: list[Material] = []
        self._cards: dict[str, GalleryCard] = {}
        self._current_page = 1
        self._has_more = True
        self._is_loading = False

        self._thumb_loader = ThumbnailLoader(max_concurrent=4, parent=self)
        self._thumb_loader.thumbnail_ready.connect(self._on_thumbnail_ready)

        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header bar
        header = QWidget(self)
        header.setFixedHeight(52)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(SPACING_MD, 0, SPACING_MD, 0)
        header_layout.setSpacing(SPACING_SM)

        self._back_btn = ToolButton(FluentIcon.LEFT_ARROW, header)
        self._back_btn.setFixedSize(36, 36)
        self._back_btn.clicked.connect(self.back_requested.emit)
        header_layout.addWidget(self._back_btn)

        self._header_title = SubtitleLabel("", header)
        self._header_title.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        header_layout.addWidget(self._header_title, stretch=1)

        root.addWidget(header)

        # Scrollable body
        self._scroll_area = ScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll_area.verticalScrollBar().valueChanged.connect(self._on_scroll)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(SPACING_LG, SPACING_MD, SPACING_LG, SPACING_LG)
        body_layout.setSpacing(SPACING_MD)

        # Creator info card
        self._info_card = CreatorInfoCard(body)
        body_layout.addWidget(self._info_card)

        # Works section
        works_title = SubtitleLabel("作品", body)
        body_layout.addWidget(works_title)

        self._grid_container = QWidget(body)
        self._waterfall = WaterfallLayout(
            self._grid_container,
            column_width=GALLERY_CARD_COLUMN_WIDTH,
            spacing=GALLERY_GRID_SPACING,
        )
        self._waterfall.setContentsMargins(0, 0, 0, 0)
        body_layout.addWidget(self._grid_container)

        # Empty / loading states
        self._empty_label = SubtitleLabel("暂无作品", body)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)
        body_layout.addWidget(self._empty_label)

        self._loading_label = SubtitleLabel("加载中...", body)
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_label.setVisible(False)
        body_layout.addWidget(self._loading_label)

        body_layout.addStretch()

        self._scroll_area.setWidget(body)
        root.addWidget(self._scroll_area, stretch=1)

    # ── Public API ────────────────────────────────────────────

    def load_creator(self, creator_id: str) -> None:
        """Load creator profile and works."""
        self._creator_id = creator_id
        self._materials.clear()
        self._cards.clear()
        self._waterfall.clear()
        self._current_page = 1
        self._has_more = True
        self._empty_label.setVisible(False)

        # Load profile
        self._profile_worker = CreatorProfileWorker(
            self._services.api_client, creator_id, parent=self
        )
        self._profile_worker.completed.connect(self._on_profile_loaded)
        self._profile_worker.error.connect(self._on_profile_error)
        self._profile_worker.start()

        # Load works
        self._load_works()

    # ── Profile loading ───────────────────────────────────────

    @Slot(dict)
    def _on_profile_loaded(self, data: dict) -> None:
        name = data.get("display_name", data.get("username", ""))
        self._header_title.setText(name)
        self._info_card.set_profile(data)

        avatar_url = data.get("avatar_url", "")
        if avatar_url:
            cached = self._thumb_loader.load(avatar_url, f"creator_xl_{self._creator_id}")
            if cached:
                self._info_card.set_avatar(cached)

    @Slot(str)
    def _on_profile_error(self, detail: str) -> None:
        logger.warning("Failed to load creator profile: %s", detail)
        self._header_title.setText("创作者")

    # ── Works loading ─────────────────────────────────────────

    def _load_works(self) -> None:
        if self._is_loading or not self._has_more or not self._creator_id:
            return
        self._is_loading = True
        self._loading_label.setVisible(True)

        self._works_worker = CreatorWorksWorker(
            self._services.api_client,
            self._creator_id,
            page=self._current_page,
            per_page=MATERIALS_PER_PAGE,
            parent=self,
        )
        self._works_worker.completed.connect(self._on_works_loaded)
        self._works_worker.error.connect(self._on_works_error)
        self._works_worker.start()

    @Slot(list, int)
    def _on_works_loaded(self, items: list, total: int) -> None:
        self._loading_label.setVisible(False)

        for item_data in items:
            material = Material.from_dict(item_data)
            self._materials.append(material)

            card = GalleryCard(material, parent=self._grid_container)
            card.clicked.connect(lambda mid: self.material_selected.emit(mid))
            card.download_clicked.connect(lambda mid: self.download_requested.emit(mid))
            self._waterfall.addWidget(card)
            self._cards[material.id] = card

            if material.preview_image_path:
                cached = self._thumb_loader.load(
                    material.preview_image_path, card.preview_cache_key
                )
                if cached:
                    card.set_preview_pixmap(cached)

            if material.creator_avatar_url:
                cached = self._thumb_loader.load(
                    material.creator_avatar_url, card.avatar_cache_key
                )
                if cached:
                    card.set_avatar_pixmap(cached)

        self._has_more = len(self._materials) < total
        self._current_page += 1
        self._empty_label.setVisible(len(self._materials) == 0)
        self._is_loading = False

        self._grid_container.adjustSize()

    @Slot(str)
    def _on_works_error(self, detail: str) -> None:
        self._loading_label.setVisible(False)
        self._is_loading = False
        logger.warning("Failed to load creator works: %s", detail)
        InfoBar.error(
            title="加载失败",
            content=f"无法加载作品: {detail}",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000,
        )

    # ── Infinite scroll ───────────────────────────────────────

    @Slot(int)
    def _on_scroll(self, value: int) -> None:
        scrollbar = self._scroll_area.verticalScrollBar()
        if scrollbar.maximum() <= 0:
            return
        if value > scrollbar.maximum() * 0.8 and not self._is_loading and self._has_more:
            self._load_works()

    # ── Thumbnail routing ─────────────────────────────────────

    @Slot(str, QPixmap)
    def _on_thumbnail_ready(self, cache_key: str, pixmap: QPixmap) -> None:
        if cache_key.startswith("creator_xl_"):
            self._info_card.set_avatar(pixmap)
        elif cache_key.startswith("preview_"):
            mid = cache_key[len("preview_"):]
            card = self._cards.get(mid)
            if card:
                card.set_preview_pixmap(pixmap)
        elif cache_key.startswith("avatar_"):
            for card in self._cards.values():
                if card.avatar_cache_key == cache_key:
                    card.set_avatar_pixmap(pixmap)
