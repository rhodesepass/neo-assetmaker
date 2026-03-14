"""
后台视频帧读取线程 — 使用 PyAV (FFmpeg) 解码

PyAV 官方文档依据：
- Container.seek() 支持精确 seek (https://pyav.org/docs/develop/api/container.html)
- VideoFrame.to_ndarray() 零拷贝 numpy 转换 (https://pyav.org/docs/develop/cookbook/numpy.html)
- stream.thread_type='AUTO' 启用多线程解码 (https://pyav.org/docs/develop/api/stream.html)

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
    import av
    HAS_AV = True
except ImportError:
    HAS_AV = False

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
CMD_SET_GL_MODE = "set_gl_mode"
CMD_STOP = "stop"


class FrameReaderThread(QThread):
    """后台视频帧读取线程

    负责：视频打开/关闭、帧读取、旋转/颜色转换、生成 QImage
    不负责：QPixmap 创建、UI 更新（这些必须在主线程）

    解码后端：PyAV (FFmpeg Python 绑定)，精确 seek + 多线程解码
    """

    # 信号
    video_opened = pyqtSignal(float, int, int, int)  # fps, width, height, total_frames
    video_open_failed = pyqtSignal(str)               # error_msg
    frame_ready = pyqtSignal(int, QImage, object)     # frame_index, display_qimage, raw_frame
    yuv_frame_ready = pyqtSignal(int, bytes, bytes, bytes, int, int)  # frame_index, Y, U, V, w, h

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
        self._gl_mode: bool = False  # GL 模式：发射 YUV 平面数据

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

    def request_set_gl_mode(self, enabled: bool):
        self._command_queue.put((CMD_SET_GL_MODE, enabled))

    def request_stop(self):
        self._command_queue.put((CMD_STOP, None))

    # ── 工作线程主循环 ──

    def run(self):
        container = None
        stream = None
        fps: float = 30.0
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
                if container is not None:
                    try:
                        container.close()
                    except Exception:
                        pass
                    container = None
                    stream = None
                result = self._open_video(path)
                container = result[0]
                stream = result[1]
                fps = result[2]
                current_frame_index = result[3]
                total_frames = result[4]

            elif cmd == CMD_READ_NEXT:
                if container is None:
                    continue
                # 丢帧策略：队列中有多个 READ_NEXT 时只处理最后一个
                while not self._command_queue.empty():
                    try:
                        peek_cmd, peek_args = self._command_queue.get_nowait()
                    except queue.Empty:
                        break
                    if peek_cmd == CMD_READ_NEXT:
                        continue
                    else:
                        self._command_queue.put((peek_cmd, peek_args))
                        break

                current_frame_index += 1
                if current_frame_index >= total_frames:
                    # 循环回到开头
                    current_frame_index = 0
                    try:
                        container.seek(0, stream=stream)
                    except Exception:
                        pass

                self._read_and_emit(container, stream, current_frame_index)

            elif cmd == CMD_SEEK:
                if container is None:
                    continue
                frame_index = max(0, min(args, total_frames - 1))
                current_frame_index = frame_index
                self._seek_and_emit(container, stream, fps,
                                    current_frame_index)

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

            elif cmd == CMD_SET_GL_MODE:
                self._gl_mode = args

        # 线程结束，释放资源
        if container is not None:
            try:
                container.close()
            except Exception:
                pass
        logger.debug("FrameReaderThread 已退出")

    # ── 内部方法（仅在工作线程内调用） ──

    def _open_video(self, path: str):
        """打开视频文件，返回 (container, stream, fps, frame_index, total_frames)"""
        if not HAS_AV:
            self.video_open_failed.emit("PyAV (FFmpeg) 未安装")
            return None, None, 30.0, 0, 0

        try:
            container = av.open(path)
        except Exception as e:
            self.video_open_failed.emit(f"加载视频时出错: {e}")
            return None, None, 30.0, 0, 0

        if not container.streams.video:
            self.video_open_failed.emit("视频文件中没有视频流")
            container.close()
            return None, None, 30.0, 0, 0

        stream = container.streams.video[0]
        # 启用 FFmpeg 内部多线程解码
        stream.thread_type = "AUTO"

        # 获取可靠的元数据
        fps = float(stream.average_rate) if stream.average_rate else 30.0
        width = stream.width
        height = stream.height

        # 帧数获取策略：stream.frames > duration 计算 > 回退默认值
        total_frames = stream.frames
        if total_frames == 0 and stream.duration is not None and stream.time_base:
            duration_sec = float(stream.duration * stream.time_base)
            total_frames = max(1, int(duration_sec * fps))
        if total_frames == 0:
            # 最后手段：使用容器级 duration
            if container.duration is not None:
                duration_sec = container.duration / av.time_base
                total_frames = max(1, int(duration_sec * fps))
            else:
                total_frames = 1

        logger.info(
            f"[线程] 视频已加载 (PyAV): {width}x{height}, "
            f"{total_frames} 帧, {fps:.1f} FPS"
        )

        # 发送打开成功信号
        self.video_opened.emit(fps, width, height, total_frames)

        # 读取并发送第一帧
        self._read_and_emit(container, stream, 0)

        return container, stream, fps, 0, total_frames

    def _read_and_emit(self, container, stream, frame_index: int):
        """顺序读取下一帧、处理、通过信号发送"""
        try:
            for av_frame in container.decode(stream):
                self._process_and_emit_av(av_frame, frame_index)
                return
        except (StopIteration, av.error.EOFError):
            logger.warning(f"[线程] 视频流结束，帧 {frame_index}")
        except Exception as e:
            logger.warning(f"[线程] 无法读取帧 {frame_index}: {e}")

    def _seek_and_emit(self, container, stream, fps: float,
                       target_frame: int):
        """精确 seek 到目标帧并发射

        PyAV seek 策略：
        1. 计算目标 pts
        2. seek 到最近的关键帧（向后）
        3. 逐帧解码直到到达或超过目标帧
        """
        try:
            time_base = stream.time_base
            if not time_base or fps <= 0:
                # 回退：直接 seek 到时间戳 0 然后顺序读取
                container.seek(0, stream=stream)
                self._read_and_emit(container, stream, target_frame)
                return

            # 计算目标时间戳 (pts)
            target_sec = target_frame / fps
            target_pts = int(target_sec / time_base)

            # seek 到最近的关键帧（backward=True 确保不会跳过目标）
            container.seek(target_pts, stream=stream, backward=True)

            # 逐帧解码直到到达目标帧
            frame = None
            for av_frame in container.decode(stream):
                frame = av_frame
                if av_frame.pts is not None:
                    current_sec = float(av_frame.pts * time_base)
                    current_frame_idx = int(current_sec * fps)
                    if current_frame_idx >= target_frame:
                        break
                else:
                    # pts 不可用，直接使用第一帧
                    break

            if frame is not None:
                self._process_and_emit_av(frame, target_frame)
            else:
                logger.warning(f"[线程] seek 后无法读取帧 {target_frame}")

        except Exception as e:
            logger.warning(f"[线程] seek 到帧 {target_frame} 失败: {e}")

    def _process_and_emit_av(self, av_frame, frame_index: int):
        """处理 av.VideoFrame，根据模式发射 YUV 或 BGR 信号

        GL 编辑模式：提取 YUV420P 平面直传 GPU，跳过 CPU 旋转/合成
        GL 预览模式 / QLabel 模式：BGR 转换 + CPU 旋转/合成 + QImage
        """
        # GL 编辑模式：YUV 零拷贝
        if self._gl_mode and not self._preview_mode:
            try:
                y, u, v, w, h = self._extract_yuv_planes(av_frame)
                self.yuv_frame_ready.emit(frame_index, y, u, v, w, h)
                # 仍发射 raw_frame 供主线程存储（cropbox 交互标志）
                raw = av_frame.to_ndarray(format='bgr24')
                self.frame_ready.emit(frame_index, QImage(), raw)
                return
            except Exception as e:
                logger.warning(f"[线程] YUV 提取失败，回退 BGR: {e}")

        # QLabel 模式 / GL 预览模式：CPU 处理
        frame = av_frame.to_ndarray(format='bgr24')
        self._process_and_emit(frame, frame_index)

    def _extract_yuv_planes(self, av_frame) -> tuple:
        """从 av.VideoFrame 提取 YUV420P 平面数据

        处理 stride padding：当 plane.line_size > width 时，
        使用 numpy reshape 剥离每行末尾的填充字节。
        """
        if av_frame.format.name != 'yuv420p':
            av_frame = av_frame.reformat(format='yuv420p')

        w, h = av_frame.width, av_frame.height
        uw, uh = w // 2, h // 2

        y_plane = av_frame.planes[0]
        u_plane = av_frame.planes[1]
        v_plane = av_frame.planes[2]

        def plane_bytes(plane, pw, ph):
            if plane.line_size == pw:
                return bytes(plane)
            # 剥离 stride 填充
            buf = np.frombuffer(bytes(plane), dtype=np.uint8)
            return buf.reshape(ph, plane.line_size)[:, :pw].tobytes()

        return (plane_bytes(y_plane, w, h),
                plane_bytes(u_plane, uw, uh),
                plane_bytes(v_plane, uw, uh),
                w, h)

    def _process_and_emit(self, frame: np.ndarray, frame_index: int):
        """处理 BGR numpy 帧并通过信号发送 QImage"""
        raw_frame = frame  # 原始帧（供主线程 cropbox 交互用）

        # 应用旋转
        rotated_frame = self._apply_rotation(frame)

        # 组合显示帧（编辑模式叠加 cropbox / 预览模式裁剪+overlay）
        display_frame = self._compose_display(rotated_frame)

        # BGR → RGB → QImage
        if HAS_CV2:
            rgb_frame = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
        else:
            rgb_frame = display_frame[:, :, ::-1].copy()
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
            if HAS_CV2:
                preview_frame = cv2.resize(
                    cropped, (self._target_width, self._target_height))
            else:
                # numpy fallback (nearest neighbor)
                from PIL import Image
                pil_img = Image.fromarray(cropped)
                pil_img = pil_img.resize(
                    (self._target_width, self._target_height), Image.LANCZOS)
                preview_frame = np.array(pil_img)

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

            if HAS_CV2:
                cv2.rectangle(
                    display_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

                # 角落手柄
                hs = 8
                handle_color = (0, 200, 255)
                for px, py in [(x, y), (x + w, y),
                               (x, y + h), (x + w, y + h)]:
                    cv2.rectangle(
                        display_frame,
                        (px - hs, py - hs), (px + hs, py + hs),
                        handle_color, -1
                    )

            return display_frame

    def _apply_rotation(self, frame: np.ndarray) -> np.ndarray:
        """应用旋转"""
        if self._rotation == 0:
            return frame
        if not HAS_CV2:
            # numpy-only 正交旋转回退
            if self._rotation == 90:
                return np.rot90(frame, k=-1)
            elif self._rotation == 180:
                return np.rot90(frame, k=2)
            elif self._rotation == 270:
                return np.rot90(frame, k=1)
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
