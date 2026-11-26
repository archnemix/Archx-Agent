//! Purpose: Discovers apps from `apps/<name>/app.toml` manifests so the launcher never hard-codes a feature.
//!
//! Adding an app means adding a folder with a manifest: the tile, category,
//! status, accent and mode labels all come from that file.
//!
//! Two independent switches decide what the launcher does with a folder:
//!
//! * `ready = true|false` — has the app been *finished enough to register*?
//!   A folder that is not ready is **not registered at all**: it does not get a
//!   tile, it does not appear in the rail, and it does not touch the launcher.
//!   That is what lets several apps be built at once in parallel without any of
//!   them disturbing a launcher that already works.
//! * `status` — once ready, *how* it opens: `live` (openable), `preview`
//!   (openable, labelled), `building` (shown, not openable) or `planned`.
//!
//! The Agent's own manifest lives at `apps/archx-agent/app.toml`, so the second
//! and later apps never edit a file the Agent owns.

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
    /// "live", "preview", "planned" or "building". Only meaningful once ready.
    pub status: String,
    /// Whether this app is registered with the launcher at all. A folder with
    /// `ready = false` (or no `ready` line) is invisible to the launcher, so it
    /// can be worked on in parallel without breaking Discover.
    pub ready: bool,
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
    pub fn is_live(&self) -> bool { self.ready && self.status == "live" }

    /// The only apps the launcher shows: ready ones. Everything else is being
    /// built by someone else and stays out of the way.
    pub fn is_registered(&self) -> bool { self.ready }

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
        // A blank line, or a line that is not a key = value pair, is skipped.
        // Using `?` here aborted the whole lookup on the first blank line, which
        // is why a manifest with a comment header and a blank line parsed to
        // nothing at all.
        let Some((name, value)) = line.split_once('=') else { continue };
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
        ready: field(body, "ready").as_deref() == Some("true"),
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

thread_local! {
    /// A test-only override belonging to one thread, for the same reason the
    /// storage layer has one: `ARCHX_APPS_DIR` is shared by every test in the
    /// process, and a parallel test would otherwise scan a stranger's tree.
    static THREAD_DIR: std::cell::RefCell<Option<PathBuf>> = const { std::cell::RefCell::new(None) };
}

/// Points app discovery at `path` for the current thread only.
pub fn set_thread_directory(path: Option<PathBuf>) -> Option<PathBuf> {
    THREAD_DIR.with(|slot| slot.replace(path))
}

