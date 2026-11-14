//! Purpose: Renders separate Lab, provider-vault and session model settings surfaces.
use std::fmt;
use std::time::Instant;

use iced::widget::{button, column, container, row, scrollable, space, text, text_input};
use iced::{Element, Fill};
use zeroize::Zeroizing;

use crate::app::{MemoryMode, Message};
use crate::credentials::Provider;
use crate::model_catalog::CatalogModel;
use crate::style;

pub struct SecretText(pub Zeroizing<String>);
// Iced buttons require Clone on the entire Message enum; only the input event
// carries this type, and any cloned allocation is independently zeroized.
impl Clone for SecretText {
    fn clone(&self) -> Self { Self::new(self.0.to_string()) }
}
impl SecretText {
    pub fn new(value: String) -> Self { Self(Zeroizing::new(value)) }
}
impl Default for SecretText {
    fn default() -> Self { Self::new(String::new()) }
}
impl fmt::Debug for SecretText {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result { f.write_str("[redacted]") }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Section { Lab, Providers, Models }

pub struct SettingsState {
    pub section: Section,
    pub provider: Provider,
    pub key_entry: SecretText,
    pub key_ids: Vec<u64>,
    pub reveal: Option<(u64, SecretText, Instant)>,
    pub reveal_nonce: u64,
    pub model_entry: String,
    pub catalog: [Vec<CatalogModel>; 3],
    pub search: String,
    pub catalog_busy: bool,
    pub catalog_nonce: u64,
    pub models: [Vec<String>; 3],
    pub chosen: [Option<usize>; 3],
    pub status: String,
    pub test_busy: bool,
    pub key_busy: bool,
}
impl Default for SettingsState {
    fn default() -> Self {
        Self { section: Section::Providers, provider: Provider::OpenRouter,
            key_entry: SecretText::default(), key_ids: Vec::new(), reveal: None,
            reveal_nonce: 0, model_entry: String::new(), catalog: std::array::from_fn(|_| Vec::new()),
            search: String::new(), catalog_busy: false, catalog_nonce: 0, models: std::array::from_fn(|_| Vec::new()),
            chosen: [None; 3], status: String::new(), test_busy: false, key_busy: false }
    }
}
impl SettingsState {
    pub fn index(&self) -> usize { match self.provider { Provider::OpenRouter => 0, Provider::Grok => 1, Provider::Gemini => 2 } }
    pub fn selected_model(&self) -> Option<&str> {
        self.chosen[self.index()].and_then(|id| self.models[self.index()].get(id)).map(String::as_str)
    }
    pub fn clear_secret(&mut self) {
        self.key_entry = SecretText::default();
        self.reveal = None;
        self.reveal_nonce = self.reveal_nonce.wrapping_add(1);
    }
}

fn section_link(label: &'static str, subtitle: &'static str, section: Section, active: bool) -> Element<'static, Message> {
    button(column![
        text(label).size(13).font(style::LABEL).color(if active { style::WHITE } else { style::GREY }),
        text(subtitle).size(10).color(style::DIM)
    ].spacing(5))
        .width(Fill).padding([13, 14]).on_press(Message::SettingsSection(section))
        .style(move |theme, status| style::settings_nav(active, theme, status)).into()
}

fn surface(content: impl Into<Element<'static, Message>>) -> Element<'static, Message> {
    container(content).width(Fill).padding(25).style(style::surface).into()
}

pub fn view(state: &SettingsState, memory: MemoryMode, keep_agent: bool) -> Element<'static, Message> {
    let section_nav = column![
        text("SETTINGS").size(10).color(style::DIM),
        space().height(19),
        section_link("Connections", "Providers & keys", Section::Providers, state.section == Section::Providers),
        space().height(7),
        section_link("Models", "Choose & test", Section::Models, state.section == Section::Models),
        space().height(22),
        container(space().height(1)).width(Fill).style(style::rail_divider),
        space().height(17),
        section_link("Lab preview", "No effect yet", Section::Lab, state.section == Section::Lab),
        space().height(Fill),
        text("LOCAL SESSION").size(10).color(style::DIM)
    ].width(Fill).height(Fill).padding([28, 14]);
    let (heading, description) = match state.section {
        Section::Providers => ("Connections", "Manage provider keys in your OS credential store. Nothing is sent until you explicitly test or send a chat."),
        Section::Models => ("Models", "Choose exact provider model IDs for this session, then run a small opt-in generation test."),
        Section::Lab => ("Lab preview", "A preview of future memory controls. These choices do not change device use."),
    };
    let body = column![
        text("LAB  /  SETTINGS").size(11).color(style::DIM),
        space().height(15),
        text(heading).size(32).font(style::DISPLAY).color(style::WHITE),
        space().height(9),
        text(description).size(14).color(style::GREY),
        space().height(27),
        match state.section {
            Section::Providers => providers(state),
            Section::Models => models(state),
            Section::Lab => lab(memory, keep_agent),
        },
        space().height(17),
        text(state.status.clone()).size(12).color(style::GREY)
    ].width(Fill).padding(32);
    row![
        container(section_nav).width(190).height(Fill).style(style::settings_panel),
        scrollable(body).width(Fill).height(Fill)
    ].width(Fill).height(Fill).into()
}

