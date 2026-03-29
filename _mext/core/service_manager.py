"""Central service registry for the asset store.

Provides lazy-initialized access to all application services and emits
signals for cross-cutting concerns like download progress and auth state
changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import QObject, pyqtSignal as Signal

from _mext.core.config import Config, get_config

if TYPE_CHECKING:
    from _mext.services.api_client import ApiClient
    from _mext.services.auth_service import AuthService
    from _mext.services.download_engine import DownloadEngine
    from _mext.services.fido2_client import Fido2ClientWrapper


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
    """

    # Signals
    download_started = Signal(str)
    download_completed = Signal(str)
    download_failed = Signal(str, str)
    auth_state_changed = Signal(bool)

    def __init__(self, config: Optional[Config] = None, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._config = config or get_config()

        # Private service instances (lazy)
        self._api_client: Optional[ApiClient] = None
        self._auth_service: Optional[AuthService] = None
        self._download_engine: Optional[DownloadEngine] = None
        self._fido2_client: Optional[Fido2ClientWrapper] = None

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


    # -- Lifecycle --

    def shutdown(self) -> None:
        """Cleanly shut down all initialized services.

        Stops background threads, closes connections, and releases resources.
        Safe to call multiple times.
        """
        if self._is_shutdown:
            return

        self._is_shutdown = True

        # Cancel active downloads
        if self._download_engine is not None:
            self._download_engine.cancel_all()

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
