//! Text renderer for rotated text
//!
//! Uses fontdue to rasterize text, then rotates 90° clockwise.
//! Emulates the firmware's fbdraw_text_rot90() behavior.

use egui::{Color32, ColorImage};
use fontdue::{Font, FontSettings};

/// Embedded font for text rendering (DejaVuSans-Bold as Bebas substitute)
static FONT_DATA: &[u8] = include_bytes!("../../resources/fonts/DejaVuSans-Bold.ttf");

/// Lazy-initialized font instance
fn get_font() -> &'static Font {
    use std::sync::OnceLock;
    static FONT: OnceLock<Font> = OnceLock::new();
    FONT.get_or_init(|| {
        Font::from_bytes(FONT_DATA, FontSettings::default())
            .expect("Failed to load embedded font")
    })
}

/// Render text rotated 90° clockwise as a ColorImage.
///
/// Emulates the firmware's `fbdraw_text_rot90()`:
/// 1. Rasterize each character horizontally using fontdue
/// 2. Compose into a horizontal bitmap
/// 3. Rotate 90° clockwise
/// 4. Return as ColorImage
///
/// If `bold` is true, applies faux bold by rendering twice with 1px x-offset
/// (matching firmware's double-render technique).
pub fn render_text_rotated_90(
    text: &str,
    font_size: f32,
    color: Color32,
    bold: bool,
) -> ColorImage {
    let font = get_font();

    // Step 1: Rasterize each character and calculate total dimensions
    let mut glyphs: Vec<(fontdue::Metrics, Vec<u8>)> = Vec::new();
    let mut total_width: usize = 0;
    let mut max_height: usize = 0;

    for ch in text.chars() {
        let (metrics, bitmap) = font.rasterize(ch, font_size);
        total_width += metrics.advance_width.ceil() as usize;
        let glyph_height = (font_size.ceil() as usize).max(metrics.height + metrics.ymin.unsigned_abs() as usize);
        max_height = max_height.max(glyph_height);
        glyphs.push((metrics, bitmap));
    }

    if total_width == 0 || max_height == 0 {
        return ColorImage::new([1, 1], Color32::TRANSPARENT);
    }

    // Add padding
    let img_height = (font_size * 1.2).ceil() as usize;
    let img_height = img_height.max(max_height);

    // Step 2: Compose glyphs into horizontal bitmap
    let mut horizontal = vec![0u8; total_width * img_height];
    let baseline = (font_size * 0.85).ceil() as i32;
    let mut cursor_x: i32 = 0;

    for (metrics, bitmap) in &glyphs {
        let glyph_x = cursor_x + metrics.xmin;
        let glyph_y = baseline - metrics.height as i32 - metrics.ymin;

        for gy in 0..metrics.height {
            for gx in 0..metrics.width {
                let px = glyph_x + gx as i32;
                let py = glyph_y + gy as i32;

                if px >= 0 && (px as usize) < total_width && py >= 0 && (py as usize) < img_height {
                    let src_alpha = bitmap[gy * metrics.width + gx];
                    let dst_idx = py as usize * total_width + px as usize;
                    // Max blend for overlapping glyphs
                    horizontal[dst_idx] = horizontal[dst_idx].max(src_alpha);

                    // Faux bold: render again at x+1
                    if bold && (px + 1) < total_width as i32 {
                        let bold_idx = py as usize * total_width + (px + 1) as usize;
                        horizontal[bold_idx] = horizontal[bold_idx].max(src_alpha);
                    }
                }
            }
        }
        cursor_x += metrics.advance_width.ceil() as i32;
    }

    // Step 3: Rotate 90° clockwise
    // Original: width=total_width, height=img_height
    // Rotated:  width=img_height, height=total_width
    let rot_width = img_height;
    let rot_height = total_width;

    let mut pixels = vec![Color32::TRANSPARENT; rot_width * rot_height];

    let [r, g, b, _] = color.to_array();

    for oy in 0..img_height {
        for ox in 0..total_width {
            let alpha = horizontal[oy * total_width + ox];
            if alpha > 0 {
                // Clockwise 90°: (x, y) -> (height-1-y, x)
                let rx = img_height - 1 - oy;
                let ry = ox;
                pixels[ry * rot_width + rx] = Color32::from_rgba_unmultiplied(r, g, b, alpha);
            }
        }
    }

    ColorImage {
        size: [rot_width, rot_height],
        pixels,
    }
}

/// Render text for the top_right_bar area with split bold/regular rendering.
///
/// The firmware splits text at the first space:
/// - Part before space: faux bold (double-rendered)
/// - Part after space: regular
/// Both parts are rendered rotated 90° and composed vertically.
pub fn render_top_right_bar_text_rotated(
    text: &str,
    font_size: f32,
    color: Color32,
) -> ColorImage {
    if let Some(space_idx) = text.find(' ') {
        let bold_part = &text[..space_idx];
        let regular_part = &text[space_idx + 1..];

        let bold_img = render_text_rotated_90(bold_part, font_size, color, true);
        let regular_img = render_text_rotated_90(regular_part, font_size, color, false);

        // Combine vertically: bold on top, gap, then regular
        let gap = 6; // pixels, matching firmware's space_gap
        let combined_width = bold_img.size[0].max(regular_img.size[0]);
        let combined_height = bold_img.size[1] + gap + regular_img.size[1];

        let mut pixels = vec![Color32::TRANSPARENT; combined_width * combined_height];

        // Copy bold part
        for y in 0..bold_img.size[1] {
            for x in 0..bold_img.size[0] {
                if x < combined_width {
                    pixels[y * combined_width + x] = bold_img.pixels[y * bold_img.size[0] + x];
                }
            }
        }

        // Copy regular part
        let reg_offset_y = bold_img.size[1] + gap;
        for y in 0..regular_img.size[1] {
            for x in 0..regular_img.size[0] {
                if x < combined_width && (reg_offset_y + y) < combined_height {
                    pixels[(reg_offset_y + y) * combined_width + x] =
                        regular_img.pixels[y * regular_img.size[0] + x];
                }
            }
        }

        ColorImage {
            size: [combined_width, combined_height],
            pixels,
        }
    } else {
        // No space: render all as faux bold
        render_text_rotated_90(text, font_size, color, true)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_render_basic_text() {
        let img = render_text_rotated_90("TEST", 20.0, Color32::WHITE, false);
        assert!(img.size[0] > 0);
        assert!(img.size[1] > 0);
    }

    #[test]
    fn test_render_bold_text() {
        let img = render_text_rotated_90("BOLD", 20.0, Color32::WHITE, true);
        assert!(img.size[0] > 0);
        assert!(img.size[1] > 0);
    }

    #[test]
    fn test_render_top_right_bar_with_space() {
        let img = render_top_right_bar_text_rotated("RHODES ISLAND", 10.0, Color32::WHITE);
        assert!(img.size[0] > 0);
        assert!(img.size[1] > 0);
    }

    #[test]
    fn test_render_top_right_bar_without_space() {
        let img = render_top_right_bar_text_rotated("NOBREAK", 10.0, Color32::WHITE);
        assert!(img.size[0] > 0);
        assert!(img.size[1] > 0);
    }

    #[test]
    fn test_render_empty_text() {
        let img = render_text_rotated_90("", 20.0, Color32::WHITE, false);
        // Should return a minimal image
        assert!(img.size[0] >= 1);
        assert!(img.size[1] >= 1);
    }
}
