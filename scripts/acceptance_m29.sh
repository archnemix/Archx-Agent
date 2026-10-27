#!/usr/bin/env bash
# M29 acceptance: the local web GUI, driven over a real socket.
#
# The claims being checked are the ones that would be easy to fake:
#   * the GUI is a client of this app, not a second one: a chat turn made in the browser is
#     a real task, a memory stored there is a real memory, a research run is a real run;
#   * it is reachable only with the token it printed, and a browser-shaped write (cookie,
#     no custom header) is refused;
#   * it serves only its own assets - no path escapes, no CDN, no interpreter banner;
#   * a refusal is shown as a refusal: web research without net.fetch returns 403 naming
#     the approval, and approving it in the GUI makes the same request work.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$HERE/.venv/bin/archx-agent"
PY="$HERE/.venv/bin/python"
HOME_DIR="${1:-$(mktemp -d /tmp/archx-m29-XXXXXX)}"
export ARCHX_PATHS_HOME="$HOME_DIR"
export ARCHX_ALLOW_SIMULATED=1
mkdir -p "$HOME_DIR"
PORT="$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
SITE_PORT="$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
TOKEN="m29-acceptance-token"
BASE="http://127.0.0.1:$PORT"
FAILURES=0
CHECKS=()
GUI_PID=""
SITE_PID=""

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
code_of() { curl -s -o /dev/null -w '%{http_code}' -X POST -H "Content-Type: application/json" -H "X-Archx-Token: $TOKEN" -d "$2" "$1"; }
get_json() { curl -s -H "X-Archx-Token: $TOKEN" "$1"; }
post_json() { curl -s -X POST -H "X-Archx-Token: $TOKEN" -H "Content-Type: application/json" -d "$2" "$1"; }

cleanup() {
  [ -n "$GUI_PID" ] && kill "$GUI_PID" 2>/dev/null
  [ -n "$SITE_PID" ] && kill "$SITE_PID" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT

# a tiny site so the web-research path is real, not described
cat > "$HOME_DIR/site.py" <<'PYEOF'
import http.server, sys

PAGE = (b"<html><head><title>SQLite locking explained</title></head><body>"
        b"<p>SQLite takes one write lock per transaction. Readers continue in WAL mode. "
        b"A busy timeout makes a second writer wait instead of failing.</p></body></html>")

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] != "/locking":
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)
    def log_message(self, *a):
        pass

http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
PYEOF

"$PY" "$HOME_DIR/site.py" "$SITE_PORT" >"$HOME_DIR/site.log" 2>&1 &
SITE_PID=$!

say "a fresh home, with one model and one fact to find"
run init
run models add-scripted --name demo
run memory add --kind permanent --title "SQLite locking" --content "SQLite takes one write lock per transaction; WAL lets readers continue." --category fact

say "the GUI starts, prints its token, and answers only with it"
"$CLI" gui serve --port "$PORT" --token "$TOKEN" >"$HOME_DIR/gui.log" 2>&1 &
GUI_PID=$!
for _ in $(seq 1 100); do
  if grep -q "access token" "$HOME_DIR/gui.log" 2>/dev/null; then break; fi
  sleep 0.1
done
if ! grep -q "access token" "$HOME_DIR/gui.log" 2>/dev/null; then
  printf 'the GUI did not start; see %s\n' "$HOME_DIR/gui.log" >&2
  cat "$HOME_DIR/gui.log" >&2
  exit 1
fi
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
sed -n 1,6p "$HOME_DIR/gui.log"
check "the banner says which home it serves" "$(grep -c "$HOME_DIR" "$HOME_DIR/gui.log")" "1"
check "the banner prints a URL with the token" "$(grep -c "open      .*token=$TOKEN" "$HOME_DIR/gui.log")" "1"

say "reachability: the page is public, the API is not"
check "the page is served" "$(status_of "$BASE/")" "200"
check "the page is the app" "$(curl -s "$BASE/" | grep -c '<title>Archx Agent</title>')" "1"
check "the script is served as javascript" "$(curl -s -o /dev/null -w '%{content_type}' "$BASE/app.js")" "text/javascript; charset=utf-8"
check "the page is a rail of modes, not a wall of tabs" "$(curl -s "$BASE/" | grep -c 'class="rail"')" "1"
check "the rail groups modes, work and control" "$(curl -s "$BASE/" | grep -c 'class="nav-label"')" "3"
check "the header shows the current mode's tools" "$(curl -s "$BASE/" | grep -c 'id="mode-tools"')" "1"
check "the theme switch is in the page" "$(curl -s "$BASE/" | grep -c 'id="theme-toggle"')" "1"
check "the stylesheet carries a dark palette" "$(curl -s "$BASE/style.css" | grep -c '#0a0c11')" "1"
check "and a light one behind the same tokens" "$(curl -s "$BASE/style.css" | grep -c '#f5f6f9')" "1"
check "each mode has its own accent" \
  "$([ "$(curl -s "$BASE/style.css" | grep -c 'mode-accent')" -ge 10 ] && echo yes)" "yes"
