"""
叠加层动画渲染器 - 基于固件 drm_app_neo/src/overlay/opinfo.c 实现

动画效果包括：
- 文字打字机效果
- EINK电子墨水效果（条码、职业图标）
- 颜色渐晕效果（右下角）
- Logo淡入效果
- 进度条/分割线贝塞尔动画
- 箭头循环动画
- 入场滑动动画

参考固件源码:
- drm_app_neo/src/overlay/opinfo.c (776行)
- drm_app_neo/src/config.h (时序常量)

数据驱动架构:
- 所有常量从 FirmwareConfig 读取
- 支持从 JSON 配置文件加载
- 向后兼容：无参数时使用默认配置
"""
import logging
from typing import Optional, Tuple, Dict, TYPE_CHECKING
from enum import Enum
from dataclasses import dataclass

import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

from config.epconfig import ArknightsOverlayOptions
from core.transition_renderer import cubic_bezier, ease_in_out_bezier

if TYPE_CHECKING:
    from config.firmware_config import FirmwareConfig

logger = logging.getLogger(__name__)


# ==================== 动画时序常量 (基于固件 config.h) ====================
# 注意: 这些模块级常量保留用于向后兼容
# 新代码应使用 FirmwareConfig 通过 ConfigManager 获取配置
# 参考: drm_app_neo/src/config.h:80-113

# 帧率
ANIMATION_FPS = 50  # 50fps = 20ms per frame

# 文字打字机效果 (opinfo.c:167-203)
NAME_START_FRAME = 30
NAME_FRAME_PER_CHAR = 3
CODE_START_FRAME = 40
CODE_FRAME_PER_CHAR = 3
STAFF_TEXT_START_FRAME = 40
STAFF_TEXT_FRAME_PER_CHAR = 3
AUX_TEXT_START_FRAME = 50
AUX_TEXT_FRAME_PER_CHAR = 2

# EINK效果 (opinfo.c:207-223, 391-456)
BARCODE_START_FRAME = 30
BARCODE_FRAME_PER_STATE = 15
CLASSICON_START_FRAME = 60
CLASSICON_FRAME_PER_STATE = 15

# 颜色渐晕 (opinfo.c:139-152, 225-234)
COLOR_FADE_START_FRAME = 15
COLOR_FADE_VALUE_PER_FRAME = 10
COLOR_FADE_END_VALUE = 192

# Logo淡入
LOGO_FADE_START_FRAME = 30
LOGO_FADE_VALUE_PER_FRAME = 5

# 进度条/分割线 (opinfo.c:251-271)
AK_BAR_START_FRAME = 100
AK_BAR_FRAME_COUNT = 40
LINE_UPPER_START_FRAME = 80
LINE_LOWER_START_FRAME = 90
LINE_FRAME_COUNT = 40
LINE_WIDTH = 280

# 箭头动画
ARROW_Y_INCR_PER_FRAME = 1

# 入场动画 (opinfo.c:727-733)
ENTRY_ANIMATION_FRAMES = 50  # 1秒 @ 50fps

# UI布局常量 (基于固件 config.h)
OVERLAY_WIDTH = 360
OVERLAY_HEIGHT = 640
BTM_INFO_OFFSET_X = 70
OPNAME_OFFSET_Y = 415
UPPERLINE_OFFSET_Y = 455
LOWERLINE_OFFSET_Y = 475
OPCODE_OFFSET_Y = 457
STAFF_TEXT_OFFSET_Y = 480
CLASS_ICON_OFFSET_Y = 525
AK_BAR_OFFSET_Y = 578
AUX_TEXT_OFFSET_Y = 592
BARCODE_OFFSET_X = 1
BARCODE_OFFSET_Y = 450
BARCODE_WIDTH = 50
BARCODE_HEIGHT = 180
TOP_RIGHT_ARROW_OFFSET_Y = 100


