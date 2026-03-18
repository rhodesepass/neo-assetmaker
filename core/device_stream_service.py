"""
设备实时画面流接收服务 — HTTP MJPEG 流解码
"""

import logging
import threading
import time
import urllib.request
import urllib.error
from typing import Optional

import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_HOST = "192.168.137.2"
DEFAULT_STREAM_PORT = 8080
DEFAULT_SSH_PORT = 22
DEFAULT_SSH_USER = "root"
DEFAULT_SSH_PASSWORD = "toor"
DEFAULT_STREAM_PATH = "/?action=stream"
MAX_RECONNECT_ATTEMPTS = 3
RECONNECT_INTERVAL = 2.0
FPS_WINDOW_SIZE = 30
CONNECT_TIMEOUT = 5


class DeviceStreamThread(QThread):
    """
    HTTP MJPEG 流接收线程
    """

    frame_ready = pyqtSignal(QImage)
    stream_started = pyqtSignal()
    stream_stopped = pyqtSignal()
    stream_error = pyqtSignal(str)
    fps_updated = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_event = threading.Event()
        self._host: str = DEFAULT_HOST
        self._stream_port: int = DEFAULT_STREAM_PORT
        self._ssh_port: int = DEFAULT_SSH_PORT
        self._ssh_user: str = DEFAULT_SSH_USER
        self._ssh_password: str = DEFAULT_SSH_PASSWORD
        self._auto_start_server: bool = False
        self._response: Optional[object] = None
        self._frame_times: list[float] = []

    def setup(
        self,
        host: str = DEFAULT_HOST,
        stream_port: int = DEFAULT_STREAM_PORT,
        ssh_port: int = DEFAULT_SSH_PORT,
        ssh_user: str = DEFAULT_SSH_USER,
        ssh_password: str = DEFAULT_SSH_PASSWORD,
        auto_start_server: bool = False,
    ):
        """配置连接参数，必须在 start() 之前调用"""
        self._host = host
        self._stream_port = stream_port
        self._ssh_port = ssh_port
        self._ssh_user = ssh_user
        self._ssh_password = ssh_password
        self._auto_start_server = auto_start_server

    def stop(self):
        """请求停止线程"""
        self._stop_event.set()
        # 关闭 HTTP 连接以中断阻塞 read
        resp = self._response
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

    def run(self):
        """主循环：连接 → 读取帧 → 重连"""
        self._stop_event.clear()

        # 可选：通过 SSH 启动 mjpg-streamer
        if self._auto_start_server:
            try:
                self._start_mjpg_streamer_via_ssh()
            except Exception as e:
                logger.warning("SSH 启动 mjpg-streamer 失败: %s", e)
                self.stream_error.emit(f"SSH 启动 mjpg-streamer 失败: {e}")
                # 不中断，仍然尝试连接（可能已经在运行）

        stream_url = f"http://{self._host}:{self._stream_port}{DEFAULT_STREAM_PATH}"
        reconnect_count = 0

        while not self._stop_event.is_set():
            try:
                logger.info("连接 MJPEG 流: %s", stream_url)
                self._response = urllib.request.urlopen(
                    stream_url, timeout=CONNECT_TIMEOUT
                )
                reconnect_count = 0
                self._frame_times.clear()
                self.stream_started.emit()
                logger.info("MJPEG 流已连接")

                self._read_stream_loop(self._response)

            except Exception as e:
                if self._stop_event.is_set():
                    break
                reconnect_count += 1
                msg = f"流连接异常: {e}"
                logger.warning(msg)

                if reconnect_count > MAX_RECONNECT_ATTEMPTS:
                    self.stream_error.emit(
                        f"连接失败，已重试 {MAX_RECONNECT_ATTEMPTS} 次: {e}"
                    )
                    break

                self.stream_error.emit(
                    f"{msg}，{RECONNECT_INTERVAL}s 后重试 "
                    f"({reconnect_count}/{MAX_RECONNECT_ATTEMPTS})"
                )
                # 等待重连间隔，期间可被 stop() 中断
                if self._stop_event.wait(RECONNECT_INTERVAL):
                    break
            finally:
                self._close_response()

        self._close_response()
        self.stream_stopped.emit()
        logger.info("MJPEG 流线程已退出")

    def _read_stream_loop(self, response):
        """从 HTTP multipart 响应中持续读取帧"""
        while not self._stop_event.is_set():
            jpeg_data = self._read_mjpeg_frame(response)
            if jpeg_data is None:
                break

            # JPEG → numpy BGR → QImage
            arr = np.frombuffer(jpeg_data, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                logger.debug("JPEG 解码失败，跳过帧")
                continue

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_frame.shape
            bytes_per_line = ch * w
            # .copy() 确保 QImage 数据独立于 numpy buffer
            # Qt 6 QImage 文档: "The buffer must remain valid throughout
            # the life of the QImage"
            qimg = QImage(
                rgb_frame.data, w, h, bytes_per_line,
                QImage.Format.Format_RGB888,
            ).copy()

            self.frame_ready.emit(qimg)
            self._update_fps()

    def _read_mjpeg_frame(self, response) -> Optional[bytes]:
        """
        从 HTTP multipart 响应中提取单帧 JPEG 数据
        """
        # 跳过行直到找到 Content-Length 或 boundary
        content_length = -1
        while not self._stop_event.is_set():
            line = response.readline()
            if not line:
                return None  # 连接关闭

            line_str = line.decode("utf-8", errors="ignore").strip()

            if line_str.lower().startswith("content-length:"):
                try:
                    content_length = int(line_str.split(":")[1].strip())
                except (ValueError, IndexError):
                    content_length = -1

            # 空行标志 header 结束，开始读取数据
            if line_str == "" and content_length > 0:
                jpeg_data = self._read_exact(response, content_length)
                if jpeg_data is None or len(jpeg_data) != content_length:
                    return None
                return jpeg_data

        return None

    def _read_exact(self, response, length: int) -> Optional[bytes]:
        """精确读取指定字节数"""
        data = b""
        remaining = length
        while remaining > 0 and not self._stop_event.is_set():
            chunk = response.read(remaining)
            if not chunk:
                return None
            data += chunk
            remaining -= len(chunk)
        return data

    def _update_fps(self):
        """滑动窗口帧率统计"""
        now = time.monotonic()
        self._frame_times.append(now)
        # 只保留最近 N 帧的时间戳
        if len(self._frame_times) > FPS_WINDOW_SIZE:
            self._frame_times = self._frame_times[-FPS_WINDOW_SIZE:]
        if len(self._frame_times) >= 2:
            elapsed = self._frame_times[-1] - self._frame_times[0]
            if elapsed > 0:
                fps = (len(self._frame_times) - 1) / elapsed
                self.fps_updated.emit(round(fps, 1))

    def _close_response(self):
        """安全关闭 HTTP 响应"""
        resp = self._response
        self._response = None
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

    def _start_mjpg_streamer_via_ssh(self):
        """
        通过 SSH 在设备上启动 mjpg-streamer
        """
        import paramiko

        logger.info("通过 SSH 启动 mjpg-streamer (%s:%d)", self._host, self._ssh_port)
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(
                self._host,
                port=self._ssh_port,
                username=self._ssh_user,
                password=self._ssh_password,
                timeout=10,
                banner_timeout=10,
                auth_timeout=10,
            )
            # 先尝试停止已有实例
            ssh.exec_command("killall mjpg_streamer 2>/dev/null")
            time.sleep(0.5)
            # 启动 mjpg-streamer（后台运行）
            cmd = (
                "mjpg_streamer "
                "-i 'input_uvc.so -d /dev/video0 -r 640x360 -f 15' "
                "-o 'output_http.so -p 8080 -w /www'"
            )
            ssh.exec_command(f"nohup {cmd} > /dev/null 2>&1 &")
            # 等待启动
            time.sleep(1.0)
            logger.info("mjpg-streamer 启动指令已发送")
        finally:
            ssh.close()
