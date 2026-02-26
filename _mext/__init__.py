"""Asset Store - Cross-platform material asset manager.

A Qt desktop application (via qtpy) for browsing, downloading, and managing
material assets with FIDO2 authentication and USB device integration.
"""

__version__ = "1.0.0"
__app_name__ = "Asset Store"
__author__ = "AssetStore"

from _mext.core.constants import API_VERSION, APP_ID, APP_NAME

__all__ = [
    "__version__",
    "__app_name__",
    "__author__",
    "APP_ID",
    "APP_NAME",
    "API_VERSION",
]
