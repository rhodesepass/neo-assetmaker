"""HTTP API client for the asset store server communication.

Uses httpx synchronous client with automatic Bearer token injection
and transparent token refresh on 401 responses.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Generator, Optional

import httpx

from _mext.core.config import Config, get_config
from _mext.core.constants import (
    DOWNLOAD_CHUNK_SIZE,
)

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """Raised when the API returns an unexpected status code."""

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class ApiClient:
    """Synchronous HTTP client with token management.

    Parameters
    ----------
    config : Config, optional
        Application configuration. Uses the global singleton if not provided.
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        self._config = config or get_config()
        self._access_token: Optional[str] = None
        self._refresh_callback: Optional[callable] = None

        self._client = httpx.Client(
            base_url=self._config.api_url,
            timeout=httpx.Timeout(
                connect=10.0,
                read=float(self._config.api_timeout),
                write=30.0,
                pool=10.0,
            ),
            follow_redirects=True,
            headers={
                "User-Agent": "AssetStore/1.0",
                "Accept": "application/json",
            },
        )

    # -- Token management --

    @property
    def access_token(self) -> Optional[str]:
        """Return the current access token, if set."""
        return self._access_token

    @access_token.setter
    def access_token(self, token: Optional[str]) -> None:
        """Set the access token for subsequent requests."""
        self._access_token = token

    def set_refresh_callback(self, callback: callable) -> None:
        """Register a callback invoked when a 401 triggers token refresh.

        The callback should return a new access token string or None.
        """
        self._refresh_callback = callback

    def _build_headers(self, extra_headers: Optional[dict[str, str]] = None) -> dict[str, str]:
        """Build request headers, injecting Authorization if token exists."""
        headers: dict[str, str] = {}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _handle_response(self, response: httpx.Response) -> httpx.Response:
        """Check response status and raise ApiError on failure."""
        if response.status_code >= 400:
            detail = ""
            try:
                body = response.json()
                detail = body.get("detail", body.get("message", str(body)))
            except Exception:
                detail = response.text[:500]
            raise ApiError(response.status_code, detail)
        return response

    def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> httpx.Response:
        """Execute a request with automatic 401 retry after token refresh."""
        merged_headers = self._build_headers(headers)

        try:
            response = self._client.request(
                method,
                path,
                json=json,
                params=params,
                data=data,
                headers=merged_headers,
            )
        except httpx.TimeoutException as exc:
            raise ApiError(0, f"请求超时: {exc}") from exc
        except httpx.TransportError as exc:
            raise ApiError(0, f"网络连接失败: {exc}") from exc

        # Attempt token refresh on 401
        if response.status_code == 401 and self._refresh_callback is not None:
            logger.info("Received 401, attempting token refresh...")
            new_token = self._refresh_callback()
            if new_token:
                self._access_token = new_token
                merged_headers = self._build_headers(headers)
                try:
                    response = self._client.request(
                        method,
                        path,
                        json=json,
                        params=params,
                        data=data,
                        headers=merged_headers,
                    )
                except httpx.TimeoutException as exc:
                    raise ApiError(0, f"请求超时: {exc}") from exc
                except httpx.TransportError as exc:
                    raise ApiError(0, f"网络连接失败: {exc}") from exc

        return self._handle_response(response)

    # -- Public HTTP methods --

    def get(
        self,
        path: str,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Any:
        """Send a GET request and return the JSON response body."""
        response = self._request_with_retry("GET", path, params=params, headers=headers)
        return response.json()

    def post(
        self,
        path: str,
        json: Any = None,
        data: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Any:
        """Send a POST request and return the JSON response body."""
        response = self._request_with_retry("POST", path, json=json, data=data, headers=headers)
        if response.status_code == 204:
            return {}
        return response.json()

    def put(
        self,
        path: str,
        json: Any = None,
        headers: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Send a PUT request and return the JSON response body."""
        response = self._request_with_retry("PUT", path, json=json, headers=headers)
        return response.json()

    def delete(
        self,
        path: str,
        headers: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Send a DELETE request and return the JSON response body.

        Returns an empty dict for 204 No Content responses.
        """
        response = self._request_with_retry("DELETE", path, headers=headers)
        if response.status_code == 204:
            return {}
        return response.json()

    def stream_download(
        self,
        url: str,
        dest: Path,
        *,
        resume_from: int = 0,
        chunk_size: int = DOWNLOAD_CHUNK_SIZE,
    ) -> Generator[tuple[int, int], None, None]:
        """Stream a file download, yielding (bytes_downloaded, total_size).

        Parameters
        ----------
        url : str
            Full URL or path to download from.
        dest : Path
            Destination file path (writes to .tmp then renames).
        resume_from : int
            Byte offset to resume from (sends Range header).
        chunk_size : int
            Size of each chunk to read.

        Yields
        ------
        tuple[int, int]
            (bytes_downloaded_so_far, total_expected_size). total may be 0
            if the server does not provide Content-Length.
        """
        headers = self._build_headers()
        if resume_from > 0:
            headers["Range"] = f"bytes={resume_from}-"

        with self._client.stream(
            "GET",
            url,
            headers=headers,
            timeout=httpx.Timeout(
                connect=10.0,
                read=float(self._config.api_stream_timeout),
                write=30.0,
                pool=10.0,
            ),
        ) as response:
            if response.status_code not in (200, 206):
                raise ApiError(response.status_code, "Download failed")

            total_size = int(response.headers.get("content-length", 0))
            if resume_from > 0 and total_size > 0:
                total_size += resume_from

            downloaded = resume_from
            mode = "ab" if resume_from > 0 else "wb"

            with open(dest, mode) as fh:
                for chunk in response.iter_bytes(chunk_size=chunk_size):
                    fh.write(chunk)
                    downloaded += len(chunk)
                    yield downloaded, total_size

    # -- Lifecycle --

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
