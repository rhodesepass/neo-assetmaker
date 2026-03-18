"""
远程管理页面 — 三栏布局：操作按钮+素材列表 | 预览+操作 | 日志
"""

import os
import logging
import tempfile
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QFont
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QFileDialog,
    QLabel,
    QFrame,
    QListWidgetItem,
    QMessageBox,
)

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

from gui.styles import COLOR_PREVIEW_BG
from gui.main_window import MainWindow

logger = logging.getLogger(__name__)


class AssetListItemWidget(QWidget):
    """自定义列表项Widget：左侧缩略图、名称、UUID、路径；右侧三个按钮"""

    def __init__(self, asset_data: dict, parent=None):
        super().__init__(parent)
        self.asset_data = asset_data
        self.parent_page = parent  # RemotePage实例
        # 左侧组件
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(64, 64)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setStyleSheet(
            "border: 1px solid #ccc; border-radius: 4px;"
        )
        self.thumbnail_label.setWordWrap(True)

        self.name_label = CaptionLabel(asset_data.get("name", ""))
        self.name_label.setMaximumHeight(16)
        self.uuid_label = CaptionLabel(f"UUID: {asset_data.get('uuid', '')}")
        self.uuid_label.setMaximumHeight(16)
        self.path_label = CaptionLabel(f"路径: {asset_data.get('path', '')}")
        self.path_label.setMaximumHeight(16)

        # 右侧按钮
        self.btn_delete = PushButton("删除")
        self.btn_delete.setIcon(FluentIcon.DELETE)
        self.btn_download = PushButton("下载")
        self.btn_download.setIcon(FluentIcon.DOWNLOAD)
        self.btn_edit = PushButton("编辑")
        self.btn_edit.setIcon(FluentIcon.EDIT)

        # 布局
        left_layout = QVBoxLayout()
        left_layout.setSpacing(4)

        top_layout = QHBoxLayout()
        top_layout.setSpacing(8)
        top_layout.addWidget(self.thumbnail_label, alignment=Qt.AlignmentFlag.AlignTop)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        text_layout.addWidget(self.name_label)
        text_layout.addWidget(self.uuid_label)
        text_layout.addWidget(self.path_label)
        top_layout.addLayout(text_layout)

        left_layout.addLayout(top_layout)

        right_layout = QVBoxLayout()
        right_layout.setSpacing(4)
        right_layout.addWidget(self.btn_delete)
        right_layout.addWidget(self.btn_download)
        right_layout.addWidget(self.btn_edit)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(12)
        main_layout.addLayout(left_layout)
        main_layout.addStretch()
        main_layout.addLayout(right_layout)

        # 连接信号
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_download.clicked.connect(self._on_download)
        self.btn_edit.clicked.connect(self._on_edit)

        # 加载缩略图
        self._load_thumbnail()

    def _load_thumbnail(self):
        """加载缩略图"""
        try:
            uuid = self.asset_data.get("uuid", "")
            if not uuid:
                return
            local_path = os.path.join(os.getcwd(), "tmp", uuid)
            if not os.path.exists(local_path):
                return
            from core.ssh_upload_service import GetJsonFatherKey

            icon_path = GetJsonFatherKey(
                os.path.join(local_path, "epconfig.json"), "icon"
            )
            full_icon_path = os.path.join(local_path, icon_path)
            if os.path.exists(full_icon_path):
                pixmap = QPixmap(full_icon_path)
                scaled_pixmap = pixmap.scaled(
                    64,
                    64,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.thumbnail_label.setPixmap(scaled_pixmap)
            else:
                self.thumbnail_label.setText("无图")
        except Exception as e:
            self.thumbnail_label.setText("加载失败")
            logger.error(f"加载缩略图失败: {e}")

    def _on_delete(self):
        self.parent_page._on_delete_for_asset(self.asset_data)

    def _on_download(self):
        self.parent_page._on_download_for_asset(self.asset_data)

    def _on_edit(self):
        self.parent_page._on_edit_for_asset(self.asset_data)

    def set_buttons_enabled(self, enabled: bool):
        """设置按钮启用状态"""
        self.btn_delete.setEnabled(enabled)
        self.btn_download.setEnabled(enabled)
        self.btn_edit.setEnabled(enabled)


class RemotePage(QWidget):
    """
    远程管理页面 — 三栏布局

    左栏: 操作按钮（连接、刷新、上传）+ 素材列表
    中栏: 素材详细列表（缩略图、名称、UUID、路径 + 操作按钮）
    右栏: 操作日志
    """

    setting_changed = pyqtSignal(str, object)
    upload_requested = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ssh_config: dict = {}
        self._is_connected: bool = False
        self._is_busy: bool = False
        self._upload_worker = None
        self._list_worker = None
        self._delete_worker = None
        self._download_worker = None
        self._connect_worker = None
        self._restart_worker = None
        self._local_file_path = ""

        self._init_ui()
        self._connect_signals()

    # ─── UI 构建 ─────────────────────────────────────────

    def _init_ui(self):
        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(0, 15, 0, 0)
        self.mainLayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        # 标题
        self.titleLabel = SubtitleLabel("远程管理", self)
        self.titleLabel.setContentsMargins(30, 0, 0, 0)
        self.mainLayout.addWidget(self.titleLabel)
        self.mainLayout.addSpacing(10)

        # 三栏 Splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setContentsMargins(10, 0, 10, 10)

        self._build_left_panel()
        self._build_middle_panel()
        self._build_right_panel()

        self.splitter.addWidget(self.leftPanel)
        self.splitter.addWidget(self.middlePanel)
        self.splitter.addWidget(self.rightPanel)

        self.splitter.setSizes([240, 560, 300])
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setStretchFactor(2, 1)

        self.mainLayout.addWidget(self.splitter, 1)

        # 连接状态
        self.connectionStatusLabel = CaptionLabel("未连接")
        setCustomStyleSheet(
            self.connectionStatusLabel,
            "CaptionLabel { color: #999999; }",
            "CaptionLabel { color: #777777; }",
        )

        # 进度条
        self.progressBar = ProgressBar()
        self.progressBar.setVisible(False)

        self.progressLabel = CaptionLabel(" ")
        self.progressLabel.setWordWrap(True)

        self.wrapper = QVBoxLayout()
        self.wrapper.setContentsMargins(10, 0, 10, 0)  # 左偏移

        self.wrapper.addWidget(self.connectionStatusLabel)
        self.wrapper.addWidget(self.progressBar)
        self.wrapper.addWidget(self.progressLabel)

        self.mainLayout.addLayout(self.wrapper)
        # self.mainLayout.addWidget(self.progressLabel)

    def _build_left_panel(self):
        """左栏: 操作按钮 + 状态显示"""
        self.leftPanel = SimpleCardWidget()
        self.leftPanel.setMinimumWidth(230)
        self.leftPanel.setMaximumWidth(280)

        layout = QVBoxLayout(self.leftPanel)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 按钮
        self.btnConnect = PrimaryPushButton("连接")
        self.btnConnect.setIcon(FluentIcon.WIFI)
        layout.addWidget(self.btnConnect)

        self.btnRefreshList = PushButton("刷新远程素材列表")
        self.btnRefreshList.setIcon(FluentIcon.SYNC)
        self.btnRefreshList.setEnabled(False)
        layout.addWidget(self.btnRefreshList)

        self.btnUploadLocal = PushButton("上传本地素材")
        self.btnUploadLocal.setIcon(FluentIcon.SEND)
        self.btnUploadLocal.setEnabled(False)
        layout.addWidget(self.btnUploadLocal)

        self.btnRestartDrm = PushButton("重启DrmApp")
        self.btnRestartDrm.setIcon(FluentIcon.UPDATE)
        self.btnRestartDrm.setEnabled(False)
        layout.addWidget(self.btnRestartDrm)

        self.btnRemoteFileBrowser = PushButton("远程文件管理器")
        self.btnRemoteFileBrowser.setIcon(FluentIcon.FOLDER)
        self.btnRemoteFileBrowser.setEnabled(True)
        layout.addWidget(self.btnRemoteFileBrowser)

        # 分隔线
        line1 = QFrame()
        line1.setFrameShape(QFrame.Shape.HLine)
        line1.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line1)

    def _build_middle_panel(self):
        """中栏: 素材详细列表"""
        self.middlePanel = SimpleCardWidget()
        layout = QVBoxLayout(self.middlePanel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 标题
        self.middleTitleLabel = CaptionLabel("远程素材详情")
        layout.addWidget(self.middleTitleLabel)

        # 详细列表
        self.assetDetailList = ListWidget()
        self.assetDetailList.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        setCustomStyleSheet(
            self.assetDetailList,
            "ListWidget { border: none; background: transparent; }",
            "ListWidget { border: none; background: transparent; }",
        )
        layout.addWidget(self.assetDetailList, stretch=1)

    def _build_right_panel(self):
        """右栏: 操作日志"""
        self.rightPanel = SimpleCardWidget()
        layout = QVBoxLayout(self.rightPanel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.logTitleLabel = StrongBodyLabel("操作日志")
        layout.addWidget(self.logTitleLabel)

        self.logTextEdit = PlainTextEdit()
        self.logTextEdit.setReadOnly(True)
        self.logTextEdit.setMaximumBlockCount(1000)
        self.logTextEdit.setFont(QFont("Consolas", 10))
        setCustomStyleSheet(
            self.logTextEdit,
            "PlainTextEdit { border: none; padding: 8px; }",
            "PlainTextEdit { border: none; padding: 8px; }",
        )
        layout.addWidget(self.logTextEdit, stretch=1)

        self.btnClearLog = PushButton("清空日志")
        self.btnClearLog.setIcon(FluentIcon.DELETE)
        layout.addWidget(self.btnClearLog)

    # ─── 信号连接 ────────────────────────────────────────

    def _connect_signals(self):
        self.btnConnect.clicked.connect(self._on_connect)
        self.btnRefreshList.clicked.connect(self._on_refresh_list)
        self.btnRestartDrm.clicked.connect(self._on_restart_drm)
        self.btnUploadLocal.clicked.connect(self._on_upload_local)
        self.btnClearLog.clicked.connect(self.logTextEdit.clear)
        self.btnRemoteFileBrowser.clicked.connect(self._on_upload_remote_file)

    def _on_upload_remote_file(self):
        host, port, user, password, remote_path = self._get_ssh_params()
        from gui.widgets.RemoteFileManager import RemoteFileManagerWindow

        self.fileManager = RemoteFileManagerWindow(
            self, self.parent, host, port, user, password, remote_path
        )
        self.fileManager.show()
        return

    # ─── 日志 ────────────────────────────────────────────

    def _log(self, level: str, msg: str):
        """写入日志到 UI 和 Python logging"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] [{level}] {msg}"
        self.logTextEdit.appendPlainText(line)

        # 限制最大行数
        doc = self.logTextEdit.document()
        if doc.blockCount() > 1000:
            cursor = self.logTextEdit.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.movePosition(
                cursor.MoveOperation.Down,
                cursor.MoveMode.KeepAnchor,
                doc.blockCount() - 1000,
            )
            cursor.removeSelectedText()

        # 滚动到底部
        scrollbar = self.logTextEdit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        # Python logging
        log_func = getattr(logger, level.lower(), logger.info)
        log_func(msg)

    def _worker_log(self, level: str, msg: str):
        """Worker 日志信号的槽（在主线程执行）"""
        self._log(level, msg)

    # ─── 忙碌状态管理 ─────────────────────────────────────

    def _set_busy(self, busy: bool):
        self._is_busy = busy
        self.btnConnect.setEnabled(not busy)
        self.btnRefreshList.setEnabled(not busy and self._is_connected)
        self.btnUploadLocal.setEnabled(not busy and self._is_connected)
        self.btnRestartDrm.setEnabled(not busy and self._is_connected)
        # 设置中栏列表项按钮的启用状态
        for i in range(self.assetDetailList.count()):
            item = self.assetDetailList.item(i)
            widget = self.assetDetailList.itemWidget(item)
            if widget:
                widget.set_buttons_enabled(not busy)

    # ─── SSH 配置读取 ─────────────────────────────────────

    def _get_ssh_params(self):
        """从内部缓存获取 SSH 连接参数"""
        host = self._ssh_config.get("ssh_ip_address", "192.168.137.2")
        try:
            port = int(self._ssh_config.get("ssh_port", "22"))
        except ValueError:
            port = 22
        user = self._ssh_config.get("ssh_user", "root")
        password = self._ssh_config.get("ssh_password", "toor")
        remote_path = self._ssh_config.get("ssh_default_upload_path", "/assets/")
        return host, port, user, password, remote_path

    # ─── 连接 ────────────────────────────────────────────

    def _on_connect(self):
        if self._is_busy:
            return

        if self._is_connected:
            # 断开连接
            self._is_connected = False
            self._update_connection_ui()
            self._log("INFO", "已断开连接")
            return

        host, port, user, password, _ = self._get_ssh_params()
        self._set_busy(True)

        from core.ssh_upload_service import SshConnectTestWorker

        self._connect_worker = SshConnectTestWorker(parent=self)
        self._connect_worker.setup(host, port, user, password)
        self._connect_worker.log_message.connect(self._worker_log)
        self._connect_worker.connect_succeeded.connect(self._on_connect_success)
        self._connect_worker.connect_failed.connect(self._on_connect_fail)
        self._connect_worker.start()

    def _on_connect_success(self):
        self._is_connected = True
        self._update_connection_ui()
        self._set_busy(False)

    def _on_connect_fail(self, error: str):
        self._is_connected = False
        self._update_connection_ui()
        self._set_busy(False)
        InfoBar.error(
            "连接失败", error, parent=self, position=InfoBarPosition.TOP, duration=5000
        )

    def _update_connection_ui(self):
        if self._is_connected:
            self.connectionStatusLabel.setText("已连接")
            setCustomStyleSheet(
                self.connectionStatusLabel,
                "CaptionLabel { color: #4CAF50; }",
                "CaptionLabel { color: #66BB6A; }",
            )
            self.btnConnect.setText("断开")
            self.btnRefreshList.setEnabled(True)
            self.btnUploadLocal.setEnabled(True)
            self.btnRestartDrm.setEnabled(True)
        else:
            self.connectionStatusLabel.setText("未连接")
            setCustomStyleSheet(
                self.connectionStatusLabel,
                "CaptionLabel { color: #999999; }",
                "CaptionLabel { color: #777777; }",
            )
            self.btnConnect.setText("连接")
            self.btnRefreshList.setEnabled(False)
            self.btnUploadLocal.setEnabled(False)
            self.btnRestartDrm.setEnabled(False)
            # 断开时清空列表
            self.assetDetailList.clear()

    # ─── 刷新列表 ────────────────────────────────────────

    def _on_refresh_list(self):
        if self._is_busy or not self._is_connected:
            return

        host, port, user, password, remote_path = self._get_ssh_params()
        self._set_busy(True)

        from core.ssh_upload_service import SshRemoteListWorker

        self._list_worker = SshRemoteListWorker(parent=self)
        self._list_worker.setup(host, port, user, password, remote_path)
        self._list_worker.log_message.connect(self._worker_log)
        self._list_worker.list_completed.connect(self._on_list_loaded)
        self._list_worker.list_failed.connect(self._on_list_failed)
        self._list_worker.start()

    def _on_list_loaded(self, items: list):
        self.assetDetailList.clear()
        if not items:
            placeholder = QListWidgetItem("暂无远程素材")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.assetDetailList.addItem(placeholder)
        else:
            for item in items:
                # 中栏
                widget = AssetListItemWidget(item, self)
                list_item = QListWidgetItem(self.assetDetailList)
                list_item.setSizeHint(widget.sizeHint())
                self.assetDetailList.setItemWidget(list_item, widget)

        self._set_busy(False)
        if items:
            InfoBar.success(
                "列表已刷新",
                f"找到 {len(items)} 个素材包",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000,
            )
        else:
            InfoBar.info(
                "列表已刷新",
                "未找到远程素材",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000,
            )

    def _on_list_failed(self, error: str):
        self._set_busy(False)
        InfoBar.error(
            "获取列表失败",
            error,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000,
        )

    # ─── 预览 ────────────────────────────────────────────

    # ─── 上传 ────────────────────────────────────────────

    def _on_upload_local(self):
        if self._is_busy or not self._is_connected:
            return

        path = QFileDialog.getExistingDirectory(self, "选择要上传的素材目录", "")
        if not path:
            return

        self._local_file_path = path
        host, port, user, password, remote_path = self._get_ssh_params()
        enable_restart = self._ssh_config.get("ssh_auto_restart_program", False)

        self._set_busy(True)
        self.progressBar.setVisible(True)
        self.progressBar.setValue(0)

        from core.ssh_upload_service import SshUploadWorker

        self._upload_worker = SshUploadWorker(parent=self)
        self._upload_worker.setup(
            host, port, user, password, path, remote_path, enable_restart
        )
        self._upload_worker.progress_updated.connect(self._on_upload_progress)
        self._upload_worker.log_message.connect(self._worker_log)
        self._upload_worker.upload_completed.connect(self._on_upload_done)
        self._upload_worker.upload_failed.connect(self._on_upload_failed)
        self._upload_worker.start()
        self._log("INFO", f"开始上传: {os.path.basename(path)}")

    def _on_upload_progress(self, percent: int, message: str):
        self.progressBar.setValue(percent)
        self.progressLabel.setText(message)

    def _on_upload_done(self, message: str):
        self.progressBar.setValue(100)
        self.progressLabel.setText(message)
        self._set_busy(False)
        self._log("INFO", message)
        InfoBar.success(
            "上传成功",
            message,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000,
        )
        reply = QMessageBox.question(
            self,
            "上传成功",
            f"已上传\n是否重启DrmApp以应用更改？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        # 刷新列表
        if self._is_connected:
            self._on_refresh_list()

        # 重启
        if reply != QMessageBox.StandardButton.Yes:
            return
        import threading

        t = threading.Thread(target=self.restart_drm_worker, daemon=True)
        t.start()

    def _on_upload_failed(self, error: str):
        self.progressBar.setVisible(False)
        self.progressLabel.setText("")
        self._set_busy(False)
        self._log("ERROR", f"上传失败: {error}")
        InfoBar.error(
            "上传失败", error, parent=self, position=InfoBarPosition.TOP, duration=5000
        )

    def _on_delete_done(self, name: str):
        self._set_busy(False)
        InfoBar.success(
            "删除成功",
            f"已删除: {name}",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3000,
        )
        reply = QMessageBox.question(
            self,
            "删除成功",
            f"已删除: {name}\n是否重启DrmApp以应用更改？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        # 刷新列表
        if self._is_connected:
            self._on_refresh_list()

        # 重启
        if reply != QMessageBox.StandardButton.Yes:
            return
        import threading

        t = threading.Thread(target=self.restart_drm_worker, daemon=True)
        t.start()

    def _on_restart_drm(self):
        import threading

        t = threading.Thread(target=self.restart_drm_worker, daemon=True)
        t.start()
        return

    def restart_drm_worker(self):
        try:
            import paramiko

            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            host, port, user, password, remote_path = self._get_ssh_params()
            ssh.connect(
                host,
                port=port,
                username=user,
                password=password,
                timeout=10,
                banner_timeout=10,
                auth_timeout=10,
            )
            from core.sshOperation import StopDrmApp, StartDrmApp

            self._log("INFO", f"开始重启DrmApp...")
            StopDrmApp(ssh)
            self._log("INFO", f"DrmApp 已停止，正在启动...")
            StartDrmApp(ssh)
            self._log("INFO", f"已发送重启指令")
        except Exception as e:
            InfoBar.error(
                "重启失败",
                f"重启失败：\n{e}",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=5000,
            )
        return

    def _on_delete_failed(self, error: str):
        self._set_busy(False)
        InfoBar.error(
            "删除失败", error, parent=self, position=InfoBarPosition.TOP, duration=5000
        )

    def _on_delete_for_asset(self, asset_data: dict):
        if self._is_busy:
            return

        name = asset_data.get("name", "Unknown")
        uuid = asset_data.get("uuid", "Unknown")
        path = asset_data.get("path", "Unknown")
        reply = QMessageBox.question(
            self,
            "确认删除",
            f'确定要删除远程素材 "{name}" 吗？\nUUID = {uuid}\n{path}\n此操作不可撤销。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        host, port, user, password, remote_path = self._get_ssh_params()
        self._set_busy(True)

        from core.ssh_upload_service import SshDeleteWorker

        self._delete_worker = SshDeleteWorker(parent=self)
        self._delete_worker.setup(
            host, port, user, password, remote_path, name, uuid, path
        )
        self._delete_worker.log_message.connect(self._worker_log)
        self._delete_worker.delete_completed.connect(self._on_delete_done)
        self._delete_worker.delete_failed.connect(self._on_delete_failed)
        self._delete_worker.start()

    # ─── 下载 ────────────────────────────────────────────

    def _on_download(self):
        if self._is_busy:
            return

        name = self._get_selected_asset_name()
        if not name:
            return

        save_dir = QFileDialog.getExistingDirectory(self, "选择保存位置")
        if not save_dir:
            return

        host, port, user, password, remote_path = self._get_ssh_params()
        self._set_busy(True)
        self.progressBar.setVisible(True)
        self.progressBar.setValue(0)

        from core.ssh_upload_service import SshDownloadWorker

        self._download_worker = SshDownloadWorker(parent=self)
        self._download_worker.setup(
            host, port, user, password, remote_path, name, save_dir
        )
        self._download_worker.log_message.connect(self._worker_log)
        self._download_worker.progress_updated.connect(self._on_download_progress)
        self._download_worker.download_completed.connect(self._on_download_done)
        self._download_worker.download_failed.connect(self._on_download_failed)
        self._download_worker.start()

    def _on_download_progress(self, percent: int, message: str):
        self.progressBar.setValue(percent)
        self.progressLabel.setText(message)

    def _on_download_done(self, local_path: str):
        self.progressBar.setVisible(False)
        self.progressLabel.setText("")
        self._set_busy(False)
        self._log("INFO", f"下载完成: {local_path}")
        InfoBar.success(
            "下载成功",
            f"已保存到: {local_path}",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000,
        )

    def _on_download_failed(self, error: str):
        self.progressBar.setVisible(False)
        self.progressLabel.setText("")
        self._set_busy(False)
        self._log("ERROR", f"下载失败: {error}")
        InfoBar.error(
            "下载失败", error, parent=self, position=InfoBarPosition.TOP, duration=5000
        )

    def _on_download_for_asset(self, asset_data: dict):
        if self._is_busy:
            return

        name = asset_data.get("name", "Unknown")
        remotePath = asset_data.get("path", "Unknown")
        save_dir = QFileDialog.getExistingDirectory(self, "选择保存位置")
        if not save_dir:
            return

        host, port, user, password, remote_path = self._get_ssh_params()
        self._set_busy(True)
        self.progressBar.setVisible(True)
        self.progressBar.setValue(0)

        from core.ssh_upload_service import SshDownloadWorker

        self._download_worker = SshDownloadWorker(parent=self)
        self._download_worker.setup(
            host, port, user, password, remote_path, name, save_dir, remotePath
        )
        self._download_worker.log_message.connect(self._worker_log)
        self._download_worker.progress_updated.connect(self._on_download_progress)
        self._download_worker.download_completed.connect(self._on_download_done)
        self._download_worker.download_failed.connect(self._on_download_failed)
        self._download_worker.start()

    # ─── 编辑（下载后用主窗口打开）─────────────────────────

    def _on_edit(self):
        if self._is_busy:
            return

        name = self._get_selected_asset_name()
        if not name:
            return

        # 下载到临时目录，完成后通知主窗口打开
        temp_dir = tempfile.mkdtemp(prefix="neo_asset_edit_")
        host, port, user, password, remote_path = self._get_ssh_params()
        self._set_busy(True)
        self.progressBar.setVisible(True)
        self.progressBar.setValue(0)

        from core.ssh_upload_service import SshDownloadWorker

        self._download_worker = SshDownloadWorker(parent=self)
        self._download_worker.setup(
            host, port, user, password, remote_path, name, temp_dir
        )
        self._download_worker.log_message.connect(self._worker_log)
        self._download_worker.progress_updated.connect(self._on_download_progress)
        self._download_worker.download_completed.connect(self._on_edit_download_done)
        self._download_worker.download_failed.connect(self._on_download_failed)
        self._download_worker.start()

    def _on_edit_download_done(self, local_path: str):
        self.progressBar.setVisible(False)
        self.progressLabel.setText("")
        self._set_busy(False)
        self._log("INFO", f"编辑素材已下载到: {local_path}")

        # 尝试通知主窗口打开
        self.parent = self.window()
        if hasattr(self.parent, "_open_project"):
            # 查找 JSON 配置文件
            json_files = [f for f in os.listdir(local_path) if f.endswith(".json")]
            if json_files:
                json_path = os.path.join(local_path, json_files[0])
                self.parent._open_project(json_path)
                self._log("INFO", f"已在主窗口中打开: {json_files[0]}")
            else:
                self._log("WARNING", "素材包中未找到 JSON 配置文件")
                InfoBar.warning(
                    "提示",
                    "素材包中未找到 JSON 配置文件",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=5000,
                )
        else:
            InfoBar.info(
                "提示",
                f"素材已下载到: {local_path}",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=5000,
            )

            # 查找 JSON 配置目录
            json_dirs = self.ListChildrenDirs(local_path)
            if not json_dirs:
                self._log("WARNING", "素材包中未找到 JSON 配置目录")
                return

            json_config_path = os.path.join(json_dirs[0], "epconfig.json")

            # 发送配置路径给主窗口（在主窗口支持相关接口的情况下）
            if (
                self.parent is not None
                and hasattr(self.parent, "ReadProjectFromJson")
                and hasattr(self.parent, "_on_sidebar_material")
            ):
                try:
                    self.parent.ReadProjectFromJson(json_config_path)
                    self.parent._on_sidebar_material()
                except Exception as exc:
                    logger.exception("打开素材配置失败: %s", exc)
                    self._log("ERROR", f"打开素材配置失败: {exc}")
            else:
                self._log("WARNING", "主窗口不支持从 JSON 打开素材配置")

    def _on_edit_for_asset(self, asset_data: dict):
        if self._is_busy:
            return

        name = asset_data.get("name", "Unknown")
        remoteAbsPath = asset_data.get("path", "")
        # 下载到临时目录，完成后通知主窗口打开
        temp_dir = tempfile.mkdtemp(prefix="neo_asset_edit_")
        host, port, user, password, remote_path = self._get_ssh_params()
        self._set_busy(True)
        self.progressBar.setVisible(True)
        self.progressBar.setValue(0)

        from core.ssh_upload_service import SshDownloadWorker

        self._download_worker = SshDownloadWorker(parent=self)
        self._download_worker.setup(
            host, port, user, password, remote_path, name, temp_dir, remoteAbsPath
        )
        self._download_worker.log_message.connect(self._worker_log)
        self._download_worker.progress_updated.connect(self._on_download_progress)
        self._download_worker.download_completed.connect(self._on_edit_download_done)
        self._download_worker.download_failed.connect(self._on_download_failed)
        self._download_worker.start()

    # ─── 公共接口 ────────────────────────────────────────

    def load_settings(self, settings: dict):
        """从 dict 加载 SSH 配置"""
        self._ssh_config = settings.copy()

    def shutdown(self):
        """关闭页面，取消所有进行中的操作"""
        workers = [
            self._upload_worker,
            self._list_worker,
            self._delete_worker,
            self._download_worker,
            self._connect_worker,
        ]
        for w in workers:
            if w and w.isRunning():
                if hasattr(w, "cancel"):
                    w.cancel()
                w.wait(3000)

    def ListChildrenDirs(self, path: str) -> list[str]:
        """
        返回指定路径下的所有子目录（不递归）
        """
        try:
            return [
                os.path.join(path, name)
                for name in os.listdir(path)
                if os.path.isdir(os.path.join(path, name))
            ]
        except FileNotFoundError:
            return []
        except PermissionError:
            return []
