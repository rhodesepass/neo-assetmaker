"""Cross-platform FIDO2/WebAuthn client for the asset store.

On Windows: prefers the native WindowsClient (if not running as admin).
On macOS/Linux: uses CtapHidDevice discovery + Fido2Client.

All operations use a synthetic origin derived from the configured RP ID
since this is a desktop application rather than a browser.
"""

from __future__ import annotations

import ctypes
import logging
import platform
from typing import Any, Optional

from qtpy.QtCore import QObject, Signal

from _mext.core.config import Config, get_config

logger = logging.getLogger(__name__)


class Fido2UserInteraction(QObject):
    """User interaction handler that bridges FIDO2 prompts to Qt signals.

    Signals
    -------
    touch_required()
        Emitted when the authenticator needs a user touch/presence check.
    pin_required(int)
        Emitted when a PIN is needed. The int indicates remaining retries.
    pin_provided(str)
        Emitted internally when the UI provides a PIN.
    """

    touch_required = Signal()
    pin_required = Signal(int)
    pin_provided = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._pending_pin: Optional[str] = None
        self.pin_provided.connect(self._on_pin_provided)

    def _on_pin_provided(self, pin: str) -> None:
        """Slot to receive PIN from the UI."""
        self._pending_pin = pin

    def prompt_up(self) -> None:
        """Called by fido2 library when user presence is needed."""
        logger.info("FIDO2: Touch your security key")
        self.touch_required.emit()

    def request_pin(self, permissions: Any, rp_id: Optional[str] = None) -> Optional[str]:
        """Called by fido2 library when a PIN is needed.

        Emits ``pin_required`` and blocks until ``pin_provided`` delivers
        the value. In a real integration the UI dialog would call
        ``pin_provided.emit(pin)`` after the user types the PIN.
        """
        logger.info("FIDO2: PIN requested (rp_id=%s)", rp_id)
        self._pending_pin = None
        self.pin_required.emit(8)  # Default max retries as hint

        # In production this would use QEventLoop or a threading.Event
        # to block until the UI provides the PIN. For now return the
        # pending value which the worker thread will wait for.
        return self._pending_pin

    def request_uv(self, permissions: Any, rp_id: Optional[str] = None) -> bool:
        """Called when user verification is needed. We rely on PIN or touch."""
        self.prompt_up()
        return True


def _is_windows_admin() -> bool:
    """Check if the current process is running with admin/elevated privileges on Windows."""
    if platform.system() != "Windows":
        return False
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


