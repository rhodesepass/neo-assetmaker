'''此处所有的函数都应被try catch包裹，抛出异常由调用者处理'''

from functools import partial
import time
import json
import paramiko
from scp import SCPClient
import json
import os
import re
import logging
import shutil

logger = logging.getLogger(__name__)

debug = True

def StartDrmApp(ssh):
    '''使用脚本启动DRM'''
    # 为  什  么  白  银  要  把  启  动  外  部  程  序  的  功  能  塞  在  s  h  e  l  l  里  🤬  🤬
    UploadFile(ssh,os.path.join(os.getcwd(),"core","scripts","hostStartDrm.sh"), "/root/hostStartDrm.sh")
    stdin, stdout, stderr = ssh.exec_command("chmod +x /root/hostStartDrm.sh")
    stdout.channel.recv_exit_status()
    stdin, stdout, stderr = ssh.exec_command("cd /root/ && nohup ./hostStartDrm.sh > output.log 2>&1 &")
    logger.info(stdout.read().decode())
    stdout.channel.recv_exit_status()
    return

def RefreshRemoteMaterialListCache(ssh):
    '''刷新通行证上的素材列表'''

    from core.sshAutoUpload import FindUUIDInJson
    # 清空tmp目录
    localPath = os.path.join(os.getcwd(), "tmp")
    if os.path.exists(localPath):
        shutil.rmtree(localPath)
    os.makedirs(localPath)
    os.makedirs(os.path.join(localPath, "tmp"))
    
    # 远程获取
    stdin, stdout, stderr = ssh.exec_command(
        '''find /assets/'''
    )
    fileListCache = stdout.read().decode()
    jsonList = FindJsonPath(fileListCache)

    scp = SCPClient(ssh.get_transport())
    for targetJsonFile in jsonList:
        # 重置tmp目录
        if os.path.exists(os.path.join(localPath, "tmp")):
            shutil.rmtree(os.path.join(localPath, "tmp"))
        os.makedirs(os.path.join(localPath, "tmp"))

        # 此处需要放置在临时目录的临时目录
        baseJsonFileName = os.path.basename(targetJsonFile)
        scp.get(targetJsonFile, os.path.join(localPath, "tmp", baseJsonFileName))
        
        # 通过UUID移动
        UUID = FindUUIDInJson(os.path.join(localPath, "tmp"))
        if UUID is None:
            logger.error(f"未找到UUID，无法移动文件 {targetJsonFile}")
            continue

        currentPath = os.path.join(localPath, UUID)
        if not os.path.exists(currentPath):
            os.makedirs(currentPath)
        try:
            shutil.move(os.path.join(localPath, "tmp", baseJsonFileName), currentPath)
            # 移动失败大概率是UUID重复（

            # 下载预览图
            targetPath = os.path.dirname(targetJsonFile) + "/"
            iconPath = GetIconPath(os.path.join(currentPath, baseJsonFileName))
            if iconPath is None:
                continue
            scp.get(targetPath + iconPath, os.path.join(currentPath, iconPath))

            # 保存远程文件路径
            with open(os.path.join(currentPath, "remoteFolderPath.cfg"), "w", encoding="utf-8") as f:
                f.write(targetPath)

        except Exception as e:
            logger.error(f"移动文件失败: {e}")
        finally:
            if os.path.exists(os.path.join(localPath, "tmp")):
                shutil.rmtree(os.path.join(localPath, "tmp"))
    try:
        shutil.rmtree(os.path.join(localPath, "tmp"))
    except Exception as e:
        a = 1
    finally:
        scp.close()

def GetIconPath(jsonPath):
    try:
        with open(jsonPath, "r", encoding="utf-8") as f:
            cache = f.read()
            data = json.loads(cache)
            return data.get("icon")
    except Exception as e:
        logger.error(f"读取JSON文件失败: {e}")
        return None

