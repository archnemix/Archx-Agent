//! Purpose: Sends bounded chat requests to fixed HTTPS providers and returns structured replies or a classified failure.
use std::time::{Duration, Instant};

use reqwest::{redirect, Client};
use sipper::Sender;
use serde_json::{json, Value};
use zeroize::Zeroizing;

use crate::credentials::Provider;
use crate::diagnostics::{self, Diagnosis, Stage};

// Bound transport bytes separately from visible text. SSE framing and escaped
// JSON can be much larger than the rendered answer, even for normal replies.
const MAX_REPLY_BYTES: usize = 2 * 1024 * 1024;
const MAX_VISIBLE_CHARS: usize = 96 * 1024;
/// The provider's own explanation is kept short and displayed, never trusted.
const MAX_PROVIDER_MESSAGE: usize = 280;

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

/// Transport-level detail used by the Debug page. Never holds a key or header.
#[derive(Clone, Debug, PartialEq, Eq, Default)]
pub struct Trace {
    pub status: Option<u16>,
    pub duration_ms: u128,
    pub request_bytes: usize,
    pub response_bytes: usize,
    /// Redacted excerpt of the provider's own message.
    pub provider_message: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Failure {
    pub diagnosis: Diagnosis,
    pub trace: Trace,
    /// True when a request may already have been accepted by the provider.
    pub may_have_billed: bool,
}

impl Failure {
    pub fn message(&self) -> String {
        self.diagnosis.summary.clone()
    }
}

// Kept for call sites that only need the coarse category (retry policy, tests).
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
        to_diagnosis(self, None).summary
    }
}

/// Maps a coarse error to the same diagnosis the UI displays.
pub fn to_diagnosis(error: CallError, provider_message: Option<&str>) -> Diagnosis {
    match error {
        CallError::InvalidInput => diagnostics::invalid_input(),
        CallError::Transport => diagnostics::transport(true),
        CallError::Rejected(status) => diagnostics::from_http(status, provider_message),
        CallError::Oversized => diagnostics::oversized(),
        CallError::InvalidResponse => diagnostics::invalid_response(provider_message.unwrap_or("the body did not match the expected fields")),
    }
}

impl From<CallError> for Failure {
    fn from(error: CallError) -> Self {
        Self { diagnosis: to_diagnosis(error, None), trace: Trace::default(), may_have_billed: error == CallError::Transport }
    }
}

impl From<Failure> for CallError {
    fn from(failure: Failure) -> Self {
        match (failure.diagnosis.stage, failure.diagnosis.http_status) {
            (Stage::Request, _) => CallError::InvalidInput,
            (Stage::Transport, _) => CallError::Transport,
            (Stage::Http, Some(status)) => CallError::Rejected(status),
            // An HTTP-stage failure always carries the status when it came from a
            // real response; without one there is no body to trust either.
            (Stage::Http, None) => CallError::InvalidResponse,
            (Stage::Bounds, _) => CallError::Oversized,
            (Stage::Parse, _) => CallError::InvalidResponse,
        }
    }
}

/// Reads a bounded provider message excerpt from a JSON error body.
fn provider_message(body: &Value) -> String {
    let candidates = [
        body.pointer("/error/message"), body.pointer("/error"), body.get("message"),
        body.pointer("/error/details/0/message"), body.get("detail"), body.get("msg"),
    ];
    for candidate in candidates.into_iter().flatten() {
        let text = match candidate {
            Value::String(text) => text.clone(),
            Value::Object(_) | Value::Array(_) => candidate.to_string(),
            _ => continue,
        };
        let text = crate::debug_log::redact(text.trim());
        if !text.is_empty() {
            return text.chars().take(MAX_PROVIDER_MESSAGE).collect::<String>();
        }
    }
    String::new()
}

