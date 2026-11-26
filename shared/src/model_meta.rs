//! Purpose: Enriches a model row with modality, context window, price and free-tier notes from public metadata.
//!
//! Two public sources are read, both optional and both cached on disk:
//!   * `https://models.dev/api.json` — an actively maintained, community-run
//!     machine-readable catalog of model metadata (input/output modality,
//!     context window, cost per million tokens, `type` and `status`; note that
//!     retirement is `status = "deprecated"`, there is no `deprecated` boolean).
//!   * the free-tier list in `github.com/mnfst/awesome-free-llm-apis`, stored as a
//!     local curated registry (`assets/model_meta/free_tiers.json`) because that
//!     repository is a Markdown document, not an API.
//!
//! Provider catalogs themselves already carry some of this (OpenRouter exposes
//! modality and pricing, Gemini exposes thinking support). Where the provider is
//! silent, this module fills the gap and always labels the source, so a guessed
//! or missing value is never presented as provider truth.

use std::collections::HashMap;

use reqwest::{redirect, Client};
use serde_json::Value;

use crate::credentials::Provider;

pub const MODELS_DEV_URL: &str = "https://models.dev/api.json";
/// The curated free-tier registry shipped with the app.
const FREE_TIERS: &str = include_str!("../assets/model_meta/free_tiers.json");
const MAX_META_BYTES: usize = 24 * 1024 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Source {
    Provider,
    ModelsDev,
    FreeRegistry,
    Unknown,
}

impl Source {
    pub fn label(self) -> &'static str {
        match self {
            Self::Provider => "provider",
            Self::ModelsDev => "models.dev",
            Self::FreeRegistry => "free-tier list",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Default)]
pub struct Meta {
    /// e.g. "text", "text+image", "text+audio", "embedding".
    pub input_modalities: Vec<String>,
    pub output_modalities: Vec<String>,
    pub context: Option<u64>,
    pub output_limit: Option<u64>,
    /// USD per million input / output tokens; `None` when unpriced.
    pub cost_in: Option<f64>,
    pub cost_out: Option<f64>,
    pub free_tier: Option<String>,
    pub deprecation: Option<String>,
    /// models.dev `status`: `alpha`, `beta` or `deprecated`. Kept apart from
    /// `deprecation`, which is the human-readable label shown on the row.
    pub status: Option<String>,
    /// models.dev `type` (`chat`, `embedding`, `image`, …). `None` means the
    /// catalog did not say, and models.dev treats a missing type as `chat`.
    pub kind: Option<String>,
    pub source: Option<Source>,
}

impl Meta {
    pub fn is_empty(&self) -> bool {
        self.input_modalities.is_empty() && self.output_modalities.is_empty() && self.context.is_none()
            && self.cost_in.is_none() && self.free_tier.is_none() && self.deprecation.is_none()
            && self.status.is_none() && self.kind.is_none()
    }

    pub fn modality_label(&self) -> String {
        if self.output_modalities.is_empty() { return String::new(); }
        let input = if self.input_modalities.is_empty() { "text".to_owned() } else { self.input_modalities.join("+") };
        format!("{input} → {}", self.output_modalities.join("+"))
    }

    pub fn price_label(&self) -> String {
        match (self.cost_in, self.cost_out) {
            (Some(input), Some(output)) if input == 0.0 && output == 0.0 => "free".to_owned(),
            (Some(input), Some(output)) => format!("${input:.2} / ${output:.2} per 1M"),
            _ => String::new(),
        }
    }

    pub fn context_label(&self) -> String {
        match self.context {
            Some(context) if context >= 1_000 => format!("{}k context", context / 1_000),
            Some(context) => format!("{context} context"),
            None => String::new(),
        }
    }

    /// One compact line for the model row, source-labelled.
    pub fn line(&self) -> String {
        let mut parts: Vec<String> = Vec::new();
        if !self.output_modalities.is_empty() { parts.push(self.modality_label()); }
        if !self.context_label().is_empty() { parts.push(self.context_label()); }
        if !self.price_label().is_empty() { parts.push(self.price_label()); }
        if let Some(free) = &self.free_tier { parts.push(format!("free tier: {free}")); }
        if let Some(note) = &self.deprecation { parts.push(note.clone()); }
        if parts.is_empty() { return String::new(); }
        let source = self.source.unwrap_or(Source::Unknown).label();
        format!("{}  ·  {source}", parts.join("  ·  "))
    }

