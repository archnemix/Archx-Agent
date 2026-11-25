//! Purpose: Saves chat transcripts and model-bound chat metadata so history and empty-chat rules survive a restart.
//!
//! A chat is persisted only once it holds at least one message turn, so an empty
//! "New chat" never accumulates on disk. Transcripts store the visible text and
//! the reasoning text the provider returned; nothing else (no keys, no headers).

use serde_json::{json, Value};

use crate::model_catalog::CatalogModel;
use crate::storage::{self, Area, SaveError};

pub const MAX_CHATS: usize = 200;
pub const MAX_TITLE_CHARS: usize = 80;

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct StoredChat {
    pub id: u32,
    pub title: String,
    pub mode: u8,
    pub model: Option<String>,
    pub updated: u64,
    /// (role, content) pairs; reasoning is stored alongside the assistant turn.
    pub turns: Vec<(String, String, Option<String>)>,
    pub incomplete: Vec<usize>,
}

impl StoredChat {
    pub fn is_empty(&self) -> bool {
        self.turns.is_empty()
    }

    pub fn message_count(&self) -> usize { self.turns.len() }

    /// Title from the first user message, one line, bounded.
    pub fn derived_title(turns: &[(String, String, Option<String>)]) -> String {
        let first = turns.iter().find(|(role, _, _)| role == "user").map(|(_, content, _)| content.as_str()).unwrap_or("");
        let flat: String = first.split_whitespace().collect::<Vec<_>>().join(" ");
        if flat.is_empty() { return "New chat".to_owned(); }
        if flat.chars().count() > MAX_TITLE_CHARS {
            format!("{}…", flat.chars().take(MAX_TITLE_CHARS - 1).collect::<String>())
        } else { flat }
    }

    fn to_json(&self) -> Value {
        json!({
            "id": self.id,
            "title": self.title,
            "mode": self.mode,
            "model": self.model,
            "updated": self.updated,
            "turns": self.turns.iter().map(|(role, content, reasoning)| json!({
                "role": role, "content": content, "reasoning": reasoning,
            })).collect::<Vec<_>>(),
            "incomplete": self.incomplete,
        })
    }

    fn from_json(value: &Value) -> Option<Self> {
        let id = value.get("id").and_then(Value::as_u64).filter(|id| *id > 0 && *id <= u32::MAX as u64)? as u32;
        let mut turns = Vec::new();
        for turn in value.get("turns").and_then(Value::as_array)?.iter().take(400) {
            let role = match turn.get("role").and_then(Value::as_str) { Some("user") => "user", Some("assistant") => "assistant", _ => continue };
            let Some(content) = turn.get("content").and_then(Value::as_str) else { continue };
            let reasoning = turn.get("reasoning").and_then(Value::as_str).map(|text| text.to_owned());
            turns.push((role.to_owned(), content.to_owned(), reasoning));
        }
        Some(Self {
            id,
            title: value.get("title").and_then(Value::as_str).unwrap_or("").chars().take(MAX_TITLE_CHARS).collect(),
            mode: value.get("mode").and_then(Value::as_u64).unwrap_or(0).min(5) as u8,
            model: value.get("model").and_then(Value::as_str).map(|model| model.chars().take(200).collect()),
            updated: value.get("updated").and_then(Value::as_u64).unwrap_or(0),
            turns,
            incomplete: value.get("incomplete").and_then(Value::as_array)
                .map(|slots| slots.iter().filter_map(Value::as_u64).map(|slot| slot as usize).take(400).collect())
                .unwrap_or_default(),
        })
    }
}

/// What `chats.json` holds: transcripts plus each provider's last fetched catalog.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct ChatStore {
    pub chats: Vec<StoredChat>,
    pub catalogs: [Vec<CatalogModel>; crate::credentials::Provider::COUNT],
    pub catalog_fetched: [u64; crate::credentials::Provider::COUNT],
}

impl ChatStore {
    pub fn new() -> Self { Self { chats: Vec::new(), catalogs: std::array::from_fn(|_| Vec::new()), catalog_fetched: [0; crate::credentials::Provider::COUNT] } }

