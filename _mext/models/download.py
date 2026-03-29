"""Download task data model for tracking file download state.

Each download is represented as a DownloadTask with progress, status,
file paths, and error information.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class DownloadStatus(str, Enum):
    """Status of a download task."""

    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_active(self) -> bool:
        """Return True if the download is currently active or waiting."""
        return self in (DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING)

    @property
    def is_terminal(self) -> bool:
        """Return True if the download has reached a final state."""
        return self in (
            DownloadStatus.COMPLETED,
            DownloadStatus.FAILED,
            DownloadStatus.CANCELLED,
        )

    @property
    def display_name(self) -> str:
        """Return a human-readable status label."""
        names = {
            "queued": "Queued",
            "downloading": "Downloading",
            "paused": "Paused",
            "completed": "Completed",
            "failed": "Failed",
            "cancelled": "Cancelled",
        }
        return names.get(self.value, self.value.title())


@dataclass
class DownloadTask:
    """Tracks the state of a single file download.

    Attributes
    ----------
    id : str
        Unique task identifier (UUID).
    material_id : str
        The material this download is associated with.
    status : DownloadStatus
        Current status of the download.
    progress : int
        Number of bytes downloaded so far.
    total_size : int
        Expected total size in bytes (0 if unknown).
    file_path : str
        Final destination file path.
    temp_path : str
        Temporary file path used during download.
    download_url : str
        URL being downloaded from.
    expected_hash : str, optional
        Expected SHA-256 hash for verification.
    error : str, optional
        Error message if the download failed.
    started_at : datetime, optional
        Timestamp when the download began.
    completed_at : datetime, optional
        Timestamp when the download finished.
    """

    id: str
    material_id: str
    material_name: str = ""
    status: DownloadStatus = DownloadStatus.QUEUED
    progress: int = 0
    total_size: int = 0
    file_path: str = ""
    temp_path: str = ""
    download_url: str = ""
    expected_hash: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def progress_percent(self) -> float:
        """Return download progress as a percentage (0.0 - 100.0)."""
        if self.total_size <= 0:
            return 0.0
        return min(100.0, (self.progress / self.total_size) * 100.0)

    @property
    def progress_display(self) -> str:
        """Return a human-readable progress string."""
        downloaded = _format_bytes(self.progress)
        if self.total_size > 0:
            total = _format_bytes(self.total_size)
            return f"{downloaded} / {total} ({self.progress_percent:.1f}%)"
        return downloaded

    @property
    def speed_display(self) -> str:
        """Return estimated download speed (requires external tracking)."""
        # Speed calculation would be done by the engine/UI; this is a placeholder
        return ""

    def mark_started(self) -> None:
        """Update the task when download begins."""
        self.status = DownloadStatus.DOWNLOADING
        self.started_at = datetime.now()

    def mark_completed(self, file_path: str) -> None:
        """Update the task when download completes successfully."""
        self.status = DownloadStatus.COMPLETED
        self.file_path = file_path
        self.completed_at = datetime.now()
        self.progress = self.total_size

    def mark_failed(self, error_message: str) -> None:
        """Update the task when download fails."""
        self.status = DownloadStatus.FAILED
        self.error = error_message
        self.completed_at = datetime.now()

    @classmethod
    def from_dict(cls, data: dict) -> DownloadTask:
        """Create a DownloadTask from a dictionary."""
        status = data.get("status", "queued")
        if isinstance(status, str):
            try:
                status = DownloadStatus(status)
            except ValueError:
                status = DownloadStatus.QUEUED

        return cls(
            id=data.get("id", ""),
            material_id=data.get("material_id", ""),
            material_name=data.get("material_name", ""),
            status=status,
            progress=data.get("progress", 0),
            total_size=data.get("total_size", 0),
            file_path=data.get("file_path", ""),
            temp_path=data.get("temp_path", ""),
            download_url=data.get("download_url", ""),
            expected_hash=data.get("expected_hash"),
            error=data.get("error"),
        )

    def to_dict(self) -> dict:
        """Serialize to a dictionary."""
        return {
            "id": self.id,
            "material_id": self.material_id,
            "material_name": self.material_name,
            "status": self.status.value,
            "progress": self.progress,
            "total_size": self.total_size,
            "file_path": self.file_path,
            "temp_path": self.temp_path,
            "download_url": self.download_url,
            "expected_hash": self.expected_hash,
            "error": self.error,
        }


def _format_bytes(size: int) -> str:
    """Format a byte count as a human-readable string."""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.2f} GB"
