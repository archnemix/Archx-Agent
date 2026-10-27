#!/usr/bin/env bash
# M21 acceptance: capability-safe routing, probes, refusal and fallback - in the real app.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$HERE/.venv/bin/archx-agent"
PY="$HERE/.venv/bin/python"
HOME_DIR="${1:-$(mktemp -d /tmp/archx-m21-XXXXXX)}"
export ARCHX_PATHS_HOME="$HOME_DIR"
PORT="${2:-8141}"

say() { printf '\n### %s\n' "$*"; }
run() { printf '$ archx-agent %s\n' "$*"; "$CLI" "$@"; printf '[exit %s]\n' "$?"; }

say "home"; echo "$HOME_DIR"; run init

say "a local GGUF-shaped file: chat is INFERRED (adapter), not verified"
mkdir -p "$HOME_DIR/models"
printf 'GGUF' > "$HOME_DIR/models/tiny-model-q4_k_m.gguf"
head -c 4096 /dev/zero >> "$HOME_DIR/models/tiny-model-q4_k_m.gguf"
run models discover
run models capabilities

say "the router refuses to pretend it can run the file: llama.cpp is not installed here"
run models route
run chat -m "hello"

say "register the labelled test double and look at the decision"
run models add-scripted --name sim --json
"$CLI" --home "$HOME_DIR" --allow-simulated models route --json

say "capability states are evidence, not labels"
run --allow-simulated models probe sim --capability chat
run models capabilities sim
say "probing something the runtime cannot do is refused rather than faked"
run --allow-simulated models probe sim --capability vision

say "require_verified flips the decision for a model that has only been inferred"
run models remove sim
run models add-scripted --name fresh-sim
run config set router.require_verified true
run --allow-simulated models route
run --allow-simulated models probe fresh-sim --capability chat
run --allow-simulated models route
run config set router.require_verified false

say "a required capability nobody has is reported per candidate"
run models route --require ocr

say "a small context window is excluded when the task needs more"
run models route --min-context 32000

say "remote models are never chosen by the router on its own"
run models add-http --name remote --base-url https://api.openai.com/v1 --model gpt-x
run models route
run models route --allow-cloud
say "and naming it explicitly still hits the local-only policy"
MODEL_ID=$("$CLI" models list --json | "$PY" -c 'import json,sys;print([m["id"] for m in json.load(sys.stdin) if m["name"]=="remote"][0])')
printf '$ archx-agent chat --model %s -m hello\n' "$MODEL_ID"
"$CLI" --home "$HOME_DIR" chat --model "$MODEL_ID" -m "hello"; echo "[exit $?]"

say "fallback: a dead endpoint with a retryable failure falls back, visibly"
"$PY" - <<'PY'
import sys
sys.path.insert(0, "src")
from archx_agent.application.workspace import open_workspace
ws = open_workspace(home=__import__("os").environ["ARCHX_PATHS_HOME"], env={"ARCHX_ALLOW_SIMULATED": "1"})
dead = ws.models.register_remote("dead", provider="local-http", runtime="openai-http",
                                 model_ref="dead-1", base_url="http://127.0.0.1:9/v1",
                                 capabilities=["chat"])
ws.models.set_preferred_for(dead.id, ["chat"])
reply = ws.chat.send("prove the fallback works")
print("answered by      :", reply.model["name"])
print("fallback_from    :", reply.model.get("fallback_from"))
print("routing chosen   :", reply.model["routing"]["chosen_name"])
print("routing fallbacks:", [m for m in reply.model["routing"]["fallbacks"]])
for warning in reply.warnings:
    print("warning          :", warning)
ws.events.flush()
print("model_call events:", [e.name for e in ws.events.query(kind="model_call")])
ws.close()
PY

say "trace and database health"
run trace list --limit 12
run db check
