//! Purpose: Presents shared Lab preferences as an honest, non-persistent UI preview.
use iced::widget::{button, column, container, row, scrollable, space, text};
use iced::{Element, Fill};

use crate::app::{MemoryMode, Message};
use crate::style;

fn choice(label: &'static str, value: MemoryMode, active: bool) -> Element<'static, Message> {
    button(text(label).size(13).color(if active { style::WHITE } else { style::GREY }))
        .width(Fill)
        .padding([14, 16])
        .on_press(Message::MemoryPreview(value))
        .style(move |theme, status| style::nav(active, theme, status))
        .into()
}

pub fn view(memory: MemoryMode, keep_agent: bool) -> Element<'static, Message> {
    let custom = if memory == MemoryMode::Custom {
        column![
            text("CUSTOM  /  DESTINATIONS").size(11).color(style::DIM),
            space().height(12),
            button(text(if keep_agent { "Archx Agent    /    Keep ready" } else { "Archx Agent    /    Load on open" })
                .size(14).color(style::WHITE))
                .width(Fill)
                .padding([15, 17])
                .on_press(Message::ToggleAgentPreview)
                .style(style::quiet_button),
            space().height(11),
            text("Model Training and Fine-tuning will appear here when built.")
                .size(12).color(style::DIM)
        ]
    } else {
        column![
            text("CUSTOM  /  DESTINATIONS").size(11).color(style::DIM),
            space().height(12),
            text("Choose Custom to preview per-destination controls.")
                .size(13).color(style::GREY)
        ]
    };
    let content = column![
        text("LAB SETTINGS  /  SHARED ACROSS WORKSPACES").size(11).color(style::DIM),
        space().height(18),
        text("Make room for what matters.").size(32).font(style::DISPLAY).color(style::WHITE),
        space().height(10),
        text("One settings home for the Lab. Each destination remains its own experience.")
            .size(14).color(style::GREY),
        space().height(28),
        container(
            column![
                text("MEMORY  /  PREVIEW").size(11).color(style::DIM),
                space().height(14),
                text("Choose how the Lab should use memory later.")
                    .size(20).font(style::DISPLAY).color(style::WHITE),
                space().height(12),
                text("These controls are a layout preview. They do not save a preference, preload a model or change RAM use yet.")
                    .size(13).color(style::GREY),
                space().height(22),
                row![
                    choice("Memory Light", MemoryMode::Light, memory == MemoryMode::Light),
                    choice("Memory Heavy", MemoryMode::Heavy, memory == MemoryMode::Heavy),
                    choice("Custom", MemoryMode::Custom, memory == MemoryMode::Custom)
                ].spacing(9),
                space().height(23),
                custom
            ]
            .width(Fill)
            .padding(25)
        )
        .width(Fill)
        .style(style::surface),
        space().height(18),
        text("Memory Light: open on demand, release on exit.  /  Memory Heavy: keep ready.  /  Custom: choose per destination.")
            .size(12).color(style::DIM)
    ]
    .width(Fill)
    .padding(36);
    scrollable(content).width(Fill).height(Fill).into()
}
