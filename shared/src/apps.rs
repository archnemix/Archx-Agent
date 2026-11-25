//! Purpose: Discovers apps from `apps/<name>/app.toml` manifests so the launcher never hard-codes a feature.
//!
//! Adding an app means adding a folder with a manifest: the tile, category,
//! status, accent and mode labels all come from that file. `status = "live"` is
//! what makes a tile openable; anything else (planned, building) renders as a
//! non-clickable card. The Agent's own manifest lives at
//! `apps/archx-agent/app.toml`, and the second app's folder at
//! `apps/training/app.toml`, so the two never edit this file in parallel.

use std::path::{Path, PathBuf};

/// Where a manifest was found. Embedded copies keep CI honest when the tree is
/// checked out without the `apps/` directory.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Origin {
    Disk,
    Embedded,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct App {
    /// Folder name, e.g. "archx-agent". Stable identifier.
    pub id: String,
    pub name: String,
    pub category: String,
    pub summary: String,
    /// "live", "preview", "planned" or "building".
    pub status: String,
    pub modes: Vec<String>,
    /// Artwork style: "agent" or "workbench".
    pub art: String,
    pub origin: Origin,
}

impl App {
    pub fn is_live(&self) -> bool { self.status == "live" }

    pub fn status_label(&self) -> &'static str {
        match self.status.as_str() {
            "live" => "OPEN",
            "preview" => "PREVIEW",
            "building" => "IN PROGRESS",
            _ => "COMING LATER",
        }
    }

    pub fn mode_count(&self) -> u8 { self.modes.len().max(1).min(12) as u8 }

    /// One-word stage names used by the workbench artwork.
    pub fn stage_words(&self) -> Vec<String> {
        self.modes.iter().take(4).cloned().collect()
    }

    /// A manifest must name a folder that matches its id.
    fn valid(&self) -> bool {
        !self.id.is_empty() && self.id.len() <= 40
            && self.id.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
            && !self.name.is_empty() && self.name.len() <= 60
    }
}

fn field(body: &str, key: &str) -> Option<String> {
    for line in body.lines() {
        let line = line.trim();
        if line.starts_with('#') { continue; }
        let (name, value) = line.split_once('=')?;
        if name.trim() != key { continue; }
        let value = value.trim();
        let value = value.strip_prefix('"').and_then(|value| value.strip_suffix('"'))
            .or_else(|| value.strip_prefix('\'').and_then(|value| value.strip_suffix('\'')))
            .unwrap_or(value);
        return Some(value.trim().to_owned());
    }
    None
}

fn list(body: &str, key: &str) -> Vec<String> {
    let Some(raw) = field(body, key) else { return Vec::new() };
    raw.trim_start_matches('[').trim_end_matches(']')
        .split(',')
        .map(|item| item.trim().trim_matches('"').trim_matches('\'').trim().to_owned())
        .filter(|item| !item.is_empty() && item.len() <= 24 && item.chars().all(|c| c.is_alphanumeric() || c == ' ' || c == '-' || c == '&' || c == '+' || c == '/'))
        .take(12)
        .collect()
}

/// Parses a manifest with `id` derived from the folder name.
pub fn parse(id: &str, body: &str) -> Option<App> {
    let app = App {
        id: id.to_owned(),
        name: field(body, "name")?.chars().take(60).collect(),
        category: field(body, "category").unwrap_or_else(|| "AI WORKSPACE".into()).chars().take(48).collect(),
        summary: field(body, "summary").unwrap_or_default().chars().take(200).collect(),
        status: field(body, "status").unwrap_or_else(|| "planned".into()).to_lowercase(),
        modes: list(body, "modes"),
        art: field(body, "art").unwrap_or_else(|| "workbench".into()).to_lowercase(),
        origin: Origin::Disk,
    };
    app.valid().then_some(app)
}

/// Manifests compiled into the binary, used when `apps/` is absent at runtime.
/// Keep these in sync with the files on disk; `manifests_match_the_tree` tests it.
pub const EMBEDDED: [(&str, &str); 2] = [
    ("archx-agent", include_str!("../../apps/archx-agent/app.toml")),
    ("training", include_str!("../../apps/training/app.toml")),
];

/// Directory searched at runtime. `ARCHX_APPS_DIR` overrides it for tests.
pub fn root() -> PathBuf {
    if let Some(path) = std::env::var_os("ARCHX_APPS_DIR") { return PathBuf::from(path); }
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("apps")
}

