"""SSH 上传/下载/列表/删除服务"""

import os
import threading
import logging
from typing import Optional
import glob
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

def GetJsonFatherKey(jsonPath, key):
    import json
    try:
        with open(jsonPath, "r", encoding="utf-8") as f:
            cache = f.read()
            data = json.loads(cache)
            return data.get(key)
    except Exception as e:
        logger.error(f"读取JSON文件失败: {e}")
        return None


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
            from datetime import datetime
            now = datetime.now()
            formatted_time = now.strftime("%Y-%m-%d %H:%M:%S")

            stdin, stdout, stderr = ssh.exec_command(f"date -s \"{formatted_time}\"", timeout=15)
            exit_status = stdout.channel.recv_exit_status()

            self.log_message.emit("INFO", f"SSH 已同步通行证时间 ({formatted_time})")
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

    list_completed = pyqtSignal(list)  # [{name, size, date, UUID}]
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
            from core.sshOperation import RefreshRemoteMaterialListCache
            RefreshRemoteMaterialListCache(ssh)
            localPath = os.path.join(os.getcwd(), "tmp")

            childrenFolders = [name for name in os.listdir(localPath) if os.path.isdir(os.path.join(localPath, name))]
            self.log_message.emit("INFO", f"找到 {len(childrenFolders)} 个素材包")
            items = []
            for folder in childrenFolders:
                # 读取远程文件路径
                with open(os.path.join(localPath, folder, "remoteFolderPath.cfg"), "r", encoding="utf-8") as f:
                    remoteAbsPath = f.read()
                jsonPath = os.path.join(localPath, folder, "epconfig.json")
                items.append({"name": GetJsonFatherKey(jsonPath, "name"), "size": 0, "date": 0, "uuid": GetJsonFatherKey(jsonPath, "uuid"), "path": remoteAbsPath})
            self.list_completed.emit(items)
        except Exception as e:
            self.log_message.emit("ERROR", f"获取远程素材列表失败: {e}")
            self.list_failed.emit(str(e))
            return

class SshDeleteWorker(QThread):
    """SSH 删除远程素材工作线程"""

    delete_completed = pyqtSignal(str)
    delete_failed = pyqtSignal(str)
    log_message = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._args = None

    def setup(self, host: str, port: int, user: str, password: str,
              remote_path: str, target_name: str,uuid: str, path: str):
        self._args = (host, port, user, password, remote_path, target_name, uuid, path)

    def run(self):
        if not self._args:
            self.delete_failed.emit("参数不足")
            return
        host, port, user, password, remote_path, target_name, uuid, path = self._args
        ssh = None
        try:
            self.log_message.emit("INFO", f"正在删除远程素材: {target_name}...")
            ssh = _create_ssh_client(host, port, user, password)

            stdin, stdout, stderr = ssh.exec_command(f"rm -rf {path}", timeout=15)
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
              remote_path: str, target_name: str, local_save_dir: str, remoteAbsPath: str):
        self._args = (host, port, user, password, remote_path, target_name, local_save_dir, remoteAbsPath)
        self._cancel_event.clear()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        if not self._args:
            self.download_failed.emit("参数不足")
            return
        host, port, user, password, remote_path, target_name, local_save_dir, remoteAbsPath = self._args
        ssh = None
        scp_client = None
        try:
            self.log_message.emit("INFO", f"正在下载: {target_name}...")
            self.progress_updated.emit(0, "正在连接...")

            ssh = _create_ssh_client(host, port, user, password)
            scp_client = SCPClient(ssh.get_transport())

            full_remote = remoteAbsPath
            os.makedirs(local_save_dir, exist_ok=True)

            self.progress_updated.emit(10, "正在下载文件...")
            scp_client.get(full_remote, local_path=local_save_dir, recursive=True)

            if self._cancel_event.is_set():
                self.log_message.emit("INFO", "下载已取消")
                self.download_failed.emit("下载已取消")
                return

            self.progress_updated.emit(100, "下载完成")
            self.log_message.emit("INFO", f"已下载到: {local_save_dir}")
            self.download_completed.emit(local_save_dir)

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
