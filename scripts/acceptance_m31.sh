#!/usr/bin/env bash
# M31 acceptance: the coding workspace, driven the way a person would use it.
#
# The claims being checked are the ones that would be easy to fake:
#   * a session is a real record: a directory, a task, and rows the CLI, the page and sqlite
#     all agree on;
#   * nothing happens without a grant: a write with no grant leaves the file untouched, says
#     which approval it needs, and only then does the write land;
#   * the runner records every command - including the ones it refused - with the argv that
#     ran, the exit code and the duration;
#   * an edit is a diff you can read afterwards, attached to the task as an artifact;
#   * a check is the project's own declaration, run and recorded under its name;
#   * a session is reproducible: `tasks reproduce` prints the commands, and `code rerun`
#     replays one.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The repo's own venv when there is one (local runs); the interpreter that has archx-agent
# installed otherwise (the CI runner installs it into the system python).
CLI="${ARCHX_CLI:-$HERE/.venv/bin/archx-agent}"
[ -x "$CLI" ] || CLI="$(command -v archx-agent)"
PY="${ARCHX_PY:-$HERE/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python)"
WORK="${1:-$(mktemp -d /tmp/archx-m31-XXXXXX)}"
HOME_DIR="$WORK/home"
PROJECT="$WORK/project"
export ARCHX_PATHS_HOME="$HOME_DIR"
export ARCHX_TOOLS_ROOTS="$PROJECT"
export ARCHX_ALLOW_SIMULATED=1
mkdir -p "$HOME_DIR" "$PROJECT"
PORT="$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
TOKEN="m31-acceptance-token"
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
post_code() { curl -s -o /dev/null -w '%{http_code}' -X POST -H "X-Archx-Token: $TOKEN" -H "Content-Type: application/json" -d "$2" "$1"; }

dbq() { "$PY" "$WORK/dbq.py" "$HOME_DIR/archx.db" "$1"; }

