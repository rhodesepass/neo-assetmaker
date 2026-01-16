//! IPC protocol definitions
//!
//! Defines message formats for communication with the Python editor.

use serde::{Deserialize, Serialize};
use crate::config::EPConfig;
use crate::app::state::PlayState;

/// Control commands from editor to simulator
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ControlCommand {
    /// Start playback
    Play,
    /// Pause playback
    Pause,
    /// Stop and reset
    Stop,
    /// Reset to initial state
    Reset,
    /// Seek to specific state
    SeekTo(u8),
}

/// IPC message types
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", content = "payload")]
pub enum IpcMessage {
    // === Editor -> Simulator ===

    /// Load configuration
    #[serde(rename = "load_config")]
    LoadConfig {
        config: EPConfig,
        base_dir: String,
    },

    /// Control command
    #[serde(rename = "control")]
    Control(ControlCommand),

    /// Update transition settings
    #[serde(rename = "set_transition")]
    SetTransition {
        transition_in: String,
        transition_loop: String,
    },

    /// Shutdown simulator
    #[serde(rename = "shutdown")]
    Shutdown,

    // === Simulator -> Editor ===

    /// State update notification
    #[serde(rename = "state_update")]
    StateUpdate {
        state: u8,
        frame: u64,
        is_playing: bool,
    },

    /// Simulator ready
    #[serde(rename = "ready")]
    Ready,

    /// Error occurred
    #[serde(rename = "error")]
    Error {
        code: i32,
        message: String,
    },
}

impl IpcMessage {
    /// Create a state update message
    pub fn state_update(state: PlayState, frame: u64, is_playing: bool) -> Self {
        IpcMessage::StateUpdate {
            state: state as u8,
            frame,
            is_playing,
        }
    }

    /// Create a ready message
    pub fn ready() -> Self {
        IpcMessage::Ready
    }

    /// Create an error message
    pub fn error(code: i32, message: impl Into<String>) -> Self {
        IpcMessage::Error {
            code,
            message: message.into(),
        }
    }

    /// Serialize to JSON string (line-delimited)
    pub fn to_json(&self) -> Result<String, serde_json::Error> {
        serde_json::to_string(self)
    }

    /// Deserialize from JSON string
    pub fn from_json(s: &str) -> Result<Self, serde_json::Error> {
        serde_json::from_str(s)
    }
}

/// Error codes
pub mod error_codes {
    pub const OK: i32 = 0;
    pub const INVALID_CONFIG: i32 = 1;
    pub const VIDEO_LOAD_FAILED: i32 = 2;
    pub const INTERNAL_ERROR: i32 = 100;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_message_serialization() {
        let msg = IpcMessage::ready();
        let json = msg.to_json().unwrap();
        assert!(json.contains("ready"));

        let parsed = IpcMessage::from_json(&json).unwrap();
        assert!(matches!(parsed, IpcMessage::Ready));
    }

    #[test]
    fn test_control_command() {
        let msg = IpcMessage::Control(ControlCommand::Play);
        let json = msg.to_json().unwrap();
        assert!(json.contains("play"));
    }
}