    fn merge(&mut self, other: Meta) {
        if self.input_modalities.is_empty() { self.input_modalities = other.input_modalities; }
        if self.output_modalities.is_empty() { self.output_modalities = other.output_modalities; }
        self.context = self.context.or(other.context);
        self.output_limit = self.output_limit.or(other.output_limit);
        self.cost_in = self.cost_in.or(other.cost_in);
        self.cost_out = self.cost_out.or(other.cost_out);
        self.free_tier = self.free_tier.take().or(other.free_tier);
        self.deprecation = self.deprecation.take().or(other.deprecation);
        self.status = self.status.take().or(other.status);
        self.kind = self.kind.take().or(other.kind);
        self.source = self.source.or(other.source);
    }
}

/// Provider id in models.dev terms, used to pick the right sub-object.
fn models_dev_provider(provider: Provider) -> &'static str {
    match provider {
        Provider::OpenRouter => "openrouter",
        Provider::Grok => "xai",
        Provider::Gemini => "google",
        Provider::OpenAI => "openai",
        Provider::Anthropic => "anthropic",
        Provider::Groq => "groq",
        Provider::Zai => "zai",
        Provider::OllamaLocal | Provider::OllamaCloud => "ollama",
        Provider::Custom => "",
    }
}

pub struct Registry {
    /// provider id -> (model id -> meta)
    by_provider: HashMap<String, HashMap<String, Meta>>,
    free: HashMap<String, String>,
}

fn parse_modalities(value: Option<&Value>) -> Vec<String> {
    value.and_then(Value::as_array)
        .map(|items| items.iter().filter_map(Value::as_str).take(4)
            .map(|item| item.chars().take(16).collect::<String>()).collect())
        .unwrap_or_default()
}

fn number(value: Option<&Value>) -> Option<f64> {
    value.and_then(Value::as_f64).filter(|value| value.is_finite() && *value >= 0.0)
}

/// Parses models.dev's document into per-provider lookups. The public schema is
/// `{ "<provider>": { "models": { "<id>": { "modalities": {…}, "limit": {…}, "cost": {…} } } } }`.
pub fn parse_models_dev(body: &Value) -> Registry {
    let mut by_provider: HashMap<String, HashMap<String, Meta>> = HashMap::new();
    let Some(providers) = body.as_object() else { return registry(by_provider) };
    for (provider_id, provider) in providers {
        let models = provider.get("models").and_then(Value::as_object)
            .or_else(|| provider.get("model").and_then(Value::as_object));
        let Some(models) = models else { continue };
        let mut lookup = HashMap::new();
        for (model_id, model) in models {
            let modalities = model.get("modalities");
            let meta = Meta {
                input_modalities: parse_modalities(modalities.and_then(|value| value.get("input"))),
                output_modalities: parse_modalities(modalities.and_then(|value| value.get("output"))),
                context: model.pointer("/limit/context").and_then(Value::as_u64),
                output_limit: model.pointer("/limit/output").and_then(Value::as_u64),
                cost_in: number(model.pointer("/cost/input")),
                cost_out: number(model.pointer("/cost/output")),
                free_tier: None,
                // models.dev has no `deprecated` boolean: retirement is the
                // `status` field, whose only negative value is "deprecated".
                deprecation: match model.get("status").and_then(Value::as_str) {
                    Some("deprecated") => Some("marked deprecated".to_owned()),
                    Some("alpha") => Some("alpha".to_owned()),
                    Some("beta") => Some("beta".to_owned()),
                    _ => None,
                },
                status: model.get("status").and_then(Value::as_str).map(str::to_ascii_lowercase),
                kind: model.get("type").and_then(Value::as_str).map(str::to_ascii_lowercase),
                source: Some(Source::ModelsDev),
            };
            lookup.insert(model_id.to_ascii_lowercase(), meta);
        }
        by_provider.insert(provider_id.to_ascii_lowercase(), lookup);
    }
    registry(by_provider)
}

