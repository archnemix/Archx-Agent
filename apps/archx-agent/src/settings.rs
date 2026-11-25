//! Purpose: Renders separate Lab, provider-vault and session model settings surfaces.
use std::collections::HashSet;
use std::fmt;
use std::time::Instant;

use iced::widget::{button, column, container, row, scrollable, space, stack, text, text_input};
use iced::{Center, Element, Fill};
use zeroize::Zeroizing;

use crate::app::{MemoryMode, Message};
use archx_shared::credentials::Provider;
use crate::custom_endpoint::Profile;
use archx_shared::health::{KeyHealthSet, ModelHealthSet};
use archx_shared::model_catalog::CatalogModel;
use archx_shared::style;

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
pub enum Section { Providers, Models, Runtime, Storage, Lab }

impl Section {
    pub const ALL: [Self; 5] = [Self::Providers, Self::Models, Self::Runtime, Self::Storage, Self::Lab];

    pub fn label(self) -> &'static str {
        match self {
            Self::Providers => "Providers",
            Self::Models => "Models",
            Self::Runtime => "Runtime memory",
            Self::Storage => "Storage & display",
            Self::Lab => "Lab preview",
        }
    }
}

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
    /// Model rows currently ticked for a bulk action (test/remove/disable).
    pub bulk_selected: HashSet<String>,
    /// Scrollable model list page; the list never renders every model at once.
    pub model_page: usize,
    /// Rows per page in the Models list.
    pub model_page_size: usize,
    /// Provider picker (custom listbox) open state.
    pub provider_picker: bool,
    /// Endpoint row being edited, mirrored from the app for rendering.
    pub endpoint_draft: Option<(archx_shared::endpoints::Kind, String)>,
    /// Key rest windows and the rotation toggle, mirrored for rendering only.
    pub key_health: KeyHealthSet,
    pub key_auto_rotate: bool,
    /// Measured cache sizes for the Runtime page.
    pub usage: Vec<archx_shared::memory::Usage>,
    /// Keep/drop matrix for the Runtime page.
    pub budget: archx_shared::memory::Budget,
    /// Model health (enabled/disabled per id).
    pub model_health: ModelHealthSet,
    /// Public metadata for the rows (models.dev + free-tier registry).
    pub meta: Option<archx_shared::model_meta::Registry>,
}
impl Default for SettingsState {
    fn default() -> Self {
        Self { section: Section::Providers, provider: Provider::OpenRouter,
            key_entry: SecretText::default(), key_ids: Vec::new(), reveal: None,
            reveal_nonce: 0, model_entry: String::new(), catalog: std::array::from_fn(|_| Vec::new()),
            catalog_manual: std::array::from_fn(|_| Vec::new()),
            search: String::new(), catalog_modal: false, catalog_only_verified: false, catalog_page: 0, catalog_selected: std::array::from_fn(|_| Vec::new()),
            probe_pending: false, probe_busy: false, probe_nonce: 0, probe_results: Vec::new(), catalog_busy: false, catalog_nonce: 0, models: std::array::from_fn(|_| Vec::new()),
            chosen: [None; Provider::COUNT], status: String::new(), test_busy: false, test_evidence: None, stream_chat: true, key_busy: false, custom: Profile::default(), custom_curl: SecretText::default(), custom_approved: false, expected_word: "OK".into(),
            bulk_selected: HashSet::new(), model_page: 0, model_page_size: 25, provider_picker: false,
            endpoint_draft: None }
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

pub fn view<'a>(state: &'a SettingsState, memory: MemoryMode, keep_agent: bool,
    display: &archx_shared::persist::DisplaySettings, storage_path: &str, usage: &'a [archx_shared::memory::Usage],
    budget: &'a archx_shared::memory::Budget) -> Element<'a, Message> {
    let (heading, description) = match state.section {
        Section::Providers => ("Providers", "Select a provider from the list, see and edit the exact URLs it calls, and manage its vault keys."),
        Section::Models => ("Models", "The list scrolls and pages. Tick several models to test, enable, disable or remove them together."),
        Section::Runtime => ("Runtime memory", "Choose what the Agent keeps in RAM at each stage. Sizes are measured, never estimated."),
        Section::Storage => ("Storage & display", "Where your data lives, how big the text is in each area, and how to wipe it."),
        Section::Lab => ("Agent & Lab", "How much the Agent keeps resident, who owns it, and where the other apps' settings will live."),
    };
    let status_notice: Element<'static, Message> = if state.status.is_empty() { space().height(0).into() }
    else { column![
        container(text(state.status.clone()).size(12).color(style::WHITE))
            .padding([9, 12]).width(Fill).style(style::chat_panel),
        space().height(12)
    ].into() };
    let page_head = container(column![
        text("Settings").size(24).font(style::STRONG).color(style::WHITE),
        text("Each side of the Lab keeps its own settings: these belong to the Archx Agent.")
            .size(12.5).color(style::GREY)
    ].spacing(5)).width(Fill).padding([18, 28]).style(style::settings_header);
    let category = container(scrollable(column(
        Section::ALL.into_iter().map(|section| setting_link(section.label(), section, state.section))
    ).spacing(4).padding([16, 12])).height(Fill).style(style::quiet_scroll)).width(200).height(Fill).style(style::rail);
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
            Section::Runtime => runtime(state),
            Section::Storage => storage(state, &display),
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

/// Provider chooser: one closed dropdown instead of ten always-visible rows.
/// Clicking the header opens a scrollable list of every provider.
fn provider_picker(state: &SettingsState, busy: bool) -> Element<'static, Message> {
    let current = state.provider;
    let header = button(row![
        text(current.name()).size(13).font(style::LABEL).color(style::WHITE).width(Fill),
        text(if state.provider_picker { "\u{25B4}" } else { "\u{25BE}" }).size(11).color(style::GREY)
    ].align_y(Center))
        .width(Fill).padding([10, 12])
        .on_press_maybe((!busy).then_some(if state.provider_picker { Message::CloseProviderPicker } else { Message::OpenProviderPicker }))
        .style(style::topbar_pill);
    if !state.provider_picker {
        return container(header).width(Fill).style(style::card).into();
    }
    let mut list = column![].spacing(2);
    for provider in Provider::ALL {
        let selected = current == provider;
        list = list.push(button(row![
            text(provider.name()).size(13).color(if selected { style::WHITE } else { style::GREY }),
            space().width(Fill),
            text(if provider.needs_key() { "key" } else { "no key" }).size(10).color(style::DIM)
        ].align_y(Center))
            .width(Fill).padding([8, 10])
            .on_press(Message::SelectProvider(provider))
            .style(move |theme, status| style::provider_choice(selected, theme, status)));
    }
    column![
        header,
        container(scrollable(list).height(196).style(style::quiet_scroll))
            .padding(6).width(Fill).style(style::card)
    ].spacing(4).width(Fill).into()
}

/// The exact URLs this provider calls, shown in full, editable, resettable.
fn endpoint_rows(state: &SettingsState) -> Element<'static, Message> {
    let provider = state.provider;
    if provider == Provider::Custom {
        return text("Custom destinations are edited in the form above; they are never defaulted.")
            .size(12).color(style::GREY).into();
    }
    let defaults = archx_shared::endpoints::default_template(provider);
    let mut rows = column![].spacing(8);
    for (kind, default) in [
        (archx_shared::endpoints::Kind::Chat, defaults.chat),
        (archx_shared::endpoints::Kind::Stream, defaults.stream),
        (archx_shared::endpoints::Kind::Models, defaults.models),
    ] {
        let shown = state.endpoint_draft.as_ref()
            .filter(|(draft_kind, _)| *draft_kind == kind)
            .map(|(_, value)| value.clone())
            .unwrap_or_else(|| match kind {
                archx_shared::endpoints::Kind::Chat => defaults.chat.to_owned(),
                archx_shared::endpoints::Kind::Stream => defaults.stream.to_owned(),
                archx_shared::endpoints::Kind::Models => defaults.models.to_owned(),
            });
        let edited = state.endpoint_draft.as_ref().is_some_and(|(draft_kind, value)| *draft_kind == kind && value != default);
        rows = rows.push(column![
            row![
                text(kind.label()).size(11).font(style::LABEL).color(style::DIM).width(Fill),
                if edited { text("edited · unsaved").size(10).color(style::WARN) } else { text("documented").size(10).color(style::DIM) }
            ].align_y(Center),
            row![
                text_input("https://…", &shown)
                    .on_input(move |value| Message::EditEndpoint(kind, value))
                    .padding([9, 11]).size(12).style(style::composer_input),
                button(text("Save").size(11)).on_press(Message::SaveEndpoint(kind)).style(style::tiny_button),
                button(text("Default").size(11)).on_press(Message::ResetEndpoint(kind)).style(style::tiny_button)
            ].spacing(6)
        ].spacing(4));
    }
    column![
        eyebrow("ENDPOINTS  /  SHOWN AND EDITABLE"),
        space().height(10),
        text("A provider that moves a path, or a compatible gateway, needs no new build: edit the URL here. Only https:// (or http:// on loopback) is accepted.")
            .size(11.5).color(style::GREY),
        space().height(8),
        rows
    ].width(Fill).into()
}

fn providers(state: &SettingsState) -> Element<'static, Message> {
    let mut keys = column![eyebrow("SAVED KEY SLOTS  /  ONE IS USED PER REQUEST")].spacing(8);
    if state.key_ids.is_empty() {
        keys = keys.push(text(if state.provider.needs_key() {
            if state.provider == Provider::Custom { "No saved key. Custom endpoints can work without one." }
            else { "No saved keys yet. Keys stay in the OS vault; the Agent never writes them to a file." }
        } else { "No key needed: this provider runs on this machine." }).size(12.5).color(style::GREY));
    }
    for slot in &state.key_health.slots {
        let id = slot.id;
        let showing = state.reveal.as_ref().is_some_and(|(visible, _, until)| *visible == id && Instant::now() < *until);
        let label = if showing {
            state.reveal.as_ref().map(|(_, secret, _)| secret.0.to_string()).unwrap_or_default()
        } else { format!("Key {id}    ••••••••") };
        let resting = slot.cooldown_until > archx_shared::storage::now_secs();
        let status: Element<'static, Message> = if resting {
            tag(format!("resting · {} s", slot.cooldown_until.saturating_sub(archx_shared::storage::now_secs())), Some(false)).into()
        } else if slot.failures > 0 {
            tag(format!("{} recent failure(s)", slot.failures), None).into()
        } else { tag("ready", Some(true)).into() };
        let mut row = row![
            text(label).size(12.5).color(style::WHITE).width(Fill),
            status
        ].spacing(8).align_y(Center);
        if resting {
            row = row.push(button(text("Retry now").size(10.5)).on_press(Message::RetryKeyNow(id)).style(style::tiny_button));
        }
        row = row.push(button(text(if showing { "Hide" } else { "Reveal 15s" }).size(10.5))
            .on_press(if showing { Message::HideKey } else { Message::RevealKey(id) }).style(style::tiny_button));
        row = row.push(button(text("Remove").size(10.5))
            .on_press_maybe((!state.key_busy).then_some(Message::RemoveKey(id))).style(style::tiny_button));
        keys = keys.push(column![row,
            if resting && !slot.reason.is_empty() {
                text(slot.reason.clone()).size(10.5).color(style::GREY).into()
            } else { space().height(0).into() }
        ].spacing(2));
    }
    let rotation: Element<'static, Message> = row![
        {
            let on = state.key_auto_rotate;
            let knob = container(space().width(14).height(14))
                .style(move |theme| style::switch_knob(on, theme));
            let track: Element<'static, Message> = if on { row![space().width(Fill), knob].align_y(Center).into() }
                else { row![knob, space().width(Fill)].align_y(Center).into() };
            button(container(track).width(36).height(20).padding(2))
                .on_press(Message::ToggleAutoRotate).padding(0).width(36).height(20)
                .style(move |theme, status| style::switch_track(on, theme, status))
        },
        column![
            text("Rotate across keys and rest failing ones").size(12.5).font(style::STRONG).color(style::WHITE),
            text("One key per request. A key the provider blames rests 5 minutes (or the provider's Retry-After) and one other key is tried once.")
                .size(11).color(style::GREY)
        ].spacing(2)

    ].spacing(10).align_y(Center);
    let credential_control: Element<'static, Message> = if state.provider.needs_key() {
        column![text_input::<Message, iced::Theme, iced::Renderer>("Paste an API key", state.key_entry.0.as_str()).secure(true)
            .on_input(|value| Message::EditKey(SecretText::new(value)))
            .padding([12, 14]).style(style::composer_input),
            button(text("Save key to OS vault").size(12))
                .on_press_maybe((!state.key_busy && !state.key_entry.0.is_empty()).then_some(Message::SaveKey))
                .padding([10, 14]).style(style::control_button)].spacing(8).into()
    } else {
        button(text("Browse local models").size(12)).on_press(Message::OpenCatalogModal)
            .style(style::control_button).into()
    };
    column![
        surface(column![
            eyebrow("PROVIDER  /  CONNECTION"),
            space().height(10),
            provider_picker(state, state.key_busy || state.probe_busy),
            space().height(14),
            if state.provider == Provider::Custom { custom_controls(state) } else { space().height(0).into() },
            space().height(14),
            credential_control,
            space().height(10),
            text(if state.provider.needs_key() {
                format!("Requests use the Agent's own {} s limit per request. Keys are never written to disk, logs or the Debug page.", archx_shared::diagnostics::REQUEST_TIMEOUT_SECS)
            } else {
                "Loopback only: 127.0.0.1, no key, no remote URL.".to_owned() }).size(11.5).color(style::GREY)
        ].width(Fill)),
        surface(endpoint_rows(state)),
        surface(column![eyebrow("KEY HEALTH"), space().height(10), rotation, space().height(12), keys,
            space().height(10),
            text("A refused key cannot be proven healthy again by the Agent; it returns after its window, or press Retry now once you have fixed the account.")
                .size(10.5).color(style::DIM)].width(Fill))
    ].spacing(14).width(Fill).into()
}

