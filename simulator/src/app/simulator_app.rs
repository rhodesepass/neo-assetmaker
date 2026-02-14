//! Main simulator application
//!
//! Implements the egui App trait for the pass simulator.

use std::path::PathBuf;
use std::time::{Duration, Instant};

use egui::{Color32, RichText, Vec2, Rect, Pos2, Stroke, FontId, Align2};
use image::RgbImage;
use tracing::{info, warn};

use crate::config::{EPConfig, FirmwareConfig, TransitionType, TransitionOptions, OverlayType, ArknightsOverlayOptions, ImageOverlayOptions};
use crate::app::state::EinkState;
use crate::render::{TransitionRenderer, OverlayRenderer, ImageLoader, generate_vertical_barcode_gradient, render_text_rotated_90, render_top_right_bar_text_rotated};
use crate::animation::AnimationController;
use crate::video::VideoPlayer;
use crate::ipc::{start_ipc_server, IpcMessage, IpcReceiver, IpcSender, ControlCommand};

use super::state::{PlayState, SimulatorState, TransitionPhase};

/// Frame interval for 50fps
const FRAME_INTERVAL: Duration = Duration::from_millis(20);

/// Main simulator application
pub struct SimulatorApp {
    /// Firmware configuration
    firmware_config: FirmwareConfig,
    /// Current EP configuration
    epconfig: Option<EPConfig>,
    /// Base directory for assets
    base_dir: PathBuf,
    /// Application directory for program resources (modular assets, etc.)
    app_dir: PathBuf,

    /// Simulator state
    state: SimulatorState,

    /// Video player
    video_player: VideoPlayer,

    /// Transition renderer
    transition_renderer: TransitionRenderer,
    /// Overlay renderer
    overlay_renderer: OverlayRenderer,
    /// Animation controller
    animation_controller: AnimationController,

    /// Last frame time for timing control
    last_frame_time: Instant,

    /// Current frame texture
    frame_texture: Option<egui::TextureHandle>,

    /// Reusable color buffer to avoid allocations every frame
    color_image_buffer: Vec<Color32>,

    /// UI state
    selected_transition_in: usize,
    selected_transition_loop: usize,

    /// Is first transition (forces SWIPE)
    is_first_transition: bool,

    /// IPC receiver
    ipc_rx: Option<IpcReceiver>,
    /// IPC sender
    ipc_tx: Option<IpcSender>,

    /// Image loader for textures
    image_loader: ImageLoader,

    /// Barcode texture (dynamically generated)
    barcode_texture: Option<egui::TextureHandle>,

    /// Class icon texture
    class_icon_texture: Option<egui::TextureHandle>,

    /// Logo texture
    logo_texture: Option<egui::TextureHandle>,

    /// Image overlay texture (for OverlayType::Image)
    image_overlay_texture: Option<egui::TextureHandle>,

    /// Transition image texture (for transition effect)
    transition_image_texture: Option<egui::TextureHandle>,

    /// Transition image raw pixel data (for direct pixel access during transition)
    transition_image_data: Option<(Vec<Color32>, usize, usize)>, // (pixels, width, height)

    /// AK progress bar image texture (from res/ak_bar.png)
    ak_bar_texture: Option<egui::TextureHandle>,

    /// Top-right arrow image texture (from res/top_right_arrow.png)
    top_right_arrow_texture: Option<egui::TextureHandle>,

    /// Left upper L-shape black decoration (modular asset)
    top_left_rect_texture: Option<egui::TextureHandle>,

    /// Left upper Rhodes decoration below L-shape (modular asset)
    top_left_rhodes_texture: Option<egui::TextureHandle>,

    /// Right upper yellow bar + full vertical bar (modular asset)
    top_right_bar_texture: Option<egui::TextureHandle>,

    /// Left side colorful gradient bar (modular asset)
    btm_left_bar_texture: Option<egui::TextureHandle>,

    /// Pre-rendered rotated text texture for top_left_rhodes custom text
    top_left_rhodes_text_texture: Option<egui::TextureHandle>,
    /// Pre-rendered rotated text texture for top_right_bar custom text
    top_right_bar_text_texture: Option<egui::TextureHandle>,
    /// Cached text value to detect changes
    cached_rhodes_text: String,
    /// Cached text value to detect changes
    cached_top_right_bar_text: String,

    /// Whether textures have been loaded for current config
    textures_loaded: bool,
}

impl SimulatorApp {
    /// Create new simulator application
    pub fn new(
        _cc: &eframe::CreationContext<'_>,
        initial_config: Option<EPConfig>,
        base_dir: PathBuf,
        app_dir: PathBuf,
        pipe_name: Option<String>,
        use_stdio: bool,
        cropbox: Option<(u32, u32, u32, u32)>,
        rotation: i32,
    ) -> Self {
        let firmware_config = FirmwareConfig::get_default();
        let width = firmware_config.overlay_width();
        let height = firmware_config.overlay_height();

        let mut state = SimulatorState::new();

        // Set appear time from config if available
        if let Some(ref config) = initial_config {
            let appear_us = config.get_appear_time();
            state.appear_time_frames = microseconds_to_frames(appear_us, firmware_config.fps());
        }

        // Create video player with cropbox and rotation
        let mut video_player = VideoPlayer::new(width, height, cropbox, rotation);

        // Load videos from config
        if let Some(ref config) = initial_config {
            video_player.load_from_config(config, &base_dir);
        }

        // Start IPC server if requested
        let (ipc_rx, ipc_tx) = if use_stdio || pipe_name.is_some() {
            match start_ipc_server(pipe_name.clone(), use_stdio) {
                Some((rx, tx)) => {
                    info!("IPC server started");
                    (Some(rx), Some(tx))
                }
                None => (None, None),
            }
        } else {
            (None, None)
        };

        info!(
            "Simulator initialized: {}x{} @ {}fps",
            width, height,
            firmware_config.fps()
        );

        // Auto-start playback if config was provided via command line
        let auto_start = initial_config.is_some();

        // Read transition settings from config
        let (selected_transition_in, selected_transition_loop) = if let Some(ref config) = initial_config {
            let trans_in = config.get_transition_in_type();
            let trans_loop = config.get_transition_loop_type();
            info!("Transition settings from config: in={:?}, loop={:?}", trans_in, trans_loop);
            (
                Self::transition_type_to_index(trans_in),
                Self::transition_type_to_index(trans_loop),
            )
        } else {
            (0, 0) // Default to Fade
        };

        // Pre-allocate color buffer for frame rendering
        let buffer_size = (width * height) as usize;

        let mut app = Self {
            firmware_config: firmware_config.clone(),
            epconfig: initial_config,
            base_dir: base_dir.clone(),
            app_dir,
            state,
            video_player,
            transition_renderer: TransitionRenderer::new(firmware_config.clone()),
            overlay_renderer: OverlayRenderer::new(firmware_config.clone()),
            animation_controller: AnimationController::new(firmware_config),
            last_frame_time: Instant::now(),
            frame_texture: None,
            color_image_buffer: Vec::with_capacity(buffer_size),
            selected_transition_in,
            selected_transition_loop,
            is_first_transition: true,
            ipc_rx,
            ipc_tx,
            image_loader: ImageLoader::new(base_dir),
            barcode_texture: None,
            class_icon_texture: None,
            logo_texture: None,
            image_overlay_texture: None,
            transition_image_texture: None,
            transition_image_data: None,
            ak_bar_texture: None,
            top_right_arrow_texture: None,
            top_left_rect_texture: None,
            top_left_rhodes_texture: None,
            top_right_bar_texture: None,
            btm_left_bar_texture: None,
            top_left_rhodes_text_texture: None,
            top_right_bar_text_texture: None,
            cached_rhodes_text: String::new(),
            cached_top_right_bar_text: String::new(),
            textures_loaded: false,
        };

        // Auto-start playback if config was provided
        if auto_start && app.video_player.has_loop() {
            info!("Auto-starting playback...");
            app.start_playback();
        }

        app
    }

    /// Load a new configuration
    pub fn load_config(&mut self, config: EPConfig, base_dir: PathBuf) {
        // Update appear time
        let appear_us = config.get_appear_time();
        self.state.appear_time_frames = microseconds_to_frames(appear_us, self.firmware_config.fps());

        // Load videos
        self.video_player.load_from_config(&config, &base_dir);

        // Apply transition settings from config
        let trans_in = config.get_transition_in_type();
        if trans_in != TransitionType::None {
            self.selected_transition_in = Self::transition_type_to_index(trans_in);
        }
        let trans_loop = config.get_transition_loop_type();
        if trans_loop != TransitionType::None {
            self.selected_transition_loop = Self::transition_type_to_index(trans_loop);
        }

        self.epconfig = Some(config);
        self.base_dir = base_dir.clone();
        self.reset_playback();

        // Reset textures for new config
        self.image_loader.set_base_dir(base_dir);
        self.barcode_texture = None;
        self.class_icon_texture = None;
        self.logo_texture = None;
        self.image_overlay_texture = None;
        self.transition_image_texture = None;
        self.transition_image_data = None;
        self.ak_bar_texture = None;
        self.top_right_arrow_texture = None;
        self.top_left_rect_texture = None;
        self.top_left_rhodes_texture = None;
        self.top_right_bar_texture = None;
        self.btm_left_bar_texture = None;
        self.top_left_rhodes_text_texture = None;
        self.top_right_bar_text_texture = None;
        self.cached_rhodes_text.clear();
        self.cached_top_right_bar_text.clear();
        self.textures_loaded = false;

        info!("Configuration loaded");
    }

    /// Get transition type from index
    fn transition_type_from_index(index: usize) -> TransitionType {
        match index {
            0 => TransitionType::Fade,
            1 => TransitionType::Move,
            2 => TransitionType::Swipe,
            _ => TransitionType::None,
        }
    }

    /// Get index from transition type
    fn transition_type_to_index(trans_type: TransitionType) -> usize {
        match trans_type {
            TransitionType::Fade => 0,
            TransitionType::Move => 1,
            TransitionType::Swipe => 2,
            TransitionType::None => 3,
        }
    }

    /// Get transition frames
    fn get_transition_frames(&self, is_intro: bool) -> u32 {
        let fps = self.firmware_config.fps();
        let default_frames = self.firmware_config.transition.default_frames;

        if let Some(ref config) = self.epconfig {
            let duration = if is_intro {
                config.get_transition_in_duration()
            } else {
                config.get_transition_loop_duration()
            };

            if duration > 0 {
                // Total duration = 3 × stage duration
                let stage_frames = microseconds_to_frames(duration, fps);
                return stage_frames * 3;
            }
        }

        default_frames
    }

