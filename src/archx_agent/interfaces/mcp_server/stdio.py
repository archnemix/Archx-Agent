"""MCP server bounded line framing and explicit stdin/stdout loop."""

from __future__ import annotations
import json
import sys
from archx_agent.helpers.exceptions import ValidationError
from archx_agent.helpers.processes import positive_integer


class McpStdioMixin:
    def serve_stdio(self, stdin=None, stdout=None, *, max_message_bytes=8_000_000):
        try:
            positive_integer(max_message_bytes, "max_message_bytes")
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        reader = stdin if stdin is not None else sys.stdin.buffer
        writer = stdout if stdout is not None else sys.stdout
        while True:
            line = reader.readline(max_message_bytes + 1)
            if not line:
                break
            raw = line.encode("utf-8") if isinstance(line, str) else line
            overflow = len(raw) > max_message_bytes
            if overflow:
                response = self._error(None, -32600, "message exceeds byte budget")
            else:
                try:
                    text = raw.decode("utf-8").strip()
                    if not text:
                        continue
                    message = json.loads(text)
                except (ValueError, UnicodeError, RecursionError):
                    response = self._error(None, -32700, "parse error")
                else:
                    response = self.handle(message)
            if response is not None:
                encoded = json.dumps(response)
                if len(encoded.encode("utf-8")) > max_message_bytes:
                    encoded = json.dumps(
                        self._error(None, -32000, "response exceeds byte budget")
                    )
                writer.write(encoded + "\n")
                writer.flush()
            if overflow:
                return  # never reinterpret the rest of an oversized line
