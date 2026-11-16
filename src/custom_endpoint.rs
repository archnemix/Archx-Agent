//! Session-only custom HTTP text endpoint. Never invoke a cURL command as a process.
//! The user's explicit approval applies to the displayed destination and credentials;
//! redirects, ambient proxies and implicit DNS/URL substitution are disabled.
use std::time::Duration;
use reqwest::{Client, Url, redirect, header::{HeaderName, HeaderValue}};
use serde_json::{json, Value};
use zeroize::Zeroizing;
use crate::provider_api::{CallError, Reply, Turn};

// Only these cURL options have a meaning. Reject all others rather than
// accidentally interpreting a shell pipeline, @file body, -k or a redirect.
pub fn parse_curl(input: &str) -> Result<(String, String, String), &'static str> {
    let mut tokens = Zeroizing::new(Vec::new());
    let mut word = Zeroizing::new(String::new());
    let mut quote = None;
    let mut escaped = false;
    for ch in input.chars() {
        if escaped { word.push(ch); escaped = false; continue; }
        if ch == '\\' && quote != Some('\'') { escaped = true; continue; }
        if let Some(q) = quote {
            if ch == q { quote = None; } else { word.push(ch); }
        } else if ch == '\'' || ch == '"' { quote = Some(ch); }
        else if ch.is_whitespace() {
            if !word.is_empty() { tokens.push(std::mem::take(&mut *word)); }
        } else if matches!(ch, ';' | '|' | '&' | '>' | '<' | '`' | '$' | '\n') {
            return Err("Shell syntax is not supported. Supply only a literal cURL request.");
        } else { word.push(ch); }
    }
    if escaped || quote.is_some() { return Err("Unclosed cURL quote or escape."); }
    if !word.is_empty() { tokens.push(std::mem::take(&mut *word)); }
    if tokens.first().map(String::as_str) != Some("curl") { return Err("Expected a literal curl command."); }
    let mut url = String::new(); let mut headers = Vec::new(); let mut body = String::new();
    let mut i = 1;
    while i < tokens.len() {
        let flag = tokens[i].as_str(); i += 1;
        if !matches!(flag, "-X" | "--request" | "-H" | "--header" | "-d" | "--data" | "--data-raw" | "--url") {
            if flag.starts_with("http://") || flag.starts_with("https://") {
                if !url.is_empty() { return Err("Only one destination is allowed."); }
                url = flag.to_owned(); continue;
            }
            return Err("Unsupported cURL option. Files, redirects, TLS bypass and shell commands are not allowed.");
        }
        let value = tokens.get(i).ok_or("Missing cURL option value.")?;
        i += 1;
        match flag {
            "-X" | "--request" if value == "POST" => (),
            "-X" | "--request" => return Err("Only POST requests are supported."),
            "-H" | "--header" => headers.push(value.to_owned()),
            "--url" if url.is_empty() => url = value.to_owned(),
            "--url" => return Err("Only one destination is allowed."),
            _ if body.is_empty() => body = value.to_owned(),
            _ => return Err("Only one JSON request body is allowed."),
        }
    }
    if url.is_empty() || body.is_empty() { return Err("A destination and JSON body are required."); }
    if body.starts_with('@') { return Err("Reading files from cURL is not allowed."); }
    validate_url(&url)?;
    let _: Value = serde_json::from_str(&body).map_err(|_| "The cURL body must be valid JSON.")?;
    if headers.len() > 16 { return Err("Too many headers."); }
    for header in &headers { validate_header(header)?; }
    Ok((url, headers.join("\n"), body))
}

pub fn validate_url(raw: &str) -> Result<Url, &'static str> {
    let url = Url::parse(raw).map_err(|_| "Enter an absolute HTTPS URL (or HTTP loopback URL).")?;
    let host = url.host_str().ok_or("URL needs a host.")?;
    let loopback = matches!(host, "localhost" | "127.0.0.1" | "[::1]");
    if (url.scheme() != "https" && !(url.scheme() == "http" && loopback)) ||
        !url.username().is_empty() || url.password().is_some() || url.fragment().is_some() ||
        raw.len() > 2048 { return Err("Only HTTPS or HTTP loopback without URL credentials/fragments is allowed."); }
    Ok(url)
}

