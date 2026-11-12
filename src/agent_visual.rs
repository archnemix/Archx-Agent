//! Purpose: Draws the Agent's kinetic type artwork without implying its six modes are live.
use iced::widget::{column, container, row, space, text};
use iced::{Element, Fill, FillPortion};

use crate::app::Message;
use crate::style;

const MODES: [&str; 6] = ["CHAT", "TASKS", "RESEARCH", "CODING", "LEARNING", "PLAY"];

pub const MODE_COUNT: u8 = MODES.len() as u8;

fn mode(phase: u8) -> &'static str {
    MODES[usize::from(phase % MODE_COUNT)]
}

fn markers(phase: u8) -> iced::widget::Row<'static, Message> {
    (0..MODE_COUNT)
        .fold(row![].spacing(5), |row, index| {
            row.push(
                container(space().height(2))
                    .width(FillPortion(1))
                    .style(move |theme| style::mode_marker(theme, index == phase % MODE_COUNT)),
            )
        })
        .width(Fill)
}

pub fn hero(phase: u8) -> Element<'static, Message> {
    container(
        column![
            text("SIX MODES  /  ONE AGENT").size(11).color(style::GREY),
            space().height(25),
            text("ARCHX").size(32).color(style::GREY),
            text("AGENT").size(52).color(style::WHITE),
            space().height(18),
            row![
                text(format!("{:02}  /  06", phase % MODE_COUNT + 1))
                    .size(11)
                    .color(style::DIM)
                    .width(Fill),
                text(mode(phase)).size(13).color(style::WHITE)
            ],
            space().height(11),
            markers(phase)
        ]
        .width(Fill)
        .padding([23, 30]),
    )
    .width(FillPortion(1))
    .height(248)
    .style(style::agent_surface)
    .into()
}

pub fn tile(phase: u8) -> Element<'static, Message> {
    container(
        column![
            text("ARCHX  /  SIX MODES").size(10).color(style::GREY),
            space().height(5),
            text("AGENT").size(39).color(style::WHITE),
            space().height(Fill),
            row![
                text(format!("{:02} / 06", phase % MODE_COUNT + 1))
                    .size(10)
                    .color(style::DIM)
                    .width(Fill),
                text(mode(phase)).size(12).color(style::WHITE)
            ],
            space().height(8),
            markers(phase)
        ]
        .width(Fill)
        .height(Fill)
        .padding(18),
    )
    .width(Fill)
    .height(140)
    .clip(true)
    .style(style::agent_surface)
    .into()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    #[test]
    fn six_mode_names_are_distinct_and_wrap_after_one_cycle() {
        assert_eq!(MODES.iter().collect::<HashSet<_>>().len(), MODE_COUNT as usize);
        assert_eq!(mode(0), "CHAT");
        assert_eq!(mode(5), "PLAY");
        assert_eq!(mode(6), mode(0));
    }
}
