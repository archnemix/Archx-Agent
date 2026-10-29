#!/usr/bin/env bash
# M37 acceptance: remote compute and portability - a bundle that can be checked, and a hash that is
# re-measured on arrival.
#
# The claim this script exists to test is *not* "a bundle was sent somewhere". It is:
#   * the bundle identifies its input: its hash matches its bytes, each record carries the file
#     digest M35 recorded and a separate digest of the text the trainer sees, and a corpus edited
#     after the build is refused rather than shipped;
#   * nothing leaves the machine without the switch, an endpoint and an approval, and every refusal
#     is a row with a reason;
#   * the worker checks the bundle against itself before it computes (protocol, body hash, text
#     digests, rebuilt manifest) and refuses over the wire, not with a traceback;
#   * the artifact the worker produced is re-hashed here, and the numbers match a *local* run of the
#     same config exactly - a worker that computed something else would show up as a difference;
#   * a worker that misreports its hash produces `received`, never `verified`, and re-reading the
#     file cannot rescue it;
#   * a dispatch to a port nobody is listening on is an attempt row, not a crash.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="${ARCHX_CLI:-$HERE/.venv/bin/archx-agent}"
[ -x "$CLI" ] || CLI="$(command -v archx-agent)"
PY="${ARCHX_PY:-$HERE/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python)"
WORK="${1:-$(mktemp -d /tmp/archx-m37-XXXXXX)}"
HOME_DIR="$WORK/home"
LAB="$WORK/lab"
export ARCHX_PATHS_HOME="$HOME_DIR"
export ARCHX_TOOLS_ROOTS="$LAB"
mkdir -p "$HOME_DIR" "$LAB"
free_port() {
  "$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'
}
PORT="$(free_port)"
WPORT="$(free_port)"
LIE_PORT="$(free_port)"
OLD_PORT="$(free_port)"
DEAD_PORT="$(free_port)"
TOKEN="m37-acceptance-token"
BASE="http://127.0.0.1:$PORT"
ENDPOINT="http://127.0.0.1:$WPORT"
FAILURES=0
CHECKS=()
GUI_PID=""
WORKER_PID=""
LIE_PID=""
OLD_PID=""

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
api_jsonq() { "$PY" -c "import json,sys; d=json.load(sys.stdin)['data']; print($1)"; }
dbq() {
  "$PY" - "$HOME_DIR/archx.db" "$1" <<'PYEOF'
import sqlite3, sys
connection = sqlite3.connect(sys.argv[1])
print(connection.execute(sys.argv[2]).fetchone()[0])
PYEOF
}
wait_for_port() {
  for _ in $(seq 1 60); do
    if curl -s -o /dev/null "http://127.0.0.1:$1/health"; then return 0; fi
    sleep 0.1
  done
  return 1
}

