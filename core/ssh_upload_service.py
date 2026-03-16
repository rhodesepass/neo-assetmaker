"""SSH 上传/下载/列表/删除服务"""

import os
import threading
import logging
from typing import Optional

import paramiko
import socket
from scp import SCPClient

from PyQt6.QtCore import QThread, pyqtSignal

from core.sshAutoUpload import ssh_auto_upload

logger = logging.getLogger(__name__)


def _create_ssh_client(host: str, port: int, user: str, password: str) -> paramiko.SSHClient:
    """创建并连接 SSH 客户端（各 Worker 复用）"""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, port=port, username=user, password=password,
                timeout=10, banner_timeout=10, auth_timeout=10)
    return ssh


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
                self.upload_completed.emit(f"上传到 {remote_path} 成功")
            else:
                self.upload_failed.emit("SSH 上传失败")
        except Exception as e:
            logger.exception("SSH 上传失败")
            self.upload_failed.emit(str(e))


class SshConnectTestWorker(QThread):
    """SSH 连接测试工作线程"""

    connect_succeeded = pyqtSignal()
    connect_failed = pyqtSignal(str)
    log_message = pyqtSignal(str, str)  # (level, message)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._args = None

    def setup(self, host: str, port: int, user: str, password: str):
        self._args = (host, port, user, password)

    def run(self):
        if not self._args:
            self.connect_failed.emit("参数不足")
            return
        host, port, user, password = self._args
        ssh = None
        try:
            self.log_message.emit("INFO", f"正在连接 {host}:{port}...")
            ssh = _create_ssh_client(host, port, user, password)
            self.log_message.emit("INFO", f"SSH 连接成功 ({host}:{port})")
            self.connect_succeeded.emit()
        except socket.timeout:
            self.log_message.emit("ERROR", "连接超时")
            self.connect_failed.emit("连接超时")
        except paramiko.ssh_exception.NoValidConnectionsError:
            self.log_message.emit("ERROR", "SSH 端口无法连接")
            self.connect_failed.emit("SSH 端口无法连接")
        except paramiko.ssh_exception.AuthenticationException:
            self.log_message.emit("ERROR", "SSH 认证失败，请检查用户名和密码")
            self.connect_failed.emit("SSH 认证失败")
        except paramiko.SSHException as e:
            self.log_message.emit("ERROR", f"SSH 错误: {e}")
            self.connect_failed.emit(str(e))
        except Exception as e:
            self.log_message.emit("ERROR", f"连接失败: {e}")
            self.connect_failed.emit(str(e))
        finally:
            if ssh:
                try:
                    ssh.close()
                except Exception:
                    pass


class SshRemoteListWorker(QThread):
    """SSH 远程素材列表获取工作线程"""

    list_completed = pyqtSignal(list)  # [{name, size, date}]
    list_failed = pyqtSignal(str)
    log_message = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._args = None

    def setup(self, host: str, port: int, user: str, password: str, remote_path: str):
        self._args = (host, port, user, password, remote_path)

    def run(self):
        if not self._args:
            self.list_failed.emit("参数不足")
            return
        host, port, user, password, remote_path = self._args
        ssh = None
        try:
            self.log_message.emit("INFO", "正在获取远程素材列表...")
            ssh = _create_ssh_client(host, port, user, password)

            # 列出子目录: 名称, 大小(du), 修改日期
            cmd = (
                f"for d in {remote_path}/*/; do "
                f"[ -d \"$d\" ] && "
                f"name=$(basename \"$d\") && "
                f"size=$(du -sh \"$d\" 2>/dev/null | cut -f1) && "
                f"mtime=$(stat -c '%Y' \"$d\" 2>/dev/null || stat -f '%m' \"$d\" 2>/dev/null) && "
                f"echo \"$name|$size|$mtime\"; "
                f"done"
            )
            stdin, stdout, stderr = ssh.exec_command(cmd, timeout=15)
            output = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()

            items = []
            if output:
                for line in output.splitlines():
                    parts = line.split("|", 2)
                    if len(parts) == 3:
                        name, size, mtime = parts
                        # 转换 unix 时间戳为可读日期
                        try:
                            import datetime
                            dt = datetime.datetime.fromtimestamp(int(mtime))
                            date_str = dt.strftime("%Y-%m-%d %H:%M")
                        except (ValueError, OSError):
                            date_str = mtime
                        items.append({"name": name, "size": size, "date": date_str})

            self.log_message.emit("INFO", f"找到 {len(items)} 个素材包")
            self.list_completed.emit(items)

        except socket.timeout:
            self.log_message.emit("ERROR", "连接超时")
            self.list_failed.emit("连接超时")
        except paramiko.ssh_exception.AuthenticationException:
            self.log_message.emit("ERROR", "SSH 认证失败")
            self.list_failed.emit("SSH 认证失败")
        except Exception as e:
            logger.exception("获取远程列表失败")
            self.log_message.emit("ERROR", f"获取列表失败: {e}")
            self.list_failed.emit(str(e))
        finally:
            if ssh:
                try:
                    ssh.close()
                except Exception:
                    pass


