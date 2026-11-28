//! Purpose: Owns the Agent's page state (chat surface, settings, debug), persistence, key rotation and request journal.
//!
//! This is the app-level state machine. The launcher owns navigation between
//! apps and launcher-only settings; everything below belongs to Archx Agent:
//!   * chat drafts, transcripts saved to `chats.json`, and the rule that an empty
//!     chat is never persisted or created twice;
//!   * provider/model configuration persisted to `settings.json` (no secrets);
//!   * round-robin key rotation with rest windows (`health`), model auto-disable;
//!   * a bounded request journal (`debug_log`) behind the Debug page;
//!   * per-area text scale and reasoning-panel preferences.

use std::collections::HashSet;
use std::path::PathBuf;
use std::time::{Duration, Instant};

use iced::time;
use iced::task::sipper;
use iced::window;
use iced::widget::{markdown, text_editor};
use iced::{Element, Subscription, Task};
use zeroize::Zeroizing;

use archx_shared::credentials::{Provider, Vault, VaultError};
use archx_shared::diagnostics::{self, Diagnosis};
use archx_shared::health::{KeyHealthSet, ModelHealthSet};
use archx_shared::model_catalog::CatalogModel;
use archx_shared::persist::{DisplaySettings, PersistedSettings};
use archx_shared::provider_api::{Failure, Reply, Turn};
use archx_shared::{debug_log, endpoints, model_catalog, model_meta, provider_api, storage, transcripts};
use archx_shared::transcripts::{ChatStore, StoredChat};
use crate::custom_endpoint;
use crate::settings::{SecretText, Section, SettingsState};
use crate::{agent, debug_page, home, settings};

/// The Agent's own surfaces. The launcher decides which one is shown.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Page {
    Chat,
    Settings,
    Debug,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MemoryMode {
    Light,
    Heavy,
    Custom,
}

/// The output ceiling this Agent requests for a chat reply.
///
/// It is a request parameter, not a provider limit, so the number belongs here
/// rather than being repeated at every call site. When a reply stops at this
/// ceiling the provider says so with a normal 200 and a `finish_reason` of
/// `length`; that is now surfaced as an explicit truncation instead of a
/// silent half-answer.
pub const CHAT_OUTPUT_TOKENS: u32 = 4096;
/// The small ceiling a catalog probe uses. A probe only needs a word back.
pub const TEST_OUTPUT_TOKENS: u32 = 256;

/// One open chat. Empty chats exist in memory but are never saved.
pub struct ChatDraft {
    pub id: u32,
    pub mode: u8,
    pub text: String,
    pub editor: text_editor::Content,
    /// Rendered turns: slot, parsed body, **raw** reasoning (plain text, as the
    /// reference renders it) and whether its panel starts open.
    pub formatted: Vec<(usize, markdown::Content, Option<String>, bool)>,
    /// Streaming snapshot: parsed body and the raw reasoning text so far.
    pub partial: Option<(markdown::Content, Option<String>)>,
    pub partial_raw: Option<Reply>,
    pub partial_reasoning_open: bool,
    pub partial_reasoning_touched: bool,
    pub incomplete_slots: Vec<usize>,
    /// Turns whose reply stopped at our output ceiling. Kept apart from
    /// `incomplete_slots` because the cause differs: one was interrupted, this
    /// one arrived whole and simply ran out of room.
    pub cut_off_slots: Vec<usize>,
    pub request_handle: Option<iced::task::Handle>,
    pub turns: Vec<Turn>,
    /// Reasoning text for each turn, parallel to `turns` (empty when none).
    pub reasoning: Vec<Option<String>>,
    /// The model this chat was started with, so a later restart keeps context.
    pub model: Option<String>,
    pub busy: bool,
    pub follow_tail: bool,
    pub error: Option<String>,
    /// The most recent failure, for the Debug page and the error notice.
    pub diagnosis: Option<Diagnosis>,
    pub last_viewed: u64,
}

impl ChatDraft {
    pub fn new(id: u32) -> Self {
        Self {
            id, mode: 0, text: String::new(), editor: text_editor::Content::new(),
            formatted: Vec::new(), partial: None, partial_raw: None,
            partial_reasoning_open: true, partial_reasoning_touched: false,
            incomplete_slots: Vec::new(), cut_off_slots: Vec::new(), request_handle: None, turns: Vec::new(),
            reasoning: Vec::new(), model: None, busy: false, follow_tail: true,
            error: None, diagnosis: None, last_viewed: 0,
        }
    }

    /// An empty draft: no turns and no typed text. The "New chat" rule uses this.
    pub fn is_empty(&self) -> bool {
        self.turns.is_empty() && self.text.trim().is_empty()
    }

    pub fn has_messages(&self) -> bool { !self.turns.is_empty() }

    pub fn title(&self) -> String {
        let turns: Vec<(String, String, Option<String>)> = self.turns.iter().enumerate()
            .map(|(slot, turn)| (turn.role.to_owned(), turn.content.clone(), self.reasoning.get(slot).cloned().flatten()))
            .collect();
        StoredChat::derived_title(&turns)
    }

    pub(crate) fn to_stored(&self, model: Option<String>) -> StoredChat {
        StoredChat {
            id: self.id,
            title: self.title(),
            mode: self.mode,
            model: model.or_else(|| self.model.clone()),
            updated: storage::now_secs(),
            turns: self.turns.iter().enumerate()
                .map(|(slot, turn)| (turn.role.to_owned(), turn.content.clone(), self.reasoning.get(slot).cloned().flatten()))
                .collect(),
            incomplete: self.incomplete_slots.clone(),
            cut_off: self.cut_off_slots.clone(),
        }
    }
}

#[derive(Clone)]
pub struct SecretReply(pub Reply);
impl std::fmt::Debug for SecretReply {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result { f.write_str("[redacted reply]") }
}

#[derive(Clone)]
pub struct EditorAction(pub text_editor::Action);
impl std::fmt::Debug for EditorAction {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result { f.write_str("[redacted editor action]") }
}

/// A finished debug-journal write.
#[derive(Debug, Clone)]
pub struct Finished {
    pub id: u64,
    pub key_id: u64,
    pub model: String,
    pub duration_ms: u128,
    pub outcome: Result<(usize, usize, usize), (Diagnosis, String)>,
}