    /// Replaces or inserts one chat; empty chats are never stored.
    pub fn upsert(&mut self, chat: StoredChat) {
        if chat.is_empty() {
            self.chats.retain(|other| other.id != chat.id);
            return;
        }
        match self.chats.iter_mut().find(|other| other.id == chat.id) {
            Some(existing) => *existing = chat,
            None => self.chats.push(chat),
        }
        if self.chats.len() > MAX_CHATS {
            // Drop the oldest by update time, keeping what the user touched last.
            self.chats.sort_by_key(|chat| chat.updated);
            let excess = self.chats.len() - MAX_CHATS;
            self.chats.drain(..excess);
        }
    }

    pub fn get(&self, id: u32) -> Option<&StoredChat> {
        self.chats.iter().find(|chat| chat.id == id)
    }

    pub fn remove(&mut self, id: u32) -> bool {
        let before = self.chats.len();
        self.chats.retain(|chat| chat.id != id);
        self.chats.len() != before
    }

    pub fn newest_first(&self) -> Vec<&StoredChat> {
        let mut chats: Vec<_> = self.chats.iter().collect();
        chats.sort_by(|a, b| b.updated.cmp(&a.updated).then(b.id.cmp(&a.id)));
        chats
    }

    pub fn store_catalog(&mut self, provider: crate::credentials::Provider, models: Vec<CatalogModel>) {
        self.catalogs[provider.index()] = models;
        self.catalog_fetched[provider.index()] = storage::now_secs();
    }

    pub fn age_of_catalog(&self, provider: crate::credentials::Provider) -> Option<u64> {
        let at = self.catalog_fetched[provider.index()];
        (at > 0).then(|| storage::now_secs().saturating_sub(at))
    }

    pub fn to_json(&self) -> Value {
        let mut catalogs = serde_json::Map::new();
        for provider in crate::credentials::Provider::ALL {
            let models = &self.catalogs[provider.index()];
            if models.is_empty() { continue; }
            catalogs.insert(provider.name().into(), json!({
                "fetched": self.catalog_fetched[provider.index()],
                "models": models.iter().map(|model| json!({
                    "id": model.id, "name": model.name, "free": model.free,
                    "router": model.router, "reasoning": model.reasoning,
                })).collect::<Vec<_>>(),
            }));
        }
        // `storage::save` adds the envelope; a second one here would nest it and
        // make the file unreadable.
        json!({
            "chats": self.chats.iter().map(StoredChat::to_json).collect::<Vec<_>>(),
            "catalogs": catalogs,
        })
    }

    pub fn from_json(value: &Value) -> Option<Self> {
        // A bare body and a whole envelope both read, as in `PersistedSettings`.
        let body = storage::body(value).unwrap_or(value);
        let mut store = Self::new();
        for chat in body.get("chats").and_then(Value::as_array)?.iter().take(MAX_CHATS * 2) {
            if let Some(chat) = StoredChat::from_json(chat) {
                if !chat.is_empty() { store.chats.push(chat); }
            }
        }
        if store.chats.len() > MAX_CHATS {
            store.chats.sort_by_key(|chat| chat.updated);
            let excess = store.chats.len() - MAX_CHATS;
            store.chats.drain(..excess);
        }
        if let Some(catalogs) = body.get("catalogs").and_then(Value::as_object) {
            for provider in crate::credentials::Provider::ALL {
                let Some(entry) = catalogs.get(provider.name()) else { continue };
                store.catalog_fetched[provider.index()] = entry.get("fetched").and_then(Value::as_u64).unwrap_or(0);
                if let Some(models) = entry.get("models").and_then(Value::as_array) {
                    store.catalogs[provider.index()] = models.iter().take(8192).filter_map(|model| {
                        let id = model.get("id").and_then(Value::as_str)?;
                        if !crate::provider_api::valid_model(provider, id) { return None; }
                        Some(CatalogModel {
                            id: id.to_owned(),
                            name: model.get("name").and_then(Value::as_str).unwrap_or(id).chars().take(100).collect(),
                            free: model.get("free").and_then(Value::as_bool).unwrap_or(false),
                            router: model.get("router").and_then(Value::as_bool).unwrap_or(false),
                            reasoning: model.get("reasoning").and_then(Value::as_bool).unwrap_or(false),
                        })
                    }).collect();
                }
            }
        }
        Some(store)
    }

    pub fn save(&self) -> Result<(), SaveError> { storage::save(Area::Chats, self.to_json()) }

    pub fn load() -> Option<Self> { Self::from_json(&storage::load_body(Area::Chats)?) }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::credentials::Provider;

