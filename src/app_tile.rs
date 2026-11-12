//! Purpose: Renders three unavailable AI apps with distinct Agent and model-workspace typography.
use iced::widget::{column, container, mouse_area, row, space, text};
use iced::{Element, Fill, FillPortion};

use crate::agent_visual;
use crate::app::Message;
use crate::style;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Art {
    Agent,
    Training,
    Tuning,
}

pub struct AppTile {
    pub name: &'static str,
    pub category: &'static str,
    pub art: Art,
}

pub const APPS: [AppTile; 3] = [
    AppTile { name: "Archx Agent", category: "SIX MODES / ONE AGENT", art: Art::Agent },
    AppTile { name: "Model Training", category: "BUILD MODELS", art: Art::Training },
    AppTile { name: "Fine-tuning", category: "REFINE MODELS", art: Art::Tuning },
];

pub fn view(tile: &'static AppTile, phase: u8, agent_phase: u8) -> Element<'static, Message> {
    let cover: Element<'static, Message> = match tile.art {
        Art::Agent => agent_visual::tile(agent_phase),
        Art::Training | Art::Tuning => {
            let (eyebrow, headline, steps) = match tile.art {
                Art::Training => ("MODEL / TRAINING", "Build from data.", ["DATA", "LEARN", "REVIEW"]),
                Art::Tuning => ("MODEL / FINE-TUNING", "Refine what's there.", ["BASE", "ADAPT", "CHECK"]),
                Art::Agent => unreachable!(),
            };
            let stages = steps.into_iter().enumerate().fold(row![].spacing(16), |row, (index, label)| {
                row.push(text(label).size(11).color(if index == phase as usize { style::WHITE } else { style::DIM }))
            });
            let panel = container(
                column![
                    text(eyebrow).size(10).color(style::GREY),
                    space().height(18),
                    text(headline).size(23).color(style::WHITE),
                    space().height(Fill),
                    stages
                ]
                .width(Fill)
                .height(Fill)
                .padding(19),
            )
            .width(Fill)
            .height(140)
            .clip(true)
            .style(style::cover);

            mouse_area(panel)
                .on_enter(Message::TileHover(tile.art, true))
                .on_exit(Message::TileHover(tile.art, false))
                .into()
        }
    };

    column![
        cover,
        space().height(14),
        text(tile.category).size(10).color(style::DIM),
        space().height(5),
        text(tile.name).size(17).color(style::WHITE),
        space().height(5),
        text("COMING LATER").size(11).color(style::GREY)
    ]
    .width(FillPortion(1))
    .into()
}

#[cfg(test)]
mod tests {
    use super::{Art, APPS};
    use std::collections::HashSet;

    #[test]
    fn app_tiles_have_unique_names_and_only_the_agreed_destinations() {
        let names: HashSet<_> = APPS.iter().map(|app| app.name).collect();
        assert_eq!(names.len(), APPS.len());
        assert_eq!(APPS.len(), 3);
        assert!(APPS.iter().all(|app| app.art != Art::Agent || app.name == "Archx Agent"));
    }

}
