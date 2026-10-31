"""Embeddings operations for workspace composition."""

from __future__ import annotations

import os

from archx_agent.adapters.embedding_runtime import (
    EmbeddingProvider,
    HashEmbeddingProvider,
    HttpEmbeddingProvider,
    SentenceTransformerProvider,
)
from archx_agent.helpers.config import Config


def _build_embedding_provider(
    config: Config,
) -> tuple[EmbeddingProvider | None, str | None]:
    """Build the embedding provider, or explain why there is none.

    Remote embeddings are off by default and always require an explicit
    preference; we never silently send memory text to a remote service.
    """
    if not config.get("memory.embeddings_enabled"):
        return None, None
    kind = (config.get("memory.embedding_provider") or "local-hash").lower()
    if kind in ("local-hash", "hash", "archx-hash"):
        try:
            return HashEmbeddingProvider(), None
        except Exception as exc:  # noqa: BLE001
            return None, f"local hash embeddings unavailable: {exc}"
    if kind in ("http", "http-embeddings"):
        base_url = os.environ.get("ARCHX_EMBEDDING_BASE_URL", "")
        model = os.environ.get("ARCHX_EMBEDDING_MODEL", "")
        if not base_url or not model:
            return None, (
                "memory.embedding_provider=http needs ARCHX_EMBEDDING_BASE_URL and ARCHX_EMBEDDING_MODEL"
            )
        if not config.get("memory.remote_embeddings") and base_url.startswith(
            ("http://", "https://")
        ):
            host = base_url.split("//")[-1].split("/")[0].split(":")[0]
            if host not in ("127.0.0.1", "localhost", "::1"):
                return None, (
                    "remote embedding endpoint configured but memory.remote_embeddings is false; "
                    "embeddings are disabled"
                )
        api_key = os.environ.get("ARCHX_EMBEDDING_API_KEY")
        try:
            return HttpEmbeddingProvider(base_url, model=model, api_key=api_key), None
        except Exception as exc:  # noqa: BLE001
            return None, f"http embedding provider failed to initialise: {exc}"
    if kind in ("sentence-transformers", "st"):
        try:
            return SentenceTransformerProvider(), None
        except Exception as exc:  # noqa: BLE001
            return None, (
                f"local semantic embeddings unavailable ({exc}); "
                "keyword retrieval stays active and is reported as degraded"
            )
    return None, f"unknown embedding provider {kind!r}; semantic retrieval disabled"
