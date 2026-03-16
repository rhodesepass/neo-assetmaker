"""
JSON预览组件 - 实时显示配置JSON和验证状态
"""
import json
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout,
    QHBoxLayout, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QTextCharFormat, QSyntaxHighlighter, QTextDocument
from qfluentwidgets import (
    TextEdit, StrongBodyLabel, CaptionLabel, setCustomStyleSheet
)

from config.epconfig import EPConfig
from core.validator import EPConfigValidator, ValidationLevel
from gui.widgets.drop_overlay import DropOverlayWidget


class JsonSyntaxHighlighter(QSyntaxHighlighter):
    """JSON语法高亮"""

    def __init__(self, document: QTextDocument):
        super().__init__(document)

        self._key_format = QTextCharFormat()
        self._key_format.setForeground(QColor("#9cdcfe"))

        self._string_format = QTextCharFormat()
        self._string_format.setForeground(QColor("#ce9178"))

        self._number_format = QTextCharFormat()
        self._number_format.setForeground(QColor("#b5cea8"))

        self._bool_format = QTextCharFormat()
        self._bool_format.setForeground(QColor("#569cd6"))

        self._null_format = QTextCharFormat()
        self._null_format.setForeground(QColor("#569cd6"))

    def highlightBlock(self, text: str):
        """高亮代码块"""
        import re

        for match in re.finditer(r'"([^"]+)"\s*:', text):
            self.setFormat(match.start(), match.end() - match.start() - 1, self._key_format)

        for match in re.finditer(r':\s*"([^"]*)"', text):
            start = text.find('"', match.start() + 1)
            end = text.find('"', start + 1) + 1
            self.setFormat(start, end - start, self._string_format)

        for match in re.finditer(r':\s*(-?\d+\.?\d*)', text):
            self.setFormat(match.start(1), len(match.group(1)), self._number_format)

        for match in re.finditer(r'\b(true|false)\b', text):
            self.setFormat(match.start(), match.end() - match.start(), self._bool_format)

        for match in re.finditer(r'\bnull\b', text):
            self.setFormat(match.start(), match.end() - match.start(), self._null_format)


