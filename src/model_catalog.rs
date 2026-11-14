//! Purpose: Fetches bounded, read-only model catalogs for the three fixed providers.
use std::collections::HashSet;
use std::time::Duration;

use reqwest::{redirect, Client, RequestBuilder};
use serde_json::Value;
use zeroize::Zeroizing;

use crate::credentials::Provider;
use crate::provider_api::{valid_model, CallError};

const MAX_CATALOG_BYTES: usize = 2 * 1024 * 1024;
const MAX_MODELS: usize = 4000;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CatalogModel {
    pub id: String,
    pub name: String,
    pub free: bool,
    pub router: bool,
    pub reasoning: bool,
}

fn entry(provider: Provider, id: &str, name: &str, free: bool, router: bool, reasoning: bool) -> Option<CatalogModel> {
    valid_model(provider, id).then(|| CatalogModel {
        id: id.to_owned(),
        name: name.chars().take(100).collect(),
        free,
        router,
        reasoning,
    })
}

fn parse(provider: Provider, body: &Value) -> Result<(Vec<CatalogModel>, Option<String>), CallError> {
    let (items, token) = match provider {
        Provider::OpenRouter => (body.get("data").and_then(Value::as_array), body.get("next").and_then(Value::as_str)),
        Provider::Grok => (body.get("models").and_then(Value::as_array), None),
        Provider::Gemini => (body.get("models").and_then(Value::as_array), body.get("nextPageToken").and_then(Value::as_str)),
    };
    let items = items.ok_or(CallError::InvalidResponse)?;
    let mut models = Vec::new();
    for item in items {
        let Some(raw_id) = item.get(if provider == Provider::Gemini { "name" } else { "id" }).and_then(Value::as_str) else { continue };
        let id = if provider == Provider::Gemini { raw_id.strip_prefix("models/").unwrap_or("") } else { raw_id };
        if provider == Provider::Gemini && !item["supportedGenerationMethods"].as_array().is_some_and(|methods| methods.iter().any(|method| method.as_str() == Some("generateContent"))) { continue; }
        if provider == Provider::Grok && !item["output_modalities"].as_array().is_some_and(|modalities| modalities.iter().any(|modality| modality.as_str() == Some("text"))) { continue; }
        if provider == Provider::OpenRouter {
            if item["architecture"]["output_modalities"].as_array().is_some_and(|modalities| !modalities.iter().any(|modality| modality.as_str() == Some("text"))) { continue; }
            if id.ends_with(":batch") { continue; }
        }
        let router = provider == Provider::OpenRouter && id == "openrouter/free";
        let free = if provider == Provider::OpenRouter {
            router || (id.ends_with(":free") && item["pricing"]["prompt"].as_str() == Some("0") && item["pricing"]["completion"].as_str() == Some("0")) ||
            (item["pricing"]["prompt"].as_str() == Some("0") && item["pricing"]["completion"].as_str() == Some("0"))
        } else { false };
        let reasoning = match provider {
            Provider::OpenRouter => item["supported_parameters"].as_array().is_some_and(|parameters| parameters.iter().any(|p| p.as_str() == Some("reasoning"))),
            Provider::Grok => item["capabilities"]["reasoning_effort"].as_array().is_some_and(|efforts| !efforts.is_empty()),
            Provider::Gemini => item["thinking"].as_bool() == Some(true),
        };
        let name = item.get(if provider == Provider::Gemini { "displayName" } else { "name" }).and_then(Value::as_str).unwrap_or(id);
        if let Some(model) = entry(provider, id, name, free, router, reasoning) { models.push(model); }
    }
    Ok((models, token.map(str::to_owned)))
}

// Never echo provider JSON or transport errors: responses can include account data.
async fn read_json(mut response: reqwest::Response) -> Result<Value, CallError> {
    let status = response.status();
    if !status.is_success() { return Err(CallError::Rejected(status.as_u16())); }
    let mut bytes = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|_| CallError::Transport)? {
        if bytes.len().saturating_add(chunk.len()) > MAX_CATALOG_BYTES { return Err(CallError::Oversized); }
        bytes.extend_from_slice(&chunk);
    }
    serde_json::from_slice(&bytes).map_err(|_| CallError::InvalidResponse)
}

