"""Rows for media assets, transcripts and every attempt to hear or speak.

Three tables, three different kinds of claim:

``media_assets``
    What a file *is*, measured. The row keeps the format the bytes declared and, separately, what
    the file name claimed (``name_claim`` / ``name_mismatch``), because a ``.png`` that is really a
    JPEG is a finding worth keeping, not a validation error to swallow.

``voice_transcripts``
    Words tied to an asset, each with a ``source``. Today the only source this build can produce
    is ``human``: there is no speech model here, and a transcript that does not say who wrote it is
    a transcript you cannot trust.

``voice_attempts``
    Every attempt, including the refused ones. A refusal is the most informative row a voice mode
    can write on a machine with no microphone and no weights, so it is stored with the reason and
    the engine that was consulted - in the same spirit as M33's refused moves.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now, new_id

from .base import BaseManager

MEDIA_TABLES = ("media_assets", "voice_attempts", "voice_transcripts")

VOICE_ACTIONS = ("probe", "transcribe", "synthesize")
VOICE_STATUSES = ("refused", "completed", "failed")
TRANSCRIPT_SOURCES = ("human",)


@dataclass
class MediaAsset:
    id: str
    kind: str
    format: str
    path: str
    sha256: str
    bytes: int
    created_at: str
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    bits_per_sample: int | None = None
    name_claim: str = ""
    name_mismatch: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)
    task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def audio(self) -> bool:
        return self.kind == "audio"

    @property
    def image(self) -> bool:
        return self.kind == "image"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "format": self.format,
            "path": self.path,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "width": self.width,
            "height": self.height,
            "duration_ms": self.duration_ms,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "bits_per_sample": self.bits_per_sample,
            "name_claim": self.name_claim,
            "name_mismatch": self.name_mismatch,
            "facts": dict(self.facts),
            "task_id": self.task_id,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


@dataclass
class VoiceAttempt:
    id: str
    action: str
    status: str
    created_at: str
    asset_id: str | None = None
    reason: str | None = None
    engine: str | None = None
    chars: int | None = None
    task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "asset_id": self.asset_id,
            "action": self.action,
            "status": self.status,
            "reason": self.reason,
            "engine": self.engine,
            "chars": self.chars,
            "task_id": self.task_id,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


@dataclass
class Transcript:
    id: str
    asset_id: str
    text: str
    source: str
    created_at: str
    task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "asset_id": self.asset_id,
            "text": self.text,
            "source": self.source,
            "chars": len(self.text),
            "task_id": self.task_id,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


def _loads(raw: Any, fallback: Any) -> Any:
    if raw in (None, ""):
        return fallback
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):  # pragma: no cover - a hand-edited row
        return fallback
    return value if isinstance(value, type(fallback)) else fallback


def _asset_from_row(row: Mapping[str, Any]) -> MediaAsset:
    return MediaAsset(
        id=row["id"],
        kind=row["kind"],
        format=row["format"],
        path=row["path"],
        sha256=row["sha256"],
        bytes=int(row["bytes"]),
        width=row["width"],
        height=row["height"],
        duration_ms=row["duration_ms"],
        sample_rate=row["sample_rate"],
        channels=row["channels"],
        bits_per_sample=row["bits_per_sample"],
        name_claim=row["name_claim"] or "",
        name_mismatch=row["name_mismatch"],
        facts=_loads(row["facts"], {}),
        task_id=row["task_id"],
        created_at=row["created_at"],
        metadata=_loads(row["metadata"], {}),
    )


def _attempt_from_row(row: Mapping[str, Any]) -> VoiceAttempt:
    return VoiceAttempt(
        id=row["id"],
        asset_id=row["asset_id"],
        action=row["action"],
        status=row["status"],
        reason=row["reason"],
        engine=row["engine"],
        chars=row["chars"],
        task_id=row["task_id"],
        created_at=row["created_at"],
        metadata=_loads(row["metadata"], {}),
    )


def _transcript_from_row(row: Mapping[str, Any]) -> Transcript:
    return Transcript(
        id=row["id"],
        asset_id=row["asset_id"],
        text=row["text"],
        source=row["source"],
        created_at=row["created_at"],
        task_id=row["task_id"],
        metadata=_loads(row["metadata"], {}),
    )


class MediaManager(BaseManager):
    """Rows for measured media, the words attached to it, and the attempts to process it."""

    tables = MEDIA_TABLES

    def register_handlers(self) -> None:
        self.coordinator.register("media.asset", self._apply_asset)
        self.coordinator.register("media.attempt", self._apply_attempt)
        self.coordinator.register("media.transcript", self._apply_transcript)

    # -- write handlers ---------------------------------------------------
    def _apply_asset(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        asset = payload["asset"]
        tx.execute(
            "INSERT INTO media_assets(id, kind, format, path, sha256, bytes, width, height,"
            " duration_ms, sample_rate, channels, bits_per_sample, name_claim, name_mismatch,"
            " facts, task_id, created_at, metadata)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                asset["id"], asset["kind"], asset["format"], asset["path"], asset["sha256"],
                int(asset["bytes"]), asset.get("width"), asset.get("height"),
                asset.get("duration_ms"), asset.get("sample_rate"), asset.get("channels"),
                asset.get("bits_per_sample"), asset.get("name_claim") or "",
                asset.get("name_mismatch"), json_text(asset.get("facts") or {}),
                asset.get("task_id"), asset["created_at"], json_text(asset.get("metadata") or {}),
            ),
        )
        return {"id": asset["id"]}

    def _apply_attempt(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        attempt = payload["attempt"]
        tx.execute(
            "INSERT INTO voice_attempts(id, asset_id, action, status, reason, engine, chars,"
            " task_id, created_at, metadata) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                attempt["id"], attempt.get("asset_id"), attempt["action"], attempt["status"],
                attempt.get("reason"), attempt.get("engine"), attempt.get("chars"),
                attempt.get("task_id"), attempt["created_at"],
                json_text(attempt.get("metadata") or {}),
            ),
        )
        return {"id": attempt["id"]}

    def _apply_transcript(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        transcript = payload["transcript"]
        tx.execute(
            "INSERT INTO voice_transcripts(id, asset_id, text, source, created_at, task_id,"
            " metadata) VALUES (?,?,?,?,?,?,?)",
            (
                transcript["id"], transcript["asset_id"], transcript["text"],
                transcript["source"], transcript["created_at"], transcript.get("task_id"),
                json_text(transcript.get("metadata") or {}),
            ),
        )
        return {"id": transcript["id"]}

    # -- media ------------------------------------------------------------
    def record_asset(
        self,
        *,
        kind: str,
        format: str,
        path: str,
        sha256: str,
        bytes: int,
        width: int | None = None,
        height: int | None = None,
        duration_ms: int | None = None,
        sample_rate: int | None = None,
        channels: int | None = None,
        bits_per_sample: int | None = None,
        name_claim: str = "",
        name_mismatch: str | None = None,
        facts: dict[str, Any] | None = None,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MediaAsset:
        asset = MediaAsset(
            id=new_id("ma_"),
            kind=kind,
            format=format,
            path=path,
            sha256=sha256,
            bytes=int(bytes),
            width=width,
            height=height,
            duration_ms=duration_ms,
            sample_rate=sample_rate,
            channels=channels,
            bits_per_sample=bits_per_sample,
            name_claim=name_claim,
            name_mismatch=name_mismatch,
            facts=dict(facts or {}),
            task_id=task_id,
            created_at=iso_now(),
            metadata=dict(metadata or {}),
        )
        self._write("media.asset", {"asset": asset.to_dict()})
        self.trace(
            "media", "media.asset", status="ok", task_id=task_id,
            payload={
                "asset_id": asset.id, "kind": kind, "format": format, "bytes": int(bytes),
                "sha256": sha256, "name_mismatch": name_mismatch,
            },
        )
        return asset

    def get_asset(self, asset_id: str) -> MediaAsset:
        row = self.store.query_one("SELECT * FROM media_assets WHERE id = ?", (asset_id,))
        if row is None:
            raise NotFoundError(f"no such media asset: {asset_id}")
        return _asset_from_row(row)

    def asset_by_sha(self, sha256: str) -> MediaAsset | None:
        row = self.store.query_one(
            "SELECT * FROM media_assets WHERE sha256 = ? ORDER BY created_at LIMIT 1", (sha256,)
        )
        return _asset_from_row(row) if row else None

    def assets(
        self, *, kind: str | None = None, limit: int = 50
    ) -> list[MediaAsset]:
        sql = "SELECT * FROM media_assets"
        params: list[Any] = []
        if kind:
            sql += " WHERE kind = ?"
            params.append(kind)
        sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(int(limit))
        return [_asset_from_row(row) for row in self.store.query(sql, params)]

    # -- attempts ---------------------------------------------------------
    def record_attempt(
        self,
        *,
        action: str,
        status: str,
        asset_id: str | None = None,
        reason: str | None = None,
        engine: str | None = None,
        chars: int | None = None,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> VoiceAttempt:
        if action not in VOICE_ACTIONS:
            raise ValidationError(f"unknown voice action: {action}")
        if status not in VOICE_STATUSES:
            raise ValidationError(f"unknown voice status: {status}")
        attempt = VoiceAttempt(
            id=new_id("va_"),
            action=action,
            status=status,
            asset_id=asset_id,
            reason=reason,
            engine=engine,
            chars=chars,
            task_id=task_id,
            created_at=iso_now(),
            metadata=dict(metadata or {}),
        )
        self._write("media.attempt", {"attempt": attempt.to_dict()})
        self.trace(
            "media", "media.attempt", status="ok" if status == "completed" else "error",
            task_id=task_id,
            payload={
                "attempt_id": attempt.id, "action": action, "status": status,
                "asset_id": asset_id, "reason": reason, "engine": engine,
            },
        )
        return attempt

    def attempts(self, *, asset_id: str | None = None, limit: int = 50) -> list[VoiceAttempt]:
        sql = "SELECT * FROM voice_attempts"
        params: list[Any] = []
        if asset_id:
            sql += " WHERE asset_id = ?"
            params.append(asset_id)
        sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(int(limit))
        return [_attempt_from_row(row) for row in self.store.query(sql, params)]

    def get_attempt(self, attempt_id: str) -> VoiceAttempt:
        row = self.store.query_one("SELECT * FROM voice_attempts WHERE id = ?", (attempt_id,))
        if row is None:
            raise NotFoundError(f"no such voice attempt: {attempt_id}")
        return _attempt_from_row(row)

    # -- transcripts ------------------------------------------------------
    def record_transcript(
        self,
        asset_id: str,
        text: str,
        *,
        source: str = "human",
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Transcript:
        if source not in TRANSCRIPT_SOURCES:
            raise ValidationError(
                "this build can only record a transcript a person wrote "
                f"(source: {', '.join(TRANSCRIPT_SOURCES)}); it has no speech model"
            )
        if not str(text or "").strip():
            raise ValidationError("a transcript with no words is not a transcript")
        transcript = Transcript(
            id=new_id("vt_"),
            asset_id=asset_id,
            text=str(text),
            source=source,
            task_id=task_id,
            created_at=iso_now(),
            metadata=dict(metadata or {}),
        )
        self._write("media.transcript", {"transcript": transcript.to_dict()})
        self.trace(
            "media", "media.transcript", status="ok", task_id=task_id,
            payload={
                "transcript_id": transcript.id, "asset_id": asset_id, "source": source,
                "chars": len(transcript.text),
            },
        )
        return transcript

    def transcripts(self, asset_id: str) -> list[Transcript]:
        rows = self.store.query(
            "SELECT * FROM voice_transcripts WHERE asset_id = ? ORDER BY created_at, rowid",
            (asset_id,),
        )
        return [_transcript_from_row(row) for row in rows]

    # -- counts -----------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        return {
            "assets": self.table_count("media_assets"),
            "images": int(
                self.store.scalar("SELECT COUNT(*) FROM media_assets WHERE kind = 'image'") or 0
            ),
            "audio": int(
                self.store.scalar("SELECT COUNT(*) FROM media_assets WHERE kind = 'audio'") or 0
            ),
            "audio_ms": int(
                self.store.scalar("SELECT COALESCE(SUM(duration_ms), 0) FROM media_assets") or 0
            ),
            "mislabelled": int(
                self.store.scalar(
                    "SELECT COUNT(*) FROM media_assets WHERE name_mismatch IS NOT NULL"
                ) or 0
            ),
            "transcripts": self.table_count("voice_transcripts"),
            "attempts": self.table_count("voice_attempts"),
            "refused": int(
                self.store.scalar(
                    "SELECT COUNT(*) FROM voice_attempts WHERE status = 'refused'"
                ) or 0
            ),
        }
