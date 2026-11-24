//! Purpose: Renders separate Lab, provider-vault and session model settings surfaces.
use std::collections::HashSet;
use std::fmt;
use std::time::Instant;

use iced::widget::{button, column, container, row, scrollable, space, stack, text, text_input};
use iced::{Center, Element, Fill};
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
    /// Manual IDs staged in the current import dialog, never added until import.
    pub catalog_manual: [Vec<String>; Provider::COUNT],
    pub search: String,
    pub catalog_modal: bool,
    pub catalog_only_verified: bool,
    pub catalog_page: usize,
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
            catalog_manual: std::array::from_fn(|_| Vec::new()),
            search: String::new(), catalog_modal: false, catalog_only_verified: false, catalog_page: 0, catalog_selected: std::array::from_fn(|_| Vec::new()),
            probe_pending: false, probe_busy: false, probe_nonce: 0, probe_results: Vec::new(), catalog_busy: false, catalog_nonce: 0, models: std::array::from_fn(|_| Vec::new()),
            chosen: [None; Provider::COUNT], status: String::new(), test_busy: false, test_evidence: None, stream_chat: true, key_busy: false, custom: Profile::default(), custom_curl: SecretText::default(), custom_approved: false, expected_word: "OK".into() }
    }
}
impl SettingsState {
    pub fn index(&self) -> usize { self.provider.index() }
    /// A model counts as verified only if the most recent explicit probe
    /// returned the configured word. An untested model never passes this filter.
    pub fn importable_catalog_ids(&self) -> Vec<String> {
        let index = self.index();
        let catalog: HashSet<&str> = self.catalog[index].iter().map(|item| item.id.as_str()).collect();
        let added: HashSet<&str> = self.models[index].iter().map(String::as_str).collect();
        let verified: HashSet<&str> = self.probe_results.iter()
            .filter(|(_, ok, _)| *ok).map(|(id, _, _)| id.as_str()).collect();
        self.catalog_selected[index].iter().filter(|id| {
            catalog.contains(id.as_str()) && !added.contains(id.as_str()) &&
            (!self.catalog_only_verified || verified.contains(id.as_str()))
        }).cloned().collect()
    }
    /// Discard provisional IDs when leaving the dialog (or changing providers).
    /// No staged model enters the Agent's imported list on Cancel.
    pub fn discard_catalog_staging(&mut self) {
        let index = self.index();
        let staged: HashSet<&str> = self.catalog_manual[index].iter().map(String::as_str).collect();
        self.catalog[index].retain(|item| !staged.contains(item.id.as_str()));
        self.catalog_selected[index].retain(|id| !staged.contains(id.as_str()));
        self.probe_results.retain(|(id, _, _)| !staged.contains(id.as_str()));
        self.catalog_manual[index].clear();
        self.model_entry.clear();
    }
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
    container(content).width(Fill).padding(20).style(style::card).into()
}

fn eyebrow(label: &'static str) -> Element<'static, Message> {
    // Reference `.set-sec h4`: uppercase section label in `--accent`.
    text(label).size(12).font(style::STRONG).color(style::WHITE).into()
}

/// 17px reference checkbox (`.model-import-row input[type="checkbox"]`).
fn checkbox_box(checked: bool) -> Element<'static, Message> {
    let mark: Element<'static, Message> = if checked {
        text("✓").size(11).color(style::BLACK).into()
    } else {
        space().width(0).height(0).into()
    };
    container(mark).width(17).height(17).align_x(Center).align_y(Center)
        .style(move |t| style::checkbox(checked, t)).into()
}

/// Outlined status pill from the reference import rows (`free`, `✓ works`, …).
fn tag(label: impl Into<String>, ok: Option<bool>) -> Element<'static, Message> {
    let color = match ok {
        Some(true) => style::OK,
        Some(false) => style::FAILURE,
        None => style::GREY,
    };
    container(text(label.into()).size(10).color(color))
        .padding([2, 8]).style(move |t| style::tag_badge(ok, t)).into()
}