    /// Start playback
    fn start_playback(&mut self) {
        let has_intro = self.video_player.has_intro();

        // Firmware behavior: first transition is always SWIPE
        let transition_type = if self.is_first_transition {
            self.is_first_transition = false;
            TransitionType::Swipe
        } else {
            Self::transition_type_from_index(
                if has_intro { self.selected_transition_in } else { self.selected_transition_loop }
            )
        };

        let total_frames = self.get_transition_frames(has_intro);

        self.state.start_playback(has_intro, transition_type, total_frames);
        self.animation_controller.reset();

        // Reset frame accumulators for FPS sync
        self.state.loop_frame_accumulator = 0;
        self.state.intro_frame_accumulator = 0;

        // Prepare videos
        if has_intro {
            self.video_player.seek_intro_to_start();
        }
        self.video_player.seek_loop_to_start();

        info!("Playback started: has_intro={}, transition={:?}", has_intro, transition_type);
    }

    /// Reset playback
    fn reset_playback(&mut self) {
        self.state.reset();
        self.animation_controller.reset();
        self.video_player.reset();
        self.is_first_transition = true;
        info!("Playback reset");
    }

    /// Handle IPC messages
    fn handle_ipc_messages(&mut self) {
        // Collect messages first to avoid borrow issues
        let messages: Vec<IpcMessage> = if let Some(ref rx) = self.ipc_rx {
            let mut msgs = Vec::new();
            while let Some(msg) = rx.try_recv() {
                msgs.push(msg);
            }
            msgs
        } else {
            return;
        };

        for msg in messages {
            match msg {
                IpcMessage::LoadConfig { config, base_dir } => {
                    self.load_config(config, PathBuf::from(base_dir));
                }
                IpcMessage::Control(cmd) => match cmd {
                    ControlCommand::Play => {
                        if self.state.play_state == PlayState::Idle {
                            self.start_playback();
                        } else {
                            self.state.resume();
                        }
                    }
                    ControlCommand::Pause => {
                        self.state.pause();
                    }
                    ControlCommand::Stop | ControlCommand::Reset => {
                        self.reset_playback();
                    }
                    ControlCommand::SeekTo(state) => {
                        // Seek to specific state
                        if let Some(play_state) = PlayState::from_u8(state) {
                            self.state.play_state = play_state;
                        }
                    }
                },
                IpcMessage::SetTransition { transition_in, transition_loop } => {
                    self.selected_transition_in = match transition_in.as_str() {
                        "fade" => 0,
                        "move" => 1,
                        "swipe" => 2,
                        _ => 3,
                    };
                    self.selected_transition_loop = match transition_loop.as_str() {
                        "fade" => 0,
                        "move" => 1,
                        "swipe" => 2,
                        _ => 3,
                    };
                }
                IpcMessage::Shutdown => {
                    info!("Received shutdown command");
                    std::process::exit(0);
                }
                _ => {}
            }
        }
    }

    /// Send state update via IPC
    fn send_state_update(&self) {
        if let Some(ref tx) = self.ipc_tx {
            let msg = IpcMessage::state_update(
                self.state.play_state,
                self.state.frame_counter as u64,
                self.state.is_playing,
            );
            tx.send(msg);
        }
    }

    /// Update simulation state
    fn update_simulation(&mut self) {
        if !self.state.is_playing {
            return;
        }

        self.state.frame_counter += 1;

        match self.state.play_state {
            PlayState::TransitionIn => self.process_transition_in(),
            PlayState::Intro => self.process_intro(),
            PlayState::TransitionLoop => self.process_transition_loop(),
            PlayState::PreOpinfo => self.process_pre_opinfo(),
            PlayState::Loop => self.process_loop(),
            PlayState::Idle => {}
        }

        // Send state update every 10 frames
        if self.state.frame_counter % 10 == 0 {
            self.send_state_update();
        }
    }

    fn process_transition_in(&mut self) {
        self.state.transition.frame += 1;
        let phase = self.state.transition.phase();

        // Switch video during hold phase
        if phase == TransitionPhase::PhaseHold && !self.state.transition.video_switched {
            self.state.transition.video_switched = true;
            self.video_player.seek_intro_to_start();
        }

        // Transition complete
        if self.state.transition.is_complete() {
            self.state.play_state = PlayState::Intro;
            self.state.intro_frame_accumulator = 0;  // Reset for FPS sync
            self.video_player.seek_intro_to_start();
        }
    }

    fn process_intro(&mut self) {
        // Calculate video frame duration (microseconds)
        let video_fps = self.video_player.intro_fps();
        let frame_duration_us = (1_000_000.0 / video_fps) as i64;

        // Accumulate time (50fps render = 20ms = 20000us per tick)
        self.state.intro_frame_accumulator += 20000;

        // Advance video frame only when accumulated time exceeds frame duration
        if self.state.intro_frame_accumulator >= frame_duration_us {
            self.state.intro_frame_accumulator -= frame_duration_us;
            // Advance to next intro video frame (updates internal cache)
            if !self.video_player.advance_intro_frame() {
                // Intro video ended, start transition to loop
                self.start_transition_loop();
            }
        }
    }

    fn start_transition_loop(&mut self) {
        self.state.play_state = PlayState::TransitionLoop;
        let transition_type = Self::transition_type_from_index(self.selected_transition_loop);
        let total_frames = self.get_transition_frames(false);
        self.state.transition.reset(transition_type, total_frames);
    }

    fn process_transition_loop(&mut self) {
        self.state.transition.frame += 1;
        let phase = self.state.transition.phase();

        // Switch video during hold phase
        if phase == TransitionPhase::PhaseHold && !self.state.transition.video_switched {
            self.state.transition.video_switched = true;
            self.video_player.seek_loop_to_start();
        }

        // Transition complete
        if self.state.transition.is_complete() {
            self.state.play_state = PlayState::PreOpinfo;
            self.state.pre_opinfo_counter = 0;
            self.state.loop_frame_accumulator = 0;  // Reset for FPS sync
            self.video_player.seek_loop_to_start();
        }
    }

    fn process_pre_opinfo(&mut self) {
        self.state.pre_opinfo_counter += 1;

        // Calculate video frame duration (microseconds)
        let video_fps = self.video_player.loop_fps();
        let frame_duration_us = (1_000_000.0 / video_fps) as i64;

        // Accumulate time (50fps render = 20ms = 20000us per tick)
        self.state.loop_frame_accumulator += 20000;

        // Advance loop video frame only when accumulated time exceeds frame duration
        if self.state.loop_frame_accumulator >= frame_duration_us {
            self.state.loop_frame_accumulator -= frame_duration_us;
            self.video_player.advance_loop_frame();
        }

        // Wait for appear_time
        if self.state.pre_opinfo_counter >= self.state.appear_time_frames {
            self.state.play_state = PlayState::Loop;
            self.animation_controller.reset();
            self.animation_controller.start_entry_animation();
        }
    }

    fn process_loop(&mut self) {
        // Calculate video frame duration (microseconds)
        let video_fps = self.video_player.loop_fps();
        let frame_duration_us = (1_000_000.0 / video_fps) as i64;

        // Accumulate time (50fps render = 20ms = 20000us per tick)
        self.state.loop_frame_accumulator += 20000;

        // Advance loop video frame only when accumulated time exceeds frame duration
        if self.state.loop_frame_accumulator >= frame_duration_us {
            self.state.loop_frame_accumulator -= frame_duration_us;
            self.video_player.advance_loop_frame();
        }

        // Update animation
        self.animation_controller.update(&mut self.state.animation);
    }

    /// Update a color buffer from an RgbImage
    /// Takes the buffer as a separate parameter to avoid borrow checker issues
    fn update_color_buffer(buffer: &mut Vec<Color32>, img: &RgbImage) {
        let pixels = img.as_raw();
        let len = img.width() as usize * img.height() as usize;

        // Clear and reuse the existing buffer
        buffer.clear();

        // Reserve capacity if needed (only allocates if buffer is too small)
        if buffer.capacity() < len {
            buffer.reserve(len - buffer.capacity());
        }

        // Convert RGB pixels to Color32
        for i in 0..len {
            let idx = i * 3;
            buffer.push(Color32::from_rgb(
                pixels[idx],
                pixels[idx + 1],
                pixels[idx + 2],
            ));
        }
    }

    /// Fill color buffer with black pixels
    fn fill_color_buffer_black(buffer: &mut Vec<Color32>, width: usize, height: usize) {
        let len = width * height;
        buffer.clear();
        if buffer.capacity() < len {
            buffer.reserve(len - buffer.capacity());
        }
        buffer.resize(len, Color32::BLACK);
    }

    /// Render the current frame
    fn render_frame(&mut self, ctx: &egui::Context) {
        let width = self.firmware_config.overlay_width() as usize;
        let height = self.firmware_config.overlay_height() as usize;

        // Determine frame source based on current state (avoids multiple borrows)
        enum FrameSource {
            Loop,
            Intro,
            Black,
        }

        let source = match self.state.play_state {
            PlayState::Idle => FrameSource::Loop,
            PlayState::TransitionIn => FrameSource::Loop,
            PlayState::Intro => FrameSource::Intro,
            PlayState::TransitionLoop => {
                if self.state.transition.video_switched {
                    FrameSource::Loop
                } else {
                    FrameSource::Intro
                }
            }
            PlayState::PreOpinfo | PlayState::Loop => FrameSource::Loop,
        };

        // Update color buffer from the appropriate frame source (using references, no clone)
        let has_frame = match source {
            FrameSource::Loop => {
                if let Some(frame) = self.video_player.get_loop_current_frame() {
                    Self::update_color_buffer(&mut self.color_image_buffer, frame);
                    true
                } else {
                    false
                }
            }
            FrameSource::Intro => {
                if let Some(frame) = self.video_player.get_intro_last_frame() {
                    Self::update_color_buffer(&mut self.color_image_buffer, frame);
                    true
                } else {
                    false
                }
            }
            FrameSource::Black => false,
        };

        // Fill with black if no frame available
        if !has_frame {
            Self::fill_color_buffer_black(&mut self.color_image_buffer, width, height);
        }

        // Create ColorImage from the buffer
        // We clone here because egui needs ownership, but the buffer retains its capacity for reuse
        // The main memory savings come from not cloning RgbImage (2.7MB per frame saved)
        let mut image = egui::ColorImage {
            size: [width, height],
            pixels: self.color_image_buffer.clone(),
        };

        // Apply transition effect if in transition state
        if matches!(self.state.play_state, PlayState::TransitionIn | PlayState::TransitionLoop) {
            self.apply_transition_overlay(&mut image);
        }

        // If in loop state with arknights overlay, render color fade at pixel level
        if self.state.play_state == PlayState::Loop {
            if let Some(ref config) = self.epconfig {
                if let Some(ref overlay) = config.overlay {
                    if overlay.overlay_type == OverlayType::Arknights {
                        self.render_color_fade(&mut image.pixels, width, height);
                    }
                }
            }
        }

        // Update texture
        if let Some(ref mut texture) = self.frame_texture {
            texture.set(image, egui::TextureOptions::NEAREST);
        } else {
            self.frame_texture = Some(ctx.load_texture(
                "frame",
                image,
                egui::TextureOptions::NEAREST,
            ));
        }
    }

