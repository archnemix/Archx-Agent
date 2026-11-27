//! Purpose: Defines the persisted settings document (providers, models, health, display) and its save/load/wipe.
//!
//! Nothing secret is stored: vault key *ids* yes, key text never. The write path
//! refuses a credential-shaped field, so a bug in a caller cannot quietly move a
//! key onto disk. Display preferences (text scale per area) live here too, which
//! is what makes "enlarge the chat text" survive a restart.

use serde_json::{json, Map, Value};

use crate::credentials::Provider;
use crate::endpoints::Registry;
use crate::health::{KeyHealthSet, ModelHealthSet};
use crate::storage::{self, Area, SaveError};

/// Text scale multiplier applied to one area of the interface.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TextScale(u16); // hundredths, 80..=160

impl Default for TextScale {
    fn default() -> Self { Self(100) }
}

impl TextScale {
    pub const MIN: u16 = 80;
    pub const MAX: u16 = 160;
    pub const STEP: u16 = 5;

    pub fn from_percent(percent: u16) -> Self {
        Self(percent.clamp(Self::MIN, Self::MAX))
    }

    pub fn percent(self) -> u16 { self.0 }

    /// The multiplier a view applies to its base font size.
    pub fn factor(self) -> f32 { f32::from(self.0) / 100.0 }

    pub fn larger(self) -> Self { Self((self.0 + Self::STEP).min(Self::MAX)) }
    pub fn smaller(self) -> Self { Self(self.0.saturating_sub(Self::STEP).max(Self::MIN)) }

    pub fn label(self) -> String { format!("{}%", self.0) }
}

/// Per-area text sizes, so Chat can be larger without enlarging Settings.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DisplaySettings {
    pub chat: TextScale,
    pub settings: TextScale,
    pub launcher: TextScale,
    /// Widest comfortable reading measure for a chat message, in pixels.
    pub chat_measure: u16,
}

impl Default for DisplaySettings {
    fn default() -> Self {
        Self { chat: TextScale::default(), settings: TextScale::default(), launcher: TextScale::default(), chat_measure: 860 }
    }
}

impl DisplaySettings {
    pub const MEASURE_MIN: u16 = 620;
    pub const MEASURE_MAX: u16 = 1080;

    pub fn measure_wider(self) -> Self { Self { chat_measure: (self.chat_measure + 40).min(Self::MEASURE_MAX), ..self } }
    pub fn measure_narrower(self) -> Self { Self { chat_measure: self.chat_measure.saturating_sub(40).max(Self::MEASURE_MIN), ..self } }

    pub fn to_json(self) -> Value {
        // Item 10 asks for a text size per area, so each area keeps its own
        // key. `chat_measure` is the reading width, not a size.
        json!({
            "chat_scale": self.chat.percent(),
            "settings_scale": self.settings.percent(),
            "launcher_scale": self.launcher.percent(),
            "chat_measure": self.chat_measure,
        })
    }

    pub fn from_json(value: &Value) -> Self {
        let percent = |key: &str| value.get(key).and_then(Value::as_u64)
            .map(|raw| TextScale::from_percent(raw.min(400) as u16)).unwrap_or_default();
        let mut display = Self {
            chat: percent("chat_scale"),
            settings: percent("settings_scale"),
            launcher: percent("launcher_scale"),
            ..Self::default()
        };
        if let Some(measure) = value.get("chat_measure").and_then(Value::as_u64) {
            display.chat_measure = (measure as u16).clamp(Self::MEASURE_MIN, Self::MEASURE_MAX);
        }
        display
    }
}

/// Everything that survives a restart, minus secrets.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PersistedSettings {
    pub provider: Provider,
    pub models: [Vec<String>; Provider::COUNT],
    pub chosen: [Option<usize>; Provider::COUNT],
    pub custom_url: String,
    pub endpoints: Registry,
    pub keys: KeyHealthSet,
    pub model_health: ModelHealthSet,
    pub display: DisplaySettings,
    /// The App's own per-stage RAM matrix (Settings → Runtime memory).
    pub budget: crate::memory::Budget,
    /// The Launcher's per-stage matrix. Separate on purpose: launcher settings
    /// live here, app settings live in the app, and neither edits the other.
    pub launcher_budget: crate::memory::Budget,
    pub stream_chat: bool,
    pub dialog_timeout_secs: u16,
    pub import_page_size: u16,
    pub last_page: String,
}