fn models(state: &SettingsState) -> Element<'static, Message> {
    let index = state.index();
    let query = state.search.trim().to_lowercase();
    let visible: Vec<(usize, &String)> = state.models[index].iter().enumerate()
        .filter(|(_, model)| query.is_empty() || model.to_lowercase().contains(&query))
        .collect();
    let page_size = state.model_page_size.max(1);
    let total_pages = visible.len().div_ceil(page_size).max(1);
    let page = state.model_page.min(total_pages - 1);
    let start = (page * page_size).min(visible.len());
    let shown = &visible[start..(start + page_size).min(visible.len())];
    let selected = state.bulk_selected.len();
    let disabled = state.model_health.disabled_ids().len();
    let mut list = column![].spacing(6);
    if visible.is_empty() {
        list = list.push(text(if state.models[index].is_empty() {
            "No models yet. Use Add models to import IDs, or add one exact ID by hand."
        } else { "No model matches the filter." }).size(12.5).color(style::GREY));
    }
    for (slot, model) in shown.iter().copied() {
        let active = state.chosen[index] == Some(slot);
        let ticked = state.bulk_selected.contains(model);
        let enabled = state.model_health.is_enabled(model);
        let meta = state.meta.as_ref().map(|registry| registry.lookup(state.provider, model));
        let detail: Element<'static, Message> = match &meta {
            Some(meta) if !meta.line().is_empty() => text(meta.line()).size(10.5).color(style::GREY).into(),
            _ => space().height(0).into(),
        };
        let failure: Element<'static, Message> = state.model_health.slot(model)
            .filter(|slot| slot.disabled && !slot.reason.is_empty())
            .map(|slot| text(format!("disabled · {}", slot.reason)).size(10.5).color(style::WARN).into())
            .unwrap_or_else(|| space().height(0).into());
        list = list.push(container(column![
            row![
                button(checkbox_box(ticked))
                    .padding(0).on_press(Message::BulkSelect(slot, !ticked)).style(style::ghost_button),
                button(text(model.clone()).size(12.5).font(style::LABEL)
                    .color(if !enabled { style::DIM } else if active { style::WHITE } else { style::GREY }))
                    .width(Fill).padding([2, 4]).on_press(Message::ChooseModel(slot))
                    .style(move |theme, status| style::list_row(active, theme, status)),
                if active { tag("active", Some(true)) } else { space().height(0).into() },
                button(text(if enabled { "Disable" } else { "Enable" }).size(10.5))
                    .on_press(Message::ToggleModelEnabled(model.clone())).style(style::tiny_button),
                button(text("Remove").size(10.5)).on_press(Message::RemoveModel(slot)).style(style::tiny_button)
            ].spacing(6).align_y(Center),
            detail,
            failure
        ].spacing(3)).padding([6, 8]).width(Fill).style(style::card));
    }
    let bulk: Element<'static, Message> = row![
        text(format!("{selected} ticked")).size(11).color(if selected > 0 { style::WHITE } else { style::DIM }).width(Fill),
        button(text("Tick matching").size(10.5)).on_press(Message::BulkSelectMatching).style(style::tiny_button),
        button(text("Clear").size(10.5)).on_press(Message::BulkClearSelection).style(style::tiny_button),
        button(text("Test selected").size(10.5)).on_press_maybe((selected > 0).then_some(Message::BulkRunSelected))
            .style(style::control_button),
        button(text("Enable").size(10.5)).on_press_maybe((selected > 0).then_some(Message::BulkEnableSelected))
            .style(style::tiny_button),
        button(text("Disable").size(10.5)).on_press_maybe((selected > 0).then_some(Message::BulkDisableSelected))
            .style(style::tiny_button),
        button(text("Remove").size(10.5)).on_press_maybe((selected > 0).then_some(Message::BulkRemoveSelected))
            .style(style::tiny_button)
    ].spacing(6).align_y(Center);
    let pager: Element<'static, Message> = row![
        button(text("Previous").size(10.5)).on_press_maybe((page > 0).then_some(Message::ModelPagePrevious)).style(style::tiny_button),
        text(format!("Page {} of {} · {} model(s) shown of {}", page + 1, total_pages, shown.len(), visible.len()))
            .size(10.5).color(style::DIM).width(Fill),
        button(text("Next").size(10.5)).on_press_maybe((page + 1 < total_pages).then_some(Message::ModelPageNext)).style(style::tiny_button)
    ].spacing(6).align_y(Center);
    let auto_disable = state.model_health.auto_disable;
    column![
        surface(column![
            eyebrow("MODEL CATALOG  /  EXPLICIT IMPORT"),
            space().height(10),
            provider_picker(state, state.key_busy || state.probe_busy),
            space().height(12),
            row![
                text_input("Filter this provider's models…", &state.search).on_input(Message::SearchModels)
                    .padding([9, 11]).size(12).style(style::composer_input),
                button(text("Add models…").size(12)).on_press(Message::OpenCatalogModal).padding([9, 13]).style(style::control_button)
            ].spacing(8),
            space().height(8),
            row![
                button(text("Refresh metadata").size(10.5)).on_press(Message::FetchModelMeta).style(style::tiny_button),
                text(if state.meta.is_some() {
                    "models.dev + curated free-tier notes cached locally"
                } else { "No metadata yet: press Refresh metadata" }).size(10.5).color(style::DIM).width(Fill),
                text(if disabled > 0 { format!("{disabled} disabled") } else { String::new() }).size(10.5).color(style::WARN)
            ].spacing(8).align_y(Center)
        ].width(Fill)),
        surface(column![
            eyebrow("ADDED MODELS  /  SCROLLABLE, PAGED, BULK"),
            space().height(10),
            bulk,
            space().height(8),
            scrollable(list).height(340).style(style::quiet_scroll),
            space().height(6),
            pager
        ].width(Fill)),
        surface(column![
            eyebrow("AUTOMATIC HEALTH"),
            space().height(10),
            row![
                {
                    let knob = container(space().width(14).height(14))
                        .style(move |theme| style::switch_knob(auto_disable, theme));
                    let track: Element<'static, Message> = if auto_disable { row![space().width(Fill), knob].align_y(Center).into() }
                        else { row![knob, space().width(Fill)].align_y(Center).into() };
                    button(container(track).width(36).height(20).padding(2))
                        .on_press(Message::ToggleAutoDisable).padding(0).width(36).height(20)
                        .style(move |theme, status| style::switch_track(auto_disable, theme, status))
                },
                column![
                    text("Disable a model when the provider says it is gone").size(12.5).font(style::STRONG).color(style::WHITE),
                    text("Retired or inaccessible IDs are disabled, never deleted. Three consecutive provider failures also disable a model. A bad key never does.")
                        .size(11).color(style::GREY)
                ].spacing(2)
            ].spacing(10).align_y(Center),
            space().height(10),
            row![
                button(text("Re-enable all").size(10.5)).on_press(Message::EnableAllModels).style(style::tiny_button),
                text("Disabled models stay listed so you can re-check them later.").size(10.5).color(style::DIM).width(Fill)
            ].spacing(8).align_y(Center),
            space().height(10),
            text_input("Expected test word (default OK)", &state.expected_word).on_input(Message::ExpectedWord)
                .padding([9, 11]).size(12).style(style::composer_input),
            space().height(8),
            button(text("Run small generation test").size(11))
                .on_press_maybe((state.selected_model().is_some() && !state.test_busy).then_some(Message::RunTest))
                .padding([9, 12]).style(style::control_button),
            space().height(6),
            text(state.test_evidence.clone().unwrap_or_default()).size(10.5).color(style::GREY),
            space().height(6),
            text("Tests are explicit and may be billable. Results are saved until you re-run or wipe them.").size(10.5).color(style::DIM)
        ].width(Fill))
    ].spacing(14).width(Fill).into()
}

