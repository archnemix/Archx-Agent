"""M34 - Voice and multimodal: what a file is, who wrote the words, and what cannot be heard.

This milestone could be faked in three ways, and the tests are organised around refusing each one:

1. **a media fact read from the file name.** `TestTheSniffer` builds containers byte by byte and
   checks the measurement, then checks that a misleading name is recorded *as a disagreement*
   instead of being adopted or rejected. `TestAMislabelledFile` does the same through the service,
   where the row is what matters.
2. **a transcript with no author.** `TestTranscriptionIsRefused` checks that asking for words gets a
   refusal with every reason in the chain, that the refusal is a row, and that the only transcript
   this build can store is one a person typed - the table refuses any other source.
3. **speech that is not speech.** `TestSynthesisIsRefused` checks the same for `voice say`, and
   `TestTheChainIsReal` removes one link at a time to show the reasons are computed from the
   workspace, not printed from a constant.

The media fixtures are generated here rather than committed: a 3-byte header written by the test
is a clearer statement of what the parser reads than a binary blob would be.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from archx_agent.application import media
from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    NotFoundError,
    ValidationError,
)
from archx_agent.managers.media import TRANSCRIPT_SOURCES
from archx_agent.managers.schema import SCHEMA_VERSION


# --------------------------------------------------------------------------
# fixtures: containers built byte by byte
# --------------------------------------------------------------------------
def png_bytes(width: int = 3, height: int = 2) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def jpeg_bytes(width: int = 40, height: int = 30) -> bytes:
    return (
        b"\xff\xd8"
        + b"\xff\xe0"
        + struct.pack(">H", 16)
        + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xc0"
        + struct.pack(">H", 17)
        + bytes([8])
        + struct.pack(">HH", height, width)
        + bytes([3])
        + b"\x01\x11\x00\x02\x11\x01\x03\x11\x01"
        + b"\xff\xd9"
    )


def gif_bytes(width: int = 7, height: int = 5) -> bytes:
    return (
        b"GIF89a"
        + struct.pack("<HH", width, height)
        + b"\xf7\x00\x00"
        + b"\x00" * 6
        + b";"
    )


def wav_bytes(*, rate: int = 8000, channels: int = 1, bits: int = 16, samples: int = 800) -> bytes:
    data = b"\x00\x00" * samples * channels
    block = channels * bits // 8
    fmt = struct.pack("<HHIIHH", 1, channels, rate, rate * block, block, bits)
    body = (
        b"WAVE"
        + b"fmt "
        + struct.pack("<I", 16)
        + fmt
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body


@pytest.fixture()
def lab(tmp_path) -> Path:
    """A directory inside the tool roots holding one of each container."""
    folder = tmp_path / "lab"
    folder.mkdir()
    (folder / "pixel.png").write_bytes(png_bytes(12, 8))
    (folder / "photo.jpg").write_bytes(jpeg_bytes(40, 30))
    (folder / "sprite.gif").write_bytes(gif_bytes(7, 5))
    (folder / "tone.wav").write_bytes(wav_bytes())
    (folder / "notes.txt").write_text("hello\nworld\n", encoding="utf-8")
    # A PNG wearing a .jpg name: the case the name-based pipeline gets wrong.
    (folder / "liar.jpg").write_bytes(png_bytes(4, 4))
    (folder / "mystery.bin").write_bytes(b"\x00\x01\x02\x03nope")
    (folder / "empty.dat").write_bytes(b"")
    return folder


@pytest.fixture()
def ws(tmp_path, lab):
    with open_workspace(
        home=str(tmp_path / "home"),
        overrides={"tools.roots": [str(lab)]},
        env={"ARCHX_ALLOW_SIMULATED": "1"},
    ) as workspace:
        yield workspace


@pytest.fixture()
def granted(ws):
    ws.permissions.grant("fs.read", subject="*", duration="persistent", confirm=True)
    return ws


@pytest.fixture()
def voice(granted):
    return granted.voice


# --------------------------------------------------------------------------
# the sniffer, on its own
# --------------------------------------------------------------------------
class TestTheSniffer:
    def test_png_dimensions_come_from_the_ihdr(self):
        facts = media.sniff(png_bytes(12, 8), total_bytes=len(png_bytes(12, 8)))
        assert (facts.kind, facts.format, facts.width, facts.height) == ("image", "png", 12, 8)
        assert facts.details["bit_depth"] == 8

    def test_jpeg_dimensions_come_from_the_start_of_frame(self):
        blob = jpeg_bytes(40, 30)
        facts = media.sniff(blob, total_bytes=len(blob))
        assert (facts.format, facts.width, facts.height) == ("jpeg", 40, 30)
        assert facts.details["sof_marker"] == "0xc0"

    def test_a_jpeg_with_no_frame_header_is_refused_rather_than_guessed(self):
        with pytest.raises(ValidationError):
            media.sniff(b"\xff\xd8\xff\xe0" + b"\x00" * 40, total_bytes=44)

    def test_gif_reads_the_screen_descriptor(self):
        blob = gif_bytes(7, 5)
        facts = media.sniff(blob, total_bytes=len(blob))
        assert (facts.format, facts.width, facts.height) == ("gif", 7, 5)
        assert facts.details["global_colour_table"] is True
        assert facts.details["version"] == "89a"

    def test_wav_reports_the_sample_format_and_the_duration_arithmetic(self):
        blob = wav_bytes(rate=8000, channels=1, bits=16, samples=800)
        facts = media.sniff(blob, total_bytes=len(blob))
        assert (facts.kind, facts.format) == ("audio", "wav")
        assert (facts.sample_rate, facts.channels, facts.bits_per_sample) == (8000, 1, 16)
        assert facts.duration_ms == 100, "800 mono frames at 8 kHz is a tenth of a second"

    def test_wav_duration_follows_the_sample_rate_not_a_guess(self):
        blob = wav_bytes(rate=16000, samples=16000)
        assert media.sniff(blob, total_bytes=len(blob)).duration_ms == 1000

    def test_a_wav_that_disagrees_with_itself_keeps_both_numbers(self):
        blob = wav_bytes()
        facts = media.sniff(blob[:60], total_bytes=52)
        assert facts.details["data_bytes_claimed"] == 1600
        assert facts.details["measured_bytes"] == 52
        assert any("1600" in note for note in facts.notes)

    def test_a_compressed_wav_is_refused_by_name(self):
        data = b"\x00" * 32
        fmt = struct.pack("<HHIIHH", 6, 1, 8000, 1000, 1, 8)  # 6 = A-law
        body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", len(data)) + data
        blob = b"RIFF" + struct.pack("<I", len(body)) + body
        with pytest.raises(ValidationError) as caught:
            media.sniff(blob, total_bytes=len(blob))
        assert "PCM" in str(caught.value)

    def test_text_is_measured_not_assumed(self):
        blob = b"hello\nworld\n"
        facts = media.sniff(blob, total_bytes=len(blob))
        assert (facts.kind, facts.text_chars, facts.text_lines) == ("text", 12, 2)

    def test_bytes_that_are_not_a_container_are_refused_with_the_head(self):
        with pytest.raises(ValidationError) as caught:
            media.sniff(b"\x00\x01\x02\x03", total_bytes=4)
        assert "00 01 02 03" in str(caught.value)

    def test_an_empty_file_has_nothing_to_measure(self):
        with pytest.raises(ValidationError):
            media.sniff(b"", total_bytes=0)

    def test_a_misleading_extension_is_a_disagreement_not_an_error(self):
        facts = media.sniff(png_bytes(4, 4), total_bytes=len(png_bytes(4, 4)))
        assert media.check_name("liar.jpg", facts) == "the name says 'jpg' but the bytes are png"
        assert media.check_name("honest.png", facts) is None
        assert media.check_name("a.jpeg", media.sniff(jpeg_bytes(), total_bytes=len(jpeg_bytes()))) is None
        assert media.check_name("no-extension", facts) is None


# --------------------------------------------------------------------------
# the schema
# --------------------------------------------------------------------------
class TestTheSchema:
    def test_media_is_a_versioned_migration(self, ws):
        assert SCHEMA_VERSION >= 24
        assert ws.store.schema_version() == SCHEMA_VERSION

    def test_the_three_tables_exist(self, ws):
        names = {
            row["name"]
            for row in ws.store.query("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"media_assets", "voice_attempts", "voice_transcripts"} <= names

    def test_the_asset_row_can_hold_a_mismatch_and_a_measurement(self, ws):
        columns = {row["name"] for row in ws.store.query("PRAGMA table_info(media_assets)")}
        assert {"sha256", "bytes", "width", "height", "duration_ms", "name_claim", "name_mismatch"} <= columns

    def test_a_fresh_home_has_measured_nothing(self, voice):
        stats = voice.stats()
        assert stats["assets"] == 0 and stats["attempts"] == 0 and stats["transcripts"] == 0

    def test_only_a_human_transcript_is_an_allowed_source(self):
        assert TRANSCRIPT_SOURCES == ("human",)


# --------------------------------------------------------------------------
# probing through the service
# --------------------------------------------------------------------------
class TestProbing:
    def test_an_image_is_measured_and_the_row_says_what_it_is(self, voice):
        asset = voice.probe("pixel.png")
        assert (asset["kind"], asset["format"]) == ("image", "png")
        assert (asset["width"], asset["height"]) == (12, 8)
        assert asset["sha256"] and asset["bytes"] > 0
        assert asset["name_mismatch"] is None
        assert asset["described"] == f"png image, 12x8, {asset['bytes']} bytes"

    def test_audio_carries_its_sample_rate_and_duration(self, voice):
        asset = voice.probe("tone.wav")
        assert asset["kind"] == "audio"
        assert (asset["sample_rate"], asset["channels"], asset["bits_per_sample"]) == (8000, 1, 16)
        assert asset["duration_ms"] == 100
        assert "8000 Hz" in asset["described"]

    def test_text_is_probed_as_text_not_refused(self, voice):
        asset = voice.probe("notes.txt")
        assert asset["kind"] == "text"
        assert asset["format"] == "utf-8"

    def test_the_hash_is_of_the_bytes_not_of_the_name(self, voice):
        first = voice.probe("pixel.png")
        # same bytes, different name: the same asset comes back, and says it is the same bytes
        import shutil

        source = Path(granted_root(voice)) / "pixel.png"
        clone = source.with_name("copy_of_pixel.png")
        shutil.copyfile(source, clone)
        again = voice.probe("copy_of_pixel.png")
        assert again["duplicate"] is True
        assert again["id"] == first["id"]
        assert again["this_probe"]["path"] == "copy_of_pixel.png"
        clone.unlink()

    def test_force_measures_the_same_bytes_into_a_second_row(self, voice, ws):
        first = voice.probe("pixel.png")
        second = voice.probe("pixel.png", force=True)
        assert second["id"] != first["id"]
        assert ws.media.stats()["assets"] == 2

    def test_a_mislabelled_file_is_stored_as_what_it_is(self, voice, ws):
        asset = voice.probe("liar.jpg")
        assert asset["format"] == "png", "the bytes decide, not the name"
        assert asset["name_claim"] == "jpg"
        assert asset["name_mismatch"] == "the name says 'jpg' but the bytes are png"
        assert ws.media.stats()["mislabelled"] == 1

    def test_an_unmeasurable_file_is_refused_and_the_refusal_is_a_row(self, voice, ws):
        with pytest.raises(ValidationError) as caught:
            voice.probe("mystery.bin")
        assert "could not be measured" in str(caught.value)
        attempt = ws.media.attempts()[0]
        assert attempt.action == "probe" and attempt.status == "refused"
        assert attempt.reason
        assert ws.media.stats()["assets"] == 0

    def test_an_empty_file_is_refused_without_a_row_of_its_own(self, voice):
        with pytest.raises(ValidationError):
            voice.probe("empty.dat")

    def test_probing_needs_fs_read(self, ws):
        with pytest.raises(ApprovalRequiredError):
            ws.voice.probe("pixel.png")

    def test_a_denied_probe_is_recorded_as_a_refused_attempt(self, ws):
        """"It never even looked" is still an answer worth keeping."""
        with pytest.raises(ApprovalRequiredError):
            ws.voice.probe("pixel.png")
        attempt = ws.media.attempts()[0]
        assert attempt.action == "probe" and attempt.status == "refused"
        assert "fs.probe" in attempt.reason
        assert ws.media.stats()["assets"] == 0

    def test_a_missing_file_is_a_tool_error(self, voice):
        from archx_agent.helpers.exceptions import ArchxError

        with pytest.raises(ArchxError):
            voice.probe("nope.png")

    def test_view_carries_the_transcripts_and_the_attempts(self, voice):
        asset = voice.probe("tone.wav")
        voice.add_transcript(asset["id"], text="a person typed this")
        shown = voice.view(asset["id"])
        assert [t["text"] for t in shown["transcripts"]] == ["a person typed this"]
        assert shown["attempts"][0]["status"] == "completed"

    def test_an_unknown_asset_is_not_found(self, voice):
        with pytest.raises(NotFoundError):
            voice.view("ma_nope")

    def test_the_list_filters_by_kind(self, voice):
        voice.probe("pixel.png")
        voice.probe("tone.wav")
        assert [a["kind"] for a in voice.assets(kind="audio")] == ["audio"]
        assert len(voice.assets()) == 2


def _simulated(ws, name: str = "sim", capabilities=("chat",)):
    """A test-double model: the only kind registerable without weights."""
    return ws.models.register_remote(
        name,
        provider="test-double",
        runtime="scripted",
        model_ref=f"simulated-{name}",
        context_length=8192,
        capabilities=list(capabilities),
        verification="unverified",
        claims={"simulated": True},
    )


def granted_root(voice) -> str:
    return voice.ws.tools.roots()[0]


# --------------------------------------------------------------------------
# retaining the bytes is a decision, not a default
# --------------------------------------------------------------------------
class TestRetainingBytes:
    def test_retaining_without_the_setting_is_refused_before_anything_is_copied(self, voice, ws):
        with pytest.raises(ValidationError) as caught:
            voice.probe("tone.wav", retain=True)
        assert "voice.retain_audio" in str(caught.value)
        assert ws.media.stats()["assets"] == 0, "a refused probe is not a row"

    def test_with_the_setting_on_the_bytes_land_under_their_own_hash(self, voice, ws):
        ws.config.set("voice.retain_audio", True)
        asset = voice.probe("tone.wav", retain=True)
        retained = Path(asset["metadata"]["retained_path"])
        assert retained.exists() and retained.name == "tone.wav"
        assert asset["sha256"][:16] in str(retained), "the same bytes are only stored once"
        assert retained.read_bytes() == Path(granted_root(voice), "tone.wav").read_bytes()
        assert voice.stats()["retain_audio"] is True


# --------------------------------------------------------------------------
# transcription: refused, on the record, with the whole chain
# --------------------------------------------------------------------------
class TestTranscriptionIsRefused:
    def test_asking_for_words_refuses_and_names_every_gap(self, voice):
        asset = voice.probe("tone.wav")
        result = voice.transcribe(asset["id"])
        assert result["status"] == "refused"
        reasons = result["reasons"]
        assert len(reasons) == 3
        assert "voice features are off" in reasons[0]
        assert "no model is named in voice.stt_model" in reasons[1]
        assert "no runtime in this build can transcribe audio" in reasons[2]

    def test_the_refusal_is_a_row_with_the_engine_that_was_consulted(self, voice, ws):
        asset = voice.probe("tone.wav")
        result = voice.transcribe(asset["id"])
        attempt = ws.media.get_attempt(result["attempt_id"])
        assert attempt.action == "transcribe"
        assert attempt.status == "refused"
        assert attempt.asset_id == asset["id"]
        assert "voice features are off" in attempt.reason
        assert ws.media.stats()["refused"] >= 1

    def test_nothing_pretends_to_be_a_transcript(self, voice, ws):
        asset = voice.probe("tone.wav")
        voice.transcribe(asset["id"])
        assert ws.media.stats()["transcripts"] == 0

    def test_an_image_cannot_be_transcribed_at_all(self, voice):
        asset = voice.probe("pixel.png")
        with pytest.raises(ValidationError) as caught:
            voice.transcribe(asset["id"])
        assert "not audio" in str(caught.value)

    def test_a_human_transcript_is_the_one_this_build_can_store(self, voice):
        asset = voice.probe("tone.wav")
        transcript = voice.add_transcript(asset["id"], text="  one two three  ")
        assert transcript["source"] == "human"
        assert transcript["text"] == "  one two three  ", "the words are kept as typed"
        assert transcript["chars"] == len("  one two three  ")
        assert voice.stats()["transcripts"] == 1

    def test_a_transcript_from_a_file_goes_through_fs_read(self, voice, lab):
        (lab / "words.txt").write_text("from a file, by a person\n", encoding="utf-8")
        asset = voice.probe("tone.wav")
        transcript = voice.add_transcript(asset["id"], path="words.txt")
        assert transcript["text"].strip() == "from a file, by a person"
        assert transcript["metadata"]["from_file"] == "words.txt"

    def test_a_transcript_with_no_words_is_refused(self, voice):
        asset = voice.probe("tone.wav")
        with pytest.raises(ValidationError):
            voice.add_transcript(asset["id"], text="   ")
        with pytest.raises(ValidationError):
            voice.add_transcript(asset["id"], text="x", path="notes.txt")

    def test_the_service_refuses_any_source_but_a_person(self, voice, ws):
        asset = voice.probe("tone.wav")
        with pytest.raises(ValidationError) as caught:
            ws.media.record_transcript(asset["id"], "made up", source="whisper")
        assert "no speech model" in str(caught.value)
        assert ws.media.stats()["transcripts"] == 0

    def test_the_table_refuses_it_too(self, voice, ws):
        """A CHECK in the schema, because a rule only the service keeps is a rule one writer skips."""
        import sqlite3

        asset = voice.probe("tone.wav")
        with pytest.raises(sqlite3.IntegrityError):
            ws.store.execute(
                "INSERT INTO voice_transcripts(id, asset_id, text, source, created_at)"
                " VALUES ('vt_x', ?, 'made up', 'whisper', '2026-01-01T00:00:00Z')",
                (asset["id"],),
            )
        assert ws.media.stats()["transcripts"] == 0

    def test_adding_a_transcript_records_the_attempt_that_produced_it(self, voice, ws):
        asset = voice.probe("tone.wav")
        voice.add_transcript(asset["id"], text="typed")
        completed = [a for a in ws.media.attempts() if a.status == "completed"]
        assert len(completed) == 1
        assert completed[0].engine == "human"
        assert "not recognised" in completed[0].reason


# --------------------------------------------------------------------------
# synthesis: the same refusal, for the same reasons
# --------------------------------------------------------------------------
class TestSynthesisIsRefused:
    def test_asking_for_speech_refuses_and_keeps_the_length(self, voice):
        result = voice.say("read this aloud")
        assert result["status"] == "refused"
        assert result["chars"] == len("read this aloud")
        assert "no runtime in this build can generate speech" in result["reasons"][-1]

    def test_the_attempt_is_a_row_with_no_asset(self, voice, ws):
        result = voice.say("hello")
        attempt = ws.media.get_attempt(result["attempt_id"])
        assert attempt.asset_id is None
        assert attempt.action == "synthesize"
        assert attempt.chars == 5

    def test_empty_text_is_a_validation_error_before_any_row(self, voice, ws):
        with pytest.raises(ValidationError):
            voice.say("   ")
        assert ws.media.stats()["attempts"] == 0

    def test_the_switch_is_the_first_reason_for_speech_too(self, voice):
        """Both directions of the mode read the same switch, so neither can quietly ignore it."""
        assert voice.say("hello")["reasons"][0].startswith("voice features are off")
        voice.ws.config.set("voice.enabled", True)
        result = voice.say("hello")
        assert result["reasons"][0].startswith("no model is named in voice.tts_model")


# --------------------------------------------------------------------------
# the chain is computed, not printed
# --------------------------------------------------------------------------
class TestTheChainIsReal:
    def test_turning_voice_on_removes_only_that_reason(self, voice):
        asset = voice.probe("tone.wav")
        before = voice.transcribe(asset["id"])["reasons"]
        voice.ws.config.set("voice.enabled", True)
        after = voice.transcribe(asset["id"])["reasons"]
        assert before[0] != after[0]
        assert len(after) == len(before) - 1
        assert not any("voice features are off" in reason for reason in after)

    def test_naming_a_model_that_does_not_exist_names_the_model(self, voice):
        voice.ws.config.set("voice.enabled", True)
        voice.ws.config.set("voice.stt_model", "whisper-large")
        reasons = voice.blockers("transcribe")
        assert "whisper-large" in reasons[0]
        assert "registered" in reasons[0]

    def test_a_registered_model_that_cannot_transcribe_is_reported_as_such(self, voice, ws):
        record = _simulated(ws, "tiny")
        voice.ws.config.set("voice.enabled", True)
        voice.ws.config.set("voice.stt_model", record.name)
        reasons = voice.blockers("transcribe")
        assert any("does not claim transcription" in reason for reason in reasons), reasons
        assert "no runtime in this build can transcribe audio" in reasons[-1]

    def test_a_model_that_does_claim_transcription_still_has_no_adapter(self, voice, ws):
        """The last link is the one that matters: a claim is not a runtime."""
        record = _simulated(ws, "claims-transcription", capabilities=["chat", "transcription"])
        voice.ws.config.set("voice.enabled", True)
        voice.ws.config.set("voice.stt_model", record.id)
        reasons = voice.blockers("transcribe")
        assert not any("does not claim transcription" in reason for reason in reasons), reasons
        reasons = voice.blockers("transcribe")
        assert reasons[-1] == (
            "no runtime in this build can transcribe audio: the adapters here speak chat and "
            "tools only, so a registered model is not enough"
        )

    def test_stats_says_plainly_whether_it_can_hear_or_speak(self, voice):
        stats = voice.stats()
        assert stats["can_transcribe"] is False and stats["can_speak"] is False
        assert stats["enabled"] is False
        assert stats["formats"] == ["png", "jpeg", "gif", "wav", "utf-8"]


# --------------------------------------------------------------------------
# the GUI is a client of the same service
# --------------------------------------------------------------------------
@pytest.fixture()
def gui(tmp_path, lab):
    from archx_agent.interfaces.gui.server import GuiApi

    with open_workspace(
        home=str(tmp_path / "home"),
        overrides={"tools.roots": [str(lab)]},
        env={"ARCHX_ALLOW_SIMULATED": "1"},
    ) as workspace:
        workspace.permissions.grant("fs.read", subject="*", duration="persistent", confirm=True)
        yield GuiApi(workspace), workspace


def http(api, method, path, *, body=None):
    from archx_agent.interfaces.gui.server import Request, split_target

    parsed_path, query, _token = split_target(path)
    request = Request(
        method=method,
        path=parsed_path,
        query=query,
        headers={"x-archx-token": api.token, "x-archx-request": "gui"},
        body=body,
    )
    response = api.dispatch(request)
    payload = response.payload
    if isinstance(payload, dict) and set(payload) == {"ok", "data"}:
        payload = payload["data"]
    return response.status, payload


class TestTheGuiIsTheSameService:
    def test_probing_in_the_page_is_the_row_the_cli_lists(self, gui):
        api, ws = gui
        status, asset = http(api, "POST", "/api/voice/probe", body={"path": "pixel.png"})
        assert status == 200
        assert ws.media.get_asset(asset["id"]).format == "png"
        _, listed = http(api, "GET", "/api/voice/assets")
        assert [row["id"] for row in listed["assets"]] == [asset["id"]]

    def test_a_mislabelled_file_says_so_over_http(self, gui):
        api, _ws = gui
        status, asset = http(api, "POST", "/api/voice/probe", body={"path": "liar.jpg"})
        assert status == 200
        assert asset["format"] == "png" and asset["name_mismatch"]

    def test_an_unmeasurable_file_is_a_400_with_the_reason(self, gui):
        api, _ws = gui
        status, payload = http(api, "POST", "/api/voice/probe", body={"path": "mystery.bin"})
        assert status == 400
        assert "could not be measured" in payload["error"]["message"]

    def test_transcribing_over_http_is_a_200_refusal_not_an_error(self, gui):
        """The mode not being able to hear is an answer, not a broken request."""
        api, _ws = gui
        _, asset = http(api, "POST", "/api/voice/probe", body={"path": "tone.wav"})
        status, result = http(api, "POST", f"/api/voice/assets/{asset['id']}/transcribe", body={})
        assert status == 200
        assert result["status"] == "refused"
        assert result["reasons"]

    def test_saying_something_over_http_is_a_200_refusal(self, gui):
        api, _ws = gui
        status, result = http(api, "POST", "/api/voice/say", body={"text": "hello"})
        assert status == 200 and result["status"] == "refused"

    def test_a_human_transcript_can_be_added_from_the_page(self, gui):
        api, ws = gui
        _, asset = http(api, "POST", "/api/voice/probe", body={"path": "tone.wav"})
        status, transcript = http(
            api, "POST", f"/api/voice/assets/{asset['id']}/transcripts",
            body={"text": "typed in the page"},
        )
        assert status == 200 and transcript["source"] == "human"
        assert [t.text for t in ws.media.transcripts(asset["id"])] == ["typed in the page"]

    def test_a_transcript_with_no_words_is_a_400(self, gui):
        api, _ws = gui
        _, asset = http(api, "POST", "/api/voice/probe", body={"path": "tone.wav"})
        status, payload = http(
            api, "POST", f"/api/voice/assets/{asset['id']}/transcripts", body={"text": ""}
        )
        assert status == 400

    def test_the_stats_endpoint_says_it_cannot_hear(self, gui):
        api, _ws = gui
        _, stats = http(api, "GET", "/api/voice/stats")
        assert stats["can_transcribe"] is False and stats["can_speak"] is False
        assert stats["assets"] == 0

    def test_an_unknown_asset_is_a_404(self, gui):
        api, _ws = gui
        status, _payload = http(api, "GET", "/api/voice/assets/ma_nope")
        assert status == 404

    def test_the_probe_needs_fs_read_in_the_page_too(self, tmp_path, lab):
        from archx_agent.interfaces.gui.server import GuiApi

        with open_workspace(
            home=str(tmp_path / "home2"),
            overrides={"tools.roots": [str(lab)]},
            env={"ARCHX_ALLOW_SIMULATED": "1"},
        ) as workspace:
            api = GuiApi(workspace)
            status, payload = http(api, "POST", "/api/voice/probe", body={"path": "pixel.png"})
            assert status == 403
            assert payload["error"]["code"] == "approval_required"


# --------------------------------------------------------------------------
# the tool layer
# --------------------------------------------------------------------------
class TestTheProbeTool:
    def test_fs_probe_is_registered_with_fs_read(self, ws):
        spec = ws.tools.spec("fs.probe")
        assert spec.capability == "fs.read"
        assert spec.inputs["path"]

    def test_fs_probe_returns_a_hash_and_the_head_but_no_text(self, granted):
        run = granted.tools.execute("fs.probe", {"path": "pixel.png"}, requester="test")
        assert run.status == "succeeded"
        assert run.result["sha256_scope"] == "whole file"
        assert run.result["binary"] is True
        assert "content" not in run.result

    def test_fs_read_still_refuses_a_binary_file(self, granted):
        """The probe is a second door, not a loosening of the first one."""
        from archx_agent.helpers.exceptions import ArchxError

        with pytest.raises(ArchxError):
            granted.tools.execute("fs.read", {"path": "pixel.png"}, requester="test")

    def test_fs_probe_needs_the_grant(self, ws):
        with pytest.raises(ApprovalRequiredError):
            ws.tools.execute("fs.probe", {"path": "pixel.png"}, requester="test")

    def test_the_head_is_bounded(self, granted):
        run = granted.tools.execute(
            "fs.probe", {"path": "tone.wav", "head_bytes": 8}, requester="test"
        )
        assert run.result["head_bytes"] == 8