#[derive(Debug, Clone)]
pub enum Message {
    // Navigation inside the Agent.
    Open(Page),
    /// Ask the launcher to return to its own Discover screen.
    BackToLauncher,
    // Chat chrome.
    ToggleSidebar,
    NewChat,
    OpenChat(u32),
    DeleteChat(u32),
    SelectMode(u8),
    EditDraft(u32, SecretText),
    EditEditor(u32, EditorAction),
    ClearDraft(u32),
    SendChat,
    StopChat,
    ChatResult(u32, Result<SecretReply, Box<Failure>>),
    AttemptDone(u32, bool, Box<AttemptOutcome>),
    AttemptFailed(u32, bool, Box<Failure>, usize, u64),
    ChatProgress(u32, SecretReply),
    ChatScrolled(u32, bool),
    JumpToLatest,
    ToggleReasoning(u32, usize),
    ToggleStreaming,
    ToggleReasoningDefault,
    ToggleModelMenu,
    ToggleModeMenu,
    SearchChatModels(String),
    IgnoreMarkdownLink,
    CopyCode(SecretText),
    // Provider and keys.
    SelectProvider(Provider),
    OpenProviderPicker,
    CloseProviderPicker,
    EditKey(SecretText),
    SaveKey,
    KeySaved(Provider, Result<u64, VaultError>),
    RefreshKeys,
    KeysLoaded(Provider, Result<Vec<u64>, VaultError>),
    RemoveKey(u64),
    KeyRemoved(Provider, Result<(), VaultError>),
    RevealKey(u64),
    HideKey,
    KeyRevealed(u64, u64, Result<SecretText, VaultError>),
    RevealExpired(u64),
    ToggleAutoRotate,
    RetryKeyNow(u64),
    /// Read what the provider publishes about a key's remaining usage.
    FetchKeyUsage,
    KeyUsageRead(u64, Result<Option<archx_shared::usage::KeyUsage>, String>),
    // Endpoints.
    EditEndpoint(endpoints::Kind, String),
    SaveEndpoint(endpoints::Kind),
    ResetEndpoint(endpoints::Kind),
    // Models.
    EditModel(String),
    AddModel,
    ChooseModel(usize),
    RemoveModel(usize),
    ToggleModelEnabled(String),
    EnableAllModels,
    BulkSelect(usize, bool),
    BulkSelectMatching,
    BulkClearSelection,
    BulkRunSelected,
    BulkRemoveSelected,
    BulkDisableSelected,
    BulkEnableSelected,
    ModelPageNext,
    ModelPagePrevious,
    FetchModels,
    ModelsFetched(Provider, u64, Result<Vec<CatalogModel>, String>),
    FetchModelMeta,
    ModelMetaFetched(Result<usize, String>),
    /// Compare the added models against the provider's live `/models` list and
    /// cached models.dev metadata; data-dependent part done, nothing disabled yet.
    SweepModels,
    /// The live `/models` list has arrived, or `Err` when the provider could
    /// not be asked — in which case only models.dev is used.
    SweepChecked(Provider, u64, Result<Vec<String>, String>),
    SweepApply,
    SweepUndo,
    SweepDismiss,
    SearchModels(String),
    ToggleAutoDisable,
    // Runtime-memory matrix and display scale (Settings → Runtime / Storage).
    ToggleRuntime(archx_shared::memory::Stage, archx_shared::memory::Item),
    ScaleIn(Area),
    ScaleOut(Area),
    ScaleReset(Area),
    MeasureWider,
    MeasureNarrower,
    // Settings sections.
    SettingsSection(Section),
    MemoryPreview(MemoryMode),
    ToggleAgentPreview,
    LauncherScope(MemoryScope),
    // Catalog dialog and probes.
    OpenCatalogModal,
    CloseCatalogModal,
    CatalogNext,
    CatalogPrevious,
    ToggleCatalogSelection(Provider, usize),
    SelectMatchingModels,
    ClearCatalogSelection,
    ToggleCatalogVerified,
    StageCatalogId,
    ImportSelectedModels,
    RequestCatalogProbe,
    CancelCatalogProbe,
    ConfirmCatalogProbe,
    CatalogProbeProgress(Provider, u64, String, Result<(SecretText, u128), String>),
    CatalogProbeDone(Provider, u64, Result<(), String>),
    DismissProbeResults,
    // Custom endpoint.
    CustomUrl(String),
    CustomHeaders(SecretText),
    CustomBody(String),
    CustomAnswer(String),
    CustomDelta(String),
    CustomStream,
    CustomCurl(SecretText),
    ImportCustomCurl,
    ApproveCustom,
    CustomOpenAiPreset,
    CustomAnthropicPreset,
    // Tests.
    RunTest,
    TestResult(Result<SecretText, String>),
    ExpectedWord(String),
    // Debug page.
    DebugFilter(debug_log::Filter),
    DebugSelect(u64),
    DebugRefresh,
    DebugExport,
    DebugWipe,
    // Storage.
    WipeArea(storage::Area),
    WipeEverything,
    Notice(String),
    DismissNotice,
    // Animation / screenshots.
    AgentPulse,
    Tick,
    SnapshotTick,
    SnapshotReady(window::screenshot::Screenshot),
}

/// Which area of the interface a scale control affects.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Area {
    Chat,
    Settings,
    Launcher,
}

/// Memory scope handed down by the launcher.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MemoryScope {
    Light,
    Balanced,
    Heavy,
    Custom,
}

impl MemoryScope {
    pub fn mode(self) -> MemoryMode {
        match self {
            Self::Light => MemoryMode::Light,
            Self::Heavy | Self::Balanced => MemoryMode::Heavy,
            Self::Custom => MemoryMode::Custom,
        }
    }
}

pub struct App {
    pub page: Page,
    pub sidebar_expanded: bool,
    pub drafts: Vec<ChatDraft>,
    pub selected_draft: u32,
    pub(crate) next_chat_id: u32,
    pub model_menu_open: bool,
    pub mode_menu_open: bool,
    pub chat_model_search: String,
    pub memory_preview: MemoryMode,
    pub keep_agent_preview: bool,
    pub settings: SettingsState,
    pub keys: KeyHealthSet,
    pub model_health: ModelHealthSet,
    /// Picks one key per request; the launcher hands it nothing else.
    pub store: ChatStore,
    pub journal: debug_log::Journal,
    pub journal_filter: debug_log::Filter,
    pub endpoints: endpoints::Registry,
    /// An endpoint row being edited, before Save validates it.
    pub endpoint_draft: Option<(endpoints::Kind, String)>,
    /// The last explicit probe run's handle, so Stop can abort it.
    pub probe_handle: Option<iced::task::Handle>,
    pub display: DisplaySettings,
    pub meta: Option<model_meta::Registry>,
    pub meta_checked: Option<u64>,
    /// Whether the launcher's Agent page is the one being shown.
    pub visible: bool,
    /// Launcher-provided memory scope.
    pub scope: MemoryScope,
    /// Which caches stay resident at each stage (Runtime page).
    pub memory_budget: archx_shared::memory::Budget,
    pub notice: Option<String>,
    pub storage_path: String,
    pub debug_selected: Option<u64>,
    pub reasoning_open_default: bool,
    pub(crate) agent_phase: u8,
    pub(crate) snapshot: Option<PathBuf>,
    pub(crate) snapshot_requested: bool,
    pub(crate) snapshot_scrolled: bool,
    pub(crate) snapshot_chat: Option<String>,
    pub(crate) frozen_snapshot_phase: bool,
    pub hovered: bool,
    /// Measured cache sizes shown on the Runtime page.
    pub memory_usage: Vec<archx_shared::memory::Usage>,
    /// Set when the user pressed "Back to launcher" (read by the launcher).
    pub left_for_launcher: bool,
    /// True while a screenshot run pins the surface.
    snapshot_setup: bool,
}

