"""Main embeddable widget for the asset forum.

MaterialForumWidget is designed to be embedded in any QWidget-based
host application. It provides a Pivot-based tab navigation between
all major pages (Forum, Library, Downloads, Settings).
"""

from __future__ import annotations

import importlib
import logging
from typing import Any, Optional

from qfluentwidgets import Pivot, SubtitleLabel
from PyQt6.QtCore import Qt, pyqtSignal as Signal, pyqtSlot as Slot
from PyQt6.QtWidgets import (
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from _mext.core.service_manager import ServiceManager

logger = logging.getLogger(__name__)

# Page factory definitions: (display_name, module_path, class_name)
_PAGE_FACTORIES = [
    ("ForumPage", "_mext.ui.pages.forum_page", "ForumPage"),
    ("LibraryPage", "_mext.ui.pages.library_page", "LibraryPage"),
    ("DownloadsPage", "_mext.ui.pages.downloads_page", "DownloadsPage"),
    ("SettingsPage", "_mext.ui.pages.settings_page", "SettingsPage"),
]


class MaterialForumWidget(QWidget):
    """Embeddable forum widget with tabbed page navigation.

    Parameters
    ----------
    service_manager : ServiceManager, optional
        Shared service registry. Creates its own if not provided.
    parent : QWidget, optional
        Parent widget.

    Signals
    -------
    page_changed(str)
        Emitted when the user switches to a different page tab.
    """

    page_changed = Signal(str)

    _PAGE_AUTH_REQUIRED = {1}  # LibraryPage requires authentication

    def __init__(
        self,
        service_manager: Optional[ServiceManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._services = service_manager or ServiceManager(parent=self)
        self._pages: list[Optional[QWidget]] = [None] * len(_PAGE_FACTORIES)
        self._initialized = False

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        """Build the widget layout with Pivot navigation and stacked pages."""
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(12, 8, 12, 12)
        self._main_layout.setSpacing(8)

        # Pivot navigation bar
        self._pivot = Pivot(self)

        # Stacked widget with placeholder pages
        self._stack = QStackedWidget(self)
        for _ in range(len(_PAGE_FACTORIES)):
            self._stack.addWidget(QWidget())

        # Add pivot items
        self._pivot.addItem(
            routeKey="forum",
            text="论坛",
            onClick=lambda: self._switch_page(0, "forum"),
        )
        self._pivot.addItem(
            routeKey="library",
            text="素材库",
            onClick=lambda: self._switch_page(1, "library"),
        )
        self._pivot.addItem(
            routeKey="downloads",
            text="下载",
            onClick=lambda: self._switch_page(2, "downloads"),
        )
        self._pivot.addItem(
            routeKey="settings",
            text="设置",
            onClick=lambda: self._switch_page(3, "settings"),
        )

        self._pivot.setCurrentItem("forum")

        self._main_layout.addWidget(self._pivot)
        self._main_layout.addWidget(self._stack)

    def _connect_signals(self) -> None:
        """Connect inter-component signals."""
        self._services.auth_state_changed.connect(self._on_auth_state_changed)

    def showEvent(self, event: Any) -> None:  # noqa: N802
        """Perform deferred initialization on first show."""
        super().showEvent(event)
        if not self._initialized:
            self._initialized = True
            self._ensure_page(0)  # Load forum page directly

    def _ensure_page(self, index: int) -> Optional[QWidget]:
        """Lazily create a tab page on first access.

        Replaces the placeholder QWidget in the stack with the real page.
        On failure, shows an error label instead of crashing.
        """
        if self._pages[index] is not None:
            return self._pages[index]

        display_name, module_path, class_name = _PAGE_FACTORIES[index]
        try:
            module = importlib.import_module(module_path)
            page_class = getattr(module, class_name)
            page = page_class(self._services, parent=self)

            # Replace placeholder with real page
            placeholder = self._stack.widget(index)
            self._stack.removeWidget(placeholder)
            placeholder.deleteLater()
            self._stack.insertWidget(index, page)

            self._pages[index] = page
        except Exception as exc:
            logger.error("%s 创建失败: %s", display_name, exc, exc_info=True)
            error_widget = self._stack.widget(index)
            error_layout = QVBoxLayout(error_widget)
            error_label = SubtitleLabel(f"{display_name} 加载失败: {exc}", error_widget)
            error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            error_layout.addWidget(error_label)

        return self._pages[index]

    def _switch_page(self, index: int, name: str) -> None:
        """Switch the stacked widget to the specified page index."""
        if index in self._PAGE_AUTH_REQUIRED and not self._services.auth_service.is_authenticated:
            self._show_login_dialog(on_success=lambda: self._do_switch_page(index, name))
            return
        self._do_switch_page(index, name)

    def _do_switch_page(self, index: int, name: str) -> None:
        """Perform the actual page switch."""
        self._ensure_page(index)
        self._stack.setCurrentIndex(index)
        self.page_changed.emit(name)

    def _show_login_dialog(self, on_success=None):
        """Show a modal login dialog."""
        from _mext.ui.dialogs.login_dialog import LoginDialog
        dialog = LoginDialog(self._services, parent=self)
        if on_success:
            dialog.login_successful.connect(on_success)
        dialog.exec()

    def require_auth(self, on_success):
        """Public API for child pages to request authentication."""
        if self._services.auth_service.is_authenticated:
            on_success()
            return True
        self._show_login_dialog(on_success=on_success)
        return self._services.auth_service.is_authenticated

    @Slot(bool)
    def _on_auth_state_changed(self, authenticated: bool) -> None:
        """Handle authentication state changes."""
        if not authenticated and self._stack.currentIndex() == 1:
            self._do_switch_page(0, "forum")
            self._pivot.setCurrentItem("forum")

    @property
    def service_manager(self) -> ServiceManager:
        """Return the service manager instance."""
        return self._services

    def shutdown(self) -> None:
        """Clean up resources before the widget is destroyed."""
        self._services.shutdown()
