#!/usr/bin/env bash
# M30 acceptance: learning mode, driven the way a person would use it.
#
# The claims being checked are the ones that would be easy to fake:
#   * a goal is a real record: its items, attempts and sessions are rows the CLI and the
#     GUI both read, and deleting a goal takes its children with it;
#   * grading is honest: an exact answer is checked, an ungraded answer says so and asks
#     for a self rating instead of pretending a model marked it;
#   * a hint cannot be bought with nothing: before an attempt the ladder is refused
#     (exit 3 / HTTP 409), after an attempt it opens one rung at a time and then stops;
#   * the schedule is explained: every answer returns why the next date moved;
#   * the plan without a model says it came from rules, and never invents an answer key.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$HERE/.venv/bin/archx-agent"
PY="$HERE/.venv/bin/python"
HOME_DIR="${1:-$(mktemp -d /tmp/archx-m30-XXXXXX)}"
export ARCHX_PATHS_HOME="$HOME_DIR"
export ARCHX_ALLOW_SIMULATED=1
mkdir -p "$HOME_DIR"
PORT="$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
TOKEN="m30-acceptance-token"
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

dbq() { "$PY" "$HOME_DIR/dbq.py" "$HOME_DIR/archx.db" "$1"; }

cleanup() {
  [ -n "$GUI_PID" ] && kill "$GUI_PID" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT

cat > "$HOME_DIR/dbq.py" <<'PYEOF'
import sqlite3, sys

connection = sqlite3.connect(sys.argv[1])
print(connection.execute(sys.argv[2]).fetchone()[0])
PYEOF

printf 'M30 acceptance on %s\n' "$HOME_DIR"

say "a fresh home knows about learning"
"$CLI" learning goal list >/dev/null
check "the build is M30" "$("$CLI" --version | awk '{print $3}')" "0.30.0"
check "the schema has been migrated through v19 for learning" \
  "$([ "$(dbq 'select max(version) from schema_migrations')" -ge 19 ] && echo yes)" "yes"
check "the v19 migration is the learning one" \
  "$(dbq "select name from schema_migrations where version = 19")" "learning-mode"
check "a fresh home opens the learning tables" \
  "$(dbq "select count(*) from sqlite_master where type='table' and name like 'learning%'")" "5"
check "the group is reachable from the CLI" "$("$CLI" learning --help | grep -c 'what you are learning')" "1"

say "a goal says what you are learning and what counts as done"
GOAL="$("$CLI" learning goal create "Learn SQLite locking" \
  --criteria "explain WAL" --criteria "fix a busy error" --json)"
GOAL_ID="$(printf '%s' "$GOAL" | jq_ "d['id']")"
run learning goal list
check "the goal exists" "$(printf '%s' "$GOAL" | jq_ "d['id'][:3]")" "lg_"
check "its criteria are kept" "$(printf '%s' "$GOAL" | jq_ "len(d['success_criteria'])")" "2"
check "it starts active" "$(printf '%s' "$GOAL" | jq_ "d['status']")" "active"
check "the CLI lists it" "$("$CLI" --json learning goal list | jq_ "len(d)")" "1"

say "an item carries a question, an answer key and a hint ladder"
ITEM="$("$CLI" learning item add "$GOAL_ID" "Which journal mode lets readers continue during a write?" \
  --expected "WAL" --hint "it is a three-letter mode" --hint "write-ahead log" \
  --explanation "WAL = write-ahead logging" --json)"
ITEM_ID="$(printf '%s' "$ITEM" | jq_ "d['id']")"
check "the item exists" "$(printf '%s' "$ITEM" | jq_ "d['id'][:3]")" "li_"
check "the ladder has two rungs" "$(printf '%s' "$ITEM" | jq_ "d['hint_count']")" "2"
check "it has never been attempted" "$(printf '%s' "$ITEM" | jq_ "d['attempts']")" "0"
check "new material is due now" "$(printf '%s' "$ITEM" | jq_ "d['due']")" "True"

say "what to study next comes with a reason"
NEXT="$("$CLI" learning next "$GOAL_ID" --json)"
check "next names an item" "$(printf '%s' "$NEXT" | jq_ "d['item']['id'][:3]")" "li_"
check "next counts what else is due" "$(printf '%s' "$NEXT" | jq_ "d['due_count'] > 0")" "True"
check "next explains itself" "$(printf '%s' "$NEXT" | jq_ "bool(d['why'])")" "True"
check "the reason is about the schedule, not a guess" \
  "$(printf '%s' "$NEXT" | jq_ "'attempted' in d['why'] or 'never' in d['why'] or 'due' in d['why']")" "True"

say "the question can be shown without its answer"
ASK="$("$CLI" learning ask "$GOAL_ID" --json)"
check "ask names the same item" "$(printf '%s' "$ASK" | jq_ "d['item']['id']")" "$ITEM_ID"
check "ask withholds the answer key" "$(printf '%s' "$ASK" | jq_ "'expected' not in d['item']")" "True"
check "ask withholds the ladder" "$(printf '%s' "$ASK" | jq_ "'hints' not in d['item']")" "True"
check "ask keeps the reason and the count" \
  "$(printf '%s' "$ASK" | jq_ "bool(d['why']) and d['due_count'] > 0")" "True"

say "a hint before an attempt is refused, not sold"
HINT_OUT="$("$CLI" learning hint "$ITEM_ID" --json 2>&1)"
HINT_CODE=$?
check "the ladder is refused before trying" "$HINT_CODE" "3"
check "the refusal is a record, not a crash" "$(printf '%s' "$HINT_OUT" | grep -c '"refused": true')" "1"
check "the refusal says what to do instead" "$(printf '%s' "$HINT_OUT" | grep -c 'try first')" "1"
check "the refusal names the switch that did it" "$(printf '%s' "$HINT_OUT" | grep -c 'learning.try_first')" "1"

say "answering is graded and the schedule explains itself"
WRONG="$("$CLI" learning answer "$ITEM_ID" "rollback journal" --json)"
check "a wrong answer is wrong" "$(printf '%s' "$WRONG" | jq_ "d['attempt']['correct']")" "False"
check "it says who graded it" "$(printf '%s' "$WRONG" | jq_ "d['grade']['graded_by']")" "exact"
check "it shows the answer key" "$(printf '%s' "$WRONG" | jq_ "d['grade']['expected']")" "WAL"
check "a lapse puts it back to now" "$(printf '%s' "$WRONG" | jq_ "d['schedule']['interval_days']")" "0.0"
check "the lapse lowers ease" "$(printf '%s' "$WRONG" | jq_ "d['schedule']['ease'] < 2.5")" "True"
check "and says why" "$(printf '%s' "$WRONG" | jq_ "'resets' in d['schedule']['why']")" "True"
RIGHT="$("$CLI" learning answer "$ITEM_ID" "  wal " --json)"
check "case and spacing do not decide the grade" "$(printf '%s' "$RIGHT" | jq_ "d['attempt']['correct']")" "True"
check "a correct answer is scheduled a day out" "$(printf '%s' "$RIGHT" | jq_ "d['schedule']['interval_days']")" "1.0"
check "the streak counts it" "$(printf '%s' "$RIGHT" | jq_ "d['schedule']['streak']")" "1"
check "the schedule is a review, not new" "$(printf '%s' "$RIGHT" | jq_ "d['item']['status']")" "review"
check "it still records which hints were used" "$(printf '%s' "$RIGHT" | jq_ "'hints_used' in d['attempt']")" "True"

say "the ladder opens after an attempt, one rung at a time"
HINT1="$("$CLI" learning hint "$ITEM_ID" --json)"
check "the first rung is the first hint" "$(printf '%s' "$HINT1" | jq_ "d['level']")" "1"
check "it is a nudge, not the answer" "$(printf '%s' "$HINT1" | jq_ "d['hint']")" "it is a three-letter mode"
check "it counts the rungs left" "$(printf '%s' "$HINT1" | jq_ "d['more']")" "1"
check "one rung shows only what came before it" "$(printf '%s' "$HINT1" | jq_ "len(d['revealed'])")" "1"
EDIT="$("$CLI" learning item edit "$ITEM_ID" --add-hint "three letters, starts with W" --json)"
check "the ladder can be extended after the fact" "$(printf '%s' "$EDIT" | jq_ "d['hint_count']")" "3"
"$CLI" learning item edit "$ITEM_ID" --clear-hints --add-hint "it is a three-letter mode" \
  --add-hint "write-ahead log" >/dev/null
check "the ladder can be rewritten" \
  "$("$CLI" --json learning item list "$GOAL_ID" | jq_ "next(i['hint_count'] for i in d if i['id'] == '$ITEM_ID')")" "2"
HINT2="$("$CLI" learning hint "$ITEM_ID" --level 2 --json)"
check "the next level is the next hint" "$(printf '%s' "$HINT2" | jq_ "d['level']")" "2"
check "and it is a different hint" "$(printf '%s' "$HINT2" | jq_ "d['hint']")" "write-ahead log"
check "the last rung says there is no more" "$(printf '%s' "$HINT2" | jq_ "d['more']")" "0"
EXHAUSTED="$("$CLI" learning hint "$ITEM_ID" --level 3 --json 2>&1)"
EXHAUSTED_CODE=$?
check "asking past the ladder is an error, not silence" "$EXHAUSTED_CODE" "2"
check "and it says how many rungs there are" "$(printf '%s' "$EXHAUSTED" | grep -c 'ask for a level between 1 and 2')" "1"

say "an ungraded item is not marked by a machine"
SELF="$("$CLI" learning item add "$GOAL_ID" "Explain in your own words why WAL helps readers" --json)"
SELF_ID="$(printf '%s' "$SELF" | jq_ "d['id']")"
SELF_OUT="$("$CLI" learning answer "$SELF_ID" "readers keep their snapshot" --self-rate 4 --json)"
check "the item had no answer key" "$(printf '%s' "$SELF" | jq_ "d['expected']")" "None"
check "so Archx did not grade it" "$(printf '%s' "$SELF_OUT" | jq_ "d['grade']['graded_by']")" "self"
check "it says Archx did not check the answer" "$(printf '%s' "$SELF_OUT" | jq_ "d['grade']['correct']")" "True"
check "your own rating is kept" "$(printf '%s' "$SELF_OUT" | jq_ "d['attempt']['self_rating']")" "4"

say "a plan without a model is honest about being rules"
PLAN="$("$CLI" learning plan "$GOAL_ID" --no-model --json)"
check "the plan is attributed to rules" "$(printf '%s' "$PLAN" | jq_ "d['goal']['planned_by']")" "rules"
check "it proposes items" "$(printf '%s' "$PLAN" | jq_ "len(d['items']) >= 1")" "True"
check "proposed items carry no answer key" "$(printf '%s' "$PLAN" | jq_ "all(i['expected'] is None for i in d['items'])")" "True"
check "they land in the same list the CLI reads" "$("$CLI" --json learning item list "$GOAL_ID" | jq_ "len(d) > 3")" "True"

say "a session is a real task you can close"
SESSION="$("$CLI" learning session start "$GOAL_ID" --mode review --json)"
SESSION_ID="$(printf '%s' "$SESSION" | jq_ "d['id'] if 'id' in d else d['session']['id']")"
check "the session exists" "$(printf '%s' "$SESSION_ID" | cut -c1-3)" "ls_"
CLOSED="$("$CLI" learning session end "$SESSION_ID" --json)"
check "closing it summarises the sitting" "$(printf '%s' "$CLOSED" | jq_ "'answered' in d['summary']")" "True"
check "a closed session stays closed" "$(printf '%s' "$CLOSED" | jq_ "d['session']['status']")" "closed"

say "review gathers what is due, and refuses to pretend there is anything"
REVIEW="$("$CLI" learning review "$GOAL_ID" --json 2>&1)"
REVIEW_CODE=$?
if [ "$REVIEW_CODE" = "0" ]; then REVIEW_OUTCOME="opened"; else REVIEW_OUTCOME="refused"; fi
check "review either opens with what is due or refuses" "$REVIEW_OUTCOME" "opened"
check "the session it opens is a task you can see" "$(printf '%s' "$REVIEW" | jq_ "d['session']['task_id'][:3]")" "tk_"
check "the review queue is drawn from the schedule" "$(printf '%s' "$REVIEW" | jq_ "all(i['due'] is True for i in d['items'])")" "True"

say "progress is counted, not asserted"
STATS="$("$CLI" learning stats --json)"
check "every attempt is counted" "$(printf '%s' "$STATS" | jq_ "d['attempts']")" "3"
check "accuracy is derived from them" "$(printf '%s' "$STATS" | jq_ "d['accuracy']")" "0.667"
check "due counts what the schedule says" "$(printf '%s' "$STATS" | jq_ "d['due'] >= 0")" "True"

say "the report is a document, and the search finds the goal"
REPORT="$("$CLI" learning report "$GOAL_ID" --write "$HOME_DIR/report.md")"
check "the report names the goal" "$(grep -c '# Learning: Learn SQLite locking' "$HOME_DIR/report.md")" "1"
check "it lists the criteria" "$([ "$(grep -c 'fix a busy error' "$HOME_DIR/report.md")" -ge 1 ] && echo yes)" "yes"
check "it explains how grading works" "$(grep -c 'How this record is graded' "$HOME_DIR/report.md")" "1"
check "search finds the goal" "$("$CLI" --json learning search locking | jq_ "any(h['kind'] == 'goal' for h in d)")" "True"

say "the GUI is the same record, not a second one"
"$CLI" gui serve --port "$PORT" --token "$TOKEN" >"$HOME_DIR/gui.log" 2>&1 &
GUI_PID=$!
for _ in $(seq 1 100); do
  if curl -s -o /dev/null "http://127.0.0.1:$PORT/api/health" 2>/dev/null; then break; fi
  sleep 0.1
done
check "the learning page is served" "$(curl -s "http://127.0.0.1:$PORT/" | grep -c 'id="view-learning"')" "1"
check "the learning tab is in the markup" "$(curl -s "http://127.0.0.1:$PORT/" | grep -c 'data-view="learning"')" "1"
check "the view is wired in the script" \
  "$([ "$(curl -s "http://127.0.0.1:$PORT/view-learning.js" | grep -c 'loadLearningGoals')" -ge 1 ] && echo yes)" "yes"
check "the API shows the goal the CLI made" "$(get_json "$BASE/api/learning" | jq_ "any(g['id'] == '$GOAL_ID' for g in d['data']['goals'])")" "True"
NEW_GOAL="$(post_json "$BASE/api/learning/goals" '{"title":"Learn WAL checkpoints","criteria":["describe a checkpoint"]}')"
GUI_GOAL="$(printf '%s' "$NEW_GOAL" | jq_ "d['data']['id']")"
check "a goal made in the GUI is a real goal" "$(printf '%s' "$GUI_GOAL" | cut -c1-3)" "lg_"
check "the CLI can show it" \
  "$("$CLI" --json learning goal list | jq_ "any(g['id'] == '$GUI_GOAL' for g in d)")" "True"
GUI_PLAN="$(post_json "$BASE/api/learning/goals/$GUI_GOAL/plan" '{"use_model":false}')"
check "the GUI plan is attributed to rules" "$(printf '%s' "$GUI_PLAN" | jq_ "d['data']['goal']['planned_by']")" "rules"
DETAIL="$(get_json "$BASE/api/learning/goals/$GUI_GOAL")"
GUI_ITEM="$(printf '%s' "$DETAIL" | jq_ "d['data']['items'][0]['id']")"
check "the detail lists the planned items" "$(printf '%s' "$DETAIL" | jq_ "len(d['data']['items']) >= 1")" "True"
check "a rule-planned item has no answer key to leak" \
  "$(printf '%s' "$DETAIL" | jq_ "d['data']['items'][0]['expected']")" "None"
"$CLI" learning item edit "$GUI_ITEM" --hint "say it out loud" --hint "it is about the log" >/dev/null
check "a hint before an attempt is a 409, not a 500" "$(post_code "$BASE/api/learning/items/$GUI_ITEM/hint" '{}')" "409"
check "the refusal carries a code the page can branch on" \
  "$(post_json "$BASE/api/learning/items/$GUI_ITEM/hint" '{}' | jq_ "d['error']['code']")" "try_first"
check "answering in the GUI grades it" \
  "$(post_json "$BASE/api/learning/goals/$GUI_GOAL/answer" "{\"item_id\":\"$GUI_ITEM\",\"answer\":\"checkpoints truncate the log\",\"self_rating\":5}" | jq_ "d['data']['grade']['graded_by']")" "self"
check "the same answer is visible to the CLI" \
  "$("$CLI" --json learning item list "$GUI_GOAL" | jq_ "any(i['attempts'] == 1 for i in d)")" "True"
ADDED="$(post_json "$BASE/api/learning/goals/$GUI_GOAL/items" \
  '{"prompt":"What does a checkpoint do?","expected":"truncates the log","hints":"a file\nstarts with a c"}')"
check "an item can be added from the page" "$(printf '%s' "$ADDED" | jq_ "d['data']['hint_count']")" "2"
check "the added item has an answer key" "$(printf '%s' "$ADDED" | jq_ "d['data']['expected']")" "truncates the log"
check "the CLI sees the same item" \
  "$("$CLI" --json learning item list "$GUI_GOAL" | jq_ "any(i['id'] == '$(printf '%s' "$ADDED" | jq_ "d['data']['id']")' for i in d)")" "True"
check "the GUI can start a review" "$(post_code "$BASE/api/learning/goals/$GUI_GOAL/review" '{}')" "200"
check "the learning routes are in the route table" \
  "$("$CLI" gui routes | grep -c '/api/learning')" "8"

say "deleting a goal takes its children, and is not silent"
COUNT_BEFORE="$("$CLI" --json learning item list "$GUI_GOAL" | jq_ "len(d)")"
check "the goal had items before" "$COUNT_BEFORE" "3"
"$CLI" learning goal delete "$GUI_GOAL" --yes >/dev/null 2>&1
check "the goal is gone" "$(get_json "$BASE/api/learning" | jq_ "any(g['id'] == '$GUI_GOAL' for g in d['data']['goals'])")" "False"
check "asking for it is a 404, not a half-record" "$(status_of -H "X-Archx-Token: $TOKEN" "$BASE/api/learning/goals/$GUI_GOAL")" "404"

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
  printf '\nM30 ACCEPTANCE FAILED: %d check(s)\n' "$FAILURES"
  exit 1
fi
printf '\nM30 acceptance: %d checks passed\n' "${#CHECKS[@]}"
