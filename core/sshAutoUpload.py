import paramiko
import socket
from scp import SCPClient
import json
import os
import re
import time
import logging
from typing import Callable, Optional
import threading

logger = logging.getLogger(__name__)


def ssh_auto_upload(
    host: str,
    port: int,
    user: str,
    password: str,
    local_path: str,
    remote_path: str,
    enableRestart: bool,
    cancel_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> bool:
    """通过 SSH 将本地目录上载到远程主机。

    Args:
        cancel_event: (可选) 一个 threading.Event，用于请求取消上传。
        progress_callback: (可选) 用于报告进度的回调 (percent, message)。
    """

    def _report(progress: int, message: str):
        if progress_callback:
            try:
                progress_callback(progress, message)
            except Exception:
                pass

    def _check_cancel() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    scp = None
    try:
        if _check_cancel():
            _report(0, "已取消")
            return False

        # 找UUID
        uuid = FindUUIDInJson(local_path)
        if uuid == "":
            _report(0, "未找到 UUID")
            return False

        _report(0, "正在连接 SSH...")
        # 连接
        ssh.connect(
            host,
            port=port,
            username=user,
            password=password,
            timeout=10,
            banner_timeout=10,
            auth_timeout=10,
        )

        scp = SCPClient(ssh.get_transport())

        if _check_cancel():
            _report(0, "已取消")
            return False

        # 上传
        logger.info("正在使用SSH上传")
        _report(5, "正在创建远程目录...")
        ssh.exec_command(f"mkdir -p {remote_path}/{uuid}")

        _report(10, "正在上传文件...")
        _upload_dir_with_progress(scp, ssh, local_path, f"{remote_path}/{uuid}", cancel_event, _report)

        if _check_cancel():
            _report(0, "已取消")
            return False

        logger.info("上传完成")
        _report(100, "上传完成")

        if enableRestart:
            _report(100, "正在尝试重启远程程序...")
            stdin, stdout, stderr = ssh.exec_command("pidof epass_drm_app")
            stdout.channel.recv_exit_status()
            stdin, stdout, stderr = ssh.exec_command(f"kill {stdout.read().decode().strip()}")

            # 某个神秘应用退出的时候磨磨蹭蹭（）（）（）（）
            start_time = time.time()
            while True:
                if _check_cancel():
                    _report(0, "已取消")
                    return False
                stdin, stdout, stderr = ssh.exec_command("pidof epass_drm_app")
                if not stdout.read().decode().strip().isdigit():
                    logger.info("主程序已退出")
                    break
                if time.time() - start_time > 10:
                    logger.error("等待程序退出超时，可能需要手动重启通行证上的程序")
                    _report(100, "退出失败，请手动重启通行证上的程序")
                    return False
                time.sleep(0.5)
                
            _report(100, "正在尝试启动主程序")
            from core.sshOperation import startDrmApp
            startDrmApp(ssh)
            _report(100, "重启命令已发送，等待程序启动...")

        return True

    except socket.timeout:
        logger.error("连接或执行命令超时")
        _report(0, "连接或执行命令超时")
        return False

    except paramiko.ssh_exception.NoValidConnectionsError:
        logger.error("SSH端口无法连接")
        _report(0, "SSH端口无法连接")
        return False

    except paramiko.ssh_exception.AuthenticationException:
        logger.error("SSH认证失败")
        _report(0, "SSH认证失败")
        return False

    except paramiko.SSHException as e:
        logger.error("SSH错误:", e)
        _report(0, "SSH错误")
        return False

    finally:
        if scp is not None:
            try:
                scp.close()
            except Exception:
                pass
        try:
            ssh.close()
        except Exception:
            pass


def _count_files_in_dir(path: str) -> int:
    """递归计算目录下的所有文件数量"""
    total = 0
    for root, dirs, files in os.walk(path):
        total += len(files)
    return total


def _upload_dir_with_progress(
    scp: SCPClient,
    ssh,
    local_dir: str,
    remote_dir: str,
    cancel_event: Optional[threading.Event],
    report: Callable[[int, str], None],
):
    """上传 local_dir 下的所有文件和文件夹到 remote_dir，并通过 report 报告进度"""

    if not os.path.isdir(local_dir):
        raise ValueError(f"{local_dir} 不是有效目录")

    total_files = _count_files_in_dir(local_dir)
    uploaded = 0

    def _report_file_progress():
        if total_files == 0:
            report(100, "上传完成")
            return
        percent = int(uploaded / total_files * 90) + 10
        report(percent, f"正在上传文件 ({uploaded}/{total_files})...")

    for item in os.listdir(local_dir):
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("上传已取消")

        local_path = os.path.join(local_dir, item)
        remote_path = f"{remote_dir}/{item}"

        if os.path.isfile(local_path):
            scp.put(local_path, remote_path=remote_path)
            uploaded += 1
            _report_file_progress()
        elif os.path.isdir(local_path):
            ssh.exec_command(f"mkdir -p {remote_path}")
            _upload_dir_with_progress(
                scp, ssh, local_path, remote_path, cancel_event, report
            )

    # 如果刚好完成最后一个文件，更新进度
    if uploaded == total_files:
        report(100, "上传完成")


def FindUUIDInJson(path):
    """
    在指定的path下查找*.json文件（只会查找一次），找到后返回uuid字段，仅包含字母、数字和连字符，失败返回空文本
    """
    try:
        if not os.path.isdir(path):
            return ""
        
        # 查找.json文件
        json_files = [f for f in os.listdir(path) if f.endswith('.json')]
        if not json_files:
            return ""
        
        # 只取第一个.json文件
        json_file = json_files[0]
        json_path = os.path.join(path, json_file)
        
        # 读取并解析JSON
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        uuid_raw = data.get('uuid', '')
        
        # 过滤，只保留字母、数字和连字符
        uuid_clean = re.sub(r'[^a-zA-Z0-9\-]', '', uuid_raw)
        return uuid_clean
    
    except Exception:
        return ""

def upload_dir(scp: SCPClient, ssh, local_dir: str, remote_dir: str):
    """
    上传 local_dir 下的所有文件和文件夹到 remote_dir。
    """
    if not os.path.isdir(local_dir):
        raise ValueError(f"{local_dir} 不是有效目录")

    for item in os.listdir(local_dir):
        local_path = os.path.join(local_dir, item)
        remote_path = f"{remote_dir}/{item}"
        
        if os.path.isfile(local_path):
            scp.put(local_path, remote_path=remote_path)
        elif os.path.isdir(local_path):
            # 创建远程目录
            ssh.exec_command(f"mkdir -p {remote_path}")
            # 递归上传子目录
            upload_dir(scp, ssh, local_path, remote_path)