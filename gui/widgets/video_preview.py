"""
视频预览组件 - 支持视频播放和裁剪框交互
"""
import logging
from typing import Optional, Tuple, TYPE_CHECKING

import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

from PyQt6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint
from PyQt6.QtGui import QImage, QPixmap, QMouseEvent, QKeyEvent

if TYPE_CHECKING:
    from config.epconfig import EPConfig

logger = logging.getLogger(__name__)

# 默认目标裁剪尺寸
DEFAULT_TARGET_WIDTH = 360
DEFAULT_TARGET_HEIGHT = 640


class VideoPreviewWidget(QWidget):
    """视频预览组件，支持裁剪框交互"""

    # 信号
    cropbox_changed = pyqtSignal(int, int, int, int)  # x, y, w, h
    frame_changed = pyqtSignal(int)  # 当前帧号
    playback_state_changed = pyqtSignal(bool)  # 播放状态
    video_loaded = pyqtSignal(int, float)  # 总帧数, fps
    rotation_changed = pyqtSignal(int)  # 旋转角度 (0, 90, 180, 270)

    # 拖拽模式
    DRAG_NONE = 0
    DRAG_MOVE = 1
    DRAG_RESIZE_TL = 2  # 左上
    DRAG_RESIZE_TR = 3  # 右上
    DRAG_RESIZE_BL = 4  # 左下
    DRAG_RESIZE_BR = 5  # 右下

    def __init__(self, parent=None):
        super().__init__(parent)

        # 视频状态
        self.cap = None
        self.video_path: str = ""
        self.video_fps: float = 30.0
        self.video_width: int = 0
        self.video_height: int = 0
        self.total_frames: int = 0
        self.current_frame_index: int = 0
        self.current_frame = None

        # 播放状态
        self.is_playing: bool = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_timer_tick)

        # 裁剪框
        self.target_width = DEFAULT_TARGET_WIDTH
        self.target_height = DEFAULT_TARGET_HEIGHT
        self.target_aspect_ratio = self.target_width / self.target_height
        self.cropbox = [0, 0, self.target_width, self.target_height]

        # 显示缩放
        self.display_scale: float = 1.0
        self.display_offset_x: int = 0
        self.display_offset_y: int = 0

        # 拖拽状态
        self.drag_mode: int = self.DRAG_NONE
        self.drag_start_pos: Optional[QPoint] = None
        self.drag_start_cropbox: list = []
        self.handle_size: int = 15

        # 预览模式
        self._preview_mode: bool = False
        self._epconfig: Optional["EPConfig"] = None
        self._overlay_renderer = None

        # 视频旋转 (0, 90, 180, 270)
        self._rotation: int = 0

        self._setup_ui()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        # 视频显示标签
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setMinimumSize(320, 180)
        self.video_label.setStyleSheet(
            "background-color: #1a1a1a; border: 1px solid #333;"
        )
        self.video_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.video_label.setText("未加载视频")
        self.video_label.setMouseTracking(True)
        self.video_label.setToolTip("视频预览区域\nWASD移动裁剪框，空格播放/暂停")
        layout.addWidget(self.video_label)

        # 信息标签（控制按钮已移至时间轴组件）
        self.info_label = QLabel("帧: 0/0 | 裁剪: (0, 0, 0, 0)")
        self.info_label.setStyleSheet("color: #888; font-size: 11px; padding: 2px 5px;")
        layout.addWidget(self.info_label)

    def set_target_resolution(self, width: int, height: int):
        """设置目标裁剪分辨率"""
        self.target_width = width
        self.target_height = height
        self.target_aspect_ratio = width / height
        if self.current_frame is not None:
            self._init_cropbox()
            self._display_frame(self.current_frame)

    def load_video(self, path: str) -> bool:
        """加载视频"""
        logger.info(f"尝试加载视频: {path}")

        if not HAS_CV2:
            logger.error("OpenCV 未安装")
            self.video_label.setText("未安装 opencv-python")
            return False

        import os
        if not os.path.exists(path):
            logger.error(f"视频文件不存在: {path}")
            self.video_label.setText(f"文件不存在: {path}")
            return False

        if self.cap is not None:
            self.cap.release()
        self.pause()

        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            logger.error(f"无法打开视频: {path}")
            self.video_label.setText("无法加载视频")
            return False

        self.video_path = path
        self.video_fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.video_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.video_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.current_frame_index = 0

        logger.info(
            f"视频已加载: {self.video_width}x{self.video_height}, "
            f"{self.total_frames} 帧, {self.video_fps:.1f} FPS"
        )

        self._init_cropbox()
        self._read_and_display_frame()
        self.video_loaded.emit(self.total_frames, self.video_fps)
        return True

    def load_static_image_from_file(self, image_path: str) -> bool:
        """从文件路径加载静态图片"""
        if not HAS_CV2:
            logger.error("OpenCV 未安装")
            return False

        import os
        if not os.path.exists(image_path):
            logger.error(f"图片文件不存在: {image_path}")
            return False

        # 使用 open + cv2.imdecode 避免 OpenCV 的中文路径编码问题
        with open(image_path, 'rb') as f:
            data = np.frombuffer(f.read(), dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
        if img is None:
            logger.error(f"无法读取图片: {image_path}")
            return False

        # BGRA → BGR（如果有 alpha 通道）
        if len(img.shape) == 3 and img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

        self._load_static_frame(img)
        logger.info(f"已加载静态图片: {image_path} ({img.shape[1]}x{img.shape[0]})")
        return True

    def load_static_image_from_array(self, frame: np.ndarray) -> bool:
        """从 numpy 数组加载静态图片"""
        if frame is None:
            return False
        self._load_static_frame(frame.copy())
        logger.info(f"已加载静态图片帧: {frame.shape[1]}x{frame.shape[0]}")
        return True

    def _load_static_frame(self, frame: np.ndarray):
        """内部方法：设置静态图片到预览"""
        # 释放之前的视频（如果有）
        self.pause()
        if self.cap is not None:
            self.cap.release()
            self.cap = None

        self.video_width = frame.shape[1]
        self.video_height = frame.shape[0]
        self.current_frame = frame
        self.total_frames = 1
        self.current_frame_index = 0

        self._init_cropbox()
        self._display_frame(frame)

    def _init_cropbox(self):
        """初始化裁剪框（在旋转后坐标系中）"""
        rotated_w, rotated_h = self._get_rotated_video_size()
        w, h = self.target_width, self.target_height

        if w > rotated_w:
            w = rotated_w
            h = int(w / self.target_aspect_ratio)
        if h > rotated_h:
            h = rotated_h
            w = int(h * self.target_aspect_ratio)

        x = (rotated_w - w) // 2
        y = (rotated_h - h) // 2
        self.cropbox = [x, y, w, h]
        self._emit_cropbox_changed()

    def _bound_cropbox(self):
        """限制裁剪框在旋转后视频范围内"""
        rotated_w, rotated_h = self._get_rotated_video_size()
        x, y, w, h = self.cropbox

        if w > rotated_w:
            w = rotated_w
            h = int(w / self.target_aspect_ratio)
        if h > rotated_h:
            h = rotated_h
            w = int(h * self.target_aspect_ratio)

        # 最小尺寸
        w = max(w, 90)
        h = max(h, int(90 / self.target_aspect_ratio))

        # 边界限制
        x = max(0, min(x, rotated_w - w))
        y = max(0, min(y, rotated_h - h))
        self.cropbox = [x, y, w, h]

    def _emit_cropbox_changed(self):
        """发送裁剪框变更信号"""
        x, y, w, h = self.cropbox
        self.cropbox_changed.emit(x, y, w, h)
        self._update_info_label()

    def _update_info_label(self):
        """更新信息标签"""
        x, y, w, h = self.cropbox
        rotation_str = f" | 旋转: {self._rotation}°" if self._rotation != 0 else ""
        self.info_label.setText(
            f"帧: {self.current_frame_index}/{self.total_frames} | "
            f"裁剪: ({x}, {y}, {w}, {h}){rotation_str}"
        )

    def _read_and_display_frame(self):
        """读取并显示当前帧"""
        if self.cap is None:
            logger.warning("_read_and_display_frame: cap 为 None")
            return

        ret, frame = self.cap.read()
        if not ret:
            logger.warning(f"无法读取帧 {self.current_frame_index}")
            self.pause()
            return

        self.current_frame = frame
        logger.debug(f"读取帧 {self.current_frame_index}, 尺寸: {frame.shape}")
        self._display_frame(frame)
        self.frame_changed.emit(self.current_frame_index)
        self._update_info_label()

    def _display_frame(self, frame):
        """显示帧"""
        if frame is None or not HAS_CV2:
            return

        # 应用旋转
        rotated_frame = self._apply_rotation(frame)

        x, y, w, h = self.cropbox

        if self._preview_mode:
            # 预览模式：显示裁剪后的最终效果
            display_frame = self._render_preview_frame(rotated_frame)
        else:
            # 编辑模式：显示完整帧+裁剪框
            display_frame = rotated_frame.copy()

            # cropbox 已经在旋转后坐标系中，直接使用
            cv2.rectangle(display_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

            # 绘制角落手柄
            hs = 8
            handle_color = (0, 200, 255)
            for px, py in [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]:
                cv2.rectangle(
                    display_frame,
                    (px - hs, py - hs), (px + hs, py + hs),
                    handle_color, -1
                )

            # 信息叠加
            cv2.putText(
                display_frame,
                f"Frame: {self.current_frame_index}/{self.total_frames}",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1
            )
            cv2.putText(
                display_frame,
                f"Crop: x={x} y={y} w={w} h={h}",
                (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1
            )

        # 转换为QPixmap
        rgb_frame = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
        h_frame, w_frame, ch = rgb_frame.shape
        q_image = QImage(
            rgb_frame.data, w_frame, h_frame,
            ch * w_frame, QImage.Format.Format_RGB888
        )

        label_size = self.video_label.size()
        pixmap = QPixmap.fromImage(q_image).scaled(
            label_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        # 更新显示参数（仅编辑模式需要用于坐标转换）
        if not self._preview_mode:
            # 使用旋转后的帧宽度计算缩放比例
            rotated_width = self.video_height if self._rotation in (90, 270) else self.video_width
            self.display_scale = pixmap.width() / rotated_width if rotated_width > 0 else 1.0
            self.display_offset_x = (label_size.width() - pixmap.width()) // 2
            self.display_offset_y = (label_size.height() - pixmap.height()) // 2

        self.video_label.setPixmap(pixmap)

    def _render_preview_frame(self, frame) -> np.ndarray:
        """渲染预览帧（裁剪+叠加UI）"""
        x, y, w, h = self.cropbox

        # 裁剪
        cropped = frame[y:y+h, x:x+w].copy()

        # 缩放到目标分辨率
        preview_frame = cv2.resize(cropped, (self.target_width, self.target_height))

        # 应用叠加UI
        if self._epconfig and self._overlay_renderer:
            from config.epconfig import OverlayType
            if self._epconfig.overlay.type == OverlayType.ARKNIGHTS:
                preview_frame = self._overlay_renderer.render_arknights_overlay(
                    preview_frame,
                    self._epconfig.overlay.arknights_options
                )

        return preview_frame

    def _on_timer_tick(self):
        """定时器回调"""
        if self.cap is None:
            return
        self.current_frame_index += 1
        if self.current_frame_index >= self.total_frames:
            self.current_frame_index = 0
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self._read_and_display_frame()

    def play(self):
        """播放"""
        if self.cap is None or self.is_playing:
            return
        # 使用 round() 减少截断误差
        interval = round(1000 / self.video_fps)
        self.timer.start(interval)
        self.is_playing = True
        self.playback_state_changed.emit(True)

    def pause(self):
        """暂停"""
        self.timer.stop()
        self.is_playing = False
        self.playback_state_changed.emit(False)

    def toggle_play(self):
        """切换播放/暂停"""
        if self.is_playing:
            self.pause()
        else:
            self.play()

    def next_frame(self):
        """下一帧"""
        if self.cap is None:
            return
        self.pause()
        self.current_frame_index = min(self.current_frame_index + 1, self.total_frames - 1)
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame_index)
        self._read_and_display_frame()

    def prev_frame(self):
        """上一帧"""
        if self.cap is None:
            return
        self.pause()
        self.current_frame_index = max(self.current_frame_index - 1, 0)
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame_index)
        self._read_and_display_frame()

    def seek_to_frame(self, index: int):
        """跳转到指定帧"""
        if self.cap is None:
            return
        index = max(0, min(index, self.total_frames - 1))
        self.current_frame_index = index
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        self._read_and_display_frame()

    def get_current_frame(self) -> int:
        """获取当前帧号"""
        return self.current_frame_index

    def get_cropbox(self) -> Tuple[int, int, int, int]:
        """获取裁剪框（旋转后坐标系）"""
        return tuple(self.cropbox)

    def _cropbox_to_original_coords(self, x: int, y: int, w: int, h: int) -> Tuple[int, int, int, int]:
        """将 cropbox 从旋转后坐标系逆变换到原始视频坐标系（用于导出）"""
        if self._rotation == 0:
            return (x, y, w, h)
        elif self._rotation == 90:
            # 旋转后坐标 -> 原始坐标
            return (y, self.video_height - x - w, h, w)
        elif self._rotation == 180:
            return (self.video_width - x - w, self.video_height - y - h, w, h)
        elif self._rotation == 270:
            return (self.video_width - y - h, x, h, w)
        return (x, y, w, h)

    def get_cropbox_for_export(self) -> Tuple[int, int, int, int]:
        """获取导出用的 cropbox（原始坐标系）"""
        x, y, w, h = self.cropbox
        return self._cropbox_to_original_coords(x, y, w, h)

    def set_cropbox(self, x: int, y: int, w: int, h: int):
        """设置裁剪框"""
        self.cropbox = [x, y, w, h]
        self._bound_cropbox()
        self._emit_cropbox_changed()
        if self.current_frame is not None:
            self._display_frame(self.current_frame)

    def get_video_info(self) -> Tuple[float, int, int, int]:
        """获取视频信息 (fps, total_frames, width, height)"""
        return (self.video_fps, self.total_frames, self.video_width, self.video_height)

    def set_preview_mode(self, enabled: bool):
        """设置预览模式"""
        self._preview_mode = enabled
        if self.current_frame is not None:
            self._display_frame(self.current_frame)

    def is_preview_mode(self) -> bool:
        """获取预览模式状态"""
        return self._preview_mode

    def set_rotation(self, degrees: int):
        """设置视频旋转角度 (0, 90, 180, 270)"""
        degrees = degrees % 360
        if degrees not in (0, 90, 180, 270):
            degrees = 0
        if self._rotation != degrees:
            self._rotation = degrees
            self.rotation_changed.emit(degrees)
            # 旋转后只验证边界，不重新初始化 cropbox
            # 这样 cropbox 在屏幕上的视觉位置保持不变
            if self.video_width > 0 and self.video_height > 0:
                self._bound_cropbox()  # 只验证边界，确保在新尺寸范围内
            if self.current_frame is not None:
                self._display_frame(self.current_frame)

    def get_rotation(self) -> int:
        """获取视频旋转角度"""
        return self._rotation

    def rotate_clockwise(self):
        """顺时针旋转90度"""
        new_rotation = (self._rotation + 90) % 360
        self.set_rotation(new_rotation)

    def rotate_counterclockwise(self):
        """逆时针旋转90度"""
        new_rotation = (self._rotation - 90) % 360
        self.set_rotation(new_rotation)

    def _apply_rotation(self, frame: np.ndarray) -> np.ndarray:
        """应用旋转到帧"""
        if self._rotation == 0:
            return frame
        elif self._rotation == 90:
            return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif self._rotation == 180:
            return cv2.rotate(frame, cv2.ROTATE_180)
        elif self._rotation == 270:
            return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return frame

    def _get_rotated_video_size(self) -> Tuple[int, int]:
        """获取旋转后的视频尺寸"""
        if self._rotation in (90, 270):
            return (self.video_height, self.video_width)
        return (self.video_width, self.video_height)

    def set_epconfig(self, config: "EPConfig"):
        """设置配置（用于叠加UI渲染）"""
        self._epconfig = config
        # 初始化叠加渲染器
        if self._overlay_renderer is None:
            from core.overlay_renderer import OverlayRenderer
            self._overlay_renderer = OverlayRenderer()
        if self.current_frame is not None:
            self._display_frame(self.current_frame)

    def _display_to_rotated_coords(self, pos: QPoint) -> Tuple[int, int]:
        """将显示坐标转换为旋转后视频坐标"""
        label_pos = self.video_label.mapFrom(self, pos)
        rx = int((label_pos.x() - self.display_offset_x) / self.display_scale) if self.display_scale > 0 else 0
        ry = int((label_pos.y() - self.display_offset_y) / self.display_scale) if self.display_scale > 0 else 0
        return (rx, ry)

    def _get_drag_mode(self, vx: int, vy: int) -> int:
        """判断拖拽模式"""
        x, y, w, h = self.cropbox
        hs = self.handle_size

        if abs(vx - x) < hs and abs(vy - y) < hs:
            return self.DRAG_RESIZE_TL
        if abs(vx - (x + w)) < hs and abs(vy - y) < hs:
            return self.DRAG_RESIZE_TR
        if abs(vx - x) < hs and abs(vy - (y + h)) < hs:
            return self.DRAG_RESIZE_BL
        if abs(vx - (x + w)) < hs and abs(vy - (y + h)) < hs:
            return self.DRAG_RESIZE_BR
        if x <= vx <= x + w and y <= vy <= y + h:
            return self.DRAG_MOVE
        return self.DRAG_NONE

    def mousePressEvent(self, event: QMouseEvent):
        """鼠标按下"""
        if event.button() == Qt.MouseButton.LeftButton and self.current_frame is not None:
            rx, ry = self._display_to_rotated_coords(event.pos())
            self.drag_mode = self._get_drag_mode(rx, ry)
            if self.drag_mode != self.DRAG_NONE:
                self.drag_start_pos = event.pos()
                self.drag_start_cropbox = self.cropbox.copy()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        """鼠标移动"""
        if self.drag_mode != self.DRAG_NONE and self.drag_start_pos is not None:
            crx, cry = self._display_to_rotated_coords(event.pos())
            srx, sry = self._display_to_rotated_coords(self.drag_start_pos)
            dx, dy = crx - srx, cry - sry
            sx, sy, sw, sh = self.drag_start_cropbox

            if self.drag_mode == self.DRAG_MOVE:
                self.cropbox = [sx + dx, sy + dy, sw, sh]
            elif self.drag_mode == self.DRAG_RESIZE_BR:
                new_w = sw + dx
                self.cropbox = [sx, sy, new_w, int(new_w / self.target_aspect_ratio)]
            elif self.drag_mode == self.DRAG_RESIZE_TL:
                new_w = sw - dx
                new_h = int(new_w / self.target_aspect_ratio)
                self.cropbox = [sx + (sw - new_w), sy + (sh - new_h), new_w, new_h]
            elif self.drag_mode == self.DRAG_RESIZE_TR:
                new_w = sw + dx
                new_h = int(new_w / self.target_aspect_ratio)
                self.cropbox = [sx, sy + (sh - new_h), new_w, new_h]
            elif self.drag_mode == self.DRAG_RESIZE_BL:
                new_w = sw - dx
                new_h = int(new_w / self.target_aspect_ratio)
                self.cropbox = [sx + (sw - new_w), sy, new_w, new_h]

            self._bound_cropbox()
            self._emit_cropbox_changed()
            if self.current_frame is not None:
                self._display_frame(self.current_frame)

        elif self.current_frame is not None:
            rx, ry = self._display_to_rotated_coords(event.pos())
            mode = self._get_drag_mode(rx, ry)
            cursors = {
                self.DRAG_RESIZE_TL: Qt.CursorShape.SizeFDiagCursor,
                self.DRAG_RESIZE_BR: Qt.CursorShape.SizeFDiagCursor,
                self.DRAG_RESIZE_TR: Qt.CursorShape.SizeBDiagCursor,
                self.DRAG_RESIZE_BL: Qt.CursorShape.SizeBDiagCursor,
                self.DRAG_MOVE: Qt.CursorShape.SizeAllCursor,
            }
            self.setCursor(cursors.get(mode, Qt.CursorShape.ArrowCursor))

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        """鼠标释放"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_mode = self.DRAG_NONE
            self.drag_start_pos = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        """键盘事件"""
        if self.current_frame is None:
            super().keyPressEvent(event)
            return

        key = event.key()
        step = 10

        # 播放/帧跳转操作需要视频
        if key == Qt.Key.Key_Space and self.cap is not None:
            self.toggle_play()
        elif key == Qt.Key.Key_Left and self.cap is not None:
            self.prev_frame()
        elif key == Qt.Key.Key_Right and self.cap is not None:
            self.next_frame()
        # WASD 裁剪框移动（视频和静态图片都支持）
        elif key == Qt.Key.Key_W:
            self.cropbox[1] -= step
        elif key == Qt.Key.Key_S:
            self.cropbox[1] += step
        elif key == Qt.Key.Key_A:
            self.cropbox[0] -= step
        elif key == Qt.Key.Key_D:
            self.cropbox[0] += step
        else:
            super().keyPressEvent(event)
            return

        self._bound_cropbox()
        self._emit_cropbox_changed()
        if self.current_frame is not None:
            self._display_frame(self.current_frame)

    def resizeEvent(self, event):
        """窗口大小变化时重绘当前帧"""
        super().resizeEvent(event)
        if self.current_frame is not None:
            self._display_frame(self.current_frame)

    def closeEvent(self, event):
        """关闭事件"""
        self.pause()
        if self.cap is not None:
            self.cap.release()
        super().closeEvent(event)

    def clear(self):
        """清空预览状态"""
        self.pause()
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self.video_path = ""
        self.total_frames = 0
        self.current_frame_index = 0
        self.current_frame = None
        self.video_label.clear()
        self.video_label.setText("未加载视频")
        self.info_label.setText("帧: 0/0 | 裁剪: (0, 0, 0, 0)")
