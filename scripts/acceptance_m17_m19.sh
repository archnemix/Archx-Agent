#!/usr/bin/env bash
# Real acceptance run for M17 (memory systems), M18 (retrieval) and M19 (context).
#
# Executes the installed console script against a throw-away home and prints
# everything it did. No mocks: this is the same binary a user runs.
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$HERE/.venv/bin/archx-agent"
HOME_DIR="${1:-$(mktemp -d /tmp/archx-accept-XXXXXX)}"
export ARCHX_PATHS_HOME="$HOME_DIR"

say() { printf '\n### %s\n' "$*"; }
run() { printf '$ archx-agent %s\n' "$*"; "$CLI" "$@"; printf '[exit %s]\n' "$?"; }

say "home"
echo "$HOME_DIR"
run init

say "M17 - six memory systems"
run models add-scripted --name demo
PROJECT=$("$CLI" projects create "Archx" --path archx --json | "$HERE/.venv/bin/python" -c 'import json,sys;print(json.load(sys.stdin)["id"])')
echo "project id: $PROJECT"
CONV=$("$CLI" chat -m "We are building the memory system." --json --allow-simulated | "$HERE/.venv/bin/python" -c 'import json,sys;print(json.load(sys.stdin)["conversation_id"])')
echo "conversation id: $CONV"

run memory add --kind active --conversation "$CONV" --category goal --title "Current goal" \
    --content "Finish the memory foundation before retrieval work" --slot current_goal
run memory add --kind permanent --category preference --title "Style" \
    --content "Prefer short, direct answers without filler"
run memory add --kind archival --category finding --title "Benchmark note" \
    --content "Keyword scan over 20k memories took 41 ms on this machine" \
    --provenance-origin "manual benchmark" --source user
run memory add --kind project --project "$PROJECT" --category decision --title "Storage choice" \
    --content "Use one SQLite database with a single writer thread" \
    --provenance-origin "design review" --source user
run memory add --kind solution --category known_issue --title "Database is locked" \
    --content "Under concurrent writers SQLite returned database is locked" \
    --problem "concurrent writes fail with database is locked" \
    --solution "serialise writes through one writer thread and set busy_timeout" \
    --verification verified --evidence "storage suite: 40 concurrent writes, 0 failures"
run memory add --kind learning --category progress --title "Learned WAL" \
    --content "WAL mode lets readers continue while a write is in flight" \
    --topic sqlite --outcome passed

say "retrieval under a budget (what actually reaches the model)"
run memory retrieve --conversation "$CONV" --project "$PROJECT" --budget 90

say "edit keeps history, duplicate is refused"
FIRST=$("$CLI" memory list --kind permanent --json | "$HERE/.venv/bin/python" -c 'import json,sys;print(json.load(sys.stdin)[0]["id"])')
run memory edit "$FIRST" --content "Prefer short, direct answers; no filler at all"
run memory history "$FIRST"
run memory add --kind permanent --category preference --title "Style" \
    --content "Prefer short, direct answers; no filler at all"

say "search, then delete (soft) and confirm it is gone from results"
run memory search "sqlite"
run memory delete "$FIRST"
run memory search "filler"
run memory stats

say "M18 - embeddings and measured retrieval quality"
run config set memory.embeddings_enabled true
run embeddings status
run embeddings backfill
run embeddings search "which database do we use for storage" -k 3 --threshold 0
run eval retrieval --dataset "$HERE/data/retrieval_set.json" --k 5
run eval retrieval --dataset "$HERE/data/retrieval_set.json" --k 5 --json --no-scratch

say "M19 - five context strategies preserve history"
for i in 1 2 3 4 5 6 7; do
    "$CLI" chat -m "Filler turn $i: scheduling, resources and databases discussed at length $i" \
        -c "$CONV" --allow-simulated >/dev/null
done
run context build "$CONV" --strategy oldest_first --budget 120
run context build "$CONV" --strategy ai_select --budget 150 --message "what did we decide about storage"
run context build "$CONV" --strategy summarize --budget 150 --allow-simulated
PROPOSAL=$("$CLI" context propose "$CONV" --budget 150 --json | "$HERE/.venv/bin/python" -c 'import json,sys;print(json.load(sys.stdin)["id"])')
echo "proposal: $PROPOSAL"
run context build "$CONV" --strategy ai_proposed --proposal "$PROPOSAL" --budget 150 --allow-simulated
MID=$("$CLI" conv show "$CONV" --json | "$HERE/.venv/bin/python" -c 'import json,sys;print(json.load(sys.stdin)["messages"][2]["id"])')
run context build "$CONV" --strategy manual --manual-ids "$MID" --budget 300
run context summaries "$CONV"
echo "stored messages after all of the above:"
"$CLI" conv show "$CONV" --json | "$HERE/.venv/bin/python" -c 'import json,sys;print(len(json.load(sys.stdin)["messages"]))'

say "trace: every write above is recorded"
run trace list --limit 12
run db check
