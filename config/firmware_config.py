"""
FirmwareConfig 数据模型 - 固件配置的 Python 表示

从 JSON 配置文件加载固件常量和枚举定义，
为渲染器提供数据驱动的配置支持。
"""

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any


@dataclass
class TypewriterElementConfig:
    """单个打字机元素配置"""
    start_frame: int = 30
    frame_per_char: int = 3


@dataclass
class TypewriterConfig:
    """打字机效果配置"""
    name: TypewriterElementConfig = field(default_factory=lambda: TypewriterElementConfig(30, 3))
    code: TypewriterElementConfig = field(default_factory=lambda: TypewriterElementConfig(40, 3))
    staff: TypewriterElementConfig = field(default_factory=lambda: TypewriterElementConfig(40, 3))
    aux: TypewriterElementConfig = field(default_factory=lambda: TypewriterElementConfig(50, 2))

    @classmethod
    def from_dict(cls, data: dict) -> "TypewriterConfig":
        return cls(
            name=TypewriterElementConfig(**data.get("name", {})),
            code=TypewriterElementConfig(**data.get("code", {})),
            staff=TypewriterElementConfig(**data.get("staff", {})),
            aux=TypewriterElementConfig(**data.get("aux", {}))
        )


@dataclass
class EinkElementConfig:
    """单个 EINK 元素配置"""
    start_frame: int = 30
    frame_per_state: int = 15


@dataclass
class EinkConfig:
    """EINK 电子墨水效果配置"""
    barcode: EinkElementConfig = field(default_factory=lambda: EinkElementConfig(30, 15))
    classicon: EinkElementConfig = field(default_factory=lambda: EinkElementConfig(60, 15))
    states: List[str] = field(default_factory=lambda: [
        "FIRST_BLACK", "FIRST_WHITE", "SECOND_BLACK", "SECOND_WHITE", "IDLE", "CONTENT"
    ])

    @classmethod
    def from_dict(cls, data: dict) -> "EinkConfig":
        return cls(
            barcode=EinkElementConfig(**data.get("barcode", {})),
            classicon=EinkElementConfig(**data.get("classicon", {})),
            states=data.get("states", cls.__dataclass_fields__["states"].default_factory())
        )


@dataclass
class ColorFadeConfig:
    """颜色渐晕配置"""
    start_frame: int = 15
    value_per_frame: int = 10
    end_value: int = 192

    @classmethod
    def from_dict(cls, data: dict) -> "ColorFadeConfig":
        return cls(**data)


@dataclass
class LogoFadeConfig:
    """Logo 淡入配置"""
    start_frame: int = 30
    value_per_frame: int = 5

    @classmethod
    def from_dict(cls, data: dict) -> "LogoFadeConfig":
        return cls(**data)


@dataclass
class BarLineElementConfig:
    """单个进度条/分割线配置"""
    start_frame: int = 80
    frame_count: int = 40


@dataclass
class BarsLinesConfig:
    """进度条和分割线配置"""
    ak_bar: BarLineElementConfig = field(default_factory=lambda: BarLineElementConfig(100, 40))
    upper_line: BarLineElementConfig = field(default_factory=lambda: BarLineElementConfig(80, 40))
    lower_line: BarLineElementConfig = field(default_factory=lambda: BarLineElementConfig(90, 40))
    line_width: int = 280

    @classmethod
    def from_dict(cls, data: dict) -> "BarsLinesConfig":
        return cls(
            ak_bar=BarLineElementConfig(**data.get("ak_bar", {})),
            upper_line=BarLineElementConfig(**data.get("upper_line", {})),
            lower_line=BarLineElementConfig(**data.get("lower_line", {})),
            line_width=data.get("line_width", 280)
        )


@dataclass
class ArrowConfig:
    """箭头动画配置"""
    y_incr_per_frame: int = 1

    @classmethod
    def from_dict(cls, data: dict) -> "ArrowConfig":
        return cls(**data)


@dataclass
class EntryConfig:
    """入场动画配置"""
    total_frames: int = 50

    @classmethod
    def from_dict(cls, data: dict) -> "EntryConfig":
        return cls(**data)


@dataclass
class AnimationConfig:
    """动画配置总类"""
    fps: int = 50
    step_time_us: int = 20000
    typewriter: TypewriterConfig = field(default_factory=TypewriterConfig)
    eink: EinkConfig = field(default_factory=EinkConfig)
    color_fade: ColorFadeConfig = field(default_factory=ColorFadeConfig)
    logo_fade: LogoFadeConfig = field(default_factory=LogoFadeConfig)
    bars_lines: BarsLinesConfig = field(default_factory=BarsLinesConfig)
    arrow: ArrowConfig = field(default_factory=ArrowConfig)
    entry: EntryConfig = field(default_factory=EntryConfig)

    @classmethod
    def from_dict(cls, data: dict) -> "AnimationConfig":
        return cls(
            fps=data.get("fps", 50),
            step_time_us=data.get("step_time_us", 20000),
            typewriter=TypewriterConfig.from_dict(data.get("typewriter", {})),
            eink=EinkConfig.from_dict(data.get("eink", {})),
            color_fade=ColorFadeConfig.from_dict(data.get("color_fade", {})),
            logo_fade=LogoFadeConfig.from_dict(data.get("logo_fade", {})),
            bars_lines=BarsLinesConfig.from_dict(data.get("bars_lines", {})),
            arrow=ArrowConfig.from_dict(data.get("arrow", {})),
            entry=EntryConfig.from_dict(data.get("entry", {}))
        )