cleanup() {
  [ -n "$GUI_PID" ] && kill "$GUI_PID" 2>/dev/null
  [ -n "$WORKER_PID" ] && kill "$WORKER_PID" 2>/dev/null
  [ -n "$LIE_PID" ] && kill "$LIE_PID" 2>/dev/null
  [ -n "$OLD_PID" ] && kill "$OLD_PID" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT

# Two labels, four files each: the same corpus M36 trained on, so a local run and a remote run can
# be compared on identical input.
mkdir -p "$LAB/corpus/python" "$LAB/corpus/rust"
for n in 1 2 3 4; do
  printf 'def function_%s(x):\n    return x + %s\n' "$n" "$n" > "$LAB/corpus/python/file$n.txt"
  printf 'fn function_%s(x: i32) -> i32 {\n    x + %s\n}\n' "$n" "$n" > "$LAB/corpus/rust/file$n.txt"
done

printf 'M37 acceptance on %s\n' "$WORK"
"$CLI" init >/dev/null 2>&1

say "the schema adopts the table v8 reserved, and adds what makes a result checkable"
check "remote is a versioned migration" \
  "$(dbq "SELECT COUNT(*) FROM schema_migrations WHERE version = 27")" "1"
check "jobs and attempts are tables" \
  "$(dbq "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('remote_jobs','remote_attempts')")" "2"
check "the reserved columns survive the adoption" \
  "$(dbq "SELECT COUNT(*) FROM pragma_table_info('remote_jobs') WHERE name IN ('provider','status','config','estimate','actual','outputs','approved_by','task_id')")" "8"
check "and the two hashes are separate columns" \
  "$(dbq "SELECT COUNT(*) FROM pragma_table_info('remote_jobs') WHERE name IN ('claimed_sha256','received_sha256')")" "2"
check "a fresh home has dispatched nothing" "$("$CLI" --json remote stats | jq_ "d['jobs']")" "0"
check "and says why nothing could be" "$("$CLI" --json remote stats | jq_ "any('remote compute is off' in r for r in d['why_not'])")" "True"
check "the protocol is named" "$("$CLI" --json remote stats | jq_ "d['protocol']")" "archx-remote/1"

"$CLI" permissions grant fs.read --subject '*' --duration persistent --confirm >/dev/null
"$CLI" permissions grant fs.write --subject '*' --duration persistent --confirm >/dev/null
DS="$("$CLI" --json dataset create code --source corpus --license MIT | jq_ "d['id']")"
"$CLI" dataset scan "$DS" >/dev/null 2>&1
"$CLI" dataset clean "$DS" >/dev/null 2>&1

say "a bundle cannot be made from a dataset nobody built"
"$CLI" remote export "$DS" >"$WORK/unbuilt.out" 2>&1
check "an unbuilt dataset exits 2 (usage), not 0" "$?" "2"
check "and the reason asks for a build" \
  "$(grep -c 'no manifest yet' "$WORK/unbuilt.out")" "1"

"$CLI" dataset split "$DS" --train 0.5 --val 0.25 --test 0.25 --seed m37 >/dev/null 2>&1
"$CLI" dataset build "$DS" >/dev/null 2>&1

say "a bundle identifies its input down to two digests per record"
JOB="$("$CLI" --json remote export "$DS" --order 2 --seed 5 | jq_ "d['id']")"
BUNDLE_SHA="$(dbq "SELECT bundle_sha256 FROM remote_jobs WHERE id = '$JOB'")"
BUNDLE="$(dbq "SELECT bundle_path FROM remote_jobs WHERE id = '$JOB'")"
BUNDLE_FILE="$LAB/$(basename "$BUNDLE")"
check "the bundle is a file on disk" "$([ -f "$BUNDLE_FILE" ] && echo yes)" "yes"
check "its hash is the hash of its bytes" \
  "$("$PY" -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$BUNDLE_FILE")" \
  "$BUNDLE_SHA"
check "it carries every kept record" \
  "$("$PY" -c "import json,sys; print(len(json.load(open(sys.argv[1]))['dataset']['entries']))" "$BUNDLE_FILE")" "8"
check "with a file digest and a text digest that differ" \
  "$("$PY" -c "
import json,sys
b=json.load(open(sys.argv[1]))
print(all(e['file_sha256'] != e['text_sha256'] for e in b['dataset']['entries']))" "$BUNDLE_FILE")" "True"
check "the text digest is the digest of the text" \
  "$("$PY" -c "
import hashlib,json,sys
b=json.load(open(sys.argv[1]))
print(all(hashlib.sha256(e['text'].encode()).hexdigest() == e['text_sha256'] for e in b['dataset']['entries']))" "$BUNDLE_FILE")" "True"
check "the manifest checksum is the dataset's own" \
  "$("$PY" -c "
import json,sys
b=json.load(open(sys.argv[1]))
print(b['dataset']['manifest_checksum'])" "$BUNDLE_FILE")" \
  "$(dbq "SELECT checksum FROM datasets WHERE id = '$DS'")"
check "the run is declared in the bundle" \
  "$("$PY" -c "
import json,sys
print(json.load(open(sys.argv[1]))['run']['order'])" "$BUNDLE_FILE")" "2"

say "nothing leaves the machine until the switch, an endpoint and an approval all say yes"
"$CLI" config set remote.endpoint "$ENDPOINT" >/dev/null
run remote dispatch "$JOB"
check "a dispatch without approval is refused" \
  "$(dbq "SELECT status FROM remote_jobs WHERE id = '$JOB'")" "refused"
check "and says which approval is missing" \
  "$(dbq "SELECT refusal FROM remote_jobs WHERE id = '$JOB'" | grep -c 'require_approval')" "1"
check "the refusal is an attempt row" \
  "$(dbq "SELECT COUNT(*) FROM remote_attempts WHERE job_id = '$JOB' AND action = 'dispatch' AND status = 'refused'")" "1"
"$CLI" remote approve "$JOB" >/dev/null
check "the approval is on the job" \
  "$(dbq "SELECT approved_by FROM remote_jobs WHERE id = '$JOB'")" "user:user"
check "a dispatch with the switch off is still refused" \
  "$("$CLI" remote dispatch "$JOB" >"$WORK/off.out" 2>&1; echo $?)" "3"
check "and it names the switch" \
  "$(grep -q 'remote compute is off' "$WORK/off.out" && echo yes)" "yes"
