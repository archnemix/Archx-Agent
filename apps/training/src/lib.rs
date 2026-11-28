//! Purpose: Root module for `archx-training`, exposing the native Rust Model Training pipeline to Archx AI Lab.

pub mod app;
pub mod charts;
pub mod config;
pub mod dataset;
pub mod home;
pub mod optim;
pub mod rng;
pub mod telemetry;
pub mod tokenizer;
pub mod trainer;
pub mod transformer;
pub mod views;

pub use app::{App, Message};

/// Crate version displayed in the Model Training sidebar footer.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");
