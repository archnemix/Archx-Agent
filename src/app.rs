//! Purpose: Owns navigation, ephemeral Chat/Settings state, explicit provider actions, and screenshots.
use std::path::PathBuf;
use std::time::Duration;

use iced::time;
use iced::task::sipper;
use iced::window;
use iced::{Element, Subscription, Task};
use iced::widget::text_editor;
use std::fmt;

use crate::agent_visual::MODE_COUNT;
use crate::app_tile::Art;
use crate::home;
use crate::model_catalog::{self, CatalogModel};
use crate::credentials::{Provider, Vault, VaultError};
use crate::custom_endpoint;
use crate::provider_api::{self, Turn, Reply, CallError};
use iced::widget::markdown;
use crate::settings::{SecretText, Section, SettingsState};
use zeroize::Zeroizing;
use std::time::Instant;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Page {
    Home,
    Agent,
    Settings,
    About,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MemoryMode {
    Light,
    Heavy,
    Custom,
}

pub struct ChatDraft {
    pub id: u32,
    pub mode: u8,
    pub text: String,
    pub editor: text_editor::Content,
    pub formatted: Vec<(usize, markdown::Content, Option<markdown::Content>, bool)>,
    pub partial: Option<(markdown::Content, Option<markdown::Content>)>,
    pub partial_raw: Option<Reply>,
    pub incomplete_slots: Vec<usize>,
    pub request_handle: Option<iced::task::Handle>,
    pub turns: Vec<Turn>,
    pub busy: bool,
    pub error: Option<String>,
}

#[derive(Clone)]
pub struct SecretReply(pub Reply);
impl fmt::Debug for SecretReply {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result { f.write_str("[redacted reply]") }
}


#[derive(Clone)]
pub struct EditorAction(pub text_editor::Action);
impl fmt::Debug for EditorAction {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result { f.write_str("[redacted editor action]") }
}


#[derive(Debug, Clone)]
pub enum Message {
    Navigate(Page),
    ToggleSidebar,
    NewChat,
    OpenChat(u32),
    SelectMode(u8),
    EditDraft(u32, SecretText),
    EditEditor(u32, EditorAction),
    ClearDraft(u32),
    MemoryPreview(MemoryMode),
    ToggleAgentPreview,
    TileHover(Art, bool),
    Animate,
    AgentPulse,
    SettingsSection(Section),
    OpenModelSettings,
    OpenModelCatalogSettings,
    SelectProvider(Provider),
    EditKey(SecretText),
    CustomUrl(String),
    CustomHeaders(SecretText),
    CustomBody(String),
    CustomAnswer(String),
    CustomDelta(String),
    CustomStream,
    CustomCurl(SecretText),
    ImportCustomCurl,
    ApproveCustom,
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
    EditModel(String),
    AddModel,
    ChooseModel(usize),
    RemoveModel(usize),
    FetchModels,
    ModelsFetched(Provider, u64, Result<Vec<CatalogModel>, String>),
    SearchModels(String),
    AddCatalogModel(Provider, usize),
    ToggleCatalogSelection(Provider, usize),
    ImportSelectedModels,
    RequestCatalogProbe,
    CancelCatalogProbe,
    ConfirmCatalogProbe,
    CatalogProbeProgress(Provider, u64, String, Result<SecretText, String>),
    CatalogProbeDone(Provider, u64, Result<(), String>),
    SendChat,
    StopChat,
    ChatResult(u32, Result<SecretReply, String>),
    ToggleReasoning(u32, usize),
    ToggleStreaming,
    ToggleModelMenu,
    ToggleModeMenu,
    SearchChatModels(String),
    ChatProgress(u32, SecretReply),
    IgnoreMarkdownLink,
    RunTest,
    TestResult(Result<SecretText, String>),
    SnapshotTick,
    SnapshotReady(window::screenshot::Screenshot),
}

pub struct App {
    page: Page,
    sidebar_expanded: bool,
    drafts: Vec<ChatDraft>,
    selected_draft: u32,
    model_menu_open: bool,
    mode_menu_open: bool,
    chat_model_search: String,
    memory_preview: MemoryMode,
    settings: SettingsState,
    key_cursor: [usize; Provider::COUNT],
    probe_handle: Option<iced::task::Handle>,
    keep_agent_preview: bool,
    snapshot: Option<PathBuf>,
    snapshot_requested: bool,
    hovered: Option<Art>,
    phase: u8,
    agent_phase: u8,
    frozen_snapshot_phase: bool,
}

impl App {
    pub fn new() -> Self {
        let snapshot = std::env::var_os("ARCHX_SNAPSHOT").map(PathBuf::from);
        let page = if snapshot.is_some() {
            match std::env::var("ARCHX_SNAPSHOT_PAGE").as_deref() {
                Ok("about") => Page::About,
                Ok("agent") => Page::Agent,
                Ok("settings") => Page::Settings,
                _ => Page::Home,
            }
        } else {
            Page::Home
        };
        let preview_art = if snapshot.is_some() && page == Page::Home {
            match std::env::var("ARCHX_SNAPSHOT_HOVER").as_deref() {
                Ok("training") => Some(Art::Training),
                Ok("tuning") => Some(Art::Tuning),
                _ => None,
            }
        } else {
            None
        };
        let phase = if snapshot.is_some() {
            std::env::var("ARCHX_SNAPSHOT_PHASE")
                .ok()
                .and_then(|value| value.parse::<u8>().ok())
                .filter(|phase| *phase < 3)
        } else {
            None
        };
        let agent_phase = if snapshot.is_some() {
            std::env::var("ARCHX_SNAPSHOT_AGENT_PHASE")
                .ok()
                .and_then(|value| value.parse::<u8>().ok())
                .filter(|phase| *phase < MODE_COUNT)
                .unwrap_or(0)
        } else {
            0
        };
        let preview_mode = if snapshot.is_some() && page == Page::Agent {
            std::env::var("ARCHX_SNAPSHOT_MODE").ok()
                .and_then(|value| value.parse::<u8>().ok())
                .filter(|mode| *mode < MODE_COUNT)
                .unwrap_or(0)
        } else { 0 };
        let preview_memory = if snapshot.is_some() && page == Page::Settings
            && std::env::var("ARCHX_SNAPSHOT_MEMORY").as_deref() == Ok("custom") {
            MemoryMode::Custom
        } else { MemoryMode::Light };
        // CI may capture an unsent draft state. Normal launches always start empty.
        let preview_text = if snapshot.is_some() && page == Page::Agent {
            std::env::var("ARCHX_SNAPSHOT_DRAFT").unwrap_or_default()
        } else { String::new() };
        let mut settings = SettingsState::default();
        if snapshot.is_some() && page == Page::Settings {
            settings.section = match std::env::var("ARCHX_SNAPSHOT_SETTINGS").as_deref() {
                Ok("models" | "import-review") => Section::Models,
                _ if preview_memory == MemoryMode::Custom => Section::Lab,
                _ => Section::Providers,
            };
        }
        if snapshot.is_some() && page == Page::Settings &&
            std::env::var("ARCHX_SNAPSHOT_SETTINGS").as_deref() == Ok("import-review") {
            settings.catalog[0] = vec![
                CatalogModel { id: "vendor/alpha:free".into(), name: "Alpha".into(), free: true, router: false, reasoning: false },
                CatalogModel { id: "vendor/beta".into(), name: "Beta".into(), free: false, router: false, reasoning: true },
                CatalogModel { id: "vendor/gamma".into(), name: "Gamma".into(), free: false, router: false, reasoning: false },
            ];
            settings.probe_results.push(("vendor/beta".into(), true, "OK".into()));
            settings.probe_results.push(("vendor/gamma".into(), false, "HTTP 429 · account quota exceeded".into()));
        }
        let mut drafts = vec![ChatDraft { id: 1, mode: preview_mode,
            editor: text_editor::Content::with_text(&preview_text), text: preview_text,
            formatted: Vec::new(), partial: None, partial_raw: None, incomplete_slots: Vec::new(), request_handle: None, turns: Vec::new(), busy: false, error: None }];
        // Only scripted CI screenshots use synthetic messages; normal launches start empty.
        if snapshot.is_some() && page == Page::Agent && matches!(std::env::var("ARCHX_SNAPSHOT_CHAT").as_deref(), Ok("reasoning" | "model-menu" | "review")) {
            settings.models[0] = vec!["demo/model:free".into(), "demo/another".into()];
            settings.chosen[0] = Some(0);
            if matches!(std::env::var("ARCHX_SNAPSHOT_CHAT").as_deref(), Ok("reasoning" | "review")) {
            drafts[0].turns = vec![
                Turn { role: "user", content: "Show a short example".into() },
                Turn { role: "assistant", content: "## Example\n\nA **bold** answer with `code`.\n\n- First item\n- Second item".into() },
            ];
            if std::env::var("ARCHX_SNAPSHOT_CHAT").as_deref() == Ok("review") {
                drafts[0].turns[1].content = "# Server-sent events\n\nSSE keeps one HTTP response open and delivers updates as they arrive.\n\n```javascript\nconst source = new EventSource('/events');\nsource.onmessage = (event) => console.log(event.data);\n```\n\n| Feature | SSE | Polling |\n| :--- | :--- | :--- |\n| Connection | Persistent | Repeated requests |\n| Direction | Server to client | Request/response |".into();
            }
            let demo_answer = drafts[0].turns[1].content.clone();
            drafts[0].formatted.push((1,
                markdown::Content::parse(&demo_answer),
                Some(markdown::Content::parse("The provider returned this synthetic reasoning content. It is collapsed unless the user opens it.")),
                std::env::var("ARCHX_SNAPSHOT_CHAT").as_deref() == Ok("review")));
            }
        }
        Self {
            page,
            sidebar_expanded: !(snapshot.is_some()
                && std::env::var("ARCHX_SNAPSHOT_SIDEBAR").as_deref() == Ok("collapsed")),
            drafts,
            selected_draft: 1,
            model_menu_open: snapshot.is_some() && page == Page::Agent
                && std::env::var("ARCHX_SNAPSHOT_CHAT").as_deref() == Ok("model-menu"),
            mode_menu_open: false,
            chat_model_search: String::new(),
            memory_preview: preview_memory,
            settings,
            key_cursor: [0; Provider::COUNT],
            probe_handle: None,
            keep_agent_preview: false,
            snapshot,
            snapshot_requested: false,
            hovered: preview_art,
            phase: phase.unwrap_or(0),
            agent_phase,
            frozen_snapshot_phase: phase.is_some(),
        }
    }

    pub fn update(&mut self, message: Message) -> Task<Message> {
        match message {
            Message::Navigate(page) => {
                if page != Page::Settings {
                    self.settings.clear_secret();
                    if let Some(handle) = self.probe_handle.take() { handle.abort(); }
                    self.settings.probe_busy = false;
                    self.settings.probe_nonce = self.settings.probe_nonce.wrapping_add(1);
                }
                self.page = page;
                self.model_menu_open = false;
                self.mode_menu_open = false;
                self.hovered = None;
                if page == Page::Settings { return self.update(Message::RefreshKeys); }
            }
            Message::OpenModelSettings => {
                self.page = Page::Settings;
                self.model_menu_open = false;
                self.mode_menu_open = false;
                self.settings.section = Section::Providers;
                return self.update(Message::RefreshKeys);
            }
            Message::OpenModelCatalogSettings => {
                self.page = Page::Settings;
                self.model_menu_open = false;
                self.mode_menu_open = false;
                self.settings.section = Section::Models;
                return self.update(Message::RefreshKeys);
            }
            Message::ToggleSidebar => {
                self.sidebar_expanded = !self.sidebar_expanded;
            }
            Message::NewChat if self.page == Page::Agent => {
                let id = self.drafts.last().map_or(1, |draft| draft.id + 1);
                self.drafts.push(ChatDraft { id, mode: 0, text: String::new(), editor: text_editor::Content::new(), formatted: Vec::new(), partial: None, partial_raw: None, incomplete_slots: Vec::new(), request_handle: None, turns: Vec::new(), busy: false, error: None });
                self.selected_draft = id;
                self.model_menu_open = false;
                self.mode_menu_open = false;
            }
            Message::OpenChat(id) if self.page == Page::Agent && self.drafts.iter().any(|draft| draft.id == id) => {
                self.selected_draft = id;
                self.model_menu_open = false;
                self.mode_menu_open = false;
            }
            Message::SelectMode(mode) if self.page == Page::Agent && mode < MODE_COUNT => {
                if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == self.selected_draft) {
                    draft.mode = mode;
                    self.mode_menu_open = false;
                }
            }
            Message::EditEditor(id, EditorAction(action)) if self.page == Page::Agent && self.selected_draft == id => {
                if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == id) {
                    if !draft.busy {
                        let prior = draft.text.clone();
                        draft.editor.perform(action);
                        let updated = draft.editor.text();
                        if updated.chars().count() <= 4000 { draft.text = updated; }
                        else { draft.editor = text_editor::Content::with_text(&prior); }
                    }
                }
            }
            Message::EditDraft(id, text) if self.page == Page::Agent && self.selected_draft == id => {
                if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == id) {
                    if !draft.busy && text.0.chars().count() <= 4000 { draft.text = text.0.to_string(); draft.editor = text_editor::Content::with_text(&draft.text); }
                }
            }
            Message::ClearDraft(id) if self.page == Page::Agent && self.selected_draft == id => {
                if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == id) {
                    if !draft.busy { draft.text.clear(); draft.editor = text_editor::Content::new(); }
                }
            }
            Message::MemoryPreview(memory) if self.page == Page::Settings => {
                self.memory_preview = memory;
            }
            Message::ToggleAgentPreview if self.page == Page::Settings && self.memory_preview == MemoryMode::Custom => {
                self.keep_agent_preview = !self.keep_agent_preview;
            }
            Message::TileHover(art, true) if self.page == Page::Home && art != Art::Agent => {
                self.hovered = Some(art);
                self.phase = 0;
            }
            Message::TileHover(art, false) if self.hovered == Some(art) => {
                self.hovered = None;
                self.phase = 0;
            }
            Message::Animate if self.hovered.is_some() && !self.frozen_snapshot_phase => {
                self.phase = (self.phase + 1) % 3;
            }
            Message::AgentPulse if self.page == Page::Home && self.snapshot.is_none() => {
                self.agent_phase = (self.agent_phase + 1) % MODE_COUNT;
            }
            Message::SettingsSection(section) if self.page == Page::Settings => {
                self.settings.clear_secret();
                if section != Section::Models && self.settings.probe_busy {
                    if let Some(handle) = self.probe_handle.take() { handle.abort(); }
                    self.settings.probe_busy = false;
                    self.settings.probe_nonce = self.settings.probe_nonce.wrapping_add(1);
                }
                self.settings.probe_pending = false;
                self.settings.section = section;
            }
            Message::SelectProvider(provider) if matches!(self.page, Page::Settings | Page::Agent) && !self.settings.key_busy && !self.settings.probe_busy => {
                self.settings.clear_secret();
                self.settings.custom_approved = false;
                self.settings.provider = provider;
                self.settings.model_entry.clear();
                self.settings.search.clear();
                self.settings.probe_pending = false;
                self.settings.catalog_nonce = self.settings.catalog_nonce.wrapping_add(1);
                self.settings.catalog_busy = false;
                self.settings.key_ids.clear();
                self.settings.status.clear();
                if self.page == Page::Settings { return self.update(Message::RefreshKeys); }
            }
            Message::CustomUrl(value) if self.page == Page::Settings && self.settings.provider == Provider::Custom => {
                if value.len() <= 2048 { self.settings.custom.url = value; self.settings.custom_approved = false; }
            }
            Message::CustomHeaders(value) if self.page == Page::Settings && self.settings.provider == Provider::Custom => {
                if value.0.len() <= 8192 { self.settings.custom.headers = value.0; self.settings.custom_approved = false; }
            }
            Message::CustomBody(value) if self.page == Page::Settings && self.settings.provider == Provider::Custom => {
                if value.len() <= 16_384 { self.settings.custom.body = value; self.settings.custom_approved = false; }
            }
            Message::CustomAnswer(value) if self.page == Page::Settings && self.settings.provider == Provider::Custom => {
                if value.len() <= 256 { self.settings.custom.answer_pointer = value; self.settings.custom_approved = false; }
            }
            Message::CustomDelta(value) if self.page == Page::Settings && self.settings.provider == Provider::Custom => {
                if value.len() <= 256 { self.settings.custom.stream_pointer = value; self.settings.custom_approved = false; }
            }
            Message::CustomStream if self.page == Page::Settings && self.settings.provider == Provider::Custom => {
                self.settings.custom.stream = !self.settings.custom.stream; self.settings.custom_approved = false;
            }
            Message::CustomCurl(value) if self.page == Page::Settings && self.settings.provider == Provider::Custom => {
                if value.0.len() <= 24_000 { self.settings.custom_curl = value; self.settings.custom_approved = false; }
            }
            Message::ImportCustomCurl if self.page == Page::Settings && self.settings.provider == Provider::Custom => {
                match custom_endpoint::parse_curl(&self.settings.custom_curl.0) {
                    Ok((url, headers, body)) => {
                        self.settings.custom.url = url;
                        self.settings.custom.headers = Zeroizing::new(headers);
                        self.settings.custom.body = body;
                        self.settings.custom_curl = SecretText::default();
                        self.settings.custom_approved = false;
                        self.settings.status = "Parsed literal cURL fields. Review destination, headers and response pointer before approval.".into();
                    }
                    Err(error) => self.settings.status = error.into(),
                }
            }
            Message::ApproveCustom if self.page == Page::Settings && self.settings.provider == Provider::Custom => {
                if self.settings.custom_approved { self.settings.custom_approved = false; }
                else { match self.settings.custom.check() {
                    Ok(()) => { self.settings.custom_approved = true; self.settings.status = "Destination approved for this session. Add an exact model ID; send or run an explicit test when ready.".into(); }
                    Err(error) => self.settings.status = error.into(),
                }}
            }
            Message::EditKey(value) if self.page == Page::Settings && self.settings.section != Section::Lab => {
                if value.0.len() <= 1024 { self.settings.key_entry = value; }
            }
            Message::SaveKey if self.page == Page::Settings && self.settings.section != Section::Lab && !self.settings.key_entry.0.is_empty() && !self.settings.key_busy => {
                self.settings.key_busy = true;
                self.settings.custom_approved = false;
                let provider = self.settings.provider;
                let secret = std::mem::take(&mut self.settings.key_entry).0;
                self.settings.clear_secret();
                self.settings.status = "Saving to the OS vault…".into();
                return Task::perform(async move {
                    tokio::task::spawn_blocking(move || Vault::os().add(provider, secret))
                        .await.unwrap_or(Err(VaultError::Unavailable))
                }, move |result| Message::KeySaved(provider, result));
            }
            Message::KeySaved(provider, result) if self.settings.provider == provider => {
                self.settings.key_busy = false;
                match result {
                    Ok(_) => {
                        self.settings.section = Section::Models;
                        let keys = self.update(Message::RefreshKeys);
                        let catalog = self.update(Message::FetchModels);
                        self.settings.status = "Key saved. Fetching model IDs only; no generation test will run without your confirmation.".into();
                        return Task::batch([keys, catalog]);
                    }
                    Err(error) => self.settings.status = error.message().into(),
                }
                return self.update(Message::RefreshKeys);
            }
            Message::RefreshKeys if self.page == Page::Settings => {
                let provider = self.settings.provider;
                if !provider.needs_key() { self.settings.key_ids.clear(); return Task::none(); }
                return Task::perform(async move {
                    tokio::task::spawn_blocking(move || Vault::os().list(provider))
                        .await.unwrap_or(Err(VaultError::Unavailable))
                }, move |result| Message::KeysLoaded(provider, result));
            }
            Message::KeysLoaded(provider, result) if self.page == Page::Settings && self.settings.provider == provider => {
                match result {
                    Ok(ids) => self.settings.key_ids = ids,
                    Err(error) => { self.settings.key_ids.clear(); self.settings.status = error.message().into(); }
                }
            }
            Message::RemoveKey(id) if self.page == Page::Settings && !self.settings.key_busy && self.settings.key_ids.contains(&id) => {
                self.settings.key_busy = true;
                self.settings.clear_secret();
                let provider = self.settings.provider;
                return Task::perform(async move {
                    tokio::task::spawn_blocking(move || Vault::os().remove(provider, id))
                        .await.unwrap_or(Err(VaultError::Unavailable))
                }, move |result| Message::KeyRemoved(provider, result));
            }
            Message::KeyRemoved(provider, result) if self.settings.provider == provider => {
                self.settings.key_busy = false;
                self.settings.status = match result { Ok(()) => "Key removed from OS vault.".into(), Err(error) => error.message().into() };
                return self.update(Message::RefreshKeys);
            }
            Message::HideKey if self.page == Page::Settings => self.settings.clear_secret(),
            Message::RevealKey(id) if self.page == Page::Settings && self.snapshot.is_none() && self.settings.key_ids.contains(&id) => {
                self.settings.clear_secret();
                let provider = self.settings.provider;
                let nonce = self.settings.reveal_nonce;
                return Task::perform(async move {
                    let result = tokio::task::spawn_blocking(move || Vault::os().with_key(provider, id, |key| SecretText::new(key.to_owned())))
                        .await.unwrap_or(Err(VaultError::Unavailable));
                    (nonce, id, result)
                }, |(nonce, id, result)| Message::KeyRevealed(nonce, id, result));
            }
            Message::KeyRevealed(nonce, id, result) if self.page == Page::Settings && nonce == self.settings.reveal_nonce => {
                match result {
                    Ok(key) => {
                        self.settings.reveal = Some((id, key, Instant::now() + Duration::from_secs(15)));
                        return Task::perform(async move { tokio::time::sleep(Duration::from_secs(15)).await; nonce }, Message::RevealExpired);
                    }
                    Err(error) => self.settings.status = error.message().into(),
                }
            }
            Message::RevealExpired(nonce) if nonce == self.settings.reveal_nonce => self.settings.clear_secret(),
            Message::EditModel(model) if self.page == Page::Settings && self.settings.section != Section::Lab => {
                if model.len() <= 100 { self.settings.model_entry = model; }
            }
            Message::AddModel if self.page == Page::Settings && self.settings.section != Section::Lab => {
                let provider = self.settings.provider;
                let model = self.settings.model_entry.trim().to_owned();
                let index = self.settings.index();
                if provider_api::valid_model(provider, &model) && !self.settings.models[index].contains(&model) && self.settings.models[index].len() < 32 {
                    self.settings.models[index].push(model);
                    self.settings.model_entry.clear();
                    self.settings.status = "Model added, not verified. Choose it from Chat when ready.".into();
                } else { self.settings.status = "Invalid, duplicate or over-limit model ID.".into(); }
            }
            Message::ChooseModel(slot) if matches!(self.page, Page::Settings | Page::Agent) && slot < self.settings.models[self.settings.index()].len() => {
                let index = self.settings.index(); self.settings.chosen[index] = Some(slot);
                if self.page == Page::Agent { self.model_menu_open = false; }
            }
            Message::RemoveModel(slot) if self.page == Page::Settings && slot < self.settings.models[self.settings.index()].len() => {
                let index = self.settings.index();
                self.settings.models[index].remove(slot);
                self.settings.chosen[index] = None;
            }
            Message::SearchModels(query) if self.page == Page::Settings && self.settings.section != Section::Lab => {
                if query.len() <= 100 { self.settings.search = query; }
            }
            Message::AddCatalogModel(provider, slot) if self.page == Page::Settings && self.settings.section != Section::Lab && self.settings.provider == provider => {
                let index = self.settings.index();
                if let Some(item) = self.settings.catalog[index].get(slot) {
                    let model = item.id.clone();
                    if provider_api::valid_model(provider, &model) && !self.settings.models[index].contains(&model) && self.settings.models[index].len() < 32 {
                        self.settings.models[index].push(model);
                        self.settings.status = "Model added, not verified. Testing is optional and may be billable.".into();
                    }
                }
            }
            Message::ToggleCatalogSelection(provider, slot) if self.page == Page::Settings && self.settings.provider == provider => {
                let index = self.settings.index();
                if let Some(item) = self.settings.catalog[index].get(slot) {
                    if let Some(where_at) = self.settings.catalog_selected[index].iter().position(|id| id == &item.id) {
                        self.settings.catalog_selected[index].remove(where_at);
                    } else if self.settings.catalog_selected[index].len() < 10 {
                        self.settings.catalog_selected[index].push(item.id.clone());
                    } else { self.settings.status = "Select up to 10 models per import or probe.".into(); }
                }
            }
            Message::ImportSelectedModels if self.page == Page::Settings && !self.settings.probe_busy => {
                let index = self.settings.index();
                let checked = std::mem::take(&mut self.settings.catalog_selected[index]);
                let mut added = 0;
                for id in checked {
                    if self.settings.models[index].len() >= 32 { break; }
                    if self.settings.catalog[index].iter().any(|item| item.id == id) &&
                       !self.settings.models[index].contains(&id) {
                        self.settings.models[index].push(id);
                        added += 1;
                    }
                }
                self.settings.status = format!("Added {added} chosen IDs. They are unverified until you explicitly test or send a message; no model was activated automatically.");
            }
            Message::RequestCatalogProbe if self.page == Page::Settings && !self.settings.probe_busy => {
                let count = self.settings.catalog_selected[self.settings.index()].len();
                if count > 0 { self.settings.probe_pending = true; }
                else { self.settings.status = "Select at least one model first. All models begin unchecked.".into(); }
            }
            Message::CancelCatalogProbe if self.page == Page::Settings => {
                self.settings.probe_pending = false;
                if self.settings.probe_busy {
                    if let Some(handle) = self.probe_handle.take() { handle.abort(); }
                    self.settings.probe_busy = false;
                    self.settings.probe_nonce = self.settings.probe_nonce.wrapping_add(1);
                    self.settings.status = "Testing stopped. Results already received remain visible; no further models will be tested.".into();
                }
            }
            Message::ConfirmCatalogProbe if self.page == Page::Settings && self.settings.probe_pending && !self.settings.probe_busy && self.snapshot.is_none() => {
                let provider = self.settings.provider;
                let index = self.settings.index();
                let ids = self.settings.catalog_selected[index].clone();
                self.settings.probe_pending = false;
                self.settings.probe_busy = true;
                self.settings.probe_results.clear();
                self.settings.probe_nonce = self.settings.probe_nonce.wrapping_add(1);
                let nonce = self.settings.probe_nonce;
                let cursor = self.key_cursor[index];
                let task = Task::sip(sipper(async move |mut sender| {
                    for (offset, id) in ids.into_iter().enumerate() {
                        let result = match selected_key(provider, cursor.wrapping_add(offset)).await {
                            Ok(key) => provider_api::send(provider, id.clone(), key,
                                vec![Turn { role: "user", content: "Reply with the word OK.".into() }], 256)
                                .await.map(|reply| SecretText::new(reply.content))
                                .map_err(|error| error.message()),
                            Err(error) => Err(error),
                        };
                        sender.send((id, result)).await;
                    }
                    Ok::<(), String>(())
                }), move |(id, result)| Message::CatalogProbeProgress(provider, nonce, id, result),
                    move |result| Message::CatalogProbeDone(provider, nonce, result));
                let (task, handle) = task.abortable();
                self.probe_handle = Some(handle);
                self.settings.status = "Testing selected models (up to 256 output tokens each); this may be billable. Stop to cancel remaining requests.".into();
                return task;
            }
            Message::CatalogProbeProgress(provider, nonce, id, result) if self.page == Page::Settings &&
                self.settings.provider == provider && self.settings.probe_busy && self.settings.probe_nonce == nonce => {
                // Only display a bounded plain-text response. Never display auth or raw transport errors.
                let (ok, output) = match result {
                    Ok(text) => (true, text.0.chars().filter(|c| !c.is_control() || *c == '\n').take(240).collect()),
                    Err(error) => (false, error),
                };
                self.settings.probe_results.push((id, ok, output));
            }
            Message::CatalogProbeDone(provider, nonce, result) if self.page == Page::Settings &&
                self.settings.provider == provider && self.settings.probe_nonce == nonce => {
                self.settings.probe_busy = false;
                self.probe_handle = None;
                self.settings.status = match result {
                    Ok(()) => "Testing finished. Only explicit selected IDs are imported; a passed probe is not a permanent availability guarantee.".into(),
                    Err(error) => error,
                };
            }
            Message::FetchModels if self.settings.provider != Provider::Custom && self.page == Page::Settings && self.settings.section != Section::Lab && !self.settings.catalog_busy && self.snapshot.is_none() => {
                let provider = self.settings.provider;
                self.settings.catalog_busy = true;
                self.settings.catalog_nonce = self.settings.catalog_nonce.wrapping_add(1);
                let nonce = self.settings.catalog_nonce;
                self.settings.status = "Fetching catalog; no generation request is being sent…".into();
                return Task::perform(async move {
                    let key = if matches!(provider, Provider::OpenRouter | Provider::OllamaLocal) { None } else {
                        let result = tokio::task::spawn_blocking(move || {
                            let vault = Vault::os();
                            let id = vault.list(provider)?.first().copied().ok_or(VaultError::MissingKey)?;
                            vault.with_key(provider, id, |secret| Zeroizing::new(secret.to_owned()))
                        }).await.map_err(|_| VaultError::Unavailable).and_then(|result| result)
                            .map_err(|error| error.message().to_owned());
                        match result { Ok(key) => Some(key), Err(error) => return Err(error) }
                    };
                    model_catalog::fetch(provider, key).await.map_err(CallError::message)
                }, move |result| Message::ModelsFetched(provider, nonce, result));
            }
            Message::ModelsFetched(provider, nonce, result) if self.settings.provider == provider && self.settings.catalog_nonce == nonce => {
                self.settings.catalog_busy = false;
                match result {
                    Ok(models) => {
                        let count = models.len();
                        self.settings.catalog_selected[self.settings.index()].clear();
                        self.settings.probe_results.clear();
                        self.settings.catalog[self.settings.index()] = models;
                        self.settings.status = format!("Fetched {count} models. Search and add individual choices; no models were added automatically.");
                    }
                    Err(error) => self.settings.status = error,
                }
            }
            Message::SendChat if self.page == Page::Agent => return self.send_chat(false),
            Message::StopChat if self.page == Page::Agent => {
                if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == self.selected_draft && draft.busy) {
                    if let Some(handle) = draft.request_handle.take() { handle.abort(); }
                    return self.update(Message::ChatResult(self.selected_draft,
                        Err("Generation stopped. Text received so far is preserved but incomplete.".into())));
                }
            },
            Message::RunTest if self.page == Page::Settings && !self.settings.test_busy => return self.send_chat(true),
            Message::IgnoreMarkdownLink => {}
            Message::ToggleModelMenu if self.page == Page::Agent => {
                self.model_menu_open = !self.model_menu_open;
                self.mode_menu_open = false;
            }
            Message::ToggleModeMenu if self.page == Page::Agent => {
                self.mode_menu_open = !self.mode_menu_open;
                self.model_menu_open = false;
            }
            Message::SearchChatModels(value) if self.page == Page::Agent => {
                if value.chars().count() <= 100 { self.chat_model_search = value; }
            }
            Message::ToggleStreaming if self.page == Page::Agent => {
                self.settings.stream_chat = !self.settings.stream_chat;
            }
            Message::ChatProgress(id, SecretReply(reply)) => {
                if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == id && draft.busy) {
                    draft.partial = Some((markdown::Content::parse(&reply.content), reply.reasoning.as_ref().map(|r| markdown::Content::parse(r))));
                    draft.partial_raw = Some(reply);
                }
            }
            Message::ToggleReasoning(id, index) if self.page == Page::Agent => {
                if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == id) {
                    if let Some((_, _, _, expanded)) = draft.formatted.iter_mut().find(|(slot, _, _, _)| *slot == index) {
                        *expanded = !*expanded;
                    }
                }
            }
            Message::ChatResult(id, result) => {
                if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == id && draft.busy) {
                    draft.busy = false;
                    draft.partial = None;
                    draft.request_handle = None;
                    match result {
                        Ok(SecretReply(reply)) => {
                            draft.partial_raw = None;
                            let slot = draft.turns.len();
                            let body = markdown::Content::parse(&reply.content);
                            let reasoning = reply.reasoning.as_ref().map(|r| markdown::Content::parse(r));
                            draft.formatted.push((slot, body, reasoning, false));
                            draft.turns.push(Turn { role: "assistant", content: reply.content });
                        },
                        Err(error) => {
                            // Preserve already-received streaming text. Mark it incomplete
                            // and exclude it from subsequent provider context.
                            if let Some(partial) = draft.partial_raw.take().filter(|r|
                                !r.content.trim().is_empty() || r.reasoning.as_ref().is_some_and(|r| !r.trim().is_empty())) {
                                let slot = draft.turns.len();
                                let body = if partial.content.is_empty() { "Response interrupted before an answer.".to_owned() } else { partial.content };
                                draft.formatted.push((slot, markdown::Content::parse(&body),
                                    partial.reasoning.as_ref().map(|r| markdown::Content::parse(r)), false));
                                draft.turns.push(Turn { role: "assistant", content: body });
                                draft.incomplete_slots.push(slot);
                            } else if let Some(last) = draft.turns.pop() {
                                // No response arrived. Restore the input instead of
                                // silently resending after a possible billed request.
                                if last.role == "user" { draft.text = last.content; draft.editor = text_editor::Content::with_text(&draft.text); }
                                else { draft.turns.push(last); }
                            }
                            draft.error = Some(error);
                        },
                    }
                }
            }
            Message::TestResult(result) => {
                self.settings.test_busy = false;
                self.settings.status = match result {
                    Ok(content) => {
                        let received: String = content.0.chars().filter(|c| !c.is_control() || *c == '\n').take(240).collect();
                        self.settings.test_evidence = Some(format!("Sent: Reply with the word OK.  ·  Received: {received}"));
                        "Generation probe received text (not a permanent availability guarantee).".into()
                    }
                    Err(error) => {
                        self.settings.test_evidence = Some(format!("Sent: Reply with the word OK.  ·  Failed: {error}"));
                        error
                    }
                };
            },
            Message::SnapshotTick if self.snapshot.is_some() && !self.snapshot_requested => {
                self.snapshot_requested = true;
                return window::latest()
                    .and_then(window::screenshot)
                    .map(Message::SnapshotReady);
            }
            Message::SnapshotReady(screenshot) => {
                if let Some(path) = &self.snapshot {
                    if let Some(directory) = path.parent() {
                        std::fs::create_dir_all(directory)
                            .expect("Create screenshot directory");
                    }
                    image::save_buffer(
                        path,
                        &screenshot.rgba,
                        screenshot.size.width,
                        screenshot.size.height,
                        image::ColorType::Rgba8,
                    )
                    .expect("Save OS screenshot");
                    return window::latest().and_then(window::close);
                }
            }
            _ => {}
        }
        Task::none()
    }

    fn send_chat(&mut self, test: bool) -> Task<Message> {
        if self.snapshot.is_some() { return Task::none(); }
        let provider = self.settings.provider;
        let Some(model) = self.settings.selected_model().map(str::to_owned) else {
            let notice = "Select a provider and model in Chat, or add one in Settings → Connections & models.";
            if test { self.settings.status = notice.into(); }
            else if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == self.selected_draft) { draft.error = Some(notice.into()); }
            return Task::none();
        };
        let index = self.settings.index();
        let cursor = self.key_cursor[index];
        if provider == Provider::Custom && !self.settings.custom_approved {
            self.settings.status = "Approve the custom destination in Settings → Providers before sending any prompt or key.".into();
            if let Some(draft) = self.drafts.iter_mut().find(|d| d.id == self.selected_draft) {
                draft.error = Some(self.settings.status.clone());
            }
            return Task::none();
        }
        let custom = self.settings.custom.clone();
        let id = self.selected_draft;
        let turns = if test {
            self.settings.test_busy = true;
            self.settings.test_evidence = None;
            self.settings.status = "Sending a small billable generation test…".into();
            vec![Turn { role: "user", content: "Reply with the word OK.".into() }]
        } else {
            let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == id) else { return Task::none(); };
            if draft.mode != 0 || draft.busy || draft.text.trim().is_empty() || draft.text.chars().count() > 4000 { return Task::none(); }
            draft.error = None;
            draft.partial_raw = None;
            draft.busy = true;
            draft.turns.push(Turn { role: "user", content: std::mem::take(&mut draft.text) });
            draft.editor = text_editor::Content::new();
            draft.turns.iter().enumerate().rev()
                .filter(|(slot, _)| !draft.incomplete_slots.contains(slot))
                .take(12).map(|(_, turn)| turn.clone()).collect::<Vec<_>>()
                .into_iter().rev().collect()
        };
        self.key_cursor[index] = cursor.wrapping_add(1);
        if test || !self.settings.stream_chat {
            let task = async move {
                let selected = selected_key(provider, cursor).await?;
                if provider == Provider::Custom {
                    custom_endpoint::send(custom, model, selected, turns, if test { 256 } else { 4096 }).await
                } else {
                    provider_api::send(provider, model, selected, turns, if test { 256 } else { 4096 }).await
                }.map_err(CallError::message)
            };
            if test { Task::perform(task, |result| Message::TestResult(result.map(|reply| SecretText::new(reply.content)))) }
            else {
                let (task, handle) = Task::perform(task, move |result| Message::ChatResult(id, result.map(SecretReply))).abortable();
                if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == id) { draft.request_handle = Some(handle); }
                task
            }
        } else {
            let task = Task::sip(sipper(async move |mut progress| {
                let selected = selected_key(provider, cursor).await?;
                if provider == Provider::Custom {
                    // The configurable SSE parser returns a complete bounded answer. A
                    // follow-up will expose incremental deltas in the UI as well.
                    custom_endpoint::send(custom, model, selected, turns, 4096).await
                } else {
                    provider_api::send_stream(provider, model, selected, turns, &mut progress, 4096).await
                }.map_err(CallError::message)
            }), move |reply| Message::ChatProgress(id, SecretReply(reply)),
                move |result| Message::ChatResult(id, result.map(SecretReply)));
            let (task, handle) = task.abortable();
            if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == id) { draft.request_handle = Some(handle); }
            task
        }
    }

    pub fn view(&self) -> Element<'_, Message> {
        home::view(self.page, self.sidebar_expanded, self.hovered, self.phase, self.agent_phase, &self.drafts, self.selected_draft, self.memory_preview, self.keep_agent_preview, &self.settings, self.model_menu_open, self.mode_menu_open, &self.chat_model_search)
    }

    pub fn subscription(&self) -> Subscription<Message> {
        let snapshot = if self.snapshot.is_some() && !self.snapshot_requested {
            time::every(Duration::from_secs(5)).map(|_| Message::SnapshotTick)
        } else {
            Subscription::none()
        };
        let animation = if self.page == Page::Home && self.hovered.is_some() && !self.frozen_snapshot_phase {
            time::every(Duration::from_millis(700)).map(|_| Message::Animate)
        } else {
            Subscription::none()
        };
        let agent = if self.page == Page::Home && self.snapshot.is_none() {
            time::every(Duration::from_millis(1500)).map(|_| Message::AgentPulse)
        } else {
            Subscription::none()
        };
        Subscription::batch([snapshot, animation, agent])
    }
}

