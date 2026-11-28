//! Purpose: Classifies provider failures into a stage, an owner, a suggested cooldown and a plain-language explanation.
//!
//! Every failure the Agent shows is produced here, so the Debug page and the
//! chat error line always agree. The important distinction the UI must never
//! blur: a transport timeout is *our* configured limit (45 s per request), not
//! a provider quota, and not proof that the provider stopped generating.

use std::time::Duration;

/// The Agent's own per-request limits. Shown verbatim in Settings and Debug.
pub const REQUEST_TIMEOUT_SECS: u64 = 45;
pub const CATALOG_TIMEOUT_SECS: u64 = 25;

/// Cooldown applied to one vault key after a failure that is specific to it.
pub const KEY_COOLDOWN_SECS: u64 = 300;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stage {
    /// Building the request (invalid model, empty input).
    Request,
    /// DNS, TLS, proxy, connect or read timeout.
    Transport,
    /// A non-2xx HTTP status came back.
    Http,
    /// A 2xx response whose body was not the expected shape.
    Parse,
    /// The response exceeded the Agent's byte or character bounds.
    Bounds,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Owner {
    /// The Agent's own guard rails and configuration.
    Agent,
    /// The provider or the network path to it.
    Provider,
    /// The specific API key used (quota, revoked, wrong project).
    Key,
    /// The specific model id (retired, not enabled for this account).
    Model,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Diagnosis {
    pub stage: Stage,
    pub owner: Owner,
    pub http_status: Option<u16>,
    /// Seconds this key or model should rest before another attempt.
    pub cooldown: Option<u64>,
    /// The key-specific window when the provider sent a reset hint.
    pub retry_after: Option<u64>,
    /// One sentence a user can act on.
    pub summary: String,
}

impl Diagnosis {
    pub fn stage_label(&self) -> &'static str {
        match self.stage {
            Stage::Request => "request",
            Stage::Transport => "transport",
            Stage::Http => "http",
            Stage::Parse => "parse",
            Stage::Bounds => "bounds",
        }
    }

    pub fn owner_label(&self) -> &'static str {
        match self.owner {
            Owner::Agent => "Agent (this app)",
            Owner::Provider => "Provider",
            Owner::Key => "API key",
            Owner::Model => "Model",
        }
    }

    pub fn retries_key(&self) -> bool {
        matches!(self.owner, Owner::Key)
    }

    pub fn retries_model(&self) -> bool {
        matches!(self.owner, Owner::Model)
    }
}

/// Reasons a provider gives for refusing a request, matched conservatively.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Reason {
    Auth,
    Quota,
    RateLimit,
    ModelRetired,
    ModelAccess,
    Overloaded,
    ContextTooLong,
    Other,
}

/// Classifies a provider's own message text. Only called with a short,
/// bounded excerpt the provider returned; never with our headers or key.
pub fn classify_message(status: Option<u16>, message: &str) -> Reason {
    let text = message.to_ascii_lowercase();
    let has = |needles: &[&str]| needles.iter().any(|needle| text.contains(needle));
    // Retired or renamed model ids first: several providers phrase these with
    // "not found" or "invalid", which would otherwise read as an auth failure.
    if has(&["decommission", "deprecat", "retired", "no longer available", "sunset", "shut down", "shutdown"]) {
        return Reason::ModelRetired;
    }
    if has(&["does not exist", "not found", "unknown model", "model_not_found", "no such model", "invalid model"]) {
        return Reason::ModelRetired;
    }
    if has(&["not enabled", "no access", "access to model", "not available in your", "permission", "not supported in your country", "verify your account", "billing"]) {
        return Reason::ModelAccess;
    }
    if has(&["quota", "insufficient", "exceeded your current", "credits", "payment required", "out of tokens", "balance"]) {
        return Reason::Quota;
    }
    if has(&["rate limit", "too many requests", "per minute", "requests per", "throttl"]) {
        return Reason::RateLimit;
    }
    if has(&["api key", "unauthor", "invalid key", "authentication", "401", "forbidden", "api_key_invalid", "key not valid"]) {
        return Reason::Auth;
    }
    if has(&["overload", "capacity", "busy", "temporarily unavailable", "try again"]) {
        return Reason::Overloaded;
    }
    if has(&["context length", "context_length", "too long", "maximum context", "token limit", "too many tokens"]) {
        return Reason::ContextTooLong;
    }
    match status {
        Some(401 | 403) => Reason::Auth,
        Some(402) => Reason::Quota,
        Some(404 | 410) => Reason::ModelRetired,
        Some(413) => Reason::ContextTooLong,
        Some(429) => Reason::RateLimit,
        Some(503 | 529) => Reason::Overloaded,
        _ => Reason::Other,
    }
}

