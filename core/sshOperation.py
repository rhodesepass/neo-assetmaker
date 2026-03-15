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


def startDrmApp(ssh):

    # 为  什  么  白  银  要  把  启  动  外  部  程  序  的  功  能  塞  在  s  h  e  l  l  里  🤬  🤬
    scp = SCPClient(ssh.get_transport())
    scp.put(os.path.join(os.getcwd(),"core","scripts","hostStartDrm.sh"), "/root/hostStartDrm.sh")
    scp.close()
    stdin, stdout, stderr = ssh.exec_command("chmod +x /root/hostStartDrm.sh")
    stdout.channel.recv_exit_status()
    stdin, stdout, stderr = ssh.exec_command("cd /root/ && nohup ./hostStartDrm.sh > output.log 2>&1 &")
    stdout.channel.recv_exit_status()
    return

