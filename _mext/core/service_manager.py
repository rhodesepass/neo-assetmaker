"""Central service registry for the asset store.

Provides lazy-initialized access to all application services and emits
signals for cross-cutting concerns like download progress, auth state
changes, and USB device events.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from qtpy.QtCore import QObject, Signal

from _mext.core.config import Config, get_config

if TYPE_CHECKING:
    from _mext.services.api_client import ApiClient
    from _mext.services.auth_service import AuthService
    from _mext.services.download_engine import DownloadEngine
    from _mext.services.fido2_client import Fido2ClientWrapper
    from _mext.services.mtp_service import MtpService
    from _mext.services.usb_service import UsbService


class ServiceManager(QObject):
    """Central service registry with lifecycle management.

    All services are lazily initialized on first access. The ``shutdown()``
    method must be called before application exit to cleanly tear down
    background threads and connections.

    Signals
    -------
    download_started(str)
        Emitted when a download begins. Payload is the download task ID.
    download_completed(str)
        Emitted when a download finishes successfully. Payload is the task ID.
    download_failed(str, str)
        Emitted when a download fails. Payload is (task_id, error_message).
    auth_state_changed(bool)
        Emitted when the user logs in or out. Payload is ``True`` if
        authenticated, ``False`` otherwise.
    usb_device_changed(str, bool)
        Emitted when a USB device is connected or disconnected.
        Payload is (device_id, connected).
    """

    # Signals
    download_started = Signal(str)
    download_completed = Signal(str)
    download_failed = Signal(str, str)
    auth_state_changed = Signal(bool)
    usb_device_changed = Signal(str, bool)

    def __init__(self, config: Optional[Config] = None, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._config = config or get_config()

        # Private service instances (lazy)
        self._api_client: Optional[ApiClient] = None
        self._auth_service: Optional[AuthService] = None
        self._download_engine: Optional[DownloadEngine] = None
        self._fido2_client: Optional[Fido2ClientWrapper] = None
        self._usb_service: Optional[UsbService] = None
        self._mtp_service: Optional[MtpService] = None

        self._is_shutdown = False

    # -- Properties for lazy service access --

    @property
    def config(self) -> Config:
        """Return the application configuration."""
        return self._config

    @property
    def api_client(self) -> ApiClient:
        """Return the HTTP API client, creating it on first access."""
        if self._api_client is None:
            from _mext.services.api_client import ApiClient

            self._api_client = ApiClient(config=self._config)
        return self._api_client

    @property
    def auth_service(self) -> AuthService:
        """Return the authentication service, creating it on first access."""
        if self._auth_service is None:
            from _mext.services.auth_service import AuthService

            self._auth_service = AuthService(
                api_client=self.api_client,
                config=self._config,
            )
            # Wire auth signals
            self._auth_service.auth_changed.connect(self.auth_state_changed.emit)
        return self._auth_service

    @property
    def download_engine(self) -> DownloadEngine:
        """Return the download engine, creating it on first access."""
        if self._download_engine is None:
            from _mext.services.download_engine import DownloadEngine

            self._download_engine = DownloadEngine(
                api_client=self.api_client,
                config=self._config,
                parent=self,
            )
            # Wire download signals
            self._download_engine.download_started.connect(self.download_started.emit)
            self._download_engine.download_completed.connect(
                lambda task_id, _path: self.download_completed.emit(task_id)
            )
            self._download_engine.download_failed.connect(self.download_failed.emit)
        return self._download_engine

    @property
    def fido2_client(self) -> Fido2ClientWrapper:
        """Return the FIDO2 client wrapper, creating it on first access."""
        if self._fido2_client is None:
            from _mext.services.fido2_client import Fido2ClientWrapper

            self._fido2_client = Fido2ClientWrapper(config=self._config)
        return self._fido2_client

    @property
    def usb_service(self) -> UsbService:
        """Return the USB monitoring service, creating it on first access."""
        if self._usb_service is None:
            from _mext.services.usb_service import UsbService

            self._usb_service = UsbService(parent=self)
            self._usb_service.device_connected.connect(
                lambda info: self.usb_device_changed.emit(info.get("device_id", "unknown"), True)
            )
            self._usb_service.device_disconnected.connect(
                lambda dev_id: self.usb_device_changed.emit(dev_id, False)
            )
        return self._usb_service

    @property
    def mtp_service(self) -> MtpService:
        """Return the MTP service, creating it on first access."""
        if self._mtp_service is None:
            from _mext.services.mtp_service import MtpService

            self._mtp_service = MtpService()
        return self._mtp_service

    # -- Lifecycle --

    def shutdown(self) -> None:
        """Cleanly shut down all initialized services.

        Stops background threads, closes connections, and releases resources.
        Safe to call multiple times.
        """
        if self._is_shutdown:
            return

        self._is_shutdown = True

        # Stop USB polling
        if self._usb_service is not None:
            self._usb_service.stop_monitoring()

        # Cancel active downloads
        if self._download_engine is not None:
            self._download_engine.cancel_all()

        # Close MTP sessions
        if self._mtp_service is not None:
            try:
                self._mtp_service.close_session()
            except Exception:
                pass

        # Logout / cleanup auth
        if self._auth_service is not None:
            self._auth_service.cleanup()

        # Close HTTP client
        if self._api_client is not None:
            self._api_client.close()

    @property
    def is_shutdown(self) -> bool:
        """Return True if shutdown() has been called."""
        return self._is_shutdown
