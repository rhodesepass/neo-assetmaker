"""Filter panel for material browsing.

Provides category and tag filters using PillPushButtons for a modern
chip/pill-based filtering UI.
"""

from __future__ import annotations

from typing import Optional

from qfluentwidgets import (
    FlowLayout,
    PillPushButton,
    PushButton,
    SubtitleLabel,
)
from qtpy.QtCore import Signal, Slot
from qtpy.QtWidgets import (
    QVBoxLayout,
    QWidget,
)

from _mext.models.material import MaterialCategory


class FilterPanel(QWidget):
    """Category and tag filter panel with pill-style toggle buttons.

    Signals
    -------
    category_changed(str)
        Emitted when the selected category changes. Empty string means "all".
    tags_changed(list)
        Emitted when the set of selected tags changes.
    filters_cleared()
        Emitted when all filters are cleared.
    """

    category_changed = Signal(str)
    tags_changed = Signal(list)
    filters_cleared = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._selected_category: str = ""
        self._selected_tags: set[str] = set()
        self._category_pills: dict[str, PillPushButton] = {}
        self._tag_pills: dict[str, PillPushButton] = {}

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the filter panel layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        # Category section
        cat_label = SubtitleLabel("分类", self)
        layout.addWidget(cat_label)

        cat_flow_container = QWidget(self)
        self._cat_flow = FlowLayout(cat_flow_container, needAni=False)
        self._cat_flow.setContentsMargins(0, 0, 0, 0)
        self._cat_flow.setHorizontalSpacing(6)
        self._cat_flow.setVerticalSpacing(6)

        # "All" category
        all_pill = PillPushButton("All", cat_flow_container)
        all_pill.setCheckable(True)
        all_pill.setChecked(True)
        all_pill.clicked.connect(lambda: self._on_category_clicked(""))
        self._cat_flow.addWidget(all_pill)
        self._category_pills[""] = all_pill

        # Category pills
        for category in MaterialCategory:
            pill = PillPushButton(category.display_name, cat_flow_container)
            pill.setCheckable(True)
            pill.setChecked(False)
            pill.clicked.connect(lambda checked, cat=category.value: self._on_category_clicked(cat))
            self._cat_flow.addWidget(pill)
            self._category_pills[category.value] = pill

        layout.addWidget(cat_flow_container)

        # Tags section
        tag_label = SubtitleLabel("标签", self)
        layout.addWidget(tag_label)

        tag_flow_container = QWidget(self)
        self._tag_flow = FlowLayout(tag_flow_container, needAni=False)
        self._tag_flow.setContentsMargins(0, 0, 0, 0)
        self._tag_flow.setHorizontalSpacing(6)
        self._tag_flow.setVerticalSpacing(6)

        # Common predefined tags
        default_tags = [
            "PBR",
            "Seamless",
            "4K",
            "8K",
            "Organic",
            "Metal",
            "Wood",
            "Stone",
            "Fabric",
            "Procedural",
            "Scan",
            "Free",
            "Premium",
        ]
        for tag in default_tags:
            pill = PillPushButton(tag, tag_flow_container)
            pill.setCheckable(True)
            pill.setChecked(False)
            pill.clicked.connect(lambda checked, t=tag: self._on_tag_clicked(t))
            self._tag_flow.addWidget(pill)
            self._tag_pills[tag] = pill

        layout.addWidget(tag_flow_container)

        # Clear filters button
        self._clear_btn = PushButton("Clear Filters", self)
        self._clear_btn.clicked.connect(self.clear_all)
        layout.addWidget(self._clear_btn)

        layout.addStretch()

    def _on_category_clicked(self, category: str) -> None:
        """Handle category pill toggle."""
        # Uncheck all other category pills
        for cat_value, pill in self._category_pills.items():
            pill.setChecked(cat_value == category)

        self._selected_category = category
        self.category_changed.emit(category)

    def _on_tag_clicked(self, tag: str) -> None:
        """Handle tag pill toggle."""
        pill = self._tag_pills.get(tag)
        if pill is None:
            return

        if pill.isChecked():
            self._selected_tags.add(tag)
        else:
            self._selected_tags.discard(tag)

        self.tags_changed.emit(sorted(self._selected_tags))

    @Slot()
    def clear_all(self) -> None:
        """Clear all filters and reset pills to unchecked state."""
        self._selected_category = ""
        self._selected_tags.clear()

        for cat_value, pill in self._category_pills.items():
            pill.setChecked(cat_value == "")

        for pill in self._tag_pills.values():
            pill.setChecked(False)

        self.category_changed.emit("")
        self.tags_changed.emit([])
        self.filters_cleared.emit()

    @property
    def selected_category(self) -> str:
        """Return the currently selected category value, or empty string for 'all'."""
        return self._selected_category

    @property
    def selected_tags(self) -> list[str]:
        """Return a sorted list of currently selected tags."""
        return sorted(self._selected_tags)

    def add_tag(self, tag: str) -> None:
        """Dynamically add a new tag pill to the filter panel."""
        if tag in self._tag_pills:
            return

        parent = self._tag_flow.parent()
        pill = PillPushButton(tag, parent)
        pill.setCheckable(True)
        pill.setChecked(False)
        pill.clicked.connect(lambda checked, t=tag: self._on_tag_clicked(t))
        self._tag_flow.addWidget(pill)
        self._tag_pills[tag] = pill

    def set_tags(self, tags: list[str]) -> None:
        """Replace the tag list with a new set of tags."""
        # Clear existing tag pills
        for pill in self._tag_pills.values():
            pill.deleteLater()
        self._tag_pills.clear()
        self._selected_tags.clear()

        for tag in tags:
            self.add_tag(tag)