/// Builds a failure for a non-2xx answer, honouring `Retry-After`.
fn http_failure(status: u16, body: &[u8], retry_after: Option<u64>, trace: Trace) -> Failure {
    let text = String::from_utf8_lossy(body);
    let parsed: Option<Value> = serde_json::from_str(&text).ok();
    let message = parsed.as_ref().map(provider_message).filter(|message| !message.is_empty())
        .unwrap_or_else(|| crate::debug_log::redact(&text.chars().take(MAX_PROVIDER_MESSAGE).collect::<String>()));
    let diagnosis = diagnostics::from_http(status, Some(&message)).with_retry_after(retry_after);
    Failure {
        diagnosis,
        trace: Trace { status: Some(status), provider_message: message, ..trace },
        may_have_billed: true,
    }
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
    } else if provider == Provider::Anthropic {
        let parts = body.get("content").and_then(Value::as_array).ok_or(CallError::InvalidResponse)?;
        let text = parts.iter().filter(|part| part["type"] == "text")
            .filter_map(|part| part["text"].as_str()).collect::<String>();
        let thinking = parts.iter().filter(|part| part["type"] == "thinking")
            .filter_map(|part| part["thinking"].as_str()).collect::<String>();
        (text, thinking)
    } else {
        let message = body.pointer("/choices/0/message").ok_or(CallError::InvalidResponse)?;
        let text = message.get("content").and_then(Value::as_str).unwrap_or_default().to_owned();
        let thought = message.get("reasoning_content").or_else(|| message.get("reasoning"))
            .and_then(Value::as_str).unwrap_or_default().to_owned();
        (text, thought)
    };
    if content.trim().is_empty() { return Err(CallError::InvalidResponse); }
    if content.chars().count() > MAX_VISIBLE_CHARS || reasoning.chars().count() > MAX_VISIBLE_CHARS { return Err(CallError::Oversized); }
    Ok(Reply {
        content,
        reasoning: (!reasoning.trim().is_empty()).then_some(reasoning),
    })
}

pub fn valid_model(provider: Provider, model: &str) -> bool {
    !model.is_empty() && model.len() <= 100 && !model.starts_with('/') &&
        !model.contains("//") && !model.contains("..") && !model.contains("://") &&
        model.bytes().all(|b| b.is_ascii_alphanumeric() || matches!(b, b'/' | b'-' | b'_' | b'.' | b':' | b'+')) &&
        (provider != Provider::Gemini || !model.contains('/'))
}

/// The documented chat URL with the model substituted in.
fn endpoint(provider: Provider, model: &str) -> String {
    crate::endpoints::default_template(provider).chat.replace("{model}", model)
}

/// Where this provider's chat requests go, for display in Settings and Debug.
pub fn endpoint_for(provider: Provider, model: Option<&str>) -> Option<String> {
    if provider == Provider::Custom { return None; }
    Some(endpoint(provider, model.unwrap_or("{model}")))
}

fn payload(provider: Provider, model: &str, turns: &[Turn], max_output_tokens: u32) -> Value {
    if provider == Provider::Gemini {
        json!({"contents": turns.iter().map(|turn| json!({"role": if turn.role == "assistant" { "model" } else { "user" }, "parts": [{"text": turn.content}]})).collect::<Vec<_>>(),
            "generationConfig": {"maxOutputTokens": max_output_tokens}})
    } else if provider == Provider::Anthropic {
        json!({"model": model, "max_tokens": max_output_tokens,
            "messages": turns.iter().map(|turn| json!({"role": turn.role, "content": turn.content})).collect::<Vec<_>>()})
    } else {
        let mut body = json!({"model": model, "messages": turns.iter().map(|turn| json!({"role": turn.role, "content": turn.content})).collect::<Vec<_>>(),
            "max_tokens": max_output_tokens, "stream": false});
        if provider == Provider::OpenRouter {
            body["provider"] = json!({"allow_fallbacks": false});
        }
        body
    }
}

fn validate(provider: Provider, model: &str, turns: &[Turn], max_output_tokens: u32) -> Result<(), Failure> {
    if !valid_model(provider, model) || turns.is_empty() || turns.len() > 12 ||
        turns.last().is_none_or(|turn| turn.role != "user") ||
        turns.iter().any(|turn| !matches!(turn.role, "user" | "assistant") || turn.content.is_empty() || turn.content.chars().count() > if turn.role == "user" { 4000 } else { MAX_VISIBLE_CHARS }) {
        return Err(Failure::from(CallError::InvalidInput));
    }
    if !(1..=8192).contains(&max_output_tokens) { return Err(Failure::from(CallError::InvalidInput)); }
    Ok(())
}

/// How many bytes the encoded request body will take, for the Debug page.
pub fn request_size(provider: Provider, model: &str, turns: &[Turn], max_output_tokens: u32) -> usize {
    payload(provider, model, turns, max_output_tokens).to_string().len()
}

