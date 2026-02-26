//! Bezier curve calculations
//!
//! Implements cubic bezier curves for easing functions.
//! Corresponds to firmware layer_animation.c lv_cubic_bezier

/// Calculate cubic bezier curve value
///
/// Control points: P0=(0,0), P1=(p1x,p1y), P2=(p2x,p2y), P3=(1,1)
///
/// Uses Newton-Raphson iteration to solve for t given x,
/// then evaluates y(t).
pub fn cubic_bezier(t: f32, p1x: f32, p1y: f32, p2x: f32, p2y: f32) -> f32 {
    // Boundary conditions
    if t <= 0.0 {
        return 0.0;
    }
    if t >= 1.0 {
        return 1.0;
    }

    // Newton-Raphson iteration to find s where x(s) = t
    let mut s = t; // Initial guess

    for _ in 0..8 {
        let s2 = s * s;
        let s3 = s2 * s;
        let one_minus_s = 1.0 - s;
        let one_minus_s2 = one_minus_s * one_minus_s;

        // Calculate x(s)
        let x = 3.0 * one_minus_s2 * s * p1x + 3.0 * one_minus_s * s2 * p2x + s3;

        // Calculate dx/ds
        let dx = 3.0 * one_minus_s2 * p1x
            + 6.0 * one_minus_s * s * (p2x - p1x)
            + 3.0 * s2 * (1.0 - p2x);

        if dx.abs() < 1e-10 {
            break;
        }

        // Newton step
        s = (s - (x - t) / dx).clamp(0.0, 1.0);
    }

    // Calculate y(s)
    let s2 = s * s;
    let s3 = s2 * s;
    let one_minus_s = 1.0 - s;
    let one_minus_s2 = one_minus_s * one_minus_s;

    let y = 3.0 * one_minus_s2 * s * p1y + 3.0 * one_minus_s * s2 * p2y + s3;

    y.clamp(0.0, 1.0)
}

/// Ease-out function
///
/// Used for MOVE transition entry phase.
/// Control points: (0, 0) -> (0.58, 1)
pub fn ease_out(t: f32) -> f32 {
    cubic_bezier(t, 0.0, 0.0, 0.58, 1.0)
}

/// Ease-in function
///
/// Used for MOVE transition exit phase.
/// Control points: (0.42, 0) -> (1, 1)
pub fn ease_in(t: f32) -> f32 {
    cubic_bezier(t, 0.42, 0.0, 1.0, 1.0)
}

/// Ease-in-out function
///
/// Used for SWIPE transition and entry animation.
/// Control points: (0.42, 0) -> (0.58, 1)
pub fn ease_in_out(t: f32) -> f32 {
    cubic_bezier(t, 0.42, 0.0, 0.58, 1.0)
}

/// Precompute bezier values for SWIPE effect
///
/// Returns a vector of x-offsets for each scanline.
pub fn precompute_swipe_bezier(height: u32) -> Vec<i32> {
    let mut values = Vec::with_capacity(height as usize);

    for y in 0..height {
        let progress = y as f32 / height as f32;
        let bezier_val = ease_in_out(progress);
        values.push((bezier_val * height as f32) as i32);
    }

    values
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cubic_bezier_boundaries() {
        // At t=0, should return 0
        assert!((cubic_bezier(0.0, 0.42, 0.0, 0.58, 1.0) - 0.0).abs() < 0.001);
        // At t=1, should return 1
        assert!((cubic_bezier(1.0, 0.42, 0.0, 0.58, 1.0) - 1.0).abs() < 0.001);
    }

    #[test]
    fn test_ease_functions() {
        // ease_out at 0.5 should be > 0.5 (fast start)
        assert!(ease_out(0.5) > 0.5);
        // ease_in at 0.5 should be < 0.5 (slow start)
        assert!(ease_in(0.5) < 0.5);
        // ease_in_out at 0.5 should be ~0.5
        assert!((ease_in_out(0.5) - 0.5).abs() < 0.1);
    }

    #[test]
    fn test_precompute_swipe() {
        let values = precompute_swipe_bezier(100);
        assert_eq!(values.len(), 100);
        // First value should be near 0
        assert!(values[0] < 10);
        // Last value should be near height
        assert!(values[99] > 90);
    }
}
