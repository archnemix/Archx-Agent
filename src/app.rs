//! Purpose: Owns home-shell navigation state and opt-in cross-platform screenshot capture.
use std::path::PathBuf;
use std::time::Duration;

use iced::time;
use iced::window;
use iced::{Element, Subscription, Task};

use crate::agent_visual::MODE_COUNT;
use crate::app_tile::Art;
use crate::home;
use crate::credentials::{Provider, Vault, VaultError};
use crate::provider_api::{self, Turn, CallError};
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

#[derive(Debug, Clone)]
pub struct ChatDraft {
    pub id: u32,
    pub mode: u8,
    pub text: String,
    pub turns: Vec<Turn>,
    pub busy: bool,
    pub error: Option<String>,
}

#[derive(Debug, Clone)]
pub enum Message {
    Navigate(Page),
    ToggleSidebar,
    NewChat,
    OpenChat(u32),
    SelectMode(u8),
    EditDraft(u32, SecretText),
    ClearDraft(u32),
    MemoryPreview(MemoryMode),
    ToggleAgentPreview,
    TileHover(Art, bool),
    Animate,
    AgentPulse,
    SettingsSection(Section),
    SelectProvider(Provider),
    EditKey(SecretText),
    SaveKey,
    KeySaved(Provider, Result<u64, VaultError>),
    RefreshKeys,
    KeysLoaded(Provider, Result<Vec<u64>, VaultError>),
    RemoveKey(u64),
    KeyRemoved(Provider, Result<(), VaultError>),
    RevealKey(u64),
    KeyRevealed(u64, u64, Result<SecretText, VaultError>),
    RevealExpired(u64),
    EditModel(String),
    AddModel,
    ChooseModel(usize),
    RemoveModel(usize),
    SendChat,
    ChatResult(u32, Result<SecretText, String>),
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
    memory_preview: MemoryMode,
    settings: SettingsState,
    key_cursor: [usize; 3],
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
                Ok("models") => Section::Models,
                _ if preview_memory == MemoryMode::Custom => Section::Lab,
                _ => Section::Providers,
            };
        }
        Self {
            page,
            sidebar_expanded: !(snapshot.is_some()
                && std::env::var("ARCHX_SNAPSHOT_SIDEBAR").as_deref() == Ok("collapsed")),
            drafts: vec![ChatDraft { id: 1, mode: preview_mode, text: preview_text, turns: Vec::new(), busy: false, error: None }],
            selected_draft: 1,
            memory_preview: preview_memory,
            settings,
            key_cursor: [0; 3],
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
                if page != Page::Settings { self.settings.clear_secret(); }
                self.page = page;
                self.hovered = None;
                if page == Page::Settings { return self.update(Message::RefreshKeys); }
            }
            Message::ToggleSidebar => {
                self.sidebar_expanded = !self.sidebar_expanded;
            }
            Message::NewChat if self.page == Page::Agent => {
                let id = self.drafts.last().map_or(1, |draft| draft.id + 1);
                self.drafts.push(ChatDraft { id, mode: 0, text: String::new(), turns: Vec::new(), busy: false, error: None });
                self.selected_draft = id;
            }
            Message::OpenChat(id) if self.page == Page::Agent && self.drafts.iter().any(|draft| draft.id == id) => {
                self.selected_draft = id;
            }
            Message::SelectMode(mode) if self.page == Page::Agent && mode < MODE_COUNT => {
                if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == self.selected_draft) {
                    draft.mode = mode;
                }
            }
            Message::EditDraft(id, text) if self.page == Page::Agent && self.selected_draft == id => {
                if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == id) {
                    if !draft.busy && text.0.chars().count() <= 4000 { draft.text = text.0.to_string(); }
                }
            }
            Message::ClearDraft(id) if self.page == Page::Agent && self.selected_draft == id => {
                if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == id) {
                    if !draft.busy { draft.text.clear(); }
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
                self.settings.section = section;
            }
            Message::SelectProvider(provider) if self.page == Page::Settings => {
                self.settings.clear_secret();
                self.settings.provider = provider;
                self.settings.model_entry.clear();
                self.settings.key_ids.clear();
                self.settings.status.clear();
                return self.update(Message::RefreshKeys);
            }
            Message::EditKey(value) if self.page == Page::Settings && self.settings.section == Section::Providers => {
                if value.0.len() <= 1024 { self.settings.key_entry = value; }
            }
            Message::SaveKey if self.page == Page::Settings && self.settings.section == Section::Providers => {
                let provider = self.settings.provider;
                let secret = std::mem::take(&mut self.settings.key_entry).0;
                self.settings.clear_secret();
                self.settings.status = "Saving to the OS vault…".into();
                return Task::perform(async move {
                    tokio::task::spawn_blocking(move || Vault::os().add(provider, secret))
                        .await.unwrap_or(Err(VaultError::Unavailable))
                }, move |result| Message::KeySaved(provider, result));
            }
            Message::KeySaved(provider, result) if self.page == Page::Settings && self.settings.provider == provider => {
                self.settings.status = match result {
                    Ok(_) => "Saved to OS vault. Select a model before chatting.".into(),
                    Err(error) => error.message().into(),
                };
                return self.update(Message::RefreshKeys);
            }
            Message::RefreshKeys if self.page == Page::Settings => {
                let provider = self.settings.provider;
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
            Message::RemoveKey(id) if self.page == Page::Settings && self.settings.key_ids.contains(&id) => {
                self.settings.clear_secret();
                let provider = self.settings.provider;
                return Task::perform(async move {
                    tokio::task::spawn_blocking(move || Vault::os().remove(provider, id))
                        .await.unwrap_or(Err(VaultError::Unavailable))
                }, move |result| Message::KeyRemoved(provider, result));
            }
            Message::KeyRemoved(provider, result) if self.page == Page::Settings && self.settings.provider == provider => {
                self.settings.status = match result { Ok(()) => "Key removed from OS vault.".into(), Err(error) => error.message().into() };
                return self.update(Message::RefreshKeys);
            }
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
            Message::EditModel(model) if self.page == Page::Settings && self.settings.section == Section::Models => {
                if model.len() <= 100 { self.settings.model_entry = model; }
            }
            Message::AddModel if self.page == Page::Settings && self.settings.section == Section::Models => {
                let provider = self.settings.provider;
                let model = self.settings.model_entry.trim().to_owned();
                let index = self.settings.index();
                if provider_api::valid_model(provider, &model) && !self.settings.models[index].contains(&model) && self.settings.models[index].len() < 32 {
                    self.settings.models[index].push(model);
                    self.settings.chosen[index] = Some(self.settings.models[index].len() - 1);
                    self.settings.model_entry.clear();
                    self.settings.status = "Model selected for this session. Live requests may incur charges.".into();
                } else { self.settings.status = "Invalid, duplicate or over-limit model ID.".into(); }
            }
            Message::ChooseModel(slot) if self.page == Page::Settings && slot < self.settings.models[self.settings.index()].len() => {
                let index = self.settings.index(); self.settings.chosen[index] = Some(slot);
            }
            Message::RemoveModel(slot) if self.page == Page::Settings && slot < self.settings.models[self.settings.index()].len() => {
                let index = self.settings.index();
                self.settings.models[index].remove(slot);
                self.settings.chosen[index] = None;
            }
            Message::SendChat if self.page == Page::Agent => return self.send_chat(false),
            Message::RunTest if self.page == Page::Settings && !self.settings.test_busy => return self.send_chat(true),
            Message::ChatResult(id, result) => {
                if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == id) {
                    draft.busy = false;
                    match result {
                        Ok(reply) => draft.turns.push(Turn { role: "assistant", content: reply.0.to_string() }),
                        Err(error) => draft.error = Some(error),
                    }
                }
            }
            Message::TestResult(result) => {
                self.settings.test_busy = false;
                self.settings.status = match result {
                    Ok(_) => "Generation test succeeded; the provider returned text. This call may be billable.".into(),
                    Err(error) => error,
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
            let notice = "Select a provider and model in Settings → Models first.";
            if test { self.settings.status = notice.into(); }
            else if let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == self.selected_draft) { draft.error = Some(notice.into()); }
            return Task::none();
        };
        let index = self.settings.index();
        let cursor = self.key_cursor[index];
        let id = self.selected_draft;
        let turns = if test {
            self.settings.test_busy = true;
            self.settings.status = "Sending a small billable generation test…".into();
            vec![Turn { role: "user", content: "Reply with the word OK.".into() }]
        } else {
            let Some(draft) = self.drafts.iter_mut().find(|draft| draft.id == id) else { return Task::none(); };
            if draft.mode != 0 || draft.busy || draft.text.trim().is_empty() || draft.text.chars().count() > 4000 { return Task::none(); }
            draft.error = None;
            draft.busy = true;
            draft.turns.push(Turn { role: "user", content: std::mem::take(&mut draft.text) });
            draft.turns.iter().rev().take(12).cloned().collect::<Vec<_>>().into_iter().rev().collect()
        };
        self.key_cursor[index] = cursor.wrapping_add(1);
        let task = async move {
            let selected = tokio::task::spawn_blocking(move || {
                let vault = Vault::os();
                let keys = vault.list(provider)?;
                let key_id = keys.get(cursor % keys.len().max(1)).copied().ok_or(VaultError::MissingKey)?;
                vault.with_key(provider, key_id, |secret| Zeroizing::new(secret.to_owned()))
            }).await.map_err(|_| VaultError::Unavailable)
                .and_then(|result| result).map_err(|error| error.message().to_owned())?;
            provider_api::send(provider, model, selected, turns).await.map_err(CallError::message)
        };
        if test { Task::perform(task, |result| Message::TestResult(result.map(SecretText::new))) }
        else { Task::perform(task, move |result| Message::ChatResult(id, result.map(SecretText::new))) }
    }

    pub fn view(&self) -> Element<'_, Message> {
        home::view(self.page, self.sidebar_expanded, self.hovered, self.phase, self.agent_phase, &self.drafts, self.selected_draft, self.memory_preview, self.keep_agent_preview, &self.settings)
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
        assert_eq!(app.settings.selected_model(), Some("vendor/model:free"));
        let _ = app.update(Message::Navigate(Page::Agent));
        let _ = app.update(Message::SelectMode(3));
        let _ = app.update(Message::EditDraft(1, SecretText::new("private unsent".into())));
        let _ = app.update(Message::SendChat);
        assert!(app.drafts[0].turns.is_empty());
        assert_eq!(App::new().settings.selected_model(), None);
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