/// Sends one chat request using the provider's **current** endpoints (the
/// user-editable registry wins over the documented default).
pub async fn send_via(provider: Provider, model: String, key: Zeroizing<String>, turns: Vec<Turn>, max_output_tokens: u32,
    endpoints: &crate::endpoints::Registry) -> Result<(Reply, Trace), Failure> {
    validate(provider, &model, &turns, max_output_tokens)?;
    let started = Instant::now();
    let body = payload(provider, &model, &turns, max_output_tokens);
    let request_bytes = body.to_string().len();
    let client = Client::builder()
        .https_only(provider != Provider::OllamaLocal)
        .no_proxy()
        .redirect(redirect::Policy::none())
        .timeout(Duration::from_secs(diagnostics::REQUEST_TIMEOUT_SECS))
        .build().map_err(|_| Failure::from(CallError::Transport))?;
    let url = endpoints.resolve(provider, crate::endpoints::Kind::Chat, &model);
    let request = client.post(url).json(&body);
    let request = match provider {
        Provider::Gemini => request.header("x-goog-api-key", key.as_str()),
        Provider::Anthropic => request.header("x-api-key", key.as_str())
            .header("anthropic-version", "2023-06-01"),
        Provider::OllamaLocal => request,
        _ => request.bearer_auth(key.as_str()),
    };
    let response = request.send().await.map_err(|_| Failure { diagnosis: diagnostics::transport(true), trace: Trace { request_bytes, ..Trace::default() }, may_have_billed: true })?;
    let status = response.status().as_u16();
    let retry_after = response.headers().get("retry-after").and_then(|value| value.to_str().ok())
        .and_then(diagnostics::retry_after);
    let mut bytes = Vec::new();
    let mut response_ok = response;
    loop {
        match response_ok.chunk().await {
            Ok(Some(chunk)) => {
                if bytes.len() + chunk.len() > MAX_REPLY_BYTES {
                    return Err(Failure {
                        diagnosis: diagnostics::oversized(),
                        trace: Trace { status: Some(status), duration_ms: started.elapsed().as_millis(), request_bytes, response_bytes: bytes.len(), provider_message: String::new() },
                        may_have_billed: true,
                    });
                }
                bytes.extend_from_slice(&chunk);
            }
            Ok(None) => break,
            Err(_) => {
                // A body truncated mid-stream: the status line may already have been 2xx.
                let trace = Trace { status: Some(status), duration_ms: started.elapsed().as_millis(), request_bytes, response_bytes: bytes.len(), provider_message: String::new() };
                if status >= 400 { return Err(http_failure(status, &bytes, retry_after, trace)); }
                return Err(Failure { diagnosis: diagnostics::transport(true), trace, may_have_billed: true });
            }
        }
    }
    let trace = Trace { status: Some(status), duration_ms: started.elapsed().as_millis(), request_bytes, response_bytes: bytes.len(), provider_message: String::new() };
    if status >= 400 { return Err(http_failure(status, &bytes, retry_after, trace)); }
    let body: Value = match serde_json::from_slice(&bytes) {
        Ok(body) => body,
        Err(_) => return Err(Failure {
            diagnosis: diagnostics::invalid_response("the response was not JSON"),
            trace: Trace { provider_message: crate::debug_log::redact(&String::from_utf8_lossy(&bytes).chars().take(MAX_PROVIDER_MESSAGE).collect::<String>()), ..trace },
            may_have_billed: true,
        }),
    };
    let reply = extract_reply(provider, &body).map_err(|error| {
        let message = provider_message(&body);
        Failure {
            diagnosis: to_diagnosis(error, (!message.is_empty()).then_some(message.as_str())),
            trace: Trace { provider_message: message, ..trace.clone() },
            may_have_billed: error != CallError::InvalidInput,
        }
    })?;
    Ok((reply, trace))
}

