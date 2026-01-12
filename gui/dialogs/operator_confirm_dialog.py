"""
干员确认对话框

当OCR模糊匹配时，弹出此对话框让用户确认或选择正确的干员
"""
from typing import List, Tuple, Optional, TYPE_CHECKING

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton,
    QLineEdit, QGroupBox, QFrame
)
from PyQt6.QtCore import Qt

if TYPE_CHECKING:
    from core.operator_lookup import OperatorInfo, OperatorLookup


class OperatorConfirmDialog(QDialog):
    """干员确认对话框"""

    def __init__(
        self,
        ocr_text: str,
        candidates: List[Tuple['OperatorInfo', int]],
        operator_lookup: Optional['OperatorLookup'] = None,
        parent=None
    ):
        """
        初始化对话框

        Args:
            ocr_text: OCR识别的原始文本
            candidates: 候选干员列表 [(OperatorInfo, similarity_score), ...]
            operator_lookup: 干员查询实例（用于手动搜索）
            parent: 父窗口
        """
        super().__init__(parent)
        self._ocr_text = ocr_text
        self._candidates = candidates
        self._operator_lookup = operator_lookup
        self._selected_operator: Optional['OperatorInfo'] = None
        self._setup_ui()

    def _setup_ui(self):
        """设置UI"""
        self.setWindowTitle("确认干员信息")
        self.setMinimumSize(550, 450)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(15, 15, 15, 15)

        # OCR结果显示
        ocr_group = QGroupBox("OCR识别结果")
        ocr_layout = QVBoxLayout(ocr_group)
        self.label_ocr = QLabel(f"识别文本: <b>{self._ocr_text}</b>")
        self.label_ocr.setStyleSheet("font-size: 13px; padding: 5px;")
        ocr_layout.addWidget(self.label_ocr)
        layout.addWidget(ocr_group)

        # 候选列表
        candidates_group = QGroupBox("候选干员（点击选择，双击确认）")
        candidates_layout = QVBoxLayout(candidates_group)

        self.list_candidates = QListWidget()
        self.list_candidates.setAlternatingRowColors(True)
        self.list_candidates.setStyleSheet("""
            QListWidget {
                font-size: 12px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #e0e0e0;
            }
            QListWidget::item:selected {
                background-color: #0078d4;
                color: white;
            }
            QListWidget::item:hover {
                background-color: #e5f3ff;
            }
        """)
        self.list_candidates.itemClicked.connect(self._on_candidate_clicked)
        self.list_candidates.itemDoubleClicked.connect(self._on_candidate_double_clicked)
        candidates_layout.addWidget(self.list_candidates)

        # 填充候选列表
        for op_info, score in self._candidates:
            display_text = (
                f"{op_info.name} ({op_info.name_zh}) - "
                f"{op_info.op_class} - 相似度: {score}%"
            )
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, op_info)
            self.list_candidates.addItem(item)

        layout.addWidget(candidates_group)

        # 手动搜索
        search_group = QGroupBox("手动搜索（如果列表中没有正确选项）")
        search_layout = QVBoxLayout(search_group)

        search_input_layout = QHBoxLayout()
        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("输入干员名称搜索（支持中英文）...")
        self.edit_search.returnPressed.connect(self._on_search)
        search_input_layout.addWidget(self.edit_search)

        self.btn_search = QPushButton("搜索")
        self.btn_search.setFixedWidth(80)
        self.btn_search.clicked.connect(self._on_search)
        search_input_layout.addWidget(self.btn_search)

        search_layout.addLayout(search_input_layout)

        # 搜索结果列表
        self.list_search_results = QListWidget()
        self.list_search_results.setMaximumHeight(120)
        self.list_search_results.setStyleSheet("""
            QListWidget {
                font-size: 12px;
            }
            QListWidget::item {
                padding: 5px;
            }
            QListWidget::item:selected {
                background-color: #0078d4;
                color: white;
            }
        """)
        self.list_search_results.itemClicked.connect(self._on_search_result_clicked)
        self.list_search_results.itemDoubleClicked.connect(self._on_search_result_double_clicked)
        self.list_search_results.hide()
        search_layout.addWidget(self.list_search_results)

        layout.addWidget(search_group)

        # 选中信息显示
        self.label_selected = QLabel("当前选择: <无>")
        self.label_selected.setStyleSheet(
            "font-size: 12px; padding: 8px; background-color: #f5f5f5; "
            "border-radius: 4px;"
        )
        layout.addWidget(self.label_selected)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        # 按钮区
        btn_layout = QHBoxLayout()

        self.btn_skip = QPushButton("跳过（使用图片模式）")
        self.btn_skip.setStyleSheet("color: #666;")
        self.btn_skip.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_skip)

        btn_layout.addStretch()

        self.btn_confirm = QPushButton("确认选择")
        self.btn_confirm.setEnabled(False)
        self.btn_confirm.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                padding: 8px 20px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
            QPushButton:hover:enabled {
                background-color: #106ebe;
            }
        """)
        self.btn_confirm.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_confirm)

        layout.addLayout(btn_layout)

    def _update_selected_display(self):
        """更新选中信息显示"""
        if self._selected_operator:
            info = self._selected_operator
            self.label_selected.setText(
                f"当前选择: <b>{info.name}</b> ({info.name_zh}) - "
                f"{info.op_class} - 代号: {info.code} - 颜色: {info.color}"
            )
            self.btn_confirm.setEnabled(True)
        else:
            self.label_selected.setText("当前选择: <无>")
            self.btn_confirm.setEnabled(False)

    def _on_candidate_clicked(self, item: QListWidgetItem):
        """候选项被点击"""
        self._selected_operator = item.data(Qt.ItemDataRole.UserRole)
        self._update_selected_display()
        # 清除搜索结果的选择
        self.list_search_results.clearSelection()

    def _on_candidate_double_clicked(self, item: QListWidgetItem):
        """候选项被双击，直接确认"""
        self._selected_operator = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def _on_search_result_clicked(self, item: QListWidgetItem):
        """搜索结果被点击"""
        self._selected_operator = item.data(Qt.ItemDataRole.UserRole)
        self._update_selected_display()
        # 清除候选列表的选择
        self.list_candidates.clearSelection()

    def _on_search_result_double_clicked(self, item: QListWidgetItem):
        """搜索结果被双击，直接确认"""
        self._selected_operator = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def _on_search(self):
        """执行搜索"""
        keyword = self.edit_search.text().strip()
        if not keyword:
            return

        self.list_search_results.clear()

        if self._operator_lookup:
            results = self._operator_lookup.search(keyword, limit=10)
            if results:
                self.list_search_results.show()
                for op_info in results:
                    display_text = (
                        f"{op_info.name} ({op_info.name_zh}) - "
                        f"{op_info.op_class} - {op_info.code}"
                    )
                    item = QListWidgetItem(display_text)
                    item.setData(Qt.ItemDataRole.UserRole, op_info)
                    self.list_search_results.addItem(item)
            else:
                self.list_search_results.show()
                self.list_search_results.addItem("未找到匹配的干员")
        else:
            self.list_search_results.show()
            self.list_search_results.addItem("搜索功能不可用")

    def get_selected_operator(self) -> Optional['OperatorInfo']:
        """获取用户选择的干员"""
        return self._selected_operator
