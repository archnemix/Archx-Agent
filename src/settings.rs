//! Purpose: Renders separate Lab, provider-vault and session model settings surfaces.
use std::fmt;
use std::time::Instant;

use iced::widget::{button, column, container, row, scrollable, space, text, text_input};
use iced::{Element, Fill};
use zeroize::Zeroizing;

use crate::app::{MemoryMode, Message};
use crate::credentials::Provider;
use crate::custom_endpoint::Profile;
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
    pub catalog: [Vec<CatalogModel>; Provider::COUNT],
    pub search: String,
    pub catalog_selected: [Vec<String>; Provider::COUNT],
    pub probe_pending: bool,
    pub probe_busy: bool,
    pub probe_nonce: u64,
    pub probe_results: Vec<(String, bool, String)>,
    pub catalog_busy: bool,
    pub catalog_nonce: u64,
    pub models: [Vec<String>; Provider::COUNT],
    pub chosen: [Option<usize>; Provider::COUNT],
    pub status: String,
    pub test_busy: bool,
    pub test_evidence: Option<String>,
    pub stream_chat: bool,
    pub key_busy: bool,
    pub custom: Profile,
    pub custom_curl: SecretText,
    pub custom_approved: bool,
    pub expected_word: String,
}
impl Default for SettingsState {
    fn default() -> Self {
        Self { section: Section::Providers, provider: Provider::OpenRouter,
            key_entry: SecretText::default(), key_ids: Vec::new(), reveal: None,
            reveal_nonce: 0, model_entry: String::new(), catalog: std::array::from_fn(|_| Vec::new()),
            search: String::new(), catalog_selected: std::array::from_fn(|_| Vec::new()),
            probe_pending: false, probe_busy: false, probe_nonce: 0, probe_results: Vec::new(), catalog_busy: false, catalog_nonce: 0, models: std::array::from_fn(|_| Vec::new()),
            chosen: [None; Provider::COUNT], status: String::new(), test_busy: false, test_evidence: None, stream_chat: true, key_busy: false, custom: Profile::default(), custom_curl: SecretText::default(), custom_approved: false, expected_word: "OK".into() }
    }
}
impl SettingsState {
    pub fn index(&self) -> usize { self.provider.index() }
    pub fn selected_model(&self) -> Option<&str> {
        self.chosen[self.index()].and_then(|id| self.models[self.index()].get(id)).map(String::as_str)
    }
    pub fn clear_secret(&mut self) {
        self.key_entry = SecretText::default();
        self.reveal = None;
        self.reveal_nonce = self.reveal_nonce.wrapping_add(1);
    }
}

fn surface(content: impl Into<Element<'static, Message>>) -> Element<'static, Message> {
    container(content).width(Fill).padding(22).style(style::chat_panel).into()
}

pub fn view(state: &SettingsState, memory: MemoryMode, keep_agent: bool) -> Element<'static, Message> {
    let (heading, description) = match state.section {
        Section::Providers => ("Providers", "Set up a provider or custom endpoint. Nothing is sent until you choose to request or explicitly test a model."),
        Section::Models => ("Models", "Choose IDs to import; optionally test them first. A passing probe cannot guarantee future availability."),
        Section::Lab => ("Lab preview", "These options do not yet affect device memory."),
    };
    let nav = column![
        text("SETTINGS").size(10).color(style::DIM),
        space().height(15),
        setting_link("Providers", Section::Providers, state.section),
        setting_link("Models", Section::Models, state.section),
        space().height(14),
        container(space().height(1)).width(Fill).style(style::rail_divider),
        space().height(14),
        setting_link("Lab preview", Section::Lab, state.section),
        space().height(Fill),
        text("Local session").size(11).color(style::DIM),
    ].spacing(6).height(Fill).width(Fill).padding(16);
    let body = column![
        text("LAB  /  SETTINGS").size(10).color(style::DIM),
        space().height(14),
        text(heading).size(29).font(style::DISPLAY).color(style::WHITE),
        space().height(8),
        text(description).size(13).color(style::GREY),
        space().height(24),
        match state.section {
            Section::Providers => providers(state),
            Section::Models => models(state),
            Section::Lab => lab(memory, keep_agent),
        },
        space().height(18),
        text(state.status.clone()).size(12).color(style::GREY)
    ].width(Fill).padding([28, 30]);
    row![
        container(nav).width(170).height(Fill).style(style::rail),
        scrollable(body).width(Fill).height(Fill)
    ].width(Fill).height(Fill).into()
}

