//! Video decoder module
//!
//! Provides video frame decoding functionality using FFmpeg.

use std::path::Path;
use anyhow::{Result, Context};
use image::RgbImage;
use tracing::{info, error};

use ffmpeg_next as ffmpeg;
use ffmpeg::format::input;
use ffmpeg::media::Type;
use ffmpeg::software::scaling::{Context as Scaler, Flags};
use ffmpeg::util::frame::video::Video as VideoFrame;
use ffmpeg::format::Pixel;

/// Video decoder that extracts frames from video files using FFmpeg
pub struct VideoDecoder {
    /// FFmpeg format context
    input_ctx: ffmpeg::format::context::Input,
    /// Video stream index
    video_stream_index: usize,
    /// Video decoder
    decoder: ffmpeg::codec::decoder::Video,
    /// Scaler for format conversion (to RGB24, original size)
    rgb_scaler: Scaler,
    /// Scaler for final resize (after crop and rotate)
    final_scaler: Option<Scaler>,
    /// Target width for resize
    target_width: u32,
    /// Target height for resize
    target_height: u32,
    /// Video FPS
    fps: f64,
    /// Packet iterator state
    packet_iter_exhausted: bool,
    /// Cropbox (x, y, w, h) in rotated video coordinates
    cropbox: Option<(u32, u32, u32, u32)>,
    /// Rotation in degrees (0, 90, 180, 270)
    rotation: i32,
    /// Source width (original video)
    src_width: u32,
    /// Source height (original video)
    src_height: u32,
}

impl VideoDecoder {
    /// Open a video file for decoding
    ///
    /// # Arguments
    /// * `path` - Path to the video file
    /// * `target_width` - Target width for frame resize
    /// * `target_height` - Target height for frame resize
    /// * `cropbox` - Optional cropbox (x, y, w, h) in rotated video coordinates
    /// * `rotation` - Rotation in degrees (0, 90, 180, 270)
    pub fn open(
        path: &str,
        target_width: u32,
        target_height: u32,
        cropbox: Option<(u32, u32, u32, u32)>,
        rotation: i32,
    ) -> Result<Self> {
        let path_obj = Path::new(path);

        if !path_obj.exists() {
            anyhow::bail!("Video file not found: {}", path);
        }

        // Initialize FFmpeg (safe to call multiple times)
        ffmpeg::init().context("Failed to initialize FFmpeg")?;

        // Open input file
        let input_ctx = input(&path).context("Failed to open video file")?;

        // Find best video stream
        let video_stream = input_ctx
            .streams()
            .best(Type::Video)
            .ok_or_else(|| anyhow::anyhow!("No video stream found in file"))?;

        let video_stream_index = video_stream.index();

        // Get stream rate (fps)
        let rate = video_stream.rate();
        let fps = if rate.1 != 0 {
            rate.0 as f64 / rate.1 as f64
        } else {
            30.0
        };

        // Create decoder
        let context_decoder = ffmpeg::codec::context::Context::from_parameters(video_stream.parameters())
            .context("Failed to create decoder context")?;
        let decoder = context_decoder.decoder().video()
            .context("Failed to create video decoder")?;

        let src_width = decoder.width();
        let src_height = decoder.height();
        let src_format = decoder.format();

        info!(
            "Opened video: {}x{} @ {:.1}fps, format: {:?}, cropbox: {:?}, rotation: {}",
            src_width, src_height, fps, src_format, cropbox, rotation
        );

        // Create scaler for RGB24 conversion (original size, no resize)
        let rgb_scaler = Scaler::get(
            src_format,
            src_width,
            src_height,
            Pixel::RGB24,
            src_width,
            src_height,
            Flags::BILINEAR,
        ).context("Failed to create RGB scaler")?;

        // Calculate final scaler dimensions based on cropbox and rotation
        // Processing order: rotate full frame → crop from rotated frame
        // cropbox is in rotated-space coordinates, so its dimensions are the final input size
        let final_scaler = if cropbox.is_some() || rotation != 0 {
            let (final_w, final_h) = if let Some((_, _, w, h)) = cropbox {
                // cropbox dimensions are already in rotated space
                (w, h)
            } else if rotation == 90 || rotation == 270 {
                // No cropbox, but rotation swaps dimensions
                (src_height, src_width)
            } else {
                // Arbitrary angle: bounding box is larger than original
                let rad = (rotation as f64).to_radians();
                let abs_cos = rad.cos().abs();
                let abs_sin = rad.sin().abs();
                (
                    (src_width as f64 * abs_cos + src_height as f64 * abs_sin).ceil() as u32,
                    (src_width as f64 * abs_sin + src_height as f64 * abs_cos).ceil() as u32,
                )
            };

            // Create final scaler from crop size to target size
            Some(Scaler::get(
                Pixel::RGB24,
                final_w,
                final_h,
                Pixel::RGB24,
                target_width,
                target_height,
                Flags::BILINEAR,
            ).context("Failed to create final scaler")?)
        } else {
            // No cropbox or rotation, create a direct scaler
            Some(Scaler::get(
                Pixel::RGB24,
                src_width,
                src_height,
                Pixel::RGB24,
                target_width,
                target_height,
                Flags::BILINEAR,
            ).context("Failed to create final scaler")?)
        };

        Ok(Self {
            input_ctx,
            video_stream_index,
            decoder,
            rgb_scaler,
            final_scaler,
            target_width,
            target_height,
            fps,
            packet_iter_exhausted: false,
            cropbox,
            rotation,
            src_width,
            src_height,
        })
    }

