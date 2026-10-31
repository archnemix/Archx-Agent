"""In-process GGUF runtime via ``llama-cpp-python``.

The dependency is optional. When it is missing we raise a precise error rather
than pretending the model is usable, and the CLI reports "local runtime not
installed" with the install command.
"""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path
from typing import Any, Iterator, Sequence

from archx_agent.adapters.chat_payloads import first_message, usage_counts, stream_piece
from archx_agent.helpers.exceptions import (
    MalformedOutputError,
    LocalRuntimeFailureError,
    ModelNotFoundError,
    ProviderError,
    ResourceExhaustedError,
)
from archx_agent.helpers.tokens import CallableTokenizer, Tokenizer

from .model_runtime import (
    BaseRuntime,
    ChatResult,
    GenerationParams,
    ModelSpec,
    RuntimeHealth,
)

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

    def __init__(
        self,
        *,
        n_threads: int | None = None,
        n_ctx: int | None = None,
        verbose: bool = False,
    ) -> None:
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
        self.unload()
        if not llama_cpp_available():
            self._load_error = f"llama-cpp-python is not installed ({INSTALL_HINT})"
            raise LocalRuntimeFailureError(
                self._load_error, provider=self.provider, model=spec.id
            )
        path = Path(spec.path or "")
        try:
            info = path.stat()
        except FileNotFoundError as exc:
            self._load_error = f"model file not found: {path}"
            raise ModelNotFoundError(
                self._load_error, provider=self.provider, model=spec.id
            ) from exc
        except OSError as exc:
            self._load_error = f"cannot inspect model file {path.name}: {exc.strerror or type(exc).__name__}"
            raise LocalRuntimeFailureError(
                self._load_error, provider=self.provider, model=spec.id
            ) from exc
        if not stat.S_ISREG(info.st_mode):
            self._load_error = f"model path is not a regular file: {path}"
            raise ModelNotFoundError(
                self._load_error, provider=self.provider, model=spec.id
            )
        if info.st_size < 1024:
            self._load_error = f"model file is suspiciously small: {path}"
            raise ModelNotFoundError(
                self._load_error, provider=self.provider, model=spec.id
            )
        try:
            from llama_cpp import Llama

            self._model = Llama(
                model_path=str(path),
                n_ctx=self.n_ctx or spec.context_length,
                n_threads=self.n_threads,
                verbose=self.verbose,
            )
        except MemoryError as exc:
            self._load_error = f"not enough memory to load {path.name}"
            raise ResourceExhaustedError(
                f"not enough memory to load {path.name}",
                provider=self.provider,
                model=spec.id,
            ) from exc
        except Exception as exc:  # noqa: BLE001 - native failure surfaces here
            self._load_error = f"failed to load {path.name}: {exc}"
            raise LocalRuntimeFailureError(
                self._load_error, provider=self.provider, model=spec.id
            ) from exc
        self.spec = spec
        self._load_error = None

    def unload(self) -> None:
        model, self._model = self._model, None
        model_id = self.spec.id if self.spec else ""
        super().unload()
        try:
            if model is not None and callable(getattr(model, "close", None)):
                model.close()
        except Exception as exc:  # noqa: BLE001 - native cleanup must not leave loaded state
            self._load_error = f"failed to release native model: {type(exc).__name__}"
            raise LocalRuntimeFailureError(
                self._load_error, provider=self.provider, model=model_id
            ) from exc

    def health(self) -> RuntimeHealth:
        if not llama_cpp_available():
            return RuntimeHealth(
                ok=False, detail=f"llama-cpp-python missing ({INSTALL_HINT})"
            )
        if self._load_error:
            return RuntimeHealth(ok=False, detail=self._load_error)
        return RuntimeHealth(
            ok=True,
            detail="in-process llama.cpp ready"
            if self.loaded
            else "runtime available, no model loaded",
            loaded=self.loaded,
            capabilities=tuple(sorted(self._capabilities)),
        )

    def tokenizer(self) -> Tokenizer | None:
        if self._model is None:
            return None
        try:
            return CallableTokenizer(
                f"llama_cpp:{Path(self.spec.path).name if self.spec else 'model'}",
                self._model.tokenize,
            )
        except Exception:  # noqa: BLE001
            return None

    # -- inference --------------------------------------------------------
    def chat(
        self, messages: Sequence[dict[str, str]], params: GenerationParams
    ) -> ChatResult:
        if self._model is None:
            raise ProviderError(
                "no model loaded; call load() first", provider=self.provider
            )
        started = time.perf_counter()
        try:
            result = self._model.create_chat_completion(
                messages=[
                    {"role": m["role"], "content": m["content"]} for m in messages
                ],
                temperature=params.temperature,
                top_p=params.top_p,
                max_tokens=params.max_tokens,
                stop=list(params.stop) or None,
                seed=params.seed,
                stream=False,
            )
        except MemoryError as exc:  # pragma: no cover
            raise ResourceExhaustedError(
                "out of memory during inference", provider=self.provider
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(
                f"llama.cpp inference failed: {exc}",
                provider=self.provider,
                model=self.spec.id if self.spec else "",
            ) from exc
        latency = round((time.perf_counter() - started) * 1000, 2)
        choice, message = first_message(result, self.provider)
        text = message.get("content")
        if not isinstance(text, str) or not text.strip():
            raise MalformedOutputError(
                "llama.cpp returned empty or non-text content", provider=self.provider
            )
        prompt_tokens, completion_tokens = usage_counts(result, self.provider)
        return ChatResult(
            text=text,
            model_id=self.spec.id if self.spec else "",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=str(choice.get("finish_reason") or "stop"),
            latency_ms=latency,
        )

    def stream(
        self, messages: Sequence[dict[str, str]], params: GenerationParams
    ) -> Iterator[str]:
        if self._model is None:
            raise ProviderError(
                "no model loaded; call load() first", provider=self.provider
            )
        try:
            stream = self._model.create_chat_completion(
                messages=[
                    {"role": m["role"], "content": m["content"]} for m in messages
                ],
                temperature=params.temperature,
                top_p=params.top_p,
                max_tokens=params.max_tokens,
                stop=list(params.stop) or None,
                seed=params.seed,
                stream=True,
            )
            for chunk in stream:
                piece = stream_piece(chunk, self.provider)
                if piece:
                    yield piece
        except MemoryError as exc:
            raise ResourceExhaustedError(
                "out of memory during streaming", provider=self.provider
            ) from exc
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(
                f"llama.cpp streaming failed: {exc}", provider=self.provider
            ) from exc

    def close(self) -> None:
        self.unload()


__all__ = ["LlamaCppRuntime", "llama_cpp_available", "INSTALL_HINT"]