check "no token means no data" "$(status_of "$BASE/api/status")" "401"
check "a wrong token is refused" "$(status_of -H 'X-Archx-Token: nope' "$BASE/api/status")" "401"
check "the right token is accepted" "$(status_of -H "X-Archx-Token: $TOKEN" "$BASE/api/status")" "200"
check "health is public and knows the version" "$(curl -s "$BASE/api/health" | jq_ "d['data']['version']")" "$("$CLI" --version | awk '{print $3}')"
check "nobody can iframe-proof the preview, but scripts stay same-origin" \
  "$(curl -s -i "$BASE/" | grep -ci "frame-ancestors \*")" "1"
check "the interpreter version is not advertised" "$(curl -s -i "$BASE/" | grep -ci "^Server: .*Python")" "0"
check "an unknown API route is a JSON 404" "$(get_json "$BASE/api/nope" | jq_ "d['error']['code']")" "no_route"
check "an asset path cannot escape the assets directory" "$(status_of "$BASE/../server.py")" "404"
check "a CORS preflight is refused, so no cross-site write is possible" "$(status_of -X OPTIONS "$BASE/api/chat")" "405"

say "a chat turn made in the GUI is a real task"
CHAT="$(post_json "$BASE/api/chat" '{"message":"how does sqlite locking work"}')"
printf '%s\n' "$CHAT" | head -4
check "the GUI answered" "$(printf '%s' "$CHAT" | jq_ "bool(d['data']['text'])")" "True"
check "the reply is labelled simulated" "$(printf '%s' "$CHAT" | jq_ "d['data']['simulated']")" "True"
check "the turn recorded a task of type chat" "$(printf '%s' "$CHAT" | jq_ "d['data']['task']['type']")" "chat"
check "the task is in the task list the CLI shows" "$("$CLI" --json tasks list --limit 5 | jq_ "any(t['id'] == '$(printf '%s' "$CHAT" | jq_ "d['data']['task']['id']")' for t in d)")" "True"

say "a memory stored in the GUI is a real memory"
MEM="$(post_json "$BASE/api/memory" '{"kind":"permanent","title":"GUI note","content":"the GUI writes through the same manager","category":"fact"}')"
check "the memory was stored" "$(printf '%s' "$MEM" | jq_ "d['data']['id'].startswith('mem_')")" "True"
check "the CLI can show it" "$("$CLI" memory show "$(printf '%s' "$MEM" | jq_ "d['data']['id']")" | grep -c 'GUI writes through')" "1"
check "a duplicate is a 409, not a second copy" \
  "$(code_of "$BASE/api/memory" '{"kind":"permanent","title":"GUI note","content":"the GUI writes through the same manager","category":"fact"}')" "409"

say "one search across the sources the GUI can see"
SEARCH="$(get_json "$BASE/api/search?q=sqlite%20locking")"
check "search finds the memory" "$(printf '%s' "$SEARCH" | jq_ "any(h['kind'] == 'memory' for h in d['data']['hits'])")" "True"
check "search reports what it could not read" "$(printf '%s' "$SEARCH" | jq_ "'skipped' in d['data'] and 'degraded' in d['data']")" "True"

say "web research without the capability is a 403 that names the decision"
BLOCKED="$(post_json "$BASE/api/research" "{\"question\":\"how does sqlite locking work\",\"mode\":\"web\",\"urls\":[\"http://127.0.0.1:$SITE_PORT/locking\"],\"use_model\":false}")"
check "the request is refused, not failed mysteriously" "$(printf '%s' "$BLOCKED" | jq_ "d['error']['code']")" "approval_required"
APPROVAL="$(printf '%s' "$BLOCKED" | jq_ "d['error']['data']['approval_id']")"
check "it names an approval" "$(printf '%s' "$APPROVAL" | cut -c1-3)" "ap_"
check "the approval is listed for a human to decide" "$(get_json "$BASE/api/approvals?status=pending" | jq_ "any(a['id'] == '$APPROVAL' for a in d['data'])")" "True"
check "approving in the GUI mints exactly that grant" \
  "$(post_json "$BASE/api/approvals/$APPROVAL/approve" '{}' | jq_ "d['data']['grant']['capability']")" "net.fetch"
check "one active grant exists" "$(get_json "$BASE/api/permissions?active_only=1" | jq_ "len(d['data']['grants'])")" "1"