    /// Apply transition overlay effect to the image
    fn apply_transition_overlay(&self, image: &mut egui::ColorImage) {
        let progress = self.state.transition.progress();
        let trans_type = self.state.transition.transition_type;
        let phase = self.state.transition.phase();
        let width = image.size[0];
        let height = image.size[1];

        // Get transition options based on current state
        let is_intro = self.state.play_state == PlayState::TransitionIn;
        let options = self.get_transition_options(is_intro);

        // Get background color from config (default black)
        let bg_color = options
            .map(|o| Self::parse_hex_color(&o.background_color))
            .unwrap_or(Color32::BLACK);

        // Check if we have a transition image and we're in Hold phase
        let has_transition_image = options
            .map(|o| !o.image.is_empty())
            .unwrap_or(false);

        match trans_type {
            TransitionType::Fade => {
                // Calculate fade alpha based on progress
                let alpha = self.transition_renderer.calculate_fade_alpha(progress);

                // During Hold phase with transition image, show the image
                if phase == TransitionPhase::PhaseHold && has_transition_image {
                    if let Some((ref trans_pixels, trans_width, trans_height)) = self.transition_image_data {
                        // Calculate aspect-ratio-preserving scale (contain mode, centered)
                        let screen_aspect = width as f32 / height as f32;
                        let image_aspect = trans_width as f32 / trans_height as f32;

                        let (scaled_w, scaled_h, offset_x, offset_y) = if image_aspect > screen_aspect {
                            // Image is wider - fit to width
                            let scaled_w = width as f32;
                            let scaled_h = width as f32 / image_aspect;
                            let offset_y = ((height as f32 - scaled_h) / 2.0) as i32;
                            (scaled_w, scaled_h, 0i32, offset_y)
                        } else {
                            // Image is taller - fit to height
                            let scaled_h = height as f32;
                            let scaled_w = height as f32 * image_aspect;
                            let offset_x = ((width as f32 - scaled_w) / 2.0) as i32;
                            (scaled_w, scaled_h, offset_x, 0i32)
                        };

                        for (i, pixel) in image.pixels.iter_mut().enumerate() {
                            let x = i % width;
                            let y = i / width;

                            // Map screen coordinates to source image coordinates
                            let src_x = ((x as i32 - offset_x) as f32 * trans_width as f32 / scaled_w) as i32;
                            let src_y = ((y as i32 - offset_y) as f32 * trans_height as f32 / scaled_h) as i32;

                            if src_x >= 0 && src_x < trans_width as i32 && src_y >= 0 && src_y < trans_height as i32 {
                                let tex_idx = src_y as usize * trans_width + src_x as usize;
                                if tex_idx < trans_pixels.len() {
                                    let trans_pixel = trans_pixels[tex_idx];
                                    let blend = alpha as f32 / 255.0;
                                    let inv_blend = 1.0 - blend;
                                    *pixel = Color32::from_rgb(
                                        ((trans_pixel.r() as f32 * blend) + (pixel.r() as f32 * inv_blend)) as u8,
                                        ((trans_pixel.g() as f32 * blend) + (pixel.g() as f32 * inv_blend)) as u8,
                                        ((trans_pixel.b() as f32 * blend) + (pixel.b() as f32 * inv_blend)) as u8,
                                    );
                                }
                            } else {
                                // Outside bounds - fill with background color
                                let blend = alpha as f32 / 255.0;
                                let inv_blend = 1.0 - blend;
                                *pixel = Color32::from_rgb(
                                    ((bg_color.r() as f32 * blend) + (pixel.r() as f32 * inv_blend)) as u8,
                                    ((bg_color.g() as f32 * blend) + (pixel.g() as f32 * inv_blend)) as u8,
                                    ((bg_color.b() as f32 * blend) + (pixel.b() as f32 * inv_blend)) as u8,
                                );
                            }
                        }
                        return;
                    }
                }

                // Apply background color overlay with alpha (instead of hardcoded black)
                for pixel in image.pixels.iter_mut() {
                    let blend = alpha as f32 / 255.0;
                    let inv_blend = 1.0 - blend;

                    *pixel = Color32::from_rgb(
                        ((bg_color.r() as f32 * blend) + (pixel.r() as f32 * inv_blend)) as u8,
                        ((bg_color.g() as f32 * blend) + (pixel.g() as f32 * inv_blend)) as u8,
                        ((bg_color.b() as f32 * blend) + (pixel.b() as f32 * inv_blend)) as u8,
                    );
                }
            }
            TransitionType::Move => {
                // Calculate move offset
                let offset = self.transition_renderer.calculate_move_offset(progress);

                // During Hold phase with transition image, fill above the line with bg_color
                if phase == TransitionPhase::PhaseHold {
                    // Fill area above the offset line with background color
                    for y in 0..(offset as usize).min(height) {
                        for x in 0..width {
                            let idx = y * width + x;
                            image.pixels[idx] = bg_color;
                        }
                    }
                }

                // Draw line at the offset position
                if offset > 0 && (offset as usize) < height {
                    for x in 0..width {
                        image.pixels[offset as usize * width + x] = Color32::WHITE;
                    }
                }
            }
            TransitionType::Swipe => {
                // Calculate swipe progress (0.0 to 1.0)
                let swipe_progress = self.transition_renderer.calculate_swipe_progress(progress);
                let swipe_y = (swipe_progress * height as f32) as usize;

                // Draw swipe line
                if swipe_y > 0 && swipe_y < height {
                    for x in 0..width {
                        image.pixels[swipe_y * width + x] = Color32::from_rgb(200, 200, 200);
                    }

                    // Fill area above swipe line with background color (or darkened if no bg specified)
                    for y in 0..swipe_y.min(height) {
                        for x in 0..width {
                            let idx = y * width + x;
                            if bg_color != Color32::BLACK {
                                // Use configured background color
                                image.pixels[idx] = bg_color;
                            } else {
                                // Default: darken the existing pixels
                                let p = image.pixels[idx];
                                image.pixels[idx] = Color32::from_rgb(
                                    p.r() / 3,
                                    p.g() / 3,
                                    p.b() / 3,
                                );
                            }
                        }
                    }
                }
            }
            TransitionType::None => {}
        }
    }

    /// Render color fade effect at pixel level (blends with video)
    fn render_color_fade(&self, pixels: &mut [Color32], width: usize, height: usize) {
        let anim = &self.state.animation;
        let radius = anim.color_fade_radius as usize;

        if radius == 0 {
            return;
        }

        // Get theme color
        let theme_color = self.get_theme_color();

        // Draw color fade in bottom-right corner (matching C firmware draw_color_fade)
        for x in 0..radius.min(width) {
            for y in 0..radius.min(height) {
                // C firmware: if(x+y > radius - 2) break;
                if x + y > radius.saturating_sub(2) {
                    break;
                }

                // Calculate alpha: 255 - ((x+y)*255 / radius)
                let alpha = 255.0 - ((x + y) as f32 * 255.0 / radius as f32);
                let alpha = (alpha * 0.8).clamp(0.0, 255.0) as u8; // Slightly reduce opacity

                // Calculate real coordinates (bottom-right corner)
                let real_x = width - x - 1;
                let real_y = height - y - 1;

                if real_y < height && real_x < width {
                    let idx = real_y * width + real_x;
                    // Blend with existing pixel
                    let bg = pixels[idx];
                    pixels[idx] = Self::blend_colors(bg, theme_color, alpha);
                }
            }
        }
    }

    /// Blend two colors with alpha
    fn blend_colors(bg: Color32, fg: Color32, alpha: u8) -> Color32 {
        let a = alpha as f32 / 255.0;
        let inv_a = 1.0 - a;

        Color32::from_rgb(
            ((fg.r() as f32 * a) + (bg.r() as f32 * inv_a)) as u8,
            ((fg.g() as f32 * a) + (bg.g() as f32 * inv_a)) as u8,
            ((fg.b() as f32 * a) + (bg.b() as f32 * inv_a)) as u8,
        )
    }

    /// Parse hex color string to Color32
    fn parse_hex_color(hex: &str) -> Color32 {
        let hex = hex.trim_start_matches('#');

        if hex.len() >= 6 {
            let r = u8::from_str_radix(&hex[0..2], 16).unwrap_or(0);
            let g = u8::from_str_radix(&hex[2..4], 16).unwrap_or(0);
            let b = u8::from_str_radix(&hex[4..6], 16).unwrap_or(0);
            Color32::from_rgb(r, g, b)
        } else {
            Color32::WHITE
        }
    }

    /// Get theme color from config
    fn get_theme_color(&self) -> Color32 {
        self.get_arknights_options()
            .map(|opts| Self::parse_hex_color(&opts.color))
            .unwrap_or(Color32::from_rgb(255, 100, 100))
    }

    /// Get ArknightsOverlayOptions from config
    fn get_arknights_options(&self) -> Option<ArknightsOverlayOptions> {
        self.epconfig
            .as_ref()
            .and_then(|c| c.overlay.as_ref())
            .and_then(|o| o.arknights_options())
    }

    /// Get ImageOverlayOptions from config
    fn get_image_overlay_options(&self) -> Option<ImageOverlayOptions> {
        self.epconfig
            .as_ref()
            .and_then(|c| c.overlay.as_ref())
            .and_then(|o| o.image_options())
    }

    /// Get transition options for current state (in or loop)
    fn get_transition_options(&self, is_intro: bool) -> Option<&TransitionOptions> {
        self.epconfig.as_ref().and_then(|config| {
            if is_intro {
                config.transition_in.as_ref().and_then(|t| t.options.as_ref())
            } else {
                config.transition_loop.as_ref().and_then(|t| t.options.as_ref())
            }
        })
    }

