from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor
from qtpy.QtGui import QColor, QPixmap
import os
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QScrollArea,
    QWidget,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QApplication,
    QInputDialog,
)
from PyQt6.QtCore import Qt
import sys
from qfluentwidgets import (
    SimpleCardWidget,
    SubtitleLabel,
    StrongBodyLabel,
    CaptionLabel,
    PrimaryPushButton,
    PushButton,
    ProgressBar,
    ListWidget,
    PlainTextEdit,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    setCustomStyleSheet,
)
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QMenuBar,
    QMenu,
    QStatusBar,
    QFileDialog,
    QMessageBox,
    QLabel,
    QScrollArea,
    QGroupBox,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QSpinBox,
    QLineEdit,
    QTabWidget,
    QDialog,
)
from core import sshOperation
import paramiko
from scp import SCPClient
import logging

logger = logging.getLogger(__name__)


# 👂？ 我没对象 所以创建一个 :D
class FileItem:
    def __init__(self, name, type_):
        self.name = name
        self.type = type_


class RemoteFileManagerWindow(QWidget):
    def __init__(
        self, parent, mainwindow, sshIp, sshPort, sshUser, sshPassword, sshDefaultFolder
    ):
        super().__init__()
        self.main_window = mainwindow
        self.host = sshIp
        self.port = sshPort
        self.sshUser = sshUser
        self.sshPassword = sshPassword
        self.sshDefaultFolder = sshDefaultFolder

        self.setWindowTitle("远程文件管理")
        self.resize(1200, 1000)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)  # 阻塞主窗口

        # 主布局
        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(10, 10, 10, 10)
        self.mainLayout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 顶部路径栏
        self.topPathGrid = QWidget()
        self.topPathLayout = QHBoxLayout(self.topPathGrid)
        self.topPathLayout.setContentsMargins(10, 10, 10, 10)
        self.mainLayout.addWidget(self.topPathGrid, 0, Qt.AlignmentFlag.AlignTop)

        # 路径
        self.lb_currentPathlb = QLabel("当前位置：")
        self.topPathLayout.addWidget(self.lb_currentPathlb)

        self.lb_currentPath = QLabel("/")
        self.topPathLayout.addWidget(self.lb_currentPath)

        # 挤占右边空间
        self.topPathLayout.addStretch()

        # 文件浏览器滚动区域
        self.fileWarpper = QScrollArea()
        self.fileWarpper.setWidgetResizable(True)
        self.mainLayout.addWidget(self.fileWarpper)

        # 容器
        self.container = QWidget()
        self.containerLayout = QVBoxLayout(self.container)
        self.containerLayout.setSpacing(10)
        self.containerLayout.setContentsMargins(10, 10, 10, 10)
        self.fileWarpper.setWidget(self.container)

        # 列表控件
        self.fileManagerList = QListWidget()
        self.fileManagerList.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        setCustomStyleSheet(
            self.fileManagerList,
            "ListWidget { border: none; background: transparent; }",
            "ListWidget { border: none; background: transparent; }",
        )
        self.fileManagerList.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.containerLayout.addWidget(self.fileManagerList)

        # 底部工具栏
        self.buttomGrid = QWidget()
        self.buttomLayout = QHBoxLayout(self.buttomGrid)
        self.buttomLayout.setContentsMargins(10, 10, 10, 10)
        self.containerLayout.addWidget(self.buttomGrid)

        # 挤占左边空间
        self.buttomLayout.addStretch()

        buttonWidth = 100

        self.btn_refresh = PushButton("刷新")
        self.btn_refresh.setIcon(FluentIcon.UPDATE)
        self.btn_refresh.setMinimumWidth(buttonWidth)
        self.btn_refresh.setContentsMargins(10, 10, 10, 10)
        self.btn_refresh.clicked.connect(self._on_refresh)
        self.buttomLayout.addWidget(self.btn_refresh, 0, Qt.AlignmentFlag.AlignRight)

        self.btn_goParentFolder = PushButton("上一级")
        self.btn_goParentFolder.setIcon(FluentIcon.UP)
        self.btn_goParentFolder.setMinimumWidth(buttonWidth)
        self.btn_goParentFolder.setContentsMargins(10, 10, 10, 10)
        self.btn_goParentFolder.clicked.connect(self._on_goParentFolder)
        self.buttomLayout.addWidget(
            self.btn_goParentFolder, 0, Qt.AlignmentFlag.AlignRight
        )

        self.btn_Rename = PushButton("重命名")
        self.btn_Rename.setIcon(FluentIcon.EDIT)
        self.btn_Rename.setMinimumWidth(buttonWidth)
        self.buttomLayout.addWidget(self.btn_Rename, 0, Qt.AlignmentFlag.AlignRight)
        self.btn_Rename.clicked.connect(self._on_file_rename_clicked)

        self.btn_Delete = PushButton("删除")
        self.btn_Delete.setIcon(FluentIcon.DELETE)
        self.btn_Delete.setMinimumWidth(buttonWidth)
        self.buttomLayout.addWidget(self.btn_Delete, 0, Qt.AlignmentFlag.AlignRight)
        self.btn_Delete.clicked.connect(self._on_file_delete_clicked)

        self.btn_Download = PushButton("下载")
        self.btn_Download.setIcon(FluentIcon.DOWNLOAD)
        self.btn_Download.setMinimumWidth(buttonWidth)
        self.buttomLayout.addWidget(self.btn_Download, 0, Qt.AlignmentFlag.AlignRight)
        self.btn_Download.clicked.connect(self._on_file_download_clicked)

        self.btn_uploadFile = PushButton("上传")
        self.btn_uploadFile.setIcon(FluentIcon.SEND)
        self.btn_uploadFile.setMinimumWidth(buttonWidth)
        self.btn_uploadFile.setContentsMargins(10, 10, 10, 10)
        self.btn_uploadFile.clicked.connect(self._on_upload)
        self.buttomLayout.addWidget(self.btn_uploadFile, 0, Qt.AlignmentFlag.AlignRight)

        # 进度条与进度文本
        self.lb_process = QLabel()
        self.lb_process.setText("无任务")
        self.containerLayout.addWidget(self.lb_process)
        self.progressBar = ProgressBar()
        self.containerLayout.addWidget(self.progressBar)

        self._on_refresh()

    def _on_goParentFolder(self):
        self.DirChanged("..")
        self._on_refresh()
        return

    def _on_file_rename_clicked(self):
        item = self.fileManagerList.currentItem()
        if not item:
            return
        filename = item.data(Qt.ItemDataRole.UserRole)[2:]
        if not DetectProtectedPath(filename):
            return
        while True:
            text, ok = QInputDialog.getText(
                self,
                "重命名...",
                f"正在重命名:{self.lb_currentPath.text()}/{filename}\n输入目标名称：",  # 父窗口  # 标题  # 提示信息
            )
            if ok:
                if CheckValidFileName(text):
                    break
                else:
                    continue
            else:  # 用户按下“取消”
                return
        try:
            if not self.TryStartSSH():
                raise ValueError("初始化SSH失败")
            stdin, stdout, stderr = self.ssh.exec_command(
                f'mv "{self.lb_currentPath.text()}/{filename}" "{self.lb_currentPath.text()}/{text}"'
            )
            stdout.channel.recv_exit_status()
            self._on_refresh()
        except Exception as ex:
            logger.error(f"重命名失败{ex}", stack_info=True)

    def LoadFiles(self, fileList: list):
        # 检查颜色调色板
        app = QApplication.instance() or QApplication([])
        if app.palette().color(QPalette.ColorRole.Window).lightness() < 128:
            themeType = "dark"
        else:
            themeType = "light"

        # 使用字典重排序
        self.fileList = sorted(fileList, key=lambda x: x.name)

        for file in self.fileList:
            filename = file.name

            item_widget = QWidget()

            layout = QHBoxLayout(item_widget)
            layout.setContentsMargins(10, 10, 10, 10)

            # 图标 QLabel
            icon_label = QLabel()
            if getattr(file, "type", "") == "folder":
                icon_label.setPixmap(
                    QPixmap(
                        os.path.join(os.getcwd(), "assets", f"folder_{themeType}.png")
                    ).scaled(
                        24,
                        24,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                icon_label.setPixmap(
                    QPixmap(
                        os.path.join(os.getcwd(), "assets", f"file_{themeType}.png")
                    ).scaled(
                        24,
                        24,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            layout.addWidget(icon_label)

            label = CaptionLabel(filename)
            layout.addWidget(label, 1, Qt.AlignmentFlag.AlignLeft)

            list_item = QListWidgetItem(self.fileManagerList)
            list_item.setSizeHint(item_widget.sizeHint())

            list_item.setData(Qt.ItemDataRole.UserRole, filename)  # 存文件名
            self.fileManagerList.addItem(list_item)
            self.fileManagerList.setItemWidget(list_item, item_widget)

    def StartSSH(self):
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # 自动接受新主机
        self.ssh.connect(
            self.host,
            self.port,
            self.sshUser,
            self.sshPassword,
            timeout=10,
            banner_timeout=10,
            auth_timeout=10,
        )
        return

    def TryStartSSH(self) -> bool:
        for i in range(0, 3):
            try:
                stdin, stdout, stderr = self.ssh.exec_command("help")
                if stdout.read() == None:
                    self.StartSSH()
                    continue
                else:
                    return True
            except Exception as e:
                logger.error(f"载入SSH失败")
                self.StartSSH()
        return False

    def _on_file_delete_clicked(self):
        item = self.fileManagerList.currentItem()
        if not item:
            return
        filename = item.data(Qt.ItemDataRole.UserRole)[2:]
        if not DetectProtectedPath(filename):
            return
        result = QMessageBox.question(
            self,
            "删除...",
            f"是否确认删除：（此操作不可逆）{self.lb_currentPath.text()}/{filename}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            if not self.TryStartSSH():
                raise ValueError("初始化SSH失败")
            self.ssh.exec_command(f"rm -rf {self.lb_currentPath.text()}/{filename}")
        except Exception as ex:
            logger.error(f"删除失败{ex}", stack_info=True)
        finally:
            self._on_refresh()

    def _on_file_download_clicked(self):
        print(f"按钮点击:")
        return

    def _on_upload(self):
        try:
            import threading
            from core.sshOperation import UploadDir
            from core.sshOperation import UploadFile

            # 检查SSH
            remotePath = "/assets/tmp/"
            if not self.TryStartSSH():
                raise ValueError("初始化SSH失败")

            result = QMessageBox.question(
                self,
                "上传...",
                "点击 “是” 上传文件夹；点击 “否” 上传文件",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            path = ""

            if result == QMessageBox.StandardButton.Yes:
                path = QFileDialog.getExistingDirectory(self, "打开文件夹", "")
                if not path:
                    return
                # 确保文件夹存在
                stdin, stdout, stderr = self.ssh.exec_command(f"mkdir -p {remotePath}")
                stdout.channel.recv_exit_status()
                uploadThread = threading.Thread(
                    target=UploadDir,
                    args=(
                        self.ssh,
                        path,
                        remotePath,
                        self.reportProcess,
                    ),
                    daemon=True,
                )
                uploadThread.start()
            else:
                path, _ = QFileDialog.getOpenFileName(
                    self, "打开文件", "", "所有文件 (*.*)"
                )
                if not path:
                    return
                # 确保文件夹存在
                stdin, stdout, stderr = self.ssh.exec_command(f"mkdir -p {remotePath}")
                stdout.channel.recv_exit_status()
                uploadThread = threading.Thread(
                    target=UploadFile,
                    args=(
                        self.ssh,
                        path,
                        remotePath,
                        self.reportProcess,
                        0,
                        os.path.getsize(path),
                    ),
                    daemon=True,
                )
                uploadThread.start()
        except Exception as e:
            logger.error(f"上传失败:{e}", exc_info=True)
        return

    def _on_refresh(self):
        try:
            self.fileManagerList.clear()
            currentFolder = self.lb_currentPath.text()
            if not self.TryStartSSH():
                raise ValueError("初始化SSH失败")
            fileList = []
            fileList = self.getAllFiles(self.ssh, currentFolder, fileList)
            fileList = self.getFolder(self.ssh, currentFolder, fileList)
            self.LoadFiles(fileList)
        except Exception as e:
            logger.error(f"刷新失败{e}", stack_info=True)
        return

    def CalcCurrentPath(self) -> str:

        return ""

    def getAllFiles(self, ssh: paramiko.SSHClient, currentFolder, list=[]) -> list:
        stdin, stdout, stderr = ssh.exec_command(
            f"""cd {currentFolder} && find . -maxdepth 1"""
        )
        lines = stdout.read().decode("utf-8", errors="ignore").splitlines()
        for line in lines:
            if line == ".":
                line = ".."
            list.append(FileItem(line, "file"))
        return list

    def getFolder(self, ssh: paramiko.SSHClient, currentFolder, fileList=[]) -> list:
        """此函数会将传入的list中为folder的项目进行标记"""
        stdin, stdout, stderr = ssh.exec_command(
            f"""cd {currentFolder} && find . -type d -maxdepth 1"""
        )
        lines = stdout.read().decode("utf-8", errors="ignore").splitlines()
        for i in range(0, len(lines)):
            for j in range(0, len(fileList)):
                if lines[i] == ".":
                    lines[i] = ".."
                if lines[i] == fileList[j].name:
                    fileList[j].type = "folder"
        return fileList

    def reportProcess(self, processBarPositon: int, text: str):
        """修改进度条和文本"""
        self.progressBar.setValue(processBarPositon)
        self.lb_process.setText(text)
        if processBarPositon == 100:
            self.lb_process.setText("完成")
            self.progressBar.setValue(0)
        return

    def on_item_double_clicked(self, item: QListWidgetItem):
        fileName = item.data(Qt.ItemDataRole.UserRole)  # 之前存的文件名
        for item in self.fileList:
            if fileName == item.name:
                if item.type == "folder":
                    self.DirChanged(fileName)
                    self._on_refresh()
                    return
                else:
                    return
        return

    def DirChanged(self, nextDir: str):
        currentPath = self.lb_currentPath.text()

        if nextDir == ".." and currentPath != "/":
            # 返回上一级目录
            import os

            parentDir = os.path.dirname(currentPath.rstrip("/"))
            self.lb_currentPath.setText(parentDir)
            return parentDir
        elif nextDir == ".":
            # 刷新当前目录
            return currentPath
        else:
            # 切换到指定子目录
            import os

            nextDir = nextDir[2:]  # 从索引 2 开始取，前两个字符" ./ "被删除
            if currentPath != "/":
                newPath = f"{currentPath}/{nextDir}"
            else:
                newPath = f"/{nextDir}"
            self.lb_currentPath.setText(newPath)
            return newPath


def CheckValidFileName(name: str) -> bool:
    if not name or name.strip() == "":
        return False  # 不能为空
    if "/" in name:
        return False
    if len(name) > 255:
        return False
    return True


def DetectProtectedPath(path: str):
    """检测当前文件夹/文件夹是否允许被更改"""
    protectedDirList = [".", "..", "//", "/"]
    for prt in protectedDirList:
        if path == prt:
            return False
    return True