class EinkState(Enum):
    """
    EINK动画状态 (opinfo.c:92-99)

    固件定义:
    typedef enum {
        ANIMATION_EINK_FIRST_BLACK,
        ANIMATION_EINK_FIRST_WHITE,
        ANIMATION_EINK_SECOND_BLACK,
        ANIMATION_EINK_SECOND_WHITE,
        ANIMATION_EINK_IDLE,
        ANIMATION_EINK_CONTENT
    }
    """
    FIRST_BLACK = 0    # 第一次黑
    FIRST_WHITE = 1    # 第一次白
    SECOND_BLACK = 2   # 第二次黑
    SECOND_WHITE = 3   # 第二次白
    IDLE = 4           # 空闲
    CONTENT = 5        # 显示内容


@dataclass
class AnimationState:
    """动画状态"""
    frame_counter: int = 0

    # 文字打字机进度 (已显示字符数)
    name_chars: int = 0
    code_chars: int = 0
    staff_chars: int = 0
    aux_chars: int = 0

    # EINK状态
    barcode_state: EinkState = EinkState.IDLE
    classicon_state: EinkState = EinkState.IDLE

    # 颜色渐晕半径
    color_fade_radius: int = 0

    # Logo透明度
    logo_alpha: int = 0

    # 进度条/分割线宽度
    ak_bar_width: int = 0
    upper_line_width: int = 0
    lower_line_width: int = 0

    # 箭头Y偏移（循环）
    arrow_y: int = 30

    # 入场动画进度
    entry_progress: float = 0.0
    entry_y_offset: int = 640  # 默认值，会在 reset 时根据配置更新


