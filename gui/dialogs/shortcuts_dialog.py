"""
操作帮助对话框
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget,
    QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from qfluentwidgets import (
    PushButton, TabWidget, SubtitleLabel, StrongBodyLabel, BodyLabel,
    CardWidget, TableWidget, CaptionLabel, SmoothScrollArea
)
from gui.styles import (
    COLOR_TEXT_SECONDARY, COLOR_TEXT_MUTED, COLOR_BG_SURFACE,
    apply_themed_style
)


class ShortcutsDialog(QDialog):
    """操作帮助对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("操作帮助")
        self.setMinimumSize(560, 600)
        self.setModal(True)
        self._setup_ui()

    def _setup_ui(self):
        """设置UI"""
        apply_themed_style(
            self,
            f"QDialog {{ background-color: {COLOR_BG_SURFACE[0]}; }}",
            f"QDialog {{ background-color: {COLOR_BG_SURFACE[1]}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        # 选项卡 - 使用Fluent TabWidget
        tab_widget = TabWidget()
        tab_widget.setTabsClosable(False)
        tab_widget.setMovable(False)
        tab_widget.tabBar.setAddButtonVisible(False)
        layout.addWidget(tab_widget)

        # 视频预览选项卡
        tab_video = self._create_scrollable_tab(self._create_video_tab)
        tab_widget.addTab(tab_video, "视频预览")

        # 文件操作选项卡
        tab_file = self._create_scrollable_tab(self._create_file_tab)
        tab_widget.addTab(tab_file, "文件操作")

        # 工具选项卡
        tab_tools = self._create_scrollable_tab(self._create_tools_tab)
        tab_widget.addTab(tab_tools, "工具")

        # 鼠标操作选项卡
        tab_mouse = self._create_scrollable_tab(self._create_mouse_tab)
        tab_widget.addTab(tab_mouse, "鼠标操作")

        # 关闭按钮 - 使用Fluent PushButton
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        btn_close = PushButton("关闭")
        btn_close.clicked.connect(self.accept)
        button_layout.addWidget(btn_close)
        layout.addLayout(button_layout)

    def _create_scrollable_tab(self, content_factory) -> SmoothScrollArea:
        """用 SmoothScrollArea 包裹选项卡内容"""
        scroll = SmoothScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(SmoothScrollArea.Shape.NoFrame)
        content = content_factory()
        scroll.setWidget(content)
        return scroll

    def _create_shortcut_table(self, shortcuts: list) -> TableWidget:
        """创建快捷键表格"""
        table = TableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["快捷键", "功能"])
        table.setRowCount(len(shortcuts))
        table.setBorderVisible(True)
        table.setBorderRadius(5)
        table.verticalHeader().hide()
        table.setSelectionMode(TableWidget.SelectionMode.NoSelection)

        # 设置列宽
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        # 禁用编辑
        table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)

        # 填充数据
        for row, (key, desc) in enumerate(shortcuts):
            key_item = QTableWidgetItem(key)
            key_font = QFont()
            key_font.setBold(True)
            key_item.setFont(key_font)
            table.setItem(row, 0, key_item)
            table.setItem(row, 1, QTableWidgetItem(desc))

        return table

    def _create_notes_section(self, notes: list[str]) -> CardWidget:
        """创建注意事项卡片"""
        card = CardWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 12)
        card_layout.setSpacing(6)

        title = CaptionLabel("注意事项")
        apply_themed_style(
            title,
            f"CaptionLabel {{ color: {COLOR_TEXT_SECONDARY[0]}; font-weight: bold; }}",
            f"CaptionLabel {{ color: {COLOR_TEXT_SECONDARY[1]}; font-weight: bold; }}"
        )
        card_layout.addWidget(title)

        for note in notes:
            label = CaptionLabel(f"· {note}")
            label.setWordWrap(True)
            apply_themed_style(
                label,
                f"CaptionLabel {{ color: {COLOR_TEXT_MUTED[0]}; }}",
                f"CaptionLabel {{ color: {COLOR_TEXT_MUTED[1]}; }}"
            )
            card_layout.addWidget(label)

        return card

    def _create_tutorial_section(self, items: list[tuple[str, list[str]]]) -> CardWidget:
        """创建使用教程卡片

        Parameters
        ----------
        items : list of (subtitle, bullet_points)
            每个元组为一个子标题和对应的要点列表
        """
        card = CardWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 12)
        card_layout.setSpacing(6)

        title = CaptionLabel("使用教程")
        apply_themed_style(
            title,
            f"CaptionLabel {{ color: {COLOR_TEXT_SECONDARY[0]}; font-weight: bold; }}",
            f"CaptionLabel {{ color: {COLOR_TEXT_SECONDARY[1]}; font-weight: bold; }}"
        )
        card_layout.addWidget(title)

        for subtitle, points in items:
            sub_label = StrongBodyLabel(subtitle)
            card_layout.addWidget(sub_label)

            for point in points:
                label = CaptionLabel(f"  · {point}")
                label.setWordWrap(True)
                apply_themed_style(
                    label,
                    f"CaptionLabel {{ color: {COLOR_TEXT_MUTED[0]}; }}",
                    f"CaptionLabel {{ color: {COLOR_TEXT_MUTED[1]}; }}"
                )
                card_layout.addWidget(label)

        return card

    def _create_video_tab(self) -> QWidget:
        """创建视频预览选项卡"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        shortcuts = [
            ("Space", "播放/暂停视频"),
            ("←", "上一帧"),
            ("→", "下一帧"),
            ("W", "向上移动裁剪框（10像素）"),
            ("S", "向下移动裁剪框（10像素）"),
            ("A", "向左移动裁剪框（10像素）"),
            ("D", "向右移动裁剪框（10像素）"),
        ]

        table = self._create_shortcut_table(shortcuts)
        layout.addWidget(table)

        # 提示 - 使用Fluent CaptionLabel
        tip = CaptionLabel("提示: 使用WASD可以精确微调裁剪框位置，每次移动10像素")
        apply_themed_style(
            tip,
            f"CaptionLabel {{ color: {COLOR_TEXT_MUTED[0]}; font-style: italic; }}",
            f"CaptionLabel {{ color: {COLOR_TEXT_MUTED[1]}; font-style: italic; }}"
        )
        layout.addWidget(tip)

        # 使用教程
        tutorial = self._create_tutorial_section([
            ("裁剪框调整", [
                "鼠标拖动裁剪框内部可移动整个裁剪框",
                "拖动四个角落手柄可调整大小（自动保持宽高比）",
                "使用 WASD 键精确微调位置，每次移动 10 像素",
                "裁剪框最小宽度 90 像素，不会超出画面边界",
            ]),
            ("帧导航", [
                "使用 ← → 逐帧查看，按 Space 播放/暂停",
                "点击时间轴可直接跳转到指定位置",
                "拖动时间轴可快速浏览视频",
            ]),
            ("素材导入", [
                "将视频或图片文件直接拖入预览区域即可导入",
                "系统会根据当前选项卡自动识别素材类型",
            ]),
        ])
        layout.addWidget(tutorial)

        # 注意事项
        notes = self._create_notes_section([
            "Space / ← / → 仅在已加载视频时生效",
            "WASD 在视频和静态图片模式下均可使用",
            "以上按键需在无修饰键（Ctrl/Shift/Alt）时按下",
            "需要预览区域获得焦点（点击预览区域即可）",
        ])
        layout.addWidget(notes)

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
            ("Ctrl+Z", "撤销上一步操作"),
            ("Ctrl+Shift+Z / Ctrl+Y", "重做已撤销的操作"),
            ("Ctrl+Q", "退出程序"),
        ]

        table = self._create_shortcut_table(shortcuts)
        layout.addWidget(table)

        # 注意事项
        notes = self._create_notes_section([
            "撤销/重做仅在有历史操作记录时可用",
        ])
        layout.addWidget(notes)

        # 使用教程
        tutorial = self._create_tutorial_section([
            ("项目管理", [
                "使用 Ctrl+N 新建项目，Ctrl+O 打开已有项目",
                "Ctrl+S 保存到当前路径，Ctrl+Shift+S 另存为新路径",
                "操作支持撤销（Ctrl+Z）和重做（Ctrl+Y 或 Ctrl+Shift+Z）",
            ]),
            ("拖拽导入", [
                "将 .json 配置文件拖入右侧 JSON 预览面板可快速导入项目",
                "将视频/图片文件拖入中央预览区域可自动导入素材",
                "拖入的素材类型根据当前选项卡自动识别处理",
            ]),
            ("自动保存", [
                "程序每 5 分钟自动保存一次当前项目",
                "异常退出后重新打开程序会提示恢复",
            ]),
        ])
        layout.addWidget(tutorial)

        return widget

    def _create_tools_tab(self) -> QWidget:
        """创建工具选项卡"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        shortcuts = [
            ("Ctrl+T", "验证配置"),
            ("Ctrl+E", "导出素材"),
            ("F1", "显示操作帮助（本对话框）"),
        ]

        table = self._create_shortcut_table(shortcuts)
        layout.addWidget(table)

        # 注意事项
        notes = self._create_notes_section([
            "导出（Ctrl+E）需先通过配置验证，验证失败时无法导出",
        ])
        layout.addWidget(notes)

        # 使用教程
        tutorial = self._create_tutorial_section([
            ("导出流程", [
                "先加载循环素材（视频或图片），再使用 Ctrl+E 导出",
                "导出前会自动验证配置，验证失败时会显示错误详情",
                "也可先用 Ctrl+T 手动验证，提前发现配置问题",
                "导出时需选择输出目录，素材会保存到该目录中",
            ]),
        ])
        layout.addWidget(tutorial)

        return widget

    def _create_mouse_tab(self) -> QWidget:
        """创建鼠标操作选项卡"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 裁剪框操作
        crop_card = CardWidget()
        crop_layout = QVBoxLayout(crop_card)
        crop_layout.setContentsMargins(16, 12, 16, 12)
        crop_title = SubtitleLabel("裁剪框操作")
        crop_layout.addWidget(crop_title)

        operations = [
            ("拖动裁剪框内部", "移动整个裁剪框"),
            ("拖动角落手柄", "调整裁剪框大小（保持比例）"),
            ("左上角手柄", "从左上角调整大小"),
            ("右下角手柄", "从右下角调整大小"),
        ]

        for op, desc in operations:
            row = QHBoxLayout()
            op_label = StrongBodyLabel(op)
            op_label.setMinimumWidth(120)
            row.addWidget(op_label)
            row.addWidget(BodyLabel(desc))
            row.addStretch()
            crop_layout.addLayout(row)

        # 裁剪框补充说明
        crop_detail = CaptionLabel(
            "四个角落手柄均支持缩放，自动保持目标宽高比。"
            "光标自动变化提示当前操作模式。"
        )
        crop_detail.setWordWrap(True)
        apply_themed_style(
            crop_detail,
            f"CaptionLabel {{ color: {COLOR_TEXT_MUTED[0]}; font-style: italic; }}",
            f"CaptionLabel {{ color: {COLOR_TEXT_MUTED[1]}; font-style: italic; }}"
        )
        crop_layout.addWidget(crop_detail)

        layout.addWidget(crop_card)

        # 时间轴操作
        timeline_card = CardWidget()
        timeline_layout = QVBoxLayout(timeline_card)
        timeline_layout.setContentsMargins(16, 12, 16, 12)
        timeline_title = SubtitleLabel("时间轴操作")
        timeline_layout.addWidget(timeline_title)

        timeline_ops = [
            ("点击时间轴", "跳转到指定位置"),
            ("拖动时间轴", "快速浏览视频"),
        ]

        for op, desc in timeline_ops:
            row = QHBoxLayout()
            op_label = StrongBodyLabel(op)
            op_label.setMinimumWidth(120)
            row.addWidget(op_label)
            row.addWidget(BodyLabel(desc))
            row.addStretch()
            timeline_layout.addLayout(row)

        # 时间轴补充说明
        timeline_detail = CaptionLabel("拖动时有节流保护，不会卡顿。")
        timeline_detail.setWordWrap(True)
        apply_themed_style(
            timeline_detail,
            f"CaptionLabel {{ color: {COLOR_TEXT_MUTED[0]}; font-style: italic; }}",
            f"CaptionLabel {{ color: {COLOR_TEXT_MUTED[1]}; font-style: italic; }}"
        )
        timeline_layout.addWidget(timeline_detail)

        layout.addWidget(timeline_card)

        # 注意事项
        notes = self._create_notes_section([
            "裁剪框操作需要先加载视频或图片",
            "裁剪框大小有最小限制（宽度 >= 90 像素）",
            "鼠标悬停在角落手柄上时光标会变为对角线箭头",
        ])
        layout.addWidget(notes)

        return widget
