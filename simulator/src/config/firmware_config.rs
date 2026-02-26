//! FirmwareConfig data structure
//!
//! Contains animation timing constants extracted from the firmware.
//! Corresponds to Python's config/firmware_config.py

use serde::{Deserialize, Serialize};

/// Typewriter element configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TypewriterElementConfig {
    pub start_frame: u32,
    pub frame_per_char: u32,
}

impl Default for TypewriterElementConfig {
    fn default() -> Self {
        Self {
            start_frame: 30,
            frame_per_char: 3,
        }
    }
}

/// Typewriter effect configuration
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TypewriterConfig {
    #[serde(default)]
    pub name: TypewriterElementConfig,
    #[serde(default)]
    pub code: TypewriterElementConfig,
    #[serde(default)]
    pub staff: TypewriterElementConfig,
    #[serde(default)]
    pub aux: TypewriterElementConfig,
}

/// EINK element configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EinkElementConfig {
    pub start_frame: u32,
    pub frame_per_state: u32,
}

impl Default for EinkElementConfig {
    fn default() -> Self {
        Self {
            start_frame: 30,
            frame_per_state: 15,
        }
    }
}

/// EINK effect configuration
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct EinkConfig {
    #[serde(default)]
    pub barcode: EinkElementConfig,
    #[serde(default)]
    pub classicon: EinkElementConfig,
}

/// Color fade configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ColorFadeConfig {
    pub start_frame: u32,
    pub value_per_frame: u32,
    pub end_value: u32,
}

impl Default for ColorFadeConfig {
    fn default() -> Self {
        Self {
            start_frame: 15,
            value_per_frame: 10,
            end_value: 192,
        }
    }
}

/// Logo fade configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LogoFadeConfig {
    pub start_frame: u32,
    pub value_per_frame: u32,
}

impl Default for LogoFadeConfig {
    fn default() -> Self {
        Self {
            start_frame: 30,
            value_per_frame: 5,
        }
    }
}

/// Bar/line element configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BarLineElementConfig {
    pub start_frame: u32,
    pub frame_count: u32,
}

/// Bars and lines configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BarsLinesConfig {
    #[serde(default)]
    pub ak_bar: BarLineElementConfig,
    #[serde(default)]
    pub upper_line: BarLineElementConfig,
    #[serde(default)]
    pub lower_line: BarLineElementConfig,
    #[serde(default = "default_line_width")]
    pub line_width: u32,
}

fn default_line_width() -> u32 {
    280
}

impl Default for BarLineElementConfig {
    fn default() -> Self {
        Self {
            start_frame: 80,
            frame_count: 40,
        }
    }
}

impl Default for BarsLinesConfig {
    fn default() -> Self {
        Self {
            ak_bar: BarLineElementConfig {
                start_frame: 100,
                frame_count: 40,
            },
            upper_line: BarLineElementConfig {
                start_frame: 80,
                frame_count: 40,
            },
            lower_line: BarLineElementConfig {
                start_frame: 90,
                frame_count: 40,
            },
            line_width: 280,
        }
    }
}

/// Arrow configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ArrowConfig {
    pub y_incr_per_frame: i32,
}

impl Default for ArrowConfig {
    fn default() -> Self {
        Self { y_incr_per_frame: 1 }
    }
}

/// Entry animation configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EntryConfig {
    pub total_frames: u32,
}

impl Default for EntryConfig {
    fn default() -> Self {
        Self { total_frames: 50 }
    }
}

/// Animation configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AnimationConfig {
    #[serde(default = "default_fps")]
    pub fps: u32,
    #[serde(default = "default_step_time_us")]
    pub step_time_us: u32,
    #[serde(default)]
    pub typewriter: TypewriterConfig,
    #[serde(default)]
    pub eink: EinkConfig,
    #[serde(default)]
    pub color_fade: ColorFadeConfig,
    #[serde(default)]
    pub logo_fade: LogoFadeConfig,
    #[serde(default)]
    pub bars_lines: BarsLinesConfig,
    #[serde(default)]
    pub arrow: ArrowConfig,
    #[serde(default)]
    pub entry: EntryConfig,
}

