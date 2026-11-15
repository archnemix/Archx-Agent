//! Purpose: Renders the native, reference-led Chat workspace and session-only mode previews.
use iced::widget::{button, column, container, markdown, row, scrollable, space, stack, text, text_editor, text_input};
use iced::{Center, Element, Fill, keyboard};

use crate::app::{ChatDraft, Message};
use crate::style;
use crate::settings::SettingsState;
use crate::credentials::Provider;

pub const MODES: [&str; 6] = ["Chat", "Tasks", "Research", "Coding", "Learning", "Play"];

fn action(label: &'static str, message: Message) -> Element<'static, Message> {
    button(text(label).size(13)).padding([9, 12])
        .on_press(message).style(style::chat_button).into()
}

fn model_menu<'a>(settings: &SettingsState, search: &'a str) -> Element<'a, Message> {
    let mut providers = column![text("PROVIDER").size(10).color(style::DIM)].spacing(6);
    for provider in Provider::ALL {
        let active = settings.provider == provider;
        providers = providers.push(button(text(provider.name()).size(13))
            .on_press(Message::SelectProvider(provider)).width(Fill).padding([10, 11])
            .style(move |t, s| style::chat_menu_choice(active, t, s)));
    }
    let mut models = column![text_input("Filter models…", search)
        .on_input(Message::SearchChatModels).padding([10, 12]).size(13)
        .style(style::composer_input)]
        .spacing(7).width(Fill);
    let mut count = 0;
    for (slot, model) in settings.models[settings.index()].iter().enumerate() {
        if !model.to_lowercase().contains(&search.to_lowercase()) { continue; }
        count += 1;
        let active = settings.chosen[settings.index()] == Some(slot);
        models = models.push(button(text(model.clone()).size(13))
            .on_press(Message::ChooseModel(slot)).padding([10, 11]).width(Fill)
            .style(move |t, s| style::chat_menu_choice(active, t, s)));
    }
    if count == 0 {
        models = models.push(text(if search.is_empty() { "No models added yet" } else { "No matching models" })
            .size(12).color(style::GREY));
    }
    models = models.push(row![
        text(format!("{count} models · this session")).size(11).color(style::DIM),
        space().width(Fill),
        button(text("Manage models ↗").size(11)).on_press(Message::OpenModelSettings)
            .style(style::chat_menu_choice_inactive)
    ].align_y(Center));
    container(row![container(providers).width(155), container(scrollable(models).height((count as f32 * 39.0 + 90.0).clamp(145.0, 290.0))).width(Fill)]
        .spacing(12).width(Fill))
        .width(540).padding(14).style(style::chat_panel).into()
}

fn mode_menu() -> Element<'static, Message> {
    let mut modes = column![text("WORKSPACE PREVIEW").size(10).color(style::DIM)].spacing(3);
    for (index, label) in MODES.iter().enumerate() {
        modes = modes.push(button(text(*label).size(13)).width(Fill).padding([8, 12])
            .on_press(Message::SelectMode(index as u8)).style(style::chat_menu_choice_inactive));
    }
    container(modes).padding(12).width(200).style(style::chat_panel).into()
}

fn avatar(assistant: bool) -> Element<'static, Message> {
    container(text(if assistant { "A" } else { "Y" }).size(11)
        .color(if assistant { style::BLACK } else { style::GREY }))
        .width(30).height(30).align_x(Center).align_y(Center)
        .style(move |t| style::chat_avatar(assistant, t)).into()
}

