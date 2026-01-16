"""
快捷键帮助对话框
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QWidget, QLabel, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QGroupBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class ShortcutsDialog(QDialog):
    """快捷键帮助对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("快捷键帮助")
        self.setMinimumSize(500, 450)
        self.setModal(True)
        self._setup_ui()

    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        # 选项卡
        tab_widget = QTabWidget()
        layout.addWidget(tab_widget)

        # 视频预览选项卡
        tab_video = self._create_video_tab()
        tab_widget.addTab(tab_video, "视频预览")

        # 文件操作选项卡
        tab_file = self._create_file_tab()
        tab_widget.addTab(tab_file, "文件操作")

        # 工具选项卡
        tab_tools = self._create_tools_tab()
        tab_widget.addTab(tab_tools, "工具")

        # 鼠标操作选项卡
        tab_mouse = self._create_mouse_tab()
        tab_widget.addTab(tab_mouse, "鼠标操作")

        # 关闭按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        button_layout.addWidget(btn_close)
        layout.addLayout(button_layout)

    def _create_shortcut_table(self, shortcuts: list) -> QTableWidget:
        """创建快捷键表格"""
        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["快捷键", "功能"])
        table.setRowCount(len(shortcuts))

        # 设置列宽
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        # 禁用编辑
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        # 填充数据
        for row, (key, desc) in enumerate(shortcuts):
            key_item = QTableWidgetItem(key)
            key_font = QFont()
            key_font.setBold(True)
            key_item.setFont(key_font)
            table.setItem(row, 0, key_item)
            table.setItem(row, 1, QTableWidgetItem(desc))

        return table

    def _create_video_tab(self) -> QWidget:
        """创建视频预览选项卡"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        shortcuts = [
            ("Space", "播放/暂停视频"),
            ("←", "上一帧"),
            ("→", "下一帧"),
            ("W", "向上移动裁剪框"),
            ("S", "向下移动裁剪框"),
            ("A", "向左移动裁剪框"),
            ("D", "向右移动裁剪框"),
        ]

        table = self._create_shortcut_table(shortcuts)
        layout.addWidget(table)

        # 提示
        tip = QLabel("提示: 使用WASD可以精确微调裁剪框位置，每次移动10像素")
        tip.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(tip)

        return widget

    def _create_file_tab(self) -> QWidget:
        """创建文件操作选项卡"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        shortcuts = [
            ("Ctrl+N", "新建项目"),
            ("Ctrl+O", "打开项目"),
            ("Ctrl+S", "保存项目"),
            ("Ctrl+Shift+S", "另存为"),
            ("Ctrl+Q", "退出程序"),
        ]

        table = self._create_shortcut_table(shortcuts)
        layout.addWidget(table)

        return widget

    def _create_tools_tab(self) -> QWidget:
        """创建工具选项卡"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        shortcuts = [
            ("Ctrl+T", "验证配置"),
            ("Ctrl+E", "导出素材"),
            ("F1", "显示快捷键帮助"),
        ]

        table = self._create_shortcut_table(shortcuts)
        layout.addWidget(table)

        return widget

    def _create_mouse_tab(self) -> QWidget:
        """创建鼠标操作选项卡"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 裁剪框操作
        group_crop = QGroupBox("裁剪框操作")
        crop_layout = QVBoxLayout(group_crop)

        operations = [
            ("拖动裁剪框内部", "移动整个裁剪框"),
            ("拖动角落手柄", "调整裁剪框大小（保持比例）"),
            ("左上角手柄", "从左上角调整大小"),
            ("右下角手柄", "从右下角调整大小"),
        ]

        for op, desc in operations:
            row = QHBoxLayout()
            op_label = QLabel(op)
            op_font = QFont()
            op_font.setBold(True)
            op_label.setFont(op_font)
            op_label.setMinimumWidth(120)
            row.addWidget(op_label)
            row.addWidget(QLabel(desc))
            row.addStretch()
            crop_layout.addLayout(row)

        layout.addWidget(group_crop)

        # 时间轴操作
        group_timeline = QGroupBox("时间轴操作")
        timeline_layout = QVBoxLayout(group_timeline)

        timeline_ops = [
            ("点击时间轴", "跳转到指定位置"),
            ("拖动时间轴", "快速浏览视频"),
        ]

        for op, desc in timeline_ops:
            row = QHBoxLayout()
            op_label = QLabel(op)
            op_font = QFont()
            op_font.setBold(True)
            op_label.setFont(op_font)
            op_label.setMinimumWidth(120)
            row.addWidget(op_label)
            row.addWidget(QLabel(desc))
            row.addStretch()
            timeline_layout.addLayout(row)

        layout.addWidget(group_timeline)
        layout.addStretch()

        return widget