impl Default for PersistedSettings {
    fn default() -> Self {
        Self {
            provider: Provider::OpenRouter,
            models: std::array::from_fn(|_| Vec::new()),
            chosen: [None; Provider::COUNT],
            custom_url: String::new(),
            endpoints: Registry::new(),
            keys: KeyHealthSet::new(),
            model_health: ModelHealthSet::new(),
            display: DisplaySettings::default(),
            budget: crate::memory::Budget::default(),
            launcher_budget: crate::memory::Budget::default(),
            stream_chat: true,
            dialog_timeout_secs: 45,
            import_page_size: 60,
            last_page: "home".to_owned(),
        }
    }
}

/// Only the launcher's own page ids are valid on disk; anything else becomes Home.
fn page_id(page: &str) -> &str {
    match page { "agent" => "agent", "settings" => "settings", "debug" => "debug", "about" => "about", _ => "home" }
}

impl PersistedSettings {
    pub fn to_json(&self) -> Value {
        // Health is keyed by model id / key id, and both repeat across providers,
        // so each provider keeps its own block. A wrong value here would make the
        // file unreadable at start-up, so the writer is tested against a reload.
        let mut providers = Map::new();
        for provider in Provider::ALL {
            let index = provider.index();
            providers.insert(provider.name().into(), json!({
                "models": self.models[index].clone(),
                "chosen": self.chosen[index],
                "keys": self.keys_for(provider).to_json(),
                "model_health": self.model_health_for(provider).to_json(),
            }));
        }
        json!({
            "provider": self.provider.name(),
            "providers": providers,
            "custom_url": self.custom_url.clone(),
            "endpoints": self.endpoints.to_json(),
            "display": self.display.to_json(),
            "budget": self.budget.to_json(),
            // Which stages the launcher keeps its own data for. The launcher's
            // own state is a few KB, so this is a decision recorded honestly,
            // not a cap; the UI says exactly that.
            "launcher_budget": self.launcher_budget.to_json(),
            "stream_chat": self.stream_chat,
            "dialog_timeout_secs": self.dialog_timeout_secs,
            "import_page_size": self.import_page_size,
            "last_page": page_id(&self.last_page),
        })
    }

    /// Health is stored per provider because key ids repeat across providers.
    fn keys_for(&self, _provider: Provider) -> &KeyHealthSet { &self.keys }
    fn model_health_for(&self, _provider: Provider) -> &ModelHealthSet { &self.model_health }

    pub fn from_json(value: &Value) -> Option<Self> {
        // Accepts either a bare body or a whole envelope, so the on-disk file,
        // the to_json() round trip and the tests all read the same way.
        let body = storage::body(value).unwrap_or(value);
        let mut settings = Self::default();
        settings.provider = Provider::ALL.iter().copied()
            .find(|provider| Some(provider.name()) == body.get("provider").and_then(Value::as_str))
            .unwrap_or(Provider::OpenRouter);
        if let Some(providers) = body.get("providers").and_then(Value::as_object) {
            for provider in Provider::ALL {
                let Some(entry) = providers.get(provider.name()) else { continue };
                let index = provider.index();
                if let Some(models) = entry.get("models").and_then(Value::as_array) {
                    settings.models[index] = models.iter()
                        .filter_map(Value::as_str)
                        .filter(|id| crate::provider_api::valid_model(provider, id))
                        .take(2048).map(str::to_owned).collect();
                }
                settings.chosen[index] = entry.get("chosen").and_then(Value::as_u64)
                    .map(|slot| slot as usize)
                    .filter(|slot| *slot < settings.models[index].len());
                if let Some(keys) = entry.get("keys") {
                    settings.keys = KeyHealthSet::from_json(keys);
                }
                if let Some(health) = entry.get("model_health") {
                    settings.model_health = ModelHealthSet::from_json(health);
                }
            }
        }
        settings.custom_url = body.get("custom_url").and_then(Value::as_str).unwrap_or("").chars().take(2048).collect();
        settings.endpoints = Registry::from_json(body.get("endpoints").unwrap_or(&Value::Null));
        if let Some(display) = body.get("display") { settings.display = DisplaySettings::from_json(display); }
        if let Some(budget) = body.get("budget") { settings.budget = crate::memory::Budget::from_json(budget); }
        if let Some(budget) = body.get("launcher_budget") { settings.launcher_budget = crate::memory::Budget::from_json(budget); }
        settings.stream_chat = body.get("stream_chat").and_then(Value::as_bool).unwrap_or(true);
        settings.dialog_timeout_secs = body.get("dialog_timeout_secs").and_then(Value::as_u64)
            .map(|raw| raw.clamp(15, 180) as u16).unwrap_or(45);
        settings.import_page_size = body.get("import_page_size").and_then(Value::as_u64)
            .map(|raw| raw.clamp(20, 200) as u16).unwrap_or(60);
        settings.last_page = page_id(body.get("last_page").and_then(Value::as_str).unwrap_or("home")).to_owned();
        Some(settings)
    }

