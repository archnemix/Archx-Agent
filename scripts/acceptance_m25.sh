#!/usr/bin/env bash
# M25 acceptance: agent workflows - user-directed and model-proposed - in the installed app.
#
# The model here is a *protocol* stub: a real HTTP server answering the OpenAI chat
# completions API. The plan is therefore parsed from a real response over a real socket,
# and the plan is refused until a human approves it.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$HERE/.venv/bin/archx-agent"
PY="$HERE/.venv/bin/python"
HOME_DIR="${1:-$(mktemp -d /tmp/archx-m25-XXXXXX)}"
export ARCHX_PATHS_HOME="$HOME_DIR"
export ARCHX_ALLOW_SIMULATED=1
WORK="$HOME_DIR/workspace"
PORT="${2:-$(( 20000 + RANDOM % 20000 ))}"

say() { printf '\n### %s\n' "$*"; }
run() { printf '$ archx-agent %s\n' "$*"; "$CLI" "$@"; printf '[exit %s]\n' "$?"; }
jq_() { "$PY" -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
cleanup() { [ -n "${STUB_PID:-}" ] && kill "$STUB_PID" 2>/dev/null; }
trap cleanup EXIT

say "home"; echo "$HOME_DIR"
run init
mkdir -p "$WORK"
printf 'alpha\nbeta\ngamma\n' > "$WORK/notes.txt"

say "a user-written workflow: read a file, ask a model, keep provenance"
run models add-scripted --name sim
run permissions grant fs.read --subject fs.read --duration persistent --confirm
cat > "$HOME_DIR/summarise.json" <<'JSON'
{
  "name": "summarise-notes",
  "goal": "summarise notes.txt",
  "steps": [
    {"kind": "tool", "title": "read notes", "tool": "fs.read", "args": {"path": "notes.txt"}},
    {"kind": "model", "title": "summarise", "prompt": "Summarise these notes: {{step.1.output}}"},
    {"kind": "note", "title": "provenance", "text": "source: notes.txt"},
    {"kind": "memory", "title": "recall", "query": "notes"}
  ]
}
JSON
run agent run-file "$HOME_DIR/summarise.json"
WF=$("$CLI" agent list --json | jq_ "d[0]['id']")
run agent show "$WF"
run agent steps "$WF"

say "every step is a record, and the whole run is a task with a conversation"
TASK=$("$CLI" agent show "$WF" --json | jq_ "d['task_id']")
run tasks show "$TASK"
run conv list

say "a subagent is a child task with its own conversation - and it cannot exceed the budgets"
cat > "$HOME_DIR/delegate.json" <<'JSON'
{
  "name": "delegate",
  "goal": "check the notes with a helper",
  "steps": [
    {"kind": "subagent", "title": "reviewer", "goal": "review notes.txt",
     "steps": [
       {"kind": "tool", "tool": "fs.read", "args": {"path": "notes.txt"}},
       {"kind": "model", "prompt": "Review this: {{step.1.output}}"}
     ]}
  ]
}
JSON
run agent run-file "$HOME_DIR/delegate.json"
DELEGATED=$("$CLI" agent list --json | jq_ "d[0]['id']")
run agent show "$DELEGATED"

say "a tool without a grant stops the run at that step - and the plan is not the permission"
cat > "$HOME_DIR/write.json" <<'JSON'
{
  "name": "write-without-grant",
  "goal": "try to write a file",
  "steps": [
    {"kind": "tool", "title": "write", "tool": "fs.write",
     "args": {"path": "blocked.txt", "content": "should not exist"}}
  ]
}
JSON
run agent run-file "$HOME_DIR/write.json"
ls "$WORK" | tr '\n' ' '; echo

say "an AI-directed plan: a real HTTP model proposes JSON, which is stored UNAPPROVED"
cat > "$HOME_DIR/plan.json" <<'JSON'
{
  "name": "inspect-workspace",
  "goal": "inspect the workspace and report",
  "steps": [
    {"kind": "tool", "title": "facts", "tool": "archx.info", "args": {}},
    {"kind": "checkpoint", "title": "review", "text": "look at the facts before reporting"},
    {"kind": "model", "title": "report", "prompt": "Write a short report from: {{step.1.output}}"}
  ]
}
JSON
"$PY" "$HERE/scripts/openai_protocol_stub.py" --port "$PORT" --reply-file "$HOME_DIR/plan.json" >/dev/null 2>&1 &
STUB_PID=$!
"$PY" - "$PORT" <<'PY'
import sys, time, urllib.request
port = sys.argv[1]
for _ in range(100):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=1)
        print("stub ready")
        break
    except Exception:
        time.sleep(0.1)
PY
run models add-http --name planner --base-url "http://127.0.0.1:$PORT/v1" --provider local-http --model protocol-stub
echo "(the stub returns the same canned text for every request, so the final model step echoes it)"
run agent plan "inspect the workspace and report"
PROPOSED=$("$CLI" agent list --status proposed --json | jq_ "d[0]['id']")
run agent show "$PROPOSED"

say "the proposal cannot run until a human approves it (exit 4, nothing executed)"
run agent run "$PROPOSED"
run agent run "$PROPOSED" --approve
PLANNED_TASK=$("$CLI" agent show "$PROPOSED" --json | jq_ "d['task_id'] or ''")
run tasks list --type agent | head -5

say "a plan that names a tool this machine does not have is refused before it is stored"
cat > "$HOME_DIR/bad-plan.json" <<'JSON'
{"name": "bad", "goal": "delete everything", "steps": [
  {"kind": "tool", "title": "oops", "tool": "shell.rm_rf", "args": {}}
]}
JSON
kill "$STUB_PID" 2>/dev/null; wait "$STUB_PID" 2>/dev/null
"$PY" "$HERE/scripts/openai_protocol_stub.py" --port "$PORT" --reply-file "$HOME_DIR/bad-plan.json" >/dev/null 2>&1 &
STUB_PID=$!
"$PY" - "$PORT" <<'PY'
import sys, time, urllib.request
for _ in range(100):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/v1/models", timeout=1); break
    except Exception:
        time.sleep(0.1)
PY
run agent plan "delete everything"
run agent list

say "templates are user-directed workflows with inputs"
run agent templates
run agent run-template summarise-file --input path=notes.txt

say "the user grants the capability the refused step needed; a re-run is an explicit new record"
run permissions grant fs.write --subject fs.write --duration persistent --confirm
FAILED=$("$CLI" agent list --status failed --json | jq_ "[w['id'] for w in d if w['name']=='write-without-grant'][0]")
run agent rerun "$FAILED" --approve
ls "$WORK" | tr '\n' ' '; echo

say "stats, traces and a consistent database"
run agent stats
run tasks stats
run trace list --kind agent_run --limit 6
run db check
