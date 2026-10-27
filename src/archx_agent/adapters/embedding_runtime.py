"""Embedding providers.

Three implementations, each honest about what it is:

* ``HashEmbeddingProvider`` - deterministic, dependency-free, **lexical features
  only**. It is *not* semantic: it hashes character n-grams and words. It exists
  so embeddings, storage, migration and evaluation work offline and so the
  degraded path is real. Results are labelled ``lexical-hash``.
* ``HttpEmbeddingProvider`` - a real client for OpenAI-compatible
  ``POST /v1/embeddings``. Remote and local endpoints both work; remote use is
  gated by the ``memory.remote_embeddings`` preference upstream.
* ``SentenceTransformerProvider`` - optional real local semantic model (e.g.
  ``BAAI/bge-small-en-v1.5``, 384-dim, MIT, CPU-friendly). Only available when
  ``sentence-transformers`` and the model weights are present.

A provider always reports ``model_id`` and ``dim``; vectors from different
models are never mixed.
"""

from __future__ import annotations

import hashlib
import json
import math
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable

from archx_agent.helpers.exceptions import (
    MalformedOutputError,
    NetworkFailureError,
    ProviderError,
    UnsupportedOperationError,
    ValidationError,
)
from archx_agent.helpers.redaction import register_secret
from archx_agent.helpers.vectors import normalize


@dataclass
class EmbeddingResult:
    vectors: list[list[float]]
    model_id: str
    dim: int
    provider: str
    semantic: bool
    prompt_tokens: int = 0
    latency_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "count": len(self.vectors),
            "model_id": self.model_id,
            "dim": self.dim,
            "provider": self.provider,
            "semantic": self.semantic,
            "prompt_tokens": self.prompt_tokens,
            "latency_ms": self.latency_ms,
        }


@dataclass
class EmbeddingHealth:
    ok: bool
    detail: str
    model_id: str
    dim: int
    semantic: bool


@runtime_checkable
class EmbeddingProvider(Protocol):
    provider_id: str
    model_id: str
    dim: int
    semantic: bool
    is_local: bool

    def embed(self, texts: Sequence[str]) -> EmbeddingResult: ...

    def health(self) -> EmbeddingHealth: ...


class HashEmbeddingProvider:
    """Deterministic lexical-hash embeddings (no model, no download).

    Documented behaviour: not semantic. Two sentences that mean the same thing
    in different words will not be close. It is useful for reproducible tests,
    storage plumbing and a measurable baseline - nothing more.
    """

    provider_id = "local-hash"
    model_id = "archx-hash-v1"
    is_local = True
    semantic = False

    def __init__(self, dim: int = 256) -> None:
        if dim < 32 or dim > 4096:
            raise ValidationError("embedding dimension must be between 32 and 4096")
        self.dim = dim

    def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        if not isinstance(texts, (list, tuple)):
            raise ValidationError("embed() expects a sequence of strings")
        vectors = []
        for text in texts:
            if not isinstance(text, str):
                raise ValidationError("embedding input must be strings")
            vectors.append(self._vector(text))
        return EmbeddingResult(
            vectors=vectors,
            model_id=self.model_id,
            dim=self.dim,
            provider=self.provider_id,
            semantic=False,
        )

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        tokens = _tokenize(text)
        if not tokens:
            vector[0] = 1.0
            return vector
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            weight = 1.0 / math.sqrt(len(tokens))
            vector[index] += sign * weight
            # character trigrams give a little robustness to typos/inflection
            if len(token) > 3:
                for i in range(len(token) - 2):
                    tri = token[i : i + 3]
                    d2 = hashlib.blake2b(tri.encode("utf-8"), digest_size=8).digest()
                    idx2 = int.from_bytes(d2[:4], "little") % self.dim
                    vector[idx2] += (1.0 if d2[4] % 2 == 0 else -1.0) * 0.35 * weight
        return normalize(vector)

    def health(self) -> EmbeddingHealth:
        return EmbeddingHealth(
            ok=True,
            detail="deterministic lexical-hash embeddings (not semantic)",
            model_id=self.model_id,
            dim=self.dim,
            semantic=False,
        )


