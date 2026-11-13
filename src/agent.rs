//! Purpose: Renders the UI-only Archx Agent workspace, draft navigation, and six mode previews.
use iced::widget::{button, column, container, row, scrollable, space, text, text_input};
use iced::{Center, Element, Fill};

use crate::app::{ChatDraft, Message};
use crate::style;

pub const MODES: [&str; 6] = ["Chat", "Tasks", "Research", "Coding", "Learning", "Play"];

fn action(label: &'static str, message: Message) -> Element<'static, Message> {
    button(text(label).size(13).color(style::WHITE))
        .padding([11, 15])
        .on_press(message)
        .style(style::quiet_button)
        .into()
}

pub fn view(drafts: &[ChatDraft], selected: u32) -> Element<'static, Message> {
    let current = drafts.iter().find(|draft| draft.id == selected);
    let active_mode = current.map_or(0, |draft| draft.mode);
    let draft_text = current.map_or("", |draft| draft.text.as_str());

    let mut history = column![
        text("WORKSPACE  /  ARCHX AGENT").size(11).color(style::DIM),
        space().height(22),
        text("Conversations").size(21).font(style::DISPLAY).color(style::WHITE),
        space().height(17),
        action("+  New draft", Message::NewChat),
        space().height(28),
        text("THIS SESSION").size(10).color(style::DIM),
        space().height(12)
    ]
    .spacing(0);
    for draft in drafts.iter().rev() {
        let id = draft.id;
        let selected_draft = selected == id;
        history = history.push(
            button(text(format!("Draft {:02}    /    {}", id, MODES[usize::from(draft.mode)]))
                .size(12)
                .color(if selected_draft { style::WHITE } else { style::GREY }))
            .width(Fill)
            .padding([13, 12])
            .on_press(Message::OpenChat(id))
            .style(move |theme, status| style::nav(selected_draft, theme, status))
        ).push(space().height(6));
    }
    history = history.push(space().height(24)).push(
        text("Unsent text stays with each draft.\nEverything disappears when you close the Lab.")
            .size(11)
            .color(style::DIM)
    );

    let rail = container(scrollable(history.padding(24)).height(Fill))
        .width(255)
        .height(Fill)
        .style(style::rail);

    let modes = MODES.iter().enumerate().fold(row![].spacing(8), |row, (index, label)| {
        let mode = index as u8;
        let active = active_mode == mode;
        row.push(
            button(text(*label).size(12).color(if active { style::WHITE } else { style::GREY }))
                .padding([10, 12])
                .on_press(Message::SelectMode(mode))
                .style(move |theme, status| style::nav(active, theme, status))
        )
    });
    let lead = if active_mode == 0 { "A place for your next conversation." } else { "A workspace for what comes next." };
    let center = container(
        column![
            text("ARCHX  /  AGENT").size(11).color(style::DIM),
            space().height(12),
            text(MODES[usize::from(active_mode)]).size(36).font(style::DISPLAY).color(style::WHITE),
            space().height(12),
            text(lead).size(15).color(style::GREY),
            space().height(23),
            container(text("UI PREVIEW  /  NO MODEL CONNECTED").size(11).color(style::GREY))
                .padding([9, 13])
                .style(style::badge)
        ]
        .align_x(Center)
    )
    .center_x(Fill)
    .center_y(Fill);

    let composer = container(
        column![
            row![
                text("UNSENT DRAFT").size(10).color(style::DIM).width(Fill),
                text(format!("{} CHARACTERS  /  THIS SESSION ONLY", draft_text.chars().count()))
                    .size(10).color(style::DIM)
            ],
            space().height(10),
            text_input("Write a thought here — it will not be sent", draft_text)
                .padding([14, 16])
                .size(14)
                .on_input(move |value| Message::EditDraft(selected, value))
                .style(style::composer_input),
            space().height(10),
            row![
                button(text("Clear draft").size(11).color(style::GREY))
                    .padding([8, 10])
                    .on_press_maybe((!draft_text.is_empty()).then_some(Message::ClearDraft(selected)))
                    .style(style::quiet_button),
                space().width(Fill),
                text("SEND UNAVAILABLE  /  NO MODEL CONNECTED").size(11).color(style::DIM)
            ].align_y(Center),
            space().height(7),
            text("You can test typing and switching drafts. No message, history or mode conversion is created.")
                .size(11).color(style::DIM)
        ]
        .width(Fill)
    )
    .width(Fill)
    .padding(18)
    .style(style::surface);

    let main = column![
        row![
            text("ARCHX AGENT").size(12).color(style::WHITE),
            space().width(Fill),
            text("DRAFT WORKSPACE  /  NOT CONNECTED").size(11).color(style::DIM)
        ],
        space().height(24),
        scrollable(modes).width(Fill),
        center,
        composer
    ]
    .width(Fill)
    .height(Fill)
    .padding(30);

    row![rail, main].width(Fill).height(Fill).into()
}

#[cfg(test)]
mod tests {
    use super::MODES;
    use std::collections::HashSet;

    #[test]
    fn six_preview_modes_are_distinct() {
        assert_eq!(MODES.len(), 6);
        assert_eq!(MODES.iter().collect::<HashSet<_>>().len(), 6);
    }
}
