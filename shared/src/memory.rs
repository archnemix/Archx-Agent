//! Purpose: Models which of the Agent's in-process caches may stay resident at each stage of the app, and measures them.
//!
//! What this layer can honestly do: it releases or retains data structures the
//! Agent itself owns (parsed chat bodies, fetched catalogs, the metadata cache,
//! the debug journal) and reports their measured retained size. What it cannot
//! do is cap another process's or the OS's RAM, so the UI never claims to.
//!
//! The configuration is a matrix: one keep/drop decision per cache per stage,
//! which is what "what should remain in RAM at what point of the app" means in
//! practice. The launcher has its own copy of the same matrix, and the launcher
//! only ever holds its own (tiny) state.

/// Stages of the app a user can configure for.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stage {
    /// Launcher / Discover screen.
    Launcher,
    /// Agent open, no request in flight.
    AgentIdle,
    /// Agent open with a request streaming.
    ChatActive,
    /// Agent Settings open.
    Settings,
}

impl Stage {
    pub const ALL: [Self; 4] = [Self::Launcher, Self::AgentIdle, Self::ChatActive, Self::Settings];

    pub fn label(self) -> &'static str {
        match self {
            Self::Launcher => "Launcher",
            Self::AgentIdle => "Agent idle",
            Self::ChatActive => "Chat streaming",
            Self::Settings => "Settings open",
        }
    }

    pub fn index(self) -> usize {
        match self { Self::Launcher => 0, Self::AgentIdle => 1, Self::ChatActive => 2, Self::Settings => 3 }
    }

    fn key(self) -> &'static str {
        match self { Self::Launcher => "launcher", Self::AgentIdle => "agent_idle", Self::ChatActive => "chat_active", Self::Settings => "settings" }
    }

    fn from_key(key: &str) -> Option<Self> {
        Self::ALL.into_iter().find(|stage| stage.key() == key)
    }
}

/// Caches the Agent actually holds in RAM.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Item {
    /// Parsed markdown bodies and rendered turns for open chats.
    ChatBodies,
    /// Fetched provider catalogs (re-fetchable from the provider).
    ModelCatalog,
    /// models.dev + free-tier metadata.
    ModelMeta,
    /// The bounded request journal shown on the Debug page.
    DebugJournal,
    /// Resting/rotation state for vault keys (tiny, but listed for completeness).
    KeyHealth,
}

impl Item {
    pub const ALL: [Self; 5] = [Self::ChatBodies, Self::ModelCatalog, Self::ModelMeta, Self::DebugJournal, Self::KeyHealth];

    pub fn label(self) -> &'static str {
        match self {
            Self::ChatBodies => "Parsed chat bodies",
            Self::ModelCatalog => "Fetched model catalogs",
            Self::ModelMeta => "models.dev metadata",
            Self::DebugJournal => "Debug journal",
            Self::KeyHealth => "Key rotation state",
        }
    }

    pub fn detail(self) -> &'static str {
        match self {
            Self::ChatBodies => "Markdown parsed per message. Dropping it re-parses the open chat on demand; nothing is lost.",
            Self::ModelCatalog => "Last fetched ID lists. Dropping it means the next Add-models opening re-fetches.",
            Self::ModelMeta => "Modality, price and free-tier notes. Dropping it keeps the rows bare until the next refresh.",
            Self::DebugJournal => "Request metadata for the last 200 calls. Wiping it removes old requests from the Debug page.",
            Self::KeyHealth => "Which key rests until when. Kept in memory so rotation is instant; it is also on disk.",
        }
    }

    pub fn index(self) -> usize {
        match self { Self::ChatBodies => 0, Self::ModelCatalog => 1, Self::ModelMeta => 2, Self::DebugJournal => 3, Self::KeyHealth => 4 }
    }

    fn key(self) -> &'static str {
        match self {
            Self::ChatBodies => "chat_bodies", Self::ModelCatalog => "model_catalog", Self::ModelMeta => "model_meta",
            Self::DebugJournal => "debug_journal", Self::KeyHealth => "key_health",
        }
    }

    fn from_key(key: &str) -> Option<Self> {
        Self::ALL.into_iter().find(|item| item.key() == key)
    }

    /// The default matrix. Streaming needs the bodies; Settings needs the
    /// catalogs; the launcher keeps nothing of the Agent's.
    fn default_keep(self, stage: Stage) -> bool {
        match (self, stage) {
            (_, Stage::Launcher) => false,
            (Self::ChatBodies, Stage::Settings) => false,
            (Self::ModelCatalog, Stage::AgentIdle | Stage::ChatActive) => false,
            (Self::ModelMeta, _) => true,
            (Self::KeyHealth, _) => true,
            _ => true,
        }
    }
}

/// Keep/drop per (item, stage).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Budget {
    keep: [[bool; 5]; 4],
}

impl Default for Budget {
    fn default() -> Self {
        let mut keep = [[false; 5]; 4];
        for stage in Stage::ALL {
            for item in Item::ALL {
                keep[stage.index()][item.index()] = item.default_keep(stage);
            }
        }
        Self { keep }
    }
}

impl Budget {
    pub fn keeps(&self, stage: Stage, item: Item) -> bool {
        self.keep[stage.index()][item.index()]
    }

    pub fn toggle(&mut self, stage: Stage, item: Item) {
        let slot = &mut self.keep[stage.index()][item.index()];
        *slot = !*slot;
    }

    pub fn set(&mut self, stage: Stage, item: Item, keep: bool) {
        self.keep[stage.index()][item.index()] = keep;
    }

    /// Items that must be released when the app reaches `stage`.
    pub fn release_at(&self, stage: Stage) -> Vec<Item> {
        Item::ALL.into_iter().filter(|item| !self.keeps(stage, *item)).collect()
    }

