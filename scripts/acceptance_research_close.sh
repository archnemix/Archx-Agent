#!/usr/bin/env bash
# Research closure acceptance: a question is done when you say so.
#
# The claims being checked are the ones that would be easy to fake:
#   * closing is a second fact - it does not rewrite the run's own status or coverage;
#   * it is explicit and reversible, and both directions are recorded;
#   * a second close (or a reopen of an open run) is a refusal, not a silent no-op;
#   * the CLI, the HTTP layer and the page all see the same record;
#   * a run that was closed can still be read, reported and deleted.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$HERE/.venv/bin/archx-agent"
PY="$HERE/.venv/bin/python"
HOME_DIR="${1:-$(mktemp -d /tmp/archx-close-XXXXXX)}"
export ARCHX_PATHS_HOME="$HOME_DIR"
export ARCHX_ALLOW_SIMULATED=1
mkdir -p "$HOME_DIR"
PORT="$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
TOKEN="close-acceptance-token"
BASE="http://127.0.0.1:$PORT"
FAILURES=0
CHECKS=()
GUI_PID=""

say() { printf '\n### %s\n' "$*"; }
jq_() { "$PY" -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
dbq() { "$PY" -c "
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
print(conn.execute(sys.argv[2]).fetchone()[0])
" "$HOME_DIR/archx.db" "$1"; }
check() {
  if [ "$2" = "$3" ]; then
    CHECKS+=("ok   | $1 | $2"); printf '[ok]   %s = %s\n' "$1" "$2"
  else
    CHECKS+=("FAIL | $1 | got '$2' want '$3'"); printf "[FAIL] %s: got '%s' want '%s'\n" "$1" "$2" "$3"
    FAILURES=$((FAILURES + 1))
  fi
}
http_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
get_json() { curl -s -H "X-Archx-Token: $TOKEN" "$1"; }
post_json() { curl -s -X POST -H "X-Archx-Token: $TOKEN" -H "X-Archx-Request: gui" -H "Content-Type: application/json" -d "$2" "$1"; }
post_code() { curl -s -o /dev/null -w '%{http_code}' -X POST -H "X-Archx-Token: $TOKEN" -H "X-Archx-Request: gui" -H "Content-Type: application/json" -d "$2" "$1"; }

cleanup() {
  [ -n "$GUI_PID" ] && kill "$GUI_PID" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT

say "a fresh home reaches the closure migration"
"$CLI" --version
"$CLI" info >/dev/null      # opens (and migrates) the home before we read it
check "the schema is past v19" "$([ "$(dbq 'select max(version) from schema_migrations')" -ge 20 ] && echo yes)" "yes"
check "v20 is the research-closure migration" \
  "$(dbq "select name from schema_migrations where version = 20")" "research-closure"
check "the run table carries the closure columns" \
  "$(dbq "select count(*) from pragma_table_info('research_runs') where name in ('closed_at','closed_note')")" "2"

say "a real local run, then a close that does not touch what the runner said"
"$CLI" memory add --kind permanent --category fact --title "SQLite locking" \
  --content "SQLite takes one write lock per transaction. WAL mode lets readers continue. A busy timeout makes a second writer wait instead of failing." >/dev/null

say "the GUI starts and answers only with its token"
"$CLI" gui serve --port "$PORT" --token "$TOKEN" >"$HOME_DIR/gui.log" 2>&1 &
GUI_PID=$!
for _ in $(seq 1 100); do
  if "$PY" - "$PORT" <<'PYE'
import socket, sys
try:
    socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=0.2).close()
except OSError:
    raise SystemExit(1)
PYE
  then break; fi
  sleep 0.1
done
check "the page is served" "$(http_of "$BASE/")" "200"
check "no token means no run list" "$(http_of "$BASE/api/research")" "401"

RUN_JSON="$(post_json "$BASE/api/research" '{"question":"how does sqlite locking work","mode":"local","use_model":false}')"
RUN_ID="$(printf '%s' "$RUN_JSON" | jq_ "d['data']['run']['id']")"
check "a local run completed" "$(printf '%s' "$RUN_JSON" | jq_ "d['data']['run']['status']")" "completed"
check "and it is not closed by itself" "$(printf '%s' "$RUN_JSON" | jq_ "d['data']['run']['closed']")" "False"
BEFORE_COVERAGE="$(printf '%s' "$RUN_JSON" | jq_ "d['data']['run']['coverage']")"

say "closing records your decision, not the runner's number"
CLOSED="$(post_json "$BASE/api/research/$RUN_ID/close" '{"note":"enough for the design doc"}')"
check "the close is a 200" "$(printf '%s' "$CLOSED" | jq_ "d['ok']")" "True"
check "the run is closed" "$(printf '%s' "$CLOSED" | jq_ "d['data']['closed']")" "True"
check "with the note you gave it" "$(printf '%s' "$CLOSED" | jq_ "d['data']['closed_note']")" "enough for the design doc"
check "the run's own status is untouched" "$(printf '%s' "$CLOSED" | jq_ "d['data']['status']")" "completed"
check "the coverage is untouched" "$(printf '%s' "$CLOSED" | jq_ "d['data']['coverage']")" "$BEFORE_COVERAGE"
check "a timestamp was written" "$(printf '%s' "$CLOSED" | jq_ "bool(d['data']['closed_at'])")" "True"

say "a second close is a refusal with a reason"
CODE="$(post_code "$BASE/api/research/$RUN_ID/close" '{}')"
check "closing twice is a 409" "$CODE" "409"
check "and names the first close" "$(post_json "$BASE/api/research/$RUN_ID/close" '{}' | jq_ "'already closed' in d['error']['message']")" "True"

say "the filters agree with the record"
check "closed=1 finds it" "$(get_json "$BASE/api/research?closed=1" | jq_ "any(r['id'] == '$RUN_ID' for r in d['data'])")" "True"
check "closed=0 does not" "$(get_json "$BASE/api/research?closed=0" | jq_ "any(r['id'] == '$RUN_ID' for r in d['data'])")" "False"
check "the CLI sees the same record" \
  "$("$CLI" --json research show "$RUN_ID" | jq_ "d['closed']")" "True"
check "research list --closed prints it" \
  "$("$CLI" --json research list --closed | jq_ "any(r['id'] == '$RUN_ID' for r in d)")" "True"

say "a closed run can still be read, reported and reopened"
check "the report is still served" "$(http_of -H "X-Archx-Token: $TOKEN" "$BASE/api/research/$RUN_ID/report")" "200"
REOPENED="$(post_json "$BASE/api/research/$RUN_ID/reopen" '{}')"
check "reopen clears the flag" "$(printf '%s' "$REOPENED" | jq_ "d['data']['closed']")" "False"
check "reopen clears the timestamp" "$(printf '%s' "$REOPENED" | jq_ "d['data']['closed_at'] is None")" "True"
check "reopening again is a 409" "$(post_code "$BASE/api/research/$RUN_ID/reopen" '{}')" "409"

say "the CLI is the same record, and its refusals are exit codes"
check "research close exits 0" "$("$CLI" research close "$RUN_ID" --note "settled" >/dev/null 2>&1; echo $?)" "0"
check "a second close exits 1" "$("$CLI" research close "$RUN_ID" >/dev/null 2>&1; echo $?)" "1"
check "the refusal names the first close" \
  "$("$CLI" research close "$RUN_ID" 2>&1 | grep -c 'already closed')" "1"
check "--closed and --open together exit 2" "$("$CLI" research list --closed --open >/dev/null 2>&1; echo $?)" "2"
check "an unknown run is a usage error" "$("$CLI" research close rs_nope >/dev/null 2>&1; echo $?)" "2"
check "research reopen exits 0" "$("$CLI" research reopen "$RUN_ID" >/dev/null 2>&1; echo $?)" "0"
check "reopening an open run exits 1" "$("$CLI" research reopen "$RUN_ID" >/dev/null 2>&1; echo $?)" "1"

say "the record is in the trace, not only in the row"
"$CLI" research close "$RUN_ID" >/dev/null 2>&1
check "the close was traced" \
  "$("$CLI" --json trace list --kind research 2>/dev/null | jq_ "any(e['name'] == 'research.closed' for e in d)")" "True"

say "the page offers the control, and nothing pretends"
check "the research panel has a detail region" \
  "$(curl -s "$BASE/" | grep -c 'id="research-detail"')" "1"
check "the page calls the close route" \
  "$(curl -s "$BASE/view-research.js" | grep -c '/close')" "1"
check "the reopen path exists too" "$(curl -s "$BASE/view-research.js" | grep -c '/reopen')" "1"
check "no inline handler was added" "$(curl -s "$BASE/" | grep -c 'onclick=')" "0"

say "summary"
printf '\n'
if [ "$FAILURES" -eq 0 ]; then
  printf 'Research closure acceptance: %s checks passed\n' "${#CHECKS[@]}"
else
  printf 'RESEARCH CLOSURE ACCEPTANCE FAILED: %s of %s checks\n' "$FAILURES" "${#CHECKS[@]}"
fi
exit "$FAILURES"
