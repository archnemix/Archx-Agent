//! Purpose: Describes and renders the launcher’s clearly unavailable AI app tiles.
use iced::widget::{column, container, row, space, text};
use iced::{Center, Element, Fill, FillPortion};

use crate::app::Message;
use crate::style;

pub struct AppTile {
    pub index: &'static str,
    pub letter: &'static str,
    pub name: &'static str,
    pub category: &'static str,
}

pub const APPS: [AppTile; 4] = [
    AppTile { index: "01", letter: "A", name: "Archx Agent", category: "CHAT & AGENTS" },
    AppTile { index: "02", letter: "M", name: "Model Training", category: "BUILD MODELS" },
    AppTile { index: "03", letter: "F", name: "Fine-tuning", category: "REFINE MODELS" },
    AppTile { index: "04", letter: "O", name: "Model Monitor", category: "OBSERVE MODELS" },
];

pub fn view(tile: &'static AppTile) -> Element<'static, Message> {
    let cover = container(
        column![
            row![
                text(tile.index).size(12).color(style::GREY).width(Fill),
                text("ARCHX / LAB").size(10).color(style::DIM)
            ]
            .align_y(Center),
            space().height(Fill),
            text(tile.letter).size(62).color(style::WHITE)
        ]
        .width(Fill)
        .height(144),
    )
    .width(Fill)
    .height(176)
    .padding(16)
    .style(style::cover);

    column![
        cover,
        space().height(15),
        text(tile.category).size(10).color(style::DIM),
        space().height(6),
        text(tile.name).size(17).color(style::WHITE),
        space().height(6),
        text("COMING LATER").size(11).color(style::GREY)
    ]
    .width(FillPortion(1))
    .into()
}

#[cfg(test)]
mod tests {
    use super::APPS;
    use std::collections::HashSet;

    #[test]
    fn app_tiles_have_unique_names_and_ordered_slots() {
        let names: HashSet<_> = APPS.iter().map(|app| app.name).collect();
        assert_eq!(names.len(), APPS.len());
        assert_eq!(APPS.iter().map(|app| app.index).collect::<Vec<_>>(), ["01", "02", "03", "04"]);
    }
}
