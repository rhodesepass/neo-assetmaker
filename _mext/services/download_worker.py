"""QRunnable-based download worker for streaming file downloads.

Supports resume via HTTP Range headers, pause/cancel via threading events,
SHA-256 hash verification, and atomic file writes (.tmp -> rename).
"""

from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path
from typing import Optional

from qtpy.QtCore import QObject, QRunnable, Signal

from _mext.core.constants import DOWNLOAD_CHUNK_SIZE
from _mext.services.api_client import ApiClient

logger = logging.getLogger(__name__)


class DownloadWorkerSignals(QObject):
    """Signals emitted by DownloadWorker.

    These are on a separate QObject because QRunnable cannot directly
    define signals (it does not inherit QObject).
    """

    started = Signal(str)
    progress = Signal(str, int, int)
    completed = Signal(str, str)
    failed = Signal(str, str)


class DownloadWorker(QRunnable):
    """Runnable that downloads a single file with progress reporting.

    Supports:
    - Resume: sends Range header based on existing .tmp file size.
    - Pause: blocks on a threading.Event until resumed.
    - Cancel: sets a cancel flag and stops writing.
    - Hash verification: computes SHA-256 of the final file.

    Parameters
    ----------
    task_id : str
        Unique identifier for this download task.
    url : str
        URL to download from.
    temp_path : Path
        Temporary file path to write to during download.
    final_path : Path
        Destination file path after download completes.
    api_client : ApiClient
        HTTP client for making the download request.
    expected_hash : str, optional
        Expected SHA-256 hex digest for verification.
    chunk_size : int
        Size of each read chunk in bytes.
    """

    def __init__(
        self,
        task_id: str,
        url: str,
        temp_path: Path,
        final_path: Path,
        api_client: ApiClient,
        expected_hash: Optional[str] = None,
        chunk_size: int = DOWNLOAD_CHUNK_SIZE,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)

        self.task_id = task_id
        self.url = url
        self.temp_path = Path(temp_path)
        self.final_path = Path(final_path)
        self.api_client = api_client
        self.expected_hash = expected_hash
        self.chunk_size = chunk_size

        self.signals = DownloadWorkerSignals()

        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused by default
        self._cancelled = threading.Event()
        self._resume_offset = 0

    def pause(self) -> None:
        """Pause the download. The worker will block until resume() is called."""
        self._pause_event.clear()
        logger.debug("Download %s paused", self.task_id)

    def resume(self) -> None:
        """Resume a paused download."""
        self._pause_event.set()
        logger.debug("Download %s resumed", self.task_id)

    def cancel(self) -> None:
        """Cancel the download. The worker will stop at the next chunk boundary."""
        self._cancelled.set()
        self._pause_event.set()  # Unblock if paused so the thread can exit
        logger.debug("Download %s cancelled", self.task_id)

    @property
    def is_cancelled(self) -> bool:
        """Return True if the download has been cancelled."""
        return self._cancelled.is_set()

    def run(self) -> None:
        """Execute the download (called by QThreadPool)."""
        try:
            self._execute_download()
        except Exception as exc:
            if not self.is_cancelled:
                logger.error("Download %s failed: %s", self.task_id, exc)
                self.signals.failed.emit(self.task_id, str(exc))

    def _execute_download(self) -> None:
        """Core download logic with resume, pause, cancel, and hash check."""
        # Determine resume offset from existing temp file
        if self.temp_path.exists():
            self._resume_offset = self.temp_path.stat().st_size
            logger.info("Resuming download %s from byte %d", self.task_id, self._resume_offset)
        else:
            self._resume_offset = 0
            # Ensure parent directory exists
            self.temp_path.parent.mkdir(parents=True, exist_ok=True)

        self.signals.started.emit(self.task_id)

        # Build headers for the request
        import httpx

        headers: dict[str, str] = {}
        if self.api_client.access_token:
            headers["Authorization"] = f"Bearer {self.api_client.access_token}"
        if self._resume_offset > 0:
            headers["Range"] = f"bytes={self._resume_offset}-"

        # Open streaming connection
        downloaded = self._resume_offset
        hasher = hashlib.sha256()

        # If resuming, we need to hash the existing partial content
        if self._resume_offset > 0 and self.expected_hash:
            with open(self.temp_path, "rb") as existing:
                while True:
                    block = existing.read(self.chunk_size)
                    if not block:
                        break
                    hasher.update(block)

        mode = "ab" if self._resume_offset > 0 else "wb"

        with httpx.Client(follow_redirects=True) as http_client:
            with http_client.stream(
                "GET",
                self.url,
                headers=headers,
                timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0),
            ) as response:
                if response.status_code not in (200, 206):
                    raise RuntimeError(f"Server returned HTTP {response.status_code}")

                total_size = int(response.headers.get("content-length", 0))
                if self._resume_offset > 0 and total_size > 0:
                    total_size += self._resume_offset

                with open(self.temp_path, mode) as fh:
                    for chunk in response.iter_bytes(chunk_size=self.chunk_size):
                        # Check cancel
                        if self.is_cancelled:
                            logger.info("Download %s cancelled mid-stream", self.task_id)
                            return

                        # Block while paused
                        self._pause_event.wait()

                        if self.is_cancelled:
                            return

                        fh.write(chunk)
                        downloaded += len(chunk)

                        if self.expected_hash:
                            hasher.update(chunk)

                        self.signals.progress.emit(self.task_id, downloaded, total_size)

        if self.is_cancelled:
            return

        # Verify hash if expected
        if self.expected_hash:
            actual_hash = hasher.hexdigest()
            if actual_hash != self.expected_hash:
                # Remove corrupted temp file
                self.temp_path.unlink(missing_ok=True)
                raise RuntimeError(
                    f"Hash mismatch: expected {self.expected_hash}, got {actual_hash}"
                )
            logger.info("Hash verification passed for download %s", self.task_id)

        # Atomic rename: .tmp -> final
        if self.final_path.exists():
            self.final_path.unlink()
        self.temp_path.rename(self.final_path)

        logger.info("Download %s completed: %s", self.task_id, self.final_path)
        self.signals.completed.emit(self.task_id, str(self.final_path))