    /// Load textures for the current configuration
    fn load_textures(&mut self, ctx: &egui::Context) {
        if self.textures_loaded {
            return;
        }

        // Load ak_bar.png from resources/data directory
        if self.ak_bar_texture.is_none() {
            let ak_bar_path = self.app_dir.join("resources/data/ak_bar.png");
            if let Ok(img) = image::open(&ak_bar_path) {
                let rgba = img.to_rgba8();
                let size = [rgba.width() as usize, rgba.height() as usize];
                let pixels: Vec<Color32> = rgba
                    .pixels()
                    .map(|p| Color32::from_rgba_unmultiplied(p[0], p[1], p[2], p[3]))
                    .collect();
                let color_image = egui::ColorImage { size, pixels };
                self.ak_bar_texture = Some(ctx.load_texture(
                    "ak_bar",
                    color_image,
                    egui::TextureOptions::LINEAR,
                ));
                info!("Loaded ak_bar.png: {}", ak_bar_path.display());
            } else {
                warn!("Failed to load ak_bar.png: {}", ak_bar_path.display());
            }
        }

        // Load top_right_arrow.png from resources/data directory
        if self.top_right_arrow_texture.is_none() {
            let arrow_path = self.app_dir.join("resources/data/top_right_arrow.png");
            if let Ok(img) = image::open(&arrow_path) {
                let rgba = img.to_rgba8();
                let size = [rgba.width() as usize, rgba.height() as usize];
                let pixels: Vec<Color32> = rgba
                    .pixels()
                    .map(|p| Color32::from_rgba_unmultiplied(p[0], p[1], p[2], p[3]))
                    .collect();
                let color_image = egui::ColorImage { size, pixels };
                self.top_right_arrow_texture = Some(ctx.load_texture(
                    "top_right_arrow",
                    color_image,
                    egui::TextureOptions::LINEAR,
                ));
                info!("Loaded top_right_arrow.png: {}", arrow_path.display());
            } else {
                warn!("Failed to load top_right_arrow.png: {}", arrow_path.display());
            }
        }

        // Load modular decoration textures

        // Load top_left_rect.png (L-shape black decoration at top-left)
        if self.top_left_rect_texture.is_none() {
            let path = self.app_dir.join("resources/data/top_left_rect.png");
            if let Ok(img) = image::open(&path) {
                let rgba = img.to_rgba8();
                let size = [rgba.width() as usize, rgba.height() as usize];
                let pixels: Vec<Color32> = rgba
                    .pixels()
                    .map(|p| Color32::from_rgba_unmultiplied(p[0], p[1], p[2], p[3]))
                    .collect();
                let color_image = egui::ColorImage { size, pixels };
                self.top_left_rect_texture = Some(ctx.load_texture(
                    "top_left_rect",
                    color_image,
                    egui::TextureOptions::LINEAR,
                ));
                info!("Loaded top_left_rect.png: {}", path.display());
            } else {
                warn!("Failed to load top_left_rect.png: {}", path.display());
            }
        }

        // Load top_left_rhodes.png (Rhodes decoration below L-shape)
        if self.top_left_rhodes_texture.is_none() {
            let path = self.app_dir.join("resources/data/top_left_rhodes.png");
            if let Ok(img) = image::open(&path) {
                let rgba = img.to_rgba8();
                let size = [rgba.width() as usize, rgba.height() as usize];
                let pixels: Vec<Color32> = rgba
                    .pixels()
                    .map(|p| Color32::from_rgba_unmultiplied(p[0], p[1], p[2], p[3]))
                    .collect();
                let color_image = egui::ColorImage { size, pixels };
                self.top_left_rhodes_texture = Some(ctx.load_texture(
                    "top_left_rhodes",
                    color_image,
                    egui::TextureOptions::LINEAR,
                ));
                info!("Loaded top_left_rhodes.png: {}", path.display());
            } else {
                warn!("Failed to load top_left_rhodes.png: {}", path.display());
            }
        }

        // Load top_right_bar.png (yellow bar + full vertical bar on right)
        if self.top_right_bar_texture.is_none() {
            let path = self.app_dir.join("resources/data/top_right_bar.png");
            if let Ok(img) = image::open(&path) {
                let rgba = img.to_rgba8();
                let size = [rgba.width() as usize, rgba.height() as usize];
                let pixels: Vec<Color32> = rgba
                    .pixels()
                    .map(|p| Color32::from_rgba_unmultiplied(p[0], p[1], p[2], p[3]))
                    .collect();
                let color_image = egui::ColorImage { size, pixels };
                self.top_right_bar_texture = Some(ctx.load_texture(
                    "top_right_bar",
                    color_image,
                    egui::TextureOptions::LINEAR,
                ));
                info!("Loaded top_right_bar.png: {}", path.display());
            } else {
                warn!("Failed to load top_right_bar.png: {}", path.display());
            }
        }

        // Load btm_left_bar.png (colorful gradient bar on left side)
        if self.btm_left_bar_texture.is_none() {
            let path = self.app_dir.join("resources/data/btm_left_bar.png");
            if let Ok(img) = image::open(&path) {
                let rgba = img.to_rgba8();
                let size = [rgba.width() as usize, rgba.height() as usize];
                let pixels: Vec<Color32> = rgba
                    .pixels()
                    .map(|p| Color32::from_rgba_unmultiplied(p[0], p[1], p[2], p[3]))
                    .collect();
                let color_image = egui::ColorImage { size, pixels };
                self.btm_left_bar_texture = Some(ctx.load_texture(
                    "btm_left_bar",
                    color_image,
                    egui::TextureOptions::LINEAR,
                ));
                info!("Loaded btm_left_bar.png: {}", path.display());
            } else {
                warn!("Failed to load btm_left_bar.png: {}", path.display());
            }
        }

        // Load image overlay texture if type is Image
        if let Some(image_opts) = self.get_image_overlay_options() {
            if !image_opts.image.is_empty() && self.image_overlay_texture.is_none() {
                let image_path = self.image_loader.resolve_path(&image_opts.image);
                if let Ok(img) = image::open(&image_path) {
                    let rgba = img.to_rgba8();
                    let size = [rgba.width() as usize, rgba.height() as usize];
                    let pixels: Vec<Color32> = rgba
                        .pixels()
                        .map(|p| Color32::from_rgba_unmultiplied(p[0], p[1], p[2], p[3]))
                        .collect();
                    let color_image = egui::ColorImage { size, pixels };
                    self.image_overlay_texture = Some(ctx.load_texture(
                        "image_overlay",
                        color_image,
                        egui::TextureOptions::LINEAR,
                    ));
                    info!("Loaded image overlay: {}", image_path.display());
                } else {
                    warn!("Failed to load image overlay: {}", image_path.display());
                }
            }
        }

        // Load transition image texture if specified in transition_in or transition_loop
        if self.transition_image_texture.is_none() {
            // Check transition_in first, then transition_loop
            let image_path = self.get_transition_options(true)
                .filter(|opts| !opts.image.is_empty())
                .map(|opts| opts.image.clone())
                .or_else(|| {
                    self.get_transition_options(false)
                        .filter(|opts| !opts.image.is_empty())
                        .map(|opts| opts.image.clone())
                });

            if let Some(image_file) = image_path {
                let resolved_path = self.image_loader.resolve_path(&image_file);
                if let Ok(img) = image::open(&resolved_path) {
                    let rgba = img.to_rgba8();
                    let img_width = rgba.width() as usize;
                    let img_height = rgba.height() as usize;
                    let size = [img_width, img_height];
                    let pixels: Vec<Color32> = rgba
                        .pixels()
                        .map(|p| Color32::from_rgba_unmultiplied(p[0], p[1], p[2], p[3]))
                        .collect();

                    // Store raw pixel data for direct access during transition
                    self.transition_image_data = Some((pixels.clone(), img_width, img_height));

                    let color_image = egui::ColorImage { size, pixels };
                    self.transition_image_texture = Some(ctx.load_texture(
                        "transition_image",
                        color_image,
                        egui::TextureOptions::LINEAR,
                    ));
                    info!("Loaded transition image: {}", resolved_path.display());
                } else {
                    warn!("Failed to load transition image: {}", resolved_path.display());
                }
            }
        }

        // Load Arknights-specific textures
        let options = match self.get_arknights_options() {
            Some(opts) => opts,
            None => {
                self.textures_loaded = true;
                return;
            }
        };

        // Generate barcode texture from barcode_text (with gradient colors)
        if !options.barcode_text.is_empty() && self.barcode_texture.is_none() {
            let barcode_width = self.firmware_config.layout.barcode.width;
            // Use gradient colors for barcode (purple → blue → cyan → yellow)
            if let Some(barcode_image) = generate_vertical_barcode_gradient(&options.barcode_text, barcode_width, true) {
                self.barcode_texture = Some(ctx.load_texture(
                    "barcode",
                    barcode_image,
                    egui::TextureOptions::NEAREST,
                ));
                info!("Generated gradient barcode texture");
            }
        }

        // Load class icon texture
        if !options.operator_class_icon.is_empty() && self.class_icon_texture.is_none() {
            let icon_path = self.image_loader.resolve_path(&options.operator_class_icon);
            if let Ok(img) = image::open(&icon_path) {
                let size = [img.width() as usize, img.height() as usize];
                let pixels: Vec<Color32> = img
                    .to_rgba8()
                    .pixels()
                    .map(|p| Color32::from_rgba_unmultiplied(p[0], p[1], p[2], p[3]))
                    .collect();
                let color_image = egui::ColorImage { size, pixels };
                self.class_icon_texture = Some(ctx.load_texture(
                    "class_icon",
                    color_image,
                    egui::TextureOptions::LINEAR,
                ));
                info!("Loaded class icon: {}", icon_path.display());
            } else {
                warn!("Failed to load class icon: {}", icon_path.display());
            }
        }

        // Load logo texture
        if !options.logo.is_empty() && self.logo_texture.is_none() {
            let logo_path = self.image_loader.resolve_path(&options.logo);
            if let Ok(img) = image::open(&logo_path) {
                let size = [img.width() as usize, img.height() as usize];
                let pixels: Vec<Color32> = img
                    .to_rgba8()
                    .pixels()
                    .map(|p| Color32::from_rgba_unmultiplied(p[0], p[1], p[2], p[3]))
                    .collect();
                let color_image = egui::ColorImage { size, pixels };
                self.logo_texture = Some(ctx.load_texture(
                    "logo",
                    color_image,
                    egui::TextureOptions::LINEAR,
                ));
                info!("Loaded logo: {}", logo_path.display());
            } else {
                warn!("Failed to load logo: {}", logo_path.display());
            }
        }

        self.textures_loaded = true;
    }

    /// Render complete overlay UI using egui Painter
    fn render_overlay_ui(&mut self, painter: &egui::Painter, image_rect: Rect) {
        let anim = &self.state.animation;
        let options = match self.get_arknights_options() {
            Some(opts) => opts,
            None => return,
        };

        // Calculate scaling factor (image might be scaled)
        let fw_width = self.firmware_config.overlay_width() as f32;
        let fw_height = self.firmware_config.overlay_height() as f32;
        let scale_x = image_rect.width() / fw_width;
        let scale_y = image_rect.height() / fw_height;

        // Calculate Y offset for entry animation
        let y_offset = anim.entry_y_offset as f32 * scale_y;

        // Get layout offsets
        let offsets = &self.firmware_config.layout.offsets;
        let btm_info_x = offsets.btm_info_x as f32 * scale_x + image_rect.min.x;
        let theme_color = self.get_theme_color();
        let entry_alpha = (anim.entry_progress * 255.0) as u8;

        // ============================================
        // 1. Render modular static decorations
        // ============================================
        self.render_modular_decorations(painter, image_rect, scale_x, scale_y, y_offset, entry_alpha, &options);

        // ============================================
        // 2. Render dynamic elements
        // ============================================

        // Arrow indicator (3 yellow chevrons pointing upward with scrolling animation)
        self.render_arrow_indicator(painter, image_rect, scale_x, scale_y, y_offset, theme_color);

        // Typewriter texts (operator name, code, staff_text, etc.)
        self.render_typewriter_texts(painter, image_rect, scale_x, scale_y, y_offset, &options, theme_color);

        // EINK areas (barcode with gradient, class icon)
        self.render_eink_areas(painter, image_rect, scale_x, scale_y, y_offset);

        // Divider lines (white color per C reference)
        self.render_divider_lines(painter, image_rect, scale_x, scale_y, y_offset, btm_info_x, theme_color);

        // Progress bar (AK bar)
        self.render_progress_bar(painter, image_rect, scale_x, scale_y, y_offset, btm_info_x, theme_color);

        // Logo image (dynamic fade-in)
        self.render_logo_image(painter, image_rect, scale_x, scale_y, y_offset);
    }