fn validate_header(line: &str) -> Result<(), &'static str> {
    let (name, value) = line.split_once(':').ok_or("Use Name: value for each header.")?;
    let name = HeaderName::from_bytes(name.trim().as_bytes()).map_err(|_| "Invalid header name.")?;
    HeaderValue::from_str(value.trim()).map_err(|_| "Invalid header value.")?;
    if matches!(name.as_str(), "host" | "content-length" | "connection" | "transfer-encoding" | "proxy-authorization" | "cookie") {
        return Err("Transport, cookie and proxy headers are not allowed.");
    }
    Ok(())
}

// Placeholders occupy entire JSON string leaves so they preserve their type.
fn expand(value: &mut Value, model: &str, turns: &[Turn], limit: u32, stream: bool) {
    match value {
        Value::String(s) => {
            *value = match s.as_str() {
                "{{model}}" => json!(model),
                "{{prompt}}" => json!(turns.last().map(|t| t.content.as_str()).unwrap_or("")),
                "{{messages}}" => json!(turns.iter().map(|t| json!({"role":t.role,"content":t.content})).collect::<Vec<_>>()),
                "{{max_tokens}}" => json!(limit),
                "{{stream}}" => json!(stream),
                _ => return,
            };
        }
        Value::Array(items) => for item in items { expand(item, model, turns, limit, stream); },
        Value::Object(items) => for item in items.values_mut() { expand(item, model, turns, limit, stream); },
        _ => (),
    }
}

// No arbitrary scripting or selector language. RFC 6901 JSON pointer only.
pub fn parse_answer(value: &Value, pointer: &str) -> Result<Reply, CallError> {
    if !pointer.starts_with('/') || pointer.len() > 256 { return Err(CallError::InvalidInput); }
    let content = value.pointer(pointer).and_then(Value::as_str).ok_or(CallError::InvalidResponse)?;
    if content.is_empty() { return Err(CallError::InvalidResponse); }
    if content.chars().count() > 96 * 1024 { return Err(CallError::Oversized); }
    Ok(Reply { content: content.to_owned(), reasoning: None })
}

// Profile is intentionally not Debug, serialized or persisted. A credential
// placeholder is replaced only immediately before transport, never in UI text.
#[derive(Clone)]
pub struct Profile {
    pub url: String,
    pub headers: Zeroizing<String>,
    pub body: String,
    pub answer_pointer: String,
    pub stream: bool,
    pub stream_pointer: String,
}
impl Default for Profile {
    fn default() -> Self {
        Self { url: String::new(), headers: Zeroizing::new(String::new()),
            body: r#"{"model":"{{model}}","messages":"{{messages}}","max_tokens":"{{max_tokens}}","stream":"{{stream}}"}"#.into(),
            answer_pointer: "/choices/0/message/content".into(), stream: false,
            stream_pointer: "/choices/0/delta/content".into() }
    }
}
impl Profile {
    pub fn check(&self) -> Result<(), &'static str> {
        validate_url(&self.url)?;
        if self.headers.len() > 8192 || self.body.len() > 16_384 { return Err("Custom request is too long."); }
        for line in self.headers.split(['\n', '|']) { if !line.trim().is_empty() { validate_header(line)?; } }
        let body: Value = serde_json::from_str(&self.body).map_err(|_| "Request body must be JSON.")?;
        if !body.to_string().contains("{{prompt}}") && !body.to_string().contains("{{messages}}") {
            return Err("Include {{prompt}} or {{messages}} in the JSON request.");
        }
        if !self.answer_pointer.starts_with('/') || !self.stream_pointer.starts_with('/') {
            return Err("Response selectors must be JSON pointers starting with /.");
        }
        Ok(())
    }
}

pub async fn send(profile: Profile, model: String, key: Zeroizing<String>, turns: Vec<Turn>, max_tokens: u32) -> Result<Reply, CallError> {
    send_inner(profile, model, key, turns, max_tokens, None).await
}

pub async fn send_stream(profile: Profile, model: String, key: Zeroizing<String>, turns: Vec<Turn>, max_tokens: u32,
    progress: &mut sipper::Sender<Reply>) -> Result<Reply, CallError> {
    send_inner(profile, model, key, turns, max_tokens, Some(progress)).await
}

