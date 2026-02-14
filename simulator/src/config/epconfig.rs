//! EPConfig data structure
//!
//! Corresponds to Python's config/epconfig.py

use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::path::Path;
use uuid::Uuid;

/// Screen resolution type
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum ScreenType {
    #[default]
    #[serde(rename = "360x640")]
    S360x640,
    #[serde(rename = "480x854")]
    S480x854,
    #[serde(rename = "720x1080")]
    S720x1080,
}

impl ScreenType {
    pub fn dimensions(&self) -> (u32, u32) {
        match self {
            ScreenType::S360x640 => (360, 640),
            ScreenType::S480x854 => (480, 854),
            ScreenType::S720x1080 => (720, 1080),
        }
    }
}

/// Transition effect type
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum TransitionType {
    #[default]
    None,
    Fade,
    Move,
    Swipe,
}

/// Overlay UI type
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum OverlayType {
    #[default]
    None,
    Arknights,
    Image,
}

/// Transition options
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TransitionOptions {
    /// Duration in microseconds (default: 500000 = 0.5s)
    #[serde(default = "default_transition_duration")]
    pub duration: i64,

    /// Optional transition image path
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub image: String,

    /// Background color in hex format (e.g., "#000000")
    #[serde(default = "default_background_color")]
    pub background_color: String,
}

fn default_transition_duration() -> i64 {
    500000
}

fn default_background_color() -> String {
    "#000000".to_string()
}

impl Default for TransitionOptions {
    fn default() -> Self {
        Self {
            duration: default_transition_duration(),
            image: String::new(),
            background_color: default_background_color(),
        }
    }
}

/// Transition configuration
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Transition {
    #[serde(rename = "type", default)]
    pub transition_type: TransitionType,

    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub options: Option<TransitionOptions>,
}

/// Loop video configuration
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct LoopConfig {
    /// Video file path
    #[serde(default)]
    pub file: String,

    /// True if using image mode instead of video
    #[serde(default)]
    pub is_image: bool,
}

/// Intro video configuration
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct IntroConfig {
    /// Whether intro is enabled
    #[serde(default)]
    pub enabled: bool,

    /// Intro video file path
    #[serde(default)]
    pub file: String,

    /// Duration in microseconds (default: 5000000 = 5s)
    #[serde(default = "default_intro_duration")]
    pub duration: i64,
}

fn default_intro_duration() -> i64 {
    5000000
}

/// Arknights overlay UI options
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ArknightsOverlayOptions {
    /// Time to appear in microseconds
    #[serde(default = "default_appear_time")]
    pub appear_time: i64,

    /// Operator name (uppercase)
    #[serde(default = "default_operator_name")]
    pub operator_name: String,

    /// Custom text for top-left area (replaces Rhodes logo when non-empty)
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub top_left_rhodes: String,

    /// Custom text for top-right bar (replaces embedded text when non-empty)
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub top_right_bar_text: String,

    /// Operator code
    #[serde(default = "default_operator_code")]
    pub operator_code: String,

    /// Barcode text
    #[serde(default = "default_barcode_text")]
    pub barcode_text: String,

    /// Auxiliary text (multiline)
    #[serde(default = "default_aux_text")]
    pub aux_text: String,

    /// Staff text
    #[serde(default = "default_staff_text")]
    pub staff_text: String,

    /// Theme color in hex format
    #[serde(default = "default_color")]
    pub color: String,

    /// Optional logo image path
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub logo: String,

    /// Optional operator class icon path
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub operator_class_icon: String,
}

fn default_appear_time() -> i64 {
    100000
}

fn default_operator_name() -> String {
    "OPERATOR".to_string()
}

fn default_operator_code() -> String {
    "ARKNIGHTS - UNK0".to_string()
}

fn default_barcode_text() -> String {
    "OPERATOR - ARKNIGHTS".to_string()
}

fn default_aux_text() -> String {
    "Operator of Rhodes Island\nUndefined/Rhodes Island\n Hypergryph".to_string()
}

fn default_staff_text() -> String {
    "STAFF".to_string()
}

fn default_color() -> String {
    "#000000".to_string()
}

impl Default for ArknightsOverlayOptions {
    fn default() -> Self {
        Self {
            appear_time: default_appear_time(),
            operator_name: default_operator_name(),
            top_left_rhodes: String::new(),
            top_right_bar_text: String::new(),
            operator_code: default_operator_code(),
            barcode_text: default_barcode_text(),
            aux_text: default_aux_text(),
            staff_text: default_staff_text(),
            color: default_color(),
            logo: String::new(),
            operator_class_icon: String::new(),
        }
    }
}

