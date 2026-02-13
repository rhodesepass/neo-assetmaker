"""
过渡图片预览组件 - 左右并排显示进入过渡和循环过渡图片，支持交互式裁切
"""
import logging

from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal

from gui.widgets.video_preview import VideoPreviewWidget

logger = logging.getLogger(__name__)


class TransitionPreviewWidget(QWidget):
    """过渡图片预览组件，左右并排显示进入过渡和循环过渡图片，支持裁切框交互"""

    # cropbox 变化信号，发射 trans_type ("in" 或 "loop")
    transition_crop_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        """设置UI"""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(10)

        # 左侧：进入过渡
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(5)

        label_in_title = QLabel("进入过渡")
        label_in_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label_in_title.setStyleSheet("color: #ccc; font-size: 13px; font-weight: bold;")
        left_layout.addWidget(label_in_title)

        self.preview_in = VideoPreviewWidget()
        self.preview_in.cropbox_changed.connect(
            lambda *_: self.transition_crop_changed.emit("in")
        )
        left_layout.addWidget(self.preview_in, stretch=1)

        main_layout.addWidget(left_widget, stretch=1)

        # 右侧：循环过渡
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(5)

        label_loop_title = QLabel("循环过渡")
        label_loop_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label_loop_title.setStyleSheet("color: #ccc; font-size: 13px; font-weight: bold;")
        right_layout.addWidget(label_loop_title)

        self.preview_loop = VideoPreviewWidget()
        self.preview_loop.cropbox_changed.connect(
            lambda *_: self.transition_crop_changed.emit("loop")
        )
        right_layout.addWidget(self.preview_loop, stretch=1)

        main_layout.addWidget(right_widget, stretch=1)

    def load_image(self, trans_type: str, image_path: str):
        """加载并显示过渡图片

        Args:
            trans_type: "in" 或 "loop"
            image_path: 图片文件的绝对路径
        """
        preview = self.preview_in if trans_type == "in" else self.preview_loop
        if preview.load_static_image_from_file(image_path):
            logger.info(f"已加载{trans_type}过渡图片: {image_path}")
        else:
            logger.warning(f"无法加载过渡图片: {image_path}")

    def clear_image(self, trans_type: str):
        """清除过渡图片

        Args:
            trans_type: "in" 或 "loop"
        """
        preview = self.preview_in if trans_type == "in" else self.preview_loop
        preview.clear()

    def get_cropbox(self, trans_type: str):
        """获取指定过渡图片的裁切框坐标

        Args:
            trans_type: "in" 或 "loop"

        Returns:
            (x, y, w, h) 元组
        """
        preview = self.preview_in if trans_type == "in" else self.preview_loop
        return preview.get_cropbox()

    def set_target_resolution(self, width: int, height: int):
        """设置两个预览的目标裁切分辨率"""
        self.preview_in.set_target_resolution(width, height)
        self.preview_loop.set_target_resolution(width, height)
