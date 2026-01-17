//! Image loading and texture management
//!
//! Provides utilities for loading images from disk and converting them to egui textures.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use egui::{Color32, ColorImage, Context, TextureHandle, TextureId, TextureOptions};
use image::GenericImageView;
use tracing::{info, warn};

/// Image loader for managing textures
pub struct ImageLoader {
    /// Cached textures by path
    textures: HashMap<String, TextureHandle>,
    /// Base directory for resolving relative paths
    base_dir: PathBuf,
}

impl ImageLoader {
    /// Create a new image loader
    pub fn new(base_dir: PathBuf) -> Self {
        Self {
            textures: HashMap::new(),
            base_dir,
        }
    }

    /// Set the base directory for resolving relative paths
    pub fn set_base_dir(&mut self, base_dir: PathBuf) {
        self.base_dir = base_dir;
    }

    /// Resolve a path relative to the base directory
    pub fn resolve_path(&self, relative_path: &str) -> PathBuf {
        if Path::new(relative_path).is_absolute() {
            PathBuf::from(relative_path)
        } else {
            self.base_dir.join(relative_path)
        }
    }

    /// Load an image from disk and create a texture
    pub fn load_image(&mut self, ctx: &Context, path: &str) -> Option<TextureId> {
        // Check cache first
        if let Some(handle) = self.textures.get(path) {
            return Some(handle.id());
        }

        // Resolve the path
        let full_path = self.resolve_path(path);

        // Load the image
        let img = match image::open(&full_path) {
            Ok(img) => img,
            Err(e) => {
                warn!("Failed to load image '{}': {}", full_path.display(), e);
                return None;
            }
        };

        // Convert to ColorImage
        let size = [img.width() as usize, img.height() as usize];
        let pixels: Vec<Color32> = img
            .to_rgba8()
            .pixels()
            .map(|p| Color32::from_rgba_unmultiplied(p[0], p[1], p[2], p[3]))
            .collect();

        let color_image = ColorImage { size, pixels };

        // Create texture
        let texture = ctx.load_texture(
            path,
            color_image,
            TextureOptions::LINEAR,
        );

        let id = texture.id();
        self.textures.insert(path.to_string(), texture);

        info!("Loaded image: {} ({}x{})", path, size[0], size[1]);
        Some(id)
    }

    /// Get a cached texture by path
    pub fn get_texture(&self, path: &str) -> Option<&TextureHandle> {
        self.textures.get(path)
    }

    /// Get texture ID by path
    pub fn get_texture_id(&self, path: &str) -> Option<TextureId> {
        self.textures.get(path).map(|h| h.id())
    }

    /// Load an image and return its dimensions along with the texture ID
    pub fn load_image_with_size(&mut self, ctx: &Context, path: &str) -> Option<(TextureId, [usize; 2])> {
        // Check cache first
        if let Some(handle) = self.textures.get(path) {
            let size = handle.size();
            return Some((handle.id(), size));
        }

        // Resolve the path
        let full_path = self.resolve_path(path);

        // Load the image
        let img = match image::open(&full_path) {
            Ok(img) => img,
            Err(e) => {
                warn!("Failed to load image '{}': {}", full_path.display(), e);
                return None;
            }
        };

        // Convert to ColorImage
        let size = [img.width() as usize, img.height() as usize];
        let pixels: Vec<Color32> = img
            .to_rgba8()
            .pixels()
            .map(|p| Color32::from_rgba_unmultiplied(p[0], p[1], p[2], p[3]))
            .collect();

        let color_image = ColorImage { size, pixels };

        // Create texture
        let texture = ctx.load_texture(
            path,
            color_image,
            TextureOptions::LINEAR,
        );

        let id = texture.id();
        self.textures.insert(path.to_string(), texture);

        info!("Loaded image: {} ({}x{})", path, size[0], size[1]);
        Some((id, size))
    }

    /// Clear all cached textures
    pub fn clear(&mut self) {
        self.textures.clear();
    }

    /// Remove a specific texture from cache
    pub fn remove(&mut self, path: &str) -> Option<TextureHandle> {
        self.textures.remove(path)
    }
}

/// Preprocess text for Code128 barcode encoding
/// Ensures all characters are valid ASCII printable characters (32-126)
/// and adds Code128 Set B prefix required by barcoders library
fn preprocess_barcode_text(text: &str) -> String {
    // Filter to valid ASCII printable characters only
    let cleaned: String = text
        .chars()
        .filter_map(|c| {
            if c.is_ascii() && (c as u8) >= 32 && (c as u8) <= 126 {
                // Valid ASCII printable character
                Some(c)
            } else if c == '\u{2013}' || c == '\u{2014}' {
                // En-dash or em-dash -> hyphen
                Some('-')
            } else if c == '\u{00A0}' {
                // Non-breaking space -> regular space
                Some(' ')
            } else if c.is_whitespace() {
                Some(' ')
            } else {
                // Skip invalid characters
                None
            }
        })
        .collect();

    // Code128 Set B supports ASCII 32-127 (upper/lowercase, digits, punctuation)
    // barcoders library REQUIRES a charset prefix at the start of the text:
    // - '\u{00C0}' (À) = Character-set A
    // - '\u{0181}' (Ɓ) = Character-set B (best for mixed case text)
    // - '\u{0106}' (Ć) = Character-set C (numeric pairs only)
    format!("\u{0181}{}", cleaned)
}

