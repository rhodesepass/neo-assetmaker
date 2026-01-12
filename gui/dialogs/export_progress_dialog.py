"""
导出进度对话框
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar,
    QPushButton
)
from PyQt6.QtCore import Qt, pyqtSignal


class ExportProgressDialog(QDialog):
    """导出进度对话框"""

    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_completed = False
        self._setup_ui()

    def _setup_ui(self):
        """设置UI"""
        self.setWindowTitle("导出素材")
        self.setMinimumSize(400, 150)
        self.setModal(True)
        # 禁用关闭按钮
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # 状态标签
        self.label_status = QLabel("准备导出...")
        self.label_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_status.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self.label_status)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        # 详细信息标签
        self.label_detail = QLabel("")
        self.label_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_detail.setStyleSheet("color: #666;")
        layout.addWidget(self.label_detail)

        # 按钮
        self.btn_action = QPushButton("取消")
        self.btn_action.clicked.connect(self._on_action_clicked)
        layout.addWidget(self.btn_action)

    def update_progress(self, value: int, message: str):
        """更新进度"""
        self.progress_bar.setValue(value)
        self.label_detail.setText(message)

    def set_completed(self, success: bool, message: str):
        """设置完成状态"""
        self._is_completed = True
        self.progress_bar.setValue(100 if success else self.progress_bar.value())
        self.label_status.setText("导出完成!" if success else "导出失败")
        self.label_detail.setText(message)
        self.btn_action.setText("确定")

        if success:
            self.label_status.setStyleSheet(
                "font-size: 14px; font-weight: bold; color: green;"
            )
        else:
            self.label_status.setStyleSheet(
                "font-size: 14px; font-weight: bold; color: red;"
            )

    def _on_action_clicked(self):
        """按钮点击"""
        if self._is_completed:
            self.accept()
        else:
            # 请求取消
            self.cancel_requested.emit()
            self.label_status.setText("正在取消...")
            self.btn_action.setEnabled(False)

    def closeEvent(self, event):
        """关闭事件"""
        if self._is_completed:
            event.accept()
        else:
            event.ignore()  # 导出过程中禁止关闭
