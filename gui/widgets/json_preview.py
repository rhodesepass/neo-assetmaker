"""
JSON预览组件 - 实时显示配置JSON和验证状态
"""
import json
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QLabel,
    QHBoxLayout, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor, QTextCharFormat, QSyntaxHighlighter, QTextDocument

from config.epconfig import EPConfig
from core.validator import EPConfigValidator, ValidationLevel


class JsonSyntaxHighlighter(QSyntaxHighlighter):
    """JSON语法高亮"""

    def __init__(self, document: QTextDocument):
        super().__init__(document)

        # 定义格式
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

        # 键
        for match in re.finditer(r'"([^"]+)"\s*:', text):
            self.setFormat(match.start(), match.end() - match.start() - 1, self._key_format)

        # 字符串值
        for match in re.finditer(r':\s*"([^"]*)"', text):
            start = text.find('"', match.start() + 1)
            end = text.find('"', start + 1) + 1
            self.setFormat(start, end - start, self._string_format)

        # 数字
        for match in re.finditer(r':\s*(-?\d+\.?\d*)', text):
            self.setFormat(match.start(1), len(match.group(1)), self._number_format)

        # 布尔值
        for match in re.finditer(r'\b(true|false)\b', text):
            self.setFormat(match.start(), match.end() - match.start(), self._bool_format)

        # null
        for match in re.finditer(r'\bnull\b', text):
            self.setFormat(match.start(), match.end() - match.start(), self._null_format)


class JsonPreviewWidget(QWidget):
    """JSON预览组件"""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._config: Optional[EPConfig] = None
        self._validator: Optional[EPConfigValidator] = None

        self._setup_ui()

    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        # 标题
        title_label = QLabel("配置预览 (JSON)")
        title_label.setStyleSheet(
            "font-weight: bold; color: #ddd; padding: 5px; "
            "background-color: #333; border-bottom: 1px solid #444;"
        )
        layout.addWidget(title_label)

        # JSON文本框
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("Consolas", 10))
        self.text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: none;
                padding: 10px;
            }
        """)
        layout.addWidget(self.text_edit)

        # 语法高亮
        self._highlighter = JsonSyntaxHighlighter(self.text_edit.document())

        # 验证状态
        self.status_frame = QFrame()
        self.status_frame.setStyleSheet(
            "background-color: #2d2d2d; border-top: 1px solid #444;"
        )
        status_layout = QHBoxLayout(self.status_frame)
        status_layout.setContentsMargins(10, 5, 10, 5)

        self.status_icon = QLabel()
        status_layout.addWidget(self.status_icon)

        self.status_label = QLabel("未加载配置")
        self.status_label.setStyleSheet("color: #888;")
        status_layout.addWidget(self.status_label)

        status_layout.addStretch()

        self.error_count_label = QLabel()
        self.error_count_label.setStyleSheet("color: #f44;")
        status_layout.addWidget(self.error_count_label)

        self.warning_count_label = QLabel()
        self.warning_count_label.setStyleSheet("color: #fa0;")
        status_layout.addWidget(self.warning_count_label)

        layout.addWidget(self.status_frame)

    def set_config(self, config: EPConfig, base_dir: str = ""):
        """设置配置"""
        self._config = config
        self._validator = EPConfigValidator(base_dir)

        # 更新JSON显示
        self._update_json()

        # 更新验证状态
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

        # 执行验证
        results = self._validator.validate_config(self._config)
        errors = self._validator.get_errors()
        warnings = self._validator.get_warnings()

        # 更新状态
        if len(errors) == 0:
            self.status_icon.setText("✓")
            self.status_icon.setStyleSheet("color: #4a4; font-size: 16px;")
            self.status_label.setText("配置有效")
            self.status_label.setStyleSheet("color: #4a4;")
        else:
            self.status_icon.setText("✗")
            self.status_icon.setStyleSheet("color: #f44; font-size: 16px;")
            self.status_label.setText("配置无效")
            self.status_label.setStyleSheet("color: #f44;")

        # 更新计数和详细提示
        if len(errors) > 0:
            self.error_count_label.setText(f"{len(errors)} 个错误")
            # 构建详细的 tooltip
            tooltip_lines = ["<b>错误列表:</b>"]
            for r in errors:
                tooltip_lines.append(f"• {r.field}: {r.message}")
            self.error_count_label.setToolTip("<br>".join(tooltip_lines))
        else:
            self.error_count_label.setText("")
            self.error_count_label.setToolTip("")

        if len(warnings) > 0:
            self.warning_count_label.setText(f"{len(warnings)} 个警告")
            # 构建详细的 tooltip
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
