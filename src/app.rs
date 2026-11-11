//! Purpose: Owns home-shell navigation state and opt-in cross-platform screenshot capture.
use std::path::PathBuf;
use std::time::Duration;

use iced::time;
use iced::window;
use iced::{Element, Subscription, Task};

use crate::home;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Page {
    Home,
    About,
}

#[derive(Debug, Clone)]
pub enum Message {
    Navigate(Page),
    SnapshotTick,
    SnapshotReady(window::screenshot::Screenshot),
}

pub struct App {
    page: Page,
    snapshot: Option<PathBuf>,
    snapshot_requested: bool,
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
        Self { page, snapshot, snapshot_requested: false }
    }

    pub fn update(&mut self, message: Message) -> Task<Message> {
        match message {
            Message::Navigate(page) => self.page = page,
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
        home::view(self.page)
    }

    pub fn subscription(&self) -> Subscription<Message> {
        if self.snapshot.is_some() && !self.snapshot_requested {
            time::every(Duration::from_secs(5)).map(|_| Message::SnapshotTick)
        } else {
            Subscription::none()
        }
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
}