    /// Read the next frame from the video
    ///
    /// Returns None if end of video or error
    pub fn read_frame(&mut self) -> Option<RgbImage> {
        // Try to receive already decoded frames first
        let mut decoded = VideoFrame::empty();
        if self.decoder.receive_frame(&mut decoded).is_ok() {
            return self.convert_frame(&decoded);
        }

        // Need to send more packets
        if self.packet_iter_exhausted {
            return None;
        }

        // Read packets until we get a frame
        loop {
            // Get next packet
            let packet_result = self.input_ctx.packets().next();

            match packet_result {
                Some((stream, packet)) => {
                    // Skip non-video packets
                    if stream.index() != self.video_stream_index {
                        continue;
                    }

                    // Send packet to decoder
                    if self.decoder.send_packet(&packet).is_err() {
                        continue;
                    }

                    // Try to receive frame
                    let mut decoded = VideoFrame::empty();
                    if self.decoder.receive_frame(&mut decoded).is_ok() {
                        return self.convert_frame(&decoded);
                    }
                }
                None => {
                    // End of stream, flush decoder
                    self.packet_iter_exhausted = true;
                    let _ = self.decoder.send_eof();

                    // Try to get remaining frames
                    let mut decoded = VideoFrame::empty();
                    if self.decoder.receive_frame(&mut decoded).is_ok() {
                        return self.convert_frame(&decoded);
                    }
                    return None;
                }
            }
        }
    }

