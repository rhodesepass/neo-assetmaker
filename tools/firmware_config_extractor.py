#!/usr/bin/env python3
"""
固件配置提取器 - 从 C 源码自动提取常量和枚举定义

用法:
    python firmware_config_extractor.py --source D:\Document\GitHub\drm_app_neo --output config/firmware/default.firmware.json

功能:
    1. 解析 config.h 提取 #define 常量
    2. 解析 prts.h 和 opinfo.c 提取枚举定义
    3. 输出结构化的 JSON 配置文件
"""

import argparse
import json
import os
import re
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple


# ==================== 正则表达式模式 ====================

# 基础数值常量: #define NAME 123
PATTERN_DEFINE_NUMERIC = re.compile(
    r'^#define\s+(\w+)\s+(\d+)\s*(?://.*)?$'
)

# 带括号的数值: #define NAME (123)
PATTERN_DEFINE_PAREN_NUMERIC = re.compile(
    r'^#define\s+(\w+)\s+\((\d+)\)\s*(?://.*)?$'
)

# 带乘法的常量: #define NAME (500 * 1000)
PATTERN_DEFINE_MULTIPLY = re.compile(
    r'^#define\s+(\w+)\s+\((\d+)\s*\*\s*(\d+)(?:\s*\*\s*(\d+))?\)\s*(?://.*)?$'
)

# 字符串常量: #define NAME "value"
PATTERN_DEFINE_STRING = re.compile(
    r'^#define\s+(\w+)\s+"([^"]+)"\s*(?://.*)?$'
)

# 十六进制常量: #define NAME 0xABCD
PATTERN_DEFINE_HEX = re.compile(
    r'^#define\s+(\w+)\s+(0x[0-9A-Fa-f]+)\s*(?://.*)?$'
)

# 枚举块: typedef enum { ... } name_t;
PATTERN_ENUM_BLOCK = re.compile(
    r'typedef\s+enum\s*\{([^}]+)\}\s*(\w+)\s*;',
    re.MULTILINE | re.DOTALL
)

# 枚举成员: NAME = 0, 或 NAME,
PATTERN_ENUM_MEMBER = re.compile(
    r'(\w+)\s*(?:=\s*(\d+))?\s*,?'
)


