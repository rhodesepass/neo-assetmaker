"""Library page for managing the user's downloaded and favorited materials.

Displays materials in either a grid or list view with tabs for
"All Materials" and "Favorites".
"""

from __future__ import annotations

import logging
from typing import Optional

from qfluentwidgets import (
    FlowLayout,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    ScrollArea,
    SearchLineEdit,
    SubtitleLabel,
    TabBar,
    TableWidget,
    ToolButton,
)
from PyQt6.QtCore import Qt, pyqtSignal as Signal, pyqtSlot as Slot
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from _mext.core.service_manager import ServiceManager
from _mext.models.material import Material
from _mext.services.api_client import ApiError
from _mext.services.api_worker import LibraryLoadWorker
from _mext.ui.styles import GRID_H_SPACING, GRID_V_SPACING

from _mext.ui.components.material_card import MaterialCard

logger = logging.getLogger(__name__)


class LibraryPage(QWidget):
    """User's material library with tabs and view modes.

    Signals
    -------
    material_selected(str)
        Emitted when a material is clicked. Payload is the material ID.
    """

    material_selected = Signal(str)

    def __init__(
        self,
        service_manager: ServiceManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._services = service_manager
        self._all_materials: list[Material] = []
        self._favorite_materials: list[Material] = []
        self._is_grid_view = True
        self._current_tab = "all"

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        """Build the library page layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Header row: tabs + view toggle + search
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        self._tab_bar = TabBar(self)
        self._tab_bar.addTab("all", "All Materials")
        self._tab_bar.addTab("favorites", "Favorites")
        self._tab_bar.setCurrentTab("all")
        self._tab_bar.setTabsClosable(False)
        self._tab_bar.setAddButtonVisible(False)
        header_layout.addWidget(self._tab_bar)

        header_layout.addStretch()

        self._search_edit = SearchLineEdit(self)
        self._search_edit.setPlaceholderText("搜索素材库...")
        self._search_edit.setFixedWidth(250)
        header_layout.addWidget(self._search_edit)

        self._grid_btn = ToolButton(FluentIcon.TILES, self)
        self._grid_btn.setToolTip("卡片视图")
        self._grid_btn.setCheckable(True)
        self._grid_btn.setChecked(True)
        header_layout.addWidget(self._grid_btn)

        self._list_btn = ToolButton(FluentIcon.VIEW, self)
        self._list_btn.setToolTip("列表视图")
        self._list_btn.setCheckable(True)
        self._list_btn.setChecked(False)
        header_layout.addWidget(self._list_btn)

        self._refresh_btn = ToolButton(FluentIcon.SYNC, self)
        self._refresh_btn.setToolTip("刷新素材库")
        header_layout.addWidget(self._refresh_btn)

        layout.addLayout(header_layout)

        # Grid view (card flow)
        self._grid_scroll = ScrollArea(self)
        self._grid_scroll.setWidgetResizable(True)
        self._grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._grid_container = QWidget()
        self._grid_flow = FlowLayout(self._grid_container, needAni=False)
        self._grid_flow.setContentsMargins(0, 0, 0, 0)
        self._grid_flow.setHorizontalSpacing(GRID_H_SPACING)
        self._grid_flow.setVerticalSpacing(GRID_V_SPACING)
        self._grid_scroll.setWidget(self._grid_container)
        layout.addWidget(self._grid_scroll, stretch=1)

        # List view (table) — QFluentWidgets TableWidget for Fluent theme support
        self._table = TableWidget(self)
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["Name", "Category", "Operator", "Size", "Date"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setVisible(False)
        layout.addWidget(self._table, stretch=1)

        # Empty state
        self._empty_label = SubtitleLabel("素材库为空", self)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)
        layout.addWidget(self._empty_label)

    def _connect_signals(self) -> None:
        """Wire signals for tabs, view toggling, search, and refresh."""
        self._tab_bar.currentChanged.connect(self._on_tab_changed)
        self._grid_btn.clicked.connect(self._switch_to_grid)
        self._list_btn.clicked.connect(self._switch_to_list)
        self._search_edit.textChanged.connect(self._on_search_changed)
        self._refresh_btn.clicked.connect(self._load_library)
        self._table.cellDoubleClicked.connect(self._on_table_row_clicked)

    @Slot(int)
    def _on_tab_changed(self, index: int) -> None:
        """Handle tab switch between All and Favorites."""
        self._current_tab = "favorites" if index == 1 else "all"
        self._refresh_view()

    @Slot()
    def _switch_to_grid(self) -> None:
        """Switch to grid (card) view."""
        self._is_grid_view = True
        self._grid_btn.setChecked(True)
        self._list_btn.setChecked(False)
        self._grid_scroll.setVisible(True)
        self._table.setVisible(False)
        self._refresh_view()

    @Slot()
    def _switch_to_list(self) -> None:
        """Switch to list (table) view."""
        self._is_grid_view = False
        self._list_btn.setChecked(True)
        self._grid_btn.setChecked(False)
        self._grid_scroll.setVisible(False)
        self._table.setVisible(True)
        self._refresh_view()

    @Slot(str)
    def _on_search_changed(self, text: str) -> None:
        """Filter displayed materials by search text."""
        self._refresh_view()

    @Slot(int, int)
    def _on_table_row_clicked(self, row: int, col: int) -> None:
        """Handle double-click on a table row."""
        materials = self._get_filtered_materials()
        if 0 <= row < len(materials):
            self.material_selected.emit(materials[row].id)

    def _get_filtered_materials(self) -> list[Material]:
        """Return materials filtered by current tab and search text."""
        source = (
            self._favorite_materials if self._current_tab == "favorites" else self._all_materials
        )
        query = self._search_edit.text().strip().lower()
        if not query:
            return source
        return [
            m
            for m in source
            if query in m.name.lower()
            or query in m.operator_name.lower()
            or any(query in tag.lower() for tag in m.tags)
        ]

    def _refresh_view(self) -> None:
        """Refresh the currently visible view with filtered materials."""
        materials = self._get_filtered_materials()
        self._empty_label.setVisible(len(materials) == 0)

        if self._is_grid_view:
            self._populate_grid(materials)
        else:
            self._populate_table(materials)

    def _populate_grid(self, materials: list[Material]) -> None:
        """Fill the grid layout with material cards."""
        # Clear existing cards
        while self._grid_flow.count():
            item = self._grid_flow.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for material in materials:
            card = MaterialCard(material, parent=self._grid_container)
            card.clicked.connect(lambda mid=material.id: self.material_selected.emit(mid))
            self._grid_flow.addWidget(card)

    def _populate_table(self, materials: list[Material]) -> None:
        """Fill the table widget with material rows."""
        self._table.setRowCount(len(materials))
        for row, material in enumerate(materials):
            self._table.setItem(row, 0, QTableWidgetItem(material.name))
            self._table.setItem(row, 1, QTableWidgetItem(material.category.display_name))
            self._table.setItem(row, 2, QTableWidgetItem(material.operator_name))
            self._table.setItem(row, 3, QTableWidgetItem(material.file_size_display))
            self._table.setItem(row, 4, QTableWidgetItem(material.created_at.strftime("%Y-%m-%d")))

    def _load_library(self) -> None:
        """Fetch the user's download history and favorites from the API.

        Uses the server endpoints:
        - GET /users/me/downloads for download history
        - GET /users/me/favorites for favorited materials
        """
        self._library_worker = LibraryLoadWorker(
            self._services.api_client, parent=self
        )
        self._library_worker.completed.connect(self._on_library_loaded)
        self._library_worker.error.connect(self._on_library_error)
        self._library_worker.start()

    @Slot(list, list)
    def _on_library_loaded(self, materials_raw: list, fav_raw: list) -> None:
        """Handle library data loaded from background worker."""
        self._all_materials = [Material.from_dict(d) for d in materials_raw]
        if fav_raw:
            self._favorite_materials = [Material.from_dict(item) for item in fav_raw]
            fav_ids = {m.id for m in self._favorite_materials}
            for m in self._all_materials:
                m.is_favorited = m.id in fav_ids
        else:
            self._favorite_materials = [m for m in self._all_materials if m.is_favorited]
        self._refresh_view()

    @Slot(str)
    def _on_library_error(self, detail: str) -> None:
        """Handle library load failure."""
        logger.error("Failed to load library: %s", detail)
        InfoBar.error(
            title="加载失败",
            content=f"无法加载素材库: {detail}",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000,
        )

    def load_initial(self) -> None:
        """Load library data on first display."""
        if not self._all_materials:
            self._load_library()
