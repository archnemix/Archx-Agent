"""ModelRouter: probing operations."""

from __future__ import annotations

from typing import Any
from archx_agent.helpers.exceptions import (
    ModelNotFoundError,
    ValidationError,
)

from .records import PROBEABLE, _probe_prompt, _require_json

class ModelRouterProbingMixin:
    def probe(
        self,
        model_id: str,
        capability: str = "chat",
        *,
        record: bool = True,
    ) -> dict[str, Any]:
        """Actually exercise a capability and record the measurement.

        Nothing here is a simulation of a test: the runtime is driven, the result is
        inspected, and the outcome is written to ``model_capability_tests`` where the
        router reads it back.
        """
        if capability not in PROBEABLE:
            raise ValidationError(
                f"cannot probe {capability!r} here (probeable: {', '.join(PROBEABLE)}); "
                "capabilities such as vision or OCR need their own adapter and are not invented"
            )
        record_obj = self.models.get(model_id)
        if record_obj.is_err:
            record_obj = self.models.by_name(model_id)
        if record_obj.is_err:
            raise ModelNotFoundError(f"no model matches {model_id!r}", model=model_id)
        model = record_obj.value
        from archx_agent.adapters.model_runtime import GenerationParams  # local import: adapter layer

        runtime = self.runtime_for(model)
        messages: list[dict[str, str]] = [{"role": "user", "content": _probe_prompt(capability)}]
        params = GenerationParams(temperature=0.0, max_tokens=16)
        import time

        started = time.perf_counter()
        try:
            if capability == "tools":
                # The tool has to *be offered* for the reply to mean anything: a model that is
                # never given a tool cannot demonstrate calling one.
                caller = getattr(runtime, "chat_with_tools", None)
                if caller is None:
                    raise ValidationError(
                        f"the {model.runtime} runtime has no tool-calling path, so tool use "
                        "cannot be probed (evidence is not invented)"
                    )
                result = caller(messages, params)
            else:
                result = runtime.chat(messages, params)
            latency = (time.perf_counter() - started) * 1000.0
            text = (result.text or "").strip()
            raw = getattr(result, "raw", {}) or {}
            tool_calls = raw.get("tool_calls") or []
            if capability == "tools":
                if not tool_calls:
                    raise ValidationError(
                        "the runtime answered but did not return a tool call; tool use is not proven"
                    )
                name = tool_calls[0].get("name") or "a tool"
                text = f"called {name} with {tool_calls[0].get('arguments') or '{}'}"
            elif not text:
                raise ValidationError("the runtime returned an empty reply")
            if capability == "json":
                _require_json(text)
            if capability == "tools":
                detail = f"{text}, finish_reason={result.finish_reason}"
            else:
                detail = f"{len(text)} chars, finish_reason={result.finish_reason}"
            outcome = "passed"
        except Exception as exc:  # noqa: BLE001 - any failure is a measurement
            latency = (time.perf_counter() - started) * 1000.0
            outcome = "failed"
            detail = f"{type(exc).__name__}: {getattr(exc, 'message', str(exc))}"[:400]
            text = ""

        if record:
            self.models.record_capability_test(
                model.id, capability, outcome, detail=detail, latency_ms=round(latency, 1)
            )
            if outcome == "passed":
                self.models.set_verified_capabilities(
                    model.id,
                    sorted(set(model.verified_capabilities) | {capability}),
                    basis=f"probe passed at {latency:.0f} ms",
                )
            elif self.events is not None:
                self.events.record(
                    "model",
                    "model.probe_failed",
                    status="error",
                    payload={"model_id": model.id, "capability": capability, "detail": detail},
                )
        if self.events is not None:
            self.events.record(
                "model",
                "model.probed",
                status="ok" if outcome == "passed" else "error",
                duration_ms=round(latency, 1),
                payload={
                    "model_id": model.id,
                    "capability": capability,
                    "outcome": outcome,
                    "simulated": model.runtime == "scripted",
                },
            )
        return {
            "model_id": model.id,
            "model": model.name,
            "capability": capability,
            "outcome": outcome,
            "detail": detail,
            "latency_ms": round(latency, 1),
            "state_after": self.models.capability_state(self.models.require(model.id), capability),
            "message": text[:120],
        }
