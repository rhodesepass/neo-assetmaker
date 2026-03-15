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
    shellScript = '''cat > /root/hostStartDrmScript.sh << 'EOF'\n''' \
                '''memcheck\n'''\
                '''wait_any_key(){\n'''\
                '''LAST_TIME=$(date +%s)\n'''\
                '''echo "Press any key to continue..."\n'''\
                '''while [ $? -eq 0 ]; do\n'''\
                '''read -n1\n'''\
                '''CURRENT_TIME=$(date +%s)\n'''\
                '''ELAPSED_TIME=$((CURRENT_TIME - LAST_TIME))\n'''\
                '''if [ $ELAPSED_TIME -ge 3 ]; then\n'''\
                '''echo "Triggered!"\n'''\
                '''break\n'''\
                '''fi\n'''\
                '''done\n'''\
                '''}\n'''\
                '''randomly_start_prts_last_call(){\n'''\
                '''RANDOM_NUM=$((RANDOM % 10))\n'''\
                '''if [ $RANDOM_NUM -eq 0 ]; then\n'''\
                '''prts_last_call\n'''\
                '''echo "........."\n'''\
                '''sleep 3\n'''\
                '''clear\n'''\
                '''echo "Signal Lost...."\n'''\
                '''fi\n'''\
                '''}\n'''\
                '''drain_stdin() {\n'''\
                '''LAST_TIME=$(date +%s)\n'''\
                '''echo "Draining stdin buffer..."\n'''\
                '''while true; do\n'''\
                '''read -n 1 -t 1\n'''\
                '''CURRENT_TIME=$(date +%s)\n'''\
                '''ELAPSED_TIME=$((CURRENT_TIME - LAST_TIME))\n'''\
                '''if [ $ELAPSED_TIME -ge 3 ]; then\n'''\
                '''echo "Done."\n'''\
                '''break\n'''\
                '''fi\n'''\
                '''done\n'''\
                '''}\n'''\
                '''remount_sd(){\n'''\
                '''umount /sd > /dev/null 2>&1\n'''\
                '''umount /dev/mmcblk0p1 > /dev/null 2>&1\n'''\
                '''mkdir /sd > /dev/null 2>&1\n'''\
                '''mount -o iocharset=utf8 /dev/mmcblk0p1 /sd\n'''\
                '''mount_ret=$?\n'''\
                '''if [ $mount_ret -eq 0 ]; then\n'''\
                '''echo "SD Card Mounted!"\n'''\
                '''touch /tmp/sd_mounted\n'''\
                '''else\n'''\
                '''echo "No SD Card Found."\n'''\
                '''rm -f /tmp/sd_mounted\n'''\
                '''fi\n'''\
                '''}\n'''\
                '''remount_sd\n'''\
                '''if [ ! -f "./epass_drm_app" ]; then\n'''\
                '''cat << EOF\n'''\
                '''  _   _  ____  _____       _______\n'''\
                ''' | \\ | |/ __ \\|  __ \\   /\\|__   __|/\\\n'''\
                ''' |  \\| | |  | | |  | | /  \\  | |  /  \\\n'''\
                ''' | . \\ | |  | | |  | |/ /\\ \\ | | / /\\ \\\n'''\
                ''' | |\\  | |__| | |__| / ____ \\| |/ ____ \\\n'''\
                ''' |_| \\_|\\____/|_____/_/    \\_\\_/_/    \\_\\\n'''\
                '''\n'''\
                '''Please copy 'epass_drm_app' and asset files.\n'''\
                '''to app directory.\n'''\
                '''EOF\n'''\
                '''usbctl mtp\n'''\
                '''return\n'''\
                '''fi\n'''\
                '''cat logo.txt\n'''\
                '''cat << EOF\n'''\
                '''---------------------------------------------\n'''\
                '''     RHODES ISLAND AUTHORIZATION PASS\n'''\
                '''   VERSION 1.0 (c) Ada.Closure.Church 1097\n'''\
                '''---------------------------------------------\n'''\
                '''EOF\n'''\
                '''echo -n -e "\\e[31m"\n'''\
                '''cat << EOF\n'''\
                '''   This pass certifies that the bearer is an\n'''\
                ''' authorized operator of Rhodes Island Co'Ltd.\n'''\
                '''  Unauthorized use of Rhodes Island property\n'''\
                '''            is strictly prohibited.\n'''\
                '''EOF\n'''\
                '''echo -n -e "\\e[0m"\n'''\
                '''cat << EOF\n'''\
                '''---------------------------------------------\n'''\
                '''EOF\n'''\
                '''sleep 1\n'''\
                '''echo -n -e "\\e[32m"\n'''\
                '''echo "Welcome to Rhodes Island!"\n'''\
                '''echo "You are in Terminal $(tty)."\n'''\
                '''echo "Access Level: Operator"\n'''\
                '''echo -n -e "\\e[0m"\n'''\
                '''echo ""\n'''\
                '''chmod +x ./epass_drm_app\n'''\
                '''./epass_drm_app version\n'''\
                '''cat /etc/os-release\n'''
    ssh.exec_command(f"cd /root/ && nohup {shellScript} > /root/output.log 2>&1 &")
    return