    /// Convert FFmpeg frame to RgbImage with optional crop and rotation
    fn convert_frame(&mut self, decoded: &VideoFrame) -> Option<RgbImage> {
        // Step 1: Convert to RGB24 at original size
        let mut rgb_frame = VideoFrame::empty();

        if let Err(e) = self.rgb_scaler.run(decoded, &mut rgb_frame) {
            error!("Failed to convert frame to RGB: {}", e);
            return None;
        }

        // Extract RGB data from frame
        let data = rgb_frame.data(0);
        let stride = rgb_frame.stride(0);
        let src_width = self.src_width as usize;
        let src_height = self.src_height as usize;

        // Create a contiguous buffer for the original frame
        let mut rgb_data = Vec::with_capacity(src_width * src_height * 3);
        for y in 0..src_height {
            let row_start = y * stride;
            let row_end = row_start + src_width * 3;
            rgb_data.extend_from_slice(&data[row_start..row_end]);
        }

        // Step 2: Apply rotation FIRST (on full frame, isotropic space)
        let (rotated_data, rotated_w, rotated_h) =
            self.rotate_frame(&rgb_data, self.src_width, self.src_height, self.rotation);

        // Step 3: Apply crop from rotated frame (rotated-space coordinates)
        let (final_data, final_w, final_h) = if let Some((cx, cy, cw, ch)) = self.cropbox {
            let cropped = self.crop_frame(&rotated_data, rotated_w, cx, cy, cw, ch);
            (cropped, cw, ch)
        } else {
            (rotated_data, rotated_w, rotated_h)
        };

        // Step 4: Scale to target size using the final scaler
        if let Some(ref mut final_scaler) = self.final_scaler {
            // Create a VideoFrame from our cropped data
            let mut src_frame = VideoFrame::new(Pixel::RGB24, final_w, final_h);

            // Copy data into the frame
            // Get stride first (immutable borrow), then get mutable data
            let frame_stride = src_frame.stride(0);
            let frame_data = src_frame.data_mut(0);

            for y in 0..final_h as usize {
                let src_start = y * (final_w as usize) * 3;
                let dst_start = y * frame_stride;
                let row_len = (final_w as usize) * 3;
                frame_data[dst_start..dst_start + row_len].copy_from_slice(&final_data[src_start..src_start + row_len]);
            }

            // Scale to target size
            let mut scaled_frame = VideoFrame::empty();
            if let Err(e) = final_scaler.run(&src_frame, &mut scaled_frame) {
                error!("Failed to scale frame: {}", e);
                return None;
            }

            // Extract final result
            let final_data = scaled_frame.data(0);
            let final_stride = scaled_frame.stride(0);
            let target_width = self.target_width as usize;
            let target_height = self.target_height as usize;

            if final_stride == target_width * 3 {
                RgbImage::from_raw(
                    self.target_width,
                    self.target_height,
                    final_data[..target_width * target_height * 3].to_vec(),
                )
            } else {
                let mut pixels = Vec::with_capacity(target_width * target_height * 3);
                for y in 0..target_height {
                    let row_start = y * final_stride;
                    let row_end = row_start + target_width * 3;
                    pixels.extend_from_slice(&final_data[row_start..row_end]);
                }
                RgbImage::from_raw(self.target_width, self.target_height, pixels)
            }
        } else {
            // No final scaler, use rotated data directly (shouldn't happen normally)
            RgbImage::from_raw(final_w, final_h, final_data)
        }
    }

    /// Crop a frame from RGB24 data
    fn crop_frame(&self, data: &[u8], src_width: u32, x: u32, y: u32, w: u32, h: u32) -> Vec<u8> {
        let mut cropped = Vec::with_capacity((w * h * 3) as usize);
        let src_stride = (src_width * 3) as usize;

        for row in y..(y + h) {
            let start = (row as usize * src_stride) + (x as usize * 3);
            let end = start + (w as usize * 3);
            cropped.extend_from_slice(&data[start..end]);
        }
        cropped
    }

    /// Rotate a frame
    fn rotate_frame(&self, data: &[u8], w: u32, h: u32, rotation: i32) -> (Vec<u8>, u32, u32) {
        match rotation {
            0 => (data.to_vec(), w, h),
            90 => self.rotate_90(data, w, h),
            180 => self.rotate_180(data, w, h),
            270 => self.rotate_270(data, w, h),
            _ => self.rotate_arbitrary(data, w, h, rotation),
        }
    }

    /// Rotate 90 degrees clockwise
    fn rotate_90(&self, data: &[u8], w: u32, h: u32) -> (Vec<u8>, u32, u32) {
        let new_w = h;
        let new_h = w;
        let mut result = vec![0u8; (new_w * new_h * 3) as usize];

        for y in 0..h {
            for x in 0..w {
                let src_idx = ((y * w + x) * 3) as usize;
                let new_x = h - 1 - y;
                let new_y = x;
                let dst_idx = ((new_y * new_w + new_x) * 3) as usize;
                result[dst_idx..dst_idx + 3].copy_from_slice(&data[src_idx..src_idx + 3]);
            }
        }
        (result, new_w, new_h)
    }

    /// Rotate 180 degrees
    fn rotate_180(&self, data: &[u8], w: u32, h: u32) -> (Vec<u8>, u32, u32) {
        let mut result = vec![0u8; (w * h * 3) as usize];

        for y in 0..h {
            for x in 0..w {
                let src_idx = ((y * w + x) * 3) as usize;
                let new_x = w - 1 - x;
                let new_y = h - 1 - y;
                let dst_idx = ((new_y * w + new_x) * 3) as usize;
                result[dst_idx..dst_idx + 3].copy_from_slice(&data[src_idx..src_idx + 3]);
            }
        }
        (result, w, h)
    }

