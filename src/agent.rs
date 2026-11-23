//! Purpose: Renders the native, reference-led Chat workspace and session-only mode previews.
use std::sync::LazyLock;

use iced::widget::{button, column, container, image, markdown, row, scrollable, space, stack, svg, text, text_editor, text_input};
use iced::{Center, Color, Element, Fill, keyboard};

use crate::app::{ChatDraft, Message, Page};
use crate::style;
use crate::settings::{SettingsState, SecretText};
use crate::credentials::Provider;

pub const MODES: [&str; 6] = ["Chat", "Tasks", "Research", "Coding", "Learning", "Play"];

static BRAND_MARK: LazyLock<image::Handle> = LazyLock::new(|| {
    image::Handle::from_bytes(include_bytes!("../assets/brand/archnemix-sidebar.png").to_vec())
});

// Small outline glyphs for the Agent chrome. Vector paths are the bundled
// Lucide set plus recreations of the MIT-licensed 1.9.0 reference's own icons;
// see assets/icons/README.md. Everything loads from compiled bytes.
#[derive(Clone, Copy)]
enum Glyph { Monitor, Send, Stop, Chevron, Plus, ArrowDown, Message, Lock, Settings, House }

fn icon(glyph: Glyph, size: u32, color: Color) -> svg::Svg<'static> {
    let bytes: &'static [u8] = match glyph {
        Glyph::Monitor => include_bytes!("../assets/icons/monitor.svg"),
        Glyph::Send => include_bytes!("../assets/icons/send.svg"),
        Glyph::Stop => include_bytes!("../assets/icons/stop.svg"),
        Glyph::Chevron => include_bytes!("../assets/icons/chevron-down.svg"),
        Glyph::Plus => include_bytes!("../assets/icons/plus.svg"),
        Glyph::ArrowDown => include_bytes!("../assets/icons/arrow-down.svg"),
        Glyph::Message => include_bytes!("../assets/icons/message-square.svg"),
        Glyph::Lock => include_bytes!("../assets/icons/lock.svg"),
        Glyph::Settings => include_bytes!("../assets/icons/settings-2.svg"),
        Glyph::House => include_bytes!("../assets/icons/house.svg"),
    };
    svg(svg::Handle::from_memory(bytes))
        .width(size)
        .height(size)
        .style(move |_, _| svg::Style { color: Some(color) })
}

// Iced's Markdown parser already keeps HTML, links and images inert. Wrap only
// native code/table widgets to reproduce the supplied reference's hierarchy;
// do not execute code, auto-fetch images or follow generated links.
struct ChatViewer;
impl<'a> markdown::Viewer<'a, Message> for ChatViewer {
    fn on_link_click(_: markdown::Uri) -> Message { Message::IgnoreMarkdownLink }

    fn code_block(&self, settings: markdown::Settings, language: Option<&'a str>, code: &'a str,
        lines: &'a [markdown::Text]) -> Element<'a, Message> {
        container(column![
            container(row![
                text(language.unwrap_or("code").to_owned()).size(11).color(style::DIM),
                space().width(Fill),
                button(text("Copy code").size(11)).on_press(Message::CopyCode(SecretText::new(code.to_owned())))
                    .padding([2, 8]).style(style::tiny_button)
            ].align_y(Center)).width(Fill).padding([6, 10]).style(style::chat_code_header),
            markdown::code_block(settings, lines, Self::on_link_click),
        ]).width(Fill).style(style::chat_panel).into()
    }

    fn table(&self, settings: markdown::Settings, columns: &'a [markdown::Column],
        rows: &'a [markdown::Row]) -> Element<'a, Message> {
        container(column![
            text(format!("Table · {} rows × {} columns", rows.len() + 1, columns.len()))
                .size(11).color(style::DIM),
            markdown::table(self, settings, columns, rows)
        ].spacing(5)).padding(9).width(Fill).style(style::chat_panel).into()
    }
}

fn chat_md<'a>(items: impl IntoIterator<Item = &'a markdown::Item>) -> Element<'a, Message> {
    let mut settings = markdown::Settings::with_text_size(style::AGENT_BODY_SIZE, iced::Theme::Dark);
    settings.h1_size = 24.into();
    settings.h2_size = 20.into();
    settings.code_size = 12.into();
    settings.spacing = 11.into();
    markdown::view_with(items, settings, &ChatViewer)
}

