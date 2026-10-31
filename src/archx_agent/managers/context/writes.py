"""Transactional write handlers for context windows."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.jsonio import json_text


class ContextManagerWritesMixin:
    """Writes responsibility for ContextManager."""

    def register_handlers(self) -> None:
        self.coordinator.register("context.manifest", self._apply_manifest)
        self.coordinator.register("context.summary", self._apply_summary)
        self.coordinator.register("context.proposal", self._apply_proposal)

    def _apply_manifest(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        m = payload["manifest"]
        tx.execute(
            "INSERT INTO context_manifests(id, conversation_id, message_id, strategy, token_budget,"
            " tokens_used, omitted, included, notes, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                m["id"],
                m["conversation_id"],
                m.get("message_id"),
                m["strategy"],
                m["budget"],
                m["tokens_used"],
                json_text(m.get("omitted") or []),
                json_text(m.get("included") or []),
                m.get("notes"),
                m["created_at"],
            ),
        )
        return {"id": m["id"]}

    def _apply_proposal(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        p = payload["proposal"]
        tx.execute(
            "INSERT OR REPLACE INTO context_proposals(id, conversation_id, strategy, payload, rationale,"
            " estimated_tokens, created_at, approved_at, applied_manifest_id, rejected_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                p["id"],
                p["conversation_id"],
                p["strategy"],
                json_text(p),
                p.get("rationale"),
                p.get("estimated_tokens"),
                p["created_at"],
                p.get("approved_at"),
                p.get("applied_manifest_id"),
                p.get("rejected_at"),
            ),
        )
        return {"id": p["id"]}

    def _apply_summary(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        s = payload["summary"]
        tx.execute(
            "INSERT INTO summaries(id, conversation_id, source_start_seq, source_end_seq, content,"
            " token_estimate, generator, created_at, superseded_by) VALUES (?,?,?,?,?,?,?,?,NULL)",
            (
                s["id"],
                s["conversation_id"],
                s["source_start_seq"],
                s["source_end_seq"],
                s["content"],
                s["token_estimate"],
                s["generator"],
                s["created_at"],
            ),
        )
        if payload.get("supersede"):
            tx.execute(
                "UPDATE summaries SET superseded_by=? WHERE id=?",
                (s["id"], payload["supersede"]),
            )
        return {"id": s["id"]}
