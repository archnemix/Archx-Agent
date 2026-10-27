"""Deterministic runtime used **only** for tests and offline demos.

It performs no inference. It exists so the rest of the system (context
strategies, tracing, permissions, scheduler) can be exercised deterministically
without a model. To stop it from ever being mistaken for a real model:

* ``verified_capabilities`` is empty, so the router treats it as unverified;
* it refuses to run unless explicitly enabled for tests;
* every result is tagged ``simulated=True`` and traced as such;
* the CLI labels it ``[SIMULATED]``.
"""

from __future__ import annotations

import re
import time
from typing import Iterator, Sequence

from archx_agent.helpers.exceptions import ProviderError, ValidationError

from .model_runtime import BaseRuntime, ChatResult, GenerationParams, ModelSpec, RuntimeHealth

ENV_FLAG = "ARCHX_ALLOW_SIMULATED"


class ScriptedRuntime(BaseRuntime):
    runtime_id = "scripted"
    provider = "test-double"
    is_local = True
    supports_streaming = True
    _capabilities = frozenset({"chat"})
    simulated = True

    def __init__(self, *, script: dict[str, str] | None = None, echo: bool = True, enabled: bool = False) -> None:
        super().__init__()
        self.script = dict(script or {})
        self.echo = echo
        self._enabled = enabled
        self.calls: list[dict[str, object]] = []

    def _require(self) -> None:
        import os

        if not (self._enabled or os.environ.get(ENV_FLAG) == "1"):
            raise ProviderError(
                "the simulated runtime is a test double and is disabled; "
                f"set {ENV_FLAG}=1 to use it deliberately, or configure a real model"
            )

    def available(self) -> tuple[bool, str]:
        try:
            self._require()
        except ProviderError as exc:
            return False, exc.message
        return True, "ready (simulated - performs no inference)"

    def load(self, spec: ModelSpec) -> None:
        self._require()
        if spec.runtime != self.runtime_id:
            raise ValidationError(f"ScriptedRuntime cannot load runtime {spec.runtime!r}")
        self.spec = spec

    def health(self) -> RuntimeHealth:
        return RuntimeHealth(
            ok=True,
            detail="simulated test double - performs no inference",
            loaded=self.loaded,
            capabilities=tuple(sorted(self._capabilities)),
        )

    def chat(self, messages: Sequence[dict[str, str]], params: GenerationParams) -> ChatResult:
        self._require()
        if not self.loaded:
            raise ProviderError("no model loaded; call load() first", provider=self.provider)
        started = time.perf_counter()
        prompt = messages[-1]["content"] if messages else ""
        self.calls.append({"messages": list(messages), "params": params.to_dict()})
        text = self._answer(prompt)
        return ChatResult(
            text=text,
            model_id=self.spec.id if self.spec else "scripted",
            prompt_tokens=len(prompt.split()),
            completion_tokens=len(text.split()),
            finish_reason="stop",
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            raw={"simulated": True},
        )

    def stream(self, messages: Sequence[dict[str, str]], params: GenerationParams) -> Iterator[str]:
        result = self.chat(messages, params)
        for word in result.text.split(" "):
            yield word + " "

    def _answer(self, prompt: str) -> str:
        for key, value in self.script.items():
            if re.search(key, prompt, re.IGNORECASE):
                return value
        if self.echo:
            # deterministic, obviously-not-a-model output
            return f"[SIMULATED] I received {len(prompt.split())} words. No model was run."
        return "[SIMULATED] no scripted answer"


__all__ = ["ScriptedRuntime", "ENV_FLAG"]