/// Compact inline probe summary: "✓ works · 42 ms" or "✗ HTTP 429 · …".
pub fn probe_summary(ok: bool, output: &str) -> String {
    if ok {
        let first = output.split(" · ").next().unwrap_or("").trim();
        if first.is_empty() { "✓ works".to_owned() } else { format!("✓ works · {first}") }
    } else {
        let short: String = output.chars().take(38).collect();
        if output.chars().count() > 38 { format!("✗ {short}…") } else { format!("✗ {short}") }
    }
}

pub fn view(state: &SettingsState, memory: MemoryMode, keep_agent: bool) -> Element<'static, Message> {
    let (heading, description) = match state.section {
        Section::Providers => ("Providers", "Set up a provider or custom endpoint. Nothing is sent until you choose to request or explicitly test a model."),
        Section::Models => ("Models", "Choose IDs to import; optionally test them first. A passing probe cannot guarantee future availability."),
        Section::Lab => ("Lab preview", "These options do not yet affect device memory."),
    };
    let status_notice: Element<'static, Message> = if state.status.is_empty() { space().height(0).into() }
    else { column![
        container(text(state.status.clone()).size(12).color(style::WHITE))
            .padding([9, 12]).width(Fill).style(style::chat_panel),
        space().height(12)
    ].into() };
    let page_head = container(column![
        text("Settings").size(24).font(style::STRONG).color(style::WHITE),
        text("Manage the Agent's providers and models. Other reference features are not yet available here.")
            .size(12.5).color(style::GREY)
    ].spacing(5)).width(Fill).padding([18, 28]).style(style::settings_header);
    let category = container(scrollable(column![
        setting_link("Providers", Section::Providers, state.section),
        setting_link("Models", Section::Models, state.section),
        setting_link("Lab preview", Section::Lab, state.section)
    ].spacing(4).padding([16, 12])).height(Fill).style(style::quiet_scroll)).width(200).height(Fill).style(style::rail);
    let body = column![
        eyebrow("AGENT SETTINGS"),
        space().height(8),
        text(heading).size(20).font(style::STRONG).color(style::WHITE),
        space().height(6),
        text(description).size(13).color(style::GREY),
        space().height(20),
        status_notice,
        match state.section {
            Section::Providers => providers(state),
            Section::Models => models(state),
            Section::Lab => lab(memory, keep_agent),
        }
    ].width(Fill).padding(iced::Padding { top: 24.0, right: 28.0, bottom: 40.0, left: 28.0 });
    let base = column![
        page_head,
        container(space().height(1)).width(Fill).style(style::rail_divider),
        row![
            category,
            container(space().width(1)).height(Fill).style(style::rail_divider),
            scrollable(container(body).max_width(960).center_x(Fill)).width(Fill).height(Fill)
                .style(style::quiet_scroll)
        ].width(Fill).height(Fill)
    ].width(Fill).height(Fill);
    base.into()
}

/// The reference dialog is centered over the *entire* Agent window, not the
/// settings content column. Agent's settings shell stacks this over its rail.
pub fn catalog_overlay(state: &SettingsState) -> Element<'static, Message> {
    stack![
        button(text(" ")).width(Fill).height(Fill)
            .on_press(Message::CloseCatalogModal).style(style::catalog_scrim),
        container(catalog_dialog(state)).center_x(Fill).center_y(Fill)
            .width(Fill).height(Fill)
    ].width(Fill).height(Fill).into()
}

fn setting_link(label: &'static str, section: Section, current: Section) -> Element<'static, Message> {
    let active = section == current;
    let bar: Element<'static, Message> = if active {
        container(space().width(2).height(16))
            .style(|_| container::Style::default().background(style::ACCENT)
                .border(iced::Border { radius: 1.0.into(), ..iced::Border::default() })).into()
    } else {
        space().width(2).height(16).into()
    };
    button(row![bar, text(label).size(13.5).font(style::LABEL)].spacing(10).align_y(Center))
        .width(Fill).padding([8, 10])
        .on_press(Message::SettingsSection(section))
        .style(move |t, status| style::sub_nav(active, t, status)).into()
}

