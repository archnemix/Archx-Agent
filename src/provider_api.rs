//! Purpose: Sends only explicitly requested plain-text chat to fixed provider HTTPS origins.
use std::time::Duration;

use reqwest::{redirect, Client};
use serde_json::{json, Value};
use zeroize::Zeroizing;

use crate::credentials::Provider;

const MAX_REPLY_BYTES: usize = 64 * 1024;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Turn {
    pub role: &'static str,
    pub content: String,
}

// Do not surface provider bodies or reqwest errors: either can echo a key,
// prompt, proxy hostname, account metadata or private data.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CallError {
    InvalidInput,
    Transport,
    Rejected(u16),
    Oversized,
    InvalidResponse,
}

impl CallError {
    pub fn message(self) -> String {
        match self {
            Self::InvalidInput => "Choose a valid model and enter a short message (up to 4,000 characters).".into(),
            Self::Transport => "Could not reach the provider securely. Check your network and try again.".into(),
            Self::Rejected(code) => format!("Provider returned HTTP {code}. Check the selected model, key and account; no automatic retry occurred."),
            Self::Oversized => "Provider response exceeded the local size limit.".into(),
            Self::InvalidResponse => "The provider returned no supported plain-text reply.".into(),
        }
    }
}

pub fn valid_model(provider: Provider, model: &str) -> bool {
    !model.is_empty() && model.len() <= 100 && !model.starts_with('/') &&
        !model.contains("//") && !model.contains("..") && !model.contains("://") &&
        model.bytes().all(|b| b.is_ascii_alphanumeric() || matches!(b, b'/' | b'-' | b'_' | b'.' | b':' | b'+')) &&
        (provider != Provider::Gemini || !model.contains('/'))
}

fn endpoint(provider: Provider, model: &str) -> String {
    match provider {
        Provider::OpenRouter => "https://openrouter.ai/api/v1/chat/completions".into(),
        Provider::Grok => "https://api.x.ai/v1/chat/completions".into(),
        Provider::Gemini => format!("https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"),
    }
}

fn payload(provider: Provider, model: &str, turns: &[Turn]) -> Value {
    if provider == Provider::Gemini {
        json!({"contents": turns.iter().map(|turn| json!({"role": if turn.role == "assistant" { "model" } else { "user" }, "parts": [{"text": turn.content}]})).collect::<Vec<_>>(),
            "generationConfig": {"maxOutputTokens": 256}})
    } else {
        let mut body = json!({"model": model, "messages": turns.iter().map(|turn| json!({"role": turn.role, "content": turn.content})).collect::<Vec<_>>(),
            "max_tokens": 256, "stream": false});
        if provider == Provider::OpenRouter {
            body["provider"] = json!({"allow_fallbacks": false});
        }
        body
    }
}

pub async fn send(provider: Provider, model: String, key: Zeroizing<String>, turns: Vec<Turn>) -> Result<String, CallError> {
    if !valid_model(provider, &model) || turns.is_empty() || turns.len() > 12 ||
        turns.last().is_none_or(|turn| turn.role != "user") ||
        turns.iter().any(|turn| !matches!(turn.role, "user" | "assistant") || turn.content.is_empty() || turn.content.chars().count() > 4000) {
        return Err(CallError::InvalidInput);
    }
    let client = Client::builder()
        .https_only(true)
        .no_proxy()
        .redirect(redirect::Policy::none())
        .timeout(Duration::from_secs(45))
        .build().map_err(|_| CallError::Transport)?;
    let url = endpoint(provider, &model);
    let request = client.post(url).json(&payload(provider, &model, &turns));
    let request = match provider {
        Provider::Gemini => request.header("x-goog-api-key", key.as_str()),
        _ => request.bearer_auth(key.as_str()),
    };
    let mut response = request.send().await.map_err(|_| CallError::Transport)?;
    let status = response.status();
    if !status.is_success() { return Err(CallError::Rejected(status.as_u16())); }
    let mut bytes = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|_| CallError::Transport)? {
        if bytes.len() + chunk.len() > MAX_REPLY_BYTES { return Err(CallError::Oversized); }
        bytes.extend_from_slice(&chunk);
    }
    let body: Value = serde_json::from_slice(&bytes).map_err(|_| CallError::InvalidResponse)?;
    let answer = if provider == Provider::Gemini {
        body.pointer("/candidates/0/content/parts/0/text")
    } else {
        body.pointer("/choices/0/message/content")
    }.and_then(Value::as_str).filter(|text| !text.trim().is_empty()).ok_or(CallError::InvalidResponse)?;
    Ok(answer.chars().take(16000).collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn endpoints_are_fixed_and_model_paths_are_constrained() {
        assert!(valid_model(Provider::OpenRouter, "vendor/model:free"));
        assert!(!valid_model(Provider::Gemini, "../other/model"));
        assert!(!valid_model(Provider::OpenRouter, "https://example.com"));
        assert_eq!(endpoint(Provider::Grok, "any"), "https://api.x.ai/v1/chat/completions");
        assert_eq!(endpoint(Provider::Gemini, "gemini-test"), "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent");
    }

    #[test]
    fn payload_sends_no_tools_and_no_free_to_paid_fallback() {
        let turns = [Turn { role: "user", content: "synthetic".into() }];
        let open = payload(Provider::OpenRouter, "vendor/model:free", &turns);
        assert_eq!(open["model"], "vendor/model:free");
        assert_eq!(open["provider"]["allow_fallbacks"], false);
        assert!(open.get("tools").is_none());
        let gemini = payload(Provider::Gemini, "gemini-test", &turns);
        assert_eq!(gemini["contents"][0]["parts"][0]["text"], "synthetic");
    }
}
