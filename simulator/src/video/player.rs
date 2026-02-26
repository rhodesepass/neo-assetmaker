//! Video player module
//!
//! High-level video player that manages loop and intro videos.

use std::path::{Path, PathBuf};
use image::RgbImage;
use tracing::{info, warn, error};

use crate::config::EPConfig;
use super::decoder::VideoDecoder;

/// Video player that manages playback of loop and intro videos
pub struct VideoPlayer {
    /// Loop video decoder
    loop_video: Option<VideoDecoder>,
    /// Intro video decoder
    intro_video: Option<VideoDecoder>,
    /// Current cached frame from loop video
    loop_current_frame: Option<RgbImage>,
    /// Last frame from intro video (for transition)
    intro_last_frame: Option<RgbImage>,
    /// Target width
    target_width: u32,
    /// Target height
    target_height: u32,
    /// Cropbox for loop video (x, y, w, h) in original video coordinates
    loop_cropbox: Option<(u32, u32, u32, u32)>,
    /// Rotation for loop video in degrees (0, 90, 180, 270)
    loop_rotation: i32,
}

impl VideoPlayer {
    /// Create a new video player with the given target dimensions
    pub fn new(
        target_width: u32,
        target_height: u32,
        cropbox: Option<(u32, u32, u32, u32)>,
        rotation: i32,
    ) -> Self {
        Self {
            loop_video: None,
            intro_video: None,
            loop_current_frame: None,
            intro_last_frame: None,
            target_width,
            target_height,
            loop_cropbox: cropbox,
            loop_rotation: rotation,
        }
    }

    /// Load videos from EPConfig
    ///
    /// # Arguments
    /// * `config` - The EP configuration
    /// * `base_dir` - Base directory for resolving relative paths
    pub fn load_from_config(&mut self, config: &EPConfig, base_dir: &Path) {
        info!("Loading videos from config, base_dir: {:?}", base_dir);

        // Load loop video
        if !config.loop_config.file.is_empty() {
            let loop_path = Self::resolve_path(&config.loop_config.file, base_dir);
            info!("Loop video path: {:?} (exists: {})", loop_path, loop_path.exists());
            info!("Loop video cropbox: {:?}, rotation: {}", self.loop_cropbox, self.loop_rotation);
            match VideoDecoder::open(
                &loop_path.to_string_lossy(),
                self.target_width,
                self.target_height,
                self.loop_cropbox,
                self.loop_rotation,
            ) {
                Ok(decoder) => {
                    info!("Loaded loop video successfully: {}", loop_path.display());
                    self.loop_video = Some(decoder);
                }
                Err(e) => {
                    error!("Failed to load loop video '{}': {}", loop_path.display(), e);
                }
            }
        } else {
            warn!("No loop video file configured");
        }

        // Load intro video if enabled (no cropbox/rotation for intro)
        if let Some(ref intro) = config.intro {
            if intro.enabled && !intro.file.is_empty() {
                let intro_path = Self::resolve_path(&intro.file, base_dir);
                match VideoDecoder::open(
                    &intro_path.to_string_lossy(),
                    self.target_width,
                    self.target_height,
                    None,  // No cropbox for intro
                    0,     // No rotation for intro
                ) {
                    Ok(decoder) => {
                        info!("Loaded intro video: {}", intro_path.display());
                        self.intro_video = Some(decoder);
                    }
                    Err(e) => {
                        warn!("Failed to load intro video: {}", e);
                    }
                }
            }
        }

        // Read first frame of loop video for initial display
        self.read_first_loop_frame();
    }

    /// Resolve a potentially relative path against the base directory
    fn resolve_path(file_path: &str, base_dir: &Path) -> PathBuf {
        let path = Path::new(file_path);
        if path.is_absolute() {
            path.to_path_buf()
        } else {
            base_dir.join(path)
        }
    }