fn provider_tabs(current: Provider, busy: bool) -> Element<'static, Message> {
    Provider::ALL.into_iter().fold(row![].spacing(8), |row, provider| {
        let selected = current == provider;
        row.push(button(text(provider.name()).size(12).color(if selected { style::WHITE } else { style::GREY }))
            .padding([11, 14]).on_press_maybe((!busy).then_some(Message::SelectProvider(provider)))
            .style(move |theme, status| style::nav(selected, theme, status)))
    }).into()
}

fn providers(state: &SettingsState) -> Element<'static, Message> {
    let mut keys = column![text("SAVED KEY SLOTS").size(11).color(style::DIM)].spacing(10);
    if state.key_ids.is_empty() {
        keys = keys.push(text("No saved keys for this provider. Paste one above to store it in your OS vault.").size(13).color(style::GREY));
    }
    for id in &state.key_ids {
        let id = *id;
        let showing = state.reveal.as_ref().is_some_and(|(visible, _, until)| *visible == id && Instant::now() < *until);
        let label = if showing {
            state.reveal.as_ref().map(|(_, secret, _)| secret.0.to_string()).unwrap_or_default()
        } else { format!("Key {id}    ••••••••") };
        keys = keys.push(row![
            text(label).size(13).color(style::WHITE).width(Fill),
            button(text(if showing { "Hide" } else { "Reveal 15s" }).size(11))
                .on_press(if showing { Message::HideKey } else { Message::RevealKey(id) }).style(style::quiet_button),
            button(text("Remove").size(11)).on_press_maybe((!state.key_busy).then_some(Message::RemoveKey(id))).style(style::quiet_button)
        ].spacing(10));
    }
    surface(column![
        text("PROVIDERS  /  OS VAULT").size(11).color(style::DIM),
        space().height(12), provider_tabs(state.provider, state.key_busy),
        space().height(17),
        text("Keys are held in your OS credential store. The Lab never saves a plaintext key file.")
            .size(13).color(style::GREY),
        space().height(18),
        text_input("Paste an API key", state.key_entry.0.as_str()).secure(true)
            .on_input(|value| Message::EditKey(SecretText::new(value)))
            .padding([13, 15]).style(style::composer_input),
        space().height(10),
        button(text("Save key to OS vault").size(12)).on_press_maybe((!state.key_busy && !state.key_entry.0.is_empty()).then_some(Message::SaveKey))
            .padding([11, 15]).style(style::quiet_button),
        space().height(26), keys,
        space().height(12),
        text("Reveal is opt-in and hidden after 15 seconds or when you leave this page. Anyone with access to your unlocked session or screen may still see it.")
            .size(11).color(style::DIM)
    ].width(Fill))
}

fn models(state: &SettingsState) -> Element<'static, Message> {
    let index = state.index();
    let mut list = column![text("ADDED MODELS  /  THIS SESSION").size(11).color(style::DIM)].spacing(10);
    for (slot, name) in state.models[index].iter().enumerate() {
        let active = state.chosen[index] == Some(slot);
        list = list.push(row![
            button(text(name.clone()).size(13).color(if active { style::WHITE } else { style::GREY }))
                .width(Fill).on_press(Message::ChooseModel(slot))
                .style(move |theme, status| style::nav(active, theme, status)),
            button(text("Remove").size(11)).on_press(Message::RemoveModel(slot)).style(style::quiet_button)
        ].spacing(10));
    }
    surface(column![
        text("MODELS  /  MANUAL IDENTIFIERS").size(11).color(style::DIM),
        space().height(12), provider_tabs(state.provider, state.key_busy),
        space().height(18),
        text("Type the exact provider model ID. IDs are not verified until a live request; a :free OpenRouter variant is distinct from its paid model.")
            .size(13).color(style::GREY),
        space().height(13),
        text_input("e.g. provider/model:free", &state.model_entry)
            .on_input(Message::EditModel).padding([13, 15]).style(style::composer_input),
        space().height(10),
        button(text("Add model").size(12)).on_press(Message::AddModel).padding([11, 15]).style(style::quiet_button),
        space().height(23), list,
        space().height(24), catalog_view(state),
        space().height(16),
        text("Explicit test: sends only ‘Reply with the word OK.’ to the selected provider/model. Output cap 256 tokens; this may be billable and total tokens are not guaranteed.")
            .size(12).color(style::GREY),
        space().height(12),
        button(text("Run small generation test  ↗").size(12))
            .on_press_maybe((state.selected_model().is_some() && !state.test_busy).then_some(Message::RunTest))
            .padding([11, 15]).style(style::quiet_button),
        space().height(18),
        text("Catalog labels reflect provider metadata at fetch time, not a price guarantee. Generation is a separate explicit action.")
            .size(12).color(style::DIM)
    ].width(Fill))
}


