//! Purpose: Declares the Archx Agent app: its pages, provider workspaces, persistence and debug surfaces.
//!
//! Everything specific to Archx Agent lives in `apps/archx-agent/`. The launcher
//! discovers this app from `app.toml` and hosts it in-process by depending on
//! this crate; app-neutral code (vault, transports, storage, diagnostics, design
//! tokens) comes from `archx-shared`, never from a copy.

pub mod agent;
pub mod agent_visual;
pub mod app;
/// The provider, key, endpoint, model, debug and storage half of the Agent state machine.
pub mod app_provider;
pub mod custom_endpoint;
/// The Debug page: every request with its stage, owner and billing status.
pub mod debug_page;
pub mod home;
pub mod settings;
/// Every catalog test run, saved with its provenance so a failure can be read
/// back later and "never sent" is never shown as a provider error.
pub mod test_journal;

/// Version stamp shown in the Agent rail.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");
