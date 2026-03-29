"""
视频预览组件 - 支持视频播放和裁剪框交互
"""
import logging
from typing import Optional, Tuple, TYPE_CHECKING

import numpy as np

try:
    import av
    HAS_AV = True
except ImportError:
    HAS_AV = False

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

from PyQt6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QSizePolicy, QStackedWidget
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint
from PyQt6.QtGui import QImage, QPixmap, QMouseEvent, QKeyEvent
from qfluentwidgets import CaptionLabel, setCustomStyleSheet

if TYPE_CHECKING:
    from config.epconfig import EPConfig

logger = logging.getLogger(__name__)

DEFAULT_TARGET_WIDTH = 360
DEFAULT_TARGET_HEIGHT = 640


class VideoPreviewWidget(QWidget):
    """视频预览组件，支持裁剪框交互"""

    cropbox_changed = pyqtSignal(int, int, int, int)  # x, y, w, h
    frame_changed = pyqtSignal(int)  # 当前帧号
    playback_state_changed = pyqtSignal(bool)  # 播放状态
    video_loaded = pyqtSignal(int, float)  # 总帧数, fps
    rotation_changed = pyqtSignal(int)  # 旋转角度 (0-359)

    DRAG_NONE = 0
    DRAG_MOVE = 1
    DRAG_RESIZE_TL = 2  # 左上
    DRAG_RESIZE_TR = 3  # 右上
    DRAG_RESIZE_BL = 4  # 左下
    DRAG_RESIZE_BR = 5  # 右下

    def __init__(self, parent=None):
        super().__init__(parent)

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
        # 加载代数守卫：每次 clear()/load_video() 递增，回调检查是否匹配
        self._load_generation: int = 0
        self._active_gen: int = 0

        self.is_playing: bool = False
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._on_timer_tick)

        self.target_width = DEFAULT_TARGET_WIDTH
        self.target_height = DEFAULT_TARGET_HEIGHT
        self.target_aspect_ratio = self.target_width / self.target_height
        self.cropbox = [0, 0, self.target_width, self.target_height]

        self.display_scale: float = 1.0
        self.display_offset_x: int = 0
        self.display_offset_y: int = 0

        self.drag_mode: int = self.DRAG_NONE
        self.drag_start_pos: Optional[QPoint] = None
        self.drag_start_cropbox: list = []
        self.handle_size: int = 15

        self._preview_mode: bool = False
        self._epconfig: Optional["EPConfig"] = None
        self._overlay_renderer = None

        # 视频旋转 (0-359 任意整数角度)
        self._rotation: int = 0

        # 图片循环模式（load_image_as_loop 设置）
        self._loop_frame: Optional[np.ndarray] = None

        # GL 渲染模式（_setup_ui 中初始化）
        self._use_gl: bool = False
        self._gl_renderer = None

        # 预读帧缓冲区统计（自适应预读深度）
        self._underrun_count: int = 0
        self._tick_count: int = 0
        self._last_adaptive_check: int = 0
        self._adaptive_interval: int = 15  # 每 15 帧检查一次 (0.5秒@30fps)

        self._setup_ui()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        self._display_stack = QStackedWidget()
        self._display_stack.setMinimumSize(320, 180)
        self._display_stack.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._display_stack.setMouseTracking(True)

        # 页面 0: QLabel — 状态文本 / 软件渲染回退
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
        self._display_stack.addWidget(self.video_label)

        # 页面 1: GLVideoWidget — GPU 加速渲染
        try:
            from gui.widgets.gl_video_renderer import (
                GLVideoWidget, _check_opengl_available
            )
            if _check_opengl_available():
                self._gl_renderer = GLVideoWidget(self)
                self._gl_renderer.setMouseTracking(True)
                self._gl_renderer.setToolTip(
                    "视频预览区域\nWASD移动裁剪框，空格播放/暂停")
                self._display_stack.addWidget(self._gl_renderer)
                self._use_gl = True
                logger.info("GLVideoWidget 已创建，等待 OpenGL 初始化")
        except Exception as e:
            logger.warning(f"GLVideoWidget 创建失败，使用 QLabel 回退: {e}")

        layout.addWidget(self._display_stack)

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
            # 先断开所有信号连接，防止已排队的旧信号触发回调
            try:
                self._reader_thread.video_opened.disconnect(self._on_video_opened)
            except (TypeError, RuntimeError):
                pass
            try:
                self._reader_thread.video_open_failed.disconnect(self._on_video_open_failed)
            except (TypeError, RuntimeError):
                pass
            try:
                self._reader_thread.frame_ready.disconnect(self._on_frame_ready)
            except (TypeError, RuntimeError):
                pass
            try:
                self._reader_thread.yuv_frame_ready.disconnect(self._on_yuv_frame_ready)
            except (TypeError, RuntimeError):
                pass

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
        if self._active_gen != self._load_generation:
            return
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
        self._sync_state_to_reader()
        self.video_loaded.emit(total_frames, fps)

        if self._use_gl and self._gl_renderer:
            self._display_stack.setCurrentIndex(1)

    def _on_video_open_failed(self, error_msg: str):
        """视频打开失败的回调"""
        if self._active_gen != self._load_generation:
            return
        logger.error(f"视频加载失败: {error_msg}")
        self._display_stack.setCurrentIndex(0)
        self.video_label.setText(f"加载失败: {error_msg}")
        self._has_video = False

    def _on_yuv_frame_ready(self, frame_index: int, y_data: bytes,
                            u_data: bytes, v_data: bytes,
                            width: int, height: int):
        """YUV 帧就绪回调 — GL 编辑模式：直传 GPU，零 CPU 处理

        仅在 GL 编辑模式下调用（工作线程 _gl_mode=True 且非预览模式）。
        """
        if self._active_gen != self._load_generation:
            return
        if not (self._use_gl and self._gl_renderer
                and not self._gl_renderer.gl_failed):
            return  # GL 不可用，由 frame_ready 处理

        self._gl_renderer.upload_yuv_frame(
            y_data, u_data, v_data, width, height)
        self._gl_renderer.set_rotation(self._rotation)
        rotated_w, rotated_h = self._get_rotated_video_size()
        self._gl_renderer.set_cropbox(
            *self.cropbox, rotated_w, rotated_h)
        self._gl_renderer.set_show_cropbox(not self._preview_mode)

    def _on_frame_ready(self, frame_index: int, qimage: QImage,
                        raw_frame: object):
        """后台线程帧就绪回调（主线程执行 — Qt QueuedConnection 保证）

        GL 编辑模式：仅存储 raw_frame（显示由 _on_yuv_frame_ready 处理）
        GL 预览模式：CPU 处理后上传 BGR 到 GPU
        QLabel 模式：QImage → QPixmap.scaled() → setPixmap()
        """
        if self._active_gen != self._load_generation:
            return
        self.current_frame_index = frame_index
        self.current_frame = raw_frame  # 保存原始帧，供 cropbox 交互即时重绘

        if self._use_gl and self._gl_renderer:
            if self._gl_renderer.gl_failed:
                # GL 初始化失败，永久回退到 QLabel
                self._use_gl = False
                self._display_stack.setCurrentIndex(0)
                logger.warning("OpenGL 初始化失败，回退到 QLabel 软件渲染")
            elif not self._preview_mode:
                # GL 编辑模式：YUV 帧由 _on_yuv_frame_ready 处理显示
                self.frame_changed.emit(frame_index)
                self._update_info_label()
                return
            else:
                # GL 预览模式：CPU 处理后上传
                self._display_frame(raw_frame)
                self.frame_changed.emit(frame_index)
                self._update_info_label()
                return

        # QLabel 模式：QImage → QPixmap（必须在主线程）
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
        if self.target_width == width and self.target_height == height:
            return
        self.target_width = width
        self.target_height = height
        self.target_aspect_ratio = width / height
        if self.current_frame is not None:
            self._init_cropbox()
            self._sync_state_to_reader()
            self._refresh_display()

    def load_video(self, path: str) -> bool:
        """加载视频（异步，不阻塞 UI）

        返回 True 表示加载请求已提交（路径有效），
        实际加载结果通过 video_loaded 信号通知。
        """
        logger.info(f"尝试加载视频: {path}")

        if not HAS_AV:
            logger.error("PyAV (FFmpeg) 未安装")
            self.video_label.setText("未安装 PyAV (FFmpeg)")
            return False

        import os
        if not os.path.exists(path):
            logger.error(f"视频文件不存在: {path}")
            self.video_label.setText(f"文件不存在: {path}")
            return False

        self._load_generation += 1
        self._stop_reader_thread()
        self.pause()
        self._loop_frame = None

        self.video_path = path
        self._display_stack.setCurrentIndex(0)
        self.video_label.setText("正在加载视频...")

        from gui.widgets.frame_reader_thread import FrameReaderThread
        self._reader_thread = FrameReaderThread(self)
        self._reader_thread.video_opened.connect(self._on_video_opened)
        self._reader_thread.video_open_failed.connect(self._on_video_open_failed)
        self._reader_thread.frame_ready.connect(self._on_frame_ready)
        self._reader_thread.yuv_frame_ready.connect(self._on_yuv_frame_ready)
        self._active_gen = self._load_generation
        self._reader_thread.start()

        self._sync_state_to_reader()
        if self._use_gl and self._gl_renderer:
            self._reader_thread.request_set_gl_mode(True)
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
        self.pause()
        self._stop_reader_thread()
        self._loop_frame = None

        self.video_width = frame.shape[1]
        self.video_height = frame.shape[0]
        self.current_frame = frame
        self.total_frames = 1
        self.current_frame_index = 0

        self._init_cropbox()
        if self._use_gl and self._gl_renderer:
            self._display_stack.setCurrentIndex(1)
        self._display_frame(frame)

    def _init_cropbox(self):
        """初始化裁剪框（在旋转后坐标系中，视频坐标空间）

        之前的实现：裁剪框初始化为最大可能尺寸（填满视频的某个维度），
        导致在该维度上没有移动空间（例如 16:9→9:16 时垂直方向无法移动）。

        修复：初始化为最大尺寸的 75%，居中放置，四周留出移动空间。
        用户可以拖动角落放大到最大尺寸，也可以缩小。
        """
        rotated_w, rotated_h = self._get_rotated_video_size()
        target_ratio = self.target_aspect_ratio

        if rotated_w / rotated_h > target_ratio:
            max_h = rotated_h
            max_w = int(max_h * target_ratio)
        else:
            max_w = rotated_w
            max_h = int(max_w / target_ratio)

        # 初始化为最大尺寸的 75%，留出移动空间
        crop_w = int(max_w * 0.75)
        crop_h = int(crop_w / target_ratio)

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

        w = max(w, 90)
        h = max(h, int(90 / self.target_aspect_ratio))

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

    def _refresh_display(self):
        """刷新显示（cropbox/旋转/预览模式变化时调用，不重新上传帧纹理）

        GL 编辑模式：仅更新 GPU 渲染参数（旋转、cropbox），帧纹理不变
        GL 预览模式/QLabel：需要 CPU 重新处理，回退 _display_frame
        """
        if (self._use_gl and self._gl_renderer
                and not self._gl_renderer.gl_failed
                and not self._preview_mode):
            # GL 编辑模式：帧纹理已在 GPU，只需更新渲染参数
            rotated_w, rotated_h = self._get_rotated_video_size()
            self._gl_renderer.set_rotation(self._rotation)
            self._gl_renderer.set_cropbox(
                *self.cropbox, rotated_w, rotated_h)
            self._gl_renderer.set_show_cropbox(True)
            self._gl_renderer.update()
            return

        if self.current_frame is not None:
            self._display_frame(self.current_frame)

    def _display_frame(self, frame):
        """显示帧（静态图片/预览模式/QLabel 回退）

        GL 编辑模式：上传原始 BGR 到 GPU，GPU 负责旋转+cropbox
        GL 预览模式：CPU 裁剪+overlay → 上传合成帧到 GPU
        QLabel 模式：CPU 全部处理 → QImage → QPixmap → setPixmap
        """
        if frame is None or not HAS_CV2:
            return

        if self._use_gl and self._gl_renderer and not self._gl_renderer.gl_failed:
            if self._preview_mode:
                # GL 预览模式：CPU 旋转+裁剪+overlay → 上传合成帧
                rotated_frame = self._apply_rotation(frame)
                display_frame = self._render_preview_frame(rotated_frame)
                self._gl_renderer.upload_bgr_frame(display_frame)
                self._gl_renderer.set_rotation(0)  # 已在 CPU 处理旋转
                self._gl_renderer.set_show_cropbox(False)
            else:
                # GL 编辑模式：上传原始帧，GPU 处理旋转+cropbox
                self._gl_renderer.upload_bgr_frame(frame)
                rotated_w, rotated_h = self._get_rotated_video_size()
                self._gl_renderer.set_rotation(self._rotation)
                self._gl_renderer.set_cropbox(
                    *self.cropbox, rotated_w, rotated_h)
                self._gl_renderer.set_show_cropbox(True)
            self._gl_renderer.update()
            return

        # QLabel 模式：CPU 全部处理
        rotated_frame = self._apply_rotation(frame)
        x, y, w, h = self.cropbox

        if self._preview_mode:
            display_frame = self._render_preview_frame(rotated_frame)
        else:
            display_frame = rotated_frame.copy()

            cv2.rectangle(
                display_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

            hs = 8
            handle_color = (0, 200, 255)
            for px, py in [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]:
                cv2.rectangle(
                    display_frame,
                    (px - hs, py - hs), (px + hs, py + hs),
                    handle_color, -1
                )

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

        if not self._preview_mode:
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

        cropped = frame[y:y+h, x:x+w].copy()

        preview_frame = cv2.resize(
            cropped, (self.target_width, self.target_height))

        if self._epconfig and self._overlay_renderer:
            from config.epconfig import OverlayType
            if self._epconfig.overlay.type == OverlayType.ARKNIGHTS:
                preview_frame = self._overlay_renderer.render_arknights_overlay(
                    preview_frame,
                    self._epconfig.overlay.arknights_options
                )

        return preview_frame

    def _on_timer_tick(self):
        """定时器回调 — 从预读帧缓冲区消费帧

        预读模式：工作线程主动提前解码填充缓冲区，timer tick 直接取帧。
        缓冲区空时跳帧（不阻塞 UI），并统计欠载次数用于自适应预读深度。
        """
        if self._loop_frame is not None:
            # 图片循环模式：帧索引递增但画面不变（无 I/O，保持主线程）
            self.current_frame_index += 1
            if self.current_frame_index >= self.total_frames:
                self.current_frame_index = 0
            self.frame_changed.emit(self.current_frame_index)
            return
        if self._reader_thread is None:
            return

        # 循环排空所有过期帧，取第一个版本匹配的帧
        current_version = self._reader_thread.params_version
        frame = None
        while True:
            candidate = self._reader_thread.frame_buffer.get()
            if candidate is None:
                break
            if candidate.params_version == current_version:
                frame = candidate
                break
            # 过期帧，继续取下一帧

        if frame is None:
            self._underrun_count += 1
            return

        self._consume_buffered_frame(frame)
        self._adaptive_prefetch()

    def _consume_buffered_frame(self, frame):
        """消费一个缓冲帧，更新显示"""
        from gui.widgets.frame_reader_thread import BufferedFrame

        self.current_frame_index = frame.frame_index
        self.current_frame = frame.raw_frame

        if self._use_gl and self._gl_renderer:
            if self._gl_renderer.gl_failed:
                self._use_gl = False
                self._display_stack.setCurrentIndex(0)
                logger.warning("OpenGL 初始化失败，回退到 QLabel 软件渲染")
            elif frame.yuv_data is not None and not self._preview_mode:
                y, u, v, w, h = frame.yuv_data
                self._gl_renderer.upload_yuv_frame(y, u, v, w, h)
                self._gl_renderer.set_rotation(self._rotation)
                rotated_w, rotated_h = self._get_rotated_video_size()
                self._gl_renderer.set_cropbox(
                    *self.cropbox, rotated_w, rotated_h)
                self._gl_renderer.set_show_cropbox(True)
                self.frame_changed.emit(frame.frame_index)
                self._update_info_label()
                return
            else:
                if frame.raw_frame is not None:
                    self._display_frame(frame.raw_frame)
                self.frame_changed.emit(frame.frame_index)
                self._update_info_label()
                return

        if frame.qimage is not None and not frame.qimage.isNull():
            label_size = self.video_label.size()
            pixmap = QPixmap.fromImage(frame.qimage).scaled(
                label_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            if not self._preview_mode:
                rotated_width, _ = self._get_rotated_video_size()
                self.display_scale = (
                    pixmap.width() / rotated_width
                    if rotated_width > 0 else 1.0)
                self.display_offset_x = (
                    label_size.width() - pixmap.width()) // 2
                self.display_offset_y = (
                    label_size.height() - pixmap.height()) // 2
            self.video_label.setPixmap(pixmap)

        self.frame_changed.emit(frame.frame_index)
        self._update_info_label()

    def _adaptive_prefetch(self):
        """根据缓冲区欠载率动态调整预读深度（3~16 帧）

        倍增策略：欠载率 >10% 时缓冲区翻倍（应对 I-frame 集群），
        欠载率 <3% 时逐步缩减。
        """
        self._tick_count += 1
        if (self._tick_count - self._last_adaptive_check
                < self._adaptive_interval):
            return

        underrun_rate = (
            self._underrun_count / max(self._adaptive_interval, 1))

        if self._reader_thread is None:
            return
        buffer = self._reader_thread.frame_buffer
        current_max = buffer.max_size

        if underrun_rate > 0.10:
            new_max = min(current_max * 2, 16)
            if new_max != current_max:
                buffer.max_size = new_max
                logger.debug(
                    f"预读深度增加到 {buffer.max_size} "
                    f"(欠载率 {underrun_rate:.1%})")
        elif underrun_rate < 0.03 and current_max > 3:
            buffer.max_size = max(current_max - 1, 3)
            logger.debug(
                f"预读深度减少到 {buffer.max_size} "
                f"(欠载率 {underrun_rate:.1%})")

        self._underrun_count = 0
        self._last_adaptive_check = self._tick_count

    def play(self):
        """播放"""
        if self.is_playing:
            return
        if not self._has_video and self._loop_frame is None:
            return

        self._underrun_count = 0
        self._tick_count = 0

        if self._reader_thread is not None:
            self._reader_thread.start_prefetch()

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

        # 停止预读（节省 CPU）
        if self._reader_thread is not None:
            self._reader_thread.stop_prefetch()

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
            self.pause()
            index = max(0, min(index, self.total_frames - 1))
            self.current_frame_index = index
            self.frame_changed.emit(self.current_frame_index)
            return
        if not self._has_video or self._reader_thread is None:
            return
        self.pause()
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

    def _original_to_rotated_coords(
        self, x: int, y: int, w: int, h: int
    ) -> Tuple[int, int, int, int]:
        """将 cropbox 从原始视频坐标系正变换到当前旋转后坐标系"""
        if self._rotation == 0:
            return (x, y, w, h)
        elif self._rotation == 90:
            return (self.video_height - y - h, x, h, w)
        elif self._rotation == 180:
            return (self.video_width - x - w, self.video_height - y - h, w, h)
        elif self._rotation == 270:
            return (y, self.video_width - x - w, h, w)
        # 任意角度：仿射正变换
        ow, oh = self.video_width, self.video_height
        M = cv2.getRotationMatrix2D(
            (ow / 2.0, oh / 2.0), -self._rotation, 1.0)
        cos_a, sin_a = abs(M[0, 0]), abs(M[0, 1])
        nw = int(ow * cos_a + oh * sin_a)
        nh = int(ow * sin_a + oh * cos_a)
        M[0, 2] += (nw - ow) / 2.0
        M[1, 2] += (nh - oh) / 2.0
        corners = np.array(
            [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
            dtype=np.float64)
        rotated = np.array(
            [M[:, :2] @ c + M[:, 2] for c in corners])
        rx0 = max(0, int(np.floor(rotated[:, 0].min())))
        ry0 = max(0, int(np.floor(rotated[:, 1].min())))
        rx1 = min(nw, int(np.ceil(rotated[:, 0].max())))
        ry1 = min(nh, int(np.ceil(rotated[:, 1].max())))
        return (rx0, ry0, rx1 - rx0, ry1 - ry0)

    def get_cropbox_for_export(self) -> Tuple[int, int, int, int]:
        """获取导出用的 cropbox（原始坐标系，供模拟器使用）"""
        x, y, w, h = self.cropbox
        return self._cropbox_to_original_coords(x, y, w, h)

    def get_cropbox_in_rotated_space(self) -> Tuple[int, int, int, int]:
        """获取旋转空间中的 cropbox（用于视频导出，无坐标转换）"""
        return tuple(self.cropbox)

    def set_cropbox(self, x: int, y: int, w: int, h: int):
        """设置裁剪框"""
        self.cropbox = [x, y, w, h]
        self._bound_cropbox()
        self._emit_cropbox_changed()
        if self._reader_thread is not None:
            self._reader_thread.request_set_cropbox(self.cropbox)
        self._refresh_display()

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
        self._refresh_display()

    def is_preview_mode(self) -> bool:
        """获取预览模式状态"""
        return self._preview_mode

    def set_use_gl(self, enabled: bool):
        """切换 GL/QLabel 渲染模式（硬件加速开关）"""
        if enabled == self._use_gl:
            return

        if enabled and self._gl_renderer is None:
            logger.warning("GLVideoWidget 不可用，无法启用硬件加速")
            return

        if enabled and self._gl_renderer and self._gl_renderer.gl_failed:
            logger.warning("OpenGL 初始化失败，无法启用硬件加速")
            return

        self._use_gl = enabled
        logger.info(f"渲染模式切换: {'GL 硬件加速' if enabled else 'QLabel 软件渲染'}")

        if self.current_frame is not None:
            if enabled:
                self._display_stack.setCurrentIndex(1)
            else:
                self._display_stack.setCurrentIndex(0)
            self._display_frame(self.current_frame)
        else:
            self._display_stack.setCurrentIndex(0)

    def set_rotation(self, degrees: int):
        """设置视频旋转角度（0-359 任意角度）"""
        degrees = degrees % 360
        if self._rotation != degrees:
            old_orthogonal = self._rotation in (0, 90, 180, 270)
            new_orthogonal = degrees in (0, 90, 180, 270)

            if (old_orthogonal and new_orthogonal
                    and self.video_width > 0 and self.video_height > 0):
                # 正交角度间切换：中心点跟踪 + 尺寸保持
                # 保存旋转前的 cropbox 尺寸（已满足 target_aspect_ratio）
                old_crop_w, old_crop_h = self.cropbox[2], self.cropbox[3]
                # Step 1: 旧旋转空间 → 原始坐标（self._rotation 仍为旧值）
                ox, oy, ow, oh = self._cropbox_to_original_coords(
                    *self.cropbox)
                # Step 2: 更新旋转角度
                self._rotation = degrees
                # Step 3: 原始坐标 → 新旋转空间（用于计算变换后的中心点）
                nx, ny, nw, nh = self._original_to_rotated_coords(
                    ox, oy, ow, oh)
                # Step 4: 以变换后的中心点定位，保持原始尺寸（维持宽高比）
                new_cx = nx + nw / 2.0
                new_cy = ny + nh / 2.0
                self.cropbox = [
                    int(new_cx - old_crop_w / 2.0),
                    int(new_cy - old_crop_h / 2.0),
                    old_crop_w,
                    old_crop_h,
                ]
                self._bound_cropbox()
            else:
                self._rotation = degrees
                if self.video_width > 0 and self.video_height > 0:
                    self._init_cropbox()

            self.rotation_changed.emit(degrees)
            if self._reader_thread is not None:
                self._reader_thread.request_set_rotation(degrees)
            if self.video_width > 0 and self.video_height > 0:
                if self._reader_thread is not None:
                    self._reader_thread.request_set_cropbox(self.cropbox)
            if self.current_frame is not None:
                self._refresh_display()

    def get_rotation(self) -> int:
        """获取视频旋转角度"""
        return self._rotation


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
        if self._overlay_renderer is None:
            from core.overlay_renderer import OverlayRenderer
            self._overlay_renderer = OverlayRenderer()
        if self._reader_thread is not None:
            self._reader_thread.request_set_preview_params(
                self._preview_mode, self.target_width, self.target_height,
                self._epconfig, self._overlay_renderer)
        if self.current_frame is not None:
            self._refresh_display()

    def _display_to_rotated_coords(self, pos: QPoint) -> Tuple[int, int]:
        """将显示坐标转换为旋转后视频坐标"""
        if self._use_gl and self._gl_renderer and not self._gl_renderer.gl_failed:
            gl_pos = self._gl_renderer.mapFrom(self, pos)
            dx, dy, dw, dh = self._gl_renderer._display_rect
            if dw <= 0 or dh <= 0:
                return (0, 0)
            rotated_w, rotated_h = self._get_rotated_video_size()
            vx = int((gl_pos.x() - dx) / dw * rotated_w)
            vy = int((gl_pos.y() - dy) / dh * rotated_h)
            return (max(0, vx), max(0, vy))

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

            # GL 编辑模式下 cropbox 由 GPU 绘制，无需同步到后台线程
            if self._reader_thread is not None and (
                    not self._use_gl or self._preview_mode
                    or (self._gl_renderer and self._gl_renderer.gl_failed)):
                self._reader_thread.request_set_cropbox(self.cropbox)
            if self.current_frame is not None:
                self._refresh_display()

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
        if self._reader_thread is not None:
            self._reader_thread.request_set_cropbox(self.cropbox)
        if self.current_frame is not None:
            self._refresh_display()

    def resizeEvent(self, event):
        """窗口大小变化时重绘当前帧"""
        super().resizeEvent(event)
        if self._use_gl and self._gl_renderer and not self._gl_renderer.gl_failed:
            # GL 模式: resizeGL 自动更新视口，纹理数据不变无需重新上传
            return
        if self.current_frame is not None:
            self._display_frame(self.current_frame)

    def closeEvent(self, event):
        """关闭事件"""
        self.pause()
        self._stop_reader_thread()
        if self._gl_renderer is not None:
            self._gl_renderer.cleanup()
        super().closeEvent(event)

    def clear(self):
        """清空预览状态"""
        self._load_generation += 1
        self.pause()
        self._stop_reader_thread()
        self._loop_frame = None
        self.video_path = ""
        self.total_frames = 0
        self.current_frame_index = 0
        self.current_frame = None
        self._display_stack.setCurrentIndex(0)
        self.video_label.clear()
        self.video_label.setText("未加载视频")
        self.info_label.setText("帧: 0/0 | 裁剪: (0, 0, 0, 0)")