// SSE frames are parsed only after a newline; partial UTF-8 bytes remain buffered.
fn stream_delta(provider: Provider, body: &Value, reply: &mut Reply) {
    if provider == Provider::Anthropic {
        if body["type"] == "content_block_delta" {
            if let Some(text) = body["delta"]["text"].as_str() { reply.content.push_str(text); }
            if let Some(text) = body["delta"]["thinking"].as_str() {
                reply.reasoning.get_or_insert_with(String::new).push_str(text);
            }
        }
    } else if provider == Provider::Gemini {
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

/// Returns the provider's own error text from an SSE `error` frame, if present.
fn stream_error_message(frame: &Value) -> Option<String> {
    let text = crate::debug_log::redact(&frame.get("error")?.to_string());
    (!text.is_empty()).then(|| text.chars().take(MAX_PROVIDER_MESSAGE).collect())
}

pub async fn send_stream_via(provider: Provider, model: String, key: Zeroizing<String>, turns: Vec<Turn>, progress: &mut Sender<Reply>, max_output_tokens: u32,
    endpoints: &crate::endpoints::Registry) -> Result<(Reply, Trace), Failure> {
    validate(provider, &model, &turns, max_output_tokens)?;
    let started = Instant::now();
    let mut body = payload(provider, &model, &turns, max_output_tokens);
    if provider != Provider::Gemini { body["stream"] = Value::Bool(true); }
    let request_bytes = body.to_string().len();
    let client = Client::builder().https_only(provider != Provider::OllamaLocal).no_proxy().redirect(redirect::Policy::none())
        .timeout(Duration::from_secs(diagnostics::REQUEST_TIMEOUT_SECS)).build()
        .map_err(|_| Failure::from(CallError::Transport))?;
    let url = endpoints.resolve(provider, crate::endpoints::Kind::Stream, &model);
    let request = client.post(url).json(&body);
    let request = match provider {
        Provider::Gemini => request.header("x-goog-api-key", key.as_str()),
        Provider::Anthropic => request.header("x-api-key", key.as_str()).header("anthropic-version", "2023-06-01"),
        Provider::OllamaLocal => request,
        _ => request.bearer_auth(key.as_str()),
    };
    let mut response = request.send().await.map_err(|_| Failure {
        diagnosis: diagnostics::transport(true), trace: Trace { request_bytes, ..Trace::default() }, may_have_billed: true })?;
    let status = response.status().as_u16();
    let retry_after = response.headers().get("retry-after").and_then(|value| value.to_str().ok())
        .and_then(diagnostics::retry_after);
    if status >= 400 {
        // Drain a bounded error body so the user sees the provider's reason.
        let mut error_body = Vec::new();
        while let Some(chunk) = response.chunk().await.map_err(|_| Failure::from(CallError::Transport))? {
            if error_body.len() + chunk.len() > MAX_PROVIDER_MESSAGE * 8 { break; }
            error_body.extend_from_slice(&chunk);
        }
        let trace = Trace { status: Some(status), duration_ms: started.elapsed().as_millis(), request_bytes, response_bytes: error_body.len(), provider_message: String::new() };
        return Err(http_failure(status, &error_body, retry_after, trace));
    }
    let mut pending = Vec::<u8>::new();
    let mut read = 0usize;
    let mut reply = Reply::default();
    let mut done = false;
    let mut gemini_finished = false;
    let mut provider_error: Option<String> = None;
    while let Some(chunk) = response.chunk().await.map_err(|_| Failure {
        diagnosis: diagnostics::transport(true),
        trace: Trace { status: Some(status), duration_ms: started.elapsed().as_millis(), request_bytes, response_bytes: read, provider_message: String::new() },
        may_have_billed: true })? {
        read = read.saturating_add(chunk.len());
        if read > MAX_REPLY_BYTES { return Err(Failure::from(CallError::Oversized)); }
        pending.extend_from_slice(&chunk);
        while let Some(end) = pending.iter().position(|b| *b == b'\n') {
            let line = pending.drain(..=end).collect::<Vec<u8>>();
            let line = std::str::from_utf8(&line).map_err(|_| Failure::from(CallError::InvalidResponse))?.trim();
            let Some(data) = line.strip_prefix("data:") else { continue; };
            let data = data.trim();
            if data == "[DONE]" { done = true; break; }
            let frame: Value = serde_json::from_str(data).map_err(|_| Failure::from(CallError::InvalidResponse))?;
            if frame.get("error").is_some() || matches!(frame["type"].as_str(), Some("response.failed" | "response.incomplete")) {
                provider_error = stream_error_message(&frame);
                break;
            }
            if provider == Provider::Anthropic && frame["type"] == "message_stop" { done = true; }
            if provider == Provider::Gemini && frame["candidates"][0].get("finishReason").is_some() {
                gemini_finished = matches!(frame["candidates"][0]["finishReason"].as_str(), Some("STOP" | "MAX_TOKENS"));
                if !gemini_finished { return Err(Failure::from(CallError::InvalidResponse)); }
            }
            stream_delta(provider, &frame, &mut reply);
            if reply.content.chars().count() > MAX_VISIBLE_CHARS || reply.reasoning.as_ref().is_some_and(|r| r.chars().count() > MAX_VISIBLE_CHARS) {
                return Err(Failure::from(CallError::Oversized));
            }
            progress.send(reply.clone()).await;
        }
        if done || provider_error.is_some() { break; }
    }
    let trace = Trace { status: Some(status), duration_ms: started.elapsed().as_millis(), request_bytes, response_bytes: read, provider_message: provider_error.clone().unwrap_or_default() };
    if let Some(message) = provider_error {
        let diagnosis = diagnostics::from_http(500, Some(&message));
        return Err(Failure { diagnosis, trace, may_have_billed: true });
    }
    if reply.content.trim().is_empty() || (!done && provider != Provider::Gemini) || (provider == Provider::Gemini && !gemini_finished) {
        // A clean end without [DONE] is a truncated stream: the user sees the
        // partial text and the Debug page shows why it stopped.
        let diagnosis = if reply.content.trim().is_empty() {
            diagnostics::invalid_response("the stream ended without any answer text")
        } else {
            diagnostics::invalid_response("the stream ended before the provider's completion marker")
        };
        return Err(Failure { diagnosis, trace, may_have_billed: true });
    }
    Ok((reply, trace))
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
        assert_eq!(endpoint(Provider::OllamaLocal, "any"), "http://127.0.0.1:11434/v1/chat/completions");
        assert_eq!(endpoint(Provider::Groq, "any"), "https://api.groq.com/openai/v1/chat/completions");
        // Settings shows the same URL the transport will use.
        assert_eq!(endpoint_for(Provider::OpenRouter, None).as_deref(), Some("https://openrouter.ai/api/v1/chat/completions"));
        assert_eq!(endpoint_for(Provider::Custom, None), None);
    }

    #[test]
    fn anthropic_text_and_returned_thinking_are_separated() {
        let reply = extract_reply(Provider::Anthropic, &json!({"content": [
            {"type":"thinking","thinking":"Thought"}, {"type":"text","text":"Answer"}
        ]})).unwrap();
        assert_eq!(reply.content, "Answer");
        assert_eq!(reply.reasoning.as_deref(), Some("Thought"));
        let turns = [Turn { role: "user", content: "Hi".into() }];
        assert!(payload(Provider::Anthropic, "claude", &turns, 256).get("stream").is_none());
    }

    #[test]
    fn normal_large_reply_is_not_discarded_or_silently_cut() {
        let response = "A".repeat(20_000);
        let body = json!({"choices":[{"message":{"content":response}}]});
        assert_eq!(extract_reply(Provider::OpenRouter, &body).unwrap().content.len(), 20_000);
        let too_large = "B".repeat(MAX_VISIBLE_CHARS + 1);
        assert_eq!(extract_reply(Provider::OpenRouter,
            &json!({"choices":[{"message":{"content":too_large}}]})), Err(CallError::Oversized));
    }

    #[test]
    fn payload_sends_no_tools_and_no_free_to_paid_fallback() {
        let turns = [Turn { role: "user", content: "synthetic".into() }];
        let open = payload(Provider::OpenRouter, "vendor/model:free", &turns, 4096);
        assert_eq!(open["model"], "vendor/model:free");
        assert_eq!(open["provider"]["allow_fallbacks"], false);
        assert!(open.get("tools").is_none());
        let gemini = payload(Provider::Gemini, "gemini-test", &turns, 256);
        assert_eq!(gemini["contents"][0]["parts"][0]["text"], "synthetic");
    }

    #[test]
    fn provider_error_bodies_become_a_readable_classified_failure() {
        let body = br#"{"error":{"message":"You exceeded your current quota, please check your plan","type":"insufficient_quota"}}"#;
        let failure = http_failure(429, body, Some(120), Trace::default());
        assert_eq!(failure.diagnosis.http_status, Some(429));
        assert_eq!(failure.diagnosis.owner, crate::diagnostics::Owner::Key);
        assert_eq!(failure.diagnosis.retry_after, Some(120));
        assert!(failure.trace.provider_message.contains("exceeded your current quota"));
        assert!(failure.may_have_billed);

        // A retired model must bench the model, never the key.
        let retired = http_failure(404, br#"{"error":{"message":"models/gemini-1.0-pro is not found"}}"#, None, Trace::default());
        assert_eq!(retired.diagnosis.owner, crate::diagnostics::Owner::Model);
        assert_eq!(retired.diagnosis.cooldown, None);

        // An HTML error page is reduced to a redacted excerpt.
        let html = http_failure(502, b"<html><body>Bad gateway</body></html>", None, Trace::default());
        assert!(html.trace.provider_message.contains("Bad gateway"));
        // A key echoed in an error body never reaches storage or the UI.
        let leaking = http_failure(401, br#"{"error":{"message":"Incorrect API key provided: sk-proj-abcdefghijklmnopqrstuvwx"}}"#, None, Trace::default());
        assert!(!leaking.trace.provider_message.contains("sk-proj-abcdefghijklmnopqrstuvwx"));
        assert!(leaking.trace.provider_message.contains("[redacted]"));
    }

    #[test]
    fn request_size_matches_the_encoded_payload() {
        let turns = [Turn { role: "user", content: "hello".into() }];
        assert_eq!(request_size(Provider::OpenAI, "m", &turns, 256), payload(Provider::OpenAI, "m", &turns, 256).to_string().len());
    }
}
