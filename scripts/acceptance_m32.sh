#!/usr/bin/env bash
# M32 acceptance: Experimental Mode, driven the way a person would use it.
#
# The claims being checked are the ones that would be easy to fake:
#   * an experiment is a declared row: a command, its parameters and where the numbers come from,
#     and a declaration that does not add up is refused before anything runs;
#   * a run is a real execution: the parameters it used, the command it resolved to, the exit code,
#     the duration and the task that recorded it;
#   * a metric is only ever read from the declared source - bad JSON, a non-numeric value and a
#     missing file all leave the metric absent *and say why*, instead of showing a zero;
#   * a comparison ranks what it can and names what it cannot, rather than dropping silent rows;
#   * the numbers are queryable rows, so "which run was best" is a query and not a re-parse.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The repo's own venv when there is one (local runs); the interpreter that has archx-agent
# installed otherwise (the CI runner installs it into the system python).
CLI="${ARCHX_CLI:-$HERE/.venv/bin/archx-agent}"
[ -x "$CLI" ] || CLI="$(command -v archx-agent)"
PY="${ARCHX_PY:-$HERE/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python)"
WORK="${1:-$(mktemp -d /tmp/archx-m32-XXXXXX)}"
HOME_DIR="$WORK/home"
LAB="$WORK/lab"
export ARCHX_PATHS_HOME="$HOME_DIR"
export ARCHX_TOOLS_ROOTS="$LAB"
export ARCHX_ALLOW_SIMULATED=1
mkdir -p "$HOME_DIR" "$LAB"
PORT="$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
TOKEN="m32-acceptance-token"
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

dbq() { "$PY" "$WORK/dbq.py" "$HOME_DIR/archx.db" "$1"; }
# JSON columns are stored readable (indented), so a shell string compare needs them canonical
jsonq() { "$PY" "$WORK/jsonq.py" "$HOME_DIR/archx.db" "$1"; }
api_jsonq() { "$PY" -c "import json,sys; d=json.load(sys.stdin)['data']; print($1)"; }

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

cat > "$WORK/jsonq.py" <<'PYEOF'
import json, sqlite3, sys

connection = sqlite3.connect(sys.argv[1])
value = connection.execute(sys.argv[2]).fetchone()[0]
try:
    print(json.dumps(json.loads(value), sort_keys=True))
except (TypeError, ValueError):
    print(value)
PYEOF

printf 'M32 acceptance on %s\n' "$WORK"
"$CLI" init >/dev/null 2>&1

# Three scripts: one emits its metrics as the last line of stdout, one writes a file, and one
# fails after printing, which is the case where "it ran" and "it worked" come apart.
cat > "$LAB/bench.py" <<'PYEOF'
import json, sys
n = int(sys.argv[1])
data = sorted(range(n * 100), reverse=True)
print("sorted", len(data), "values")
print(json.dumps({"size": n, "quality": n / 10.0}))
PYEOF
cat > "$LAB/tofile.py" <<'PYEOF'
import json
json.dump({"accuracy": 0.91, "loss": 0.12}, open("metrics.json", "w"))
print("wrote metrics.json")
PYEOF
cat > "$LAB/noisy.py" <<'PYEOF'
print("this line is not json")
PYEOF
cat > "$LAB/broken.py" <<'PYEOF'
import sys
print("printed before failing")
sys.exit(3)
PYEOF

say "an experiment is a declaration, and a bad one is refused"
EXP="$("$CLI" --json experiment create sizes \
  --command 'python bench.py {n}' --param n=5 --metric-source stdout-json \
  --hypothesis "a bigger n sorts more values" | jq_ "d['id']")"
printf 'experiment: %s\n' "$EXP"
check "the declaration is a row" "$(dbq "SELECT COUNT(*) FROM experiment_specs WHERE id = '$EXP'")" "1"
check "it is open" "$(dbq "SELECT status FROM experiment_specs WHERE id = '$EXP'")" "open"
check "the metrics source is stored as declared" \
  "$(jsonq "SELECT metrics_source FROM experiment_specs WHERE id = '$EXP'")" '{"kind": "stdout-json"}'
