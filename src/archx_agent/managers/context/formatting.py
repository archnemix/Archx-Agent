"""Feature-specific formatting for context windows."""

from __future__ import annotations

from typing import Any, Sequence

from archx_agent.managers.conversation import Message


def _format_memory(memory: Any) -> str:
    bits = [f"[{memory.kind}/{memory.category}] {memory.title}", memory.content]
    if memory.verification:
        bits.append(f"(verification: {memory.verification})")
    if memory.limitations:
        bits.append(f"(limitations: {memory.limitations})")
    return "\n".join(bits)


def _message_units(messages: Sequence[Message]) -> list[list[Message]]:
    """Group tool calls with their results so a pair is never split."""
    units: list[list[Message]] = []
    for message in messages:
        if (
            units
            and message.role == "tool"
            and units[-1]
            and units[-1][-1].role == "assistant"
        ):
            units[-1].append(message)
        elif units and message.role == "tool" and units[-1][-1].role == "tool":
            units[-1].append(message)
        else:
            units.append([message])
    return units


def _message_units_flat(messages: Sequence[Message]) -> list[Message]:
    return list(messages)
