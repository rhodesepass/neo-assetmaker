//! Render module
//!
//! Contains transition effects and overlay rendering.

mod transition;
mod overlay;
pub mod bezier;
pub mod image_loader;
pub mod text_renderer;

pub use transition::TransitionRenderer;
pub use overlay::OverlayRenderer;
pub use bezier::*;
pub use image_loader::{ImageLoader, generate_barcode, generate_vertical_barcode, generate_vertical_barcode_gradient};
pub use text_renderer::{render_text_rotated_90, render_top_right_bar_text_rotated};
