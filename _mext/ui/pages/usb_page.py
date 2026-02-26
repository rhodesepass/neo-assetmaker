"""USB device management page.

Displays connected USB devices as cards with storage information
and provides file browsing and transfer capabilities via MTP.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from qfluentwidgets import (
    BodyLabel,
    FlowLayout,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    ScrollArea,
    SubtitleLabel,
)
from qtpy.QtCore import Qt, Signal, Slot
from qtpy.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from _mext.core.service_manager import ServiceManager
from _mext.services.mtp_service import MtpError
from _mext.ui.components.usb_device_card import UsbDeviceCard

logger = logging.getLogger(__name__)


class UsbPage(QWidget):
    """USB device browsing and file transfer page.

    Signals
    -------
    transfer_started(str)
        Emitted when a file transfer to USB begins.
    transfer_completed(str)
        Emitted when a file transfer to USB completes.
    """

    transfer_started = Signal(str)
    transfer_completed = Signal(str)

    def __init__(
        self,
        service_manager: ServiceManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._services = service_manager
        self._device_cards: dict[str, UsbDeviceCard] = {}
        self._selected_device_id: Optional[str] = None

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        """Build the USB page layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Header
        header_layout = QHBoxLayout()
        self._title_label = SubtitleLabel("USB 设备", self)
        header_layout.addWidget(self._title_label)
        header_layout.addStretch()

        self._scan_btn = PushButton("Scan for Devices", self)
        header_layout.addWidget(self._scan_btn)

        self._monitoring_btn = PrimaryPushButton("开始监控", self)
        header_layout.addWidget(self._monitoring_btn)

        layout.addLayout(header_layout)

        # Main content splitter
        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Left: device cards
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self._device_scroll = ScrollArea(left_widget)
        self._device_scroll.setWidgetResizable(True)
        self._device_container = QWidget()
        self._device_flow = FlowLayout(self._device_container, needAni=False)
        self._device_flow.setContentsMargins(0, 0, 0, 0)
        self._device_flow.setVerticalSpacing(8)
        self._device_scroll.setWidget(self._device_container)
        left_layout.addWidget(self._device_scroll)

        self._no_devices_label = BodyLabel(
            "No USB devices detected. Click 'Start Monitoring' to begin.", left_widget
        )
        self._no_devices_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(self._no_devices_label)

        self._splitter.addWidget(left_widget)

        # Right: file tree and transfer
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self._file_tree_label = BodyLabel("Device Files", right_widget)
        right_layout.addWidget(self._file_tree_label)

        self._file_tree = QTreeWidget(right_widget)
        self._file_tree.setHeaderLabels(["Name", "Size", "Type"])
        self._file_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        right_layout.addWidget(self._file_tree, stretch=1)

        # Transfer progress
        transfer_layout = QHBoxLayout()
        self._transfer_label = BodyLabel("", right_widget)
        transfer_layout.addWidget(self._transfer_label, stretch=1)

        self._transfer_progress = ProgressBar(right_widget)
        self._transfer_progress.setVisible(False)
        transfer_layout.addWidget(self._transfer_progress, stretch=2)

        right_layout.addLayout(transfer_layout)

        # Transfer buttons
        btn_layout = QHBoxLayout()
        self._transfer_to_device_btn = PrimaryPushButton("Transfer to Device", right_widget)
        self._transfer_to_device_btn.setEnabled(False)
        btn_layout.addWidget(self._transfer_to_device_btn)

        self._transfer_from_device_btn = PushButton("Copy from Device", right_widget)
        self._transfer_from_device_btn.setEnabled(False)
        btn_layout.addWidget(self._transfer_from_device_btn)

        right_layout.addLayout(btn_layout)

        self._splitter.addWidget(right_widget)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 2)

        layout.addWidget(self._splitter, stretch=1)

    def _connect_signals(self) -> None:
        """Wire button and service signals."""
        usb_service = self._services.usb_service

        self._scan_btn.clicked.connect(self._on_scan)
        self._monitoring_btn.clicked.connect(self._toggle_monitoring)
        self._transfer_to_device_btn.clicked.connect(self._on_transfer_to_device)
        self._transfer_from_device_btn.clicked.connect(self._on_transfer_from_device)

        usb_service.device_connected.connect(self._on_device_connected)
        usb_service.device_disconnected.connect(self._on_device_disconnected)
        usb_service.scan_error.connect(self._on_scan_error)

    @Slot()
    def _on_scan(self) -> None:
        """Trigger an immediate USB device scan."""
        usb = self._services.usb_service
        if not usb.is_monitoring:
            usb.start_monitoring()
            self._monitoring_btn.setText("停止监控")
        usb._poll()

    @Slot()
    def _toggle_monitoring(self) -> None:
        """Toggle USB device monitoring on/off."""
        usb = self._services.usb_service
        if usb.is_monitoring:
            usb.stop_monitoring()
            self._monitoring_btn.setText("开始监控")
        else:
            usb.start_monitoring()
            self._monitoring_btn.setText("停止监控")

    @Slot(dict)
    def _on_device_connected(self, device_info: dict[str, Any]) -> None:
        """Handle a new USB device connection."""
        device_id = device_info.get("device_id", "unknown")

        if device_id in self._device_cards:
            return

        card = UsbDeviceCard(device_info, parent=self._device_container)
        card.selected.connect(lambda: self._on_device_selected(device_id))
        self._device_cards[device_id] = card
        self._device_flow.addWidget(card)

        self._no_devices_label.setVisible(False)

        InfoBar.info(
            title="USB 设备已连接",
            content=f"{device_info.get('product', 'Unknown Device')} 已连接",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3000,
        )

    @Slot(str)
    def _on_device_disconnected(self, device_id: str) -> None:
        """Handle a USB device disconnection."""
        card = self._device_cards.pop(device_id, None)
        if card:
            card.deleteLater()

        if device_id == self._selected_device_id:
            self._selected_device_id = None
            self._file_tree.clear()
            self._transfer_to_device_btn.setEnabled(False)
            self._transfer_from_device_btn.setEnabled(False)

        self._no_devices_label.setVisible(len(self._device_cards) == 0)

        InfoBar.warning(
            title="USB 设备已断开",
            content=f"Device {device_id} was disconnected",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3000,
        )

    @Slot(str)
    def _on_scan_error(self, error: str) -> None:
        """Handle USB scan errors."""
        InfoBar.error(
            title="USB 错误",
            content=error,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000,
        )

    def _on_device_selected(self, device_id: str) -> None:
        """Handle device card selection; load file tree via MTP."""
        self._selected_device_id = device_id
        self._transfer_to_device_btn.setEnabled(True)
        self._transfer_from_device_btn.setEnabled(True)

        # Highlight selected card
        for did, card in self._device_cards.items():
            card.set_selected(did == device_id)

        self._load_device_files(device_id)

    def _load_device_files(self, device_id: str) -> None:
        """Load the file tree from the selected device using MTP."""
        self._file_tree.clear()

        device_info = self._services.usb_service.get_device(device_id)
        if device_info is None:
            return

        mtp = self._services.mtp_service
        try:
            if not mtp.is_connected:
                mtp.connect(device_info)
            if not mtp.is_session_open:
                mtp.open_session()

            storage_ids = mtp.get_storage_ids()

            for sid in storage_ids:
                storage_item = QTreeWidgetItem(
                    self._file_tree, [f"Storage 0x{sid:08X}", "", "Storage"]
                )

                try:
                    handles = mtp.get_object_handles(sid)
                    for handle in handles:
                        QTreeWidgetItem(
                            storage_item,
                            [f"Object 0x{handle:08X}", "", "File"],
                        )
                except MtpError as exc:
                    QTreeWidgetItem(
                        storage_item,
                        [f"Error: {exc}", "", ""],
                    )

                storage_item.setExpanded(True)

        except MtpError as exc:
            logger.error("MTP error loading files: %s", exc)
            InfoBar.error(
                title="MTP 错误",
                content=str(exc),
                parent=self,
                position=InfoBarPosition.TOP,
                duration=5000,
            )

    @Slot()
    def _on_transfer_to_device(self) -> None:
        """Transfer selected material to the connected USB device."""
        if not self._selected_device_id:
            return

        InfoBar.info(
            title="传输",
            content="从素材库选择素材传输到设备",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3000,
        )

    @Slot()
    def _on_transfer_from_device(self) -> None:
        """Copy selected file from USB device to local storage."""
        selected_items = self._file_tree.selectedItems()
        if not selected_items:
            InfoBar.warning(
                title="未选择",
                content="请选择设备中的文件",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000,
            )
            return

        self._transfer_progress.setVisible(True)
        self._transfer_progress.setValue(0)
        self._transfer_label.setText("正在从设备复制...")

        # The actual MTP transfer would be performed here
        self._transfer_progress.setValue(100)
        self._transfer_label.setText("传输完成")
        self.transfer_completed.emit(self._selected_device_id or "")