fn provider_tabs(current: Provider, busy: bool) -> Element<'static, Message> {
    let mut rows = column![].spacing(5);
    for group in Provider::ALL.chunks(3) {
        let mut line = row![].spacing(6);
        for provider in group.iter().copied() {
            let selected = current == provider;
            line = line.push(button(text(provider.name()).size(12))
                .width(135).padding([8, 10]).on_press_maybe((!busy).then_some(Message::SelectProvider(provider)))
                .style(move |theme, status| style::provider_choice(selected, theme, status)));
        }
        rows = rows.push(line);
    }
    rows.into()
}

fn providers(state: &SettingsState) -> Element<'static, Message> {
    let mut keys = column![eyebrow("SAVED KEY SLOTS")].spacing(10);
    if state.key_ids.is_empty() {
        keys = keys.push(text(if state.provider.needs_key() { if state.provider == Provider::Custom { "No saved key. Custom endpoints can work without a key." } else { "No saved keys. Paste one above to store it in your OS vault." } } else { "No key needed. Select Models to browse the local Ollama server." }).size(13).color(style::GREY));
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
                .on_press(if showing { Message::HideKey } else { Message::RevealKey(id) }).style(style::tiny_button),
            button(text("Remove").size(11)).on_press_maybe((!state.key_busy).then_some(Message::RemoveKey(id))).style(style::tiny_button)
        ].spacing(10));
    }
    let credential_control: Element<'static, Message> = if state.provider.needs_key() {
        column![text_input::<Message, iced::Theme, iced::Renderer>("Paste an API key", state.key_entry.0.as_str()).secure(true)
            .on_input(|value| Message::EditKey(SecretText::new(value)))
            .padding([13, 15]).style(style::composer_input),
            button(text("Save key to OS vault").size(12))
                .on_press_maybe((!state.key_busy && !state.key_entry.0.is_empty()).then_some(Message::SaveKey))
                .padding([11, 15]).style(style::control_button)].spacing(10).into()
    } else {
        button(text("Browse local Ollama models ↗").size(12)).on_press(Message::OpenModelCatalogSettings)
            .style(style::control_button).into()
    };
    surface(column![
        eyebrow("PROVIDER  /  CONNECTION"),
        space().height(12), provider_tabs(state.provider, state.key_busy),
        space().height(17),
        if state.provider == Provider::Custom { custom_controls(state) } else { space().height(0).into() },
        space().height(17),
        text(if state.provider.needs_key() { "Keys are held in your OS credential store. The Lab never saves a plaintext key file." }
            else { "Local Ollama: fixed loopback address 127.0.0.1:11434 · no key needed · no remote URL accepted." })
            .size(13).color(style::GREY),
        space().height(18),
        credential_control,
        space().height(26), keys,
        space().height(12),
        text("Reveal is opt-in and hidden after 15 seconds or when you leave this page. Anyone with access to your unlocked session or screen may still see it.")
            .size(11).color(style::DIM)
    ].width(Fill))
}