    /// Rotate 270 degrees clockwise (90 degrees counter-clockwise)
    fn rotate_270(&self, data: &[u8], w: u32, h: u32) -> (Vec<u8>, u32, u32) {
        let new_w = h;
        let new_h = w;
        let mut result = vec![0u8; (new_w * new_h * 3) as usize];

        for y in 0..h {
            for x in 0..w {
                let src_idx = ((y * w + x) * 3) as usize;
                let new_x = y;
                let new_y = w - 1 - x;
                let dst_idx = ((new_y * new_w + new_x) * 3) as usize;
                result[dst_idx..dst_idx + 3].copy_from_slice(&data[src_idx..src_idx + 3]);
            }
        }
        (result, new_w, new_h)
    }

    /// Rotate by arbitrary angle using affine transform + bilinear interpolation
    /// Equivalent to Python's cv2.warpAffine with cv2.INTER_LINEAR
    fn rotate_arbitrary(&self, data: &[u8], w: u32, h: u32, rotation: i32) -> (Vec<u8>, u32, u32) {
        let rad = (rotation as f64).to_radians();
        let cos_a = rad.cos();
        let sin_a = rad.sin();
        let abs_cos = cos_a.abs();
        let abs_sin = sin_a.abs();

        // Bounding box (matches Python _get_rotated_video_size)
        let nw = (w as f64 * abs_cos + h as f64 * abs_sin).ceil() as u32;
        let nh = (w as f64 * abs_sin + h as f64 * abs_cos).ceil() as u32;

        // Original center & new center
        let cx = w as f64 / 2.0;
        let cy = h as f64 / 2.0;
        let ncx = nw as f64 / 2.0;
        let ncy = nh as f64 / 2.0;

        let src_stride = w as usize * 3;
        let dst_stride = nw as usize * 3;
        let mut result = vec![0u8; (nw * nh * 3) as usize];
        let w_limit = (w - 1) as f64;
        let h_limit = (h - 1) as f64;

        for dst_y in 0..nh {
            for dst_x in 0..nw {
                // Inverse mapping: dst → src
                let dx = dst_x as f64 - ncx;
                let dy = dst_y as f64 - ncy;
                let src_xf = cos_a * dx + sin_a * dy + cx;
                let src_yf = -sin_a * dx + cos_a * dy + cy;

                // Bilinear interpolation (out-of-bounds stays black = 0)
                if src_xf >= 0.0 && src_xf < w_limit
                    && src_yf >= 0.0 && src_yf < h_limit
                {
                    let x0 = src_xf.floor() as usize;
                    let y0 = src_yf.floor() as usize;
                    let x1 = x0 + 1;
                    let y1 = y0 + 1;
                    let fx = src_xf - x0 as f64;
                    let fy = src_yf - y0 as f64;

                    let dst_idx = dst_y as usize * dst_stride + dst_x as usize * 3;
                    for c in 0..3 {
                        let v00 = data[y0 * src_stride + x0 * 3 + c] as f64;
                        let v10 = data[y0 * src_stride + x1 * 3 + c] as f64;
                        let v01 = data[y1 * src_stride + x0 * 3 + c] as f64;
                        let v11 = data[y1 * src_stride + x1 * 3 + c] as f64;
                        let v = (1.0 - fx) * (1.0 - fy) * v00
                              + fx * (1.0 - fy) * v10
                              + (1.0 - fx) * fy * v01
                              + fx * fy * v11;
                        result[dst_idx + c] = v.round() as u8;
                    }
                }
            }
        }
        (result, nw, nh)
    }

    /// Seek to the beginning of the video
    pub fn seek_to_start(&mut self) {
        // Seek to beginning
        if let Err(e) = self.input_ctx.seek(0, ..) {
            error!("Failed to seek to start: {}", e);
        }

        // Flush decoder
        self.decoder.flush();
        self.packet_iter_exhausted = false;
    }

    /// Get the video FPS
    pub fn fps(&self) -> f64 {
        self.fps
    }

    /// Get the target (output) width
    pub fn target_width(&self) -> u32 {
        self.target_width
    }

    /// Get the target (output) height
    pub fn target_height(&self) -> u32 {
        self.target_height
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_decoder_nonexistent() {
        // Test that decoder returns error for nonexistent file
        let result = VideoDecoder::open("nonexistent.mp4", 360, 640, None, 0);
        assert!(result.is_err());
    }
}
