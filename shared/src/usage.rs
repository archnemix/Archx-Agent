//! Purpose: Reads what a provider will say about a key's remaining usage, and states plainly where it will say nothing.
//!
//! The honest position, taken from each provider's own documentation:
//!
//! | Provider | Available to a normal model key? | What we can show |
//! | --- | --- | --- |
//! | OpenRouter | Yes — `GET /api/v1/key` documents the key's cap, spend and free-model allowance | cap, spend, remaining, free-model requests/day |
//! | xAI (Grok), Gemini, OpenAI-compatible | No such endpoint for a model key | nothing; the panel says so |
//!
//! Two rules this module never breaks:
//!
//! * **Account balance needs a different credential.** OpenRouter's account
//!   balance is `GET /api/v1/credits`, which a normal model key cannot read
//!   (it needs a management key). We do not ask for one and never label a
//!   per-key cap as "balance".
//! * **A failed read is not a zero.** An error, a missing field or an unknown
//!   shape returns `Err`/`None`, and the UI shows "not available", never "0".
//!   The key itself is never logged, stored or shown by this path.

use std::time::Duration;

use reqwest::{redirect, Client};
use serde_json::Value;
use zeroize::Zeroizing;

use crate::credentials::Provider;

/// Our own limit for this read. It is a status call, not a generation, so it is
/// shorter than a chat request.
pub const USAGE_TIMEOUT_SECS: u64 = 20;

/// Where a provider publishes key usage, if it does at all.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UsageSource {
    /// `GET https://openrouter.ai/api/v1/key` with a normal key.
    OpenRouterKey,
    /// The provider documents no endpoint a model key can call.
    NotPublished,
}

impl UsageSource {
    pub fn for_provider(provider: Provider) -> Self {
        match provider {
            Provider::OpenRouter => Self::OpenRouterKey,
            // Every other provider authenticates a model key for inference
            // only. None of them documents a usage read for that same key, so we
            // do not invent one or try a guess at a URL. Gemini in particular
            // reports quota on *errors* only, which is not a usage read.
            Provider::Grok | Provider::Gemini | Provider::OpenAI | Provider::Anthropic
            | Provider::Groq | Provider::Zai | Provider::OllamaLocal | Provider::OllamaCloud
            | Provider::Custom => Self::NotPublished,
        }
    }

    /// One line the UI can print without hedging.
    pub fn explanation(self) -> &'static str {
        match self {
            Self::OpenRouterKey =>
                "OpenRouter publishes a key's own limit, spend and remaining credit at GET /api/v1/key, so these figures are provider facts, not estimates.",
            Self::NotPublished =>
                "This provider documents no usage or balance endpoint a model key can call. The Agent will not guess one or show a number it cannot source. Account balance, where it exists, needs that provider's billing page.",
        }
    }
}

/// What one key reports about itself. Every field is optional: a missing field
/// means "the provider did not say", never "zero".
#[derive(Debug, Clone, Default, PartialEq)]
pub struct KeyUsage {
    pub label: Option<String>,
    /// The key's own spending cap, in USD, when the provider sets one.
    pub limit: Option<f64>,
    pub remaining: Option<f64>,
    pub usage: Option<f64>,
    pub usage_daily: Option<f64>,
    /// Free-model requests used and allowed today, for a free-tier account.
    pub free_requests_used: Option<u64>,
    pub free_requests_limit: Option<u64>,
    /// Provider's own statement that this is a free-tier account.
    pub free_tier: Option<bool>,
}

impl KeyUsage {
    pub fn is_empty(&self) -> bool {
        self.label.is_none() && self.limit.is_none() && self.remaining.is_none() && self.usage.is_none()
            && self.free_requests_used.is_none() && self.free_requests_limit.is_none()
    }