    pub fn keep_count(&self, stage: Stage) -> usize {
        Item::ALL.into_iter().filter(|item| self.keeps(stage, *item)).count()
    }

    pub fn to_json(&self) -> serde_json::Value {
        let mut map = serde_json::Map::new();
        for stage in Stage::ALL {
            let kept: Vec<&str> = Item::ALL.into_iter().filter(|item| self.keeps(stage, *item)).map(Item::key).collect();
            map.insert(stage.key().into(), serde_json::Value::from(kept));
        }
        serde_json::Value::Object(map)
    }

    pub fn from_json(value: &serde_json::Value) -> Self {
        let mut budget = Self::default();
        let Some(map) = value.as_object() else { return budget };
        for (key, list) in map {
            let Some(stage) = Stage::from_key(key) else { continue };
            let Some(list) = list.as_array() else { continue };
            let kept: Vec<Item> = list.iter().filter_map(|value| value.as_str()).filter_map(Item::from_key).collect();
            for item in Item::ALL {
                budget.set(stage, item, kept.contains(&item));
            }
        }
        budget
    }
}

/// Measured retained size of one cache, for the table.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Usage {
    pub item: Item,
    pub bytes: usize,
    pub entries: usize,
}

impl Usage {
    pub fn label(self) -> String {
        if self.bytes == 0 { return "not loaded".to_owned(); }
        format!("{} · {}", bytes_label(self.bytes), entries_label(self.entries))
    }
}

pub fn bytes_label(bytes: usize) -> String {
    if bytes < 1024 { format!("{bytes} B") }
    else if bytes < 1024 * 1024 { format!("{:.1} KB", bytes as f64 / 1024.0) }
    else { format!("{:.2} MB", bytes as f64 / (1024.0 * 1024.0)) }
}

fn entries_label(entries: usize) -> String {
    if entries == 1 { "1 entry".to_owned() } else { format!("{entries} entries") }
}

/// Sum of everything currently resident.
pub fn resident_total(usage: &[Usage]) -> usize {
    usage.iter().map(|usage| usage.bytes).sum()
}

/// The share a stage would keep, given what is loaded now.
pub fn retained_for(budget: &Budget, stage: Stage, usage: &[Usage]) -> usize {
    usage.iter().filter(|usage| budget.keeps(stage, usage.item)).map(|usage| usage.bytes).sum()
}

/// Rough retained size of a cached string collection (char count as UTF-8 bytes).
pub fn string_bytes(items: impl IntoIterator<Item = usize>) -> usize {
    items.into_iter().sum()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn default_matrix_keeps_what_each_stage_needs_and_drops_the_rest() {
        let budget = Budget::default();
        // The launcher holds none of the Agent's caches.
        assert_eq!(budget.keep_count(Stage::Launcher), 0);
        // Streaming needs the bodies but not a fetched catalog.
        assert!(budget.keeps(Stage::ChatActive, Item::ChatBodies));
        assert!(!budget.keeps(Stage::ChatActive, Item::ModelCatalog));
        // Settings needs catalogs, not parsed chat bodies.
        assert!(budget.keeps(Stage::Settings, Item::ModelCatalog));
        assert!(!budget.keeps(Stage::Settings, Item::ChatBodies));
        // Key rotation state is cheap and always kept inside the Agent.
        assert!(budget.keeps(Stage::AgentIdle, Item::KeyHealth));
        assert_eq!(budget.release_at(Stage::Launcher), Item::ALL.to_vec());
    }

    #[test]
    fn measured_usage_reports_bytes_and_entries() {
        assert_eq!(Usage { item: Item::DebugJournal, bytes: 0, entries: 0 }.label(), "not loaded");
        assert_eq!(Usage { item: Item::DebugJournal, bytes: 2_048, entries: 200 }.label(), "2.0 KB · 200 entries");
        assert_eq!(Usage { item: Item::ChatBodies, bytes: 900, entries: 1 }.label(), "900 B · 1 entry");
        assert_eq!(bytes_label(3 * 1024 * 1024), "3.00 MB");
        let usage = vec![
            Usage { item: Item::ChatBodies, bytes: 1_000, entries: 4 },
            Usage { item: Item::ModelCatalog, bytes: 2_000, entries: 400 },
        ];
        assert_eq!(resident_total(&usage), 3_000);
        // At Settings, only the catalog counts as retained.
        assert_eq!(retained_for(&Budget::default(), Stage::Settings, &usage), 2_000);
        assert_eq!(retained_for(&Budget::default(), Stage::Launcher, &usage), 0);
    }

    #[test]
    fn toggles_are_per_stage_and_round_trip_through_json() {
        let mut budget = Budget::default();
        budget.toggle(Stage::Settings, Item::ChatBodies);
        assert!(budget.keeps(Stage::Settings, Item::ChatBodies));
        assert!(!budget.keeps(Stage::AgentIdle, Item::ChatBodies) == false);
        let restored = Budget::from_json(&budget.to_json());
        assert_eq!(restored, budget);
        // A document naming only some stages leaves the rest at their defaults.
        let partial = Budget::from_json(&json!({ "settings": ["chat_bodies"] }));
        assert!(partial.keeps(Stage::Settings, Item::ChatBodies));
        assert!(!partial.keeps(Stage::Settings, Item::ModelCatalog));
        assert!(partial.keeps(Stage::ChatActive, Item::ChatBodies));
        // Unknown keys and values are ignored rather than panicking.
        assert_eq!(Budget::from_json(&json!({"nope": ["x"], "settings": "bad"})), Budget::default());
    }
}