    /// Render modular static decorations (replaces overlay_template.png)
    ///
    /// Positions are based on hardware implementation (opinfo.c):
    /// - top_left_rhodes: (0, 0) - left upper corner origin
    /// - top_left_rect: (60, 0) - L-shape black decoration offset from left
    /// - top_right_bar: (360-width, 0) - right-aligned
    /// - btm_left_bar: (0, 640-height) - bottom-aligned
    fn render_modular_decorations(
        &mut self,
        painter: &egui::Painter,
        image_rect: Rect,
        scale_x: f32,
        scale_y: f32,
        y_offset: f32,
        entry_alpha: u8,
        options: &ArknightsOverlayOptions,
    ) {
        let tint = Color32::from_rgba_unmultiplied(255, 255, 255, entry_alpha);
        let uv_full = Rect::from_min_max(Pos2::ZERO, Pos2::new(1.0, 1.0));
        let fw_height = 640.0; // Firmware screen height

        // 1. top_left_rhodes - custom text or default image
        if !options.top_left_rhodes.is_empty() {
            // Custom text mode: render rotated text replacing default Rhodes logo
            // Per firmware opinfo.c:687-693: rect=(0, 5, 67, OPNAME_Y-5=410)
            if self.cached_rhodes_text != options.top_left_rhodes {
                let img = render_text_rotated_90(
                    &options.top_left_rhodes,
                    48.0, // Font size (scaled down from firmware's 72px for display)
                    Color32::WHITE,
                    false,
                );
                self.top_left_rhodes_text_texture = Some(
                    painter.ctx().load_texture("rhodes_text", img, egui::TextureOptions::LINEAR)
                );
                self.cached_rhodes_text = options.top_left_rhodes.clone();
            }
            if let Some(ref tex) = self.top_left_rhodes_text_texture {
                let tex_w = tex.size()[0] as f32;
                let tex_h = tex.size()[1] as f32;
                // Position at (0, 5), constrain to area 67x410
                let max_w = 67.0;
                let max_h = 410.0;
                let display_w = tex_w.min(max_w);
                let display_h = tex_h.min(max_h);
                let rect = Rect::from_min_size(
                    Pos2::new(image_rect.min.x, image_rect.min.y + 5.0 * scale_y + y_offset),
                    egui::vec2(display_w * scale_x, display_h * scale_y),
                );
                painter.image(tex.id(), rect, uv_full, tint);
            }
        } else {
            // Default: use top_left_rhodes.png image
            if let Some(ref tex) = self.top_left_rhodes_texture {
                let tex_w = tex.size()[0] as f32;
                let tex_h = tex.size()[1] as f32;
                let rect = Rect::from_min_size(
                    Pos2::new(image_rect.min.x, image_rect.min.y + y_offset),
                    egui::vec2(tex_w * scale_x, tex_h * scale_y),
                );
                painter.image(tex.id(), rect, uv_full, tint);
            }
        }

        // 2. top_left_rect - L-shape black decoration, positioned right after top_left_rhodes
        if let Some(ref tex) = self.top_left_rect_texture {
            let tex_w = tex.size()[0] as f32;
            let tex_h = tex.size()[1] as f32;

            // Use actual rhodes texture width for positioning
            let rhodes_width = if !options.top_left_rhodes.is_empty() {
                // When using custom text, use the text texture width
                self.top_left_rhodes_text_texture
                    .as_ref()
                    .map(|t| (t.size()[0] as f32).min(67.0))
                    .unwrap_or(60.0)
            } else {
                self.top_left_rhodes_texture
                    .as_ref()
                    .map(|t| t.size()[0] as f32)
                    .unwrap_or(60.0)
            };

            let rect = Rect::from_min_size(
                Pos2::new(
                    image_rect.min.x + rhodes_width * scale_x,
                    image_rect.min.y + y_offset,
                ),
                egui::vec2(tex_w * scale_x, tex_h * scale_y),
            );
            painter.image(tex.id(), rect, uv_full, tint);
        }

        // 3. top_right_bar (360-width, 0) - right-aligned
        if let Some(ref tex) = self.top_right_bar_texture {
            let tex_w = tex.size()[0] as f32;
            let tex_h = tex.size()[1] as f32;
            let bar_x = image_rect.max.x - tex_w * scale_x;
            let rect = Rect::from_min_size(
                Pos2::new(bar_x, image_rect.min.y + y_offset),
                egui::vec2(tex_w * scale_x, tex_h * scale_y),
            );
            painter.image(tex.id(), rect, uv_full, tint);

            // Custom top_right_bar_text: overlay on top of bar image
            if !options.top_right_bar_text.is_empty() {
                // Per firmware opinfo.c:643-683:
                // 1. Black rect to cover embedded text at (bar_x+42, 314, 10, 102)
                let cover_x = bar_x + 42.0 * scale_x;
                let cover_y = image_rect.min.y + 314.0 * scale_y + y_offset;
                let cover_rect = Rect::from_min_size(
                    Pos2::new(cover_x, cover_y),
                    egui::vec2(10.0 * scale_x, 102.0 * scale_y),
                );
                let black_tint = Color32::from_rgba_unmultiplied(0, 0, 0, entry_alpha);
                painter.rect_filled(cover_rect, 0.0, black_tint);

                // 2. Render custom text (split at space: bold + regular)
                if self.cached_top_right_bar_text != options.top_right_bar_text {
                    let img = render_top_right_bar_text_rotated(
                        &options.top_right_bar_text,
                        10.0,
                        Color32::WHITE,
                    );
                    self.top_right_bar_text_texture = Some(
                        painter.ctx().load_texture("top_right_bar_text", img, egui::TextureOptions::LINEAR)
                    );
                    self.cached_top_right_bar_text = options.top_right_bar_text.clone();
                }
                if let Some(ref text_tex) = self.top_right_bar_text_texture {
                    let text_w = text_tex.size()[0] as f32;
                    let text_h = text_tex.size()[1] as f32;
                    // Constrain to the covered area
                    let display_w = text_w.min(10.0);
                    let display_h = text_h.min(102.0);
                    let text_rect = Rect::from_min_size(
                        Pos2::new(cover_x, cover_y),
                        egui::vec2(display_w * scale_x, display_h * scale_y),
                    );
                    painter.image(text_tex.id(), text_rect, uv_full, tint);
                }
            }
        }

        // 4. btm_left_bar (0, 640-height) - bottom-aligned
        if let Some(ref tex) = self.btm_left_bar_texture {
            let tex_w = tex.size()[0] as f32;
            let tex_h = tex.size()[1] as f32;
            let rect = Rect::from_min_size(
                Pos2::new(
                    image_rect.min.x,
                    image_rect.min.y + (fw_height - tex_h) * scale_y + y_offset,
                ),
                egui::vec2(tex_w * scale_x, tex_h * scale_y),
            );
            painter.image(tex.id(), rect, uv_full, tint);
        }
    }

    /// Render image overlay (for OverlayType::Image)
    fn render_image_overlay(&self, painter: &egui::Painter, image_rect: Rect) {
        // Get image overlay options
        let options = match self.get_image_overlay_options() {
            Some(opts) => opts,
            None => return,
        };

        // Calculate current time in microseconds since Loop state started
        let fps = self.firmware_config.fps();
        let current_time_us = (self.state.animation.frame_counter as i64 * 1_000_000) / fps as i64;

        // Check if we're within the display window
        // appear_time: when overlay starts showing (relative to Loop state start)
        // duration: how long to show the overlay (0 means show indefinitely)
        let should_show = if options.duration > 0 {
            current_time_us >= options.appear_time && current_time_us < options.appear_time + options.duration
        } else {
            // If duration is 0 or negative, show indefinitely after appear_time
            current_time_us >= options.appear_time
        };

        if !should_show {
            return;
        }

        // Draw the image overlay - use original size, don't stretch
        if let Some(ref texture) = self.image_overlay_texture {
            // Get texture original size
            let tex_size = texture.size();
            let img_width = tex_size[0] as f32;
            let img_height = tex_size[1] as f32;

            // Calculate scale factor (based on hardware resolution 360x640)
            let scale_x = image_rect.width() / 360.0;
            let scale_y = image_rect.height() / 640.0;

            // Use uniform scale factor to maintain aspect ratio (consistent with C reference)
            let uniform_scale = scale_x.min(scale_y);

            // Calculate display size (original size × uniform scale)
            let display_width = img_width * uniform_scale;
            let display_height = img_height * uniform_scale;

            // Position: start from top-left corner (0, 0) of image_rect
            let overlay_rect = Rect::from_min_size(
                image_rect.min, // top-left corner (0, 0)
                egui::vec2(display_width, display_height),
            );

            let uv = Rect::from_min_max(Pos2::ZERO, Pos2::new(1.0, 1.0));
            painter.image(texture.id(), overlay_rect, uv, Color32::WHITE);
        }
    }

    /// Render typewriter effect texts
    fn render_typewriter_texts(
        &self,
        painter: &egui::Painter,
        image_rect: Rect,
        scale_x: f32,
        scale_y: f32,
        y_offset: f32,
        options: &ArknightsOverlayOptions,
        theme_color: Color32,
    ) {
        let anim = &self.state.animation;
        let offsets = &self.firmware_config.layout.offsets;
        let btm_info_x = offsets.btm_info_x as f32 * scale_x + image_rect.min.x;

        // Operator name (large white text)
        if anim.name_chars > 0 {
            let name: String = options.operator_name.chars().take(anim.name_chars).collect();
            let y = offsets.opname_y as f32 * scale_y + image_rect.min.y + y_offset;

            if y >= image_rect.min.y && y <= image_rect.max.y {
                let pos = Pos2::new(btm_info_x, y);
                painter.text(
                    pos,
                    Align2::LEFT_TOP,
                    &name,
                    FontId::proportional(32.0 * scale_y),
                    Color32::WHITE,
                );
            }
        }

        // Operator code (theme color, smaller text)
        if anim.code_chars > 0 {
            let code: String = options.operator_code.chars().take(anim.code_chars).collect();
            let y = offsets.opcode_y as f32 * scale_y + image_rect.min.y + y_offset;

            if y >= image_rect.min.y && y <= image_rect.max.y {
                let pos = Pos2::new(btm_info_x, y);
                painter.text(
                    pos,
                    Align2::LEFT_TOP,
                    &code,
                    FontId::proportional(14.0 * scale_y),
                    theme_color,
                );
            }
        }

        // Staff text
        if anim.staff_chars > 0 {
            let staff: String = options.staff_text.chars().take(anim.staff_chars).collect();
            let y = offsets.staff_text_y as f32 * scale_y + image_rect.min.y + y_offset;

            if y >= image_rect.min.y && y <= image_rect.max.y {
                let pos = Pos2::new(btm_info_x, y);
                painter.text(
                    pos,
                    Align2::LEFT_TOP,
                    &staff,
                    FontId::proportional(12.0 * scale_y),
                    Color32::WHITE,
                );
            }
        }

        // Auxiliary text (multiline)
        if anim.aux_chars > 0 {
            let aux: String = options.aux_text.chars().take(anim.aux_chars).collect();
            let base_y = offsets.aux_text_y as f32 * scale_y + image_rect.min.y + y_offset;
            let line_height = offsets.aux_text_line_height as f32 * scale_y;

            for (i, line) in aux.lines().enumerate() {
                let y = base_y + (i as f32 * line_height);

                if y >= image_rect.min.y && y <= image_rect.max.y {
                    let pos = Pos2::new(btm_info_x, y);
                    painter.text(
                        pos,
                        Align2::LEFT_TOP,
                        line,
                        FontId::proportional(10.0 * scale_y),
                        Color32::GRAY,
                    );
                }
            }
        }
    }

