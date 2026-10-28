"""What a file *is*, measured from its own bytes.

There is no machine learning in this module and no dependency: it reads the first few hundred bytes
of a file and reports what the container itself declares. That is the whole point.

The rule it keeps
-----------------
**A media fact is a fact only if it was read from the file.** Not from the extension, not from what
the user said, not from a metadata block that can claim anything. So:

* a file called ``holiday.png`` that begins ``\\xff\\xd8\\xff`` is a JPEG, and is recorded as a JPEG -
  the extension is kept as a *claim*, alongside the measurement, and the two disagreeing is a
  finding rather than an error;
* a WAV header that says its data chunk is 100 000 bytes long when the file has 40 is reported as
  ``data_bytes_claimed`` versus ``bytes`` - the file disagrees with itself and both numbers are
  kept;
* a file whose first bytes are not a container this build can measure is refused with the bytes it
  began with, rather than guessed at.

Why no PIL, no ffmpeg, no `file` binary: a header parse is about thirty lines per format, it cannot
change under you, and a media pipeline that only works when a 60 MB wheel is installed is a media
pipeline that will not run on the machine that needs it. The formats here are the ones a "voice and
multimodal foundation" can honestly claim: PNG, JPEG, GIF, WAV, and plain text.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from typing import Any

from archx_agent.helpers.exceptions import ValidationError

#: Enough for every header this module understands, with room for a JPEG's segment chain.
SNIFF_BYTES = 4096

IMAGE_KINDS = ("image",)
AUDIO_KINDS = ("audio",)
KINDS = ("image", "audio", "text", "unknown")


@dataclass
class MediaFacts:
    """What the bytes said. Every field is either measured or explicitly absent."""

    kind: str
    format: str
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    bits_per_sample: int | None = None
    text_chars: int | None = None
    text_lines: int | None = None
    details: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "format": self.format,
            "width": self.width,
            "height": self.height,
            "duration_ms": self.duration_ms,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "bits_per_sample": self.bits_per_sample,
            "text_chars": self.text_chars,
            "text_lines": self.text_lines,
            "details": dict(self.details),
            "notes": list(self.notes),
        }


# --------------------------------------------------------------------------
# images
# --------------------------------------------------------------------------
def _png(head: bytes) -> MediaFacts:
    # signature(8) length(4) 'IHDR'(4) width(4) height(4) bitdepth(1) colourtype(1) ...
    if len(head) < 26 or head[12:16] != b"IHDR":
        raise ValidationError("PNG signature but no IHDR chunk in the first bytes")
    width, height = struct.unpack(">II", head[16:24])
    bit_depth, colour_type = head[24], head[25]
    depth = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(colour_type)
    return MediaFacts(
        kind="image",
        format="png",
        width=width,
        height=height,
        details={
            "bit_depth": bit_depth,
            "colour_type": colour_type,
            "channels": depth,
        },
        notes=[] if width and height else ["the IHDR reports a zero dimension"],
    )


_JPEG_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def _jpeg(head: bytes) -> MediaFacts:
    """Walk the segment chain to the start-of-frame; the size lives there, nowhere else."""
    index = 2
    while index + 9 < len(head):
        if head[index] != 0xFF:
            index += 1
            continue
        marker = head[index + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        length = struct.unpack(">H", head[index + 2 : index + 4])[0]
        if marker in _JPEG_SOF:
            precision = head[index + 4]
            height, width = struct.unpack(">HH", head[index + 5 : index + 9])
            components = head[index + 9]
            return MediaFacts(
                kind="image",
                format="jpeg",
                width=width,
                height=height,
                details={
                    "precision": precision,
                    "components": components,
                    "sof_marker": f"0x{marker:02x}",
                },
            )
        if marker == 0xDA:  # start of scan before any frame header: the file is malformed
            break
        index += 2 + length
    raise ValidationError("JPEG but no start-of-frame in the first bytes, so the size is unknown")


def _gif(head: bytes) -> MediaFacts:
    if len(head) < 13:
        raise ValidationError("GIF signature but the logical screen descriptor is truncated")
    width, height = struct.unpack("<HH", head[6:10])
    flags = head[10]
    return MediaFacts(
        kind="image",
        format="gif",
        width=width,
        height=height,
        details={
            "version": head[3:6].decode("ascii", "replace"),
            "global_colour_table": bool(flags & 0x80),
            "colour_resolution_bits": ((flags >> 4) & 0x07) + 1,
        },
    )


# --------------------------------------------------------------------------
# audio
# --------------------------------------------------------------------------
#: The largest WAV header this parser will walk. A `LIST`/`bext` chunk can push fmt/data a few
#: kilobytes into the file, and anything past this is a container this build does not claim.
_WAV_HEADER_LIMIT = 1_048_576


def _wav(head: bytes) -> MediaFacts:
    """RIFF/WAVE: the fmt chunk says what the samples are; the data chunk says how many."""
    if len(head) < 12 or head[8:12] != b"WAVE":
        raise ValidationError("RIFF but not WAVE, which this build does not measure")
    index = 12
    fmt: dict[str, int] = {}
    data_bytes: int | None = None
    chunks: list[str] = []
    while index + 8 <= len(head):
        name = head[index : index + 4]
        size = struct.unpack("<I", head[index + 4 : index + 8])[0]
        chunks.append(name.decode("ascii", "replace"))
        body = head[index + 8 : index + 8 + size]
        if name == b"fmt ":
            if len(body) < 16:
                raise ValidationError("WAV fmt chunk is truncated, so the sample format is unknown")
            audio_format, channels, rate, byte_rate, block_align, bits = struct.unpack(
                "<HHIIHH", body[:16]
            )
            fmt = {
                "audio_format": audio_format,
                "channels": channels,
                "sample_rate": rate,
                "byte_rate": byte_rate,
                "block_align": block_align,
                "bits_per_sample": bits,
            }
        elif name == b"data":
            data_bytes = size
            break
        index += 8 + size + (size & 1)  # chunks are word-aligned
        if index > _WAV_HEADER_LIMIT:  # pragma: no cover - defensive
            break
    if not fmt:
        raise ValidationError("WAV without a fmt chunk before the data, so nothing can be measured")
    duration = None
    if data_bytes is not None and fmt["byte_rate"]:
        duration = int(round(data_bytes / fmt["byte_rate"] * 1000))
    if fmt["audio_format"] not in (1, 3):
        raise ValidationError(
            f"WAV compression format {fmt['audio_format']} is not PCM or IEEE float; "
            "this build measures uncompressed audio only"
        )
    return MediaFacts(
        kind="audio",
        format="wav",
        duration_ms=duration,
        sample_rate=fmt["sample_rate"],
        channels=fmt["channels"],
        bits_per_sample=fmt["bits_per_sample"],
        details={"chunks": chunks, "data_bytes_claimed": data_bytes, **fmt},
    )


# --------------------------------------------------------------------------
# the sniffer
# --------------------------------------------------------------------------
def _text(head: bytes, total_bytes: int, *, truncated: bool) -> MediaFacts:
    text = head.decode("utf-8", "replace")
    return MediaFacts(
        kind="text",
        format="utf-8" if not truncated else "utf-8 (head)",
        text_chars=total_bytes if not truncated else None,
        text_lines=(text.count("\n") + (0 if text.endswith("\n") or not text else 1))
        if not truncated
        else None,
        details={"head_bytes": len(head)},
        notes=["only the first bytes were read, so text counts are absent"] if truncated else [],
    )


def sniff(head: bytes, *, total_bytes: int = 0) -> MediaFacts:
    """Identify a file from its first bytes. Raises `ValidationError` rather than guessing."""
    if not head:
        raise ValidationError("the file is empty, so there is nothing to measure")
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        facts = _png(head)
    elif head.startswith(b"\xff\xd8\xff"):
        facts = _jpeg(head)
    elif head[:6] in (b"GIF87a", b"GIF89a"):
        facts = _gif(head)
    elif head[:4] == b"RIFF":
        facts = _wav(head)
    elif b"\x00" not in head[:1024]:
        facts = _text(head, total_bytes or len(head), truncated=bool(total_bytes) and total_bytes > len(head))
    else:
        raise ValidationError(
            "the first bytes are not a container this build measures: "
            f"{head[:8].hex(' ')} (png, jpeg, gif, wav and text only)"
        )
    # A file that is smaller than the header it declares is a finding, not a failure.
    claimed = facts.details.get("data_bytes_claimed")
    if claimed is not None and total_bytes and claimed > total_bytes:
        facts.notes.append(
            f"the header claims {claimed} data bytes but the file is {total_bytes} bytes"
        )
    facts.details["measured_bytes"] = total_bytes
    return facts


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extension_claim(path: str) -> str:
    """What the *name* says the format is. Kept because a wrong name is worth knowing about."""
    name = str(path).rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def check_name(path: str, facts: MediaFacts) -> str | None:
    """Return the disagreement between the extension and the measurement, or None.

    A `.png` that is really a JPEG is not an error - the file is still readable - but a record that
    silently adopts the extension would be wrong about what is stored.
    """
    claim = extension_claim(path)
    if not claim:
        return None
    aliases = {"jpg": "jpeg", "jpe": "jpeg", "wave": "wav", "text": "utf-8", "txt": "utf-8", "md": "utf-8"}
    normalised = aliases.get(claim, claim)
    actual = aliases.get(facts.format, facts.format)
    if normalised != actual:
        return f"the name says {claim!r} but the bytes are {facts.format}"
    return None
