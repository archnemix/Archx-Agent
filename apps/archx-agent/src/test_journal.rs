//! Purpose: Records every catalog test run so a failure can be read back later, and says plainly whether a model was ever asked.
//!
//! Item 5 in the owner's list asked for three things this module holds:
//!
//! 1. **Clicking outside must not stop testing.** Nothing here cancels; the run
//!    is owned by the Agent, not by the dialog that started it.
//! 2. **Results are saved for debugging.** Each finished model is written to
//!    `model-tests.json` as it arrives, so a crash or a closed dialog loses
//!    nothing that had already returned.
//! 3. **Only a re-run overwrites them.** A run starts a new *run id* and
//!    replaces the stored document; nothing else clears it.
//!
//! The module also fixes a reporting bug that mattered more than it looked:
//! previously a model whose row could not even be checked (no key for that
//! offset, an unapproved endpoint) was stored as a bare failure string, which
//! reads as "the provider refused". It now carries a [`Source`], so the UI can
//! say *never sent* instead of blaming the provider for a request it never saw.
//!
//! Persistence mechanism: the same JSON-area file the Agent already uses
//! (`storage::Area::ModelTests`), not a database. The reasoning is in
//! `docs/Testing_Results_Persistence.md`: the data is small, bounded, read once
//! at start, written on a handful of events, and already covered by the atomic
//! write and the credential guard. A second store would add a schema and a
//! failure mode without buying a single query.

use serde_json::{json, Value};
use std::sync::{Mutex, OnceLock};

/// Where a row's outcome came from. This is the field that stops a local
/// refusal from being misread as a provider failure.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Source {
    /// We sent a request and the provider answered (success or error).
    Provider,
    /// We never sent a request: no usable key, an unapproved endpoint, or a
    /// shape this build refuses. The model's status is unknown, not bad.
    NotSent,
}

impl Source {
    pub fn id(self) -> &'static str {
        match self { Self::Provider => "provider", Self::NotSent => "never-sent" }
    }
    pub fn label(self) -> &'static str {
        match self { Self::Provider => "provider answered", Self::NotSent => "never sent" }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct Entry {
    pub id: String,
    pub ok: bool,
    pub output: String,
    pub source: Source,
    pub at: u64,
    /// The Agent's own per-request limit at the time, so a time-out can be read
    /// years later as *our* limit rather than the provider's quota.
    pub request_timeout_secs: u64,
}

/// One run: who started it, what was asked for, and what came back.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Run {
    pub run_id: u64,
    pub started_at: u64,
    pub finished_at: Option<u64>,
    pub provider: String,
    pub requested: usize,
    pub entries: Vec<Entry>,
}

impl Run {
    pub fn answered(&self) -> usize { self.entries.iter().filter(|entry| entry.source == Source::Provider).count() }
    pub fn not_sent(&self) -> usize { self.entries.iter().filter(|entry| entry.source == Source::NotSent).count() }
    pub fn passed(&self) -> usize { self.entries.iter().filter(|entry| entry.ok).count() }
    /// Rows the run never reached: cancelled, or the app closed mid-run.
    pub fn unattempted(&self) -> usize { self.requested.saturating_sub(self.entries.len()) }

    /// The one sentence the Settings page and the Debug page both show.
    pub fn summary(&self) -> String {
        let mut text = format!("{} asked for · {} answered · {} passed · {} never sent",
            self.requested, self.answered(), self.passed(), self.not_sent());
        if self.unattempted() > 0 { text.push_str(&format!(" · {} not attempted", self.unattempted())); }
        text
    }

    pub fn to_json(&self) -> Value {
        json!({
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "provider": self.provider,
            "requested": self.requested,
            "entries": self.entries.iter().map(|entry| json!({
                "id": entry.id,
                "ok": entry.ok,
                "output": entry.output,
                "source": entry.source.id(),
                "at": entry.at,
                "request_timeout_secs": entry.request_timeout_secs,
            })).collect::<Vec<_>>(),
        })
    }

    /// Tolerant reader: an unknown `source` becomes `NotSent`, never `Provider`,
    /// so an older or corrupted file can only under-claim, never blame a provider.
    pub fn from_json(body: &Value) -> Option<Self> {
        let entries = body.get("entries")?.as_array()?;
        Some(Self {
            run_id: body.get("run_id").and_then(Value::as_u64).unwrap_or(0),
            started_at: body.get("started_at").and_then(Value::as_u64).unwrap_or(0),
            finished_at: body.get("finished_at").and_then(Value::as_u64),
            provider: body.get("provider").and_then(Value::as_str).unwrap_or("").to_owned(),
            requested: body.get("requested").and_then(Value::as_u64).unwrap_or(entries.len() as u64) as usize,
            entries: entries.iter().filter_map(|entry| Some(Entry {
                id: entry.get("id")?.as_str()?.to_owned(),
                ok: entry.get("ok").and_then(Value::as_bool).unwrap_or(false),
                output: entry.get("output").and_then(Value::as_str).unwrap_or("").to_owned(),
                source: match entry.get("source").and_then(Value::as_str) {
                    Some("provider") => Source::Provider,
                    _ => Source::NotSent,
                },
                at: entry.get("at").and_then(Value::as_u64).unwrap_or(0),
                request_timeout_secs: entry.get("request_timeout_secs").and_then(Value::as_u64).unwrap_or(0),
            })).collect(),
        })
    }
}

