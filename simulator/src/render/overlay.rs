//! Overlay renderer
//!
//! Renders the Arknights-style overlay UI.
//! Corresponds to Python's core/overlay_animator.py

use crate::config::FirmwareConfig;
use crate::app::state::AnimationState;

/// Overlay renderer
pub struct OverlayRenderer {
    config: FirmwareConfig,
}

impl OverlayRenderer {
    /// Create new overlay renderer
    pub fn new(config: FirmwareConfig) -> Self {
        Self { config }
    }

    /// Get overlay dimensions
    pub fn dimensions(&self) -> (u32, u32) {
        (self.config.overlay_width(), self.config.overlay_height())
    }

    /// Calculate entry animation Y offset
    ///
    /// Uses ease-in-out for smooth entry from bottom.
    pub fn calculate_entry_offset(&self, progress: f32) -> i32 {
        let height = self.config.overlay_height() as f32;
        let eased = super::bezier::ease_in_out(progress);
        ((1.0 - eased) * height) as i32
    }

    /// Calculate color fade radius
    pub fn calculate_color_fade_radius(&self, frame: u32) -> u32 {
        let start = self.config.color_fade_start_frame();
        let per_frame = self.config.color_fade_value_per_frame();
        let end_value = self.config.color_fade_end_value();

        if frame < start {
            return 0;
        }

        let elapsed = frame - start;
        (elapsed * per_frame).min(end_value)
    }

    /// Calculate logo alpha
    pub fn calculate_logo_alpha(&self, frame: u32) -> u8 {
        let start = self.config.logo_fade_start_frame();
        let per_frame = self.config.logo_fade_value_per_frame();

        if frame < start {
            return 0;
        }

        let elapsed = frame - start;
        (elapsed * per_frame).min(255) as u8
    }

    /// Calculate bar/line width using bezier easing
    pub fn calculate_bar_width(&self, frame: u32, start_frame: u32, frame_count: u32, target_width: u32) -> u32 {
        if frame < start_frame {
            return 0;
        }

        let elapsed = frame - start_frame;
        if elapsed >= frame_count {
            return target_width;
        }

        let progress = elapsed as f32 / frame_count as f32;
        let eased = super::bezier::ease_in_out(progress);
        (eased * target_width as f32) as u32
    }

    /// Calculate typewriter visible characters
    pub fn calculate_typewriter_chars(&self, frame: u32, text_len: usize, start_frame: u32, frame_per_char: u32) -> usize {
        if frame < start_frame {
            return 0;
        }

        let elapsed = frame - start_frame;
        let chars = (elapsed / frame_per_char + 1) as usize;
        chars.min(text_len)
    }

    /// Update animation state for current frame
    pub fn update_animation_state(&self, state: &mut AnimationState, name_len: usize, code_len: usize, staff_len: usize, aux_len: usize) {
        let frame = state.frame_counter;

        // Typewriter effects
        state.name_chars = self.calculate_typewriter_chars(
            frame, name_len,
            self.config.name_start_frame(),
            self.config.name_frame_per_char()
        );
        state.code_chars = self.calculate_typewriter_chars(
            frame, code_len,
            self.config.code_start_frame(),
            self.config.code_frame_per_char()
        );
        state.staff_chars = self.calculate_typewriter_chars(
            frame, staff_len,
            self.config.staff_start_frame(),
            self.config.staff_frame_per_char()
        );
        state.aux_chars = self.calculate_typewriter_chars(
            frame, aux_len,
            self.config.aux_start_frame(),
            self.config.aux_frame_per_char()
        );

        // Color fade
        state.color_fade_radius = self.calculate_color_fade_radius(frame);

        // Logo alpha
        state.logo_alpha = self.calculate_logo_alpha(frame);

        // Progress bar and lines
        let line_width = self.config.animation.bars_lines.line_width;
        state.ak_bar_width = self.calculate_bar_width(
            frame,
            self.config.animation.bars_lines.ak_bar.start_frame,
            self.config.animation.bars_lines.ak_bar.frame_count,
            line_width
        );
        state.upper_line_width = self.calculate_bar_width(
            frame,
            self.config.animation.bars_lines.upper_line.start_frame,
            self.config.animation.bars_lines.upper_line.frame_count,
            line_width
        );
        state.lower_line_width = self.calculate_bar_width(
            frame,
            self.config.animation.bars_lines.lower_line.start_frame,
            self.config.animation.bars_lines.lower_line.frame_count,
            line_width
        );

        // Arrow animation - decrement to scroll upward (per C reference opinfo.c:553)
        let arrow_incr = self.config.animation.arrow.y_incr_per_frame;
        state.arrow_y -= arrow_incr;

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
    fn test_entry_offset() {
        let config = FirmwareConfig::get_default();
        let renderer = OverlayRenderer::new(config);

        // At start (progress=0), offset = height
        let offset = renderer.calculate_entry_offset(0.0);
        assert_eq!(offset, 640);

        // At end (progress=1), offset = 0
        let offset = renderer.calculate_entry_offset(1.0);
        assert_eq!(offset, 0);
    }

    #[test]
    fn test_color_fade() {
        let config = FirmwareConfig::get_default();
        let renderer = OverlayRenderer::new(config);

        // Before start frame
        assert_eq!(renderer.calculate_color_fade_radius(10), 0);

        // After start frame (15), per frame = 10
        assert_eq!(renderer.calculate_color_fade_radius(16), 10);
        assert_eq!(renderer.calculate_color_fade_radius(17), 20);

        // Should cap at end_value (192)
        assert_eq!(renderer.calculate_color_fade_radius(100), 192);
    }

    #[test]
    fn test_typewriter() {
        let config = FirmwareConfig::get_default();
        let renderer = OverlayRenderer::new(config);

        // Name: starts at frame 30, 3 frames per char
        assert_eq!(renderer.calculate_typewriter_chars(29, 10, 30, 3), 0);
        assert_eq!(renderer.calculate_typewriter_chars(30, 10, 30, 3), 1);
        assert_eq!(renderer.calculate_typewriter_chars(33, 10, 30, 3), 2);
        assert_eq!(renderer.calculate_typewriter_chars(100, 10, 30, 3), 10); // capped
    }
}