@dataclass
class SizeConfig:
    """尺寸配置"""
    width: int = 360
    height: int = 640

    @classmethod
    def from_dict(cls, data: dict) -> "SizeConfig":
        return cls(**data)


@dataclass
class LayoutOffsetsConfig:
    """布局偏移配置"""
    btm_info_x: int = 70
    opname_y: int = 415
    upperline_y: int = 455
    lowerline_y: int = 475
    opcode_y: int = 457
    staff_text_y: int = 480
    class_icon_y: int = 525
    ak_bar_y: int = 578
    aux_text_y: int = 592
    aux_text_line_height: int = 15
    arrow_y: int = 100

    @classmethod
    def from_dict(cls, data: dict) -> "LayoutOffsetsConfig":
        return cls(**data)


@dataclass
class BarcodeLayoutConfig:
    """条码布局配置"""
    x: int = 1
    y: int = 450
    width: int = 50
    height: int = 180

    @classmethod
    def from_dict(cls, data: dict) -> "BarcodeLayoutConfig":
        return cls(**data)


@dataclass
class LayoutConfig:
    """布局配置总类"""
    overlay: SizeConfig = field(default_factory=SizeConfig)
    offsets: LayoutOffsetsConfig = field(default_factory=LayoutOffsetsConfig)
    barcode: BarcodeLayoutConfig = field(default_factory=BarcodeLayoutConfig)
    class_icon: SizeConfig = field(default_factory=lambda: SizeConfig(50, 50))

    @classmethod
    def from_dict(cls, data: dict) -> "LayoutConfig":
        return cls(
            overlay=SizeConfig.from_dict(data.get("overlay", {})),
            offsets=LayoutOffsetsConfig.from_dict(data.get("offsets", {})),
            barcode=BarcodeLayoutConfig.from_dict(data.get("barcode", {})),
            class_icon=SizeConfig.from_dict(data.get("class_icon", {}))
        )


@dataclass
class TransitionConfig:
    """过渡效果配置"""
    default_frames: int = 75
    phase_ratio: List[float] = field(default_factory=lambda: [0.333, 0.333, 0.333])

    @classmethod
    def from_dict(cls, data: dict) -> "TransitionConfig":
        return cls(
            default_frames=data.get("default_frames", 75),
            phase_ratio=data.get("phase_ratio", [0.333, 0.333, 0.333])
        )


