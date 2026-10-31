"""The model runtime interface.

Every runtime - local in-process, local HTTP server, cloud provider - implements
this protocol so routing, tracing and permissions stay uniform.

Contract
--------
``capabilities`` lists operations the runtime *can* perform. It is never derived
from "the model is multimodal"; the model catalogue records verified facts and
claims separately, and the router only routes on verified facts (M21).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol, Sequence, runtime_checkable

from archx_agent.helpers.tokens import Tokenizer

CAPABILITIES = (
    "chat",
    "completion",
    "embeddings",
    "rerank",
    "ocr",
    "transcription",
    "speech_synthesis",
    "image_generation",
    "image_edit",
    "video_generation",
    "audio_generation",
    "vision",
)


@dataclass
class ModelSpec:
    """What to load. ``path`` is a local file, ``model`` a remote identifier."""

    id: str
    provider: str
    runtime: str
    path: str | None = None
    model: str | None = None
    context_length: int = 2048
    quantization: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def display(self) -> str:
        return self.model or self.path or self.id


@dataclass
class GenerationParams:
    temperature: float = 0.2
    top_p: float = 0.95
    max_tokens: int = 512
    stop: Sequence[str] = ()
    seed: int | None = None
    stream: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "stop": list(self.stop),
            "seed": self.seed,
        }


@dataclass
class ChatResult:
    text: str
    model_id: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str = "stop"
    latency_ms: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "model_id": self.model_id,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "finish_reason": self.finish_reason,
            "latency_ms": self.latency_ms,
        }


@dataclass
class RuntimeHealth:
    ok: bool
    detail: str
    loaded: bool = False
    capabilities: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "detail": self.detail, "loaded": self.loaded, "capabilities": list(self.capabilities)}


@runtime_checkable
class ModelRuntime(Protocol):
    runtime_id: str
    provider: str
    is_local: bool
    supports_streaming: bool

    def available(self) -> tuple[bool, str]: ...

    def load(self, spec: ModelSpec) -> None: ...

    def unload(self) -> None: ...

    def health(self) -> RuntimeHealth: ...

    def chat(self, messages: Sequence[dict[str, str]], params: GenerationParams) -> ChatResult: ...

    def stream(self, messages: Sequence[dict[str, str]], params: GenerationParams) -> Iterator[str]: ...

    def tokenizer(self) -> Tokenizer | None: ...

    def close(self) -> None: ...


class BaseRuntime:
    """Shared plumbing: model bookkeeping, capability declaration, close()."""

    def available(self) -> tuple[bool, str]:
        """Can this runtime run at all in this environment? ``(ok, reason_if_not)``.

        This is a cheap check (an import, a file's existence, a setting) - it must never
        load weights or open a socket. The router uses it so it cannot offer a model whose
        runtime is missing."""
        return True, "ready"

    runtime_id = "base"
    provider = "base"
    is_local = True
    supports_streaming = False
    _capabilities: frozenset[str] = frozenset({"chat"})

    def __init__(self) -> None:
        self.spec: ModelSpec | None = None

    def capabilities(self) -> frozenset[str]:
        return self._capabilities

    def load(self, spec: ModelSpec) -> None:  # pragma: no cover - overridden
        self.spec = spec

    def unload(self) -> None:
        self.spec = None

    def health(self) -> RuntimeHealth:  # pragma: no cover - overridden
        raise NotImplementedError

    def chat(self, messages: Sequence[dict[str, str]], params: GenerationParams) -> ChatResult:
        raise NotImplementedError

    def stream(self, messages: Sequence[dict[str, str]], params: GenerationParams) -> Iterator[str]:
        result = self.chat(messages, params)
        yield result.text

    def tokenizer(self) -> Tokenizer | None:
        return None

    def close(self) -> None:
        self.unload()

    @property
    def loaded(self) -> bool:
        return self.spec is not None


def validate_capability(capability: str) -> str:
    if capability not in CAPABILITIES:
        raise ValueError(f"unknown capability {capability!r} (expected one of {list(CAPABILITIES)})")
    return capability


__all__ = [
    "ModelRuntime",
    "BaseRuntime",
    "ModelSpec",
    "GenerationParams",
    "ChatResult",
    "RuntimeHealth",
    "CAPABILITIES",
    "validate_capability",
]