fn doctor_for(reason: Reason) -> &'static str {
    match reason {
        Reason::Auth => "Check this key: the provider rejected it as unauthenticated or revoked.",
        Reason::Quota => "This key has no quota or credit left. Add credit, or use another key; the model is not at fault.",
        Reason::RateLimit => "This key is sending too fast or hit its per-minute limit. It rests, then returns automatically.",
        Reason::ModelRetired => "The provider says this model ID is retired or unknown. Remove it, or fetch the catalog again for the current list.",
        Reason::ModelAccess => "This account cannot use this model (not enabled or not on your plan). It is not a network problem.",
        Reason::Overloaded => "The provider is temporarily overloaded. This is on their side; retrying later is reasonable.",
        Reason::ContextTooLong => "The conversation no longer fits this model's context window. Start a shorter chat.",
        Reason::Other => "The provider refused the request. Read its message above; nothing was retried automatically.",
    }
}

/// Classifies an HTTP refusal using the provider's short message excerpt.
pub fn from_http(status: u16, message: Option<&str>) -> Diagnosis {
    let reason = classify_message(Some(status), message.unwrap_or(""));
    let (owner, cooldown) = match reason {
        Reason::Auth | Reason::Quota => (Owner::Key, Some(KEY_COOLDOWN_SECS)),
        Reason::RateLimit => (Owner::Key, Some(KEY_COOLDOWN_SECS)),
        Reason::ModelRetired | Reason::ModelAccess => (Owner::Model, None),
        Reason::Overloaded | Reason::ContextTooLong | Reason::Other => (Owner::Provider, None),
    };
    Diagnosis {
        stage: Stage::Http,
        owner,
        http_status: Some(status),
        cooldown,
        retry_after: None,
        summary: format!("HTTP {status}: {}", doctor_for(reason)),
    }
}

/// Classifies a transport-level failure. The Agent's 45 s client timeout is
/// reported as such — it says nothing about the provider's own limit.
pub fn transport(may_have_billed: bool) -> Diagnosis {
    Diagnosis {
        stage: Stage::Transport,
        owner: Owner::Agent,
        http_status: None,
        cooldown: None,
        retry_after: None,
        summary: if may_have_billed {
            format!("No response within the Agent's own {REQUEST_TIMEOUT_SECS} s request limit (DNS, TLS, proxy or the provider could not be reached before it expired). The provider may still be generating and may bill the request; retrying can duplicate a charge.")
        } else {
            "The connection failed before a response arrived (DNS, TLS, proxy or offline). Nothing was billed by the Agent.".to_owned()
        },
    }
}

/// A reply that stopped because the model reached the output cap *we* asked for.
///
/// This is the one failure that arrives looking like success: a provider reports
/// a normal HTTP 200 and a `finish_reason` of `length` (OpenAI-compatible),
/// `max_tokens` (Anthropic) or `MAX_TOKENS` (Gemini). Nothing in the status code
/// or the error channel says "cut off", so a build that ignores the finish
/// reason shows half an answer and no error at all.
///
/// The owner is the Agent, not the provider: the ceiling is the `max_tokens`
/// this app sends. Being honest about that is the whole point — the user's
/// answer was truncated by our request, and the fix is a longer limit or a
/// shorter conversation.
pub fn output_capped(cap_tokens: u32) -> Diagnosis {
    Diagnosis {
        stage: Stage::Parse,
        owner: Owner::Agent,
        http_status: Some(200),
        cooldown: None,
        retry_after: None,
        summary: format!(
            "The answer stopped because it reached the {cap_tokens}-token output limit this Agent sent, not because the model finished or the provider failed. The text above is real but incomplete. Ask for the rest of it, or start a shorter chat so more of the window is left for the answer."
        ),
    }
}

