//! Main simulator application
//!
//! Implements the egui App trait for the pass simulator.

use std::path::PathBuf;
use std::time::{Duration, Instant};

use egui::{Color32, RichText, Vec2, Rect, Pos2, Stroke, FontId, Align2};
use image::RgbImage;
use tracing::{info, warn};

use crate::config::{EPConfig, FirmwareConfig, TransitionType, OverlayType, ArknightsOverlayOptions};
use crate::app::state::EinkState;
use crate::render::{TransitionRenderer, OverlayRenderer, ImageLoader, generate_vertical_barcode_gradient};
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
    /// Application directory for program resources (overlay_template.png, etc.)
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

    /// Overlay template texture (static background for all decorations)
    overlay_template_texture: Option<egui::TextureHandle>,

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

        // Create video player
        let mut video_player = VideoPlayer::new(width, height);

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
            overlay_template_texture: None,
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
        self.overlay_template_texture = None;
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
            self.video_player.seek_intro_to_start();
        }
    }

    fn process_intro(&mut self) {
        // Advance to next intro video frame (updates internal cache)
        if !self.video_player.advance_intro_frame() {
            // Intro video ended, start transition to loop
            self.start_transition_loop();
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
            self.video_player.seek_loop_to_start();
        }
    }

    fn process_pre_opinfo(&mut self) {
        self.state.pre_opinfo_counter += 1;

        // Advance loop video frame (updates internal cache, no clone)
        self.video_player.advance_loop_frame();

        // Wait for appear_time
        if self.state.pre_opinfo_counter >= self.state.appear_time_frames {
            self.state.play_state = PlayState::Loop;
            self.animation_controller.reset();
            self.animation_controller.start_entry_animation();
        }
    }

    fn process_loop(&mut self) {
        // Advance loop video frame (updates internal cache, no clone)
        self.video_player.advance_loop_frame();

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

        // Draw state indicator (debug)
        let state_color = match self.state.play_state {
            PlayState::Idle => Color32::DARK_GRAY,
            PlayState::TransitionIn | PlayState::TransitionLoop => Color32::YELLOW,
            PlayState::Intro => Color32::BLUE,
            PlayState::PreOpinfo => Color32::LIGHT_BLUE,
            PlayState::Loop => Color32::GREEN,
        };

        // Draw small indicator in top-left corner
        for y in 0..10 {
            for x in 0..30 {
                if y < height && x < width {
                    image.pixels[y * width + x] = state_color;
                }
            }
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
        let width = image.size[0];
        let height = image.size[1];

        match trans_type {
            TransitionType::Fade => {
                // Calculate fade alpha based on progress
                let alpha = self.transition_renderer.calculate_fade_alpha(progress);
                // Apply black overlay with alpha
                for pixel in image.pixels.iter_mut() {
                    let blend = ((255 - alpha as u16) * 255 / 255) as u8;
                    *pixel = Color32::from_rgb(
                        ((pixel.r() as u16 * blend as u16) / 255) as u8,
                        ((pixel.g() as u16 * blend as u16) / 255) as u8,
                        ((pixel.b() as u16 * blend as u16) / 255) as u8,
                    );
                }
            }
            TransitionType::Move => {
                // Calculate move offset
                let offset = self.transition_renderer.calculate_move_offset(progress);
                // For simplicity, just show a line at the offset position
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
                    // Darken area above swipe line
                    for y in 0..swipe_y.min(height) {
                        for x in 0..width {
                            let idx = y * width + x;
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

    /// Load textures for the current configuration
    fn load_textures(&mut self, ctx: &egui::Context) {
        if self.textures_loaded {
            return;
        }

        // Load overlay template texture (static background with all decorations)
        // Use app_dir (program directory) instead of base_dir (user material directory)
        if self.overlay_template_texture.is_none() {
            let template_path = self.app_dir.join("resources/data/overlay_template.png");
            if let Ok(img) = image::open(&template_path) {
                let rgba = img.to_rgba8();
                let size = [rgba.width() as usize, rgba.height() as usize];
                let pixels: Vec<Color32> = rgba
                    .pixels()
                    .map(|p| Color32::from_rgba_unmultiplied(p[0], p[1], p[2], p[3]))
                    .collect();
                let color_image = egui::ColorImage { size, pixels };
                self.overlay_template_texture = Some(ctx.load_texture(
                    "overlay_template",
                    color_image,
                    egui::TextureOptions::LINEAR,
                ));
                info!("Loaded overlay template: {}", template_path.display());
            } else {
                warn!("Failed to load overlay template: {}", template_path.display());
            }
        }

        let options = match self.get_arknights_options() {
            Some(opts) => opts,
            None => return,
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
    fn render_overlay_ui(&self, painter: &egui::Painter, image_rect: Rect) {
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

        // 1. Draw template as base layer (contains all static decorations:
        //    top-left corner, top-right gradient, right side bar, vertical text,
        //    bottom-left gradient, logo background)
        if let Some(ref template) = self.overlay_template_texture {
            let uv = Rect::from_min_max(Pos2::ZERO, Pos2::new(1.0, 1.0));
            // Apply entry animation alpha for smooth fade-in
            let entry_alpha = (anim.entry_progress * 255.0) as u8;
            let tint = Color32::from_rgba_unmultiplied(255, 255, 255, entry_alpha);
            painter.image(template.id(), image_rect, uv, tint);
        }

        // 2. Render dynamic elements only (on top of the template)

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

        if anim.ak_bar_width > 0 {
            let y = offsets.ak_bar_y as f32 * scale_y + image_rect.min.y + y_offset;
            let width = anim.ak_bar_width as f32 * scale_x;
            let bar_height = 3.0 * scale_y; // 3 pixels thick

            if y >= image_rect.min.y && y + bar_height <= image_rect.max.y {
                let bar_rect = Rect::from_min_size(
                    Pos2::new(btm_info_x, y),
                    egui::vec2(width, bar_height),
                );
                painter.rect_filled(bar_rect, 0.0, theme_color);
            }
        }
    }

    /// Render arrow animation indicator (3 chevrons pointing UP on the right side)
    /// Uses yellow/gold color to match the reference design
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
        let offsets = &self.firmware_config.layout.offsets;

        // Only show arrows when entry animation is complete
        if !anim.is_entry_complete() {
            return;
        }

        let base_y = offsets.arrow_y as f32 * scale_y + image_rect.min.y + y_offset;
        let arrow_offset = anim.arrow_y as f32 * scale_y;

        // Position on the right side of the screen (inside the yellow gradient area)
        let x = image_rect.max.x - 40.0 * scale_x;

        // Draw 3 chevrons pointing UPWARD (^ shape)
        let chevron_spacing = 12.0 * scale_y;
        let chevron_size = 8.0 * scale_x;

        // Use yellow/gold color for chevrons (to match the gradient area)
        let chevron_color = Color32::from_rgb(255, 200, 50);
        let stroke = Stroke::new(2.0 * scale_x.min(scale_y), chevron_color);

        for i in 0..3 {
            let y = base_y + arrow_offset + (i as f32 * chevron_spacing);

            if y >= image_rect.min.y && y <= image_rect.max.y {
                // Draw chevron (^ shape pointing UP)
                // Top vertex points up, left and right vertices are below
                let left = Pos2::new(x - chevron_size, y + chevron_size);
                let top = Pos2::new(x, y);
                let right = Pos2::new(x + chevron_size, y + chevron_size);

                painter.line_segment([left, top], stroke);
                painter.line_segment([top, right], stroke);
            }
        }
    }

    // NOTE: Static decoration functions removed (render_top_left_corner, render_right_side_bar,
    // render_top_right_gradient, render_bottom_left_gradient, render_logo_background, render_vertical_text)
    // These elements are now pre-rendered in overlay_template.png to match C firmware behavior.
    // C firmware uses fbdraw_copy_rect() to copy pre-rendered assets, not programmatic drawing.

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
            let logo_y = image_rect.max.y - logo_height - 40.0 * scale_y + y_offset;

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
                if let Some(ref config) = self.epconfig {
                    if let Some(ref overlay) = config.overlay {
                        if overlay.overlay_type == OverlayType::Arknights {
                            if let Some(image_rect) = image_response.inner {
                                let painter = ui.painter_at(image_rect);
                                self.render_overlay_ui(&painter, image_rect);
                            }
                        }
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
