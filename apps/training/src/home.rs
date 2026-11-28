//! Purpose: Exposes the single manifest-declared `home::view` entry point rendered by Archx AI Lab.

use iced::Element;
use iced::widget::container;

use archx_shared::style;

use crate::app::{App, Message};
use crate::views;

/// Manifest-declared entry function (`view = "home::view"` in `apps/training/app.toml`).
pub fn view(app: &App) -> Element<'_, Message> {
    container(views::root_view(app))
        .width(iced::Fill)
        .height(iced::Fill)
        .style(style::canvas)
        .into()
}
