//! Purpose: The Agent app's single view entry: it renders whichever surface (chat, settings, debug) is open.
//!
//! The launcher owns the window, the app tiles and its own settings. This module
//! only decides between the Agent's own surfaces, so adding a surface means a
//! new function here — never a launcher change.

use iced::Element;
use iced::widget::container;

use crate::agent;
use crate::app::{App, Message};
use archx_shared::style;

pub fn view(app: &App) -> Element<'_, Message> {
    container(agent::surface(app))
        .width(iced::Fill)
        .height(iced::Fill)
        .style(style::canvas)
        .into()
}

/// Text scale for the Agent surfaces, exposed so the launcher can read it
/// without reaching into `App`'s private state.
pub fn chat_scale(app: &App) -> f32 {
    app.display.chat.factor()
}
