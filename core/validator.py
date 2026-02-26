"""
EPConfig 校验器 - 验证配置文件的完整性和正确性
"""
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum
import os
import re
import uuid

from config.constants import RESOLUTION_SPECS, TRANSITION_TYPES, OVERLAY_TYPES


class ValidationLevel(Enum):
    """校验结果级别"""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationResult:
    """校验结果"""
    level: ValidationLevel
    field: str
    message: str

    def __str__(self) -> str:
        level_str = {
            ValidationLevel.ERROR: "错误",
            ValidationLevel.WARNING: "警告",
            ValidationLevel.INFO: "信息"
        }.get(self.level, "未知")
        return f"[{level_str}] {self.field}: {self.message}"


class EPConfigValidator:
    """epconfig.json 校验器"""

    VALID_SCREENS = list(RESOLUTION_SPECS.keys())
    VALID_TRANSITION_TYPES = TRANSITION_TYPES
    VALID_OVERLAY_TYPES = OVERLAY_TYPES
    COLOR_PATTERN = re.compile(r'^#[0-9a-fA-F]{6}$')
    UUID_PATTERN = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
        re.IGNORECASE
    )

    def __init__(self, base_dir: str = ""):
        """
        初始化校验器

        Args:
            base_dir: 素材目录的基础路径
        """
        self.base_dir = base_dir
        self.results: List[ValidationResult] = []

    def validate(self, config: dict) -> List[ValidationResult]:
        """
        执行完整校验

        Args:
            config: 配置字典

        Returns:
            校验结果列表
        """
        self.results = []

        self._validate_version(config)
        self._validate_uuid(config)
        self._validate_screen(config)
        self._validate_name(config)
        self._validate_icon(config)
        self._validate_loop(config)
        self._validate_intro(config)
        self._validate_transition(config, "transition_in")
        self._validate_transition(config, "transition_loop")
        self._validate_overlay(config)

        return self.results

    def validate_config(self, config) -> List[ValidationResult]:
        """
        校验 EPConfig 对象

        Args:
            config: EPConfig 对象

        Returns:
            校验结果列表
        """
        return self.validate(config.to_dict())

    def has_errors(self) -> bool:
        """检查是否有错误级别的校验结果"""
        return any(r.level == ValidationLevel.ERROR for r in self.results)

    def has_warnings(self) -> bool:
        """检查是否有警告级别的校验结果"""
        return any(r.level == ValidationLevel.WARNING for r in self.results)

    def get_errors(self) -> List[ValidationResult]:
        """获取所有错误"""
        return [r for r in self.results if r.level == ValidationLevel.ERROR]

    def get_warnings(self) -> List[ValidationResult]:
        """获取所有警告"""
        return [r for r in self.results if r.level == ValidationLevel.WARNING]

    def get_infos(self) -> List[ValidationResult]:
        """获取所有信息"""
        return [r for r in self.results if r.level == ValidationLevel.INFO]

    def get_summary(self) -> str:
        """获取校验结果摘要"""
        errors = len(self.get_errors())
        warnings = len(self.get_warnings())
        infos = len(self.get_infos())

        if errors == 0 and warnings == 0:
            return "配置有效"
        elif errors == 0:
            return f"配置有效，但有 {warnings} 个警告"
        else:
            return f"配置无效: {errors} 个错误, {warnings} 个警告"

    def _add_result(self, level: ValidationLevel, field: str, message: str):
        """添加校验结果"""
        self.results.append(ValidationResult(level, field, message))

    def _validate_version(self, config: dict):
        """校验版本号"""
        version = config.get("version")
        if version is None:
            self._add_result(ValidationLevel.ERROR, "version", "缺少version字段")
        elif version != 1:
            self._add_result(ValidationLevel.ERROR, "version",
                           f"版本号必须为1，当前为: {version}")

    def _validate_uuid(self, config: dict):
        """校验UUID"""
        uuid_str = config.get("uuid", "")
        if not uuid_str:
            self._add_result(ValidationLevel.ERROR, "uuid", "uuid为必填字段")
        elif not self.UUID_PATTERN.match(uuid_str):
            self._add_result(ValidationLevel.ERROR, "uuid",
                           f"uuid格式不合法: {uuid_str}")

    def _validate_screen(self, config: dict):
        """校验屏幕分辨率"""
        screen = config.get("screen", "")
        if not screen:
            self._add_result(ValidationLevel.ERROR, "screen", "screen为必填字段")
        elif screen not in self.VALID_SCREENS:
            self._add_result(ValidationLevel.ERROR, "screen",
                           f"screen必须为{self.VALID_SCREENS}之一，当前为: {screen}")

    def _validate_name(self, config: dict):
        """校验名称"""
        name = config.get("name", "")
        if not name:
            self._add_result(ValidationLevel.INFO, "name",
                           "未设置name，将使用文件夹名称")

    def _validate_icon(self, config: dict):
        """校验图标"""
        icon = config.get("icon", "")
        if icon:
            self._validate_optional_image("icon", icon)

    def _validate_loop(self, config: dict):
        """校验循环动画配置"""
        loop = config.get("loop")
        if not loop or not isinstance(loop, dict):
            self._add_result(ValidationLevel.ERROR, "loop", "缺少loop配置")
            return

        loop_file = loop.get("file", "")
        is_image = loop.get("is_image", False)

        if not loop_file:
            self._add_result(ValidationLevel.ERROR, "loop.file",
                           "loop.file为必填字段")
        elif self.base_dir:
            if is_image:
                # 图片模式校验
                self._validate_optional_image("loop.file", loop_file)
            else:
                # 视频模式校验
                self._validate_file_exists("loop.file", loop_file)

    def _validate_intro(self, config: dict):
        """校验入场动画配置"""
        intro = config.get("intro")
        if not intro:
            return  # intro是可选的

        if intro.get("enabled"):
            intro_file = intro.get("file", "")
            if not intro_file:
                self._add_result(ValidationLevel.ERROR, "intro.file",
                               "intro.enabled=true时，intro.file为必填")
            elif self.base_dir:
                self._validate_file_exists("intro.file", intro_file)

            duration = intro.get("duration", 0)
            if duration <= 0:
                self._add_result(ValidationLevel.ERROR, "intro.duration",
                               "intro.enabled=true时，duration必须大于0")

    def _validate_transition(self, config: dict, key: str):
        """校验过渡效果配置"""
        trans = config.get(key)
        if not trans:
            return  # transition是可选的

        trans_type = trans.get("type", "")
        if trans_type not in self.VALID_TRANSITION_TYPES:
            self._add_result(ValidationLevel.ERROR, f"{key}.type",
                           f"type必须为{self.VALID_TRANSITION_TYPES}之一")
            return

        if trans_type != "none":
            options = trans.get("options")
            if not options:
                self._add_result(ValidationLevel.ERROR, f"{key}.options",
                               f"type={trans_type}时options为必填")
                return

            duration = options.get("duration", 0)
            if duration <= 0:
                self._add_result(ValidationLevel.ERROR, f"{key}.options.duration",
                               "duration必须大于0")

            bg_color = options.get("background_color", "")
            if bg_color and not self.COLOR_PATTERN.match(bg_color):
                self._add_result(ValidationLevel.WARNING,
                               f"{key}.options.background_color",
                               f"颜色格式不合法，将使用默认黑色: {bg_color}")

            image = options.get("image")
            if image and self.base_dir:
                self._validate_optional_image(f"{key}.options.image", image)

    def _validate_overlay(self, config: dict):
        """校验叠加UI配置"""
        overlay = config.get("overlay")
        if not overlay:
            return

        overlay_type = overlay.get("type", "")
        if overlay_type not in self.VALID_OVERLAY_TYPES:
            self._add_result(ValidationLevel.ERROR, "overlay.type",
                           f"type必须为{self.VALID_OVERLAY_TYPES}之一")
            return

        if overlay_type == "none":
            return

        options = overlay.get("options")
        if not options:
            self._add_result(ValidationLevel.ERROR, "overlay.options",
                           f"type={overlay_type}时options为必填")
            return

        appear_time = options.get("appear_time", 0)
        if appear_time <= 0:
            self._add_result(ValidationLevel.WARNING, "overlay.options.appear_time",
                           "appear_time建议设置大于0")

        if overlay_type == "arknights":
            self._validate_arknights_overlay(options)
        elif overlay_type == "image":
            self._validate_image_overlay(options)

    def _validate_arknights_overlay(self, options: dict):
        """校验明日方舟叠加UI选项"""
        color = options.get("color", "")
        if color and not self.COLOR_PATTERN.match(color):
            self._add_result(ValidationLevel.WARNING, "overlay.options.color",
                           f"颜色格式不合法，将使用默认黑色: {color}")

        if self.base_dir:
            if options.get("logo"):
                self._validate_optional_image("overlay.options.logo", options["logo"])
            if options.get("operator_class_icon"):
                self._validate_optional_image("overlay.options.operator_class_icon",
                                             options["operator_class_icon"])

    def _validate_image_overlay(self, options: dict):
        """校验图片叠加UI选项"""
        duration = options.get("duration", 0)
        if duration <= 0:
            self._add_result(ValidationLevel.WARNING, "overlay.options.duration",
                           "duration建议设置大于0")
        if self.base_dir and options.get("image"):
            self._validate_optional_image("overlay.options.image", options["image"])

    def _validate_file_exists(self, field: str, rel_path: str):
        """校验文件是否存在"""
        if not self.base_dir:
            return

        abs_path = os.path.join(self.base_dir, rel_path)
        if not os.path.exists(abs_path):
            self._add_result(ValidationLevel.ERROR, field,
                           f"文件不存在: {rel_path}")
        elif not os.access(abs_path, os.R_OK):
            self._add_result(ValidationLevel.ERROR, field,
                           f"文件不可读: {rel_path}")

    def _validate_optional_image(self, field: str, rel_path: str):
        """校验可选图片（不存在时只警告）"""
        if not rel_path or not isinstance(rel_path, str):
            return

        if not self.base_dir:
            return

        abs_path = os.path.join(self.base_dir, rel_path)
        if not os.path.exists(abs_path):
            self._add_result(ValidationLevel.WARNING, field,
                           f"图片文件不存在，将被忽略: {rel_path}")
            return

        # 尝试验证图片
        try:
            from PIL import Image
            with Image.open(abs_path) as img:
                w, h = img.size
                if w <= 0 or h <= 0:
                    self._add_result(ValidationLevel.WARNING, field,
                                   f"图片尺寸不合法，将被忽略: {rel_path}")
        except ImportError:
            pass  # Pillow未安装，跳过
        except Exception as e:
            self._add_result(ValidationLevel.WARNING, field,
                           f"图片无法加载，将被忽略: {rel_path}")
