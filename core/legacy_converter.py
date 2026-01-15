"""
老素材格式转换器

将老版本素材格式转换为新格式 (2.0):
- epconfig.txt -> epconfig.json
- logo.argb (BGRA, 无变换) -> icon.png
- overlay.argb (BGRA, 旋转180度) -> overlay.png (可选)
- loop.mp4 (旋转180度) -> loop.mp4 (重新编码, 使用vflip+hflip)
- intro.mp4 (旋转180度) -> intro.mp4 (重新编码, 使用vflip+hflip)

支持OCR自动识别干员名称（需要easyocr和thefuzz依赖）
"""
import os
import subprocess
import logging
import shutil
from typing import Dict, Any, Optional, List, Tuple, Callable, TYPE_CHECKING
from dataclasses import dataclass

import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

from config.epconfig import (
    EPConfig, Overlay, OverlayType, ArknightsOverlayOptions,
    ImageOverlayOptions, IntroConfig, Transition, TransitionType, TransitionOptions
)
from config.constants import MICROSECONDS_PER_SECOND, DEFAULT_INTRO_DURATION
from utils.file_utils import get_app_dir

if TYPE_CHECKING:
    from core.operator_lookup import OperatorInfo, OperatorLookup
    from core.ocr_service import OCRService

logger = logging.getLogger(__name__)


@dataclass
class ConversionResult:
    """转换结果"""
    success: bool
    src_path: str
    dst_path: str
    message: str = ""
    files_converted: List[str] = None

    def __post_init__(self):
        if self.files_converted is None:
            self.files_converted = []


