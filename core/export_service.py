"""
导出服务 - 素材导出和打包
"""
import os
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

from PyQt6.QtCore import QThread, pyqtSignal, QObject

from config.constants import get_resolution_spec
from config.epconfig import EPConfig
from utils.file_utils import get_app_dir

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
    cropbox: Tuple[int, int, int, int]  # (x, y, w, h)
    start_frame: int
    end_frame: int
    fps: float
    resolution: str = "360x640"
    is_image: bool = False  # True=从图片生成视频


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

    def setup(
        self,
        tasks: List[ExportTask],
        output_dir: str,
        ffmpeg_path: str = "",
        epconfig: Optional[EPConfig] = None,
        resolution: str = "360x640"
    ):
        """设置导出任务"""
        self._tasks = tasks
        self._output_dir = output_dir
        self._ffmpeg_path = ffmpeg_path or self._find_ffmpeg()
        self._epconfig = epconfig
        self._resolution = resolution
        self._cancelled = False

    def cancel(self):
        """取消导出"""
        self._cancelled = True
        logger.info("导出任务已请求取消")

    def _find_ffmpeg(self) -> str:
        """查找ffmpeg（支持打包环境）"""
        # 1. 先在应用程序目录查找（支持 Nuitka/PyInstaller 打包）
        app_ffmpeg = os.path.join(get_app_dir(), "ffmpeg.exe")
        if os.path.isfile(app_ffmpeg):
            return app_ffmpeg

        # 2. 在当前工作目录查找
        local_ffmpeg = os.path.join(os.getcwd(), "ffmpeg.exe")
        if os.path.isfile(local_ffmpeg):
            return local_ffmpeg

        # 3. 在系统 PATH 中查找
        try:
            cmd = ["where", "ffmpeg"] if os.name == 'nt' else ["which", "ffmpeg"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip().split('\n')[0]
        except Exception:
            pass

        return ""

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

            # 生成epconfig.json
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
                cv2.imwrite(output_path, task.data)

        elif task.export_type in (ExportType.LOOP_VIDEO, ExportType.INTRO_VIDEO):
            self.progress_updated.emit(base_progress, f"正在导出 {task.output_path}...")
            self._export_video(output_path, task.data, base_progress, total_tasks)

    def _export_argb(self, output_path: str, mat: np.ndarray, is_logo: bool = False):
        """导出ARGB格式文件"""
        # 旋转180度
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

        # 图片模式：从单张图片生成1秒循环视频
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
            cap = cv2.VideoCapture(params.video_path)
            if not cap.isOpened():
                raise RuntimeError(f"无法打开视频: {params.video_path}")

            cap.set(cv2.CAP_PROP_POS_FRAMES, params.start_frame)
            total_frames = params.end_frame - params.start_frame

            frames_written = 0
            for frame_idx in range(total_frames):
                if self._cancelled:
                    raise InterruptedError("导出已取消")

                ret, frame = cap.read()
                if not ret:
                    break

                x, y, w, h = params.cropbox
                frame = frame[y:y+h, x:x+w]
                frame = cv2.resize(frame, (target_w, target_h))

                if rotate_180:
                    frame = cv2.rotate(frame, cv2.ROTATE_180)

                if padding_side == "right":
                    pad_w = padded_w - target_w
                    if pad_w > 0:
                        padding = np.zeros((target_h, pad_w, 3), dtype=np.uint8)
                        frame = np.hstack([frame, padding])
                elif padding_side == "bottom":
                    pad_h = padded_h - target_h
                    if pad_h > 0:
                        padding = np.zeros((pad_h, target_w, 3), dtype=np.uint8)
                        frame = np.vstack([frame, padding])

                frame_path = os.path.join(temp_dir, f"frame_{frame_idx:06d}.png").replace("\\", "/")
                success, encoded = cv2.imencode('.png', frame)
                if success:
                    with open(frame_path, 'wb') as f:
                        f.write(encoded.tobytes())
                    frames_written += 1

                if frame_idx % 10 == 0:
                    progress = base_progress + int((frame_idx / total_frames) * 50 / total_tasks)
                    self.progress_updated.emit(progress, f"处理帧 {frame_idx}/{total_frames}")

            cap.release()

            if frames_written == 0:
                raise RuntimeError("没有成功写入任何视频帧")
            logger.info(f"成功写入 {frames_written} 帧")

            self.progress_updated.emit(base_progress + 50, "正在编码视频...")
            input_pattern = f"{temp_dir}/frame_%06d.png"
            output_file = output_path.replace("\\", "/")

            ffmpeg_cmd = [
                self._ffmpeg_path,
                "-hide_banner",
                "-framerate", str(params.fps),
                "-i", input_pattern,
                "-c:v", "libx264",
                "-profile:v", "high",
                "-level", "4.0",
                "-pix_fmt", "yuv420p",
                "-b:v", "3000k",
                "-an", "-y",
                output_file
            ]

            logger.info(f"执行ffmpeg命令: {' '.join(ffmpeg_cmd)}")

            process = subprocess.run(
                ffmpeg_cmd,
                capture_output=True,
                encoding='utf-8',
                errors='replace'
            )
            if process.returncode != 0:
                stderr_msg = process.stderr[-500:] if process.stderr else "未知错误"
                logger.error(f"ffmpeg完整stderr: {process.stderr}")
                raise RuntimeError(f"ffmpeg编码失败 (code {process.returncode}): {stderr_msg}")

        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

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

        # 读取图片
        image_path = params.video_path
        img_array = np.fromfile(image_path, dtype=np.uint8)
        frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError(f"无法打开图片: {image_path}")

        # 缩放到目标分辨率
        frame = cv2.resize(frame, (target_w, target_h))

        # 旋转180度
        if rotate_180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)

        # 添加黑边
        if padding_side == "right":
            pad_w = padded_w - target_w
            if pad_w > 0:
                padding = np.zeros((target_h, pad_w, 3), dtype=np.uint8)
                frame = np.hstack([frame, padding])
        elif padding_side == "bottom":
            pad_h = padded_h - target_h
            if pad_h > 0:
                padding = np.zeros((pad_h, target_w, 3), dtype=np.uint8)
                frame = np.vstack([frame, padding])

        temp_dir = os.path.join(self._output_dir, "_temp_frames").replace("\\", "/")
        os.makedirs(temp_dir, exist_ok=True)

        try:
            # 生成30帧（1秒@30fps）
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

            # 使用ffmpeg编码
            self.progress_updated.emit(base_progress + 50, "正在编码视频...")
            input_pattern = f"{temp_dir}/frame_%06d.png"
            output_file = output_path.replace("\\", "/")

            ffmpeg_cmd = [
                self._ffmpeg_path,
                "-hide_banner",
                "-framerate", str(fps),
                "-i", input_pattern,
                "-c:v", "libx264",
                "-profile:v", "high",
                "-level", "4.0",
                "-pix_fmt", "yuv420p",
                "-b:v", "3000k",
                "-an", "-y",
                output_file
            ]

            logger.info(f"执行ffmpeg命令: {' '.join(ffmpeg_cmd)}")

            process = subprocess.run(
                ffmpeg_cmd,
                capture_output=True,
                encoding='utf-8',
                errors='replace'
            )
            if process.returncode != 0:
                stderr_msg = process.stderr[-500:] if process.stderr else "未知错误"
                logger.error(f"ffmpeg完整stderr: {process.stderr}")
                raise RuntimeError(f"ffmpeg编码失败 (code {process.returncode}): {stderr_msg}")

        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

    def _generate_epconfig(self):
        """生成epconfig.json"""
        if not self._epconfig:
            return

        config_path = os.path.join(self._output_dir, "epconfig.json")
        try:
            exported_types = {task.export_type for task in self._tasks}

            if ExportType.LOOP_VIDEO in exported_types:
                self._epconfig.loop.file = "loop.mp4"
            if ExportType.ICON in exported_types:
                self._epconfig.icon = "icon.png"
            if ExportType.INTRO_VIDEO in exported_types:
                self._epconfig.intro.file = "intro.mp4"

            self._epconfig.save_to_file(config_path)
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
            self._ffmpeg_path = self._find_ffmpeg()
        return bool(self._ffmpeg_path)

    def _find_ffmpeg(self) -> str:
        """查找ffmpeg（支持打包环境）"""
        # 1. 先在应用程序目录查找（支持 Nuitka/PyInstaller 打包）
        app_ffmpeg = os.path.join(get_app_dir(), "ffmpeg.exe")
        if os.path.isfile(app_ffmpeg):
            return app_ffmpeg

        # 2. 在当前工作目录查找
        local_ffmpeg = os.path.join(os.getcwd(), "ffmpeg.exe")
        if os.path.isfile(local_ffmpeg):
            return local_ffmpeg

        # 3. 在系统 PATH 中查找
        try:
            cmd = ["where", "ffmpeg"] if os.name == 'nt' else ["which", "ffmpeg"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip().split('\n')[0]
        except Exception:
            pass

        return ""

    def export_all(
        self,
        output_dir: str,
        epconfig: EPConfig,
        logo_mat: Optional[np.ndarray] = None,
        overlay_mat: Optional[np.ndarray] = None,
        loop_video_params: Optional[VideoExportParams] = None,
        intro_video_params: Optional[VideoExportParams] = None
    ):
        """导出所有素材"""
        if self.is_exporting:
            self.export_failed.emit("已有导出任务正在进行")
            return

        tasks = []
        resolution = epconfig.screen.value

        # Logo/Icon
        if logo_mat is not None:
            tasks.append(ExportTask(
                export_type=ExportType.ICON,
                output_path="icon.png",
                data=logo_mat
            ))

        # Overlay
        if overlay_mat is not None:
            tasks.append(ExportTask(
                export_type=ExportType.OVERLAY,
                output_path="overlay.argb",
                data=overlay_mat
            ))

        # Loop视频
        if loop_video_params is not None:
            if not self.ffmpeg_available:
                self.export_failed.emit("未找到ffmpeg，无法导出视频")
                return
            loop_video_params.resolution = resolution
            tasks.append(ExportTask(
                export_type=ExportType.LOOP_VIDEO,
                output_path="loop.mp4",
                data=loop_video_params
            ))

        # Intro视频
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

        # 启动工作线程
        self._worker = ExportWorker(self)
        self._worker.setup(
            tasks=tasks,
            output_dir=output_dir,
            ffmpeg_path=self._ffmpeg_path,
            epconfig=epconfig,
            resolution=resolution
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
