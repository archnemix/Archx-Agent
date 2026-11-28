//! Purpose: Keeps a bounded, persistent record of every provider request for the in-app Debug page.
//!
//! The reference does this with a server-side journal (`POST /api/chat` logs every
//! provider attempt keyed by `traceId`, read back through `GET /api/chat-debug`);
//! `CHATDEBUG-MAP.md` documents its ring buffer and pinned-scroll behaviour. The
//! native app has no server, so the same information is recorded in-process and
//! mirrored to `debug-journal.json` (the `Debug` storage area), which the Settings
//! page can read, filter, export and wipe.
//!
//! Only metadata is stored: provider, model, key slot number, timings, byte
//! counts, HTTP status, a redacted provider message excerpt and the diagnosis.
//! The prompt and answer bodies are never recorded.

use serde_json::{json, Value};

use crate::diagnostics::{Diagnosis, Owner, Stage};

pub const MAX_ENTRIES: usize = 200;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    Pending,
    Ok,
    /// Answered, but the answer stopped at the output ceiling this Agent sent.
    /// Kept distinct from `Ok` on purpose: the request did succeed, and the
    /// reply is still not a finished answer.
    Capped,
    Failed,
}

impl Outcome {
    pub fn label(self) -> &'static str {
        match self {
            Self::Pending => "running",
            Self::Ok => "ok",
            Self::Capped => "cut off",
            Self::Failed => "failed",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Entry {
    pub id: u64,
    pub at: u64,
    pub provider: &'static str,
    pub model: String,
    /// 0 when no vault key was used (for example loopback Ollama).
    pub key_id: u64,
    pub streamed: bool,
    pub outcome: Outcome,
    pub started_ms: u128,
    pub duration_ms: u128,
    pub status: Option<u16>,
    pub request_bytes: usize,
    pub response_bytes: usize,
    pub chars: usize,
    pub reasoning_chars: usize,
    /// Redacted provider excerpt (never our headers or key).
    pub detail: String,
    pub diagnosis: Option<Diagnosis>,
}

impl Entry {
    pub fn is_success(&self) -> bool {
        self.outcome == Outcome::Ok
    }

    /// Answered, but not in full. Counted apart from a clean success so a page
    /// cannot report "all requests succeeded" over a reply that was cut off.
    pub fn is_capped(&self) -> bool {
        self.outcome == Outcome::Capped
    }

    pub fn summary(&self) -> String {
        match self.outcome {
            Outcome::Pending => format!("{} · {} · streaming…", self.provider, self.model),
            Outcome::Ok => format!("{} · {} · {} ms · {} chars", self.provider, self.model, self.duration_ms, self.chars),
            Outcome::Capped => format!("{} · {} · {} ms · {} chars · stopped at our output limit",
                self.provider, self.model, self.duration_ms, self.chars),
            Outcome::Failed => format!("{} · {} · {} · {} ms", self.provider, self.model,
                self.status.map_or("no status".to_owned(), |status| format!("HTTP {status}")), self.duration_ms),
        }
    }

    pub fn to_json(&self) -> Value {
        json!({
            "id": self.id,
            "at": self.at,
            "provider": self.provider,
            "model": self.model,
            "key_id": self.key_id,
            "streamed": self.streamed,
            "outcome": self.outcome.label(),
            "duration_ms": self.duration_ms,
            "status": self.status,
            "request_bytes": self.request_bytes,
            "response_bytes": self.response_bytes,
            "chars": self.chars,
            "reasoning_chars": self.reasoning_chars,
            "detail": self.detail,
            "diagnosis": self.diagnosis.as_ref().map(|d| json!({
                "stage": d.stage_label(), "owner": match d.owner {
                    Owner::Agent => "agent", Owner::Provider => "provider", Owner::Key => "key", Owner::Model => "model"
                }, "http_status": d.http_status, "cooldown": d.cooldown, "retry_after": d.retry_after,
                "summary": redact(&d.summary)
            })),
        })
    }

    pub fn from_json(value: &Value) -> Option<Self> {
        let provider = match value.get("provider").and_then(Value::as_str)? {
            "OpenRouter" => "OpenRouter", "Grok (xAI)" => "Grok (xAI)", "Gemini" => "Gemini",
            "OpenAI" => "OpenAI", "Anthropic" => "Anthropic", "Groq" => "Groq", "Z.ai" => "Z.ai",
            "Ollama · local" => "Ollama · local", "Ollama · cloud" => "Ollama · cloud", _ => "Custom URL",
        };
        Some(Self {
            id: value.get("id").and_then(Value::as_u64)?,
            at: value.get("at").and_then(Value::as_u64).unwrap_or(0),
            provider,
            model: value.get("model").and_then(Value::as_str).unwrap_or("").chars().take(200).collect(),
            key_id: value.get("key_id").and_then(Value::as_u64).unwrap_or(0),
            streamed: value.get("streamed").and_then(Value::as_bool).unwrap_or(false),
            outcome: match value.get("outcome").and_then(Value::as_str) {
                Some("ok") => Outcome::Ok, Some("cut off") => Outcome::Capped,
                Some("failed") => Outcome::Failed, _ => Outcome::Pending,
            },
            started_ms: 0,
            duration_ms: value.get("duration_ms").and_then(Value::as_u64).unwrap_or(0) as u128,
            status: value.get("status").and_then(Value::as_u64).map(|code| code as u16),
            request_bytes: value.get("request_bytes").and_then(Value::as_u64).unwrap_or(0) as usize,
            response_bytes: value.get("response_bytes").and_then(Value::as_u64).unwrap_or(0) as usize,
            chars: value.get("chars").and_then(Value::as_u64).unwrap_or(0) as usize,
            reasoning_chars: value.get("reasoning_chars").and_then(Value::as_u64).unwrap_or(0) as usize,
            detail: value.get("detail").and_then(Value::as_str).unwrap_or("").chars().take(600).collect(),
            diagnosis: value.get("diagnosis").and_then(|d| {
                let stage = match d.get("stage")?.as_str()? {
                    "request" => Stage::Request, "transport" => Stage::Transport, "http" => Stage::Http,
                    "parse" => Stage::Parse, "bounds" => Stage::Bounds, _ => return None,
                };
                let owner = match d.get("owner")?.as_str()? {
                    "agent" => Owner::Agent, "provider" => Owner::Provider, "key" => Owner::Key, "model" => Owner::Model, _ => return None,
                };
                Some(Diagnosis { stage, owner,
                    http_status: d.get("http_status").and_then(Value::as_u64).and_then(|n| u16::try_from(n).ok()),
                    cooldown: d.get("cooldown").and_then(Value::as_u64),
                    retry_after: d.get("retry_after").and_then(Value::as_u64),
                    summary: d.get("summary").and_then(Value::as_str).unwrap_or("").chars().take(600).collect(),
                })
            }),
        })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Filter {
    All,
    Failed,
    Provider(&'static str),
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Journal {
    entries: Vec<Entry>,
    next_id: u64,
}

impl Journal {
    pub fn new() -> Self {
        Self { entries: Vec::new(), next_id: 1 }
    }

    pub fn entries(&self) -> &[Entry] {
        &self.entries
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    pub fn clear(&mut self) {
        self.entries.clear();
    }

    /// Records the start of a request and returns its id for the completion.
    pub fn begin(&mut self, provider: &'static str, model: String, key_id: u64, streamed: bool, request_bytes: usize) -> u64 {
        let id = self.next_id;
        self.next_id = self.next_id.saturating_add(1);
        self.entries.push(Entry {
            id,
            at: crate::storage::now_secs(),
            provider,
            model,
            key_id,
            streamed,
            outcome: Outcome::Pending,
            started_ms: crate::storage::now_secs() as u128 * 1000,
            duration_ms: 0,
            status: None,
            request_bytes,
            response_bytes: 0,
            chars: 0,
            reasoning_chars: 0,
            detail: String::new(),
            diagnosis: None,
        });
        self.trim();
        id
    }

    pub fn finish_ok(&mut self, id: u64, duration_ms: u128, chars: usize, reasoning_chars: usize, response_bytes: usize) {
        if let Some(entry) = self.entries.iter_mut().find(|entry| entry.id == id) {
            entry.outcome = Outcome::Ok;
            entry.duration_ms = duration_ms;
            entry.chars = chars;
            entry.reasoning_chars = reasoning_chars;
            entry.response_bytes = response_bytes;
            entry.detail.clear();
            entry.diagnosis = None;
        }
    }

    /// Records a request that succeeded at the transport level but whose answer
    /// stopped at the output ceiling this Agent sent.
    ///
    /// The entry stays `Ok`: nothing failed, the key is healthy and the model did
    /// nothing wrong. It carries a diagnosis and the detail line anyway, because
    /// "why does this reply end mid-sentence" is exactly the question the Debug
    /// page exists to answer, and the honest answer is ours, not the provider's.
    pub fn finish_capped(&mut self, id: u64, duration_ms: u128, chars: usize, reasoning_chars: usize,
        response_bytes: usize, diagnosis: Diagnosis) {
        if let Some(entry) = self.entries.iter_mut().find(|entry| entry.id == id) {
            entry.outcome = Outcome::Capped;
            entry.duration_ms = duration_ms;
            entry.chars = chars;
            entry.reasoning_chars = reasoning_chars;
            entry.response_bytes = response_bytes;
            // Ours, not the provider's: the page labels this line by who said it.
            entry.detail = "finish_reason = length".to_owned();
            entry.diagnosis = Some(diagnosis);
        }
    }

    pub fn finish_failed(&mut self, id: u64, duration_ms: u128, diagnosis: Diagnosis, detail: String) {
        if let Some(entry) = self.entries.iter_mut().find(|entry| entry.id == id) {
            entry.outcome = Outcome::Failed;
            entry.duration_ms = duration_ms;
            entry.status = diagnosis.http_status;
            entry.detail = redact(&detail);
            entry.diagnosis = Some(diagnosis);
        }
    }

    /// A streaming failure keeps the text already shown; the entry records both.
    pub fn finish_partial(&mut self, id: u64, duration_ms: u128, chars: usize, reasoning_chars: usize, diagnosis: Diagnosis) {
        if let Some(entry) = self.entries.iter_mut().find(|entry| entry.id == id) {
            entry.outcome = Outcome::Failed;
            entry.duration_ms = duration_ms;
            entry.status = diagnosis.http_status;
            entry.chars = chars;
            entry.reasoning_chars = reasoning_chars;
            entry.detail = format!("Partial text was shown to the user before this failure. {}", redact(&diagnosis.summary));
            entry.diagnosis = Some(diagnosis);
        }
    }

    fn trim(&mut self) {
        if self.entries.len() > MAX_ENTRIES {
            let excess = self.entries.len() - MAX_ENTRIES;
            self.entries.drain(..excess);
        }
    }

    /// Newest first, filtered. The Debug page renders this order.
    pub fn view(&self, filter: Filter) -> Vec<&Entry> {
        self.entries.iter().rev()
            .filter(|entry| match filter {
                Filter::All => true,
                Filter::Failed => entry.outcome == Outcome::Failed,
                Filter::Provider(name) => entry.provider == name,
            })
            .collect()
    }

    pub fn counts(&self) -> (usize, usize, usize) {
        let failed = self.entries.iter().filter(|entry| entry.outcome == Outcome::Failed).count();
        (self.entries.len(), failed, self.entries.iter().filter(|entry| entry.outcome == Outcome::Pending).count())
    }

    pub fn to_json(&self) -> Value {
        json!({ "entries": self.entries.iter().map(Entry::to_json).collect::<Vec<_>>() })
    }

    pub fn from_json(value: &Value) -> Self {
        let mut journal = Self::new();
        // Accepts a bare body or a whole envelope, as the other areas do.
        let value = crate::storage::body(value).unwrap_or(value);
        if let Some(entries) = value.get("entries").and_then(Value::as_array) {
            for entry in entries.iter().rev().take(MAX_ENTRIES).rev() {
                if let Some(entry) = Entry::from_json(entry) {
                    journal.next_id = journal.next_id.max(entry.id + 1);
                    journal.entries.push(entry);
                }
            }
        }
        journal
    }

    /// Plain-text export for a bug report. No prompt or answer text exists here.
    pub fn export(&self) -> String {
        let mut text = String::from("Archx Agent request journal · metadata only, no prompt or reply text\n");
        for entry in self.entries.iter().rev() {
            text.push_str(&format!(
                "#{:04} {} · {} · {} · key {} · {} · {} ms · in {} B · out {} B · {} chars\n",
                entry.id, entry.provider, entry.model, entry.outcome.label(),
                if entry.key_id == 0 { "none".to_owned() } else { format!("#{}", entry.key_id) },
                entry.status.map_or("-".to_owned(), |status| status.to_string()),
                entry.duration_ms, entry.request_bytes, entry.response_bytes, entry.chars));
            if !entry.detail.is_empty() { text.push_str(&format!("      {}\n", entry.detail)); }
            if let Some(diagnosis) = &entry.diagnosis {
                text.push_str(&format!("      {} · {} · {}\n", diagnosis.stage_label(), diagnosis.owner_label(), diagnosis.summary));
            }
        }
        text
    }
}

/// Removes anything that looks like a bearer token or key from provider text
/// before it is stored or displayed.
pub fn redact(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    for (index, token) in input.split_whitespace().enumerate() {
        if index > 0 { out.push(' '); }
        let lower = token.to_ascii_lowercase();
        let looks_secret = token.len() >= 20 && (
            lower.starts_with("sk-") || lower.starts_with("gsk_") || lower.starts_with("aiza")
                || lower.starts_with("bearer") || (token.chars().filter(|c| c.is_ascii_alphanumeric()).count() > 24
                    && token.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))));
        // The word around the secret is what makes the message readable, so the
        // redaction replaces the token and leaves the spacing alone.
        if looks_secret { out.push_str("[redacted]"); } else { out.push_str(token); }
    }
    out.chars().take(600).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::diagnostics::{from_http, transport};

    #[test]
    fn journal_records_success_and_failure_with_bounded_metadata() {
        let mut journal = Journal::new();
        let ok = journal.begin("OpenRouter", "vendor/model".into(), 1, true, 812);
        journal.finish_ok(ok, 2_310, 1_204, 88, 9_001);
        let failed = journal.begin("Gemini", "gemini-2".into(), 0, false, 640);
        journal.finish_failed(failed, 45_000, transport(true), "read timeout".to_owned());
        let entries = journal.view(Filter::All);
        assert_eq!(entries.len(), 2);
        // Newest first.
        assert_eq!(entries[0].id, failed);
        assert_eq!(entries[0].status, None);
        assert_eq!(entries[1].outcome, Outcome::Ok);
        assert_eq!(entries[1].chars, 1_204);
        assert_eq!(journal.counts(), (2, 1, 0));
        assert_eq!(journal.view(Filter::Failed).len(), 1);
        assert_eq!(journal.view(Filter::Provider("OpenRouter")).len(), 1);
        assert!(journal.export().contains("metadata only"));
    }

    #[test]
    fn failure_diagnosis_survives_reload() {
        let mut journal = Journal::new();
        let id = journal.begin("Gemini", "model".into(), 1, false, 100);
        journal.finish_failed(id, 10, transport(true), String::new());
        let reloaded = Journal::from_json(&journal.to_json());
        let diagnosis = reloaded.entries()[0].diagnosis.as_ref().expect("saved diagnosis");
        assert_eq!(diagnosis.stage, Stage::Transport);
        assert_eq!(diagnosis.owner, Owner::Agent);
    }

    #[test]
    fn journal_is_a_ring_buffer_and_json_round_trips() {
        let mut journal = Journal::new();
        for n in 0..(MAX_ENTRIES + 12) {
            let id = journal.begin("Groq", format!("m{n}"), 1, false, 10);
            journal.finish_ok(id, 5, 1, 0, 20);
        }
        assert_eq!(journal.len(), MAX_ENTRIES);
        let restored = Journal::from_json(&journal.to_json());
        assert_eq!(restored.len(), MAX_ENTRIES);
        assert_eq!(restored.entries().last().map(|entry| entry.model.clone()), Some(format!("m{}", MAX_ENTRIES + 11)));
        // A hostile document cannot grow the journal past the bound.
        let many: Vec<_> = (0..500).map(|n| json!({"id": n + 1, "provider": "OpenAI", "model": "x"})).collect();
        assert_eq!(Journal::from_json(&json!({ "entries": many })).len(), MAX_ENTRIES);
    }

    #[test]
    fn provider_excerpts_are_redacted_before_storage() {
        assert_eq!(redact("Incorrect key sk-or-v1-abcdef0123456789abcdef supplied"), "Incorrect key [redacted] supplied");
        assert_eq!(redact("Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345"), "Authorization: Bearer [redacted]");
        // Ordinary short words are untouched.
        assert_eq!(redact("quota exceeded for this key"), "quota exceeded for this key");
        assert!(redact(&"x".repeat(2_000)).chars().count() <= 600);
        let long = "word ".repeat(400);
        assert!(redact(&long).chars().count() <= 600);
    }

    #[test]
    fn partial_stream_failure_is_recorded_with_what_the_user_saw() {
        let mut journal = Journal::new();
        let id = journal.begin("Anthropic", "claude".into(), 3, true, 500);
        journal.finish_partial(id, 9_000, 1_500, 200, from_http(500, Some("internal error")));
        let entry = &journal.entries()[0];
        assert_eq!(entry.outcome, Outcome::Failed);
        assert_eq!(entry.chars, 1_500);
        assert!(entry.detail.contains("Partial text"));
        assert_eq!(entry.status, Some(500));
    }
}