class SshDeleteWorker(QThread):
    """SSH 删除远程素材工作线程"""

    delete_completed = pyqtSignal(str)
    delete_failed = pyqtSignal(str)
    log_message = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._args = None

    def setup(self, host: str, port: int, user: str, password: str,
              remote_path: str, target_name: str):
        self._args = (host, port, user, password, remote_path, target_name)

    def run(self):
        if not self._args:
            self.delete_failed.emit("参数不足")
            return
        host, port, user, password, remote_path, target_name = self._args
        ssh = None
        try:
            self.log_message.emit("INFO", f"正在删除远程素材: {target_name}...")
            ssh = _create_ssh_client(host, port, user, password)

            full_path = f"{remote_path.rstrip('/')}/{target_name}"
            stdin, stdout, stderr = ssh.exec_command(f"rm -rf {full_path}", timeout=15)
            exit_status = stdout.channel.recv_exit_status()
            err = stderr.read().decode("utf-8", errors="replace").strip()

            if exit_status == 0:
                self.log_message.emit("INFO", f"已删除: {target_name}")
                self.delete_completed.emit(target_name)
            else:
                self.log_message.emit("ERROR", f"删除失败: {err}")
                self.delete_failed.emit(err or "删除失败")

        except Exception as e:
            logger.exception("SSH 删除失败")
            self.log_message.emit("ERROR", f"删除失败: {e}")
            self.delete_failed.emit(str(e))
        finally:
            if ssh:
                try:
                    ssh.close()
                except Exception:
                    pass


class SshDownloadWorker(QThread):
    """SSH 下载远程素材工作线程"""

    progress_updated = pyqtSignal(int, str)
    download_completed = pyqtSignal(str)  # 本地保存路径
    download_failed = pyqtSignal(str)
    log_message = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel_event = threading.Event()
        self._args = None

    def setup(self, host: str, port: int, user: str, password: str,
              remote_path: str, target_name: str, local_save_dir: str):
        self._args = (host, port, user, password, remote_path, target_name, local_save_dir)
        self._cancel_event.clear()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        if not self._args:
            self.download_failed.emit("参数不足")
            return
        host, port, user, password, remote_path, target_name, local_save_dir = self._args
        ssh = None
        scp_client = None
        try:
            self.log_message.emit("INFO", f"正在下载: {target_name}...")
            self.progress_updated.emit(0, "正在连接...")

            ssh = _create_ssh_client(host, port, user, password)
            scp_client = SCPClient(ssh.get_transport())

            full_remote = f"{remote_path.rstrip('/')}/{target_name}"
            local_dest = os.path.join(local_save_dir, target_name)
            os.makedirs(local_dest, exist_ok=True)

            self.progress_updated.emit(10, "正在下载文件...")
            scp_client.get(full_remote, local_path=local_dest, recursive=True)

            if self._cancel_event.is_set():
                self.log_message.emit("INFO", "下载已取消")
                self.download_failed.emit("下载已取消")
                return

            self.progress_updated.emit(100, "下载完成")
            self.log_message.emit("INFO", f"已下载到: {local_dest}")
            self.download_completed.emit(local_dest)

        except Exception as e:
            logger.exception("SSH 下载失败")
            self.log_message.emit("ERROR", f"下载失败: {e}")
            self.download_failed.emit(str(e))
        finally:
            if scp_client:
                try:
                    scp_client.close()
                except Exception:
                    pass
            if ssh:
                try:
                    ssh.close()
                except Exception:
                    pass


class SshPreviewWorker(QThread):
    """SSH 下载预览图片工作线程"""

    preview_ready = pyqtSignal(bytes)  # 图片数据
    preview_failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._args = None

    def setup(self, host: str, port: int, user: str, password: str,
              remote_path: str, target_name: str):
        self._args = (host, port, user, password, remote_path, target_name)

    def run(self):
        if not self._args:
            self.preview_failed.emit("参数不足")
            return
        host, port, user, password, remote_path, target_name = self._args
        ssh = None
        try:
            ssh = _create_ssh_client(host, port, user, password)
            sftp = ssh.open_sftp()

            asset_dir = f"{remote_path.rstrip('/')}/{target_name}"
            # 尝试查找图片文件
            image_exts = ('.png', '.jpg', '.jpeg', '.bmp', '.webp')
            files = sftp.listdir(asset_dir)
            image_file = None
            for f in files:
                if f.lower().endswith(image_exts):
                    image_file = f
                    break

            if image_file:
                import io
                with sftp.open(f"{asset_dir}/{image_file}", "rb") as remote_f:
                    data = remote_f.read()
                self.preview_ready.emit(data)
            else:
                self.preview_failed.emit("无图片文件")

        except Exception as e:
            self.preview_failed.emit(str(e))
        finally:
            if ssh:
                try:
                    ssh.close()
                except Exception:
                    pass
