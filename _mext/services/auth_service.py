"""Authentication service for the asset store.

Implements OAuth2 + PKCE flow with local HTTP callback server, token
management via keyring, and integration with the API client for login,
register, logout, and token refresh operations.
"""

from __future__ import annotations

import http.server
import logging
import threading
import urllib.parse
import webbrowser
from typing import Any, Optional

import keyring
from qtpy.QtCore import QObject, QTimer, Signal

from _mext.core.config import Config, get_config
from _mext.core.constants import (
    KEYRING_REFRESH_TOKEN_KEY,
    KEYRING_SERVICE_NAME,
    OAUTH_REDIRECT_HOST,
)
from _mext.services.api_client import ApiClient, ApiError

logger = logging.getLogger(__name__)


class _OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """Minimal HTTP handler that captures the OAuth callback parameters."""

    code: Optional[str] = None
    state: Optional[str] = None
    error: Optional[str] = None

    def do_GET(self) -> None:  # noqa: N802
        """Handle GET request from the OAuth redirect."""
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        _OAuthCallbackHandler.code = params.get("code", [None])[0]
        _OAuthCallbackHandler.state = params.get("state", [None])[0]
        _OAuthCallbackHandler.error = params.get("error", [None])[0]

        # Send a simple success page back to the browser
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        body = (
            "<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
            "<h1>Authentication Successful</h1>"
            "<p>You can close this tab and return to the asset store.</p>"
            "</body></html>"
        )
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default stderr logging."""
        logger.debug("OAuth callback: %s", format % args)


class AuthService(QObject):
    """Manages authentication state, OAuth2 + PKCE flow, and token lifecycle.

    Signals
    -------
    auth_changed(bool)
        Emitted when authentication state changes. ``True`` = logged in.
    login_error(str)
        Emitted when a login attempt fails.
    """

    auth_changed = Signal(bool)
    login_error = Signal(str)
    fido2_required = Signal(str, str)  # (fido2_token, username)

    def __init__(
        self,
        api_client: ApiClient,
        config: Optional[Config] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._config = config or get_config()

        self._access_token: Optional[str] = None
        self._user_info: Optional[dict[str, Any]] = None
        self._oauth_state: Optional[str] = None
        self._callback_server: Optional[http.server.HTTPServer] = None
        self._callback_thread: Optional[threading.Thread] = None

        # Register refresh callback on the API client
        self._api.set_refresh_callback(self._do_refresh_token)

        # Attempt to restore session from keyring asynchronously
        QTimer.singleShot(0, self._restore_session)

    # -- Public properties --

    @property
    def is_authenticated(self) -> bool:
        """Return ``True`` if the user has a valid access token."""
        return self._access_token is not None

    @property
    def user_info(self) -> Optional[dict[str, Any]]:
        """Return cached user information, or None if not logged in."""
        return self._user_info

    @property
    def access_token(self) -> Optional[str]:
        """Return the current access token."""
        return self._access_token

    # -- Login / register / logout --

    def login(self, username: str, password: str) -> bool:
        """Authenticate with username and password.

        Returns True on success. If the server indicates FIDO2 is required,
        emits ``fido2_required(fido2_token, username)`` and returns False
        (the caller should then start the FIDO2 flow). Emits ``login_error``
        on failure.
        """
        try:
            data = self._api.post(
                "auth/login",
                json={"username": username, "password": password},
            )

            # Check if FIDO2 second factor is required
            if data.get("requires_fido2"):
                fido2_token = data.get("fido2_token", "")
                self.fido2_required.emit(fido2_token, username)
                return False

            self._handle_token_response(data)
            return True
        except ApiError as exc:
            logger.warning("Login failed: %s", exc)
            self.login_error.emit(str(exc.detail or exc))
            return False

    def register(self, username: str, email: str, password: str) -> bool:
        """Register a new user account.

        Returns True on success, emits ``login_error`` on failure.
        """
        try:
            data = self._api.post(
                "auth/register",
                json={"username": username, "email": email, "password": password},
            )
            self._handle_token_response(data)
            return True
        except ApiError as exc:
            logger.warning("Registration failed: %s", exc)
            self.login_error.emit(str(exc.detail or exc))
            return False

    def logout(self) -> None:
        """Log out: revoke tokens on the server, clear local state."""
        if self._access_token:
            try:
                stored_refresh = keyring.get_password(
                    KEYRING_SERVICE_NAME, KEYRING_REFRESH_TOKEN_KEY
                )
                self._api.post("auth/logout", json={"refresh_token": stored_refresh})
            except Exception:
                logger.debug("Server-side logout failed, continuing local cleanup")

        self._clear_tokens()
        self.auth_changed.emit(False)

    # -- OAuth2 + PKCE (DRM login) --

    def initiate_drm_login(self) -> None:
        """Start the OAuth2 + PKCE flow.

        Asks the server for the authorization URL (the server generates the
        PKCE pair and stores the code_verifier), then opens the system
        browser and starts a local HTTP server to receive the callback.
        """
        try:
            # Ask server to generate the authorization URL with PKCE
            redirect_uri = self._config.oauth_redirect_uri
            data = self._api.post(
                f"auth/drm-login/initiate?redirect_uri={urllib.parse.quote(redirect_uri)}",
            )
            auth_url = data.get("auth_url", "")
            self._oauth_state = data.get("state", "")

            if not auth_url:
                self.login_error.emit("Server returned empty authorization URL.")
                return

            # Start local callback server
            self._start_callback_server()

            logger.info("Opening browser for DRM login: %s", auth_url)
            webbrowser.open(auth_url)
        except ApiError as exc:
            self.login_error.emit(f"Could not initiate DRM login: {exc.detail}")

    def handle_callback(self) -> bool:
        """Wait for and process the OAuth callback.

        Returns True if the callback was received and tokens were obtained.
        This blocks until the callback server receives a request or times out.
        """
        if self._callback_thread is None:
            return False

        # Wait for callback (with timeout)
        self._callback_thread.join(timeout=120)
        self._stop_callback_server()

        code = _OAuthCallbackHandler.code
        state = _OAuthCallbackHandler.state
        error = _OAuthCallbackHandler.error

        # Reset handler class vars
        _OAuthCallbackHandler.code = None
        _OAuthCallbackHandler.state = None
        _OAuthCallbackHandler.error = None

        if error:
            self.login_error.emit(f"OAuth error: {error}")
            return False

        if not code or state != self._oauth_state:
            self.login_error.emit("Invalid OAuth callback: state mismatch or missing code")
            return False

        # Send code + state to server for token exchange
        try:
            data = self._api.post(
                "auth/drm-login/callback",
                json={
                    "code": code,
                    "state": state,
                },
            )
            self._handle_token_response(data)
            return True
        except ApiError as exc:
            self.login_error.emit(f"Token exchange failed: {exc.detail}")
            return False

    def _start_callback_server(self) -> None:
        """Start the local HTTP server for OAuth callback."""
        self._stop_callback_server()

        #
        self._callback_server = http.server.HTTPServer(
            (OAUTH_REDIRECT_HOST, self._config.oauth_redirect_port),
            _OAuthCallbackHandler,
        )
        self._callback_server.timeout = 120

        def serve() -> None:
            self._callback_server.handle_request()

        self._callback_thread = threading.Thread(target=serve, daemon=True)
        self._callback_thread.start()

    def _stop_callback_server(self) -> None:
        """Stop the local OAuth callback server if running."""
        if self._callback_server is not None:
            try:
                self._callback_server.server_close()
            except Exception:
                pass
            self._callback_server = None
        self._callback_thread = None

    # -- Token management --

    def refresh_token(self) -> bool:
        """Attempt to refresh the access token using the stored refresh token.

        Returns True on success.
        """
        new_token = self._do_refresh_token()
        return new_token is not None

    def _do_refresh_token(self) -> Optional[str]:
        """Internal refresh logic, used as callback for ApiClient 401 retry."""
        try:
            stored_refresh = keyring.get_password(KEYRING_SERVICE_NAME, KEYRING_REFRESH_TOKEN_KEY)
        except Exception as exc:
            logger.warning("Failed to read refresh token from keyring: %s", exc)
            return None
        if not stored_refresh:
            logger.warning("No refresh token available")
            self._clear_tokens()
            self.auth_changed.emit(False)
            return None

        try:
            # Use a direct request to avoid infinite retry loop
            response = self._api._client.post(
                "auth/refresh",
                json={"refresh_token": stored_refresh},
                headers={"Accept": "application/json"},
            )
            if response.status_code != 200:
                logger.warning("Token refresh returned %d", response.status_code)
                self._clear_tokens()
                self.auth_changed.emit(False)
                return None

            data = response.json()
            self._handle_token_response(data, emit_signal=False)
            return self._access_token
        except Exception as exc:
            logger.error("Token refresh error: %s", exc)
            self._clear_tokens()
            self.auth_changed.emit(False)
            return None

    def _handle_token_response(self, data: dict[str, Any], emit_signal: bool = True) -> None:
        """Process a token response from the server."""
        self._access_token = data.get("access_token")
        self._api.access_token = self._access_token

        refresh = data.get("refresh_token")
        if refresh:
            try:
                keyring.set_password(KEYRING_SERVICE_NAME, KEYRING_REFRESH_TOKEN_KEY, refresh)
            except Exception:
                logger.warning("Could not save refresh token to keyring")

        self._user_info = data.get("user")

        if emit_signal:
            self.auth_changed.emit(True)

    def _restore_session(self) -> None:
        """Try to restore a session from a stored refresh token on startup."""
        try:
            stored_refresh = keyring.get_password(KEYRING_SERVICE_NAME, KEYRING_REFRESH_TOKEN_KEY)
        except Exception:
            logger.debug("Could not access keyring for session restore")
            return
        if stored_refresh:
            logger.info("Found stored refresh token, attempting session restore...")
            new_token = self._do_refresh_token()
            if new_token:
                logger.info("Session restored successfully")

    def _clear_tokens(self) -> None:
        """Clear all local token state and keyring entries."""
        self._access_token = None
        self._api.access_token = None
        self._user_info = None
        try:
            keyring.delete_password(KEYRING_SERVICE_NAME, KEYRING_REFRESH_TOKEN_KEY)
        except Exception:
            pass

    # -- Cleanup --

    def cleanup(self) -> None:
        """Release resources held by the auth service."""
        self._stop_callback_server()


# ---------------------------------------------------------------------------
# PKCE utility functions
# ---------------------------------------------------------------------------


def _generate_code_verifier(length: int = 128) -> str:
    """Generate an OAuth 2.0 PKCE code verifier.

    Args:
        length: Desired length of the verifier (max 128).

    Returns:
        A URL-safe random string of the specified length.
    """
    import secrets

    return secrets.token_urlsafe(length)[:length]


def _generate_code_challenge(verifier: str) -> str:
    """Generate an S256 PKCE code challenge from a verifier.

    Args:
        verifier: The code verifier string.

    Returns:
        Base64url-encoded SHA-256 hash without padding.
    """
    import base64
    import hashlib

    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
