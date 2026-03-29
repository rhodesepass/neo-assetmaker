"""QThread-based workers for offloading blocking API / auth calls.

Runs network operations off the main thread so the UI remains responsive.
Each worker emits ``completed`` on success and ``error(str)`` on failure.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal as Signal

from _mext.services.api_client import ApiClient, ApiError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Register (passwordless)
# ---------------------------------------------------------------------------

class AuthRegisterWorker(QThread):
    """Run ``auth_service.register()`` in a background thread."""

    completed = Signal(bool)
    error = Signal(str)

    def __init__(
        self,
        auth_service: Any,
        username: str,
        email: str,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._auth = auth_service
        self._username = username
        self._email = email

    def run(self) -> None:
        try:
            result = self._auth.register(self._username, self._email)
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
# Forum: load materials
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
# Forum: resolve download URL (two-step)
# ---------------------------------------------------------------------------

class MaterialDetailWorker(QThread):
    """Fetch full details for a single material.  GET /materials/{id}

    Signals
    -------
    completed(dict)
        The raw material detail dictionary.
    error(str)
        Error description.
    """

    completed = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        api_client: ApiClient,
        material_id: str,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._material_id = material_id

    def run(self) -> None:
        try:
            response = self._api.get(f"materials/{self._material_id}")
            self.completed.emit(response)
        except ApiError as exc:
            self.error.emit(exc.detail or str(exc))
        except Exception as exc:
            logger.error("MaterialDetailWorker error: %s", exc)
            self.error.emit(str(exc))


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


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

class CommentsLoadWorker(QThread):
    """Fetch comments for a material.  GET /materials/{id}/comments?page=&per_page=

    Signals
    -------
    completed(list, int)
        (comments_raw: list[dict], total: int)
    error(str)
        Error description.
    """

    completed = Signal(list, int)
    error = Signal(str)

    def __init__(
        self,
        api_client: ApiClient,
        material_id: str,
        page: int = 1,
        per_page: int = 20,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._material_id = material_id
        self._page = page
        self._per_page = per_page

    def run(self) -> None:
        try:
            response = self._api.get(
                f"materials/{self._material_id}/comments",
                params={"page": self._page, "per_page": self._per_page},
            )
            items = response.get("items", [])
            total = response.get("total", 0)
            self.completed.emit(items, total)
        except ApiError as exc:
            self.error.emit(exc.detail or str(exc))
        except Exception as exc:
            logger.error("CommentsLoadWorker error: %s", exc)
            self.error.emit(str(exc))


class CommentPostWorker(QThread):
    """Post a new comment.  POST /materials/{id}/comments

    Signals
    -------
    completed(dict)
        The newly created comment as a raw dict.
    error(str)
        Error description.
    """

    completed = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        api_client: ApiClient,
        material_id: str,
        content: str,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._material_id = material_id
        self._content = content

    def run(self) -> None:
        try:
            response = self._api.post(
                f"materials/{self._material_id}/comments",
                json={"content": self._content},
            )
            self.completed.emit(response)
        except ApiError as exc:
            self.error.emit(exc.detail or str(exc))
        except Exception as exc:
            logger.error("CommentPostWorker error: %s", exc)
            self.error.emit(str(exc))


class CommentDeleteWorker(QThread):
    """Delete a comment.  DELETE /comments/{id}

    Signals
    -------
    completed(str)
        The deleted comment ID.
    error(str)
        Error description.
    """

    completed = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        api_client: ApiClient,
        comment_id: str,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._comment_id = comment_id

    def run(self) -> None:
        try:
            self._api.delete(f"comments/{self._comment_id}")
            self.completed.emit(self._comment_id)
        except ApiError as exc:
            self.error.emit(exc.detail or str(exc))
        except Exception as exc:
            logger.error("CommentDeleteWorker error: %s", exc)
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Like / Favorite toggle
# ---------------------------------------------------------------------------

class LikeToggleWorker(QThread):
    """Toggle like state.  POST (like) or DELETE (unlike) /materials/{id}/like

    Signals
    -------
    completed(str, bool, int)
        (material_id, is_liked, new_like_count)
    error(str)
        Error description.
    """

    completed = Signal(str, bool, int)
    error = Signal(str)

    def __init__(
        self,
        api_client: ApiClient,
        material_id: str,
        should_like: bool,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._material_id = material_id
        self._should_like = should_like

    def run(self) -> None:
        try:
            if self._should_like:
                response = self._api.post(f"materials/{self._material_id}/like")
            else:
                response = self._api.delete(f"materials/{self._material_id}/like")
            is_liked = response.get("is_liked", self._should_like)
            like_count = response.get("like_count", 0)
            self.completed.emit(self._material_id, is_liked, like_count)
        except ApiError as exc:
            self.error.emit(exc.detail or str(exc))
        except Exception as exc:
            logger.error("LikeToggleWorker error: %s", exc)
            self.error.emit(str(exc))


class FavoriteToggleWorker(QThread):
    """Toggle favorite state.  POST or DELETE /materials/{id}/favorite

    Signals
    -------
    completed(str, bool)
        (material_id, is_favorited)
    error(str)
        Error description.
    """

    completed = Signal(str, bool)
    error = Signal(str)

    def __init__(
        self,
        api_client: ApiClient,
        material_id: str,
        should_favorite: bool,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._material_id = material_id
        self._should_favorite = should_favorite

    def run(self) -> None:
        try:
            if self._should_favorite:
                response = self._api.post(f"materials/{self._material_id}/favorite")
            else:
                response = self._api.delete(f"materials/{self._material_id}/favorite")
            is_fav = response.get("is_favorited", self._should_favorite)
            self.completed.emit(self._material_id, is_fav)
        except ApiError as exc:
            self.error.emit(exc.detail or str(exc))
        except Exception as exc:
            logger.error("FavoriteToggleWorker error: %s", exc)
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Creator profile & works
# ---------------------------------------------------------------------------

class CreatorProfileWorker(QThread):
    """Fetch a creator's profile.  GET /users/{id}/profile

    Signals
    -------
    completed(dict)
        The profile data.
    error(str)
        Error description.
    """

    completed = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        api_client: ApiClient,
        creator_id: str,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._creator_id = creator_id

    def run(self) -> None:
        try:
            response = self._api.get(f"users/{self._creator_id}/profile")
            self.completed.emit(response)
        except ApiError as exc:
            self.error.emit(exc.detail or str(exc))
        except Exception as exc:
            logger.error("CreatorProfileWorker error: %s", exc)
            self.error.emit(str(exc))


class CreatorWorksWorker(QThread):
    """Fetch a creator's materials.  GET /users/{id}/materials?page=&per_page=

    Signals
    -------
    completed(list, int)
        (materials_raw: list[dict], total: int)
    error(str)
        Error description.
    """

    completed = Signal(list, int)
    error = Signal(str)

    def __init__(
        self,
        api_client: ApiClient,
        creator_id: str,
        page: int = 1,
        per_page: int = 20,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._creator_id = creator_id
        self._page = page
        self._per_page = per_page

    def run(self) -> None:
        try:
            response = self._api.get(
                f"users/{self._creator_id}/materials",
                params={"page": self._page, "per_page": self._per_page},
            )
            items = response.get("items", [])
            total = response.get("total", 0)
            self.completed.emit(items, total)
        except ApiError as exc:
            self.error.emit(exc.detail or str(exc))
        except Exception as exc:
            logger.error("CreatorWorksWorker error: %s", exc)
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Featured / Related materials
# ---------------------------------------------------------------------------

class FeaturedMaterialsWorker(QThread):
    """Fetch featured materials.  GET /materials/featured?limit=

    Signals
    -------
    completed(list)
        list[dict] of featured material data.
    error(str)
        Error description.
    """

    completed = Signal(list)
    error = Signal(str)

    def __init__(
        self,
        api_client: ApiClient,
        limit: int = 10,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._limit = limit

    def run(self) -> None:
        try:
            response = self._api.get(
                "materials/featured",
                params={"limit": self._limit},
            )
            items = response if isinstance(response, list) else response.get("items", [])
            self.completed.emit(items)
        except ApiError as exc:
            self.error.emit(exc.detail or str(exc))
        except Exception as exc:
            logger.error("FeaturedMaterialsWorker error: %s", exc)
            self.error.emit(str(exc))


class RelatedMaterialsWorker(QThread):
    """Fetch related materials.  GET /materials/{id}/related?limit=

    Signals
    -------
    completed(list)
        list[dict] of related material data.
    error(str)
        Error description.
    """

    completed = Signal(list)
    error = Signal(str)

    def __init__(
        self,
        api_client: ApiClient,
        material_id: str,
        limit: int = 6,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._material_id = material_id
        self._limit = limit

    def run(self) -> None:
        try:
            response = self._api.get(
                f"materials/{self._material_id}/related",
                params={"limit": self._limit},
            )
            items = response if isinstance(response, list) else response.get("items", [])
            self.completed.emit(items)
        except ApiError as exc:
            self.error.emit(exc.detail or str(exc))
        except Exception as exc:
            logger.error("RelatedMaterialsWorker error: %s", exc)
            self.error.emit(str(exc))
