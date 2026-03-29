"""Main embeddable widget for the asset forum.

MaterialForumWidget provides a gallery-style browsing experience with
GalleryHeaderBar navigation, waterfall discover page, material detail
view, and utility pages (Library, Downloads, Settings) accessible via
user menu.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any, Optional

from qfluentwidgets import (
    Action,
    FluentIcon,
    RoundMenu,
    SubtitleLabel,
)
from PyQt6.QtCore import Qt, pyqtSignal as Signal, pyqtSlot as Slot
from PyQt6.QtWidgets import (
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from _mext.core.service_manager import ServiceManager
from _mext.ui.components.gallery_header import GalleryHeaderBar

logger = logging.getLogger(__name__)

# Page factory definitions: (display_name, module_path, class_name)
# Index 0 = DiscoverPage, 1 = MaterialDetailPage, 2-4 = utility pages
_PAGE_FACTORIES = [
    ("DiscoverPage", "_mext.ui.pages.discover_page", "DiscoverPage"),
    ("MaterialDetailPage", "_mext.ui.pages.material_detail_page", "MaterialDetailPage"),
    ("LibraryPage", "_mext.ui.pages.library_page", "LibraryPage"),
    ("DownloadsPage", "_mext.ui.pages.downloads_page", "DownloadsPage"),
    ("SettingsPage", "_mext.ui.pages.settings_page", "SettingsPage"),
    ("CreatorProfilePage", "_mext.ui.pages.creator_profile_page", "CreatorProfilePage"),
]

_IDX_DISCOVER = 0
_IDX_DETAIL = 1
_IDX_LIBRARY = 2
_IDX_DOWNLOADS = 3
_IDX_SETTINGS = 4
_IDX_CREATOR = 5


class MaterialForumWidget(QWidget):
    """Embeddable forum widget with gallery-style navigation.

    Parameters
    ----------
    service_manager : ServiceManager, optional
        Shared service registry. Creates its own if not provided.
    parent : QWidget, optional
        Parent widget.

    Signals
    -------
    page_changed(str)
        Emitted when the user switches to a different page.
    """

    page_changed = Signal(str)

    _PAGE_AUTH_REQUIRED = {_IDX_LIBRARY}  # LibraryPage requires authentication

    def __init__(
        self,
        service_manager: Optional[ServiceManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._services = service_manager or ServiceManager(parent=self)
        self._pages: list[Optional[QWidget]] = [None] * len(_PAGE_FACTORIES)
        self._initialized = False
        self._previous_index = _IDX_DISCOVER

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        """Build the widget layout with GalleryHeaderBar and stacked pages."""
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        # Gallery header bar (replaces Pivot)
        self._header = GalleryHeaderBar(self)
        self._main_layout.addWidget(self._header)

        # Stacked widget with placeholder pages
        self._stack = QStackedWidget(self)
        for _ in range(len(_PAGE_FACTORIES)):
            self._stack.addWidget(QWidget())
        self._main_layout.addWidget(self._stack, stretch=1)

    def _connect_signals(self) -> None:
        """Connect header signals and auth state."""
        self._header.tab_changed.connect(self._on_tab_changed)
        self._header.search_triggered.connect(self._on_search)
        self._header.user_menu_requested.connect(self._show_user_menu)
        self._services.auth_state_changed.connect(self._on_auth_state_changed)

    def showEvent(self, event: Any) -> None:  # noqa: N802
        """Perform deferred initialization on first show."""
        super().showEvent(event)
        if not self._initialized:
            self._initialized = True
            self._ensure_page(_IDX_DISCOVER)
            page = self._pages[_IDX_DISCOVER]
            if page and hasattr(page, "load_initial"):
                page.load_initial()

    # ── Page management ───────────────────────────────────────

    def _ensure_page(self, index: int) -> Optional[QWidget]:
        """Lazily create a page on first access."""
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

            # Wire page-specific signals
            self._connect_page_signals(index, page)
        except Exception as exc:
            logger.error("%s 创建失败: %s", display_name, exc, exc_info=True)
            error_widget = self._stack.widget(index)
            error_layout = QVBoxLayout(error_widget)
            error_label = SubtitleLabel(f"{display_name} 加载失败: {exc}", error_widget)
            error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            error_layout.addWidget(error_label)

        return self._pages[index]

    def _connect_page_signals(self, index: int, page: QWidget) -> None:
        """Wire signals for a newly created page."""
        if index == _IDX_DISCOVER:
            page.material_selected.connect(self._navigate_to_detail)
            page.download_requested.connect(
                lambda _: self._switch_page(_IDX_DOWNLOADS, "downloads")
            )
            page.creator_clicked.connect(self._navigate_to_creator)
        elif index == _IDX_DETAIL:
            page.back_requested.connect(self._navigate_back)
            page.download_requested.connect(self._on_detail_download)
            page.like_state_changed.connect(self._sync_like_state)
            page.creator_clicked.connect(self._navigate_to_creator)
        elif index == _IDX_CREATOR:
            page.back_requested.connect(self._navigate_back)
            page.material_selected.connect(self._navigate_to_detail)
            page.download_requested.connect(self._on_detail_download)

    def _switch_page(self, index: int, name: str) -> None:
        """Switch to a page, checking auth if required."""
        if index in self._PAGE_AUTH_REQUIRED and not self._services.auth_service.is_authenticated:
            self._show_login_dialog(on_success=lambda: self._do_switch_page(index, name))
            return
        self._do_switch_page(index, name)

    def _do_switch_page(self, index: int, name: str) -> None:
        """Perform the actual page switch."""
        self._previous_index = self._stack.currentIndex()
        self._ensure_page(index)
        self._stack.setCurrentIndex(index)
        self.page_changed.emit(name)

    # ── Navigation ────────────────────────────────────────────

    @Slot(str)
    def _on_tab_changed(self, tab_key: str) -> None:
        """GalleryHeaderBar tab changed → adjust DiscoverPage sort mode."""
        # Always show DiscoverPage for content tabs
        self._do_switch_page(_IDX_DISCOVER, tab_key)
        page = self._pages[_IDX_DISCOVER]
        if page and hasattr(page, "set_sort_mode"):
            page.set_sort_mode(tab_key)

    @Slot(str)
    def _on_search(self, query: str) -> None:
        """Header search → delegate to DiscoverPage."""
        self._do_switch_page(_IDX_DISCOVER, "discover")
        page = self._pages[_IDX_DISCOVER]
        if page and hasattr(page, "set_search_query"):
            page.set_search_query(query)

    @Slot(str)
    def _navigate_to_detail(self, material_id: str) -> None:
        """Card clicked → show MaterialDetailPage."""
        self._ensure_page(_IDX_DETAIL)
        detail_page = self._pages[_IDX_DETAIL]
        if detail_page is None:
            return

        # Try to pass the already-loaded material for instant display
        discover_page = self._pages[_IDX_DISCOVER]
        material = None
        if discover_page and hasattr(discover_page, "get_material"):
            material = discover_page.get_material(material_id)

        if material:
            detail_page.load_material(material)
        else:
            detail_page.load_material_by_id(material_id)

        self._do_switch_page(_IDX_DETAIL, "detail")

    @Slot()
    def _navigate_back(self) -> None:
        """Detail page back button → return to previous page."""
        prev = self._previous_index if self._previous_index != _IDX_DETAIL else _IDX_DISCOVER
        self._do_switch_page(prev, "discover")
        self._header.set_current_tab("discover")

    @Slot(str)
    def _on_detail_download(self, material_id: str) -> None:
        """Handle download from detail page using the shared download flow."""
        # Delegate to discover page's download logic
        discover_page = self._pages[_IDX_DISCOVER]
        if discover_page and hasattr(discover_page, "_on_download_requested"):
            discover_page._on_download_requested(material_id)

    @Slot(str)
    def _navigate_to_creator(self, creator_id: str) -> None:
        """Navigate to a creator's profile page."""
        self._ensure_page(_IDX_CREATOR)
        creator_page = self._pages[_IDX_CREATOR]
        if creator_page:
            creator_page.load_creator(creator_id)
        self._do_switch_page(_IDX_CREATOR, "creator")

    @Slot(str, bool, int)
    def _sync_like_state(self, material_id: str, is_liked: bool, like_count: int) -> None:
        """Sync like state from detail page back to discover page cards."""
        discover = self._pages[_IDX_DISCOVER]
        if discover and hasattr(discover, "update_card_like_state"):
            discover.update_card_like_state(material_id, is_liked, like_count)

    # ── User menu ─────────────────────────────────────────────

    def _show_user_menu(self) -> None:
        """Show a context menu with utility page links."""
        menu = RoundMenu(parent=self)
        menu.addAction(
            Action(FluentIcon.BOOK_SHELF, "\u7d20\u6750\u5e93",  # 素材库
                   triggered=lambda: self._switch_page(_IDX_LIBRARY, "library"))
        )
        menu.addAction(
            Action(FluentIcon.DOWNLOAD, "\u4e0b\u8f7d",  # 下载
                   triggered=lambda: self._switch_page(_IDX_DOWNLOADS, "downloads"))
        )
        menu.addSeparator()
        menu.addAction(
            Action(FluentIcon.SETTING, "\u8bbe\u7f6e",  # 设置
                   triggered=lambda: self._switch_page(_IDX_SETTINGS, "settings"))
        )

        # Position below the user button
        btn = self._header._user_btn
        pos = btn.mapToGlobal(btn.rect().bottomLeft())
        menu.exec(pos)

    # ── Auth ──────────────────────────────────────────────────

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
        if not authenticated and self._stack.currentIndex() == _IDX_LIBRARY:
            self._do_switch_page(_IDX_DISCOVER, "discover")
            self._header.set_current_tab("discover")

    # ── Public API ────────────────────────────────────────────

    @property
    def service_manager(self) -> ServiceManager:
        """Return the service manager instance."""
        return self._services

    def shutdown(self) -> None:
        """Clean up resources before the widget is destroyed."""
        self._services.shutdown()
