"""
后台视频帧读取线程

Qt 6 官方文档依据：
- QImage 可安全在非 GUI 线程创建 (https://doc.qt.io/qt-6/qimage.html#details)
- QThread.run() 在新线程执行 (https://doc.qt.io/qt-6/qthread.html#run)
- 跨线程信号自动使用 QueuedConnection (https://doc.qt.io/qt-6/threads-qobjects.html)
- QPixmap 必须在主线程创建 (https://doc.qt.io/qt-6/qpixmap.html#details)
"""
import logging
import queue
from typing import Optional

import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage

logger = logging.getLogger(__name__)

# 命令常量
CMD_OPEN = "open"
CMD_READ_NEXT = "read_next"
CMD_SEEK = "seek"
CMD_SET_ROTATION = "set_rotation"
CMD_SET_CROPBOX = "set_cropbox"
CMD_SET_PREVIEW_PARAMS = "set_preview_params"
CMD_STOP = "stop"


class FrameReaderThread(QThread):
    """后台视频帧读取线程

    负责：视频打开/关闭、帧读取、旋转/颜色转换、生成 QImage
    不负责：QPixmap 创建、UI 更新（这些必须在主线程）
    """

    # 信号
    video_opened = pyqtSignal(float, int, int, int)  # fps, width, height, total_frames
    video_open_failed = pyqtSignal(str)               # error_msg
    frame_ready = pyqtSignal(int, QImage, object)     # frame_index, display_qimage, raw_frame

    def __init__(self, parent=None):
        super().__init__(parent)
        self._command_queue: queue.Queue = queue.Queue()

        # 工作线程内部状态（仅在 run() 中访问）
        self._rotation: int = 0
        self._cropbox: list = [0, 0, 360, 640]
        self._preview_mode: bool = False
        self._epconfig = None
        self._overlay_renderer = None
        self._target_width: int = 360
        self._target_height: int = 640
        self._target_aspect_ratio: float = 360 / 640

    # ── 公共方法（主线程调用，往队列塞命令） ──

    def request_open(self, path: str):
        self._command_queue.put((CMD_OPEN, path))

    def request_read_next(self):
        self._command_queue.put((CMD_READ_NEXT, None))

    def request_seek(self, frame_index: int):
        self._command_queue.put((CMD_SEEK, frame_index))

    def request_set_rotation(self, degrees: int):
        self._command_queue.put((CMD_SET_ROTATION, degrees))

    def request_set_cropbox(self, cropbox: list):
        self._command_queue.put((CMD_SET_CROPBOX, cropbox.copy()))

    def request_set_preview_params(self, preview_mode: bool, target_w: int,
                                   target_h: int, epconfig=None,
                                   overlay_renderer=None):
        self._command_queue.put((CMD_SET_PREVIEW_PARAMS, (
            preview_mode, target_w, target_h, epconfig, overlay_renderer
        )))

    def request_stop(self):
        self._command_queue.put((CMD_STOP, None))

    # ── 工作线程主循环 ──

    def run(self):
        cap: Optional[cv2.VideoCapture] = None
        current_frame_index: int = 0
        total_frames: int = 0

        while True:
            try:
                cmd, args = self._command_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            if cmd == CMD_STOP:
                break

            elif cmd == CMD_OPEN:
                path = args
                if cap is not None:
                    cap.release()
                    cap = None
                cap, current_frame_index, total_frames = self._open_video(path)

            elif cmd == CMD_READ_NEXT:
                if cap is None:
                    continue
                # 丢帧策略：队列中有多个 READ_NEXT 时只处理最后一个
                skip_count = 0
                while not self._command_queue.empty():
                    try:
                        peek_cmd, peek_args = self._command_queue.get_nowait()
                    except queue.Empty:
                        break
                    if peek_cmd == CMD_READ_NEXT:
                        skip_count += 1
                        continue
                    else:
                        # 非 READ_NEXT 命令放回队列前面处理
                        # 由于 queue.Queue 不支持 put_front，我们手动处理
                        self._command_queue.put((peek_cmd, peek_args))
                        break

                current_frame_index += 1
                if current_frame_index >= total_frames:
                    current_frame_index = 0
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

                self._read_and_emit(cap, current_frame_index)

            elif cmd == CMD_SEEK:
                if cap is None:
                    continue
                frame_index = max(0, min(args, total_frames - 1))
                current_frame_index = frame_index
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                self._read_and_emit(cap, current_frame_index)

            elif cmd == CMD_SET_ROTATION:
                self._rotation = args % 360

            elif cmd == CMD_SET_CROPBOX:
                self._cropbox = args

            elif cmd == CMD_SET_PREVIEW_PARAMS:
                (self._preview_mode, self._target_width,
                 self._target_height, self._epconfig,
                 self._overlay_renderer) = args
                if self._target_height > 0:
                    self._target_aspect_ratio = (
                        self._target_width / self._target_height)

        # 线程结束，释放资源
        if cap is not None:
            cap.release()
        logger.debug("FrameReaderThread 已退出")

    # ── 内部方法（仅在工作线程内调用） ──

    def _open_video(self, path: str):
        """打开视频文件，返回 (cap, current_frame_index, total_frames)"""
        if not HAS_CV2:
            self.video_open_failed.emit("OpenCV 未安装")
            return None, 0, 0

        try:
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                import sys
                if sys.platform.startswith('win'):
                    cap = cv2.VideoCapture(str(path))
        except Exception as e:
            self.video_open_failed.emit(f"加载视频时出错: {e}")
            return None, 0, 0

        if not cap.isOpened():
            self.video_open_failed.emit("无法打开视频")
            return None, 0, 0

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        logger.info(
            f"[线程] 视频已加载: {width}x{height}, "
            f"{total_frames} 帧, {fps:.1f} FPS"
        )

        # 发送打开成功信号
        self.video_opened.emit(fps, width, height, total_frames)

        # 读取并发送第一帧
        self._read_and_emit(cap, 0)

        return cap, 0, total_frames

    def _read_and_emit(self, cap, frame_index: int):
        """读取一帧、处理、通过信号发送"""
        ret, frame = cap.read()
        if not ret:
            logger.warning(f"[线程] 无法读取帧 {frame_index}")
            return

        raw_frame = frame  # 原始帧（供主线程 cropbox 交互用）

        # 应用旋转
        rotated_frame = self._apply_rotation(frame)

        # 组合显示帧（编辑模式叠加 cropbox / 预览模式裁剪+overlay）
        display_frame = self._compose_display(rotated_frame)

        # BGR → RGB → QImage
        rgb_frame = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_frame.shape
        bytes_per_line = ch * w
        # .copy() 确保 QImage 数据独立于 numpy buffer
        qimg = QImage(
            rgb_frame.data, w, h, bytes_per_line,
            QImage.Format.Format_RGB888
        ).copy()

        self.frame_ready.emit(frame_index, qimg, raw_frame)

    def _compose_display(self, rotated_frame: np.ndarray) -> np.ndarray:
        """组合显示帧"""
        x, y, w, h = self._cropbox

        if self._preview_mode:
            # 预览模式：裁剪 + 缩放 + overlay
            rh, rw = rotated_frame.shape[:2]
            # 确保裁剪区域在帧范围内
            cx = max(0, min(x, rw - 1))
            cy = max(0, min(y, rh - 1))
            cw = min(w, rw - cx)
            ch = min(h, rh - cy)
            if cw <= 0 or ch <= 0:
                return rotated_frame

            cropped = rotated_frame[cy:cy+ch, cx:cx+cw].copy()
            preview_frame = cv2.resize(
                cropped, (self._target_width, self._target_height))

            if self._epconfig and self._overlay_renderer:
                try:
                    from config.epconfig import OverlayType
                    if self._epconfig.overlay.type == OverlayType.ARKNIGHTS:
                        preview_frame = (
                            self._overlay_renderer.render_arknights_overlay(
                                preview_frame,
                                self._epconfig.overlay.arknights_options
                            ))
                except Exception:
                    pass

            return preview_frame
        else:
            # 编辑模式：绘制 cropbox 叠加层
            display_frame = rotated_frame.copy()

            cv2.rectangle(
                display_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

            # 角落手柄
            hs = 8
            handle_color = (0, 200, 255)
            for px, py in [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]:
                cv2.rectangle(
                    display_frame,
                    (px - hs, py - hs), (px + hs, py + hs),
                    handle_color, -1
                )

            return display_frame

    def _apply_rotation(self, frame: np.ndarray) -> np.ndarray:
        """应用旋转（从 VideoPreviewWidget 迁移的逻辑）"""
        if self._rotation == 0:
            return frame
        if self._rotation == 90:
            return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif self._rotation == 180:
            return cv2.rotate(frame, cv2.ROTATE_180)
        elif self._rotation == 270:
            return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        # 任意角度
        h, w = frame.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), -self._rotation, 1.0)
        cos_a, sin_a = abs(M[0, 0]), abs(M[0, 1])
        new_w = int(w * cos_a + h * sin_a)
        new_h = int(w * sin_a + h * cos_a)
        M[0, 2] += (new_w - w) / 2.0
        M[1, 2] += (new_h - h) / 2.0
        return cv2.warpAffine(
            frame, M, (new_w, new_h),
            borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
