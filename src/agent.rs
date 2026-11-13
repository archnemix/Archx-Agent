//! Purpose: Renders the UI-only Archx Agent workspace, draft navigation, and six mode previews.
use iced::widget::{button, column, container, row, scrollable, space, text, text_input};
use iced::{Center, Element, Fill};

use crate::app::{ChatDraft, Message};
use crate::style;
use crate::settings::{SecretText, SettingsState};

pub const MODES: [&str; 6] = ["Chat", "Tasks", "Research", "Coding", "Learning", "Play"];

fn action(label: &'static str, message: Message) -> Element<'static, Message> {
    button(text(label).size(13).color(style::WHITE))
        .padding([11, 15])
        .on_press(message)
        .style(style::quiet_button)
        .into()
}

pub fn view(drafts: &[ChatDraft], selected: u32, settings: &SettingsState) -> Element<'static, Message> {
    let current = drafts.iter().find(|draft| draft.id == selected);
    let active_mode = current.map_or(0, |draft| draft.mode);
    let draft_text = current.map_or("", |draft| draft.text.as_str());
    let connected = settings.selected_model().is_some();

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
        text("Chat stays in this process only.\nEverything disappears when you close the Lab.")
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
    let center: Element<'static, Message> = if active_mode == 0 && current.is_some_and(|draft| !draft.turns.is_empty()) {
        let draft = current.expect("checked above");
        let mut log = column![text("SESSION CHAT  /  NO DISK HISTORY").size(11).color(style::DIM)].spacing(16);
        for turn in &draft.turns {
            let who = if turn.role == "user" { "YOU" } else { "ASSISTANT" };
            log = log.push(container(column![
                text(who).size(10).color(style::DIM),
                text(turn.content.clone()).size(14).color(style::WHITE)
            ].spacing(8)).width(Fill).padding(16).style(style::surface));
        }
        if let Some(error) = &draft.error { log = log.push(text(error.clone()).size(12).color(style::GREY)); }
        scrollable(log.padding([20, 8])).height(Fill).width(Fill).into()
    } else {
        container(column![
            text("ARCHX  /  AGENT").size(11).color(style::DIM),
            space().height(12),
            text(MODES[usize::from(active_mode)]).size(36).font(style::DISPLAY).color(style::WHITE),
            space().height(12),
            text(lead).size(15).color(style::GREY),
            space().height(23),
            container(text(if active_mode != 0 { "PREVIEW ONLY  /  NO TOOLS" }
                else if connected { "PLAIN CHAT  /  EXPLICIT SEND ONLY" }
                else { "ADD A KEY AND MODEL IN SETTINGS" }).size(11).color(style::GREY))
                .padding([9, 13]).style(style::badge)
        ].align_x(Center)).center_x(Fill).center_y(Fill).into()
    };

    let composer = container(
        column![
            row![
                text("UNSENT DRAFT").size(10).color(style::DIM).width(Fill),
                text(format!("{} CHARACTERS  /  THIS SESSION ONLY", draft_text.chars().count()))
                    .size(10).color(style::DIM)
            ],
            space().height(10),
            text_input(if active_mode == 0 && connected { "Write a message — click Send to share it" } else { "Write a draft — only Chat can send" }, draft_text)
                .padding([14, 16])
                .size(14)
                .on_input(move |value| Message::EditDraft(selected, SecretText::new(value)))
                .style(style::composer_input),
            space().height(10),
            row![
                button(text("Clear draft").size(11).color(style::GREY))
                    .padding([8, 10])
                    .on_press_maybe((!draft_text.is_empty()).then_some(Message::ClearDraft(selected)))
                    .style(style::quiet_button),
                space().width(Fill),
                button(text(if current.is_some_and(|draft| draft.busy) { "Waiting…" } else { "Send ↗" }).size(12))
                    .on_press_maybe((active_mode == 0 && connected && !draft_text.trim().is_empty()
                        && current.is_some_and(|draft| !draft.busy)).then_some(Message::SendChat))
                    .padding([10, 16]).style(style::quiet_button)
            ].align_y(Center),
            space().height(7),
            text("Only Chat sends when you click Send. Messages stay in this process until the Lab closes; provider requests may cost money.")
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
            text(if connected { "SESSION ONLY  /  NO TOOLS" } else { "DRAFT WORKSPACE  /  NOT CONNECTED" }).size(11).color(style::DIM)
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
