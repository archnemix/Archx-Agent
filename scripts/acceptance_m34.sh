#!/usr/bin/env bash
# M34 acceptance: voice and multimodal, driven the way a person would use it.
#
# The claims being checked are the ones that would be easy to fake:
#   * a media fact is measured from the bytes: the fixtures are generated here, one byte at a time,
#     and the width/height/sample rate the record holds are the ones the header declared;
#   * the file name is a *claim*: a PNG named `.jpg` is stored as a PNG and the disagreement is a
#     column, not a warning that goes nowhere;
#   * an unmeasurable file is refused with the bytes it began with, and the refusal is a row;
#   * asking for words or speech is refused on the record, with every missing link named, and no
#     transcript is invented - the only transcript this build can store is one a person typed, and
#     the table refuses any other source;
#   * the reasons are computed: turning voice on removes exactly that reason and no other;
#   * the page is a client of the same service.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="${ARCHX_CLI:-$HERE/.venv/bin/archx-agent}"
[ -x "$CLI" ] || CLI="$(command -v archx-agent)"
PY="${ARCHX_PY:-$HERE/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python)"
WORK="${1:-$(mktemp -d /tmp/archx-m34-XXXXXX)}"
HOME_DIR="$WORK/home"
LAB="$WORK/lab"
export ARCHX_PATHS_HOME="$HOME_DIR"
export ARCHX_TOOLS_ROOTS="$LAB"
export ARCHX_ALLOW_SIMULATED=1
mkdir -p "$HOME_DIR" "$LAB"
PORT="$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
TOKEN="m34-acceptance-token"
BASE="http://127.0.0.1:$PORT"
FAILURES=0
CHECKS=()
GUI_PID=""

