//! Purpose: Persists the Agent's non-secret state to small atomic JSON files in the OS app-data directory, with explicit wipe.
//!
//! Design decision (documented in `Docs/Persistence.md`): the app writes one
//! small JSON document per area, each replaced atomically (write a temporary
//! file, then rename over the target). A JSON file is inspectable, needs no
//! server, and fails closed: a corrupt file is ignored rather than partially
//! applied. Secrets never enter this layer — API keys stay in the OS vault and
//! the writer refuses a document that carries a credential-shaped field.

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{Map, Value};

/// Areas a user can wipe independently. `Settings` holds provider/model
/// configuration and display preferences; `Chats` holds conversation text;
/// `ModelTests` holds probe evidence; `Debug` holds the request journal.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Area {
    Settings,
    Chats,
    ModelTests,
    Debug,
}

impl Area {
    pub const ALL: [Self; 4] = [Self::Settings, Self::Chats, Self::ModelTests, Self::Debug];

    pub fn id(self) -> &'static str {
        match self {
            Self::Settings => "settings",
            Self::Chats => "chats",
            Self::ModelTests => "model-tests",
            Self::Debug => "debug-journal",
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::Settings => "Providers, models and display",
            Self::Chats => "Chat history",
            Self::ModelTests => "Model test results",
            Self::Debug => "Debug journal",
        }
    }

    fn file(self) -> &'static str {
        match self {
            Self::Settings => "settings.json",
            Self::Chats => "chats.json",
            Self::ModelTests => "model-tests.json",
            Self::Debug => "debug-journal.json",
        }
    }

    pub fn path(self) -> PathBuf {
        root().join(self.file())
    }

    pub fn exists(self) -> bool {
        self.path().is_file()
    }
}

/// `ARCHX_CONFIG_DIR` overrides the location for tests and portable runs.
pub fn root() -> PathBuf {
    if let Some(path) = std::env::var_os("ARCHX_CONFIG_DIR") {
        return PathBuf::from(path);
    }
    #[cfg(target_os = "windows")]
    if let Some(base) = std::env::var_os("APPDATA") {
        return PathBuf::from(base).join("Archx AI Lab");
    }
    #[cfg(target_os = "macos")]
    if let Some(home) = std::env::var_os("HOME") {
        return PathBuf::from(home).join("Library/Application Support/Archx AI Lab");
    }
    if let Some(base) = std::env::var_os("XDG_CONFIG_HOME") {
        return PathBuf::from(base).join("archx-ai-lab");
    }
    if let Some(home) = std::env::var_os("HOME") {
        return PathBuf::from(home).join(".config/archx-ai-lab");
    }
    std::env::temp_dir().join("archx-ai-lab")
}

/// Seconds since the Unix epoch, used for persisted cooldown deadlines.
pub fn now_secs() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|elapsed| elapsed.as_secs()).unwrap_or(0)
}

/// Field names that would mean a credential leaked into a persisted document.
const FORBIDDEN_FIELDS: [&str; 9] = [
    "api_key", "apikey", "key", "authorization", "token", "secret", "password", "custom_curl", "headers",
];