fn models(state: &SettingsState) -> Element<'static, Message> {
    let index = state.index();
    let mut list = column![].spacing(8);
    if state.models[index].is_empty() {
        list = list.push(text("No models added yet. Use Add models to import IDs into this session.")
            .size(13).color(style::GREY));
    }
    for (slot, name) in state.models[index].iter().enumerate() {
        let active = state.chosen[index] == Some(slot);
        list = list.push(row![
            button(text(name.clone()).size(13).color(if active { style::WHITE } else { style::GREY }))
                .width(Fill).padding([9, 12]).on_press(Message::ChooseModel(slot))
                .style(move |theme, status| style::list_row(active, theme, status)),
            button(text("Remove").size(11)).on_press(Message::RemoveModel(slot)).style(style::tiny_button)
        ].spacing(8));
    }
    column![
        surface(column![
            eyebrow("MODEL CATALOG  /  EXPLICIT IMPORT"),
            space().height(12),
            provider_tabs(state.provider, state.key_busy || state.probe_busy),
            space().height(14),
            text("Manage the models available in this Agent. The catalog only shows IDs that are not already added.")
                .size(13).color(style::GREY),
            space().height(13),
            button(text("Add models…  ↗").size(13).font(style::LABEL)).on_press(Message::OpenCatalogModal)
                .padding([10, 14]).style(style::control_button),
            space().height(10),
            text("Fetching, selecting and optional generation tests take place in the Add models dialog. No test is sent just by opening it.")
                .size(11.5).color(style::DIM)
        ].width(Fill)),
        surface(column![
            eyebrow("ADDED MODELS  /  THIS SESSION · ACTIVE MODEL CAN ALSO BE CHANGED IN CHAT"),
            space().height(12), list
        ].width(Fill)),
        surface(column![
            eyebrow("OPTIONAL GENERATION TEST"),
            space().height(12),
            text("Explicit test: sends a small prompt to the selected provider/model. Output cap 256 tokens; this may be billable and total tokens are not guaranteed.")
                .size(12.5).color(style::GREY),
            space().height(12),
            text_input("Expected test word (default OK)", &state.expected_word).on_input(Message::ExpectedWord)
                .padding([11, 15]).style(style::composer_input),
            space().height(10),
            button(text("Run small generation test  ↗").size(12))
                .on_press_maybe((state.selected_model().is_some() && !state.test_busy).then_some(Message::RunTest))
                .padding([11, 15]).style(style::control_button),
            space().height(8),
            text(state.test_evidence.clone().unwrap_or_default()).size(11).color(style::GREY),
            space().height(10),
            text("Catalog labels reflect provider metadata at fetch time, not a price guarantee. Generation is a separate explicit action.")
                .size(11.5).color(style::DIM)
        ].width(Fill))
    ].spacing(16).width(Fill).into()
}


// Paginate the native widgets for responsiveness, not as a limit on imports.
// The catalog itself and selection set are unbounded by a fixed app quota.
fn available_catalog<'a>(state: &'a SettingsState, query: &str) -> Vec<(usize, &'a CatalogModel)> {
    let index = state.index();
    let added: HashSet<&str> = state.models[index].iter().map(String::as_str).collect();
    state.catalog[index].iter().enumerate()
        .filter(|(_, model)| !added.contains(model.id.as_str()))
        .filter(|(_, model)| query.is_empty() || model.id.to_lowercase().contains(query) || model.name.to_lowercase().contains(query))
        .collect()
}