check "no dispatch succeeded while the switch was off" \
  "$(dbq "SELECT COUNT(*) FROM remote_attempts WHERE job_id = '$JOB' AND action = 'dispatch' AND status = 'ok'")" "0"

say "a dispatch to a port nobody is listening on is a row, not a crash"
"$CLI" config set remote.enabled true >/dev/null
DEAD_JOB="$("$CLI" --json remote export "$DS" --order 2 --seed 6 | jq_ "d['id']")"
"$CLI" remote approve "$DEAD_JOB" >/dev/null
"$CLI" remote dispatch "$DEAD_JOB" --endpoint "http://127.0.0.1:$DEAD_PORT" >"$WORK/dead.out" 2>&1
check "an unreachable endpoint exits 3" "$?" "3"
check "the job is failed, not verified" \
  "$(dbq "SELECT status FROM remote_jobs WHERE id = '$DEAD_JOB'")" "failed"
check "the failed attempt is in the log" \
  "$(dbq "SELECT COUNT(*) FROM remote_attempts WHERE job_id = '$DEAD_JOB' AND status = 'failed'")" "1"
check "and the error is stored, not printed at the user" \
  "$(dbq "SELECT COUNT(*) FROM remote_jobs WHERE id = '$DEAD_JOB' AND error IS NOT NULL")" "1"

say "a worker checks a bundle against itself before it computes anything"
"$CLI" remote worker --port "$WPORT" --name acceptance-box >"$WORK/worker.log" 2>&1 &
WORKER_PID=$!
check "the worker is up and says which protocol it speaks" \
  "$(wait_for_port "$WPORT" && curl -s "http://127.0.0.1:$WPORT/health" | jq_ "d['protocol']")" "archx-remote/1"
check "the worker is a separate process with no database" \
  "$(grep -c 'archx worker acceptance-box' "$WORK/worker.log")" "1"

say "an approved bundle is dispatched, computed, collected and verified"
SENT="$("$CLI" --json remote dispatch "$JOB" | jq_ "d['id']")"
check "the dispatch is recorded against the endpoint" \
  "$(dbq "SELECT endpoint FROM remote_jobs WHERE id = '$JOB'")" "$ENDPOINT"
check "the worker's machine is recorded" \
  "$(dbq "SELECT machine FROM remote_jobs WHERE id = '$JOB'")" "acceptance-box"
check "the worker named its own job id" \
  "$(dbq "SELECT COUNT(*) FROM remote_jobs WHERE id = '$JOB' AND remote_job_id IS NOT NULL")" "1"
sleep 0.3
COLLECTED="$("$CLI" --json remote collect "$JOB")"
check "collecting exits 0 only when the hash agrees" "$?" "0"
check "the job is verified" "$(echo "$COLLECTED" | jq_ "d['status']")" "verified"
check "what the worker claimed and what this machine measured agree" \
  "$(echo "$COLLECTED" | jq_ "d['claimed_sha256'] == d['received_sha256']")" "True"
check "and the claim is not empty" "$(echo "$COLLECTED" | jq_ "len(d['claimed_sha256'])")" "64"
ARTIFACT_REL="$(echo "$COLLECTED" | jq_ "d['artifact_path']")"
check "the artifact is a file on disk" "$([ -f "$LAB/$ARTIFACT_REL" ] && echo yes)" "yes"
check "the file hashes to what was stored" \
  "$("$PY" -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$LAB/$ARTIFACT_REL")" \
  "$(echo "$COLLECTED" | jq_ "d['received_sha256']")"
check "a second verify still agrees" "$("$CLI" remote verify "$JOB" | grep -c 'still hashes')" "1"
check "the verification time is recorded" \
  "$(dbq "SELECT COUNT(*) FROM remote_jobs WHERE id = '$JOB' AND verified_at IS NOT NULL")" "1"

say "the numbers are a local run's numbers, because it is the same trainer"
LOCAL="$("$CLI" --json train run --method ngram --dataset "$DS" --order 2 --seed 5 --label-source record)"
LOCAL_ARTIFACT="$LAB/$(echo "$LOCAL" | jq_ "d['artifact_path']")"
REMOTE_TRAIN="$("$PY" -c "import json,sys; print(json.loads(sys.argv[1])['outputs']['metrics']['train']['perplexity'])" "$COLLECTED")"
LOCAL_TRAIN="$(echo "$LOCAL" | jq_ "d['metrics']['train']['perplexity']")"
check "the remote train perplexity equals the local one" "$REMOTE_TRAIN" "$LOCAL_TRAIN"
check "each split agrees exactly" \
  "$("$PY" -c "