/// Runtime memory: one row per cache per stage, with measured sizes.
fn runtime(state: &SettingsState) -> Element<'static, Message> {
    let mut matrix = column![].spacing(6);
    for item in archx_shared::memory::Item::ALL {
        let usage = state.usage.iter().find(|usage| usage.item == item);
        let mut row = row![
            column![
                text(item.label()).size(12.5).font(style::STRONG).color(style::WHITE),
                text(item.detail()).size(10.5).color(style::GREY)
            ].spacing(2).width(Fill),
            text(usage.map(archx_shared::memory::Usage::label).unwrap_or_else(|| "not loaded".into()))
                .size(11).color(style::GREY).width(140)
        ].spacing(8).align_y(Center);
        for stage in archx_shared::memory::Stage::ALL {
            let keep = state.budget.keeps(stage, item);
            row = row.push(button(text(if keep { "keep" } else { "drop" }).size(10)
                .color(if keep { style::WHITE } else { style::DIM }))
                .padding([5, 8]).on_press(Message::ToggleRuntime(stage, item))
                .style(move |theme, status| style::list_row(keep, theme, status)));
        }
        matrix = matrix.push(container(row).padding([6, 8]).width(Fill).style(style::card));
    }
    let resident = archx_shared::memory::resident_total(&state.usage);
    column![
        surface(column![
            eyebrow("RESIDENT CACHES  /  MEASURED"),
            space().height(10),
            text(format!("Loaded now: {}. Nothing here is estimated; each figure counts the bytes this process holds.",
                archx_shared::memory::bytes_label(resident))).size(11.5).color(style::GREY),
            space().height(10),
            matrix,
            space().height(8),
            text("Columns are stages: Launcher · Agent idle · Streaming · Settings · (drop = released on entry).")
                .size(10.5).color(style::DIM)
        ].width(Fill)),
        surface(column![
            eyebrow("WHAT THIS CANNOT DO"),
            space().height(8),
            text("The Agent can release its own caches and stop holding a fetched catalog or parsed chat. It cannot cap another process's or the operating system's memory, and it does not claim to. A 'drop' makes the next use re-fetch or re-parse.")
                .size(11.5).color(style::GREY)
        ].width(Fill))
    ].spacing(14).width(Fill).into()
}

