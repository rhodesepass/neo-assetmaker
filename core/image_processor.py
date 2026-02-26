"""
图片处理器 - 图片缩放、旋转和格式转换
"""
import os
import logging
from typing import Optional, Tuple

import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from config.constants import (
    LOGO_WIDTH, LOGO_HEIGHT,
    get_resolution_spec
)

logger = logging.getLogger(__name__)


class ImageProcessor:
    """图片处理器"""

    @staticmethod
    def load_image(path: str) -> Optional[np.ndarray]:
        """
        加载图片为numpy数组 (BGR/BGRA格式)

        Args:
            path: 图片路径

        Returns:
            numpy数组，失败返回None
        """
        if not os.path.exists(path):
            logger.error(f"图片文件不存在: {path}")
            return None

        try:
            if HAS_CV2:
                # 使用 numpy 读取文件字节，再用 cv2.imdecode 解码
                # 这样可以避免 OpenCV 的中文路径编码问题
                with open(path, 'rb') as f:
                    data = np.frombuffer(f.read(), dtype=np.uint8)
                img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
                if img is None:
                    raise ValueError("OpenCV无法解码图片")
                return img
            elif HAS_PIL:
                # PIL加载并转换为numpy
                pil_img = Image.open(path)
                if pil_img.mode == 'RGBA':
                    img = np.array(pil_img)
                    # RGBA -> BGRA
                    img = img[:, :, [2, 1, 0, 3]]
                elif pil_img.mode == 'RGB':
                    img = np.array(pil_img)
                    # RGB -> BGR
                    img = img[:, :, [2, 1, 0]]
                else:
                    # 转换为RGBA
                    pil_img = pil_img.convert('RGBA')
                    img = np.array(pil_img)
                    img = img[:, :, [2, 1, 0, 3]]
                return img
            else:
                raise ImportError("需要安装 opencv-python 或 Pillow")
        except Exception as e:
            logger.error(f"加载图片失败: {e}")
            return None

    @staticmethod
    def save_image(img: np.ndarray, path: str) -> bool:
        """
        保存图片

        Args:
            img: numpy数组 (BGR/BGRA格式)
            path: 输出路径

        Returns:
            是否成功
        """
        try:
            if HAS_CV2:
                ext = os.path.splitext(path)[1] or '.png'
                success, encoded = cv2.imencode(ext, img)
                if success:
                    with open(path, 'wb') as f:
                        f.write(encoded.tobytes())
            elif HAS_PIL:
                # BGR(A) -> RGB(A)
                if img.shape[-1] == 4:
                    img_rgb = img[:, :, [2, 1, 0, 3]]
                    pil_img = Image.fromarray(img_rgb, 'RGBA')
                else:
                    img_rgb = img[:, :, [2, 1, 0]]
                    pil_img = Image.fromarray(img_rgb, 'RGB')
                pil_img.save(path)
            else:
                raise ImportError("需要安装 opencv-python 或 Pillow")
            return True
        except Exception as e:
            logger.error(f"保存图片失败: {e}")
            return False

    @staticmethod
    def resize_image(
        img: np.ndarray,
        target_width: int,
        target_height: int,
        keep_aspect: bool = True
    ) -> np.ndarray:
        """
        缩放图片

        Args:
            img: 输入图片
            target_width: 目标宽度
            target_height: 目标高度
            keep_aspect: 是否保持宽高比（居中裁剪/填充）

        Returns:
            缩放后的图片
        """
        if not HAS_CV2:
            raise ImportError("resize_image 需要 opencv-python")

        h, w = img.shape[:2]

        if not keep_aspect:
            return cv2.resize(img, (target_width, target_height))

        # 计算缩放比例
        scale = max(target_width / w, target_height / h)
        new_w = int(w * scale)
        new_h = int(h * scale)

        # 缩放
        resized = cv2.resize(img, (new_w, new_h))

        # 居中裁剪
        start_x = (new_w - target_width) // 2
        start_y = (new_h - target_height) // 2
        cropped = resized[start_y:start_y+target_height, start_x:start_x+target_width]

        return cropped

    @staticmethod
    def rotate_180(img: np.ndarray) -> np.ndarray:
        """旋转图片180度"""
        if HAS_CV2:
            return cv2.rotate(img, cv2.ROTATE_180)
        else:
            return np.rot90(img, 2)

    @staticmethod
    def ensure_bgra(img: np.ndarray) -> np.ndarray:
        """确保图片为BGRA格式"""
        if len(img.shape) == 2:
            # 灰度图
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA) if HAS_CV2 else \
                  np.stack([img, img, img, np.full_like(img, 255)], axis=-1)
        elif img.shape[-1] == 3:
            # BGR -> BGRA
            if HAS_CV2:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
            else:
                alpha = np.full((img.shape[0], img.shape[1], 1), 255, dtype=img.dtype)
                img = np.concatenate([img, alpha], axis=-1)
        return img

    @staticmethod
    def process_for_logo(img: np.ndarray) -> np.ndarray:
        """
        处理图片用于Logo导出

        Args:
            img: 输入图片

        Returns:
            处理后的图片 (256x256 BGRA)
        """
        # 缩放到Logo尺寸
        img = ImageProcessor.resize_image(img, LOGO_WIDTH, LOGO_HEIGHT)
        # 确保BGRA格式
        img = ImageProcessor.ensure_bgra(img)
        # 旋转180度
        img = ImageProcessor.rotate_180(img)
        return img

    @staticmethod
    def process_for_overlay(img: np.ndarray, resolution: str = "360x640") -> np.ndarray:
        """
        处理图片用于Overlay导出

        Args:
            img: 输入图片
            resolution: 目标分辨率

        Returns:
            处理后的图片
        """
        spec = get_resolution_spec(resolution)
        target_w = spec["width"]
        target_h = spec["height"]

        # 缩放到目标分辨率
        img = ImageProcessor.resize_image(img, target_w, target_h)
        # 确保BGRA格式
        img = ImageProcessor.ensure_bgra(img)
        # 旋转180度
        img = ImageProcessor.rotate_180(img)
        return img

    @staticmethod
    def get_image_info(path: str) -> Optional[dict]:
        """
        获取图片信息

        Args:
            path: 图片路径

        Returns:
            包含宽度、高度、通道数的字典
        """
        img = ImageProcessor.load_image(path)
        if img is None:
            return None

        h, w = img.shape[:2]
        channels = img.shape[-1] if len(img.shape) == 3 else 1
        has_alpha = channels == 4

        return {
            "width": w,
            "height": h,
            "channels": channels,
            "has_alpha": has_alpha,
            "size_str": f"{w}x{h}"
        }
