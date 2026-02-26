"""
崩溃恢复对话框 - 显示可恢复的项目
"""
import os
import logging
from typing import Optional, List

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox, QGroupBox,
    QTextEdit, QProgressBar
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from qfluentwidgets import setCustomStyleSheet
from core.crash_recovery_service import RecoveryInfo, CrashRecoveryService

logger = logging.getLogger(__name__)


class RecoveryListWidget(QListWidget):
    """恢复项目列表"""

    item_selected = pyqtSignal(RecoveryInfo)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._recovery_items: List[RecoveryInfo] = []

        # 设置样式
        setCustomStyleSheet(
            self,
            "QListWidget { border: 1px solid #ddd; border-radius: 5px; padding: 5px; background-color: white; } QListWidget::item { padding: 10px; margin: 2px; border-radius: 3px; } QListWidget::item:hover { background-color: #f0f0f0; } QListWidget::item:selected { background-color: #ff6b8b; color: white; }",
            "QListWidget { border: 1px solid #555; border-radius: 5px; padding: 5px; background-color: #2b2b2b; color: #ddd; } QListWidget::item { padding: 10px; margin: 2px; border-radius: 3px; } QListWidget::item:hover { background-color: #404040; } QListWidget::item:selected { background-color: #ff6b8b; color: white; }"
        )

        # 连接信号
        self.itemClicked.connect(self._on_item_clicked)

    def load_recoveries(self, recovery_list: List[RecoveryInfo]):
        """加载恢复项目"""
        self.clear()
        self._recovery_items = recovery_list

        for recovery_info in recovery_list:
            item = QListWidgetItem()
            item.setText(self._format_recovery_item(recovery_info))
            item.setData(Qt.ItemDataRole.UserRole, recovery_info)
            self.addItem(item)

    def get_selected_recovery(self) -> Optional[RecoveryInfo]:
        """获取选中的恢复项目"""
        current_item = self.currentItem()
        if not current_item:
            return None

        return current_item.data(Qt.ItemDataRole.UserRole)

    def _on_item_clicked(self, item: QListWidgetItem):
        """项目点击事件"""
        recovery_info = item.data(Qt.ItemDataRole.UserRole)
        self.item_selected.emit(recovery_info)

    def _format_recovery_item(self, recovery_info: RecoveryInfo) -> str:
        """格式化恢复项目显示"""
        import time

        timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(recovery_info.timestamp))

        project_type = "临时项目" if recovery_info.is_temp else "永久项目"
        if recovery_info.project_path:
            project_name = os.path.basename(recovery_info.project_path)
        else:
            project_name = "未命名项目"

        return f"{timestamp_str} - {project_name} ({project_type})"