cleanup() {
  [ -n "$GUI_PID" ] && kill "$GUI_PID" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT

cat > "$WORK/dbq.py" <<'PYEOF'
import sqlite3, sys

connection = sqlite3.connect(sys.argv[1])
print(connection.execute(sys.argv[2]).fetchone()[0])
PYEOF

printf 'M31 acceptance on %s\n' "$WORK"
"$CLI" init >/dev/null 2>&1

printf 'def greet(name):\n    return "hi " + name\n' > "$PROJECT/hello.py"
# the project's test expects the old greeting, so it fails on the code this session just wrote
printf 'import hello\n\ndef test_greet():\n    assert hello.greet("x") == "hi x"\n' > "$PROJECT/test_hello.py"

say "a session is a directory, a task and a row"
SESSION="$("$CLI" --json code open --title "fix the greeting" | jq_ "d['id']")"
run code open --title "second session" >/dev/null
printf '$ archx-agent code list\n'
"$CLI" code list
check "the session is a database row" "$(dbq "SELECT COUNT(*) FROM code_sessions WHERE id = '$SESSION'")" "1"
check "the session binds the directory" "$(dbq "SELECT root FROM code_sessions WHERE id = '$SESSION'")" "$PROJECT"
check "the session owns a coding task" \
  "$(dbq "SELECT t.type FROM code_sessions s JOIN tasks t ON t.id = s.task_id WHERE s.id = '$SESSION'")" "coding"
TASK="$(dbq "SELECT task_id FROM code_sessions WHERE id = '$SESSION'")"
check "the schema grew, it did not reuse a table" \
  "$(dbq "SELECT name FROM sqlite_master WHERE name = 'code_changes'")" "code_changes"

say "nothing happens without a grant"
printf 'def greet(name):\n    return "hello " + name\n' > "$WORK/new_hello.py"
BEFORE="$(sha1sum "$PROJECT/hello.py" | cut -d' ' -f1)"
"$CLI" code write "$SESSION" hello.py --file "$WORK/new_hello.py" >"$WORK/refused.txt" 2>&1
REFUSED_EXIT=$?
check "a write without fs.write exits 4" "$REFUSED_EXIT" "4"
check "the file is untouched" "$(sha1sum "$PROJECT/hello.py" | cut -d' ' -f1)" "$BEFORE"
# once inside the reason the tool layer wrote, once in the hint this command adds
check "the refusal names the approval" "$(grep -c 'approvals approve ap_' "$WORK/refused.txt")" "2"
check "the refusal created a pending request" \
  "$("$CLI" --json approvals list | jq_ "any(a['capability'] == 'fs.write' and a['status'] == 'pending' for a in d)")" "True"
check "the refused edit did not become a change row" \
  "$(dbq "SELECT COUNT(*) FROM code_changes WHERE session_id = '$SESSION'")" "0"
cat "$WORK/refused.txt"

say "approving is what makes it possible, and the write then lands"
APPROVAL="$("$CLI" --json approvals list | jq_ "[a['id'] for a in d if a['capability'] == 'fs.write' and a['status'] == 'pending'][0]")"
"$CLI" approvals approve "$APPROVAL" >/dev/null
"$CLI" permissions grant fs.read --duration persistent --confirm >/dev/null
"$CLI" permissions grant fs.write --duration persistent --confirm >/dev/null
"$CLI" permissions grant shell.run --duration persistent --confirm >/dev/null
run code write "$SESSION" hello.py --file "$WORK/new_hello.py"
check "the file really changed" "$(grep -c 'hello ' "$PROJECT/hello.py")" "1"
check "the change is a row with a diff" \
  "$(dbq "SELECT action FROM code_changes WHERE session_id = '$SESSION'")" "modify"
check "the diff mentions the old and the new line" \
  "$("$CLI" --json code show "$SESSION" | jq_ "sum(c['diff'].count('-    return \"hi \"') + c['diff'].count('+    return \"hello \"') for c in d['changes'])")" "2"
check "the edit is attached to the task as an artifact" \
  "$("$CLI" --json tasks show "$TASK" | jq_ "any(a['kind'] == 'diff' for a in d['artifacts'])")" "True"

say "the runner records every command"
printf 'import hello\nprint(hello.greet("archx"))\n' > "$PROJECT/try_it.py"
printf '$ archx-agent code run %s "python3 try_it.py"\n' "$SESSION"
"$CLI" code run "$SESSION" "python3 try_it.py"
check "the command passed" \
  "$(dbq "SELECT status FROM code_runs WHERE session_id = '$SESSION' ORDER BY rowid DESC LIMIT 1")" "passed"
check "the exit code is recorded" \
  "$(dbq "SELECT exit_code FROM code_runs WHERE session_id = '$SESSION' ORDER BY rowid DESC LIMIT 1")" "0"
check "the argv that ran is recorded, not just the string" \
  "$("$CLI" --json code runs "$SESSION" | jq_ "d[0]['argv']")" "['python3', 'try_it.py']"
"$CLI" code run "$SESSION" "python3 -c failed_command" >/dev/null 2>&1
FAILED_EXIT=$?
check "a failing command exits 1" "$FAILED_EXIT" "1"
check "the failure is a failed row with its exit code" \
  "$(dbq "SELECT status || '/' || exit_code FROM code_runs WHERE session_id = '$SESSION' ORDER BY rowid DESC LIMIT 1")" "failed/1"
check "the failure asked a question on the task" \
  "$("$CLI" --json tasks show "$TASK" | jq_ "any('exited 1' in q for q in d['unresolved'])")" "True"
check "a timeout is a timeout, not a failure" \
  "$("$CLI" --json code run "$SESSION" "python3 -c \"import time; time.sleep(9)\"" --timeout 1 | jq_ "d['status']")" "timeout"

