//! Purpose: Renders session-only plain Chat and non-networked previews of other Agent modes.
use iced::widget::{button, column, container, row, scrollable, space, text, text_editor, markdown};
use iced::{Center, Element, Fill, keyboard};

use crate::app::{ChatDraft, Message};
use crate::style;
use crate::settings::{SecretText, SettingsState};
use crate::credentials::Provider;

pub const MODES: [&str; 6] = ["Chat", "Tasks", "Research", "Coding", "Learning", "Play"];

fn action(label: &'static str, message: Message) -> Element<'static, Message> {
    button(text(label).size(13).color(style::WHITE))
        .padding([11, 15])
        .on_press(message)
        .style(style::quiet_button)
        .into()
}

pub fn view<'a>(drafts: &'a [ChatDraft], selected: u32, settings: &SettingsState) -> Element<'a, Message> {
    let current = drafts.iter().find(|draft| draft.id == selected);
    let active_mode = current.map_or(0, |draft| draft.mode);
    let draft_text = current.map_or("", |draft| draft.text.as_str());
    let connected = settings.selected_model().is_some();
    let mut provider_row = row![].spacing(8);
    for provider in Provider::ALL {
        let active = settings.provider == provider;
        provider_row = provider_row.push(button(text(provider.name()).size(12))
            .on_press(Message::SelectProvider(provider))
            .padding([9, 13]).style(move |t, st| style::nav(active, t, st)));
    }
    let mut model_row = row![].spacing(8);
    for (slot, model) in settings.models[settings.index()].iter().enumerate() {
        let active = settings.chosen[settings.index()] == Some(slot);
        model_row = model_row.push(button(text(model.clone()).size(12))
            .on_press(Message::ChooseModel(slot))
            .padding([9, 13]).style(move |t, st| style::nav(active, t, st)));
    }
    let selector = column![
        row![text("PROVIDER").size(11).color(style::DIM), space().width(20), provider_row],
        space().height(9),
        row![text("MODEL").size(11).color(style::DIM), space().width(20),
            if settings.models[settings.index()].is_empty() {
                button(text("+ Add a model in Settings").size(12))
                    .on_press(Message::OpenModelSettings).style(style::quiet_button).into()
            } else { scrollable(model_row).direction(iced::widget::scrollable::Direction::Horizontal(
                        iced::widget::scrollable::Scrollbar::default())).height(40).into() }
        ],
        space().height(7),
        text("Active choice is session-only. Keys remain in the OS vault; sending may incur charges.").size(11).color(style::DIM)
    ].width(Fill);


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
        for (slot, turn) in draft.turns.iter().enumerate() {
            let who = if turn.role == "user" { "YOU" } else { "ARCHX AGENT" };
            let mut message = column![text(who).size(10).color(style::DIM)].spacing(9);
            if let Some((_, content, reasoning, expanded)) = draft.formatted.iter().find(|(index, _, _, _)| *index == slot) {
                if let Some(reasoning) = reasoning {
                    message = message.push(button(text(if *expanded { "Reasoning  ▴" } else { "Reasoning  ▾" }).size(12))
                        .on_press(Message::ToggleReasoning(draft.id, slot)).style(style::quiet_button));
                    if *expanded {
                        message = message.push(container(markdown::view(reasoning.items(), iced::Theme::Dark)
                            .map(|_| Message::IgnoreMarkdownLink)).padding(14).width(Fill).style(style::settings_panel));
                    }
                }
                message = message.push(markdown::view(content.items(), iced::Theme::Dark)
                    .map(|_| Message::IgnoreMarkdownLink));
            } else {
                message = message.push(text(turn.content.clone()).size(14).color(style::WHITE));
            }
            log = log.push(container(message).width(Fill).padding(18).style(style::surface));
        }
        if let Some((content, reasoning)) = &draft.partial {
            let mut active = column![text("ARCHX AGENT  ·  STREAMING").size(10).color(style::DIM)].spacing(9);
            if let Some(reasoning) = reasoning {
                active = active.push(text("Reasoning received").size(11).color(style::GREY))
                    .push(markdown::view(reasoning.items(), iced::Theme::Dark).map(|_| Message::IgnoreMarkdownLink));
            }
            active = active.push(markdown::view(content.items(), iced::Theme::Dark).map(|_| Message::IgnoreMarkdownLink));
            log = log.push(container(active).width(Fill).padding(18).style(style::surface));
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
            button(text(if active_mode != 0 { "PREVIEW ONLY  /  NO TOOLS" }
                else if connected { "MODEL SELECTED  /  KEY CHECK ON SEND" }
                else { "SET UP PROVIDER & MODEL IN SETTINGS  ↗" }).size(11).color(style::GREY))
                .on_press(Message::OpenModelSettings).padding([9, 13]).style(style::quiet_button)
        ].align_x(Center)).center_x(Fill).center_y(Fill).into()
    };

    let error_notice: Element<'static, Message> = match current.and_then(|draft| draft.error.as_deref()) {
        Some(error) => text(error.to_owned()).size(12).color(style::GREY).into(),
        None => space().height(0).into(),
    };
    let can_enter_send = active_mode == 0 && connected && !draft_text.trim().is_empty() && current.is_some_and(|draft| !draft.busy);
    let composer = container(
        column![
            row![
                text("UNSENT DRAFT").size(10).color(style::DIM).width(Fill),
                text(format!("{} CHARACTERS  /  THIS SESSION ONLY", draft_text.chars().count()))
                    .size(10).color(style::DIM)
            ],
            space().height(10),
            if let Some(draft) = current {
                text_editor(&draft.editor)
                    .placeholder(if active_mode == 0 { "Write a message · Enter to send · Shift+Enter for newline" } else { "Draft only · this mode cannot send" })
                    .height(80).max_height(140).padding(14).size(14)
                    .on_action(move |action| Message::EditEditor(selected, crate::app::EditorAction(action)))
                    .key_binding(move |event| {
                        if can_enter_send &&
                            event.key == keyboard::Key::Named(keyboard::key::Named::Enter) &&
                            !event.modifiers.shift() && !event.modifiers.command() && !event.modifiers.alt() {
                            Some(text_editor::Binding::Custom(Message::SendChat))
                        } else { text_editor::Binding::from_key_press(event) }
                    }).into()
            } else { space().height(80).into() },
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
            text("Enter sends · Shift+Enter adds a line. Send shares up to 12 recent turns with the chosen provider. No disk history or tools; requests may cost money.")
                .size(11).color(style::DIM),
            error_notice
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
        space().height(16),
        selector,
        space().height(10),
        button(text(if settings.stream_chat { "Streaming ON · click for whole reply" } else { "Whole reply · click to stream" }).size(11))
            .on_press(Message::ToggleStreaming).style(style::quiet_button),
        space().height(12),
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
