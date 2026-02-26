"""Platform detection utilities for the asset store.

Provides functions to identify the current operating system and privilege
level, used for platform-specific FIDO2 client selection, USB access,
and build configuration.
"""

from __future__ import annotations

import ctypes
import os
import platform


def is_windows() -> bool:
    """Return True if running on Windows."""
    return platform.system() == "Windows"


def is_macos() -> bool:
    """Return True if running on macOS."""
    return platform.system() == "Darwin"


def is_linux() -> bool:
    """Return True if running on Linux."""
    return platform.system() == "Linux"


def get_platform_name() -> str:
    """Return a normalized platform name string.

    Returns one of: "windows", "macos", "linux", or "unknown".
    """
    system = platform.system()
    mapping = {
        "Windows": "windows",
        "Darwin": "macos",
        "Linux": "linux",
    }
    return mapping.get(system, "unknown")


def is_admin() -> bool:
    """Return True if the current process has administrator/root privileges.

    On Windows, checks for elevated (Administrator) privileges.
    On Unix systems, checks if the effective user ID is 0 (root).
    """
    if is_windows():
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except (AttributeError, OSError):
            return False
    else:
        return os.geteuid() == 0


def get_system_info() -> dict[str, str]:
    """Return a dictionary of system information for diagnostics.

    Useful for bug reports and compatibility checks.
    """
    return {
        "platform": get_platform_name(),
        "platform_version": platform.version(),
        "platform_release": platform.release(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "is_admin": str(is_admin()),
    }


def get_qt_binding() -> str:
    """Return the name of the active Qt binding (e.g., 'PySide6', 'PyQt6').

    Uses qtpy's API_NAME which is set at import time based on the
    QT_API environment variable or auto-detection.
    """
    try:
        import qtpy

        return qtpy.API_NAME
    except ImportError:
        return "unknown"