fn catalog_dialog(state: &SettingsState) -> Element<'static, Message> {
    let index = state.index();
    let query = state.search.trim().to_lowercase();
    let matching = available_catalog(state, &query);
    let checked = state.catalog_selected[index].len();
    let importable = state.importable_catalog_ids().len();
    let only_verified = state.catalog_only_verified;
    let list_height = (matching.len().min(8) as f32 * 44.0 + 34.0).clamp(130.0, 280.0);
    let start = state.catalog_page.saturating_mul(60).min(matching.len());
    let mut items = column![].spacing(3).width(Fill);
    for (slot, model) in matching.iter().copied().skip(start).take(60) {
        let selected = state.catalog_selected[index].contains(&model.id);
        let manual = state.catalog_manual[index].contains(&model.id);
        let probe = state.probe_results.iter().find(|(id, _, _)| id == &model.id).map(|(_, ok, output)| (*ok, output.as_str()));
        let probe_ok = probe.map(|(ok, _)| ok);
        let dot: Element<'static, Message> = container(space().width(7).height(7))
            .style(move |t| style::probe_dot(probe_ok, t)).into();
        let id_text = text(model.id.clone()).size(12.5).font(style::LABEL)
            .color(style::WHITE);
        let tags: Element<'static, Message> = if manual {
            tag("manual", None).into()
        } else if model.free {
            tag("free", Some(true)).into()
        } else {
            space().height(0).into()
        };
        let status: Element<'static, Message> = match probe {
            Some((ok, output)) => tag(probe_summary(ok, output), Some(ok)).into(),
            None => space().height(0).into(),
        };
        let mut entry = column![button(row![
            dot, id_text, tags, space().width(Fill), status, checkbox_box(selected)
        ].spacing(8).align_y(Center))
            .width(Fill).padding([8, 10]).on_press_maybe((!state.probe_busy).then_some(Message::ToggleCatalogSelection(state.provider, slot)))
            .style(move |t, s| style::list_row(false, t, s))].spacing(2);
        if let Some((_ok, output)) = probe {
            // Fuller bounded probe evidence than the web's collapsed detail;
            // it stays quiet like `.import-detail summary` — the status pill
            // above carries the only strong color.
            entry = entry.push(container(row![
                text(output.to_owned()).size(10.5).color(style::GREY)
            ].padding(iced::Padding { top: 0.0, right: 0.0, bottom: 0.0, left: 27.0 })).width(Fill));
        }
        items = items.push(entry);
    }
    if matching.is_empty() && state.provider != Provider::Custom {
        items = items.push(text(if state.catalog_busy { "Fetching…" } else { "No matching new models. Fetch, change the filter, or add an exact ID." }).size(12).color(style::GREY));
    }
    let pending: Element<'static, Message> = if state.probe_pending {
        row![
            text(format!("Probe {checked} selected models? Each may send up to two billable requests (retry only HTTP 408/429/5xx), 256 output tokens per attempt. Never auto-tests.")).size(11).color(style::WHITE).width(Fill),
            button(text("Cancel").size(11)).on_press(Message::CancelCatalogProbe).style(style::control_button),
            button(text("Confirm tests").size(11)).on_press(Message::ConfirmCatalogProbe).style(style::control_button)
        ].spacing(8).align_y(Center).into()
    } else { space().height(0).into() };
    let progress: Element<'static, Message> = if state.probe_busy {
        text(format!("Testing · {} of {checked} returned · Stop cancels remaining requests", state.probe_results.len()))
            .size(12).color(style::GREY).into()
    } else { space().height(0).into() };
    let dialog = column![
        row![
            column![
                text(format!("Add models from {}", state.provider.name())).size(19).font(style::STRONG).color(style::WHITE),
                text("Choose exactly which models should be added to your Agent list. Unchecked models are not added.").size(11.5).color(style::GREY)
            ].spacing(4).width(Fill),
            button(text("×").size(17)).on_press(Message::CloseCatalogModal).style(style::ghost_button)
        ].align_y(Center),
        row![
            text_input("Filter by text contained in model id…", &state.search).on_input(Message::SearchModels)
                .padding([9, 11]).style(style::composer_input),
            button(text(if state.catalog_busy { "Fetching…" } else { "Fetch models" }).size(12))
                .on_press_maybe((state.provider != Provider::Custom && !state.catalog_busy && !state.probe_busy).then_some(Message::FetchModels))
                .style(style::control_button)
        ].spacing(8),
        row![
            text(format!("{} new models found · {} checked · {} eligible", matching.len(), checked, importable)).size(11).color(style::DIM).width(Fill),
            button(text(if state.search.trim().is_empty() { "Select all" } else { "Select matching" }).size(11))
                .on_press_maybe((!state.probe_busy).then_some(Message::SelectMatchingModels)).style(style::tiny_button),
            button(text("Clear all").size(11)).on_press_maybe((!state.probe_busy).then_some(Message::ClearCatalogSelection)).style(style::tiny_button)
        ].align_y(Center).spacing(8),
        row![
            {
                let knob = container(space().width(14).height(14))
                    .style(move |t| style::switch_knob(only_verified, t));
                let track: Element<'static, Message> = if only_verified {
                    row![space().width(Fill), knob].align_y(Center).into()
                } else {
                    row![knob, space().width(Fill)].align_y(Center).into()
                };
                button(container(track).width(36).height(20).padding(2))
                    .on_press_maybe((!state.probe_busy).then_some(Message::ToggleCatalogVerified))
                    .padding(0).width(36).height(20)
                    .style(move |t, s| style::switch_track(only_verified, t, s))
            },
            column![
                text("Add only verified models").size(12.5).font(style::STRONG).color(style::WHITE),
                text("testing never auto-starts; only verified skips untested and failed IDs").size(11).color(style::GREY)
            ].spacing(2)
        ].spacing(10).align_y(Center),
        scrollable(container(items).width(Fill).padding(8).style(style::card)).height(list_height)
            .style(style::quiet_scroll),
        row![
            button(text("Previous").size(11)).on_press_maybe((start > 0).then_some(Message::CatalogPrevious)).style(style::tiny_button),
            text(format!("{}–{} of {} new matches", start.min(matching.len()) + usize::from(!matching.is_empty()), (start + 60).min(matching.len()), matching.len()))
                .size(11).color(style::DIM).width(Fill),
            button(text("Next").size(11)).on_press_maybe((start + 60 < matching.len()).then_some(Message::CatalogNext)).style(style::tiny_button)
        ].align_y(Center).spacing(8),
        column![
            text("Model not listed? Enter an exact ID").size(13).color(style::WHITE),
            row![
                text_input("e.g. my-finetune-v2", &state.model_entry)
                    .on_input(Message::EditModel).padding([9, 11]).style(style::composer_input),
                button(text("Stage ID").size(12))
                    .on_press_maybe((!state.probe_busy).then_some(Message::StageCatalogId)).style(style::control_button)
            ].spacing(8)
        ].spacing(6),
        row![
            button(text(if state.probe_busy { "Testing…" } else { "Test selected…  (may be billable)" }).size(12))
                .on_press_maybe((checked > 0 && !state.probe_busy).then_some(Message::RequestCatalogProbe)).style(style::control_button),
            button(text("Stop tests").size(12)).on_press_maybe(state.probe_busy.then_some(Message::CancelCatalogProbe)).style(style::control_button),
            space().width(Fill),
            button(text("Cancel").size(12)).on_press(Message::CloseCatalogModal).style(style::ghost_button),
            button(text(if state.catalog_only_verified { "Add verified checked" } else { "Add checked models" }).size(12).font(style::STRONG).color(style::BLACK))
                .on_press_maybe((importable > 0 && !state.probe_busy).then_some(Message::ImportSelectedModels))
                .padding([10, 14]).style(style::primary_button)
        ].align_y(Center).spacing(8),
        pending, progress,
        text(state.status.clone()).size(11).color(style::GREY),
        text("Manual IDs stay staged. Only verified skips untested/failed; testing always asks first.")
            .size(11).color(style::DIM)
    ].spacing(style::AGENT_GAP_CONTROL).width(Fill);
    container(dialog).max_width(680).width(Fill).padding(20).style(style::modal_card).into()
}

