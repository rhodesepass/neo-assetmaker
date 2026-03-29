"""Multi-column waterfall (masonry) layout.

Places each item into the shortest column, producing a Pinterest/ArtStation
style staggered grid.  Column count adapts to the container width.

Qt officially supports custom layouts by subclassing QLayout:
https://doc.qt.io/qt-6/layout.html
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtWidgets import QLayout, QLayoutItem, QWidget


class WaterfallLayout(QLayout):
    """Multi-column waterfall layout.

    Each item is placed into the column with the smallest accumulated
    height, producing a masonry / Pinterest-style staggered grid.

    Parameters
    ----------
    parent : QWidget, optional
        Parent widget that owns this layout.
    column_width : int
        Preferred width of each column in pixels (default 260).
    spacing : int
        Gap between items / columns in pixels (default 16).
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        column_width: int = 260,
        spacing: int = 16,
    ) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._column_width = column_width
        self._spacing = spacing
        self._cached_height = 0

    # ── QLayout required overrides ────────────────────────────

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        min_w = self._column_width + self.contentsMargins().left() + self.contentsMargins().right()
        return QSize(min_w, max(self._cached_height, 0))

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), apply_geometry=False)

    # ── Core layout logic ─────────────────────────────────────

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, apply_geometry=True)

    def _compute_columns(self, available_width: int) -> int:
        """Determine column count based on available width.

        Breakpoints:
        - < 600px  → 2 columns
        - 600-900  → 3 columns
        - 900-1200 → 4 columns
        - 1200+    → 5 columns
        """
        if available_width < 600:
            return 2
        elif available_width < 900:
            return 3
        elif available_width < 1200:
            return 4
        else:
            return 5

    def _do_layout(self, rect: QRect, *, apply_geometry: bool) -> int:
        """Compute (and optionally apply) item positions.

        Returns the total height consumed by the layout.
        """
        if not self._items:
            self._cached_height = 0
            return 0

        margins = self.contentsMargins()
        effective_rect = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        available_width = effective_rect.width()

        cols = self._compute_columns(available_width)

        # Compute actual column width to fill the available space evenly
        total_spacing = self._spacing * (cols - 1)
        col_width = max(1, (available_width - total_spacing) // cols)

        col_heights = [0] * cols
        x_start = effective_rect.x()
        y_start = effective_rect.y()

        for item in self._items:
            # Pick the shortest column
            min_col = col_heights.index(min(col_heights))
            x = x_start + min_col * (col_width + self._spacing)
            y = y_start + col_heights[min_col]

            item_h = item.sizeHint().height()

            if apply_geometry:
                item.setGeometry(QRect(x, y, col_width, item_h))

            col_heights[min_col] += item_h + self._spacing

        total_height = max(col_heights) if col_heights else 0
        # Remove trailing spacing
        if total_height > 0:
            total_height -= self._spacing
        total_height += margins.top() + margins.bottom()

        self._cached_height = total_height
        return total_height

    # ── Public helpers ────────────────────────────────────────

    @property
    def column_width(self) -> int:
        return self._column_width

    @column_width.setter
    def column_width(self, value: int) -> None:
        self._column_width = value
        self.invalidate()

    def clear(self) -> None:
        """Remove and delete all items from the layout."""
        while self._items:
            item = self._items.pop()
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.invalidate()
