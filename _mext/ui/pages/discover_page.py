"""Waterfall-style discover page for browsing materials.

Replaces the legacy ForumPage with a Pinterest/ArtStation style
masonry grid, horizontal category bar, and infinite scroll.
"""

from __future__ import annotations

import logging
from typing import Optional

from qfluentwidgets import (
    ComboBox,
    FlowLayout,
    InfoBar,
    InfoBarPosition,
    PillPushButton,
    ScrollArea,
    SearchLineEdit,
    SubtitleLabel,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal as Signal, pyqtSlot as Slot
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from _mext.core.constants import GALLERY_CARD_COLUMN_WIDTH, MATERIALS_PER_PAGE, SEARCH_DEBOUNCE_MS
from _mext.core.service_manager import ServiceManager
from _mext.models.material import Material, MaterialCategory
from _mext.services.api_worker import (
    DownloadUrlWorker,
    FeaturedMaterialsWorker,
    LikeToggleWorker,
    MaterialsLoadWorker,
)
from _mext.ui.components.gallery_card import GalleryCard
from _mext.ui.components.thumbnail_loader import ThumbnailLoader
from _mext.ui.layouts.waterfall_layout import WaterfallLayout
from _mext.ui.styles import (
    COMBO_WIDTH_MD,
    FEATURED_BANNER_HEIGHT,
    FEATURED_CARD_WIDTH,
    GALLERY_GRID_SPACING,
    SPACING_MD,
    SPACING_SM,
)

logger = logging.getLogger(__name__)


class DiscoverPage(QWidget):
    """Waterfall-grid discover page with infinite scroll.

    Signals
    -------
    material_selected(str)
        Emitted when a card is clicked (material ID).
    download_requested(str)
        Emitted when a download is triggered (material ID).
    """

    material_selected = Signal(str)
    download_requested = Signal(str)
    creator_clicked = Signal(str)  # creator_id

    _SORT_OPTIONS = [
        ("\u6700\u65b0", "newest"),        # 最新
        ("\u70ed\u95e8", "popular"),        # 热门
        ("\u540d\u79f0 A-Z", "name_asc"),   # 名称 A-Z
        ("\u540d\u79f0 Z-A", "name_desc"),  # 名称 Z-A
        ("\u6587\u4ef6\u5927\u5c0f", "file_size"),  # 文件大小
    ]

    def __init__(
        self,
        service_manager: ServiceManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._services = service_manager
        self._materials: list[Material] = []
        self._cards: dict[str, GalleryCard] = {}  # material_id → card
        self._current_page = 1
        self._page_size = MATERIALS_PER_PAGE
        self._is_loading = False
        self._has_more = True

        self._current_query = ""
        self._current_category: Optional[str] = None
        self._current_sort = "newest"

        self._thumb_loader = ThumbnailLoader(parent=self)
        self._thumb_loader.thumbnail_ready.connect(self._on_thumbnail_ready)

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_SM)

        # ── Category bar (horizontal pills) ───────────────────
        cat_row = QWidget(self)
        cat_layout = QHBoxLayout(cat_row)
        cat_layout.setContentsMargins(SPACING_MD, SPACING_SM, SPACING_MD, SPACING_SM)
        cat_layout.setSpacing(8)

        self._category_pills: dict[str, PillPushButton] = {}

        # "All" pill
        all_pill = PillPushButton("All", cat_row)
        all_pill.setCheckable(True)
        all_pill.setChecked(True)
        all_pill.setFixedHeight(28)
        all_pill.clicked.connect(lambda: self._on_category_clicked(""))
        cat_layout.addWidget(all_pill)
        self._category_pills[""] = all_pill

        for category in MaterialCategory:
            pill = PillPushButton(category.display_name, cat_row)
            pill.setCheckable(True)
            pill.setChecked(False)
            pill.setFixedHeight(28)
            pill.clicked.connect(
                lambda checked, cat=category.value: self._on_category_clicked(cat)
            )
            cat_layout.addWidget(pill)
            self._category_pills[category.value] = pill

        cat_layout.addStretch()

        # Sort combo
        self._sort_combo = ComboBox(cat_row)
        self._sort_combo.addItems([label for label, _ in self._SORT_OPTIONS])
        self._sort_combo.setCurrentIndex(0)
        self._sort_combo.setFixedWidth(COMBO_WIDTH_MD)
        cat_layout.addWidget(self._sort_combo)

        layout.addWidget(cat_row)

        # ── Featured banner (horizontal scroll) ────────────────
        self._featured_scroll = ScrollArea(self)
        self._featured_scroll.setFixedHeight(FEATURED_BANNER_HEIGHT)
        self._featured_scroll.setWidgetResizable(True)
        self._featured_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._featured_scroll.setVisible(False)

        self._featured_container = QWidget()
        self._featured_layout = QHBoxLayout(self._featured_container)
        self._featured_layout.setContentsMargins(SPACING_MD, 0, SPACING_MD, 0)
        self._featured_layout.setSpacing(SPACING_SM)
        self._featured_layout.addStretch()

        self._featured_scroll.setWidget(self._featured_container)
        layout.addWidget(self._featured_scroll)

        # ── Waterfall scroll area ─────────────────────────────
        self._scroll_area = ScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self._grid_container = QWidget()
        self._waterfall = WaterfallLayout(
            self._grid_container,
            column_width=GALLERY_CARD_COLUMN_WIDTH,
            spacing=GALLERY_GRID_SPACING,
        )
        self._waterfall.setContentsMargins(SPACING_MD, SPACING_SM, SPACING_MD, SPACING_MD)

        self._scroll_area.setWidget(self._grid_container)
        layout.addWidget(self._scroll_area, stretch=1)

        # ── Empty state ──────────────────────────────────────
        self._empty_label = SubtitleLabel(
            "\u672a\u627e\u5230\u7d20\u6750", self  # 未找到素材
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)
        layout.addWidget(self._empty_label)

        # ── Loading indicator ─────────────────────────────────
        self._loading_label = SubtitleLabel(
            "\u52a0\u8f7d\u4e2d...", self  # 加载中...
        )
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_label.setVisible(False)
        layout.addWidget(self._loading_label)

        # ── Search debounce timer ─────────────────────────────
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DEBOUNCE_MS)

    def _connect_signals(self) -> None:
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        self._scroll_area.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self._search_timer.timeout.connect(self._on_search_debounced)

    # ── Infinite scroll ───────────────────────────────────────

    @Slot(int)
    def _on_scroll(self, value: int) -> None:
        """Auto-load next page when scrolled to 80% of content."""
        scrollbar = self._scroll_area.verticalScrollBar()
        if scrollbar.maximum() <= 0:
            return
        if value > scrollbar.maximum() * 0.8 and not self._is_loading and self._has_more:
            self._load_materials()

    # ── Category / sort / search ──────────────────────────────

    def _on_category_clicked(self, category: str) -> None:
        for cat_val, pill in self._category_pills.items():
            pill.setChecked(cat_val == category)
        self._current_category = category if category else None
        self._reset_and_load()

    @Slot(int)
    def _on_sort_changed(self, index: int) -> None:
        if 0 <= index < len(self._SORT_OPTIONS):
            self._current_sort = self._SORT_OPTIONS[index][1]
        self._reset_and_load()

    def on_search_text_changed(self, text: str) -> None:
        """Called by the header bar's search. Debounces the search."""
        self._search_timer.stop()
        self._pending_search = text.strip()
        self._search_timer.start()

    @Slot()
    def _on_search_debounced(self) -> None:
        self._current_query = getattr(self, "_pending_search", "")
        self._reset_and_load()

    def set_search_query(self, query: str) -> None:
        """Set the search query directly (from header bar searchSignal)."""
        self._current_query = query
        self._reset_and_load()

    def set_sort_mode(self, mode: str) -> None:
        """Set sort mode from GalleryHeaderBar tab (discover/featured/trending/newest)."""
        tab_to_sort = {
            "discover": "newest",
            "featured": "popular",
            "trending": "popular",
            "newest": "newest",
        }
        new_sort = tab_to_sort.get(mode, "newest")
        if new_sort != self._current_sort:
            self._current_sort = new_sort
            # Sync the combo box
            for i, (_, sort_key) in enumerate(self._SORT_OPTIONS):
                if sort_key == new_sort:
                    self._sort_combo.setCurrentIndex(i)
                    break
            self._reset_and_load()

    # ── Data loading ──────────────────────────────────────────

    def _reset_and_load(self) -> None:
        self._current_page = 1
        self._has_more = True
        self._clear_grid()
        self._load_materials()

    def _clear_grid(self) -> None:
        self._waterfall.clear()
        self._materials.clear()
        self._cards.clear()

    def _get_sort_params(self) -> tuple[str, str]:
        mapping = {
            "newest": ("created_at", "desc"),
            "popular": ("download_count", "desc"),
            "name_asc": ("name", "asc"),
            "name_desc": ("name", "desc"),
            "file_size": ("file_size", "desc"),
        }
        return mapping.get(self._current_sort, ("created_at", "desc"))

    def _load_materials(self) -> None:
        if self._is_loading or not self._has_more:
            return

        self._is_loading = True
        self._loading_label.setVisible(True)

        sort_by, sort_order = self._get_sort_params()
        params: dict = {
            "page": self._current_page,
            "per_page": self._page_size,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }
        if self._current_query:
            params["query"] = self._current_query
        if self._current_category:
            params["category"] = self._current_category

        self._materials_worker = MaterialsLoadWorker(
            self._services.api_client, params, parent=self
        )
        self._materials_worker.completed.connect(self._on_materials_loaded)
        self._materials_worker.error.connect(self._on_materials_error)
        self._materials_worker.start()

    @Slot(list, int)
    def _on_materials_loaded(self, items: list, total: int) -> None:
        self._loading_label.setVisible(False)

        for item_data in items:
            material = Material.from_dict(item_data)
            self._materials.append(material)

            card = GalleryCard(material, parent=self._grid_container)
            card.clicked.connect(lambda mid: self.material_selected.emit(mid))
            card.download_clicked.connect(
                lambda mid: self._on_download_requested(mid)
            )
            card.favorite_toggled.connect(self._on_favorite_toggled)
            card.creator_clicked.connect(lambda cid: self.creator_clicked.emit(cid))
            self._waterfall.addWidget(card)
            self._cards[material.id] = card

            # Queue thumbnail loading
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

        # Force layout recalculation
        self._grid_container.adjustSize()

    @Slot(str)
    def _on_materials_error(self, detail: str) -> None:
        logger.error("Failed to load materials: %s", detail)
        self._loading_label.setVisible(False)
        InfoBar.error(
            title="\u52a0\u8f7d\u5931\u8d25",  # 加载失败
            content=f"\u65e0\u6cd5\u52a0\u8f7d\u7d20\u6750: {detail}",  # 无法加载素材
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000,
        )
        self._is_loading = False

    @Slot(str, QPixmap)
    def _on_thumbnail_ready(self, cache_key: str, pixmap: QPixmap) -> None:
        """Route loaded thumbnails to the correct card."""
        if cache_key.startswith("preview_"):
            mid = cache_key[len("preview_"):]
            card = self._cards.get(mid)
            if card:
                card.set_preview_pixmap(pixmap)
        elif cache_key.startswith("avatar_"):
            # avatar_<creator_id_or_name>
            for card in self._cards.values():
                if card.avatar_cache_key == cache_key:
                    card.set_avatar_pixmap(pixmap)

    # ── Download flow ─────────────────────────────────────────

    @Slot(str)
    def _on_download_requested(self, material_id: str) -> None:
        if not self._services.auth_service.is_authenticated:
            forum_widget = self.parent()
            while forum_widget and not hasattr(forum_widget, "require_auth"):
                forum_widget = forum_widget.parent()
            if forum_widget:
                forum_widget.require_auth(
                    on_success=lambda mid=material_id: self._on_download_requested(mid)
                )
            return

        material = next((m for m in self._materials if m.id == material_id), None)
        if material is None:
            return

        self._download_url_worker = DownloadUrlWorker(
            self._services.api_client,
            material.id,
            material.file_hash or "",
            material.file_size or 0,
            parent=self,
        )
        self._pending_download_material = material
        self._download_url_worker.completed.connect(self._on_download_url_ready)
        self._download_url_worker.error.connect(self._on_download_url_error)
        self._download_url_worker.start()

    @Slot(str, str, int)
    def _on_download_url_ready(self, download_url: str, file_hash: str, file_size: int) -> None:
        material = self._pending_download_material
        if material is None:
            return

        safe_name = "".join(
            c if c.isalnum() or c in "._- " else "_" for c in material.name
        ).strip()
        filename = f"{safe_name}_{material.id}"

        self._services.download_engine.start_download(
            material_id=material.id,
            download_url=download_url,
            filename=filename,
            material_name=material.name,
            expected_hash=file_hash or None,
            expected_size=file_size,
        )

        InfoBar.success(
            title="\u4e0b\u8f7d\u5df2\u5f00\u59cb",  # 下载已开始
            content=f"'{material.name}' \u5df2\u6dfb\u52a0\u5230\u4e0b\u8f7d\u961f\u5217\u3002",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3000,
        )
        self.download_requested.emit(material.id)

    @Slot(str)
    def _on_download_url_error(self, detail: str) -> None:
        logger.error("Failed to generate download URL: %s", detail)
        InfoBar.error(
            title="\u4e0b\u8f7d\u5931\u8d25",  # 下载失败
            content=f"\u65e0\u6cd5\u751f\u6210\u4e0b\u8f7d\u94fe\u63a5: {detail}",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000,
        )

    @Slot(str, bool)
    def _on_favorite_toggled(self, material_id: str, should_like: bool) -> None:
        if not self._services.auth_service.is_authenticated:
            card = self._cards.get(material_id)
            if card:
                card.update_like_state(not should_like, card.material.like_count)
            forum_widget = self.parent()
            while forum_widget and not hasattr(forum_widget, "require_auth"):
                forum_widget = forum_widget.parent()
            if forum_widget:
                forum_widget.require_auth(on_success=lambda: None)
            return

        worker = LikeToggleWorker(
            self._services.api_client, material_id, should_like, parent=self
        )
        worker.completed.connect(self._on_like_result)
        worker.error.connect(self._on_like_error)
        self._current_like_worker = worker
        worker.start()

    @Slot(str, bool, int)
    def _on_like_result(self, mid: str, is_liked: bool, count: int) -> None:
        card = self._cards.get(mid)
        if card:
            card.update_like_state(is_liked, count)
        for m in self._materials:
            if m.id == mid:
                m.is_liked = is_liked
                m.like_count = count
                break

    @Slot(str)
    def _on_like_error(self, detail: str) -> None:
        worker = getattr(self, "_current_like_worker", None)
        if worker is not None:
            mid = worker._material_id
            card = self._cards.get(mid)
            if card:
                card.update_like_state(not worker._should_like, card.material.like_count)
        InfoBar.warning(
            title="操作失败",
            content=detail,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3000,
        )

    # ── Public API ────────────────────────────────────────────

    def load_initial(self) -> None:
        """Load the initial set of materials."""
        if not self._materials:
            self._load_materials()
        self._load_featured()

    def get_material(self, material_id: str) -> Optional[Material]:
        """Return a cached material by ID, if available."""
        return next((m for m in self._materials if m.id == material_id), None)

    def update_card_like_state(self, material_id: str, is_liked: bool, like_count: int) -> None:
        """Update a card's like state from external source (DetailPage sync)."""
        card = self._cards.get(material_id)
        if card:
            card.update_like_state(is_liked, like_count)
        for m in self._materials:
            if m.id == material_id:
                m.is_liked = is_liked
                m.like_count = like_count
                break

    # ── Featured materials ─────────────────────────────────────

    def _load_featured(self) -> None:
        self._featured_worker = FeaturedMaterialsWorker(
            self._services.api_client, limit=10, parent=self
        )
        self._featured_worker.completed.connect(self._on_featured_loaded)
        self._featured_worker.error.connect(self._on_featured_error)
        self._featured_worker.start()

    @Slot(list)
    def _on_featured_loaded(self, items: list) -> None:
        if not items:
            self._featured_scroll.setVisible(False)
            return

        # Clear existing
        while self._featured_layout.count():
            item = self._featured_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._featured_layout.addStretch()

        self._featured_cards: dict[str, GalleryCard] = {}
        for item_data in items:
            material = Material.from_dict(item_data)
            card = GalleryCard(material, parent=self._featured_container)
            card.setFixedWidth(FEATURED_CARD_WIDTH)
            card.clicked.connect(lambda mid: self.material_selected.emit(mid))
            card.download_clicked.connect(
                lambda mid: self._on_download_requested(mid)
            )
            idx = self._featured_layout.count() - 1
            self._featured_layout.insertWidget(idx, card)
            self._featured_cards[material.id] = card

            if material.preview_image_path:
                cache_key = f"featured_{material.id}"
                cached = self._thumb_loader.load(material.preview_image_path, cache_key)
                if cached:
                    card.set_preview_pixmap(cached)

        self._featured_scroll.setVisible(True)
        self._featured_container.adjustSize()

    @Slot(str)
    def _on_featured_error(self, detail: str) -> None:
        logger.debug("Failed to load featured materials: %s", detail)
        self._featured_scroll.setVisible(False)