printf '$ archx-agent experiment create broken --command "python bench.py {depth}"\n'
"$CLI" experiment create broken --command 'python bench.py {depth}' >/dev/null 2>"$WORK/e1"
check "an undeclared placeholder is refused" "$?" "2"
check "and it is named" "$(grep -c 'no parameter is declared' "$WORK/e1")" "1"
printf '$ archx-agent experiment create unused --command "echo hi" --param unused=1\n'
"$CLI" experiment create unused --command 'echo hi' --param unused=1 >/dev/null 2>"$WORK/e2"
check "a parameter the command never uses is refused" "$?" "2"
printf '$ archx-agent experiment create nometrics --command "echo hi" --metric-source vibes\n'
"$CLI" experiment create nometrics --command 'echo hi' --metric-source vibes >/dev/null 2>&1
check "an invented metrics source is refused" "$?" "2"
check "no refused declaration was stored" "$(dbq "SELECT COUNT(*) FROM experiment_specs")" "1"

say "a run without a grant is recorded as refused, and runs nothing"
printf '$ archx-agent experiment run %s\n' "$EXP"
"$CLI" experiment run "$EXP" >/dev/null 2>"$WORK/e3"
check "an ungranted run exits 4" "$?" "4"
check "the refusal names the approval to approve" \
  "$(grep -q 'approvals approve ap_' "$WORK/e3" && echo yes || echo no)" "yes"
check "the refusal is a row, not an absence" \
  "$(dbq "SELECT status FROM experiment_runs WHERE experiment_id = '$EXP'")" "refused"
check "and it says why there are no numbers" \
  "$(dbq "SELECT metrics_error FROM experiment_runs WHERE experiment_id = '$EXP'")" \
  "the command was refused before it ran"

say "with shell.run granted, the run is real"
"$CLI" permissions grant shell.run --duration persistent --subject '*' --confirm >/dev/null
"$CLI" permissions grant fs.read --duration persistent --subject '*' --confirm >/dev/null
RUN1="$("$CLI" --json experiment run "$EXP" --set n=5 | jq_ "d['id']")"
printf 'run: %s\n' "$RUN1"
check "the run passed" "$(dbq "SELECT status FROM experiment_runs WHERE id = '$RUN1'")" "passed"
check "the parameters it actually used are kept" \
  "$(jsonq "SELECT params FROM experiment_runs WHERE id = '$RUN1'")" '{"n": "5"}'
check "the resolved command is kept" \
  "$(dbq "SELECT command FROM experiment_runs WHERE id = '$RUN1'")" "python bench.py 5"
check "the metrics are rows" \
  "$(dbq "SELECT COUNT(*) FROM experiment_metrics WHERE run_id = '$RUN1'")" "2"
check "the size metric is the number the command printed" \
  "$(dbq "SELECT value FROM experiment_metrics WHERE run_id = '$RUN1' AND name = 'size'")" "5.0"
check "the run belongs to a task" \
  "$(dbq "SELECT COUNT(*) FROM tasks WHERE id = (SELECT task_id FROM experiment_runs WHERE id = '$RUN1')")" "1"
check "and the task completed" \
  "$(dbq "SELECT status FROM tasks WHERE id = (SELECT task_id FROM experiment_runs WHERE id = '$RUN1')")" "completed"
check "the output is an artifact" \
  "$(dbq "SELECT COUNT(*) FROM artifacts WHERE id = (SELECT artifact_id FROM experiment_runs WHERE id = '$RUN1')")" "1"
check "the task timeline carries the metric" \
  "$(dbq "SELECT COUNT(*) FROM task_log WHERE task_id = (SELECT task_id FROM experiment_runs WHERE id = '$RUN1') AND detail LIKE '%size = 5%'")" "1"

