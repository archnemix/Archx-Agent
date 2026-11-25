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
    /// Crate name declared in the workspace (e.g. "archx-agent"). `None` means
    /// the app has no code yet, which is a valid state for a planned app.
    pub krate: Option<String>,
    /// Library entry point, relative to the app folder (e.g. "src/lib.rs").
    pub entry: Option<String>,
    /// The function the launcher calls to render the app, as
    /// `"module::function"`. It must take `&App` and return an `Element`.
    pub view: Option<String>,
    /// Where this app's own documentation lives, relative to the app folder.
    pub docs: Option<String>,
    /// Shared or app crates this app links. `archx-shared` is always implicit.
    pub requires: Vec<String>,
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

    /// Whether this app declares code. A code-less app is a reserved folder.
    pub fn has_code(&self) -> bool { self.krate.is_some() && self.entry.is_some() }

    /// Problems that would stop this app from building or being opened. Empty
    /// means the manifest is internally consistent; the paths are checked
    /// separately by `verify_files`, which touches the filesystem.
    pub fn contract_problems(&self) -> Vec<String> {
        let mut problems = Vec::new();
        if !self.valid() {
            problems.push(format!("id `{}` must match its folder and use lowercase letters, digits or `-`", self.id));
        }
        if self.is_live() && !self.has_code() {
            problems.push("status = \"live\" needs `crate` and `entry` so the launcher can host the app".into());
        }
        if let Some(krate) = &self.krate {
            if !krate.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-') {
                problems.push(format!("crate `{krate}` must be lowercase letters, digits or `-`"));
            }
        }
        if let Some(view) = &self.view {
            match view.split_once("::") {
                Some((module, function)) if !module.is_empty() && !function.is_empty() => {}
                _ => problems.push(format!("view `{view}` must be written as `module::function`")),
            }
        }
        if self.has_code() && self.view.is_none() {
            problems.push("an app with code needs `view = \"module::function\"`".into());
        }
        if self.modes.len() > 12 {
            problems.push("at most 12 modes".into());
        }
        problems
    }

    /// Checks the declared paths inside the app folder. Used by the build-time
    /// test, never at runtime.
    pub fn verify_files(&self, folder: &Path) -> Vec<String> {
        let mut problems = Vec::new();
        if let Some(entry) = &self.entry {
            if !folder.join(entry).is_file() {
                problems.push(format!("entry `{entry}` does not exist"));
            }
        }
        if let Some(docs) = &self.docs {
            if !folder.join(docs).is_dir() {
                problems.push(format!("docs `{docs}` is not a directory"));
            }
        }
        if self.has_code() && !folder.join("Cargo.toml").is_file() {
            problems.push("an app with code needs its own Cargo.toml".into());
        }
        problems
    }

    /// A manifest must name a folder that matches its id.
    fn valid(&self) -> bool {
        !self.id.is_empty() && self.id.len() <= 40
            && self.id.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
            && !self.name.is_empty() && self.name.len() <= 60
    }
}

