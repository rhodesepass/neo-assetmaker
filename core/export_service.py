"""
导出服务 - 素材导出和打包
"""
import json
import os
import sys
import struct
import shutil
import subprocess
import logging
from typing import Optional, Dict, Any, Tuple, List
from dataclasses import dataclass
from enum import Enum

import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

# PyAV 用于视频解码，替代 cv2.VideoCapture
try:
    import av
    HAS_AV = True
except ImportError:
    HAS_AV = False

from PyQt6.QtCore import QThread, pyqtSignal, QObject

from config.constants import get_resolution_spec
from config.epconfig import EPConfig
from core.video_processor import find_ffmpeg, X264_PARAMS

logger = logging.getLogger(__name__)


class ExportType(Enum):
    """导出类型枚举"""
    LOGO = "logo"
    OVERLAY = "overlay"
    LOOP_VIDEO = "loop"
    INTRO_VIDEO = "intro"
    ICON = "icon"


@dataclass
class VideoExportParams:
    """视频导出参数"""
    video_path: str
    cropbox: Tuple[int, int, int, int]  # (x, y, w, h) 旋转后坐标系
    start_frame: int
    end_frame: int
    fps: float
    resolution: str = "360x640"
    is_image: bool = False  # True=从图片生成视频
    rotation: int = 0  # 旋转角度 (0, 90, 180, 270)


@dataclass
class ExportTask:
    """导出任务"""
    export_type: ExportType
    output_path: str
    data: Any


