//! Purpose: Owns home-shell navigation state and opt-in cross-platform screenshot capture.
use std::path::PathBuf;
use std::time::Duration;

use iced::time;
use iced::window;
use iced::{Element, Subscription, Task};

use crate::app_tile::Art;
use crate::home;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Page {
    Home,
    About,
}

#[derive(Debug, Clone)]
pub enum Message {
    Navigate(Page),
    TileHover(Art, bool),
    Animate,
    SnapshotTick,
    SnapshotReady(window::screenshot::Screenshot),
}

pub struct App {
    page: Page,
    snapshot: Option<PathBuf>,
    snapshot_requested: bool,
    hovered: Option<Art>,
    phase: u8,
    frozen_snapshot_phase: bool,
}

impl App {
    pub fn new() -> Self {
        let snapshot = std::env::var_os("ARCHX_SNAPSHOT").map(PathBuf::from);
        let page = if snapshot.is_some()
            && std::env::var("ARCHX_SNAPSHOT_PAGE").as_deref() == Ok("about")
        {
            Page::About
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
        Self {
            page,
            snapshot,
            snapshot_requested: false,
            hovered: preview_art,
            phase: phase.unwrap_or(0),
            frozen_snapshot_phase: phase.is_some(),
        }
    }

    pub fn update(&mut self, message: Message) -> Task<Message> {
        match message {
            Message::Navigate(page) => {
                self.page = page;
                self.hovered = None;
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
        home::view(self.page, self.hovered, self.phase)
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
        Subscription::batch([snapshot, animation])
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