/// Real configuration state only: never invent connectivity we cannot prove.
pub fn endpoint_label(provider: &str, model: Option<&str>) -> String {
    match model {
        Some(model) => format!("{provider} · {model}"),
        None => "no provider configured".to_owned(),
    }
}

pub fn conn_label(connected: bool) -> &'static str {
    if connected { "model selected" } else { "not configured" }
}

/// Empty-view copy. Preview modes must never read as working tools.
pub fn empty_heading(mode: u8, connected: bool) -> &'static str {
    if mode != 0 { MODES[usize::from(mode)] }
    else if !connected { "No provider configured" }
    else { "How can I help?" }
}

pub fn empty_body(mode: u8, connected: bool) -> &'static str {
    if mode != 0 {
        "This mode is a preview. No tools are running."
    } else if !connected {
        "Connect a provider and choose a model to start chatting.\nKeys stay in the OS credential store; chats stay in this session."
    } else {
        "Streaming, reasoning view, markdown, code and tables — powered by your selected model."
    }
}

fn brand_row() -> Element<'static, Message> {
    row![
        image(BRAND_MARK.clone()).width(26).height(26).content_fit(iced::ContentFit::Contain),
        text("Archx Agent").size(15).font(style::STRONG).color(style::WHITE)
    ].spacing(9).align_y(Center).into()
}

fn nav_row(glyph: Glyph, label: &'static str, action: Message, active: bool) -> Element<'static, Message> {
    button(row![
        icon(glyph, 15, if active { style::WHITE } else { style::GREY }),
        text(label).size(13).font(style::LABEL).color(if active { style::WHITE } else { style::GREY })
    ].spacing(9).align_y(Center))
        .width(Fill).padding([8, 12]).on_press(action)
        .style(move |t, s| style::side_nav(active, t, s)).into()
}

fn model_menu<'a>(settings: &SettingsState, search: &'a str) -> Element<'a, Message> {
    let mut providers = column![text("PROVIDER").size(10).color(style::DIM)].spacing(4);
    for provider in Provider::ALL {
        let active = settings.provider == provider;
        providers = providers.push(button(text(provider.name()).size(13))
            .on_press(Message::SelectProvider(provider)).width(Fill).padding([8, 10])
            .style(move |t, s| style::list_row(active, t, s)));
    }
    let mut models = column![text("MODEL").size(10).color(style::DIM),
        text_input("Filter models…", search)
            .on_input(Message::SearchChatModels).padding([9, 11]).size(13)
            .style(style::composer_input)]
        .spacing(7).width(Fill);
    let mut count = 0;
    for (slot, model) in settings.models[settings.index()].iter().enumerate() {
        if !model.to_lowercase().contains(&search.to_lowercase()) { continue; }
        count += 1;
        let active = settings.chosen[settings.index()] == Some(slot);
        models = models.push(button(text(model.clone()).size(13))
            .on_press(Message::ChooseModel(slot)).padding([8, 10]).width(Fill)
            .style(move |t, s| style::list_row(active, t, s)));
    }
    if count == 0 {
        models = models.push(text(if search.is_empty() { "No models added yet" } else { "No matching models" })
            .size(12).color(style::GREY));
    }
    models = models.push(row![
        text(format!("{count} models · this session")).size(11).color(style::DIM),
        space().width(Fill),
        button(text("Manage models ↗").size(11)).on_press(Message::OpenModelCatalogSettings)
            .style(style::ghost_button)
    ].align_y(Center));
    container(row![container(scrollable(providers).height(340)).width(155), container(scrollable(models).height((count as f32 * 36.0 + 96.0).clamp(150.0, 290.0))).width(Fill)]
        .spacing(12).width(Fill))
        .width(540).padding(14).style(style::chat_panel).into()
}

fn mode_menu(active_mode: u8) -> Element<'static, Message> {
    let mut modes = column![text("WORKSPACE PREVIEW").size(10).color(style::DIM)].spacing(3);
    for (index, label) in MODES.iter().enumerate() {
        let active = index == usize::from(active_mode);
        modes = modes.push(button(text(*label).size(13)).width(Fill).padding([8, 12])
            .on_press(Message::SelectMode(index as u8))
            .style(move |t, s| style::list_row(active, t, s)));
    }
    container(modes).padding(12).width(200).style(style::chat_panel).into()
}