#[cfg(test)]
mod catalog_tests {
    use super::*;

    #[test]
    fn available_popup_excludes_every_imported_id_without_truncating_catalog() {
        let mut state = SettingsState::default();
        state.catalog[0] = (0..120).map(|n| CatalogModel {
            id: format!("vendor/model-{n}"), name: format!("Model {n}"),
            free: false, router: false, reasoning: false,
        }).collect();
        state.models[0] = (0..75).map(|n| format!("vendor/model-{n}")).collect();
        let available = available_catalog(&state, "");
        assert_eq!(available.len(), 45);
        assert!(available.iter().all(|(_, item)| !state.models[0].contains(&item.id)));
        assert_eq!(available_catalog(&state, "model-119").len(), 1);
    }

    #[test]
    fn probe_summary_shows_compact_reference_badges() {
        assert_eq!(probe_summary(true, "42 ms · expected word found · OK"), "✓ works · 42 ms");
        assert_eq!(probe_summary(true, "OK"), "✓ works · OK");
        assert_eq!(probe_summary(false, "HTTP 429 · account quota exceeded"), "✗ HTTP 429 · account quota exceeded");
        let long = "HTTP 500 · upstream returned a very long diagnostic body that should be cut";
        assert!(probe_summary(false, long).ends_with('…'));
    }
}

fn lab(memory: MemoryMode, keep_agent: bool) -> Element<'static, Message> {
    let custom = if memory == MemoryMode::Custom {
        button(text(if keep_agent { "Archx Agent / Keep ready" } else { "Archx Agent / Load on open" }).size(13))
            .on_press(Message::ToggleAgentPreview).style(style::control_button)
    } else {
        button(text("Select Custom to preview destination controls").size(13)).style(style::control_button)
    };
    surface(column![
        eyebrow("MEMORY  /  PREVIEW ONLY"),
        space().height(16),
        text("These controls do not save preferences, load models or change RAM use.").size(13).color(style::GREY),
        space().height(20),
        row![
            button(text("Light").size(13)).on_press(Message::MemoryPreview(MemoryMode::Light)).style(move |t, s| style::side_nav(memory == MemoryMode::Light,t,s)),
            button(text("Heavy").size(13)).on_press(Message::MemoryPreview(MemoryMode::Heavy)).style(move |t, s| style::side_nav(memory == MemoryMode::Heavy,t,s)),
            button(text("Custom").size(13)).on_press(Message::MemoryPreview(MemoryMode::Custom)).style(move |t, s| style::side_nav(memory == MemoryMode::Custom,t,s)),
        ].spacing(10),
        space().height(20), custom
    ].width(Fill))
}

