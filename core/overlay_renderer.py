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

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

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

        # === 左上角自定义文字 (top_left_rhodes) ===
        if options.top_left_rhodes:
            # 旋转90°显示在左侧区域 (0, 5) ~ (67, opname_y)
            rhodes_w = int(w * 67 / 360)
            rhodes_h = int(h * 410 / 640)
            self._draw_rotated_text(
                result, options.top_left_rhodes,
                0, int(h * 5 / 640), rhodes_w, rhodes_h,
                font_scale=h / 10, color_rgb=(255, 255, 255)
            )

        # === 右上角栏自定义文字 (top_right_bar_text) ===
        if options.top_right_bar_text:
            # 旋转90°显示在右上角栏区域
            bar_x = int(w * (360 - 80) / 360) + int(w * 42 / 360)
            bar_y = int(h * 314 / 640)
            bar_w = int(w * 10 / 360)
            bar_h = int(h * 102 / 640)
            self._draw_rotated_text(
                result, options.top_right_bar_text,
                bar_x, bar_y, bar_w, bar_h,
                font_scale=h / 80, color_rgb=(255, 255, 255)
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

    def _draw_rotated_text(
        self,
        frame: np.ndarray,
        text: str,
        x: int, y: int, width: int, height: int,
        font_scale: float,
        color_rgb: Tuple[int, int, int]
    ):
        """将文字旋转90°（顺时针）渲染到帧上

        使用 Pillow 绘制水平文字后旋转90°，再叠加到 OpenCV 帧上。
        模拟固件 fbdraw_text_rot90 的效果。
        """
        if not HAS_PIL or width <= 0 or height <= 0:
            return

        # 旋转90°后: 原始水平文字的宽度对应旋转后的高度
        # 所以先绘制水平文字，尺寸为 (height, width)
        text_img = Image.new('RGBA', (height, width), (0, 0, 0, 0))
        draw = ImageDraw.Draw(text_img)

        # 使用默认字体，按比例缩放
        font_size = max(8, int(font_scale))
        try:
            font = ImageFont.truetype("arial", font_size)
        except (IOError, OSError):
            font = ImageFont.load_default()

        draw.text((2, 0), text, fill=(*color_rgb, 255), font=font)

        # 顺时针旋转90° (PIL的rotate是逆时针，所以用270°或-90°)
        rotated = text_img.rotate(-90, expand=True)

        # 裁剪到目标尺寸
        rotated = rotated.crop((0, 0, min(rotated.width, width), min(rotated.height, height)))

        # 转为 numpy array 并叠加到帧上
        rot_array = np.array(rotated)
        if rot_array.shape[2] == 4:
            alpha = rot_array[:, :, 3] / 255.0
            # RGBA -> BGR for OpenCV
            for c in range(3):
                bgr_c = 2 - c  # RGB -> BGR
                region = frame[y:y + rot_array.shape[0], x:x + rot_array.shape[1], bgr_c]
                if region.shape == alpha.shape:
                    frame[y:y + rot_array.shape[0], x:x + rot_array.shape[1], bgr_c] = (
                        region * (1 - alpha) + rot_array[:, :, c] * alpha
                    ).astype(np.uint8)

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
