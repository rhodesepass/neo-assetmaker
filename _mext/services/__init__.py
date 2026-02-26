"""Service layer for the asset store.

Provides API communication, authentication, downloads, FIDO2 integration,
USB device monitoring, and MTP file transfers.
"""

__all__ = [
    "ApiClient",
    "AuthService",
    "DownloadEngine",
    "DownloadWorker",
    "Fido2ClientWrapper",
    "Fido2RegisterWorker",
    "Fido2AuthWorker",
    "UsbService",
    "MtpService",
]


def __getattr__(name: str):  # noqa: N807
    """Lazy imports to avoid circular dependencies and heavy startup cost."""
    _import_map = {
        "ApiClient": "_mext.services.api_client",
        "AuthService": "_mext.services.auth_service",
        "DownloadEngine": "_mext.services.download_engine",
        "DownloadWorker": "_mext.services.download_worker",
        "Fido2ClientWrapper": "_mext.services.fido2_client",
        "Fido2RegisterWorker": "_mext.services.fido2_worker",
        "Fido2AuthWorker": "_mext.services.fido2_worker",
        "UsbService": "_mext.services.usb_service",
        "MtpService": "_mext.services.mtp_service",
    }
    if name in _import_map:
        import importlib

        module = importlib.import_module(_import_map[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