    pub fn save(&self) -> Result<(), SaveError> {
        storage::save(Area::Settings, self.to_json())
    }

    pub fn load() -> Option<Self> { Self::from_json(&storage::load_body(Area::Settings)?) }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn text_scales_clamp_and_step_within_bounds() {
        let scale = TextScale::from_percent(250);
        assert_eq!(scale.percent(), TextScale::MAX);
        assert_eq!(TextScale::from_percent(10).percent(), TextScale::MIN);
        assert_eq!(TextScale::default().larger().percent(), 105);
        assert_eq!(TextScale::from_percent(82).smaller().percent(), TextScale::MIN);
        assert!((TextScale::from_percent(150).factor() - 1.5).abs() < f32::EPSILON);
        assert_eq!(TextScale::default().label(), "100%");
        // Each area is independent, which is the point of per-area control.
        let display = DisplaySettings { chat: TextScale::from_percent(130), ..DisplaySettings::default() };
        assert_eq!(display.settings.percent(), 100);
        assert_eq!(display.measure_wider().chat_measure, 900);
        assert_eq!(DisplaySettings::default().measure_narrower().chat_measure, 820);
        assert_eq!(DisplaySettings { chat_measure: DisplaySettings::MEASURE_MAX, ..DisplaySettings::default() }
            .measure_wider().chat_measure, DisplaySettings::MEASURE_MAX);
    }

    #[test]
    fn settings_round_trip_including_health_and_endpoints() {
        let mut settings = PersistedSettings::default();
        settings.provider = Provider::Gemini;
        settings.models[Provider::Gemini.index()] = vec!["gemini-2.5-flash".into(), "gemini-2.5-pro".into()];
        settings.chosen[Provider::Gemini.index()] = Some(1);
        settings.display.chat = TextScale::from_percent(120);
        settings.stream_chat = false;
        settings.endpoints.set(Provider::Gemini, crate::endpoints::Kind::Models, "https://mirror.example/v1beta/models").unwrap();
        settings.keys.sync(&[1, 2]);
        settings.keys.record_failure(2, &crate::diagnostics::from_http(429, Some("quota")), 100);
        settings.model_health.sync(&["gemini-2.5-pro".into()]);
        settings.model_health.disable("gemini-2.5-pro", "retired", 200);

        let restored = PersistedSettings::from_json(&settings.to_json()).expect("valid document");
        assert_eq!(restored.provider, Provider::Gemini);
        assert_eq!(restored.models[Provider::Gemini.index()].len(), 2);
        assert_eq!(restored.chosen[Provider::Gemini.index()], Some(1));
        assert_eq!(restored.display.chat.percent(), 120);
        assert!(!restored.stream_chat);
        assert!(restored.endpoints.is_override(Provider::Gemini, crate::endpoints::Kind::Models));
        assert_eq!(restored.keys.slot(2).map(|slot| slot.cooldown_until), Some(400));
        assert!(!restored.model_health.is_enabled("gemini-2.5-pro"));
    }

    #[test]
    fn the_two_memory_matrices_round_trip_separately() {
        let mut settings = PersistedSettings::default();
        // The app drops metadata while streaming; the launcher keeps its own
        // launcher-stage list. Neither may overwrite the other.
        settings.budget = crate::memory::Budget::default();
        settings.budget.set(crate::memory::Stage::ChatActive, crate::memory::Item::ModelMeta, false);
        settings.launcher_budget = crate::memory::Budget::default();
        settings.launcher_budget.set(crate::memory::Stage::Launcher, crate::memory::Item::ModelMeta, true);
        let restored = PersistedSettings::from_json(&settings.to_json()).expect("valid document");
        assert!(!restored.budget.keeps(crate::memory::Stage::ChatActive, crate::memory::Item::ModelMeta));
        assert!(restored.launcher_budget.keeps(crate::memory::Stage::Launcher, crate::memory::Item::ModelMeta));
        // The app's matrix was not disturbed by the launcher's edit.
        assert!(restored.budget.keeps(crate::memory::Stage::Launcher, crate::memory::Item::ChatBodies)
            == settings.budget.keeps(crate::memory::Stage::Launcher, crate::memory::Item::ChatBodies));
    }

