//! Purpose: Renders the in-app Debug page: every provider request with stage, owner, timing and status.
//!
//! The reference has a server-side journal behind `GET /api/chat-debug`
//! (`CHATDEBUG-MAP.md`). This page is the native equivalent: it reads the bounded
//! in-process journal and answers the two questions the user actually asked —
//! "what does this red error mean, and who timed out?" — on the same screen.
//! Only metadata is shown; no prompt, answer or key text exists in the journal.

use iced::widget::{button, column, container, row, scrollable, space, text};
use iced::{Center, Element, Fill};

use crate::app::Message;
use archx_shared::credentials::Provider;
use archx_shared::debug_log::{Entry, Filter, Journal, Outcome};
use archx_shared::diagnostics;
use archx_shared::style;

fn status_color(outcome: Outcome) -> iced::Color {
    match outcome {
        Outcome::Ok => style::OK,
        Outcome::Capped => style::WARN,
        Outcome::Failed => style::FAILURE,
        Outcome::Pending => style::GREY,
    }
}

/// A filter button that reads as selected when its filter is active.
fn filter_chip(label: &str, active: bool, message: Message) -> Element<'static, Message> {
    button(text(label.to_owned()).size(11))
        .padding([5, 10]).on_press(message)
        .style(move |theme, status| style::list_row(active, theme, status))
        .into()
}

fn entry_row(entry: &Entry, selected: bool, id: u64) -> Element<'static, Message> {
    let mut details = column![].spacing(3);
    details = details.push(text(entry.summary()).size(12).color(style::WHITE));
    let mut meta = format!("key {} · {} B in · {} B out · {} chars", if entry.key_id == 0 { "none".to_owned() } else { format!("#{}", entry.key_id) },
        entry.request_bytes, entry.response_bytes, entry.chars);
    if entry.reasoning_chars > 0 { meta.push_str(&format!(" · {} reasoning chars", entry.reasoning_chars)); }
    if entry.streamed { meta.push_str(" · streamed"); }
    details = details.push(text(meta).size(10.5).color(style::DIM));
    if selected {
        if let Some(diagnosis) = &entry.diagnosis {
            details = details.push(text(format!("stage: {} · owner: {}", diagnosis.stage_label(), diagnosis.owner_label()))
                .size(11).color(style::WHITE));
            details = details.push(text(diagnosis.summary.clone()).size(11).color(style::GREY));
            if let Some(cooldown) = diagnosis.cooldown {
                details = details.push(text(format!("suggested rest: {}", diagnostics::human_duration(cooldown)))
                    .size(10.5).color(style::GREY));
            }
        }
        if !entry.detail.is_empty() {
            // This line is either the provider's own words or our note about its
            // finish reason, so it is labelled by who actually said it.
            let label = if entry.is_capped() { "our reading" } else { "provider said" };
            details = details.push(text(format!("{label}: {}", entry.detail)).size(10.5).color(style::GREY));
        }
    }
    button(column![
        row![
            text(format!("#{:04}  ·  {}", entry.id, entry.provider)).size(10.5).color(style::GREY),
            space().width(Fill),
            text(entry.outcome.label()).size(10.5).color(status_color(entry.outcome)),
            text(entry.status.map_or(String::new(), |status| format!("HTTP {status}"))).size(10.5).color(style::DIM)
        ].spacing(6).align_y(Center),
        details
    ].spacing(4))
        .width(Fill).padding([8, 10])
        .on_press(Message::DebugSelect(id))
        .style(move |theme, status| style::list_row(selected, theme, status))
        .into()
}

pub fn view(journal: &Journal, filter: Filter, selected: Option<u64>, help_open: bool, help_seen: bool) -> Element<'static, Message> {
    let (total, failed, pending) = journal.counts();
    let entries: Vec<Entry> = journal.view(filter).into_iter().cloned().collect();
    let mut list = column![].spacing(4).width(Fill);
    if entries.is_empty() {
        list = list.push(text(if total == 0 {
            "No requests recorded yet. Every send, test and probe appears here with its outcome."
        } else {
            "No request matches this filter."
        }).size(12).color(style::GREY));
    }
    for entry in &entries {
        list = list.push(entry_row(entry, selected == Some(entry.id), entry.id));
    }
    let mut filters = row![
        filter_chip("All", filter == Filter::All, Message::DebugFilter(Filter::All)),
        filter_chip("Failed", filter == Filter::Failed, Message::DebugFilter(Filter::Failed))
    ].spacing(6);
    for provider in Provider::ALL.iter().copied().filter(|provider| *provider != Provider::Custom) {
        let active = filter == Filter::Provider(provider.name());
        filters = filters.push(filter_chip(provider.name(), active, Message::DebugFilter(Filter::Provider(provider.name()))));
    }
    let stage_legend = column![
        text("Stage tells you where it broke:").size(11.5).color(style::WHITE),
        text("request · the Agent refused to send (model, length)").size(11).color(style::GREY),
        text("transport · DNS, TLS, proxy or our own timeout — nothing came back").size(11).color(style::GREY),
        text("http · the provider answered with a status and a reason").size(11).color(style::GREY),
        text("parse · a reply arrived but not in the expected shape").size(11).color(style::GREY),
        text("bounds · our 2 MiB / 96,000-character limit stopped it").size(11).color(style::GREY),
        space().height(6),
        text(format!("Timeouts: the Agent enforces its own limit of {} s per request and {} s per catalog fetch. A timeout is our limit, not the provider's quota; the request may already be billed.",
            diagnostics::REQUEST_TIMEOUT_SECS, diagnostics::CATALOG_TIMEOUT_SECS)).size(11).color(style::DIM)
    ].spacing(3);
    let help: Element<'static, Message> = if help_open {
        container(column![stage_legend, space().height(8),
            button(text(if help_seen { "Close" } else { "OK, got it" }).size(11))
                .on_press(Message::DebugHelpOk).style(style::tiny_button)
        ].spacing(4)).padding(16).width(Fill).style(style::card).into()
    } else { space().height(0).into() };
    let header = row![
        column![
            text("Request debug").size(20).font(style::STRONG).color(style::WHITE),
            text("Every provider request, its stage, owner and timing. Metadata only: no prompt, reply or key text is stored.")
                .size(11.5).color(style::GREY)
        ].spacing(3).width(Fill),
        button(text("Help").size(11)).on_press(Message::DebugHelpToggle).style(style::tiny_button),
        button(text("Export").size(11)).on_press(Message::DebugExport).style(style::tiny_button),
        button(text("Reload").size(11)).on_press(Message::DebugRefresh).style(style::tiny_button),
        button(text("Clear").size(11)).on_press(Message::DebugWipe).style(style::tiny_button)
    ].spacing(6).align_y(Center);
    column![
        container(header).padding(20).width(Fill).style(style::settings_header),
        container(column![
            row![
                text(format!("{total} recorded")).size(11).color(style::DIM).width(Fill),
                text(format!("{failed} failed")).size(11).color(if failed > 0 { style::FAILURE } else { style::DIM }),
                text(if pending > 0 { format!("{pending} running") } else { String::new() }).size(11).color(style::WARN)
            ].spacing(10).align_y(Center),
            space().height(10),
            filters,
            space().height(12),
            scrollable(column![help, space().height(8), container(list).width(Fill)].width(Fill)).height(Fill).style(style::quiet_scroll)
        ].width(Fill).height(Fill)).padding(20).width(Fill).height(Fill)
    ].width(Fill).height(Fill).into()
}
