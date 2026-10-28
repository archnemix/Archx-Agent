#!/usr/bin/env bash
# SDK acceptance: the vendor clients Archx can drive, and the gates around them.
#
# This does not talk to any vendor. It starts one local server that speaks three protocols
# (OpenAI-compatible, Anthropic messages, Gemini generateContent) and then has each *official
# client* talk to it, through Archx, over real sockets. That checks the part we own: the
# request we let the SDK build, the answer we parse back, the error taxonomy, the credential
# handling, and the consent ladder.
#
#   ./scripts/acceptance_sdk.sh [home-dir]
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$HERE/.venv/bin/archx-agent"
PY="$HERE/.venv/bin/python"
HOME_DIR="${1:-$(mktemp -d /tmp/archx-sdk-XXXXXX)}"
export ARCHX_PATHS_HOME="$HOME_DIR"
export OPENAI_API_KEY="acceptance-openai-key-not-real"
export ANTHROPIC_API_KEY="acceptance-anthropic-key-not-real"
export GEMINI_API_KEY="acceptance-google-key-not-real"
export MISTRAL_API_KEY="acceptance-mistral-key-not-real"
KEY="$OPENAI_API_KEY"
mkdir -p "$HOME_DIR"

free_port() { "$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'; }
PORT="$(free_port)"
BASE="http://127.0.0.1:$PORT"
STUB_PID=""
FAILURES=0
CHECKS=()

say() { printf '\n### %s\n' "$*"; }
jq_() { "$PY" -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
has() { if grep -q -E -- "$1" "$2" 2>/dev/null; then echo 1; else echo 0; fi; }
check() {
  if [ "$2" = "$3" ]; then
    CHECKS+=("ok   | $1 | $2"); printf '[ok]   %s = %s\n' "$1" "$2"
  else
    CHECKS+=("FAIL | $1 | got '$2' want '$3'"); printf "[FAIL] %s: got '%s' want '%s'\n" "$1" "$2" "$3"
    FAILURES=$((FAILURES + 1))
  fi
}
cleanup() { [ -n "$STUB_PID" ] && kill "$STUB_PID" 2>/dev/null; wait 2>/dev/null; }
trap cleanup EXIT

say "home"
echo "$HOME_DIR"
"$CLI" init >/dev/null 2>&1
check "init exits 0" "$?" "0"

say "every official client Archx knows about"
"$CLI" models sdks >"$HOME_DIR/sdks.out" 2>&1
check "models sdks exits 0" "$?" "0"
for sdk in openai anthropic google mistral; do
  check "the catalogue lists $sdk" "$(has "^$sdk" "$HOME_DIR/sdks.out")" "1"
done
check "each row says where its key comes from" "$(has 'OPENAI_API_KEY' "$HOME_DIR/sdks.out")" "1"
check "an SDK that is not installed would say so, not be hidden" \
  "$(has 'installed|MISSING' "$HOME_DIR/sdks.out")" "1"

say "a local server that speaks three protocols"
"$PY" - "$PORT" <<'PY' >"$HOME_DIR/stub.log" 2>&1 &
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def _send(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def do_GET(self):
        self._send(200, {"object": "list", "data": [{"id": "local", "object": "model"}]})
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path.endswith("/messages") and b"anthropic" in (self.headers.get("user-agent", "").encode()):
            return self._send(200, {"id": "m", "type": "message", "role": "assistant", "model": "claude-stub",
                "content": [{"type": "text", "text": "answer via the anthropic SDK"}],
                "stop_reason": "end_turn", "usage": {"input_tokens": 12, "output_tokens": 4}})
        if "generateContent" in self.path:
            return self._send(200, {"candidates": [{"content": {"role": "model", "parts": [{"text": "answer via the google SDK"}]}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 3, "totalTokenCount": 12}, "modelVersion": "gemini-stub"})
        if self.path.endswith("/messages"):
            return self._send(200, {"id": "m", "type": "message", "role": "assistant", "model": "claude-stub",
                "content": [{"type": "text", "text": "answer via the anthropic SDK"}],
                "stop_reason": "end_turn", "usage": {"input_tokens": 12, "output_tokens": 4}})
        return self._send(200, {"id": "c", "object": "chat.completion", "created": 1, "model": "openai-stub",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "answer via the SDK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}})

ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
PY
STUB_PID=$!
for _ in $(seq 1 100); do
  "$PY" -c "import socket,sys; s=socket.socket(); s.settimeout(0.2); sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)" && break
  sleep 0.1
done
check "the local protocol server answers" "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/v1/models")" "200"

say "each SDK is registered through the CLI, with a reference and never a key"
for sdk in openai anthropic google mistral; do
  "$CLI" models add-sdk --name "m-$sdk" --sdk "$sdk" --model local \
    --base-url "$BASE" >"$HOME_DIR/add-$sdk.out" 2>&1
  check "add-sdk $sdk exits 0" "$?" "0"
  check "$sdk is registered as runtime=sdk" "$(has 'runtime=sdk' "$HOME_DIR/add-$sdk.out")" "1"
  check "$sdk's key is a reference" "$(has 'secret://env/' "$HOME_DIR/add-$sdk.out")" "1"
  check "$sdk's output does not contain its key" \
    "$(grep -c 'acceptance-.*-key-not-real' "$HOME_DIR/add-$sdk.out")" "0"
done
check "a literal key is refused" \
  "$("$CLI" models add-sdk --name literal --sdk openai --model local --credential-ref "$KEY" >/dev/null 2>&1; echo $?)" "2"
check "an unknown SDK is refused" \
  "$("$CLI" models add-sdk --name weird --sdk nonesuch --model local >/dev/null 2>&1; echo $?)" "2"

say "each SDK is actually driven, over a real socket"
for sdk in openai anthropic google mistral; do
  OUT="$("$CLI" models probe "m-$sdk" --capability chat 2>&1)"
  printf '%s\n' "$OUT" >"$HOME_DIR/probe-$sdk.out"
  # the verdict line, not every line containing the word
  check "$sdk probe passed" "$(grep -c '^chat: passed' "$HOME_DIR/probe-$sdk.out")" "1"
  check "$sdk probe did not substitute a test double" "$(printf '%s' "$OUT" | grep -c -i 'simulat')" "0"
done

say "a chat turn through the SDK becomes an ordinary task"
"$CLI" chat --message "hello" --model m-openai >"$HOME_DIR/chat.out" 2>&1
check "chat exits 0" "$?" "0"
check "the reply came back parsed" "$(has 'answer via the SDK' "$HOME_DIR/chat.out")" "1"
check "it is not labelled simulated" "$(has 'SIMULATED' "$HOME_DIR/chat.out")" "0"
check "the task records tokens from usage" \
  "$("$CLI" --json tasks list --limit 5 | jq_ "any((t.get('resource_use') or {}).get('completion_tokens') for t in d)")" "True"

say "the four consent rungs apply to SDK clients too"
"$CLI" models add-sdk --name cloud-openai --sdk openai --model gpt-4o-mini >"$HOME_DIR/cloud.out" 2>&1
"$CLI" chat --message hello --model cloud-openai >"$HOME_DIR/g1.out" 2>&1
check "rung 1: local_only refuses it" "$(has 'model.local_only is true' "$HOME_DIR/g1.out")" "1"
"$CLI" config set model.local_only false >/dev/null 2>&1
"$CLI" chat --message hello --model cloud-openai >"$HOME_DIR/g2.out" 2>&1
check "rung 2: an unregistered endpoint is refused" "$(has 'not a registered provider' "$HOME_DIR/g2.out")" "1"
"$CLI" providers add openai --template openai >/dev/null 2>&1
"$CLI" chat --message hello --model cloud-openai >"$HOME_DIR/g3.out" 2>&1
check "rung 3: unknown privacy terms are refused" "$(has 'privacy terms are unknown' "$HOME_DIR/g3.out")" "1"
"$CLI" providers confirm openai --data-leaves-device yes >/dev/null 2>&1
"$CLI" chat --message hello --model cloud-openai >"$HOME_DIR/g4.out" 2>&1
check "rung 4: missing consent is refused" "$(has 'record explicit consent' "$HOME_DIR/g4.out")" "1"

say "nothing kept the key"
check "no file under the home holds any key" \
  "$(grep -rl 'acceptance-.*-key-not-real' "$HOME_DIR" 2>/dev/null | wc -l | tr -d ' ')" "0"
check "the database does not contain a key" \
  "$("$PY" -c "
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
hits = 0
for (table,) in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\"):
    for row in conn.execute(f'SELECT * FROM \\\"{table}\\\"'):
        for value in row:
            if 'acceptance-' in str(value) and '-key-not-real' in str(value):
                hits += 1
print(hits)
" "$HOME_DIR/archx.db")" "0"
check "the trace does not contain one" \
  "$("$CLI" --json trace list --limit 200 2>/dev/null | grep -c 'key-not-real')" "0"

printf '\n### summary\n'
for line in "${CHECKS[@]}"; do printf '%s\n' "$line"; done
printf '\n'
if [ "$FAILURES" -eq 0 ]; then
  printf 'SDK acceptance: %s checks passed\n' "${#CHECKS[@]}"
else
  printf 'SDK ACCEPTANCE FAILED: %s of %s checks\n' "$FAILURES" "${#CHECKS[@]}"
fi
exit "$FAILURES"