pub fn view<'a>(drafts: &'a [ChatDraft], selected: u32, settings: &SettingsState,
    model_menu_open: bool, mode_menu_open: bool, search: &'a str) -> Element<'a, Message> {
    let current = drafts.iter().find(|draft| draft.id == selected);
    let active_mode = current.map_or(0, |draft| draft.mode);
    let draft_text = current.map_or("", |draft| draft.text.as_str());
    let connected = settings.selected_model().is_some();

    let mut history = column![
        text("ARCHX  /  AGENT").size(11).color(style::DIM),
        space().height(18),
        text("Chats").size(19).font(style::DISPLAY).color(style::WHITE),
        space().height(14),
        action("+  New chat", Message::NewChat),
        space().height(22),
        text("THIS SESSION").size(10).color(style::DIM),
        space().height(8)
    ];
    for draft in drafts.iter().rev() {
        let id = draft.id;
        let selected_draft = selected == id;
        history = history.push(button(text(format!("Chat {:02}   ·   {}", id, MODES[usize::from(draft.mode)]))
            .size(12).color(if selected_draft { style::WHITE } else { style::GREY }))
            .width(Fill).padding([10, 12]).on_press(Message::OpenChat(id))
            .style(move |t, s| style::chat_menu_choice(selected_draft, t, s)))
            .push(space().height(4));
    }
    history = history.push(space().height(24)).push(
        text("Chats are kept in memory only.\nClosing the Lab clears this session.")
            .size(11).color(style::DIM));
    let rail = container(scrollable(history.padding(18)).height(Fill))
        .width(214).height(Fill).style(style::rail);

    let model_label = settings.selected_model().map(|model| {
        let short = if model.chars().count() > 28 {
            format!("{}…", model.chars().take(27).collect::<String>())
        } else { model.to_owned() };
        format!("{}  /  {short}", settings.provider.name())
    }).unwrap_or_else(|| "Choose a model".to_owned());
    let topbar = row![
        button(text(format!("◇   {model_label}   ⌄")).size(13)).on_press(Message::ToggleModelMenu)
            .padding([9, 12]).style(style::chat_button),
        space().width(Fill),
        button(text(format!("{}  ⌄", MODES[usize::from(active_mode)])).size(12))
            .on_press(Message::ToggleModeMenu).padding([9, 12]).style(style::chat_button)
    ].align_y(Center);

    let center: Element<'a, Message> = if active_mode == 0 && current.is_some_and(|d| !d.turns.is_empty()) {
        let draft = current.expect("checked above");
        let mut log = column![].spacing(24).width(Fill);
        for (slot, turn) in draft.turns.iter().enumerate() {
            let assistant = turn.role != "user";
            let mut body = column![
                text(if assistant { "Archx Agent" } else { "You" }).size(13).color(style::WHITE)
            ].spacing(7).width(Fill);
            if !assistant {
                body = body.push(container(text(turn.content.clone()).size(15).color(style::WHITE))
                    .padding([12, 16]).style(style::chat_user));
            } else if let Some((_, content, reasoning, expanded)) = draft.formatted.iter().find(|(index, _, _, _)| *index == slot) {
                if let Some(reasoning) = reasoning {
                    let mut thinking = column![button(text(if *expanded { "✧  Thinking  ▴" } else { "✧  Thinking  ▾" })
                        .size(12).color(style::GREY)).on_press(Message::ToggleReasoning(draft.id, slot))
                        .padding([8, 12]).style(style::chat_menu_choice_inactive)].spacing(4);
                    if *expanded {
                        thinking = thinking.push(container(markdown::view(reasoning.items(), iced::Theme::Dark)
                            .map(|_| Message::IgnoreMarkdownLink)).padding([5, 12]));
                    }
                    body = body.push(container(thinking).style(style::chat_thinking));
                }
                body = body.push(markdown::view(content.items(), iced::Theme::Dark)
                    .map(|_| Message::IgnoreMarkdownLink));
            } else {
                body = body.push(text(turn.content.clone()).size(15).color(style::WHITE));
            }
            log = log.push(row![avatar(assistant), body].spacing(16).width(Fill));
        }
        if let Some((content, reasoning)) = &draft.partial {
            let mut body = column![text("Archx Agent  ·  responding").size(13).color(style::GREY)].spacing(8);
            if let Some(reasoning) = reasoning {
                body = body.push(container(column![text("✧  Thinking").size(12).color(style::GREY),
                    markdown::view(reasoning.items(), iced::Theme::Dark).map(|_| Message::IgnoreMarkdownLink)]
                    .spacing(8)).padding(12).style(style::chat_thinking));
            }
            body = body.push(markdown::view(content.items(), iced::Theme::Dark)
                .map(|_| Message::IgnoreMarkdownLink));
            log = log.push(row![avatar(true), body].spacing(16).width(Fill));
        }
        scrollable(container(container(log).max_width(860).width(Fill).padding([24, 20]))
            .center_x(Fill)).width(Fill).height(Fill).into()
    } else {
        let lead = if active_mode == 0 { "A place for your next conversation." } else { "A workspace for what comes next." };
        container(column![
            text("ARCHX  /  AGENT").size(11).color(style::DIM),
            space().height(12),
            text(MODES[usize::from(active_mode)]).size(36).font(style::DISPLAY).color(style::WHITE),
            space().height(12),
            text(lead).size(15).color(style::GREY),
            space().height(23),
            button(text(if active_mode != 0 { "PREVIEW ONLY  /  NO TOOLS" }
                else if connected { "MODEL SELECTED  /  KEY CHECK ON SEND" }
                else { "ADD A KEY AND MODEL IN SETTINGS  ↗" }).size(11).color(style::GREY))
                .on_press(Message::OpenModelSettings).padding([9, 13]).style(style::chat_button)
        ].align_x(Center)).center_x(Fill).center_y(Fill).into()
    };

    let can_send = active_mode == 0 && connected && !draft_text.trim().is_empty() && current.is_some_and(|draft| !draft.busy);
    let editor: Element<'_, Message> = if let Some(draft) = current {
        text_editor::<Message, iced::Theme, iced::Renderer>(&draft.editor)
            .placeholder(if active_mode == 0 { "Send a message…  (Enter to send, Shift+Enter for a new line)" }
                else { "Draft only · this mode cannot send" })
            .height(58).max_height(126).padding([8, 10]).size(15)
            .style(style::chat_editor)
            .on_action(move |action| Message::EditEditor(selected, crate::app::EditorAction(action)))
            .key_binding(move |event| {
                if can_send && event.key == keyboard::Key::Named(keyboard::key::Named::Enter)
                    && !event.modifiers.shift() && !event.modifiers.command() && !event.modifiers.alt() {
                    Some(text_editor::Binding::Custom(Message::SendChat))
                } else { text_editor::Binding::from_key_press(event) }
            }).into()
    } else { space().height(58).into() };
    let composer = container(column![
        editor,
        row![
            button(text(if settings.stream_chat { "Streaming  ·  on" } else { "Whole reply  ·  on" }).size(11))
                .on_press(Message::ToggleStreaming).padding([7, 9]).style(style::chat_menu_choice_inactive),
            space().width(Fill),
            button(text("Send  ↗").size(12))
                .on_press_maybe(can_send.then_some(Message::SendChat)).padding([8, 15])
                .style(style::chat_button)
        ].align_y(Center)
    ].spacing(4)).max_width(860).width(Fill).padding(12).style(style::chat_panel);
    let error_notice: Element<'_, Message> = match current.and_then(|draft| draft.error.as_deref()) {
        Some(error) => text(error.to_owned()).size(12).color(style::GREY).into(),
        None => space().height(0).into(),
    };
    let footer = column![
        container(composer).center_x(Fill),
        error_notice,
        space().height(7),
        text("Enter sends · Shift+Enter for a new line · Up to 12 recent turns sent to your provider · Session only")
            .size(11).color(style::DIM),
    ].align_x(Center).width(Fill).padding([12, 20]);

    let main = column![
        container(topbar).padding([12, 20]).width(Fill),
        center,
        footer
    ].width(Fill).height(Fill);
    let main: Element<'a, Message> = if model_menu_open || mode_menu_open {
        let menu: Element<'a, Message> = if model_menu_open { model_menu(settings, search) } else { mode_menu() };
        stack![main, container(menu).width(Fill).height(Fill).padding([57, 12])
            .align_x(if model_menu_open { iced::alignment::Horizontal::Left }
                else { iced::alignment::Horizontal::Right })
            .align_y(iced::alignment::Vertical::Top)].width(Fill).height(Fill).into()
    } else { main.into() };
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
