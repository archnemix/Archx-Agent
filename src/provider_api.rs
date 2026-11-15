//! Purpose: Sends bounded chat requests to fixed HTTPS providers and parses structured replies.
use std::time::Duration;

use reqwest::{redirect, Client};
use sipper::Sender;
use serde_json::{json, Value};
use zeroize::Zeroizing;

use crate::credentials::Provider;

const MAX_REPLY_BYTES: usize = 64 * 1024;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Turn {
    pub role: &'static str,
    pub content: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Default)]
pub struct Reply {
    pub content: String,
    pub reasoning: Option<String>,
}

fn extract_reply(provider: Provider, body: &Value) -> Result<Reply, CallError> {
    let (content, reasoning) = if provider == Provider::Gemini {
        let parts = body.pointer("/candidates/0/content/parts").and_then(Value::as_array)
            .ok_or(CallError::InvalidResponse)?;
        let mut text = String::new();
        let mut thought = String::new();
        for part in parts {
            if let Some(value) = part.get("text").and_then(Value::as_str) {
                if part.get("thought").and_then(Value::as_bool) == Some(true) { thought.push_str(value); }
                else { text.push_str(value); }
            }
        }
        (text, thought)
    } else {
        let message = body.pointer("/choices/0/message").ok_or(CallError::InvalidResponse)?;
        let text = message.get("content").and_then(Value::as_str).unwrap_or_default().to_owned();
        let thought = message.get("reasoning_content").or_else(|| message.get("reasoning"))
            .and_then(Value::as_str).unwrap_or_default().to_owned();
        (text, thought)
    };
    if content.trim().is_empty() { return Err(CallError::InvalidResponse); }
    Ok(Reply {
        content: content.chars().take(16000).collect(),
        reasoning: (!reasoning.trim().is_empty()).then(|| reasoning.chars().take(16000).collect()),
    })
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
            Self::Transport => "The secure request failed or timed out. The provider may already have received it; retry only if you accept possible duplicate billing.".into(),
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

pub async fn send(provider: Provider, model: String, key: Zeroizing<String>, turns: Vec<Turn>) -> Result<Reply, CallError> {
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
    extract_reply(provider, &body)
}

// SSE frames are parsed only after a newline; partial UTF-8 bytes remain buffered.
fn stream_delta(provider: Provider, body: &Value, reply: &mut Reply) {
    if provider == Provider::Gemini {
        if let Some(parts) = body.pointer("/candidates/0/content/parts").and_then(Value::as_array) {
            for part in parts {
                if let Some(text) = part.get("text").and_then(Value::as_str) {
                    if part["thought"].as_bool() == Some(true) {
                        reply.reasoning.get_or_insert_with(String::new).push_str(text);
                    } else { reply.content.push_str(text); }
                }
            }
        }
    } else {
        let delta = &body["choices"][0]["delta"];
        if let Some(text) = delta["content"].as_str() { reply.content.push_str(text); }
        if let Some(text) = delta["reasoning_content"].as_str().or_else(|| delta["reasoning"].as_str()) {
            reply.reasoning.get_or_insert_with(String::new).push_str(text);
        }
    }
}

pub async fn send_stream(provider: Provider, model: String, key: Zeroizing<String>, turns: Vec<Turn>, progress: &mut Sender<Reply>) -> Result<Reply, CallError> {
    if !valid_model(provider, &model) || turns.is_empty() || turns.len() > 12 ||
        turns.last().is_none_or(|turn| turn.role != "user") ||
        turns.iter().any(|turn| !matches!(turn.role, "user" | "assistant") || turn.content.is_empty() || turn.content.chars().count() > 4000) {
        return Err(CallError::InvalidInput);
    }
    let client = Client::builder().https_only(true).no_proxy().redirect(redirect::Policy::none())
        .timeout(Duration::from_secs(45)).build().map_err(|_| CallError::Transport)?;
    let url = if provider == Provider::Gemini {
        format!("https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse")
    } else { endpoint(provider, &model) };
    let mut body = payload(provider, &model, &turns);
    if provider != Provider::Gemini { body["stream"] = Value::Bool(true); }
    let request = client.post(url).json(&body);
    let request = if provider == Provider::Gemini { request.header("x-goog-api-key", key.as_str()) }
        else { request.bearer_auth(key.as_str()) };
    let mut response = request.send().await.map_err(|_| CallError::Transport)?;
    if !response.status().is_success() { return Err(CallError::Rejected(response.status().as_u16())); }
    let mut pending = Vec::<u8>::new();
    let mut read = 0usize;
    let mut reply = Reply::default();
    let mut done = false;
    let mut gemini_finished = false;
    while let Some(chunk) = response.chunk().await.map_err(|_| CallError::Transport)? {
        read = read.saturating_add(chunk.len());
        if read > MAX_REPLY_BYTES { return Err(CallError::Oversized); }
        pending.extend_from_slice(&chunk);
        while let Some(end) = pending.iter().position(|b| *b == b'\n') {
            let line = pending.drain(..=end).collect::<Vec<u8>>();
            let line = std::str::from_utf8(&line).map_err(|_| CallError::InvalidResponse)?.trim();
            let Some(data) = line.strip_prefix("data:") else { continue; };
            let data = data.trim();
            if data == "[DONE]" { done = true; break; }
            let frame: Value = serde_json::from_str(data).map_err(|_| CallError::InvalidResponse)?;
            if frame.get("error").is_some() || matches!(frame["type"].as_str(), Some("response.failed" | "response.incomplete")) {
                return Err(CallError::InvalidResponse);
            }
            if provider == Provider::Gemini && frame["candidates"][0].get("finishReason").is_some() {
                gemini_finished = matches!(frame["candidates"][0]["finishReason"].as_str(), Some("STOP" | "MAX_TOKENS"));
                if !gemini_finished { return Err(CallError::InvalidResponse); }
            }
            stream_delta(provider, &frame, &mut reply);
            if reply.content.chars().count() > 16000 || reply.reasoning.as_ref().is_some_and(|r| r.chars().count() > 16000) {
                return Err(CallError::Oversized);
            }
            progress.send(reply.clone()).await;
        }
        if done { break; }
    }
    if reply.content.trim().is_empty() || (!done && provider != Provider::Gemini) || (provider == Provider::Gemini && !gemini_finished) { return Err(CallError::InvalidResponse); }
    Ok(reply)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stream_delta_tracks_returned_reasoning_without_guessing() {
        let mut reply = Reply::default();
        stream_delta(Provider::OpenRouter, &json!({"choices":[{"delta":{"reasoning":"Why"}}]}), &mut reply);
        stream_delta(Provider::OpenRouter, &json!({"choices":[{"delta":{"content":"Answer"}}]}), &mut reply);
        assert_eq!(reply.reasoning.as_deref(), Some("Why"));
        assert_eq!(reply.content, "Answer");
        let mut plain = Reply::default();
        stream_delta(Provider::Gemini, &json!({"candidates":[{"content":{"parts":[{"text":"Plain"}]}}]}), &mut plain);
        assert_eq!(plain.reasoning, None);
    }

    #[test]
    fn reasoning_is_only_shown_when_returned_separately() {
        let plain = extract_reply(Provider::OpenRouter, &json!({"choices":[{"message":{"content":"Hello"}}]})).unwrap();
        assert_eq!(plain.reasoning, None);
        let reasoned = extract_reply(Provider::Grok, &json!({"choices":[{"message":{"content":"Answer","reasoning_content":"Steps"}}]})).unwrap();
        assert_eq!(reasoned.reasoning.as_deref(), Some("Steps"));
        let gemini = extract_reply(Provider::Gemini, &json!({"candidates":[{"content":{"parts":[{"thought":true,"text":"Why"},{"text":"Final"}]}}]})).unwrap();
        assert_eq!(gemini.content, "Final");
        assert_eq!(gemini.reasoning.as_deref(), Some("Why"));
    }

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