fn custom_controls(state: &SettingsState) -> Element<'static, Message> {
    let p = &state.custom;
    let stream_control: Element<'static, Message> = if p.stream {
        column![text("SSE answer delta / JSON pointer").size(11).color(style::GREY),
            text_input::<Message, iced::Theme, iced::Renderer>("/choices/0/delta/content", &p.stream_pointer)
                .on_input(Message::CustomDelta).size(13).padding([9, 12]).style(style::composer_input)]
            .spacing(5).into()
    } else { space().height(0).into() };
    column![
        text("Custom text endpoint").size(17).font(style::STRONG).color(style::WHITE),
        text("Session only · HTTPS or loopback HTTP · approval required before sending a prompt or vault key")
            .size(12).color(style::GREY),
        row![button(text("OpenAI-compatible preset").size(11)).on_press(Message::CustomOpenAiPreset).style(style::tiny_button),
            button(text("Anthropic-compatible preset").size(11)).on_press(Message::CustomAnthropicPreset).style(style::tiny_button)].spacing(8),
        column![text("Destination URL").size(11).color(style::GREY),
            text_input("https://example.com/chat", &p.url).on_input(Message::CustomUrl)
                .size(13).padding([9, 12]).style(style::composer_input)].spacing(5),
        column![text("Request headers  ·  separate entries with |  ·  {{api_key}} inserts the optional OS-vault key")
            .size(11).color(style::GREY),
            text_input("Authorization: Bearer {{api_key}}", p.headers.as_str())
                .on_input(|s| Message::CustomHeaders(SecretText::new(s)))
                .size(13).padding([9, 12]).style(style::composer_input)].spacing(5),
        column![text("JSON request body  ·  use {{prompt}} or {{messages}}; {{model}}, {{max_tokens}}, {{stream}} are optional")
            .size(11).color(style::GREY),
            text_input("{\"prompt\":\"{{prompt}}\"}", &p.body).on_input(Message::CustomBody)
                .size(13).padding([9, 12]).style(style::composer_input)].spacing(5),
        column![text("Answer text / JSON pointer").size(11).color(style::GREY),
            text_input("/choices/0/message/content", &p.answer_pointer).on_input(Message::CustomAnswer)
                .size(13).padding([9, 12]).style(style::composer_input)].spacing(5),
        button(text(if p.stream { "Streaming: SSE data JSON" } else { "Streaming: off (JSON response)" }).size(12))
            .on_press(Message::CustomStream).style(style::control_button),
        stream_control,
        text("Or paste a literal cURL POST request · parsed as text, never executed").size(12).color(style::GREY),
        text_input("curl -X POST https://... -H 'Authorization: Bearer {{api_key}}' -d '{...}'", state.custom_curl.0.as_str())
            .secure(true).on_input(|s| Message::CustomCurl(SecretText::new(s)))
            .size(13).padding([9, 12]).style(style::composer_input),
        button(text("Parse cURL into fields").size(12)).on_press(Message::ImportCustomCurl).style(style::control_button),
        text(format!("Destination for approval: {}", if p.url.is_empty() { "not entered" } else { &p.url })).size(12).color(style::WHITE),
        button(text(if state.custom_approved { "Approved for this session · revoke" } else { "Approve sending prompts and key to this destination" }).size(12))
            .on_press(Message::ApproveCustom).style(style::control_button),
        text("Edits revoke approval. No redirects, ambient proxies, files or shell execution. Review any literal header secrets before sharing your screen.")
            .size(11).color(style::DIM)
    ].spacing(10).width(Fill).into()
}
