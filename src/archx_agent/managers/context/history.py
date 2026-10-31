"""History operations for context windows."""

from __future__ import annotations

import json
from typing import Any

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.result import Err, Ok, Result
from archx_agent.helpers.timeutil import iso_now, new_id
from archx_agent.managers.conversation import Message
from archx_agent.managers.context.records import Summary, _summary_from_row


class ContextManagerHistoryMixin:
    """History responsibility for ContextManager."""

    def save_summary(
        self,
        conversation_id: str,
        start_seq: int,
        end_seq: int,
        content: str,
        *,
        generator: str = "model",
    ) -> Summary:
        if not content.strip():
            raise ValidationError("summary content must not be empty")
        if end_seq < start_seq:
            raise ValidationError("summary range end must not precede start")
        existing = self._find_summary(conversation_id, start_seq, end_seq)
        summary = Summary(
            id=new_id("sum_"),
            conversation_id=conversation_id,
            source_start_seq=start_seq,
            source_end_seq=end_seq,
            content=content,
            token_estimate=self.tokenizer.count(content),
            generator=generator,
            created_at=iso_now(),
        )
        self._write(
            "context.summary",
            {
                "summary": summary.to_dict(),
                "supersede": existing.id if existing else None,
            },
        )
        self.trace(
            "context",
            "context.summary_created",
            conversation_id=conversation_id,
            payload={
                "summary_id": summary.id,
                "range": [start_seq, end_seq],
                "generator": generator,
                "tokens": summary.token_estimate,
                "originals_preserved": True,
            },
        )
        return summary

    def _find_summary(
        self, conversation_id: str, start_seq: int, end_seq: int
    ) -> Summary | None:
        row = self.store.query_one(
            "SELECT * FROM summaries WHERE conversation_id = ? AND source_start_seq = ?"
            " AND source_end_seq = ? AND superseded_by IS NULL ORDER BY created_at DESC LIMIT 1",
            (conversation_id, start_seq, end_seq),
        )
        return _summary_from_row(row) if row else None

    def summaries(self, conversation_id: str) -> list[Summary]:
        rows = self.store.query(
            "SELECT * FROM summaries WHERE conversation_id = ? ORDER BY source_start_seq, created_at",
            (conversation_id,),
        )
        return [_summary_from_row(r) for r in rows]

    def summary_sources(self, summary_id: str) -> list[Message]:
        row = self.store.query_one(
            "SELECT * FROM summaries WHERE id = ?", (summary_id,)
        )
        if row is None:
            raise NotFoundError(f"summary {summary_id} not found")
        messages = self.conversations.messages(
            row["conversation_id"], include_excluded=True
        )
        return [
            m
            for m in messages
            if row["source_start_seq"] <= m.seq <= row["source_end_seq"]
        ]

    def manifest(self, manifest_id: str) -> Result[dict[str, Any]]:
        row = self.store.query_one(
            "SELECT * FROM context_manifests WHERE id = ?", (manifest_id,)
        )
        if row is None:
            return Err(NotFoundError(f"manifest {manifest_id} not found"))
        return Ok(
            {
                "id": row["id"],
                "conversation_id": row["conversation_id"],
                "strategy": row["strategy"],
                "budget": row["token_budget"],
                "tokens_used": row["tokens_used"],
                "included": json.loads(row["included"]) if row["included"] else [],
                "omitted": json.loads(row["omitted"]) if row["omitted"] else [],
                "notes": row["notes"],
                "created_at": row["created_at"],
            }
        )

    def manifests(self, conversation_id: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.store.query(
            "SELECT id, strategy, token_budget, tokens_used, created_at FROM context_manifests"
            " WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?",
            (conversation_id, limit),
        )
        return rows
