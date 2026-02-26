"""
视频处理器 - 32像素对齐和黑边处理
融合 OpenCV 读取和 FFmpeg 编码
"""
import subprocess
import sys
import os
import logging
from dataclasses import dataclass
from typing import Optional, Callable, Tuple, Dict, Any

from config.constants import RESOLUTION_SPECS, get_resolution_spec
from utils.file_utils import get_app_dir

logger = logging.getLogger(__name__)


@dataclass
class VideoInfo:
    """视频信息"""
    width: int
    height: int
    duration: float  # 秒
    fps: float
    total_frames: int
    codec: str


class VideoProcessor:
    """
    视频处理器 - 实现32像素对齐

    分辨率处理规则：
    - 360x640 -> 384x640 (右边加24px黑边)
    - 480x854 -> 480x864 (下边加10px黑边)
    - 720x1080 -> 720x1080 (旋转180度)
    """

    def __init__(self, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe"):
        """
        初始化视频处理器

        Args:
            ffmpeg_path: ffmpeg可执行文件路径
            ffprobe_path: ffprobe可执行文件路径
        """
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path

    def check_ffmpeg_available(self) -> Tuple[bool, str]:
        """
        检查FFmpeg是否可用

        Returns:
            (是否可用, 错误信息或版本信息)
        """
        try:
            result = subprocess.run(
                [self.ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                # 提取版本信息
                first_line = result.stdout.split('\n')[0] if result.stdout else ""
                return True, first_line
            return False, "FFmpeg返回非零退出码"
        except FileNotFoundError:
            return False, "未找到FFmpeg，请确保已安装并添加到系统PATH"
        except subprocess.TimeoutExpired:
            return False, "FFmpeg响应超时"
        except Exception as e:
            return False, f"检查FFmpeg时出错: {e}"

    def find_ffmpeg(self) -> str:
        """查找系统中的ffmpeg（支持打包环境）"""
        # 1. 先在应用程序目录查找（支持 Nuitka/PyInstaller 打包）
        app_ffmpeg = os.path.join(get_app_dir(), "ffmpeg.exe")
        if os.path.isfile(app_ffmpeg):
            return app_ffmpeg

        # 2. 在 ffmpeg 目录中查找
        ffmpeg_dir_ffmpeg = os.path.join(get_app_dir(), "ffmpeg", "ffmpeg.exe")
        if os.path.isfile(ffmpeg_dir_ffmpeg):
            return ffmpeg_dir_ffmpeg

        # 3. 在当前工作目录查找
        local_ffmpeg = os.path.join(os.getcwd(), "ffmpeg.exe")
        if os.path.isfile(local_ffmpeg):
            return local_ffmpeg

        # 4. 在系统 PATH 中查找（使用 where 命令）
        try:
            cmd = ["where", "ffmpeg"] if os.name == 'nt' else ["which", "ffmpeg"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip().split('\n')[0]
        except Exception:
            pass

        # 5. 直接检查系统 PATH 环境变量中的路径
        try:
            path_env = os.environ.get("PATH", "")
            paths = path_env.split(os.pathsep)
            for path in paths:
                ffmpeg_path = os.path.join(path, "ffmpeg.exe")
                if os.path.isfile(ffmpeg_path):
                    return ffmpeg_path
        except Exception:
            pass

        return ""

    def get_video_info(self, input_path: str) -> Optional[VideoInfo]:
        """
        获取视频信息

        Args:
            input_path: 视频文件路径

        Returns:
            视频信息，失败返回None
        """
        cmd = [
            self.ffprobe_path, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,duration,r_frame_rate,codec_name,nb_frames",
            "-of", "csv=p=0",
            input_path
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                check=True, timeout=30
            )
            parts = result.stdout.strip().split(',')
            if len(parts) >= 5:
                # 解析帧率
                fps_parts = parts[3].split('/')
                if len(fps_parts) == 2:
                    fps = float(fps_parts[0]) / float(fps_parts[1])
                else:
                    fps = float(fps_parts[0])

                # 解析时长
                duration_str = parts[2]
                duration = float(duration_str) if duration_str != 'N/A' else 0

                # 解析总帧数
                total_frames = 0
                if len(parts) >= 6 and parts[5] != 'N/A':
                    try:
                        total_frames = int(parts[5])
                    except ValueError:
                        pass
                if total_frames == 0 and duration > 0:
                    total_frames = int(duration * fps)

                return VideoInfo(
                    width=int(parts[0]),
                    height=int(parts[1]),
                    duration=duration,
                    fps=fps,
                    total_frames=total_frames,
                    codec=parts[4]
                )
        except subprocess.TimeoutExpired:
            logger.error("获取视频信息超时")
        except subprocess.CalledProcessError as e:
            logger.error(f"获取视频信息失败: {e.stderr}")
        except Exception as e:
            logger.error(f"获取视频信息异常: {e}")
        return None

    def process_video(
        self,
        input_path: str,
        output_path: str,
        target_resolution: str,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> Tuple[bool, str]:
        """
        处理视频：添加黑边实现32像素对齐

        Args:
            input_path: 输入视频路径
            output_path: 输出视频路径
            target_resolution: 目标分辨率 ("360x640", "480x854", "720x1080")
            progress_callback: 进度回调函数(进度0.0-1.0, 状态信息)

        Returns:
            (处理是否成功, 错误信息)
        """
        # 检查输入文件
        if not os.path.exists(input_path):
            return False, f"输入文件不存在: {input_path}"

        # 获取分辨率配置
        spec = get_resolution_spec(target_resolution)
        orig_w = spec["width"]
        orig_h = spec["height"]
        target_w = spec["padded_width"]
        target_h = spec["padded_height"]
        pad_dir = spec["padding_side"]
        rotate_180 = spec["rotate_180"]

        # 构建FFmpeg命令
        cmd = [self.ffmpeg_path, "-y", "-i", input_path]

        # 视频滤镜
        filters = []

        # 1. 缩放到原始分辨率
        filters.append(f"scale={orig_w}:{orig_h}")

        # 2. 添加黑边
        if pad_dir:
            filters.append(f"pad={target_w}:{target_h}:0:0:black")

        # 3. 720x1080需要旋转180度
        if rotate_180:
            filters.append("rotate=PI")

        # 组合滤镜
        if filters:
            cmd.extend(["-vf", ",".join(filters)])

        # 编码参数
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-an",  # 无音频
            output_path
        ])

        if progress_callback:
            progress_callback(0.1, "开始处理视频...")

        try:
            popen_kwargs = {
                'stdout': subprocess.PIPE,
                'stderr': subprocess.PIPE,
                'universal_newlines': True
            }
            if sys.platform == 'win32':
                popen_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

            process = subprocess.Popen(cmd, **popen_kwargs)

            if progress_callback:
                progress_callback(0.5, "正在编码...")

            stdout, stderr = process.communicate(timeout=600)

            if process.returncode == 0:
                if progress_callback:
                    progress_callback(1.0, "处理完成")
                return True, ""
            else:
                return False, f"FFmpeg错误: {stderr}"

        except subprocess.TimeoutExpired:
            process.kill()
            return False, "视频处理超时（超过10分钟）"
        except Exception as e:
            return False, f"视频处理异常: {e}"

    def generate_ffmpeg_command(
        self,
        input_path: str,
        output_path: str,
        target_resolution: str
    ) -> str:
        """
        生成FFmpeg命令字符串（用于显示给用户）

        Args:
            input_path: 输入视频路径
            output_path: 输出视频路径
            target_resolution: 目标分辨率

        Returns:
            FFmpeg命令字符串
        """
        spec = get_resolution_spec(target_resolution)
        orig_w = spec["width"]
        orig_h = spec["height"]
        target_w = spec["padded_width"]
        target_h = spec["padded_height"]
        pad_dir = spec["padding_side"]
        rotate_180 = spec["rotate_180"]

        filters = [f"scale={orig_w}:{orig_h}"]

        if pad_dir:
            filters.append(f"pad={target_w}:{target_h}:0:0:black")

        if rotate_180:
            filters.append("rotate=PI")

        filter_str = ",".join(filters)

        return (f'ffmpeg -i "{input_path}" -vf "{filter_str}" '
                f'-c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p '
                f'-an "{output_path}"')

    def get_resolution_info(self, resolution: str) -> Dict[str, Any]:
        """
        获取分辨率处理信息

        Args:
            resolution: 分辨率字符串

        Returns:
            包含原始和目标分辨率信息的字典
        """
        spec = get_resolution_spec(resolution)

        info = {
            "original": f"{spec['width']}x{spec['height']}",
            "target": f"{spec['padded_width']}x{spec['padded_height']}",
            "pad_direction": spec["padding_side"],
            "pad_pixels": spec.get("padding_amount", 0),
            "needs_rotation": spec["rotate_180"],
            "description": spec.get("description", "")
        }

        return info