import json,sys
remote = json.loads(sys.argv[1])['outputs']['metrics']
local = json.loads(sys.argv[2])['metrics']
print(all(remote[s][n] == v for s in local for n, v in local[s].items()))" "$COLLECTED" "$LOCAL")" "True"
# The counts and vocabulary are the model. A worker that trained something else would differ here
# even if it happened to report a similar number.
check "the artifact holds the same counts as the local run's" \
  "$("$PY" -c "
import json,sys
remote = json.load(open(sys.argv[1]))
local = json.load(open(sys.argv[2]))
print(remote['counts'] == local['counts'] and remote['vocab'] == local['vocab'] and remote['kind'] == 'ngram')" \
    "$LAB/$ARTIFACT_REL" "$LOCAL_ARTIFACT")" "True"
check "the worker says who computed it" \
  "$("$PY" -c "import json,sys; print(json.load(open(sys.argv[1]))['computed_by'])" "$LAB/$ARTIFACT_REL")" \
  "worker:acceptance-box"

say "a worker that misreports its hash produces a disagreement, not a result"
cat > "$WORK/liar.py" <<'PYEOF'
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ARTIFACT = {"kind": "ngram", "order": 2, "smoothing": 0.1, "vocab": ["x"], "counts": {"<s> x": {"x": 1}}}

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *args):
        pass
    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        self._send(200, {
            "protocol": "archx-remote/1", "machine": "liarbox", "job_id": "rj_worker_liar",
            "status": "completed", "artifact": ARTIFACT,
            "artifact_sha256": "0" * 64,
            "metrics": {"train": {"perplexity": 1.0}},
            "actual": {"records": 8, "seconds": 0.001},
        })
    def do_POST(self):
        self._send(200, {
            "protocol": "archx-remote/1", "machine": "liarbox",
            "job_id": "rj_worker_liar", "approved_by": "worker:liarbox", "status": "running",
        })

ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
PYEOF
"$PY" "$WORK/liar.py" "$LIE_PORT" >"$WORK/liar.log" 2>&1 &
LIE_PID=$!
wait_for_port "$LIE_PORT"
LIE_JOB="$("$CLI" --json remote export "$DS" --order 2 --seed 7 | jq_ "d['id']")"
"$CLI" remote approve "$LIE_JOB" >/dev/null
"$CLI" remote dispatch "$LIE_JOB" --endpoint "http://127.0.0.1:$LIE_PORT" >/dev/null
LIE_RESULT="$("$CLI" --json remote collect "$LIE_JOB")"
check "a claimed hash that does not match is not verified" \
  "$(echo "$LIE_RESULT" | jq_ "d['status']")" "received"
check "the two hashes are stored separately" \
  "$(echo "$LIE_RESULT" | jq_ "d['claimed_sha256'] != d['received_sha256']")" "True"
check "the note names both" \
  "$(echo "$LIE_RESULT" | jq_ "all(k in d['verify_note'] for k in ('claimed','hash to'))")" "True"
check "nothing wrote a verification time" \
  "$(dbq "SELECT COALESCE(verified_at, 'none') FROM remote_jobs WHERE id = '$LIE_JOB'")" "none"
check "the attempt is recorded as a mismatch" \
  "$(dbq "SELECT status FROM remote_attempts WHERE job_id = '$LIE_JOB' AND action = 'collect'")" "mismatch"
check "re-verifying cannot rescue it" "$("$CLI" remote verify "$LIE_JOB" >/dev/null 2>&1; echo $?)" "3"
check "and the job stays received" \
  "$(dbq "SELECT status FROM remote_jobs WHERE id = '$LIE_JOB'")" "received"
check "the stats count it as unverified" "$("$CLI" --json remote stats | jq_ "d['unverified']")" "1"

say "a worker speaking another protocol is refused by both names"
cat > "$WORK/old.py" <<'PYEOF'
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *args):
        pass
    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_POST(self):
        self._send(200, {"protocol": "archx-remote/0", "machine": "oldbox", "job_id": "rj_old",
                         "status": "running"})

ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
PYEOF
"$PY" "$WORK/old.py" "$OLD_PORT" >"$WORK/old.log" 2>&1 &
OLD_PID=$!
wait_for_port "$OLD_PORT"
OLD_JOB="$("$CLI" --json remote export "$DS" --order 2 --seed 8 | jq_ "d['id']")"
"$CLI" remote approve "$OLD_JOB" >/dev/null
"$CLI" remote dispatch "$OLD_JOB" --endpoint "http://127.0.0.1:$OLD_PORT" >"$WORK/old.out" 2>&1
check "a protocol mismatch exits 3" "$?" "3"
check "the job is refused, not dispatched" \
  "$(dbq "SELECT status FROM remote_jobs WHERE id = '$OLD_JOB'")" "refused"