@dataclass
class FirmwareConfig:
    """
    固件配置主类

    包含从固件源码提取的所有常量和枚举定义。
    支持从 JSON 文件加载和使用默认值。
    """
    version: int = 1
    name: str = "default"
    source: str = ""
    extracted_at: str = ""

    animation: AnimationConfig = field(default_factory=AnimationConfig)
    layout: LayoutConfig = field(default_factory=LayoutConfig)
    transition: TransitionConfig = field(default_factory=TransitionConfig)

    bezier_presets: Dict[str, List[float]] = field(default_factory=lambda: {
        "ease_out": [0.0, 0.0, 0.58, 1.0],
        "ease_in": [0.42, 0.0, 1.0, 1.0],
        "ease_in_out": [0.42, 0.0, 0.58, 1.0]
    })

    enums: Dict[str, Dict[str, int]] = field(default_factory=lambda: {
        "prts_state": {"IDLE": 0, "TRANSITION_IN": 1, "INTRO": 2, "TRANSITION_LOOP": 3, "PRE_OPINFO": 4},
        "transition_type": {"FADE": 0, "MOVE": 1, "SWIPE": 2, "NONE": 3},
        "eink_state": {"FIRST_BLACK": 0, "FIRST_WHITE": 1, "SECOND_BLACK": 2, "SECOND_WHITE": 3, "IDLE": 4, "CONTENT": 5},
        "opinfo_type": {"IMAGE": 0, "ARKNIGHTS": 1, "NONE": 2}
    })

    @classmethod
    def from_dict(cls, data: dict) -> "FirmwareConfig":
        """从字典创建配置"""
        return cls(
            version=data.get("version", 1),
            name=data.get("name", "default"),
            source=data.get("source", ""),
            extracted_at=data.get("extracted_at", ""),
            animation=AnimationConfig.from_dict(data.get("animation", {})),
            layout=LayoutConfig.from_dict(data.get("layout", {})),
            transition=TransitionConfig.from_dict(data.get("transition", {})),
            bezier_presets=data.get("bezier_presets", cls.__dataclass_fields__["bezier_presets"].default_factory()),
            enums=data.get("enums", cls.__dataclass_fields__["enums"].default_factory())
        )

    @classmethod
    def load_from_file(cls, path: str) -> "FirmwareConfig":
        """从 JSON 文件加载配置"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls.from_dict(data)

    @classmethod
    def get_default(cls) -> "FirmwareConfig":
        """获取默认配置（与之前硬编码值一致）"""
        return cls()

    def get_bezier(self, name: str) -> Tuple[float, float, float, float]:
        """获取贝塞尔曲线控制点"""
        preset = self.bezier_presets.get(name, [0.42, 0.0, 0.58, 1.0])
        return tuple(preset)

    # ==================== 便捷属性 ====================

    @property
    def fps(self) -> int:
        """动画帧率"""
        return self.animation.fps

    @property
    def overlay_width(self) -> int:
        """叠加层宽度"""
        return self.layout.overlay.width

    @property
    def overlay_height(self) -> int:
        """叠加层高度"""
        return self.layout.overlay.height

    # 打字机时序
    @property
    def name_start_frame(self) -> int:
        return self.animation.typewriter.name.start_frame

    @property
    def name_frame_per_char(self) -> int:
        return self.animation.typewriter.name.frame_per_char

    @property
    def code_start_frame(self) -> int:
        return self.animation.typewriter.code.start_frame

    @property
    def code_frame_per_char(self) -> int:
        return self.animation.typewriter.code.frame_per_char

    @property
    def staff_start_frame(self) -> int:
        return self.animation.typewriter.staff.start_frame

    @property
    def staff_frame_per_char(self) -> int:
        return self.animation.typewriter.staff.frame_per_char

    @property
    def aux_start_frame(self) -> int:
        return self.animation.typewriter.aux.start_frame

    @property
    def aux_frame_per_char(self) -> int:
        return self.animation.typewriter.aux.frame_per_char

    # EINK 时序
    @property
    def barcode_start_frame(self) -> int:
        return self.animation.eink.barcode.start_frame

    @property
    def barcode_frame_per_state(self) -> int:
        return self.animation.eink.barcode.frame_per_state

    @property
    def classicon_start_frame(self) -> int:
        return self.animation.eink.classicon.start_frame

    @property
    def classicon_frame_per_state(self) -> int:
        return self.animation.eink.classicon.frame_per_state

    # 颜色渐晕
    @property
    def color_fade_start_frame(self) -> int:
        return self.animation.color_fade.start_frame

    @property
    def color_fade_value_per_frame(self) -> int:
        return self.animation.color_fade.value_per_frame

    @property
    def color_fade_end_value(self) -> int:
        return self.animation.color_fade.end_value

    # Logo 淡入
    @property
    def logo_fade_start_frame(self) -> int:
        return self.animation.logo_fade.start_frame

    @property
    def logo_fade_value_per_frame(self) -> int:
        return self.animation.logo_fade.value_per_frame

    # 进度条/分割线
    @property
    def ak_bar_start_frame(self) -> int:
        return self.animation.bars_lines.ak_bar.start_frame

    @property
    def ak_bar_frame_count(self) -> int:
        return self.animation.bars_lines.ak_bar.frame_count

    @property
    def line_upper_start_frame(self) -> int:
        return self.animation.bars_lines.upper_line.start_frame

    @property
    def line_lower_start_frame(self) -> int:
        return self.animation.bars_lines.lower_line.start_frame

    @property
    def line_frame_count(self) -> int:
        return self.animation.bars_lines.upper_line.frame_count

    @property
    def line_width(self) -> int:
        return self.animation.bars_lines.line_width

    # 箭头
    @property
    def arrow_y_incr(self) -> int:
        return self.animation.arrow.y_incr_per_frame

    # 入场动画
    @property
    def entry_animation_frames(self) -> int:
        return self.animation.entry.total_frames

    # 布局偏移
    @property
    def btm_info_offset_x(self) -> int:
        return self.layout.offsets.btm_info_x

    @property
    def opname_offset_y(self) -> int:
        return self.layout.offsets.opname_y

    @property
    def upperline_offset_y(self) -> int:
        return self.layout.offsets.upperline_y

    @property
    def lowerline_offset_y(self) -> int:
        return self.layout.offsets.lowerline_y

    @property
    def opcode_offset_y(self) -> int:
        return self.layout.offsets.opcode_y

    @property
    def staff_text_offset_y(self) -> int:
        return self.layout.offsets.staff_text_y

    @property
    def class_icon_offset_y(self) -> int:
        return self.layout.offsets.class_icon_y

    @property
    def ak_bar_offset_y(self) -> int:
        return self.layout.offsets.ak_bar_y

    @property
    def aux_text_offset_y(self) -> int:
        return self.layout.offsets.aux_text_y

    @property
    def arrow_offset_y(self) -> int:
        return self.layout.offsets.arrow_y

    # 条码布局
    @property
    def barcode_offset_x(self) -> int:
        return self.layout.barcode.x

    @property
    def barcode_offset_y(self) -> int:
        return self.layout.barcode.y

    @property
    def barcode_width(self) -> int:
        return self.layout.barcode.width

    @property
    def barcode_height(self) -> int:
        return self.layout.barcode.height
