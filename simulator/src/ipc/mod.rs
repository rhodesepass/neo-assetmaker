//! IPC communication module
//!
//! Handles communication with the Python editor via Named Pipe or stdin/stdout.

mod protocol;
mod server;

pub use protocol::*;
pub use server::{start_ipc_server, IpcReceiver, IpcSender};