/// Storage & display: where data lives, per-area text scale, and wiping.
fn storage(state: &SettingsState, display: &archx_shared::persist::DisplaySettings) -> Element<'static, Message> {
    let path = archx_shared::storage::display_path();
    let mut wipes = column![].spacing(6);
    for area in archx_shared::storage::Area::ALL {
        wipes = wipes.push(row![
            text(area.label()).size(12).color(style::WHITE).width(Fill),
            text(if area.exists() { "file present" } else { "not written yet" }).size(10.5).color(style::DIM),
            button(text("Wipe").size(10.5)).on_press(Message::WipeArea(area)).style(style::tiny_button)
        ].spacing(8).align_y(Center));
    }
    let scale_row = |label: &'static str, area: crate::app::Area, scale: archx_shared::persist::TextScale| -> Element<'static, Message> {
        row![
            text(label).size(12).color(style::WHITE).width(Fill),
            button(text("A−").size(11)).on_press(Message::ScaleOut(area)).style(style::tiny_button),
            text(scale.label()).size(11).color(style::GREY).width(46),
            button(text("A+").size(11)).on_press(Message::ScaleIn(area)).style(style::tiny_button),
            button(text("Reset").size(10.5)).on_press(Message::ScaleReset(area)).style(style::tiny_button)
        ].spacing(6).align_y(Center).into()
    };
    column![
        surface(column![
            eyebrow("DISPLAY  /  PER AREA"),
            space().height(10),
            text("Each area scales on its own: make chat text larger without enlarging Settings. The choice is saved and applies on the next start.")
                .size(11.5).color(style::GREY),
            space().height(10),
            scale_row("Chat text", crate::app::Area::Chat, display.chat),
            scale_row("Settings text", crate::app::Area::Settings, display.settings),
            scale_row("Launcher text", crate::app::Area::Launcher, display.launcher),
            space().height(10),
            row![
                text(format!("Chat reading width: {} px", display.chat_measure)).size(11.5).color(style::GREY).width(Fill),
                button(text("Narrower").size(10.5)).on_press(Message::MeasureNarrower).style(style::tiny_button),
                button(text("Wider").size(10.5)).on_press(Message::MeasureWider).style(style::tiny_button)
            ].spacing(6).align_y(Center)
        ].width(Fill)),
        surface(column![
            eyebrow("DATA  /  WHERE IT LIVES"),
            space().height(8),
            text(path).size(11.5).font(style::LABEL).color(style::WHITE),
            space().height(6),
            text("Four small JSON files, each replaced atomically: settings, chats, model tests, debug journal. No API key ever enters them; the writer refuses a credential-shaped field.")
                .size(11).color(style::GREY),
            space().height(10),
            wipes,
            space().height(8),
            row![
                button(text("Wipe everything").size(11)).on_press(Message::WipeEverything)
                    .padding([8, 12]).style(style::control_button),
                text("Keys in the OS vault are not touched by any wipe.").size(10.5).color(style::DIM).width(Fill)
            ].spacing(8).align_y(Center),
            space().height(6),
            text(state.status.clone()).size(10.5).color(style::GREY)
        ].width(Fill))
    ].spacing(14).width(Fill).into()
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