class FirmwareConfigExtractor:
    """固件配置提取器"""

    def __init__(self, firmware_path: str):
        self.firmware_path = firmware_path
        self.defines: Dict[str, Any] = {}
        self.enums: Dict[str, Dict[str, int]] = {}

    def extract(self) -> Dict[str, Any]:
        """提取所有配置"""
        # 1. 提取 config.h 中的常量
        config_h_path = os.path.join(self.firmware_path, 'src', 'config.h')
        if os.path.exists(config_h_path):
            self._extract_defines(config_h_path)

        # 2. 提取枚举定义
        enum_files = [
            ('src/prts/prts.h', ['prts_state_t', 'prts_request_type_t', 'display_type_t']),
            ('src/overlay/opinfo.c', ['arknights_overlay_animation_eink_state_t']),
            ('src/overlay/opinfo.h', ['opinfo_type_t']),
            ('src/overlay/transitions.h', ['transition_type_t']),
        ]
        for rel_path, enum_names in enum_files:
            full_path = os.path.join(self.firmware_path, rel_path)
            if os.path.exists(full_path):
                self._extract_enums(full_path, enum_names)

        # 3. 构建结构化配置
        return self._build_config()

    def _extract_defines(self, file_path: str):
        """从文件中提取 #define 常量"""
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        for line in content.split('\n'):
            line = line.strip()
            if not line.startswith('#define'):
                continue

            # 尝试各种模式匹配
            value = self._parse_define(line)
            if value is not None:
                name, val = value
                self.defines[name] = val

    def _parse_define(self, line: str) -> Optional[Tuple[str, Any]]:
        """解析单个 #define 行"""
        # 带乘法的常量
        match = PATTERN_DEFINE_MULTIPLY.match(line)
        if match:
            name = match.group(1)
            val = int(match.group(2)) * int(match.group(3))
            if match.group(4):
                val *= int(match.group(4))
            return (name, val)

        # 带括号的数值
        match = PATTERN_DEFINE_PAREN_NUMERIC.match(line)
        if match:
            return (match.group(1), int(match.group(2)))

        # 基础数值
        match = PATTERN_DEFINE_NUMERIC.match(line)
        if match:
            return (match.group(1), int(match.group(2)))

        # 十六进制
        match = PATTERN_DEFINE_HEX.match(line)
        if match:
            return (match.group(1), int(match.group(2), 16))

        # 字符串
        match = PATTERN_DEFINE_STRING.match(line)
        if match:
            return (match.group(1), match.group(2))

        return None

    def _extract_enums(self, file_path: str, target_enums: List[str]):
        """从文件中提取枚举定义"""
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        for match in PATTERN_ENUM_BLOCK.finditer(content):
            enum_body = match.group(1)
            enum_name = match.group(2)

            if enum_name not in target_enums:
                continue

            members = {}
            current_value = 0
            for member_match in PATTERN_ENUM_MEMBER.finditer(enum_body):
                member_name = member_match.group(1)
                if member_match.group(2):
                    current_value = int(member_match.group(2))
                members[member_name] = current_value
                current_value += 1

            if members:
                self.enums[enum_name] = members

    def _get_define(self, name: str, default: Any = None) -> Any:
        """获取常量值，支持前缀匹配"""
        # 完整名称匹配
        if name in self.defines:
            return self.defines[name]

        # 尝试加前缀
        prefixes = [
            'OVERLAY_ANIMATION_OPINFO_',
            'OVERLAY_ARKNIGHTS_',
            'LAYER_ANIMATION_',
            'UI_LAYER_ANIMATION_',
        ]
        for prefix in prefixes:
            full_name = prefix + name
            if full_name in self.defines:
                return self.defines[full_name]

        return default

    def _build_config(self) -> Dict[str, Any]:
        """构建结构化配置"""
        # 计算 FPS
        step_time = self._get_define('OVERLAY_ANIMATION_STEP_TIME', 20000)
        fps = 1000000 // step_time if step_time > 0 else 50

        config = {
            "version": 1,
            "name": "drm_app_neo_extracted",
            "source": self.firmware_path,
            "extracted_at": datetime.now().isoformat(),

            "animation": {
                "fps": fps,
                "step_time_us": step_time,

                "typewriter": {
                    "name": {
                        "start_frame": self._get_define('NAME_START_FRAME', 30),
                        "frame_per_char": self._get_define('NAME_FRAME_PER_CODEPOINT', 3)
                    },
                    "code": {
                        "start_frame": self._get_define('CODE_START_FRAME', 40),
                        "frame_per_char": self._get_define('CODE_FRAME_PER_CODEPOINT', 3)
                    },
                    "staff": {
                        "start_frame": self._get_define('STAFF_TEXT_START_FRAME', 40),
                        "frame_per_char": self._get_define('STAFF_TEXT_FRAME_PER_CODEPOINT', 3)
                    },
                    "aux": {
                        "start_frame": self._get_define('AUX_TEXT_START_FRAME', 50),
                        "frame_per_char": self._get_define('AUX_TEXT_FRAME_PER_CODEPOINT', 2)
                    }
                },

                "eink": {
                    "barcode": {
                        "start_frame": self._get_define('BARCODE_START_FRAME', 30),
                        "frame_per_state": self._get_define('BARCODE_FRAME_PER_STATE', 15)
                    },
                    "classicon": {
                        "start_frame": self._get_define('CLASSICON_START_FRAME', 60),
                        "frame_per_state": self._get_define('CLASSICON_FRAME_PER_STATE', 15)
                    },
                    "states": self._get_eink_states()
                },

                "color_fade": {
                    "start_frame": self._get_define('COLOR_FADE_START_FRAME', 15),
                    "value_per_frame": self._get_define('COLOR_FADE_VALUE_PER_FRAME', 10),
                    "end_value": self._get_define('COLOR_FADE_END_VALUE', 192)
                },

                "logo_fade": {
                    "start_frame": self._get_define('LOGO_FADE_START_FRAME', 30),
                    "value_per_frame": self._get_define('LOGO_FADE_VALUE_PER_FRAME', 5)
                },

                "bars_lines": {
                    "ak_bar": {
                        "start_frame": self._get_define('AK_BAR_SWIPE_START_FRAME', 100),
                        "frame_count": self._get_define('AK_BAR_SWIPE_FRAME_COUNT', 40)
                    },
                    "upper_line": {
                        "start_frame": self._get_define('LINE_UPPER_START_FRAME', 80),
                        "frame_count": self._get_define('LINE_FRAME_COUNT', 40)
                    },
                    "lower_line": {
                        "start_frame": self._get_define('LINE_LOWER_START_FRAME', 90),
                        "frame_count": self._get_define('LINE_FRAME_COUNT', 40)
                    },
                    "line_width": self._get_define('LINE_WIDTH', 280)
                },

                "arrow": {
                    "y_incr_per_frame": self._get_define('ARROW_Y_INCR_PER_FRAME', 1)
                },

                "entry": {
                    "total_frames": 50  # 1秒 @ 50fps
                }
            },

            "layout": {
                "overlay": {
                    "width": self._get_define('OVERLAY_WIDTH', 360),
                    "height": self._get_define('OVERLAY_HEIGHT', 640)
                },
                "offsets": {
                    "btm_info_x": self._get_define('BTM_INFO_OFFSET_X', 70),
                    "opname_y": self._get_define('OPNAME_OFFSET_Y', 415),
                    "upperline_y": self._get_define('UPPERLINE_OFFSET_Y', 455),
                    "lowerline_y": self._get_define('LOWERLINE_OFFSET_Y', 475),
                    "opcode_y": self._get_define('OPCODE_OFFSET_Y', 457),
                    "staff_text_y": self._get_define('STAFF_TEXT_OFFSET_Y', 480),
                    "class_icon_y": self._get_define('CLASS_ICON_OFFSET_Y', 525),
                    "ak_bar_y": self._get_define('AK_BAR_OFFSET_Y', 578),
                    "aux_text_y": self._get_define('AUX_TEXT_OFFSET_Y', 592),
                    "aux_text_line_height": self._get_define('AUX_TEXT_LINE_HEIGHT', 15),
                    "arrow_y": self._get_define('TOP_RIGHT_ARROW_OFFSET_Y', 100)
                },
                "barcode": {
                    "x": 1,
                    "y": self._get_define('BARCODE_OFFSET_Y', 450),
                    "width": self._get_define('BARCODE_WIDTH', 50),
                    "height": self._get_define('BARCODE_HEIGHT', 180)
                },
                "class_icon": {
                    "width": self._get_define('CLASS_ICON_WIDTH', 50),
                    "height": self._get_define('CLASS_ICON_HEIGHT', 50)
                }
            },

            "bezier_presets": {
                "ease_out": [0.0, 0.0, 0.58, 1.0],
                "ease_in": [0.42, 0.0, 1.0, 1.0],
                "ease_in_out": [0.42, 0.0, 0.58, 1.0]
            },

            "transition": {
                "default_frames": 75,
                "phase_ratio": [0.333, 0.333, 0.333]
            },

            "enums": self._build_enums()
        }

        return config

    def _get_eink_states(self) -> List[str]:
        """获取 EINK 状态列表"""
        if 'arknights_overlay_animation_eink_state_t' in self.enums:
            enum = self.enums['arknights_overlay_animation_eink_state_t']
            # 按值排序返回名称列表
            sorted_items = sorted(enum.items(), key=lambda x: x[1])
            return [name.replace('ANIMATION_EINK_', '') for name, _ in sorted_items]
        return ["FIRST_BLACK", "FIRST_WHITE", "SECOND_BLACK", "SECOND_WHITE", "IDLE", "CONTENT"]

    def _build_enums(self) -> Dict[str, Dict[str, int]]:
        """构建枚举配置"""
        result = {}

        # PRTS 状态
        if 'prts_state_t' in self.enums:
            result['prts_state'] = {
                name.replace('PRTS_STATE_', ''): val
                for name, val in self.enums['prts_state_t'].items()
            }
        else:
            result['prts_state'] = {
                "IDLE": 0, "TRANSITION_IN": 1, "INTRO": 2,
                "TRANSITION_LOOP": 3, "PRE_OPINFO": 4
            }

        # 过渡类型
        if 'transition_type_t' in self.enums:
            result['transition_type'] = {
                name.replace('TRANSITION_TYPE_', ''): val
                for name, val in self.enums['transition_type_t'].items()
            }
        else:
            result['transition_type'] = {
                "FADE": 0, "MOVE": 1, "SWIPE": 2, "NONE": 3
            }

        # EINK 状态
        if 'arknights_overlay_animation_eink_state_t' in self.enums:
            result['eink_state'] = {
                name.replace('ANIMATION_EINK_', ''): val
                for name, val in self.enums['arknights_overlay_animation_eink_state_t'].items()
            }
        else:
            result['eink_state'] = {
                "FIRST_BLACK": 0, "FIRST_WHITE": 1, "SECOND_BLACK": 2,
                "SECOND_WHITE": 3, "IDLE": 4, "CONTENT": 5
            }

        # Opinfo 类型
        if 'opinfo_type_t' in self.enums:
            result['opinfo_type'] = {
                name.replace('OPINFO_TYPE_', ''): val
                for name, val in self.enums['opinfo_type_t'].items()
            }
        else:
            result['opinfo_type'] = {
                "IMAGE": 0, "ARKNIGHTS": 1, "NONE": 2
            }

        return result


def main():
    parser = argparse.ArgumentParser(description='固件配置提取器')
    parser.add_argument(
        '--source', '-s',
        required=True,
        help='固件源码路径 (例如: D:\\Document\\GitHub\\drm_app_neo)'
    )
    parser.add_argument(
        '--output', '-o',
        required=True,
        help='输出 JSON 文件路径'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='显示详细输出'
    )

    args = parser.parse_args()

    # 检查源码路径
    if not os.path.exists(args.source):
        print(f"错误: 固件源码路径不存在: {args.source}")
        return 1

    config_h = os.path.join(args.source, 'src', 'config.h')
    if not os.path.exists(config_h):
        print(f"错误: 找不到 config.h: {config_h}")
        return 1

    # 提取配置
    print(f"正在从 {args.source} 提取配置...")
    extractor = FirmwareConfigExtractor(args.source)
    config = extractor.extract()

    if args.verbose:
        print(f"提取了 {len(extractor.defines)} 个常量")
        print(f"提取了 {len(extractor.enums)} 个枚举")

    # 确保输出目录存在
    output_dir = os.path.dirname(args.output)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 写入 JSON
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print(f"配置已保存到: {args.output}")
    return 0


if __name__ == '__main__':
    exit(main())
