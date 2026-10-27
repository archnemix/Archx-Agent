#!/usr/bin/env bash
# M24 acceptance: task history, content versions and reproduction records - driven
# entirely through the installed console script.
#
# The crash is real: a second Python process creates a running task and is killed with
# SIGKILL, and the next command reports that task as interrupted. The reproduction
# commands printed by the app are re-run here, so they are verified as commands rather
# than as prose.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$HERE/.venv/bin/archx-agent"
PY="$HERE/.venv/bin/python"
HOME_DIR="${1:-$(mktemp -d /tmp/archx-m24-XXXXXX)}"
export ARCHX_PATHS_HOME="$HOME_DIR"
export ARCHX_ALLOW_SIMULATED=1
WORK="$HOME_DIR/workspace"

say() { printf '\n### %s\n' "$*"; }
run() { printf '$ archx-agent %s\n' "$*"; "$CLI" "$@"; printf '[exit %s]\n' "$?"; }
jq_() { "$PY" -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

say "home"; echo "$HOME_DIR"
run init

say "a chat turn is a task: it is created before the model is called and closed after the reply is stored"
run models add-scripted --name sim
run chat --message "summarise the plan in one line"
run tasks list
CHAT_TASK=$("$CLI" tasks list --type chat --json | jq_ "d[0]['id']")
run tasks show "$CHAT_TASK"

say "task history is a sequence: every step has its own number, even in the same millisecond"
run tasks start --type tool --title "write and read a report"
TOOL_TASK=$("$CLI" tasks list --type tool --json | jq_ "d[0]['id']")
run permissions grant fs.write --subject fs.write --duration persistent --confirm
run permissions grant fs.read --subject fs.read --duration persistent --confirm
run tasks log "$TOOL_TASK" --kind step --detail "about to write the report"
run tools run fs.write --arg path=report.txt --arg content="alpha
beta
" --task "$TOOL_TASK"
run tools run fs.read --arg path=report.txt --task "$TOOL_TASK"

say "the artifact is a reference with a checksum, and attaching it records content version v1"
run tasks attach "$TOOL_TASK" "$WORK/report.txt" --kind report
run tasks show "$TOOL_TASK"

say "changing the file and attaching it again is v2 - history is appended, never overwritten"
run tools run fs.write --arg path=report.txt --arg content="alpha
beta
gamma
"
run tasks attach "$TOOL_TASK" "$WORK/report.txt" --kind report
run versions list artifact "$WORK/report.txt"
run versions diff artifact "$WORK/report.txt"

say "restoring v1 writes v3 (the two later states stay in the history)"
run versions restore artifact "$WORK/report.txt" v1
run versions list artifact "$WORK/report.txt"
run versions show artifact "$WORK/report.txt" v3
run tasks complete "$TOOL_TASK" --summary "report written, read, versioned and restored"

say "reproduction: a deterministic tool task is exact, and the printed command really runs"
run tasks start --type tool --title "ask the app about itself"
SELF_TASK=$("$CLI" tasks list --type tool --json | jq_ "d[0]['id']")
run tools run archx.info --task "$SELF_TASK"
run tasks complete "$SELF_TASK" --summary "read the workspace facts"
run tasks reproduce "$SELF_TASK" --record
REPRO=$("$CLI" tasks show "$SELF_TASK" --json | jq_ "d['reproductions'][0]['id']")
say "re-running the command the record printed (verified, not assumed)"
printf '$ %s tools run archx.info\n' "$CLI"
"$CLI" tools run archx.info | head -4
printf '[exit %s]\n' "$?"
run tasks reproduce "$SELF_TASK" --verify "$REPRO"

say "a simulated model can never be reproduced exactly, and the record says why"
run tasks reproduce "$CHAT_TASK" --record
CHAT_REPRO=$("$CLI" tasks show "$CHAT_TASK" --json | jq_ "d['reproductions'][0]['id']")
run tasks reproduce "$CHAT_TASK" --verify "$CHAT_REPRO"

say "removing the model makes the same task impossible - and verify notices (exit 3)"
run models remove "$("$CLI" models list --json | jq_ "d[0]['id']")"
run tasks reproduce "$CHAT_TASK" --verify "$CHAT_REPRO"

say "a real crash: a separate process starts a task and is killed with SIGKILL"
"$PY" - "$HOME_DIR" <<'PY'
import os, signal, sys
from archx_agent.application.workspace import Workspace
ws = Workspace.open(home=sys.argv[1], env={})
task = ws.tasks.create("agent", "crashed while working", start=True)
print("started", task.id)
os.kill(os.getpid(), signal.SIGKILL)
PY
echo "[the python process was killed with SIGKILL]"
run tasks list --status interrupted
CRASHED=$("$CLI" tasks list --status interrupted --json | jq_ "d[0]['id']")
run tasks show "$CRASHED"
run tasks reproduce "$CRASHED"

say "tasks can carry the questions they left open"
run tasks question "$CRASHED" --text "was the index rebuilt before the crash?"
run tasks show "$CRASHED" | tail -8
run tasks resolve "$CRASHED" 0

say "history, versions and traces are queryable, and the database is consistent"
run tasks stats
run trace list --kind task --limit 6
run versions subjects
run db check
run db stats | head -6
