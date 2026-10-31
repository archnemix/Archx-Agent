#!/usr/bin/env bash
# M27 acceptance: Simple Mode and unified search in the installed app.
#
# The interesting property is not "it answers" but "it says what it did, searches what
# actually exists, and refuses to grant itself anything". So the script asks the same
# question through search and through Simple Mode, runs every intent for real, and makes
# Simple Mode print an approval command which it then executes - twice, to show the
# refusal was the only reason the first attempt stopped.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$HERE/.venv/bin/archx-agent"
PY="$HERE/.venv/bin/python"
HOME_DIR="${1:-$(mktemp -d /tmp/archx-m27-XXXXXX)}"
export ARCHX_PATHS_HOME="$HOME_DIR"
export ARCHX_ALLOW_SIMULATED=1
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

say "home"; echo "$HOME_DIR"
run init
mkdir -p "$WORK/docs"
printf 'The database uses WAL and locks briefly during a write.\n' > "$WORK/docs/database.md"
printf 'Kafka partitions are ordered and replicated.\n' > "$WORK/docs/kafka.md"
printf 'unrelated notes about lunches\n' > "$WORK/lunch.md"
printf 'binary\x00data kafka\n' > "$WORK/blob.bin"

say "seed real data: memory, a conversation, a task, a workflow"
run models add-scripted --name sim
run memory add --kind permanent --title "Database locking" --content "SQLite locks once per write transaction; WAL keeps readers moving." --category fact
run memory add --kind permanent --title "Kafka partitions" --content "Partitions give ordering; replication gives durability." --category fact
run chat --message "the database locks during writes, what should I check" --model sim
cat > "$HOME_DIR/check.json" <<'JSON'
{"name": "database-check", "goal": "check the database notes",
 "steps": [{"kind": "note", "title": "look", "text": "database notes exist"}]}
JSON
run agent run-file "$HOME_DIR/check.json"

say "unified search finds memory, conversations, tasks, workflows and files"
run search "database"
run search "kafka" --kind memory
run search "kafka" --no-files
SEARCH_JSON=$("$CLI" --json search "database locks")
printf '%s\n' "$SEARCH_JSON" | head -20
check "search found memory and files" "$(printf '%s' "$SEARCH_JSON" | jq_ "'memory' in d['counts'] and 'file' in d['counts']")" "True"
check "search found the conversation" "$(printf '%s' "$SEARCH_JSON" | jq_ "d['counts'].get('conversation', 0) >= 1")" "True"
check "search found the task" "$(printf '%s' "$SEARCH_JSON" | jq_ "d['counts'].get('task', 0) >= 1")" "True"
check "search found the workflow" "$(printf '%s' "$SEARCH_JSON" | jq_ "d['counts'].get('workflow', 0) >= 1")" "True"
check "binary files were skipped" "$(printf '%s' "$SEARCH_JSON" | jq_ "all('blob.bin' not in h['title'] for h in d['hits'])")" "True"
check "--no-files is reported as skipped" "$("$CLI" --json search kafka --no-files | jq_ "'file' in d['skipped']")" "True"
check "memory search is honest about keyword-only" "$("$CLI" --json search kafka --kind memory | jq_ "any('keyword-only' in note for note in d['degraded'])")" "True"

say "Simple Mode: the search intent explains itself"
run simple ask "where did I write about database locks"
check "intent was search" "$("$CLI" --json simple ask "where did I write about database locks" | jq_ "d['intent']")" "search"
check "the result names its sources" "$("$CLI" --json simple ask "where did I write about database locks" | jq_ "d['data']['report']['total'] >= 2")" "True"

say "Simple Mode: remember, then recall"
run simple ask "remember that the staging key lives in vault"
run simple ask "always use metric units in examples"
check "the fact was stored as permanent" "$("$CLI" --json simple ask "remember that deploy windows are fridays" | jq_ "d['headline'].startswith('Stored as permanent')")" "True"
check "the preference was categorised" "$("$CLI" --json simple ask "always use UTC timestamps" | jq_ "d['data']['category']")" "preference"
run simple ask "recall staging"
check "recall finds it" "$("$CLI" simple ask "recall staging" | grep -c vault)" "1"
run simple ask "remember that the staging key lives in vault"

say "Simple Mode: status reads the app, it does not guess"
run simple status
check "status counts memory" "$("$CLI" --json simple status | jq_ "d['data']['memory']['total_active'] >= 4")" "True"
check "status counts the task history" "$("$CLI" --json simple status | jq_ "d['data']['tasks']['total'] >= 1")" "True"

say "Simple Mode: chat answers through the real chat service"
run simple ask "hello there"
check "chat used a model" "$("$CLI" --json simple ask "hello" | jq_ "bool(d['data']['model_id'])")" "True"
check "the simulated reply is labelled" "$("$CLI" --json simple ask "hello" | jq_ "d['simulated']")" "True"

say "Simple Mode: a workflow that needs a permission stops, prints the command, and grants nothing"
run simple ask "run template summarise-file path=docs/database.md"
DENIED=$("$CLI" --json simple ask "run template summarise-file path=docs/database.md")
printf '%s\n' "$DENIED" | head -12
check "it refused instead of escalating" "$(printf '%s' "$DENIED" | jq_ "d['intent'] == 'workflow' and 'permission' in d['headline']")" "True"
check "it printed an approval command" "$(printf '%s' "$DENIED" | jq_ "d['next_step'].startswith('archx-agent approvals approve')")" "True"
check "no grant was created" "$("$CLI" --json permissions list | jq_ "sum(1 for g in d if g['capability']=='fs.read')")" "0"

say "the printed command works, and the same request then succeeds exactly once"
APPROVAL=$(printf '%s' "$DENIED" | jq_ "d['data']['approval_id']")
echo "approval: $APPROVAL"
run approvals approve "$APPROVAL"
check "approving created the grant the user asked for" "$("$CLI" --json permissions list | jq_ "sum(1 for g in d if g['capability']=='fs.read' and g['active'])")" "1"
APPROVED=$("$CLI" --json simple ask "run template summarise-file path=docs/database.md")
check "the approved run completed" "$(printf '%s' "$APPROVED" | jq_ "d['data']['status']")" "completed"
check "a one-shot grant is spent, so the next request asks again" "$("$CLI" --json simple ask "run template summarise-file path=docs/database.md" | jq_ "d['intent'] == 'workflow' and bool(d['data'].get('approval_id'))")" "True"
check "and no long-lived grant was left behind" "$("$CLI" --json permissions list | jq_ "sum(1 for g in d if g['capability']=='fs.read' and g['active'])")" "0"

say "the chat loop: two answers, then a clean exit"
printf 'where did I write about kafka\nstatus\n/help\n/quit\n' | "$CLI" simple
echo "(loop exited)"

say "everything is still traceable afterwards"
run trace list --limit 5
run tasks list --limit 5
run db check

say "summary"
printf '%s\n' "${CHECKS[@]}"
if [ "$FAILURES" -gt 0 ]; then
  printf '\nM27 ACCEPTANCE FAILED: %s check(s)\n' "$FAILURES"
  exit 1
fi
printf '\nM27 acceptance: %s checks passed\n' "${#CHECKS[@]}"
