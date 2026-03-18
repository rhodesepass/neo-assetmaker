"""
集中式样式常量与主题辅助函数

所有 UI 组件引用此模块的颜色/字体/间距常量，
确保主题切换时视觉风格统一。
"""

from qfluentwidgets import isDarkTheme, themeColor, setCustomStyleSheet


# (light, dark) 元组

COLOR_TEXT_PRIMARY = ("#333333", "#eeeeee")
COLOR_TEXT_SECONDARY = ("#666666", "#aaaaaa")
COLOR_TEXT_MUTED = ("#999999", "#777777")

COLOR_BG_SURFACE = ("#f8f9fa", "#2d2d2d")
COLOR_BG_INSET = ("#ffffff", "#1e1e1e")
COLOR_BG_ELEVATED = ("#ffffff", "#333333")

COLOR_BORDER = ("#dddddd", "#555555")

COLOR_SUCCESS = ("#4CAF50", "#66BB6A")
COLOR_ERROR = ("#dc3545", "#e74c3c")
COLOR_WARNING = ("#ff9800", "#ffa726")

COLOR_ACCENT = ("#ff6b8b", "#ff6b8b")  # 主题强调色

# 预览区域（始终深色，参考剪映/CapCut）
COLOR_PREVIEW_BG = ("#1a1a1a", "#0a0a0a")
COLOR_PREVIEW_TEXT = ("#888888", "#666666")

SPACING_SM = 8
SPACING_MD = 12
SPACING_LG = 16


def pick(color_pair: tuple[str, str]) -> str:
    """根据当前主题选择颜色值。

    Parameters
    ----------
    color_pair : tuple[str, str]
        (light_value, dark_value)
    """
    return color_pair[1] if isDarkTheme() else color_pair[0]


def get_accent_color() -> str:
    """动态获取当前主题强调色"""
    return themeColor().name()


def apply_themed_style(widget, light_qss: str, dark_qss: str) -> None:
    """对任意 QWidget 应用主题感知样式（自动跟随切换）。

    内部调用 qfluentwidgets.setCustomStyleSheet，确保主题变更时
    DirtyStyleSheetWatcher 自动刷新。
    """
    setCustomStyleSheet(widget, light_qss, dark_qss)
