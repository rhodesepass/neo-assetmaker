"""Page views for the asset store UI.

Each page represents a top-level navigation destination within the
application.
"""

from _mext.ui.pages.downloads_page import DownloadsPage
from _mext.ui.pages.library_page import LibraryPage
from _mext.ui.pages.login_page import LoginPage
from _mext.ui.pages.market_page import MarketPage
from _mext.ui.pages.settings_page import SettingsPage
from _mext.ui.pages.usb_page import UsbPage

__all__ = [
    "LoginPage",
    "MarketPage",
    "LibraryPage",
    "DownloadsPage",
    "UsbPage",
    "SettingsPage",
]