/// Image overlay options
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ImageOverlayOptions {
    /// Time to appear in microseconds
    #[serde(default = "default_appear_time")]
    pub appear_time: i64,

    /// Display duration in microseconds
    #[serde(default = "default_appear_time")]
    pub duration: i64,

    /// Image path
    #[serde(default)]
    pub image: String,
}

/// Overlay configuration
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Overlay {
    #[serde(rename = "type", default)]
    pub overlay_type: OverlayType,

    /// Options - interpreted based on overlay_type
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub options: Option<serde_json::Value>,
}

impl Overlay {
    /// Get Arknights overlay options if type is Arknights
    pub fn arknights_options(&self) -> Option<ArknightsOverlayOptions> {
        if self.overlay_type == OverlayType::Arknights {
            self.options
                .as_ref()
                .and_then(|v| serde_json::from_value(v.clone()).ok())
        } else {
            None
        }
    }

    /// Get Image overlay options if type is Image
    pub fn image_options(&self) -> Option<ImageOverlayOptions> {
        if self.overlay_type == OverlayType::Image {
            self.options
                .as_ref()
                .and_then(|v| serde_json::from_value(v.clone()).ok())
        } else {
            None
        }
    }
}

/// EPConfig - Complete material configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EPConfig {
    /// Config version
    #[serde(default = "default_version")]
    pub version: i32,

    /// Unique identifier
    #[serde(default = "default_uuid")]
    pub uuid: String,

    /// Material name
    #[serde(default)]
    pub name: String,

    /// Description
    #[serde(default)]
    pub description: String,

    /// Icon path
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub icon: String,

    /// Screen resolution
    #[serde(default)]
    pub screen: ScreenType,

    /// Loop video configuration
    #[serde(default, rename = "loop")]
    pub loop_config: LoopConfig,

    /// Intro video configuration
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub intro: Option<IntroConfig>,

    /// Transition in effect
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub transition_in: Option<Transition>,

    /// Transition loop effect
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub transition_loop: Option<Transition>,

    /// Overlay configuration
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub overlay: Option<Overlay>,
}

fn default_version() -> i32 {
    1
}

fn default_uuid() -> String {
    Uuid::new_v4().to_string()
}

impl Default for EPConfig {
    fn default() -> Self {
        Self {
            version: default_version(),
            uuid: default_uuid(),
            name: String::new(),
            description: String::new(),
            icon: String::new(),
            screen: ScreenType::default(),
            loop_config: LoopConfig::default(),
            intro: None,
            transition_in: None,
            transition_loop: None,
            overlay: None,
        }
    }
}

impl EPConfig {
    /// Load configuration from JSON file
    pub fn load_from_file<P: AsRef<Path>>(path: P) -> Result<Self> {
        let content = std::fs::read_to_string(path)?;
        let config: EPConfig = serde_json::from_str(&content)?;
        Ok(config)
    }

    /// Get transition in type
    pub fn get_transition_in_type(&self) -> TransitionType {
        self.transition_in
            .as_ref()
            .map(|t| t.transition_type)
            .unwrap_or(TransitionType::None)
    }

    /// Get transition loop type
    pub fn get_transition_loop_type(&self) -> TransitionType {
        self.transition_loop
            .as_ref()
            .map(|t| t.transition_type)
            .unwrap_or(TransitionType::None)
    }

    /// Get transition in duration in microseconds
    pub fn get_transition_in_duration(&self) -> i64 {
        self.transition_in
            .as_ref()
            .and_then(|t| t.options.as_ref())
            .map(|o| o.duration)
            .unwrap_or(500000)
    }

    /// Get transition loop duration in microseconds
    pub fn get_transition_loop_duration(&self) -> i64 {
        self.transition_loop
            .as_ref()
            .and_then(|t| t.options.as_ref())
            .map(|o| o.duration)
            .unwrap_or(500000)
    }

    /// Get appear time in microseconds
    pub fn get_appear_time(&self) -> i64 {
        self.overlay
            .as_ref()
            .and_then(|o| o.arknights_options())
            .map(|a| a.appear_time)
            .unwrap_or(100000)
    }

    /// Check if intro is enabled
    pub fn has_intro(&self) -> bool {
        self.intro.as_ref().map(|i| i.enabled).unwrap_or(false)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = EPConfig::default();
        assert_eq!(config.version, 1);
        assert_eq!(config.screen, ScreenType::S360x640);
    }

    #[test]
    fn test_screen_dimensions() {
        assert_eq!(ScreenType::S360x640.dimensions(), (360, 640));
        assert_eq!(ScreenType::S480x854.dimensions(), (480, 854));
        assert_eq!(ScreenType::S720x1080.dimensions(), (720, 1080));
    }
}
