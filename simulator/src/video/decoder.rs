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
    /// Scaler for format conversion and resize
    scaler: Scaler,
    /// Target width for resize
    target_width: u32,
    /// Target height for resize
    target_height: u32,
    /// Video FPS
    fps: f64,
    /// Packet iterator state
    packet_iter_exhausted: bool,
}

impl VideoDecoder {
    /// Open a video file for decoding
    ///
    /// # Arguments
    /// * `path` - Path to the video file
    /// * `target_width` - Target width for frame resize
    /// * `target_height` - Target height for frame resize
    pub fn open(path: &str, target_width: u32, target_height: u32) -> Result<Self> {
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
            "Opened video: {}x{} @ {:.1}fps, format: {:?}",
            src_width, src_height, fps, src_format
        );

        // Create scaler for RGB24 conversion and resize
        let scaler = Scaler::get(
            src_format,
            src_width,
            src_height,
            Pixel::RGB24,
            target_width,
            target_height,
            Flags::BILINEAR,
        ).context("Failed to create scaler")?;

        Ok(Self {
            input_ctx,
            video_stream_index,
            decoder,
            scaler,
            target_width,
            target_height,
            fps,
            packet_iter_exhausted: false,
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

    /// Convert FFmpeg frame to RgbImage
    fn convert_frame(&mut self, decoded: &VideoFrame) -> Option<RgbImage> {
        let mut rgb_frame = VideoFrame::empty();

        if let Err(e) = self.scaler.run(decoded, &mut rgb_frame) {
            error!("Failed to scale frame: {}", e);
            return None;
        }

        // Get RGB data from frame
        let data = rgb_frame.data(0);
        let stride = rgb_frame.stride(0);
        let height = self.target_height as usize;
        let width = self.target_width as usize;

        // If stride matches width*3, we can use data directly
        if stride == width * 3 {
            RgbImage::from_raw(
                self.target_width,
                self.target_height,
                data[..width * height * 3].to_vec(),
            )
        } else {
            // Need to remove padding
            let mut pixels = Vec::with_capacity(width * height * 3);
            for y in 0..height {
                let row_start = y * stride;
                let row_end = row_start + width * 3;
                pixels.extend_from_slice(&data[row_start..row_end]);
            }
            RgbImage::from_raw(self.target_width, self.target_height, pixels)
        }
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
        let result = VideoDecoder::open("nonexistent.mp4", 360, 640);
        assert!(result.is_err());
    }
}
