"""USB device monitoring service using pyusb with QTimer polling.

Detects USB device connect/disconnect events by polling at a configurable
interval (default 2 seconds). Emits Qt signals when changes are detected.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from qtpy.QtCore import QObject, QTimer, Signal, Slot

from _mext.core.constants import USB_POLL_INTERVAL_MS
from _mext.services.api_worker import UsbScanWorker

logger = logging.getLogger(__name__)


def _device_id(dev: Any) -> str:
    """Generate a unique string identifier for a USB device."""
    return f"{dev.idVendor:04x}:{dev.idProduct:04x}:{dev.bus}:{dev.address}"


def _device_info(dev: Any) -> dict[str, Any]:
    """Extract device information into a plain dictionary."""
    info: dict[str, Any] = {
        "device_id": _device_id(dev),
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

    return info


class UsbService(QObject):
    """Monitors USB device connections using periodic polling.

    Signals
    -------
    device_connected(dict)
        Emitted when a new USB device is detected. Payload is device info dict.
    device_disconnected(str)
        Emitted when a USB device is removed. Payload is the device_id string.
    scan_error(str)
        Emitted when device enumeration encounters an error.
    """

    device_connected = Signal(dict)
    device_disconnected = Signal(str)
    scan_error = Signal(str)

    def __init__(
        self,
        poll_interval_ms: int = USB_POLL_INTERVAL_MS,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._poll_interval = poll_interval_ms
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

        # Known devices keyed by device_id
        self._known_devices: dict[str, dict[str, Any]] = {}
        self._is_monitoring = False
        self._scan_worker: Optional[UsbScanWorker] = None

    @property
    def is_monitoring(self) -> bool:
        """Return True if USB polling is active."""
        return self._is_monitoring

    def start_monitoring(self) -> None:
        """Start periodic USB device scanning."""
        if self._is_monitoring:
            return

        self._is_monitoring = True
        # Do an initial scan immediately
        self._poll()
        self._timer.start(self._poll_interval)
        logger.info("USB monitoring started (interval=%dms)", self._poll_interval)

    def stop_monitoring(self) -> None:
        """Stop periodic USB device scanning."""
        self._timer.stop()
        self._is_monitoring = False
        logger.info("USB monitoring stopped")

    def get_devices(self) -> list[dict[str, Any]]:
        """Return a list of currently known USB device info dictionaries."""
        return list(self._known_devices.values())

    def get_device(self, device_id: str) -> Optional[dict[str, Any]]:
        """Return info for a specific device, or None if not found."""
        return self._known_devices.get(device_id)

    def _poll(self) -> None:
        """Launch a background scan for USB devices."""
        if self._scan_worker is not None and self._scan_worker.isRunning():
            return  # Previous scan still running, skip this tick

        self._scan_worker = UsbScanWorker(parent=self)
        self._scan_worker.completed.connect(self._on_scan_result)
        self._scan_worker.error.connect(self._on_scan_error)
        self._scan_worker.start()

    @Slot(dict)
    def _on_scan_result(self, current_devices: dict) -> None:
        """Process scan results from the background worker."""
        # Detect new devices
        for did, info in current_devices.items():
            if did not in self._known_devices:
                logger.info("USB device connected: %s (%s)", did, info.get("product", ""))
                self.device_connected.emit(info)

        # Detect removed devices
        for did in list(self._known_devices.keys()):
            if did not in current_devices:
                logger.info("USB device disconnected: %s", did)
                self.device_disconnected.emit(did)

        self._known_devices = current_devices

    @Slot(str)
    def _on_scan_error(self, error_msg: str) -> None:
        """Handle scan worker errors."""
        if "not available" in error_msg.lower() or "not installed" in error_msg.lower():
            logger.warning("USB scan unavailable: %s", error_msg)
            self.stop_monitoring()
        else:
            logger.error("USB scan error: %s", error_msg)
        self.scan_error.emit(error_msg)