/// Reads a scalar key. A `[[modes]]` array-of-tables header is not a scalar, so
/// it is skipped rather than mistaken for the `modes` list.
fn field(body: &str, key: &str) -> Option<String> {
    for line in body.lines() {
        let line = line.trim();
        if line.starts_with('#') { continue; }
        if line.starts_with("[[") { break; }
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

/// Reads a list key. Two forms are accepted, because a long list is easier to
/// read one item per line:
///
/// ```toml
/// modes = ["CHAT", "TASKS"]
///
/// [[modes]]
/// name = "CHAT"
/// ```
///
/// Items are capped at 12 entries of 24 characters, and anything outside the
/// allowed character set is dropped rather than shown as mojibake on a tile.
fn list(body: &str, key: &str) -> Vec<String> {
    let mut items: Vec<String> = Vec::new();
    if let Some(raw) = field(body, key) {
        let raw = raw.trim();
        if raw.starts_with('[') {
            items.extend(raw.trim_start_matches('[').trim_end_matches(']').split(',')
                .map(|item| item.trim().trim_matches('"').trim_matches('\'').trim().to_owned()));
        }
    }
    let header = format!("[[{key}]]");
    let mut in_table = false;
    for line in body.lines() {
        let line = line.trim();
        if line.starts_with("[[") {
            in_table = line == header;
            continue;
        }
        if !in_table || line.starts_with('#') { continue; }
        let Some((name, value)) = line.split_once('=') else { continue };
        if name.trim() != "name" { continue; }
        items.push(value.trim().trim_matches('"').trim_matches('\'').trim().to_owned());
    }
    items.into_iter()
        .filter(|item| !item.is_empty() && item.len() <= 24
            && item.chars().all(|c| c.is_alphanumeric() || c == ' ' || c == '-' || c == '&' || c == '+' || c == '/'))
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
        krate: field(body, "crate"),
        entry: field(body, "entry"),
        view: field(body, "view"),
        docs: field(body, "docs"),
        requires: list(body, "requires"),
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
    // The manifest dir is `shared/`; app folders live beside it at the repo root.
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap_or(Path::new(".")).join("apps")
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

fn repo_root() -> PathBuf {
    // The manifest dir is `shared/`; app folders live beside it at the repo root.
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap_or(Path::new(".")).to_path_buf()
}

#[cfg(test)]
mod tests {
    use super::*;

    use super::*;

    fn workspace_members() -> Vec<String> {
        let manifest = std::fs::read_to_string(repo_root().join("Cargo.toml")).unwrap_or_default();
        let Some(start) = manifest.find("members") else { return Vec::new() };
        let Some(open) = manifest[start..].find('[') else { return Vec::new() };
        let Some(close) = manifest[start + open..].find(']') else { return Vec::new() };
        manifest[start + open + 1..start + open + close]
            .split(',')
            .map(|member| member.trim().trim_matches('"').trim().to_owned())
            .filter(|member| !member.is_empty())
            .collect()
    }

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

    /// The user's requirement: a manifest has to tell the truth about the files,
    /// so the app compiles from it and another AI can start from it.
    #[test]
    fn every_manifest_matches_the_files_on_disk() {
        let mut problems = Vec::new();
        for app in discover() {
            let folder = root().join(&app.id);
            for problem in app.contract_problems() {
                problems.push(format!("{}: {problem}", app.id));
            }
            if folder.is_dir() {
                for problem in app.verify_files(&folder) {
                    problems.push(format!("{}: {problem}", app.id));
                }
            }
        }
        assert!(problems.is_empty(), "manifest contract violations: {problems:#?}");
    }

    #[test]
    fn a_declared_crate_is_a_workspace_member() {
        let members = workspace_members();
        for app in discover() {
            let Some(krate) = &app.krate else { continue };
            let folder = format!("apps/{}", app.id);
            assert!(members.contains(&folder),
                "`{krate}` declares `crate` but {folder} is not in [workspace] members {members:?}");
        }
    }

    #[test]
    fn live_apps_declare_how_they_render() {
        let apps = discover();
        let live: Vec<_> = apps.iter().filter(|app| app.is_live()).map(|app| app.name.as_str()).collect();
        assert_eq!(live, vec!["Archx Agent"]);
        assert_eq!(apps[0].name, "Archx Agent");
        let agent = &apps[0];
        assert_eq!(agent.status_label(), "OPEN");
        assert_eq!(agent.view.as_deref(), Some("home::view"),
            "the launcher calls this function; the app must export it");
        assert_eq!(agent.docs.as_deref(), Some("docs"));
        assert!(agent.has_code());
    }

    #[test]
    fn a_reserved_folder_needs_no_code_yet() {
        let training = find("training").expect("training space");
        assert!(!training.is_live());
        assert!(!training.has_code());
        assert!(training.contract_problems().is_empty(),
            "a code-less app is valid: {:?}", training.contract_problems());
        assert_eq!(training.status_label(), "IN PROGRESS");
        assert!(training.docs.is_some(), "the second app keeps its own docs");
        assert!(training.summary.to_lowercase().contains("train"));
        assert!(!training.modes.is_empty());
    }

    #[test]
    fn a_live_app_without_code_is_rejected() {
        let body = "name = \"Broken\"\nstatus = \"live\"\nmodes = [\"ONE\"]\n";
        let app = parse("broken", body).expect("parses");
        let problems = app.contract_problems();
        assert!(problems.iter().any(|problem| problem.contains("crate")),
            "a live app must declare its code: {problems:?}");
    }

    #[test]
    fn a_view_must_be_module_and_function() {
        let body = "name = \"Odd\"\nstatus = \"building\"\nview = \"justafunction\"\n";
        let app = parse("odd", body).expect("parses");
        assert!(app.contract_problems().iter().any(|problem| problem.contains("module::function")));
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
    fn a_manifest_cannot_smuggle_paths_out_of_its_folder() {
        let body = "name = \"Escape\"\nstatus = \"building\"\nentry = \"../../etc/passwd\"\n";
        let app = parse("escape", body).expect("parses");
        let problems = app.verify_files(Path::new("/nonexistent-folder"));
        assert!(problems.iter().any(|problem| problem.contains("does not exist")));
        // The id itself can never contain a separator.
        assert!(parse("../evil", "name = \"Evil\"\n").is_none());
    }
}