    /// Render EINK effect areas (barcode, class icon)
    fn render_eink_areas(
        &self,
        painter: &egui::Painter,
        image_rect: Rect,
        scale_x: f32,
        scale_y: f32,
        y_offset: f32,
    ) {
        let anim = &self.state.animation;
        let barcode_layout = &self.firmware_config.layout.barcode;
        let class_icon_size = &self.firmware_config.layout.class_icon;
        let offsets = &self.firmware_config.layout.offsets;

        // Barcode area
        let barcode_x = barcode_layout.x as f32 * scale_x + image_rect.min.x;
        let barcode_y = barcode_layout.y as f32 * scale_y + image_rect.min.y + y_offset;
        let barcode_w = barcode_layout.width as f32 * scale_x;
        let barcode_h = barcode_layout.height as f32 * scale_y;

        if barcode_y + barcode_h >= image_rect.min.y && barcode_y <= image_rect.max.y {
            let barcode_rect = Rect::from_min_size(
                Pos2::new(barcode_x, barcode_y),
                egui::vec2(barcode_w, barcode_h),
            );

            match anim.barcode_state {
                EinkState::FirstBlack | EinkState::SecondBlack => {
                    painter.rect_filled(barcode_rect, 0.0, Color32::BLACK);
                }
                EinkState::FirstWhite | EinkState::SecondWhite => {
                    painter.rect_filled(barcode_rect, 0.0, Color32::WHITE);
                }
                EinkState::Content => {
                    // Draw real barcode texture if available
                    if let Some(ref texture) = self.barcode_texture {
                        let uv = Rect::from_min_max(Pos2::new(0.0, 0.0), Pos2::new(1.0, 1.0));
                        painter.image(texture.id(), barcode_rect, uv, Color32::WHITE);
                    } else {
                        // Fallback to simplified barcode pattern
                        self.render_barcode_pattern(painter, barcode_rect);
                    }
                }
                EinkState::Idle => {}
            }
        }

        // Class icon area
        let btm_info_x = offsets.btm_info_x as f32 * scale_x + image_rect.min.x;
        let classicon_x = btm_info_x;
        let classicon_y = offsets.class_icon_y as f32 * scale_y + image_rect.min.y + y_offset;
        let classicon_w = class_icon_size.width as f32 * scale_x;
        let classicon_h = class_icon_size.height as f32 * scale_y;

        if classicon_y + classicon_h >= image_rect.min.y && classicon_y <= image_rect.max.y {
            let classicon_rect = Rect::from_min_size(
                Pos2::new(classicon_x, classicon_y),
                egui::vec2(classicon_w, classicon_h),
            );

            match anim.classicon_state {
                EinkState::FirstBlack | EinkState::SecondBlack => {
                    painter.rect_filled(classicon_rect, 0.0, Color32::BLACK);
                }
                EinkState::FirstWhite | EinkState::SecondWhite => {
                    painter.rect_filled(classicon_rect, 0.0, Color32::WHITE);
                }
                EinkState::Content => {
                    // Draw real class icon texture if available
                    if let Some(ref texture) = self.class_icon_texture {
                        let uv = Rect::from_min_max(Pos2::new(0.0, 0.0), Pos2::new(1.0, 1.0));
                        painter.image(texture.id(), classicon_rect, uv, Color32::WHITE);
                    } else {
                        // Fallback to placeholder (X shape)
                        painter.rect_stroke(classicon_rect, 0.0, Stroke::new(1.0, Color32::WHITE));
                        let center = classicon_rect.center();
                        let half = classicon_w.min(classicon_h) * 0.3;
                        painter.line_segment(
                            [Pos2::new(center.x - half, center.y - half), Pos2::new(center.x + half, center.y + half)],
                            Stroke::new(2.0, Color32::WHITE),
                        );
                        painter.line_segment(
                            [Pos2::new(center.x + half, center.y - half), Pos2::new(center.x - half, center.y + half)],
                            Stroke::new(2.0, Color32::WHITE),
                        );
                    }
                }
                EinkState::Idle => {}
            }
        }
    }

    /// Render simplified barcode pattern
    fn render_barcode_pattern(&self, painter: &egui::Painter, rect: Rect) {
        // Draw a simplified barcode pattern (vertical stripes)
        let stripe_count = 20;
        let stripe_width = rect.width() / stripe_count as f32;

        for i in 0..stripe_count {
            // Alternate black and white stripes with some variation
            if (i % 3 != 0) && (i % 5 != 2) {
                let x = rect.min.x + i as f32 * stripe_width;
                let stripe_rect = Rect::from_min_size(
                    Pos2::new(x, rect.min.y),
                    egui::vec2(stripe_width * 0.7, rect.height()),
                );
                painter.rect_filled(stripe_rect, 0.0, Color32::WHITE);
            }
        }
    }

    /// Render divider lines (upper and lower)
    /// Note: C reference uses white (0xFFFFFFFF) for divider lines, not theme color
    fn render_divider_lines(
        &self,
        painter: &egui::Painter,
        image_rect: Rect,
        scale_x: f32,
        scale_y: f32,
        y_offset: f32,
        btm_info_x: f32,
        _theme_color: Color32, // Unused - kept for API compatibility
    ) {
        let anim = &self.state.animation;
        let offsets = &self.firmware_config.layout.offsets;

        // Upper divider line (white per C reference: fbdraw_fill_rect(&fbdst, &dst_rect, 0xFFFFFFFF))
        if anim.upper_line_width > 0 {
            let y = offsets.upperline_y as f32 * scale_y + image_rect.min.y + y_offset;
            let width = anim.upper_line_width as f32 * scale_x;

            if y >= image_rect.min.y && y <= image_rect.max.y {
                painter.line_segment(
                    [Pos2::new(btm_info_x, y), Pos2::new(btm_info_x + width, y)],
                    Stroke::new(1.0, Color32::WHITE),
                );
            }
        }

        // Lower divider line (white per C reference)
        if anim.lower_line_width > 0 {
            let y = offsets.lowerline_y as f32 * scale_y + image_rect.min.y + y_offset;
            let width = anim.lower_line_width as f32 * scale_x;

            if y >= image_rect.min.y && y <= image_rect.max.y {
                painter.line_segment(
                    [Pos2::new(btm_info_x, y), Pos2::new(btm_info_x + width, y)],
                    Stroke::new(1.0, Color32::WHITE),
                );
            }
        }
    }

    /// Render progress bar (AK bar)
    fn render_progress_bar(
        &self,
        painter: &egui::Painter,
        image_rect: Rect,
        scale_x: f32,
        scale_y: f32,
        y_offset: f32,
        btm_info_x: f32,
        theme_color: Color32,
    ) {
        let anim = &self.state.animation;
        let offsets = &self.firmware_config.layout.offsets;

        if anim.ak_bar_width == 0 {
            return;
        }

        // Use uniform scale factor to preserve aspect ratio (avoid stretching)
        let uniform_scale = scale_x.min(scale_y);

        let y = offsets.ak_bar_y as f32 * scale_y + image_rect.min.y + y_offset;
        let width = anim.ak_bar_width as f32 * uniform_scale;

        if y < image_rect.min.y || y > image_rect.max.y {
            return;
        }

        // Use AK bar image texture if available
        if let Some(ref ak_bar_texture) = self.ak_bar_texture {
            // Get actual texture dimensions
            let tex_width = ak_bar_texture.size()[0] as f32;
            let tex_height = ak_bar_texture.size()[1] as f32;

            // Calculate reveal ratio for sweep-in animation
            let max_bar_width = 280.0;
            let reveal_ratio = (anim.ak_bar_width as f32 / max_bar_width).min(1.0);

            // Use original texture height, only scale for display
            let displayed_width = tex_width * reveal_ratio * uniform_scale;
            let displayed_height = tex_height * uniform_scale;

            let bar_rect = Rect::from_min_size(
                Pos2::new(btm_info_x, y),
                egui::vec2(displayed_width, displayed_height),
            );

            let uv = Rect::from_min_max(
                Pos2::new(0.0, 0.0),
                Pos2::new(reveal_ratio, 1.0),
            );

            painter.image(ak_bar_texture.id(), bar_rect, uv, Color32::WHITE);
        } else {
            // Fallback: solid color rectangle
            let bar_height = 3.0 * scale_y;
            if y + bar_height <= image_rect.max.y {
                let bar_rect = Rect::from_min_size(
                    Pos2::new(btm_info_x, y),
                    egui::vec2(width, bar_height),
                );
                painter.rect_filled(bar_rect, 0.0, theme_color);
            }
        }
    }

