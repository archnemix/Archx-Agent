#!/usr/bin/env bash
# M28 acceptance: Researcher Mode in the installed app.
#
# The claims being checked are the ones that would be easy to fake:
#   * a plan that says where it came from, and a report that cites what it read;
#   * real HTTP pages read through net.fetch, which is a capability - the first attempt is
#     refused, creates no grant, and prints the command that would grant it;
#   * a page that cannot be read is recorded, not omitted;
#   * a question with no evidence produces "I found no evidence" and exit 3, never prose;
#   * the report is a real file, attached to a real task, and every citation resolves.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$HERE/.venv/bin/archx-agent"
PY="$HERE/.venv/bin/python"
HOME_DIR="${1:-$(mktemp -d /tmp/archx-m28-XXXXXX)}"
export ARCHX_PATHS_HOME="$HOME_DIR"
export ARCHX_ALLOW_SIMULATED=1
mkdir -p "$HOME_DIR"
PORT="$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
WORK="$HOME_DIR/workspace"
FAILURES=0
CHECKS=()

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

cat > "$HOME_DIR/site.py" <<'PYEOF'
import http.server, socketserver, sys

PAGES = {
    "/locking": b"""<html><head><title>SQLite locking explained</title></head><body>
<h1>Locking</h1><p>SQLite takes one write lock per transaction. Readers continue in WAL mode.</p>
<p>A busy timeout makes a second writer wait instead of failing immediately, and a retry loop
handles SQLITE_BUSY. Locking errors commonly appear under heavy concurrent writes.</p>
</body></html>""",
    "/wal": b"""<html><head><title>WAL limits</title></head><body>
<p>WAL does not survive a process crash; the -wal file must be checkpointed. What commonly goes
wrong is a stale reader holding a snapshot while the writer grows the WAL file.</p>
</body></html>""",
    "/binary": b"\x00\x01\x02 not text",
}

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGES.get(self.path.split("?")[0])
        if body is None:
            self.send_response(404); self.end_headers(); return
        ctype = "application/octet-stream" if self.path.startswith("/binary") else "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass

socketserver.TCPServer.allow_reuse_address = True
srv = socketserver.TCPServer(("127.0.0.1", int(sys.argv[1])), H)
print("ready", flush=True)
srv.serve_forever()
PYEOF

"$PY" "$HOME_DIR/site.py" "$PORT" > "$HOME_DIR/site.log" 2>&1 &
SERVER_PID=$!
cleanup() { kill "$SERVER_PID" 2>/dev/null; wait "$SERVER_PID" 2>/dev/null; }
trap cleanup EXIT
for _ in $(seq 1 100); do
  if grep -q ready "$HOME_DIR/site.log" 2>/dev/null; then break; fi
  sleep 0.1
done
if ! grep -q ready "$HOME_DIR/site.log" 2>/dev/null; then
  printf 'the test site did not start; see %s\n' "$HOME_DIR/site.log" >&2
  exit 1
fi
BASE="http://127.0.0.1:$PORT"

say "home"; echo "$HOME_DIR"; echo "site $BASE"
run init
mkdir -p "$WORK/docs"
printf 'SQLite locking: a write transaction takes an exclusive lock. WAL mode allows readers to continue while a writer commits. A busy timeout makes a second writer wait instead of failing.\n' > "$WORK/docs/locking.md"
printf 'Unrelated notes about lunch, weather and the office plant.\n' > "$WORK/docs/notes.md"
run memory add --kind permanent --title "SQLite locking" --content "SQLite takes one write lock per transaction; WAL lets readers continue." --category fact

say "local research: the plan is stated, the evidence is cited, the report is a file"
run research run "how does sqlite locking work" --no-model --subquestion "how does a write transaction lock" --subquestion "what happens when a second writer arrives"
LOCAL_JSON=$("$CLI" --json research run "how does sqlite locking work" --no-model --subquestion "how does a write transaction lock")
printf '%s\n' "$LOCAL_JSON" | head -12
RUN=$(printf '%s' "$LOCAL_JSON" | jq_ "d['run']['id']")
check "the run completed" "$(printf '%s' "$LOCAL_JSON" | jq_ "d['run']['status']")" "completed"
check "coverage is computed, not assumed" "$(printf '%s' "$LOCAL_JSON" | jq_ "d['run']['coverage'] > 0")" "True"
RULES_JSON=$("$CLI" --json research run "how does sqlite locking work" --no-model)
check "a planned run says the plan came from rules" "$(printf '%s' "$RULES_JSON" | jq_ "d['run']['planned_by']")" "rules"
check "a directed run says the user framed it" "$(printf '%s' "$LOCAL_JSON" | jq_ "d['run']['planned_by']")" "user"
check "every citation resolves" "$(printf '%s' "$LOCAL_JSON" | jq_ "d['verification']['ok']")" "True"
check "the report file exists" "$(test -f "$(printf '%s' "$LOCAL_JSON" | jq_ "d['report_path']")" && echo yes)" "yes"
check "the report names its sources" "$(grep -c '^## Sources' "$(printf '%s' "$LOCAL_JSON" | jq_ "d['report_path']")")" "1"
check "the limitations say no model judged stance" "$("$CLI" --json research show "$RUN" | jq_ "any('no model was configured' in note for note in d['limitations'])")" "True"
check "a task of type research was recorded" "$("$CLI" --json tasks list --limit 5 | jq_ "any(t['type'] == 'research' for t in d)")" "True"

