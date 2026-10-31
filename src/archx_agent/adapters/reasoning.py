"""Separate provider-emitted reasoning from answers; never generate reasoning ourselves."""

from archx_agent.helpers.exceptions import MalformedOutputError


def reasoning_text(message: dict, provider: str) -> str:
    """OpenAI-compatible providers use either of these optional text fields."""
    for key in ("reasoning", "reasoning_content"):
        value = message.get(key)
        if value is not None and not isinstance(value, str):
            raise MalformedOutputError(f"{key} must be text", provider=provider)
    return message.get("reasoning") or message.get("reasoning_content") or ""


class ThinkingSplitter:
    """Recognize only a leading <think> block, including tags split across chunks.

    Inline examples of the tag in ordinary answers are left alone. An unclosed leading
    block remains reasoning, rather than silently presenting it as the final answer.
    """

    def __init__(self) -> None:
        self.mode = "prefix"
        self.buffer = ""

    def feed(self, text: str) -> list[tuple[str, str]]:
        if self.mode == "answer":
            return [("content", text)] if text else []
        self.buffer += text
        if self.mode == "prefix":
            candidate = self.buffer.lstrip()
            if not candidate or ("<think>".startswith(candidate) and candidate != "<think>"):
                return []
            if candidate.startswith("<think>"):
                self.mode = "reasoning"
                self.buffer = candidate[len("<think>"):]
            else:
                self.mode = "answer"
                result, self.buffer = self.buffer, ""
                return [("content", result)]
        close = self.buffer.find("</think>")
        if close >= 0:
            reason = self.buffer[:close]
            answer = self.buffer[close + len("</think>"):]
            self.buffer = ""
            self.mode = "answer"
            return [(kind, value) for kind, value in [("reasoning", reason), ("content", answer)] if value]
        # Hold only a possible partial closing tag, not the whole reasoning transcript.
        keep = 0
        for size in range(1, min(len(self.buffer), len("</think>") - 1) + 1):
            if "</think>".startswith(self.buffer[-size:]):
                keep = size
        ready = self.buffer[:-keep] if keep else self.buffer
        self.buffer = self.buffer[-keep:] if keep else ""
        return [("reasoning", ready)] if ready else []

    def finish(self) -> list[tuple[str, str]]:
        kind = "reasoning" if self.mode == "reasoning" else "content"
        result, self.buffer = self.buffer, ""
        return [(kind, result)] if result else []
