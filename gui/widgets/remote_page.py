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
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QFileDialog, QLabel, QFrame, QListWidgetItem,
    QMessageBox,
)

from qfluentwidgets import (
    SimpleCardWidget,
    SubtitleLabel, StrongBodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton,
    ProgressBar, ListWidget, PlainTextEdit,
    FluentIcon, InfoBar, InfoBarPosition,
    setCustomStyleSheet,
)

from gui.styles import COLOR_PREVIEW_BG

logger = logging.getLogger(__name__)


class RemotePage(QWidget):
    """
    远程管理页面 — 三栏布局（应该是能用的吧，啊哈哈......）

    左栏: 操作按钮（连接、刷新、上传）+ 素材列表
    中栏: 预览显示 + 操作按钮（删除、下载、编辑）
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
        self._preview_worker = None
        self._connect_worker = None
        self._local_file_path = ""

        self._init_ui()
        self._connect_signals()

    # ─── UI 构建 ─────────────────────────────────────────

    def _init_ui(self):
        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(0, 15, 0, 0)

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

        self.mainLayout.addWidget(self.splitter)

    def _build_left_panel(self):
        """左栏: 操作按钮 + 素材列表"""
        self.leftPanel = SimpleCardWidget()
        self.leftPanel.setMinimumWidth(230)
        self.leftPanel.setMaximumWidth(280)

        layout = QVBoxLayout(self.leftPanel)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

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

        # 分隔线
        line1 = QFrame()
        line1.setFrameShape(QFrame.Shape.HLine)
        line1.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line1)

        # 连接状态
        self.connectionStatusLabel = CaptionLabel("未连接")
        setCustomStyleSheet(
            self.connectionStatusLabel,
            "CaptionLabel { color: #999999; }",
            "CaptionLabel { color: #777777; }",
        )
        layout.addWidget(self.connectionStatusLabel)

        # 进度条
        self.progressBar = ProgressBar()
        self.progressBar.setVisible(False)
        layout.addWidget(self.progressBar)

        self.progressLabel = CaptionLabel("")
        layout.addWidget(self.progressLabel)

        # 分隔线 2 — 分隔状态区和列表区
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line2)

        # 远程素材列表
        self.assetListLabel = CaptionLabel("远程素材")
        layout.addWidget(self.assetListLabel)

        self.remoteAssetList = ListWidget()
        self.remoteAssetList.setTextElideMode(
            Qt.TextElideMode.ElideMiddle)
        # 去除 ListWidget 默认边框，融入 SimpleCardWidget
        setCustomStyleSheet(
            self.remoteAssetList,
            "ListWidget { border: none; background: transparent; }",
            "ListWidget { border: none; background: transparent; }",
        )
        layout.addWidget(self.remoteAssetList, stretch=1)

    def _build_middle_panel(self):
        """中栏: 预览显示 + 操作按钮"""
        self.middlePanel = QWidget()
        layout = QVBoxLayout(self.middlePanel)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(8)

        # 预览容器（SimpleCardWidget，无 hover 动画）
        self.previewContainer = SimpleCardWidget()
        previewLayout = QVBoxLayout(self.previewContainer)
        previewLayout.setContentsMargins(10, 10, 10, 10)
        previewLayout.setSpacing(8)

        # 选中素材名称标签
        self.previewNameLabel = CaptionLabel("")
        self.previewNameLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        previewLayout.addWidget(self.previewNameLabel)

        # 预览图片显示
        self.previewLabel = QLabel()
        self.previewLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.previewLabel.setMinimumHeight(250)
        self.previewLabel.setText("选择素材以预览")
        setCustomStyleSheet(
            self.previewLabel,
            f"QLabel {{ color: #888888; font-size: 13px;"
            f" background-color: {COLOR_PREVIEW_BG[0]};"
            f" border-radius: 8px; }}",
            f"QLabel {{ color: #666666; font-size: 13px;"
            f" background-color: {COLOR_PREVIEW_BG[1]};"
            f" border-radius: 8px; }}",
        )
        previewLayout.addWidget(self.previewLabel, stretch=1)

        # 操作按钮行（在预览容器内部）
        actionLayout = QHBoxLayout()
        actionLayout.setSpacing(8)

        self.btnDelete = PushButton("删除")
        self.btnDelete.setIcon(FluentIcon.DELETE)
        self.btnDelete.setEnabled(False)

        self.btnDownload = PushButton("下载")
        self.btnDownload.setIcon(FluentIcon.DOWNLOAD)
        self.btnDownload.setEnabled(False)

        self.btnEdit = PushButton("编辑")
        self.btnEdit.setIcon(FluentIcon.EDIT)
        self.btnEdit.setEnabled(False)

        actionLayout.addWidget(self.btnDelete)
        actionLayout.addWidget(self.btnDownload)
        actionLayout.addWidget(self.btnEdit)
        previewLayout.addLayout(actionLayout)

        layout.addWidget(self.previewContainer, stretch=1)

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
        self.btnUploadLocal.clicked.connect(self._on_upload_local)
        self.btnDelete.clicked.connect(self._on_delete)
        self.btnDownload.clicked.connect(self._on_download)
        self.btnEdit.clicked.connect(self._on_edit)
        self.btnClearLog.clicked.connect(self.logTextEdit.clear)
        self.remoteAssetList.currentItemChanged.connect(self._on_asset_selected)

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
            cursor.movePosition(cursor.MoveOperation.Down,
                                cursor.MoveMode.KeepAnchor, doc.blockCount() - 1000)
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
        has_selection = self.remoteAssetList.currentItem() is not None
        self.btnDelete.setEnabled(not busy and has_selection)
        self.btnDownload.setEnabled(not busy and has_selection)
        self.btnEdit.setEnabled(not busy and has_selection)

    # ─── SSH 配置读取 ─────────────────────────────────────

    def _get_ssh_params(self):
        """从内部缓存获取 SSH 连接参数"""
        host = self._ssh_config.get('ssh_ip_address', '192.168.137.2')
        try:
            port = int(self._ssh_config.get('ssh_port', '22'))
        except ValueError:
            port = 22
        user = self._ssh_config.get('ssh_user', 'root')
        password = self._ssh_config.get('ssh_password', 'toor')
        remote_path = self._ssh_config.get('ssh_default_upload_path', '/assets/')
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
        InfoBar.error("连接失败", error, parent=self,
                      position=InfoBarPosition.TOP, duration=5000)

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
            # 断开时清空列表和预览
            self.remoteAssetList.clear()
            self.previewNameLabel.setText("")
            self.previewLabel.setPixmap(QPixmap())
            self.previewLabel.setText("选择素材以预览")

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
        self.remoteAssetList.clear()
        if not items:
            placeholder = QListWidgetItem("暂无远程素材")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.remoteAssetList.addItem(placeholder)
        else:
            for item in items:
                li = QListWidgetItem(item["name"])
                li.setData(Qt.ItemDataRole.UserRole, item)
                li.setToolTip(f"大小: {item['size']} | 修改日期: {item['date']}")
                self.remoteAssetList.addItem(li)

        self._set_busy(False)
        if items:
            InfoBar.success("列表已刷新", f"找到 {len(items)} 个素材包",
                            parent=self, position=InfoBarPosition.TOP, duration=3000)
        else:
            InfoBar.info("列表已刷新", "未找到远程素材",
                         parent=self, position=InfoBarPosition.TOP, duration=3000)

    def _on_list_failed(self, error: str):
        self._set_busy(False)
        InfoBar.error("获取列表失败", error, parent=self,
                      position=InfoBarPosition.TOP, duration=5000)

    # ─── 素材选中 ────────────────────────────────────────

    def _on_asset_selected(self, current, previous):
        has_selection = current is not None and (current.flags() & Qt.ItemFlag.ItemIsSelectable)

        if not self._is_busy:
            self.btnDelete.setEnabled(has_selection)
            self.btnDownload.setEnabled(has_selection)
            self.btnEdit.setEnabled(has_selection)

        if has_selection:
            name = current.text()
            self.previewNameLabel.setText(f"正在预览: {name}")
            self._load_preview(name)
        else:
            self.previewNameLabel.setText("")
            self.previewLabel.setPixmap(QPixmap())
            self.previewLabel.setText("选择素材以预览")

    def _get_selected_asset_name(self) -> str:
        item = self.remoteAssetList.currentItem()
        if item and (item.flags() & Qt.ItemFlag.ItemIsSelectable):
            return item.text()
        return ""

    # ─── 预览 ────────────────────────────────────────────

    def _load_preview(self, asset_name: str):
        host, port, user, password, remote_path = self._get_ssh_params()

        from core.ssh_upload_service import SshPreviewWorker
        self._preview_worker = SshPreviewWorker(parent=self)
        self._preview_worker.setup(host, port, user, password, remote_path, asset_name)
        self._preview_worker.preview_ready.connect(self._on_preview_ready)
        self._preview_worker.preview_failed.connect(self._on_preview_failed)
        self._preview_worker.start()

    def _on_preview_ready(self, data: bytes):
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                self.previewLabel.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.previewLabel.setPixmap(scaled)
            self.previewLabel.setText("")
        else:
            self.previewLabel.setText("无法解析图片")

    def _on_preview_failed(self, error: str):
        self.previewLabel.setPixmap(QPixmap())
        self.previewLabel.setText(f"无预览 ({error})")

    # ─── 上传 ────────────────────────────────────────────

    def _on_upload_local(self):
        if self._is_busy or not self._is_connected:
            return

        path = QFileDialog.getExistingDirectory(
            self, "选择要上传的素材目录", "")
        if not path:
            return

        self._local_file_path = path
        host, port, user, password, remote_path = self._get_ssh_params()
        enable_restart = self._ssh_config.get('ssh_auto_restart_program', False)

        self._set_busy(True)
        self.progressBar.setVisible(True)
        self.progressBar.setValue(0)

        from core.ssh_upload_service import SshUploadWorker
        self._upload_worker = SshUploadWorker(parent=self)
        self._upload_worker.setup(host, port, user, password, path,
                                  remote_path, enable_restart)
        self._upload_worker.progress_updated.connect(self._on_upload_progress)
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
        InfoBar.success("上传成功", message, parent=self,
                        position=InfoBarPosition.TOP, duration=5000)
        # 自动刷新列表
        if self._is_connected:
            self._on_refresh_list()

    def _on_upload_failed(self, error: str):
        self.progressBar.setVisible(False)
        self.progressLabel.setText("")
        self._set_busy(False)
        self._log("ERROR", f"上传失败: {error}")
        InfoBar.error("上传失败", error, parent=self,
                      position=InfoBarPosition.TOP, duration=5000)

    # ─── 删除 ────────────────────────────────────────────

    def _on_delete(self):
        if self._is_busy:
            return

        name = self._get_selected_asset_name()
        if not name:
            return

        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除远程素材 \"{name}\" 吗？\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        host, port, user, password, remote_path = self._get_ssh_params()
        self._set_busy(True)

        from core.ssh_upload_service import SshDeleteWorker
        self._delete_worker = SshDeleteWorker(parent=self)
        self._delete_worker.setup(host, port, user, password, remote_path, name)
        self._delete_worker.log_message.connect(self._worker_log)
        self._delete_worker.delete_completed.connect(self._on_delete_done)
        self._delete_worker.delete_failed.connect(self._on_delete_failed)
        self._delete_worker.start()

    def _on_delete_done(self, name: str):
        self._set_busy(False)
        InfoBar.success("删除成功", f"已删除: {name}", parent=self,
                        position=InfoBarPosition.TOP, duration=3000)
        # 刷新列表
        if self._is_connected:
            self._on_refresh_list()

    def _on_delete_failed(self, error: str):
        self._set_busy(False)
        InfoBar.error("删除失败", error, parent=self,
                      position=InfoBarPosition.TOP, duration=5000)

    # ─── 下载 ────────────────────────────────────────────

    def _on_download(self):
        if self._is_busy:
            return

        name = self._get_selected_asset_name()
        if not name:
            return

        save_dir = QFileDialog.getExistingDirectory(
            self, "选择保存位置")
        if not save_dir:
            return

        host, port, user, password, remote_path = self._get_ssh_params()
        self._set_busy(True)
        self.progressBar.setVisible(True)
        self.progressBar.setValue(0)

        from core.ssh_upload_service import SshDownloadWorker
        self._download_worker = SshDownloadWorker(parent=self)
        self._download_worker.setup(host, port, user, password,
                                    remote_path, name, save_dir)
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
        InfoBar.success("下载成功", f"已保存到: {local_path}", parent=self,
                        position=InfoBarPosition.TOP, duration=5000)

    def _on_download_failed(self, error: str):
        self.progressBar.setVisible(False)
        self.progressLabel.setText("")
        self._set_busy(False)
        self._log("ERROR", f"下载失败: {error}")
        InfoBar.error("下载失败", error, parent=self,
                      position=InfoBarPosition.TOP, duration=5000)

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
        self._download_worker.setup(host, port, user, password,
                                    remote_path, name, temp_dir)
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
        main_window = self.window()
        if hasattr(main_window, '_open_project'):
            # 查找 JSON 配置文件
            json_files = [f for f in os.listdir(local_path) if f.endswith('.json')]
            if json_files:
                json_path = os.path.join(local_path, json_files[0])
                main_window._open_project(json_path)
                self._log("INFO", f"已在主窗口中打开: {json_files[0]}")
            else:
                self._log("WARNING", "素材包中未找到 JSON 配置文件")
                InfoBar.warning("提示", "素材包中未找到 JSON 配置文件",
                                parent=self, position=InfoBarPosition.TOP,
                                duration=5000)
        else:
            InfoBar.info("提示", f"素材已下载到: {local_path}",
                         parent=self, position=InfoBarPosition.TOP,
                         duration=5000)

    # ─── 公共接口 ────────────────────────────────────────

    def load_settings(self, settings: dict):
        """从 dict 加载 SSH 配置"""
        self._ssh_config = settings.copy()

    def shutdown(self):
        """关闭页面，取消所有进行中的操作"""
        workers = [
            self._upload_worker, self._list_worker,
            self._delete_worker, self._download_worker,
            self._preview_worker, self._connect_worker,
        ]
        for w in workers:
            if w and w.isRunning():
                if hasattr(w, 'cancel'):
                    w.cancel()
                w.wait(3000)
