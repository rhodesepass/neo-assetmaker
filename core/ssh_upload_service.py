"""SSH 上传服务"""

import threading
import logging
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from core.sshAutoUpload import ssh_auto_upload

logger = logging.getLogger(__name__)


class SshUploadWorker(QThread):
    """SSH 上传工作线程"""

    progress_updated = pyqtSignal(int, str)
    upload_completed = pyqtSignal(str)
    upload_failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel_event = threading.Event()
        self._args = None

    def setup(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        local_path: str,
        remote_path: str,
        enable_restart: bool,
    ):
        self._args = (host, port, user, password, local_path, remote_path, enable_restart)
        self._cancel_event.clear()

    def cancel(self):
        """请求取消上传"""
        logger.info("SSH 上传请求取消")
        self._cancel_event.set()

    def run(self):
        if not self._args:
            self.upload_failed.emit("参数不足，无法开始上传")
            return

        host, port, user, password, local_path, remote_path, enable_restart = self._args

        def _report(progress: int, message: str):
            self.progress_updated.emit(progress, message)

        try:
            success = ssh_auto_upload(
                host=host,
                port=port,
                user=user,
                password=password,
                local_path=local_path,
                remote_path=remote_path,
                enableRestart=enable_restart,
                cancel_event=self._cancel_event,
                progress_callback=_report,
            )
            if success:
                self.upload_completed.emit(f"上传到 {remote_path} 成功，请等待程序启动")
            else:
                self.upload_failed.emit("SSH 上传失败")
        except Exception as e:
            logger.exception("SSH 上传失败")
            self.upload_failed.emit(str(e))
