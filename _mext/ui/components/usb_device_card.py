"""USB device card widget.

Displays information about a connected USB device including vendor,
product name, serial number, and storage list. Supports selection
highlighting for MTP interaction.
"""

from __future__ import annotations

from typing import Any, Optional

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    SubtitleLabel,
)
from qtpy.QtCore import Signal
from qtpy.QtWidgets import (
    QVBoxLayout,
    QWidget,
)


class UsbDeviceCard(CardWidget):
    """Card showing USB device information.

    Signals
    -------
    selected()
        Emitted when the card is clicked.
    """

    selected = Signal()

    def __init__(
        self,
        device_info: dict[str, Any],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._info = device_info
        self._is_selected = False
        self.setFixedSize(240, 160)
        self._setup_ui()
        self._populate()

    def _setup_ui(self) -> None:
        """Build the card layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(4)

        self._product_label = SubtitleLabel("", self)
        layout.addWidget(self._product_label)

        self._manufacturer_label = BodyLabel("", self)
        layout.addWidget(self._manufacturer_label)

        self._vid_pid_label = CaptionLabel("", self)
        layout.addWidget(self._vid_pid_label)

        self._serial_label = CaptionLabel("", self)
        layout.addWidget(self._serial_label)

        self._bus_label = CaptionLabel("", self)
        layout.addWidget(self._bus_label)

        layout.addStretch()

    def _populate(self) -> None:
        """Fill card content from device info dictionary."""
        product = self._info.get("product", "Unknown Device")
        manufacturer = self._info.get("manufacturer", "Unknown Manufacturer")
        vid = self._info.get("vendor_id", "????")
        pid = self._info.get("product_id", "????")
        serial = self._info.get("serial_number", "")
        bus = self._info.get("bus", "")
        address = self._info.get("address", "")

        self._product_label.setText(product or "USB 设备")
        self._manufacturer_label.setText(manufacturer or "")
        self._vid_pid_label.setText(f"VID:PID {vid}:{pid}")

        if serial:
            self._serial_label.setText(f"S/N: {serial}")
        else:
            self._serial_label.setText("")

        if bus:
            self._bus_label.setText(f"Bus {bus}, Address {address}")
        else:
            self._bus_label.setText("")

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        """Emit selected signal on click."""
        super().mouseReleaseEvent(event)
        self.selected.emit()

    def set_selected(self, selected: bool) -> None:
        """Update the visual selection state of the card."""
        self._is_selected = selected
        if selected:
            self.setStyleSheet("CardWidget { border: 2px solid #0078d4; }")
        else:
            self.setStyleSheet("")

    @property
    def device_info(self) -> dict[str, Any]:
        """Return the device info dictionary."""
        return self._info

    @property
    def device_id(self) -> str:
        """Return the device identifier string."""
        return self._info.get("device_id", "unknown")
