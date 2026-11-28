//! Purpose: Root module for `archx-training`, exposing the native Rust Model Training pipeline to Archx AI Lab and the standalone `archx-training` desktop binary.

pub mod app;
pub mod charts;
pub mod config;
pub mod dataset;
pub mod hardware;
pub mod home;
pub mod optim;
pub mod repro;
pub mod rng;
pub mod telemetry;
pub mod tokenizer;
pub mod trainer;
pub mod transformer;
pub mod views;
pub mod views_advanced;

pub use app::{App, Message};

/// Crate version displayed in the Model Training sidebar footer.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");