async fn send_inner(profile: Profile, model: String, key: Zeroizing<String>, turns: Vec<Turn>, max_tokens: u32,
    mut progress: Option<&mut sipper::Sender<Reply>>) -> Result<Reply, CallError> {
    profile.check().map_err(|_| CallError::InvalidInput)?;
    if turns.is_empty() || max_tokens == 0 || max_tokens > 4096 { return Err(CallError::InvalidInput); }
    let client = Client::builder().no_proxy().redirect(redirect::Policy::none())
        .timeout(Duration::from_secs(45)).build().map_err(|_| CallError::Transport)?;
    let mut body: Value = serde_json::from_str(&profile.body).map_err(|_| CallError::InvalidInput)?;
    expand(&mut body, &model, &turns, max_tokens, profile.stream);
    let mut request = client.post(validate_url(&profile.url).map_err(|_| CallError::InvalidInput)?).json(&body);
    for line in profile.headers.split(['\n', '|']) {
        if line.trim().is_empty() { continue; }
        let (name, value) = line.split_once(':').ok_or(CallError::InvalidInput)?;
        validate_header(line).map_err(|_| CallError::InvalidInput)?;
        let value = Zeroizing::new(value.trim().replace("{{api_key}}", key.as_str()));
        request = request.header(name.trim(), value.as_str());
    }
    let mut response = request.send().await.map_err(|_| CallError::Transport)?;
    if !response.status().is_success() { return Err(CallError::Rejected(response.status().as_u16())); }
    let mut bytes = Vec::new();
    let mut read = 0usize;
    let mut reply = Reply::default();
    let mut done = false;
    while let Some(chunk) = response.chunk().await.map_err(|_| CallError::Transport)? {
        read = read.saturating_add(chunk.len());
        if read > 2 * 1024 * 1024 { return Err(CallError::Oversized); }
        bytes.extend_from_slice(&chunk);
        if profile.stream {
            while let Some(end) = bytes.iter().position(|b| *b == b'\n') {
                let line = bytes.drain(..=end).collect::<Vec<_>>();
                let line = std::str::from_utf8(&line).map_err(|_| CallError::InvalidResponse)?;
                let Some(data) = line.trim().strip_prefix("data:") else { continue; };
                if data.trim() == "[DONE]" { done = true; break; }
                let frame: Value = serde_json::from_str(data.trim()).map_err(|_| CallError::InvalidResponse)?;
                let delta = frame.pointer(&profile.stream_pointer).and_then(Value::as_str)
                    .ok_or(CallError::InvalidResponse)?;
                if reply.content.len().saturating_add(delta.len()) > 96 * 1024 { return Err(CallError::Oversized); }
                reply.content.push_str(delta);
                if let Some(sender) = progress.as_mut() { sender.send(reply.clone()).await; }
            }
            if done { break; }
        }
    }
    if profile.stream {
        if reply.content.is_empty() { return Err(CallError::InvalidResponse); }
        // Some user-built wrappers close cleanly without a [DONE] sentinel.
        Ok(reply)
    } else {
        let body: Value = serde_json::from_slice(&bytes).map_err(|_| CallError::InvalidResponse)?;
        parse_answer(&body, &profile.answer_pointer)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_shell_and_unsafe_destinations() {
        assert!(parse_curl("curl -k https://localhost -d '{}'").is_err());
        assert!(parse_curl("curl https://localhost -d '{}' ; echo secret").is_err());
        assert!(parse_curl("curl https://localhost -d @/tmp/secret").is_err());
        assert!(validate_url("http://example.com/ai").is_err());
        assert!(validate_url("https://user:pass@example.com/ai").is_err());
    }
    #[test]
    fn parses_literal_curl_and_typed_templates() {
        let (url, headers, body) = parse_curl("curl -X POST https://example.com/chat -H 'Authorization: Bearer {{api_key}}' -d '{\"prompt\":\"{{prompt}}\",\"limit\":\"{{max_tokens}}\"}'").unwrap();
        assert_eq!(url, "https://example.com/chat");
        assert!(headers.contains("{{api_key}}"));
        let mut value: Value = serde_json::from_str(&body).unwrap();
        expand(&mut value, "smol", &[Turn { role: "user", content: "Hi".into() }], 256, false);
        assert_eq!(value["prompt"], "Hi");
        assert_eq!(value["limit"], 256);
        assert_eq!(parse_answer(&json!({"result":{"text":"OK"}}), "/result/text").unwrap().content, "OK");
    }
}