    /// Read and cache the first frame of the loop video
    fn read_first_loop_frame(&mut self) {
        if let Some(ref mut decoder) = self.loop_video {
            decoder.seek_to_start();
            if let Some(frame) = decoder.read_frame() {
                self.loop_current_frame = Some(frame);
            }
            decoder.seek_to_start();
        }
    }

    /// Check if intro video is available
    pub fn has_intro(&self) -> bool {
        self.intro_video.is_some()
    }

    /// Check if loop video is available
    pub fn has_loop(&self) -> bool {
        self.loop_video.is_some()
    }

    /// Advance to the next frame in the loop video
    ///
    /// Updates the internal cache without returning a clone.
    /// Loops automatically when reaching the end.
    /// Returns true if a frame was successfully read.
    pub fn advance_loop_frame(&mut self) -> bool {
        if let Some(ref mut decoder) = self.loop_video {
            match decoder.read_frame() {
                Some(frame) => {
                    self.loop_current_frame = Some(frame);  // Direct move, no clone
                    true
                }
                None => {
                    // End of video, loop back
                    decoder.seek_to_start();
                    if let Some(frame) = decoder.read_frame() {
                        self.loop_current_frame = Some(frame);  // Direct move, no clone
                        true
                    } else {
                        false
                    }
                }
            }
        } else {
            false
        }
    }

    /// Advance to the next frame in the intro video
    ///
    /// Updates the internal cache without returning a clone.
    /// Returns true if a frame was read, false when the intro video ends (no looping).
    pub fn advance_intro_frame(&mut self) -> bool {
        if let Some(ref mut decoder) = self.intro_video {
            match decoder.read_frame() {
                Some(frame) => {
                    self.intro_last_frame = Some(frame);  // Direct move, no clone
                    true
                }
                None => {
                    // End of intro video
                    false
                }
            }
        } else {
            false
        }
    }

    /// Get the last frame from the intro video
    ///
    /// Useful for transition effects after intro ends
    pub fn get_intro_last_frame(&self) -> Option<&RgbImage> {
        self.intro_last_frame.as_ref()
    }

    /// Get the current cached loop frame
    pub fn get_loop_current_frame(&self) -> Option<&RgbImage> {
        self.loop_current_frame.as_ref()
    }

    /// Seek intro video to start
    pub fn seek_intro_to_start(&mut self) {
        if let Some(ref mut decoder) = self.intro_video {
            decoder.seek_to_start();
        }
    }

    /// Seek loop video to start
    pub fn seek_loop_to_start(&mut self) {
        if let Some(ref mut decoder) = self.loop_video {
            decoder.seek_to_start();
        }
    }

    /// Reset both videos to start
    pub fn reset(&mut self) {
        self.seek_intro_to_start();
        self.seek_loop_to_start();
        self.intro_last_frame = None;
        self.read_first_loop_frame();
    }

    /// Get the FPS of the loop video
    pub fn loop_fps(&self) -> f64 {
        self.loop_video.as_ref().map(|d| d.fps()).unwrap_or(30.0)
    }

    /// Get the FPS of the intro video
    pub fn intro_fps(&self) -> f64 {
        self.intro_video.as_ref().map(|d| d.fps()).unwrap_or(30.0)
    }

    /// Create a black frame with the target dimensions
    pub fn create_black_frame(&self) -> RgbImage {
        image::RgbImage::from_pixel(
            self.target_width,
            self.target_height,
            image::Rgb([0, 0, 0]),
        )
    }
}

impl Default for VideoPlayer {
    fn default() -> Self {
        Self::new(360, 640, None, 0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_video_player_new() {
        let player = VideoPlayer::new(360, 640);
        assert!(!player.has_intro());
        assert!(!player.has_loop());
    }

    #[test]
    fn test_create_black_frame() {
        let player = VideoPlayer::new(360, 640);
        let frame = player.create_black_frame();
        assert_eq!(frame.width(), 360);
        assert_eq!(frame.height(), 640);
    }
}