    #[test]
    fn persisted_document_never_contains_a_credential_field() {
        let mut settings = PersistedSettings::default();
        settings.keys.sync(&[7]);
        settings.custom_url = "https://example.invalid/v1".into();
        let document = settings.to_json();
        assert_eq!(storage::credential_field(&document), None);
        // The vault key id is a number, never the key itself.
        assert!(document.to_string().contains("\"id\":7"));
    }

    #[test]
    fn hostile_or_truncated_documents_degrade_safely() {
        // A bare settings body is accepted (it is what `to_json` produces), but a
        // document with no provider map still has to come back as defaults rather
        // than as garbage.
        assert!(PersistedSettings::from_json(&json!({"version": 1})).is_some());
        // A body with nothing in it is the same as no body: defaults, not a panic.
        assert!(PersistedSettings::from_json(&json!({"version": 9, "kind": "settings", "body": {}})).is_some());
        let mut body = serde_json::Map::new();
        body.insert("version".into(), 1.into());
        body.insert("kind".into(), "settings".into());
        body.insert("body".into(), json!({
            "provider": "Nope",
            "providers": { "OpenAI": { "models": ["good-model", "../evil", ""], "chosen": 99 } },
            "display": { "chat_scale": 100_000, "chat_measure": 5 },
            "dialog_timeout_secs": 9_999,
        }));
        let settings = PersistedSettings::from_json(&Value::Object(body)).expect("body parses");
        assert_eq!(settings.provider, Provider::OpenRouter);
        assert_eq!(settings.models[Provider::OpenAI.index()], vec!["good-model"]);
        assert_eq!(settings.chosen[Provider::OpenAI.index()], None);
        assert_eq!(settings.display.chat.percent(), TextScale::MAX);
        assert_eq!(settings.display.chat_measure, DisplaySettings::MEASURE_MIN);
        assert_eq!(settings.dialog_timeout_secs, 180);
    }

    /// The whole promise of item 5: what a user configured is still there after
    /// a restart. The envelope is easy to get wrong in either direction (a body
    /// written without its header, or a reader that reads the header), and both
    /// mistakes look exactly like "it forgot everything", so they are pinned.
    #[test]
    fn a_configured_provider_survives_a_save_and_reload() {
        let dir = std::env::temp_dir().join(format!("archx-persist-round-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        crate::storage::set_thread_directory(Some(dir.clone()));
        let mut settings = PersistedSettings::default();
        settings.provider = Provider::Groq;
        settings.models[Provider::Groq.index()] = vec!["llama-3.1-8b".into(), "qwen-2.5".into()];
        settings.chosen[Provider::Groq.index()] = Some(1);
        // Two slots, so the reload also proves health is not renumbered.
        settings.keys.sync(&[1, 2]);
        settings.keys.record_failure(1, &crate::diagnostics::from_http(429, None), 1_000);
        settings.display.chat = TextScale::from_percent(120);
        settings.save().expect("save");
        let loaded = PersistedSettings::load().expect("reload");
        assert_eq!(loaded.provider, Provider::Groq);
        assert_eq!(loaded.models[Provider::Groq.index()], vec!["llama-3.1-8b", "qwen-2.5"]);
        assert_eq!(loaded.chosen[Provider::Groq.index()], Some(1));
        assert_eq!(loaded.display.chat.percent(), 120);
        assert!(loaded.keys.slot(1).is_some_and(|slot| slot.cooldown_until > 0));
        crate::storage::set_thread_directory(None);
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn save_and_load_use_the_config_directory() {
        let dir = std::env::temp_dir().join(format!("archx-persist-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        crate::storage::set_thread_directory(Some(dir.clone()));
        let mut settings = PersistedSettings::default();
        settings.display.chat = TextScale::from_percent(115);
        settings.save().expect("save");
        assert_eq!(PersistedSettings::load().map(|loaded| loaded.display.chat.percent()), Some(115));
        assert!(storage::wipe(Area::Settings));
        assert_eq!(PersistedSettings::load(), None);
        crate::storage::set_thread_directory(None);
        let _ = std::fs::remove_dir_all(dir);
    }
}
