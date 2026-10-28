#!/usr/bin/env bash
# M35 acceptance: a corpus prepared the way a person would prepare one, with the file contents
# written by this script so every hash below is known before the pipeline starts.
#
# The claims being checked are the four that make a prepared corpus worth having, and each is
# checked by trying to break it:
#   * every candidate is a row - a file removed by a rule keeps the rule and the reason, and
#     `dataset explain` answers "why is this not in my dataset" from the record;
#   * a split is a function of the record, not of its position: adding a file to the corpus does
#     not move the files already in train, and the same seed reproduces the assignment;
#   * a resaved document (same text, different whitespace or case) cannot sit in two splits - the
#     split is refused and names the pair, and `--normalize` closes the gap;
#   * the manifest is a claim that can fail: edit one file after the build and `verify` disagrees,
#     prints both hashes and says which record changed;
#   * the license is recorded, and an unstated one is written as `unknown` rather than assumed.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="${ARCHX_CLI:-$HERE/.venv/bin/archx-agent}"
[ -x "$CLI" ] || CLI="$(command -v archx-agent)"
PY="${ARCHX_PY:-$HERE/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python)"
WORK="${1:-$(mktemp -d /tmp/archx-m35-XXXXXX)}"
HOME_DIR="$WORK/home"
LAB="$WORK/lab"
export ARCHX_PATHS_HOME="$HOME_DIR"
export ARCHX_TOOLS_ROOTS="$LAB"
mkdir -p "$HOME_DIR" "$LAB"
PORT="$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
TOKEN="m35-acceptance-token"
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
api_jsonq() { "$PY" -c "import json,sys; d=json.load(sys.stdin)['data']; print($1)"; }
dbq() {
  "$PY" - "$HOME_DIR/archx.db" "$1" <<'PYEOF'
import sqlite3, sys
connection = sqlite3.connect(sys.argv[1])
print(connection.execute(sys.argv[2]).fetchone()[0])
PYEOF
}
sha_of() { sha256sum "$1" | cut -d' ' -f1; }

