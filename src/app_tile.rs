//! Purpose: Renders unavailable AI workspaces with distinct kinetic typography on hover.
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

struct Workbench {
    eyebrow: &'static str,
    footer: &'static str,
    words: [&'static str; 3],
}

fn workbench(art: Art) -> Workbench {
    match art {
        Art::Training => Workbench {
            eyebrow: "MODEL FORGE",
            footer: "TRAINING LAB",
            words: ["DESIGN", "TRAIN", "EVALUATE"],
        },
        Art::Tuning => Workbench {
            eyebrow: "REFINEMENT STUDIO",
            footer: "FINE-TUNING LAB",
            words: ["SELECT", "ADAPT", "VALIDATE"],
        },
        Art::Agent => unreachable!("The Agent has its own visual"),
    }
}

fn stage_markers(phase: u8) -> iced::widget::Row<'static, Message> {
    (0..3)
        .fold(row![].spacing(5), |row, index| {
            row.push(
                container(space().height(2))
                    .width(FillPortion(1))
                    .style(move |theme| style::mode_marker(theme, index == phase % 3)),
            )
        })
        .width(Fill)
}

pub fn view(tile: &'static AppTile, phase: u8, agent_phase: u8) -> Element<'static, Message> {
    let artwork: Element<'static, Message> = match tile.art {
        Art::Agent => agent_visual::tile(agent_phase),
        Art::Training | Art::Tuning => {
            let copy = workbench(tile.art);
            let panel = container(
                column![
                    text(copy.eyebrow)
                        .size(style::TYPE_LABEL)
                        .font(style::LABEL)
                        .color(style::GREY),
                    space().height(style::SPACE_1),
                    text(copy.words[usize::from(phase % 3)])
                        .size(35)
                        .font(style::DISPLAY_BOLD)
                        .color(style::WHITE),
                    space().height(Fill),
                    row![
                        text(copy.footer).size(10).font(style::LABEL).color(style::DIM).width(Fill),
                        text(format!("{:02} / 03", phase % 3 + 1)).size(10).color(style::GREY)
                    ],
                    space().height(style::SPACE_1),
                    stage_markers(phase)
                ]
                .width(Fill)
                .height(Fill)
                .padding(style::SPACE_2),
            )
            .width(Fill)
            .height(140)
            .clip(true)
            .style(move |theme| style::workbench_surface(theme, tile.art == Art::Tuning));

            mouse_area(panel)
                .on_enter(Message::TileHover(tile.art, true))
                .on_exit(Message::TileHover(tile.art, false))
                .into()
        }
    };

    column![
        artwork,
        space().height(style::SPACE_2),
        text(tile.category).size(style::TYPE_LABEL).font(style::LABEL).color(style::DIM),
        space().height(4),
        text(tile.name).size(17).font(style::DISPLAY).color(style::WHITE),
        space().height(4),
        text("COMING LATER").size(style::TYPE_LABEL).color(style::GREY)
    ]
    .width(FillPortion(1))
    .into()
}

#[cfg(test)]
mod tests {
    use super::{workbench, Art, APPS};
    use std::collections::HashSet;

    #[test]
    fn three_destinations_have_unique_names() {
        let names: HashSet<_> = APPS.iter().map(|app| app.name).collect();
        assert_eq!(names.len(), 3);
        assert_eq!(APPS.len(), 3);
    }

    #[test]
    fn training_and_tuning_have_distinct_lab_language_and_full_cycles() {
        let training = workbench(Art::Training);
        let tuning = workbench(Art::Tuning);
        assert_ne!(training.eyebrow, tuning.eyebrow);
        assert!(training.words.iter().all(|word| !tuning.words.contains(word)));
        assert_eq!(training.words.len(), 3);
        assert_eq!(tuning.words.len(), 3);
    }
}
