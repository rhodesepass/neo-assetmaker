"""
批量转换进度对话框
"""
import threading
from typing import List, Optional, Callable
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar,
    QPushButton, QTextEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from core.legacy_converter import LegacyConverter, ConversionResult


class BatchConvertWorker(QThread):
    """批量转换工作线程"""

    progress = pyqtSignal(int, int, str)  # current, total, name
    folder_progress = pyqtSignal(str)  # message
    finished = pyqtSignal(list)  # results
    error = pyqtSignal(str)  # error message
    confirmation_needed = pyqtSignal(str, list)  # ocr_text, candidates

    def __init__(
        self,
        converter: LegacyConverter,
        src_dir: str,
        dst_dir: str,
        overlay_mode: str,
        auto_ocr: bool
    ):
        super().__init__()
        self.converter = converter
        self.src_dir = src_dir
        self.dst_dir = dst_dir
        self.overlay_mode = overlay_mode
        self.auto_ocr = auto_ocr
        # 线程间通信机制
        self._confirmation_event = threading.Event()
        self._confirmation_result = None

    def set_confirmation_result(self, result):
        """主线程调用，设置确认结果"""
        self._confirmation_result = result
        self._confirmation_event.set()

    def _request_confirmation(self, ocr_text, candidates):
        """工作线程调用，请求用户确认（线程安全）"""
        self._confirmation_event.clear()
        self._confirmation_result = None
        self.confirmation_needed.emit(ocr_text, candidates)
        self._confirmation_event.wait()  # 阻塞等待主线程响应
        return self._confirmation_result

    def run(self):
        """执行批量转换"""
        try:
            results = self.converter.batch_convert(
                self.src_dir,
                self.dst_dir,
                overlay_mode=self.overlay_mode,
                auto_ocr=self.auto_ocr,
                progress_callback=self._on_progress,
                folder_progress_callback=self._on_folder_progress,
                confirm_callback=self._request_confirmation
            )
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, current: int, total: int, name: str):
        """进度回调"""
        self.progress.emit(current, total, name)

    def _on_folder_progress(self, message: str):
        """文件夹内部进度回调"""
        self.folder_progress.emit(message)


class BatchConvertDialog(QDialog):
    """批量转换进度对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._results: List[ConversionResult] = []
        self._worker: Optional[BatchConvertWorker] = None
        self._is_completed = False
        self._setup_ui()

    def _setup_ui(self):
        """设置UI"""
        self.setWindowTitle("批量转换老素材")
        self.setMinimumSize(500, 400)
        self.setModal(True)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        # 状态标签
        self.label_status = QLabel("准备转换...")
        self.label_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_status.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self.label_status)

        # 总进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        # 当前文件夹标签
        self.label_current = QLabel("")
        self.label_current.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label_current)

        # 详细信息标签
        self.label_detail = QLabel("")
        self.label_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_detail.setStyleSheet("color: #666;")
        layout.addWidget(self.label_detail)

        # 日志区域
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(200)
        layout.addWidget(self.log_text)

        # 按钮
        self.btn_action = QPushButton("取消")
        self.btn_action.clicked.connect(self._on_action_clicked)
        layout.addWidget(self.btn_action)

    def start(
        self,
        converter: LegacyConverter,
        src_dir: str,
        dst_dir: str,
        overlay_mode: str,
        auto_ocr: bool,
        confirm_callback: Optional[Callable] = None
    ):
        """开始批量转换"""
        self._confirm_callback = confirm_callback
        self._worker = BatchConvertWorker(
            converter, src_dir, dst_dir,
            overlay_mode, auto_ocr
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.folder_progress.connect(self._on_folder_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.confirmation_needed.connect(self._on_confirmation_needed)
        self._worker.start()

    def _on_confirmation_needed(self, ocr_text: str, candidates: list):
        """在主线程中处理确认请求"""
        result = None
        if self._confirm_callback:
            result = self._confirm_callback(ocr_text, candidates)
        self._worker.set_confirmation_result(result)

    def get_results(self) -> List[ConversionResult]:
        """获取转换结果"""
        return self._results

    def _on_progress(self, current: int, total: int, name: str):
        """更新总进度"""
        percent = int(current / total * 100) if total > 0 else 0
        self.progress_bar.setValue(percent)
        self.label_status.setText(f"正在转换 ({current}/{total})")
        self.label_current.setText(f"当前: {name}")
        self._log(f"[{current}/{total}] 开始转换: {name}")

    def _on_folder_progress(self, message: str):
        """更新文件夹内部进度"""
        self.label_detail.setText(message)

    def _on_finished(self, results: List[ConversionResult]):
        """转换完成"""
        self._results = results
        self._is_completed = True

        success_count = sum(1 for r in results if r.success)
        total_count = len(results)

        self.progress_bar.setValue(100)
        self.label_status.setText("转换完成!")
        self.label_current.setText("")
        self.label_detail.setText(f"成功: {success_count}/{total_count}")
        self.btn_action.setText("确定")

        # 记录结果
        self._log("")
        self._log("=" * 40)
        self._log(f"转换完成: {success_count}/{total_count} 成功")
        for r in results:
            status = "成功" if r.success else "失败"
            self._log(f"  [{status}] {r.src_path}")
            if not r.success and r.message:
                self._log(f"        原因: {r.message}")

        if success_count == total_count:
            self.label_status.setStyleSheet(
                "font-size: 14px; font-weight: bold; color: green;"
            )
        elif success_count > 0:
            self.label_status.setStyleSheet(
                "font-size: 14px; font-weight: bold; color: orange;"
            )
        else:
            self.label_status.setStyleSheet(
                "font-size: 14px; font-weight: bold; color: red;"
            )

    def _on_error(self, error_msg: str):
        """转换出错"""
        self._is_completed = True
        self.label_status.setText("转换失败")
        self.label_status.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: red;"
        )
        self.label_detail.setText(error_msg)
        self.btn_action.setText("确定")
        self._log(f"错误: {error_msg}")

    def _on_action_clicked(self):
        """按钮点击"""
        if self._is_completed:
            self.accept()
        else:
            # 请求取消 - 目前不支持中途取消
            self.label_status.setText("正在取消...")
            self.btn_action.setEnabled(False)
            # 等待线程结束
            if self._worker and self._worker.isRunning():
                self._worker.wait()
            self.reject()

    def _log(self, message: str):
        """添加日志"""
        self.log_text.append(message)
        # 滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def closeEvent(self, event):
        """关闭事件"""
        if self._is_completed:
            event.accept()
        else:
            event.ignore()
