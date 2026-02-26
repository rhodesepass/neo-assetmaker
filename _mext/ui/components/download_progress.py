"""Download progress widget for a single download task.

Shows the file name, progress bar, status label, speed/ETA info,
and action buttons (pause, resume, cancel, open).
"""

from __future__ import annotations

from typing import Optional

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ProgressBar,
    PushButton,
    ToolButton,
)
from qtpy.QtCore import Signal
from qtpy.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from _mext.models.download import DownloadStatus, DownloadTask


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


class DownloadProgressWidget(CardWidget):
    """Widget showing a single download's progress with action controls.

    Signals
    -------
    pause_clicked()
        The pause button was clicked.
    resume_clicked()
        The resume button was clicked.
    cancel_clicked()
        The cancel button was clicked.
    open_clicked()
        The open/show-in-folder button was clicked.
    """

    pause_clicked = Signal()
    resume_clicked = Signal()
    cancel_clicked = Signal()
    open_clicked = Signal()

    def __init__(
        self,
        task: DownloadTask,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._task = task
        self.setFixedHeight(80)
        self._setup_ui()
        self._update_state()

    def _setup_ui(self) -> None:
        """Build the progress widget layout."""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(12)

        # Left: info + progress bar
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        # File name
        display_name = self._task.material_name or self._task.material_id
        self._name_label = BodyLabel(display_name, self)
        font = self._name_label.font()
        font.setBold(True)
        self._name_label.setFont(font)
        info_layout.addWidget(self._name_label)

        # Progress bar
        self._progress_bar = ProgressBar(self)
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setValue(0)
        info_layout.addWidget(self._progress_bar)

        # Status line: progress text + status
        status_layout = QHBoxLayout()
        status_layout.setSpacing(8)

        self._progress_label = CaptionLabel("0 B", self)
        status_layout.addWidget(self._progress_label)

        self._status_label = CaptionLabel("Queued", self)
        status_layout.addWidget(self._status_label)

        status_layout.addStretch()
        info_layout.addLayout(status_layout)

        main_layout.addLayout(info_layout, stretch=1)

        # Right: action buttons
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(4)

        button_row = QHBoxLayout()
        button_row.setSpacing(4)

        self._pause_btn = ToolButton(self)
        self._pause_btn.setText("||")
        self._pause_btn.setFixedSize(28, 28)
        self._pause_btn.setToolTip("暂停")
        self._pause_btn.clicked.connect(self.pause_clicked.emit)
        button_row.addWidget(self._pause_btn)

        self._resume_btn = ToolButton(self)
        self._resume_btn.setText(">")
        self._resume_btn.setFixedSize(28, 28)
        self._resume_btn.setToolTip("继续")
        self._resume_btn.clicked.connect(self.resume_clicked.emit)
        self._resume_btn.setVisible(False)
        button_row.addWidget(self._resume_btn)

        self._cancel_btn = ToolButton(self)
        self._cancel_btn.setText("X")
        self._cancel_btn.setFixedSize(28, 28)
        self._cancel_btn.setToolTip("取消")
        self._cancel_btn.clicked.connect(self.cancel_clicked.emit)
        button_row.addWidget(self._cancel_btn)

        self._open_btn = PushButton("Open", self)
        self._open_btn.setFixedHeight(28)
        self._open_btn.setToolTip("打开文件位置")
        self._open_btn.clicked.connect(self.open_clicked.emit)
        self._open_btn.setVisible(False)
        button_row.addWidget(self._open_btn)

        btn_layout.addLayout(button_row)
        main_layout.addLayout(btn_layout)

    def _update_state(self) -> None:
        """Update button visibility and status text based on task state."""
        status = self._task.status
        self._status_label.setText(status.display_name)

        is_active = status == DownloadStatus.DOWNLOADING
        is_paused = status == DownloadStatus.PAUSED
        is_terminal = status.is_terminal

        self._pause_btn.setVisible(is_active)
        self._resume_btn.setVisible(is_paused)
        self._cancel_btn.setVisible(not is_terminal)
        self._open_btn.setVisible(status == DownloadStatus.COMPLETED)

        if is_terminal:
            self._progress_bar.setValue(
                100 if status == DownloadStatus.COMPLETED else self._progress_bar.value()
            )

    def update_progress(self, downloaded: int, total: int) -> None:
        """Update the progress bar and label with new values."""
        if total > 0:
            percent = min(100, int((downloaded / total) * 100))
            self._progress_bar.setValue(percent)
            self._progress_label.setText(
                f"{_format_bytes(downloaded)} / {_format_bytes(total)} ({percent}%)"
            )
        else:
            self._progress_label.setText(_format_bytes(downloaded))

        self._status_label.setText("下载中")
        self._pause_btn.setVisible(True)
        self._resume_btn.setVisible(False)
        self._cancel_btn.setVisible(True)
        self._open_btn.setVisible(False)

    def mark_completed(self, file_path: str) -> None:
        """Update the widget to show download completion."""
        self._task.status = DownloadStatus.COMPLETED
        self._task.file_path = file_path
        self._progress_bar.setValue(100)
        self._status_label.setText("已完成")
        self._progress_label.setText(f"已保存到: {file_path}")
        self._update_state()

    def mark_failed(self, error: str) -> None:
        """Update the widget to show download failure."""
        self._task.status = DownloadStatus.FAILED
        self._status_label.setText("失败")
        self._progress_label.setText(f"错误: {error}")
        self._status_label.setStyleSheet("color: #e74c3c;")
        self._update_state()

    def mark_paused(self) -> None:
        """Update the widget to show paused state."""
        self._task.status = DownloadStatus.PAUSED
        self._status_label.setText("已暂停")
        self._update_state()

    def mark_downloading(self) -> None:
        """Update the widget to show active downloading state."""
        self._task.status = DownloadStatus.DOWNLOADING
        self._status_label.setText("下载中")
        self._update_state()

    def mark_cancelled(self) -> None:
        """Update the widget to show cancelled state."""
        self._task.status = DownloadStatus.CANCELLED
        self._status_label.setText("已取消")
        self._update_state()
