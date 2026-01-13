"""
文件操作工具函数
"""
import os
import sys
from typing import Optional, Tuple

from config.constants import SUPPORTED_VIDEO_FORMATS, SUPPORTED_IMAGE_FORMATS


def get_relative_path(base_dir: str, file_path: str) -> str:
    """
    获取相对于基础目录的相对路径

    Args:
        base_dir: 基础目录
        file_path: 文件完整路径

    Returns:
        相对路径
    """
    try:
        return os.path.relpath(file_path, base_dir)
    except ValueError:
        # 在不同驱动器时返回原路径
        return file_path


def get_absolute_path(base_dir: str, rel_path: str) -> str:
    """
    将相对路径转换为绝对路径

    Args:
        base_dir: 基础目录
        rel_path: 相对路径

    Returns:
        绝对路径
    """
    if os.path.isabs(rel_path):
        return rel_path
    return os.path.normpath(os.path.join(base_dir, rel_path))


def ensure_directory(dir_path: str) -> bool:
    """
    确保目录存在，不存在则创建

    Args:
        dir_path: 目录路径

    Returns:
        是否成功
    """
    try:
        os.makedirs(dir_path, exist_ok=True)
        return True
    except Exception:
        return False


def is_valid_video_file(file_path: str, check_exists: bool = True) -> bool:
    """
    检查是否是有效的视频文件

    Args:
        file_path: 文件路径
        check_exists: 是否检查文件存在

    Returns:
        是否有效
    """
    if check_exists and not os.path.exists(file_path):
        return False

    ext = os.path.splitext(file_path)[1].lower()
    return ext in SUPPORTED_VIDEO_FORMATS


def is_valid_image_file(file_path: str, check_exists: bool = True) -> bool:
    """
    检查是否是有效的图片文件

    Args:
        file_path: 文件路径
        check_exists: 是否检查文件存在

    Returns:
        是否有效
    """
    if check_exists and not os.path.exists(file_path):
        return False

    ext = os.path.splitext(file_path)[1].lower()
    return ext in SUPPORTED_IMAGE_FORMATS


def get_file_extension(file_path: str) -> str:
    """获取文件扩展名（小写）"""
    return os.path.splitext(file_path)[1].lower()


def get_file_size(file_path: str) -> int:
    """获取文件大小（字节）"""
    try:
        return os.path.getsize(file_path)
    except OSError:
        return 0


def format_file_size(size_bytes: int) -> str:
    """格式化文件大小为可读字符串"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def format_duration_us(duration_us: int) -> str:
    """
    格式化微秒时长为可读字符串

    Args:
        duration_us: 微秒数

    Returns:
        格式化字符串，如 "5.0秒"
    """
    seconds = duration_us / 1_000_000
    if seconds >= 1:
        return f"{seconds:.1f}秒"
    else:
        ms = duration_us / 1000
        return f"{ms:.0f}毫秒"


def parse_duration_to_us(duration_str: str) -> Optional[int]:
    """
    解析时长字符串为微秒

    Args:
        duration_str: 时长字符串，如 "5秒" 或 "500毫秒" 或纯数字

    Returns:
        微秒数，解析失败返回None
    """
    try:
        duration_str = duration_str.strip()

        if duration_str.endswith('秒'):
            value = float(duration_str[:-1])
            return int(value * 1_000_000)
        elif duration_str.endswith('毫秒'):
            value = float(duration_str[:-2])
            return int(value * 1000)
        elif duration_str.endswith('us') or duration_str.endswith('微秒'):
            value = float(duration_str.replace('us', '').replace('微秒', ''))
            return int(value)
        else:
            # 纯数字，假设为微秒
            return int(float(duration_str))
    except (ValueError, AttributeError):
        return None


def get_video_filter() -> str:
    """获取视频文件过滤器字符串（用于文件对话框）"""
    exts = " ".join(f"*{ext}" for ext in SUPPORTED_VIDEO_FORMATS)
    return f"视频文件 ({exts})"


def get_image_filter() -> str:
    """获取图片文件过滤器字符串（用于文件对话框）"""
    exts = " ".join(f"*{ext}" for ext in SUPPORTED_IMAGE_FORMATS)
    return f"图片文件 ({exts})"


def get_json_filter() -> str:
    """获取JSON文件过滤器字符串"""
    return "JSON文件 (*.json)"


def get_all_files_filter() -> str:
    """获取所有文件过滤器字符串"""
    return "所有文件 (*.*)"


def get_app_dir() -> str:
    """
    获取应用程序所在目录（支持 Nuitka/PyInstaller 打包）

    Returns:
        应用程序所在目录的绝对路径
    """
    if getattr(sys, 'frozen', False):
        # Nuitka/PyInstaller 打包后，sys.executable 指向打包的 exe
        return os.path.dirname(sys.executable)
    else:
        # 开发环境，返回项目根目录
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
