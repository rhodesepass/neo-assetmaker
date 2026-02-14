"""
欢迎对话框 - 首次运行时显示
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class WelcomeDialog(QDialog):
    """欢迎对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("欢迎使用明日方舟通行证素材制作器")
        self.setMinimumWidth(500)
        self.setModal(True)
        self._setup_ui()

    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(25, 25, 25, 25)

        # 标题
        title_label = QLabel("欢迎使用明日方舟通行证素材制作器")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        # 操作流程说明
        intro_label = QLabel("基本操作流程:")
        intro_font = QFont()
        intro_font.setBold(True)
        intro_label.setFont(intro_font)
        layout.addWidget(intro_label)

        steps = [
            ("1. 开始编辑", "启动后即可编辑，首次保存时选择工作目录"),
            ("2. 配置视频", "在\"视频配置\"选项卡中选择循环视频文件"),
            ("3. 调整裁剪框", "在预览区域拖动裁剪框，使用WASD微调位置"),
            ("4. 设置入出点", "在时间轴上设置视频的起止帧"),
            ("5. 配置叠加UI", "在\"叠加UI\"选项卡中配置干员信息"),
            ("6. 导出素材", "点击\"导出素材\"按钮生成最终文件"),
        ]

        for step_title, step_desc in steps:
            step_layout = QVBoxLayout()
            step_layout.setSpacing(2)

            title = QLabel(step_title)
            title_font = QFont()
            title_font.setBold(True)
            title.setFont(title_font)
            step_layout.addWidget(title)

            desc = QLabel(step_desc)
            desc.setStyleSheet("color: #666; margin-left: 15px;")
            step_layout.addWidget(desc)

            layout.addLayout(step_layout)

        # 注意事项
        note_label = QLabel(
            "注意: 传入素材时需要进入扩列图信息或其他页面，"
            "否则有概率导致素材传入失败"
        )
        note_label.setStyleSheet(
            "color: #d32f2f; background-color: #ffebee; "
            "padding: 8px; border-radius: 4px;"
        )
        note_label.setWordWrap(True)
        layout.addWidget(note_label)

        # 分隔线
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line2)

        # 快捷键提示
        shortcut_label = QLabel("提示: 按 F1 键可随时查看快捷键帮助")
        shortcut_label.setStyleSheet("color: #4285f4;")
        layout.addWidget(shortcut_label)

        # 底部按钮
        button_layout = QHBoxLayout()

        self.check_dont_show = QCheckBox("不再显示")
        button_layout.addWidget(self.check_dont_show)

        button_layout.addStretch()

        self.btn_shortcuts = QPushButton("查看快捷键")
        self.btn_shortcuts.clicked.connect(self._show_shortcuts)
        button_layout.addWidget(self.btn_shortcuts)

        self.btn_start = QPushButton("开始使用")
        self.btn_start.setDefault(True)
        self.btn_start.clicked.connect(self.accept)
        button_layout.addWidget(self.btn_start)

        layout.addLayout(button_layout)

    def _show_shortcuts(self):
        """显示快捷键帮助"""
        from gui.dialogs.shortcuts_dialog import ShortcutsDialog
        dialog = ShortcutsDialog(self)
        dialog.exec()

    def should_not_show_again(self) -> bool:
        """是否不再显示"""
        return self.check_dont_show.isChecked()