class HttpEmbeddingProvider:
    """OpenAI-compatible ``/v1/embeddings`` client (remote or local server)."""

    provider_id = "http-embeddings"
    is_local = False
    semantic = True

    def __init__(
        self,
        base_url: str,
        *,
        model: str,
        api_key: str | None = None,
        dim: int | None = None,
        timeout: float = 60.0,
        is_local: bool | None = None,
        provider_id: str = "http-embeddings",
    ) -> None:
        if not base_url or not model:
            raise ValidationError("embedding endpoint requires base_url and model")
        self.base_url = base_url.rstrip("/")
        self.model_id = model
        self.dim = dim or 0  # discovered on first successful call
        self.timeout = timeout
        self.provider_id = provider_id
        self._api_key = api_key
        if api_key:
            register_secret(api_key)
        if is_local is None:
            host = self.base_url.split("//")[-1].split("/")[0].split(":")[0]
            is_local = host in ("127.0.0.1", "localhost", "::1")
        self.is_local = bool(is_local)

    def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        import time

        if not texts:
            return EmbeddingResult([], self.model_id, self.dim, self.provider_id, True)
        body = json.dumps({"model": self.model_id, "input": list(texts)}).encode()
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        path = "/v1/embeddings" if not self.base_url.endswith("/v1") else "/embeddings"
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=body, headers=headers, method="POST"
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise ProviderError(
                f"embedding endpoint returned HTTP {exc.code}", provider=self.provider_id
            ) from None
        except (socket.timeout, TimeoutError) as exc:
            raise NetworkFailureError("embedding request timed out", provider=self.provider_id) from exc
        except urllib.error.URLError as exc:
            raise NetworkFailureError(
                f"cannot reach embedding endpoint: {exc.reason}", provider=self.provider_id
            ) from exc
        try:
            data = json.loads(raw)
            entries = data["data"]
            vectors = [entry["embedding"] for entry in entries]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise MalformedOutputError("embedding response is malformed", provider=self.provider_id) from exc
        if len(vectors) != len(texts):
            raise MalformedOutputError(
                f"asked for {len(texts)} embeddings, received {len(vectors)}", provider=self.provider_id
            )
        dim = len(vectors[0])
        if any(len(v) != dim for v in vectors):
            raise MalformedOutputError("inconsistent embedding dimensions in one response", provider=self.provider_id)
        if self.dim and self.dim != dim:
            raise MalformedOutputError(
                f"endpoint changed dimension from {self.dim} to {dim}; vectors are not comparable",
                provider=self.provider_id,
            )
        self.dim = dim
        usage = data.get("usage") or {}
        return EmbeddingResult(
            vectors=[normalize([float(x) for x in v]) for v in vectors],
            model_id=self.model_id,
            dim=dim,
            provider=self.provider_id,
            semantic=True,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    def health(self) -> EmbeddingHealth:
        try:
            result = self.embed(["health check"])
        except ProviderError as exc:
            return EmbeddingHealth(False, f"{type(exc).__name__}: {exc.message}", self.model_id, self.dim, True)
        return EmbeddingHealth(True, "endpoint reachable", result.model_id, result.dim, True)


class SentenceTransformerProvider:
    """Local semantic embeddings when the optional stack is installed."""

    provider_id = "sentence-transformers"
    is_local = True
    semantic = True

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5", *, query_prefix: str = "") -> None:
        self.model_id = model
        self.query_prefix = query_prefix
        self._model = None
        self.dim = 0
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except Exception as exc:  # noqa: BLE001 - optional dependency
            raise UnsupportedOperationError(
                f"sentence-transformers is not installed ({exc}); "
                "install it with `pip install sentence-transformers` for local semantic embeddings"
            ) from exc
        self._model = SentenceTransformer(model)
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        if not text_list_ok(texts):
            raise ValidationError("embedding input must be strings")
        import time

        started = time.perf_counter()
        vectors = self._model.encode([self.query_prefix + t for t in texts], normalize_embeddings=True)
        return EmbeddingResult(
            vectors=[[float(x) for x in v] for v in vectors],
            model_id=self.model_id,
            dim=self.dim,
            provider=self.provider_id,
            semantic=True,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    def health(self) -> EmbeddingHealth:
        return EmbeddingHealth(True, "local semantic model loaded", self.model_id, self.dim, True)


def text_list_ok(texts: Sequence[str]) -> bool:
    return isinstance(texts, (list, tuple)) and all(isinstance(t, str) for t in texts)


def _tokenize(text: str) -> list[str]:
    import re

    words = re.findall(r"[a-z0-9_]{2,}", text.lower())
    return words


def build_provider(kind: str, **kwargs) -> EmbeddingProvider:
    if kind in ("hash", "local-hash", "archx-hash"):
        return HashEmbeddingProvider(**kwargs)
    if kind in ("http", "http-embeddings"):
        return HttpEmbeddingProvider(**kwargs)
    if kind in ("sentence-transformers", "st"):
        return SentenceTransformerProvider(**kwargs)
    raise ValidationError(
        f"unknown embedding provider {kind!r} (expected hash, http or sentence-transformers)"
    )


__all__ = [
    "EmbeddingProvider",
    "EmbeddingResult",
    "EmbeddingHealth",
    "HashEmbeddingProvider",
    "HttpEmbeddingProvider",
    "SentenceTransformerProvider",
    "build_provider",
]
