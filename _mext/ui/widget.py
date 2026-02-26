"""Main embeddable widget for the asset store.

MaterialMarketWidget is designed to be embedded in any QWidget-based
host application. It provides a Pivot-based tab navigation between
all major pages (Market, Library, Downloads, USB, Settings).
"""

from __future__ import annotations

from typing import Optional

from qfluentwidgets import Pivot
from qtpy.QtCore import Signal, Slot
from qtpy.QtWidgets import (
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from _mext.core.service_manager import ServiceManager
from _mext.ui.pages.downloads_page import DownloadsPage
from _mext.ui.pages.library_page import LibraryPage
from _mext.ui.pages.login_page import LoginPage
from _mext.ui.pages.market_page import MarketPage
from _mext.ui.pages.settings_page import SettingsPage
from _mext.ui.pages.usb_page import UsbPage


class MaterialMarketWidget(QWidget):
    """Embeddable main widget with tabbed page navigation.

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

    def __init__(
        self,
        service_manager: Optional[ServiceManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._services = service_manager or ServiceManager(parent=self)

        self._setup_ui()
        self._connect_signals()

        # Check if authenticated; show login page if not
        if not self._services.auth_service.is_authenticated:
            self._show_login()
        else:
            self._show_main()

    def _setup_ui(self) -> None:
        """Build the widget layout with Pivot navigation and stacked pages."""
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        # Login page (shown when not authenticated)
        self._login_page = LoginPage(self._services, parent=self)

        # Pivot navigation bar
        self._pivot = Pivot(self)

        # Stacked widget for page content
        self._stack = QStackedWidget(self)

        # Create pages
        self._market_page = MarketPage(self._services, parent=self)
        self._library_page = LibraryPage(self._services, parent=self)
        self._downloads_page = DownloadsPage(self._services, parent=self)
        self._usb_page = UsbPage(self._services, parent=self)
        self._settings_page = SettingsPage(self._services, parent=self)

        # Add pages to stack
        self._stack.addWidget(self._market_page)
        self._stack.addWidget(self._library_page)
        self._stack.addWidget(self._downloads_page)
        self._stack.addWidget(self._usb_page)
        self._stack.addWidget(self._settings_page)

        # Add pivot items
        self._pivot.addItem(
            routeKey="market",
            text="商城",
            onClick=lambda: self._switch_page(0, "market"),
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
            routeKey="usb",
            text="USB 设备",
            onClick=lambda: self._switch_page(3, "usb"),
        )
        self._pivot.addItem(
            routeKey="settings",
            text="设置",
            onClick=lambda: self._switch_page(4, "settings"),
        )

        self._pivot.setCurrentItem("market")

        # Build layout
        self._content_layout = QVBoxLayout()
        self._content_layout.setContentsMargins(12, 8, 12, 12)
        self._content_layout.setSpacing(8)
        self._content_layout.addWidget(self._pivot)
        self._content_layout.addWidget(self._stack)

        # Content wrapper (hidden when login is shown)
        self._content_widget = QWidget(self)
        self._content_widget.setLayout(self._content_layout)

        self._main_layout.addWidget(self._login_page)
        self._main_layout.addWidget(self._content_widget)

    def _connect_signals(self) -> None:
        """Connect inter-component signals."""
        # Auth state changes
        self._services.auth_state_changed.connect(self._on_auth_state_changed)

        # Login page signals
        self._login_page.login_successful.connect(self._show_main)

    def _switch_page(self, index: int, name: str) -> None:
        """Switch the stacked widget to the specified page index."""
        self._stack.setCurrentIndex(index)
        self.page_changed.emit(name)

    @Slot()
    def _show_login(self) -> None:
        """Show the login page, hide the main content."""
        self._login_page.setVisible(True)
        self._content_widget.setVisible(False)

    @Slot()
    def _show_main(self) -> None:
        """Show the main content, hide the login page."""
        self._login_page.setVisible(False)
        self._content_widget.setVisible(True)

    @Slot(bool)
    def _on_auth_state_changed(self, authenticated: bool) -> None:
        """Handle authentication state changes."""
        if authenticated:
            self._show_main()
        else:
            self._show_login()

    @property
    def service_manager(self) -> ServiceManager:
        """Return the service manager instance."""
        return self._services

    def shutdown(self) -> None:
        """Clean up resources before the widget is destroyed."""
        self._services.shutdown()