fn avatar(assistant: bool) -> Element<'static, Message> {
    container(text(if assistant { "A" } else { "Y" }).size(11)
        .color(if assistant { style::BLACK } else { style::GREY }))
        .width(30).height(30).align_x(Center).align_y(Center)
        .style(move |t| style::chat_avatar(assistant, t)).into()
}

fn rail(drafts: &[ChatDraft], selected: u32, settings: &SettingsState, settings_open: bool) -> Element<'static, Message> {
    let connected = settings.selected_model().is_some();
    let badge_label = endpoint_label(settings.provider.name(), settings.selected_model());
    let mut history = column![
        container(brand_row()).padding(iced::Padding { top: 4.0, right: 10.0, bottom: 0.0, left: 10.0 }),
        space().height(18),
        nav_row(Glyph::Message, "Chat", Message::Navigate(Page::Agent), !settings_open),
        space().height(2),
        nav_row(Glyph::Settings, "Settings", Message::Navigate(Page::Settings), settings_open),
        space().height(2),
        nav_row(Glyph::House, "Back to launcher", Message::Navigate(Page::Home), false),
        space().height(16),
        button(container(row![
            icon(Glyph::Plus, 15, style::BLACK),
            text("New chat").size(13).font(style::STRONG).color(style::BLACK)
        ].spacing(8).align_y(Center)).center_x(Fill))
            .width(Fill).height(40).padding([0, 12])
            .on_press(Message::NewChat).style(style::primary_button),
        space().height(20),
        container(row![
            text("CHATS").size(11).font(style::LABEL).color(style::DIM),
            text("· this session").size(11).color(style::DIM)
        ].spacing(6)).padding([0, 10]),
        space().height(8)
    ];
    for draft in drafts.iter().rev() {
        let id = draft.id;
        let selected_draft = !settings_open && selected == id;
        history = history.push(button(text(format!("Chat {:02}  ·  {}", id, MODES[usize::from(draft.mode)]))
            .size(12).font(style::LABEL).color(if selected_draft { style::WHITE } else { style::GREY }))
            .width(Fill).padding([8, 12]).on_press(Message::OpenChat(id))
            .style(move |t, s| style::list_row(selected_draft, t, s)))
            .push(space().height(style::AGENT_GAP_TIGHT));
    }
    let footer = column![
        container(space().height(1)).width(Fill).style(style::rail_divider),
        space().height(12),
        button(row![
            container(space().width(7).height(7)).style(move |t| style::status_dot(connected, t)),
            text(badge_label).size(11).font(style::LABEL).color(style::GREY).width(Fill),
        ].spacing(8).align_y(Center))
            .width(Fill).padding([8, 10])
            .on_press(Message::OpenModelSettings).style(style::endpoint_badge),
        space().height(8),
        row![
            icon(Glyph::Lock, 11, style::DIM),
            text("keys in OS vault · chats session-only").size(10).color(style::DIM).width(Fill),
            text(concat!("v", env!("CARGO_PKG_VERSION"))).size(10).color(style::DIM)
        ].spacing(6).align_y(Center).padding([0, 4])
    ].width(Fill);
    let rail = container(column![
        scrollable(history.padding([17, 10])).height(Fill),
        container(footer).padding([12, 15]).width(Fill)
    ].height(Fill)).width(260).height(Fill).style(style::rail);

    rail.into()
}

