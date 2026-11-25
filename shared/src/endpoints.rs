//! Purpose: Holds each provider's chat, streaming and model-list URLs as visible, editable templates.
//!
//! A provider can move a path (or a user may be behind a compatible gateway).
//! Hard-coding those URLs meant any change needed a new app build. Every URL is
//! therefore a template shown in Settings with its current value, editable, and
//! resettable to the documented default. `{model}` is substituted for the model
//! id. Only HTTPS (or HTTP on loopback) is accepted, with no embedded credentials.

use serde_json::{json, Value};
use zeroize::Zeroizing;

use archx_shared::credentials::Provider;

#[derive(Clone, PartialEq, Eq)]
pub struct Template {
    pub chat: &'static str,
    pub stream: &'static str,
    pub models: &'static str,
}

/// Documented defaults. `{model}` is replaced with the selected model id.
pub fn default_template(provider: Provider) -> Template {
    match provider {
        Provider::OpenRouter => Template {
            chat: "https://openrouter.ai/api/v1/chat/completions",
            stream: "https://openrouter.ai/api/v1/chat/completions",
            models: "https://openrouter.ai/api/v1/models",
        },
        Provider::Grok => Template {
            chat: "https://api.x.ai/v1/chat/completions",
            stream: "https://api.x.ai/v1/chat/completions",
            models: "https://api.x.ai/v1/language-models",
        },
        Provider::Gemini => Template {
            chat: "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            stream: "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse",
            models: "https://generativelanguage.googleapis.com/v1beta/models",
        },
        Provider::OpenAI => Template {
            chat: "https://api.openai.com/v1/chat/completions",
            stream: "https://api.openai.com/v1/chat/completions",
            models: "https://api.openai.com/v1/models",
        },
        Provider::Anthropic => Template {
            chat: "https://api.anthropic.com/v1/messages",
            stream: "https://api.anthropic.com/v1/messages",
            models: "https://api.anthropic.com/v1/models",
        },
        Provider::Groq => Template {
            chat: "https://api.groq.com/openai/v1/chat/completions",
            stream: "https://api.groq.com/openai/v1/chat/completions",
            models: "https://api.groq.com/openai/v1/models",
        },
        Provider::Zai => Template {
            chat: "https://api.z.ai/api/paas/v4/chat/completions",
            stream: "https://api.z.ai/api/paas/v4/chat/completions",
            models: "https://api.z.ai/api/paas/v4/models",
        },
        Provider::OllamaLocal => Template {
            chat: "http://127.0.0.1:11434/v1/chat/completions",
            stream: "http://127.0.0.1:11434/v1/chat/completions",
            models: "http://127.0.0.1:11434/api/tags",
        },
        Provider::OllamaCloud => Template {
            chat: "https://ollama.com/v1/chat/completions",
            stream: "https://ollama.com/v1/chat/completions",
            models: "https://ollama.com/api/tags",
        },
        Provider::Custom => Template { chat: "", stream: "", models: "" },
    }
}

/// Which of the three URLs an override replaces.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Chat,
    Stream,
    Models,
}

impl Kind {
    pub fn label(self) -> &'static str {
        match self {
            Self::Chat => "Chat URL",
            Self::Stream => "Streaming URL",
            Self::Models => "Model list URL",
        }
    }
    fn index(self) -> usize {
        match self { Self::Chat => 0, Self::Stream => 1, Self::Models => 2 }
    }
}

/// A URL that has passed validation: HTTPS, or HTTP on loopback only.
pub fn validate(raw: &str, requires_model_slot: bool) -> Result<(), &'static str> {
    let raw = raw.trim();
    if raw.is_empty() { return Err("Enter a URL."); }
    if raw.len() > 512 { return Err("URL is too long (512 characters maximum)."); }
    let (scheme, rest) = raw.split_once("://").ok_or("Include https:// in the URL.")?;
    if !matches!(scheme, "https" | "http") { return Err("Only https:// URLs are accepted (http:// is limited to loopback)."); }
    if rest.contains('@') { return Err("Remove embedded credentials from the URL; keys come from the OS vault."); }
    if rest.contains('#') { return Err("Remove the URL fragment."); }
    let host = rest.split(['/', '?']).next().unwrap_or("");
    if host.is_empty() { return Err("The URL needs a host."); }
    let hostname = host.split(':').next().unwrap_or("");
    let loopback = matches!(hostname, "localhost" | "127.0.0.1" | "[::1]" | "::1");
    if scheme == "http" && !loopback { return Err("Plain HTTP is only allowed for 127.0.0.1 and localhost."); }
    if requires_model_slot && !raw.contains("{model}") { return Err("Include the {model} placeholder in the chat and streaming URLs."); }
    if raw.contains('{') && !raw.contains("{model}") { return Err("Only the {model} placeholder is supported."); }
    if raw.contains(' ') { return Err("Remove spaces from the URL."); }
    Ok(())
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Registry {
    /// Indexed by `Provider::index()`; `None` means the documented default.
    overrides: [Option<[Option<String>; 3]>; Provider::COUNT],
}