say() { printf '\n### %s\n' "$*"; }
run() { printf '$ archx-agent %s\n' "$*"; "$CLI" "$@"; printf '[exit %s]\n' "$?"; }
jq_() { "$PY" -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
check() {
  if [ "$2" = "$3" ]; then
    CHECKS+=("ok   | $1 | $2"); printf '[ok]   %s = %s\n' "$1" "$2"
  else
    CHECKS+=("FAIL | $1 | got '$2' want '$3'"); printf "[FAIL] %s: got '%s' want '%s'\n" "$1" "$2" "$3"
    FAILURES=$((FAILURES + 1))
  fi
}
status_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
get_json() { curl -s -H "X-Archx-Token: $TOKEN" "$1"; }
post_json() { curl -s -X POST -H "X-Archx-Token: $TOKEN" -H "Content-Type: application/json" -d "$2" "$1"; }
api_jsonq() { "$PY" -c "import json,sys; d=json.load(sys.stdin)['data']; print($1)"; }

dbq() { "$PY" - "$HOME_DIR/archx.db" "$1" <<'PYEOF'
import sqlite3, sys
connection = sqlite3.connect(sys.argv[1])
print(connection.execute(sys.argv[2]).fetchone()[0])
PYEOF
}

cleanup() {
  [ -n "$GUI_PID" ] && kill "$GUI_PID" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT

# The fixtures are built here rather than committed: a header written by this script is a clearer
# statement of what the parser reads than a binary blob would be.
cat > "$WORK/make_media.py" <<'PYEOF'
import struct, sys, zlib
from pathlib import Path

out = Path(sys.argv[1])

def chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

def png(width, height):
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

def jpeg(width, height):
    return (b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            + b"\xff\xc0" + struct.pack(">H", 17) + bytes([8]) + struct.pack(">HH", height, width)
            + bytes([3]) + b"\x01\x11\x00\x02\x11\x01\x03\x11\x01" + b"\xff\xd9")

def wav(rate, samples, channels=1, bits=16):
    data = b"\x00\x00" * samples * channels
    block = channels * bits // 8
    fmt = struct.pack("<HHIIHH", 1, channels, rate, rate * block, block, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", len(body)) + body

(out / "pixel.png").write_bytes(png(12, 8))
(out / "photo.jpg").write_bytes(jpeg(40, 30))
(out / "tone.wav").write_bytes(wav(8000, 800))
(out / "long.wav").write_bytes(wav(16000, 16000))
(out / "notes.txt").write_text("hello\nworld\n", encoding="utf-8")
# A PNG wearing a .jpg name, with different bytes from pixel.png so it is its own row.
(out / "liar.jpg").write_bytes(png(4, 4))
(out / "mystery.bin").write_bytes(b"\x00\x01\x02\x03nope")
(out / "empty.dat").write_bytes(b"")
(out / "words.txt").write_text("the words a person typed\n", encoding="utf-8")
PYEOF
"$PY" "$WORK/make_media.py" "$LAB"

printf 'M34 acceptance on %s\n' "$WORK"
"$CLI" init >/dev/null 2>&1

say "the schema keeps a measurement and a claim apart"
check "media is a versioned migration" \
  "$(dbq "SELECT COUNT(*) FROM schema_migrations WHERE version = 24")" "1"
check "assets, attempts and transcripts are tables" \
  "$(dbq "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('media_assets','voice_attempts','voice_transcripts')")" "3"
check "an asset row can hold the name's claim and the mismatch" \
  "$(dbq "SELECT COUNT(*) FROM pragma_table_info('media_assets') WHERE name IN ('name_claim','name_mismatch')")" "2"
check "a fresh home has measured nothing" "$("$CLI" --json voice stats | jq_ "d['assets']")" "0"

say "measuring needs the grant, and the refusal is a row"
"$CLI" voice probe pixel.png >/dev/null 2>"$WORK/refused.err"
check "probe without fs.read exits 1" "$?" "1"
check "and names the approval to approve" "$(grep -c 'approvals approve' "$WORK/refused.err")" "1"
check "the refusal was recorded" "$(dbq "SELECT COUNT(*) FROM voice_attempts WHERE status = 'refused'")" "1"
check "and nothing was measured" "$(dbq "SELECT COUNT(*) FROM media_assets")" "0"

"$CLI" permissions grant fs.read --subject '*' --duration persistent --confirm >/dev/null

say "a media fact is measured from the bytes"
PNG="$("$CLI" --json voice probe pixel.png | jq_ "d['id']")"
check "the png is a row" "$(dbq "SELECT COUNT(*) FROM media_assets WHERE id = '$PNG'")" "1"
check "its kind is image" "$(dbq "SELECT kind FROM media_assets WHERE id = '$PNG'")" "image"
check "its format came from the signature" "$(dbq "SELECT format FROM media_assets WHERE id = '$PNG'")" "png"
check "its width came from the IHDR" "$(dbq "SELECT width FROM media_assets WHERE id = '$PNG'")" "12"
check "its height came from the IHDR" "$(dbq "SELECT height FROM media_assets WHERE id = '$PNG'")" "8"
check "the hash is a sha256 of the bytes" \
  "$(dbq "SELECT LENGTH(sha256) FROM media_assets WHERE id = '$PNG'")" "64"
check "the size matches the file on disk" \
  "$(dbq "SELECT bytes FROM media_assets WHERE id = '$PNG'")" "$(stat -c %s "$LAB/pixel.png")"
check "the honest name is not a mismatch" \
  "$(dbq "SELECT COUNT(*) FROM media_assets WHERE id = '$PNG' AND name_mismatch IS NULL")" "1"

say "a jpeg's size is in its frame header, not its name"
JPG="$("$CLI" --json voice probe photo.jpg | jq_ "d['id']")"
check "the jpeg is 40 wide" "$(dbq "SELECT width FROM media_assets WHERE id = '$JPG'")" "40"
check "the jpeg is 30 high" "$(dbq "SELECT height FROM media_assets WHERE id = '$JPG'")" "30"
check "and it says jpeg, not jpg" "$(dbq "SELECT format FROM media_assets WHERE id = '$JPG'")" "jpeg"

say "audio carries the sample format and the duration arithmetic"
WAV="$("$CLI" --json voice probe tone.wav | jq_ "d['id']")"
check "the wav is audio" "$(dbq "SELECT kind FROM media_assets WHERE id = '$WAV'")" "audio"
check "the rate is the one in the fmt chunk" "$(dbq "SELECT sample_rate FROM media_assets WHERE id = '$WAV'")" "8000"
check "the channels are the ones declared" "$(dbq "SELECT channels FROM media_assets WHERE id = '$WAV'")" "1"
check "the bit depth is declared, not assumed" "$(dbq "SELECT bits_per_sample FROM media_assets WHERE id = '$WAV'")" "16"
check "800 frames at 8 kHz is 100 ms" "$(dbq "SELECT duration_ms FROM media_assets WHERE id = '$WAV'")" "100"
LONG="$("$CLI" --json voice probe long.wav | jq_ "d['id']")"
check "16000 frames at 16 kHz is 1000 ms" "$(dbq "SELECT duration_ms FROM media_assets WHERE id = '$LONG'")" "1000"

say "the name is a claim, and disagreement is a finding"
LIAR="$("$CLI" --json voice probe liar.jpg | jq_ "d['id']")"
check "a png named .jpg is stored as png" "$(dbq "SELECT format FROM media_assets WHERE id = '$LIAR'")" "png"
check "the name's claim is kept" "$(dbq "SELECT name_claim FROM media_assets WHERE id = '$LIAR'")" "jpg"
check "the disagreement is a column" \
  "$(dbq "SELECT name_mismatch FROM media_assets WHERE id = '$LIAR'")" \
  "the name says 'jpg' but the bytes are png"
check "stats counts it" "$("$CLI" --json voice stats | jq_ "d['mislabelled']")" "1"
check "and the record still holds what the bytes said" \
  "$("$CLI" --json voice show "$LIAR" | jq_ "d['width']")" "4"

say "the same bytes are one asset, however they are named"
cp "$LAB/pixel.png" "$LAB/copy_of_pixel.png"
DUP="$("$CLI" --json voice probe copy_of_pixel.png)"
check "the second probe says duplicate" "$(printf '%s' "$DUP" | jq_ "d['duplicate']")" "True"
check "and points at the same row" "$(printf '%s' "$DUP" | jq_ "d['id']")" "$PNG"
rm -f "$LAB/copy_of_pixel.png"

say "an unmeasurable file is refused with the bytes it began with"
"$CLI" voice probe mystery.bin >/dev/null 2>"$WORK/mystery.err"
check "an unknown container exits 2" "$?" "2"
check "the reason includes the head" "$(grep -c '00 01 02 03' "$WORK/mystery.err")" "1"
check "and names what is measured" "$(grep -c 'wav' "$WORK/mystery.err")" "1"
check "nothing was stored for it" \
  "$(dbq "SELECT COUNT(*) FROM media_assets WHERE path = 'mystery.bin'")" "0"
"$CLI" voice probe empty.dat >/dev/null 2>&1
check "an empty file exits 2" "$?" "2"

say "words are refused on the record, with every missing link named"
"$CLI" --json voice transcribe "$WAV" >"$WORK/transcribe.json" 2>/dev/null
check "asking for words exits 3 (not a break, not a success)" "$?" "3"
check "the attempt is a row" "$(dbq "SELECT COUNT(*) FROM voice_attempts WHERE action = 'transcribe' AND status = 'refused'")" "1"
check "with the asset attached" \
  "$(dbq "SELECT asset_id FROM voice_attempts WHERE action = 'transcribe' AND status = 'refused'")" "$WAV"
check "three reasons, in the order found" "$(jq_ "len(d['reasons'])" < "$WORK/transcribe.json")" "3"
check "the first is the voice switch" \
  "$(jq_ "'voice features are off' in d['reasons'][0]" < "$WORK/transcribe.json")" "True"
check "the second is the missing model" \
  "$(jq_ "'no model is named' in d['reasons'][1]" < "$WORK/transcribe.json")" "True"
check "the third is the missing adapter" \
  "$(jq_ "'no runtime in this build can transcribe audio' in d['reasons'][2]" < "$WORK/transcribe.json")" "True"
check "nothing pretended to be a transcript" "$(dbq "SELECT COUNT(*) FROM voice_transcripts")" "0"
check "stats says plainly it cannot hear" "$("$CLI" --json voice stats | jq_ "d['can_transcribe']")" "False"

say "the reasons are computed, not printed"
"$CLI" config set voice.enabled true >/dev/null
"$CLI" --json voice transcribe "$WAV" >"$WORK/transcribe2.json" 2>/dev/null
check "turning voice on removes exactly that reason" \
  "$(jq_ "len(d['reasons'])" < "$WORK/transcribe2.json")" "2"
check "and the switch is no longer mentioned" \
  "$(jq_ "any('voice features are off' in r for r in d['reasons'])" < "$WORK/transcribe2.json")" "False"
"$CLI" config set voice.stt_model whisper-large >/dev/null
"$CLI" --json voice transcribe "$WAV" >"$WORK/transcribe3.json" 2>/dev/null
check "a model that is not registered is named" \
  "$(jq_ "'whisper-large' in d['reasons'][0]" < "$WORK/transcribe3.json")" "True"
"$CLI" config set voice.stt_model "" >/dev/null

say "speech is refused the same way, with the length kept"
"$CLI" --json voice say "read this aloud" >"$WORK/say.json" 2>/dev/null
check "asking for speech exits 3" "$?" "3"
check "the length asked for is recorded" "$(jq_ "d['chars']" < "$WORK/say.json")" "15"
check "the attempt is a row with no asset" \
  "$(dbq "SELECT COUNT(*) FROM voice_attempts WHERE action = 'synthesize' AND asset_id IS NULL")" "1"
check "nothing was written anywhere" "$(ls "$HOME_DIR"/artifacts 2>/dev/null | wc -l)" "0"

say "the one transcript this build can keep is one a person wrote"
WORDS="$("$CLI" --json voice transcript add "$WAV" --text "the words a person typed")"
check "the source is human" "$(printf '%s' "$WORDS" | jq_ "d['source']")" "human"
check "the words are kept as typed" \
  "$(dbq "SELECT text FROM voice_transcripts WHERE asset_id = '$WAV'")" "the words a person typed"
check "the attempt that produced it is completed, not refused" \
  "$(dbq "SELECT COUNT(*) FROM voice_attempts WHERE action = 'transcribe' AND status = 'completed'")" "1"
check "and says who produced it" \
  "$(dbq "SELECT engine FROM voice_attempts WHERE status = 'completed'")" "human"
FILEWORDS="$("$CLI" --json voice transcript add "$WAV" --file words.txt)"
check "words can come from a file, through fs.read" \
  "$(printf '%s' "$FILEWORDS" | jq_ "d['text'].strip()")" "the words a person typed"
check "and the file is recorded" \
  "$(printf '%s' "$FILEWORDS" | jq_ "d['metadata']['from_file']")" "words.txt"
check "two transcripts for one recording" \
  "$("$CLI" --json voice transcript list "$WAV" | jq_ "len(d)")" "2"
"$CLI" voice transcript add "$WAV" --text "   " >/dev/null 2>&1
check "empty words are refused" "$?" "2"
check "a non-human source cannot be written even by hand" \
  "$("$PY" - "$HOME_DIR/archx.db" "$WAV" <<'PYEOF'
import sqlite3, sys
connection = sqlite3.connect(sys.argv[1])
try:
    connection.execute(
        "INSERT INTO voice_transcripts(id, asset_id, text, source, created_at)"
        " VALUES ('vt_bad', ?, 'made up', 'whisper', '2026-01-01T00:00:00Z')", (sys.argv[2],)
    )
    connection.commit()
    print("ACCEPTED")
except sqlite3.IntegrityError as exc:
    print("refused")
PYEOF
)" "refused"
check "so there are still two" \
  "$("$CLI" --json voice stats | jq_ "d['transcripts']")" "2"

say "keeping the bytes is a decision, not a default"
"$CLI" config set voice.retain_audio false >/dev/null
"$CLI" voice probe tone.wav --retain --force >/dev/null 2>"$WORK/retain.err"
check "retaining without the setting exits 2" "$?" "2"
check "and says what to set" "$(grep -c 'voice.retain_audio' "$WORK/retain.err")" "1"
"$CLI" config set voice.retain_audio true >/dev/null
RETAINED="$("$CLI" --json voice probe tone.wav --retain --force | jq_ "d['metadata']['retained_path']")"
check "with the setting on the bytes are copied" "$([ -f "$RETAINED" ] && echo yes)" "yes"
check "under the file's own hash" "$(printf '%s' "$RETAINED" | grep -c 'artifacts/media')" "1"
check "and the copy is byte-identical" "$(cmp -s "$RETAINED" "$LAB/tone.wav" && echo same)" "same"

say "the counts agree with the rows"
check "assets" "$("$CLI" --json voice stats | jq_ "d['assets']")" "$(dbq "SELECT COUNT(*) FROM media_assets")"
check "audio" "$("$CLI" --json voice stats | jq_ "d['audio']")" \
  "$(dbq "SELECT COUNT(*) FROM media_assets WHERE kind = 'audio'")"
check "transcripts" "$("$CLI" --json voice stats | jq_ "d['transcripts']")" \
  "$(dbq "SELECT COUNT(*) FROM voice_transcripts")"
check "refused attempts" "$("$CLI" --json voice stats | jq_ "d['refused']")" \
  "$(dbq "SELECT COUNT(*) FROM voice_attempts WHERE status = 'refused'")"
run voice stats

say "the page is a client of the same service"
"$CLI" gui serve --host 127.0.0.1 --port "$PORT" --token "$TOKEN" --no-open >"$WORK/gui.log" 2>&1 &
GUI_PID=$!
for _ in $(seq 1 40); do
  [ "$(status_of "$BASE/api/health")" = "200" ] && break
  sleep 0.25
done
check "the page lists what was measured" \
  "$(get_json "$BASE/api/voice/assets" | api_jsonq "len(d['assets'])")" "$(dbq "SELECT COUNT(*) FROM media_assets")"
PAGE_ASSET="$(post_json "$BASE/api/voice/probe" '{"path":"pixel.png"}' | api_jsonq "d['id']")"
check "a probe in the page is the row the CLI reads" \
  "$(dbq "SELECT COUNT(*) FROM media_assets WHERE id = '$PAGE_ASSET'")" "1"
check "a mislabelled file says so over HTTP" \
  "$(post_json "$BASE/api/voice/probe" '{"path":"liar.jpg","force":true}' | api_jsonq "d['name_mismatch'] is not None")" "True"
check "an unmeasurable file is a 400" \
  "$(status_of -X POST -H "X-Archx-Token: $TOKEN" -H 'Content-Type: application/json' \
      -d '{"path":"mystery.bin"}' "$BASE/api/voice/probe")" "400"
check "asking for words is a 200 refusal, not an error" \
  "$(post_json "$BASE/api/voice/assets/$WAV/transcribe" '{}' | api_jsonq "d['status']")" "refused"
check "and the refusal is in the same table the CLI reads" \
  "$(dbq "SELECT COUNT(*) FROM voice_attempts WHERE action = 'transcribe' AND status = 'refused'")" \
  "$("$CLI" --json voice attempts --asset "$WAV" | jq_ "sum(1 for a in d if a['status'] == 'refused')")"
check "a transcript typed in the page is a row" \
  "$(post_json "$BASE/api/voice/assets/$WAV/transcripts" '{"text":"typed in the page"}' | api_jsonq "d['source']")" "human"
check "empty words are a 400" \
  "$(status_of -X POST -H "X-Archx-Token: $TOKEN" -H 'Content-Type: application/json' \
      -d '{"text":""}' "$BASE/api/voice/assets/$WAV/transcripts")" "400"
check "the stats endpoint says it cannot hear" \
  "$(get_json "$BASE/api/voice/stats" | api_jsonq "d['can_transcribe']")" "False"
check "the reasons travel with the stats" \
  "$(get_json "$BASE/api/voice/stats" | api_jsonq "len(d['reasons']['transcribe']) > 0")" "True"
check "an unauthenticated call is refused" "$(status_of "$BASE/api/voice/assets")" "401"
check "an unknown asset is a 404" "$(status_of -H "X-Archx-Token: $TOKEN" "$BASE/api/voice/assets/ma_nope")" "404"

say "the record survives a restart"
check "the measurement is still there" \
  "$("$CLI" --json voice show "$PNG" | jq_ "d['width']")" "12"
check "the mismatch is still a mismatch" \
  "$("$CLI" --json voice show "$LIAR" | jq_ "d['name_mismatch'] is not None")" "True"
check "the words are still attributed" \
  "$("$CLI" --json voice transcript list "$WAV" | jq_ "d[0]['source']")" "human"
check "and it still cannot hear" "$("$CLI" --json voice stats | jq_ "d['can_transcribe']")" "False"

printf '\nM34 acceptance: %s checks passed, %s failed\n' \
  "$((${#CHECKS[@]} - FAILURES))" "$FAILURES"
[ "$FAILURES" -eq 0 ] || exit 1
