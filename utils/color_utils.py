"""
颜色处理工具函数
"""
import re
from typing import Tuple, Optional


# 颜色格式正则表达式
COLOR_HEX_PATTERN = re.compile(r'^#([0-9a-fA-F]{6})$')
COLOR_HEX_ALPHA_PATTERN = re.compile(r'^#([0-9a-fA-F]{8})$')


def is_valid_hex_color(color: str) -> bool:
    """
    检查是否是有效的十六进制颜色（#RRGGBB）

    Args:
        color: 颜色字符串

    Returns:
        是否有效
    """
    if not color:
        return False
    return bool(COLOR_HEX_PATTERN.match(color))


def is_valid_hex_color_with_alpha(color: str) -> bool:
    """
    检查是否是有效的带透明度的十六进制颜色（#AARRGGBB）

    Args:
        color: 颜色字符串

    Returns:
        是否有效
    """
    if not color:
        return False
    return bool(COLOR_HEX_ALPHA_PATTERN.match(color))


def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """
    将十六进制颜色转换为RGB元组

    Args:
        hex_color: 十六进制颜色字符串（#RRGGBB）

    Returns:
        (R, G, B) 元组，每个值为0-255

    Raises:
        ValueError: 颜色格式无效
    """
    match = COLOR_HEX_PATTERN.match(hex_color)
    if not match:
        raise ValueError(f"无效的十六进制颜色: {hex_color}")

    hex_str = match.group(1)
    r = int(hex_str[0:2], 16)
    g = int(hex_str[2:4], 16)
    b = int(hex_str[4:6], 16)
    return (r, g, b)


def hex_to_rgba(hex_color: str) -> Tuple[int, int, int, int]:
    """
    将带透明度的十六进制颜色转换为RGBA元组

    Args:
        hex_color: 十六进制颜色字符串（#AARRGGBB）

    Returns:
        (R, G, B, A) 元组，每个值为0-255

    Raises:
        ValueError: 颜色格式无效
    """
    match = COLOR_HEX_ALPHA_PATTERN.match(hex_color)
    if not match:
        raise ValueError(f"无效的十六进制颜色: {hex_color}")

    hex_str = match.group(1)
    a = int(hex_str[0:2], 16)
    r = int(hex_str[2:4], 16)
    g = int(hex_str[4:6], 16)
    b = int(hex_str[6:8], 16)
    return (r, g, b, a)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    """
    将RGB值转换为十六进制颜色字符串

    Args:
        r: 红色值 (0-255)
        g: 绿色值 (0-255)
        b: 蓝色值 (0-255)

    Returns:
        十六进制颜色字符串 (#RRGGBB)
    """
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def rgba_to_hex(r: int, g: int, b: int, a: int = 255) -> str:
    """
    将RGBA值转换为带透明度的十六进制颜色字符串

    Args:
        r: 红色值 (0-255)
        g: 绿色值 (0-255)
        b: 蓝色值 (0-255)
        a: 透明度值 (0-255)

    Returns:
        十六进制颜色字符串 (#AARRGGBB)
    """
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))
    a = max(0, min(255, a))
    return f"#{a:02x}{r:02x}{g:02x}{b:02x}"


def normalize_color(color: str, default: str = "#000000") -> str:
    """
    规范化颜色值

    Args:
        color: 颜色字符串
        default: 默认颜色（当输入无效时返回）

    Returns:
        规范化后的颜色字符串（#RRGGBB）
    """
    if not color:
        return default

    color = color.strip()

    # 尝试匹配标准格式
    if COLOR_HEX_PATTERN.match(color):
        return color.lower()

    # 尝试不带#的格式
    if len(color) == 6:
        try:
            int(color, 16)
            return f"#{color.lower()}"
        except ValueError:
            pass

    return default


def get_contrast_color(hex_color: str) -> str:
    """
    获取对比色（用于确保文本在背景上可见）

    Args:
        hex_color: 背景色（#RRGGBB）

    Returns:
        对比色（黑色或白色）
    """
    try:
        r, g, b = hex_to_rgb(hex_color)
        # 计算亮度
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return "#000000" if luminance > 0.5 else "#ffffff"
    except ValueError:
        return "#000000"