def FindJsonPath(text):
    '''使用正则匹配 */*.json'''
    pattern = r'/assets/[^/]+/[^/]+\.json'
    matches = re.findall(pattern, text, flags=re.UNICODE)
    return matches

def StopDrmApp(ssh) -> bool:
    '''停止DRM'''
    stdin, stdout, stderr = ssh.exec_command("pidof epass_drm_app")
    stdout.channel.recv_exit_status()
    stdin, stdout, stderr = ssh.exec_command(f"kill {stdout.read().decode().strip()}")
    start_time = time.time()
    while True:
        stdin, stdout, stderr = ssh.exec_command("pidof epass_drm_app")
        if not stdout.read().decode().strip().isdigit():
            logger.info("主程序已退出")
            break
        if time.time() - start_time > 10:
            logger.error("等待程序退出超时，可能需要手动重启通行证上的程序")
            return False
        time.sleep(0.5)
    return True

def DelRemoteFile(ssh, remotePath) -> bool:
    '''删除远程文件'''
    stdin, stdout, stderr = ssh.exec_command(f"rm -rf {remotePath}")
    stdout.channel.recv_exit_status()

    if stdout.read().decode().strip() != "":
        logger.error(f"删除远程文件失败: {remotePath}")
        return False
    else:
        logger.info(f"删除远程文件成功: {remotePath}")
        return True

def UploadFile(ssh, localPath, remotePath, report = None, finishedSize : int = 0, totalSize : int = 0):
    '''上传文件'''
    if report == None:
        scp = SCPClient(ssh.get_transport())
    else:
        scp = SCPClient(ssh.get_transport(), progress = partial(CalcUploadSpeed, report, finishedSize, totalSize))    
    scp.put(localPath, remotePath)

    scp.close() 

sshUploadSpeedCalculatorLastTime = time.time()
sshUploadSpeedCalculatorLastSent = 0
def CalcUploadSpeed(report, finishedSize, totalSize, filename, size, sent):
    '''计算上传速度'''
    global sshUploadSpeedCalculatorLastTime, sshUploadSpeedCalculatorLastSent, currentSize
    now = time.time()
    dt = now - sshUploadSpeedCalculatorLastTime
    ds = sent - sshUploadSpeedCalculatorLastSent
    if dt > 0:
        speed = ds / dt   # B/s
        report(int(((finishedSize + sent) / totalSize) * 100), f"正在上传文件 ({sent}/{size})... {speed/1024:.2f} KB/s")
    sshUploadSpeedCalculatorLastTime = now
    sshUploadSpeedCalculatorLastSent = sent


def DownloadFile(ssh, remotePath, localPath, report = None):
    '''下载文件'''
    if report == None:
        scp = SCPClient(ssh.get_transport())
    else:
        scp = SCPClient(ssh.get_transport(), progress = partial(CalcDownloadSpeed, report))    
    scp.get(remotePath, localPath, recursive=True)

    scp.close()

sshDownloadSpeedCalculatorLastTime = time.time()
sshDownloadSpeedCalculatorLastSent = 0
def CalcDownloadSpeed(report, filename, size, sent):
    '''计算下载速度'''
    global sshDownloadSpeedCalculatorLastTime, sshDownloadSpeedCalculatorLastSent, currentSize
    now = time.time()
    dt = now - sshDownloadSpeedCalculatorLastTime
    ds = sent - sshDownloadSpeedCalculatorLastSent
    if dt > 0:
        speed = ds / dt   # B/s
        report(int((sent / size) * 100), f"正在下载文件 ({sent}/{size})... {speed/1024:.2f} KB/s")
    sshDownloadSpeedCalculatorLastTime = now
    sshDownloadSpeedCalculatorLastSent = sent

if __name__ == "__main__" and debug == True:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        "192.168.137.2",
        port="22",
        username="root",
        password="toor",
        timeout=10,
        banner_timeout=10,
        auth_timeout=10,
    )
    RefreshRemoteMaterialListCache(ssh)
    StopDrmApp(ssh)
    StartDrmApp(ssh)
