"""QThread-based workers for FIDO2 registration and authentication.

Runs FIDO2 operations off the main thread so the UI remains responsive.
Emits signals for touch prompts, PIN requests, completion, and errors.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from qtpy.QtCore import QObject, QThread, Signal

from _mext.services.fido2_client import Fido2ClientWrapper

logger = logging.getLogger(__name__)


class Fido2RegisterWorker(QThread):
    """Worker thread for FIDO2 credential registration.

    Signals
    -------
    touch_required()
        The authenticator is waiting for user presence.
    pin_required(int)
        A PIN is needed; int is a hint for remaining retries.
    completed(dict)
        Registration succeeded. Payload is the attestation response.
    error(str)
        Registration failed. Payload is the error message.
    """

    touch_required = Signal()
    pin_required = Signal(int)
    completed = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        fido2_client: Fido2ClientWrapper,
        creation_options: dict[str, Any],
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._fido2 = fido2_client
        self._options = creation_options
        self._pin_value: Optional[str] = None

        # Wire interaction signals to our forwarding signals
        interaction = self._fido2.interaction
        interaction.touch_required.connect(self.touch_required.emit)
        interaction.pin_required.connect(self.pin_required.emit)

    def provide_pin(self, pin: str) -> None:
        """Provide the PIN entered by the user (called from UI thread)."""
        self._pin_value = pin
        self._fido2.interaction.pin_provided.emit(pin)

    def run(self) -> None:
        """Execute FIDO2 registration in the background."""
        try:
            logger.info("Starting FIDO2 registration...")
            result = self._fido2.make_credential(self._options)
            logger.info("FIDO2 registration completed successfully")
            self.completed.emit(result)
        except RuntimeError as exc:
            logger.error("FIDO2 registration error: %s", exc)
            self.error.emit(str(exc))
        except Exception as exc:
            logger.error("Unexpected FIDO2 registration error: %s", exc)
            self.error.emit(f"Registration failed: {exc}")


class Fido2AuthWorker(QThread):
    """Worker thread for FIDO2 assertion (authentication).

    Signals
    -------
    touch_required()
        The authenticator is waiting for user presence.
    pin_required(int)
        A PIN is needed; int is a hint for remaining retries.
    completed(dict)
        Authentication succeeded. Payload is the assertion response.
    error(str)
        Authentication failed. Payload is the error message.
    """

    touch_required = Signal()
    pin_required = Signal(int)
    completed = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        fido2_client: Fido2ClientWrapper,
        request_options: dict[str, Any],
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._fido2 = fido2_client
        self._options = request_options
        self._pin_value: Optional[str] = None

        # Wire interaction signals
        interaction = self._fido2.interaction
        interaction.touch_required.connect(self.touch_required.emit)
        interaction.pin_required.connect(self.pin_required.emit)

    def provide_pin(self, pin: str) -> None:
        """Provide the PIN entered by the user (called from UI thread)."""
        self._pin_value = pin
        self._fido2.interaction.pin_provided.emit(pin)

    def run(self) -> None:
        """Execute FIDO2 authentication in the background."""
        try:
            logger.info("Starting FIDO2 authentication...")
            result = self._fido2.get_assertion(self._options)
            logger.info("FIDO2 authentication completed successfully")
            self.completed.emit(result)
        except RuntimeError as exc:
            logger.error("FIDO2 authentication error: %s", exc)
            self.error.emit(str(exc))
        except Exception as exc:
            logger.error("Unexpected FIDO2 authentication error: %s", exc)
            self.error.emit(f"Authentication failed: {exc}")