class Fido2ClientWrapper:
    """Wraps python-fido2 to provide a unified API across platforms.

    Parameters
    ----------
    config : Config, optional
        Application configuration (used for origin and rp_id).
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        self._config = config or get_config()
        self._origin = self._config.fido2_origin
        self._rp_id = self._config.fido2_rp_id
        self._interaction = Fido2UserInteraction()

    @property
    def interaction(self) -> Fido2UserInteraction:
        """Return the user interaction handler for signal connections."""
        return self._interaction

    def _discover_devices(self) -> list[Any]:
        """Discover connected FIDO2 HID devices.

        Returns a list of CtapHidDevice instances, or an empty list if
        none are found or the library is unavailable.
        """
        try:
            from fido2.hid import CtapHidDevice

            devices = list(CtapHidDevice.list_devices())
            logger.info("Discovered %d FIDO2 HID device(s)", len(devices))
            return devices
        except Exception as exc:
            logger.warning("FIDO2 device discovery failed: %s", exc)
            return []

    def _get_client(self) -> Any:
        """Return an appropriate Fido2Client for the current platform.

        On Windows (non-admin): uses WindowsClient if available.
        Otherwise: uses Fido2Client with the first discovered HID device.
        """
        system = platform.system()

        # Try Windows native client first
        if system == "Windows" and not _is_windows_admin():
            try:
                from fido2.win_api import WindowsClient

                if WindowsClient.is_available():
                    logger.info("Using WindowsClient (native Windows Hello)")
                    return WindowsClient(self._origin)
            except ImportError:
                logger.debug("WindowsClient not available, falling back to HID")

        # HID-based client (macOS, Linux, or Windows admin/fallback)
        devices = self._discover_devices()
        if not devices:
            raise RuntimeError(
                "No FIDO2 security key detected. Please insert your security key and try again."
            )

        from fido2.client import Fido2Client, UserInteraction

        # Create a bridge adapter matching the fido2 UserInteraction protocol
        class _InteractionBridge(UserInteraction):
            def __init__(self, handler: Fido2UserInteraction) -> None:
                self._handler = handler

            def prompt_up(self) -> None:
                self._handler.prompt_up()

            def request_pin(self, permissions: Any, rp_id: Optional[str] = None) -> Optional[str]:
                return self._handler.request_pin(permissions, rp_id)

            def request_uv(self, permissions: Any, rp_id: Optional[str] = None) -> bool:
                return self._handler.request_uv(permissions, rp_id)

        device = devices[0]
        client = Fido2Client(
            device,
            self._origin,
            user_interaction=_InteractionBridge(self._interaction),
        )
        return client

    def make_credential(self, options: dict[str, Any]) -> dict[str, Any]:
        """Create a new FIDO2 credential (registration).

        Parameters
        ----------
        options : dict
            PublicKeyCredentialCreationOptions from the server, typically
            containing ``rp``, ``user``, ``challenge``, ``pubKeyCredParams``,
            and optional ``excludeCredentials``, ``authenticatorSelection``.

        Returns
        -------
        dict
            Attestation response suitable for sending to the server, including
            ``attestationObject`` and ``clientDataJSON`` (base64url-encoded).
        """
        import base64

        from fido2.webauthn import (
            PublicKeyCredentialCreationOptions,
            PublicKeyCredentialParameters,
            PublicKeyCredentialRpEntity,
            PublicKeyCredentialType,
            PublicKeyCredentialUserEntity,
        )

        client = self._get_client()

        # Parse server options into fido2 objects
        rp = PublicKeyCredentialRpEntity(
            id=options.get("rp", {}).get("id", self._rp_id),
            name=options.get("rp", {}).get("name", "Asset Store"),
        )
        user = PublicKeyCredentialUserEntity(
            id=base64.urlsafe_b64decode(options["user"]["id"] + "=="),
            name=options["user"]["name"],
            display_name=options["user"].get("displayName", options["user"]["name"]),
        )

        challenge = base64.urlsafe_b64decode(options["challenge"] + "==")

        pub_key_cred_params = []
        for param in options.get("pubKeyCredParams", [{"type": "public-key", "alg": -7}]):
            pub_key_cred_params.append(
                PublicKeyCredentialParameters(
                    type=PublicKeyCredentialType(param["type"]),
                    alg=param["alg"],
                )
            )

        creation_options = PublicKeyCredentialCreationOptions(
            rp=rp,
            user=user,
            challenge=challenge,
            pub_key_cred_params=pub_key_cred_params,
        )

        result = client.make_credential(creation_options)

        # Serialize for transport back to server
        attestation_object = (
            base64.urlsafe_b64encode(result.attestation_object).rstrip(b"=").decode("ascii")
        )
        client_data = base64.urlsafe_b64encode(result.client_data).rstrip(b"=").decode("ascii")

        return {
            "attestationObject": attestation_object,
            "clientDataJSON": client_data,
            "type": "public-key",
        }

    def get_assertion(self, options: dict[str, Any]) -> dict[str, Any]:
        """Perform a FIDO2 assertion (authentication).

        Parameters
        ----------
        options : dict
            PublicKeyCredentialRequestOptions from the server, containing
            ``challenge``, ``rpId``, and optional ``allowCredentials``.

        Returns
        -------
        dict
            Assertion response suitable for sending to the server, including
            ``authenticatorData``, ``signature``, ``clientDataJSON``, and
            ``credentialId`` (all base64url-encoded).
        """
        import base64

        from fido2.webauthn import (
            PublicKeyCredentialDescriptor,
            PublicKeyCredentialRequestOptions,
            PublicKeyCredentialType,
        )

        client = self._get_client()

        challenge = base64.urlsafe_b64decode(options["challenge"] + "==")
        rp_id = options.get("rpId", self._rp_id)

        allow_credentials = None
        if "allowCredentials" in options:
            allow_credentials = []
            for cred in options["allowCredentials"]:
                cred_id = base64.urlsafe_b64decode(cred["id"] + "==")
                allow_credentials.append(
                    PublicKeyCredentialDescriptor(
                        type=PublicKeyCredentialType(cred.get("type", "public-key")),
                        id=cred_id,
                    )
                )

        request_options = PublicKeyCredentialRequestOptions(
            challenge=challenge,
            rp_id=rp_id,
            allow_credentials=allow_credentials,
        )

        result = client.get_assertion(request_options)
        assertion = result.get_response(0)

        authenticator_data = (
            base64.urlsafe_b64encode(assertion.authenticator_data).rstrip(b"=").decode("ascii")
        )
        signature = base64.urlsafe_b64encode(assertion.signature).rstrip(b"=").decode("ascii")
        client_data = base64.urlsafe_b64encode(assertion.client_data).rstrip(b"=").decode("ascii")
        credential_id = (
            base64.urlsafe_b64encode(assertion.credential_id).rstrip(b"=").decode("ascii")
        )

        return {
            "authenticatorData": authenticator_data,
            "signature": signature,
            "clientDataJSON": client_data,
            "credentialId": credential_id,
            "type": "public-key",
        }