fn default_fps() -> u32 {
    50
}

fn default_step_time_us() -> u32 {
    20000
}

impl Default for AnimationConfig {
    fn default() -> Self {
        Self {
            fps: default_fps(),
            step_time_us: default_step_time_us(),
            typewriter: TypewriterConfig {
                name: TypewriterElementConfig {
                    start_frame: 30,
                    frame_per_char: 3,
                },
                code: TypewriterElementConfig {
                    start_frame: 40,
                    frame_per_char: 3,
                },
                staff: TypewriterElementConfig {
                    start_frame: 40,
                    frame_per_char: 3,
                },
                aux: TypewriterElementConfig {
                    start_frame: 50,
                    frame_per_char: 2,
                },
            },
            eink: EinkConfig {
                barcode: EinkElementConfig {
                    start_frame: 30,
                    frame_per_state: 15,
                },
                classicon: EinkElementConfig {
                    start_frame: 60,
                    frame_per_state: 15,
                },
            },
            color_fade: ColorFadeConfig::default(),
            logo_fade: LogoFadeConfig::default(),
            bars_lines: BarsLinesConfig::default(),
            arrow: ArrowConfig::default(),
            entry: EntryConfig::default(),
        }
    }
}

/// Layout offsets configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LayoutOffsetsConfig {
    pub btm_info_x: u32,
    pub opname_y: u32,
    pub upperline_y: u32,
    pub lowerline_y: u32,
    pub opcode_y: u32,
    pub staff_text_y: u32,
    pub class_icon_y: u32,
    pub ak_bar_y: u32,
    pub aux_text_y: u32,
    pub aux_text_line_height: u32,
    pub arrow_y: u32,
}

impl Default for LayoutOffsetsConfig {
    fn default() -> Self {
        Self {
            btm_info_x: 70,
            opname_y: 415,
            upperline_y: 455,
            lowerline_y: 475,
            opcode_y: 457,
            staff_text_y: 480,
            class_icon_y: 525,
            ak_bar_y: 578,
            aux_text_y: 592,
            aux_text_line_height: 15,
            arrow_y: 100,
        }
    }
}

/// Barcode layout configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BarcodeLayoutConfig {
    pub x: u32,
    pub y: u32,
    pub width: u32,
    pub height: u32,
}

impl Default for BarcodeLayoutConfig {
    fn default() -> Self {
        Self {
            x: 1,
            y: 450,
            width: 50,
            height: 180,
        }
    }
}

/// Size configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SizeConfig {
    pub width: u32,
    pub height: u32,
}

impl Default for SizeConfig {
    fn default() -> Self {
        Self {
            width: 360,
            height: 640,
        }
    }
}

/// Layout configuration
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct LayoutConfig {
    #[serde(default)]
    pub overlay: SizeConfig,
    #[serde(default)]
    pub offsets: LayoutOffsetsConfig,
    #[serde(default)]
    pub barcode: BarcodeLayoutConfig,
    #[serde(default)]
    pub class_icon: SizeConfig,
}

/// Transition configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TransitionAnimConfig {
    #[serde(default = "default_transition_frames")]
    pub default_frames: u32,
    #[serde(default = "default_phase_ratio")]
    pub phase_ratio: [f32; 3],
}

fn default_transition_frames() -> u32 {
    75
}

fn default_phase_ratio() -> [f32; 3] {
    [0.333, 0.333, 0.333]
}

impl Default for TransitionAnimConfig {
    fn default() -> Self {
        Self {
            default_frames: default_transition_frames(),
            phase_ratio: default_phase_ratio(),
        }
    }
}

/// Bezier presets
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BezierPresets {
    pub ease_out: [f32; 4],
    pub ease_in: [f32; 4],
    pub ease_in_out: [f32; 4],
}

impl Default for BezierPresets {
    fn default() -> Self {
        Self {
            ease_out: [0.0, 0.0, 0.58, 1.0],
            ease_in: [0.42, 0.0, 1.0, 1.0],
            ease_in_out: [0.42, 0.0, 0.58, 1.0],
        }
    }
}

