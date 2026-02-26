"""Download engine managing concurrent file downloads.

Uses QThreadPool with QRunnable-based workers for parallel downloads.
Provides pause, resume, cancel, and progress tracking capabilities.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from qtpy.QtCore import QObject, QThreadPool, Signal

from _mext.core.config import Config, get_config
from _mext.models.download import DownloadStatus, DownloadTask
from _mext.services.api_client import ApiClient
from _mext.services.download_worker import DownloadWorker

logger = logging.getLogger(__name__)


class DownloadEngine(QObject):
    """Manages concurrent downloads with progress tracking.

    Signals
    -------
    download_started(str)
        A download has been started. Payload is the task ID.
    progress_updated(str, int, int)
        Download progress update. Payload is (task_id, bytes_downloaded, total_bytes).
    download_completed(str, str)
        A download finished. Payload is (task_id, file_path).
    download_failed(str, str)
        A download failed. Payload is (task_id, error_message).
    queue_changed()
        The download queue has changed (item added, removed, or status changed).
    """

    download_started = Signal(str)
    progress_updated = Signal(str, int, int)
    download_completed = Signal(str, str)
    download_failed = Signal(str, str)
    queue_changed = Signal()

    def __init__(
        self,
        api_client: ApiClient,
        config: Optional[Config] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._config = config or get_config()

        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(self._config.max_concurrent_downloads)

        self._tasks: dict[str, DownloadTask] = {}
        self._workers: dict[str, DownloadWorker] = {}

    # -- Properties --

    @property
    def active_count(self) -> int:
        """Return the number of currently active downloads."""
        return sum(
            1
            for t in self._tasks.values()
            if t.status in (DownloadStatus.DOWNLOADING, DownloadStatus.QUEUED)
        )

    @property
    def tasks(self) -> dict[str, DownloadTask]:
        """Return a copy of the current task dictionary."""
        return dict(self._tasks)

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        """Return a specific download task by ID, or None."""
        return self._tasks.get(task_id)

    # -- Download management --

    def start_download(
        self,
        material_id: str,
        download_url: str,
        filename: str,
        *,
        material_name: str = "",
        expected_hash: Optional[str] = None,
        expected_size: int = 0,
    ) -> str:
        """Start a new download and return its task ID.

        Parameters
        ----------
        material_id : str
            The material identifier this download corresponds to.
        download_url : str
            URL to download the file from.
        filename : str
            Destination filename (stored in the configured download directory).
        material_name : str
            Human-readable material name for display in the UI.
        expected_hash : str, optional
            Expected SHA-256 hash for post-download verification.
        expected_size : int
            Expected file size in bytes (0 if unknown).

        Returns
        -------
        str
            The unique task ID for this download.
        """
        task_id = str(uuid.uuid4())
        dest = self._config.get_final_download_path(filename)
        temp_dest = self._config.get_temp_download_path(filename)

        task = DownloadTask(
            id=task_id,
            material_id=material_id,
            material_name=material_name or filename,
            status=DownloadStatus.QUEUED,
            progress=0,
            total_size=expected_size,
            file_path=str(dest),
            temp_path=str(temp_dest),
            download_url=download_url,
            expected_hash=expected_hash,
        )
        self._tasks[task_id] = task

        worker = DownloadWorker(
            task_id=task_id,
            url=download_url,
            temp_path=temp_dest,
            final_path=dest,
            api_client=self._api,
            expected_hash=expected_hash,
        )

        # Connect worker signals
        worker.signals.progress.connect(self._on_progress)
        worker.signals.completed.connect(self._on_completed)
        worker.signals.failed.connect(self._on_failed)
        worker.signals.started.connect(self._on_started)

        self._workers[task_id] = worker
        self._pool.start(worker)
        self.queue_changed.emit()

        logger.info("Queued download %s for %s -> %s", task_id, download_url, dest)
        return task_id

    def pause(self, task_id: str) -> bool:
        """Pause an active download. Returns True if the task was paused."""
        worker = self._workers.get(task_id)
        task = self._tasks.get(task_id)
        if worker is None or task is None:
            return False

        if task.status != DownloadStatus.DOWNLOADING:
            return False

        worker.pause()
        task.status = DownloadStatus.PAUSED
        self.queue_changed.emit()
        logger.info("Paused download %s", task_id)
        return True

    def resume(self, task_id: str) -> bool:
        """Resume a paused download. Returns True if the task was resumed."""
        worker = self._workers.get(task_id)
        task = self._tasks.get(task_id)
        if worker is None or task is None:
            return False

        if task.status != DownloadStatus.PAUSED:
            return False

        worker.resume()
        task.status = DownloadStatus.DOWNLOADING
        self.queue_changed.emit()
        logger.info("Resumed download %s", task_id)
        return True

    def cancel(self, task_id: str) -> bool:
        """Cancel a download. Returns True if the task was cancelled."""
        worker = self._workers.get(task_id)
        task = self._tasks.get(task_id)
        if task is None:
            return False

        if task.status in (DownloadStatus.COMPLETED, DownloadStatus.CANCELLED):
            return False

        if worker is not None:
            worker.cancel()

        task.status = DownloadStatus.CANCELLED
        self.queue_changed.emit()
        logger.info("Cancelled download %s", task_id)
        return True

    def cancel_all(self) -> None:
        """Cancel all active and queued downloads."""
        for task_id in list(self._tasks.keys()):
            self.cancel(task_id)

    def remove_task(self, task_id: str) -> bool:
        """Remove a completed/cancelled/failed task from the list."""
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if task.status in (DownloadStatus.DOWNLOADING, DownloadStatus.QUEUED):
            self.cancel(task_id)
        self._tasks.pop(task_id, None)
        self._workers.pop(task_id, None)
        self.queue_changed.emit()
        return True

    def clear_completed(self) -> None:
        """Remove all completed, cancelled, and failed tasks."""
        to_remove = [
            tid
            for tid, t in self._tasks.items()
            if t.status
            in (DownloadStatus.COMPLETED, DownloadStatus.CANCELLED, DownloadStatus.FAILED)
        ]
        for tid in to_remove:
            self._tasks.pop(tid, None)
            self._workers.pop(tid, None)
        if to_remove:
            self.queue_changed.emit()

    # -- Worker signal handlers --

    def _on_started(self, task_id: str) -> None:
        """Handle worker started signal."""
        task = self._tasks.get(task_id)
        if task:
            task.status = DownloadStatus.DOWNLOADING
        self.download_started.emit(task_id)
        self.queue_changed.emit()

    def _on_progress(self, task_id: str, downloaded: int, total: int) -> None:
        """Handle worker progress signal."""
        task = self._tasks.get(task_id)
        if task:
            task.progress = downloaded
            task.total_size = total if total > 0 else task.total_size
        self.progress_updated.emit(task_id, downloaded, total)

    def _on_completed(self, task_id: str, file_path: str) -> None:
        """Handle worker completion signal."""
        task = self._tasks.get(task_id)
        if task:
            task.status = DownloadStatus.COMPLETED
            task.file_path = file_path
            task.progress = task.total_size
        self._workers.pop(task_id, None)
        self.download_completed.emit(task_id, file_path)
        self.queue_changed.emit()
        logger.info("Download %s completed: %s", task_id, file_path)

    def _on_failed(self, task_id: str, error_msg: str) -> None:
        """Handle worker failure signal."""
        task = self._tasks.get(task_id)
        if task:
            task.status = DownloadStatus.FAILED
            task.error = error_msg
        self._workers.pop(task_id, None)
        self.download_failed.emit(task_id, error_msg)
        self.queue_changed.emit()
        logger.error("Download %s failed: %s", task_id, error_msg)