fn setting_link(label: &'static str, section: Section, current: Section) -> Element<'static, Message> {
    button(text(label).size(13)).width(Fill).padding([11, 12])
        .on_press(Message::SettingsSection(section))
        .style(move |t, status| style::chat_menu_choice(section == current, t, status)).into()
}

fn provider_tabs(current: Provider, busy: bool) -> Element<'static, Message> {
    let mut rows = column![].spacing(6);
    for group in Provider::ALL.chunks(4) {
        let mut line = row![].spacing(6);
        for provider in group.iter().copied() {
            let selected = current == provider;
            line = line.push(button(text(provider.name()).size(12))
                .width(150).padding([9, 12]).on_press_maybe((!busy).then_some(Message::SelectProvider(provider)))
                .style(move |theme, status| style::chat_menu_choice(selected, theme, status)));
        }
        rows = rows.push(line);
    }
    rows.into()
}

fn providers(state: &SettingsState) -> Element<'static, Message> {
    let mut keys = column![text("SAVED KEY SLOTS").size(11).color(style::DIM)].spacing(10);
    if state.key_ids.is_empty() {
        keys = keys.push(text(if state.provider.needs_key() { "No saved keys. Custom endpoints can also work without a key." } else { "No key needed. Select Models to browse the local Ollama server." }).size(13).color(style::GREY));
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
    let credential_control: Element<'static, Message> = if state.provider.needs_key() {
        column![text_input::<Message, iced::Theme, iced::Renderer>("Paste an API key", state.key_entry.0.as_str()).secure(true)
            .on_input(|value| Message::EditKey(SecretText::new(value)))
            .padding([13, 15]).style(style::composer_input),
            button(text("Save key to OS vault").size(12))
                .on_press_maybe((!state.key_busy && !state.key_entry.0.is_empty()).then_some(Message::SaveKey))
                .padding([11, 15]).style(style::chat_button)].spacing(10).into()
    } else {
        button(text("Browse local Ollama models ↗").size(12)).on_press(Message::OpenModelCatalogSettings)
            .style(style::chat_button).into()
    };
    surface(column![
        text("PROVIDER  /  OS KEYCHAIN").size(11).color(style::DIM),
        space().height(12), provider_tabs(state.provider, state.key_busy),
        space().height(17),
        text(if state.provider.needs_key() { "Keys are held in your OS credential store. The Lab never saves a plaintext key file." }
            else { "Local Ollama: fixed loopback address 127.0.0.1:11434 · no key needed · no remote URL accepted." })
            .size(13).color(style::GREY),
        space().height(18),
        credential_control,
        space().height(26), keys,
        if state.provider == Provider::Custom { custom_controls(state) } else { space().height(0).into() },
        space().height(12),
        text("Reveal is opt-in and hidden after 15 seconds or when you leave this page. Anyone with access to your unlocked session or screen may still see it.")
            .size(11).color(style::DIM)
    ].width(Fill))
}

