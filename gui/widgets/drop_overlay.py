"""
拖放叠加层组件 — 为目标区域提供文件拖放功能和视觉反馈
"""
import os
import logging
from typing import Tuple

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, pyqtSignal, QEvent, QPoint
from PyQt6.QtGui import QPainter, QColor, QPen, QFont

logger = logging.getLogger(__name__)


class DropOverlayWidget(QWidget):
    """拖放叠加层 — 当用户将文件拖入目标区域时显示视觉反馈并发射信号"""

    file_dropped = pyqtSignal(str, QPoint)  # (文件绝对路径, 释放位置)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._accepted_extensions: Tuple[str, ...] = ()
        self._hint_text: str = "释放以导入文件"
        self.hide()
        # 在父 widget 上启用拖放并安装事件过滤器
        parent.setAcceptDrops(True)
        parent.installEventFilter(self)

    def set_context(self, accepted_extensions: Tuple[str, ...], hint_text: str):
        """动态更新接受的扩展名和提示文字"""
        self._accepted_extensions = accepted_extensions
        self._hint_text = hint_text

    # ---- 事件过滤器：拦截父 widget 的拖放事件 ----

    def eventFilter(self, obj, event):
        if obj is not self.parent():
            return super().eventFilter(obj, event)

        event_type = event.type()

        if event_type == QEvent.Type.DragEnter:
            if self._validate_drop(event):
                event.acceptProposedAction()
                self._show_overlay()
                return True
            return False

        if event_type == QEvent.Type.DragMove:
            event.acceptProposedAction()
            return True

        if event_type == QEvent.Type.DragLeave:
            self._hide_overlay()
            return True

        if event_type == QEvent.Type.Drop:
            file_path = self._extract_file_path(event)
            if file_path:
                event.acceptProposedAction()
                drop_pos = event.position().toPoint()
                self.file_dropped.emit(file_path, drop_pos)
            self._hide_overlay()
            return True

        if event_type == QEvent.Type.Resize:
            # 保持叠加层与父 widget 同尺寸
            self.setGeometry(obj.rect())

        return super().eventFilter(obj, event)

    # ---- 内部方法 ----

    def _validate_drop(self, event) -> bool:
        """检查拖入的文件是否包含可接受的格式"""
        mime = event.mimeData()
        if not mime.hasUrls():
            return False
        for url in mime.urls():
            if url.isLocalFile():
                ext = os.path.splitext(url.toLocalFile())[1].lower()
                if ext in self._accepted_extensions:
                    return True
        return False

    def _extract_file_path(self, event) -> str:
        """提取第一个扩展名匹配的本地文件路径"""
        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                ext = os.path.splitext(path)[1].lower()
                if ext in self._accepted_extensions:
                    return path
        return ""

    def _show_overlay(self):
        """显示叠加层"""
        self.setGeometry(self.parent().rect())
        self.raise_()
        self.show()

    def _hide_overlay(self):
        """隐藏叠加层"""
        self.hide()

    # ---- 绘制 ----

    def paintEvent(self, event):
        """绘制半透明叠加层 + 虚线边框 + 提示文字"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 半透明背景
        painter.fillRect(self.rect(), QColor(0, 120, 215, 30))

        # 虚线圆角边框（内缩 8px）
        pen = QPen(QColor(0, 120, 215, 150))
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        inner = self.rect().adjusted(8, 8, -8, -8)
        painter.drawRoundedRect(inner, 12, 12)

        # 居中提示文字
        painter.setPen(QColor(255, 255, 255, 200))
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._hint_text)

        painter.end()