    /// Render arrow animation indicator (3 chevrons pointing UP on the right side)
    /// Uses dark gray color to match C reference design
    /// Per C reference (opinfo.c:553): arrows scroll upward via Y decrement
    fn render_arrow_indicator(
        &self,
        painter: &egui::Painter,
        image_rect: Rect,
        scale_x: f32,
        scale_y: f32,
        y_offset: f32,
        _theme_color: Color32,
    ) {
        let anim = &self.state.animation;

        // Only show arrows when entry animation is complete
        if !anim.is_entry_complete() {
            return;
        }

        // Use image texture if available
        if let Some(ref arrow_texture) = self.top_right_arrow_texture {
            // Arrow image dimensions: 24x100, positioned at Y=100 per opinfo.c reference
            let arrow_width = 24.0 * scale_x;
            let arrow_height = 100.0 * scale_y;
            let arrow_x = image_rect.max.x - arrow_width;  // Right-aligned
            let arrow_y = image_rect.min.y + 100.0 * scale_y + y_offset;  // Y=100

            // UV scrolling to implement upward loop animation
            // anim.arrow_y cycles 0-99, use it as scroll offset
            let scroll_offset = (anim.arrow_y as f32 / 100.0).fract();
            let uv = Rect::from_min_max(
                Pos2::new(0.0, scroll_offset),
                Pos2::new(1.0, scroll_offset + 1.0),
            );

            let arrow_rect = Rect::from_min_size(
                Pos2::new(arrow_x, arrow_y),
                egui::vec2(arrow_width, arrow_height),
            );

            painter.image(arrow_texture.id(), arrow_rect, uv, Color32::WHITE);
        } else {
            // Fallback: draw programmatic dark gray chevrons
            let offsets = &self.firmware_config.layout.offsets;
            let base_y = offsets.arrow_y as f32 * scale_y + image_rect.min.y + y_offset;
            let arrow_offset = anim.arrow_y as f32 * scale_y;

            // Position on the right side of the screen
            let x = image_rect.max.x - 40.0 * scale_x;

            // Draw 3 chevrons pointing UPWARD (^ shape)
            let chevron_spacing = 12.0 * scale_y;
            let chevron_size = 8.0 * scale_x;

            // Use dark gray color for chevrons (matching C reference opinfo.c)
            let chevron_color = Color32::from_rgb(40, 40, 40);
            let stroke = Stroke::new(2.0 * scale_x.min(scale_y), chevron_color);

            for i in 0..3 {
                let y = base_y + arrow_offset + (i as f32 * chevron_spacing);

                if y >= image_rect.min.y && y <= image_rect.max.y {
                    // Draw chevron (^ shape pointing UP)
                    let left = Pos2::new(x - chevron_size, y + chevron_size);
                    let top = Pos2::new(x, y);
                    let right = Pos2::new(x + chevron_size, y + chevron_size);

                    painter.line_segment([left, top], stroke);
                    painter.line_segment([top, right], stroke);
                }
            }
        }
    }

    // ============================================
    // Legacy static decoration rendering functions
    // These functions are no longer used since we now use modular assets
    // Kept for reference only
    // ============================================

    /// Render top-left black L-shape decoration
    #[allow(dead_code)]
    fn render_top_left_corner(
        &self,
        painter: &egui::Painter,
        image_rect: Rect,
        scale_x: f32,
        scale_y: f32,
        alpha: u8,
    ) {
        let black = Color32::from_rgba_unmultiplied(0, 0, 0, alpha);

        // Horizontal bar: 95x25 pixels (original template precise value)
        let h_rect = Rect::from_min_size(
            image_rect.min,
            egui::vec2(95.0 * scale_x, 25.0 * scale_y),
        );
        painter.rect_filled(h_rect, 0.0, black);

        // Vertical bar: 25x105 pixels (original template precise value)
        let v_rect = Rect::from_min_size(
            image_rect.min,
            egui::vec2(25.0 * scale_x, 105.0 * scale_y),
        );
        painter.rect_filled(v_rect, 0.0, black);

        // White triangle cutout (at inner corner of L-shape)
        let white = Color32::from_rgba_unmultiplied(255, 255, 255, alpha);
        let triangle_size = 15.0;
        let tri_x = image_rect.min.x + 25.0 * scale_x;
        let tri_y = image_rect.min.y + 25.0 * scale_y;

        // Triangle points: right-angle triangle pointing to bottom-right
        let points = vec![
            Pos2::new(tri_x, tri_y),
            Pos2::new(tri_x + triangle_size * scale_x, tri_y),
            Pos2::new(tri_x, tri_y + triangle_size * scale_y),
        ];
        painter.add(egui::Shape::convex_polygon(points, white, Stroke::NONE));
    }

    /// Render top-right black background with gold stripes and dark chevron arrows
    #[allow(dead_code)]
    fn render_top_right_gradient(
        &self,
        painter: &egui::Painter,
        image_rect: Rect,
        scale_x: f32,
        scale_y: f32,
        alpha: u8,
    ) {
        // 1. Black background rectangle (X=280-360, Y=0-145)
        let bg_rect = Rect::from_min_max(
            Pos2::new(image_rect.min.x + 280.0 * scale_x, image_rect.min.y),
            Pos2::new(image_rect.max.x, image_rect.min.y + 145.0 * scale_y),
        );
        let black = Color32::from_rgba_unmultiplied(0, 0, 0, alpha);
        painter.rect_filled(bg_rect, 0.0, black);

        // 2. Gold yellow stripes (uniform color #FFD700, starting from right edge)
        let gold = Color32::from_rgba_unmultiplied(255, 215, 0, alpha);

        // Define stripes (Y offset, height, width) - stripes get shorter from top to bottom
        let stripes: [(f32, f32, f32); 12] = [
            (0.0, 6.0, 76.0),   // Top stripe - longest
            (8.0, 8.0, 72.0),
            (18.0, 10.0, 68.0),
            (30.0, 8.0, 64.0),
            (40.0, 12.0, 60.0),
            (54.0, 10.0, 56.0),
            (66.0, 8.0, 52.0),
            (76.0, 10.0, 48.0),
            (88.0, 8.0, 44.0),
            (98.0, 6.0, 40.0),
            (106.0, 6.0, 36.0),
            (114.0, 4.0, 32.0), // Bottom stripe - shortest
        ];

        for (y_off, height, stripe_width) in stripes.iter() {
            let y = image_rect.min.y + y_off * scale_y;
            let x = image_rect.max.x - stripe_width * scale_x;

            let rect = Rect::from_min_size(
                Pos2::new(x, y),
                egui::vec2(*stripe_width * scale_x, *height * scale_y),
            );
            painter.rect_filled(rect, 0.0, gold);
        }

        // 3. Dark/black chevron arrows (outline style)
        let arrow_x = image_rect.min.x + 320.0 * scale_x;
        let dark = Color32::from_rgba_unmultiplied(40, 40, 40, alpha); // Dark gray/black
        let stroke = Stroke::new(2.5 * scale_x.min(scale_y), dark);
        let chevron_size = 10.0;

        for i in 0..3 {
            let arrow_y = image_rect.min.y + (58.0 + i as f32 * 22.0) * scale_y;
            // Upward chevron (^)
            let left = Pos2::new(
                arrow_x - chevron_size * scale_x,
                arrow_y + chevron_size * scale_y,
            );
            let top = Pos2::new(arrow_x, arrow_y);
            let right = Pos2::new(
                arrow_x + chevron_size * scale_x,
                arrow_y + chevron_size * scale_y,
            );

            painter.line_segment([left, top], stroke);
            painter.line_segment([top, right], stroke);
        }
    }

    /// Render right side black vertical bar with "RHODES ISLAND INC." text
    /// RHODES is yellow (#FFD700), ISLAND INC. is white
    #[allow(dead_code)]
    fn render_right_side_bar(
        &self,
        painter: &egui::Painter,
        image_rect: Rect,
        scale_x: f32,
        scale_y: f32,
        y_offset: f32,
        alpha: u8,
    ) {
        // Black vertical bar: width 30px, from Y=145 to Y=600 (original template precise values)
        let bar_width = 30.0 * scale_x;
        let bar_x = image_rect.max.x - bar_width;
        let bar_start_y = image_rect.min.y + 145.0 * scale_y + y_offset;
        let bar_end_y = image_rect.min.y + 600.0 * scale_y + y_offset;

        // Clamp to image bounds
        let clamped_start = bar_start_y.max(image_rect.min.y);
        let clamped_end = bar_end_y.min(image_rect.max.y);

        if clamped_end > clamped_start {
            let bar_rect = Rect::from_min_max(
                Pos2::new(bar_x, clamped_start),
                Pos2::new(image_rect.max.x, clamped_end),
            );
            let bar_color = Color32::from_rgba_unmultiplied(0, 0, 0, alpha);
            painter.rect_filled(bar_rect, 0.0, bar_color);

            // Text colors
            let yellow = Color32::from_rgba_unmultiplied(255, 215, 0, alpha); // #FFD700 for RHODES
            let white = Color32::from_rgba_unmultiplied(255, 255, 255, alpha);
            let text_x = bar_x + bar_width / 2.0;
            let text_start_y = clamped_start + 30.0 * scale_y;

            // RHODES (yellow, bold - simulated with slightly larger font)
            let rhodes = "RHODES";
            for (i, ch) in rhodes.chars().enumerate() {
                let char_y = text_start_y + i as f32 * 18.0 * scale_y;
                if char_y < image_rect.max.y {
                    painter.text(
                        Pos2::new(text_x, char_y),
                        Align2::CENTER_TOP,
                        ch.to_string(),
                        FontId::proportional(14.0 * scale_y), // Larger for bold effect
                        yellow, // RHODES is yellow
                    );
                }
            }

            // ISLAND INC. (white, normal)
            let island_inc = " ISLAND INC.";
            let island_start_y = text_start_y + rhodes.len() as f32 * 18.0 * scale_y;
            for (i, ch) in island_inc.chars().enumerate() {
                let char_y = island_start_y + i as f32 * 14.0 * scale_y;
                if char_y < image_rect.max.y {
                    painter.text(
                        Pos2::new(text_x, char_y),
                        Align2::CENTER_TOP,
                        ch.to_string(),
                        FontId::proportional(10.0 * scale_y),
                        white, // ISLAND INC. is white
                    );
                }
            }
        }
    }

    /// Render left colorful gradient stripe (yellow → orange → purple → blue → cyan)
    #[allow(dead_code)]
    fn render_left_gradient_stripe(
        &self,
        painter: &egui::Painter,
        image_rect: Rect,
        scale_x: f32,
        scale_y: f32,
        y_offset: f32,
        alpha: u8,
    ) {
        // Position X=58, width 7px (original template precise values)
        let stripe_x = image_rect.min.x + 58.0 * scale_x;
        let stripe_width = 7.0 * scale_x;
        let stripe_start_y = image_rect.min.y + 110.0 * scale_y + y_offset;
        let stripe_end_y = image_rect.max.y;

        // More refined gradient: yellow → orange → purple → blue → cyan
        let segment_count = 30;
        let total_height = stripe_end_y - stripe_start_y;
        let segment_height = total_height / segment_count as f32;

        for i in 0..segment_count {
            let y = stripe_start_y + i as f32 * segment_height;
            if y < image_rect.min.y || y > image_rect.max.y {
                continue;
            }

            let t = i as f32 / segment_count as f32;
            let (r, g, b) = if t < 0.15 {
                // Yellow (255, 220, 50)
                (255, 220, 50)
            } else if t < 0.30 {
                // Yellow → orange
                let t2 = (t - 0.15) / 0.15;
                (255, (220.0 - t2 * 80.0) as u8, (50.0 + t2 * 30.0) as u8)
            } else if t < 0.50 {
                // Orange → purple
                let t2 = (t - 0.30) / 0.20;
                (
                    (255.0 - t2 * 100.0) as u8,
                    (140.0 - t2 * 40.0) as u8,
                    (80.0 + t2 * 120.0) as u8,
                )
            } else if t < 0.75 {
                // Purple → blue
                let t2 = (t - 0.50) / 0.25;
                (
                    (155.0 - t2 * 80.0) as u8,
                    (100.0 + t2 * 80.0) as u8,
                    (200.0 + t2 * 40.0) as u8,
                )
            } else {
                // Blue → cyan
                let t2 = (t - 0.75) / 0.25;
                (
                    (75.0 + t2 * 25.0) as u8,
                    (180.0 + t2 * 40.0) as u8,
                    (240.0 - t2 * 20.0) as u8,
                )
            };

            let color = Color32::from_rgba_unmultiplied(r, g, b, alpha);
            let rect = Rect::from_min_size(
                Pos2::new(stripe_x, y),
                egui::vec2(stripe_width, segment_height + 1.0), // +1 to avoid gaps
            );
            painter.rect_filled(rect, 0.0, color);
        }
    }

