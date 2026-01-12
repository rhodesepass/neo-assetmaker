"""
叠加UI渲染器 - 在视频帧上渲染Arknights风格的UI元素
"""
import logging
from typing import Optional, Tuple

import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

from config.epconfig import ArknightsOverlayOptions

logger = logging.getLogger(__name__)


class OverlayRenderer:
    """叠加UI渲染器"""

    def __init__(self):
        self._font = cv2.FONT_HERSHEY_SIMPLEX if HAS_CV2 else None

    @staticmethod
    def hex_to_bgr(hex_color: str) -> Tuple[int, int, int]:
        """将十六进制颜色转换为BGR格式"""
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 6:
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            return (b, g, r)
        return (0, 0, 0)

    def render_arknights_overlay(
        self,
        frame: np.ndarray,
        options: Optional[ArknightsOverlayOptions]
    ) -> np.ndarray:
        """
        渲染Arknights风格叠加UI

        Args:
            frame: 输入帧 (BGR格式)
            options: Arknights叠加选项

        Returns:
            渲染后的帧
        """
        if not HAS_CV2 or options is None:
            return frame

        result = frame.copy()
        h, w = result.shape[:2]

        # 获取主题色
        color = self.hex_to_bgr(options.color)
        # 白色用于文字
        white = (255, 255, 255)
        # 半透明背景色
        overlay_bg = (30, 30, 30)

        # === 顶部区域：干员名称和代号 ===
        top_bar_height = int(h * 0.12)
        self._draw_transparent_rect(
            result, 0, 0, w, top_bar_height,
            overlay_bg, alpha=0.7
        )

        # 干员名称 (大字)
        name_font_scale = h / 400
        name_thickness = max(1, int(h / 200))
        cv2.putText(
            result, options.operator_name,
            (int(w * 0.05), int(h * 0.07)),
            self._font, name_font_scale, white, name_thickness, cv2.LINE_AA
        )

        # 干员代号 (小字)
        code_font_scale = h / 800
        code_thickness = max(1, int(h / 400))
        cv2.putText(
            result, options.operator_code,
            (int(w * 0.05), int(h * 0.10)),
            self._font, code_font_scale, color, code_thickness, cv2.LINE_AA
        )

        # === 左侧装饰线 ===
        line_x = int(w * 0.02)
        cv2.line(
            result,
            (line_x, int(h * 0.15)),
            (line_x, int(h * 0.85)),
            color, max(2, int(w / 180))
        )

        # === 底部区域：条码和辅助文字 ===
        bottom_bar_y = int(h * 0.88)
        bottom_bar_height = h - bottom_bar_y
        self._draw_transparent_rect(
            result, 0, bottom_bar_y, w, bottom_bar_height,
            overlay_bg, alpha=0.7
        )

        # 条码文字
        barcode_font_scale = h / 900
        barcode_thickness = max(1, int(h / 500))
        cv2.putText(
            result, options.barcode_text,
            (int(w * 0.05), int(h * 0.93)),
            self._font, barcode_font_scale, white, barcode_thickness, cv2.LINE_AA
        )

        # 绘制模拟条码线
        self._draw_barcode(
            result,
            int(w * 0.05), int(h * 0.95),
            int(w * 0.5), int(h * 0.02),
            white
        )

        # Staff文字（右下角）
        staff_font_scale = h / 800
        staff_thickness = max(1, int(h / 400))
        staff_size = cv2.getTextSize(
            options.staff_text, self._font,
            staff_font_scale, staff_thickness
        )[0]
        cv2.putText(
            result, options.staff_text,
            (w - staff_size[0] - int(w * 0.05), int(h * 0.96)),
            self._font, staff_font_scale, color, staff_thickness, cv2.LINE_AA
        )

        # === 辅助文字区域（右侧） ===
        aux_lines = options.aux_text.split('\n')
        aux_font_scale = h / 1000
        aux_thickness = max(1, int(h / 600))
        aux_y_start = int(h * 0.20)
        aux_line_height = int(h * 0.03)

        for i, line in enumerate(aux_lines[:5]):  # 最多显示5行
            cv2.putText(
                result, line.strip(),
                (int(w * 0.65), aux_y_start + i * aux_line_height),
                self._font, aux_font_scale, white, aux_thickness, cv2.LINE_AA
            )

        # === 角落装饰 ===
        corner_size = int(min(w, h) * 0.03)
        corner_thickness = max(1, int(min(w, h) / 200))

        # 左上角
        cv2.line(result, (0, corner_size), (0, 0), color, corner_thickness)
        cv2.line(result, (0, 0), (corner_size, 0), color, corner_thickness)

        # 右上角
        cv2.line(result, (w - corner_size, 0), (w, 0), color, corner_thickness)
        cv2.line(result, (w - 1, 0), (w - 1, corner_size), color, corner_thickness)

        # 左下角
        cv2.line(result, (0, h - corner_size), (0, h - 1), color, corner_thickness)
        cv2.line(result, (0, h - 1), (corner_size, h - 1), color, corner_thickness)

        # 右下角
        cv2.line(result, (w - corner_size, h - 1), (w, h - 1), color, corner_thickness)
        cv2.line(result, (w - 1, h - corner_size), (w - 1, h - 1), color, corner_thickness)

        return result

    def _draw_transparent_rect(
        self,
        frame: np.ndarray,
        x: int, y: int, w: int, h: int,
        color: Tuple[int, int, int],
        alpha: float = 0.5
    ):
        """绘制半透明矩形"""
        overlay = frame.copy()
        cv2.rectangle(overlay, (x, y), (x + w, y + h), color, -1)
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

    def _draw_barcode(
        self,
        frame: np.ndarray,
        x: int, y: int, width: int, height: int,
        color: Tuple[int, int, int]
    ):
        """绘制模拟条码"""
        import random
        random.seed(42)  # 固定种子确保条码一致

        bar_x = x
        while bar_x < x + width:
            bar_width = random.randint(1, 3)
            if random.random() > 0.4:  # 60%概率绘制条码线
                cv2.rectangle(
                    frame,
                    (bar_x, y),
                    (bar_x + bar_width, y + height),
                    color, -1
                )
            bar_x += bar_width + random.randint(1, 2)
