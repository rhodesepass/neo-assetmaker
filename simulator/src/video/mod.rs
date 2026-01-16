//! Video module
//!
//! Provides video decoding and playback functionality using FFmpeg.
//!
//! # Usage
//!
//! ```rust,ignore
//! use video::VideoPlayer;
//!
//! let mut player = VideoPlayer::new(360, 640);
//! player.load_from_config(&config, &base_dir);
//!
//! // Read frames
//! if let Some(frame) = player.read_loop_frame() {
//!     // Use the frame
//! }
//! ```

mod decoder;
mod player;

pub use decoder::VideoDecoder;
pub use player::VideoPlayer;
