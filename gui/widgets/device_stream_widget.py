"""
设备实时画面显示组件

显示从设备 mjpg-streamer 接收的 MJPEG 流画面，
提供开始/停止串流控制和状态信息显示。
"""

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

from qfluentwidgets import (
    PrimaryPushButton,
    PushButton,
    CaptionLabel,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    setCustomStyleSheet,
)

from core.device_stream_service import DeviceStreamThread

logger = logging.getLogger(__name__)


class DeviceStreamWidget(QWidget):
    """
    设备实时画面显示组件
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stream_thread: DeviceStreamThread | None = None
        self._is_streaming: bool = False

        # SSH 连接参数（由 RemotePage 设置）
        self._host: str = "192.168.137.2"
        self._ssh_port: int = 22
        self._ssh_user: str = "root"
        self._ssh_password: str = "toor"

        self._init_ui()
        self._connect_signals()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # ── 控制栏 ──
        control_layout = QHBoxLayout()
        control_layout.setSpacing(8)

        self.btnStart = PrimaryPushButton("开始串流")
        self.btnStart.setIcon(FluentIcon.PLAY)
        self.btnStop = PushButton("停止")
        self.btnStop.setIcon(FluentIcon.CLOSE)
        self.btnStop.setEnabled(False)

        control_layout.addWidget(self.btnStart)
        control_layout.addWidget(self.btnStop)
        control_layout.addStretch()
        layout.addLayout(control_layout)

        # ── 画面显示区 ──
        self.displayLabel = QLabel()
        self.displayLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.displayLabel.setMinimumSize(320, 240)
        self.displayLabel.setStyleSheet(
            "QLabel { background-color: #1a1a1a; border-radius: 4px; }"
        )
        self.displayLabel.setText("未连接")
        setCustomStyleSheet(
            self.displayLabel,
            "QLabel { color: #666666; font-size: 14px; }",
            "QLabel { color: #888888; font-size: 14px; }",
        )
        layout.addWidget(self.displayLabel, stretch=1)

        # ── 状态栏 ──
        self.statusLabel = CaptionLabel("未连接")
        setCustomStyleSheet(
            self.statusLabel,
            "CaptionLabel { color: #999999; }",
            "CaptionLabel { color: #777777; }",
        )
        layout.addWidget(self.statusLabel)

    def _connect_signals(self):
        self.btnStart.clicked.connect(self._on_start_stream)
        self.btnStop.clicked.connect(self._on_stop_stream)

    # ─── 串流控制 ─────────────────────────────────────

    def _on_start_stream(self):
        if self._is_streaming:
            return

        self._stream_thread = DeviceStreamThread(parent=self)
        self._stream_thread.setup(
            host=self._host,
            ssh_port=self._ssh_port,
            ssh_user=self._ssh_user,
            ssh_password=self._ssh_password,
        )

        self._stream_thread.frame_ready.connect(self._on_frame_ready)
        self._stream_thread.stream_started.connect(self._on_stream_started)
        self._stream_thread.stream_stopped.connect(self._on_stream_stopped)
        self._stream_thread.stream_error.connect(self._on_stream_error)
        self._stream_thread.fps_updated.connect(self._on_fps_updated)

        self._stream_thread.start()
        self._is_streaming = True
        self.btnStart.setEnabled(False)
        self.btnStop.setEnabled(True)
        self.statusLabel.setText("连接中...")
        self.displayLabel.setText("连接中...")

    def _on_stop_stream(self):
        if not self._is_streaming:
            return
        self._stop_thread()

    def _stop_thread(self):
        """停止流线程并清理"""
        if self._stream_thread is not None:
            self._stream_thread.stop()
            self._stream_thread.wait(3000)
            self._stream_thread.deleteLater()
            self._stream_thread = None

        self._is_streaming = False
        self.btnStart.setEnabled(True)
        self.btnStop.setEnabled(False)

    # ─── 信号槽 ─────────────────────────────────────

    def _on_frame_ready(self, qimage: QImage):
        """收到解码帧，缩放显示"""
        pixmap = QPixmap.fromImage(qimage)
        scaled = pixmap.scaled(
            self.displayLabel.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.displayLabel.setPixmap(scaled)

    def _on_stream_started(self):
        self.statusLabel.setText("已连接")
        setCustomStyleSheet(
            self.statusLabel,
            "CaptionLabel { color: #4CAF50; }",
            "CaptionLabel { color: #66BB6A; }",
        )

    def _on_stream_stopped(self):
        self._is_streaming = False
        self.btnStart.setEnabled(True)
        self.btnStop.setEnabled(False)
        self.statusLabel.setText("已断开")
        setCustomStyleSheet(
            self.statusLabel,
            "CaptionLabel { color: #999999; }",
            "CaptionLabel { color: #777777; }",
        )

    def _on_stream_error(self, msg: str):
        logger.warning("流错误: %s", msg)
        self.statusLabel.setText(f"错误: {msg[:60]}")
        setCustomStyleSheet(
            self.statusLabel,
            "CaptionLabel { color: #F44336; }",
            "CaptionLabel { color: #EF5350; }",
        )
        InfoBar.warning(
            "串流异常",
            msg,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=4000,
        )

    def _on_fps_updated(self, fps: float):
        """更新状态栏帧率和分辨率"""
        pixmap = self.displayLabel.pixmap()
        if pixmap and not pixmap.isNull():
            w, h = pixmap.width(), pixmap.height()
            self.statusLabel.setText(f"已连接 | FPS: {fps} | {w}x{h}")
        else:
            self.statusLabel.setText(f"已连接 | FPS: {fps}")

    # ─── 公共接口 ─────────────────────────────────────

    def set_ssh_params(self, host: str, port: int, user: str, password: str):
        """从 RemotePage 传入 SSH 参数"""
        self._host = host
        self._ssh_port = port
        self._ssh_user = user
        self._ssh_password = password

    def shutdown(self):
        """停止线程，清理资源"""
        self._stop_thread()
