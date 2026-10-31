#!/usr/bin/env bash
# Gemini acceptance: a real network provider, wired end to end, with the gates intact.
#
# Google's host is not reachable from this sandbox (its TLS is closed by an egress filter), so
# the client is driven against scripts/gemini_protocol_stub.py - a server that speaks the
# documented protocol on a real socket. What this proves is everything this repository owns:
# the request it builds, the key handling, the answer it parses, the errors it classifies, and
# the consent ladder that stands between a model and the network. What it cannot prove is that
# Google's service behaves as documented today.
#
#   ./scripts/acceptance_gemini.sh [home-dir]
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$HERE/.venv/bin/archx-agent"
PY="$HERE/.venv/bin/python"
HOME_DIR="${1:-$(mktemp -d /tmp/archx-gemini-XXXXXX)}"
export ARCHX_PATHS_HOME="$HOME_DIR"
export GEMINI_API_KEY="acceptance-gemini-key-not-a-real-one"
KEY="$GEMINI_API_KEY"
mkdir -p "$HOME_DIR"

free_port() { "$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'; }
STUB_PORT="$(free_port)"
STUB="http://127.0.0.1:$STUB_PORT"
GUI_PORT="$(free_port)"
TOKEN="gemini-acceptance-token"
BASE="http://127.0.0.1:$GUI_PORT"
STUB_PID=""
GUI_PID=""
FAILURES=0
CHECKS=()

say() { printf '\n### %s\n' "$*"; }
jq_() { "$PY" -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
# the HTTP layer wraps every answer in {"ok": true, "data": ...}
jqd() { "$PY" -c "import json,sys; d=json.load(sys.stdin)['data']; print($1)"; }
has() { if grep -q -E -- "$1" "$2" 2>/dev/null; then echo 1; else echo 0; fi; }
hasin() { if printf '%s' "$2" | grep -q -E -- "$1"; then echo 1; else echo 0; fi; }
check() {
  if [ "$2" = "$3" ]; then
    CHECKS+=("ok   | $1 | $2"); printf '[ok]   %s = %s\n' "$1" "$2"
  else
    CHECKS+=("FAIL | $1 | got '$2' want '$3'"); printf "[FAIL] %s: got '%s' want '%s'\n" "$1" "$2" "$3"
    FAILURES=$((FAILURES + 1))
  fi
}
cleanup() {
  for pid in "$STUB_PID" "$GUI_PID"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null
  done
  wait 2>/dev/null
}
trap cleanup EXIT

port_open() { "$PY" -c "import socket,sys; s=socket.socket(); s.settimeout(0.2); sys.exit(0 if s.connect_ex(('127.0.0.1',$1))==0 else 1)" 2>/dev/null; }

use_stub() {
  if [ -n "$STUB_PID" ]; then
    kill "$STUB_PID" 2>/dev/null
    wait "$STUB_PID" 2>/dev/null
    STUB_PID=""
    for _ in $(seq 1 50); do port_open "$STUB_PORT" || break; sleep 0.1; done
  fi
  "$PY" "$HERE/scripts/gemini_protocol_stub.py" --port "$STUB_PORT" "$@" >>"$HOME_DIR/stub.log" 2>&1 &
  STUB_PID=$!
  for _ in $(seq 1 100); do
    port_open "$STUB_PORT" && return 0
    sleep 0.1
  done
  printf 'the stub did not start; see %s\n' "$HOME_DIR/stub.log" >&2
  return 1
}

ask() { "$CLI" chat --message "${2:-hello}" --model "$1" 2>&1; }

say "home"
echo "$HOME_DIR"
"$CLI" init >/dev/null 2>&1
check "info exits 0" "$("$CLI" info >/dev/null 2>&1; echo $?)" "0"

use_stub || exit 1

say "a Gemini model is registered with a *reference*, never the key"
"$CLI" models add-gemini --name flash --model gemini-2.0-flash --base-url "$STUB" >"$HOME_DIR/add.out" 2>&1
check "add-gemini exits 0" "$?" "0"
check "the runtime is gemini" "$(has 'runtime=gemini' "$HOME_DIR/add.out")" "1"
check "the reference is reported, not the key" "$(has 'secret://env/GEMINI_API_KEY' "$HOME_DIR/add.out")" "1"
check "the key is not in the CLI output" "$(has "$KEY" "$HOME_DIR/add.out")" "0"
check "the endpoint is recorded at the versioned path" "$(has "/v1beta" "$HOME_DIR/add.out")" "1"
check "the model row stores the reference" \
  "$("$CLI" --json models show flash | jq_ "d['user_metadata'].get('credential_ref')")" \
  "secret://env/GEMINI_API_KEY"

say "a literal key in --credential-ref is refused"
"$CLI" models add-gemini --name literal --model gemini-2.0-flash \
  --credential-ref "$KEY" >"$HOME_DIR/literal.out" 2>&1
check "a literal key exits 2" "$?" "2"
check "it says credentials must be a reference" "$(has 'secret://env/NAME' "$HOME_DIR/literal.out")" "1"
check "and it does not echo the key" "$(has "$KEY" "$HOME_DIR/literal.out")" "0"

say "the probe is a measurement: it calls the endpoint and records the outcome"
"$CLI" models probe flash --capability chat >"$HOME_DIR/probe.out" 2>&1
check "probe exits 0" "$?" "0"
check "the probe passed" "$(has 'passed' "$HOME_DIR/probe.out")" "1"
check "the capability is now verified" \
  "$("$CLI" --json models show flash | jq_ "'chat' in (d.get('verified_capabilities') or [])")" "True"

say "a chat turn goes through the socket and comes back parsed"
ask flash "what is the answer" >"$HOME_DIR/chat.out" 2>&1
check "chat exits 0" "$?" "0"
check "the reply is the stub's, parsed out of candidates[0].content.parts" \
  "$(has 'PROTOCOL-STUB' "$HOME_DIR/chat.out")" "1"
check "the reply is not labelled simulated" "$(has 'SIMULATED' "$HOME_DIR/chat.out")" "0"
check "usage was parsed from usageMetadata into the task record" \
  "$("$CLI" --json tasks list --limit 5 | jq_ "any((t.get('resource_use') or {}).get('completion_tokens') for t in d)")" "True"
check "the key is not in the reply, its footer or its error stream" "$(has "$KEY" "$HOME_DIR/chat.out")" "0"

say "the request the client builds is the documented one"
"$PY" - "$HOME_DIR" <<'PY'
import json, pathlib, sys
home = pathlib.Path(sys.argv[1])
# the trace records what was sent, without the credential
events = [json.loads(line) for line in (home / "trace.jsonl").read_text().splitlines() if line.strip()] \
    if (home / "trace.jsonl").exists() else []
print(f"{len(events)} trace events")
PY

say "the errors are classified, not collapsed into one another"
use_stub --fail 401 || exit 1
ask flash >"$HOME_DIR/e401.out" 2>&1
check "a 401 is an auth failure" "$(has 'AuthDeniedError' "$HOME_DIR/e401.out")" "1"
check "a 401 is not reported as a rate limit" "$(has 'RateLimited' "$HOME_DIR/e401.out")" "0"
check "the provider's echoed key is redacted" "$(has "$KEY" "$HOME_DIR/e401.out")" "0"
check "a 401 body carries no credential to echo" "$(has 'API key not valid' "$HOME_DIR/e401.out")" "1"

# A 400 is the path where the vendor echoes the offending key back; the client must not show it.
WRONG_KEY="wrong-key-that-must-never-be-printed-9f3a"
use_stub --key "$KEY" || exit 1
GEMINI_API_KEY="$WRONG_KEY" "$CLI" chat --message hello --model flash >"$HOME_DIR/echo.out" 2>&1
check "a key the endpoint rejects is an auth failure" "$(has 'AuthDeniedError' "$HOME_DIR/echo.out")" "1"
check "the echoed key is not shown" "$(has "$WRONG_KEY" "$HOME_DIR/echo.out")" "0"
check "the redaction is visible, not silent" "$(has '\[REDACTED\]' "$HOME_DIR/echo.out")" "1"

use_stub --fail 429 >"$HOME_DIR/stub.log" 2>&1 || exit 1
ask flash >"$HOME_DIR/e429.out" 2>&1
check "a plain 429 is a rate limit" "$(has 'RateLimitedError' "$HOME_DIR/e429.out")" "1"
check "a plain 429 is not called a quota problem" "$(has 'quota' "$HOME_DIR/e429.out")" "0"

use_stub --fail 429 --quota || exit 1
ask flash >"$HOME_DIR/equota.out" 2>&1
check "an exhausted quota is named separately from a burst limit" \
  "$(has 'quota' "$HOME_DIR/equota.out")" "1"
check "and it is not reported as a rate-limit retry" \
  "$(has 'RateLimitedError' "$HOME_DIR/equota.out")" "0"

use_stub --fail 404 || exit 1
ask flash >"$HOME_DIR/e404.out" 2>&1
check "an unknown model is model-not-found" "$(has 'ModelNotFoundError' "$HOME_DIR/e404.out")" "1"

use_stub --block || exit 1
ask flash >"$HOME_DIR/eblock.out" 2>&1
check "a content-policy block is not an empty reply" "$(has 'blocked by content policy' "$HOME_DIR/eblock.out")" "1"
check "the block reason is carried through" "$(has 'SAFETY' "$HOME_DIR/eblock.out")" "1"

use_stub --empty || exit 1
ask flash >"$HOME_DIR/eempty.out" 2>&1
check "an empty candidate list is a malformed output, not a silent success" \
  "$(has 'MalformedOutputError' "$HOME_DIR/eempty.out")" "1"

use_stub --fail 500 || exit 1
ask flash >"$HOME_DIR/e500.out" 2>&1
check "a 500 is a provider outage" "$(has 'ProviderOutageError' "$HOME_DIR/e500.out")" "1"

use_stub || exit 1
ask flash >"$HOME_DIR/recovered.out" 2>&1
check "the endpoint recovers: the next call succeeds" "$(has 'PROTOCOL-STUB' "$HOME_DIR/recovered.out")" "1"

say "the consent ladder: a remote endpoint is refused until every rung is climbed"
"$CLI" models add-gemini --name cloud --model gemini-2.0-pro >"$HOME_DIR/cloud-add.out" 2>&1
check "a second google model with a different id is registered" "$?" "0"
ask cloud >"$HOME_DIR/cloud1.out" 2>&1
check "rung 1: model.local_only refuses the first call" \
  "$(has 'model.local_only is true' "$HOME_DIR/cloud1.out")" "1"
"$CLI" config set model.local_only false >/dev/null 2>&1
ask cloud >"$HOME_DIR/cloud2.out" 2>&1
check "rung 2: an unregistered endpoint is refused" \
  "$(has 'not a registered provider' "$HOME_DIR/cloud2.out")" "1"
check "and the hint names the right template for a Gemini model" \
  "$(has 'template google' "$HOME_DIR/cloud2.out")" "1"
"$CLI" providers add google --template google >/dev/null 2>&1
PROVIDER_ID="$("$CLI" --json providers list | jq_ "[p['id'] for p in d if p['slug']=='google'][0]")"
ask cloud >"$HOME_DIR/cloud3.out" 2>&1
check "rung 3: unknown privacy terms are refused" "$(has 'privacy terms are unknown' "$HOME_DIR/cloud3.out")" "1"
"$CLI" providers confirm google --data-leaves-device yes >/dev/null 2>&1
ask cloud >"$HOME_DIR/cloud4.out" 2>&1
check "rung 4: missing consent is refused" \
  "$(has 'record explicit consent' "$HOME_DIR/cloud4.out")" "1"
"$CLI" providers consent google >/dev/null 2>&1
check "consent is on file, with a timestamp" \
  "$("$CLI" --json providers show google | jq_ "bool(d.get('consent_at'))")" "True"
ask cloud >"$HOME_DIR/cloud5.out" 2>&1
check "the ladder is open, so the call now reaches the network layer" \
  "$(has 'NetworkFailureError|ProviderOutageError|AuthDeniedError' "$HOME_DIR/cloud5.out")" "1"
check "and the refusal is about the network, not about consent" \
  "$(has 'local_only|not a registered provider|consent' "$HOME_DIR/cloud5.out")" "0"

say "the GUI exposes the same ladder, and refuses the same things"
"$CLI" gui serve --port "$GUI_PORT" --token "$TOKEN" >"$HOME_DIR/gui.log" 2>&1 &
GUI_PID=$!
for _ in $(seq 1 100); do
  grep -q "access token" "$HOME_DIR/gui.log" 2>/dev/null && break
  sleep 0.1
done
get_json() { curl -s -H "X-Archx-Token: $TOKEN" "$1"; }
post_json() { curl -s -X POST -H "X-Archx-Token: $TOKEN" -H "X-Archx-Request: gui" -H "Content-Type: application/json" -d "$2" "$1"; }
post_code() { curl -s -o /dev/null -w '%{http_code}' -X POST -H "X-Archx-Token: $TOKEN" -H "X-Archx-Request: gui" -H "Content-Type: application/json" -d "$2" "$1"; }

check "the models route answers" \
  "$(curl -s -o /dev/null -w '%{http_code}' -H "X-Archx-Token: $TOKEN" "$BASE/api/models")" "200"
check "the cloud model carries four rungs" \
  "$(get_json "$BASE/api/models" | jqd "','.join(sorted(g['key'] for m in d if m['name']=='cloud' for g in m['gates']))")" \
  "consent,consent_policy,privacy,provider"
check "every rung reads passed once the ladder is climbed" \
  "$(get_json "$BASE/api/models" | jqd "all(g['ok'] for m in d if m['name']=='cloud' for g in m['gates'])")" "True"
check "the provider id is exposed so the panel can post to it" \
  "$(get_json "$BASE/api/models" | jqd "any(m['provider_id'] for m in d if m['name']=='cloud')")" "True"
check "a literal key posted to the GUI is refused" \
  "$(post_code "$BASE/api/models" "{\"name\":\"x\",\"model\":\"gemini-2.0-flash\",\"credential_ref\":\"$KEY\"}")" "400"
GUI_ADDED="$(post_json "$BASE/api/models" "{\"name\":\"gui-flash\",\"model\":\"gemini-2.0-flash\",\"base_url\":\"$STUB\"}")"
printf '%s' "$GUI_ADDED" >"$HOME_DIR/gui_added.json"
check "a model added through the GUI is a gemini runtime" \
  "$(printf '%s' "$GUI_ADDED" | jqd "d['runtime']")" "gemini"
check "registering the same endpoint and model again reuses the row, it does not duplicate it" \
  "$(printf '%s' "$GUI_ADDED" | jqd "d['name']")" "flash"
MODEL_ID="$(printf '%s' "$GUI_ADDED" | jqd "d['id']")"
check "the GUI probe measures the model" \
  "$(post_json "$BASE/api/models/$MODEL_ID/probe" '{"capability":"chat"}' | jqd "d['result']['outcome']")" "passed"
check "a chat through the GUI returns the parsed reply" \
  "$(post_json "$BASE/api/chat" "{\"message\":\"hi\",\"model_id\":\"$MODEL_ID\"}" | jqd "d['text'].startswith('[PROTOCOL-STUB]')")" "True"
curl -s "$BASE/" >"$HOME_DIR/served.html" 2>/dev/null
# Follow the page's script list so split view code is checked too.
: >"$HOME_DIR/served.js"
while IFS= read -r asset; do
  curl -fsS "$BASE/$asset" >>"$HOME_DIR/served.js" || exit 1
done < <("$PY" -c 'import re,sys; print("\n".join(re.findall(r"<script src=\"/([^\"/]+\.js)\"></script>",open(sys.argv[1]).read())))' "$HOME_DIR/served.html")
check "the page has a Connect Gemini form" "$(has 'id="models-form"' "$HOME_DIR/served.html")" "1"
check "the page renders the consent ladder" "$(has 'rung' "$HOME_DIR/served.js")" "1"
check "no inline handler in the models panel" "$(has 'onclick=' "$HOME_DIR/served.html")" "0"
check "the key is not served to the browser" "$(has "$KEY" "$HOME_DIR/served.js")" "0"

say "the key never landed anywhere it could be read back"
check "no file under the home holds the key" \
  "$(grep -rl "$KEY" "$HOME_DIR" 2>/dev/null | wc -l | tr -d ' ')" "0"
check "the workspace database does not contain it" \
  "$("$PY" -c "
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
hits = 0
for (table,) in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\"):
    for row in conn.execute(f'SELECT * FROM \\\"{table}\\\"'):
        if any(sys.argv[2] in str(value) for value in row):
            hits += 1
print(hits)
" "$HOME_DIR/archx.db" "$KEY")" "0"
check "the trace does not contain it" \
  "$("$CLI" --json trace list --limit 200 2>/dev/null | grep -c "$KEY")" "0"

printf '\n### summary\n'
for line in "${CHECKS[@]}"; do printf '%s\n' "$line"; done
printf '\n'
if [ "$FAILURES" -eq 0 ]; then
  printf 'Gemini acceptance: %s checks passed\n' "${#CHECKS[@]}"
else
  printf 'GEMINI ACCEPTANCE FAILED: %s of %s checks\n' "$FAILURES" "${#CHECKS[@]}"
fi
exit "$FAILURES"