class ExportWorker(QThread):
    """导出工作线程"""

    progress_updated = pyqtSignal(int, str)
    export_completed = pyqtSignal(str)
    export_failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks: List[ExportTask] = []
        self._output_dir: str = ""
        self._ffmpeg_path: str = ""
        self._cancelled: bool = False
        self._epconfig: Optional[EPConfig] = None
        self._resolution: str = "360x640"
        # 当前FFmpeg进程引用，用于支持取消操作
        # 参考: Python subprocess文档 - Popen.terminate() 可终止子进程
        self._ffmpeg_process: Optional[subprocess.Popen] = None

    def setup(
        self,
        tasks: List[ExportTask],
        output_dir: str,
        ffmpeg_path: str = "",
        epconfig: Optional[EPConfig] = None,
        resolution: str = "360x640",
    ):
        """设置导出任务"""
        self._tasks = tasks
        self._output_dir = output_dir
        self._ffmpeg_path = ffmpeg_path or find_ffmpeg()
        self._epconfig = epconfig
        self._resolution = resolution
        self._cancelled = False

    def cancel(self):
        """
        取消导出
        
        根据Python官方subprocess文档:
        - Popen.terminate(): "Stop the child. On POSIX OSs the method sends SIGTERM
          to the child. On Windows the Win32 API function TerminateProcess() is called."
        """
        self._cancelled = True
        logger.info("导出任务已请求取消")
        
        # 如果有正在运行的FFmpeg进程，立即终止它
        if self._ffmpeg_process is not None:
            try:
                self._ffmpeg_process.terminate()
                logger.info("已发送终止信号给FFmpeg进程")
            except Exception as e:
                logger.warning(f"终止FFmpeg进程时出错: {e}")

    def run(self):
        """执行导出"""
        try:
            total_tasks = len(self._tasks)
            if total_tasks == 0 and not self._epconfig:
                self.export_completed.emit("没有需要导出的任务")
                return

            os.makedirs(self._output_dir, exist_ok=True)

            completed = 0
            for i, task in enumerate(self._tasks):
                if self._cancelled:
                    self.export_failed.emit("导出已取消")
                    return

                base_progress = int((i / (total_tasks + 1)) * 100)

                try:
                    self._execute_task(task, base_progress, total_tasks)
                    completed += 1
                except Exception as e:
                    logger.exception(f"执行任务 {task.export_type.value} 失败")
                    self.export_failed.emit(f"导出 {task.export_type.value} 失败: {str(e)}")
                    return

            if self._epconfig:
                self.progress_updated.emit(95, "正在生成 epconfig.json...")
                self._generate_epconfig()

            self.progress_updated.emit(100, "导出完成")
            self.export_completed.emit(f"成功导出到 {self._output_dir}")

        except Exception as e:
            logger.exception("导出过程发生错误")
            self.export_failed.emit(f"导出失败: {str(e)}")

    def _execute_task(self, task: ExportTask, base_progress: int, total_tasks: int):
        """执行单个任务"""
        output_path = os.path.join(self._output_dir, task.output_path)

        if task.export_type == ExportType.LOGO:
            self.progress_updated.emit(base_progress, f"正在导出 {task.output_path}...")
            self._export_argb(output_path, task.data, is_logo=True)

        elif task.export_type == ExportType.OVERLAY:
            self.progress_updated.emit(base_progress, f"正在导出 {task.output_path}...")
            self._export_argb(output_path, task.data, is_logo=False)

        elif task.export_type == ExportType.ICON:
            self.progress_updated.emit(base_progress, f"正在导出 {task.output_path}...")
            if HAS_CV2:
                success, encoded = cv2.imencode('.png', task.data)
                if success:
                    with open(output_path, 'wb') as f:
                        f.write(encoded.tobytes())

        elif task.export_type in (ExportType.LOOP_VIDEO, ExportType.INTRO_VIDEO):
            self.progress_updated.emit(base_progress, f"正在导出 {task.output_path}...")
            self._export_video(output_path, task.data, base_progress, total_tasks)

    def _export_argb(self, output_path: str, mat: np.ndarray, is_logo: bool = False):
        """导出ARGB格式文件"""
        mat = cv2.rotate(mat, cv2.ROTATE_180) if HAS_CV2 else np.rot90(mat, 2)
        mat = mat.astype(np.uint8)
        h, w = mat.shape[:2]
        channels = mat.shape[-1] if len(mat.shape) == 3 else 1

        with open(output_path, "wb") as f:
            for y in range(h):
                if self._cancelled:
                    raise InterruptedError("导出已取消")
                for x in range(w):
                    if channels == 4:
                        b, g, r, a = mat[y, x]
                    elif channels == 3:
                        b, g, r = mat[y, x]
                        a = 255
                    else:
                        b = g = r = mat[y, x]
                        a = 255
                    f.write(struct.pack("BBBB", b, g, r, a))

    def _export_video(
        self,
        output_path: str,
        params: VideoExportParams,
        base_progress: int,
        total_tasks: int
    ):
        """导出视频"""
        if not self._ffmpeg_path:
            raise RuntimeError("未找到ffmpeg，无法导出视频")

        if not HAS_CV2:
            raise RuntimeError("未安装opencv-python，无法处理视频")

        if not HAS_AV:
            raise RuntimeError("未安装PyAV，无法解码视频")

        if params.is_image:
            self._export_video_from_image(output_path, params, base_progress, total_tasks)
            return

        spec = get_resolution_spec(params.resolution)
        target_w = spec["width"]
        target_h = spec["height"]
        padded_w = spec["padded_width"]
        padded_h = spec["padded_height"]
        padding_side = spec["padding_side"]
        rotate_180 = spec["rotate_180"]

        temp_dir = os.path.join(self._output_dir, "_temp_frames").replace("\\", "/")
        os.makedirs(temp_dir, exist_ok=True)

        try:
            # 使用 PyAV 解码视频，替代 cv2.VideoCapture
            # 参考: https://pyav.org/docs/stable/api/container.html
            container = av.open(params.video_path)
            stream = container.streams.video[0]
            # 启用多线程解码以提升性能
            stream.thread_type = "AUTO"

            total_frames = params.end_frame - params.start_frame

            orig_w = stream.width
            orig_h = stream.height
            rotation = params.rotation

            # 任意角度旋转：预计算旋转矩阵（循环外计算，所有帧复用）
            rot_matrix = None
            rotated_size = None
            if rotation not in (0, 90, 180, 270):
                cx, cy = orig_w / 2.0, orig_h / 2.0
                rot_matrix = cv2.getRotationMatrix2D((cx, cy), -rotation, 1.0)
                cos_a, sin_a = abs(rot_matrix[0, 0]), abs(rot_matrix[0, 1])
                nw = int(orig_w * cos_a + orig_h * sin_a)
                nh = int(orig_w * sin_a + orig_h * cos_a)
                rot_matrix[0, 2] += (nw - orig_w) / 2.0
                rot_matrix[1, 2] += (nh - orig_h) / 2.0
                rotated_size = (nw, nh)

            # cropbox 已在旋转后坐标系中，直接使用（无需坐标变换）
            rx, ry, rw, rh = params.cropbox

            # 精确 seek 到起始帧
            # 参考: https://pyav.org/docs/stable/api/container.html#av.container.InputContainer.seek
            fps = float(stream.average_rate) if stream.average_rate else params.fps
            time_base = stream.time_base
            if params.start_frame > 0 and time_base and fps > 0:
                target_sec = params.start_frame / fps
                target_pts = int(target_sec / time_base)
                container.seek(target_pts, stream=stream, backward=True)

            frames_written = 0
            frame_idx = 0
            for av_frame in container.decode(stream):
                if self._cancelled:
                    raise InterruptedError("导出已取消")

                if av_frame.pts is not None and time_base and fps > 0:
                    current_sec = float(av_frame.pts * time_base)
                    current_idx = int(current_sec * fps)
                else:
                    current_idx = frame_idx

                # 跳过 seek 后尚未到达起始帧的帧
                if current_idx < params.start_frame:
                    continue

                if current_idx >= params.end_frame:
                    break

                frame = av_frame.to_ndarray(format='bgr24')

                if rotation == 90:
                    frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                elif rotation == 180:
                    frame = cv2.rotate(frame, cv2.ROTATE_180)
                elif rotation == 270:
                    frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
                elif rotation != 0:
                    frame = cv2.warpAffine(
                        frame, rot_matrix, rotated_size,
                        flags=cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_CONSTANT,
                        borderValue=(0, 0, 0))

                frame = frame[ry:ry+rh, rx:rx+rw]
                frame = cv2.resize(frame, (target_w, target_h))

                if rotate_180:
                    frame = cv2.rotate(frame, cv2.ROTATE_180)

                # 写入帧序号基于已写入数量，确保文件名连续
                frame_path = os.path.join(temp_dir, f"frame_{frames_written:06d}.png").replace("\\", "/")
                success, encoded = cv2.imencode('.png', frame)
                if success:
                    with open(frame_path, 'wb') as f:
                        f.write(encoded.tobytes())
                    frames_written += 1

                if frames_written % 10 == 0:
                    progress = base_progress + int((frames_written / total_frames) * 50 / total_tasks)
                    self.progress_updated.emit(progress, f"处理帧 {frames_written}/{total_frames}")

                frame_idx += 1

            container.close()

            if frames_written == 0:
                raise RuntimeError("没有成功写入任何视频帧")
            logger.info(f"成功写入 {frames_written} 帧")

            self.progress_updated.emit(base_progress + 50, "正在编码视频...")
            input_pattern = f"{temp_dir}/frame_%06d.png"
            output_file = output_path.replace("\\", "/")

            self._run_ffmpeg_crf(
                input_pattern=input_pattern,
                output_file=output_file,
                fps=params.fps,
                padded_w=padded_w,
                padded_h=padded_h,
            )

        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

    def _run_ffmpeg_crf(
        self,
        input_pattern: str,
        output_file: str,
        fps: float,
        padded_w: int = 0,
        padded_h: int = 0,
    ):
        """使用FFmpeg进行CRF质量编码

        CRF (Constant Rate Factor) 模式以恒定质量为目标，
        由 x264 自动分配码率。
        参考: https://trac.ffmpeg.org/wiki/Encode/H.264#crf

        当 padded_w/padded_h 非零时，使用 -vf pad 滤镜添加黑边，
        替代之前逐帧 numpy 拼接的方式，性能更优。
        参考: https://ffmpeg.org/ffmpeg-filters.html#pad
        """
        crf_value = 19
        preset = "medium"

        vf_filters = []
        if padded_w > 0 and padded_h > 0:
            vf_filters.append(f"pad={padded_w}:{padded_h}:0:0:black")

        cmd = [
            self._ffmpeg_path,
            "-hide_banner",
            "-framerate", str(fps),
            "-i", input_pattern,
        ]
        if vf_filters:
            cmd.extend(["-vf", ",".join(vf_filters)])
        cmd.extend([
            "-c:v", "libx264",
            "-preset", preset,
            "-crf", str(crf_value),
            "-profile:v", "high",
            "-level", "4.0",
            "-pix_fmt", "yuv420p",
            "-x264-params", X264_PARAMS,
            "-an",
            "-y",
            output_file
        ])

        logger.info(f"执行ffmpeg CRF编码 (crf={crf_value}, preset={preset}): {' '.join(cmd)}")

        popen_kwargs = {
            'stdout': subprocess.PIPE,
            'stderr': subprocess.PIPE,
            'encoding': 'utf-8',
            'errors': 'replace'
        }
        if sys.platform == 'win32':
            popen_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

        self._ffmpeg_process = subprocess.Popen(cmd, **popen_kwargs)

        # 使用 communicate(timeout) 循环等待进程完成
        # Python文档警告: 使用 poll() + PIPE 会导致死锁，必须用 communicate()
        # https://docs.python.org/3/library/subprocess.html#subprocess.Popen.wait
        stdout, stderr = "", ""
        while True:
            try:
                out, err = self._ffmpeg_process.communicate(timeout=0.5)
                stdout = out or ""
                stderr = err or ""
                break
            except subprocess.TimeoutExpired:
                if self._cancelled:
                    self._ffmpeg_process.kill()
                    self._ffmpeg_process.communicate()
                    self._ffmpeg_process = None
                    raise InterruptedError("导出已取消")

        returncode = self._ffmpeg_process.returncode
        self._ffmpeg_process = None

        if returncode != 0:
            stderr_msg = stderr[-500:] if stderr else "未知错误"
            logger.error(f"ffmpeg CRF编码 stderr: {stderr}")
            raise RuntimeError(f"ffmpeg CRF编码失败 (code {returncode}): {stderr_msg}")

        logger.info("CRF编码完成")

    def _export_video_from_image(
        self,
        output_path: str,
        params: VideoExportParams,
        base_progress: int,
        total_tasks: int
    ):
        """从单张图片生成1秒循环视频（30fps，共30帧）"""
        spec = get_resolution_spec(params.resolution)
        target_w = spec["width"]
        target_h = spec["height"]
        padded_w = spec["padded_width"]
        padded_h = spec["padded_height"]
        padding_side = spec["padding_side"]
        rotate_180 = spec["rotate_180"]

        image_path = params.video_path
        img_array = np.fromfile(image_path, dtype=np.uint8)
        frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError(f"无法打开图片: {image_path}")

        frame = cv2.resize(frame, (target_w, target_h))

        if rotate_180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)

        temp_dir = os.path.join(self._output_dir, "_temp_frames").replace("\\", "/")
        os.makedirs(temp_dir, exist_ok=True)

        try:
            fps = 30.0
            total_frames = 30

            for frame_idx in range(total_frames):
                if self._cancelled:
                    raise InterruptedError("导出已取消")

                frame_path = os.path.join(temp_dir, f"frame_{frame_idx:06d}.png").replace("\\", "/")
                success, encoded = cv2.imencode('.png', frame)
                if success:
                    with open(frame_path, 'wb') as f:
                        f.write(encoded.tobytes())

                if frame_idx % 10 == 0:
                    progress = base_progress + int((frame_idx / total_frames) * 50 / total_tasks)
                    self.progress_updated.emit(progress, f"生成帧 {frame_idx}/{total_frames}")

            logger.info(f"成功生成 {total_frames} 帧")

            self.progress_updated.emit(base_progress + 50, "正在编码视频...")
            input_pattern = f"{temp_dir}/frame_%06d.png"
            output_file = output_path.replace("\\", "/")

            self._run_ffmpeg_crf(
                input_pattern=input_pattern,
                output_file=output_file,
                fps=fps,
                padded_w=padded_w,
                padded_h=padded_h,
            )

        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

    def _generate_epconfig(self):
        """生成epconfig.json"""
        if not self._epconfig:
            return

        config_path = os.path.join(self._output_dir, "epconfig.json")
        try:
            config_dict = self._epconfig.to_dict(normalize_paths=True)
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_dict, f, ensure_ascii=False, indent=4)
            logger.info(f"已生成配置: {config_path}")
        except Exception as e:
            logger.error(f"生成epconfig.json失败: {e}")
            raise


