#!/usr/bin/env bash
# Build the demo home the live preview serves.
#
# The preview is a real workspace, not a mock: everything below goes through the same CLI
# the user would run, so every panel in the GUI has something honest to show. Re-running this
# script is safe - it never deletes an existing home, it only fills the gaps the preview
# needs, and it says what it skipped.
#
#   ./scripts/seed_demo.sh [home]        (default: ~/.archx-demo)
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$HERE/.venv/bin/archx-agent"
PY="$HERE/.venv/bin/python"
HOME_DIR="${1:-$HOME/.archx-demo}"
export ARCHX_PATHS_HOME="$HOME_DIR"
export ARCHX_ALLOW_SIMULATED=1

say() { printf '\n### %s\n' "$*"; }
jq_() { "$PY" -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

if [ ! -x "$CLI" ]; then
  printf 'no CLI at %s - run ./scripts/bootstrap.sh first\n' "$CLI" >&2
  exit 1
fi

mkdir -p "$HOME_DIR"
say "workspace"
"$CLI" init >/dev/null 2>&1 || true
printf 'home %s\n' "$HOME_DIR"
"$CLI" --version

# ---------------------------------------------------------------- model
say "a model the router can actually reach"
if "$CLI" --json models list 2>/dev/null | "$PY" -c 'import json,sys; sys.exit(0 if json.load(sys.stdin) else 1)'; then
  printf 'a model is already registered; leaving the catalogue alone\n'
else
  # The scripted runtime is the honest stand-in here: no weights are reachable from this
  # environment, and every reply it produces is labelled "simulated" in the GUI.
  "$CLI" models add-scripted --name "scripted (demo)" 2>&1 | tail -2
fi

# ---------------------------------------------------------------- chat
say "a conversation with a real task behind it"
CONV_COUNT="$("$CLI" --json conv list 2>/dev/null | jq_ "len(d)")"
if [ "${CONV_COUNT:-0}" = "0" ]; then
  "$CLI" chat --message "how does sqlite locking work, and what does WAL change?" 2>&1 | head -4
  # continue the same conversation, so the panel shows a thread rather than two orphans
  THREAD="$("$CLI" --json conv list 2>/dev/null | jq_ "d[0]['id'] if d else ''")"
  if [ -n "$THREAD" ]; then
    "$CLI" chat --conversation "$THREAD" \
      --message "what happens to readers when a writer holds the lock?" 2>&1 | head -2
  fi
else
  printf '%s conversation(s) already exist; not adding more\n' "$CONV_COUNT"
fi

# ---------------------------------------------------------------- memory
say "memories across the kinds the GUI offers"
add_memory() {
  local kind="$1" title="$2" content="$3" category="$4"
  shift 4
  if "$CLI" memory add --kind "$kind" --title "$title" --content "$content" \
       --category "$category" "$@" >/dev/null 2>&1; then
    printf 'stored  %s  %s\n' "$kind" "$title"
  else
    printf 'skipped %s  %s (already stored, or refused)\n' "$kind" "$title"
  fi
}
# `active` memories must be scoped to a conversation or task, so the demo uses the kinds
# that stand on their own: permanent (global) and learning (learner scope).
add_memory permanent "Local-first by default" \
  "Archx runs against a local model and keeps every record in this home unless a cloud provider is explicitly consented to." fact
add_memory permanent "The preview runs on the demo home" \
  "ARCHX_PATHS_HOME=$HOME_DIR, so nothing here touches the real ~/.archx; scripts/seed_demo.sh rebuilds it." fact
add_memory learning "Spaced repetition beats cramming" \
  "Wrong answers come back immediately and mastery needs a streak plus a real interval; that asymmetry is the point." finding \
  --topic "spaced repetition"

# ---------------------------------------------------------------- learning
say "a learning goal with items, a ladder and an attempt history"
GOALS="$("$CLI" --json learning goal list 2>/dev/null | jq_ "len(d)")"
if [ "${GOALS:-0}" = "0" ]; then
  GOAL="$("$CLI" learning goal create "SQLite locking and WAL" \
    --criteria "explain how a write lock works" \
    --criteria "fix a busy timeout error" --level intermediate --json | jq_ "d['id']")"
  printf 'goal %s\n' "$GOAL"
  ITEM="$("$CLI" learning item add "$GOAL" \
    "Which journal mode lets readers continue during a write?" \
    --expected "WAL" --hint "three letters" --hint "write-ahead log" \
    --explanation "WAL keeps a separate log; readers keep their snapshot." --json | jq_ "d['id']")"
  "$CLI" learning item add "$GOAL" \
    "Which pragma makes a second writer wait instead of failing?" \
    --expected "busy_timeout" --hint "a pragma" --hint "it is about waiting" >/dev/null
  "$CLI" learning plan "$GOAL" --no-model >/dev/null
  # one wrong answer and one right one, so the schedule panel shows both states
  "$CLI" learning answer "$ITEM" "rollback journal" >/dev/null 2>&1
  "$CLI" learning answer "$ITEM" "wal" >/dev/null 2>&1
  "$CLI" learning stats
else
  printf '%s goal(s) already exist; not adding more\n' "$GOALS"
fi

# ---------------------------------------------------------------- research
say "one research run with sources, so the panel is not an empty form"
RUNS="$("$CLI" --json research list --limit 1 2>/dev/null | jq_ "len(d)")"
if [ "${RUNS:-0}" = "0" ]; then
  # a real local run over the memories above: no model call, no network, and the run's own
  # status stays whatever the evidence gave it
  "$CLI" research run "how does sqlite locking work, and what does WAL change?" --no-model 2>&1 \
    | sed -n 1,4p
else
  printf '%s research run(s) already exist; not adding more\n' "$RUNS"
fi

# ---------------------------------------------------------------- queue
say "one queued job so the Jobs panel is not empty"
QUEUED="$("$CLI" --json jobs list --status queued 2>/dev/null | jq_ "len(d)" 2>/dev/null || echo 0)"
if [ "${QUEUED:-0}" = "0" ]; then
  "$CLI" jobs submit command "echo hello from the preview" --priority 3 2>&1 | tail -2
else
  printf '%s job(s) already queued\n' "$QUEUED"
fi

# ---------------------------------------------------------------- summary
say "what the preview will show"
"$CLI" --json info >"$HOME_DIR/info.json" 2>/dev/null
"$PY" - "$HOME_DIR/info.json" <<'PYEOF'
import json, sys

with open(sys.argv[1]) as handle:
    data = json.load(handle)
print("home        ", data["home"])
print("schema       v%s (expected v%s)" % (data["schema_version"], data["expected_schema_version"]))
print("memories    ", data["memories"], " conversations", data["conversations"], " tasks", data["tasks"])
print("models      ", len(data["models"]), "registered  workflows", data["workflows"])
for warning in data["warnings"]:
    print("warning     ", warning)
PYEOF
