#!/usr/bin/env bash
# M20 acceptance: provider catalogue, privacy metadata, consent, availability, usage.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$HERE/.venv/bin/archx-agent"
PY="$HERE/.venv/bin/python"
HOME_DIR="${1:-$(mktemp -d /tmp/archx-m20-XXXXXX)}"
export ARCHX_PATHS_HOME="$HOME_DIR"
PORT="${2:-8131}"

say() { printf '\n### %s\n' "$*"; }
run() { printf '$ archx-agent %s\n' "$*"; "$CLI" "$@"; printf '[exit %s]\n' "$?"; }

say "home"; echo "$HOME_DIR"; run init

say "start a real local OpenAI-compatible server (a protocol stub, not a model)"
"$PY" "$HERE/scripts/openai_protocol_stub.py" --port "$PORT" >/tmp/archx-stub.log 2>&1 &
STUB_PID=$!
trap 'kill $STUB_PID 2>/dev/null' EXIT
for _ in $(seq 1 50); do
  if "$PY" - "$PORT" <<'EOF'
import sys, urllib.request
try:
    urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/v1/models", timeout=1)
except Exception:
    sys.exit(1)
EOF
  then break; fi
  sleep 0.1
done
echo "stub pid $STUB_PID"

say "register it as a LOCAL provider - no consent needed, because the URL is loopback"
run providers add local-llama --template openai-compatible-local --base-url "http://127.0.0.1:$PORT/v1"
run providers privacy
run providers check local-llama
run models add-http --name stub-model --base-url "http://127.0.0.1:$PORT/v1" --model protocol-stub

say "chat through the real HTTP path (reply is labelled by the stub itself)"
run chat -m "how do providers work" --json

say "usage is attributed to the provider"
run providers usage local-llama
run providers usage local-llama --by-day --json

say "a cloud provider starts blocked: unknown privacy, no consent"
run providers add cloud-demo --template openai --auth-ref secret://env/ARCHX_DEMO_KEY
run providers consent cloud-demo
run providers confirm cloud-demo --data-leaves-device yes --retention "vendor: up to 30 days"
run providers privacy

say "consent, then the cloud provider becomes usable"
run providers consent cloud-demo --note "user accepted remote processing for testing"
run providers privacy

say "quota is declared and enforced by Archx"
run providers quota cloud-demo --requests-per-day 2
"$CLI" --home "$HOME_DIR" providers quota cloud-demo --json

say "a remote model is still refused unless local-only mode is turned off"
run models add-http --name remote-model --base-url https://api.openai.com/v1 --model gpt-x
printf '$ archx-agent chat --model <remote-model> -m hello\n'
MODEL_ID=$("$CLI" models list --json | "$PY" -c 'import json,sys;print([m["id"] for m in json.load(sys.stdin) if m["name"]=="remote-model"][0])')
printf '$ archx-agent chat --model %s -m hello\n' "$MODEL_ID"
"$CLI" --home "$HOME_DIR" chat --model "$MODEL_ID" -m "hello"; echo "[exit $?]"

say "privacy report shows the whole picture"
run providers privacy
run providers stats
run trace list --limit 10
run db check
