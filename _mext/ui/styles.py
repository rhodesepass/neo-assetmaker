"""_mext 扩展模块专用样式常量。

引用 gui/styles.py 的公共颜色/辅助函数，并定义
素材卡片、列表、间距等 _mext 专有尺寸常量。
"""

from __future__ import annotations

# 将主应用样式辅助函数重新导出，方便 _mext 内部直接 import
from gui.styles import (  # noqa: F401
    COLOR_ACCENT,
    COLOR_BG_ELEVATED,
    COLOR_BG_INSET,
    COLOR_BG_SURFACE,
    COLOR_BORDER,
    COLOR_ERROR,
    COLOR_SUCCESS,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
    apply_themed_style,
    pick,
)

# ── 素材卡片尺寸 ────────────────────────────────────────────
# 与 _mext/core/constants.py 中的 MATERIAL_CARD_WIDTH/HEIGHT 保持一致

CARD_WIDTH: int = 220
CARD_HEIGHT: int = 280
CARD_IMAGE_HEIGHT: int = 140   # 卡片顶部预览图高度（≈ 63% 卡片高）
CARD_BORDER_RADIUS: int = 8

# ── 通用间距 ────────────────────────────────────────────────

SPACING_XS: int = 4
SPACING_SM: int = 8
SPACING_MD: int = 12
SPACING_LG: int = 16
SPACING_XL: int = 24

# ── FlowLayout 卡片网格间距 ──────────────────────────────────

GRID_H_SPACING: int = 12
GRID_V_SPACING: int = 12

# ── 侧边过滤面板宽度 ─────────────────────────────────────────

FILTER_PANEL_WIDTH: int = 200

# ── 排序/通用 ComboBox 宽度 ──────────────────────────────────

COMBO_WIDTH_SM: int = 120      # 小型（如并发数，只有几个数字选项）
COMBO_WIDTH_MD: int = 150      # 中型（如排序方式）
COMBO_WIDTH_LG: int = 200      # 标准（与主应用统一）

# ── 卡片选中态颜色（用于 USB 设备卡片） ─────────────────────
# themeColor() 动态获取，这里只作 fallback

COLOR_SELECTION_BORDER = ("#ff6b8b", "#ff8fa3")   # (light, dark)

# ── 占位图颜色（替代硬编码 lightGray） ──────────────────────

COLOR_PLACEHOLDER_BG = ("#e0e0e0", "#3a3a3a")    # (light, dark)
COLOR_PLACEHOLDER_FG = ("#aaaaaa", "#666666")    # (light, dark)

# ── 画廊卡片 (Gallery / Waterfall) ─────────────────────────

GALLERY_CARD_MIN_WIDTH: int = 240
GALLERY_CARD_MAX_WIDTH: int = 380
GALLERY_GRID_SPACING: int = 16
GALLERY_CARD_BORDER_RADIUS: int = 12

# ── 头像尺寸 ──────────────────────────────────────────────

AVATAR_SM: int = 24     # 卡片内小头像
AVATAR_MD: int = 36     # 评论区头像
AVATAR_LG: int = 48     # 详情页创作者头像

# ── 详情页 ────────────────────────────────────────────────

DETAIL_MAX_WIDTH: int = 1200
DETAIL_IMAGE_MAX_HEIGHT: int = 600
DETAIL_SIDEBAR_WIDTH: int = 320

# ── Hover 遮罩颜色 ────────────────────────────────────────

COLOR_HOVER_OVERLAY = ("rgba(0,0,0,0.4)", "rgba(0,0,0,0.5)")

# ── 评论区 ──────────────────────────────────────────────

COMMENT_INPUT_MIN_HEIGHT: int = 60
COMMENT_INPUT_MAX_HEIGHT: int = 120
COMMENT_BUBBLE_PADDING: int = 12

# ── 创作者页 ────────────────────────────────────────────

CREATOR_AVATAR_XL: int = 80
CREATOR_HEADER_HEIGHT: int = 200

# ── 精选区 ──────────────────────────────────────────────

FEATURED_BANNER_HEIGHT: int = 200
FEATURED_CARD_WIDTH: int = 280

# ── 相关素材 ────────────────────────────────────────────

RELATED_SECTION_HEIGHT: int = 280
RELATED_CARD_WIDTH: int = 200