    fn chat(id: u32, text: &str, updated: u64) -> StoredChat {
        StoredChat {
            id, title: StoredChat::derived_title(&[("user".into(), text.into(), None)]),
            mode: 0, model: Some("vendor/model".into()), updated,
            turns: vec![("user".into(), text.into(), None), ("assistant".into(), "Answer".into(), Some("Why".into()))],
            incomplete: Vec::new(),
        }
    }

    #[test]
    fn empty_chats_are_never_persisted() {
        let mut store = ChatStore::new();
        store.upsert(StoredChat { id: 4, ..StoredChat::default() });
        assert!(store.chats.is_empty());
        // Removing an existing chat by replacing it with an empty one deletes it.
        store.upsert(chat(1, "hello", 10));
        assert_eq!(store.chats.len(), 1);
        store.upsert(StoredChat { id: 1, ..StoredChat::default() });
        assert!(store.chats.is_empty());
    }

    #[test]
    fn titles_come_from_the_first_user_message_and_stay_bounded() {
        assert_eq!(StoredChat::derived_title(&[]), "New chat");
        assert_eq!(StoredChat::derived_title(&[("assistant".into(), "Hi".into(), None)]), "New chat");
        assert_eq!(StoredChat::derived_title(&[("user".into(), "  Plan\n a   trip ".into(), None)]), "Plan a trip");
        let long = StoredChat::derived_title(&[("user".into(), "word ".repeat(60), None)]);
        assert_eq!(long.chars().count(), MAX_TITLE_CHARS);
        assert!(long.ends_with('…'));
    }

    #[test]
    fn store_round_trips_transcripts_and_reasoning() {
        let mut store = ChatStore::new();
        store.upsert(chat(1, "first question", 100));
        store.upsert(chat(2, "second question", 200));
        let restored = ChatStore::from_json(&store.to_json()).expect("document parses");
        assert_eq!(restored.chats.len(), 2);
        let first = restored.get(1).expect("chat 1");
        assert_eq!(first.title, "first question");
        assert_eq!(first.turns.len(), 2);
        assert_eq!(first.turns[1].2.as_deref(), Some("Why"));
        // Newest first by update time.
        assert_eq!(restored.newest_first()[0].id, 2);
        assert_eq!(storage::credential_field(&store.to_json()), None);
    }

    #[test]
    fn catalogs_survive_a_restart_so_the_models_page_is_not_empty() {
        let mut store = ChatStore::new();
        store.store_catalog(Provider::OpenRouter, vec![
            CatalogModel { id: "vendor/a:free".into(), name: "A".into(), free: true, router: false, reasoning: true },
            CatalogModel { id: "../bad".into(), name: "bad".into(), free: false, router: false, reasoning: false },
        ]);
        let restored = ChatStore::from_json(&store.to_json()).expect("document parses");
        assert_eq!(restored.catalogs[Provider::OpenRouter.index()].len(), 1);
        assert!(restored.catalogs[Provider::OpenRouter.index()][0].reasoning);
        assert!(restored.age_of_catalog(Provider::OpenRouter).is_some());
        assert_eq!(restored.age_of_catalog(Provider::Groq), None);
    }

    #[test]
    fn history_is_bounded_and_removable() {
        let mut store = ChatStore::new();
        for n in 1..=(MAX_CHATS as u32 + 10) {
            store.upsert(chat(n, &format!("question {n}"), u64::from(n)));
        }
        assert_eq!(store.chats.len(), MAX_CHATS);
        // The oldest ten were dropped.
        assert!(store.get(1).is_none());
        assert!(store.get(MAX_CHATS as u32 + 10).is_some());
        assert!(store.remove(MAX_CHATS as u32 + 10));
        assert!(!store.remove(9_999));
    }

    #[test]
    fn hostile_documents_degrade_without_panicking() {
        // No chat list at all is "no history", not a corrupt file.
        assert!(ChatStore::from_json(&json!({"version": 1, "kind": "chats"})).is_some());
        let value = json!({"version": 1, "kind": "chats", "body": {
            "chats": [{"id": 0}, {"id": "x"}, {"id": 1, "turns": [{"role": "system", "content": "no"}]}],
            "catalogs": {"Nope": {"models": []}},
        }});
        let store = ChatStore::from_json(&value).expect("body parses");
        // The id-1 chat has only an unsupported role, so it is empty and dropped.
        assert!(store.chats.is_empty());
    }
}
