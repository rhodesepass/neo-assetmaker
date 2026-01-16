//! Transition effect renderer
//!
//! Implements FADE, MOVE, and SWIPE transition effects.
//! Corresponds to Python's core/transition_renderer.py

use crate::config::{FirmwareConfig, TransitionType};
use crate::app::state::TransitionPhase;
use super::bezier::{ease_in, ease_out, ease_in_out, precompute_swipe_bezier};

/// Transition renderer
pub struct TransitionRenderer {
    config: FirmwareConfig,
    /// Precomputed bezier values for SWIPE effect
    swipe_bezier_values: Vec<i32>,
}

impl TransitionRenderer {
    /// Create new transition renderer
    pub fn new(config: FirmwareConfig) -> Self {
        let height = config.overlay_height();
        let swipe_bezier_values = precompute_swipe_bezier(height);

        Self {
            config,
            swipe_bezier_values,
        }
    }

    /// Get phase from progress
    pub fn get_phase(&self, progress: f32) -> TransitionPhase {
        TransitionPhase::from_progress(progress)
    }

    /// Calculate FADE alpha value
    ///
    /// Phase 1: alpha 0 -> 255 (fade in)
    /// Phase 2: alpha = 255 (hold)
    /// Phase 3: alpha 255 -> 0 (fade out)
    pub fn calculate_fade_alpha(&self, progress: f32) -> u8 {
        let phase = self.get_phase(progress);

        match phase {
            TransitionPhase::PhaseIn => {
                // 0 to 1/3 -> alpha 0 to 255
                let phase_progress = progress / 0.333;
                (phase_progress * 255.0).min(255.0) as u8
            }
            TransitionPhase::PhaseHold => 255,
            TransitionPhase::PhaseOut => {
                // 2/3 to 1 -> alpha 255 to 0
                let phase_progress = (progress - 0.667) / 0.333;
                ((1.0 - phase_progress) * 255.0).max(0.0) as u8
            }
            TransitionPhase::PhaseDone => 0,
        }
    }

    /// Calculate MOVE x-offset
    ///
    /// Phase 1: ease-out from right (x: width -> 0)
    /// Phase 2: x = 0 (hold)
    /// Phase 3: ease-in to left (x: 0 -> -width)
    pub fn calculate_move_offset(&self, progress: f32) -> i32 {
        let width = self.config.overlay_width() as i32;
        let phase = self.get_phase(progress);

        match phase {
            TransitionPhase::PhaseIn => {
                // ease-out: fast start, slow end
                let phase_progress = progress / 0.333;
                let eased = ease_out(phase_progress);
                ((1.0 - eased) * width as f32) as i32
            }
            TransitionPhase::PhaseHold => 0,
            TransitionPhase::PhaseOut => {
                // ease-in: slow start, fast end
                let phase_progress = (progress - 0.667) / 0.333;
                let eased = ease_in(phase_progress);
                -(eased * width as f32) as i32
            }
            TransitionPhase::PhaseDone => -width,
        }
    }

    /// Calculate SWIPE progress
    ///
    /// Phase 1: ease-in-out sweep from left to right (reveal)
    /// Phase 2: fully revealed (hold)
    /// Phase 3: ease-in-out sweep from left to right (hide)
    pub fn calculate_swipe_progress(&self, progress: f32) -> f32 {
        let phase = self.get_phase(progress);

        match phase {
            TransitionPhase::PhaseIn => {
                let phase_progress = progress / 0.333;
                ease_in_out(phase_progress)
            }
            TransitionPhase::PhaseHold => 1.0,
            TransitionPhase::PhaseOut => {
                let phase_progress = (progress - 0.667) / 0.333;
                1.0 - ease_in_out(phase_progress)
            }
            TransitionPhase::PhaseDone => 0.0,
        }
    }

    /// Get precomputed SWIPE bezier value for a scanline
    pub fn get_swipe_bezier_value(&self, y: u32) -> i32 {
        self.swipe_bezier_values
            .get(y as usize)
            .copied()
            .unwrap_or(0)
    }

    /// Get transition name
    pub fn get_transition_name(transition_type: TransitionType) -> &'static str {
        match transition_type {
            TransitionType::Fade => "fade",
            TransitionType::Move => "move",
            TransitionType::Swipe => "swipe",
            TransitionType::None => "none",
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_fade_alpha() {
        let config = FirmwareConfig::get_default();
        let renderer = TransitionRenderer::new(config);

        // Start: alpha = 0
        assert_eq!(renderer.calculate_fade_alpha(0.0), 0);
        // Middle of phase 1: alpha ~127
        let alpha = renderer.calculate_fade_alpha(0.166);
        assert!(alpha > 100 && alpha < 150);
        // End of phase 1 / start of phase 2: alpha = 255
        assert_eq!(renderer.calculate_fade_alpha(0.333), 255);
        // Phase 2: alpha = 255
        assert_eq!(renderer.calculate_fade_alpha(0.5), 255);
        // End of phase 3: alpha = 0
        assert_eq!(renderer.calculate_fade_alpha(1.0), 0);
    }

    #[test]
    fn test_move_offset() {
        let config = FirmwareConfig::get_default();
        let renderer = TransitionRenderer::new(config);
        let width = config.overlay_width() as i32;

        // Start: x = width (from right)
        assert_eq!(renderer.calculate_move_offset(0.0), width);
        // Phase 2: x = 0
        assert_eq!(renderer.calculate_move_offset(0.5), 0);
        // End: x = -width (to left)
        assert_eq!(renderer.calculate_move_offset(1.0), -width);
    }

    #[test]
    fn test_swipe_progress() {
        let config = FirmwareConfig::get_default();
        let renderer = TransitionRenderer::new(config);

        // Start: 0
        assert!((renderer.calculate_swipe_progress(0.0) - 0.0).abs() < 0.01);
        // Phase 2: 1
        assert!((renderer.calculate_swipe_progress(0.5) - 1.0).abs() < 0.01);
        // End: 0
        assert!((renderer.calculate_swipe_progress(1.0) - 0.0).abs() < 0.01);
    }
}
