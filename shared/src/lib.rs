//! Purpose: Exposes the app-neutral modules the launcher and every app compile, so no app copies them.
//!
//! These modules were framework-level all along: transcripts, the vault, endpoint
//! templates, transports, diagnostics, health, the debug journal, memory
//! accounting, persistence, storage locations and design tokens. They live in one
//! crate so the launcher and the apps cannot drift apart.

pub mod apps;
pub mod credentials;
pub mod debug_log;
pub mod diagnostics;
pub mod endpoints;
pub mod health;
pub mod memory;
pub mod model_catalog;
pub mod model_meta;
pub mod persist;
pub mod provider_api;
pub mod storage;
pub mod style;
pub mod transcripts;
pub mod usage;