impl App {
    pub fn new(persisted: Option<PersistedSettings>) -> Self {
        let snapshot = std::env::var_os("ARCHX_SNAPSHOT").map(PathBuf::from);
        let store = ChatStore::load().unwrap_or_default();
        let persisted = persisted.filter(|_| snapshot.is_none()).unwrap_or_default();
        let mut settings = SettingsState::default();
        settings.provider = persisted.provider;
        settings.models = persisted.models;
        settings.chosen = persisted.chosen;
        settings.stream_chat = persisted.stream_chat;
        settings.custom.url = persisted.custom_url;
        let mut drafts: Vec<ChatDraft> = Vec::new();
        if snapshot.is_none() {
            // Restore saved conversations, newest first is display order (the
            // rail reverses). An empty saved chat cannot exist: `upsert` drops it.
            for chat in store.chats.clone() {
                let mut draft = ChatDraft::new(chat.id);
                draft.mode = chat.mode;
                draft.model = chat.model.clone();
                draft.incomplete_slots = chat.incomplete.clone();
                draft.cut_off_slots = chat.cut_off.clone();
                draft.reasoning = chat.turns.iter().map(|(_, _, reasoning)| reasoning.clone()).collect();
                draft.turns = chat.turns.iter().map(|(role, content, _)| Turn {
                    role: if role == "user" { "user" } else { "assistant" },
                    content: content.clone(),
                }).collect();
                draft.formatted = draft.turns.iter().enumerate().filter_map(|(slot, turn)| {
                    if turn.role == "assistant" {
                        Some((slot, markdown::Content::parse(&turn.content),
                            draft.reasoning.get(slot).cloned().flatten(),
                            false))
                    } else { None }
                }).collect();
                drafts.push(draft);
            }
        }
        if drafts.is_empty() { drafts.push(ChatDraft::new(1)); }
        let next_chat_id = drafts.iter().map(|draft| draft.id).max().unwrap_or(0) + 1;
        let selected_draft = drafts.last().map_or(1, |draft| draft.id);

        let mut app = Self {
            page: Page::Chat,
            sidebar_expanded: !(snapshot.is_some()
                && std::env::var("ARCHX_SNAPSHOT_SIDEBAR").as_deref() == Ok("collapsed")),
            drafts,
            selected_draft,
            next_chat_id,
            model_menu_open: false,
            mode_menu_open: false,
            chat_model_search: String::new(),
            memory_preview: MemoryMode::Light,
            keep_agent_preview: false,
            settings,
            keys: persisted.keys,
            model_health: persisted.model_health,
            store,
            journal: debug_log::Journal::from_json(&storage::load_body(storage::Area::Debug)
                .unwrap_or(serde_json::Value::Null)),
            journal_filter: debug_log::Filter::All,
            endpoints: persisted.endpoints,
            endpoint_draft: None,
            probe_handle: None,
            display: persisted.display,
            meta: model_meta::load_cache().map(|(registry, _)| registry),
            meta_checked: model_meta::load_cache().map(|(_, at)| at),
            notice: None,
            storage_path: storage::display_path(),
            debug_selected: None,
            reasoning_open_default: false,
            visible: false,
            scope: MemoryScope::Balanced,
            memory_budget: archx_shared::memory::Budget::default(),
            agent_phase: 0,
            snapshot,
            snapshot_requested: false,
            snapshot_scrolled: false,
            snapshot_chat: std::env::var("ARCHX_SNAPSHOT_CHAT").ok(),
            frozen_snapshot_phase: false,
            hovered: false,
            memory_usage: Vec::new(),
            left_for_launcher: false,
            snapshot_setup: false,
        };
        app.load_probe_results();
        app
    }

    /// ---- scripted screenshot fixtures -------------------------------------
    // These run only when `ARCHX_SNAPSHOT` is set. A normal launch never reaches
    // them: `prepare_snapshot` returns early otherwise.

    fn activate_mode(&mut self, mode: u8) {
        if let Some(draft) = self.current_mut() { draft.mode = mode; }
        self.mode_menu_open = false;
    }

    fn set_draft_text(&mut self, text: &str) {
        if let Some(draft) = self.current_mut() {
            draft.text = text.to_owned();
            draft.editor = text_editor::Content::with_text(text);
        }
    }

    fn load_snapshot_section(&mut self) {
        let which = std::env::var("ARCHX_SNAPSHOT_SETTINGS").unwrap_or_default();
        self.settings.section = match which.as_str() {
            "models" | "import-review" | "import-verified-review" | "sweep-review" => Section::Models,
            _ if self.memory_preview == MemoryMode::Custom => Section::Runtime,
            "runtime" => Section::Runtime,
            "storage" => Section::Storage,
            "lab" => Section::Lab,
            _ => Section::Providers,
        };
        match which.as_str() {
            "custom-review" => {
                self.settings.provider = Provider::Custom;
                self.settings.custom.url = "https://example.invalid/v1/chat/completions".into();
                self.settings.custom.headers = "Authorization: Bearer {{api_key}}".to_owned().into();
                self.settings.status = "Synthetic fixture: no request was sent and no destination was approved.".into();
            }
            // Synthetic sweep fixture: one model the live list dropped, one
            // models.dev marks retired, one nobody knows, one still listed.
            // No request was sent; every string here is invented.
            "sweep-review" => {
                let index = self.settings.index();
                self.settings.models[index] = vec![
                    "demo/still-listed".into(), "demo/dropped".into(),
                    "demo/retired".into(), "demo/hand-typed-private".into(),
                ];
                self.settings.chosen[index] = Some(3);
                self.model_health.sync(&self.settings.models[index]);
                self.settings.meta = Some(archx_shared::model_meta::parse_models_dev(&serde_json::json!({
                    "openrouter": {"models": {
                        "demo/still-listed": {"type": "chat", "status": "beta"},
                        "demo/dropped": {"type": "chat"},
                        "demo/retired": {"type": "chat", "status": "deprecated"}
                    }}
                })));
                let live = vec!["demo/still-listed".to_owned(), "demo/retired".to_owned()];
                self.settings.sweep = Some(archx_shared::model_meta::sweep(
                    Provider::OpenRouter, &self.settings.models[index], Some(&live),
                    self.settings.meta.as_ref()));
                self.settings.status = "Synthetic sweep fixture: no request was sent.".into();
            }
            "import-review" | "import-verified-review" => {
                let index = self.settings.index();
                self.settings.catalog[index] = vec![
                    CatalogModel { id: "vendor/alpha:free".into(), name: "Alpha".into(), free: true, router: false, reasoning: false },
                    CatalogModel { id: "vendor/beta".into(), name: "Beta".into(), free: false, router: false, reasoning: true },
                    CatalogModel { id: "vendor/gamma".into(), name: "Gamma".into(), free: false, router: false, reasoning: false },
                ];
                self.settings.probe_results = vec![
                    ("vendor/beta".into(), true, "OK".into()),
                    ("vendor/gamma".into(), false, "HTTP 429 · account quota exceeded".into()),
                ];
                self.settings.catalog_modal = true;
                self.settings.catalog_selected[index] = vec!["vendor/beta".into()];
                if which == "import-verified-review" {
                    self.settings.catalog_only_verified = true;
                    self.settings.catalog_selected[index].push("vendor/gamma".into());
                }
            }
            _ => {}
        }
    }