    /// One compact, sourced line for the row. Empty when there is nothing to say.
    pub fn line(&self) -> String {
        let mut parts = Vec::new();
        match (self.usage, self.limit) {
            (Some(used), Some(limit)) => {
                parts.push(format!("${used:.2} of ${limit:.2} cap used"));
                if let Some(remaining) = self.remaining { parts.push(format!("${remaining:.2} left on this key")); }
            }
            (Some(used), None) if used > 0.0 => parts.push(format!("${used:.2} spent on this key")),
            (_, Some(limit)) => parts.push(format!("${limit:.2} cap on this key")),
            _ => {}
        }
        if let (Some(used), Some(limit)) = (self.free_requests_used, self.free_requests_limit) {
            parts.push(format!("{used} / {limit} free requests today"));
        }
        if parts.is_empty() { return String::new(); }
        format!("{}  ·  openrouter", parts.join("  ·  "))
    }

    /// What a balance-style headline should say, or why it says nothing.
    ///
    /// Order matters. A credit cap is the most specific claim a provider makes
    /// about a key, so it wins. A free-tier account's daily allowance is next,
    /// because a free account usually reports `usage: 0` and "spent $0.00"
    /// would hide the quota that actually limits it.
    pub fn headline(&self) -> String {
        if let Some(limit) = self.limit {
            let left = self.remaining.unwrap_or_else(|| (limit - self.usage.unwrap_or(0.0)).max(0.0));
            return format!("${left:.2} left of this key's ${limit:.2} cap");
        }
        if let (Some(used), Some(limit)) = (self.free_requests_used, self.free_requests_limit) {
            return format!("{} of {limit} free-model requests used today", used);
        }
        if let Some(used) = self.usage {
            return format!("${used:.2} spent on this key · no per-key cap set");
        }
        if let Some(true) = self.free_tier {
            return "A free-tier account; the provider did not report a remaining count.".to_owned();
        }
        "The provider returned no usage figures for this key.".to_owned()
    }
}

/// Parses the documented `GET /api/v1/key` envelope: `{ "data": { … } }`.
///
/// Tolerant by design: an unknown or renamed field yields `None` for that field
/// rather than failing the whole read, and a document with no recognisable
/// field yields an empty `KeyUsage` so the caller can say "not available".
pub fn parse_openrouter_key(body: &Value) -> KeyUsage {
    let data = body.get("data").filter(|value| value.is_object()).unwrap_or(body);
    let number = |key: &str| data.get(key).and_then(Value::as_f64);
    let count = |key: &str| data.get(key).and_then(Value::as_u64);
    KeyUsage {
        label: data.get("label").and_then(Value::as_str).map(str::to_owned),
        limit: number("limit"),
        remaining: number("limit_remaining"),
        usage: number("usage"),
        usage_daily: number("usage_daily"),
        free_requests_used: data.pointer("/free_model_daily_requests/used").and_then(Value::as_u64),
        free_requests_limit: data.pointer("/free_model_daily_requests/limit").and_then(Value::as_u64),
        free_tier: data.get("is_free_tier").and_then(Value::as_bool),
    }
}