impl Registry {
    pub fn new() -> Self { Self { overrides: std::array::from_fn(|_| None) } }

    pub fn value(&self, provider: Provider, kind: Kind) -> String {
        self.overrides[provider.index()]
            .as_ref()
            .and_then(|slots| slots[kind.index()].clone())
            .unwrap_or_else(|| {
                let template = default_template(provider);
                match kind { Kind::Chat => template.chat, Kind::Stream => template.stream, Kind::Models => template.models }.to_owned()
            })
    }

    pub fn is_override(&self, provider: Provider, kind: Kind) -> bool {
        self.overrides[provider.index()].as_ref().is_some_and(|slots| slots[kind.index()].is_some())
    }

    pub fn is_default(&self, provider: Provider) -> bool {
        self.overrides[provider.index()].is_none()
    }

    pub fn set(&mut self, provider: Provider, kind: Kind, raw: &str) -> Result<(), &'static str> {
        if provider == Provider::Custom { return Err("Custom endpoints are edited in the provider form."); }
        let value = raw.trim().to_owned();
        validate(&value, matches!(kind, Kind::Chat | Kind::Stream))?;
        let slot = &mut self.overrides[provider.index()].get_or_insert_with(|| std::array::from_fn(|_| None));
        slot[kind.index()] = Some(value);
        // Setting a value back to the documented default clears the override so
        // the row stops claiming a custom route.
        if self.value(provider, kind) == default_value(provider, kind) {
            if let Some(slot) = self.overrides[provider.index()].as_mut() { slot[kind.index()] = None; }
            if self.overrides[provider.index()].as_ref().is_some_and(|slots| slots.iter().all(Option::is_none)) {
                self.overrides[provider.index()] = None;
            }
        }
        Ok(())
    }

    pub fn reset(&mut self, provider: Provider) {
        self.overrides[provider.index()] = None;
    }

    /// Restores one URL to its documented default, keeping the others.
    pub fn reset_kind(&mut self, provider: Provider, kind: Kind) {
        if let Some(slots) = self.overrides[provider.index()].as_mut() {
            slots[kind.index()] = None;
            if slots.iter().all(Option::is_none) { self.overrides[provider.index()] = None; }
        }
    }

    pub fn reset_all(&mut self) {
        self.overrides = std::array::from_fn(|_| None);
    }

    /// Substitutes the model id into the chat or streaming URL.
    pub fn resolve(&self, provider: Provider, kind: Kind, model: &str) -> String {
        self.value(provider, kind).replace("{model}", model)
    }

    pub fn host(&self, provider: Provider, kind: Kind) -> String {
        let value = self.value(provider, kind);
        value.split("://").nth(1).and_then(|rest| rest.split(['/', '?']).next()).unwrap_or("").to_owned()
    }

    pub fn to_json(&self) -> Value {
        let mut map = serde_json::Map::new();
        for provider in Provider::ALL {
            if let Some(slots) = &self.overrides[provider.index()] {
                let mut entry = serde_json::Map::new();
                for (kind, slot) in [(Kind::Chat, 0), (Kind::Stream, 1), (Kind::Models, 2)] {
                    if let Some(value) = &slots[slot] {
                        entry.insert(kind.label().into(), Value::from(value.clone()));
                    }
                }
                map.insert(provider.name().into(), Value::Object(entry));
            }
        }
        Value::Object(map)
    }

    pub fn from_json(value: &Value) -> Self {
        let mut registry = Self::new();
        for provider in Provider::ALL {
            let Some(entry) = value.get(provider.name()).and_then(Value::as_object) else { continue };
            for kind in [Kind::Chat, Kind::Stream, Kind::Models] {
                if let Some(raw) = entry.get(kind.label()).and_then(Value::as_str) {
                    // Re-validate on load: a hand-edited file cannot smuggle in
                    // a plain-HTTP remote URL.
                    if validate(raw, matches!(kind, Kind::Chat | Kind::Stream)).is_ok() {
                        let _ = registry.set(provider, kind, raw);
                    }
                }
            }
        }
        registry
    }

    /// For the Debug page: the resolved route and whether it left the default.
    pub fn describe(&self, provider: Provider, model: &str) -> String {
        format!("{} ({} route)", self.resolve(provider, Kind::Chat, model),
            if self.is_default(provider) { "documented" } else { "edited" })
    }

    /// A key placeholder used by the request builders: keys never enter a URL.
    pub fn redacted_url(&self, provider: Provider, kind: Kind, model: &str) -> String {
        Zeroizing::new(self.resolve(provider, kind, model)).to_string()
    }
}

