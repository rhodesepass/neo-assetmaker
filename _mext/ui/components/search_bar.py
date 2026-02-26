"""Debounced search bar component.

Wraps QFluentWidgets' SearchLineEdit with a configurable debounce
timer so search queries are only emitted after the user stops typing.
"""

from __future__ import annotations

from typing import Optional

from qfluentwidgets import SearchLineEdit
from qtpy.QtCore import QTimer, Signal, Slot
from qtpy.QtWidgets import QHBoxLayout, QWidget

from _mext.core.constants import SEARCH_DEBOUNCE_MS


class SearchBar(QWidget):
    """Search input with debounced query emission.

    Signals
    -------
    search_triggered(str)
        Emitted after the user stops typing for the debounce interval.
        Payload is the trimmed search query.
    search_cleared()
        Emitted when the search text is cleared.
    """

    search_triggered = Signal(str)
    search_cleared = Signal()

    def __init__(
        self,
        placeholder: str = "Search...",
        debounce_ms: int = SEARCH_DEBOUNCE_MS,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._debounce_ms = debounce_ms

        self._setup_ui(placeholder)
        self._setup_timer()
        self._connect_signals()

    def _setup_ui(self, placeholder: str) -> None:
        """Build the widget layout."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._search_edit = SearchLineEdit(self)
        self._search_edit.setPlaceholderText(placeholder)
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setFixedHeight(36)
        layout.addWidget(self._search_edit)

    def _setup_timer(self) -> None:
        """Create the debounce timer."""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self._debounce_ms)
        self._timer.timeout.connect(self._on_debounced)

    def _connect_signals(self) -> None:
        """Connect the text edit to the debounce timer."""
        self._search_edit.textChanged.connect(self._on_text_changed)
        self._search_edit.clearSignal.connect(self._on_cleared)

    @Slot(str)
    def _on_text_changed(self, text: str) -> None:
        """Restart the debounce timer on each keystroke."""
        self._timer.stop()
        if text.strip():
            self._timer.start()
        else:
            # Immediately emit clear when text is empty
            self.search_cleared.emit()

    @Slot()
    def _on_debounced(self) -> None:
        """Emit the search query after the debounce interval."""
        query = self._search_edit.text().strip()
        if query:
            self.search_triggered.emit(query)

    @Slot()
    def _on_cleared(self) -> None:
        """Handle the clear button click."""
        self._timer.stop()
        self.search_cleared.emit()

    # -- Public API --

    def text(self) -> str:
        """Return the current text in the search field."""
        return self._search_edit.text()

    def set_text(self, text: str) -> None:
        """Set the search field text programmatically."""
        self._search_edit.setText(text)

    def clear(self) -> None:
        """Clear the search field."""
        self._search_edit.clear()

    def set_placeholder(self, text: str) -> None:
        """Update the placeholder text."""
        self._search_edit.setPlaceholderText(text)

    def set_debounce(self, ms: int) -> None:
        """Update the debounce interval in milliseconds."""
        self._debounce_ms = ms
        self._timer.setInterval(ms)
