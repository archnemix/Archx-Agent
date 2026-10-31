"""HTTP endpoints for chat. Authentication is enforced by GuiApi.dispatch."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterable
from typing import Any
from urllib.parse import unquote

from archx_agent.helpers.exceptions import (
    ArchxError,
)
from archx_agent.interfaces.gui.protocol import ApiError, Request, SSEStream, route


class ChatRoutes:
    @route("GET", "/api/conversations", "Recent conversations.")
    def get_conversations(
        self, request: Request, match: re.Match[str]
    ) -> list[dict[str, Any]]:
        limit = request.q_int("limit", 20)
        return [
            {
                "id": record.id,
                "title": record.title,
                "updated_at": record.updated_at,
                "created_at": record.created_at,
                "status": getattr(record, "status", "active"),
                "messages": getattr(record, "message_count", None),
            }
            for record in self.ws.conversations.list_conversations(limit=limit)
        ]

    @route(
        "POST", "/api/chat", "One chat turn, recorded as a task exactly like the CLI's."
    )
    def post_chat(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        message = request.text("message", required=True) or ""
        if len(message) > 8000:
            raise ApiError(
                400, "validation", "a message must be at most 8000 characters"
            )
        conversation_id = request.identifier("conversation_id")
        model_id = request.identifier("model_id")
        reply = self.ws.chat.send(
            message, conversation_id=conversation_id, model_id=model_id
        )
        payload = reply.to_dict()
        payload["simulated"] = bool(reply.simulated)
        return payload

    @route(
        "POST",
        "/api/chat/stream",
        "The same chat turn, streamed as server-sent events.",
    )
    def post_chat_stream(self, request: Request, match: re.Match[str]) -> SSEStream:
        message = request.text("message", required=True) or ""
        if len(message) > 8000:
            raise ApiError(
                400, "validation", "a message must be at most 8000 characters"
            )
        conversation_id = request.identifier("conversation_id")
        model_id = request.identifier("model_id")
        return SSEStream(self._chat_frames(message, conversation_id, model_id))

    def _chat_frames(
        self, message: str, conversation_id: str | None, model_id: str | None
    ) -> Iterable[str]:
        """Run the turn on a worker thread and yield what it produces.

        The chat service already accepts a callback per chunk (the CLI's `--stream` uses it), so
        this is plumbing rather than a second implementation: the same task is created, the same
        messages are stored, and the last frame carries the recorded reply.
        """
        import queue

        frames: queue.Queue[tuple[str, Any] | None] = queue.Queue()

        def emit(piece: str) -> None:
            frames.put(("chunk", {"text": piece}))

        def emit_reasoning(piece: str) -> None:
            frames.put(("reasoning", {"text": piece}))

        def work() -> None:
            try:
                reply = self.ws.chat.send(
                    message,
                    conversation_id=conversation_id,
                    model_id=model_id,
                    stream_callback=emit,
                    reasoning_callback=emit_reasoning,
                )
                payload = reply.to_dict()
                payload["simulated"] = bool(reply.simulated)
                frames.put(("done", payload))
            except ArchxError as exc:
                frames.put(
                    (
                        "error",
                        {"code": getattr(exc, "code", "error"), "message": exc.message},
                    )
                )
            except Exception as exc:  # noqa: BLE001 - a stream must always end with something
                frames.put(("error", {"code": "internal", "message": str(exc)[:400]}))
            finally:
                frames.put(None)

        threading.Thread(target=work, name="chat-stream", daemon=True).start()
        while True:
            item = frames.get()
            if item is None:
                return
            event, payload = item
            yield f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"

    @route(
        "GET",
        "/api/conversations/{conversation_id}/messages",
        "The messages of one conversation.",
    )
    def get_messages(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        conversation_id = unquote(match.group("conversation_id"))
        record = self.ws.conversations.get(conversation_id)
        if record.is_err:
            raise record.error
        messages = self.ws.conversations.messages(conversation_id)
        return {
            "id": conversation_id,
            "title": record.value.title,
            "model_id": record.value.model_id,
            "messages": [
                {
                    "id": message.id,
                    "role": message.role,
                    "content": message.content,
                    "reasoning": message.metadata.get("reasoning", ""),
                    "created_at": message.created_at,
                }
                for message in messages
            ],
        }

    @route(
        "GET", "/api/search", "One search across every source, with its honest notes."
    )
    def get_search(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        query = (request.q("q") or "").strip()
        if len(query) < 2:
            raise ApiError(400, "validation", "a search needs at least two characters")
        kinds = [value for value in (request.query.get("kind") or []) if value]
        report = self.ws.search.search(
            query,
            kinds=kinds or None,
            limit=request.q_int("limit", 20),
            include_files=request.q_bool("files", True),
        )
        return report.to_dict()
