"""
过渡效果渲染器 - 基于固件 drm_app_neo/src/overlay/transitions.c 实现

固件行为：
- FADE: layer_animation控制整层alpha变化
- MOVE: ease-out(0,0→0.58,1)进入 + ease-in(0.42,0→1,1)退出
- SWIPE: ease-in-out(0.42,0→0.58,1)像素扫动

三阶段时序：
- Phase 1 (0~1/3): 进入动画
- Phase 2 (1/3~2/3): 静止，middle_cb切换视频
- Phase 3 (2/3~1): 退出动画

数据驱动架构:
- 尺寸和贝塞尔预设从 FirmwareConfig 读取
- 支持从 JSON 配置文件加载
- 向后兼容：无参数时使用默认配置
"""
import numpy as np
from typing import Optional, Tuple, List, TYPE_CHECKING
from enum import Enum

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

if TYPE_CHECKING:
    from config.firmware_config import FirmwareConfig


class TransitionType(Enum):
    """过渡效果类型"""
    NONE = "none"
    FADE = "fade"
    MOVE = "move"
    SWIPE = "swipe"


class TransitionPhase(Enum):
    """过渡阶段"""
    PHASE_IN = 0      # 进入阶段
    PHASE_HOLD = 1    # 静止阶段
    PHASE_OUT = 2     # 退出阶段
    PHASE_DONE = 3    # 完成


# ==================== 三次贝塞尔曲线实现 ====================
# 与固件 layer_animation.c 中使用的 lv_cubic_bezier 一致

def cubic_bezier(t: float, p1x: float, p1y: float, p2x: float, p2y: float) -> float:
    """
    三次贝塞尔曲线计算 - CSS cubic-bezier 标准实现

    控制点: P0=(0,0), P1=(p1x,p1y), P2=(p2x,p2y), P3=(1,1)

    固件使用 LVGL 的 lv_cubic_bezier，本实现与其行为一致。

    参考:
    - drm_app_neo/src/render/layer_animation.c:39-96
    - LVGL lv_cubic_bezier 函数

    Args:
        t: 输入参数 0.0 ~ 1.0
        p1x, p1y: 控制点1
        p2x, p2y: 控制点2

    Returns:
        曲线Y值 0.0 ~ 1.0
    """
    # 使用 Newton-Raphson 方法求解 x(s) = t 对应的 s 值
    # 然后计算 y(s)

    # 三次贝塞尔曲线参数方程:
    # x(s) = 3*(1-s)^2*s*p1x + 3*(1-s)*s^2*p2x + s^3
    # y(s) = 3*(1-s)^2*s*p1y + 3*(1-s)*s^2*p2y + s^3

    # 边界情况
    if t <= 0:
        return 0.0
    if t >= 1:
        return 1.0

    # Newton-Raphson 迭代求解 s
    s = t  # 初始猜测
    for _ in range(8):  # 8次迭代足够收敛
        # x(s) = 3*(1-s)^2*s*p1x + 3*(1-s)*s^2*p2x + s^3
        s2 = s * s
        s3 = s2 * s
        one_minus_s = 1 - s
        one_minus_s2 = one_minus_s * one_minus_s

        x = 3 * one_minus_s2 * s * p1x + 3 * one_minus_s * s2 * p2x + s3

        # x'(s) = 导数
        dx = 3 * one_minus_s2 * p1x + 6 * one_minus_s * s * (p2x - p1x) + 3 * s2 * (1 - p2x)

        if abs(dx) < 1e-10:
            break

        # Newton-Raphson 更新
        s = s - (x - t) / dx
        s = max(0.0, min(1.0, s))  # 限制在 [0, 1]

    # 计算 y(s)
    s2 = s * s
    s3 = s2 * s
    one_minus_s = 1 - s
    one_minus_s2 = one_minus_s * one_minus_s

    y = 3 * one_minus_s2 * s * p1y + 3 * one_minus_s * s2 * p2y + s3

    return max(0.0, min(1.0, y))


