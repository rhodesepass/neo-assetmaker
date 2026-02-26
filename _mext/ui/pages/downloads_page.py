"""Downloads page showing active and completed download tasks.

Displays each download with a progress bar and action buttons for
pause, resume, cancel, and retry operations.
"""

from __future__ import annotations

import logging
from typing import Optional

from qfluentwidgets import (
    BodyLabel,
    InfoBar,
    InfoBarPosition,
    PushButton,
    ScrollArea,
    SubtitleLabel,
)
from qtpy.QtCore import Qt, Signal, Slot
from qtpy.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from _mext.core.service_manager import ServiceManager
from _mext.models.download import DownloadStatus
from _mext.ui.components.download_progress import DownloadProgressWidget

logger = logging.getLogger(__name__)


class DownloadsPage(QWidget):
    """Page listing all download tasks with progress tracking.

    Signals
    -------
    open_file_requested(str)
        Emitted when the user wants to open a completed download.
    """

    open_file_requested = Signal(str)

    def __init__(
        self,
        service_manager: ServiceManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._services = service_manager
        self._widgets: dict[str, DownloadProgressWidget] = {}

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        """Build the downloads page layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Header with actions
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        self._title_label = SubtitleLabel("下载管理", self)
        header_layout.addWidget(self._title_label)

        header_layout.addStretch()

        self._pause_all_btn = PushButton("Pause All", self)
        header_layout.addWidget(self._pause_all_btn)

        self._resume_all_btn = PushButton("Resume All", self)
        header_layout.addWidget(self._resume_all_btn)

        self._cancel_all_btn = PushButton("Cancel All", self)
        header_layout.addWidget(self._cancel_all_btn)

        self._clear_btn = PushButton("Clear Completed", self)
        header_layout.addWidget(self._clear_btn)

        layout.addLayout(header_layout)

        # Scrollable list of download items
        self._scroll_area = ScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch()

        self._scroll_area.setWidget(self._list_container)
        layout.addWidget(self._scroll_area, stretch=1)

        # Empty state
        self._empty_label = BodyLabel(
            "No downloads yet. Browse the Market to start downloading.", self
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(True)
        layout.addWidget(self._empty_label)

    def _connect_signals(self) -> None:
        """Wire button clicks and download engine signals."""
        engine = self._services.download_engine

        engine.download_started.connect(self._on_download_started)
        engine.progress_updated.connect(self._on_progress_updated)
        engine.download_completed.connect(self._on_download_completed)
        engine.download_failed.connect(self._on_download_failed)
        engine.queue_changed.connect(self._refresh_empty_state)

        self._pause_all_btn.clicked.connect(self._on_pause_all)
        self._resume_all_btn.clicked.connect(self._on_resume_all)
        self._cancel_all_btn.clicked.connect(self._on_cancel_all)
        self._clear_btn.clicked.connect(self._on_clear_completed)

    @Slot(str)
    def _on_download_started(self, task_id: str) -> None:
        """Add a new download progress widget for the started task."""
        task = self._services.download_engine.get_task(task_id)
        if task is None:
            return

        widget = DownloadProgressWidget(task, parent=self._list_container)
        widget.pause_clicked.connect(lambda: self._services.download_engine.pause(task_id))
        widget.resume_clicked.connect(lambda: self._services.download_engine.resume(task_id))
        widget.cancel_clicked.connect(lambda: self._services.download_engine.cancel(task_id))
        widget.open_clicked.connect(lambda: self.open_file_requested.emit(task.file_path))

        self._widgets[task_id] = widget
        # Insert before the stretch
        self._list_layout.insertWidget(self._list_layout.count() - 1, widget)
        self._refresh_empty_state()

    @Slot(str, int, int)
    def _on_progress_updated(self, task_id: str, downloaded: int, total: int) -> None:
        """Update the progress widget for the given task."""
        widget = self._widgets.get(task_id)
        if widget:
            widget.update_progress(downloaded, total)

    @Slot(str, str)
    def _on_download_completed(self, task_id: str, file_path: str) -> None:
        """Update the widget to show completion."""
        widget = self._widgets.get(task_id)
        if widget:
            widget.mark_completed(file_path)

        InfoBar.success(
            title="下载完成",
            content=f"文件已保存到 {file_path}",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=4000,
        )

    @Slot(str, str)
    def _on_download_failed(self, task_id: str, error: str) -> None:
        """Update the widget to show failure."""
        widget = self._widgets.get(task_id)
        if widget:
            widget.mark_failed(error)

        InfoBar.error(
            title="下载失败",
            content=error,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000,
        )

    @Slot()
    def _on_pause_all(self) -> None:
        """Pause all active downloads."""
        for task_id, task in self._services.download_engine.tasks.items():
            if task.status == DownloadStatus.DOWNLOADING:
                self._services.download_engine.pause(task_id)
                widget = self._widgets.get(task_id)
                if widget:
                    widget.mark_paused()

    @Slot()
    def _on_resume_all(self) -> None:
        """Resume all paused downloads."""
        for task_id, task in self._services.download_engine.tasks.items():
            if task.status == DownloadStatus.PAUSED:
                self._services.download_engine.resume(task_id)
                widget = self._widgets.get(task_id)
                if widget:
                    widget.mark_downloading()

    @Slot()
    def _on_cancel_all(self) -> None:
        """Cancel all active and queued downloads."""
        self._services.download_engine.cancel_all()
        for task_id, widget in self._widgets.items():
            task = self._services.download_engine.get_task(task_id)
            if task and task.status == DownloadStatus.CANCELLED:
                widget.mark_cancelled()

    @Slot()
    def _on_clear_completed(self) -> None:
        """Remove completed, cancelled, and failed downloads from the list."""
        self._services.download_engine.clear_completed()

        to_remove = []
        for task_id, widget in self._widgets.items():
            task = self._services.download_engine.get_task(task_id)
            if task is None:
                widget.deleteLater()
                to_remove.append(task_id)

        for task_id in to_remove:
            del self._widgets[task_id]

        self._refresh_empty_state()

    def _refresh_empty_state(self) -> None:
        """Show or hide the empty state label."""
        has_items = len(self._widgets) > 0
        self._empty_label.setVisible(not has_items)
        self._scroll_area.setVisible(has_items)
