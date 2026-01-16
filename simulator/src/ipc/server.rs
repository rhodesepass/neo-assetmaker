//! IPC Server module
//!
//! Implements Named Pipe server for Windows and stdin/stdout fallback.

use std::io::{BufRead, BufReader, Write};
use std::sync::mpsc::{Receiver, Sender};
use anyhow::Result;
use tracing::{info, warn, error, debug};

#[cfg(windows)]
use interprocess::TryClone;

use super::protocol::IpcMessage;

/// IPC Server for communication with Python editor
pub struct IpcServer {
    /// Channel to send messages to the main thread
    to_app: Sender<IpcMessage>,
    /// Channel to receive messages from the main thread
    from_app: Receiver<IpcMessage>,
}

impl IpcServer {
    /// Create a new IPC server
    pub fn new(to_app: Sender<IpcMessage>, from_app: Receiver<IpcMessage>) -> Self {
        Self { to_app, from_app }
    }

    /// Run the server using stdin/stdout
    pub fn run_stdio(&mut self) -> Result<()> {
        info!("Starting stdio IPC server");

        let stdin = std::io::stdin();
        let mut stdout = std::io::stdout();
        let reader = BufReader::new(stdin.lock());

        // Send ready message
        let ready_msg = IpcMessage::ready();
        if let Ok(json) = ready_msg.to_json() {
            let _ = writeln!(stdout, "{}", json);
            let _ = stdout.flush();
        }

        // Read messages from stdin
        for line in reader.lines() {
            match line {
                Ok(line) => {
                    if line.trim().is_empty() {
                        continue;
                    }

                    debug!("Received: {}", line);

                    match IpcMessage::from_json(&line) {
                        Ok(msg) => {
                            if matches!(msg, IpcMessage::Shutdown) {
                                info!("Received shutdown command");
                                break;
                            }

                            if self.to_app.send(msg).is_err() {
                                error!("Failed to send message to app");
                                break;
                            }
                        }
                        Err(e) => {
                            warn!("Failed to parse message: {}", e);
                            let error_msg = IpcMessage::error(
                                super::protocol::error_codes::INTERNAL_ERROR,
                                format!("Parse error: {}", e),
                            );
                            if let Ok(json) = error_msg.to_json() {
                                let _ = writeln!(stdout, "{}", json);
                                let _ = stdout.flush();
                            }
                        }
                    }
                }
                Err(e) => {
                    error!("Failed to read from stdin: {}", e);
                    break;
                }
            }

            // Check for outgoing messages
            while let Ok(msg) = self.from_app.try_recv() {
                if let Ok(json) = msg.to_json() {
                    let _ = writeln!(stdout, "{}", json);
                    let _ = stdout.flush();
                }
            }
        }

        info!("Stdio IPC server stopped");
        Ok(())
    }