/// Generate a Code128 barcode as a ColorImage
pub fn generate_barcode(text: &str, height: u32) -> Option<ColorImage> {
    use barcoders::sym::code128::Code128;

    // Preprocess text for Code128 compatibility
    let processed_text = preprocess_barcode_text(text);

    if processed_text.is_empty() {
        warn!("Barcode text is empty after preprocessing: '{}'", text);
        return None;
    }

    // Try to create Code128 barcode
    let barcode = match Code128::new(&processed_text) {
        Ok(b) => b,
        Err(e) => {
            warn!("Failed to create barcode for '{}': {:?}", text, e);
            return None;
        }
    };

    let encoded = barcode.encode();
    let width = encoded.len();

    if width == 0 {
        return None;
    }

    // Create horizontal barcode image
    let mut pixels = vec![Color32::TRANSPARENT; width * height as usize];

    for (x, &bar) in encoded.iter().enumerate() {
        let color = if bar == 1 { Color32::WHITE } else { Color32::TRANSPARENT };
        for y in 0..height as usize {
            pixels[y * width + x] = color;
        }
    }

    Some(ColorImage {
        size: [width, height as usize],
        pixels,
    })
}

/// Interpolate between colors in a gradient
fn interpolate_gradient(colors: &[Color32], t: f32) -> Color32 {
    let t = t.clamp(0.0, 1.0);
    let n = colors.len();

    if n == 0 {
        return Color32::WHITE;
    }
    if n == 1 {
        return colors[0];
    }

    // Calculate which segment we're in
    let segment_count = n - 1;
    let scaled_t = t * segment_count as f32;
    let segment = (scaled_t as usize).min(segment_count - 1);
    let local_t = scaled_t - segment as f32;

    let c1 = colors[segment];
    let c2 = colors[segment + 1];

    // Linear interpolation between the two colors
    Color32::from_rgb(
        (c1.r() as f32 * (1.0 - local_t) + c2.r() as f32 * local_t) as u8,
        (c1.g() as f32 * (1.0 - local_t) + c2.g() as f32 * local_t) as u8,
        (c1.b() as f32 * (1.0 - local_t) + c2.b() as f32 * local_t) as u8,
    )
}

/// Generate a vertical barcode (rotated 90 degrees)
/// The barcode runs from top to bottom instead of left to right
pub fn generate_vertical_barcode(text: &str, width: u32) -> Option<ColorImage> {
    generate_vertical_barcode_gradient(text, width, false)
}

/// Generate a vertical barcode with optional gradient colors
/// When use_gradient is true, bars use a purple→blue→cyan→yellow gradient
pub fn generate_vertical_barcode_gradient(text: &str, width: u32, use_gradient: bool) -> Option<ColorImage> {
    use barcoders::sym::code128::Code128;

    // Preprocess text for Code128 compatibility
    let processed_text = preprocess_barcode_text(text);

    if processed_text.is_empty() {
        warn!("Barcode text is empty after preprocessing: '{}'", text);
        return None;
    }

    // Try to create Code128 barcode
    let barcode = match Code128::new(&processed_text) {
        Ok(b) => b,
        Err(e) => {
            warn!("Failed to create barcode for '{}' (processed: '{}'): {:?}", text, processed_text, e);
            return None;
        }
    };

    let encoded = barcode.encode();
    let height = encoded.len();

    if height == 0 {
        return None;
    }

    // Gradient colors: purple → blue → cyan → yellow
    let gradient_colors = [
        Color32::from_rgb(180, 100, 220), // Purple
        Color32::from_rgb(80, 150, 255),  // Blue
        Color32::from_rgb(100, 220, 220), // Cyan
        Color32::from_rgb(255, 220, 100), // Yellow
    ];

    // Create vertical barcode image (rotated 90 degrees)
    // Each "bar" becomes a horizontal stripe
    let mut pixels = vec![Color32::TRANSPARENT; width as usize * height];

    for (y, &bar) in encoded.iter().enumerate() {
        if bar == 1 {
            let color = if use_gradient {
                let t = y as f32 / height as f32;
                interpolate_gradient(&gradient_colors, t)
            } else {
                Color32::WHITE
            };
            for x in 0..width as usize {
                pixels[y * width as usize + x] = color;
            }
        }
    }

    Some(ColorImage {
        size: [width as usize, height],
        pixels,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_generate_barcode() {
        let barcode = generate_barcode("TEST", 50);
        assert!(barcode.is_some());
        let img = barcode.unwrap();
        assert!(img.size[0] > 0);
        assert_eq!(img.size[1], 50);
    }

    #[test]
    fn test_generate_vertical_barcode() {
        let barcode = generate_vertical_barcode("TEST", 30);
        assert!(barcode.is_some());
        let img = barcode.unwrap();
        assert_eq!(img.size[0], 30);
        assert!(img.size[1] > 0);
    }
}
