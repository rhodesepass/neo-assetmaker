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
import shutil


logger = logging.getLogger(__name__)

debug = True

def startDrmApp(ssh):
    '''使用脚本启动DRM'''
    # 为  什  么  白  银  要  把  启  动  外  部  程  序  的  功  能  塞  在  s  h  e  l  l  里  🤬  🤬
    scp = SCPClient(ssh.get_transport())
    scp.put(os.path.join(os.getcwd(),"core","scripts","hostStartDrm.sh"), "/root/hostStartDrm.sh")
    scp.close()
    stdin, stdout, stderr = ssh.exec_command("chmod +x /root/hostStartDrm.sh")
    stdout.channel.recv_exit_status()
    stdin, stdout, stderr = ssh.exec_command("cd /root/ && nohup ./hostStartDrm.sh > output.log 2>&1 &")
    stdout.channel.recv_exit_status()
    return



def RefreshRemoteMaterialList(ssh):
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
    for target in jsonList:

        # 重置tmp目录
        if os.path.exists(os.path.join(localPath, "tmp")):
            shutil.rmtree(os.path.join(localPath, "tmp"))
        os.makedirs(os.path.join(localPath, "tmp"))

        # 此处需要放置在临时目录的临时目录
        scp.get(target, os.path.join(localPath, "tmp", os.path.basename(target)))
        
        # 通过UUID移动
        UUID = FindUUIDInJson(os.path.join(localPath, "tmp"))
        currentPath = os.path.join(localPath, UUID)
        if not os.path.exists(currentPath):
            os.makedirs(currentPath)
        try:
            shutil.move(os.path.join(localPath, "tmp", os.path.basename(target)), currentPath)
        except Exception as e:
            logger.error(f"移动文件失败: {e}")
        finally:
            if os.path.exists(os.path.join(localPath, "tmp")):
                shutil.rmtree(os.path.join(localPath, "tmp"))



def FindJsonPath(text):
    '''使用正则匹配 */*.json'''

    pattern = r'/assets/[^/]+/[^/]+\.json'
    matches = re.findall(pattern, text, flags=re.UNICODE)
    return matches

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
    RefreshRemoteMaterialList(ssh)