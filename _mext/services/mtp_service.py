"""MTP (Media Transfer Protocol) implementation using pyusb bulk transfers.

Implements the MTP container format with a 12-byte header and provides
operations for session management, storage enumeration, and object
transfer. Designed for interaction with Electric Pass devices using
custom storage IDs (0xFFFF0001 - 0xFFFF0006).
"""

from __future__ import annotations

import logging
import struct
from typing import Any, Optional

from _mext.core.constants import (
    ELECTRIC_PASS_STORAGE_IDS,
    MTP_CONTAINER_HEADER_SIZE,
    MTP_SESSION_ID,
)

logger = logging.getLogger(__name__)

# MTP Operation Codes
MTP_OP_GET_DEVICE_INFO = 0x1001
MTP_OP_OPEN_SESSION = 0x1002
MTP_OP_CLOSE_SESSION = 0x1003
MTP_OP_GET_STORAGE_IDS = 0x1004
MTP_OP_GET_STORAGE_INFO = 0x1005
MTP_OP_GET_NUM_OBJECTS = 0x1006
MTP_OP_GET_OBJECT_HANDLES = 0x1007
MTP_OP_GET_OBJECT_INFO = 0x1008
MTP_OP_GET_OBJECT = 0x1009
MTP_OP_SEND_OBJECT_INFO = 0x100C
MTP_OP_SEND_OBJECT = 0x100D
MTP_OP_DELETE_OBJECT = 0x100B

# MTP Container Types
MTP_CONTAINER_COMMAND = 1
MTP_CONTAINER_DATA = 2
MTP_CONTAINER_RESPONSE = 3
MTP_CONTAINER_EVENT = 4

# MTP Response Codes
MTP_RESP_OK = 0x2001
MTP_RESP_SESSION_ALREADY_OPEN = 0x201E
MTP_RESP_INVALID_OBJECT_HANDLE = 0x2009

# USB endpoint constants
MTP_USB_CLASS = 6  # Still Image class
MTP_BULK_OUT_EP = 0x01
MTP_BULK_IN_EP = 0x81
MTP_INTERRUPT_EP = 0x83
MTP_TIMEOUT_MS = 5000


class MtpError(Exception):
    """Raised when an MTP operation fails."""

    def __init__(self, message: str, response_code: int = 0) -> None:
        self.response_code = response_code
        super().__init__(message)


def _build_container(
    container_type: int,
    operation_code: int,
    transaction_id: int,
    params: Optional[list[int]] = None,
    data: Optional[bytes] = None,
) -> bytes:
    """Build an MTP container with the standard 12-byte header.

    Header format (little-endian):
        uint32  container_length
        uint16  container_type
        uint16  operation_code
        uint32  transaction_id
        [uint32  param1, param2, ...]  (for command containers)
        [bytes   data]                 (for data containers)
    """
    params = params or []
    param_bytes = b"".join(struct.pack("<I", p) for p in params)
    payload = param_bytes + (data or b"")
    length = MTP_CONTAINER_HEADER_SIZE + len(payload)

    header = struct.pack(
        "<IHHI",
        length,
        container_type,
        operation_code,
        transaction_id,
    )
    return header + payload


def _parse_container(raw: bytes) -> dict[str, Any]:
    """Parse an MTP container from raw bytes.

    Returns a dict with keys: length, type, code, transaction_id, payload.
    """
    if len(raw) < MTP_CONTAINER_HEADER_SIZE:
        raise MtpError(f"Container too short: {len(raw)} bytes")

    length, ctype, code, tid = struct.unpack("<IHHI", raw[:MTP_CONTAINER_HEADER_SIZE])
    payload = raw[MTP_CONTAINER_HEADER_SIZE:length] if length > MTP_CONTAINER_HEADER_SIZE else b""

    return {
        "length": length,
        "type": ctype,
        "code": code,
        "transaction_id": tid,
        "payload": payload,
    }


def _parse_uint32_array(data: bytes) -> list[int]:
    """Parse a sequence of little-endian uint32 values prefixed by a count."""
    if len(data) < 4:
        return []
    count = struct.unpack("<I", data[:4])[0]
    values = []
    offset = 4
    for _ in range(count):
        if offset + 4 > len(data):
            break
        values.append(struct.unpack("<I", data[offset : offset + 4])[0])
        offset += 4
    return values