pub fn invalid_response(detail: &str) -> Diagnosis {
    Diagnosis {
        stage: Stage::Parse,
        owner: Owner::Provider,
        http_status: None,
        cooldown: None,
        retry_after: None,
        summary: format!("A response arrived but was not the expected shape ({detail}). No answer was accepted."),
    }
}

pub fn oversized() -> Diagnosis {
    Diagnosis {
        stage: Stage::Bounds,
        owner: Owner::Agent,
        http_status: None,
        cooldown: None,
        retry_after: None,
        summary: "The Agent's safety bounds (2 MiB transport / 96,000 display characters) stopped this reply. This is our limit, not the provider's.".to_owned(),
    }
}

pub fn invalid_input() -> Diagnosis {
    Diagnosis {
        stage: Stage::Request,
        owner: Owner::Agent,
        http_status: None,
        cooldown: None,
        retry_after: None,
        summary: "The request was not sent: choose a valid model, a non-empty message and up to 4,000 characters.".to_owned(),
    }
}

/// Interprets a provider `Retry-After` header value in seconds.
pub fn retry_after(value: &str) -> Option<u64> {
    value.trim().parse::<u64>().ok().filter(|seconds| (1..=86_400).contains(seconds))
}

/// Duration formatter used by the Debug page and chat error lines.
pub fn human_duration(seconds: u64) -> String {
    if seconds < 60 { format!("{seconds} s") }
    else if seconds < 3600 { format!("{} min {} s", seconds / 60, seconds % 60).replace(" 0 s", "") }
    else { format!("{} h {} min", seconds / 3600, seconds % 3600 / 60).replace(" 0 min", "") }
}

/// The cooldown deadline in epoch seconds for a diagnosis starting now.
pub fn deadline(seconds: u64, now: u64) -> u64 {
    now.saturating_add(seconds)
}

/// Remaining seconds until a stored deadline (0 when already elapsed).
pub fn remaining(deadline: u64, now: u64) -> u64 {
    deadline.saturating_sub(now)
}

/// A 429 with `Retry-After` should honour the provider's window when it is
/// longer than our default, but never sleep for more than a day.
pub fn cooldown_for(status: u16, hint: Option<u64>) -> u64 {
    let base = if matches!(status, 408 | 429 | 500..=599) { KEY_COOLDOWN_SECS } else { KEY_COOLDOWN_SECS };
    hint.map_or(base, |seconds| base.max(seconds)).min(86_400)
}

impl Diagnosis {
    pub fn with_retry_after(mut self, hint: Option<u64>) -> Self {
        if let (Some(hint), Some(cooldown)) = (hint, self.cooldown) {
            self.retry_after = Some(hint);
            self.cooldown = Some(cooldown.max(hint));
        }
        self
    }

    /// Compact one-line form for the chat error notice.
    pub fn line(&self) -> String {
        match self.http_status {
            Some(status) => format!("{} · {} · {} ({}). {}", self.stage_label(), self.owner_label(), self.summary, status, String::new()).trim_end().to_owned(),
            None => format!("{} · {} · {}", self.stage_label(), self.owner_label(), self.summary),
        }
    }
}

