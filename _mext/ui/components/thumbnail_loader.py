"""Asynchronous thumbnail loader with LRU caching.

Uses a pool of QThread workers to download preview images off the
main thread and caches results in QPixmapCache.
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal as Signal
from PyQt6.QtGui import QPixmap, QPixmapCache
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtCore import QUrl

from _mext.core.constants import THUMBNAIL_CACHE_SIZE

logger = logging.getLogger(__name__)

# Increase the global pixmap cache limit (in KB)
QPixmapCache.setCacheLimit(THUMBNAIL_CACHE_SIZE * 150)  # ~30 MB


class ThumbnailLoadWorker(QThread):
    """Download a single image in a background thread.

    Signals
    -------
    completed(str, QPixmap)
        (cache_key, pixmap) on success.
    error(str, str)
        (cache_key, error_message) on failure.
    """

    completed = Signal(str, QPixmap)
    error = Signal(str, str)

    def __init__(
        self,
        url: str,
        cache_key: str,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._url = url
        self._cache_key = cache_key

    def run(self) -> None:
        try:
            import urllib.request

            req = urllib.request.Request(self._url)
            req.add_header("User-Agent", "AssetStore/1.0")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()

            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                self.completed.emit(self._cache_key, pixmap)
            else:
                self.error.emit(self._cache_key, "Failed to decode image data")
        except Exception as exc:
            self.error.emit(self._cache_key, str(exc))


class ThumbnailLoader(QObject):
    """Manages concurrent thumbnail loading with caching.

    Limits concurrent downloads to avoid overwhelming the network.
    Results are cached in QPixmapCache for instant reuse.

    Signals
    -------
    thumbnail_ready(str, QPixmap)
        Emitted when a thumbnail is ready (cache_key, pixmap).
    """

    thumbnail_ready = Signal(str, QPixmap)

    def __init__(self, max_concurrent: int = 6, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._max_concurrent = max_concurrent
        self._active_workers: dict[str, ThumbnailLoadWorker] = {}
        self._pending_queue: list[tuple[str, str]] = []  # (url, cache_key)

    def load(self, url: str, cache_key: str = "") -> Optional[QPixmap]:
        """Request a thumbnail.  Returns cached pixmap immediately if available.

        If not cached, queues a background download and emits
        ``thumbnail_ready`` when done.  Returns None in that case.
        """
        if not url:
            return None

        key = cache_key or url
        pixmap = QPixmap()
        if QPixmapCache.find(key, pixmap):
            return pixmap

        # Already loading?
        if key in self._active_workers:
            return None

        # Check queue
        if any(k == key for _, k in self._pending_queue):
            return None

        if len(self._active_workers) < self._max_concurrent:
            self._start_worker(url, key)
        else:
            self._pending_queue.append((url, key))

        return None

    def _start_worker(self, url: str, cache_key: str) -> None:
        worker = ThumbnailLoadWorker(url, cache_key, parent=self)
        worker.completed.connect(self._on_completed)
        worker.error.connect(self._on_error)
        worker.finished.connect(lambda k=cache_key: self._on_finished(k))
        self._active_workers[cache_key] = worker
        worker.start()

    def _on_completed(self, cache_key: str, pixmap: QPixmap) -> None:
        QPixmapCache.insert(cache_key, pixmap)
        self.thumbnail_ready.emit(cache_key, pixmap)

    def _on_error(self, cache_key: str, error: str) -> None:
        logger.debug("Thumbnail load failed [%s]: %s", cache_key, error)

    def _on_finished(self, cache_key: str) -> None:
        self._active_workers.pop(cache_key, None)
        self._process_queue()

    def _process_queue(self) -> None:
        while self._pending_queue and len(self._active_workers) < self._max_concurrent:
            url, key = self._pending_queue.pop(0)
            if key not in self._active_workers:
                self._start_worker(url, key)

    def clear(self) -> None:
        """Cancel all pending loads."""
        self._pending_queue.clear()