fn scan(dir: &Path) -> Vec<App> {
    let Ok(entries) = std::fs::read_dir(dir) else { return Vec::new() };
    let mut apps = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_dir() { continue; }
        let Some(id) = path.file_name().and_then(|name| name.to_str()) else { continue };
        let Ok(body) = std::fs::read_to_string(path.join("app.toml")) else { continue };
        if let Some(app) = parse(id, &body) { apps.push(app); }
    }
    apps
}

/// All known apps: disk manifests first, embedded ones only for ids the disk
/// scan did not provide. Live apps sort first, then alphabetically.
pub fn discover() -> Vec<App> {
    let mut apps = scan(&root());
    for (id, body) in EMBEDDED {
        if apps.iter().any(|app| app.id == id) { continue; }
        if let Some(mut app) = parse(id, body) { app.origin = Origin::Embedded; apps.push(app); }
    }
    apps.sort_by(|a, b| b.is_live().cmp(&a.is_live()).then(a.name.to_lowercase().cmp(&b.name.to_lowercase())));
    apps
}

/// The manifest for one app id, if present.
pub fn find(id: &str) -> Option<App> {
    discover().into_iter().find(|app| app.id == id)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_shipped_manifest_parses_and_is_unique() {
        let apps = discover();
        assert!(apps.len() >= 2, "expected the Agent and the training space");
        let ids: std::collections::HashSet<_> = apps.iter().map(|app| app.id.as_str()).collect();
        assert_eq!(ids.len(), apps.len());
        assert!(apps.iter().all(|app| app.valid() && !app.name.is_empty()));
        for app in &apps {
            if app.origin == Origin::Embedded {
                let path = root().join(&app.id).join("app.toml");
                assert!(!path.exists(), "embedded fallback used while {} exists", path.display());
            }
        }
    }

    #[test]
    fn the_agent_is_the_only_live_app_and_live_sorts_first() {
        let apps = discover();
        let live: Vec<_> = apps.iter().filter(|app| app.is_live()).map(|app| app.name.as_str()).collect();
        assert_eq!(live, vec!["Archx Agent"]);
        assert_eq!(apps[0].name, "Archx Agent");
        assert_eq!(apps[0].status_label(), "OPEN");
        let training = apps.iter().find(|app| app.id == "training").expect("training space");
        assert!(!training.is_live());
        assert_eq!(training.status_label(), "IN PROGRESS");
        assert!(training.summary.to_lowercase().contains("train"));
        assert!(!training.modes.is_empty());
    }

    #[test]
    fn manifests_define_tiles_without_touching_launcher_code() {
        // A brand-new app folder with a manifest becomes a tile with no code edit.
        let dir = std::env::temp_dir().join(format!("archx-apps-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(dir.join("embed-lab")).unwrap();
        std::fs::write(dir.join("embed-lab/app.toml"),
            "name = \"Embed Lab\"\ncategory = \"EMBEDDINGS\"\nstatus = \"planned\"\nart = \"workbench\"\nmodes = [\"CHUNK\", \"INDEX\", \"SEARCH\"]\n")
            .unwrap();
        unsafe { std::env::set_var("ARCHX_APPS_DIR", &dir) };
        let apps = discover();
        let found = apps.iter().find(|app| app.id == "embed-lab").expect("discovered from disk");
        assert_eq!(found.name, "Embed Lab");
        assert_eq!(found.mode_count(), 3);
        assert_eq!(found.origin, Origin::Disk);
        // Embedded copy is superseded by the disk manifest of the same id.
        assert!(!apps.iter().any(|app| app.id == "archx-agent"));
        unsafe { std::env::remove_var("ARCHX_APPS_DIR") };
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn malformed_manifests_are_ignored_not_fatal() {
        assert!(parse("no-name", "category = \"x\"").is_none());
        assert!(parse("Bad_Id", "name = \"x\"").is_none());
        assert!(parse("", "name = \"x\"").is_none());
        let app = parse("ok", "name = \"Fine\"\nstatus = \"WEIRD\"\nmodes = [\"A\", \"b\", \"\"]").unwrap();
        assert_eq!(app.status, "weird");
        assert_eq!(app.status_label(), "COMING LATER");
        assert_eq!(app.modes, vec!["A", "b"]);
        // Comments and blank lines do not confuse the reader.
        let commented = parse("ok", "# name = \"Wrong\"\nname = \"Right\"\n\nstatus = \"live\"\n").unwrap();
        assert_eq!(commented.name, "Right");
        assert!(commented.is_live());
    }
}