say "a refusal is in the ledger too"
G1="$("$CLI" --json permissions list --capability shell.run | jq_ "d[0]['id']")"
"$CLI" permissions revoke "$G1" --reason "acceptance: prove the refusal" >/dev/null
"$CLI" code run "$SESSION" "echo should not run" >/dev/null 2>&1
check "a refused command is recorded as refused" \
  "$(dbq "SELECT status FROM code_runs WHERE session_id = '$SESSION' ORDER BY rowid DESC LIMIT 1")" "refused"
"$CLI" permissions grant shell.run --duration persistent --confirm >/dev/null

say "checks come from the project, and run as the project"
"$PY" - "$PROJECT/archx.checks.json" <<'PYEOF'
import json, sys
json.dump({"checks": [
    {"name": "test", "command": sys.executable + " -m pytest -q test_hello.py", "timeout": 120},
    {"name": "compile", "command": sys.executable + " -m compileall -q hello.py"},
]}, open(sys.argv[1], "w"), indent=2)
PYEOF
printf '$ archx-agent code checks\n'
"$CLI" code checks "$SESSION"
check "two checks are declared" "$("$CLI" --json code checks "$SESSION" | jq_ "len(d['checks'])")" "2"
"$CLI" code test "$SESSION" >/dev/null 2>&1
TEST_EXIT=$?
check "the project's own test fails before the fix" "$TEST_EXIT" "1"
check "the failure is recorded under the check's name" \
  "$(dbq "SELECT check_name || '/' || status FROM code_runs WHERE session_id = '$SESSION' AND check_name IS NOT NULL ORDER BY rowid DESC LIMIT 1")" "test/failed"
printf 'def greet(name):\n    return "hi " + name\n' > "$WORK/reverted.py"
"$CLI" code write "$SESSION" hello.py --file "$WORK/reverted.py" >/dev/null
run code test "$SESSION"
check "the same check passes after the edit" \
  "$(dbq "SELECT status FROM code_runs WHERE session_id = '$SESSION' AND check_name = 'test' ORDER BY rowid DESC LIMIT 1")" "passed"
"$CLI" code test "$SESSION" --check nope >"$WORK/nocheck.txt" 2>&1
check "the unknown-check message lists the declared ones" "$(grep -c 'compile, test' "$WORK/nocheck.txt")" "1"

say "the session is a patch you can read"
printf '$ archx-agent code diff %s\n' "$SESSION"
"$CLI" code diff "$SESSION" | head -20
check "the patch covers the files the session edited" \
  "$("$CLI" --json code diff "$SESSION" | jq_ "d['files']")" "['hello.py']"
check "the patch is attached as an artifact" \
  "$("$CLI" --json code diff "$SESSION" | jq_ "d['artifact_id'].startswith('ar_')")" "True"

say "a session is reproducible"
check "the reproducer reads the coding task" \
  "$("$CLI" --json tasks reproduce "$TASK" 2>/dev/null | jq_ "d['fidelity'] in ('exact', 'partial')")" "True"
check "its plan contains the command that ran" \
  "$("$CLI" --json tasks reproduce "$TASK" | jq_ "any('try_it.py' in c for c in d['commands'])")" "True"
FIRST_RUN="$("$CLI" --json code runs "$SESSION" | jq_ "[r['id'] for r in d if r['status'] == 'passed'][0]")"
check "a recorded run can be replayed" "$("$CLI" --json code rerun "$FIRST_RUN" | jq_ "d['replayed_from']")" "$FIRST_RUN"

say "the page is a client of the same service"
"$CLI" gui serve --port "$PORT" --token "$TOKEN" >"$WORK/gui.log" 2>&1 &
GUI_PID=$!
for _ in $(seq 1 40); do
  [ "$(status_of "$BASE/api/health")" = "200" ] && break
  sleep 0.25
done
check "the page lists the CLI's sessions" \
  "$(get_json "$BASE/api/code/sessions" | jq_ "len(d['data']['sessions'])")" "2"