class OverlayAnimator:
    """
    叠加层动画渲染器

    完全基于固件 opinfo.c 的实现逻辑。
    支持数据驱动架构，所有常量从 FirmwareConfig 读取。

    Args:
        firmware_config: 固件配置，None 表示使用默认配置
    """

    def __init__(self, firmware_config: "FirmwareConfig" = None):
        # 加载配置
        if firmware_config is None:
            from config.config_manager import ConfigManager
            firmware_config = ConfigManager.get_firmware()
        self._config = firmware_config

        self._state = AnimationState()
        self._font = cv2.FONT_HERSHEY_SIMPLEX if HAS_CV2 else None
        self._bezier_values: Dict[str, list] = {}
        self._precompute_bezier_values()

    def _precompute_bezier_values(self):
        """
        预计算贝塞尔曲线值

        固件实现 (opinfo.c:691-703):
        使用 ease-in-out (0.42, 0) → (0.58, 1) 曲线
        """
        ak_bar_frame_count = self._config.ak_bar_frame_count
        line_frame_count = self._config.line_frame_count
        line_width = self._config.line_width

        # AK进度条贝塞尔值
        self._bezier_values['ak_bar'] = []
        for i in range(ak_bar_frame_count + 1):
            t = i / ak_bar_frame_count
            value = ease_in_out_bezier(t)
            self._bezier_values['ak_bar'].append(int(line_width * value))

        # 分割线贝塞尔值
        self._bezier_values['line'] = []
        for i in range(line_frame_count + 1):
            t = i / line_frame_count
            value = ease_in_out_bezier(t)
            self._bezier_values['line'].append(int(line_width * value))

    def reset(self):
        """重置动画状态"""
        self._state = AnimationState()
        self._state.entry_y_offset = self._config.overlay_height

    def start_entry_animation(self):
        """开始入场动画"""
        self._state.entry_progress = 0.0
        self._state.entry_y_offset = self._config.overlay_height

    def update(self):
        """
        更新一帧动画

        对应固件 arknights_overlay_worker (opinfo.c:155-561)
        """
        self._state.frame_counter += 1
        frame = self._state.frame_counter

        # 更新入场动画 (opinfo.c:727-733)
        if self._state.entry_progress < 1.0:
            entry_frames = self._config.entry_animation_frames
            overlay_height = self._config.overlay_height
            self._state.entry_progress = min(1.0, frame / entry_frames)
            ease = ease_in_out_bezier(self._state.entry_progress)
            self._state.entry_y_offset = int(overlay_height * (1 - ease))

        # 更新文字打字机 (opinfo.c:167-203)
        self._update_typewriter(frame)

        # 更新EINK效果 (opinfo.c:207-223)
        self._update_eink(frame)

        # 更新颜色渐晕 (opinfo.c:225-234)
        self._update_color_fade(frame)

        # 更新Logo淡入
        self._update_logo_fade(frame)

        # 更新进度条/分割线 (opinfo.c:251-271)
        self._update_bars_and_lines(frame)

        # 更新箭头循环 (opinfo.c:522-556)
        self._update_arrow()

    def _update_typewriter(self, frame: int):
        """
        更新文字打字机效果

        固件实现 (opinfo.c:167-203):
        if(data->curr_frame >= OVERLAY_ANIMATION_OPINFO_NAME_START_FRAME &&
           data->operator_name_cpidx != data->operator_name_cpcnt){
            if(data->curr_frame % OVERLAY_ANIMATION_OPINFO_NAME_FRAME_PER_CODEPOINT == 0){
                data->operator_name_cpidx++;
            }
        }
        """
        cfg = self._config

        # Name
        if frame >= cfg.name_start_frame:
            chars = (frame - cfg.name_start_frame) // cfg.name_frame_per_char + 1
            self._state.name_chars = chars

        # Code
        if frame >= cfg.code_start_frame:
            chars = (frame - cfg.code_start_frame) // cfg.code_frame_per_char + 1
            self._state.code_chars = chars

        # Staff
        if frame >= cfg.staff_start_frame:
            chars = (frame - cfg.staff_start_frame) // cfg.staff_frame_per_char + 1
            self._state.staff_chars = chars

        # Aux
        if frame >= cfg.aux_start_frame:
            chars = (frame - cfg.aux_start_frame) // cfg.aux_frame_per_char + 1
            self._state.aux_chars = chars

    def _update_eink(self, frame: int):
        """
        更新EINK电子墨水效果

        固件实现 (opinfo.c:207-223):
        5状态循环: FIRST_BLACK → FIRST_WHITE → SECOND_BLACK → SECOND_WHITE → CONTENT
        每状态持续 FRAME_PER_STATE 帧
        """
        cfg = self._config

        # Barcode EINK
        # 固件实现 (opinfo.c:207-213):
        # if(data->barcode_state != ANIMATION_EINK_CONTENT){
        #     if(data->curr_frame % FRAME_PER_STATE == 0){
        #         data->barcode_state++;  // 递增: 0→1→2→3→4→5
        #     }
        # }
        # 5状态 × 15帧 = 75帧 (1.5秒)
        if frame >= cfg.barcode_start_frame:
            eink_frame = frame - cfg.barcode_start_frame
            state_index = eink_frame // cfg.barcode_frame_per_state
            if state_index == 0:
                self._state.barcode_state = EinkState.FIRST_BLACK
            elif state_index == 1:
                self._state.barcode_state = EinkState.FIRST_WHITE
            elif state_index == 2:
                self._state.barcode_state = EinkState.SECOND_BLACK
            elif state_index == 3:
                self._state.barcode_state = EinkState.SECOND_WHITE
            elif state_index == 4:
                self._state.barcode_state = EinkState.IDLE  # 不跳过IDLE状态
            else:
                self._state.barcode_state = EinkState.CONTENT
        else:
            self._state.barcode_state = EinkState.IDLE

        # Class Icon EINK
        # 同样需要5状态循环
        if frame >= cfg.classicon_start_frame:
            eink_frame = frame - cfg.classicon_start_frame
            state_index = eink_frame // cfg.classicon_frame_per_state
            if state_index == 0:
                self._state.classicon_state = EinkState.FIRST_BLACK
            elif state_index == 1:
                self._state.classicon_state = EinkState.FIRST_WHITE
            elif state_index == 2:
                self._state.classicon_state = EinkState.SECOND_BLACK
            elif state_index == 3:
                self._state.classicon_state = EinkState.SECOND_WHITE
            elif state_index == 4:
                self._state.classicon_state = EinkState.IDLE  # 不跳过IDLE状态
            else:
                self._state.classicon_state = EinkState.CONTENT
        else:
            self._state.classicon_state = EinkState.IDLE

    def _update_color_fade(self, frame: int):
        """
        更新颜色渐晕效果

        固件实现 (opinfo.c:225-234):
        if(data->curr_frame >= COLOR_FADE_START_FRAME &&
           data->color_fade_value < COLOR_FADE_END_VALUE){
            data->color_fade_value += COLOR_FADE_VALUE_PER_FRAME;
        }
        """
        cfg = self._config
        if frame >= cfg.color_fade_start_frame:
            fade_frame = frame - cfg.color_fade_start_frame
            radius = fade_frame * cfg.color_fade_value_per_frame
            self._state.color_fade_radius = min(radius, cfg.color_fade_end_value)

    def _update_logo_fade(self, frame: int):
        """更新Logo淡入效果"""
        cfg = self._config
        if frame >= cfg.logo_fade_start_frame:
            fade_frame = frame - cfg.logo_fade_start_frame
            alpha = fade_frame * cfg.logo_fade_value_per_frame
            self._state.logo_alpha = min(alpha, 255)

    def _update_bars_and_lines(self, frame: int):
        """
        更新进度条和分割线

        固件实现 (opinfo.c:251-271):
        使用预计算的贝塞尔值
        """
        cfg = self._config

        # AK进度条
        if frame >= cfg.ak_bar_start_frame:
            bar_frame = frame - cfg.ak_bar_start_frame
            if bar_frame < len(self._bezier_values['ak_bar']):
                self._state.ak_bar_width = self._bezier_values['ak_bar'][bar_frame]
            else:
                self._state.ak_bar_width = cfg.line_width

        # 上分割线
        if frame >= cfg.line_upper_start_frame:
            line_frame = frame - cfg.line_upper_start_frame
            if line_frame < len(self._bezier_values['line']):
                self._state.upper_line_width = self._bezier_values['line'][line_frame]
            else:
                self._state.upper_line_width = cfg.line_width

        # 下分割线
        if frame >= cfg.line_lower_start_frame:
            line_frame = frame - cfg.line_lower_start_frame
            if line_frame < len(self._bezier_values['line']):
                self._state.lower_line_width = self._bezier_values['line'][line_frame]
            else:
                self._state.lower_line_width = cfg.line_width

    def _update_arrow(self):
        """
        更新箭头循环动画

        固件实现 (opinfo.c:522-556):
        data->arrow_y_value -= ARROW_Y_INCR_PER_FRAME;
        if(data->arrow_y_value <= 0) data->arrow_y_value = asset_h;
        """
        self._state.arrow_y -= self._config.arrow_y_incr
        if self._state.arrow_y <= 0:
            self._state.arrow_y = 30  # 重置到底部

    def render(
        self,
        frame: np.ndarray,
        options: Optional[ArknightsOverlayOptions],
        apply_entry_offset: bool = True
    ) -> np.ndarray:
        """
        渲染带动画的叠加层

        对应固件 arknights_overlay_worker 的绘制部分 (opinfo.c:273-561)
        """
        if not HAS_CV2 or options is None:
            return frame

        result = frame.copy()
        h, w = result.shape[:2]

        # 计算Y偏移（入场动画）
        y_offset = self._state.entry_y_offset if apply_entry_offset else 0

        # 获取主题色
        color = self._hex_to_bgr(options.color)
        white = (255, 255, 255)
        black = (0, 0, 0)

        # === 渲染颜色渐晕（右下角）===
        if self._state.color_fade_radius > 0:
            self._render_color_fade(result, color)

        # === 渲染静态UI元素 ===
        self._render_static_ui(result, options, color, y_offset)

        # === 渲染文字（打字机效果）===
        self._render_typewriter_text(result, options, color, white, y_offset)

        # === 渲染EINK区域 ===
        self._render_eink_areas(result, options, color, white, black, y_offset)

        # === 渲染Logo（淡入）===
        if self._state.logo_alpha > 0:
            self._render_logo(result, options, y_offset)

        # === 渲染进度条和分割线 ===
        self._render_bars_and_lines(result, options, color, y_offset)

        # === 渲染箭头循环 ===
        self._render_arrow(result, color, y_offset)

        return result

    @staticmethod
    def _hex_to_bgr(hex_color: str) -> Tuple[int, int, int]:
        """将十六进制颜色转换为BGR格式"""
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 6:
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            return (b, g, r)
        return (0, 0, 0)

    def _render_color_fade(self, frame: np.ndarray, color: Tuple[int, int, int]):
        """
        渲染颜色渐晕（右下角径向渐变）

        固件实现 (opinfo.c:139-152):
        static void draw_color_fade(uint32_t* vaddr, int radius, uint32_t color){
            for(int x=0; x < radius; x++){
                for(int y=0; y < radius; y++){
                    if(x+y > radius - 2) break;
                    uint8_t alpha = 255 - ((x+y)*255 / radius);
                    int real_x = OVERLAY_WIDTH - x - 1;
                    int real_y = OVERLAY_HEIGHT - y - 1;
                    // 直接写入带alpha的像素
                    *((uint32_t*)(vaddr) + real_x + real_y * OVERLAY_WIDTH) =
                        (color & 0x00FFFFFF) | (alpha << 24);
                }
            }
        }
        """
        h, w = frame.shape[:2]
        radius = self._state.color_fade_radius

        # 固件是直接写入ARGB像素，我们需要模拟alpha混合
        for x in range(min(radius, w)):
            for y in range(min(radius, h)):
                if x + y > radius - 2:
                    break
                alpha = (255 - ((x + y) * 255 // radius)) / 255.0
                real_x = w - x - 1
                real_y = h - y - 1
                if 0 <= real_x < w and 0 <= real_y < h:
                    # 混合颜色
                    orig = frame[real_y, real_x].astype(float)
                    new_color = np.array(color, dtype=float)
                    frame[real_y, real_x] = (orig * (1 - alpha * 0.5) + new_color * alpha * 0.5).astype(np.uint8)

    def _render_static_ui(
        self,
        frame: np.ndarray,
        options: ArknightsOverlayOptions,
        color: Tuple[int, int, int],
        y_offset: int
    ):
        """渲染静态UI元素"""
        h, w = frame.shape[:2]

        # 顶部左矩形
        rect_height = 60
        rect_width = 300
        rect_y = 30 + y_offset
        if 0 < rect_y < h:
            cv2.rectangle(
                frame,
                (60, max(0, rect_y)),
                (min(w, 60 + rect_width), min(h, rect_y + rect_height)),
                (40, 40, 40), -1
            )

        # 左侧装饰线
        line_x = 10
        line_y1 = 100 + y_offset
        line_y2 = 550 + y_offset
        if line_y1 < h:
            cv2.line(frame, (line_x, max(0, line_y1)), (line_x, min(h, line_y2)), color, 3)

        # 角落装饰
        corner_size = 15
        corner_thickness = 2

        # 左上角
        if y_offset < h:
            cv2.line(frame, (0, max(0, y_offset + corner_size)), (0, max(0, y_offset)), color, corner_thickness)
            cv2.line(frame, (0, max(0, y_offset)), (corner_size, max(0, y_offset)), color, corner_thickness)

    def _render_typewriter_text(
        self,
        frame: np.ndarray,
        options: ArknightsOverlayOptions,
        color: Tuple[int, int, int],
        white: Tuple[int, int, int],
        y_offset: int
    ):
        """
        渲染打字机效果文字

        固件实现 (opinfo.c:326-388):
        使用 fbdraw_text_range 逐字符绘制
        """
        h, w = frame.shape[:2]
        cfg = self._config

        # 干员名
        if self._state.name_chars > 0:
            name = options.operator_name[:self._state.name_chars]
            name_y = cfg.opname_offset_y + y_offset
            if 0 < name_y < h:
                cv2.putText(frame, name, (cfg.btm_info_offset_x, name_y),
                           self._font, 1.2, white, 2, cv2.LINE_AA)

        # 干员代号
        if self._state.code_chars > 0:
            code = options.operator_code[:self._state.code_chars]
            code_y = cfg.opcode_offset_y + y_offset
            if 0 < code_y < h:
                cv2.putText(frame, code, (cfg.btm_info_offset_x, code_y),
                           self._font, 0.5, color, 1, cv2.LINE_AA)

        # Staff文字
        if self._state.staff_chars > 0:
            staff = options.staff_text[:self._state.staff_chars]
            staff_y = cfg.staff_text_offset_y + y_offset
            if 0 < staff_y < h:
                cv2.putText(frame, staff, (cfg.btm_info_offset_x, staff_y),
                           self._font, 0.4, white, 1, cv2.LINE_AA)

        # 辅助文字
        if self._state.aux_chars > 0:
            aux = options.aux_text[:self._state.aux_chars]
            aux_y = cfg.aux_text_offset_y + y_offset
            if 0 < aux_y < h:
                cv2.putText(frame, aux, (cfg.btm_info_offset_x, aux_y),
                           self._font, 0.35, white, 1, cv2.LINE_AA)

    def _render_eink_areas(
        self,
        frame: np.ndarray,
        options: ArknightsOverlayOptions,
        color: Tuple[int, int, int],
        white: Tuple[int, int, int],
        black: Tuple[int, int, int],
        y_offset: int
    ):
        """
        渲染EINK电子墨水效果区域

        固件实现 (opinfo.c:391-456):
        switch(data->barcode_state) {
            case ANIMATION_EINK_FIRST_BLACK:
                fbdraw_fill_rect(&fbdst, &dst_rect, 0xFF000000);
                break;
            case ANIMATION_EINK_FIRST_WHITE:
                fbdraw_fill_rect(&fbdst, &dst_rect, 0xFFFFFFFF);
                break;
            ...
            case ANIMATION_EINK_CONTENT:
                fbdraw_barcode_rot90(...);
                break;
        }
        """
        h, w = frame.shape[:2]
        cfg = self._config

        # 条码区域
        barcode_x = cfg.barcode_offset_x
        barcode_y = cfg.barcode_offset_y + y_offset
        barcode_w = cfg.barcode_width
        barcode_h = cfg.barcode_height

        if self._state.barcode_state != EinkState.IDLE and 0 < barcode_y < h:
            if self._state.barcode_state in [EinkState.FIRST_BLACK, EinkState.SECOND_BLACK]:
                cv2.rectangle(frame, (barcode_x, barcode_y),
                             (barcode_x + barcode_w, min(h, barcode_y + barcode_h)),
                             black, -1)
            elif self._state.barcode_state in [EinkState.FIRST_WHITE, EinkState.SECOND_WHITE]:
                cv2.rectangle(frame, (barcode_x, barcode_y),
                             (barcode_x + barcode_w, min(h, barcode_y + barcode_h)),
                             white, -1)
            elif self._state.barcode_state == EinkState.CONTENT:
                # 绘制条码
                self._draw_barcode(frame, barcode_x, barcode_y, barcode_w, barcode_h, white)

        # 职业图标区域
        icon_x = cfg.btm_info_offset_x
        icon_y = cfg.class_icon_offset_y + y_offset
        icon_size = cfg.layout.class_icon.width

        if self._state.classicon_state != EinkState.IDLE and 0 < icon_y < h:
            if self._state.classicon_state in [EinkState.FIRST_BLACK, EinkState.SECOND_BLACK]:
                cv2.rectangle(frame, (icon_x, icon_y),
                             (icon_x + icon_size, min(h, icon_y + icon_size)),
                             black, -1)
            elif self._state.classicon_state in [EinkState.FIRST_WHITE, EinkState.SECOND_WHITE]:
                cv2.rectangle(frame, (icon_x, icon_y),
                             (icon_x + icon_size, min(h, icon_y + icon_size)),
                             white, -1)
            elif self._state.classicon_state == EinkState.CONTENT:
                # 绘制职业图标占位符
                cv2.rectangle(frame, (icon_x, icon_y),
                             (icon_x + icon_size, min(h, icon_y + icon_size)),
                             color, 2)

    def _draw_barcode(
        self,
        frame: np.ndarray,
        x: int, y: int, width: int, height: int,
        color: Tuple[int, int, int]
    ):
        """绘制条码（旋转90度）"""
        import random
        random.seed(42)

        bar_y = y
        while bar_y < y + height:
            bar_height = random.randint(1, 3)
            if random.random() > 0.4:
                cv2.rectangle(frame, (x, bar_y), (x + width, bar_y + bar_height), color, -1)
            bar_y += bar_height + random.randint(1, 2)

    def _render_logo(
        self,
        frame: np.ndarray,
        options: ArknightsOverlayOptions,
        y_offset: int
    ):
        """渲染Logo（淡入效果）"""
        h, w = frame.shape[:2]

        # Logo位置（右下角）
        logo_x = w - 85
        logo_y = h - 45 + y_offset

        if 0 < logo_y < h:
            alpha = self._state.logo_alpha / 255.0
            overlay = frame.copy()
            cv2.putText(overlay, "RHODES", (logo_x, logo_y),
                       self._font, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
            cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

    def _render_bars_and_lines(
        self,
        frame: np.ndarray,
        options: ArknightsOverlayOptions,
        color: Tuple[int, int, int],
        y_offset: int
    ):
        """
        渲染进度条和分割线

        固件实现 (opinfo.c:481-520)
        """
        h, w = frame.shape[:2]
        cfg = self._config

        # 上分割线
        if self._state.upper_line_width > 0:
            line_y = cfg.upperline_offset_y + y_offset
            if 0 < line_y < h:
                cv2.line(frame, (cfg.btm_info_offset_x, line_y),
                        (cfg.btm_info_offset_x + self._state.upper_line_width, line_y),
                        color, 1)

        # 下分割线
        if self._state.lower_line_width > 0:
            line_y = cfg.lowerline_offset_y + y_offset
            if 0 < line_y < h:
                cv2.line(frame, (cfg.btm_info_offset_x, line_y),
                        (cfg.btm_info_offset_x + self._state.lower_line_width, line_y),
                        color, 1)

        # AK进度条
        if self._state.ak_bar_width > 0:
            bar_y = cfg.ak_bar_offset_y + y_offset
            if 0 < bar_y < h:
                cv2.rectangle(frame, (cfg.btm_info_offset_x, bar_y),
                             (cfg.btm_info_offset_x + self._state.ak_bar_width, bar_y + 3),
                             color, -1)

    def _render_arrow(
        self,
        frame: np.ndarray,
        color: Tuple[int, int, int],
        y_offset: int
    ):
        """
        渲染箭头循环动画

        固件实现 (opinfo.c:522-556)
        """
        h, w = frame.shape[:2]

        # 右上角箭头
        arrow_x = w - 30
        arrow_base_y = self._config.arrow_offset_y + y_offset

        if 0 < arrow_base_y < h:
            arrow_y = arrow_base_y + self._state.arrow_y
            if 0 < arrow_y < h:
                # 简化箭头：三角形
                pts = np.array([
                    [arrow_x, arrow_y + 10],
                    [arrow_x - 5, arrow_y + 20],
                    [arrow_x + 5, arrow_y + 20]
                ], np.int32)
                cv2.fillPoly(frame, [pts], color)

    @property
    def is_entry_complete(self) -> bool:
        """入场动画是否完成"""
        return self._state.entry_progress >= 1.0

    @property
    def frame_counter(self) -> int:
        """当前帧计数"""
        return self._state.frame_counter

    @property
    def entry_y_offset(self) -> int:
        """当前入场Y偏移"""
        return self._state.entry_y_offset

    @property
    def config(self) -> "FirmwareConfig":
        """获取固件配置"""
        return self._config