pub fn view<'a>(drafts: &'a [ChatDraft], selected: u32, settings: &SettingsState,
    model_menu_open: bool, mode_menu_open: bool, search: &'a str) -> Element<'a, Message> {
    let current = drafts.iter().find(|draft| draft.id == selected);
    let active_mode = current.map_or(0, |draft| draft.mode);
    let draft_text = current.map_or("", |draft| draft.text.as_str());
    let connected = settings.selected_model().is_some();

    let rail = rail(drafts, selected, settings, false);

    let model_label = settings.selected_model().map(|model| {
        let short = if model.chars().count() > 28 {
            format!("{}…", model.chars().take(27).collect::<String>())
        } else { model.to_owned() };
        format!("{}  /  {short}", settings.provider.name())
    }).unwrap_or_else(|| "Choose a model".to_owned());
    let provider_initial = settings.provider.name().chars().next().unwrap_or('·');
    let topbar = row![
        button(row![
            container(text(provider_initial.to_string()).size(10).font(style::STRONG).color(style::WHITE))
                .width(19).height(19).align_x(Center).align_y(Center).style(style::badge),
            text(model_label).size(13).font(style::LABEL).color(style::WHITE),
            icon(Glyph::Chevron, 13, style::GREY)
        ].spacing(8).align_y(Center)).on_press(Message::ToggleModelMenu)
            .padding([8, 12]).style(style::topbar_pill),
        space().width(Fill),
        row![
            container(space().width(7).height(7)).style(move |t| style::status_dot(connected, t)),
            text(conn_label(connected)).size(11).color(style::GREY)
        ].spacing(7).align_y(Center),
        button(row![
            text(MODES[usize::from(active_mode)]).size(12).font(style::LABEL).color(style::GREY),
            icon(Glyph::Chevron, 12, style::GREY)
        ].spacing(6).align_y(Center))
            .on_press(Message::ToggleModeMenu).padding([8, 11]).style(style::ghost_button)
    ].align_y(Center);

    let center: Element<'a, Message> = if active_mode == 0 && current.is_some_and(|d| !d.turns.is_empty()) {
        let draft = current.expect("checked above");
        let mut log = column![].spacing(style::AGENT_GAP_SECTION).width(Fill);
        for (slot, turn) in draft.turns.iter().enumerate() {
            let assistant = turn.role != "user";
            let mut body = column![
                text(if assistant { "Assistant" } else { "You" }).size(13).font(style::STRONG).color(style::WHITE)
            ].spacing(7).width(Fill);
            if !assistant {
                body = body.push(container(text(turn.content.clone()).size(15).color(style::WHITE))
                    .padding([12, 16]).style(style::chat_user));
            } else if let Some((_, content, reasoning, expanded)) = draft.formatted.iter().find(|(index, _, _, _)| *index == slot) {
                if let Some(reasoning) = reasoning {
                    let mut thinking = column![button(text(if *expanded { "✦  Reasoning  ▴" } else { "✦  Reasoning  ▾" })
                        .size(12).color(style::GREY)).on_press(Message::ToggleReasoning(draft.id, slot))
                        .padding([8, 12]).style(style::ghost_button)].spacing(4);
                    if *expanded {
                        thinking = thinking.push(container(chat_md(reasoning.items())).padding([5, 12]));
                    }
                    body = body.push(container(thinking).width(Fill).style(style::chat_thinking));
                }
                body = body.push(chat_md(content.items()));
            } else {
                body = body.push(text(turn.content.clone()).size(15).color(style::WHITE));
            }
            if assistant && draft.incomplete_slots.contains(&slot) {
                body = body.push(text("Incomplete · excluded from future context").size(11).color(style::GREY));
            }
            log = log.push(row![avatar(assistant), body].spacing(style::AGENT_GAP_GROUP).width(Fill));
        }
        if let Some((content, reasoning)) = &draft.partial {
            let mut body = column![text("Assistant  ·  responding").size(13).font(style::STRONG).color(style::GREY)].spacing(8);
            if let Some(reasoning) = reasoning {
                let open = draft.partial_reasoning_open;
                let mut disclosure = column![button(text(if open { "✦  Thinking…  ▴" } else { "✦  Thinking…  ▾" })
                    .size(12).color(style::GREY)).on_press(Message::ToggleReasoning(draft.id, draft.turns.len()))
                    .padding([8, 12]).style(style::ghost_button)].spacing(4);
                if open { disclosure = disclosure.push(container(chat_md(reasoning.items())).padding([5, 12])); }
                body = body.push(container(disclosure).width(Fill).style(style::chat_thinking));
            }
            body = body.push(chat_md(content.items()));
            log = log.push(row![avatar(true), body].spacing(style::AGENT_GAP_GROUP).width(Fill));
        }
        let list = scrollable(container(container(log).max_width(860).width(Fill).padding([24, 20]))
            .center_x(Fill)).id("chat-log").width(Fill).height(Fill);
        // Keep screenshot fixtures on the first turn; a live conversation starts
        // at its latest message and preserves the user's distance from the end.
        let list = if std::env::var_os("ARCHX_SNAPSHOT").is_some() { list }
            else { list.anchor_bottom() };
        let id = draft.id;
        list.on_scroll(move |viewport| {
            // Anchor::End stores an offset measured *from* the bottom.
            Message::ChatScrolled(id, viewport.absolute_offset().y <= 32.0)
        }).into()
    } else {
        let no_model = active_mode == 0 && !connected;
        let actions: Element<'a, Message> = if no_model {
            row![
                button(text("Add a provider").size(13).font(style::STRONG).color(style::BLACK))
                    .on_press(Message::OpenModelSettings).padding([11, 18]).style(style::primary_button),
                button(text("Open settings").size(13).font(style::LABEL).color(style::GREY))
                    .on_press(Message::Navigate(Page::Settings)).padding([11, 14]).style(style::ghost_button)
            ].spacing(8).align_y(Center).into()
        } else if active_mode != 0 {
            button(text("Switch this draft to Chat").size(12).font(style::LABEL).color(style::GREY))
                .on_press(Message::SelectMode(0)).padding([9, 14]).style(style::ghost_button).into()
        } else {
            button(text("Manage models").size(12).font(style::LABEL).color(style::GREY))
                .on_press(Message::OpenModelCatalogSettings).padding([9, 14]).style(style::ghost_button).into()
        };
        container(column![
            icon(Glyph::Monitor, 44, style::MUTED_2),
            space().height(20),
            text(empty_heading(active_mode, connected)).size(26).font(style::STRONG).color(style::WHITE),
            space().height(10),
            text(empty_body(active_mode, connected)).size(15).color(style::GREY),
            space().height(24),
            actions
        ].align_x(Center)).center_x(Fill).center_y(Fill).into()
    };

    let can_send = active_mode == 0 && connected && !draft_text.trim().is_empty() && current.is_some_and(|draft| !draft.busy);
    let editor: Element<'_, Message> = if let Some(draft) = current {
        text_editor::<Message, iced::Theme, iced::Renderer>(&draft.editor)
            .placeholder(if active_mode == 0 { "Send a message…  (Enter to send, Shift+Enter for a new line)" }
                else { "Draft only · this mode cannot send" })
            .height(42).max_height(126).padding([8, 10]).size(15)
            .style(style::chat_editor)
            .on_action(move |action| Message::EditEditor(selected, crate::app::EditorAction(action)))
            .key_binding(move |event| {
                if can_send && event.key == keyboard::Key::Named(keyboard::key::Named::Enter)
                    && !event.modifiers.shift() && !event.modifiers.command() && !event.modifiers.alt() {
                    Some(text_editor::Binding::Custom(Message::SendChat))
                } else { text_editor::Binding::from_key_press(event) }
            }).into()
    } else { space().height(42).into() };
    let is_busy = current.is_some_and(|draft| draft.busy);
    let send_control: Element<'_, Message> = if is_busy {
        button(container(icon(Glyph::Stop, 15, style::WHITE)).center_x(Fill).center_y(Fill))
            .on_press(Message::StopChat).width(34).height(34).padding(0)
            .style(style::ghost_button).into()
    } else {
        button(container(icon(Glyph::Send, 16, style::BLACK)).center_x(Fill).center_y(Fill))
            .on_press_maybe(can_send.then_some(Message::SendChat)).width(34).height(34).padding(0)
            .style(style::chat_send).into()
    };
    let composer = container(column![
        editor,
        row![
            button(text(if settings.stream_chat { "Streaming" } else { "Whole reply" }).size(11).font(style::LABEL))
                .on_press(Message::ToggleStreaming).padding([5, 11])
                .style(move |t, s| style::mini_toggle(settings.stream_chat, t, s)),
            space().width(Fill),
            send_control
        ].align_y(Center)
    ].spacing(6)).max_width(860).width(Fill)
        .padding(iced::Padding { top: 12.0, right: 12.0, bottom: 8.0, left: 12.0 }).style(style::chat_panel);
    let error_notice: Element<'_, Message> = match current.and_then(|draft| draft.error.as_deref()) {
        Some(error) => container(text(error.to_owned()).size(12).color(style::WHITE))
            .max_width(860).width(Fill).padding([7, 12]).style(style::chat_error).into(),
        None => space().height(0).into(),
    };
    let jump: Element<'_, Message> = if current.is_some_and(|draft| !draft.follow_tail && !draft.turns.is_empty()) {
        button(row![icon(Glyph::ArrowDown, 13, style::WHITE), text("Jump to latest").size(12).font(style::LABEL).color(style::WHITE)]
            .spacing(7).align_y(Center))
            .on_press(Message::JumpToLatest)
            .padding([8, 14]).style(style::jump_pill).into()
    } else { space().height(0).into() };
    let footer = column![
        error_notice,
        jump,
        container(composer).center_x(Fill),
        space().height(8),
        text("Chats are session-only · keys stay in the OS credential vault · replies use up to 12 recent turns")
            .size(11).color(style::DIM),
    ].align_x(Center).width(Fill).padding([12, 20]);

    let main = column![
        container(topbar).padding([12, 20]).width(Fill).style(style::settings_header),
        center,
        footer
    ].width(Fill).height(Fill);
    let main: Element<'a, Message> = if model_menu_open || mode_menu_open {
        let menu: Element<'a, Message> = if model_menu_open { model_menu(settings, search) } else { mode_menu(active_mode) };
        stack![main, container(menu).width(Fill).height(Fill).padding([57, 12])
            .align_x(if model_menu_open { iced::alignment::Horizontal::Left }
                else { iced::alignment::Horizontal::Right })
            .align_y(iced::alignment::Vertical::Top)].width(Fill).height(Fill).into()
    } else { main.into() };
    row![rail, main].width(Fill).height(Fill).into()
}

