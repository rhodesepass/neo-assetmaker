"""QThread-based workers for offloading blocking API / auth calls.

Runs network operations off the main thread so the UI remains responsive.
Each worker emits ``completed`` on success and ``error(str)`` on failure.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from qtpy.QtCore import QObject, QThread, Signal

from _mext.services.api_client import ApiClient, ApiError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Login / Register
# ---------------------------------------------------------------------------

class AuthLoginWorker(QThread):
    """Run ``auth_service.login()`` in a background thread.

    Signals
    -------
    completed(bool)
        Login result (True = success, False = FIDO2 required).
    fido2_required(str, str)
        Emitted when FIDO2 2FA is needed (fido2_token, username).
    error(str)
        Error message on failure.
    """

    completed = Signal(bool)
    fido2_required = Signal(str, str)
    error = Signal(str)

    def __init__(
        self,
        auth_service: Any,
        username: str,
        password: str,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._auth = auth_service
        self._username = username
        self._password = password
        self._fido2_emitted = False

        # Temporarily intercept the fido2_required signal from auth_service
        self._auth.fido2_required.connect(self._on_fido2)

    def _on_fido2(self, token: str, username: str) -> None:
        self._fido2_emitted = True
        self.fido2_required.emit(token, username)

    def run(self) -> None:
        try:
            result = self._auth.login(self._username, self._password)
            if not self._fido2_emitted:
                self.completed.emit(result)
        except Exception as exc:
            logger.error("AuthLoginWorker error: %s", exc)
            self.error.emit(str(exc))
        finally:
            try:
                self._auth.fido2_required.disconnect(self._on_fido2)
            except (TypeError, RuntimeError):
                pass


class AuthRegisterWorker(QThread):
    """Run ``auth_service.register()`` in a background thread."""

    completed = Signal(bool)
    error = Signal(str)

    def __init__(
        self,
        auth_service: Any,
        username: str,
        email: str,
        password: str,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._auth = auth_service
        self._username = username
        self._email = email
        self._password = password

    def run(self) -> None:
        try:
            result = self._auth.register(self._username, self._email, self._password)
            self.completed.emit(result)
        except Exception as exc:
            logger.error("AuthRegisterWorker error: %s", exc)
            self.error.emit(str(exc))


class DrmLoginInitWorker(QThread):
    """Run ``auth_service.initiate_drm_login()`` in a background thread."""

    completed = Signal()
    error = Signal(str)

    def __init__(
        self,
        auth_service: Any,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._auth = auth_service

    def run(self) -> None:
        try:
            self._auth.initiate_drm_login()
            self.completed.emit()
        except Exception as exc:
            logger.error("DrmLoginInitWorker error: %s", exc)
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Generic single-shot API call
# ---------------------------------------------------------------------------

class ApiCallWorker(QThread):
    """Execute a single API call (get / post / put / delete) off the UI thread.

    Signals
    -------
    completed(object)
        The JSON response (dict or list).
    error(str)
        Error description.
    """

    completed = Signal(object)
    error = Signal(str)

    def __init__(
        self,
        api_client: ApiClient,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._method = method.upper()
        self._path = path
        self._json = json
        self._params = params
        self._data = data
        self._headers = headers

    def run(self) -> None:
        try:
            if self._method == "GET":
                result = self._api.get(self._path, params=self._params, headers=self._headers)
            elif self._method == "POST":
                result = self._api.post(
                    self._path, json=self._json, data=self._data, headers=self._headers
                )
            elif self._method == "PUT":
                result = self._api.put(self._path, json=self._json, headers=self._headers)
            elif self._method == "DELETE":
                result = self._api.delete(self._path, headers=self._headers)
            else:
                self.error.emit(f"Unsupported HTTP method: {self._method}")
                return
            self.completed.emit(result)
        except ApiError as exc:
            logger.warning("ApiCallWorker %s %s failed: %s", self._method, self._path, exc)
            self.error.emit(exc.detail or str(exc))
        except Exception as exc:
            logger.error("ApiCallWorker unexpected error: %s", exc)
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Market: load materials
# ---------------------------------------------------------------------------

class MaterialsLoadWorker(QThread):
    """Fetch a page of materials from the API."""

    completed = Signal(list, int)  # (items_raw: list[dict], total: int)
    error = Signal(str)

    def __init__(
        self,
        api_client: ApiClient,
        params: dict[str, Any],
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._params = params

    def run(self) -> None:
        try:
            response = self._api.get("materials", params=self._params)
            items = response.get("items", [])
            total = response.get("total", 0)
            self.completed.emit(items, total)
        except ApiError as exc:
            self.error.emit(exc.detail or str(exc))
        except Exception as exc:
            logger.error("MaterialsLoadWorker error: %s", exc)
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Market: resolve download URL (two-step)
# ---------------------------------------------------------------------------

class DownloadUrlWorker(QThread):
    """Request signed download URL then verify to get presigned URL.

    Signals
    -------
    completed(str, str, int)
        (download_url, file_hash, file_size)
    error(str)
        Error description.
    """

    completed = Signal(str, str, int)
    error = Signal(str)

    def __init__(
        self,
        api_client: ApiClient,
        material_id: str,
        fallback_hash: str,
        fallback_size: int,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._material_id = material_id
        self._fallback_hash = fallback_hash
        self._fallback_size = fallback_size

    def run(self) -> None:
        try:
            # Step 1: request signed verification URL
            url_response = self._api.post(
                "downloads/generate-url",
                json={"material_id": self._material_id},
            )
            verify_url = url_response.get("url", "")
            if not verify_url:
                self.error.emit("Server returned empty download URL")
                return

            if verify_url.startswith("/"):
                server_origin = self._api._config.api_base_url.rstrip("/")
                verify_url = f"{server_origin}{verify_url}"

            # Step 2: verify → get presigned URL
            verify_response = self._api.get(verify_url)
            download_url = verify_response.get("presigned_url", "")
            if not download_url:
                self.error.emit("Server returned empty presigned URL")
                return

            file_hash = verify_response.get("file_hash", self._fallback_hash)
            file_size = verify_response.get("file_size", self._fallback_size)
            self.completed.emit(download_url, file_hash or "", file_size)
        except ApiError as exc:
            self.error.emit(exc.detail or str(exc))
        except Exception as exc:
            logger.error("DownloadUrlWorker error: %s", exc)
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Library: load downloads + favourites (fixes N+1 pattern)
# ---------------------------------------------------------------------------

class LibraryLoadWorker(QThread):
    """Load user's download history and favourites in the background.

    Signals
    -------
    completed(list, list)
        (all_materials: list[dict], favorite_materials: list[dict])
    error(str)
        Error description.
    """

    completed = Signal(list, list)
    error = Signal(str)

    def __init__(
        self,
        api_client: ApiClient,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client

    def run(self) -> None:
        try:
            # 1. Fetch download records
            download_records = self._api.get("users/me/downloads")
            materials_raw: list[dict] = []
            if isinstance(download_records, list):
                seen_ids: set[str] = set()
                for record in download_records:
                    mid = str(record.get("material_id", ""))
                    if mid and mid not in seen_ids:
                        seen_ids.add(mid)
                        try:
                            mat_data = self._api.get(f"materials/{mid}")
                            materials_raw.append(mat_data)
                        except ApiError:
                            pass  # Material may have been deleted

            # 2. Fetch favourites
            fav_raw: list[dict] = []
            try:
                fav_items = self._api.get("users/me/favorites")
                if isinstance(fav_items, list):
                    fav_raw = fav_items
            except ApiError:
                pass

            self.completed.emit(materials_raw, fav_raw)
        except ApiError as exc:
            self.error.emit(exc.detail or str(exc))
        except Exception as exc:
            logger.error("LibraryLoadWorker error: %s", exc)
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Settings: load FIDO2 credentials
# ---------------------------------------------------------------------------

class CredentialsLoadWorker(QThread):
    """Load FIDO2 credentials from the server."""

    completed = Signal(list)  # list[dict]
    error = Signal(str)

    def __init__(
        self,
        api_client: ApiClient,
        path: str,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._path = path

    def run(self) -> None:
        try:
            response = self._api.get(self._path)
            self.completed.emit(response.get("credentials", []))
        except ApiError as exc:
            self.error.emit(exc.detail or str(exc))
        except Exception as exc:
            logger.error("CredentialsLoadWorker error: %s", exc)
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# USB: load device files via MTP
# ---------------------------------------------------------------------------

class MtpFileLoadWorker(QThread):
    """Load file tree from a device using MTP in the background.

    Signals
    -------
    completed(list)
        List of (storage_id, handles_or_error) tuples.
    error(str)
        Error description.
    """

    completed = Signal(list)
    error = Signal(str)

    def __init__(
        self,
        mtp_service: Any,
        device_info: dict,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._mtp = mtp_service
        self._device_info = device_info

    def run(self) -> None:
        try:
            mtp = self._mtp
            if not mtp.is_connected:
                mtp.connect(self._device_info)
            if not mtp.is_session_open:
                mtp.open_session()

            storage_ids = mtp.get_storage_ids()
            result: list[tuple[int, list | str]] = []

            for sid in storage_ids:
                try:
                    handles = mtp.get_object_handles(sid)
                    result.append((sid, handles))
                except Exception as exc:
                    result.append((sid, str(exc)))

            self.completed.emit(result)
        except Exception as exc:
            logger.error("MtpFileLoadWorker error: %s", exc)
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# USB: device scan
# ---------------------------------------------------------------------------

class UsbScanWorker(QThread):
    """Run USB device enumeration in a background thread.

    Signals
    -------
    completed(dict)
        Dict of device_id → device_info for all currently connected devices.
    error(str)
        Error description.
    """

    completed = Signal(dict)
    error = Signal(str)

    def run(self) -> None:
        try:
            import usb.core

            devices: dict[str, dict] = {}
            for dev in usb.core.find(find_all=True):
                try:
                    did = f"{dev.idVendor:04x}:{dev.idProduct:04x}:{dev.bus}:{dev.address}"
                    info: dict[str, Any] = {
                        "device_id": did,
                        "vendor_id": f"{dev.idVendor:04x}",
                        "product_id": f"{dev.idProduct:04x}",
                        "bus": dev.bus,
                        "address": dev.address,
                    }
                    try:
                        info["manufacturer"] = dev.manufacturer or ""
                    except Exception:
                        info["manufacturer"] = ""
                    try:
                        info["product"] = dev.product or ""
                    except Exception:
                        info["product"] = ""
                    try:
                        info["serial_number"] = dev.serial_number or ""
                    except Exception:
                        info["serial_number"] = ""
                    devices[did] = info
                except Exception:
                    continue
            self.completed.emit(devices)
        except ImportError:
            self.error.emit("pyusb library not available")
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Auth: background session restore
# ---------------------------------------------------------------------------

class SessionRestoreWorker(QThread):
    """Restore a stored session (keyring + token refresh) in a background thread.

    Avoids blocking the UI thread with keyring reads and synchronous HTTP.

    Signals
    -------
    completed(bool)
        True if the session was restored successfully, False otherwise.
    error(str)
        Error description if an unexpected error occurred.
    """

    completed = Signal(bool)
    error = Signal(str)

    def __init__(
        self,
        auth_service: Any,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._auth = auth_service

    def run(self) -> None:
        try:
            import keyring
            from _mext.core.constants import KEYRING_SERVICE_NAME, KEYRING_REFRESH_TOKEN_KEY

            try:
                stored_refresh = keyring.get_password(
                    KEYRING_SERVICE_NAME, KEYRING_REFRESH_TOKEN_KEY
                )
            except Exception:
                logger.debug("Could not access keyring for session restore")
                self.completed.emit(False)
                return

            if stored_refresh:
                logger.info("Found stored refresh token, attempting session restore...")
                new_token = self._auth._do_refresh_token()
                self.completed.emit(new_token is not None)
            else:
                self.completed.emit(False)
        except Exception as exc:
            logger.error("SessionRestoreWorker error: %s", exc)
            self.error.emit(str(exc))