pub async fn fetch(provider: Provider, key: Option<Zeroizing<String>>) -> Result<Vec<CatalogModel>, CallError> {
    let client = Client::builder().https_only(true).no_proxy().redirect(redirect::Policy::none())
        .timeout(Duration::from_secs(25)).build().map_err(|_| CallError::Transport)?;
    let mut all = Vec::new();
    let mut token: Option<String> = None;
    let mut seen = HashSet::new();
    let mut page_tokens = HashSet::new();
    for page in 0..10 {
        let request: RequestBuilder = match provider {
            Provider::OpenRouter => client.get("https://openrouter.ai/api/v1/models")
                .query(&[("limit", "1000"), ("offset", &(page * 1000).to_string()), ("endpoints", "/api/v1/chat/completions")]),
            Provider::Grok => client.get("https://api.x.ai/v1/language-models")
                .bearer_auth(key.as_ref().ok_or(CallError::InvalidInput)?.as_str()),
            Provider::Gemini => {
                let mut request = client.get("https://generativelanguage.googleapis.com/v1beta/models")
                    .query(&[("pageSize", "1000")])
                    .header("x-goog-api-key", key.as_ref().ok_or(CallError::InvalidInput)?.as_str());
                if let Some(ref page) = token { request = request.query(&[("pageToken", page)]); }
                request
            }
        };
        let body = read_json(request.send().await.map_err(|_| CallError::Transport)?).await?;
        let (items, next) = parse(provider, &body)?;
        let page_len = items.len();
        for model in items {
            if seen.insert(model.id.clone()) { all.push(model); }
            if all.len() > MAX_MODELS { return Err(CallError::Oversized); }
        }
        if provider == Provider::OpenRouter && page_len == 1000 { continue; }
        match next {
            Some(next) if !next.is_empty() && provider == Provider::Gemini && page_tokens.insert(next.clone()) => token = Some(next),
            Some(_) if provider == Provider::Gemini => return Err(CallError::InvalidResponse),
            _ => {
                // The documented free router is an explicit choice even if the public catalog omits routers.
                if provider == Provider::OpenRouter && !all.iter().any(|model| model.id == "openrouter/free") {
                    all.push(entry(provider, "openrouter/free", "OpenRouter Free Router", true, true, false).expect("fixed valid ID"));
                }
                all.sort_by(|a, b| b.free.cmp(&a.free).then(a.id.cmp(&b.id)));
                return Ok(all);
            }
        }
    }
    Err(CallError::Oversized)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn openrouter_free_router_is_distinct_and_reasoning_is_metadata_only() {
        let body = json!({"data": [
            {"id":"openrouter/free","pricing":{"prompt":"-1","completion":"-1"}},
            {"id":"vendor/model:free","pricing":{"prompt":"0","completion":"0"},"supported_parameters":["reasoning"]},
            {"id":"vendor/paid","pricing":{"prompt":"0.1","completion":"0.2"}},
            {"id":"vendor/batch:batch","pricing":{"prompt":"0","completion":"0"}}
        ]});
        let (models, _) = parse(Provider::OpenRouter, &body).unwrap();
        assert_eq!(models.len(), 3);
        assert!(models[0].router && models[0].free);
        assert!(models[1].free && models[1].reasoning);
        assert!(!models[2].free && !models[2].reasoning);
    }

    #[test]
    fn filters_non_chat_models_and_does_not_assume_gemini_free() {
        let (gemini, token) = parse(Provider::Gemini, &json!({"models": [
            {"name":"models/gemini-1","displayName":"Gemini","supportedGenerationMethods":["generateContent"],"thinking":true},
            {"name":"models/embed","supportedGenerationMethods":["embedContent"]}
        ],"nextPageToken":"next"})).unwrap();
        assert_eq!(token.as_deref(), Some("next"));
        assert_eq!(gemini.len(), 1);
        assert!(gemini[0].reasoning && !gemini[0].free);
        let (xai, _) = parse(Provider::Grok, &json!({"models": [
            {"id":"grok-reasoning","output_modalities":["text"],"capabilities":{"reasoning_effort":["high"]}},
            {"id":"grok-image","output_modalities":["image"]}
        ]})).unwrap();
        assert_eq!(xai.len(), 1);
        assert!(xai[0].reasoning && !xai[0].free);
    }
}