class CrashRecoveryDialog(QDialog):
    """崩溃恢复对话框"""

    recovery_requested = pyqtSignal(RecoveryInfo, str)  # 恢复请求信号

    def __init__(self, recovery_service: CrashRecoveryService, parent=None):
        super().__init__(parent)
        self.recovery_service = recovery_service
        self._selected_recovery: Optional[RecoveryInfo] = None

        self._setup_ui()
        self._load_recoveries()

    def _setup_ui(self):
        """设置UI"""
        self.setWindowTitle("崩溃恢复")
        self.setMinimumSize(800, 600)

        layout = QVBoxLayout(self)

        # 标题
        title_label = QLabel("发现未保存的项目")
        title_label.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("color: #ff6b8b; margin-bottom: 10px;")
        layout.addWidget(title_label)

        # 说明
        desc_label = QLabel(
            "以下项目在上次运行时未正常保存，您可以选择恢复这些项目。\n"
            "选择一个项目后，点击\"恢复\"按钮将项目恢复到指定位置。"
        )
        desc_label.setWordWrap(True)
        setCustomStyleSheet(desc_label, "color: #666; margin-bottom: 10px;", "color: #aaa; margin-bottom: 10px;")
        layout.addWidget(desc_label)

        # 恢复项目列表
        list_group = QGroupBox("可恢复项目")
        list_layout = QVBoxLayout()

        self.recovery_list = RecoveryListWidget()
        self.recovery_list.item_selected.connect(self._on_recovery_selected)
        list_layout.addWidget(self.recovery_list)

        list_group.setLayout(list_layout)
        layout.addWidget(list_group)

        # 详细信息
        detail_group = QGroupBox("详细信息")
        detail_layout = QVBoxLayout()

        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMaximumHeight(150)
        setCustomStyleSheet(
            self.detail_text,
            "QTextEdit { background-color: #f8f9fa; color: #333; border: 1px solid #ddd; border-radius: 5px; padding: 10px; font-family: Consolas, monospace; font-size: 12px; }",
            "QTextEdit { background-color: #2b2b2b; color: #ddd; border: 1px solid #555; border-radius: 5px; padding: 10px; font-family: Consolas, monospace; font-size: 12px; }"
        )
        detail_layout.addWidget(self.detail_text)

        detail_group.setLayout(detail_layout)
        layout.addWidget(detail_group)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # 按钮
        button_layout = QHBoxLayout()

        self.recover_button = QPushButton("恢复")
        self.recover_button.setStyleSheet("background-color: #ff6b8b; color: white; padding: 10px 20px;")
        self.recover_button.setEnabled(False)
        self.recover_button.clicked.connect(self._on_recover)
        button_layout.addWidget(self.recover_button)

        self.delete_button = QPushButton("删除")
        self.delete_button.setStyleSheet("background-color: #dc3545; color: white; padding: 10px 20px;")
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self._on_delete)
        button_layout.addWidget(self.delete_button)

        self.delete_all_button = QPushButton("删除全部")
        self.delete_all_button.setStyleSheet("background-color: #6c757d; color: white; padding: 10px 20px;")
        self.delete_all_button.clicked.connect(self._on_delete_all)
        button_layout.addWidget(self.delete_all_button)

        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)

        button_layout.addStretch()
        layout.addLayout(button_layout)

    def _load_recoveries(self):
        """加载可恢复项目"""
        recovery_list = self.recovery_service.check_crash_recovery()

        if not recovery_list:
            # 没有可恢复的项目
            self.recovery_list.clear()
            self.detail_text.setText("没有发现可恢复的项目")
            self.recover_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            self.delete_all_button.setEnabled(False)
            return

        # 加载恢复项目
        self.recovery_list.load_recoveries(recovery_list)

    def _on_recovery_selected(self, recovery_info: RecoveryInfo):
        """恢复项目选择事件"""
        self._selected_recovery = recovery_info

        # 显示详细信息
        summary = self.recovery_service.get_recovery_summary(recovery_info)
        self.detail_text.setText(summary)

        # 启用按钮
        self.recover_button.setEnabled(True)
        self.delete_button.setEnabled(True)

    def _on_recover(self):
        """恢复项目"""
        if not self._selected_recovery:
            return

        # 选择保存位置
        from PyQt6.QtWidgets import QFileDialog

        default_name = "recovered_epconfig.json"
        if self._selected_recovery.project_path:
            default_name = os.path.basename(self._selected_recovery.project_path)

        path, _ = QFileDialog.getSaveFileName(
            self,
            "选择恢复位置",
            default_name,
            "JSON文件 (*.json)"
        )

        if not path:
            return

        # 显示进度
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # 不确定进度
        self.recover_button.setEnabled(False)

        try:
            # 执行恢复
            success = self.recovery_service.recover_project(self._selected_recovery, path)

            if success:
                # 清除恢复信息
                recovery_path = os.path.join(
                    self.recovery_service._recovery_dir,
                    f"recovery_{int(self._selected_recovery.timestamp)}.json"
                )
                self.recovery_service.clear_recovery_info(recovery_path)

                # 刷新列表
                self._load_recoveries()

                # 显示成功消息
                QMessageBox.information(
                    self,
                    "恢复成功",
                    f"项目已成功恢复到:\n{path}"
                )

                # 发出恢复请求信号
                self.recovery_requested.emit(self._selected_recovery, path)

            else:
                QMessageBox.critical(
                    self,
                    "恢复失败",
                    "项目恢复失败，请检查日志获取详细信息。"
                )

        except Exception as e:
            logger.error(f"恢复项目失败: {e}")
            QMessageBox.critical(
                self,
                "恢复失败",
                f"项目恢复失败:\n{e}"
            )

        finally:
            self.progress_bar.setVisible(False)
            self.recover_button.setEnabled(True)

    def _on_delete(self):
        """删除选中的恢复项目"""
        if not self._selected_recovery:
            return

        reply = QMessageBox.question(
            self,
            "确认删除",
            "确定要删除这个恢复项目吗？\n此操作不可撤销！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            # 删除恢复信息
            recovery_path = os.path.join(
                self.recovery_service._recovery_dir,
                f"recovery_{int(self._selected_recovery.timestamp)}.json"
            )
            self.recovery_service.clear_recovery_info(recovery_path)

            # 刷新列表
            self._load_recoveries()

            # 清空详细信息
            self.detail_text.clear()
            self._selected_recovery = None
            self.recover_button.setEnabled(False)
            self.delete_button.setEnabled(False)

        except Exception as e:
            logger.error(f"删除恢复项目失败: {e}")
            QMessageBox.critical(
                self,
                "删除失败",
                f"删除恢复项目失败:\n{e}"
            )

    def _on_delete_all(self):
        """删除所有恢复项目"""
        reply = QMessageBox.question(
            self,
            "确认删除全部",
            "确定要删除所有恢复项目吗？\n此操作不可撤销！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self.recovery_service.clear_all_recovery()

            # 刷新列表
            self._load_recoveries()

            # 清空详细信息
            self.detail_text.clear()
            self._selected_recovery = None
            self.recover_button.setEnabled(False)
            self.delete_button.setEnabled(False)

            QMessageBox.information(
                self,
                "删除成功",
                "所有恢复项目已删除"
            )

        except Exception as e:
            logger.error(f"删除所有恢复项目失败: {e}")
            QMessageBox.critical(
                self,
                "删除失败",
                f"删除所有恢复项目失败:\n{e}"
            )