class LegacyConverter:
    """老素材格式转换器"""

    # 老素材文件尺寸
    LOGO_SIZE = (256, 256)
    OVERLAY_SIZE = (360, 640)

    # 默认职业图标 (用于 arknights 模式)
    DEFAULT_CLASS_ICON = "specialist.png"
    CLASS_ICON_FILENAME = "class_icon.png"

    # 输出图标尺寸 (设备限制)
    OUTPUT_ICON_SIZE = (50, 50)

    def __init__(self):
        self._results: List[ConversionResult] = []
        self._ffmpeg_path: str = ""
        self._class_icon_path: str = self._find_class_icon()

        # OCR和干员查询服务（延迟初始化）
        self._ocr_service: Optional['OCRService'] = None
        self._operator_lookup: Optional['OperatorLookup'] = None

        # GUI确认回调
        self._confirm_callback: Optional[Callable[[str, List], Optional['OperatorInfo']]] = None

    def _find_class_icon(self) -> str:
        """查找默认职业图标路径"""
        # 优先查找项目 resources 目录
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        icon_path = os.path.join(project_root, "resources", "class_icons", self.DEFAULT_CLASS_ICON)
        if os.path.isfile(icon_path):
            return icon_path
        return ""

    def set_confirm_callback(
        self,
        callback: Callable[[str, List], Optional['OperatorInfo']]
    ):
        """
        设置模糊匹配确认回调

        Args:
            callback: 回调函数，接收 (ocr_text, candidates)，返回用户选择的 OperatorInfo 或 None
        """
        self._confirm_callback = callback

    def _get_ocr_service(self) -> Optional['OCRService']:
        """延迟初始化OCR服务"""
        if self._ocr_service is None:
            try:
                from core.ocr_service import OCRService
                self._ocr_service = OCRService()
                logger.info("OCR服务已初始化")
            except ImportError as e:
                logger.warning(f"无法导入OCR服务: {e}")
                return None
        return self._ocr_service

    def _get_operator_lookup(self) -> Optional['OperatorLookup']:
        """延迟初始化干员查询"""
        if self._operator_lookup is None:
            try:
                from core.operator_lookup import OperatorLookup
                self._operator_lookup = OperatorLookup()
                if self._operator_lookup.load():
                    logger.info("干员查询服务已初始化")
                else:
                    logger.warning("干员数据加载失败")
                    self._operator_lookup = None
            except ImportError as e:
                logger.warning(f"无法导入干员查询服务: {e}")
                return None
        return self._operator_lookup

    def _load_overlay_image(self, overlay_path: str) -> Optional[np.ndarray]:
        """
        加载overlay.argb文件为图像

        Args:
            overlay_path: overlay.argb文件路径

        Returns:
            BGRA图像数组，失败返回None
        """
        if not os.path.exists(overlay_path):
            return None

        try:
            data = np.fromfile(overlay_path, dtype=np.uint8)
            w, h = self.OVERLAY_SIZE
            expected_size = w * h * 4

            if len(data) != expected_size:
                logger.warning(f"overlay文件大小不匹配: {len(data)} != {expected_size}")
                return None

            # 重塑为图像并旋转180度
            img = data.reshape((h, w, 4))
            img = cv2.rotate(img, cv2.ROTATE_180)
            return img

        except Exception as e:
            logger.error(f"加载overlay失败: {e}")
            return None

    def _recognize_operator_from_overlay(
        self,
        overlay_image: np.ndarray
    ) -> Tuple[Optional['OperatorInfo'], bool]:
        """
        从overlay图像识别干员信息

        Args:
            overlay_image: overlay图像（BGRA格式，已旋转180度）

        Returns:
            (干员信息, 是否为arknights模板)
            - 成功: (OperatorInfo, True)
            - 非标准模板且OCR失败: (None, False)
            - 标准模板但识别失败: (None, True)
        """
        ocr = self._get_ocr_service()
        lookup = self._get_operator_lookup()

        if not ocr or not lookup:
            logger.warning("OCR或干员查询服务不可用")
            return None, False

        # 检测是否为标准模板
        is_template = ocr.is_arknights_template(overlay_image)

        if not is_template:
            logger.info("overlay不是标准arknights模板，尝试OCR识别...")

        # 无论是否为标准模板，都尝试OCR识别
        ocr_text = ocr.extract_operator_name(overlay_image)
        if not ocr_text:
            if is_template:
                logger.warning("OCR识别失败，但为标准模板")
                return None, True
            else:
                logger.info("OCR识别失败，非通行证样式")
                return None, False

        logger.info(f"OCR识别结果: {ocr_text}")

        # 查询干员
        operator_info, is_exact, candidates = lookup.lookup(ocr_text)

        if is_exact and operator_info:
            logger.info(f"精确匹配干员: {operator_info.name}")
            return operator_info, True

        if operator_info and candidates:
            # 模糊匹配，需要用户确认
            if self._confirm_callback:
                logger.info(f"模糊匹配，等待用户确认: {candidates}")
                confirmed = self._confirm_callback(ocr_text, candidates)
                if confirmed:
                    logger.info(f"用户确认干员: {confirmed.name}")
                    return confirmed, True
                else:
                    logger.info("用户跳过模糊匹配")
                    return None, is_template
            else:
                # 没有确认回调，自动使用最佳匹配
                logger.info(f"无确认回调，自动使用最佳匹配: {operator_info.name}")
                return operator_info, True

        # OCR识别到文字但未找到干员
        if is_template:
            logger.warning(f"未找到匹配的干员: {ocr_text}")
            return None, True
        else:
            logger.info(f"非标准模板，未找到干员: {ocr_text}")
            return None, False

    def _find_class_icon_by_name(self, filename: str) -> Optional[str]:
        """根据文件名查找职业图标"""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        icon_path = os.path.join(project_root, "resources", "class_icons", filename)
        if os.path.isfile(icon_path):
            return icon_path
        return None

    def _find_ak_logo(self) -> Optional[str]:
        """查找AK logo路径"""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        logo_path = os.path.join(project_root, "resources", "class_icons", "ak_logo.png")
        if os.path.isfile(logo_path):
            return logo_path
        return None

    def _generate_arknights_overlay_config(
        self,
        operator_info: 'OperatorInfo',
        dst_dir: str
    ) -> Tuple[dict, List[str]]:
        """
        生成arknights类型的overlay配置

        Args:
            operator_info: 干员信息
            dst_dir: 目标目录

        Returns:
            (overlay配置字典, 复制的文件列表)
        """
        files_copied = []
        lookup = self._get_operator_lookup()

        # 获取职业图标文件名
        class_icon_filename = ""
        if lookup:
            class_icon_filename = lookup.get_class_icon_filename(operator_info.op_class)
            src_icon = self._find_class_icon_by_name(class_icon_filename)
            if src_icon:
                dst_icon = os.path.join(dst_dir, class_icon_filename)
                shutil.copy2(src_icon, dst_icon)
                files_copied.append(class_icon_filename)
                logger.info(f"已复制职业图标: {class_icon_filename}")

        # 复制AK logo
        ak_logo_filename = ""
        ak_logo_src = self._find_ak_logo()
        if ak_logo_src:
            ak_logo_filename = "ak_logo.png"
            ak_logo_dst = os.path.join(dst_dir, ak_logo_filename)
            shutil.copy2(ak_logo_src, ak_logo_dst)
            files_copied.append(ak_logo_filename)
            logger.info(f"已复制AK logo: {ak_logo_filename}")

        # 生成国家/势力文本
        nation_name = operator_info.nation or "Rhodes Island"
        if nation_name:
            nation_name = nation_name.capitalize()

        config = {
            "type": "arknights",
            "options": {
                "appear_time": 100000,
                "operator_name": operator_info.name.upper(),
                "operator_code": f"ARKNIGHTS - {operator_info.code}",
                "barcode_text": f"{operator_info.name.upper()} - ARKNIGHTS",
                "aux_text": f"Operator of {nation_name}\n{operator_info.op_class}/{nation_name}\nArknight-EPass",
                "staff_text": "STAFF",
                "color": operator_info.color,
                "logo": ak_logo_filename,
                "operator_class_icon": class_icon_filename
            }
        }

        return config, files_copied

    @property
    def results(self) -> List[ConversionResult]:
        """获取转换结果列表"""
        return self._results

    def clear_results(self):
        """清空结果"""
        self._results.clear()

    def _find_ffmpeg(self) -> str:
        """查找ffmpeg（支持打包环境）"""
        if self._ffmpeg_path:
            return self._ffmpeg_path

        # 1. 先在应用程序目录查找（支持 Nuitka/PyInstaller 打包）
        app_ffmpeg = os.path.join(get_app_dir(), "ffmpeg.exe")
        if os.path.isfile(app_ffmpeg):
            self._ffmpeg_path = app_ffmpeg
            return self._ffmpeg_path

        # 2. 在当前工作目录查找
        local_ffmpeg = os.path.join(os.getcwd(), "ffmpeg.exe")
        if os.path.isfile(local_ffmpeg):
            self._ffmpeg_path = local_ffmpeg
            return self._ffmpeg_path

        # 3. 在系统 PATH 中查找
        try:
            cmd = ["where", "ffmpeg"] if os.name == 'nt' else ["which", "ffmpeg"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                self._ffmpeg_path = result.stdout.strip().split('\n')[0]
                return self._ffmpeg_path
        except Exception:
            pass

        return ""

    def detect_legacy_folder(self, folder_path: str) -> bool:
        """
        检测文件夹是否为老素材格式

        老素材必须包含 loop.mp4，epconfig.txt 可选

        Args:
            folder_path: 文件夹路径

        Returns:
            是否为老素材格式
        """
        if not os.path.isdir(folder_path):
            return False

        # 必须有 loop.mp4
        loop_path = os.path.join(folder_path, 'loop.mp4')
        if not os.path.exists(loop_path):
            return False

        return True

    def parse_legacy_config(self, src_dir: str) -> Dict[str, Any]:
        """
        解析老配置文件

        Args:
            src_dir: 源目录

        Returns:
            解析后的配置字典
        """
        config_path = os.path.join(src_dir, 'epconfig.txt')
        config = {
            'color': '#000000',
            'version': 0
        }

        if not os.path.exists(config_path):
            logger.info(f"配置文件不存在，使用默认值: {config_path}")
            return config

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()

            # 解析格式: "version color"
            # 例如: "0 ff000000"
            parts = content.split()
            if len(parts) >= 1:
                config['version'] = int(parts[0])
            if len(parts) >= 2:
                # 转换颜色格式: ff000000 -> #000000
                color_hex = parts[1]
                if len(color_hex) == 8:
                    # ARGB -> RGB (忽略alpha)
                    config['color'] = f"#{color_hex[2:]}"
                else:
                    config['color'] = f"#{color_hex}"

            logger.debug(f"解析老配置: {config}")

        except Exception as e:
            logger.error(f"解析配置文件失败: {e}")

        return config

    def convert_bgra_to_png(
        self,
        bgra_path: str,
        png_path: str,
        width: int,
        height: int,
        rotate_180: bool = False,
        flip_vertical: bool = False,
        target_size: Optional[Tuple[int, int]] = None
    ) -> bool:
        """
        将BGRA原始图像转换为PNG

        Args:
            bgra_path: BGRA文件路径
            png_path: 输出PNG路径
            width: 图像宽度
            height: 图像高度
            rotate_180: 是否旋转180度 (用于overlay)
            flip_vertical: 是否垂直翻转 (用于logo)
            target_size: 目标尺寸 (宽, 高)，如果指定则缩放图片

        Returns:
            是否成功
        """
        if not os.path.exists(bgra_path):
            logger.warning(f"BGRA文件不存在: {bgra_path}")
            return False

        if not HAS_CV2:
            logger.error("OpenCV未安装，无法转换图像")
            return False

        try:
            # 读取原始数据
            data = np.fromfile(bgra_path, dtype=np.uint8)

            expected_size = width * height * 4
            if len(data) != expected_size:
                logger.warning(
                    f"BGRA文件大小不匹配: {len(data)} != {expected_size}, "
                    f"尝试自动检测尺寸"
                )
                # 尝试自动检测尺寸
                detected = self._detect_image_size(len(data))
                if detected:
                    width, height = detected
                    logger.info(f"检测到图像尺寸: {width}x{height}")
                else:
                    logger.error("无法检测图像尺寸")
                    return False

            # 重塑为BGRA图像
            img = data.reshape((height, width, 4))

            # 应用变换
            if rotate_180:
                img = cv2.rotate(img, cv2.ROTATE_180)
            if flip_vertical:
                img = cv2.flip(img, 0)  # 垂直翻转(上下翻转)

            # 缩放图片
            if target_size:
                target_w, target_h = target_size
                img = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_AREA)
                logger.info(f"已缩放图片: {width}x{height} -> {target_w}x{target_h}")

            # 保存PNG (使用imencode处理中文路径)
            success, encoded = cv2.imencode('.png', img)
            if success:
                with open(png_path, 'wb') as f:
                    f.write(encoded.tobytes())
            else:
                logger.error(f"PNG编码失败")
                return False

            logger.info(f"已转换BGRA到PNG: {png_path}")
            return True

        except Exception as e:
            logger.error(f"转换BGRA失败: {e}")
            return False

    def _detect_image_size(self, data_size: int) -> Optional[Tuple[int, int]]:
        """
        根据数据大小检测图像尺寸

        Args:
            data_size: 数据字节数

        Returns:
            (宽度, 高度) 或 None
        """
        # 常见尺寸
        common_sizes = [
            (256, 256),   # logo
            (360, 640),   # overlay 360x640
            (480, 854),   # overlay 480x854
            (720, 1080),  # overlay 720x1080
            (512, 512),
            (128, 128),
        ]

        pixel_count = data_size // 4
        for w, h in common_sizes:
            if w * h == pixel_count:
                return (w, h)

        # 尝试正方形
        import math
        sqrt = int(math.sqrt(pixel_count))
        if sqrt * sqrt == pixel_count:
            return (sqrt, sqrt)

        return None

    def make_icon_from_video(self, video_path: str, output_path: str) -> bool:
        """
        从视频第一帧生成icon图片

        Args:
            video_path: 视频文件路径（老素材的loop.mp4，已旋转180度）
            output_path: 输出icon路径

        Returns:
            是否成功
        """
        if not HAS_CV2:
            logger.warning("cv2不可用，无法从视频生成icon")
            return False

        try:
            cap = cv2.VideoCapture(video_path)
            ret, frame = cap.read()
            cap.release()

            if not ret:
                logger.warning(f"读取视频帧失败: {video_path}")
                return False

            # 老素材视频是颠倒180度的，需要旋转回来
            frame = cv2.rotate(frame, cv2.ROTATE_180)

            # 裁剪中央区域 (去掉顶部和底部，取正方形区域)
            # 原视频是384x640，实际显示360x640
            # 裁剪 y:100-460, x:0-360 得到360x360区域
            h, w = frame.shape[:2]
            crop_size = min(w, 360)
            crop_top = 100
            crop_bottom = crop_top + crop_size
            frame = frame[crop_top:crop_bottom, 0:crop_size]

            # 缩放到目标尺寸
            frame = cv2.resize(frame, self.OUTPUT_ICON_SIZE)

            # 保存 (使用imencode处理中文路径)
            success, encoded = cv2.imencode('.png', frame)
            if success:
                with open(output_path, 'wb') as f:
                    f.write(encoded.tobytes())
            else:
                logger.error("PNG编码失败")
                return False

            logger.info(f"从视频生成icon成功: {output_path}")
            return True

        except Exception as e:
            logger.error(f"从视频生成icon失败: {e}")
            return False

    def convert_video(
        self,
        src_path: str,
        dst_path: str,
        progress_callback=None
    ) -> bool:
        """
        转换视频（旋转180度校正 + 重新编码为H.264 High profile）

        Args:
            src_path: 源视频路径
            dst_path: 目标视频路径
            progress_callback: 进度回调

        Returns:
            是否成功
        """
        ffmpeg_path = self._find_ffmpeg()
        if not ffmpeg_path:
            logger.error("未找到FFmpeg，无法转换视频")
            return False

        if not os.path.exists(src_path):
            logger.warning(f"源视频不存在: {src_path}")
            return False

        try:
            cmd = [
                ffmpeg_path,
                "-i", src_path,
                "-vf", "vflip,hflip",  # 旋转180度 (使用vflip+hflip替代rotate=PI以提高兼容性)
                "-c:v", "libx264",
                "-profile:v", "high",
                "-level", "4.0",
                "-pix_fmt", "yuv420p",
                "-b:v", "3000k",
                "-an",  # 无音频
                "-y",   # 覆盖输出
                dst_path
            ]

            logger.info(f"执行FFmpeg命令: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                logger.error(f"FFmpeg转换失败: {result.stderr[:500]}")
                return False

            logger.info(f"已转换视频: {dst_path}")
            return True

        except Exception as e:
            logger.error(f"视频转换失败: {e}")
            return False

    def _get_video_duration(self, video_path: str) -> Optional[float]:
        """
        使用FFprobe获取视频时长（秒）

        Args:
            video_path: 视频文件路径

        Returns:
            视频时长（秒），失败返回 None
        """
        ffmpeg_path = self._find_ffmpeg()
        if not ffmpeg_path:
            return None

        # FFprobe 与 FFmpeg 在同一目录
        ffmpeg_dir = os.path.dirname(ffmpeg_path)
        ffprobe_name = 'ffprobe.exe' if os.name == 'nt' else 'ffprobe'
        ffprobe_path = os.path.join(ffmpeg_dir, ffprobe_name)

        if not os.path.exists(ffprobe_path):
            logger.warning("未找到FFprobe")
            return None

        try:
            cmd = [
                ffprobe_path,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception as e:
            logger.error(f"获取视频时长失败: {e}")

        return None

    def generate_new_config(
        self,
        legacy_config: Dict[str, Any],
        folder_name: str,
        dst_dir: str,
        has_intro: bool = False,
        intro_duration: int = 5000000,
        overlay_mode: str = "arknights",
        has_overlay_image: bool = False,
        has_logo: bool = False,
        has_class_icon: bool = False,
        has_ak_logo: bool = False,
        arknights_overlay_config: Optional[dict] = None
    ) -> bool:
        """
        生成新配置文件

        Args:
            legacy_config: 老配置数据
            folder_name: 文件夹名称（用作素材名称）
            dst_dir: 目标目录
            has_intro: 是否有入场动画
            intro_duration: 入场动画时长（微秒）
            overlay_mode: overlay模式 ("arknights", "image", "auto")
            has_overlay_image: 是否有overlay图片
            has_logo: 是否有logo
            has_class_icon: 是否有职业图标 (用于 arknights 模式)
            has_ak_logo: 是否有ak_logo.png (用于 arknights 模式)
            arknights_overlay_config: OCR识别生成的arknights overlay配置

        Returns:
            是否成功
        """
        try:
            # 创建新配置
            config = EPConfig()
            config.name = folder_name
            config.description = f"从老素材转换: {folder_name}"
            config.loop.file = "loop.mp4"

            # 设置入场动画
            if has_intro:
                config.intro = IntroConfig(
                    enabled=True,
                    file="intro.mp4",
                    duration=intro_duration
                )
                # 设置入场到循环的过渡
                config.transition_loop = Transition(
                    type=TransitionType.FADE,
                    options=TransitionOptions(
                        duration=500000,
                        background_color=legacy_config.get('color', '#000000')
                    )
                )

            # 设置进入素材过渡
            config.transition_in = Transition(
                type=TransitionType.SWIPE,
                options=TransitionOptions(
                    duration=500000,
                    background_color=legacy_config.get('color', '#000000')
                )
            )

            # 设置叠加UI
            color = legacy_config.get('color', '#000000')

            if arknights_overlay_config:
                # 使用OCR识别生成的arknights配置
                opts = arknights_overlay_config.get("options", {})
                config.overlay = Overlay(
                    type=OverlayType.ARKNIGHTS,
                    arknights_options=ArknightsOverlayOptions(
                        appear_time=opts.get("appear_time", 100000),
                        operator_name=opts.get("operator_name", "OPERATOR"),
                        operator_code=opts.get("operator_code", ""),
                        barcode_text=opts.get("barcode_text", ""),
                        aux_text=opts.get("aux_text", ""),
                        staff_text=opts.get("staff_text", "STAFF"),
                        color=opts.get("color", color),
                        logo=opts.get("logo", ""),
                        operator_class_icon=opts.get("operator_class_icon", "")
                    )
                )
            elif overlay_mode == "image" and has_overlay_image:
                # 使用image类型
                config.overlay = Overlay(
                    type=OverlayType.IMAGE,
                    image_options=ImageOverlayOptions(
                        appear_time=100000,
                        duration=100000,
                        image="overlay.png"
                    )
                )
            else:
                # 使用arknights模板默认值
                config.overlay = Overlay(
                    type=OverlayType.ARKNIGHTS,
                    arknights_options=ArknightsOverlayOptions(
                        appear_time=100000,
                        operator_name="OPERATOR",
                        color=color,
                        logo="ak_logo.png" if has_ak_logo else "",
                        operator_class_icon=self.CLASS_ICON_FILENAME if has_class_icon else ""
                    )
                )

            # 设置图标
            if has_logo:
                config.icon = "icon.png"

            # 保存配置
            config_path = os.path.join(dst_dir, 'epconfig.json')
            config.save_to_file(config_path)

            logger.info(f"已生成配置: {config_path}")
            return True

        except Exception as e:
            logger.error(f"生成配置失败: {e}")
            return False

    def convert_folder(
        self,
        src_dir: str,
        dst_dir: str,
        overlay_mode: str = "auto",
        auto_ocr: bool = True,
        progress_callback=None
    ) -> ConversionResult:
        """
        转换单个素材文件夹

        Args:
            src_dir: 源目录
            dst_dir: 目标目录
            overlay_mode: overlay处理模式:
                - "auto": 自动检测，OCR识别干员，非标准模板用image
                - "arknights": 使用arknights模板
                - "image": 保留原overlay图片
            auto_ocr: 是否启用OCR自动识别（仅当overlay_mode为"auto"或"arknights"时生效）
            progress_callback: 进度回调

        Returns:
            转换结果
        """
        folder_name = os.path.basename(src_dir)
        logger.info(f"开始转换: {folder_name}")

        result = ConversionResult(
            success=False,
            src_path=src_dir,
            dst_path=dst_dir
        )

        # 检查源目录
        if not self.detect_legacy_folder(src_dir):
            result.message = "不是有效的老素材格式（缺少loop.mp4）"
            logger.warning(f"{folder_name}: {result.message}")
            self._results.append(result)
            return result

        # 检查FFmpeg
        if not self._find_ffmpeg():
            result.message = "未找到FFmpeg，无法转换视频"
            logger.error(result.message)
            self._results.append(result)
            return result

        # 创建目标目录
        os.makedirs(dst_dir, exist_ok=True)

        # 解析老配置
        legacy_config = self.parse_legacy_config(src_dir)

        # 定义文件路径
        loop_src = os.path.join(src_dir, 'loop.mp4')
        loop_dst = os.path.join(dst_dir, 'loop.mp4')
        intro_src = os.path.join(src_dir, 'intro.mp4')
        intro_dst = os.path.join(dst_dir, 'intro.mp4')
        overlay_src = os.path.join(src_dir, 'overlay.argb')
        overlay_dst = os.path.join(dst_dir, 'overlay.png')
        logo_src = os.path.join(src_dir, 'logo.argb')
        logo_dst = os.path.join(dst_dir, 'icon.png')

        has_intro = False
        has_overlay_image = False
        has_logo = False
        arknights_overlay_config = None  # OCR识别生成的配置

        # 1. 转换 loop.mp4 (必须) - 旋转180度校正
        if progress_callback:
            progress_callback("转换循环视频...")
        if self.convert_video(loop_src, loop_dst):
            result.files_converted.append('loop.mp4')
        else:
            result.message = "转换loop.mp4失败"
            logger.error(f"{folder_name}: {result.message}")
            self._results.append(result)
            return result

        # 2. 转换 intro.mp4 (可选) - 旋转180度校正
        actual_intro_duration = DEFAULT_INTRO_DURATION  # 默认 5 秒
        if os.path.exists(intro_src):
            if progress_callback:
                progress_callback("转换入场视频...")
            if self.convert_video(intro_src, intro_dst):
                result.files_converted.append('intro.mp4')
                has_intro = True

                # 使用 FFprobe 获取转换后视频的实际时长
                duration = self._get_video_duration(intro_dst)
                if duration and duration > 0:
                    actual_intro_duration = int(duration * MICROSECONDS_PER_SECOND)
                    logger.info(f"{folder_name}: intro视频时长 {duration:.2f}秒")
                else:
                    logger.warning(f"{folder_name}: 无法获取intro视频时长，使用默认值")
            else:
                logger.warning(f"{folder_name}: 转换intro.mp4失败，跳过")

        # 3. 处理 overlay.argb
        effective_overlay_mode = overlay_mode
        if os.path.exists(overlay_src):
            if overlay_mode == "auto" or (overlay_mode == "arknights" and auto_ocr):
                # 尝试OCR识别
                if progress_callback:
                    progress_callback("OCR识别干员...")

                overlay_image = self._load_overlay_image(overlay_src)
                if overlay_image is not None:
                    operator_info, is_template = self._recognize_operator_from_overlay(overlay_image)

                    if is_template and operator_info:
                        # 成功识别，生成arknights overlay配置
                        if progress_callback:
                            progress_callback(f"识别到干员: {operator_info.name}")
                        arknights_overlay_config, copied_files = self._generate_arknights_overlay_config(
                            operator_info, dst_dir
                        )
                        result.files_converted.extend(copied_files)
                        effective_overlay_mode = "arknights"
                        logger.info(f"{folder_name}: 识别到干员 {operator_info.name}")
                    elif not is_template and overlay_mode == "auto":
                        # 非标准模板，使用image模式
                        if progress_callback:
                            progress_callback("非标准模板，转换为图片...")
                        w, h = self.OVERLAY_SIZE
                        if self.convert_bgra_to_png(overlay_src, overlay_dst, w, h, rotate_180=True):
                            result.files_converted.append('overlay.png')
                            has_overlay_image = True
                        effective_overlay_mode = "image"
                    else:
                        # 是标准模板但识别失败，使用默认arknights配置
                        effective_overlay_mode = "arknights"
                        logger.warning(f"{folder_name}: OCR识别失败，使用默认配置")
                else:
                    logger.warning(f"{folder_name}: 加载overlay失败")
                    if overlay_mode == "auto":
                        effective_overlay_mode = "arknights"
            elif overlay_mode == "image":
                # 直接转换为图片
                if progress_callback:
                    progress_callback("转换overlay图片...")
                w, h = self.OVERLAY_SIZE
                if self.convert_bgra_to_png(overlay_src, overlay_dst, w, h, rotate_180=True):
                    result.files_converted.append('overlay.png')
                    has_overlay_image = True
                effective_overlay_mode = "image"

        # 4. 转换 logo.argb (可选, 缩放到50x50) 或从视频生成icon
        if os.path.exists(logo_src):
            if progress_callback:
                progress_callback("转换logo图片...")
            w, h = self.LOGO_SIZE
            if self.convert_bgra_to_png(logo_src, logo_dst, w, h, target_size=self.OUTPUT_ICON_SIZE):
                result.files_converted.append('icon.png')
                has_logo = True
            else:
                logger.warning(f"{folder_name}: 转换logo.argb失败，尝试从视频生成")
                # Fallback: 从视频生成icon
                if os.path.exists(loop_src):
                    if self.make_icon_from_video(loop_src, logo_dst):
                        result.files_converted.append('icon.png')
                        has_logo = True
        else:
            # logo.argb不存在，从视频生成icon
            if progress_callback:
                progress_callback("从视频生成icon...")
            if os.path.exists(loop_src):
                if self.make_icon_from_video(loop_src, logo_dst):
                    result.files_converted.append('icon.png')
                    has_logo = True
                else:
                    logger.warning(f"{folder_name}: 从视频生成icon失败")
            else:
                logger.warning(f"{folder_name}: 无logo.argb且无loop.mp4，跳过icon生成")

        # 5. 复制职业图标和ak_logo (用于没有OCR配置的arknights模式)
        has_class_icon = False
        has_ak_logo = False
        if effective_overlay_mode == "arknights" and not arknights_overlay_config:
            if self._class_icon_path:
                class_icon_dst = os.path.join(dst_dir, self.CLASS_ICON_FILENAME)
                try:
                    shutil.copy2(self._class_icon_path, class_icon_dst)
                    result.files_converted.append(self.CLASS_ICON_FILENAME)
                    has_class_icon = True
                    logger.info(f"已复制职业图标: {class_icon_dst}")
                except Exception as e:
                    logger.warning(f"{folder_name}: 复制职业图标失败: {e}")

            ak_logo_src = self._find_ak_logo()
            if ak_logo_src:
                ak_logo_dst = os.path.join(dst_dir, "ak_logo.png")
                try:
                    shutil.copy2(ak_logo_src, ak_logo_dst)
                    result.files_converted.append("ak_logo.png")
                    has_ak_logo = True
                    logger.info(f"已复制AK logo: {ak_logo_dst}")
                except Exception as e:
                    logger.warning(f"{folder_name}: 复制AK logo失败: {e}")

        # 6. 生成 epconfig.json
        if progress_callback:
            progress_callback("生成配置文件...")
        if self.generate_new_config(
            legacy_config,
            folder_name,
            dst_dir,
            has_intro=has_intro,
            intro_duration=actual_intro_duration,
            overlay_mode=effective_overlay_mode,
            has_overlay_image=has_overlay_image,
            has_logo=has_logo,
            has_class_icon=has_class_icon,
            has_ak_logo=has_ak_logo,
            arknights_overlay_config=arknights_overlay_config
        ):
            result.files_converted.append('epconfig.json')

        result.success = len(result.files_converted) > 0
        result.message = f"已转换 {len(result.files_converted)} 个文件"

        logger.info(f"{folder_name}: {result.message}")
        self._results.append(result)
        return result

    def batch_convert(
        self,
        src_root: str,
        dst_root: str,
        overlay_mode: str = "auto",
        auto_ocr: bool = True,
        progress_callback=None,
        folder_progress_callback=None,
        confirm_callback=None
    ) -> List[ConversionResult]:
        """
        批量转换多个素材文件夹

        Args:
            src_root: 源根目录
            dst_root: 目标根目录
            overlay_mode: overlay处理模式:
                - "auto": 自动检测，OCR识别干员，非标准模板用image
                - "arknights": 使用arknights模板
                - "image": 保留原overlay图片
            auto_ocr: 是否启用OCR自动识别
            progress_callback: 进度回调函数 (current, total, name)
            folder_progress_callback: 文件夹内部进度回调 (message)
            confirm_callback: 干员确认回调

        Returns:
            转换结果列表
        """
        self.clear_results()

        if not os.path.isdir(src_root):
            logger.error(f"源目录不存在: {src_root}")
            return []

        # 收集要转换的文件夹
        folders = []
        for name in os.listdir(src_root):
            path = os.path.join(src_root, name)
            if os.path.isdir(path) and self.detect_legacy_folder(path):
                folders.append((name, path))

        if not folders:
            logger.warning(f"未找到老素材文件夹: {src_root}")
            return []

        logger.info(f"找到 {len(folders)} 个老素材文件夹")

        # 创建目标目录
        os.makedirs(dst_root, exist_ok=True)

        # 转换每个文件夹
        # 设置确认回调
        if confirm_callback:
            self.set_confirm_callback(confirm_callback)

        for i, (name, src_path) in enumerate(folders):
            if progress_callback:
                progress_callback(i + 1, len(folders), name)

            dst_path = os.path.join(dst_root, name)
            self.convert_folder(
                src_path, dst_path,
                overlay_mode=overlay_mode,
                auto_ocr=auto_ocr,
                progress_callback=folder_progress_callback
            )

        return self._results

    def get_summary(self) -> str:
        """获取转换摘要"""
        if not self._results:
            return "没有转换结果"

        success_count = sum(1 for r in self._results if r.success)
        total_count = len(self._results)
        total_files = sum(len(r.files_converted) for r in self._results)

        return (
            f"转换完成: {success_count}/{total_count} 个文件夹成功, "
            f"共 {total_files} 个文件"
        )