check "and both versions are named" \
  "$(dbq "SELECT refusal FROM remote_jobs WHERE id = '$OLD_JOB'" | grep -c "archx-remote/0'")" "1"

say "a corpus edited after the build cannot become a bundle"
printf 'changed after the build\n' > "$LAB/corpus/python/file1.txt"
"$CLI" remote export "$DS" >"$WORK/drift.out" 2>&1
check "a drifted corpus exits 2" "$?" "2"
check "and the file is named with the reason" \
  "$(grep -c 'no longer hashes' "$WORK/drift.out")" "1"
check "no job was created for it" \
  "$(dbq "SELECT COUNT(*) FROM remote_jobs WHERE dataset_id = '$DS' AND status = 'draft'")" "0"
printf 'def function_1(x):\n    return x + 1\n' > "$LAB/corpus/python/file1.txt"
check "restoring the file makes the dataset verify again" \
  "$("$CLI" --json dataset verify "$DS" | jq_ "d['agrees']")" "True"

say "the page is a client of the same service, over a real socket"
"$CLI" gui serve --port "$PORT" --token "$TOKEN" --no-open >"$WORK/gui.log" 2>&1 &
GUI_PID=$!
for _ in $(seq 1 60); do
  [ "$(status_of "http://127.0.0.1:$PORT/api/status")" = "401" ] && break
  sleep 0.1
done
check "the remote route needs a token" "$(status_of "$BASE/api/remote/jobs")" "401"
check "with a token it answers" "$(status_of -H "X-Archx-Token: $TOKEN" "$BASE/api/remote/jobs")" "200"
check "an unknown job is a 404" \
  "$(status_of -H "X-Archx-Token: $TOKEN" "$BASE/api/remote/jobs/rj_nope")" "404"
check "an unknown status is a 400" \
  "$(status_of -H "X-Archx-Token: $TOKEN" "$BASE/api/remote/jobs?status=nonsense")" "400"
check "the page counts the same jobs the CLI does" \
  "$(get_json "$BASE/api/remote/jobs" | api_jsonq "d['stats']['jobs']")" \
  "$("$CLI" --json remote stats | jq_ "d['jobs']")"
GUI_JOB="$(post_json "$BASE/api/remote/export" "{\"dataset\":\"$DS\",\"order\":2}" | api_jsonq "d['id']")"
check "the page can write a bundle" "$(dbq "SELECT COUNT(*) FROM remote_jobs WHERE id = '$GUI_JOB'")" "1"
post_json "$BASE/api/remote/jobs/$GUI_JOB/approve" '{}' >/dev/null
check "and approve it" \
  "$(dbq "SELECT approved_by FROM remote_jobs WHERE id = '$GUI_JOB'")" "user:gui"
post_json "$BASE/api/remote/jobs/$GUI_JOB/dispatch" '{}' >/dev/null
check "and dispatch it to the configured endpoint" \
  "$(dbq "SELECT status FROM remote_jobs WHERE id = '$GUI_JOB'")" "dispatched"
sleep 0.3
post_json "$BASE/api/remote/jobs/$GUI_JOB/collect" '{}' >/dev/null
check "and collect a verified result" \
  "$(dbq "SELECT status FROM remote_jobs WHERE id = '$GUI_JOB'")" "verified"
check "the detail shows both hashes" \
  "$(get_json "$BASE/api/remote/jobs/$GUI_JOB" | api_jsonq "d['claimed_sha256'] == d['received_sha256']")" "True"

say "the record survives the process that wrote it"
check "every job is still there after five more processes" \
  "$(dbq "SELECT COUNT(*) FROM remote_jobs")" "5"
check "and the attempts were never overwritten" \
  "$(dbq "SELECT COUNT(DISTINCT action) FROM remote_attempts")" "3"

printf '\n'
if [ "$FAILURES" -eq 0 ]; then
  printf 'M37 acceptance: %d checks passed, 0 failed\n' "${#CHECKS[@]}"
else
  printf 'M37 acceptance: %d passed, %d failed\n' "$((${#CHECKS[@]} - FAILURES))" "$FAILURES"
  for line in "${CHECKS[@]}"; do case "$line" in FAIL*) printf '  %s\n' "$line";; esac; done
fi
exit "$([ "$FAILURES" -eq 0 ] && echo 0 || echo 1)"