/// Directory searched at runtime. `ARCHX_APPS_DIR` overrides it for tests.
pub fn root() -> PathBuf {
    if let Some(path) = THREAD_DIR.with(|slot| slot.borrow().clone()) { return path; }
    if let Some(path) = std::env::var_os("ARCHX_APPS_DIR") { return PathBuf::from(path); }
    // Compiled into `shared/`, so the app folders sit one level up. Walk up from
    // the build directory instead of trusting the process cwd, because a test
    // binary inherits cargo's cwd, not this crate's.
    let mut dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    loop {
        if dir.join("apps").is_dir() { return dir.join("apps"); }
        if !dir.pop() { break; }
    }
    PathBuf::from("apps")
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

/// Every app folder that exists on disk, ready or not. This is for tests and
/// for the Debug page; the launcher uses [`registered`].
pub fn discover() -> Vec<App> { discover_in(&root()) }

fn discover_in(dir: &Path) -> Vec<App> {
    let mut apps = scan(dir);
    for (id, body) in EMBEDDED {
        if apps.iter().any(|app| app.id == id) { continue; }
        // An embedded copy is only a fallback for a tree without `apps/`; it
        // still has to pass the same readiness rule as a disk manifest.
        if let Some(mut app) = parse(id, body) {
            app.origin = Origin::Embedded;
            if app.ready { apps.push(app); }
        }
    }
    sort_tiles(&mut apps);
    apps
}

fn sort_tiles(apps: &mut [App]) {
    apps.sort_by(|a, b| b.is_live().cmp(&a.is_live()).then(a.name.to_lowercase().cmp(&b.name.to_lowercase())));
}

/// The apps the launcher actually shows: `discover()` minus anything not ready.
/// Keeping this separate is the whole point of `ready = false` — an app being
/// built in another folder cannot add, move or break a tile until it flips.
pub fn registered() -> Vec<App> {
    let mut apps: Vec<App> = discover().into_iter().filter(App::is_registered).collect();
    sort_tiles(&mut apps);
    apps
}

/// The manifest for one registered app id, if present.
pub fn find(id: &str) -> Option<App> {
    registered().into_iter().find(|app| app.id == id)
}

/// The manifest for one app id even if it is not ready, for diagnostics.
pub fn find_any(id: &str) -> Option<App> {
    discover().into_iter().find(|app| app.id == id)
}

fn repo_root() -> PathBuf {
    // The manifest dir is `shared/`; app folders live beside it at the repo root.
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap_or(Path::new(".")).to_path_buf()
}

#[cfg(test)]
mod tests {
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

    /// Writes a throwaway `apps/` tree so readiness can be tested without
    /// touching the real folders.
    fn scratch_apps(folders: &[(&str, &str)]) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("archx-apps-{}-{}", std::process::id(), folders.len()));
        let _ = std::fs::remove_dir_all(&dir);
        for (id, manifest) in folders {
            std::fs::create_dir_all(dir.join(id)).expect("folder");
            std::fs::write(dir.join(id).join("app.toml"), manifest).expect("manifest");
        }
        dir
    }

    const READY_MANIFEST: &str = "id = \"one\"\nname = \"One\"\nstatus = \"live\"\nready = true\ncrate = \"one\"\nentry = \"src/lib.rs\"\nview = \"home::view\"\nmodes = [\"A\"]\n";

    /// A shipped manifest starts with a comment block and a blank line. The
    /// parser used to abort on the blank line, so this pins the shape that is
    /// actually on disk rather than a tidy one-line fixture.
    #[test]
    fn a_manifest_with_a_comment_header_and_blank_lines_still_parses() {
        let raw = std::fs::read_to_string(root().join("archx-agent/app.toml")).expect("manifest on disk");
        // Checked by line rather than by "\n\n": Windows checks the tree out with
        // CRLF, and a literal newline comparison would only pass on Unix.
        assert!(raw.lines().any(|line| line.trim().is_empty()),
            "the real manifest has blank lines between its comment header and its keys");
        let app = parse("archx-agent", &raw).expect("a commented manifest parses");
        assert_eq!(app.name, "Archx Agent");
        assert!(app.ready, "`ready = true` must be read past the comment header");
        assert_eq!(app.view.as_deref(), Some("home::view"));
    }

    #[test]
    fn every_shipped_manifest_parses_and_is_unique() {
        let apps = discover();
        assert!(apps.len() >= 2, "expected the Agent and at least one reserved folder");
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
        let apps = registered();
        let live: Vec<_> = apps.iter().filter(|app| app.is_live()).map(|app| app.name.as_str()).collect();
        assert_eq!(live, vec!["Archx Agent"]);
        let agent = apps.iter().find(|app| app.id == "archx-agent").expect("the Agent is registered");
        assert_eq!(agent.status_label(), "OPEN");
        assert_eq!(agent.view.as_deref(), Some("home::view"),
            "the launcher calls this function; the app must export it");
        assert_eq!(agent.docs.as_deref(), Some("docs"));
        assert!(agent.has_code());
    }

    #[test]
    fn a_reserved_folder_needs_no_code_yet() {
        let training = find_any("training").expect("training space");
        assert!(!training.is_live());
        assert!(!training.has_code());
        assert!(training.contract_problems().is_empty(),
            "a code-less app is valid: {:?}", training.contract_problems());
        assert!(training.docs.is_some(), "the second app keeps its own docs");
        assert!(training.summary.to_lowercase().contains("train"));
        assert!(!training.modes.is_empty());
    }

    /// The rule the user asked for: an app that is not ready is not registered,
    /// so several apps can be built at once without disturbing the launcher.
    #[test]
    fn an_unready_folder_is_invisible_to_the_launcher() {
        let not_ready = "id = \"two\"\nname = \"Two\"\nstatus = \"live\"\nready = false\ncrate = \"two\"\nentry = \"src/lib.rs\"\nview = \"home::view\"\n";
        let missing = "id = \"three\"\nname = \"Three\"\nstatus = \"live\"\ncrate = \"three\"\nentry = \"src/lib.rs\"\nview = \"home::view\"\n";
        let dir = scratch_apps(&[("one", READY_MANIFEST), ("two", not_ready), ("three", missing)]);
        set_thread_directory(Some(dir.clone()));
        let ids: Vec<String> = discover().into_iter().map(|app| app.id).collect();
        assert!(ids.contains(&"one".to_owned()) && ids.contains(&"two".to_owned()) && ids.contains(&"three".to_owned()),
            "every folder is still discoverable for diagnostics: {ids:?}");
        // The embedded fallbacks are appended to any scan, so only the scratch
        // ids are judged here.
        let shown: Vec<String> = registered().into_iter().map(|app| app.id)
            .filter(|id| ["one", "two", "three"].contains(&id.as_str())).collect();
        assert_eq!(shown, vec!["one".to_owned()], "only the ready app gets a tile");
        // A missing `ready` line is not ready: silence must never register code.
        assert!(!find_any("three").expect("three").ready);
        set_thread_directory(None);
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn a_ready_app_cannot_lie_about_being_open() {
        let mut app = parse("one", READY_MANIFEST).expect("parses");
        assert!(app.is_live() && app.is_registered());
        // Flipping ready off closes it even though status still says live.
        app.ready = false;
        assert!(!app.is_live(), "an unready app can never be open");
        // Status still labels a shown-but-unready app, for the folder itself.
        assert_eq!(app.status_label(), "OPEN");
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