/// Launcher-facing memory scope, plus the Agent's own stage matrix pointer.
/// The launcher shows the same scope for launcher-specific data.
fn lab(memory: MemoryMode, keep_agent: bool) -> Element<'static, Message> {
    let scope_button = |scope: MemoryScope, label: &'static str| -> Element<'static, Message> {
        let active = memory == scope.mode() && (scope != MemoryScope::Heavy || memory == MemoryMode::Heavy);
        button(text(label).size(12.5)).padding([8, 14])
            .on_press(Message::LauncherScope(scope))
            .style(move |theme, status| style::side_nav(active, theme, status)).into()
    };
    surface(column![
        eyebrow("MEMORY SCOPE"),
        space().height(12),
        text("A scope is a starting point, not a RAM limit. Light keeps the least resident; Heavy keeps fetched catalogs and metadata warm. Custom, then Runtime memory, lets you choose per cache and per stage.")
            .size(12).color(style::GREY),
        space().height(14),
        row![
            scope_button(MemoryScope::Light, "Light"),
            scope_button(MemoryScope::Balanced, "Balanced"),
            scope_button(MemoryScope::Heavy, "Heavy"),
            scope_button(MemoryScope::Custom, "Custom")
        ].spacing(8),
        space().height(14),
        button(text(if keep_agent { "Agent / Keep ready" } else { "Agent / Load on open" }).size(12))
            .on_press(Message::ToggleAgentPreview).style(style::control_button),
        space().height(8),
        text("Runtime memory (Settings → Runtime) shows what is actually held and lets you release it. Nothing here caps another process.")
            .size(10.5).color(style::DIM)
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
