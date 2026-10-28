# Voice and media

This machine has no microphone, no camera, no GPU and no speech weights. A milestone called "voice
and multimodal" could pretend otherwise in three ways - invent a transcript, synthesise a plausible
waveform, or read an image's size out of its file name - and each of them would look like progress
for a week. This mode does none of them.

What it does is build the three things that are true on any machine, and refuse the rest by name:

1. **it measures** what a file is, from its own bytes;
2. **it keeps provenance** - a transcript says who wrote it, and the schema allows exactly one
   answer to that question today;
3. **it records its refusals**, in the same spirit as M33's refused moves: "there is no speech
   model here" is the most useful thing a voice mode can tell you on this hardware.

```bash
archx-agent voice probe photos/holiday.jpg      # measure it (needs fs.read)
archx-agent voice list --kind audio
archx-agent voice show ma_…                     # the facts, the words, the attempts
archx-agent voice transcribe ma_…               # refused: this build cannot hear
archx-agent voice transcript add ma_… --text "…" # the words *you* wrote
archx-agent voice say "read this aloud"         # refused: this build cannot speak
archx-agent voice attempts                      # every attempt, refusals included
archx-agent voice stats
```

The same operations are on the **Voice** page of the GUI, which calls the same service the CLI does.

## 1. A media fact is a fact only if it was read from the file

`src/archx_agent/application/media.py` parses containers by hand - no PIL, no ffmpeg, no `file`
binary. A header parse is about thirty lines per format, it cannot change under you, and a media
pipeline that only works when a 60 MB wheel is installed is one that will not run on the machine
that needs it.

| format | where the facts come from |
|--------|---------------------------|
| PNG | `IHDR`: width, height, bit depth, colour type |
| JPEG | the segment chain, walked to the start-of-frame (`C0`-`CF`): precision, width, height, components |
| GIF | the logical screen descriptor: version, width, height, global colour table |
| WAV | the `fmt ` chunk: sample rate, channels, bits, byte rate; the `data` chunk: length → duration |
| text | measured as bytes; characters and lines only when the whole file was read |

Everything else is refused, with the bytes it began with:

```
$ archx-agent voice probe mystery.bin
error: mystery.bin could not be measured: the first bytes are not a container this build
measures: 00 01 02 03 6e 6f 70 65 (png, jpeg, gif, wav and text only)
```

A compressed WAV (A-law, ADPCM) is refused by name rather than reported with a duration derived
from a byte rate that does not mean what it looks like.

**The name is a claim, and it is kept as one.** A PNG saved as `liar.jpg` is stored as a PNG, with
`name_claim = "jpg"` and `name_mismatch = "the name says 'jpg' but the bytes are png"`. That column
is counted in `voice stats` (`mislabelled`), shown on the page, and never used to decide what the
file is.

**A file that disagrees with itself keeps both numbers.** A WAV whose header claims 100 000 data
bytes in a 40-byte file is measured as 40 bytes with a note saying so; the note is in `facts.notes`,
not swallowed.

## 2. The same bytes are one asset

`probe` hashes the file (the whole file, or the head - and the row says which, `sha256_scope`) and
looks the hash up first. Measuring the same bytes twice returns the row that exists, with
`duplicate: true` and the path that was probed this time. `--force` stores a second row when you
want two names on the record.

## 3. Retaining the bytes is a decision

`voice.retain_audio` is off. With it off, `--retain` refuses *before* anything is copied, and says
which setting to change. With it on, the copy lands in the artifacts directory under the file's own
hash, so the same recording is stored once however many times it is probed.

## 4. Transcription: refused with the whole chain

`voice transcribe` walks a chain and reports **every** missing link, in the order found:

```
$ archx-agent voice transcribe ma_…; echo "exit $?"
refused ma_…  (attempt va_…)
  - voice features are off: `archx-agent config set voice.enabled true`
  - no model is named in voice.stt_model, and this build ships no speech weights
  - no runtime in this build can transcribe audio: the adapters here speak chat and tools only,
    so a registered model is not enough
exit 3
```

The reasons are computed from the workspace, not printed from a constant:

| state | first reason |
|-------|--------------|
| `voice.enabled` false | the switch, with the command that flips it |
| enabled, no `voice.stt_model` | no model is named |
| enabled, named model not registered | the name, and that nothing matches it |
| enabled, registered, no `transcription` claim | what the model *does* claim |
| enabled, registered, claims it, runtime not ready | the runtime's own readiness sentence |
| all of that | no adapter exists in this build - and that is the last line either way |

Exit code 3, not 1: nothing broke, and a script needs to tell "cannot" apart from "you typed
nothing" (which is 2). Every attempt is a row in `voice_attempts`, refusals included, with the
engine that was consulted (`fs.probe`, `media.sniff`, `none`, `human`).

The same chain, in the other direction, backs `voice say`.

## 5. The one transcript this build can keep is one a person wrote

```
$ archx-agent voice transcript add ma_… --text "the words a person typed"
recorded vt_…  [human]  26 chars
  these are the words a person wrote; nothing recognised them
```

`--file` reads the words through `fs.read`, like every other file access in this build. The `source`
column is `TEXT NOT NULL CHECK (source IN ('human'))`: not a convention the service enforces and
another writer could skip, but a constraint even a hand-written INSERT trips over. When an adapter
exists, adding a source is a migration with a reason - not a value that was quietly already allowed.

## 6. What is stored

| table | one row per | notes |
|-------|-------------|-------|
| `media_assets` | a measured file | kind, format, size, sha256, dimensions or duration, `name_claim`, `name_mismatch`, `facts` (JSON) |
| `voice_attempts` | an attempt to probe, transcribe or speak | `status` (`refused`/`completed`/`failed`), the reason, the engine, the length |
| `voice_transcripts` | words for one asset | `source` is CHECK-constrained to `human` |

Schema **v24**. Also new in this milestone: the `fs.probe` tool (capability `fs.read`, risk low),
which reads a file's head as bytes and hashes it - `fs.read` still refuses to decode a binary file
as text, because the point of the second door is not to loosen the first one.

## 7. Tests and acceptance

* `tests/test_voice_m34.py` - 67 tests. Containers built byte by byte (PNG, JPEG, GIF, WAV,
  mislabelled, truncated, compressed, empty, unknown); the chain checked link by link by removing
  one at a time; the CHECK constraint tested directly; the GUI returning the same rows.
* `scripts/acceptance_m34.sh` - 88 checks over the CLI and a real GUI socket, including a
  hand-written INSERT that the schema refuses.
* `scripts/gui_smoke.mjs` - 14 tabs; the Voice panel renders a measurement and the disagreement
  with the file name.

## 8. What this does not do

* No speech recognition, no synthesis, no image captioning, no OCR, no video, no microphone, no
  camera. Each says so by name, on the record.
* No transcoding, no thumbnails, no waveform rendering - those are transformations, and a
  transformation that claims to preserve provenance needs a record of its own.
* `formats` is png, jpeg, gif, wav and text. WebP, TIFF, FLAC, MP3 and MP4 are refused with their
  bytes, not guessed at from the extension.
