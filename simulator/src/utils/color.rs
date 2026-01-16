//! Color utilities
//!
//! Helper functions for color conversion and manipulation.

/// Parse hex color string to RGB tuple
///
/// Accepts formats: "#RRGGBB" or "RRGGBB"
pub fn parse_hex_color(hex: &str) -> Option<(u8, u8, u8)> {
    let hex = hex.trim_start_matches('#');

    if hex.len() != 6 {
        return None;
    }

    let r = u8::from_str_radix(&hex[0..2], 16).ok()?;
    let g = u8::from_str_radix(&hex[2..4], 16).ok()?;
    let b = u8::from_str_radix(&hex[4..6], 16).ok()?;

    Some((r, g, b))
}

/// Parse hex color string to RGBA tuple (alpha = 255)
pub fn parse_hex_color_rgba(hex: &str) -> Option<(u8, u8, u8, u8)> {
    let (r, g, b) = parse_hex_color(hex)?;
    Some((r, g, b, 255))
}

/// Convert RGB to hex string
pub fn rgb_to_hex(r: u8, g: u8, b: u8) -> String {
    format!("#{:02X}{:02X}{:02X}", r, g, b)
}

/// Blend two colors with alpha
///
/// result = fg * alpha + bg * (1 - alpha)
pub fn blend_colors(
    bg: (u8, u8, u8),
    fg: (u8, u8, u8),
    alpha: f32,
) -> (u8, u8, u8) {
    let alpha = alpha.clamp(0.0, 1.0);
    let inv_alpha = 1.0 - alpha;

    let r = (fg.0 as f32 * alpha + bg.0 as f32 * inv_alpha) as u8;
    let g = (fg.1 as f32 * alpha + bg.1 as f32 * inv_alpha) as u8;
    let b = (fg.2 as f32 * alpha + bg.2 as f32 * inv_alpha) as u8;

    (r, g, b)
}

/// Blend with alpha premultiplied
pub fn blend_rgba(
    bg: (u8, u8, u8, u8),
    fg: (u8, u8, u8, u8),
) -> (u8, u8, u8, u8) {
    let fg_alpha = fg.3 as f32 / 255.0;
    let bg_alpha = bg.3 as f32 / 255.0;

    // Standard alpha compositing
    let out_alpha = fg_alpha + bg_alpha * (1.0 - fg_alpha);

    if out_alpha < 0.001 {
        return (0, 0, 0, 0);
    }

    let r = ((fg.0 as f32 * fg_alpha + bg.0 as f32 * bg_alpha * (1.0 - fg_alpha)) / out_alpha) as u8;
    let g = ((fg.1 as f32 * fg_alpha + bg.1 as f32 * bg_alpha * (1.0 - fg_alpha)) / out_alpha) as u8;
    let b = ((fg.2 as f32 * fg_alpha + bg.2 as f32 * bg_alpha * (1.0 - fg_alpha)) / out_alpha) as u8;
    let a = (out_alpha * 255.0) as u8;

    (r, g, b, a)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_hex_color() {
        assert_eq!(parse_hex_color("#FF0000"), Some((255, 0, 0)));
        assert_eq!(parse_hex_color("00FF00"), Some((0, 255, 0)));
        assert_eq!(parse_hex_color("#0000FF"), Some((0, 0, 255)));
        assert_eq!(parse_hex_color("#000000"), Some((0, 0, 0)));
        assert_eq!(parse_hex_color("#FFFFFF"), Some((255, 255, 255)));
    }

    #[test]
    fn test_rgb_to_hex() {
        assert_eq!(rgb_to_hex(255, 0, 0), "#FF0000");
        assert_eq!(rgb_to_hex(0, 255, 0), "#00FF00");
        assert_eq!(rgb_to_hex(0, 0, 255), "#0000FF");
    }

    #[test]
    fn test_blend_colors() {
        // Full opacity foreground
        assert_eq!(blend_colors((0, 0, 0), (255, 255, 255), 1.0), (255, 255, 255));
        // Full opacity background
        assert_eq!(blend_colors((255, 255, 255), (0, 0, 0), 0.0), (255, 255, 255));
        // 50% blend
        let result = blend_colors((0, 0, 0), (200, 200, 200), 0.5);
        assert!(result.0 >= 90 && result.0 <= 110);
    }
}