fn slot() -> &'static Mutex<Option<Run>> {
    static RUN: OnceLock<Mutex<Option<Run>>> = OnceLock::new();
    RUN.get_or_init(|| Mutex::new(None))
}

/// Starts a run. This is the only call that discards stored results, which is
/// exactly the "only a re-run overwrites" rule.
pub fn begin(started_at: u64, provider: &str, ids: &[String]) {
    let mut guard = slot().lock().unwrap_or_else(|poison| poison.into_inner());
    *guard = Some(Run {
        run_id: started_at,
        started_at,
        finished_at: None,
        provider: provider.to_owned(),
        requested: ids.len(),
        entries: Vec::new(),
    });
}

/// Adds one finished row. A row for the same model replaces its predecessor, so
/// a retried model does not appear twice in one run.
pub fn record(entry: Entry) {
    let mut guard = slot().lock().unwrap_or_else(|poison| poison.into_inner());
    let run = guard.get_or_insert_with(|| Run { requested: 1, ..Run::default() });
    if let Some(existing) = run.entries.iter_mut().find(|existing| existing.id == entry.id) {
        *existing = entry;
    } else {
        run.entries.push(entry);
    }
}

/// Closes the run and returns it. Also fills in rows the run never reached, so
/// a cancelled run cannot look like a run that tested everything.
pub fn finish(finished_at: u64) -> Run {
    let guard = slot().lock().unwrap_or_else(|poison| poison.into_inner());
    let mut run = guard.clone().unwrap_or_default();
    run.finished_at = Some(finished_at);
    run
}

/// Forgets the in-memory run. Called only by a deliberate wipe, so a wiped
/// file cannot be rewritten from memory on the next save.
pub fn clear() {
    *slot().lock().unwrap_or_else(|poison| poison.into_inner()) = None;
}

pub fn current() -> Option<Run> {
    slot().lock().unwrap_or_else(|poison| poison.into_inner()).clone()
}

/// The run as the one document that owns `model-tests.json`.
///
/// There is exactly one writer for that file (`persist_tests`), so the journal
/// never races the legacy `results` list over the same path; it is embedded as
/// the `run` field of the document that writer already produces.
pub fn embed(run: &Run) -> Value { run.to_json() }

pub fn from_document(body: &Value) -> Option<Run> {
    Run::from_json(body.get("run")?)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entry(id: &str, ok: bool, source: Source) -> Entry {
        Entry { id: id.into(), ok, output: "text".into(), source, at: 10, request_timeout_secs: 45 }
    }

    #[test]
    fn a_run_counts_asked_answered_never_sent_and_unattempted_separately() {
        let run = Run {
            run_id: 7, started_at: 7, finished_at: Some(9), provider: "openrouter".into(),
            requested: 4,
            entries: vec![entry("a", true, Source::Provider), entry("b", false, Source::Provider),
                entry("c", false, Source::NotSent)],
        };
        assert_eq!((run.answered(), run.not_sent(), run.passed(), run.unattempted()), (2, 1, 1, 1));
        assert_eq!(run.summary(), "4 asked for · 2 answered · 1 passed · 1 never sent · 1 not attempted");
    }

    #[test]
    fn a_never_sent_row_is_not_counted_as_an_answer() {
        let run = Run { requested: 1, entries: vec![entry("x", false, Source::NotSent)], ..Run::default() };
        assert_eq!(run.answered(), 0);
        assert!(run.summary().contains("1 never sent"));
        assert_eq!(Source::NotSent.label(), "never sent");
    }

    #[test]
    fn a_run_round_trips_with_its_provenance_and_our_timeout() {
        let run = Run { run_id: 42, started_at: 42, finished_at: Some(50), provider: "gemini".into(),
            requested: 2, entries: vec![entry("m1", true, Source::Provider), entry("m2", false, Source::NotSent)] };
        let back = Run::from_json(&run.to_json()).expect("round trip");
        assert_eq!(back, run);
        assert_eq!(back.entries[1].source, Source::NotSent);
        assert_eq!(back.entries[1].request_timeout_secs, 45, "the timeout travels with the row");
    }

    #[test]
    fn an_unreadable_source_never_becomes_a_provider_failure() {
        let body = json!({"requested": 1, "entries": [{"id": "m", "ok": false, "output": "?"}]});
        let run = Run::from_json(&body).expect("parses");
        assert_eq!(run.entries[0].source, Source::NotSent);
        assert_eq!(run.answered(), 0);
        assert!(Run::from_json(&json!({"provider": "x"})).is_none(), "no entries is not a run");
    }

    #[test]
    fn nothing_in_this_module_can_end_a_run_early() {
        // A structural guard for item 5: the journal exposes begin, record,
        // finish and clear — no handle, no cancellation — so closing a dialog
        // has no route to a run's lifetime through this module. The test looks
        // at the code above `#[cfg(test)]` so it cannot match itself.
        let source = include_str!("test_journal.rs");
        let code = source.split("#[cfg(test)]").next().unwrap_or_default();
        for forbidden in ["abort", "Cancel", "cancel_", "CloseCatalog", "cancel()"] {
            assert!(!code.contains(forbidden), "the journal must not know about {forbidden}");
        }
        for allowed in ["pub fn begin(", "pub fn record(", "pub fn finish(", "pub fn clear("] {
            assert!(code.contains(allowed), "the journal should expose {allowed}");
        }
    }
}
