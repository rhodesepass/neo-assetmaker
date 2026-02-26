//! Playback state machine
//!
//! Implements the 6-state playback flow matching the firmware behavior.

use crate::config::TransitionType;

/// Playback state - matches firmware prts_state_t
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[repr(u8)]
pub enum PlayState {
    /// Idle state
    #[default]
    Idle = 0,
    /// Transition in effect (entry transition)
    TransitionIn = 1,
    /// Intro video playback
    Intro = 2,
    /// Transition loop effect
    TransitionLoop = 3,
    /// Waiting for appear_time before showing overlay
    PreOpinfo = 4,
    /// Loop video + overlay animation
    Loop = 5,
}

impl PlayState {
    /// Get display name for the state
    pub fn display_name(&self) -> &'static str {
        match self {
            PlayState::Idle => "Idle",
            PlayState::TransitionIn => "Transition In",
            PlayState::Intro => "Intro",
            PlayState::TransitionLoop => "Transition Loop",
            PlayState::PreOpinfo => "Pre-Opinfo",
            PlayState::Loop => "Loop",
        }
    }

    /// Get Chinese display name
    pub fn display_name_zh(&self) -> &'static str {
        match self {
            PlayState::Idle => "空闲",
            PlayState::TransitionIn => "入场过渡",
            PlayState::Intro => "入场视频",
            PlayState::TransitionLoop => "循环过渡",
            PlayState::PreOpinfo => "等待显示",
            PlayState::Loop => "循环播放",
        }
    }

    /// Create PlayState from u8 value
    pub fn from_u8(value: u8) -> Option<Self> {
        match value {
            0 => Some(PlayState::Idle),
            1 => Some(PlayState::TransitionIn),
            2 => Some(PlayState::Intro),
            3 => Some(PlayState::TransitionLoop),
            4 => Some(PlayState::PreOpinfo),
            5 => Some(PlayState::Loop),
            _ => None,
        }
    }
}

/// Transition phase within a transition effect
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum TransitionPhase {
    /// Phase 1: Entry (0 ~ 1/3)
    #[default]
    PhaseIn,
    /// Phase 2: Hold (1/3 ~ 2/3) - video switch happens here
    PhaseHold,
    /// Phase 3: Exit (2/3 ~ 1)
    PhaseOut,
    /// Transition complete
    PhaseDone,
}

impl TransitionPhase {
    /// Get phase from progress (0.0 to 1.0)
    pub fn from_progress(progress: f32) -> Self {
        if progress >= 1.0 {
            TransitionPhase::PhaseDone
        } else if progress >= 0.667 {
            TransitionPhase::PhaseOut
        } else if progress >= 0.333 {
            TransitionPhase::PhaseHold
        } else {
            TransitionPhase::PhaseIn
        }
    }
}

/// EINK animation state
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[repr(u8)]
pub enum EinkState {
    FirstBlack = 0,
    FirstWhite = 1,
    SecondBlack = 2,
    SecondWhite = 3,
    #[default]
    Idle = 4,
    Content = 5,
}

impl EinkState {
    /// Get state from frame index
    pub fn from_frame(frame: u32, start_frame: u32, frame_per_state: u32) -> Self {
        if frame < start_frame {
            return EinkState::Idle;
        }

        let eink_frame = frame - start_frame;
        let state_index = eink_frame / frame_per_state;

        match state_index {
            0 => EinkState::FirstBlack,
            1 => EinkState::FirstWhite,
            2 => EinkState::SecondBlack,
            3 => EinkState::SecondWhite,
            4 => EinkState::Idle,
            _ => EinkState::Content,
        }
    }

    /// Check if EINK effect is showing content
    pub fn is_content(&self) -> bool {
        matches!(self, EinkState::Content)
    }

    /// Check if EINK effect is in a black state
    pub fn is_black(&self) -> bool {
        matches!(self, EinkState::FirstBlack | EinkState::SecondBlack)
    }

    /// Check if EINK effect is in a white state
    pub fn is_white(&self) -> bool {
        matches!(self, EinkState::FirstWhite | EinkState::SecondWhite)
    }
}

/// Animation state for overlay effects
#[derive(Debug, Clone, Default)]
pub struct AnimationState {
    /// Frame counter
    pub frame_counter: u32,

    // Typewriter effect - visible character counts
    pub name_chars: usize,
    pub code_chars: usize,
    pub staff_chars: usize,
    pub aux_chars: usize,

    // EINK states
    pub barcode_state: EinkState,
    pub classicon_state: EinkState,

    // Color fade radius
    pub color_fade_radius: u32,

    // Logo alpha (0-255)
    pub logo_alpha: u8,

    // Progress bar / divider widths
    pub ak_bar_width: u32,
    pub upper_line_width: u32,
    pub lower_line_width: u32,