fn default_value(provider: Provider, kind: Kind) -> String {
    let template = default_template(provider);
    match kind { Kind::Chat => template.chat, Kind::Stream => template.stream, Kind::Models => template.models }.to_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_match_the_transport_and_show_the_model_placeholder() {
        assert_eq!(Registry::new().value(Provider::OpenAI, Kind::Chat), "https://api.openai.com/v1/chat/completions");
        assert!(Registry::new().value(Provider::Gemini, Kind::Chat).contains("{model}"));
        assert_eq!(Registry::new().resolve(Provider::Gemini, Kind::Chat, "gemini-2.5-flash"),
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent");
        assert!(Registry::new().is_default(Provider::Groq));
        assert_eq!(Registry::new().host(Provider::OpenRouter, Kind::Models), "openrouter.ai");
    }

    #[test]
    fn overrides_are_validated_and_resettable() {
        let mut registry = Registry::new();
        assert_eq!(registry.set(Provider::OpenAI, Kind::Chat, "http://api.openai.com/v1/chat/completions"),
            Err("Plain HTTP is only allowed for 127.0.0.1 and localhost."));
        assert_eq!(registry.set(Provider::OpenAI, Kind::Chat, "https://user:pw@proxy.example/v1"),
            Err("Remove embedded credentials from the URL; keys come from the OS vault."));
        assert!(registry.set(Provider::OpenAI, Kind::Chat, "https://gateway.example/v1/chat/completions").is_ok());
        assert!(registry.is_override(Provider::OpenAI, Kind::Chat));
        assert!(!registry.is_default(Provider::OpenAI));
        assert_eq!(registry.value(Provider::OpenAI, Kind::Chat), "https://gateway.example/v1/chat/completions");
        registry.reset(Provider::OpenAI);
        assert_eq!(registry.value(Provider::OpenAI, Kind::Chat), "https://api.openai.com/v1/chat/completions");
        // Loopback HTTP is allowed for a local gateway.
        assert!(registry.set(Provider::OllamaLocal, Kind::Chat, "http://127.0.0.1:8080/v1/chat/completions").is_ok());
    }

    #[test]
    fn setting_the_documented_value_back_clears_the_override() {
        let mut registry = Registry::new();
        registry.set(Provider::Groq, Kind::Chat, "https://api.groq.com/openai/v1/chat/completions").unwrap();
        assert!(registry.is_default(Provider::Groq));
        assert!(!registry.is_override(Provider::Groq, Kind::Chat));
    }

    #[test]
    fn json_round_trips_and_revalidates_hostile_input() {
        let mut registry = Registry::new();
        registry.set(Provider::Gemini, Kind::Models, "https://mirror.example/v1beta/models").unwrap();
        let restored = Registry::from_json(&registry.to_json());
        assert_eq!(restored.value(Provider::Gemini, Kind::Models), "https://mirror.example/v1beta/models");
        assert_eq!(archx_shared::storage::credential_field(&registry.to_json()), None);
        // A hand-edited plain-HTTP remote URL is ignored on load.
        let hostile = json!({ "OpenAI": { "Chat URL": "http://evil.example/v1" } });
        assert!(Registry::from_json(&hostile).is_default(Provider::OpenAI));
        // An unknown provider name is ignored, not fatal.
        assert!(Registry::from_json(&json!({"Nope": {}})).is_default(Provider::OpenAI));
    }

    #[test]
    fn model_placeholder_is_required_for_chat_templates() {
        assert!(validate("https://example.com/v1/{model}", true).is_ok());
        assert_eq!(validate("https://example.com/v1/chat", true), Err("Include the {model} placeholder in the chat and streaming URLs."));
        assert!(validate("https://example.com/v1/models", false).is_ok());
        assert_eq!(validate("https://example.com/{id}", false), Err("Only the {model} placeholder is supported."));
    }
}