say "two more runs, so there is something to compare"
"$CLI" --json experiment run "$EXP" --set n=9 >/dev/null
"$CLI" --json experiment run "$EXP" --set n=40 >/dev/null
printf '$ archx-agent experiment compare %s --metric quality\n' "$EXP"
"$CLI" experiment compare "$EXP" --metric quality
BEST="$("$CLI" --json experiment compare "$EXP" --metric quality | jq_ "d['best']['value']")"
check "the best run is the highest quality" "$BEST" "4.0"
check "minimise flips the ranking" \
  "$("$CLI" --json experiment compare "$EXP" --metric quality --minimise | jq_ "d['best']['value']")" "0.5"
check "an unknown metric is refused with the known ones listed" \
  "$("$CLI" experiment compare "$EXP" --metric speed 2>&1 >/dev/null | grep -c 'quality')" "1"
check "the runs are all in the ledger" \
  "$(dbq "SELECT COUNT(*) FROM experiment_runs WHERE experiment_id = '$EXP'")" "4"

say "metrics are read from the declared source, or not at all"
NOISY="$("$CLI" --json experiment create noisy --command 'python noisy.py' --metric-source stdout-json | jq_ "d['id']")"
"$CLI" --json experiment run "$NOISY" >/dev/null
check "stdout that is not JSON leaves no metric" \
  "$(dbq "SELECT COUNT(*) FROM experiment_metrics WHERE run_id IN (SELECT id FROM experiment_runs WHERE experiment_id = '$NOISY')")" "0"
check "and the run says why, in words" \
  "$(dbq "SELECT COUNT(*) FROM experiment_runs WHERE experiment_id = '$NOISY' AND metrics_error LIKE '%not valid JSON%'")" "1"
check "a run with no metrics is still a run" \
  "$(dbq "SELECT status FROM experiment_runs WHERE experiment_id = '$NOISY'")" "passed"
printf '$ archx-agent experiment create failed --command "python broken.py"\n'
FAILED="$("$CLI" --json experiment create failed --command 'python broken.py' | jq_ "d['id']")"
"$CLI" experiment run "$FAILED" >/dev/null 2>&1
check "a failing command exits 1" "$?" "1"
check "and is recorded as failed with its exit code" \
  "$(dbq "SELECT status || ':' || exit_code FROM experiment_runs WHERE experiment_id = '$FAILED'")" "failed:3"
printf '$ archx-agent experiment create filed --command "python tofile.py" --metric-source file --metric-file metrics.json\n'
FILED="$("$CLI" --json experiment create filed --command 'python tofile.py' \
  --metric-source file --metric-file metrics.json | jq_ "d['id']")"
"$CLI" --json experiment run "$FILED" >/dev/null
check "a metrics file is read from the run's own directory" \
  "$(dbq "SELECT value FROM experiment_metrics WHERE name = 'accuracy' AND run_id IN (SELECT id FROM experiment_runs WHERE experiment_id = '$FILED')")" "0.91"
MISSING="$("$CLI" --json experiment create missing --command 'python tofile.py' \
  --metric-source file --metric-file nope.json | jq_ "d['id']")"
"$CLI" --json experiment run "$MISSING" >/dev/null
check "a missing metrics file is named, not zeroed" \
  "$(dbq "SELECT COUNT(*) FROM experiment_runs WHERE experiment_id = '$MISSING' AND metrics_error LIKE '%nope.json%'")" "1"

say "a parameter has to survive the shell it is substituted into"
UNSAFE="$("$CLI" experiment run "$EXP" --set 'n=5; rm -rf /' 2>&1 >/dev/null)"
printf '$ archx-agent experiment run %s --set "n=5; rm -rf /"\n' "$EXP"
"$CLI" experiment run "$EXP" --set 'n=5; rm -rf /' >/dev/null 2>&1
check "an unsafe value is refused before it runs" "$?" "2"
check "and nothing was added to the ledger" \
  "$(dbq "SELECT COUNT(*) FROM experiment_runs WHERE experiment_id = '$EXP'")" "4"