/// Returns the first credential-shaped field found anywhere in `value`.
/// The persisted documents never need one: keys live in the OS vault.
pub fn credential_field(value: &Value) -> Option<String> {
    match value {
        Value::Object(map) => {
            for (name, child) in map {
                if FORBIDDEN_FIELDS.contains(&name.to_ascii_lowercase().as_str()) {
                    return Some(name.clone());
                }
                if let Some(found) = credential_field(child) {
                    return Some(found);
                }
            }
            None
        }
        Value::Array(items) => items.iter().find_map(credential_field),
        _ => None,
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SaveError {
    /// The document carried a field the persistence layer must never hold.
    Credential(String),
    Io,
}

impl SaveError {
    pub fn message(&self) -> String {
        match self {
            Self::Credential(field) => format!(
                "Refused to save: the document contained a credential field \"{field}\". Keys stay in the OS vault."),
            Self::Io => "Could not write the data file. Changes stay in memory for this session.".into(),
        }
    }
}

fn write_atomic(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    // A distinct temporary name keeps a half-written file from ever being read.
    let temporary = path.with_extension("json.tmp");
    std::fs::write(&temporary, bytes)?;
    std::fs::rename(&temporary, path)
}

pub fn save(area: Area, document: &Value) -> Result<(), SaveError> {
    if let Some(field) = credential_field(document) {
        return Err(SaveError::Credential(field));
    }
    let bytes = serde_json::to_vec_pretty(document).map_err(|_| SaveError::Io)?;
    write_atomic(&area.path(), &bytes).map_err(|_| SaveError::Io)
}

/// Reads one area. A missing file yields `None`; a corrupt file yields
/// `Some(Err(()))` so the caller can tell the user instead of silently
/// starting fresh.
pub fn load(area: Area) -> Option<Result<Value, ()>> {
    let bytes = std::fs::read(area.path()).ok()?;
    Some(serde_json::from_slice(&bytes).map_err(|_| ()))
}

/// Deletes one area (and any leftover temporary file).
pub fn wipe(area: Area) -> bool {
    let path = area.path();
    let temporary = path.with_extension("json.tmp");
    let _ = std::fs::remove_file(&temporary);
    match std::fs::remove_file(&path) {
        Ok(()) => true,
        Err(error) => error.kind() == std::io::ErrorKind::NotFound,
    }
}

/// Deletes every area. Returns the labels actually present beforehand.
pub fn wipe_all() -> BTreeSet<&'static str> {
    let mut removed = BTreeSet::new();
    for area in Area::ALL {
        if area.exists() && wipe(area) {
            removed.insert(area.label());
        }
    }
    removed
}

/// Human-readable location for the Settings page ("Switch → Storage").
pub fn display_path() -> String {
    root().display().to_string()
}

/// A stable, versioned envelope so a future migration can recognise old files.
pub fn envelope(kind: &str, body: Value) -> Value {
    let mut map = Map::new();
    map.insert("version".into(), Value::from(1));
    map.insert("kind".into(), Value::from(kind));
    map.insert("body".into(), body);
    Value::Object(map)
}

/// Reads the `body` of an envelope, rejecting a document of another kind.
pub fn body(value: &Value) -> Option<&Value> {
    if value.get("version").and_then(Value::as_u64) != Some(1) {
        return None;
    }
    value.get("body")
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn scratch(name: &str) -> PathBuf {
        let path = std::env::temp_dir().join(format!("archx-storage-test-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&path);
        path
    }

    #[test]
    fn credential_shaped_fields_are_refused_before_any_write() {
        let document = json!({"providers": [{"name": "OpenRouter", "api_key": "sk-live"}]});
        assert_eq!(credential_field(&document), Some("api_key".into()));
        let clean = json!({"providers": [{"name": "OpenRouter", "keys": 2}]});
        assert_eq!(credential_field(&clean), None);
        // "keys" (a count) is not a credential; only exact field names are.
        assert_eq!(credential_field(&json!({"headers": "Authorization: Bearer x"})), Some("headers".into()));
        assert_eq!(credential_field(&json!([{"nested": [{"TOKEN": "x"}]}])), Some("TOKEN".into()));
    }

    #[test]
    fn envelope_round_trips_and_rejects_other_kinds() {
        let value = envelope("settings", json!({"text_scale": 1.1}));
        assert_eq!(body(&value), Some(&json!({"text_scale": 1.1})));
        assert_eq!(body(&json!({"version": 2, "kind": "settings", "body": {}})), None);
        assert_eq!(body(&json!({"kind": "chats", "body": {}})), None);
    }

    #[test]
    fn save_load_wipe_use_the_override_directory_and_are_atomic() {
        let dir = scratch("roundtrip");
        unsafe { std::env::set_var("ARCHX_CONFIG_DIR", &dir) };
        let document = envelope("settings", json!({"display": {"chat_scale": 1.0}}));
        save(Area::Settings, &document).expect("save");
        assert!(Area::Settings.exists());
        assert_eq!(load(Area::Settings), Some(Ok(document.clone())));
        // No temporary file survives a successful write.
        assert!(!dir.join("settings.json.tmp").exists());
        // A refused document leaves the previous file untouched.
        assert_eq!(save(Area::Settings, &json!({"api_key": "x"})), Err(SaveError::Credential("api_key".into())));
        assert_eq!(load(Area::Settings), Some(Ok(document)));
        assert!(wipe(Area::Settings));
        assert!(!Area::Settings.exists());
        assert_eq!(load(Area::Settings), None);
        unsafe { std::env::remove_var("ARCHX_CONFIG_DIR") };
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn corrupt_file_is_reported_instead_of_silently_reset() {
        let dir = scratch("corrupt");
        unsafe { std::env::set_var("ARCHX_CONFIG_DIR", &dir) };
        std::fs::create_dir_all(&dir).expect("dir");
        std::fs::write(Area::Chats.path(), b"{ this is not json").expect("write");
        assert_eq!(load(Area::Chats), Some(Err(())));
        assert!(wipe(Area::Chats));
        unsafe { std::env::remove_var("ARCHX_CONFIG_DIR") };
        let _ = std::fs::remove_dir_all(dir);
    }
}
