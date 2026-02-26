"""Market page for browsing and searching materials.

Provides a searchable, filterable grid of MaterialCards with sorting
options and infinite-scroll-style pagination.
"""

from __future__ import annotations

import logging
from typing import Optional

from qfluentwidgets import (
    ComboBox,
    FlowLayout,
    InfoBar,
    InfoBarPosition,
    ScrollArea,
    SearchLineEdit,
    SubtitleLabel,
)
from qtpy.QtCore import Qt, QTimer, Signal, Slot
from qtpy.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from _mext.core.constants import SEARCH_DEBOUNCE_MS
from _mext.core.service_manager import ServiceManager
from _mext.models.material import Material
from _mext.services.api_client import ApiError
from _mext.ui.components.filter_panel import FilterPanel
from _mext.ui.components.material_card import MaterialCard

logger = logging.getLogger(__name__)


class MarketPage(QWidget):
    """Material asset browsing page.

    Signals
    -------
    material_selected(str)
        Emitted when a user clicks a material card. Payload is the material ID.
    download_requested(str)
        Emitted when a user clicks a download button. Payload is the material ID.
    """

    material_selected = Signal(str)
    download_requested = Signal(str)

    def __init__(
        self,
        service_manager: ServiceManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._services = service_manager
        self._materials: list[Material] = []
        self._current_page = 1
        self._page_size = 20
        self._is_loading = False
        self._has_more = True
        self._current_query = ""
        self._current_category: Optional[str] = None
        self._current_tags: list[str] = []
        self._current_sort = "newest"

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        """Build the market page layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Header with search and sort
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        self._search_edit = SearchLineEdit(self)
        self._search_edit.setPlaceholderText("搜索素材...")
        self._search_edit.setFixedHeight(36)
        header_layout.addWidget(self._search_edit, stretch=1)

        self._sort_combo = ComboBox(self)
        self._sort_combo.addItems(["最新", "热门", "名称 A-Z", "名称 Z-A", "文件大小"])
        self._sort_combo.setCurrentIndex(0)
        self._sort_combo.setFixedWidth(150)
        header_layout.addWidget(self._sort_combo)

        layout.addLayout(header_layout)

        # Content area: filter panel + card grid
        content_layout = QHBoxLayout()
        content_layout.setSpacing(12)

        # Filter panel (left sidebar)
        self._filter_panel = FilterPanel(self)
        self._filter_panel.setFixedWidth(200)
        content_layout.addWidget(self._filter_panel)

        # Scrollable card grid
        self._scroll_area = ScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._grid_container = QWidget()
        self._grid_layout = FlowLayout(self._grid_container, needAni=False)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setHorizontalSpacing(12)
        self._grid_layout.setVerticalSpacing(12)

        self._scroll_area.setWidget(self._grid_container)
        content_layout.addWidget(self._scroll_area, stretch=1)

        layout.addLayout(content_layout, stretch=1)

        # Empty state label
        self._empty_label = SubtitleLabel("未找到素材", self)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)
        layout.addWidget(self._empty_label)

        # Search debounce timer
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DEBOUNCE_MS)

    def _connect_signals(self) -> None:
        """Wire up search, filter, and sort signals."""
        self._search_edit.textChanged.connect(self._on_search_text_changed)
        self._search_timer.timeout.connect(self._on_search_debounced)
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        self._filter_panel.category_changed.connect(self._on_category_changed)
        self._filter_panel.tags_changed.connect(self._on_tags_changed)

    @Slot(str)
    def _on_search_text_changed(self, text: str) -> None:
        """Restart the debounce timer when the search text changes."""
        self._search_timer.stop()
        self._search_timer.start()

    @Slot()
    def _on_search_debounced(self) -> None:
        """Execute the search after the debounce interval."""
        self._current_query = self._search_edit.text().strip()
        self._reset_and_load()

    @Slot(int)
    def _on_sort_changed(self, index: int) -> None:
        """Handle sort order change."""
        sort_map = {
            0: "newest",
            1: "popular",
            2: "name_asc",
            3: "name_desc",
            4: "file_size",
        }
        self._current_sort = sort_map.get(index, "newest")
        self._reset_and_load()

    @Slot(str)
    def _on_category_changed(self, category: str) -> None:
        """Handle category filter change."""
        self._current_category = category if category else None
        self._reset_and_load()

    @Slot(list)
    def _on_tags_changed(self, tags: list[str]) -> None:
        """Handle tag filter change."""
        self._current_tags = tags
        self._reset_and_load()

    def _reset_and_load(self) -> None:
        """Reset pagination and reload materials."""
        self._current_page = 1
        self._has_more = True
        self._clear_grid()
        self._load_materials()

    def _clear_grid(self) -> None:
        """Remove all material cards from the grid."""
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._materials.clear()

    def _get_sort_params(self) -> tuple[str, str]:
        """Map the UI sort selection to server sort_by and sort_order values."""
        mapping = {
            "newest": ("created_at", "desc"),
            "popular": ("download_count", "desc"),
            "name_asc": ("name", "asc"),
            "name_desc": ("name", "desc"),
            "file_size": ("file_size", "desc"),
        }
        return mapping.get(self._current_sort, ("created_at", "desc"))

    def _load_materials(self) -> None:
        """Fetch materials from the API and populate the grid."""
        if self._is_loading or not self._has_more:
            return

        self._is_loading = True

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
        if self._current_tags:
            # Server expects repeated query params: tags=a&tags=b
            params["tags"] = self._current_tags

        try:
            response = self._services.api_client.get("materials", params=params)
            items = response.get("items", [])
            total = response.get("total", 0)

            for item_data in items:
                material = Material.from_dict(item_data)
                self._materials.append(material)
                card = MaterialCard(material, parent=self._grid_container)
                card.clicked.connect(lambda mid=material.id: self.material_selected.emit(mid))
                card.download_clicked.connect(
                    lambda mid=material.id: self._on_download_requested(mid)
                )
                self._grid_layout.addWidget(card)

            self._has_more = len(self._materials) < total
            self._current_page += 1

            self._empty_label.setVisible(len(self._materials) == 0)

        except ApiError as exc:
            logger.error("Failed to load materials: %s", exc)
            InfoBar.error(
                title="加载失败",
                content=f"无法加载素材: {exc.detail}",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=5000,
            )
        finally:
            self._is_loading = False

    @Slot(str)
    def _on_download_requested(self, material_id: str) -> None:
        """Handle download button click on a material card.

        Requests a signed download URL from the server, then queues the
        download with the DownloadEngine.
        """
        material = next((m for m in self._materials if m.id == material_id), None)
        if material is None:
            return

        try:
            # Step 1: Request a signed verification URL from the server
            url_response = self._services.api_client.post(
                "downloads/generate-url",
                json={"material_id": material.id},
            )
            verify_url = url_response.get("url", "")
            if not verify_url:
                raise ApiError(500, "Server returned empty download URL")

            # Build a full URL if the server returned a relative path.
            # The signed URL is an absolute path like /api/v1/downloads/verify?...
            # so we need the bare server origin, not the versioned API base.
            if verify_url.startswith("/"):
                server_origin = self._services.api_client._config.api_base_url.rstrip("/")
                verify_url = f"{server_origin}{verify_url}"

            # Step 2: Call the verify endpoint to record the download and
            # get the actual presigned storage URL for the file
            verify_response = self._services.api_client.get(verify_url)
            download_url = verify_response.get("presigned_url", "")
            if not download_url:
                raise ApiError(500, "Server returned empty presigned URL")

            # Use server-provided hash/size if available (may be more
            # up-to-date than the cached material data)
            file_hash = verify_response.get("file_hash", material.file_hash)
            file_size = verify_response.get("file_size", material.file_size)

        except ApiError as exc:
            logger.error("Failed to generate download URL: %s", exc)
            InfoBar.error(
                title="下载失败",
                content=f"无法生成下载链接: {exc.detail}",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=5000,
            )
            return

        # Sanitize filename for filesystem
        safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in material.name).strip()
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
            title="下载已开始",
            content=f"'{material.name}' 已添加到下载队列。",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3000,
        )

        self.download_requested.emit(material_id)

    def load_initial(self) -> None:
        """Load the initial set of materials. Call after the page is shown."""
        if not self._materials:
            self._load_materials()
