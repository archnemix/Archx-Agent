"""Aggregate answer/reasoning streams without changing routing or persistence policy."""
from __future__ import annotations

import time
from collections.abc import Callable, Sequence

from archx_agent.adapters.model_runtime import ChatResult, GenerationParams
from archx_agent.adapters.reasoning import ThinkingSplitter
from archx_agent.helpers.tokens import Tokenizer


def collect_stream(
    runtime,
    messages: Sequence[dict[str, str]],
    params: GenerationParams,
    *,
    model_id: str,
    prompt_tokens: int,
    tokenizer: Tokenizer,
    callback: Callable[[str], None],
    reasoning_callback: Callable[[str], None] | None = None,
) -> ChatResult:
    """Prefer provider channels, retaining leading think-tag support for legacy runtimes."""
    started = time.perf_counter()
    chunks: list[str] = []
    reasons: list[str] = []
    splitter = ThinkingSplitter()

    def emit(kind: str, piece: str) -> None:
        if kind == "reasoning":
            reasons.append(piece)
            if reasoning_callback is not None:
                reasoning_callback(piece)
        else:
            chunks.append(piece)
            callback(piece)

    stream_events = getattr(runtime, "stream_events", None)
    events = (stream_events(messages, params) if callable(stream_events)
              else (("content", piece) for piece in runtime.stream(messages, params)))
    for kind, piece in events:
        if kind == "reasoning":
            emit(kind, piece)
        else:
            for parsed_kind, parsed_text in splitter.feed(piece):
                emit(parsed_kind, parsed_text)
    for kind, piece in splitter.finish():
        emit(kind, piece)
    answer, reasoning = "".join(chunks), "".join(reasons)
    return ChatResult(
        text=answer,
        model_id=model_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=tokenizer.count(answer + reasoning),
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
        raw={"simulated": bool(getattr(runtime, "simulated", False)), "streamed": True, "reasoning": reasoning},
    )
