"""In-process GGUF runtime via ``llama-cpp-python``.

The dependency is optional. When it is missing we raise a precise error rather
than pretending the model is usable, and the CLI reports "local runtime not
installed" with the install command.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Iterator, Sequence

from archx_agent.helpers.exceptions import (
    LocalRuntimeFailureError,
    ModelNotFoundError,
    ProviderError,
    ResourceExhaustedError,
)
from archx_agent.helpers.tokens import CallableTokenizer, Tokenizer

from .model_runtime import BaseRuntime, ChatResult, GenerationParams, ModelSpec, RuntimeHealth

INSTALL_HINT = "pip install llama-cpp-python"


def llama_cpp_available() -> bool:
    try:
        import llama_cpp  # noqa: F401
    except Exception:  # noqa: BLE001 - import may fail for unrelated native reasons
        return False
    return True


class LlamaCppRuntime(BaseRuntime):
    runtime_id = "llama-cpp"
    provider = "local-llama-cpp"
    is_local = True
    supports_streaming = True
    _capabilities = frozenset({"chat", "completion"})

    def __init__(self, *, n_threads: int | None = None, n_ctx: int | None = None, verbose: bool = False) -> None:
        super().__init__()
        self.n_threads = n_threads or max(1, min(8, (os.cpu_count() or 2)))
        self.n_ctx = n_ctx
        self.verbose = verbose
        self._model: Any = None
        self._load_error: str | None = None

    # -- lifecycle --------------------------------------------------------
    def available(self) -> tuple[bool, str]:
        if not llama_cpp_available():
            return False, f"llama-cpp-python is not installed ({INSTALL_HINT})"
        return True, "ready"

    def load(self, spec: ModelSpec) -> None:
        if not llama_cpp_available():
            self._load_error = f"llama-cpp-python is not installed ({INSTALL_HINT})"
            raise LocalRuntimeFailureError(self._load_error, provider=self.provider, model=spec.id)
        path = Path(spec.path or "")
        if not path.exists():
            self._load_error = f"model file not found: {path}"
            raise ModelNotFoundError(self._load_error, provider=self.provider, model=spec.id)
        if path.stat().st_size < 1024:
            raise ModelNotFoundError(f"model file is suspiciously small: {path}", provider=self.provider, model=spec.id)
        try:
            from llama_cpp import Llama

            self._model = Llama(
                model_path=str(path),
                n_ctx=self.n_ctx or spec.context_length,
                n_threads=self.n_threads,
                verbose=self.verbose,
            )
        except MemoryError as exc:  # pragma: no cover - environment dependent
            raise ResourceExhaustedError(
                f"not enough memory to load {path.name}", provider=self.provider, model=spec.id
            ) from exc
        except Exception as exc:  # noqa: BLE001 - native failure surfaces here
            self._load_error = f"failed to load {path.name}: {exc}"
            raise LocalRuntimeFailureError(self._load_error, provider=self.provider, model=spec.id) from exc
        self.spec = spec
        self._load_error = None

    def unload(self) -> None:
        self._model = None
        super().unload()

    def health(self) -> RuntimeHealth:
        if not llama_cpp_available():
            return RuntimeHealth(ok=False, detail=f"llama-cpp-python missing ({INSTALL_HINT})")
        if self._load_error:
            return RuntimeHealth(ok=False, detail=self._load_error)
        return RuntimeHealth(
            ok=True,
            detail="in-process llama.cpp ready" if self.loaded else "runtime available, no model loaded",
            loaded=self.loaded,
            capabilities=tuple(sorted(self._capabilities)),
        )

    def tokenizer(self) -> Tokenizer | None:
        if self._model is None:
            return None
        try:
            return CallableTokenizer(f"llama_cpp:{Path(self.spec.path).name if self.spec else 'model'}", self._model.tokenize)
        except Exception:  # noqa: BLE001
            return None

    # -- inference --------------------------------------------------------
    def chat(self, messages: Sequence[dict[str, str]], params: GenerationParams) -> ChatResult:
        if self._model is None:
            raise ProviderError("no model loaded; call load() first", provider=self.provider)
        started = time.perf_counter()
        try:
            result = self._model.create_chat_completion(
                messages=[{"role": m["role"], "content": m["content"]} for m in messages],
                temperature=params.temperature,
                top_p=params.top_p,
                max_tokens=params.max_tokens,
                stop=list(params.stop) or None,
                seed=params.seed,
                stream=False,
            )
        except MemoryError as exc:  # pragma: no cover
            raise ResourceExhaustedError("out of memory during inference", provider=self.provider) from exc
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"llama.cpp inference failed: {exc}", provider=self.provider, model=self.spec.id if self.spec else "") from exc
        latency = round((time.perf_counter() - started) * 1000, 2)
        choices = (result or {}).get("choices") or []
        if not choices:
            raise ProviderError("llama.cpp returned no choices", provider=self.provider)
        text = (choices[0].get("message") or {}).get("content") or ""
        usage = (result or {}).get("usage") or {}
        return ChatResult(
            text=text,
            model_id=self.spec.id if self.spec else "",
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            finish_reason=str(choices[0].get("finish_reason") or "stop"),
            latency_ms=latency,
        )

    def stream(self, messages: Sequence[dict[str, str]], params: GenerationParams) -> Iterator[str]:
        if self._model is None:
            raise ProviderError("no model loaded; call load() first", provider=self.provider)
        try:
            stream = self._model.create_chat_completion(
                messages=[{"role": m["role"], "content": m["content"]} for m in messages],
                temperature=params.temperature,
                top_p=params.top_p,
                max_tokens=params.max_tokens,
                stop=list(params.stop) or None,
                seed=params.seed,
                stream=True,
            )
            for chunk in stream:
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                piece = (choices[0].get("delta") or {}).get("content")
                if piece:
                    yield piece
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"llama.cpp streaming failed: {exc}", provider=self.provider) from exc

    def close(self) -> None:
        self.unload()


__all__ = ["LlamaCppRuntime", "llama_cpp_available", "INSTALL_HINT"]