    /// Render bottom-left light cyan-blue gradient
    #[allow(dead_code)]
    fn render_bottom_left_gradient(
        &self,
        painter: &egui::Painter,
        image_rect: Rect,
        scale_x: f32,
        scale_y: f32,
        y_offset: f32,
        alpha: u8,
    ) {
        // Larger, softer gradient starting from left edge and bottom
        let center_x = image_rect.min.x; // Start from left edge
        let center_y = image_rect.max.y + y_offset; // Start from bottom edge
        let max_radius = 280.0 * scale_x.min(scale_y);

        // Use more layers for softer gradient effect
        let layer_count = 20;
        for i in (0..layer_count).rev() {
            let t = i as f32 / layer_count as f32;
            let radius = max_radius * (1.0 - t * 0.3);
            // Lower opacity for softer effect
            let layer_alpha = ((alpha as f32) * 0.08 * (1.0 - t * 0.5)) as u8;
            let color = Color32::from_rgba_unmultiplied(180, 230, 240, layer_alpha);

            painter.circle_filled(Pos2::new(center_x, center_y), radius, color);
        }
    }

    /// Render bottom-right logo background with diagonal cut
    #[allow(dead_code)]
    fn render_logo_background(
        &self,
        painter: &egui::Painter,
        image_rect: Rect,
        scale_x: f32,
        scale_y: f32,
        y_offset: f32,
        alpha: u8,
    ) {
        // Size: 200x40, with diagonal cut (original template precise values)
        let bg_width = 200.0 * scale_x;
        let bg_height = 40.0 * scale_y;
        let bg_x = image_rect.max.x - bg_width;
        let bg_y = image_rect.max.y - bg_height + y_offset;
        let cut_size = 20.0 * scale_x; // Top-left diagonal cut size

        if bg_y >= image_rect.min.y && bg_y + bg_height <= image_rect.max.y {
            let black = Color32::from_rgba_unmultiplied(0, 0, 0, alpha);

            // Draw polygon with diagonal cut at top-left corner
            let points = vec![
                Pos2::new(bg_x + cut_size, bg_y),           // Top-left (after cut)
                Pos2::new(image_rect.max.x, bg_y),          // Top-right
                Pos2::new(image_rect.max.x, bg_y + bg_height), // Bottom-right
                Pos2::new(bg_x, bg_y + bg_height),          // Bottom-left
                Pos2::new(bg_x, bg_y + cut_size),           // Cut point on left edge
            ];
            painter.add(egui::Shape::convex_polygon(points, black, Stroke::NONE));

            // "Rhodes Island" text
            let white = Color32::from_rgba_unmultiplied(255, 255, 255, alpha);
            let text_y = bg_y + 8.0 * scale_y;
            painter.text(
                Pos2::new(bg_x + 30.0 * scale_x, text_y),
                Align2::LEFT_TOP,
                "Rhodes Island",
                FontId::proportional(10.0 * scale_y),
                white,
            );

            // Note: "明日方舟" requires Chinese font support, logo_image handles this separately
        }
    }

    /// Render logo image in the bottom-right corner
    fn render_logo_image(
        &self,
        painter: &egui::Painter,
        image_rect: Rect,
        scale_x: f32,
        scale_y: f32,
        y_offset: f32,
    ) {
        let anim = &self.state.animation;

        // Only show when logo alpha > 0
        if anim.logo_alpha == 0 {
            return;
        }

        // Check if we have a logo texture
        if let Some(ref texture) = self.logo_texture {
            // Logo position (bottom-right corner)
            let logo_width = 80.0 * scale_x;
            let logo_height = 30.0 * scale_y;
            let logo_x = image_rect.max.x - logo_width - 10.0 * scale_x;
            let logo_y = image_rect.max.y - logo_height - 10.0 * scale_y + y_offset;

            if logo_y >= image_rect.min.y && logo_y + logo_height <= image_rect.max.y {
                let logo_rect = Rect::from_min_size(
                    Pos2::new(logo_x, logo_y),
                    egui::vec2(logo_width, logo_height),
                );

                let uv = Rect::from_min_max(Pos2::new(0.0, 0.0), Pos2::new(1.0, 1.0));
                // Apply logo alpha
                let tint = Color32::from_rgba_unmultiplied(255, 255, 255, anim.logo_alpha);
                painter.image(texture.id(), logo_rect, uv, tint);
            }
        }
    }

    // NOTE: render_left_rhodes_island() removed - C reference uses image resource at (0,0), not text rendering
    // NOTE: render_bottom_right_logo_text() removed - C reference does not have this element
    // NOTE: render_staff_section() removed - C reference renders staff_text via typewriter effect at X=70, Y=480
    //       (already handled in render_typewriter_texts), not as centered "STAFF" with line and subtitle
}

impl eframe::App for SimulatorApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        // Handle IPC messages
        self.handle_ipc_messages();

        // Load textures for current configuration (lazy loading)
        self.load_textures(ctx);

        // Timing control for 50fps
        let now = Instant::now();
        let elapsed = now.duration_since(self.last_frame_time);

        if elapsed >= FRAME_INTERVAL && self.state.is_playing {
            self.update_simulation();
            self.last_frame_time = now;
        }

        // Render current frame
        self.render_frame(ctx);

        // Main panel
        egui::CentralPanel::default().show(ctx, |ui| {
            // Title
            ui.heading(RichText::new(format!(
                "Pass Simulator ({}x{} @ {}fps)",
                self.firmware_config.overlay_width(),
                self.firmware_config.overlay_height(),
                self.firmware_config.fps()
            )).color(Color32::LIGHT_GRAY));

            ui.separator();

            // Display area
            let image_response = ui.vertical_centered(|ui| {
                if let Some(ref texture) = self.frame_texture {
                    let response = ui.image(egui::ImageSource::Texture(egui::load::SizedTexture::new(
                        texture.id(),
                        Vec2::new(
                            self.firmware_config.overlay_width() as f32,
                            self.firmware_config.overlay_height() as f32,
                        ),
                    )));
                    Some(response.rect)
                } else {
                    None
                }
            });

            // Render overlay UI on top of the image when in Loop state
            if self.state.play_state == PlayState::Loop {
                let overlay_type = self.epconfig
                    .as_ref()
                    .and_then(|c| c.overlay.as_ref())
                    .map(|o| o.overlay_type)
                    .unwrap_or(OverlayType::None);
                if let Some(image_rect) = image_response.inner {
                    let painter = ui.painter_at(image_rect);
                    match overlay_type {
                        OverlayType::Arknights => self.render_overlay_ui(&painter, image_rect),
                        OverlayType::Image => self.render_image_overlay(&painter, image_rect),
                        OverlayType::None => {}
                    }
                }
            }

            ui.separator();

            // Transition selectors
            ui.horizontal(|ui| {
                ui.label("Transition In:");
                egui::ComboBox::from_id_salt("trans_in")
                    .selected_text(match self.selected_transition_in {
                        0 => "fade",
                        1 => "move",
                        2 => "swipe",
                        _ => "none",
                    })
                    .show_ui(ui, |ui| {
                        ui.selectable_value(&mut self.selected_transition_in, 0, "fade");
                        ui.selectable_value(&mut self.selected_transition_in, 1, "move");
                        ui.selectable_value(&mut self.selected_transition_in, 2, "swipe");
                        ui.selectable_value(&mut self.selected_transition_in, 3, "none");
                    });

                ui.label("Transition Loop:");
                egui::ComboBox::from_id_salt("trans_loop")
                    .selected_text(match self.selected_transition_loop {
                        0 => "fade",
                        1 => "move",
                        2 => "swipe",
                        _ => "none",
                    })
                    .show_ui(ui, |ui| {
                        ui.selectable_value(&mut self.selected_transition_loop, 0, "fade");
                        ui.selectable_value(&mut self.selected_transition_loop, 1, "move");
                        ui.selectable_value(&mut self.selected_transition_loop, 2, "swipe");
                        ui.selectable_value(&mut self.selected_transition_loop, 3, "none");
                    });
            });

            ui.separator();

            // Control buttons
            ui.horizontal(|ui| {
                if self.state.is_playing {
                    if ui.button("Pause").clicked() {
                        self.state.pause();
                    }
                } else {
                    if ui.button("Play").clicked() {
                        if self.state.play_state == PlayState::Idle {
                            self.start_playback();
                        } else {
                            self.state.resume();
                        }
                    }
                }

                if ui.button("Reset").clicked() {
                    self.reset_playback();
                }

                // Video status indicator
                let video_status = if self.video_player.has_loop() {
                    "Video: OK"
                } else {
                    "Video: None"
                };
                ui.label(RichText::new(video_status).color(
                    if self.video_player.has_loop() { Color32::GREEN } else { Color32::GRAY }
                ).small());
            });

            // Status display
            ui.separator();
            ui.label(RichText::new(format!(
                "State: {} | Frame: {} | Animation Frame: {}",
                self.state.play_state.display_name(),
                self.state.frame_counter,
                self.state.animation.frame_counter
            )).color(Color32::GRAY).small());

            // Animation state details (debug)
            if self.state.play_state == PlayState::Loop {
                ui.label(RichText::new(format!(
                    "Name: {} | Code: {} | Color: {} | Entry: {:.1}%",
                    self.state.animation.name_chars,
                    self.state.animation.code_chars,
                    self.state.animation.color_fade_radius,
                    self.state.animation.entry_progress * 100.0
                )).color(Color32::DARK_GRAY).small());
            }
        });

        // Request repaint if playing
        if self.state.is_playing {
            ctx.request_repaint();
        }
    }
}

/// Convert microseconds to frame count
fn microseconds_to_frames(us: i64, fps: u32) -> u32 {
    ((us * fps as i64) / 1_000_000).max(1) as u32
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_microseconds_to_frames() {
        // 1 second at 50fps = 50 frames
        assert_eq!(microseconds_to_frames(1_000_000, 50), 50);
        // 0.5 seconds at 50fps = 25 frames
        assert_eq!(microseconds_to_frames(500_000, 50), 25);
        // Very small value should return at least 1
        assert_eq!(microseconds_to_frames(1, 50), 1);
    }
}
