//! Arknights Electronic Pass Simulator
//!
//! A real device preview emulator for the Arknights Pass Material Editor.
//! Supports standalone execution or IPC communication with the Python editor.

mod app;
mod config;
mod render;
mod animation;
mod ipc;
mod utils;
mod video;

use anyhow::Result;
use clap::Parser;
use std::path::PathBuf;
use tracing::{info, Level};
use tracing_subscriber::FmtSubscriber;

use app::SimulatorApp;
use config::EPConfig;

/// Arknights Electronic Pass Simulator
#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Args {
    /// Path to epconfig.json configuration file
    #[arg(short, long)]
    config: Option<PathBuf>,

    /// Base directory for asset files
    #[arg(short, long)]
    base_dir: Option<PathBuf>,

    /// Application directory (for program resources like modular assets)
    #[arg(long)]
    app_dir: Option<PathBuf>,

    /// Named pipe name for IPC communication (Windows)
    #[arg(long)]
    pipe: Option<String>,

    /// Use stdin/stdout for IPC communication
    #[arg(long)]
    stdio: bool,

    /// Cropbox in format "x,y,w,h" (original video coordinates)
    #[arg(long)]
    cropbox: Option<String>,

    /// Video rotation in degrees (0, 90, 180, 270)
    #[arg(long, default_value = "0")]
    rotation: i32,

    /// Enable debug logging
    #[arg(short, long)]
    debug: bool,
}

fn main() -> Result<()> {
    let args = Args::parse();

    // Initialize logging
    let level = if args.debug { Level::DEBUG } else { Level::INFO };
    let subscriber = FmtSubscriber::builder()
        .with_max_level(level)
        .finish();
    tracing::subscriber::set_global_default(subscriber)?;

    info!("Arknights Pass Simulator starting...");

    // Load configuration if provided
    let initial_config = if let Some(config_path) = &args.config {
        info!("Loading config from: {:?}", config_path);
        match EPConfig::load_from_file(config_path) {
            Ok(config) => {
                info!("Config loaded successfully:");
                info!("  - name: {:?}", config.name);
                info!("  - loop.file: {:?}", config.loop_config.file);
                info!("  - intro: {:?}", config.intro.as_ref().map(|i| &i.file));
                Some(config)
            }
            Err(e) => {
                tracing::error!("Failed to load config: {:?}", e);
                None
            }
        }
    } else {
        None
    };

    let base_dir = args.base_dir.unwrap_or_else(|| {
        args.config
            .as_ref()
            .and_then(|p| p.parent())
            .map(|p| p.to_path_buf())
            .unwrap_or_else(|| PathBuf::from("."))
    });
    info!("Base directory: {:?}", base_dir);

    // Determine app_dir for program resources (modular assets, etc.)
    let app_dir = args.app_dir.unwrap_or_else(|| {
        // Default to the directory containing the executable
        std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(|p| p.to_path_buf()))
            .unwrap_or_else(|| PathBuf::from("."))
    });
    info!("App directory: {:?}", app_dir);

    // Create native options for eframe
    let native_options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([400.0, 720.0])
            .with_min_inner_size([400.0, 720.0])
            .with_resizable(false)
            .with_title("Arknights Pass Simulator"),
        ..Default::default()
    };

    // Parse cropbox
    let cropbox: Option<(u32, u32, u32, u32)> = args.cropbox.and_then(|s| {
        let parts: Vec<u32> = s.split(',').filter_map(|p| p.parse().ok()).collect();
        if parts.len() == 4 {
            Some((parts[0], parts[1], parts[2], parts[3]))
        } else {
            None
        }
    });
    let rotation = args.rotation;

    // Run the application
    eframe::run_native(
        "Arknights Pass Simulator",
        native_options,
        Box::new(move |cc| {
            Ok(Box::new(SimulatorApp::new(
                cc,
                initial_config,
                base_dir,
                app_dir,
                args.pipe,
                args.stdio,
                cropbox,
                rotation,
            )))
        }),
    )
    .map_err(|e| anyhow::anyhow!("eframe error: {}", e))?;

    Ok(())
}