    fn load_snapshot_conversation(&mut self) {
        let which = std::env::var("ARCHX_SNAPSHOT_CHAT").unwrap_or_default();
        let index = Provider::OpenRouter.index();
        match which.as_str() {
            "reasoning" | "model-menu" | "review" => {
                self.settings.provider = Provider::OpenRouter;
                self.settings.models[index] = vec!["demo/model:free".into(), "demo/another".into()];
                self.settings.chosen[index] = Some(0);
                self.model_health.sync(&self.settings.models[index]);
                self.model_menu_open = which == "model-menu";
                if which != "model-menu" {
                    let content = if which == "review" {
                        "# Server-sent events\n\nSSE keeps one HTTP response open and delivers updates as they arrive.\n\n```javascript\nconst source = new EventSource('/events');\nsource.onmessage = (event) => console.log(event.data);\n```\n\n| Feature | SSE | Polling |\n| :--- | :--- | :--- |\n| Connection | Persistent | Repeated requests |\n| Direction | Server to client | Request/response |"
                    } else {
                        "## Example\n\nA **bold** answer with `code`.\n\n- First item\n- Second item"
                    };
                    let reasoning = "The provider returned this synthetic reasoning content. It is collapsed unless the user opens it.";
                    self.set_fixture_chat(content, Some(reasoning), which == "review");
                }
            }
            // A reply that stopped at the Agent's own output ceiling. This
            // fixture exists so the marker is seen in a screenshot rather than
            // only asserted in a test.
            "cut-off" => {
                self.settings.provider = Provider::OpenRouter;
                self.settings.models[index] = vec!["demo/output-capped".into()];
                self.settings.chosen[index] = Some(0);
                self.model_health.sync(&self.settings.models[index]);
                let id = self.selected_draft;
                if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == id) {
                    let body = "An event stream is opened once and the server keeps writing to it, so the browser sees each update as it happens instead of asking again. The trade-off is that the connection has to stay open";
                    draft.turns = vec![
                        Turn { role: "user", content: "Explain SSE streaming in detail".into() },
                        Turn { role: "assistant", content: body.into() },
                    ];
                    draft.reasoning = vec![None, None];
                    draft.formatted = vec![(1, markdown::Content::parse(body), None, false)];
                    draft.cut_off_slots.push(1);
                    draft.incomplete_slots.push(1);
                    let diagnosis = archx_shared::diagnostics::output_capped(CHAT_OUTPUT_TOKENS);
                    draft.error = Some(diagnosis.summary.clone());
                    draft.diagnosis = Some(diagnosis);
                }
            }
            "conversation-review" => {
                self.settings.provider = Provider::OpenRouter;
                self.settings.models[index] = vec!["demo/review-model".into()];
                self.settings.chosen[index] = Some(0);
                self.model_health.sync(&self.settings.models[index]);
                let turns = [
                    ("user", "Hi! How are you? Also explain how SSE streaming works."),
                    ("assistant", "I'm here to help. SSE keeps one HTTP response open while the server sends updates as they happen."),
                    ("user", "Can you show JavaScript and compare SSE with polling?"),
                    ("assistant", "## How SSE works\n\nA browser opens an `EventSource` and reads updates as they arrive. Unlike polling, the connection stays open.\n\n```javascript\nconst source = new EventSource('/events');\nsource.onmessage = (event) => console.log(event.data);\n```\n\n| Feature | SSE | Polling |\n| :--- | :--- | :--- |\n| Connection | Persistent | Repeated requests |\n| Direction | Server to client | Request/response |"),
                ];
                let id = self.selected_draft;
                if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == id) {
                    draft.turns = turns.iter().map(|(role, content)| Turn { role, content: (*content).into() }).collect();
                    draft.reasoning = vec![None, None, None,
                        Some("The user asked for a JavaScript example and a comparison. Explain the open connection and keep the code and table focused on that question.".into())];
                    draft.formatted = vec![
                        (1, markdown::Content::parse(turns[1].1), None, false),
                        (3, markdown::Content::parse(turns[3].1), draft.reasoning[3].clone(), true),
                    ];
                }
            }
            _ => {}
        }
    }

    fn set_fixture_chat(&mut self, content: &str, reasoning: Option<&str>, open: bool) {
        let id = self.selected_draft;
        if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == id) {
            draft.turns = vec![
                Turn { role: "user", content: "Show a short example".into() },
                Turn { role: "assistant", content: content.into() },
            ];
            draft.reasoning = vec![None, reasoning.map(str::to_owned)];
            draft.formatted = vec![(1, markdown::Content::parse(content), reasoning.map(str::to_owned), open)];
            draft.follow_tail = true;
        }
    }

    /// Called by the launcher when the Agent becomes visible, with the
    /// launcher's own surface id: "agent", "settings" or "debug".
    pub fn enter_surface(&mut self, surface: &str) {
        self.visible = true;
        self.page = match surface {
            "settings" => Page::Settings,
            "debug" => Page::Debug,
            _ => Page::Chat,
        };
    }

    /// Called by the launcher when the user leaves the Agent entirely.
    pub fn leave_app(&mut self) -> Task<Message> {
        let active: Vec<u32> = self.drafts.iter_mut().filter(|draft| draft.busy).map(|draft| {
            if let Some(handle) = draft.request_handle.take() { handle.abort(); }
            draft.id
        }).collect();
        for id in active {
            let _ = self.update(Message::ChatResult(id,
                Err(Box::new(Failure::from(provider_api::CallError::Transport)))));
        }
        self.settings.clear_secret();
        self.model_menu_open = false;
        self.mode_menu_open = false;
        self.settings.provider_picker = false;
        self.persist_now();
        Task::none()
    }

    /// Saves only the display preferences (the launcher owns its own controls).
    pub fn save_display(&mut self, display: DisplaySettings) -> Option<String> {
        self.display = display;
        self.persist_settings().err().map(|error| error.message())
    }

    /// Writes the launcher's own document. The launcher holds the file, but only
    /// this app knows how to write `settings.json`: the four `Area` files belong
    /// to the Agent, and a second writer would race the first. So the launcher
    /// hands over its state and the existing, tested writer does the work.
    ///
    /// Only the launcher's own fields move; the Agent's settings, health and
    /// budgets are read from the file as they are and written back untouched.
    pub fn save_launcher(&mut self, display: DisplaySettings, launcher_budget: archx_shared::memory::Budget) -> Option<String> {
        self.display = display;
        let on_disk = archx_shared::persist::PersistedSettings::load();
        let agent_budget = on_disk.as_ref().map(|settings| settings.budget.clone()).unwrap_or_default();
        let mut document = self.settings_document();
        // `settings_document` reflects the Agent's in-memory state, which is the
        // authority for the Agent's own fields. The launcher's two fields are the
        // only things replaced here.
        document.display = display;
        document.launcher_budget = launcher_budget;
        document.budget = agent_budget;
        document.save().err().map(|error| error.message())
    }

    /// Screenshot runs set the page directly and skip the restored transcripts.
    /// The launcher passes its own surface id ("agent", "settings", "debug") so
    /// the app never needs to name the launcher's page enum.
    pub fn prepare_snapshot(&mut self, surface: &str) {
        if self.snapshot.is_none() { return; }
        self.snapshot_setup = true;
        self.page = match surface {
            "settings" => Page::Settings,
            "debug" => Page::Debug,
            _ => Page::Chat,
        };
        if self.snapshot_chat.as_deref() == Some("debug") { self.page = Page::Debug; }
        if std::env::var("ARCHX_SNAPSHOT_MEMORY").as_deref() == Ok("custom") {
            self.memory_preview = MemoryMode::Custom;
            self.memory_budget = archx_shared::memory::Budget::default();
        }
        if self.page == Page::Chat {
            if let Ok(mode) = std::env::var("ARCHX_SNAPSHOT_MODE") {
                if let Ok(mode) = mode.parse::<u8>() { self.activate_mode(mode); }
            }
            if let Ok(draft) = std::env::var("ARCHX_SNAPSHOT_DRAFT") {
                if !draft.is_empty() { self.set_draft_text(&draft); }
            }
        }
        if self.page == Page::Settings { self.load_snapshot_section(); }
        if matches!(self.snapshot_chat.as_deref(), Some("reasoning" | "model-menu" | "review" | "conversation-review")) {
            self.load_snapshot_conversation();
        }
    }

    /// Screenshot plumbing: the page to render is chosen by the launcher.
    pub fn set_page(&mut self, page: Page) {
        self.page = page;
        self.snapshot_setup = true;
    }

    // ----------------------------------------------------------------- state

    pub(crate) fn scale(&mut self, area: Area, larger: bool) {
        self.display = match (area, larger) {
            (Area::Chat, true) => DisplaySettings { chat: self.display.chat.larger(), ..self.display },
            (Area::Chat, false) => DisplaySettings { chat: self.display.chat.smaller(), ..self.display },
            (Area::Settings, true) => DisplaySettings { settings: self.display.settings.larger(), ..self.display },
            (Area::Settings, false) => DisplaySettings { settings: self.display.settings.smaller(), ..self.display },
            (Area::Launcher, true) => DisplaySettings { launcher: self.display.launcher.larger(), ..self.display },
            (Area::Launcher, false) => DisplaySettings { launcher: self.display.launcher.smaller(), ..self.display },
        };
        let _ = self.persist_settings();
    }

    /// Actually drops the data a "drop" decision names, and records honest sizes.
    pub fn release(&mut self, item: archx_shared::memory::Item) {
        match item {
            archx_shared::memory::Item::ChatBodies => {
                // Parsed bodies are rebuilt from the turns on the next view; the
                // transcript text itself is never dropped.
                for draft in &mut self.drafts { draft.formatted.clear(); }
            }
            archx_shared::memory::Item::ModelCatalog => {
                self.store.catalogs = std::array::from_fn(|_| Vec::new());
                self.store.catalog_fetched = [0; Provider::COUNT];
            }
            archx_shared::memory::Item::ModelMeta => { self.meta = None; }
            archx_shared::memory::Item::DebugJournal => { self.journal.clear(); }
            archx_shared::memory::Item::KeyHealth => { /* rotation state is a few bytes; kept */ }
        }
        self.refresh_usage();
    }

    /// Re-measures what the process currently holds.
    pub fn refresh_usage(&mut self) {
        use archx_shared::memory::{Item, Usage};
        let bodies: usize = self.drafts.iter()
            .flat_map(|draft| draft.turns.iter())
            .map(|turn| turn.content.len()).sum();
        let body_entries: usize = self.drafts.iter().map(|draft| draft.turns.len()).sum();
        let catalogs: usize = self.store.catalogs.iter().flat_map(|models| models.iter()).map(|model| model.id.len() + model.name.len()).sum();
        let catalog_entries: usize = self.store.catalogs.iter().map(Vec::len).sum();
        let meta_entries = self.meta.as_ref().map_or(0, |registry| registry.len());
        let journal_bytes: usize = self.journal.entries().iter()
            .map(|entry| entry.model.len() + entry.detail.len() + std::mem::size_of::<debug_log::Entry>()).sum();
        let key_bytes = self.keys.slots.len() * std::mem::size_of::<archx_shared::health::KeySlot>();
        self.memory_usage = vec![
            Usage { item: Item::ChatBodies, bytes: bodies, entries: body_entries },
            Usage { item: Item::ModelCatalog, bytes: catalogs, entries: catalog_entries },
            Usage { item: Item::ModelMeta, bytes: meta_entries * 96, entries: meta_entries },
            Usage { item: Item::DebugJournal, bytes: journal_bytes, entries: self.journal.entries().len() },
            Usage { item: Item::KeyHealth, bytes: key_bytes, entries: self.keys.slots.len() },
        ];
    }

    fn current(&self) -> Option<&ChatDraft> {
        self.drafts.iter().find(|draft| draft.id == self.selected_draft)
    }

    fn current_mut(&mut self) -> Option<&mut ChatDraft> {
        self.drafts.iter_mut().find(|draft| draft.id == self.selected_draft)
    }

    pub fn selected_model(&self) -> Option<&str> {
        self.settings.selected_model().filter(|model| self.model_health.is_enabled(model))
    }

    pub fn connected(&self) -> bool { self.settings.selected_model().is_some() }

    /// Artwork phase for the launcher tiles (cycles a few times a minute).
    pub fn phase(&self) -> u8 { self.agent_phase }

    /// True when this run is a deterministic screenshot capture.
    pub fn snapshot_active(&self) -> bool { self.snapshot.is_some() }

    /// The app's view entry (the launcher hosts it).
    pub fn view(&self) -> Element<'_, Message> { crate::home::view(self) }

    /// Drafts that hold at least one message: what the rail lists.
    pub fn saved_drafts(&self) -> impl Iterator<Item = &ChatDraft> {
        self.drafts.iter().filter(|draft| draft.has_messages())
    }

    fn blank_draft(&self) -> Option<&ChatDraft> {
        self.drafts.iter().find(|draft| draft.is_empty() && !draft.busy)
    }

    pub fn update(&mut self, message: Message) -> Task<Message> {
        // The launcher watches for this one and switches back to Discover.
        self.left_for_launcher = false;
        match message {
            Message::BackToLauncher => {
                if self.snapshot.is_some() { return Task::none(); }
                let leaving = self.leave_app();
                self.left_for_launcher = true;
                return leaving;
            }
            Message::Open(page) => {
                self.page = page;
                self.model_menu_open = false;
                self.mode_menu_open = false;
                self.settings.provider_picker = false;
                if page == Page::Settings { return self.update(Message::RefreshKeys); }
            }
            Message::ToggleSidebar => self.sidebar_expanded = !self.sidebar_expanded,
            // Rule: a new empty chat only appears when the current one already
            // holds messages. Clicking again just focuses the empty draft.
            Message::NewChat => {
                if let Some(blank) = self.blank_draft() {
                    self.selected_draft = blank.id;
                } else {
                    let id = self.next_chat_id;
                    self.next_chat_id += 1;
                    self.drafts.push(ChatDraft::new(id));
                    self.selected_draft = id;
                }
                self.page = Page::Chat;
                self.model_menu_open = false;
                self.mode_menu_open = false;
                self.notice = None;
            }
            Message::OpenChat(id) if self.drafts.iter().any(|draft| draft.id == id) => {
                self.page = Page::Chat;
                self.selected_draft = id;
                if let Some(draft) = self.current_mut() { draft.last_viewed = storage::now_secs(); }
                if self.current().is_some_and(|draft| draft.follow_tail && !draft.turns.is_empty()) {
                    return iced::widget::operation::snap_to("chat-log", iced::widget::scrollable::RelativeOffset::START);
                }
            }
            Message::DeleteChat(id) => {
                self.store.remove(id);
                self.drafts.retain(|draft| draft.id != id);
                if self.drafts.is_empty() { self.drafts.push(ChatDraft::new(self.next_chat_id)); self.next_chat_id += 1; }
                if self.selected_draft == id {
                    self.selected_draft = self.drafts.last().map_or(1, |draft| draft.id);
                }
                self.persist_chats();
            }
            Message::SelectMode(mode) if mode < agent::MODES.len() as u8 => {
                if let Some(draft) = self.current_mut() { draft.mode = mode; }
                self.mode_menu_open = false;
            }
            Message::EditEditor(id, EditorAction(action)) if self.selected_draft == id => {
                if let Some(draft) = self.current_mut().filter(|draft| !draft.busy) {
                    let prior = draft.text.clone();
                    draft.editor.perform(action);
                    let updated = draft.editor.text();
                    if updated.chars().count() <= 4000 { draft.text = updated; }
                    else { draft.editor = text_editor::Content::with_text(&prior); }
                }
            }
            Message::EditDraft(id, text) if self.selected_draft == id => {
                if let Some(draft) = self.current_mut().filter(|draft| !draft.busy) {
                    if text.0.chars().count() <= 4000 {
                        draft.text = text.0.to_string();
                        draft.editor = text_editor::Content::with_text(&draft.text);
                    }
                }
            }
            Message::ClearDraft(id) if self.selected_draft == id => {
                if let Some(draft) = self.current_mut().filter(|draft| !draft.busy) {
                    draft.text.clear();
                    draft.editor = text_editor::Content::new();
                }
            }
            Message::ToggleReasoning(id, slot) => {
                if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == id) {
                    if draft.busy && slot == draft.turns.len() {
                        draft.partial_reasoning_open = !draft.partial_reasoning_open;
                        draft.partial_reasoning_touched = true;
                    } else if let Some((_, _, _, expanded)) = draft.formatted.iter_mut().find(|(index, _, _, _)| *index == slot) {
                        *expanded = !*expanded;
                    }
                }
            }
            Message::ToggleReasoningDefault => {
                self.reasoning_open_default = !self.reasoning_open_default;
                self.persist_settings();
            }
            Message::ToggleStreaming => {
                self.settings.stream_chat = !self.settings.stream_chat;
                self.persist_settings();
            }
            Message::ToggleModelMenu => {
                self.model_menu_open = !self.model_menu_open;
                self.mode_menu_open = false;
            }
            Message::ToggleModeMenu => {
                self.mode_menu_open = !self.mode_menu_open;
                self.model_menu_open = false;
            }
            Message::SearchChatModels(value) if value.chars().count() <= 100 => self.chat_model_search = value,
            Message::ChatScrolled(id, at_end) if id == self.selected_draft && self.snapshot.is_none() => {
                if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == id) { draft.follow_tail = at_end; }
            }
            Message::JumpToLatest => {
                if let Some(draft) = self.current_mut() { draft.follow_tail = true; }
                return iced::widget::operation::snap_to("chat-log", iced::widget::scrollable::RelativeOffset::START);
            }
            Message::IgnoreMarkdownLink => {}
            Message::CopyCode(code) if self.snapshot.is_none() => return iced::clipboard::write(code.0.to_string()),
            Message::ChatProgress(id, SecretReply(reply)) => {
                if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == id && draft.busy) {
                    draft.partial = Some((markdown::Content::parse(&reply.content), reply.reasoning.clone()));
                    draft.partial_raw = Some(reply);
                    if self.selected_draft == id && draft.follow_tail {
                        return iced::widget::operation::snap_to("chat-log", iced::widget::scrollable::RelativeOffset::START);
                    }
                }
            }
            Message::ChatResult(id, result) => {
                let at_tail = self.selected_draft == id && self.drafts.iter().any(|draft| draft.id == id && draft.follow_tail);
                if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == id && draft.busy) {
                    draft.busy = false;
                    draft.partial = None;
                    draft.request_handle = None;
                    match result {
                        Ok(SecretReply(reply)) => {
                            draft.partial_raw = None;
                            let slot = draft.turns.len();
                            // Reference `ensureThinking`: a user-toggled panel keeps the
                            // user's choice; an untouched one collapses on completion.
                            // Ours also honours an explicit "open by default" preference,
                            // which the reference has no equivalent for.
                            let open = if draft.partial_reasoning_touched {
                                draft.partial_reasoning_open
                            } else {
                                self.reasoning_open_default
                            };
                            draft.formatted.push((slot, markdown::Content::parse(&reply.content),
                                reply.reasoning.clone(), open));
                            draft.reasoning.push(reply.reasoning.clone());
                            draft.turns.push(Turn { role: "assistant", content: reply.content });
                            if reply.cut_off {
                                // Item 9's "cut off with no error": the provider
                                // answered 200 and stopped at OUR max_tokens, so
                                // the reply arrives as a success. It is not one.
                                let diagnosis = archx_shared::diagnostics::output_capped(CHAT_OUTPUT_TOKENS);
                                draft.incomplete_slots.push(slot);
                                draft.cut_off_slots.push(slot);
                                draft.error = Some(diagnosis.summary.clone());
                                draft.diagnosis = Some(diagnosis);
                            } else {
                                draft.error = None;
                                draft.diagnosis = None;
                            }
                        }
                        Err(failure) => {
                            if let Some(partial) = draft.partial_raw.take().filter(|reply|
                                !reply.content.trim().is_empty() || reply.reasoning.as_ref().is_some_and(|text| !text.trim().is_empty())) {
                                let slot = draft.turns.len();
                                let body = if partial.content.is_empty() { "Response interrupted before an answer.".to_owned() } else { partial.content };
                                draft.formatted.push((slot, markdown::Content::parse(&body),
                                    partial.reasoning.clone(),
                                    if draft.partial_reasoning_touched { draft.partial_reasoning_open }
                                    else { self.reasoning_open_default }));
                                draft.reasoning.push(partial.reasoning.clone());
                                draft.turns.push(Turn { role: "assistant", content: body });
                                draft.incomplete_slots.push(slot);
                            } else if let Some(last) = draft.turns.pop() {
                                // Nothing arrived: restore the typed text; never resend silently.
                                if last.role == "user" {
                                    draft.text = last.content;
                                    draft.editor = text_editor::Content::with_text(&draft.text);
                                    draft.reasoning.pop();
                                } else { draft.turns.push(last); }
                            }
                            draft.error = Some(failure.diagnosis.summary.clone());
                            draft.diagnosis = Some(failure.diagnosis.clone());
                        }
                    }
                    self.persist_chat(id);
                    if at_tail {
                        return iced::widget::operation::snap_to("chat-log", iced::widget::scrollable::RelativeOffset::START);
                    }
                }
            }
            Message::AttemptDone(id, test, outcome) => {
                let outcome = *outcome;
                self.finish_attempt(&outcome);
                if test {
                    let received: String = outcome.reply.content.chars().filter(|c| !c.is_control() || *c == '\n').take(240).collect();
                    let word = if self.settings.expected_word.is_empty() { "OK".to_owned() } else { self.settings.expected_word.clone() };
                    let passed = received.to_lowercase().contains(&word.to_lowercase());
                    self.settings.test_busy = false;
                    self.settings.test_evidence = Some(format!("Sent: Reply with the word {word}.  ·  Received: {received}  ·  Expected word: {}",
                        if passed { "found" } else { "not found" }));
                    self.settings.status = format!("Test passed in {} ms using key {}.",
                        outcome.trace.duration_ms, if outcome.key_id == 0 { "none".to_owned() } else { format!("#{}", outcome.key_id) });
                    self.persist_tests();
                    return Task::none();
                }
                return self.update(Message::ChatResult(id, Ok(SecretReply(outcome.reply))));
            }
            Message::AttemptFailed(id, test, failure, attempts, journal_id) => {
                let failure = *failure;
                self.fail_attempt(&failure, attempts, journal_id);
                if test {
                    self.settings.test_busy = false;
                    self.settings.test_evidence = Some(format!("Failed: {}", failure.diagnosis.summary));
                    self.settings.status = failure.diagnosis.summary.clone();
                    self.persist_tests();
                    return Task::none();
                }
                return self.update(Message::ChatResult(id, Err(Box::new(failure))));
            }
            Message::SendChat => return self.send_chat(false),
            Message::StopChat => {
                if let Some(draft) = self.current_mut().filter(|draft| draft.busy) {
                    if let Some(handle) = draft.request_handle.take() { handle.abort(); }
                    let id = draft.id;
                    let stopped = Failure {
                        diagnosis: Diagnosis {
                            stage: diagnostics::Stage::Request,
                            owner: diagnostics::Owner::Agent,
                            http_status: None,
                            cooldown: None,
                            retry_after: None,
                            summary: "Generation stopped. Text received so far is kept and marked incomplete.".into(),
                        },
                        trace: provider_api::Trace::default(),
                        may_have_billed: true,
                    };
                    return self.update(Message::ChatResult(id, Err(Box::new(stopped))));
                }
            }
            Message::RunTest if !self.settings.test_busy => return self.send_chat(true),
            Message::TestResult(result) => {
                self.settings.test_busy = false;
                let word = self.settings.expected_word.clone();
                let (status, evidence) = match result {
                    Ok(content) => {
                        let received: String = content.0.chars().filter(|c| !c.is_control() || *c == '\n').take(240).collect();
                        let passed = received.to_lowercase().contains(&word.to_lowercase());
                        (if passed { "Generation probe received the expected word (not a permanent availability guarantee).".to_owned() }
                            else { "Generation returned text, but the expected word was not found.".to_owned() },
                         format!("Sent: Reply with the word {word}.  ·  Received: {received}  ·  Expected word: {}", if passed { "found" } else { "not found" }))
                    }
                    Err(error) => (error.clone(), format!("Sent: Reply with the word {word}.  ·  Failed: {error}")),
                };
                self.settings.test_evidence = Some(evidence);
                self.settings.status = status;
                self.persist_tests();
            }
            Message::ExpectedWord(value) if !self.settings.test_busy && !self.settings.probe_busy => {
                if value.chars().count() <= 32 && value.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') {
                    if value != self.settings.expected_word { self.settings.probe_results.clear(); }
                    self.settings.expected_word = value;
                }
            }
            other => return self.update_provider(other),
        }
        Task::none()
    }

    /// Sends the composer text (or runs the explicit settings test).
    ///
    /// Key policy (item 2): the rotation state chooses one key that is not
    /// resting; if the provider blames the key and another healthy key exists,
    /// the request is retried exactly once on the next key. Every attempt is
    /// recorded in the journal, and a model-specific refusal disables the model
    /// (never the key).
    pub(crate) fn send_chat(&mut self, test: bool) -> Task<Message> {
        if self.snapshot.is_some() { return Task::none(); }
        let provider = self.settings.provider;
        let model = self.settings.selected_model().map(str::to_owned);
        let Some(model) = model else {
            let notice = "Select a provider and an enabled model first.";
            if test { self.settings.status = notice.into(); }
            else if let Some(draft) = self.current_mut() { draft.error = Some(notice.into()); }
            return Task::none();
        };
        if provider == Provider::Custom && !self.settings.custom_approved {
            let message = "Approve the custom destination before sending any prompt or key.".to_owned();
            self.settings.status = message.clone();
            if let Some(draft) = self.current_mut() { draft.error = Some(message); }
            return Task::none();
        }
        let now = storage::now_secs();
        let keys = self.settings.key_ids.clone();
        self.keys.sync(&keys);
        self.keys.expire(now);
        let plan: Vec<u64> = if provider.needs_key() {
            let picks = self.key_plan(now);
            if picks.is_empty() {
                let message = "No usable vault key. Add one in Providers.".to_owned();
                self.settings.status = message.clone();
                if let Some(draft) = self.current_mut() { draft.error = Some(message); }
                return Task::none();
            }
            picks
        } else { vec![0] };

        let id = self.selected_draft;
        let custom = self.settings.custom.clone();
        let registry = self.endpoints.clone();
        let streamed = !test && self.settings.stream_chat;
        let turns = if test {
            self.settings.test_busy = true;
            self.settings.test_evidence = None;
            let word = if self.settings.expected_word.is_empty() { "OK" } else { &self.settings.expected_word };
            self.settings.status = "Sending a small billable generation test…".into();
            vec![Turn { role: "user", content: format!("Reply with the word {word}.") }]
        } else {
            let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == id) else { return Task::none(); };
            if draft.mode != 0 || draft.busy || draft.text.trim().is_empty() || draft.text.chars().count() > 4000 {
                return Task::none();
            }
            draft.error = None;
            draft.diagnosis = None;
            draft.partial_raw = None;
            draft.partial_reasoning_open = self.reasoning_open_default;
            draft.partial_reasoning_touched = false;
            draft.busy = true;
            draft.follow_tail = true;
            draft.model = Some(model.clone());
            let text = std::mem::take(&mut draft.text);
            draft.editor = text_editor::Content::new();
            draft.turns.push(Turn { role: "user", content: text });
            draft.reasoning.push(None);
            draft.turns.iter().enumerate().rev()
                .filter(|(slot, _)| !draft.incomplete_slots.contains(slot))
                .take(12).map(|(_, turn)| turn.clone()).collect::<Vec<_>>()
                .into_iter().rev().collect()
        };
        let request_bytes = provider_api::request_size(provider, &model, &turns, if test { TEST_OUTPUT_TOKENS } else { CHAT_OUTPUT_TOKENS });
        let journal_id = self.journal.begin(provider.name(), model.clone(), plan.first().copied().unwrap_or(0), streamed, request_bytes);
        self.save_journal();

        let task = Task::sip(sipper(async move |mut progress| {
            let mut attempts = 0usize;
            let mut last: Option<Failure> = None;
            for (attempt, key_id) in plan.iter().copied().enumerate() {
                attempts = attempt + 1;
                let started = Instant::now();
                let key = match fetch_key(provider, key_id).await {
                    Ok(key) => key,
                    Err(error) => {
                        last = Some(Failure { diagnosis: diagnostics::invalid_input(), trace: provider_api::Trace::default(), may_have_billed: false });
                        let _ = &error;
                        let _ = &mut progress;
                        continue;
                    }
                };
                let result = if streamed {
                    if provider == Provider::Custom {
                        custom_endpoint::send_stream(custom.clone(), model.clone(), key, turns.clone(), CHAT_OUTPUT_TOKENS, &mut progress).await
                    } else {
                        provider_api::send_stream_via(provider, model.clone(), key, turns.clone(), &mut progress, CHAT_OUTPUT_TOKENS, &registry).await
                    }
                } else if provider == Provider::Custom {
                    custom_endpoint::send(custom.clone(), model.clone(), key, turns.clone(), if test { TEST_OUTPUT_TOKENS } else { CHAT_OUTPUT_TOKENS }).await
                } else {
                    provider_api::send_via(provider, model.clone(), key, turns.clone(), if test { TEST_OUTPUT_TOKENS } else { CHAT_OUTPUT_TOKENS }, &registry).await
                };
                match result {
                    Ok((reply, trace)) => {
                        let _ = key_id;
                        let _ = started;
                        return Ok(AttemptOutcome { model: model.clone(), reply, trace, attempts, key_id, journal_id });
                    }
                    Err(failure) => {
                        let retryable_key = failure.diagnosis.retries_key();
                        last = Some(failure);
                        if retryable_key && attempt + 1 < plan.len() { continue; }
                        break;
                    }
                }
            }
            Err((last.unwrap_or_else(|| Failure::from(provider_api::CallError::InvalidInput)), attempts, journal_id))
        }),
            move |reply| Message::ChatProgress(id, SecretReply(reply)),
            move |result| match result {
                Ok(outcome) => Message::AttemptDone(id, test, Box::new(outcome)),
                Err((failure, attempts, journal_id)) => Message::AttemptFailed(id, test, Box::new(failure), attempts, journal_id),
            });
        let (task, handle) = task.abortable();
        if !test {
            if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == id) {
                draft.request_handle = Some(handle);
            }
            Task::batch([task, iced::widget::operation::snap_to("chat-log", iced::widget::scrollable::RelativeOffset::START)])
        } else {
            let _ = handle;
            task
        }
    }

    /// Keys to try, in order: the healthy pick first, then one other healthy key.
    ///
    /// This advances the rotation. Without that the cursor never moves and the
    /// first healthy key is used for every request, which is not rotation at all.
    pub(crate) fn key_plan(&mut self, now: u64) -> Vec<u64> {
        let mut plan = Vec::new();
        if let Some((position, id)) = self.keys.pick(now) {
            self.keys.advance_from(position);
            plan.push(id);
            // One fallback key for a key-specific refusal.
            if self.keys.auto_rotate {
                let healthy: Vec<u64> = self.keys.slots.iter().enumerate()
                    .filter(|(index, slot)| *index != position && !slot.cooling(now))
                    .map(|(_, slot)| slot.id).collect();
                if let Some(next) = healthy.first() { plan.push(*next); }
            }
        }
        plan
    }

    // ---------------------------------------------------------------- outcomes

    pub(crate) fn finish_attempt(&mut self, outcome: &AttemptOutcome) {
        let now = storage::now_secs();
        self.keys.record_success(outcome.key_id, now);
        self.model_health.record_success(&outcome.model, now);
        let chars = outcome.reply.content.chars().count();
        let reasoning_chars = outcome.reply.reasoning.as_ref().map_or(0, |text| text.chars().count());
        if outcome.reply.cut_off {
            self.journal.finish_capped(outcome.journal_id, outcome.trace.duration_ms, chars,
                reasoning_chars, outcome.trace.response_bytes,
                diagnostics::output_capped(CHAT_OUTPUT_TOKENS));
        } else {
            self.journal.finish_ok(outcome.journal_id, outcome.trace.duration_ms, chars,
                reasoning_chars, outcome.trace.response_bytes);
        }
        self.save_journal();
        self.persist_settings();
    }

    pub(crate) fn fail_attempt(&mut self, failure: &Failure, attempts: usize, journal_id: u64) {
        let now = storage::now_secs();
        self.journal.finish_failed(journal_id, failure.trace.duration_ms, failure.diagnosis.clone(),
            failure.trace.provider_message.clone());
        self.save_journal();
        if let Some((_, key_id)) = self.keys.pick(now) {
            self.keys.record_neutral(key_id);
            let _ = self.keys.record_failure(key_id, &failure.diagnosis, now);
        }
        let note = self.model_health.record_failure(&self.current_model_id(), &failure.diagnosis, now);
        if let Some(note) = note { self.notice = Some(note); }
        let _ = attempts;
        self.persist_settings();
    }

    pub(crate) fn current_model_id(&self) -> String {
        self.settings.selected_model().unwrap_or("").to_owned()
    }
}

/// One successful attempt, carried from the async task back into `update`.
#[derive(Debug, Clone)]
pub struct AttemptOutcome {
    pub model: String,
    pub reply: Reply,
    pub trace: provider_api::Trace,
    pub attempts: usize,
    pub key_id: u64,
    pub journal_id: u64,
}

impl std::fmt::Debug for ChatDraft {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ChatDraft").field("id", &self.id).field("busy", &self.busy).finish_non_exhaustive()
    }
}

/// Fetches one vault key by id.
async fn fetch_key(provider: Provider, key_id: u64) -> Result<Zeroizing<String>, String> {
    if !provider.needs_key() { return Ok(Zeroizing::new(String::new())); }
    tokio::task::spawn_blocking(move || Vault::os().with_key(provider, key_id, |secret| Zeroizing::new(secret.to_owned())))
        .await.map_err(|_| VaultError::Unavailable.message().to_owned())
        .and_then(|result| result.map_err(|error| error.message().to_owned()))
}

// The rest of the state machine (providers, keys, endpoints, models, catalog,
// probes, debug, storage) lives in `app_provider.rs`, which implements the same
// `App` type; it is declared next to `app` in `lib.rs`.

#[cfg(test)]
mod tests;