check "the refusal explains the rule" "$(printf '%s' "$UNSAFE" | grep -c 'shell-safe')" "1"
"$CLI" experiment run "$EXP" --set bogus=1 >/dev/null 2>&1
check "an unknown parameter is refused" "$?" "2"

say "the record stays readable, and closing is not deleting"
"$CLI" experiment close "$EXP" >/dev/null
check "the experiment is closed" "$(dbq "SELECT status FROM experiment_specs WHERE id = '$EXP'")" "closed"
"$CLI" experiment run "$EXP" >/dev/null 2>&1
check "a closed experiment cannot run" "$?" "2"
check "its four runs are still there" \
  "$(dbq "SELECT COUNT(*) FROM experiment_runs WHERE experiment_id = '$EXP'")" "4"
"$CLI" experiment show "$EXP" >/dev/null
check "show still works on a closed experiment" "$?" "0"
"$CLI" experiment reopen "$EXP" >/dev/null
check "reopening is allowed" "$(dbq "SELECT status FROM experiment_specs WHERE id = '$EXP'")" "open"

say "the GUI is a client of the same rows"
"$CLI" gui serve --host 127.0.0.1 --port "$PORT" --token "$TOKEN" --no-open >"$WORK/gui.log" 2>&1 &
GUI_PID=$!
for _ in $(seq 1 40); do
  [ "$(status_of "$BASE/api/health")" = "200" ] && break
  sleep 0.25
done
check "the page lists the experiments" \
  "$(get_json "$BASE/api/experiments" | api_jsonq "len(d['experiments'])")" "5"
check "the page shows a run's metrics" \
  "$(get_json "$BASE/api/experiments/$EXP" | api_jsonq "d['stats']['runs']")" "4"
check "the page compares on a named metric" \
  "$(get_json "$BASE/api/experiments/$EXP/compare?metric=quality" | api_jsonq "d['best']['value']")" "4.0"
HTTP_CODE="$(status_of -X POST -H "X-Archx-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"params": {"n": "5 6"}}' "$BASE/api/experiments/$EXP/run")"
check "a bad parameter is a 400 over HTTP" "$HTTP_CODE" "400"
check "an unauthenticated call is refused" "$(status_of "$BASE/api/experiments")" "401"

say "deleting takes the runs and the numbers with it"
"$CLI" experiment delete "$MISSING" >/dev/null 2>&1
check "delete without --yes is refused" "$?" "2"
"$CLI" experiment delete "$MISSING" --yes >/dev/null
check "delete with --yes removes the experiment" \
  "$(dbq "SELECT COUNT(*) FROM experiment_specs WHERE id = '$MISSING'")" "0"
check "and its runs" \
  "$(dbq "SELECT COUNT(*) FROM experiment_runs WHERE experiment_id = '$MISSING'")" "0"
check "and its metrics" \
  "$(dbq "SELECT COUNT(*) FROM experiment_metrics WHERE run_id NOT IN (SELECT id FROM experiment_runs)")" "0"

say "the record survives a restart"
"$CLI" --json experiment list >/dev/null
check "listing still works" "$?" "0"
check "the metrics are still queryable after reopening the home" \
  "$("$CLI" --json experiment compare "$EXP" --metric quality | jq_ "d['best']['value']")" "4.0"
check "stats agree with the rows" \
  "$("$CLI" --json experiment stats | jq_ "d['runs']")" \
  "$(dbq "SELECT COUNT(*) FROM experiment_runs")"

printf '\nM32 acceptance: %s checks passed, %s failed\n' \
  "$((${#CHECKS[@]} - FAILURES))" "$FAILURES"
[ "$FAILURES" -eq 0 ] || exit 1
