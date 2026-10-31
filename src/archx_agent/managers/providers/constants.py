"""Vocabulary and defaults for provider metadata."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.urls import is_loopback_url as is_loopback_url


PROVIDER_TABLES = ("providers", "provider_checks", "provider_usage")

_SELECT = (
    "SELECT id, name, slug, kind, api_style, base_url, model_family,"
    " credential_ref AS auth_ref, is_local, enabled, privacy AS privacy_claims,"
    " COALESCE(privacy_confirmed, '{}') AS privacy_confirmed, claim_source,"
    " verified AS claims_verified, price_in_per_1k, price_out_per_1k,"
    " COALESCE(currency, '') AS currency, notes, consent_at, consent_version,"
    " COALESCE(quotas, '{}') AS quotas, created_at, updated_at"
    " FROM providers"
)

KINDS = ("local", "cloud", "custom")

API_STYLES = ("openai", "anthropic", "gemini", "custom")

CONSENT_VERSION = "2026-10-1"

PRIVACY_FIELDS = ("data_leaves_device", "training_use", "retention", "region")

KNOWN_PROVIDERS: dict[str, dict[str, Any]] = {
    "openai": {
        "label": "OpenAI API",
        "kind": "cloud",
        "api_style": "openai",
        "base_url": "https://api.openai.com/v1",
        "model_family": "gpt",
        "is_local": False,
        "privacy_claims": {
            "data_leaves_device": True,
            "training_use": "vendor states API data is not used to train models by default",
            "retention": "vendor states abuse-monitoring logs are retained for up to 30 days",
            "region": "vendor-defined; may process outside your country",
        },
        "claim_source": "vendor API documentation (not verified in this environment)",
    },
    "anthropic": {
        "label": "Anthropic API",
        "kind": "cloud",
        "api_style": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model_family": "claude",
        "is_local": False,
        "privacy_claims": {
            "data_leaves_device": True,
            "training_use": "vendor states API inputs are not used for training by default",
            "retention": "vendor states inputs may be retained briefly for abuse monitoring",
            "region": "vendor-defined; may process outside your country",
        },
        "claim_source": "vendor documentation (not verified in this environment)",
    },
    "google": {
        "label": "Google Gemini API",
        "kind": "cloud",
        "api_style": "gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "model_family": "gemini",
        "is_local": False,
        "privacy_claims": {
            "data_leaves_device": True,
            "training_use": "unknown without reading the current terms; do not assume either way",
            "retention": "unknown without reading the current terms",
            "region": "vendor-defined",
        },
        "claim_source": "vendor documentation (not verified in this environment)",
    },
    # The four below ship the endpoint and the wire style only. Their privacy terms are
    # deliberately absent: transcribing a vendor's current policy from memory is exactly the
    # kind of claim this catalogue refuses to make, so the user confirms the terms they read
    # (`providers confirm`), and the refusal names that step.
    "groq": {
        "label": "Groq API",
        "kind": "cloud",
        "api_style": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "model_family": "llama, mixtral, qwen",
        "is_local": False,
        "privacy_claims": {
            "data_leaves_device": True,
            "training_use": "not transcribed here - read the vendor's terms before sending data",
            "retention": "not transcribed here - read the vendor's terms before sending data",
            "region": "vendor-defined",
        },
        "claim_source": "endpoint only; privacy terms not transcribed (confirm them yourself)",
    },
    "together": {
        "label": "Together AI",
        "kind": "cloud",
        "api_style": "openai",
        "base_url": "https://api.together.xyz/v1",
        "model_family": "open models",
        "is_local": False,
        "privacy_claims": {
            "data_leaves_device": True,
            "training_use": "not transcribed here - read the vendor's terms before sending data",
            "retention": "not transcribed here - read the vendor's terms before sending data",
            "region": "vendor-defined",
        },
        "claim_source": "endpoint only; privacy terms not transcribed (confirm them yourself)",
    },
    "cohere": {
        "label": "Cohere",
        "kind": "cloud",
        "api_style": "custom",
        "base_url": "https://api.cohere.com",
        "model_family": "command, embed",
        "is_local": False,
        "privacy_claims": {
            "data_leaves_device": True,
            "training_use": "not transcribed here - read the vendor's terms before sending data",
            "retention": "not transcribed here - read the vendor's terms before sending data",
            "region": "vendor-defined",
        },
        "claim_source": "endpoint only; privacy terms not transcribed (confirm them yourself)",
    },
    "mistral": {
        "label": "Mistral AI",
        "kind": "cloud",
        "api_style": "openai",
        "base_url": "https://api.mistral.ai",
        "model_family": "mistral, codestral",
        "is_local": False,
        "privacy_claims": {
            "data_leaves_device": True,
            "training_use": "not transcribed here - read the vendor's terms before sending data",
            "retention": "not transcribed here - read the vendor's terms before sending data",
            "region": "vendor-defined",
        },
        "claim_source": "endpoint only; privacy terms not transcribed (confirm them yourself)",
    },
    # Any third-party endpoint that speaks the OpenAI shape (Z.ai, DeepSeek, a company gateway).
    # The privacy block is deliberately empty of vendor specifics: inventing terms for a vendor is
    # worse than making the user state them, and `providers confirm` exists for exactly that.
    "openai-compatible": {
        "label": "Any OpenAI-compatible endpoint",
        "kind": "cloud",
        "api_style": "openai",
        "base_url": "",  # required: there is no default for "somebody else's server"
        "model_family": "whatever the endpoint serves",
        "is_local": False,
        "privacy_claims": {
            "data_leaves_device": True,
            "training_use": "unknown - not transcribed; ask the provider before sending data",
            "retention": "unknown - not transcribed; ask the provider before sending data",
            "region": "unknown",
        },
        "claim_source": "no claims recorded; run `providers confirm` with the terms you read",
    },
    "ollama": {
        "label": "Ollama (local daemon or Ollama Cloud)",
        "kind": "custom",
        # The daemon is on this machine; the cloud endpoint is not. `is_local` is derived from
        # the URL at registration, so this template does not get to decide.
        "api_style": "custom",
        "base_url": "http://127.0.0.1:11434",
        "model_family": "whatever you have pulled",
        "is_local": True,
        "privacy_claims": {
            "data_leaves_device": False,
            "training_use": "no: prompts stay on this machine when the daemon is local",
            "retention": "n/a on your own disk; Ollama Cloud would differ and is not assumed here",
            "region": "this machine",
        },
        "claim_source": "endpoint only; a loopback daemon sends nothing off the machine",
    },
    "openai-compatible-local": {
        "label": "Local OpenAI-compatible server (llama.cpp, Ollama, vLLM, LM Studio)",
        "kind": "local",
        "api_style": "openai",
        "base_url": "http://127.0.0.1:8080/v1",
        "model_family": "",
        "is_local": True,
        "privacy_claims": {
            "data_leaves_device": False,
            "training_use": "no; the server runs on this machine",
            "retention": "whatever your own server logs",
            "region": "this machine",
        },
        "claim_source": "derived from the loopback URL (a fact, not a vendor claim)",
    },
}