fn registry(by_provider: HashMap<String, HashMap<String, Meta>>) -> Registry {
    let free = serde_json::from_str::<Value>(FREE_TIERS).ok()
        .and_then(|value| value.get("models").and_then(Value::as_object).cloned())
        .map(|models| models.into_iter()
            .filter_map(|(id, note)| note.as_str().map(|note| (id.to_ascii_lowercase(), note.chars().take(80).collect())))
            .collect())
        .unwrap_or_default();
    Registry { by_provider, free }
}

impl Registry {
    pub fn lookup(&self, provider: Provider, model: &str) -> Meta {
        let mut meta = Meta::default();
        let provider_id = models_dev_provider(provider);
        if !provider_id.is_empty() {
            if let Some(models) = self.by_provider.get(provider_id) {
                // Try the full id, then the part after the last slash (matches
                // how OpenRouter prefixes vendor names).
                let key = model.to_ascii_lowercase();
                if let Some(found) = models.get(&key).or_else(|| model.rsplit('/').next().and_then(|tail| models.get(&tail.to_ascii_lowercase()))) {
                    meta.merge(found.clone());
                }
            }
        }
        let free_key = model.to_ascii_lowercase();
        if let Some(note) = self.free.get(&free_key).or_else(|| model.rsplit('/').next().and_then(|tail| self.free.get(&tail.to_ascii_lowercase()))) {
            meta.free_tier = Some(note.clone());
            if meta.source.is_none() { meta.source = Some(Source::FreeRegistry); }
        }
        meta
    }

    /// Whether models.dev has *any* entry for this id under this provider. A
    /// bare `{"name": ...}` still proves the id exists in the catalog.
    pub fn knows(&self, provider: Provider, model: &str) -> bool {
        let provider_id = models_dev_provider(provider);
        if provider_id.is_empty() { return false; }
        let Some(models) = self.by_provider.get(provider_id) else { return false };
        let key = model.to_ascii_lowercase();
        models.contains_key(&key)
            || model.rsplit('/').next().is_some_and(|tail| models.contains_key(&tail.to_ascii_lowercase()))
    }

    pub fn len(&self) -> usize { self.by_provider.values().map(HashMap::len).sum() }

    pub fn is_empty(&self) -> bool { self.by_provider.is_empty() }
}

/// The bundled free-tier registry alone (works offline, no network).
pub fn local_registry() -> Registry {
    registry(HashMap::new())
}

/// Downloads models.dev and returns the parsed registry. Bounded, HTTPS-only,
/// no redirects, 30 s timeout.
pub async fn fetch_models_dev() -> Result<Registry, String> {
    let client = Client::builder().https_only(true).no_proxy()
        .redirect(redirect::Policy::none())
        .timeout(std::time::Duration::from_secs(30))
        .build().map_err(|_| "Could not create the HTTPS client.".to_owned())?;
    let mut response = client.get(MODELS_DEV_URL).send().await
        .map_err(|_| "models.dev did not respond within 30 s.".to_owned())?;
    if !response.status().is_success() {
        return Err(format!("models.dev returned HTTP {}.", response.status().as_u16()));
    }
    let mut bytes = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|_| "models.dev response was interrupted.".to_owned())? {
        if bytes.len() + chunk.len() > MAX_META_BYTES { return Err("models.dev response exceeded 24 MiB.".to_owned()); }
        bytes.extend_from_slice(&chunk);
    }
    let body: Value = serde_json::from_slice(&bytes).map_err(|_| "models.dev returned an unexpected document.".to_owned())?;
    let registry = parse_models_dev(&body);
    if registry.is_empty() { return Err("models.dev returned no model metadata.".to_owned()); }
    Ok(registry)
}

/// Why a model in the user's list is considered gone.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SweepReason {
    /// models.dev still knows this id (as a live model) but the provider's own
    /// `/models` no longer lists it: two sources, both read, one answer.
    GoneFromProvider,
    /// models.dev marks it `status = "deprecated"`, whatever the live list says.
    Deprecated,
    /// Absent from the live list, but models.dev never heard of it either. Never
    /// acted on: that is exactly the shape of a private, beta or hand-typed id,
    /// which this app supports on purpose by letting a user add an exact ID.
    Unlisted,
    /// No source had anything to say. Never acted on.
    Unknown,
}