class ExportService(QObject):
    """导出服务"""

    progress_updated = pyqtSignal(int, str)
    export_completed = pyqtSignal(str)
    export_failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: Optional[ExportWorker] = None
        self._ffmpeg_path: str = ""

    @property
    def is_exporting(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    @property
    def ffmpeg_available(self) -> bool:
        if not self._ffmpeg_path:
            self._ffmpeg_path = find_ffmpeg()
        return bool(self._ffmpeg_path)

    def export_all(
        self,
        output_dir: str,
        epconfig: EPConfig,
        logo_mat: Optional[np.ndarray] = None,
        overlay_mat: Optional[np.ndarray] = None,
        loop_video_params: Optional[VideoExportParams] = None,
        intro_video_params: Optional[VideoExportParams] = None,
        loop_image_path: Optional[str] = None,
    ):
        """导出所有素材"""
        if self.is_exporting:
            self.export_failed.emit("已有导出任务正在进行")
            return

        tasks = []
        resolution = epconfig.screen.value

        if logo_mat is not None:
            tasks.append(ExportTask(
                export_type=ExportType.ICON,
                output_path="icon.png",
                data=logo_mat
            ))

        if overlay_mat is not None:
            tasks.append(ExportTask(
                export_type=ExportType.OVERLAY,
                output_path="overlay.argb",
                data=overlay_mat
            ))

        if loop_image_path is not None:
            if not self.ffmpeg_available:
                self.export_failed.emit("未找到ffmpeg，无法导出视频")
                return
            image_params = VideoExportParams(
                video_path=loop_image_path,
                cropbox=(0, 0, 0, 0),
                start_frame=0,
                end_frame=30,
                fps=30.0,
                resolution=resolution,
                is_image=True
            )
            tasks.append(ExportTask(
                export_type=ExportType.LOOP_VIDEO,
                output_path="loop.mp4",
                data=image_params
            ))
        elif loop_video_params is not None:
            if not self.ffmpeg_available:
                self.export_failed.emit("未找到ffmpeg，无法导出视频")
                return
            loop_video_params.resolution = resolution
            tasks.append(ExportTask(
                export_type=ExportType.LOOP_VIDEO,
                output_path="loop.mp4",
                data=loop_video_params
            ))

        if intro_video_params is not None:
            if not self.ffmpeg_available:
                self.export_failed.emit("未找到ffmpeg，无法导出视频")
                return
            intro_video_params.resolution = resolution
            tasks.append(ExportTask(
                export_type=ExportType.INTRO_VIDEO,
                output_path="intro.mp4",
                data=intro_video_params
            ))

        if not tasks:
            self.export_failed.emit("没有需要导出的内容")
            return

        self._worker = ExportWorker(self)
        self._worker.setup(
            tasks=tasks,
            output_dir=output_dir,
            ffmpeg_path=self._ffmpeg_path,
            epconfig=epconfig,
            resolution=resolution,
        )

        self._worker.progress_updated.connect(self.progress_updated.emit)
        self._worker.export_completed.connect(self._on_completed)
        self._worker.export_failed.connect(self._on_failed)

        self._worker.start()

    def cancel(self):
        """取消导出"""
        if self._worker and self._worker.isRunning():
            self._worker.cancel()

    def _on_completed(self, message: str):
        self.export_completed.emit(message)
        self._cleanup()

    def _on_failed(self, message: str):
        self.export_failed.emit(message)
        self._cleanup()

    def _cleanup(self):
        if self._worker:
            # 不阻塞主线程，让工作线程自然结束
            self._worker.deleteLater()
            self._worker = None