/// Reads the key's usage from the provider, using the key already in the vault.
///
/// Read-only: one GET to a fixed origin, no redirects, no proxy, bounded time,
/// no body sent, and the key is only ever placed in the `Authorization` header.
/// A provider with no published endpoint returns `Err` with the reason instead
/// of making a speculative request.
pub async fn fetch_key_usage(provider: Provider, key: Zeroizing<String>) -> Result<KeyUsage, String> {
    let source = UsageSource::for_provider(provider);
    if source == UsageSource::NotPublished {
        return Err(source.explanation().to_owned());
    }
    let client = Client::builder().https_only(true).no_proxy()
        .redirect(redirect::Policy::none())
        .timeout(Duration::from_secs(USAGE_TIMEOUT_SECS))
        .build().map_err(|_| "Could not create the HTTPS client.".to_owned())?;
    let response = client.get("https://openrouter.ai/api/v1/key")
        .header("authorization", format!("Bearer {}", key.as_str()))
        .send().await
        .map_err(|_| format!("No usage answer within {USAGE_TIMEOUT_SECS} s. That is our limit, not a provider quota."))?;
    let status = response.status();
    if status == reqwest::StatusCode::UNAUTHORIZED || status == reqwest::StatusCode::FORBIDDEN {
        return Err("The provider rejected this key for a usage read. It is not a sign the key cannot generate; a management key may be needed for this endpoint.".to_owned());
    }
    if !status.is_success() {
        return Err(format!("Usage read returned HTTP {}. No figures were shown rather than guessed.", status.as_u16()));
    }
    let bytes = response.bytes().await.map_err(|_| "The usage response was interrupted.".to_owned())?;
    if bytes.len() > 256 * 1024 { return Err("The usage response was unreasonably large; nothing was shown.".to_owned()); }
    let body: Value = serde_json::from_slice(&bytes)
        .map_err(|_| "The usage endpoint returned an unexpected document; nothing was shown.".to_owned())?;
    let usage = parse_openrouter_key(&body);
    if usage.is_empty() { return Err("The provider answered but named no field this build understands. No figures were guessed.".to_owned()); }
    Ok(usage)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn only_openrouter_claims_a_published_endpoint() {
        assert_eq!(UsageSource::for_provider(Provider::OpenRouter), UsageSource::OpenRouterKey);
        for provider in Provider::ALL.into_iter().filter(|provider| *provider != Provider::OpenRouter) {
            assert_eq!(UsageSource::for_provider(provider), UsageSource::NotPublished,
                "{:?} must not claim an endpoint it does not document", provider);
            assert!(UsageSource::for_provider(provider).explanation().contains("will not guess"));
        }
    }

    #[test]
    fn a_capped_key_reports_cap_spend_and_remainder() {
        let body = json!({"data": {
            "label": "lab key", "limit": 10.0, "limit_remaining": 4.25,
            "usage": 5.75, "usage_daily": 1.0, "is_free_tier": false
        }});
        let usage = parse_openrouter_key(&body);
        assert_eq!(usage.limit, Some(10.0));
        assert_eq!(usage.headline(), "$4.25 left of this key's $10.00 cap");
        assert!(usage.line().ends_with("openrouter"), "the row is source-labelled");
        assert!(usage.line().contains("$5.75 of $10.00 cap used"));
    }

    #[test]
    fn a_free_account_reports_its_daily_allowance() {
        let body = json!({"data": {
            "usage": 0.0, "is_free_tier": true,
            "free_model_daily_requests": {"used": 12, "limit": 50}
        }});
        let usage = parse_openrouter_key(&body);
        assert_eq!(usage.free_requests_used, Some(12));
        assert_eq!(usage.free_requests_limit, Some(50));
        assert!(usage.headline().contains("12 of 50 free-model requests"));
        assert!(usage.line().contains("12 / 50 free requests today"));
    }

    #[test]
    fn a_cap_beats_a_free_allowance_which_beats_plain_spend() {
        let capped = parse_openrouter_key(&json!({"data": {"limit": 5.0, "limit_remaining": 2.0,
            "usage": 3.0, "free_model_daily_requests": {"used": 1, "limit": 50}}}));
        assert!(capped.headline().starts_with("$2.00 left of this key's $5.00 cap"));
        let free_only = parse_openrouter_key(&json!({"data": {"usage": 0.0, "is_free_tier": true,
            "free_model_daily_requests": {"used": 7, "limit": 50}}}));
        assert_eq!(free_only.headline(), "7 of 50 free-model requests used today");
        let tier_only = parse_openrouter_key(&json!({"data": {"is_free_tier": true}}));
        assert!(tier_only.headline().contains("did not report a remaining count"));
    }

    #[test]
    fn a_renamed_or_absent_field_is_not_reported_as_zero() {
        // Unknown shape: nothing is claimed, so the caller shows "not available".
        let usage = parse_openrouter_key(&json!({"data": {"something_new": 7}}));
        assert!(usage.is_empty(), "{usage:?}");
        assert_eq!(usage.headline(), "The provider returned no usage figures for this key.");
        // A bare `{"data": null}` must not panic or invent numbers.
        assert!(parse_openrouter_key(&json!({"data": null})).is_empty());
        assert!(parse_openrouter_key(&json!([])).is_empty());
    }

    #[test]
    fn zero_spend_is_shown_as_zero_and_not_as_missing() {
        let usage = parse_openrouter_key(&json!({"data": {"usage": 0.0}}));
        assert_eq!(usage.usage, Some(0.0));
        assert_eq!(usage.headline(), "$0.00 spent on this key · no per-key cap set");
    }
}
