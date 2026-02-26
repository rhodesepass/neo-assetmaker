//! Animation controller
//!
//! Manages animation state updates for the overlay.

use crate::config::FirmwareConfig;
use crate::app::state::{AnimationState, EinkState};
use crate::render::bezier::ease_in_out;

/// Animation controller
pub struct AnimationController {
    config: FirmwareConfig,
}

impl AnimationController {
    /// Create new animation controller
    pub fn new(config: FirmwareConfig) -> Self {
        Self { config }
    }

    /// Reset animation state
    pub fn reset(&self) -> AnimationState {
        AnimationState {
            arrow_direction: 1,
            ..Default::default()
        }
    }

    /// Start entry animation
    pub fn start_entry_animation(&self) {
        // Entry animation is controlled by frame counter
        // Will be handled in update()
    }

    /// Update animation state for one frame
    pub fn update(&self, state: &mut AnimationState) {
        state.frame_counter += 1;
        let frame = state.frame_counter;

        // Update entry animation
        if !state.is_entry_complete() {
            self.update_entry_animation(state, frame);
        }

        // Update typewriter effects
        self.update_typewriter(state, frame);

        // Update EINK effects
        self.update_eink(state, frame);

        // Update color fade
        self.update_color_fade(state, frame);

        // Update logo fade
        self.update_logo_fade(state, frame);

        // Update bars and lines
        self.update_bars_lines(state, frame);

        // Update arrow animation
        self.update_arrow(state);
    }

    fn update_entry_animation(&self, state: &mut AnimationState, frame: u32) {
        let total_frames = self.config.entry_animation_frames();

        if frame >= total_frames {
            state.entry_progress = 1.0;
            state.entry_y_offset = 0;
        } else {
            let progress = frame as f32 / total_frames as f32;
            state.entry_progress = ease_in_out(progress);
            let height = self.config.overlay_height() as f32;
            state.entry_y_offset = ((1.0 - state.entry_progress) * height) as i32;
        }
    }

    fn update_typewriter(&self, state: &mut AnimationState, frame: u32) {
        // Name: starts at frame 30, 3 frames per char
        let name_start = self.config.name_start_frame();
        let name_fpc = self.config.name_frame_per_char();
        if frame >= name_start {
            state.name_chars = ((frame - name_start) / name_fpc + 1) as usize;
        }

        // Code: starts at frame 40, 3 frames per char
        let code_start = self.config.code_start_frame();
        let code_fpc = self.config.code_frame_per_char();
        if frame >= code_start {
            state.code_chars = ((frame - code_start) / code_fpc + 1) as usize;
        }

        // Staff: starts at frame 40, 3 frames per char
        let staff_start = self.config.staff_start_frame();
        let staff_fpc = self.config.staff_frame_per_char();
        if frame >= staff_start {
            state.staff_chars = ((frame - staff_start) / staff_fpc + 1) as usize;
        }

        // Aux: starts at frame 50, 2 frames per char
        let aux_start = self.config.aux_start_frame();
        let aux_fpc = self.config.aux_frame_per_char();
        if frame >= aux_start {
            state.aux_chars = ((frame - aux_start) / aux_fpc + 1) as usize;
        }
    }

    fn update_eink(&self, state: &mut AnimationState, frame: u32) {
        // Barcode: starts at frame 30, 15 frames per state
        state.barcode_state = EinkState::from_frame(
            frame,
            self.config.barcode_start_frame(),
            self.config.barcode_frame_per_state(),
        );

        // Class icon: starts at frame 60, 15 frames per state
        state.classicon_state = EinkState::from_frame(
            frame,
            self.config.classicon_start_frame(),
            self.config.classicon_frame_per_state(),
        );
    }

    fn update_color_fade(&self, state: &mut AnimationState, frame: u32) {
        let start = self.config.color_fade_start_frame();
        let per_frame = self.config.color_fade_value_per_frame();
        let end_value = self.config.color_fade_end_value();

        if frame >= start {
            let elapsed = frame - start;
            state.color_fade_radius = (elapsed * per_frame).min(end_value);
        }
    }

    fn update_logo_fade(&self, state: &mut AnimationState, frame: u32) {
        let start = self.config.logo_fade_start_frame();
        let per_frame = self.config.logo_fade_value_per_frame();

        if frame >= start {
            let elapsed = frame - start;
            state.logo_alpha = (elapsed * per_frame).min(255) as u8;
        }
    }

    fn update_bars_lines(&self, state: &mut AnimationState, frame: u32) {
        let line_width = self.config.animation.bars_lines.line_width;

        // AK bar: starts at frame 100, 40 frames to complete
        let ak_start = self.config.animation.bars_lines.ak_bar.start_frame;
        let ak_frames = self.config.animation.bars_lines.ak_bar.frame_count;
        state.ak_bar_width = self.calculate_bar_width(frame, ak_start, ak_frames, line_width);

        // Upper line: starts at frame 80, 40 frames
        let upper_start = self.config.animation.bars_lines.upper_line.start_frame;
        let upper_frames = self.config.animation.bars_lines.upper_line.frame_count;
        state.upper_line_width = self.calculate_bar_width(frame, upper_start, upper_frames, line_width);

        // Lower line: starts at frame 90, 40 frames
        let lower_start = self.config.animation.bars_lines.lower_line.start_frame;
        let lower_frames = self.config.animation.bars_lines.lower_line.frame_count;
        state.lower_line_width = self.calculate_bar_width(frame, lower_start, lower_frames, line_width);
    }

    fn calculate_bar_width(&self, frame: u32, start: u32, frame_count: u32, target: u32) -> u32 {
        if frame < start {
            return 0;
        }

        let elapsed = frame - start;
        if elapsed >= frame_count {
            return target;
        }

        let progress = elapsed as f32 / frame_count as f32;
        let eased = ease_in_out(progress);
        (eased * target as f32) as u32
    }

    fn update_arrow(&self, state: &mut AnimationState) {
        // Per C reference (opinfo.c:553): arrow_y_value DECREMENTS to scroll upward
        // data->arrow_y_value -= OVERLAY_ANIMATION_OPINFO_ARROW_Y_INCR_PER_FRAME;
        let incr = self.config.animation.arrow.y_incr_per_frame;
        state.arrow_y -= incr;

        // Loop back to height when reaching 0 (continuous upward scroll)
        const ARROW_HEIGHT: i32 = 36;
        if state.arrow_y <= 0 {
            state.arrow_y = ARROW_HEIGHT;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_animation_update() {
        let config = FirmwareConfig::get_default();
        let controller = AnimationController::new(config);
        let mut state = controller.reset();

        // Update a few frames
        for _ in 0..50 {
            controller.update(&mut state);
        }

        assert_eq!(state.frame_counter, 50);
        // Entry should be complete after 50 frames
        assert!(state.is_entry_complete());
    }
}