impl SweepReason {
    pub fn label(&self) -> &'static str {
        match self {
            Self::GoneFromProvider => "dropped by the provider; models.dev still lists it",
            Self::Deprecated => "marked deprecated by models.dev",
            Self::Unlisted => "absent from the provider list; no other source to confirm",
            Self::Unknown => "not in either source",
        }
    }
    /// Only positive evidence retires a row. `Unlisted` is deliberately not
    /// evidence: one silent source is not proof of absence.
    pub fn is_evidence(&self) -> bool {
        matches!(self, Self::GoneFromProvider | Self::Deprecated)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SweepVerdict {
    pub model: String,
    pub reason: SweepReason,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Sweep {
    /// Models with positive evidence that they no longer exist.
    pub gone: Vec<SweepVerdict>,
    /// Missing from the live list, but nothing confirms it: reported, never
    /// disabled. This is where a private or hand-typed id lands.
    pub unlisted: Vec<String>,
    /// No source had anything to say; reported, never disabled.
    pub unknown: Vec<String>,
    /// True when the provider list was actually consulted.
    pub provider_checked: bool,
}

impl Sweep {
    pub fn is_empty(&self) -> bool {
        self.gone.is_empty() && self.unlisted.is_empty() && self.unknown.is_empty()
    }
    pub fn summary(&self) -> String {
        if self.is_empty() { return "Nothing to sweep: every added model is still listed.".to_owned(); }
        let mut parts = Vec::new();
        if !self.gone.is_empty() { parts.push(format!("{} gone", self.gone.len())); }
        if !self.unlisted.is_empty() { parts.push(format!("{} unlisted", self.unlisted.len())); }
        if !self.unknown.is_empty() { parts.push(format!("{} unverified", self.unknown.len())); }
        let scope = if self.provider_checked { "provider list + models.dev" } else { "models.dev" };
        let tail = if self.gone.is_empty() { "; nothing is confirmed gone" } else { "" };
        format!("Sweep ({scope}): {}{tail}", parts.join(", "))
    }
    /// The model ids that would be disabled, in list order.
    pub fn ids(&self) -> Vec<String> { self.gone.iter().map(|verdict| verdict.model.clone()).collect() }
}

/// Compare the models the user added against the live catalog.
///
/// * `kind` — the provider the ids belong to, so models.dev is read under the
///   right provider key.
/// * `added` — ids as the user stored them (exact, no prefix rewriting).
/// * `live` — `Some(list)` when the provider's live `/models` answered.
///   `None` means it could not be consulted, so absence from it proves nothing.
/// * `meta` — models.dev registry, or `None` when it is not cached yet.
///
/// A model is reported gone only when a source positively says so:
/// models.dev marks it `deprecated`, or models.dev knows the id as a live model
/// while the provider's own list has dropped it. Absence from one source alone
/// is never enough — a private, beta or hand-typed id looks exactly like that,
/// and this app lets a user add such an id on purpose.
pub fn sweep(kind: Provider, added: &[String], live: Option<&[String]>, meta: Option<&Registry>) -> Sweep {
    let mut sweep = Sweep { provider_checked: live.is_some(), ..Sweep::default() };
    let live: Option<std::collections::HashSet<String>> = live
        .map(|ids| ids.iter().map(|id| id.to_ascii_lowercase()).collect());
    for model in added {
        let key = model.to_ascii_lowercase();
        // OpenRouter-style ids may be stored with a vendor prefix while the
        // provider echoes the bare id; try the tail as well.
        let tail = key.rsplit('/').next().unwrap_or(&key).to_owned();
        let in_provider = live.as_ref().map(|set| set.contains(&key) || set.contains(&tail));
        // `known` is "models.dev has an entry for this id", which is different
        // from "the entry says something useful" — a bare `{name}` still
        // proves the id exists in the catalog's taxonomy.
        let known = meta.map(|registry| registry.knows(kind, model)).unwrap_or(false);
        let deprecated = meta.map(|registry| registry.lookup(kind, model))
            .and_then(|meta| meta.status)
            .as_deref() == Some("deprecated");
        let reason = match (in_provider, deprecated, known) {
            (_, true, _) => SweepReason::Deprecated,
            (Some(true), false, _) => continue,
            (Some(false), false, true) => SweepReason::GoneFromProvider,
            (Some(false), false, false) => SweepReason::Unlisted,
            (None, false, _) => SweepReason::Unknown,
        };
        match reason {
            SweepReason::Unknown => sweep.unknown.push(model.clone()),
            SweepReason::Unlisted => sweep.unlisted.push(model.clone()),
            reason => sweep.gone.push(SweepVerdict { model: model.clone(), reason }),
        }
    }
    sweep
}

/// Cached document: `model-meta.json` beside the other data files.
pub fn cache_path() -> std::path::PathBuf { crate::storage::root().join("model-meta.json") }

pub fn save_cache(registry: &Registry) -> Result<(), std::io::Error> {
    let mut by_provider = serde_json::Map::new();
    for (provider, models) in &registry.by_provider {
        let mut entry = serde_json::Map::new();
        for (id, meta) in models {
            entry.insert(id.clone(), serde_json::json!({
                "input": meta.input_modalities, "output": meta.output_modalities,
                "context": meta.context, "output_limit": meta.output_limit,
                "cost_in": meta.cost_in, "cost_out": meta.cost_out, "deprecation": meta.deprecation,
                "status": meta.status, "kind": meta.kind,
            }));
        }
        by_provider.insert(provider.clone(), Value::Object(entry));
    }
    let document = serde_json::json!({"version": 1, "kind": "model-meta", "fetched": crate::storage::now_secs(), "providers": by_provider});
    let path = cache_path();
    if let Some(parent) = path.parent() { std::fs::create_dir_all(parent)?; }
    std::fs::write(&path, serde_json::to_vec(&document).map_err(|_| std::io::Error::other("encode"))?)
}

pub fn load_cache() -> Option<(Registry, u64)> {
    let bytes = std::fs::read(cache_path()).ok()?;
    let document: Value = serde_json::from_slice(&bytes).ok()?;
    if document.get("version").and_then(Value::as_u64) != Some(1) { return None; }
    let fetched = document.get("fetched").and_then(Value::as_u64).unwrap_or(0);
    let mut by_provider = HashMap::new();
    for (provider, models) in document.get("providers").and_then(Value::as_object)?.iter() {
        let mut lookup = HashMap::new();
        for (id, meta) in models.as_object()? {
            lookup.insert(id.clone(), Meta {
                input_modalities: parse_modalities(meta.get("input")),
                output_modalities: parse_modalities(meta.get("output")),
                context: meta.get("context").and_then(Value::as_u64),
                output_limit: meta.get("output_limit").and_then(Value::as_u64),
                cost_in: number(meta.get("cost_in")),
                cost_out: number(meta.get("cost_out")),
                free_tier: None,
                deprecation: meta.get("deprecation").and_then(Value::as_str).map(str::to_owned),
                status: meta.get("status").and_then(Value::as_str).map(str::to_owned),
                kind: meta.get("kind").and_then(Value::as_str).map(str::to_owned),
                source: Some(Source::ModelsDev),
            });
        }
        by_provider.insert(provider.clone(), lookup);
    }
    Some((registry(by_provider), fetched))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn models_dev_document_is_parsed_by_provider_and_alias() {
        let body = json!({
            "google": { "models": {
                "gemini-2.5-flash": {
                    "modalities": {"input": ["text", "image", "audio"], "output": ["text"]},
                    "limit": {"context": 1048576, "output": 65536},
                    "cost": {"input": 0.3, "output": 2.5}
                }
            }},
            "openai": { "models": {
                "gpt-4o": { "modalities": {"input": ["text", "image"], "output": ["text"]}, "limit": {"context": 128000} }
            }}
        });
        let registry = parse_models_dev(&body);
        assert_eq!(registry.len(), 2);
        let gemini = registry.lookup(Provider::Gemini, "gemini-2.5-flash");
        assert_eq!(gemini.modality_label(), "text+image+audio → text");
        assert_eq!(gemini.context_label(), "1048k context");
        assert_eq!(gemini.price_label(), "$0.30 / $2.50 per 1M");
        assert_eq!(gemini.source, Some(Source::ModelsDev));
        assert!(gemini.line().contains("models.dev"));
        // An OpenRouter vendor prefix still resolves.
        assert_eq!(registry.lookup(Provider::OpenAI, "openai/gpt-4o").modality_label(), "text+image → text");
        // A provider with no metadata is not guessed.
        assert!(registry.lookup(Provider::Groq, "llama-3.3-70b").is_empty());
    }

    #[test]
    fn zero_price_reads_free_and_status_is_labelled() {
        // Shape taken from the live models.dev schema: retirement is `status`,
        // there is no `deprecated` boolean.
        let body = json!({"xai": {"models": {"grok-fast": {
            "name": "Grok Fast", "type": "chat", "status": "deprecated",
            "modalities": {"input": ["text"], "output": ["text"]},
            "limit": {"context": 131072, "input": 131072, "output": 8192},
            "cost": {"input": 0.0, "output": 0.0},
            "release_date": "2025-02-01", "last_updated": "2025-09-01"
        }}}});
        let meta = parse_models_dev(&body).lookup(Provider::Grok, "grok-fast");
        assert_eq!(meta.price_label(), "free");
        assert_eq!(meta.status.as_deref(), Some("deprecated"));
        assert_eq!(meta.kind.as_deref(), Some("chat"));
        assert_eq!(meta.deprecation.as_deref(), Some("marked deprecated"));
        assert!(meta.line().contains("marked deprecated"));
        // A boolean `deprecated` is not part of the schema and must be ignored.
        let stale = json!({"xai": {"models": {"grok-old": {"deprecated": true}}}});
        assert_eq!(parse_models_dev(&stale).lookup(Provider::Grok, "grok-old").status, None);
    }

    fn strings(ids: &[&str]) -> Vec<String> { ids.iter().map(|id| (*id).to_owned()).collect() }

    fn registry_with(entries: &[(&str, &str, Option<&str>)]) -> Registry {
        let mut models = serde_json::Map::new();
        for (id, kind, status) in entries {
            let mut entry = serde_json::json!({"name": id, "type": kind});
            if let Some(status) = status { entry["status"] = json!(status); }
            models.insert((*id).to_owned(), entry);
        }
        parse_models_dev(&json!({"openrouter": {"models": models}}))
    }

    #[test]
    fn sweep_only_acts_on_positive_evidence() {
        // `brand-new-private-model` is listed by the provider but unknown to
        // models.dev; it is not in `added`, so it must not disturb anything.
        let added = strings(&["live-model", "retired-model", "deprecated-model"]);
        let live = strings(&["live-model", "deprecated-model", "brand-new-private-model"]);
        let meta = registry_with(&[
            ("live-model", "chat", None),
            ("deprecated-model", "chat", Some("deprecated")),
            // models.dev still lists it: the provider dropped it, so it is gone.
            ("retired-model", "chat", None),
        ]);
        let verdict = sweep(Provider::OpenRouter, &added, Some(&live), Some(&meta));
        assert!(verdict.provider_checked);
        assert_eq!(verdict.gone[0], SweepVerdict {
            model: "retired-model".to_owned(), reason: SweepReason::GoneFromProvider,
        });
        assert!(verdict.gone[0].reason.is_evidence());
        // Present but deprecated: gone for a different, recorded reason.
        assert_eq!(verdict.gone[1].reason, SweepReason::Deprecated);
        assert_eq!(verdict.gone.len(), 2);
        // A model the live list still carries is never touched, and one absent
        // from a successful list is evidence, not an unknown.
        assert!(verdict.unknown.is_empty(), "{:?}", verdict.unknown);
        assert_eq!(verdict.ids(), strings(&["retired-model", "deprecated-model"]));
        assert!(verdict.summary().contains("2 gone"));
        assert!(!verdict.summary().contains("unverified"));
    }

    #[test]
    fn sweep_does_not_guess_when_the_provider_did_not_answer() {
        // A failed /models fetch must not retire anything by absence, but a
        // models.dev deprecation is still positive evidence on its own.
        let added = strings(&["only-in-dev", "deprecated-model"]);
        let meta = registry_with(&[("deprecated-model", "chat", Some("deprecated"))]);
        let partial = sweep(Provider::OpenRouter, &added, None, Some(&meta));
        assert!(!partial.provider_checked);
        assert_eq!(partial.ids(), strings(&["deprecated-model"]));
        assert_eq!(partial.unknown, strings(&["only-in-dev"]));
        // With no metadata at all and no provider list, nothing is claimed.
        let blind = sweep(Provider::OpenRouter, &added, None, None);
        assert!(blind.gone.is_empty());
        assert_eq!(blind.unknown.len(), 2);
        assert!(blind.summary().starts_with("Sweep (models.dev)"));
        assert!(blind.summary().contains("2 unverified"));
    }

    #[test]
    fn a_model_the_provider_dropped_is_reported_as_dropped_once() {
        // Both sources have something to say; the row must get one verdict,
        // and the stronger evidence is "the provider no longer lists it".
        let added = strings(&["retired-model"]);
        let live = strings(&["live-model"]);
        let meta = registry_with(&[("retired-model", "chat", Some("deprecated"))]);
        let verdict = sweep(Provider::OpenRouter, &added, Some(&live), Some(&meta));
        assert_eq!(verdict.gone.len(), 1, "one row, one verdict: {:?}", verdict.gone);
        assert_eq!(verdict.gone[0].reason, SweepReason::Deprecated,
            "an explicit deprecation is the clearer reason");
    }

    #[test]
    fn a_hand_typed_private_model_is_never_swept_on_one_silent_source() {
        // The app lets a user add an exact ID because provider lists omit
        // private, beta and unannounced models. Such an id is absent from
        // /models *and* unknown to models.dev, so it must be reported only.
        let added = strings(&["acme/internal-preview-1"]);
        let live = strings(&["live-model"]);
        let meta = registry_with(&[("live-model", "chat", None)]);
        let verdict = sweep(Provider::OpenRouter, &added, Some(&live), Some(&meta));
        assert!(verdict.gone.is_empty(), "must not disable: {:?}", verdict.gone);
        assert_eq!(verdict.unlisted, added);
        assert!(!SweepReason::Unlisted.is_evidence());
        assert_eq!(verdict.ids(), Vec::<String>::new());
        assert!(verdict.summary().contains("1 unlisted"));
        assert!(verdict.summary().contains("nothing is confirmed gone"));
    }

    #[test]
    fn sweep_reads_a_vendor_prefixed_id_and_keeps_listed_models() {
        let added = strings(&["anthropic/claude-sonnet-4", "openai/gpt-4o"]);
        let live = strings(&["claude-sonnet-4", "gpt-4o"]);
        let body = json!({"openrouter": {"models": {
            "anthropic/claude-sonnet-4": {"type": "chat", "modalities": {"input": ["text"], "output": ["text"]}},
            "openai/gpt-4o": {"type": "chat"}
        }}});
        let meta = parse_models_dev(&body);
        let verdict = sweep(Provider::OpenRouter, &added, Some(&live), Some(&meta));
        assert!(verdict.is_empty(), "listed models must survive the sweep: {:?}", verdict);
    }

    #[test]
    fn bundled_free_tier_registry_annotates_known_models() {
        let registry = local_registry();
        let entry = std::fs::read_to_string("assets/model_meta/free_tiers.json").expect("registry ships with the app");
        let document: Value = serde_json::from_str(&entry).expect("registry is valid JSON");
        let first = document["models"].as_object().expect("models map").iter().next().expect("one model");
        let meta = registry.lookup(Provider::OpenRouter, first.0);
        assert!(meta.free_tier.is_some(), "{} should carry a free-tier note", first.0);
        assert!(meta.line().contains("free tier"));
        // Unknown ids stay empty rather than claiming a free tier.
        assert!(registry.lookup(Provider::OpenRouter, "vendor/definitely-not-listed").free_tier.is_none());
    }

    #[test]
    fn meta_line_is_compact_and_source_labelled() {
        let meta = Meta {
            input_modalities: vec!["text".into()], output_modalities: vec!["text".into()],
            context: Some(128_000), cost_in: Some(1.0), cost_out: Some(2.0),
            free_tier: Some("100k tokens/day".into()), deprecation: None, status: None, kind: None,
            source: Some(Source::ModelsDev), output_limit: None,
        };
        let line = meta.line();
        assert!(line.starts_with("text → text  ·  128k context  ·  $1.00 / $2.00 per 1M"));
        assert!(line.ends_with("free tier: 100k tokens/day  ·  models.dev"));
        assert_eq!(Meta::default().line(), "");
    }

    #[test]
    fn malformed_documents_do_not_panic() {
        assert!(parse_models_dev(&json!("nope")).is_empty());
        assert!(parse_models_dev(&json!({"openai": {"models": "nope"}})).is_empty());
        assert!(parse_models_dev(&json!({"openai": {"models": {"m": {"limit": {"context": -5}}}}}))
            .lookup(Provider::OpenAI, "m").context.is_none());
    }
}