// Keep the visible result count bounded; typing a query reveals deeper catalog entries.
fn catalog_view(state: &SettingsState) -> Element<'static, Message> {
    let index = state.index();
    let query = state.search.trim().to_lowercase();
    let matching: Vec<_> = state.catalog[index].iter().enumerate()
        .filter(|(_, model)| query.is_empty() || model.id.to_lowercase().contains(&query) || model.name.to_lowercase().contains(&query))
        .collect();
    let mut free = column![text("FREE AT FETCH  /  OPENROUTER ROUTER & ZERO-PRICE MODELS").size(11).color(style::DIM)].spacing(8);
    let mut other = column![text("OTHER CATALOG MODELS  /  PRICE NOT VERIFIED HERE").size(11).color(style::DIM)].spacing(8);
    let mut free_visible = 0;
    let mut other_visible = 0;
    for (slot, model) in matching.iter().copied() {
        if (model.free && free_visible >= 20) || (!model.free && other_visible >= 20) { continue; }
        if model.free { free_visible += 1; } else { other_visible += 1; }
        let label = format!("{}  ·  {}{}{}", model.name, model.id,
            if model.router { "  ·  FREE AUTO ROUTER (model varies)" } else { "" },
            if model.reasoning { "  ·  REASONING SUPPORTED" } else { "" });
        let already_added = state.models[index].contains(&model.id);
        let item = row![
            text(label).size(12).color(style::GREY).width(Fill),
            button(text(if already_added { "Added" } else { "Add" }).size(11))
                .on_press_maybe((!already_added && state.models[index].len() < 32).then_some(Message::AddCatalogModel(state.provider, slot)))
                .style(style::quiet_button)
        ].spacing(8);
        if model.free { free = free.push(item); } else { other = other.push(item); }
    }
    column![
        text("DISCOVER  /  READ-ONLY CATALOG").size(11).color(style::DIM),
        space().height(10),
        text("Fetch contacts only this provider. OpenRouter uses its public catalog; xAI and Gemini use the first saved OS-vault key. Nothing is added automatically.")
            .size(12).color(style::GREY),
        space().height(10),
        button(text(if state.catalog_busy { "Fetching…" } else { "Fetch models  ↗" }).size(12))
            .on_press_maybe((!state.catalog_busy).then_some(Message::FetchModels))
            .padding([11, 15]).style(style::quiet_button),
        space().height(10),
        text_input("Search fetched names or IDs", &state.search).on_input(Message::SearchModels)
            .padding([13, 15]).style(style::composer_input),
        space().height(10),
        text(format!("{} fetched · {} matching · showing first {}. Search to narrow results.", state.catalog[index].len(), matching.len(), free_visible + other_visible)).size(11).color(style::DIM),
        space().height(18), free,
        space().height(18), other
    ].width(Fill).into()
}

fn lab(memory: MemoryMode, keep_agent: bool) -> Element<'static, Message> {
    let custom = if memory == MemoryMode::Custom {
        button(text(if keep_agent { "Archx Agent / Keep ready" } else { "Archx Agent / Load on open" }).size(13))
            .on_press(Message::ToggleAgentPreview).style(style::quiet_button)
    } else {
        button(text("Select Custom to preview destination controls").size(13)).style(style::quiet_button)
    };
    surface(column![
        text("MEMORY  /  PREVIEW ONLY").size(11).color(style::DIM),
        space().height(16),
        text("These controls do not save preferences, load models or change RAM use.").size(13).color(style::GREY),
        space().height(20),
        row![
            button(text("Light").size(13)).on_press(Message::MemoryPreview(MemoryMode::Light)).style(move |t, s| style::nav(memory == MemoryMode::Light,t,s)),
            button(text("Heavy").size(13)).on_press(Message::MemoryPreview(MemoryMode::Heavy)).style(move |t, s| style::nav(memory == MemoryMode::Heavy,t,s)),
            button(text("Custom").size(13)).on_press(Message::MemoryPreview(MemoryMode::Custom)).style(move |t, s| style::nav(memory == MemoryMode::Custom,t,s)),
        ].spacing(10),
        space().height(20), custom
    ].width(Fill))
}
