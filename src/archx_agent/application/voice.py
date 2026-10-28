"""Voice and multimodal: the boundary, told honestly.

This machine has no microphone, no camera, no GPU and no speech weights. A milestone called "voice
and multimodal" could pretend otherwise in three ways - invent a transcript, synthesise a plausible
waveform, or report an image's size from its file name - and each of them would look like progress
for a week. This module does none of them. Instead it builds the three things that are true and
useful on any machine, and refuses the rest by name:

**It measures.** ``probe`` asks the tool layer for a file's size, hash and first bytes, and
:mod:`archx_agent.application.media` reads the container header. The facts in the record are
measured from the file, and the name's claim is kept separately, so a ``.png`` that is really a
JPEG is recorded as a JPEG *and* as a mislabelled file.

**It keeps provenance.** A transcript carries the source that produced it. The only source this
build can produce is ``human``; there is no path in this code that writes a transcript it did not
read from a person, and the table refuses any other value rather than leaving room for one.

**It records its refusals.** ``transcribe`` and ``say`` walk a chain - is voice on, is a model
named, does that model exist, does it claim the capability, is its runtime ready, is there an
adapter that can drive it - and the first missing link becomes the reason. The reason is written to
``voice_attempts`` with the engine that was consulted. Tomorrow, when an adapter exists, the same
call reaches the end of the chain; today it says exactly which link is absent, which is more useful
than a plausible paragraph of invented speech.

What the mode therefore promises: *what is stored about a recording is measured, who wrote a
transcript is recorded, and what cannot be heard is said out loud.*
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from archx_agent.application import media
from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    PermissionDeniedError,
    ToolError,
    ValidationError,
)
from archx_agent.managers.media import MediaAsset, VoiceAttempt
from archx_agent.managers.tools import ToolContext

#: Capabilities a runtime would have to offer before this mode could hear or speak. Nothing in this
#: build implements either, and `_adapter_offers` says so by asking, rather than by a comment.
SPEECH_CAPABILITIES = ("transcription", "speech_generation")


#: Claimed capabilities live in different places on different records. A reader that assumed one
#: of them would report "does not claim transcription" for a model that does, which is the exact
#: kind of wrong answer this mode is supposed to avoid.
CLAIM_CAPABILITIES = ("verified_capabilities", "capabilities", "claims")


def claimed_capabilities(record: Any) -> list[str]:
    found: set[str] = set()
    for attribute in CLAIM_CAPABILITIES:
        value = getattr(record, attribute, None)
        if isinstance(value, dict):
            found.update(str(key) for key in value)
        elif isinstance(value, (list, tuple, set)):
            found.update(str(item) for item in value)
    return sorted(found)

class VoiceService:
    """Measure media, keep transcripts with their provenance, and refuse speech by name."""

    def __init__(self, ws) -> None:
        self.ws = ws

    # -- plumbing ---------------------------------------------------------
    @property
    def manager(self):
        return self.ws.media

    def _execute(self, name: str, arguments: dict[str, Any], context: ToolContext):
        run = self.ws.tools.execute(name, arguments, context=context, requester="voice")
        if run.status == "denied":
            approval = getattr(run, "approval_id", None)
            if approval:
                raise ApprovalRequiredError(
                    f"{name} needs approval: approve {approval} or grant the capability",
                    approval_id=approval,
                )
            raise PermissionDeniedError(run.error or f"{name} was refused")
        if run.status == "failed":
            raise ToolError(run.error or f"{name} failed")
        return run

    def _model(self, wanted: str):
        """The model a setting names, by id or by name, or None.

        `models.get` reports a miss as a `Result`, not an exception - unwrapping it wrongly is how
        the first version of this method raised AttributeError instead of saying "no such model".
        """
        try:
            found = self.ws.models.get(wanted)
        except Exception:  # noqa: BLE001 - a miss is a normal outcome here
            found = None
        if found is not None and not hasattr(found, "is_err"):
            return found
        if found is not None and not found.is_err:
            return found.value
        try:
            named = self.ws.models.by_name(wanted)
        except Exception:  # noqa: BLE001
            return None
        if hasattr(named, "is_err"):
            return None if named.is_err else named.value
        return named

    def _context(self, *, purpose: str, task_id: str | None = None) -> ToolContext:
        return ToolContext(task_id=task_id, purpose=purpose)

    def _artifacts_dir(self) -> Path:
        base = Path(self.ws.config.path("paths.artifacts")) / "media"
        base.mkdir(parents=True, exist_ok=True)
        return base

    # -- probing ----------------------------------------------------------
    def probe(
        self,
        path: str,
        *,
        retain: bool = False,
        force: bool = False,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Measure a file. Needs `fs.read`, because a header is still a file."""
        head_bytes = int(self.ws.config.get("voice.max_probe_bytes", 4096))
        try:
            run = self._execute(
                "fs.probe",
                {"path": path, "head_bytes": head_bytes},
                self._context(purpose=f"voice probe {path}", task_id=task_id),
            )
        except (ToolError, PermissionDeniedError, ApprovalRequiredError) as exc:
            # Something that could not be read is still a finding - a missing grant included.
            # Record the refusal, then say it; the row is what makes "it never even looked" the
            # same kind of answer as "it looked and the bytes made no sense".
            reason = getattr(exc, "message", None) or str(exc)
            self.manager.record_attempt(
                action="probe", status="refused", reason=reason, engine="fs.probe",
                task_id=task_id,
            )
            raise

        result = dict(run.result or {})
        sha = str(result["sha256"])
        existing = self.manager.asset_by_sha(sha)
        if existing is not None and not force:
            payload = existing.to_dict()
            payload["duplicate"] = True
            payload["measured_at"] = existing.created_at
            payload["this_probe"] = {
                "path": result["path"], "bytes": result["bytes"],
                "sha256_scope": result["sha256_scope"],
            }
            return payload

        head = bytes.fromhex(result.get("head_hex") or "")
        try:
            facts = media.sniff(head, total_bytes=int(result["bytes"]))
        except ValidationError as exc:
            self.manager.record_attempt(
                action="probe", status="refused", reason=exc.message, engine="media.sniff",
                task_id=task_id,
            )
            raise ValidationError(
                f"{result['path']} could not be measured: {exc.message}"
            ) from exc

        mismatch = media.check_name(result["path"], facts)
        metadata: dict[str, Any] = {}
        if retain:
            metadata["retained_path"] = self._retain(result, sha)

        asset = self.manager.record_asset(
            kind=facts.kind,
            format=facts.format,
            path=result["path"],
            sha256=sha,
            bytes=int(result["bytes"]),
            width=facts.width,
            height=facts.height,
            duration_ms=facts.duration_ms,
            sample_rate=facts.sample_rate,
            channels=facts.channels,
            bits_per_sample=facts.bits_per_sample,
            name_claim=media.extension_claim(result["path"]),
            name_mismatch=mismatch,
            facts={"details": facts.details, "notes": facts.notes,
                   "hash_scope": result.get("sha256_scope", "whole file")},
            task_id=task_id,
            metadata=metadata,
        )
        return self.view(asset.id)

    def _retain(self, result: dict[str, Any], sha: str) -> str:
        """Keep a copy of the bytes, but only when the user asked for that beforehand.

        `voice.retain_audio` is off by default because raw audio is the most identifying thing a
        home can hold. Turning it on is a decision, and the copy lands in the artifacts directory
        under the file's own hash, so the same recording is only ever stored once.
        """
        if not self.ws.config.get("voice.retain_audio", False):
            raise ValidationError(
                "retaining the bytes needs voice.retain_audio: "
                "`archx-agent config set voice.retain_audio true`"
            )
        source = self.ws.tools.runtime.resolve(result["path"])
        target_dir = self._artifacts_dir() / sha[:16]
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / Path(result["path"]).name
        if not target.exists():
            shutil.copyfile(source, target)
        return str(target)

    # -- reading the record ----------------------------------------------
    def view(self, asset_id: str) -> dict[str, Any]:
        asset = self.manager.get_asset(asset_id)
        payload = asset.to_dict()
        payload["transcripts"] = [t.to_dict() for t in self.manager.transcripts(asset.id)]
        payload["attempts"] = [a.to_dict() for a in self.manager.attempts(asset_id=asset.id)]
        payload["described"] = self._describe(asset)
        return payload

    @staticmethod
    def _describe(asset: MediaAsset) -> str:
        """A sentence built only from measured fields - nothing guessed from the name."""
        if asset.kind == "image":
            size = f"{asset.width}x{asset.height}" if asset.width and asset.height else "size unknown"
            return f"{asset.format} image, {size}, {asset.bytes} bytes"
        if asset.kind == "audio":
            ms = f"{asset.duration_ms} ms" if asset.duration_ms is not None else "duration unknown"
            spec = " ".join(
                part
                for part in (
                    f"{asset.sample_rate} Hz" if asset.sample_rate else "",
                    f"{asset.channels} ch" if asset.channels else "",
                    f"{asset.bits_per_sample}-bit" if asset.bits_per_sample else "",
                )
                if part
            )
            return f"{asset.format} audio, {ms}{', ' + spec if spec else ''}, {asset.bytes} bytes"
        if asset.kind == "text":
            chars = asset.facts.get("details", {}).get("text_chars")
            return f"text file, {asset.bytes} bytes" + (f", {chars} characters" if chars else "")
        return f"{asset.kind} file, {asset.bytes} bytes"

    def assets(self, *, kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return [asset.to_dict() for asset in self.manager.assets(kind=kind, limit=limit)]

    # -- the speech boundary ---------------------------------------------
    def blockers(self, action: str) -> list[str]:
        """Every reason this build cannot transcribe or synthesise speech, in the order found.

        Written as a list rather than a single sentence because the useful answer to "why can it
        not hear me" is the whole chain, and a test can make one link disappear and watch the next
        one become the first.
        """
        reasons: list[str] = []
        if not self.ws.config.get("voice.enabled", False):
            reasons.append(
                "voice features are off: `archx-agent config set voice.enabled true`"
            )
        key = "voice.stt_model" if action == "transcribe" else "voice.tts_model"
        wanted = str(self.ws.config.get(key, "") or "").strip()
        if not wanted:
            reasons.append(
                f"no model is named in {key}, and this build ships no speech weights"
            )
            reasons.append(self._adapter_reason(action))
            return reasons
        record = self._model(wanted)
        if record is None:
            reasons.append(
                f"{key} names {wanted!r}, but no model with that id or name is registered"
            )
            reasons.append(self._adapter_reason(action))
            return reasons
        capability = "transcription" if action == "transcribe" else "speech_generation"
        claimed = claimed_capabilities(record)
        if capability not in claimed:
            reasons.append(
                f"model {record.name!r} does not claim {capability} "
                f"(capabilities: {', '.join(claimed) or 'none recorded'})"
            )
        ready, why = self.ws.runtime_availability(record)
        if not ready:
            reasons.append(f"model {record.name!r} is registered but not ready: {why}")
        reasons.append(self._adapter_reason(action))
        return reasons

    @staticmethod
    def _adapter_reason(action: str) -> str:
        verb = "transcribe audio" if action == "transcribe" else "generate speech"
        return (
            f"no runtime in this build can {verb}: the adapters here speak chat and tools only, "
            "so a registered model is not enough"
        )

    def _refuse(self, action: str, *, asset_id: str | None = None, chars: int | None = None) -> VoiceAttempt:
        reasons = self.blockers(action)
        attempt = self.manager.record_attempt(
            action=action,
            status="refused",
            asset_id=asset_id,
            reason="; ".join(reasons),
            engine="none",
            chars=chars,
        )
        return attempt

    def transcribe(self, asset_id: str) -> dict[str, Any]:
        """Ask for words for a recording. Today this refuses, on the record, naming every gap."""
        asset = self.manager.get_asset(asset_id)
        if not asset.audio:
            article = "an" if asset.kind[:1] in "aeiou" else "a"
            raise ValidationError(
                f"{asset.path} is {article} {asset.kind}, not audio: "
                "there is nothing to transcribe"
            )
        attempt = self._refuse("transcribe", asset_id=asset.id)
        return {
            "asset_id": asset.id,
            "attempt_id": attempt.id,
            "status": attempt.status,
            "reason": attempt.reason,
            "reasons": self.blockers("transcribe"),
            "fix": (
                "attach words you typed with `archx-agent voice transcript add "
                f"{asset.id} --text '...'` - a human transcript is the one this build can record"
            ),
        }

    def say(self, text: str) -> dict[str, Any]:
        """Ask for speech from text. Today this refuses, on the record, naming every gap."""
        words = str(text or "").strip()
        if not words:
            raise ValidationError("there is nothing to say: pass some text")
        attempt = self._refuse("synthesize", chars=len(words))
        return {
            "attempt_id": attempt.id,
            "status": attempt.status,
            "chars": len(words),
            "reason": attempt.reason,
            "reasons": self.blockers("synthesize"),
        }

    # -- transcripts ------------------------------------------------------
    def add_transcript(
        self,
        asset_id: str,
        *,
        text: str | None = None,
        path: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Attach words a person wrote. Read from a file through `fs.read`, never guessed."""
        asset = self.manager.get_asset(asset_id)
        if text is not None and path:
            raise ValidationError("pass --text or --file, not both")
        if path:
            run = self._execute(
                "fs.read",
                {"path": path},
                self._context(purpose=f"voice transcript {path}", task_id=task_id),
            )
            text = str((run.result or {}).get("content") or "")
        if not str(text or "").strip():
            raise ValidationError("a transcript needs words: pass --text or --file")
        transcript = self.manager.record_transcript(
            asset.id, str(text), source="human", task_id=task_id,
            metadata={"from_file": path} if path else {},
        )
        self.manager.record_attempt(
            action="transcribe",
            status="completed",
            asset_id=asset.id,
            reason="the words were typed by a person, not recognised",
            engine="human",
            task_id=task_id,
        )
        return transcript.to_dict()

    def transcripts(self, asset_id: str) -> list[dict[str, Any]]:
        self.manager.get_asset(asset_id)
        return [t.to_dict() for t in self.manager.transcripts(asset_id)]

    def attempts(self, *, asset_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return [a.to_dict() for a in self.manager.attempts(asset_id=asset_id, limit=limit)]

    # -- summary ----------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        data = self.manager.stats()
        data.update(
            {
                "enabled": bool(self.ws.config.get("voice.enabled", False)),
                "retain_audio": bool(self.ws.config.get("voice.retain_audio", False)),
                "stt_model": str(self.ws.config.get("voice.stt_model", "") or "") or None,
                "tts_model": str(self.ws.config.get("voice.tts_model", "") or "") or None,
                "can_transcribe": not self.blockers("transcribe"),
                "can_speak": not self.blockers("synthesize"),
                "formats": ["png", "jpeg", "gif", "wav", "utf-8"],
            }
        )
        return data

    def get_asset(self, asset_id: str) -> MediaAsset:
        return self.manager.get_asset(asset_id)