fn models(state: &SettingsState) -> Element<'static, Message> {
    let index = state.index();
    let mut list = column![text("ADDED MODELS  /  THIS SESSION · ACTIVE MODEL CAN ALSO BE CHANGED IN CHAT").size(11).color(style::DIM)].spacing(10);
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
        text("MODEL CATALOG  /  EXPLICIT IMPORT").size(11).color(style::DIM),
        space().height(12),
        provider_tabs(state.provider, state.key_busy || state.probe_busy),
        space().height(14),
        text("Select a provider, fetch its list and check only the IDs you want. Or add an exact model ID below. Import never triggers a generation test.")
            .size(13).color(style::GREY),
        space().height(13),
        if state.provider == Provider::Custom { text("Custom endpoints have no discovery endpoint. Enter an exact model ID below; requests require separate destination approval.").size(12).color(style::GREY).into() } else { catalog_view(state) },
        space().height(26),
        text("ADD AN EXACT ID MANUALLY").size(11).color(style::DIM),
        text_input("e.g. provider/model:free", &state.model_entry)
            .on_input(Message::EditModel).padding([13, 15]).style(style::composer_input),
        space().height(10),
        button(text("Add model").size(12)).on_press(Message::AddModel).padding([11, 15]).style(style::quiet_button),
        space().height(23), list,
        space().height(16),
        text("Explicit test: sends a small prompt to the selected provider/model. Output cap 256 tokens; this may be billable and total tokens are not guaranteed.")
            .size(12).color(style::GREY),
        space().height(12),
        text_input("Expected test word (default OK)", &state.expected_word).on_input(Message::ExpectedWord)
            .padding([11, 15]).style(style::composer_input),
        button(text("Run small generation test  ↗").size(12))
            .on_press_maybe((state.selected_model().is_some() && !state.test_busy).then_some(Message::RunTest))
            .padding([11, 15]).style(style::quiet_button),
        space().height(8),
        text(state.test_evidence.clone().unwrap_or_default()).size(11).color(style::GREY),
        space().height(18),
        text("Catalog labels reflect provider metadata at fetch time, not a price guarantee. Generation is a separate explicit action.")
            .size(12).color(style::DIM)
    ].width(Fill))
}


// Keep the visible list bounded; search narrows large catalogs. Nothing is
// checked or probed on fetch. A probe requires a second explicit confirmation.
fn catalog_view(state: &SettingsState) -> Element<'static, Message> {
    let index = state.index();
    let query = state.search.trim().to_lowercase();
    let matching: Vec<_> = state.catalog[index].iter().enumerate()
        .filter(|(_, model)| query.is_empty() || model.id.to_lowercase().contains(&query) || model.name.to_lowercase().contains(&query))
        .collect();
    let checked = state.catalog_selected[index].len();
    let mut items = column![].spacing(6).width(Fill);
    for (slot, model) in matching.iter().copied().take(24) {
        let selected = state.catalog_selected[index].contains(&model.id);
        let added = state.models[index].contains(&model.id);
        let label = format!("{}  {}{}{}", if selected { "☑" } else { "□" }, model.id,
            if model.free { "  ·  free at fetch" } else { "" },
            if added { "  ·  in list" } else { "" });
        let mut entry = column![button(text(label).size(12)).width(Fill)
            .padding([8, 11]).on_press(Message::ToggleCatalogSelection(state.provider, slot))
            .style(move |t, status| style::chat_menu_choice(selected, t, status))].spacing(4);
        if let Some((_, ok, output)) = state.probe_results.iter().find(|(id, _, _)| id == &model.id) {
            entry = entry.push(text(format!("{}  ·  Sent: Reply with the word OK.  ·  Received: {}",
                if *ok { "✓ Reply received" } else { "× Probe failed" }, output))
                .size(11).color(if *ok { style::GREY } else { style::DIM }));
        }
        items = items.push(entry);
    }
    let pending: Element<'static, Message> = if state.probe_pending {
        row![
            text(format!("Run {checked} small generation probe(s)? Each sends a billable request with up to 256 output tokens. No automatic retries.")).size(11).color(style::WHITE).width(Fill),
            button(text("Cancel").size(11)).on_press(Message::CancelCatalogProbe).style(style::chat_button),
            button(text("Confirm tests ↗").size(11)).on_press(Message::ConfirmCatalogProbe).style(style::chat_button)
        ].spacing(8).align_y(iced::Center).into()
    } else { space().height(0).into() };
    column![
        row![
            text("AVAILABLE FROM PROVIDER").size(11).color(style::DIM).width(Fill),
            button(text(if state.catalog_busy { "Fetching…" } else { "Fetch models  ↗" }).size(12))
                .on_press_maybe((!state.catalog_busy && !state.probe_busy).then_some(Message::FetchModels))
                .padding([8, 12]).style(style::chat_button)
        ].align_y(iced::Center),
        space().height(10),
        text_input("Filter model names and IDs…", &state.search).on_input(Message::SearchModels)
            .padding([10, 13]).style(style::composer_input),
        space().height(8),
        text(format!("{} available · {} matching · {} checked (limit 10). All models start unchecked.",
            state.catalog[index].len(), matching.len(), checked)).size(11).color(style::DIM),
        space().height(10),
        row![
            button(text("Import checked IDs").size(12))
                .on_press_maybe((checked > 0 && !state.probe_busy).then_some(Message::ImportSelectedModels))
                .padding([9, 12]).style(style::chat_button),
            button(text(if state.probe_busy { "Testing…" } else { "Test checked first…" }).size(12))
                .on_press_maybe((checked > 0 && !state.probe_busy).then_some(Message::RequestCatalogProbe))
                .padding([9, 12]).style(style::chat_button),
            if state.probe_busy { button(text("Stop tests").size(12)).on_press(Message::CancelCatalogProbe).style(style::chat_button) }
            else { button(text("Stop tests").size(12)).style(style::chat_menu_choice_inactive) }
        ].spacing(8),
        pending,
        space().height(12),
        items,
        text(if matching.len() > 24 { "Showing 24 matches. Filter to find more." } else { "Catalog metadata is not a guarantee of availability or pricing." })
            .size(11).color(style::DIM)
    ].spacing(6).width(Fill).into()
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

