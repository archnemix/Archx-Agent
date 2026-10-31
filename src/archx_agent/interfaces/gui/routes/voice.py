"""HTTP endpoints for voice. Authentication is enforced by GuiApi.dispatch."""

from __future__ import annotations


import re


from typing import Any


from urllib.parse import unquote


from archx_agent.interfaces.gui.protocol import ApiError, Request, route


class VoiceRoutes:
    @route("GET", "/api/voice/assets", "Media this home has measured, newest first.")
    def get_voice_assets(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        kind = request.q("kind")
        if kind not in (None, "", "image", "audio", "text", "unknown"):
            raise ApiError(
                400, "validation", "kind must be image, audio, text or unknown"
            )
        assets = self.ws.voice.assets(
            kind=kind or None, limit=request.q_int("limit", 20)
        )
        return {
            "assets": assets,
            "roots": self.ws.tools.roots(),
            "stats": self.ws.voice.stats(),
        }

    @route(
        "POST",
        "/api/voice/probe",
        "Measure a file's bytes; the name is only a claim. (needs fs.read)",
    )
    def post_voice_probe(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        return self.ws.voice.probe(
            request.text("path", required=True) or "",
            retain=bool(request.payload().get("retain", False)),
            force=bool(request.payload().get("force", False)),
        )

    @route(
        "GET",
        "/api/voice/assets/{asset_id}",
        "One asset: what the bytes said, its words, its attempts.",
    )
    def get_voice_asset(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.voice.view(unquote(match.group("asset_id")))

    @route(
        "POST",
        "/api/voice/assets/{asset_id}/transcribe",
        "Ask for words (this build refuses, on the record).",
    )
    def post_voice_transcribe(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        # A refusal is the answer: 200 with `status: refused` and the reasons, so the page can
        # show what is missing instead of an error banner that implies a bug.
        return self.ws.voice.transcribe(unquote(match.group("asset_id")))

    @route(
        "GET",
        "/api/voice/assets/{asset_id}/transcripts",
        "The words attached to an asset.",
    )
    def get_voice_transcripts(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        asset_id = unquote(match.group("asset_id"))
        return {
            "asset_id": asset_id,
            "transcripts": self.ws.voice.transcripts(asset_id),
        }

    @route(
        "POST",
        "/api/voice/assets/{asset_id}/transcripts",
        "Attach words a person wrote.",
    )
    def post_voice_transcript(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        return self.ws.voice.add_transcript(
            unquote(match.group("asset_id")),
            text=request.text("text", required=False),
            path=request.text("path", required=False),
        )

    @route(
        "POST", "/api/voice/say", "Ask for speech (this build refuses, on the record)."
    )
    def post_voice_say(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.voice.say(request.text("text", required=True) or "")

    @route(
        "GET",
        "/api/voice/attempts",
        "Every attempt to hear or speak, including the refused ones.",
    )
    def get_voice_attempts(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        return {
            "attempts": self.ws.voice.attempts(
                asset_id=request.q("asset_id") or None, limit=request.q_int("limit", 30)
            )
        }

    @route(
        "GET", "/api/voice/stats", "What this home holds, and what it still cannot do."
    )
    def get_voice_stats(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        stats = self.ws.voice.stats()
        stats["reasons"] = {
            "transcribe": self.ws.voice.blockers("transcribe"),
            "synthesize": self.ws.voice.blockers("synthesize"),
        }
        return stats
