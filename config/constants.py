"""
常量定义 - 分辨率、支持格式等
"""
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, List

# ===== 应用信息 =====
APP_NAME = "明日方舟通行证素材制作器"
APP_VERSION = "1.5.7"

# ===== 基础尺寸配置 =====
SCREEN_WIDTH = 360
SCREEN_HEIGHT = 640

LOGO_WIDTH = 256
LOGO_HEIGHT = 256

VIDEO_WIDTH = 384
VIDEO_HEIGHT = 640

# ===== 分辨率规范配置 =====
RESOLUTION_SPECS: Dict[str, Dict[str, Any]] = {
    "360x640": {
        "width": 360,
        "height": 640,
        "padded_width": 384,
        "padded_height": 640,
        "padding_side": "right",  # 补右边黑边
        "padding_amount": 24,
        "rotate_180": False,
        "description": "360x640 (对齐后384x640, 右边+24px黑边)"
    },
    "480x854": {
        "width": 480,
        "height": 854,
        "padded_width": 480,
        "padded_height": 864,
        "padding_side": "bottom",  # 补下边黑边
        "padding_amount": 10,
        "rotate_180": False,
        "description": "480x854 (对齐后480x864, 底部+10px黑边)"
    },
    "720x1080": {
        "width": 720,
        "height": 1080,
        "padded_width": 720,
        "padded_height": 1080,
        "padding_side": None,  # 无补边
        "padding_amount": 0,
        "rotate_180": False,
        "description": "720x1080 (无黑边)"
    }
}

# ===== 支持的文件格式 =====
SUPPORTED_VIDEO_FORMATS = ('.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv')
SUPPORTED_IMAGE_FORMATS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp')

# ===== 时间单位换算 =====
# 项目中时间统一采用微秒（microseconds）
# 1秒 = 1,000,000微秒
MICROSECONDS_PER_SECOND = 1_000_000

# ===== 默认值 =====
DEFAULT_TRANSITION_DURATION = 500000  # 0.5秒
DEFAULT_INTRO_DURATION = 5000000  # 5秒
DEFAULT_APPEAR_TIME = 100000  # 0.1秒
DEFAULT_BACKGROUND_COLOR = "#000000"

# ===== 过渡效果类型 =====
TRANSITION_TYPES = ["none", "fade", "move", "swipe"]

# ===== 叠加UI类型 =====
OVERLAY_TYPES = ["none", "arknights", "image"]

# ===== Arknights叠加UI图片尺寸 =====
ARK_CLASS_ICON_SIZE = (50, 50)    # 职业图标尺寸
ARK_LOGO_SIZE = (75, 35)          # Logo尺寸

# ===== 职业图标预设 =====
OPERATOR_CLASS_PRESETS = {
    "先锋": "vanguard",
    "近卫": "guard",
    "重装": "defender",
    "狙击": "sniper",
    "术师": "caster",
    "医疗": "medic",
    "辅助": "supporter",
    "特种": "specialist"
}


def get_resolution_spec(resolution: str) -> Dict[str, Any]:
    """获取分辨率规格"""
    return RESOLUTION_SPECS.get(resolution, RESOLUTION_SPECS["360x640"])


def microseconds_to_seconds(us: int) -> float:
    """微秒转秒"""
    return us / MICROSECONDS_PER_SECOND


def seconds_to_microseconds(s: float) -> int:
    """秒转微秒"""
    return int(s * MICROSECONDS_PER_SECOND)


# ===== GitHub 更新配置 =====
GITHUB_OWNER = "rhodesepass"
GITHUB_REPO = "neo-assetmaker"
UPDATE_CHECK_INTERVAL_HOURS = 24


# ===== 多源更新配置 =====
# 参考: https://docs.python.org/3/library/concurrent.futures.html
# 使用 ThreadPoolExecutor + as_completed() 实现多源并发请求


class SourceType(Enum):
    """更新源类型"""
    GITHUB_API = "github_api"      # GitHub 官方 API
    GITHUB_PROXY = "github_proxy"  # GitHub 代理镜像


@dataclass
class UpdateSource:
    """更新源配置"""
    name: str                      # 源名称（用于日志和UI显示）
    url_template: str              # URL 模板，支持 {owner}, {repo}, {direct_url} 占位符
    source_type: SourceType        # 源类型
    priority: int                  # 优先级（数字越小优先级越高）
    timeout: float = 10.0          # 超时时间（秒）
    enabled: bool = True           # 是否启用


# API 源池 - 用于检查更新（竞速策略：同时请求所有源，取最快返回）
UPDATE_API_SOURCES: List[UpdateSource] = [
    UpdateSource(
        name="GitHub API",
        url_template="https://api.github.com/repos/{owner}/{repo}/releases/latest",
        source_type=SourceType.GITHUB_API,
        priority=1,
        timeout=10.0
    ),
    UpdateSource(
        name="ghproxy.cc",
        url_template="https://ghproxy.cc/https://api.github.com/repos/{owner}/{repo}/releases/latest",
        source_type=SourceType.GITHUB_PROXY,
        priority=2,
        timeout=15.0
    ),
    UpdateSource(
        name="gh.idayer.com",
        url_template="https://gh.idayer.com/https://api.github.com/repos/{owner}/{repo}/releases/latest",
        source_type=SourceType.GITHUB_PROXY,
        priority=3,
        timeout=15.0
    ),
]

# 下载源池 - 用于下载安装包（故障转移策略：按优先级依次尝试）
DOWNLOAD_SOURCES: List[UpdateSource] = [
    UpdateSource(
        name="GitHub Releases",
        url_template="{direct_url}",
        source_type=SourceType.GITHUB_API,
        priority=1,
        timeout=60.0
    ),
    UpdateSource(
        name="ghproxy.cc",
        url_template="https://ghproxy.cc/{direct_url}",
        source_type=SourceType.GITHUB_PROXY,
        priority=2,
        timeout=120.0
    ),
]