# 固件使用的缓动函数预设（来自 layer_animation.c:131-162）
def ease_out_bezier(t: float) -> float:
    """
    ease-out: 快速开始，缓慢结束
    控制点: (0, 0) → (0.58, 1)

    用于 MOVE 过渡的进入阶段
    参考: layer_animation.c:145 layer_animation_ease_out_move
    """
    return cubic_bezier(t, 0.0, 0.0, 0.58, 1.0)


def ease_in_bezier(t: float) -> float:
    """
    ease-in: 缓慢开始，快速结束
    控制点: (0.42, 0) → (1, 1)

    用于 MOVE 过渡的退出阶段
    参考: layer_animation.c:152 layer_animation_ease_in_move
    """
    return cubic_bezier(t, 0.42, 0.0, 1.0, 1.0)


def ease_in_out_bezier(t: float) -> float:
    """
    ease-in-out: 缓慢开始，缓慢结束
    控制点: (0.42, 0) → (0.58, 1)

    用于 SWIPE 过渡和入场动画
    参考: layer_animation.c:138 layer_animation_ease_in_out_move
    """
    return cubic_bezier(t, 0.42, 0.0, 0.58, 1.0)


class TransitionRenderer:
    """
    过渡效果渲染器

    实现固件 transitions.c 中的三种过渡效果：
    - FADE: alpha 0→255→0 (线性)
    - MOVE: ease-out滑入 → 静止 → ease-in滑出
    - SWIPE: ease-in-out像素扫入 → 静止 → 扫出

    时序：每种过渡都是 3×duration，分三个阶段

    Args:
        firmware_config: 固件配置，None 表示使用默认配置
        width: 覆盖配置中的宽度（向后兼容）
        height: 覆盖配置中的高度（向后兼容）
    """

    def __init__(
        self,
        firmware_config: "FirmwareConfig" = None,
        width: int = None,
        height: int = None
    ):
        # 加载配置
        if firmware_config is None:
            from config.config_manager import ConfigManager
            firmware_config = ConfigManager.get_firmware()
        self._config = firmware_config

        # 使用传入的尺寸或配置中的尺寸
        self._width = width if width is not None else self._config.overlay_width
        self._height = height if height is not None else self._config.overlay_height

        # SWIPE 预计算贝塞尔值（固件在 transitions.c:393-402 预计算）
        self._swipe_bezier_values: Optional[List[int]] = None
        self._swipe_frames_per_stage: int = 0

    def precompute_swipe_bezier(self, frames_per_stage: int):
        """
        预计算 SWIPE 贝塞尔值

        固件实现 (transitions.c:393-402):
        for(int i = 0; i < frames_per_stage; i++){
            uint32_t t = lv_map(i, 0, frames_per_stage, 0, LV_BEZIER_VAL_MAX);
            int32_t step = lv_cubic_bezier(t, ctlx1, ctly1, ctx2, cty2);
            int32_t new_value = (step * UI_WIDTH) >> LV_BEZIER_VAL_SHIFT;
            data->bezeir_values[i] = new_value;
        }
        """
        if self._swipe_frames_per_stage == frames_per_stage and self._swipe_bezier_values is not None:
            return

        self._swipe_frames_per_stage = frames_per_stage
        self._swipe_bezier_values = []

        for i in range(frames_per_stage):
            t = i / frames_per_stage if frames_per_stage > 0 else 0
            value = ease_in_out_bezier(t)
            pixel_x = int(value * self._width)
            self._swipe_bezier_values.append(pixel_x)

        # 确保最后一个值是屏幕宽度
        if self._swipe_bezier_values:
            self._swipe_bezier_values[-1] = self._width

    # ==================== 辅助方法 ====================

    def get_phase(self, progress: float) -> TransitionPhase:
        """获取当前过渡阶段（公共接口）"""
        phase, _ = self._get_phase_and_progress(progress)
        return phase

    def _get_phase_and_progress(self, progress: float) -> Tuple[TransitionPhase, float]:
        """
        根据总进度计算当前阶段和阶段内进度

        固件时序 (transitions.c):
        - Phase 1 (0 ~ duration): middle_cb 在 duration 时触发
        - Phase 2 (duration ~ 2*duration): 静止
        - Phase 3 (2*duration ~ 3*duration): end_cb 在 3*duration 时触发
        """
        if progress < 1/3:
            return TransitionPhase.PHASE_IN, progress * 3
        elif progress < 2/3:
            return TransitionPhase.PHASE_HOLD, (progress - 1/3) * 3
        elif progress < 1.0:
            return TransitionPhase.PHASE_OUT, (progress - 2/3) * 3
        else:
            return TransitionPhase.PHASE_DONE, 1.0

    def _blend_frames(self, frame1: np.ndarray, frame2: np.ndarray, alpha: float) -> np.ndarray:
        """混合两帧（模拟层alpha效果）"""
        if not HAS_CV2:
            return frame1
        return cv2.addWeighted(frame1, 1 - alpha, frame2, alpha, 0)

    # ==================== FADE 过渡效果 ====================

    def render_fade(
        self,
        current_frame: np.ndarray,
        next_frame: Optional[np.ndarray],
        progress: float,
        transition_image: Optional[np.ndarray] = None
    ) -> Tuple[np.ndarray, TransitionPhase]:
        """
        渲染 FADE 过渡效果

        固件实现 (transitions.c:25-76):
        - 设置 overlay 层 alpha=0
        - 绘制背景色+目标图像到 buffer
        - layer_animation_fade_in: alpha 0→255, duration, delay=0
        - layer_animation_fade_out: alpha 255→0, duration, delay=2*duration

        在模拟器中，我们用像素级混合模拟层 alpha 效果
        """
        phase, phase_progress = self._get_phase_and_progress(progress)

        # 使用过渡图片或黑色帧
        if transition_image is not None:
            display_frame = transition_image.copy()
            # 确保是3通道
            if display_frame.shape[2] == 4:
                display_frame = display_frame[:, :, :3]
        else:
            display_frame = np.zeros_like(current_frame)

        if phase == TransitionPhase.PHASE_IN:
            # 淡入: alpha 0 → 255 (线性)
            # 固件 layer_animation.c:189-206: 线性插值
            alpha = phase_progress
            black_frame = np.zeros_like(display_frame)
            result = self._blend_frames(black_frame, display_frame, alpha)

        elif phase == TransitionPhase.PHASE_HOLD:
            # 静止: alpha = 255
            result = display_frame.copy()

        elif phase == TransitionPhase.PHASE_OUT:
            # 淡出: alpha 255 → 0 (线性)
            alpha = 1 - phase_progress
            target_frame = next_frame if next_frame is not None else np.zeros_like(display_frame)
            result = self._blend_frames(target_frame, display_frame, alpha)

        else:
            result = next_frame if next_frame is not None else current_frame

        return result, phase

    # ==================== MOVE 过渡效果 ====================

    def render_move(
        self,
        current_frame: np.ndarray,
        next_frame: Optional[np.ndarray],
        progress: float,
        transition_image: Optional[np.ndarray] = None
    ) -> Tuple[np.ndarray, TransitionPhase]:
        """
        渲染 MOVE 过渡效果

        固件实现 (transitions.c:98-156):
        - 初始坐标: (SCREEN_WIDTH, 0)
        - Phase 1: ease-out 从右侧滑入到中心
          layer_animation_ease_out_move: (0,0)→(0.58,1)
        - Phase 2: 静止在 (0, 0)
        - Phase 3: ease-in 从中心滑出到左侧
          layer_animation_ease_in_move: (0.42,0)→(1,1)
        """
        phase, phase_progress = self._get_phase_and_progress(progress)

        # 背景帧
        if phase in [TransitionPhase.PHASE_IN, TransitionPhase.PHASE_HOLD]:
            bg_frame = current_frame.copy()
        else:
            bg_frame = next_frame.copy() if next_frame is not None else current_frame.copy()

        # 过渡图片
        if transition_image is None:
            transition_image = np.zeros_like(current_frame)

        h, w = bg_frame.shape[:2]

        if phase == TransitionPhase.PHASE_IN:
            # ease-out: 从右侧快速进入，减速停止
            # 固件: x = SCREEN_WIDTH → 0
            ease = ease_out_bezier(phase_progress)
            x_offset = int(w * (1 - ease))
            result = self._overlay_with_offset(bg_frame, transition_image, x_offset, 0)

        elif phase == TransitionPhase.PHASE_HOLD:
            # 静止在中央
            result = self._overlay_with_offset(bg_frame, transition_image, 0, 0)

        elif phase == TransitionPhase.PHASE_OUT:
            # ease-in: 缓慢启动，加速离开
            # 固件: x = 0 → -SCREEN_WIDTH
            ease = ease_in_bezier(phase_progress)
            x_offset = int(-w * ease)
            result = self._overlay_with_offset(bg_frame, transition_image, x_offset, 0)

        else:
            result = next_frame if next_frame is not None else current_frame

        return result, phase

    def _overlay_with_offset(
        self,
        background: np.ndarray,
        overlay: np.ndarray,
        x_offset: int,
        y_offset: int
    ) -> np.ndarray:
        """将叠加图层放置到背景上的指定偏移位置"""
        result = background.copy()
        h, w = background.shape[:2]
        oh, ow = overlay.shape[:2]

        # 计算可见区域
        src_x1 = max(0, -x_offset)
        src_y1 = max(0, -y_offset)
        src_x2 = min(ow, w - x_offset)
        src_y2 = min(oh, h - y_offset)

        dst_x1 = max(0, x_offset)
        dst_y1 = max(0, y_offset)
        dst_x2 = dst_x1 + (src_x2 - src_x1)
        dst_y2 = dst_y1 + (src_y2 - src_y1)

        if src_x2 > src_x1 and src_y2 > src_y1:
            if len(overlay.shape) > 2 and overlay.shape[2] == 4:
                # 带 alpha 通道
                overlay_region = overlay[src_y1:src_y2, src_x1:src_x2]
                alpha = overlay_region[:, :, 3:4] / 255.0
                rgb = overlay_region[:, :, :3]
                bg_region = result[dst_y1:dst_y2, dst_x1:dst_x2]
                result[dst_y1:dst_y2, dst_x1:dst_x2] = (
                    rgb * alpha + bg_region * (1 - alpha)
                ).astype(np.uint8)
            else:
                result[dst_y1:dst_y2, dst_x1:dst_x2] = overlay[src_y1:src_y2, src_x1:src_x2, :3]

        return result

    # ==================== SWIPE 过渡效果 ====================

    def render_swipe(
        self,
        current_frame: np.ndarray,
        next_frame: Optional[np.ndarray],
        progress: float,
        transition_image: Optional[np.ndarray] = None,
        frame_index: int = 0,
        frames_per_stage: int = 25
    ) -> Tuple[np.ndarray, TransitionPhase]:
        """
        渲染 SWIPE 过渡效果

        固件实现 (transitions.c:211-351):
        - 使用 Worker 线程逐帧绘制
        - 每帧绘制 bezeir_values[curr_frame] 到 bezeir_values[curr_frame+2] 的区域
        - Phase 1 (SWIPE_DRAW_CONTENT): 从左到右扫入图像
        - Phase 2 (SWIPE_DRAW_IDLE): 静止，触发 middle_cb
        - Phase 3 (SWIPE_DRAW_CLEAR): 从左到右扫出（清除）

        贝塞尔曲线: ease-in-out (0.42, 0) → (0.58, 1)
        """
        phase, phase_progress = self._get_phase_and_progress(progress)

        # 预计算贝塞尔值
        self.precompute_swipe_bezier(frames_per_stage)

        # 背景帧
        if phase in [TransitionPhase.PHASE_IN, TransitionPhase.PHASE_HOLD]:
            bg_frame = current_frame.copy()
        else:
            bg_frame = next_frame.copy() if next_frame is not None else current_frame.copy()

        if transition_image is None:
            return bg_frame, phase

        h, w = bg_frame.shape[:2]

        if phase == TransitionPhase.PHASE_IN:
            # 扫入: ease-in-out 从左到右显示
            ease = ease_in_out_bezier(phase_progress)
            swipe_x = int(w * ease)
            result = self._swipe_draw_content(bg_frame, transition_image, 0, swipe_x)

        elif phase == TransitionPhase.PHASE_HOLD:
            # 静止: 完全显示
            result = self._overlay_with_offset(bg_frame, transition_image, 0, 0)

        elif phase == TransitionPhase.PHASE_OUT:
            # 扫出: ease-in-out 从左到右清除
            ease = ease_in_out_bezier(phase_progress)
            swipe_x = int(w * ease)
            result = self._swipe_draw_clear(bg_frame, transition_image, swipe_x, w)

        else:
            result = next_frame if next_frame is not None else current_frame

        return result, phase

    def _swipe_draw_content(
        self,
        background: np.ndarray,
        overlay: np.ndarray,
        start_x: int,
        end_x: int
    ) -> np.ndarray:
        """
        SWIPE 扫入绘制

        固件 (transitions.c:276-304):
        - 填充背景色
        - 复制图像对应部分
        """
        result = background.copy()
        h, w = background.shape[:2]
        oh, ow = overlay.shape[:2]

        if end_x <= start_x:
            return result

        # 限制范围
        draw_start = max(0, start_x)
        draw_end = min(w, min(ow, end_x))

        if draw_end <= draw_start:
            return result

        # 复制图像区域
        if len(overlay.shape) > 2 and overlay.shape[2] == 4:
            overlay_region = overlay[:oh, draw_start:draw_end]
            alpha = overlay_region[:, :, 3:4] / 255.0
            rgb = overlay_region[:, :, :3]
            bg_region = result[:oh, draw_start:draw_end]
            result[:oh, draw_start:draw_end] = (
                rgb * alpha + bg_region * (1 - alpha)
            ).astype(np.uint8)
        else:
            result[:oh, draw_start:draw_end] = overlay[:oh, draw_start:draw_end, :3]

        return result

    def _swipe_draw_clear(
        self,
        background: np.ndarray,
        overlay: np.ndarray,
        start_x: int,
        end_x: int
    ) -> np.ndarray:
        """
        SWIPE 扫出绘制

        固件 (transitions.c:306-312):
        - 清除 0~swipe_x 区域（显示背景）
        - 保留 swipe_x~end 区域（显示 overlay）
        """
        result = background.copy()
        h, w = background.shape[:2]
        oh, ow = overlay.shape[:2]

        # 只绘制 swipe_x 之后的 overlay 部分
        if start_x < ow:
            draw_start = max(0, start_x)
            draw_end = min(w, ow)

            if draw_end > draw_start:
                if len(overlay.shape) > 2 and overlay.shape[2] == 4:
                    overlay_region = overlay[:oh, draw_start:draw_end]
                    alpha = overlay_region[:, :, 3:4] / 255.0
                    rgb = overlay_region[:, :, :3]
                    bg_region = result[:oh, draw_start:draw_end]
                    result[:oh, draw_start:draw_end] = (
                        rgb * alpha + bg_region * (1 - alpha)
                    ).astype(np.uint8)
                else:
                    result[:oh, draw_start:draw_end] = overlay[:oh, draw_start:draw_end, :3]

        return result

    # ==================== 统一渲染接口 ====================

    def render(
        self,
        transition_type: TransitionType,
        current_frame: np.ndarray,
        next_frame: Optional[np.ndarray],
        progress: float,
        transition_image: Optional[np.ndarray] = None
    ) -> Tuple[np.ndarray, TransitionPhase]:
        """统一渲染接口"""
        if transition_type == TransitionType.FADE:
            return self.render_fade(current_frame, next_frame, progress, transition_image)
        elif transition_type == TransitionType.MOVE:
            return self.render_move(current_frame, next_frame, progress, transition_image)
        elif transition_type == TransitionType.SWIPE:
            return self.render_swipe(current_frame, next_frame, progress, transition_image)
        else:
            return current_frame, TransitionPhase.PHASE_DONE

    @property
    def config(self) -> "FirmwareConfig":
        """获取固件配置"""
        return self._config

    @property
    def width(self) -> int:
        """获取渲染宽度"""
        return self._width

    @property
    def height(self) -> int:
        """获取渲染高度"""
        return self._height
