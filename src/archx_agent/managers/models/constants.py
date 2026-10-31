"""ModelManager constants."""

from __future__ import annotations

import re


MODEL_TABLES = ("models", "model_capability_tests")

STATES = ("usable", "disabled", "missing", "invalid", "removed")

VERIFICATION_STATES = (
    "verified",
    "inferred",
    "unverified",
    "unsupported",
    "unavailable",
)

CAPABILITY_STATES = ("verified", "inferred", "unverified", "unsupported", "unavailable")

RUNTIME_BASELINE_CAPABILITIES: dict[str, frozenset[str]] = {
    "llama-cpp": frozenset({"chat", "streaming"}),
    "openai-http": frozenset({"chat", "streaming"}),
    "http": frozenset({"chat", "streaming"}),
    "scripted": frozenset({"chat", "streaming"}),
}

_QUANT_RE = re.compile(
    r"(?i)\b(i?q\d(?:_[a-z0-9]+)*|f16|bf16|f32|q8_0|q4_k_m|q5_k_m)\b"
)

_PARAM_RE = re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*[bBmM]\b")
