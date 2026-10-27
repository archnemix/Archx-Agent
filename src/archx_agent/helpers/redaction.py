"""Secret redaction.

Two layers of protection:

1. Pattern matching for well-known credential shapes.
2. A registry of literal secret values (API keys handed to us at runtime) which
   are replaced even if they do not match a known pattern.

Everything that can leave the process - traces, exports, reports, error
messages, logs - goes through :func:`redact`.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

REDACTED = "[REDACTED]"

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}\b")),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("huggingface", re.compile(r"\bhf_[A-Za-z0-9]{20,}\b")),
    ("slack", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{12,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
    ("auth_header", re.compile(r"(?i)\b(authorization|api[_-]?key|x-api-key)\s*[:=]\s*[\"']?([^\s\"',;}]{6,})")),
    ("url_credentials", re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)([^/\s:@]+):([^/\s@]+)@")),
    ("secret_assignment", re.compile(r"(?i)\b(password|passwd|secret|token|api_key|apikey)\s*[:=]\s*[\"']?([^\s\"',;}]{4,})")),
]

_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "secret",
    "password",
    "passwd",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "auth",
    "credential",
    "credentials",
    "private_key",
    "client_secret",
    "session_key",
    "cookie",
    "set-cookie",
}

_REFERENCE_RE = re.compile(r"(?i)\b(?:secret|credential)://[A-Za-z0-9_.\-/]+")
_REFERENCE_TOKEN = "\x00archx-secret-ref\x00"

_registered_secrets: set[str] = set()
MAX_SCAN_LEN = 1_000_000


def register_secret(value: str) -> None:
    """Register a literal secret so it is redacted wherever it appears."""
    if value and len(value) >= 4:
        _registered_secrets.add(value)


def clear_registered_secrets() -> None:
    _registered_secrets.clear()


def registered_secret_count() -> int:
    return len(_registered_secrets)


def redact_text(text: str) -> str:
    if not text:
        return text
    out = text[:MAX_SCAN_LEN]
    # secret:// schemes are *references*; they are safe to keep and must not be
    # mistaken for the value they point at.
    references = _REFERENCE_RE.findall(out)
    for index, reference in enumerate(references):
        out = out.replace(reference, f"{_REFERENCE_TOKEN}{index}\x00")
    for secret in _registered_secrets:
        if secret in out:
            out = out.replace(secret, REDACTED)
    for _name, pattern in _PATTERNS:
        if _name in ("auth_header", "url_credentials", "secret_assignment"):
            def _replace_group(match: re.Match[str]) -> str:
                groups = match.groups()
                head = groups[0] or ""
                sep = ":" if _name == "url_credentials" else match.group(0)[len(head):len(head) + 1]
                if _name == "url_credentials":
                    return f"{head}{groups[1]}:{REDACTED}@"
                return f"{head}{sep}{REDACTED}"

            out = pattern.sub(_replace_group, out)
        else:
            out = pattern.sub(REDACTED, out)
    for index, reference in enumerate(references):
        out = out.replace(f"{_REFERENCE_TOKEN}{index}\x00", reference)
    return out


def looks_secret(value: str) -> bool:
    if not value or len(value) < 8:
        return False
    if value in _registered_secrets:
        return True
    candidate = _REFERENCE_RE.sub("secret-ref", value)
    return any(p.fullmatch(candidate) or p.search(candidate) for _, p in _PATTERNS)


def redact(value: Any, *, _depth: int = 0) -> Any:
    """Recursively redact strings and sensitive keys in mappings."""
    if _depth > 12:
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in _SENSITIVE_KEYS:
                out[k] = REDACTED
            else:
                out[k] = redact(v, _depth=_depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v, _depth=_depth + 1) for v in value]
    if isinstance(value, set):
        return sorted(redact(v, _depth=_depth + 1) for v in value)
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    return value


def find_secrets_in(text: str, needles: Iterable[str]) -> list[str]:
    """Return the needles that appear in ``text`` (used by export guards/tests)."""
    return [n for n in needles if n and n in text]


def assert_redacted(text: str) -> None:
    """Raise ``AssertionError`` if ``text`` still contains a known secret."""
    leaked = find_secrets_in(text, _registered_secrets)
    if leaked:
        raise AssertionError(f"artifact leaks {len(leaked)} registered secret(s)")


__all__ = [
    "REDACTED",
    "register_secret",
    "clear_registered_secrets",
    "registered_secret_count",
    "redact_text",
    "redact",
    "looks_secret",
    "find_secrets_in",
    "assert_redacted",
]