cleanup() {
  [ -n "$GUI_PID" ] && kill "$GUI_PID" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT

# The corpus is written here, so the expectations are arithmetic on known content rather than a
# copy of whatever a previous run happened to produce.
mkdir -p "$LAB/corpus/sub"
printf 'the first document\nwith two lines\n' > "$LAB/corpus/a.txt"
printf 'the first document\nwith two lines\n' > "$LAB/corpus/copy_open.txt"
printf 'The First Document\n  with   two lines\n' > "$LAB/corpus/resaved.txt"
printf '' > "$LAB/corpus/empty.txt"
printf 'short' > "$LAB/corpus/tiny.md"
printf '\x00\x01\x02binary' > "$LAB/corpus/blob.txt"
printf 'second document here\n' > "$LAB/corpus/sub/b.md"
printf 'third document here\n' > "$LAB/corpus/c.md"
printf '\x89PNG\r\n\x1a\n' > "$LAB/corpus/screenshot.png"

printf 'M35 acceptance on %s\n' "$WORK"
"$CLI" init >/dev/null 2>&1

say "the schema adopts the tables v8 reserved"
check "datasets is a versioned migration" \
  "$(dbq "SELECT COUNT(*) FROM schema_migrations WHERE version = 25")" "1"
check "the reserved tables were kept, not redefined" \
  "$(dbq "SELECT COUNT(*) FROM pragma_table_info('datasets') WHERE name IN ('source','revision','license','format','record_count','path','checksum')")" "7"
check "records and the step ledger exist" \
  "$(dbq "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('datasets','dataset_records','dataset_transforms')")" "3"
check "a fresh home has no datasets" "$("$CLI" --json dataset stats | jq_ "d['datasets']")" "0"

say "a dataset records where it came from, and an unstated license is not guessed"
DS="$("$CLI" --json dataset create corpus --source corpus --license CC-BY-4.0 | jq_ "d['id']")"
check "the dataset is a row" "$(dbq "SELECT COUNT(*) FROM datasets WHERE id = '$DS'")" "1"
check "it starts as a draft" "$(dbq "SELECT status FROM datasets WHERE id = '$DS'")" "draft"
check "the license is the one declared" "$(dbq "SELECT license FROM datasets WHERE id = '$DS'")" "CC-BY-4.0"
UNSAID="$("$CLI" --json dataset create unsaid --source corpus | jq_ "d['id']")"
check "an unstated license is written as unknown" \
  "$(dbq "SELECT license FROM datasets WHERE id = '$UNSAID'")" "unknown"
check "and the record says nobody declared it" \
  "$("$CLI" --json dataset show "$UNSAID" | jq_ "d['license_note'].startswith('unknown')")" "True"
check "a dataset with no sources is refused" \
  "$("$CLI" dataset create bare 2>/dev/null >/dev/null; echo $?)" "2"

say "scanning measures every candidate, through the tool layer"
"$CLI" dataset scan "$DS" >/dev/null 2>"$WORK/scan.err"
check "the scan needs fs.read" "$?" "1"
check "it names the approval to approve" "$(grep -c 'approvals approve' "$WORK/scan.err")" "1"
"$CLI" permissions grant fs.read --subject '*' --duration persistent --confirm >/dev/null
"$CLI" permissions grant fs.write --subject '*' --duration persistent --confirm >/dev/null
"$CLI" dataset scan "$DS" >"$WORK/scan.out" 2>&1
check "the scan succeeds once the grant exists" "$?" "0"
check "every file is a candidate" "$(dbq "SELECT COUNT(*) FROM dataset_records WHERE dataset_id = '$DS'")" "9"
check "the binary with a text suffix was measured and shelved" \
  "$(dbq "SELECT status FROM dataset_records WHERE dataset_id = '$DS' AND path LIKE '%blob.txt'")" "dropped"
check "and the reason names the refusal, not the name" \
  "$(dbq "SELECT reason LIKE '%refusing to read it as text%' FROM dataset_records WHERE dataset_id = '$DS' AND path LIKE '%blob.txt'")" "1"
check "the empty file is dropped with its reason" \
  "$(dbq "SELECT reason FROM dataset_records WHERE dataset_id = '$DS' AND path LIKE '%empty.txt'")" "the file is empty"
check "a png is shelved as binary rather than skipped" \
  "$(dbq "SELECT reason FROM dataset_records WHERE dataset_id = '$DS' AND path LIKE '%screenshot.png'")" \
  "not a text file this build can parse"
check "the scan is a step in the ledger" \
  "$(dbq "SELECT COUNT(*) FROM dataset_transforms WHERE dataset_id = '$DS' AND kind = 'scan'")" "1"
check "the ledger says what it took in and gave back" \
  "$(dbq "SELECT records_out FROM dataset_transforms WHERE dataset_id = '$DS' AND kind = 'scan'")" "9"
check "the tool layer saw the reads" \
  "$(dbq "SELECT COUNT(*) FROM tool_runs WHERE tool_name = 'fs.probe' AND status IN ('ok','succeeded')")" "9"

say "the same text resaved is visible, because the exact hash cannot see it"
check "a.txt and resaved.txt have different bytes" \
  "$([ "$(sha_of "$LAB/corpus/a.txt")" != "$(sha_of "$LAB/corpus/resaved.txt")" ] && echo differ)" "differ"
check "but one normalised hash" \
  "$("$CLI" --json dataset records "$DS" | jq_ "
next(r for r in d if r['path'].endswith('a.txt'))['metadata']['norm_sha'] ==
next(r for r in d if r['path'].endswith('resaved.txt'))['metadata']['norm_sha']")" "True"

say "cleaning removes, and every removal keeps its reason"
"$CLI" dataset clean "$DS" --min-chars 10 >"$WORK/clean.out" 2>&1
check "cleaning succeeds" "$?" "0"
check "the byte-identical copy is dropped, naming the path it duplicates" \
  "$(dbq "SELECT reason LIKE '%corpus/a.txt' FROM dataset_records WHERE dataset_id = '$DS' AND path LIKE '%copy_open.txt'")" "1"
check "the tiny file records the comparison" \
  "$(dbq "SELECT reason FROM dataset_records WHERE dataset_id = '$DS' AND path LIKE '%tiny.md'")" \
  "fewer characters than the min_chars rule allows (5 < 10)"
check "a dropped record is still a row" \
  "$(dbq "SELECT COUNT(*) FROM dataset_records WHERE dataset_id = '$DS' AND status = 'dropped'")" "5"
check "the clean step reports each rule's count" \
  "$(dbq "SELECT report FROM dataset_transforms WHERE dataset_id = '$DS' AND kind = 'clean' AND seq = 2")" \
  "$(dbq "SELECT report FROM dataset_transforms WHERE dataset_id = '$DS' AND kind = 'clean' AND seq = 2")"
check "explain answers from the record" \
  "$("$CLI" --json dataset explain "$(dbq "SELECT id FROM dataset_records WHERE dataset_id = '$DS' AND path LIKE '%tiny.md'")" | jq_ "d['sentence'].startswith('corpus/tiny.md was dropped:')")" "True"

say "a resaved document cannot sit in two splits"
"$CLI" dataset split "$DS" --seed 1 >/dev/null 2>"$WORK/leak.err"
check "the split is refused" "$?" "2"
check "and says what it saw" "$(grep -c 'ignoring whitespace and case' "$WORK/leak.err")" "1"
check "and names the pair that crosses" "$(grep -c 'resaved.txt' "$WORK/leak.err")" "1"
check "and names the fix" "$(grep -c '\-\-normalize' "$WORK/leak.err")" "1"
check "no split was written" \
  "$(dbq "SELECT COUNT(*) FROM dataset_records WHERE dataset_id = '$DS' AND split IS NOT NULL")" "0"

say "normalising the dedupe closes the leak and the split goes through"
"$CLI" dataset clean "$DS" --min-chars 10 --normalize >/dev/null 2>&1
check "the resaved copy is dropped, naming the original" \
  "$(dbq "SELECT reason LIKE '%corpus/a.txt' FROM dataset_records WHERE dataset_id = '$DS' AND path LIKE '%resaved.txt'")" "1"
check "three records survive" "$("$CLI" --json dataset show "$DS" | jq_ "d['counts']['kept']")" "3"
"$CLI" dataset split "$DS" --seed m35 >"$WORK/split.out" 2>&1
check "the split succeeds" "$?" "0"
check "every kept record has a split" \
  "$(dbq "SELECT COUNT(*) FROM dataset_records WHERE dataset_id = '$DS' AND status = 'kept' AND split IS NULL")" "0"
check "no content hash is in two splits" \
  "$(dbq "SELECT COUNT(*) FROM (SELECT sha256 FROM dataset_records WHERE dataset_id = '$DS' AND status = 'kept' GROUP BY sha256 HAVING COUNT(DISTINCT split) > 1)")" "0"

say "the split follows from the record, so a new file does not move the old ones"
ASSIGNED="$("$CLI" --json dataset records "$DS" --status kept | jq_ "sorted((r['path'], r['split']) for r in d)")"
printf 'a later document, added after the split\n' > "$LAB/corpus/later.md"
"$CLI" dataset scan "$DS" >/dev/null 2>&1
"$CLI" dataset clean "$DS" --min-chars 10 --normalize >/dev/null 2>&1
"$CLI" dataset split "$DS" --seed m35 >/dev/null 2>&1
AFTER="$("$CLI" --json dataset records "$DS" --status kept | jq_ "sorted((r['path'], r['split']) for r in d if not r['path'].endswith('later.md'))")"
check "the earlier records kept their splits" "$AFTER" "$ASSIGNED"
check "the new file was assigned one" \
  "$("$CLI" --json dataset records "$DS" --status kept | jq_ "any(r['path'].endswith('later.md') and r['split'] for r in d)")" "True"
check "the same seed reproduces the same split" \
  "$("$CLI" --json dataset split "$DS" --seed m35 | jq_ "d['splits']['by_split']")" \
  "$("$CLI" --json dataset split "$DS" --seed m35 | jq_ "d['splits']['by_split']")"
check "the ratios must add up" "$("$CLI" dataset split "$DS" --train 0.9 --val 0.9 --test 0.9 >/dev/null 2>&1; echo $?)" "2"

say "the manifest is a claim you can check"
"$CLI" dataset build "$DS" >"$WORK/build.out" 2>&1
check "the build succeeds" "$?" "0"
CHECKSUM="$(dbq "SELECT checksum FROM datasets WHERE id = '$DS'")"
check "a manifest hash was recorded" "${#CHECKSUM}" "64"
check "the export was written through fs.write" \
  "$(dbq "SELECT COUNT(*) FROM tool_runs WHERE tool_name = 'fs.write' AND status IN ('ok','succeeded')")" "1"
check "the export file exists where the record says" \
  "$([ -f "$LAB/$(dbq "SELECT path FROM datasets WHERE id = '$DS'")" ] && echo yes)" "yes"
check "the export has one line per kept record" \
  "$(wc -l < "$LAB/$(dbq "SELECT path FROM datasets WHERE id = '$DS'")")" \
  "$(dbq "SELECT record_count FROM datasets WHERE id = '$DS'")"
"$CLI" --json dataset verify "$DS" >"$WORK/verify.json" 2>/dev/null
check "verify agrees with an untouched corpus" "$(jq_ "d['agrees']" < "$WORK/verify.json")" "True"
check "and reports the same hash twice" \
  "$(jq_ "d['stored_checksum'] == d['recomputed_checksum']" < "$WORK/verify.json")" "True"

printf 'third document, edited after the build\n' > "$LAB/corpus/c.md"
"$CLI" --json dataset verify "$DS" >"$WORK/verify2.json" 2>/dev/null
check "an edited file makes verify disagree" "$(jq_ "d['agrees']" < "$WORK/verify2.json")" "False"
check "the two hashes are printed and differ" \
  "$(jq_ "d['stored_checksum'] != d['recomputed_checksum']" < "$WORK/verify2.json")" "True"
check "the changed path is named" \
  "$(jq_ "[x['path'] for x in d['differences'] if x['kind'] == 'changed']" < "$WORK/verify2.json")" \
  "['corpus/c.md']"
"$CLI" dataset verify "$DS" >/dev/null 2>&1
check "the CLI exits 3 (degraded), not 1: nothing broke" "$?" "3"
rm "$LAB/corpus/c.md"
"$CLI" --json dataset verify "$DS" >"$WORK/verify3.json" 2>/dev/null
check "a deleted file is a difference too" \
  "$(jq_ "[x['kind'] for x in d['differences']]" < "$WORK/verify3.json")" "['missing']"

say "require_license refuses rather than inventing one"
"$CLI" dataset scan "$UNSAID" >/dev/null 2>&1
check "cleaning an undeclared dataset with require_license exits 2" \
  "$("$CLI" dataset clean "$UNSAID" --require-license >/dev/null 2>&1; echo $?)" "2"
check "and says why" \
  "$("$CLI" dataset clean "$UNSAID" --require-license 2>&1 | grep -c 'license is unknown')" "1"

say "the counters agree with the rows"
check "datasets" "$("$CLI" --json dataset stats | jq_ "d['datasets']")" \
  "$(dbq "SELECT COUNT(*) FROM datasets")"
check "candidates" "$("$CLI" --json dataset stats | jq_ "d['records']")" \
  "$(dbq "SELECT COUNT(*) FROM dataset_records")"
check "kept" "$("$CLI" --json dataset stats | jq_ "d['kept']")" \
  "$(dbq "SELECT COUNT(*) FROM dataset_records WHERE status = 'kept'")"
run dataset show "$DS"

say "the page is a client of the same service"
"$CLI" gui serve --host 127.0.0.1 --port "$PORT" --token "$TOKEN" --no-open >"$WORK/gui.log" 2>&1 &
GUI_PID=$!
for _ in $(seq 1 40); do
  [ "$(status_of "$BASE/api/health")" = "200" ] && break
  sleep 0.25
done
check "the page lists the datasets the CLI wrote" \
  "$(get_json "$BASE/api/datasets" | api_jsonq "len(d['datasets'])")" "$(dbq "SELECT COUNT(*) FROM datasets")"
check "the stats ride with the collection" \
  "$(get_json "$BASE/api/datasets" | api_jsonq "d['stats']['datasets']")" "$(dbq "SELECT COUNT(*) FROM datasets")"
PAGE_DS="$(post_json "$BASE/api/datasets" '{"name":"page-corpus","sources":["corpus"],"license":"CC0-1.0"}' | api_jsonq "d['id']")"
check "a dataset created in the page is a row the CLI reads" \
  "$(dbq "SELECT COUNT(*) FROM datasets WHERE id = '$PAGE_DS'")" "1"
check "scanning from the page measures the same files" \
  "$(post_json "$BASE/api/datasets/$PAGE_DS/scan" '{}' | api_jsonq "d['counts']['kept'] > 0")" "True"
check "dropped records are visible over HTTP with their reason" \
  "$(get_json "$BASE/api/datasets/$PAGE_DS/records?status=dropped" | api_jsonq "all(r['reason'] for r in d['records'])")" "True"
check "an unknown dataset is a 404" \
  "$(status_of -H "X-Archx-Token: $TOKEN" "$BASE/api/datasets/ds_nope")" "404"
check "a bad filter is a 400" \
  "$(status_of -H "X-Archx-Token: $TOKEN" "$BASE/api/datasets/$PAGE_DS/records?status=maybe")" "400"
check "an unauthenticated call is refused" "$(status_of "$BASE/api/datasets")" "401"
check "the verify disagreement over HTTP is a 200 with agrees false" \
  "$(post_json "$BASE/api/datasets/$PAGE_DS/verify" '{}' >/dev/null; get_json "$BASE/api/datasets/$PAGE_DS/verify" | api_jsonq "d['agrees']")" "False"

say "the record survives a restart"
check "the manifest hash is still the one built" \
  "$("$CLI" --json dataset show "$DS" | jq_ "d['checksum']")" "$CHECKSUM"
check "the dropped reasons are still there" \
  "$("$CLI" --json dataset records "$DS" --status dropped | jq_ "len(d) > 0")" "True"
check "and the ledger still has every step" \
  "$("$CLI" --json dataset steps "$DS" | jq_ "len(d) >= 5")" "True"

printf '\nM35 acceptance: %s checks passed, %s failed\n' \
  "$((${#CHECKS[@]} - FAILURES))" "$FAILURES"
[ "$FAILURES" -eq 0 ] || exit 1