    // Arrow Y offset (cycles)
    pub arrow_y: i32,
    pub arrow_direction: i32, // 1 or -1

    // Entry animation progress (0.0 to 1.0)
    pub entry_progress: f32,
    pub entry_y_offset: i32,

    // Entry animation started
    pub entry_started: bool,
}

impl AnimationState {
    /// Reset animation state
    pub fn reset(&mut self) {
        *self = Self::default();
        self.arrow_direction = 1;
    }

    /// Check if entry animation is complete
    pub fn is_entry_complete(&self) -> bool {
        self.entry_progress >= 1.0
    }
}

/// Transition state
#[derive(Debug, Clone, Default)]
pub struct TransitionState {
    /// Current frame in transition
    pub frame: u32,
    /// Total frames for transition
    pub total_frames: u32,
    /// Transition type
    pub transition_type: TransitionType,
    /// Whether video has been switched during hold phase
    pub video_switched: bool,
}

impl TransitionState {
    /// Get current progress (0.0 to 1.0)
    pub fn progress(&self) -> f32 {
        if self.total_frames == 0 {
            return 1.0;
        }
        (self.frame as f32 / self.total_frames as f32).min(1.0)
    }

    /// Get current phase
    pub fn phase(&self) -> TransitionPhase {
        TransitionPhase::from_progress(self.progress())
    }

    /// Check if transition is complete
    pub fn is_complete(&self) -> bool {
        self.frame >= self.total_frames
    }

    /// Reset transition state
    pub fn reset(&mut self, transition_type: TransitionType, total_frames: u32) {
        self.frame = 0;
        self.total_frames = total_frames;
        self.transition_type = transition_type;
        self.video_switched = false;
    }
}

/// Complete simulator state
#[derive(Debug, Clone, Default)]
pub struct SimulatorState {
    /// Current playback state
    pub play_state: PlayState,
    /// Global frame counter
    pub frame_counter: u64,
    /// Is currently playing
    pub is_playing: bool,
    /// Is first switch (firmware forces SWIPE on first transition)
    pub is_first_switch: bool,

    /// Transition effect state
    pub transition: TransitionState,
    /// Animation state
    pub animation: AnimationState,

    /// Pre-opinfo counter (frames waiting for appear_time)
    pub pre_opinfo_counter: u32,
    /// Appear time in frames
    pub appear_time_frames: u32,

    /// Loop video frame accumulator (microseconds) for FPS sync
    pub loop_frame_accumulator: i64,
    /// Intro video frame accumulator (microseconds) for FPS sync
    pub intro_frame_accumulator: i64,
}

impl SimulatorState {
    /// Create new simulator state
    pub fn new() -> Self {
        Self {
            is_first_switch: true,
            animation: AnimationState {
                arrow_direction: 1,
                ..Default::default()
            },
            ..Default::default()
        }
    }

    /// Reset to initial state
    pub fn reset(&mut self) {
        let appear_time = self.appear_time_frames;
        *self = Self::new();
        self.appear_time_frames = appear_time;
    }

    /// Start playback
    pub fn start_playback(&mut self, has_intro: bool, transition_type: TransitionType, total_frames: u32) {
        self.is_playing = true;
        self.frame_counter = 0;
        self.animation.reset();

        // Determine initial state based on whether intro exists
        if has_intro {
            self.play_state = PlayState::TransitionIn;
        } else {
            self.play_state = PlayState::TransitionLoop;
        }

        // Firmware behavior: first transition is always SWIPE
        let actual_type = if self.is_first_switch {
            self.is_first_switch = false;
            TransitionType::Swipe
        } else {
            transition_type
        };

        self.transition.reset(actual_type, total_frames);
    }

    /// Pause playback
    pub fn pause(&mut self) {
        self.is_playing = false;
    }

    /// Resume playback
    pub fn resume(&mut self) {
        self.is_playing = true;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_play_state_names() {
        assert_eq!(PlayState::Idle.display_name(), "Idle");
        assert_eq!(PlayState::Loop.display_name_zh(), "循环播放");
    }

    #[test]
    fn test_transition_phase() {
        assert_eq!(TransitionPhase::from_progress(0.0), TransitionPhase::PhaseIn);
        assert_eq!(TransitionPhase::from_progress(0.5), TransitionPhase::PhaseHold);
        assert_eq!(TransitionPhase::from_progress(0.8), TransitionPhase::PhaseOut);
        assert_eq!(TransitionPhase::from_progress(1.0), TransitionPhase::PhaseDone);
    }

    #[test]
    fn test_eink_state() {
        // Before start
        assert_eq!(EinkState::from_frame(10, 30, 15), EinkState::Idle);
        // First black
        assert_eq!(EinkState::from_frame(30, 30, 15), EinkState::FirstBlack);
        // Content after all states
        assert_eq!(EinkState::from_frame(120, 30, 15), EinkState::Content);
    }
}