    /// Run the server using Windows Named Pipe
    #[cfg(windows)]
    pub fn run_named_pipe(&mut self, pipe_name: &str) -> Result<()> {
        use interprocess::local_socket::{
            GenericNamespaced, ListenerOptions, ToNsName,
            traits::Listener,
        };

        info!("Starting Named Pipe IPC server: {}", pipe_name);

        // Create the named pipe listener
        let name = pipe_name.to_ns_name::<GenericNamespaced>()?;
        let listener = ListenerOptions::new()
            .name(name)
            .create_sync()?;

        info!("Named pipe server listening");

        // Accept a single connection
        match listener.accept() {
            Ok(mut stream) => {
                info!("Client connected");

                // Send ready message
                let ready_msg = IpcMessage::ready();
                if let Ok(json) = ready_msg.to_json() {
                    let mut msg = json;
                    msg.push('\n');
                    if let Err(e) = stream.write_all(msg.as_bytes()) {
                        error!("Failed to send ready message: {}", e);
                        return Ok(());
                    }
                }

                // Use buffered reader for the stream
                let reader_stream = stream.try_clone()?;
                let mut reader = BufReader::new(reader_stream);
                let mut line = String::new();

                loop {
                    line.clear();

                    // Try to read a line (non-blocking would be better but this works)
                    match reader.read_line(&mut line) {
                        Ok(0) => {
                            // EOF - client disconnected
                            info!("Client disconnected");
                            break;
                        }
                        Ok(_) => {
                            let trimmed = line.trim();
                            if trimmed.is_empty() {
                                continue;
                            }

                            debug!("Received: {}", trimmed);

                            match IpcMessage::from_json(trimmed) {
                                Ok(msg) => {
                                    if matches!(msg, IpcMessage::Shutdown) {
                                        info!("Received shutdown command");
                                        break;
                                    }

                                    if self.to_app.send(msg).is_err() {
                                        error!("Failed to send message to app");
                                        break;
                                    }
                                }
                                Err(e) => {
                                    warn!("Failed to parse message: {}", e);
                                }
                            }
                        }
                        Err(e) => {
                            error!("Failed to read from pipe: {}", e);
                            break;
                        }
                    }

                    // Send any outgoing messages
                    while let Ok(msg) = self.from_app.try_recv() {
                        if let Ok(json) = msg.to_json() {
                            let mut out = json;
                            out.push('\n');
                            if let Err(e) = stream.write_all(out.as_bytes()) {
                                error!("Failed to write to pipe: {}", e);
                                break;
                            }
                        }
                    }
                }
            }
            Err(e) => {
                error!("Failed to accept connection: {}", e);
            }
        }

        info!("Named Pipe IPC server stopped");
        Ok(())
    }

    #[cfg(not(windows))]
    pub fn run_named_pipe(&mut self, _pipe_name: &str) -> Result<()> {
        anyhow::bail!("Named pipes are only supported on Windows")
    }
}

/// IPC message receiver for the main application
pub struct IpcReceiver {
    rx: Receiver<IpcMessage>,
}

impl IpcReceiver {
    pub fn new(rx: Receiver<IpcMessage>) -> Self {
        Self { rx }
    }

    /// Try to receive a message without blocking
    pub fn try_recv(&self) -> Option<IpcMessage> {
        self.rx.try_recv().ok()
    }
}

/// IPC message sender for the main application
pub struct IpcSender {
    tx: Sender<IpcMessage>,
}

impl IpcSender {
    pub fn new(tx: Sender<IpcMessage>) -> Self {
        Self { tx }
    }

    /// Send a message to the IPC server
    pub fn send(&self, msg: IpcMessage) -> bool {
        self.tx.send(msg).is_ok()
    }
}

/// Start IPC server in a background thread
pub fn start_ipc_server(
    pipe_name: Option<String>,
    use_stdio: bool,
) -> Option<(IpcReceiver, IpcSender)> {
    if !use_stdio && pipe_name.is_none() {
        return None;
    }

    let (to_app_tx, to_app_rx) = std::sync::mpsc::channel();
    let (from_app_tx, from_app_rx) = std::sync::mpsc::channel();

    let pipe_name_clone = pipe_name.clone();
    std::thread::spawn(move || {
        let mut server = IpcServer::new(to_app_tx, from_app_rx);

        if use_stdio {
            if let Err(e) = server.run_stdio() {
                error!("Stdio server error: {}", e);
            }
        } else if let Some(ref name) = pipe_name_clone {
            if let Err(e) = server.run_named_pipe(name) {
                error!("Named pipe server error: {}", e);
            }
        }
    });

    Some((IpcReceiver::new(to_app_rx), IpcSender::new(from_app_tx)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_ipc_server_creation() {
        let (to_app_tx, _to_app_rx) = std::sync::mpsc::channel();
        let (_from_app_tx, from_app_rx) = std::sync::mpsc::channel();
        let _server = IpcServer::new(to_app_tx, from_app_rx);
    }
}
