//! Purpose: Owns home-shell navigation state and opt-in cross-platform screenshot capture.
use std::path::PathBuf;
use std::time::Duration;

use iced::time;
use iced::window;
use iced::{Element, Subscription, Task};

use crate::agent_visual::MODE_COUNT;
use crate::app_tile::Art;
use crate::home;

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

#[derive(Debug, Clone, Copy)]
pub struct ChatDraft {
    pub id: u32,
    pub mode: u8,
}

#[derive(Debug, Clone)]
pub enum Message {
    Navigate(Page),
    NewChat,
    OpenChat(u32),
    SelectMode(u8),
    MemoryPreview(MemoryMode),
    ToggleAgentPreview,
    TileHover(Art, bool),
    Animate,
    AgentPulse,
    SnapshotTick,
    SnapshotReady(window::screenshot::Screenshot),
}

pub struct App {
    page: Page,
    drafts: Vec<ChatDraft>,
    selected_draft: u32,
    memory_preview: MemoryMode,
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
        Self {
            page,
            drafts: vec![ChatDraft { id: 1, mode: preview_mode }],
            selected_draft: 1,
            memory_preview: preview_memory,
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
                self.page = page;
                self.hovered = None;
            }
            Message::NewChat if self.page == Page::Agent => {
                let id = self.drafts.last().map_or(1, |draft| draft.id + 1);
                self.drafts.push(ChatDraft { id, mode: 0 });
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

    pub fn view(&self) -> Element<'_, Message> {
        home::view(self.page, self.hovered, self.phase, self.agent_phase, &self.drafts, self.selected_draft, self.memory_preview, self.keep_agent_preview)
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