check "the page knows the tool roots it may open" \
  "$(get_json "$BASE/api/code/sessions" | jq_ "d['data']['roots'][0]")" "$PROJECT"
GUI_SESSION="$(post_json "$BASE/api/code/sessions" '{"title":"from the page"}' | jq_ "d['data']['id']")"
check "a session opened in the page is a CLI session" \
  "$("$CLI" --json code list | jq_ "any(s['id'] == '$GUI_SESSION' for s in d)")" "True"
for GRANT in $("$CLI" --json permissions list --capability fs.read | jq_ "' '.join(g['id'] for g in d if not g['revoked_at'])"); do
  "$CLI" permissions revoke "$GRANT" --reason "acceptance: prove the refusal" >/dev/null
done
check "a read without fs.read is a 403 that names the tool" \
  "$(post_code "$BASE/api/code/sessions/$GUI_SESSION/read" '{"path":"hello.py"}')" "403"
check "the refusal is a code the page can branch on" \
  "$(post_json "$BASE/api/code/sessions/$GUI_SESSION/read" '{"path":"hello.py"}' | jq_ "d['error']['code']")" "approval_required"
"$CLI" permissions grant fs.read --duration persistent --confirm >/dev/null
"$CLI" permissions grant fs.write --duration persistent --confirm >/dev/null
check "a write from the page is a file on disk" \
  "$(post_code "$BASE/api/code/sessions/$GUI_SESSION/write" '{"path":"made_in_the_page.py","content":"value = 7\n"}')" "200"
check "the file the page wrote is really there" "$(grep -c 'value = 7' "$PROJECT/made_in_the_page.py")" "1"
check "the CLI sees the page's edit" \
  "$("$CLI" --json code show "$GUI_SESSION" | jq_ "d['changes'][0]['path']")" "made_in_the_page.py"
check "a run from the page is in the same ledger" \
  "$(post_json "$BASE/api/code/sessions/$GUI_SESSION/run" '{"command":"echo from the page"}' | jq_ "d['data']['status']")" "passed"
check "and the CLI can read that run" \
  "$("$CLI" --json code runs "$GUI_SESSION" | jq_ "d[0]['stdout'].strip()")" "from the page"
check "a bad timeout is a 400, not a 500" \
  "$(post_code "$BASE/api/code/sessions/$GUI_SESSION/run" '{"command":"echo x","timeout":"soon"}')" "400"
check "closing a session in the page closes it for the CLI" \
  "$(post_code "$BASE/api/code/sessions/$GUI_SESSION/close" '{"note":"done"}')" "200"
check "a closed session refuses later edits with a 400" \
  "$(post_code "$BASE/api/code/sessions/$GUI_SESSION/write" '{"path":"late.py","content":"x\n"}')" "400"
check "the coding routes are in the route table" \
  "$("$CLI" gui routes | grep -c '/api/code')" "14"

say "a closed session keeps its record"
run code close "$SESSION" --note "shipped"
check "the task is completed with the session" \
  "$(dbq "SELECT status FROM tasks WHERE id = '$TASK'")" "completed"
check "the edits are still readable" \
  "$("$CLI" --json code show "$SESSION" | jq_ "len(d['changes']) > 0")" "True"

say "stopping the server closes the port"
kill "$GUI_PID"
wait "$GUI_PID" 2>/dev/null
GUI_PID=""
sleep 0.5
CLOSED_PORT="$(status_of "$BASE/api/health" 2>/dev/null)"
check "the port is closed, not orphaned" "${CLOSED_PORT:-000}" "000"

printf '\n### summary\n'
for line in "${CHECKS[@]}"; do printf '%s\n' "$line"; done
if [ "$FAILURES" -gt 0 ]; then
  printf '\nM31 ACCEPTANCE FAILED: %d check(s)\n' "$FAILURES"
  exit 1
fi
printf '\nM31 acceptance: %d checks passed\n' "${#CHECKS[@]}"