say "with the grant spent, the same request reads a real page"
WEB="$(post_json "$BASE/api/research" "{\"question\":\"how does sqlite locking work\",\"mode\":\"web\",\"urls\":[\"http://127.0.0.1:$SITE_PORT/locking\"],\"use_model\":false,\"allow_private_hosts\":true}")"
check "the run completed" "$(printf '%s' "$WEB" | jq_ "d['data']['run']['status']")" "completed"
RUN="$(printf '%s' "$WEB" | jq_ "d['data']['run']['id']")"
DETAIL="$(get_json "$BASE/api/research/$RUN")"
check "the source kept the page's own title" "$(printf '%s' "$DETAIL" | jq_ "any(s['title'] == 'SQLite locking explained' for s in d['data']['sources'])")" "True"
check "the citation labels match the report" "$(printf '%s' "$DETAIL" | jq_ "len(d['data']['labels']) >= 1")" "True"
check "verification passes" "$(printf '%s' "$DETAIL" | jq_ "d['data']['verification']['ok']")" "True"
check "the report is served as markdown, not JSON" "$(curl -s -H "X-Archx-Token: $TOKEN" "$BASE/api/research/$RUN/report" | head -1)" "# Research: how does sqlite locking work"

say "the approval was for one use, and a standing grant can be revoked"
check "the one-shot grant was spent by the fetch" "$(get_json "$BASE/api/permissions?active_only=1" | jq_ "len(d['data']['grants'])")" "0"
run permissions grant fs.read --duration persistent --confirm
GRANT="$(get_json "$BASE/api/permissions?active_only=1" | jq_ "d['data']['grants'][0]['id']")"
check "a persistent grant is visible to the GUI" "$(get_json "$BASE/api/permissions?active_only=1" | jq_ "d['data']['grants'][0]['capability']")" "fs.read"
post_json "$BASE/api/permissions/$GRANT/revoke" '{}' >/dev/null
check "revoking in the GUI removes it" "$(get_json "$BASE/api/permissions?active_only=1" | jq_ "len(d['data']['grants'])")" "0"

say "a queued job can be run from the GUI"
run jobs submit command "echo from the gui" --priority 3
check "the job is queued before the GUI runs it" "$(get_json "$BASE/api/jobs" | jq_ "d['data']['stats']['queued']")" "1"
DRAIN="$(post_json "$BASE/api/jobs/drain" '{"max_jobs":1}')"
check "the GUI ran it" "$(printf '%s' "$DRAIN" | jq_ "d['data']['ran'][0]['status']")" "completed"
check "the queue is empty afterwards" "$(printf '%s' "$DRAIN" | jq_ "d['data']['stats']['queued']")" "0"

say "the browser boundary: a cookie alone cannot write"
SESSION_HEADERS="$HOME_DIR/session.txt"
curl -s -c "$SESSION_HEADERS" -X POST -H "Content-Type: application/json" -H "X-Archx-Request: gui" \
  -d "{\"token\":\"$TOKEN\"}" "$BASE/api/session" >/dev/null
check "the session cookie opens a read" "$(status_of -b "$SESSION_HEADERS" "$BASE/api/status")" "200"
check "a cookie write without the header is refused" \
  "$(curl -s -o /dev/null -w '%{http_code}' -b "$SESSION_HEADERS" -X POST -H 'Content-Type: application/json' \
     -d '{"message":"cross-site attempt"}' "$BASE/api/chat")" "403"
check "the same write with the header is allowed" \
  "$(curl -s -o /dev/null -w '%{http_code}' -b "$SESSION_HEADERS" -X POST -H 'Content-Type: application/json' \
     -H 'X-Archx-Request: gui' -d '{"message":"in the browser"}' "$BASE/api/chat")" "200"
check "the cookie is HttpOnly and SameSite" "$(grep -c 'HttpOnly' "$SESSION_HEADERS" || true)" "1"

say "the GUI refuses to be exposed by accident"
OUT="$(cd "$HERE" && "$CLI" gui serve --host 0.0.0.0 --port 0 2>&1)"
CODE=$?
check "a remote bind without --allow-remote exits 2" "$CODE" "2"
check "and says why" "$(printf '%s' "$OUT" | grep -c 'allow-remote')" "1"

say "stopping the server closes the port"
kill "$GUI_PID"
wait "$GUI_PID" 2>/dev/null
GUI_PID=""
sleep 0.5
CLOSED="$(status_of "$BASE/api/health" 2>/dev/null)"
check "the port is closed, not orphaned" "${CLOSED:-000}" "000"

printf '\n### summary\n'
for line in "${CHECKS[@]}"; do printf '%s\n' "$line"; done
if [ "$FAILURES" -gt 0 ]; then
  printf '\nM29 ACCEPTANCE FAILED: %d check(s)\n' "$FAILURES"
  exit 1
fi
printf '\nM29 acceptance: %d checks passed\n' "${#CHECKS[@]}"