class MtpService:
    """MTP protocol client using pyusb bulk transfers.

    Usage::

        mtp = MtpService()
        mtp.connect(device_info)
        mtp.open_session()
        storage_ids = mtp.get_storage_ids()
        handles = mtp.get_object_handles(storage_ids[0])
        data = mtp.get_object(handles[0])
        mtp.close_session()
        mtp.disconnect()
    """

    def __init__(self) -> None:
        self._device: Any = None
        self._endpoint_out: Any = None
        self._endpoint_in: Any = None
        self._endpoint_interrupt: Any = None
        self._session_id: int = MTP_SESSION_ID
        self._transaction_id: int = 0
        self._is_session_open: bool = False

    @property
    def is_connected(self) -> bool:
        """Return True if a USB device is currently connected."""
        return self._device is not None

    @property
    def is_session_open(self) -> bool:
        """Return True if an MTP session is currently open."""
        return self._is_session_open

    def _next_transaction_id(self) -> int:
        """Return the next transaction ID and increment the counter."""
        self._transaction_id += 1
        return self._transaction_id

    def connect(self, device_info: dict[str, Any]) -> None:
        """Connect to a USB device and claim the MTP interface.

        Parameters
        ----------
        device_info : dict
            Device info dict from UsbService, must contain vendor_id and product_id.
        """
        import usb.core
        import usb.util

        vendor_id = int(device_info["vendor_id"], 16)
        product_id = int(device_info["product_id"], 16)

        dev = usb.core.find(idVendor=vendor_id, idProduct=product_id)
        if dev is None:
            raise MtpError(
                f"USB device {device_info['vendor_id']}:{device_info['product_id']} not found"
            )

        # Detach kernel driver if needed
        try:
            if dev.is_kernel_driver_active(0):
                dev.detach_kernel_driver(0)
        except Exception:
            pass

        dev.set_configuration()

        # Find MTP interface and endpoints
        cfg = dev.get_active_configuration()
        interface = None
        for intf in cfg:
            if intf.bInterfaceClass == MTP_USB_CLASS:
                interface = intf
                break

        if interface is None:
            # Fallback: use first interface
            interface = cfg[(0, 0)]

        self._endpoint_out = usb.util.find_descriptor(
            interface,
            custom_match=lambda e: (
                usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
            ),
        )
        self._endpoint_in = usb.util.find_descriptor(
            interface,
            custom_match=lambda e: (
                usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN
                and usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK
            ),
        )
        self._endpoint_interrupt = usb.util.find_descriptor(
            interface,
            custom_match=lambda e: (
                usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN
                and usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_INTR
            ),
        )

        if self._endpoint_out is None or self._endpoint_in is None:
            raise MtpError("Could not find required bulk endpoints on device")

        self._device = dev
        self._transaction_id = 0
        logger.info("MTP connected to %s:%s", device_info["vendor_id"], device_info["product_id"])

    def disconnect(self) -> None:
        """Release the USB device."""
        if self._device is not None:
            import usb.util

            try:
                usb.util.dispose_resources(self._device)
            except Exception:
                pass
            self._device = None
            self._endpoint_out = None
            self._endpoint_in = None
            self._endpoint_interrupt = None
            self._is_session_open = False
            logger.info("MTP disconnected")

    def _send(self, data: bytes) -> None:
        """Write data to the bulk OUT endpoint."""
        if self._endpoint_out is None:
            raise MtpError("Not connected to a device")
        self._endpoint_out.write(data, timeout=MTP_TIMEOUT_MS)

    def _receive(self, max_size: int = 65536) -> bytes:
        """Read data from the bulk IN endpoint."""
        if self._endpoint_in is None:
            raise MtpError("Not connected to a device")
        raw = self._endpoint_in.read(max_size, timeout=MTP_TIMEOUT_MS)
        return bytes(raw)

    def _send_command(
        self,
        operation_code: int,
        params: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        """Send an MTP command and return the response container.

        For operations that return data, this returns the data container.
        The response container is consumed internally.
        """
        tid = self._next_transaction_id()
        cmd = _build_container(MTP_CONTAINER_COMMAND, operation_code, tid, params)
        self._send(cmd)

        # Read response (could be data or response)
        raw = self._receive()
        container = _parse_container(raw)

        if container["type"] == MTP_CONTAINER_DATA:
            # There should be a response following the data
            data_payload = container["payload"]
            resp_raw = self._receive()
            resp = _parse_container(resp_raw)
            if resp["code"] != MTP_RESP_OK:
                raise MtpError(
                    f"MTP operation 0x{operation_code:04X} failed with "
                    f"response 0x{resp['code']:04X}",
                    response_code=resp["code"],
                )
            container["payload"] = data_payload
            return container

        if container["type"] == MTP_CONTAINER_RESPONSE:
            if container["code"] not in (MTP_RESP_OK, MTP_RESP_SESSION_ALREADY_OPEN):
                raise MtpError(
                    f"MTP operation 0x{operation_code:04X} failed with "
                    f"response 0x{container['code']:04X}",
                    response_code=container["code"],
                )
            return container

        raise MtpError(f"Unexpected container type: {container['type']}")

    # -- MTP Operations --

    def open_session(self) -> None:
        """Open an MTP session with the device."""
        if not self.is_connected:
            raise MtpError("Not connected to a device")

        self._send_command(MTP_OP_OPEN_SESSION, [self._session_id])
        self._is_session_open = True
        logger.info("MTP session opened (id=%d)", self._session_id)

    def close_session(self) -> None:
        """Close the current MTP session."""
        if not self._is_session_open:
            return

        try:
            self._send_command(MTP_OP_CLOSE_SESSION)
        except MtpError:
            pass
        self._is_session_open = False
        logger.info("MTP session closed")

    def get_storage_ids(self) -> list[int]:
        """Return a list of storage IDs available on the device."""
        if not self._is_session_open:
            raise MtpError("Session not open")

        container = self._send_command(MTP_OP_GET_STORAGE_IDS)
        return _parse_uint32_array(container.get("payload", b""))

    def get_object_handles(
        self,
        storage_id: int,
        object_format: int = 0,
        parent_handle: int = 0xFFFFFFFF,
    ) -> list[int]:
        """Return a list of object handles in a storage.

        Parameters
        ----------
        storage_id : int
            The MTP storage ID to enumerate.
        object_format : int
            Filter by object format (0 = all formats).
        parent_handle : int
            Parent object handle (0xFFFFFFFF = root).
        """
        if not self._is_session_open:
            raise MtpError("Session not open")

        container = self._send_command(
            MTP_OP_GET_OBJECT_HANDLES,
            [storage_id, object_format, parent_handle],
        )
        return _parse_uint32_array(container.get("payload", b""))

    def get_object(self, object_handle: int) -> bytes:
        """Download an object from the device.

        Parameters
        ----------
        object_handle : int
            The MTP object handle to retrieve.

        Returns
        -------
        bytes
            The raw object data.
        """
        if not self._is_session_open:
            raise MtpError("Session not open")

        container = self._send_command(MTP_OP_GET_OBJECT, [object_handle])
        return container.get("payload", b"")

    def send_object(
        self,
        storage_id: int,
        filename: str,
        data: bytes,
        parent_handle: int = 0,
    ) -> int:
        """Upload an object to the device.

        Parameters
        ----------
        storage_id : int
            Target storage ID.
        filename : str
            Object filename.
        data : bytes
            Raw object data.
        parent_handle : int
            Parent folder handle (0 = root).

        Returns
        -------
        int
            The new object handle assigned by the device.
        """
        if not self._is_session_open:
            raise MtpError("Session not open")

        # Send ObjectInfo first
        object_info = self._build_object_info(
            storage_id=storage_id,
            filename=filename,
            file_size=len(data),
            parent_handle=parent_handle,
        )

        tid = self._next_transaction_id()
        cmd = _build_container(
            MTP_CONTAINER_COMMAND,
            MTP_OP_SEND_OBJECT_INFO,
            tid,
            [storage_id, parent_handle],
        )
        self._send(cmd)

        # Send object info data
        info_data = _build_container(
            MTP_CONTAINER_DATA,
            MTP_OP_SEND_OBJECT_INFO,
            tid,
            data=object_info,
        )
        self._send(info_data)

        # Read response
        resp_raw = self._receive()
        resp = _parse_container(resp_raw)
        if resp["code"] != MTP_RESP_OK:
            raise MtpError(
                f"SendObjectInfo failed: 0x{resp['code']:04X}",
                response_code=resp["code"],
            )

        # Extract new object handle from response params
        new_handle = 0
        if len(resp["payload"]) >= 12:
            _, _, new_handle = struct.unpack("<III", resp["payload"][:12])

        # Now send the actual object data
        tid2 = self._next_transaction_id()
        cmd2 = _build_container(MTP_CONTAINER_COMMAND, MTP_OP_SEND_OBJECT, tid2)
        self._send(cmd2)

        obj_container = _build_container(
            MTP_CONTAINER_DATA,
            MTP_OP_SEND_OBJECT,
            tid2,
            data=data,
        )
        self._send(obj_container)

        resp_raw2 = self._receive()
        resp2 = _parse_container(resp_raw2)
        if resp2["code"] != MTP_RESP_OK:
            raise MtpError(
                f"SendObject failed: 0x{resp2['code']:04X}",
                response_code=resp2["code"],
            )

        logger.info("Object sent: %s (handle=%d)", filename, new_handle)
        return new_handle

    def get_electric_pass_storage_ids(self) -> dict[str, int]:
        """Return the Electric Pass custom storage ID mapping."""
        return dict(ELECTRIC_PASS_STORAGE_IDS)

    @staticmethod
    def _build_object_info(
        storage_id: int,
        filename: str,
        file_size: int,
        parent_handle: int = 0,
    ) -> bytes:
        """Build an MTP ObjectInfo dataset.

        This is a simplified version; a full implementation would include
        all MTP ObjectInfo fields.
        """
        # Encode filename as UTF-16LE with length prefix
        encoded_name = filename.encode("utf-16-le")
        name_len = len(filename) + 1  # Include null terminator

        # Minimal ObjectInfo structure
        info = struct.pack(
            "<IHHIIIIIHB",
            storage_id,  # StorageID
            0x3000,  # ObjectFormat (undefined)
            0x0000,  # ProtectionStatus
            file_size,  # ObjectCompressedSize
            0x0000,  # ThumbFormat
            0,  # ThumbCompressedSize
            0,  # ThumbPixWidth
            0,  # ThumbPixHeight
            0,  # ImagePixWidth
            name_len,  # Filename string length
        )
        info += encoded_name + b"\x00\x00"  # Null-terminated UTF-16
        return info
