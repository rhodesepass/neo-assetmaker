"""
批量转换进度对话框

提供批量转换老素材时的进度显示功能。
"""
import threading
from typing import List, Optional
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QTextEdit
)

from core.legacy_converter import LegacyConverter, ConversionResult


class BatchConvertWorker(QThread):
    """批量转换工作线程"""
    progress_updated = pyqtSignal(int, str)  # (进度百分比, 消息)
    folder_started = pyqtSignal(int, int, str)  # (当前索引, 总数, 文件夹名)
    step_updated = pyqtSignal(str)  # 子任务进度消息
    finished = pyqtSignal(bool, str, list)  # (成功, 消息, 结果列表)
    confirm_requested = pyqtSignal(str, list)  # (ocr_text, candidates) - 请求主线程显示确认对话框

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
        self._cancelled = False

        # 线程同步机制
        self._confirm_event = threading.Event()
        self._confirm_result = None

    def run(self):
        """执行批量转换"""
        try:
            results = self.converter.batch_convert(
                self.src_dir,
                self.dst_dir,
                overlay_mode=self.overlay_mode,
                auto_ocr=self.auto_ocr,
                progress_callback=self._on_batch_progress,
                folder_progress_callback=self._on_folder_progress,
                confirm_callback=self._on_confirm
            )

            # 统计结果
            success_count = sum(1 for r in results if r.success)
            total_count = len(results)

            self.finished.emit(
                True,
                f"转换完成: {success_count}/{total_count} 成功",
                results
            )
        except Exception as e:
            self.finished.emit(False, f"转换失败: {str(e)}", [])

    def _on_batch_progress(self, current: int, total: int, folder_name: str):
        """批量进度回调（文件夹级别）"""
        percent = int(current / total * 100) if total > 0 else 0
        self.folder_started.emit(current, total, folder_name)
        self.progress_updated.emit(percent, f"[{current}/{total}] {folder_name}")

    def _on_folder_progress(self, message: str):
        """文件夹内部进度回调（子任务级别）"""
        self.step_updated.emit(message)

    def _on_confirm(self, ocr_text: str, candidates: list):
        """
        干员确认回调 - 在工作线程中被调用

        发送信号到主线程显示对话框，然后等待结果
        """
        self._confirm_event.clear()
        self._confirm_result = None

        # 发送信号到主线程
        self.confirm_requested.emit(ocr_text, candidates)

        # 等待主线程处理完成
        self._confirm_event.wait()

        return self._confirm_result

    def set_confirm_result(self, result):
        """
        设置确认结果 - 由主线程调用

        设置结果并唤醒工作线程继续执行
        """
        self._confirm_result = result
        self._confirm_event.set()

    def cancel(self):
        """取消转换"""
        self._cancelled = True
        # 如果正在等待确认，也要唤醒线程
        self._confirm_event.set()


class BatchConvertDialog(QDialog):
    """批量转换进度对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量转换老素材")
        self.setMinimumWidth(500)
        self.setMinimumHeight(350)
        self.setModal(True)
        self._setup_ui()
        self._worker: Optional[BatchConvertWorker] = None
        self._results: List[ConversionResult] = []
        self._is_finished = False

    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 总体进度标签
        self.label_overall = QLabel("准备中...")
        self.label_overall.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self.label_overall)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        # 当前文件夹
        self.label_current_folder = QLabel("")
        layout.addWidget(self.label_current_folder)

        # 当前步骤
        self.label_current_step = QLabel("")
        self.label_current_step.setStyleSheet("color: #666;")
        layout.addWidget(self.label_current_step)

        # 日志区域
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        layout.addWidget(self.log_text)

        # 按钮区域
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_action = QPushButton("取消")
        self.btn_action.setMinimumWidth(100)
        self.btn_action.clicked.connect(self._on_action_clicked)
        btn_layout.addWidget(self.btn_action)

        layout.addLayout(btn_layout)

    def start(
        self,
        converter: LegacyConverter,
        src_dir: str,
        dst_dir: str,
        overlay_mode: str,
        auto_ocr: bool,
        confirm_callback=None  # 保留参数兼容，但不使用
    ):
        """开始批量转换"""
        self._worker = BatchConvertWorker(
            converter, src_dir, dst_dir, overlay_mode, auto_ocr
        )
        self._worker.progress_updated.connect(self._on_progress_updated)
        self._worker.folder_started.connect(self._on_folder_started)
        self._worker.step_updated.connect(self._on_step_updated)
        self._worker.finished.connect(self._on_finished)
        self._worker.confirm_requested.connect(self._on_confirm_requested)
        self._worker.start()

        self._log("开始批量转换...")
        self._log(f"源目录: {src_dir}")
        self._log(f"目标目录: {dst_dir}")
        self._log(f"Overlay模式: {overlay_mode}")

    def _on_progress_updated(self, percent: int, message: str):
        """进度更新"""
        if percent >= 0:
            self.progress_bar.setValue(percent)

    def _on_folder_started(self, current: int, total: int, folder_name: str):
        """开始处理新文件夹"""
        self.label_overall.setText(f"转换进度: {current}/{total}")
        self.label_current_folder.setText(f"当前: {folder_name}")
        self._log(f"[{current}/{total}] 处理: {folder_name}")

    def _on_step_updated(self, message: str):
        """子任务步骤更新"""
        self.label_current_step.setText(message)

    def _on_confirm_requested(self, ocr_text: str, candidates: list):
        """
        处理干员确认请求 - 在主线程中执行

        显示确认对话框，然后将结果返回给工作线程
        """
        from gui.dialogs.operator_confirm_dialog import OperatorConfirmDialog

        self._log(f"OCR识别: {ocr_text}，需要确认...")

        dialog = OperatorConfirmDialog(ocr_text, candidates, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            result = dialog.get_selected_operator()
            if result:
                self._log(f"确认干员: {result.name}")
            else:
                self._log("用户跳过确认")
        else:
            result = None
            self._log("用户跳过确认")

        # 将结果返回给工作线程
        if self._worker:
            self._worker.set_confirm_result(result)

    def _on_finished(self, success: bool, message: str, results: list):
        """转换完成"""
        self._is_finished = True
        self._results = results

        self.label_overall.setText(message)
        self.label_current_step.setText("")
        self.progress_bar.setValue(100)

        self.btn_action.setText("确定")

        # 输出详细结果
        self._log("")
        self._log("=" * 40)
        self._log(message)

        success_count = sum(1 for r in results if r.success)
        fail_count = len(results) - success_count

        if fail_count > 0:
            self._log(f"\n失败项目 ({fail_count}):")
            for r in results:
                if not r.success:
                    self._log(f"  - {r.source_name}: {r.message}")

    def _on_action_clicked(self):
        """按钮点击"""
        if self._is_finished:
            self.accept()
        else:
            # 取消
            if self._worker:
                self._worker.cancel()
            self._log("用户取消转换")
            self.reject()

    def _log(self, message: str):
        """添加日志"""
        self.log_text.append(message)
        # 滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def get_results(self) -> List[ConversionResult]:
        """获取转换结果"""
        return self._results

    def closeEvent(self, event):
        """关闭事件"""
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(1000)
        super().closeEvent(event)