/// Main firmware configuration
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct FirmwareConfig {
    #[serde(default = "default_config_version")]
    pub version: i32,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub source: String,
    #[serde(default)]
    pub animation: AnimationConfig,
    #[serde(default)]
    pub layout: LayoutConfig,
    #[serde(default)]
    pub transition: TransitionAnimConfig,
    #[serde(default)]
    pub bezier_presets: BezierPresets,
}

fn default_config_version() -> i32 {
    1
}

impl FirmwareConfig {
    /// Get default configuration (hardcoded values matching Python version)
    pub fn get_default() -> Self {
        Self {
            version: 1,
            name: "default".to_string(),
            source: String::new(),
            animation: AnimationConfig::default(),
            layout: LayoutConfig {
                overlay: SizeConfig {
                    width: 360,
                    height: 640,
                },
                offsets: LayoutOffsetsConfig::default(),
                barcode: BarcodeLayoutConfig::default(),
                class_icon: SizeConfig {
                    width: 50,
                    height: 50,
                },
            },
            transition: TransitionAnimConfig::default(),
            bezier_presets: BezierPresets::default(),
        }
    }

    // Convenience accessors

    pub fn fps(&self) -> u32 {
        self.animation.fps
    }

    pub fn overlay_width(&self) -> u32 {
        self.layout.overlay.width
    }

    pub fn overlay_height(&self) -> u32 {
        self.layout.overlay.height
    }

    pub fn name_start_frame(&self) -> u32 {
        self.animation.typewriter.name.start_frame
    }

    pub fn name_frame_per_char(&self) -> u32 {
        self.animation.typewriter.name.frame_per_char
    }

    pub fn code_start_frame(&self) -> u32 {
        self.animation.typewriter.code.start_frame
    }

    pub fn code_frame_per_char(&self) -> u32 {
        self.animation.typewriter.code.frame_per_char
    }

    pub fn staff_start_frame(&self) -> u32 {
        self.animation.typewriter.staff.start_frame
    }

    pub fn staff_frame_per_char(&self) -> u32 {
        self.animation.typewriter.staff.frame_per_char
    }

    pub fn aux_start_frame(&self) -> u32 {
        self.animation.typewriter.aux.start_frame
    }

    pub fn aux_frame_per_char(&self) -> u32 {
        self.animation.typewriter.aux.frame_per_char
    }

    pub fn barcode_start_frame(&self) -> u32 {
        self.animation.eink.barcode.start_frame
    }

    pub fn barcode_frame_per_state(&self) -> u32 {
        self.animation.eink.barcode.frame_per_state
    }

    pub fn classicon_start_frame(&self) -> u32 {
        self.animation.eink.classicon.start_frame
    }

    pub fn classicon_frame_per_state(&self) -> u32 {
        self.animation.eink.classicon.frame_per_state
    }

    pub fn color_fade_start_frame(&self) -> u32 {
        self.animation.color_fade.start_frame
    }

    pub fn color_fade_value_per_frame(&self) -> u32 {
        self.animation.color_fade.value_per_frame
    }

    pub fn color_fade_end_value(&self) -> u32 {
        self.animation.color_fade.end_value
    }

    pub fn logo_fade_start_frame(&self) -> u32 {
        self.animation.logo_fade.start_frame
    }

    pub fn logo_fade_value_per_frame(&self) -> u32 {
        self.animation.logo_fade.value_per_frame
    }

    pub fn entry_animation_frames(&self) -> u32 {
        self.animation.entry.total_frames
    }

    pub fn btm_info_offset_x(&self) -> u32 {
        self.layout.offsets.btm_info_x
    }

    pub fn opname_offset_y(&self) -> u32 {
        self.layout.offsets.opname_y
    }

    pub fn opcode_offset_y(&self) -> u32 {
        self.layout.offsets.opcode_y
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = FirmwareConfig::get_default();
        assert_eq!(config.fps(), 50);
        assert_eq!(config.overlay_width(), 360);
        assert_eq!(config.overlay_height(), 640);
    }
}