class JsonPreviewWidget(QWidget):
    """JSON预览组件"""

    json_file_dropped = pyqtSignal(str)  # 拖放JSON文件路径

    def __init__(self, parent=None):
        super().__init__(parent)

        self._config: Optional[EPConfig] = None
        self._validator: Optional[EPConfigValidator] = None

        self._setup_ui()

    def _setup_ui(self):
        """设置UI"""
        # 给整个面板添加左侧分隔线，与深色预览区自然分界
        self.setObjectName("json_preview_panel")
        setCustomStyleSheet(
            self,
            "QWidget#json_preview_panel { border-left: 1px solid #e0e0e0; }",
            "QWidget#json_preview_panel { border-left: 1px solid #3a3a3a; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题 — 柔和背景融入面板
        title_label = StrongBodyLabel("配置预览 (JSON)")
        setCustomStyleSheet(
            title_label,
            "padding: 8px 12px; background-color: #f5f5f5; border-bottom: 1px solid #e8e8e8; color: #333333;",
            "padding: 8px 12px; background-color: #2a2a2a; border-bottom: 1px solid #3a3a3a; color: #eeeeee;"
        )
        layout.addWidget(title_label)

        self.text_edit = TextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setAcceptDrops(False)
        self.text_edit.viewport().setAcceptDrops(False)
        self.text_edit.setFont(QFont("Consolas", 10))
        setCustomStyleSheet(
            self.text_edit,
            "TextEdit { background-color: #fafafa; color: #333; border: none; padding: 10px; }",
            "TextEdit { background-color: #1e1e1e; color: #d4d4d4; border: none; padding: 10px; }"
        )
        layout.addWidget(self.text_edit)

        self._highlighter = JsonSyntaxHighlighter(self.text_edit.document())

        # 验证状态 — 背景更接近面板整体
        self.status_frame = QFrame()
        setCustomStyleSheet(
            self.status_frame,
            "background-color: #f5f5f5; border-top: 1px solid #e8e8e8;",
            "background-color: #252525; border-top: 1px solid #3a3a3a;"
        )
        status_layout = QHBoxLayout(self.status_frame)
        status_layout.setContentsMargins(12, 6, 12, 6)

        self.status_icon = CaptionLabel()
        status_layout.addWidget(self.status_icon)

        self.status_label = CaptionLabel("未加载配置")
        setCustomStyleSheet(self.status_label, "color: #999;", "color: #888;")
        status_layout.addWidget(self.status_label)

        status_layout.addStretch()

        self.error_count_label = CaptionLabel()
        setCustomStyleSheet(self.error_count_label, "color: #dc3545;", "color: #f44;")
        status_layout.addWidget(self.error_count_label)

        self.warning_count_label = CaptionLabel()
        setCustomStyleSheet(self.warning_count_label, "color: #e68a00;", "color: #fa0;")
        status_layout.addWidget(self.warning_count_label)

        layout.addWidget(self.status_frame)

        # 拖放支持 — 接受 .json 文件导入
        self._drop_overlay = DropOverlayWidget(self)
        self._drop_overlay.set_context((".json",), "释放以导入配置文件")
        self._drop_overlay.file_dropped.connect(self._on_file_dropped)

    def _on_file_dropped(self, file_path: str, drop_pos):
        """处理拖放文件 — 转发为 json_file_dropped 信号"""
        self.json_file_dropped.emit(file_path)

    def set_config(self, config: EPConfig, base_dir: str = ""):
        """设置配置"""
        self._config = config
        self._validator = EPConfigValidator(base_dir)

        self._update_json()
        self._update_validation()

    def update_preview(self):
        """更新预览"""
        if self._config:
            self._update_json()
            self._update_validation()

    def _update_json(self):
        """更新JSON显示"""
        if self._config is None:
            self.text_edit.setText("")
            return

        config_dict = self._config.to_dict(normalize_paths=True)
        json_str = json.dumps(config_dict, ensure_ascii=False, indent=4)
        self.text_edit.setText(json_str)

    def _update_validation(self):
        """更新验证状态"""
        if self._config is None or self._validator is None:
            self.status_label.setText("未加载配置")
            self.status_icon.setText("")
            self.error_count_label.setText("")
            self.warning_count_label.setText("")
            return

        results = self._validator.validate_config(self._config)
        errors = self._validator.get_errors()
        warnings = self._validator.get_warnings()

        if len(errors) == 0:
            self.status_icon.setText("✓")
            setCustomStyleSheet(self.status_icon, "color: #2e7d32; font-size: 16px;", "color: #4a4; font-size: 16px;")
            self.status_label.setText("配置有效")
            setCustomStyleSheet(self.status_label, "color: #2e7d32;", "color: #4a4;")
        else:
            self.status_icon.setText("✗")
            setCustomStyleSheet(self.status_icon, "color: #dc3545; font-size: 16px;", "color: #f44; font-size: 16px;")
            self.status_label.setText("配置无效")
            setCustomStyleSheet(self.status_label, "color: #dc3545;", "color: #f44;")

        if len(errors) > 0:
            self.error_count_label.setText(f"{len(errors)} 个错误")
            tooltip_lines = ["<b>错误列表:</b>"]
            for r in errors:
                tooltip_lines.append(f"• {r.field}: {r.message}")
            self.error_count_label.setToolTip("<br>".join(tooltip_lines))
        else:
            self.error_count_label.setText("")
            self.error_count_label.setToolTip("")

        if len(warnings) > 0:
            self.warning_count_label.setText(f"{len(warnings)} 个警告")
            tooltip_lines = ["<b>警告列表:</b>"]
            for r in warnings:
                tooltip_lines.append(f"• {r.field}: {r.message}")
            self.warning_count_label.setToolTip("<br>".join(tooltip_lines))
        else:
            self.warning_count_label.setText("")
            self.warning_count_label.setToolTip("")

    def clear(self):
        """清空预览"""
        self._config = None
        self._validator = None
        self.text_edit.setText("")
        self.status_label.setText("未加载配置")
        self.status_icon.setText("")
        self.error_count_label.setText("")
        self.warning_count_label.setText("")