say "a question with no evidence refuses to invent an answer"
run research run "what is the airspeed of an unladen swallow" --no-model --subquestion "zeppelin schematics"
set +e
EMPTY=$("$CLI" --json research run "what is the airspeed of an unladen swallow" --no-model --subquestion "zeppelin schematics")
EMPTY_CODE=$?
check "the run is incomplete, not completed" "$(printf '%s' "$EMPTY" | jq_ "d['run']['status']")" "incomplete"
check "the report opens with 'I found no evidence'" "$(printf '%s' "$EMPTY" | jq_ "'I found no evidence' in d['run']['report']")" "True"
check "and the command exits 3" "$EMPTY_CODE" "3"

say "web research is a capability: refused first, no grant created"
run research run "how does sqlite locking work" --mode web --url "$BASE/locking" --allow-private-hosts --no-model
set +e
BLOCKED=$("$CLI" --json research run "how does sqlite locking work" --mode web --url "$BASE/locking" --allow-private-hosts --no-model)
BLOCKED_CODE=$?
printf '%s\n' "$BLOCKED" | head -8
check "the run was blocked, not failed silently" "$(printf '%s' "$BLOCKED" | jq_ "d['blocked']")" "True"
check "and the command exits 4" "$BLOCKED_CODE" "4"
check "it names an approval to decide" "$(printf '%s' "$BLOCKED" | jq_ "d['approval_id'].startswith('ap_')")" "True"
check "no net.fetch grant exists yet" "$("$CLI" --json permissions list | jq_ "sum(1 for g in d if g['capability']=='net.fetch')")" "0"

say "the user grants it, then real pages are read and hashed"
run permissions grant net.fetch --duration persistent --confirm
WEB=$("$CLI" --json research run "how does sqlite locking work" --mode web --url "$BASE/locking" --url "$BASE/wal" --url "$BASE/missing" --url "$BASE/binary" --allow-private-hosts --no-model)
WEBRUN=$(printf '%s' "$WEB" | jq_ "d['run']['id']")
printf '%s\n' "$WEB" | head -12
check "the web run completed" "$(printf '%s' "$WEB" | jq_ "d['run']['status']")" "completed"
check "two pages were usable" "$(printf '%s' "$WEB" | jq_ "d['run']['evidence_count'] == 2")" "True"
"$CLI" research sources "$WEBRUN"
check "the 404 was recorded as a failed source" "$("$CLI" --json research sources "$WEBRUN" | jq_ "any(s['status']=='failed' and '404' in (s['error'] or '') for s in d)")" "True"
check "the binary page was refused for its type" "$("$CLI" --json research sources "$WEBRUN" | jq_ "any(s['status']=='failed' and 'not a text document' in (s['error'] or '') for s in d)")" "True"
check "read pages carry a checksum" "$("$CLI" --json research sources "$WEBRUN" | jq_ "all(bool(s['checksum']) for s in d if s['status']=='fetched')")" "True"
check "the title was read from the page" "$("$CLI" --json research sources "$WEBRUN" | jq_ "any(s['title']=='SQLite locking explained' for s in d)")" "True"
check "the citations still resolve" "$("$CLI" --json research verify "$WEBRUN" | jq_ "d['ok']")" "True"

say "private addresses stay blocked without the explicit flag, even with the grant"
PRIVATE=$("$CLI" --json research run "how does sqlite locking work" --mode web --url "$BASE/locking" --no-model; true)
check "the run failed rather than reaching loopback" "$(printf '%s' "$PRIVATE" | jq_ "d['run']['status']")" "incomplete"
check "and the reason is the private-address rule" "$("$CLI" --json research sources "$(printf '%s' "$PRIVATE" | jq_ "d['run']['id']")" | jq_ "any('private or local' in (s['error'] or '') for s in d)")" "True"

say "the same question can be queued as a job"
JOB=$("$CLI" --json jobs submit research "how does sqlite locking work" --no-model --job-json '{"subquestions": ["how does a write transaction lock"]}')
echo "$JOB" | head -6
check "submitting queues, it does not run" "$(printf '%s' "$JOB" | jq_ "d['status']")" "queued"
"$CLI" jobs run --once --kind research; echo "[exit $?]"
JOB_ID=$(printf '%s' "$JOB" | jq_ "d['id']")
check "the job completed" "$("$CLI" --json jobs show "$JOB_ID" | jq_ "d['status']")" "completed"
check "the job is linked to the research task" "$("$CLI" --json jobs show "$JOB_ID" | jq_ "bool(d['task_id'])")" "True"

say "reports are searchable and deletable"
run research list
check "search finds the run" "$("$CLI" --json research search locking | jq_ "len(d) >= 1")" "True"
run research delete "$RUN" --yes
check "a deleted run is gone" "$("$CLI" --json research list | jq_ "all(r['id'] != '$RUN' for r in d)")" "True"

say "summary"
printf '%s\n' "${CHECKS[@]}"
if [ "$FAILURES" -gt 0 ]; then
  printf '\nM28 ACCEPTANCE FAILED: %s check(s)\n' "$FAILURES"
  exit 1
fi
printf '\nM28 acceptance: %s checks passed\n' "${#CHECKS[@]}"
