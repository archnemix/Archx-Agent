#!/usr/bin/env bash
# M26 acceptance: the durable job scheduler in the installed app.
#
# Everything here runs through the real console script against a real SQLite database:
# real child processes, a real SIGKILL of a worker, real pause/resume across two
# processes, and a real hard deadline that has to kill a running child.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$HERE/.venv/bin/archx-agent"
PY="$HERE/.venv/bin/python"
HOME_DIR="${1:-$(mktemp -d /tmp/archx-m26-XXXXXX)}"
export ARCHX_PATHS_HOME="$HOME_DIR"
export ARCHX_ALLOW_SIMULATED=1
WORK="$HOME_DIR/workspace"
FAILURES=0
CHECKS=()

say() { printf '\n### %s\n' "$*"; }
run() { printf '$ archx-agent %s\n' "$*"; "$CLI" "$@"; printf '[exit %s]\n' "$?"; }
jq_() { "$PY" -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
check() { # check <label> <actual> <expected>
  if [ "$2" = "$3" ]; then
    CHECKS+=("ok   | $1 | $2"); printf '[ok]   %s = %s\n' "$1" "$2"
  else
    CHECKS+=("FAIL | $1 | got '$2' want '$3'"); printf "[FAIL] %s: got '%s' want '%s'\n" "$1" "$2" "$3"
    FAILURES=$((FAILURES + 1))
  fi
}
cleanup() {
  [ -n "${RUNNER_PID:-}" ] && kill -9 "$RUNNER_PID" 2>/dev/null
  pkill -f "archx-m26-accept-child" 2>/dev/null
  return 0
}
trap cleanup EXIT

say "home"; echo "$HOME_DIR"
run init
mkdir -p "$WORK"

say "a submitted job is queued, not done - and it names its deadline and attempts"
run jobs submit command "echo hello from a job" --title greet --timeout 30
GREET=$("$CLI" jobs list --json | jq_ "d[0]['id']")
run jobs list
run jobs queue
run jobs show "$GREET"

say "running the queue executes it and records a task with a timeline"
run jobs run
run jobs logs "$GREET"
run jobs show "$GREET"
check "greet status" "$("$CLI" jobs show "$GREET" --json | jq_ "d['status']")" "completed"
check "greet exit code" "$("$CLI" jobs show "$GREET" --json | jq_ "d['result']['exit_code']")" "0"
check "greet produced a task" "$("$CLI" jobs show "$GREET" --json | jq_ "bool(d['task_id'])")" "True"

say "a duplicate submit with the same key is the same job, not twice the work"
run jobs submit command "echo low" --priority 1 --title low --dedupe-key once
run jobs submit command "echo high" --priority 9 --title high
HIGH=$("$CLI" jobs list --status queued --json | jq_ "[j['id'] for j in d if j['title']=='high'][0]")
LOW=$("$CLI" jobs list --status queued --json | jq_ "[j['id'] for j in d if j['title']=='low'][0]")
run jobs submit command "echo high" --priority 9 --title high --dedupe-key once-high
run jobs submit command "echo high" --priority 9 --title high --dedupe-key once-high
check "four submits became four jobs" "$("$CLI" jobs stats --json | jq_ "d['total']")" "4"
say "the high-priority job runs first"
run jobs queue
run jobs run --once
check "the high-priority job ran first" "$("$CLI" jobs show "$HIGH" --json | jq_ "d['status']")" "completed"
check "the low-priority job waited" "$("$CLI" jobs show "$LOW" --json | jq_ "d['status']")" "queued"
run jobs run

say "concurrency: four one-second commands at concurrency 4 finish in about a second"
for i in 1 2 3 4; do "$CLI" jobs submit command "sleep 1" --title "parallel-$i" >/dev/null; done
START=$(date +%s%N)
run jobs run --concurrency 4
END=$(date +%s%N)
ELAPSED_MS=$(( (END - START) / 1000000 ))
echo "wall clock: ${ELAPSED_MS}ms (serial would be >= 4000ms)"
check "parallel wall clock under 2600ms" "$([ "$ELAPSED_MS" -lt 2600 ] && echo yes || echo no)" "yes"

say "a hard deadline kills the child process instead of waiting for it"
run jobs submit command "sleep 30" --title timeout --timeout 1
SLOW=$("$CLI" jobs list --status queued --json | jq_ "d[0]['id']")
START=$(date +%s%N)
run jobs run
END=$(date +%s%N)
TIMEOUT_MS=$(( (END - START) / 1000000 ))
echo "timed out in ${TIMEOUT_MS}ms"
check "timeout job failed" "$("$CLI" jobs show "$SLOW" --json | jq_ "d['status']")" "failed"
check "no child left behind" "$(pgrep -fc 'sleep 30' || true)" "0"
check "timeout respected the deadline" "$([ "$TIMEOUT_MS" -lt 8000 ] && echo yes || echo no)" "yes"
run jobs logs "$SLOW"

say "a workflow job: pause at a step boundary, then resume where it stopped"
run permissions grant shell.run --subject shell.run --duration persistent --confirm
cat > "$HOME_DIR/make-flow.py" <<'PYEOF_FLOW'
import sys
from archx_agent.application.workspace import Workspace
ws = Workspace.open(home=sys.argv[1], env={})
wf = ws.workflows.create({
    "name": "paused-workflow",
    "goal": "prove pause and resume",
    "steps": [
        {"kind": "note", "title": "before", "text": "starting"},
        {"kind": "tool", "title": "slow step", "tool": "shell.run",
         "args": {"command": "sleep 1"}},
        {"kind": "note", "title": "after", "text": "finishing"},
    ],
})
print(wf.id)
ws.close()
PYEOF_FLOW
FLOW=$("$PY" "$HOME_DIR/make-flow.py" "$HOME_DIR" | tail -1)
echo "workflow $FLOW stored approved and not yet run"
run jobs submit workflow "$FLOW" --title "paused workflow" --timeout 120
PAUSED_JOB=$("$CLI" jobs list --status queued --json | jq_ "d[0]['id']")
PATH="$HERE/.venv/bin:$PATH" "$CLI" jobs run >"$HOME_DIR/runner.log" 2>&1 &
RUNNER_PID=$!
for _ in $(seq 1 200); do
  STATUS=$("$CLI" jobs show "$PAUSED_JOB" --json | jq_ "d['status']")
  CURSOR=$("$CLI" jobs show "$PAUSED_JOB" --json | jq_ "d.get('cursor') or 0")
  if [ "$STATUS" = "running" ] && [ "$CURSOR" -ge 1 ]; then break; fi
  sleep 0.05
done
run jobs pause "$PAUSED_JOB"
for _ in $(seq 1 200); do
  STATUS=$("$CLI" jobs show "$PAUSED_JOB" --json | jq_ "d['status']")
  [ "$STATUS" = "paused" ] && break
  sleep 0.05
done
kill "$RUNNER_PID" 2>/dev/null; wait "$RUNNER_PID" 2>/dev/null; RUNNER_PID=""
run jobs show "$PAUSED_JOB"
check "paused mid-run" "$("$CLI" jobs show "$PAUSED_JOB" --json | jq_ "d['status']")" "paused"
check "paused after some steps" "$("$CLI" jobs show "$PAUSED_JOB" --json | jq_ "[d['cursor'] > 0][0]")" "True"
check "the workflow was left running" "$("$CLI" jobs show "$PAUSED_JOB" --json | jq_ "d['workflow']['status']")" "running"
run jobs resume "$PAUSED_JOB"
run jobs run
check "resumed job completed" "$("$CLI" jobs show "$PAUSED_JOB" --json | jq_ "d['status']")" "completed"
check "resumed workflow completed" "$("$CLI" jobs show "$PAUSED_JOB" --json | jq_ "d['workflow']['status']")" "completed"
run jobs show "$PAUSED_JOB"
FLOW_ID=$("$CLI" jobs show "$PAUSED_JOB" --json | jq_ "d['workflow']['id']")
check "every step ran exactly once" "$("$CLI" agent steps "$FLOW_ID" --json | jq_ "len(d)")" "3"
check "all steps succeeded" "$("$CLI" agent steps "$FLOW_ID" --json | jq_ "all(s['status']=='succeeded' for s in d)")" "True"

say "a worker that is SIGKILLed leaves a row, not a lie: recover requeues it"
run jobs submit command "sh -c 'sleep 4; echo survived the restart'" --title crash-me --max-attempts 2 --timeout 60
CRASH=$("$CLI" jobs list --status queued --json | jq_ "d[0]['id']")
PATH="$HERE/.venv/bin:$PATH" "$CLI" jobs run >"$HOME_DIR/crash.log" 2>&1 &
RUNNER_PID=$!
for _ in $(seq 1 200); do
  [ "$("$CLI" jobs show "$CRASH" --json | jq_ "d['status']")" = "running" ] && break
  sleep 0.05
done
kill -9 "$RUNNER_PID" 2>/dev/null; wait "$RUNNER_PID" 2>/dev/null; RUNNER_PID=""
echo "(worker killed; the job row still says running, owned by a dead pid)"
run jobs show "$CRASH"
run jobs recover
run jobs show "$CRASH"
check "recovered job is queued" "$("$CLI" jobs show "$CRASH" --json | jq_ "d['status']")" "queued"
run jobs run
check "recovered job completed" "$("$CLI" jobs show "$CRASH" --json | jq_ "d['status']")" "completed"
check "it took a second attempt" "$("$CLI" jobs show "$CRASH" --json | jq_ "d['attempts']")" "2"
run jobs logs "$CRASH"

say "a refused capability stops a workflow job, and no file is written"
cat > "$HOME_DIR/write-flow.json" <<'JSON'
{
  "name": "write-without-grant",
  "goal": "should be refused",
  "steps": [
    {"kind": "tool", "title": "write", "tool": "fs.write",
     "args": {"path": "blocked.txt", "content": "nope"}}
  ]
}
JSON
"$CLI" agent run-file "$HOME_DIR/write-flow.json" >/dev/null 2>&1
DENIED_FLOW=$("$CLI" agent list --json | jq_ "[w['id'] for w in d if w['name']=='write-without-grant'][0]")
run jobs submit workflow "$DENIED_FLOW" --title "denied workflow" --timeout 60
DENIED_JOB=$("$CLI" jobs list --status queued --json | jq_ "d[0]['id']")
run jobs run
run jobs logs "$DENIED_JOB"
check "denied workflow job failed" "$("$CLI" jobs show "$DENIED_JOB" --json | jq_ "d['status']")" "failed"
check "no file was written" "$([ -f "$WORK/blocked.txt" ] && echo yes || echo no)" "no"
check "the run still needed a grant" "$("$CLI" permissions list --json | jq_ "sum(1 for g in d if g['capability']=='fs.write')")" "0"

say "queue statistics, traces and a consistent database"
run jobs stats
run jobs list --limit 5
run trace list --kind task --limit 8
run db check

say "summary"
printf '%s\n' "${CHECKS[@]}"
if [ "$FAILURES" -gt 0 ]; then
  printf '\nM26 ACCEPTANCE FAILED: %s check(s)\n' "$FAILURES"
  exit 1
fi
printf '\nM26 acceptance: %s checks passed\n' "${#CHECKS[@]}"