/// Test-only helper: a timeout diagnosis for a request that may have billed.
pub fn timeout_is_ours() -> Duration {
    Duration::from_secs(REQUEST_TIMEOUT_SECS)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn retired_models_are_not_mistaken_for_auth_failures() {
        // Google retires model ids with a "not found" body; that is the model's
        // fault, not the key's, and the key must not be benched for it.
        let retired = from_http(404, Some("models/gemini-1.0-pro is not found for API version v1beta"));
        assert_eq!(retired.owner, Owner::Model);
        assert!(retired.retries_model());
        assert!(!retired.retries_key());
        let decommissioned = from_http(400, Some("This model has been decommissioned and is no longer available."));
        assert_eq!(decommissioned.owner, Owner::Model);
    }

    #[test]
    fn a_cut_off_answer_blames_our_own_output_cap_and_never_the_key() {
        // The 200 is real: the provider completed the request it was given. The
        // truncation is ours (the max_tokens we sent), so the key must not rest,
        // the model must not be disabled, and the summary must say both.
        let capped = output_capped(4096);
        assert_eq!(capped.owner, Owner::Agent);
        assert_eq!(capped.stage, Stage::Parse);
        assert_eq!(capped.http_status, Some(200));
        assert!(capped.cooldown.is_none(), "a cut-off answer must not bench a key");
        assert!(!capped.retries_key());
        assert!(!capped.retries_model());
        assert!(capped.summary.contains("4096-token output limit"));
        assert!(capped.summary.contains("not because the model finished or the provider failed"));
    }

    #[test]
    fn quota_and_auth_bench_the_key_and_rate_limits_rest_it() {
        for (status, message) in [
            (429, "You exceeded your current quota, please check your plan"),
            (401, "Incorrect API key provided"),
            (402, "Payment required: insufficient credits"),
            (403, "API key not valid. Please pass a valid API key."),
        ] {
            let diagnosis = from_http(status, Some(message));
            assert_eq!(diagnosis.owner, Owner::Key, "{status} {message}");
            assert!(diagnosis.retries_key());
            assert!(diagnosis.cooldown.is_some_and(|seconds| seconds >= 60));
        }
        assert_eq!(from_http(429, Some("Rate limit reached: 20 requests per minute")).owner, Owner::Key);
    }

    #[test]
    fn provider_side_failures_never_bench_a_key_or_model() {
        for (status, message) in [(500, "internal error"), (503, "The service is overloaded"), (529, "capacity")] {
            let diagnosis = from_http(status, Some(message));
            assert_eq!(diagnosis.owner, Owner::Provider, "{status}");
            assert!(!diagnosis.retries_key() && !diagnosis.retries_model());
        }
        assert_eq!(from_http(400, Some("This model's maximum context length is 8192 tokens")).owner, Owner::Provider);
    }

    #[test]
    fn our_timeout_is_reported_as_ours_and_keeps_the_billing_warning() {
        let diagnosis = transport(true);
        assert_eq!(diagnosis.stage, Stage::Transport);
        assert_eq!(diagnosis.owner, Owner::Agent);
        assert!(diagnosis.summary.contains("45 s"));
        assert!(diagnosis.summary.contains("may still be generating"));
        assert_eq!(timeout_is_ours(), Duration::from_secs(45));
        assert!(!transport(false).summary.contains("may still be generating"));
    }

    #[test]
    fn retry_after_widens_the_window_but_stays_bounded() {
        assert_eq!(retry_after("120"), Some(120));
        assert_eq!(retry_after(" 0 "), None);
        assert_eq!(retry_after("soon"), None);
        assert_eq!(retry_after("999999999"), None);
        assert_eq!(cooldown_for(429, Some(120)), 300);
        assert_eq!(cooldown_for(429, Some(900)), 900);
        assert_eq!(cooldown_for(429, Some(200_000)), 86_400);
        let diagnosis = from_http(429, Some("rate limit")).with_retry_after(Some(600));
        assert_eq!(diagnosis.cooldown, Some(600));
        assert_eq!(diagnosis.retry_after, Some(600));
    }

    #[test]
    fn deadlines_and_durations_read_naturally() {
        assert_eq!(human_duration(45), "45 s");
        assert_eq!(human_duration(300), "5 min");
        assert_eq!(human_duration(3_900), "1 h 5 min");
        let now = 1_000;
        assert_eq!(remaining(deadline(300, now), now + 120), 180);
        assert_eq!(remaining(deadline(300, now), now + 400), 0);
    }
}