/// Agent-owned settings share its navigation, never the launcher navigation.
pub fn settings_shell(drafts: &[ChatDraft], selected: u32, settings: &SettingsState,
    memory: crate::app::MemoryMode, keep_agent: bool) -> Element<'static, Message> {
    let shell = row![rail(drafts, selected, settings, true), crate::settings::view(settings, memory, keep_agent)]
        .width(Fill).height(Fill);
    if settings.section == crate::settings::Section::Models && settings.catalog_modal {
        stack![shell, crate::settings::catalog_overlay(settings)].width(Fill).height(Fill).into()
    } else { shell.into() }
}

#[cfg(test)]
mod tests {
    use super::{MODES, conn_label, empty_body, empty_heading, endpoint_label, icon, Glyph};
    use iced::Color;
    use std::collections::HashSet;

    #[test]
    fn six_preview_modes_are_distinct() {
        assert_eq!(MODES.len(), 6);
        assert_eq!(MODES.iter().collect::<HashSet<_>>().len(), 6);
    }

    #[test]
    fn empty_state_copy_is_honest_about_setup_and_previews() {
        assert_eq!(empty_heading(0, false), "No provider configured");
        assert_eq!(empty_heading(0, true), "How can I help?");
        assert_eq!(empty_heading(3, true), "Coding");
        assert!(empty_body(0, false).contains("OS credential store"));
        assert_eq!(empty_body(2, true), "This mode is a preview. No tools are running.");
        assert!(empty_body(0, true).contains("markdown"));
    }

    #[test]
    fn endpoint_label_reports_real_configuration_state() {
        assert_eq!(endpoint_label("OpenRouter", None), "no provider configured");
        assert_eq!(endpoint_label("Groq", Some("llama-3.3-70b")), "Groq · llama-3.3-70b");
        assert_eq!(conn_label(false), "not configured");
        assert_eq!(conn_label(true), "model selected");
    }

    #[test]
    fn agent_chrome_icons_load_from_compiled_assets() {
        for glyph in [Glyph::Monitor, Glyph::Send, Glyph::Stop, Glyph::Chevron, Glyph::Plus,
            Glyph::ArrowDown, Glyph::Message, Glyph::Lock, Glyph::Settings, Glyph::House] {
            let _ = icon(glyph, 15, Color::from_rgb8(255, 255, 255));
        }
    }
}