fn custom_controls(state: &SettingsState) -> Element<'static, Message> {
    let p = &state.custom;
    column![
        space().height(20),
        text("CUSTOM TEXT ENDPOINT  /  SESSION ONLY").size(12).color(style::WHITE),
        row![button(text("OpenAI-compatible preset").size(11)).on_press(Message::CustomOpenAiPreset).style(style::quiet_button),
            button(text("Anthropic-compatible preset").size(11)).on_press(Message::CustomAnthropicPreset).style(style::quiet_button)].spacing(8),
        text("HTTPS, or HTTP loopback only. No redirects, proxies, files, shell execution or saved profile. Your prompt and optional OS-vault key go to this exact destination only after approval.").size(12).color(style::GREY),
        text_input("https://example.com/chat", &p.url).on_input(Message::CustomUrl).padding(11).style(style::composer_input),
        text_input("Headers: Name: value | Name: value (or use cURL); {{api_key}} for vault key", p.headers.as_str())
            .on_input(|s| Message::CustomHeaders(SecretText::new(s))).padding(11).style(style::composer_input),
        text_input("JSON body with {{prompt}} or {{messages}}", &p.body).on_input(Message::CustomBody).padding(11).style(style::composer_input),
        text_input("Answer JSON pointer, e.g. /result/text", &p.answer_pointer).on_input(Message::CustomAnswer).padding(11).style(style::composer_input),
        button(text(if p.stream { "Streaming: SSE data JSON" } else { "Streaming: off (JSON response)" }).size(12))
            .on_press(Message::CustomStream).style(style::quiet_button),
        if p.stream { text_input::<Message, iced::Theme, iced::Renderer>("SSE delta JSON pointer", &p.stream_pointer).on_input(Message::CustomDelta).padding(11).style(style::composer_input).into() }
            else { space().height(0).into() },
        text("Or paste a literal cURL POST request (JSON body; no shell evaluation):").size(12).color(style::GREY),
        text_input("curl -X POST https://... -H 'Authorization: Bearer {{api_key}}' -d '{...}'", state.custom_curl.0.as_str())
            .secure(true).on_input(|s| Message::CustomCurl(SecretText::new(s))).padding(11).style(style::composer_input),
        button(text("Parse cURL into fields").size(12)).on_press(Message::ImportCustomCurl).style(style::quiet_button),
        text(format!("Destination for approval: {}", if p.url.is_empty() { "not entered" } else { &p.url })).size(12).color(style::WHITE),
        button(text(if state.custom_approved { "Approved for this session · revoke" } else { "Approve sending prompts and key to this destination" }).size(12))
            .on_press(Message::ApproveCustom).style(style::chat_button),
        text("Edit any field to revoke approval. Review the displayed URL and headers before sending; custom hosts can charge or retain your data.").size(11).color(style::DIM)
    ].spacing(10).width(Fill).into()
}