// Select a vault key only for an explicit send/test, never during selection.
async fn selected_key(provider: Provider, cursor: usize) -> Result<Zeroizing<String>, String> {
    if !provider.needs_key() { return Ok(Zeroizing::new(String::new())); }
    if provider == Provider::Custom {
        let has_keys = tokio::task::spawn_blocking(|| Vault::os().list(Provider::Custom)).await
            .map_err(|_| VaultError::Unavailable).and_then(|r| r).map_err(|e| e.message().to_owned())?;
        if has_keys.is_empty() { return Ok(Zeroizing::new(String::new())); }
    }
    tokio::task::spawn_blocking(move || {
        let vault = Vault::os();
        let keys = vault.list(provider)?;
        let key_id = keys.get(cursor % keys.len().max(1)).copied().ok_or(VaultError::MissingKey)?;
        vault.with_key(provider, key_id, |secret| Zeroizing::new(secret.to_owned()))
    }).await.map_err(|_| VaultError::Unavailable)
        .and_then(|result| result).map_err(|error| error.message().to_owned())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn model_setup_is_session_only_and_other_modes_cannot_send() {
        let mut app = App::new();
        let _ = app.update(Message::Navigate(Page::Settings));
        let _ = app.update(Message::SettingsSection(Section::Models));
        let _ = app.update(Message::EditModel("vendor/model:free".into()));
        let _ = app.update(Message::AddModel);
        assert_eq!(app.settings.selected_model(), None);
        let _ = app.update(Message::ChooseModel(0));
        assert_eq!(app.settings.selected_model(), Some("vendor/model:free"));
        let _ = app.update(Message::Navigate(Page::Agent));
        let _ = app.update(Message::SelectMode(3));
        let _ = app.update(Message::EditDraft(1, SecretText::new("private unsent".into())));
        let _ = app.update(Message::SendChat);
        assert!(app.drafts[0].turns.is_empty());
        assert_eq!(App::new().settings.selected_model(), None);
    }

    #[test]
    fn catalog_requires_individual_add_and_ignores_stale_provider_results() {
        let mut app = App::new();
        let _ = app.update(Message::Navigate(Page::Settings));
        let _ = app.update(Message::SettingsSection(Section::Models));
        let model = CatalogModel { id: "vendor/model:free".into(), name: "Free model".into(), free: true, router: false, reasoning: false };
        let _ = app.update(Message::ModelsFetched(Provider::OpenRouter, 0, Ok(vec![model.clone()])));
        assert_eq!(app.settings.catalog[0].len(), 1);
        assert!(app.settings.models[0].is_empty());
        let _ = app.update(Message::SearchModels("free".into()));
        assert_eq!(app.settings.search, "free");
        let _ = app.update(Message::AddCatalogModel(Provider::OpenRouter, 0));
        let _ = app.update(Message::AddCatalogModel(Provider::OpenRouter, 0));
        assert_eq!(app.settings.models[0], vec![model.id]);
        let _ = app.update(Message::SelectProvider(Provider::Gemini));
        let _ = app.update(Message::ModelsFetched(Provider::OpenRouter, 0, Ok(Vec::new())));
        assert_eq!(app.settings.catalog[0].len(), 1);
        assert!(app.settings.models[2].is_empty());
    }

    #[test]
    fn catalog_import_is_unchecked_and_never_probes_without_confirmation() {
        let mut app = App::new();
        let _ = app.update(Message::Navigate(Page::Settings));
        app.settings.catalog[0] = vec![CatalogModel {
            id: "vendor/one:free".into(), name: "One".into(), free: true, router: false, reasoning: false,
        }, CatalogModel {
            id: "vendor/two".into(), name: "Two".into(), free: false, router: false, reasoning: false,
        }];
        assert!(app.settings.catalog_selected[0].is_empty());
        let _ = app.update(Message::ImportSelectedModels);
        assert!(app.settings.models[0].is_empty());
        let _ = app.update(Message::ToggleCatalogSelection(Provider::OpenRouter, 1));
        assert_eq!(app.settings.catalog_selected[0], vec!["vendor/two"]);
        let _ = app.update(Message::ImportSelectedModels);
        assert_eq!(app.settings.models[0], vec!["vendor/two"]);
        assert_eq!(app.settings.chosen[0], None);
        assert!(!app.settings.probe_busy && !app.settings.probe_pending);
        let _ = app.update(Message::ToggleCatalogSelection(Provider::OpenRouter, 0));
        let _ = app.update(Message::RequestCatalogProbe);
        assert!(app.settings.probe_pending);
        assert!(!app.settings.probe_busy);
        let _ = app.update(Message::CancelCatalogProbe);
        assert!(!app.settings.probe_pending);
    }

    #[test]
    fn chat_setup_opens_unified_settings_and_chat_can_switch_models() {
        let mut app = App::new();
        let _ = app.update(Message::Navigate(Page::Agent));
        let _ = app.update(Message::OpenModelSettings);
        assert_eq!(app.page, Page::Settings);
        assert_eq!(app.settings.section, Section::Providers);
        let _ = app.update(Message::EditModel("vendor/first".into()));
        let _ = app.update(Message::AddModel);
        let _ = app.update(Message::EditModel("vendor/second".into()));
        let _ = app.update(Message::AddModel);
        let _ = app.update(Message::Navigate(Page::Agent));
        let _ = app.update(Message::ChooseModel(0));
        assert_eq!(app.settings.selected_model(), Some("vendor/first"));
        let _ = app.update(Message::SelectProvider(Provider::Gemini));
        assert_eq!(app.settings.selected_model(), None);
        let _ = app.update(Message::SelectProvider(Provider::OpenRouter));
        assert_eq!(app.settings.selected_model(), Some("vendor/first"));
        assert!(app.settings.stream_chat);
        let _ = app.update(Message::ToggleStreaming);
        assert!(!app.settings.stream_chat);
    }

    #[test]
    fn chat_picker_stays_collapsed_until_opened_and_closes_after_choice() {
        let mut app = App::new();
        let _ = app.update(Message::Navigate(Page::Agent));
        assert!(!app.model_menu_open);
        let _ = app.update(Message::ToggleModelMenu);
        assert!(app.model_menu_open);
        let _ = app.update(Message::SearchChatModels("demo".into()));
        assert_eq!(app.chat_model_search, "demo");
        app.settings.models[0].push("demo/model".into());
        let _ = app.update(Message::ChooseModel(0));
        assert_eq!(app.settings.selected_model(), Some("demo/model"));
        assert!(!app.model_menu_open);
        let _ = app.update(Message::ToggleModeMenu);
        assert!(app.mode_menu_open);
        let _ = app.update(Message::SelectMode(2));
        assert!(!app.mode_menu_open);
    }

    #[test]
    fn interrupted_stream_keeps_received_text_but_excludes_it_from_context() {
        let mut app = App::new();
        let _ = app.update(Message::Navigate(Page::Agent));
        app.drafts[0].busy = true;
        app.drafts[0].turns.push(Turn { role: "user", content: "Prompt".into() });
        let _ = app.update(Message::ChatProgress(1, SecretReply(Reply {
            content: "Received paragraph".into(), reasoning: Some("Returned reasoning".into()),
        })));
        let _ = app.update(Message::ChatResult(1, Err("Stopped".into())));
        assert_eq!(app.drafts[0].turns[1].content, "Received paragraph");
        assert_eq!(app.drafts[0].incomplete_slots, vec![1]);
        assert!(!app.drafts[0].busy);
        assert_eq!(app.drafts[0].error.as_deref(), Some("Stopped"));
    }

    #[test]
    fn failed_send_restores_draft_without_reusing_it_as_hidden_context() {
        let mut app = App::new();
        app.drafts[0].busy = true;
        app.drafts[0].turns.push(Turn { role: "user", content: "synthetic prompt".into() });
        let _ = app.update(Message::ChatResult(1, Err("synthetic transport failure".into())));
        assert!(!app.drafts[0].busy);
        assert_eq!(app.drafts[0].text, "synthetic prompt");
        assert!(app.drafts[0].turns.is_empty());
    }

    #[test]
    fn a_pending_key_write_blocks_duplicate_submissions_and_provider_switches() {
        let mut app = App::new();
        let _ = app.update(Message::Navigate(Page::Settings));
        let _ = app.update(Message::EditKey(SecretText::new("synthetic-key".into())));
        let _ = app.update(Message::SaveKey); // Task is not run in this state test.
        assert!(app.settings.key_busy);
        assert!(app.settings.key_entry.0.is_empty());
        let _ = app.update(Message::SelectProvider(Provider::Gemini));
        assert_eq!(app.settings.provider, Provider::OpenRouter);
        let _ = app.update(Message::SaveKey);
        let _ = app.update(Message::KeySaved(Provider::OpenRouter, Err(VaultError::Unavailable)));
        assert!(!app.settings.key_busy);
    }

    #[test]
    fn sensitive_messages_redact_their_debug_representation() {
        let message = Message::EditKey(SecretText::new("synthetic-private-value".into()));
        assert!(!format!("{message:?}").contains("synthetic-private-value"));
    }

    #[test]
    fn navigation_changes_only_to_available_pages() {
        let mut app = App::new();
        assert_eq!(app.page, Page::Home);
        let _ = app.update(Message::Navigate(Page::About));
        assert_eq!(app.page, Page::About);
        let _ = app.update(Message::Navigate(Page::Home));
        assert_eq!(app.page, Page::Home);
    }

    #[test]
    fn agent_kinetic_type_cycles_only_on_home() {
        let mut app = App::new();
        for _ in 0..MODE_COUNT - 1 {
            let _ = app.update(Message::AgentPulse);
        }
        assert_eq!(app.agent_phase, MODE_COUNT - 1);
        let _ = app.update(Message::AgentPulse);
        assert_eq!(app.agent_phase, 0);
        let _ = app.update(Message::Navigate(Page::About));
        let _ = app.update(Message::AgentPulse);
        assert_eq!(app.agent_phase, 0);
    }

    #[test]
    fn session_only_drafts_keep_separate_mode_previews() {
        let mut app = App::new();
        let _ = app.update(Message::Navigate(Page::Agent));
        let _ = app.update(Message::SelectMode(3));
        assert_eq!(app.drafts[0].mode, 3);
        let _ = app.update(Message::NewChat);
        assert_eq!(app.drafts.len(), 2);
        assert_eq!(app.selected_draft, 2);
        assert_eq!(app.drafts[1].mode, 0);
        let _ = app.update(Message::SelectMode(6));
        assert_eq!(app.drafts[1].mode, 0);
        let _ = app.update(Message::OpenChat(77));
        assert_eq!(app.selected_draft, 2);
        let _ = app.update(Message::OpenChat(1));
        assert_eq!(app.drafts[0].mode, 3);
        assert_eq!(app.selected_draft, 1);
    }

    #[test]
    fn shared_sidebar_toggle_survives_navigation_and_reopens() {
        let mut app = App::new();
        assert!(app.sidebar_expanded);
        let _ = app.update(Message::ToggleSidebar);
        assert!(!app.sidebar_expanded);
        let _ = app.update(Message::Navigate(Page::Agent));
        let _ = app.update(Message::Navigate(Page::Settings));
        assert!(!app.sidebar_expanded);
        let _ = app.update(Message::ToggleSidebar);
        assert!(app.sidebar_expanded);
        assert_eq!(app.page, Page::Settings);
    }

    #[test]
    fn unsent_input_stays_in_its_session_draft_and_cannot_be_submitted() {
        let mut app = App::new();
        let _ = app.update(Message::Navigate(Page::Agent));
        let _ = app.update(Message::EditDraft(1, SecretText::new("First idea ✓".into())));
        let _ = app.update(Message::NewChat);
        assert!(app.drafts[1].text.is_empty());
        let _ = app.update(Message::EditDraft(1, SecretText::new("wrong draft".into())));
        let _ = app.update(Message::EditDraft(2, SecretText::new("Second idea".into())));
        let _ = app.update(Message::OpenChat(1));
        assert_eq!(app.drafts[0].text, "First idea ✓");
        assert_eq!(app.drafts[1].text, "Second idea");
        let _ = app.update(Message::ClearDraft(2));
        assert_eq!(app.drafts[1].text, "Second idea");
        let _ = app.update(Message::ClearDraft(1));
        assert!(app.drafts[0].text.is_empty());
        assert!(App::new().drafts[0].text.is_empty());
    }

    #[test]
    fn memory_preview_never_changes_outside_shared_settings() {
        let mut app = App::new();
        let _ = app.update(Message::MemoryPreview(MemoryMode::Heavy));
        assert_eq!(app.memory_preview, MemoryMode::Light);
        let _ = app.update(Message::Navigate(Page::Settings));
        let _ = app.update(Message::MemoryPreview(MemoryMode::Custom));
        let _ = app.update(Message::ToggleAgentPreview);
        assert!(app.keep_agent_preview);
        let _ = app.update(Message::Navigate(Page::Agent));
        let _ = app.update(Message::ToggleAgentPreview);
        assert!(app.keep_agent_preview);
        assert_eq!(App::new().memory_preview, MemoryMode::Light);
    }

    #[test]
    fn type_motion_only_runs_while_an_unavailable_card_is_hovered() {
        let mut app = App::new();
        let _ = app.update(Message::TileHover(Art::Agent, true));
        let _ = app.update(Message::Animate);
        assert_eq!(app.phase, 0);
        let _ = app.update(Message::TileHover(Art::Training, true));
        let _ = app.update(Message::Animate);
        assert_eq!(app.phase, 1);
        let _ = app.update(Message::TileHover(Art::Training, false));
        let _ = app.update(Message::Animate);
        assert_eq!(app.phase, 0);
        let _ = app.update(Message::TileHover(Art::Tuning, true));
        let _ = app.update(Message::Navigate(Page::About));
        let _ = app.update(Message::Animate);
        assert_eq!(app.hovered, None);
        assert_eq!(app.phase, 0);
    }
}
