"""
视频预览组件 - 支持视频播放和裁剪框交互

视频帧读取和处理已移至后台线程 (FrameReaderThread)，避免阻塞 UI 事件循环。

Qt 6 官方文档依据：
- 主线程长耗时操作阻塞事件循环 (https://doc.qt.io/qt-6/threads-qobjects.html)
- QImage 可安全在工作线程创建 (https://doc.qt.io/qt-6/qimage.html#details)
- QPixmap 必须在主线程创建 (https://doc.qt.io/qt-6/qpixmap.html#details)
- 跨线程信号自动 QueuedConnection (https://doc.qt.io/qt-6/threads-qobjects.html)
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
from qfluentwidgets import CaptionLabel, setCustomStyleSheet

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
    rotation_changed = pyqtSignal(int)  # 旋转角度 (0-359)

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
        self.video_path: str = ""
        self.video_fps: float = 30.0
        self.video_width: int = 0
        self.video_height: int = 0
        self.total_frames: int = 0
        self.current_frame_index: int = 0
        self.current_frame = None

        # 后台帧读取线程（替代旧的 self.cap）
        self._reader_thread = None
        # 标记是否有活跃的视频（用于替代 self.cap is not None 的检查）
        self._has_video: bool = False

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

        # 视频旋转 (0-359 任意整数角度)
        self._rotation: int = 0

        # 图片循环模式（load_image_as_loop 设置）
        self._loop_frame: Optional[np.ndarray] = None

        self._setup_ui()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        # 视频显示标签 — 始终深色背景（剪映/CapCut 风格）
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setMinimumSize(320, 180)
        setCustomStyleSheet(
            self.video_label,
            "background-color: #1a1a1a; border: none; border-radius: 8px; color: #888; font-size: 14px; font-weight: 500;",
            "background-color: #0a0a0a; border: none; border-radius: 8px; color: #666; font-size: 14px; font-weight: 500;"
        )
        self.video_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.video_label.setText("未加载视频")
        self.video_label.setMouseTracking(True)
        self.video_label.setToolTip("视频预览区域\nWASD移动裁剪框，空格播放/暂停")
        layout.addWidget(self.video_label)

        # 信息标签 — 透明背景，浮于深色预览区上方
        self.info_label = CaptionLabel("帧: 0/0 | 裁剪: (0, 0, 0, 0)")
        setCustomStyleSheet(
            self.info_label,
            "color: #999; padding: 4px 10px; background-color: transparent; border: none;",
            "color: #777; padding: 4px 10px; background-color: transparent; border: none;"
        )
        layout.addWidget(self.info_label)

    # ── 后台线程生命周期管理 ──

    def _stop_reader_thread(self):
        """安全停止后台帧读取线程"""
        if self._reader_thread is not None:
            self._reader_thread.request_stop()
            self._reader_thread.wait(3000)  # 最多等待 3 秒
            if self._reader_thread.isRunning():
                logger.warning("FrameReaderThread 未能在 3 秒内退出，强制终止")
                self._reader_thread.terminate()
                self._reader_thread.wait(1000)
            self._reader_thread = None
        self._has_video = False

    def _on_video_opened(self, fps: float, width: int, height: int,
                         total_frames: int):
        """后台线程成功打开视频的回调（主线程执行）"""
        self.video_fps = fps
        self.video_width = width
        self.video_height = height
        self.total_frames = total_frames
        self.current_frame_index = 0
        self._has_video = True

        logger.info(
            f"视频已加载: {width}x{height}, "
            f"{total_frames} 帧, {fps:.1f} FPS"
        )

        self._init_cropbox()
        # 同步 cropbox 到工作线程
        self._sync_state_to_reader()
        self.video_loaded.emit(total_frames, fps)

    def _on_video_open_failed(self, error_msg: str):
        """视频打开失败的回调"""
        logger.error(f"视频加载失败: {error_msg}")
        self.video_label.setText(f"加载失败: {error_msg}")
        self._has_video = False

    def _on_frame_ready(self, frame_index: int, qimage: QImage,
                        raw_frame: object):
        """后台线程帧就绪回调（主线程执行 — Qt QueuedConnection 保证）

        主线程仅做 QPixmap.fromImage() + setPixmap()，非常轻量。
        """
        self.current_frame_index = frame_index
        self.current_frame = raw_frame  # 保存原始帧，供 cropbox 交互即时重绘

        # QImage → QPixmap（必须在主线程）
        label_size = self.video_label.size()
        pixmap = QPixmap.fromImage(qimage).scaled(
            label_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        # 更新显示参数（仅编辑模式需要用于坐标转换）
        if not self._preview_mode:
            rotated_width, _ = self._get_rotated_video_size()
            self.display_scale = (
                pixmap.width() / rotated_width if rotated_width > 0 else 1.0)
            self.display_offset_x = (label_size.width() - pixmap.width()) // 2
            self.display_offset_y = (
                label_size.height() - pixmap.height()) // 2

        self.video_label.setPixmap(pixmap)
        self.frame_changed.emit(frame_index)
        self._update_info_label()

    def _sync_state_to_reader(self):
        """将当前状态同步到后台线程"""
        if self._reader_thread is not None:
            self._reader_thread.request_set_rotation(self._rotation)
            self._reader_thread.request_set_cropbox(self.cropbox)
            self._reader_thread.request_set_preview_params(
                self._preview_mode, self.target_width, self.target_height,
                self._epconfig, self._overlay_renderer)

    # ── 公共 API（保持不变） ──

    def set_target_resolution(self, width: int, height: int):
        """设置目标裁剪分辨率"""
        self.target_width = width
        self.target_height = height
        self.target_aspect_ratio = width / height
        if self.current_frame is not None:
            self._init_cropbox()
            self._sync_state_to_reader()
            self._display_frame(self.current_frame)

    def load_video(self, path: str) -> bool:
        """加载视频（异步，不阻塞 UI）

        返回 True 表示加载请求已提交（路径有效），
        实际加载结果通过 video_loaded 信号通知。
        """
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

        # 停止旧的读取线程和播放
        self._stop_reader_thread()
        self.pause()
        self._loop_frame = None  # 清除图片循环状态

        self.video_path = path
        self.video_label.setText("正在加载视频...")

        # 创建并启动后台帧读取线程
        from gui.widgets.frame_reader_thread import FrameReaderThread
        self._reader_thread = FrameReaderThread(self)
        self._reader_thread.video_opened.connect(self._on_video_opened)
        self._reader_thread.video_open_failed.connect(self._on_video_open_failed)
        self._reader_thread.frame_ready.connect(self._on_frame_ready)
        self._reader_thread.start()

        # 同步当前状态到新线程，然后请求打开视频
        self._sync_state_to_reader()
        self._reader_thread.request_open(path)

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
        logger.info(
            f"已加载静态图片: {image_path} ({img.shape[1]}x{img.shape[0]})")
        return True

    def load_static_image_from_array(self, frame: np.ndarray) -> bool:
        """从 numpy 数组加载静态图片"""
        if frame is None:
            return False
        self._load_static_frame(frame.copy())
        logger.info(f"已加载静态图片帧: {frame.shape[1]}x{frame.shape[0]}")
        return True

    def update_static_frame(self, frame: np.ndarray) -> bool:
        """更新静态图片帧数据，保留当前 cropbox 位置

        用于截取帧编辑标签页中，源视频帧变化时更新显示，
        同时保留用户已调整的 cropbox。
        """
        if frame is None:
            return False
        frame = frame.copy()
        self.video_width = frame.shape[1]
        self.video_height = frame.shape[0]
        self.current_frame = frame
        self._bound_cropbox()
        self._display_frame(frame)
        return True

    def load_image_as_loop(self, path: str, fps: float = 30.0,
                          duration: float = 5.0) -> bool:
        """将图片加载为循环视频（支持播放/暂停/裁剪框/时间轴）

        Args:
            path: 图片文件路径
            fps: 模拟帧率（默认 30fps）
            duration: 单次循环时长秒数（默认 5 秒）
        """
        if not self.load_static_image_from_file(path):
            return False

        # 覆盖 _load_static_frame 设置的 total_frames=1
        self._loop_frame = self.current_frame.copy()
        self.video_fps = fps
        self.total_frames = int(fps * duration)
        self.video_loaded.emit(self.total_frames, self.video_fps)
        logger.info(
            f"图片已加载为循环视频: {path} "
            f"({self.total_frames} 帧, {fps}fps, {duration}s)"
        )
        return True

    def _load_static_frame(self, frame: np.ndarray):
        """内部方法：设置静态图片到预览"""
        # 释放之前的视频线程（如果有）
        self.pause()
        self._stop_reader_thread()
        self._loop_frame = None  # 清除图片循环状态

        self.video_width = frame.shape[1]
        self.video_height = frame.shape[0]
        self.current_frame = frame
        self.total_frames = 1
        self.current_frame_index = 0

        self._init_cropbox()
        self._display_frame(frame)

    def _init_cropbox(self):
        """初始化裁剪框（在旋转后坐标系中，视频坐标空间）"""
        rotated_w, rotated_h = self._get_rotated_video_size()
        target_ratio = self.target_aspect_ratio

        # 在视频坐标空间中找到最大的、符合目标宽高比的裁剪区域
        if rotated_w / rotated_h > target_ratio:
            # 视频更宽 → 高度填满，宽度按比例裁剪
            crop_h = rotated_h
            crop_w = int(crop_h * target_ratio)
        else:
            # 视频更高 → 宽度填满，高度按比例裁剪
            crop_w = rotated_w
            crop_h = int(crop_w / target_ratio)

        # 居中放置裁剪框
        x = (rotated_w - crop_w) // 2
        y = (rotated_h - crop_h) // 2

        self.cropbox = [x, y, crop_w, crop_h]
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
        rotation_str = (
            f" | 旋转: {self._rotation}°" if self._rotation != 0 else "")
        self.info_label.setText(
            f"帧: {self.current_frame_index}/{self.total_frames} | "
            f"裁剪: ({x}, {y}, {w}, {h}){rotation_str}"
        )

    def _display_frame(self, frame):
        """显示帧（仅用于 cropbox 交互/静态图片的即时重绘，不涉及视频 I/O）"""
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
            cv2.rectangle(
                display_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

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
            rotated_width, _ = self._get_rotated_video_size()
            self.display_scale = (
                pixmap.width() / rotated_width if rotated_width > 0 else 1.0)
            self.display_offset_x = (label_size.width() - pixmap.width()) // 2
            self.display_offset_y = (
                label_size.height() - pixmap.height()) // 2

        self.video_label.setPixmap(pixmap)

    def _render_preview_frame(self, frame) -> np.ndarray:
        """渲染预览帧（裁剪+叠加UI）"""
        x, y, w, h = self.cropbox

        # 裁剪
        cropped = frame[y:y+h, x:x+w].copy()

        # 缩放到目标分辨率
        preview_frame = cv2.resize(
            cropped, (self.target_width, self.target_height))

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
        """定时器回调 — 不再直接读帧，改为发送命令到工作线程"""
        if self._loop_frame is not None:
            # 图片循环模式：帧索引递增但画面不变（无 I/O，保持主线程）
            self.current_frame_index += 1
            if self.current_frame_index >= self.total_frames:
                self.current_frame_index = 0
            self.frame_changed.emit(self.current_frame_index)
            return
        if self._reader_thread is None:
            return
        self._reader_thread.request_read_next()

    def play(self):
        """播放"""
        if self.is_playing:
            return
        if not self._has_video and self._loop_frame is None:
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
        if self._loop_frame is not None:
            self.pause()
            self.current_frame_index = min(
                self.current_frame_index + 1, self.total_frames - 1)
            self.frame_changed.emit(self.current_frame_index)
            return
        if not self._has_video or self._reader_thread is None:
            return
        self.pause()
        target = min(self.current_frame_index + 1, self.total_frames - 1)
        self._reader_thread.request_seek(target)

    def prev_frame(self):
        """上一帧"""
        if self._loop_frame is not None:
            self.pause()
            self.current_frame_index = max(self.current_frame_index - 1, 0)
            self.frame_changed.emit(self.current_frame_index)
            return
        if not self._has_video or self._reader_thread is None:
            return
        self.pause()
        target = max(self.current_frame_index - 1, 0)
        self._reader_thread.request_seek(target)

    def seek_to_frame(self, index: int):
        """跳转到指定帧"""
        if self._loop_frame is not None:
            index = max(0, min(index, self.total_frames - 1))
            self.current_frame_index = index
            self.frame_changed.emit(self.current_frame_index)
            return
        if not self._has_video or self._reader_thread is None:
            return
        index = max(0, min(index, self.total_frames - 1))
        self._reader_thread.request_seek(index)

    def get_current_frame(self) -> int:
        """获取当前帧号"""
        return self.current_frame_index

    def get_cropbox(self) -> Tuple[int, int, int, int]:
        """获取裁剪框（旋转后坐标系）"""
        return tuple(self.cropbox)

    def _cropbox_to_original_coords(
        self, x: int, y: int, w: int, h: int
    ) -> Tuple[int, int, int, int]:
        """将 cropbox 从旋转后坐标系逆变换到原始视频坐标系（用于导出）"""
        if self._rotation == 0:
            return (x, y, w, h)
        elif self._rotation == 90:
            # 旋转后坐标 -> 原始坐标
            return (y, self.video_height - x - w, h, w)
        elif self._rotation == 180:
            return (
                self.video_width - x - w, self.video_height - y - h, w, h)
        elif self._rotation == 270:
            return (self.video_width - y - h, x, h, w)
        # 任意角度：逆仿射变换 + 轴对齐包围盒近似
        ow, oh = self.video_width, self.video_height
        M = cv2.getRotationMatrix2D(
            (ow / 2.0, oh / 2.0), -self._rotation, 1.0)
        cos_a, sin_a = abs(M[0, 0]), abs(M[0, 1])
        nw = int(ow * cos_a + oh * sin_a)
        nh = int(ow * sin_a + oh * cos_a)
        M[0, 2] += (nw - ow) / 2.0
        M[1, 2] += (nh - oh) / 2.0
        M_inv = cv2.invertAffineTransform(M)
        corners = np.array(
            [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
            dtype=np.float64)
        orig = np.array(
            [M_inv[:, :2] @ c + M_inv[:, 2] for c in corners])
        x0 = max(0, int(np.floor(orig[:, 0].min())))
        y0 = max(0, int(np.floor(orig[:, 1].min())))
        x1 = min(ow, int(np.ceil(orig[:, 0].max())))
        y1 = min(oh, int(np.ceil(orig[:, 1].max())))
        return (x0, y0, x1 - x0, y1 - y0)

    def get_cropbox_for_export(self) -> Tuple[int, int, int, int]:
        """获取导出用的 cropbox（原始坐标系）"""
        x, y, w, h = self.cropbox
        return self._cropbox_to_original_coords(x, y, w, h)

    def set_cropbox(self, x: int, y: int, w: int, h: int):
        """设置裁剪框"""
        self.cropbox = [x, y, w, h]
        self._bound_cropbox()
        self._emit_cropbox_changed()
        # 同步到工作线程
        if self._reader_thread is not None:
            self._reader_thread.request_set_cropbox(self.cropbox)
        if self.current_frame is not None:
            self._display_frame(self.current_frame)

    def get_video_info(self) -> Tuple[float, int, int, int]:
        """获取视频信息 (fps, total_frames, width, height)"""
        return (
            self.video_fps, self.total_frames,
            self.video_width, self.video_height)

    def set_preview_mode(self, enabled: bool):
        """设置预览模式"""
        self._preview_mode = enabled
        if self._reader_thread is not None:
            self._reader_thread.request_set_preview_params(
                enabled, self.target_width, self.target_height,
                self._epconfig, self._overlay_renderer)
        if self.current_frame is not None:
            self._display_frame(self.current_frame)

    def is_preview_mode(self) -> bool:
        """获取预览模式状态"""
        return self._preview_mode

    def set_rotation(self, degrees: int):
        """设置视频旋转角度（0-359 任意角度）"""
        degrees = degrees % 360
        if self._rotation != degrees:
            old_orthogonal = self._rotation in (0, 90, 180, 270)
            new_orthogonal = degrees in (0, 90, 180, 270)
            self._rotation = degrees
            self.rotation_changed.emit(degrees)
            # 同步到工作线程
            if self._reader_thread is not None:
                self._reader_thread.request_set_rotation(degrees)
            if self.video_width > 0 and self.video_height > 0:
                if old_orthogonal and new_orthogonal:
                    self._bound_cropbox()  # 正交角度间切换：只验证边界
                else:
                    self._init_cropbox()  # 涉及非正交角度：重新初始化
                # 同步 cropbox 到工作线程
                if self._reader_thread is not None:
                    self._reader_thread.request_set_cropbox(self.cropbox)
            if self.current_frame is not None:
                self._display_frame(self.current_frame)

    def get_rotation(self) -> int:
        """获取视频旋转角度"""
        return self._rotation

    def rotate_clockwise(self):
        """顺时针旋转1度"""
        self.set_rotation((self._rotation + 1) % 360)

    def rotate_counterclockwise(self):
        """逆时针旋转1度"""
        self.set_rotation((self._rotation - 1) % 360)

    def _apply_rotation(self, frame: np.ndarray) -> np.ndarray:
        """应用旋转到帧（支持任意角度）"""
        if self._rotation == 0:
            return frame
        # 正交角度快速路径（cv2.rotate 比 warpAffine 快约 10 倍）
        if self._rotation == 90:
            return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif self._rotation == 180:
            return cv2.rotate(frame, cv2.ROTATE_180)
        elif self._rotation == 270:
            return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        # 任意角度：getRotationMatrix2D + warpAffine
        h, w = frame.shape[:2]
        M = cv2.getRotationMatrix2D(
            (w / 2.0, h / 2.0), -self._rotation, 1.0)
        cos_a, sin_a = abs(M[0, 0]), abs(M[0, 1])
        new_w = int(w * cos_a + h * sin_a)
        new_h = int(w * sin_a + h * cos_a)
        M[0, 2] += (new_w - w) / 2.0
        M[1, 2] += (new_h - h) / 2.0
        return cv2.warpAffine(frame, M, (new_w, new_h),
                              borderMode=cv2.BORDER_CONSTANT,
                              borderValue=(0, 0, 0))

    def _get_rotated_video_size(self) -> Tuple[int, int]:
        """获取旋转后的视频尺寸（包围盒）"""
        if self._rotation == 0 or self._rotation == 180:
            return (self.video_width, self.video_height)
        if self._rotation in (90, 270):
            return (self.video_height, self.video_width)
        # 任意角度：计算包围盒
        import math
        rad = math.radians(self._rotation)
        cos_a, sin_a = abs(math.cos(rad)), abs(math.sin(rad))
        return (int(self.video_width * cos_a + self.video_height * sin_a),
                int(self.video_width * sin_a + self.video_height * cos_a))

    @staticmethod
    def apply_rotation_to_frame(
        frame: np.ndarray, rotation: int
    ) -> np.ndarray:
        """对帧应用指定角度旋转（外部可调用）"""
        if rotation == 0:
            return frame
        if rotation == 90:
            return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif rotation == 180:
            return cv2.rotate(frame, cv2.ROTATE_180)
        elif rotation == 270:
            return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        h, w = frame.shape[:2]
        M = cv2.getRotationMatrix2D(
            (w / 2.0, h / 2.0), -rotation, 1.0)
        cos_a, sin_a = abs(M[0, 0]), abs(M[0, 1])
        nw, nh = (int(w * cos_a + h * sin_a),
                  int(w * sin_a + h * cos_a))
        M[0, 2] += (nw - w) / 2.0
        M[1, 2] += (nh - h) / 2.0
        return cv2.warpAffine(frame, M, (nw, nh),
                              borderMode=cv2.BORDER_CONSTANT,
                              borderValue=(0, 0, 0))

    def set_epconfig(self, config: "EPConfig"):
        """设置配置（用于叠加UI渲染）"""
        self._epconfig = config
        # 初始化叠加渲染器
        if self._overlay_renderer is None:
            from core.overlay_renderer import OverlayRenderer
            self._overlay_renderer = OverlayRenderer()
        # 同步到工作线程
        if self._reader_thread is not None:
            self._reader_thread.request_set_preview_params(
                self._preview_mode, self.target_width, self.target_height,
                self._epconfig, self._overlay_renderer)
        if self.current_frame is not None:
            self._display_frame(self.current_frame)

    def _display_to_rotated_coords(self, pos: QPoint) -> Tuple[int, int]:
        """将显示坐标转换为旋转后视频坐标"""
        label_pos = self.video_label.mapFrom(self, pos)
        rx = (int((label_pos.x() - self.display_offset_x) / self.display_scale)
              if self.display_scale > 0 else 0)
        ry = (int((label_pos.y() - self.display_offset_y) / self.display_scale)
              if self.display_scale > 0 else 0)
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
        if (event.button() == Qt.MouseButton.LeftButton
                and self.current_frame is not None):
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
                self.cropbox = [
                    sx, sy, new_w, int(new_w / self.target_aspect_ratio)]
            elif self.drag_mode == self.DRAG_RESIZE_TL:
                new_w = sw - dx
                new_h = int(new_w / self.target_aspect_ratio)
                self.cropbox = [
                    sx + (sw - new_w), sy + (sh - new_h), new_w, new_h]
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
            # 同步 cropbox 到工作线程
            if self._reader_thread is not None:
                self._reader_thread.request_set_cropbox(self.cropbox)
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
        modifiers = event.modifiers()
        step = 10

        # 仅在无修饰键时处理，避免拦截 Ctrl+S 等全局快捷键
        has_modifier = modifiers != Qt.KeyboardModifier.NoModifier

        # 播放/帧跳转操作需要视频
        if (key == Qt.Key.Key_Space and self._has_video
                and not has_modifier):
            self.toggle_play()
        elif (key == Qt.Key.Key_Left and self._has_video
              and not has_modifier):
            self.prev_frame()
        elif (key == Qt.Key.Key_Right and self._has_video
              and not has_modifier):
            self.next_frame()
        # WASD 裁剪框移动（视频和静态图片都支持，仅无修饰键时）
        elif key == Qt.Key.Key_W and not has_modifier:
            self.cropbox[1] -= step
        elif key == Qt.Key.Key_S and not has_modifier:
            self.cropbox[1] += step
        elif key == Qt.Key.Key_A and not has_modifier:
            self.cropbox[0] -= step
        elif key == Qt.Key.Key_D and not has_modifier:
            self.cropbox[0] += step
        else:
            super().keyPressEvent(event)
            return

        self._bound_cropbox()
        self._emit_cropbox_changed()
        # 同步 cropbox 到工作线程
        if self._reader_thread is not None:
            self._reader_thread.request_set_cropbox(self.cropbox)
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
        self._stop_reader_thread()
        super().closeEvent(event)

    def clear(self):
        """清空预览状态"""
        self.pause()
        self._stop_reader_thread()
        self._loop_frame = None
        self.video_path = ""
        self.total_frames = 0
        self.current_frame_index = 0
        self.current_frame = None
        self.video_label.clear()
        self.video_label.setText("未加载视频")
        self.info_label.setText("帧: 0/0 | 裁剪: (0, 0, 0, 0)")
