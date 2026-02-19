"""
更新对话框 - 检查更新、显示更新内容、下载进度
"""
import os
import sys
import subprocess
import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QTextBrowser, QFrame,
    QMessageBox, QStackedWidget, QWidget
)
from PyQt6.QtCore import Qt
from qfluentwidgets import (
    PushButton, PrimaryPushButton, SubtitleLabel, StrongBodyLabel, BodyLabel,
    ProgressBar
)

from core.update_service import UpdateService, ReleaseInfo
from config.constants import APP_VERSION

logger = logging.getLogger(__name__)


class UpdateDialog(QDialog):
    """更新对话框 - 支持三种状态：检查中、有更新、下载中"""

    def __init__(self, parent=None, auto_check: bool = False):
        super().__init__(parent)
        self._auto_check = auto_check
        self._update_service = UpdateService(APP_VERSION, self)
        self._downloaded_path: Optional[str] = None

        self._setup_ui()
        self._connect_signals()

        if auto_check:
            # Auto start check when dialog opens
            self._start_check()

    def _setup_ui(self):
        """Setup the UI"""
        self.setWindowTitle("检查更新")
        self.setMinimumSize(500, 400)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Stacked widget for different states
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        # Page 0: Checking for updates
        self._create_checking_page()

        # Page 1: Update available
        self._create_update_available_page()

        # Page 2: No update / error
        self._create_no_update_page()

        # Page 3: Downloading
        self._create_downloading_page()

        # Page 4: Download complete
        self._create_download_complete_page()

        # Bottom buttons (common)
        self.btn_layout = QHBoxLayout()
        self.btn_layout.addStretch()

        self.btn_close = PushButton("关闭")
        self.btn_close.clicked.connect(self.reject)
        self.btn_layout.addWidget(self.btn_close)

        layout.addLayout(self.btn_layout)

    def _create_checking_page(self):
        """Page 0: Checking for updates"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.label_checking = SubtitleLabel("正在检查更新...")
        self.label_checking.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label_checking)

        self.progress_checking = ProgressBar()
        self.progress_checking.setRange(0, 0)  # Indeterminate
        self.progress_checking.setMaximumWidth(300)
        layout.addWidget(self.progress_checking, alignment=Qt.AlignmentFlag.AlignCenter)

        self.label_checking_detail = BodyLabel("连接到 GitHub...")
        self.label_checking_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label_checking_detail)

        self.stack.addWidget(page)

    def _create_update_available_page(self):
        """Page 1: Update available"""
        page = QWidget()
        layout = QVBoxLayout(page)

        # Header
        header_layout = QHBoxLayout()

        self.label_new_version = SubtitleLabel("发现新版本!")
        self.label_new_version.setStyleSheet("color: #4CAF50;")
        header_layout.addWidget(self.label_new_version)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Version info
        self.label_version_info = BodyLabel()
        self.label_version_info.setStyleSheet("font-size: 13px;")
        layout.addWidget(self.label_version_info)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        # Changelog label
        changelog_label = StrongBodyLabel("更新内容:")
        layout.addWidget(changelog_label)

        # Changelog content (markdown rendered as HTML)
        self.text_changelog = QTextBrowser()
        self.text_changelog.setOpenExternalLinks(True)
        self.text_changelog.setStyleSheet(
            "QTextBrowser { "
            "background-color: #f5f5f5; "
            "color: #333333; "
            "border: 1px solid #ddd; "
            "border-radius: 4px; "
            "padding: 8px; "
            "}"
        )
        layout.addWidget(self.text_changelog, stretch=1)

        # Download button - Use Fluent widgets
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_download = PrimaryPushButton("下载更新")
        self.btn_download.clicked.connect(self._start_download)
        btn_layout.addWidget(self.btn_download)

        self.btn_skip = PushButton("稍后提醒")
        self.btn_skip.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_skip)

        layout.addLayout(btn_layout)

        self.stack.addWidget(page)

    def _create_no_update_page(self):
        """Page 2: No update available / Error"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.label_status = SubtitleLabel("当前已是最新版本")
        self.label_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label_status)

        self.label_current_version = BodyLabel(f"当前版本: v{APP_VERSION}")
        self.label_current_version.setStyleSheet("font-size: 13px;")
        self.label_current_version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label_current_version)

        self.stack.addWidget(page)

    def _create_downloading_page(self):
        """Page 3: Downloading"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.label_downloading = SubtitleLabel("正在下载更新...")
        self.label_downloading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label_downloading)

        self.progress_download = ProgressBar()
        self.progress_download.setRange(0, 100)
        self.progress_download.setMinimumWidth(350)
        layout.addWidget(self.progress_download, alignment=Qt.AlignmentFlag.AlignCenter)

        self.label_download_detail = BodyLabel("")
        self.label_download_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label_download_detail)

        # Cancel button - Use Fluent PushButton
        self.btn_cancel_download = PushButton("取消下载")
        self.btn_cancel_download.clicked.connect(self._cancel_download)
        layout.addWidget(self.btn_cancel_download, alignment=Qt.AlignmentFlag.AlignCenter)

        self.stack.addWidget(page)

    def _create_download_complete_page(self):
        """Page 4: Download complete"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.label_complete = SubtitleLabel("下载完成!")
        self.label_complete.setStyleSheet("color: #4CAF50;")
        self.label_complete.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label_complete)

        self.label_install_hint = QLabel(
            "点击\"立即安装\"将关闭程序并启动安装程序。\n"
            "安装完成后请重新启动应用。"
        )
        self.label_install_hint.setStyleSheet("color: #666;")
        self.label_install_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label_install_hint)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_install = PrimaryPushButton("立即安装")
        self.btn_install.clicked.connect(self._run_installer)
        btn_layout.addWidget(self.btn_install)

        self.btn_install_later = PushButton("稍后安装")
        self.btn_install_later.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_install_later)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.stack.addWidget(page)

    def _connect_signals(self):
        """Connect update service signals"""
        self._update_service.check_started.connect(self._on_check_started)
        self._update_service.check_completed.connect(self._on_check_completed)
        self._update_service.check_failed.connect(self._on_check_failed)

        self._update_service.download_started.connect(self._on_download_started)
        self._update_service.download_progress.connect(self._on_download_progress)
        self._update_service.download_completed.connect(self._on_download_completed)
        self._update_service.download_failed.connect(self._on_download_failed)

    def _start_check(self):
        """Start checking for updates"""
        self.stack.setCurrentIndex(0)  # Show checking page
        self.btn_close.setEnabled(True)
        self._update_service.check_for_updates()

    def _on_check_started(self):
        """Called when check starts"""
        self.label_checking_detail.setText("连接到 GitHub...")

    def _on_check_completed(self, release_info: Optional[ReleaseInfo]):
        """Called when check completes"""
        if release_info:
            # Update available
            self.label_version_info.setText(
                f"当前版本: v{APP_VERSION}  →  新版本: v{release_info.version}"
            )

            # Convert markdown to simple HTML (basic conversion)
            changelog = release_info.body or "暂无更新说明"

            # 解析 changelog，只显示当前版本内容
            # 假设格式为 "## v1.x.x" 或 "# v1.x.x" 开头的段落
            lines = changelog.split('\n')
            result_lines = []
            found_first_version = False
            for line in lines:
                # 检测版本标题（## v1.x.x 或 # v1.x.x）
                if line.strip().startswith('#') and 'v' in line.lower():
                    if found_first_version:
                        break  # 遇到下一个版本标题，停止
                    found_first_version = True
                if found_first_version:
                    result_lines.append(line)

            changelog = '\n'.join(result_lines) if result_lines else changelog

            # Basic markdown to HTML conversion
            changelog = changelog.replace('\n\n', '</p><p>')
            changelog = changelog.replace('\n', '<br>')
            changelog = f"<p>{changelog}</p>"
            self.text_changelog.setHtml(changelog)

            self.stack.setCurrentIndex(1)  # Show update available page
        else:
            # No update
            self.label_status.setText("当前已是最新版本")
            self.label_status.setStyleSheet(
                "font-size: 16px; font-weight: bold; color: #4CAF50;"
            )
            self.stack.setCurrentIndex(2)  # Show no update page

    def _on_check_failed(self, error_msg: str):
        """Called when check fails"""
        self.label_status.setText("检查更新失败")
        self.label_status.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #f44336;"
        )
        self.label_current_version.setText(error_msg)
        self.stack.setCurrentIndex(2)  # Show error on no-update page

    def _start_download(self):
        """Start downloading update"""
        self.stack.setCurrentIndex(3)  # Show downloading page
        self.btn_close.setEnabled(False)
        self._update_service.download_update()

    def _cancel_download(self):
        """Cancel download"""
        self._update_service.cancel_download()
        self.btn_close.setEnabled(True)

    def _on_download_started(self):
        """Called when download starts"""
        self.progress_download.setValue(0)
        self.label_download_detail.setText("准备下载...")

    def _on_download_progress(self, percent: int, message: str):
        """Called during download"""
        self.progress_download.setValue(percent)
        self.label_download_detail.setText(message)

    def _on_download_completed(self, file_path: str):
        """Called when download completes"""
        self._downloaded_path = file_path
        self.btn_close.setEnabled(True)
        self.stack.setCurrentIndex(4)  # Show download complete page

    def _on_download_failed(self, error_msg: str):
        """Called when download fails"""
        self.btn_close.setEnabled(True)
        QMessageBox.critical(self, "下载失败", error_msg)
        self.stack.setCurrentIndex(1)  # Go back to update available page

    def _run_installer(self):
        """Run the downloaded installer"""
        if not self._downloaded_path or not os.path.exists(self._downloaded_path):
            QMessageBox.critical(self, "错误", "安装文件不存在")
            return

        try:
            # Start installer in detached process
            if sys.platform == 'win32':
                subprocess.Popen(
                    [self._downloaded_path],
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:
                subprocess.Popen([self._downloaded_path])

            # Signal to close the application
            self.accept()

            # Get main window and close it
            if self.parent():
                self.parent().close()

        except Exception as e:
            logger.exception("启动安装程序失败")
            QMessageBox.critical(self, "错误", f"启动安装程序失败:\n{str(e)}")

    def check_updates(self):
        """Public method to start update check"""
        self._start_check()

    def closeEvent(self, event):
        """Handle close event"""
        if self._update_service.is_downloading:
            result = QMessageBox.question(
                self, "确认",
                "正在下载更新，确定要取消吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if result == QMessageBox.StandardButton.No:
                event.ignore()
                return
            self._update_service.cancel_download()
        event.accept()
