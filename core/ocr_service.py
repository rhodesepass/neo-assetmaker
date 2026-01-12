"""
OCR识别服务

功能：
- 使用 EasyOCR 识别 overlay 图片中的干员名称
- 检测 overlay 是否为标准模板
"""
import os
import logging
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# 延迟导入 EasyOCR（加载较慢）
_reader = None


def _get_ocr_reader():
    """延迟初始化 OCR reader"""
    global _reader
    if _reader is None:
        try:
            import easyocr
            _reader = easyocr.Reader(['en'], gpu=False)
            logger.info("EasyOCR reader 初始化完成")
        except ImportError:
            logger.error("easyocr 未安装，请运行: pip install easyocr")
            return None
        except Exception as e:
            logger.error(f"EasyOCR 初始化失败: {e}")
            return None
    return _reader


class OCRService:
    """OCR识别服务"""

    # 文字区域坐标（针对360x640的overlay，已旋转180度后）
    # 原始参考项目: argb[415:460, 70:300]
    TEXT_REGION_Y1 = 415
    TEXT_REGION_Y2 = 460
    TEXT_REGION_X1 = 70
    TEXT_REGION_X2 = 300

    # overlay尺寸
    OVERLAY_WIDTH = 360
    OVERLAY_HEIGHT = 640

    # 模板匹配阈值
    TEMPLATE_THRESHOLD = 0.9

    def __init__(self, template_path: Optional[str] = None):
        """
        初始化OCR服务

        Args:
            template_path: overlay模板图片路径，用于判断是否为arknights模板
        """
        self._template_path = template_path or self._get_default_template_path()
        self._template = None
        self._template_loaded = False

    @staticmethod
    def _get_default_template_path() -> str:
        """获取默认模板路径"""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(project_root, "resources", "data", "overlay_template.png")

    def _load_template(self) -> bool:
        """加载模板图片"""
        if self._template_loaded:
            return self._template is not None

        self._template_loaded = True

        if not os.path.exists(self._template_path):
            logger.warning(f"模板文件不存在: {self._template_path}")
            return False

        try:
            import cv2
            self._template = cv2.imread(self._template_path)
            if self._template is None:
                logger.error(f"无法读取模板文件: {self._template_path}")
                return False

            # 调整模板到overlay尺寸
            self._template = cv2.resize(
                self._template,
                (self.OVERLAY_WIDTH, self.OVERLAY_HEIGHT)
            )
            logger.info(f"已加载模板: {self._template_path}")
            return True

        except Exception as e:
            logger.error(f"加载模板失败: {e}")
            return False

    def is_arknights_template(self, overlay_image: np.ndarray) -> bool:
        """
        检测overlay是否为arknights标准模板

        Args:
            overlay_image: overlay图像（BGR或BGRA格式，已旋转180度）

        Returns:
            是否为标准模板
        """
        if not self._load_template():
            logger.warning("模板未加载，跳过模板检测")
            return False

        try:
            import cv2

            # 提取RGB通道（忽略Alpha）
            if overlay_image.shape[2] == 4:
                rgb_img = overlay_image[:, :, :3]
            else:
                rgb_img = overlay_image

            # 确保尺寸正确
            if rgb_img.shape[:2] != (self.OVERLAY_HEIGHT, self.OVERLAY_WIDTH):
                rgb_img = cv2.resize(rgb_img, (self.OVERLAY_WIDTH, self.OVERLAY_HEIGHT))

            # 模板匹配
            result = cv2.matchTemplate(rgb_img, self._template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)

            is_match = max_val > self.TEMPLATE_THRESHOLD
            logger.debug(f"模板匹配分数: {max_val:.4f}, 阈值: {self.TEMPLATE_THRESHOLD}, 匹配: {is_match}")

            return is_match

        except Exception as e:
            logger.error(f"模板匹配失败: {e}")
            return False

    def extract_operator_name(self, overlay_image: np.ndarray) -> Optional[str]:
        """
        从overlay图像中提取干员名称

        Args:
            overlay_image: overlay图像（BGRA格式，已旋转180度）

        Returns:
            识别到的干员名称，失败返回 None
        """
        reader = _get_ocr_reader()
        if reader is None:
            logger.error("OCR reader 不可用")
            return None

        try:
            import cv2
            from PIL import Image

            # 提取文字区域
            text_area = overlay_image[
                self.TEXT_REGION_Y1:self.TEXT_REGION_Y2,
                self.TEXT_REGION_X1:self.TEXT_REGION_X2
            ]

            # 转换为PIL Image
            text_area_pil = Image.fromarray(text_area)

            # 添加黑色背景（增强OCR效果）
            text_area_bg = Image.new('RGBA', text_area_pil.size, (0, 0, 0, 255))
            text_area_bg.alpha_composite(text_area_pil.convert('RGBA'))

            # 保存临时文件用于OCR（EasyOCR需要文件路径）
            temp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_temp_text_area.png")
            text_area_bg.save(temp_path)

            # OCR识别
            result = reader.readtext(temp_path, detail=0)

            # 清理临时文件
            if os.path.exists(temp_path):
                os.remove(temp_path)

            if result:
                text = "".join(result).strip()
                logger.info(f"OCR识别结果: {text}")
                return text
            else:
                logger.warning("OCR未识别到文字")
                return None

        except Exception as e:
            logger.error(f"OCR识别失败: {e}")
            return None

    def recognize_from_argb_file(self, argb_path: str) -> Tuple[bool, Optional[str]]:
        """
        从 overlay.argb 文件识别干员名称

        Args:
            argb_path: overlay.argb 文件路径

        Returns:
            (是否为标准模板, 识别到的名称)
        """
        if not os.path.exists(argb_path):
            logger.warning(f"overlay.argb 文件不存在: {argb_path}")
            return False, None

        try:
            import cv2

            # 加载ARGB数据
            data = np.fromfile(argb_path, dtype=np.uint8)
            expected_size = self.OVERLAY_HEIGHT * self.OVERLAY_WIDTH * 4

            if len(data) != expected_size:
                logger.warning(f"ARGB文件大小不匹配: {len(data)} != {expected_size}")
                return False, None

            # 重塑为图像
            overlay_image = data.reshape((self.OVERLAY_HEIGHT, self.OVERLAY_WIDTH, 4))

            # 旋转180度（参考项目的处理方式）
            overlay_image = cv2.rotate(overlay_image, cv2.ROTATE_180)

            # 检测是否为标准模板
            if not self.is_arknights_template(overlay_image):
                return False, None

            # OCR识别
            operator_name = self.extract_operator_name(overlay_image)
            return True, operator_name

        except Exception as e:
            logger.error(f"处理ARGB文件失败: {e}")
            return False, None


# 模块级单例
_default_service: Optional[OCRService] = None


def get_ocr_service() -> OCRService:
    """获取默认的OCR服务实例（单例）"""
    global _default_service
    if _default_service is None:
        _default_service = OCRService()
    return _default_service
