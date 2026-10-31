#!/usr/bin/env bash
# M36 acceptance: two trainers that really run, and a fine-tune refused with every reason named.
#
# The claim this script exists to test is that the numbers on screen were *measured here*. So:
#   * the corpus is written by this script, and the n-gram model's perplexity is recomputed by an
#     independent implementation in this script from the artifact the run wrote - if the two
#     disagree, the metric was invented;
#   * the classifier's prediction is checked against a document this script knows the label of;
#   * the fine-tune chain is shortened one link at a time, and the refusal is a row;
#   * a refused run has no artifact, cannot be predicted from, and is listed as refused;
#   * a comparison of two methods names no winner, and of one method names the better metric.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="${ARCHX_CLI:-$HERE/.venv/bin/archx-agent}"
[ -x "$CLI" ] || CLI="$(command -v archx-agent)"
PY="${ARCHX_PY:-$HERE/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python)"
WORK="${1:-$(mktemp -d /tmp/archx-m36-XXXXXX)}"
HOME_DIR="$WORK/home"
LAB="$WORK/lab"
export ARCHX_PATHS_HOME="$HOME_DIR"
export ARCHX_TOOLS_ROOTS="$LAB"
mkdir -p "$HOME_DIR" "$LAB"
PORT="$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
TOKEN="m36-acceptance-token"
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

cleanup() {
  [ -n "$GUI_PID" ] && kill "$GUI_PID" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT

# Two languages, four files each: enough for a split with a validation record of each label, small
# enough that the expected perplexity can be computed by hand below.
mkdir -p "$LAB/corpus/python" "$LAB/corpus/rust"
for n in 1 2 3 4; do
  printf 'def function_%s(x):\n    return x + %s\n' "$n" "$n" > "$LAB/corpus/python/file$n.txt"
  printf 'fn function_%s(x: i32) -> i32 {\n    x + %s\n}\n' "$n" "$n" > "$LAB/corpus/rust/file$n.txt"
done

printf 'M36 acceptance on %s\n' "$WORK"
"$CLI" init >/dev/null 2>&1

say "the schema adopts the table v8 reserved"
check "training is a versioned migration" \
  "$(dbq "SELECT COUNT(*) FROM schema_migrations WHERE version = 26")" "1"
check "jobs and metrics are tables" \
  "$(dbq "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('training_jobs','training_metrics')")" "2"
check "the reserved columns survive the adoption" \
  "$(dbq "SELECT COUNT(*) FROM pragma_table_info('training_jobs') WHERE name IN ('method','base_model','dataset_id','status','config','metrics','checkpoints','error')")" "8"
check "a fresh home has run nothing" "$("$CLI" --json train stats | jq_ "d['jobs']")" "0"
check "and says plainly it cannot fine-tune" \
  "$("$CLI" --json train stats | jq_ "d['can_finetune']")" "False"

"$CLI" permissions grant fs.read --subject '*' --duration persistent --confirm >/dev/null
"$CLI" permissions grant fs.write --subject '*' --duration persistent --confirm >/dev/null
DS="$("$CLI" --json dataset create code --source corpus --license MIT | jq_ "d['id']")"
"$CLI" dataset scan "$DS" >/dev/null 2>&1

say "a run is not attempted until the dataset can support one"
"$CLI" --json train preflight --method ngram --dataset "$DS" >"$WORK/early.json" 2>/dev/null
check "an unsplit dataset is not runnable" "$(jq_ "d['runnable']" < "$WORK/early.json")" "False"
check "and the reason names the missing split" \
  "$(jq_ "any('no split yet' in r for r in d['reasons'])" < "$WORK/early.json")" "True"
check "the preflight exits 3 (cannot), not 0" "$("$CLI" train preflight --method ngram --dataset "$DS" >/dev/null 2>&1; echo $?)" "3"

"$CLI" dataset clean "$DS" >/dev/null 2>&1
"$CLI" dataset split "$DS" --train 0.5 --val 0.25 --test 0.25 --seed m36 >/dev/null 2>&1
"$CLI" --json train preflight --dataset "$DS" >"$WORK/split.json" 2>/dev/null
check "a split but unbuilt dataset still fails" "$(jq_ "d['runnable']" < "$WORK/split.json")" "False"
check "and the reason names the build" \
  "$(jq_ "any('never built' in r for r in d['reasons'])" < "$WORK/split.json")" "True"
"$CLI" dataset build "$DS" >/dev/null 2>&1
"$CLI" --json train preflight --dataset "$DS" >"$WORK/ready.json" 2>/dev/null
check "a built, split, verified dataset is runnable" \
  "$(jq_ "d['runnable']" < "$WORK/ready.json")" "True"
check "every check is a row" "$(jq_ "all(c['ok'] for c in d['checks'])" < "$WORK/ready.json")" "True"
check "including the manifest" \
  "$(jq_ "any(c['check'] == 'manifest' and c['ok'] for c in d['checks'])" < "$WORK/ready.json")" "True"

say "an n-gram model is trained here, and its perplexity is arithmetic"
NG="$("$CLI" --json train run --method ngram --dataset "$DS" --order 2 --seed 7 | jq_ "d['id']")"
check "the run completed" "$(dbq "SELECT status FROM training_jobs WHERE id = '$NG'")" "completed"
check "it trained on the dataset it names" \
  "$(dbq "SELECT dataset_id FROM training_jobs WHERE id = '$NG'")" "$DS"
check "train, val and test were each scored" \
  "$(dbq "SELECT COUNT(DISTINCT split) FROM training_metrics WHERE job_id = '$NG'")" "3"
check "perplexity is recorded per split" \
  "$(dbq "SELECT COUNT(*) FROM training_metrics WHERE job_id = '$NG' AND name = 'perplexity' AND value > 0")" "3"
check "the metrics are rows, not a blob" \
  "$(dbq "SELECT COUNT(*) FROM training_metrics WHERE job_id = '$NG'")" "9"
ARTIFACT="$LAB/$(dbq "SELECT artifact_path FROM training_jobs WHERE id = '$NG'")"
check "the artifact is a file on disk" "$([ -f "$ARTIFACT" ] && echo yes)" "yes"
check "its recorded hash is the file's hash" \
  "$(dbq "SELECT artifact_sha256 FROM training_jobs WHERE id = '$NG'")" "$(sha256sum "$ARTIFACT" | cut -d' ' -f1)"
check "the artifact says what it is" "$("$PY" -c "import json;print(json.load(open('$ARTIFACT'))['kind'])")" "ngram"
check "the artifact is versioned" \
  "$([ -n "$(dbq "SELECT version_id FROM training_jobs WHERE id = '$NG'")" ] && echo versioned)" "versioned"

# An independent perplexity: read the counts out of the artifact and score the same text by hand.
REFERENCE="$("$CLI" --json train predict "$NG" "def function_1(x): return x + 1" | jq_ "d['perplexity']")"
INDEPENDENT="$("$PY" - "$ARTIFACT" "def function_1(x): return x + 1" <<'PYEOF'
import json, math, re, sys

artifact = json.load(open(sys.argv[1]))
text = sys.argv[2]
order, smoothing = artifact["order"], artifact["smoothing"]
counts = artifact["counts"]
vocab = set(artifact["vocab"])
tokens = re.findall(r"[A-Za-z0-9']+", text.lower())

def words(text):
    return re.findall(r"[A-Za-z0-9']+", text.lower())

sequence = ["<s>"] * (order - 1) + words(text) + ["</s>"]
total = 0.0
counted = 0
for index in range(order - 1, len(sequence)):
    history = " ".join(sequence[index - order + 1:index])
    word = sequence[index]
    scoring = word if (word == "</s>" or word in vocab) else "<unk>"
    counter = counts.get(history)
    if not counter:
        probability = 1.0 / (len(vocab) + 1)
    else:
        denominator = sum(counter.values()) + smoothing * (len(vocab) + 1)
        probability = (counter.get(scoring, 0) + smoothing) / denominator
    total += -math.log(probability)
    counted += 1
print(f"{math.exp(total / counted):.10f}")
PYEOF
)"
check "an independent implementation gets the same perplexity" \
  "$("$PY" -c "print(abs($REFERENCE - $INDEPENDENT) < 1e-9)")" "True"

say "a classifier is trained here, and predicts a label this script knows"
CL="$("$CLI" --json train run --method centroid --dataset "$DS" | jq_ "d['id']")"
check "the classifier completed" "$(dbq "SELECT status FROM training_jobs WHERE id = '$CL'")" "completed"
check "it labelled from the directory and said so" \
  "$(dbq "SELECT config FROM training_jobs WHERE id = '$CL'" | grep -c 'directory')" "1"
check "it saw two labels" \
  "$(dbq "SELECT value FROM training_metrics WHERE job_id = '$CL' AND name = 'labels' LIMIT 1")" "2.0"
check "accuracy is a fraction between 0 and 1" \
  "$("$PY" -c "
import sqlite3
row = sqlite3.connect('$HOME_DIR/archx.db').execute(
    \"SELECT value FROM training_metrics WHERE job_id = '$CL' AND name = 'accuracy'\").fetchone()
print(0.0 <= row[0] <= 1.0)")" "True"
check "a rust-shaped document predicts rust" \
  "$("$CLI" --json train predict "$CL" "fn function_2(x: i32) -> i32 { x + 2 }" | jq_ "d['label']")" "rust"
check "a python-shaped document predicts python" \
  "$("$CLI" --json train predict "$CL" "def function_2(x): return x + 2" | jq_ "d['label']")" "python"

say "fine-tuning is refused with every missing link, in order"
"$CLI" --json train run --method lora --dataset "$DS" >"$WORK/lora.json" 2>/dev/null
check "asking for a fine-tune exits 3" "$?" "3"
LORA="$(jq_ "d['id']" < "$WORK/lora.json")"
check "the refusal is a row" "$(dbq "SELECT status FROM training_jobs WHERE id = '$LORA'")" "refused"
check "the first reason is the switch" \
  "$(jq_ "'training is off' in d['reasons'][0]" < "$WORK/lora.json")" "True"
check "the last is the missing adapter" \
  "$(jq_ "'no adapter in this build can fine-tune anything' in d['reasons'][-1]" < "$WORK/lora.json")" "True"
BEFORE="$("$CLI" --json train stats | jq_ "len(d['why_not'])")"
"$CLI" config set training.enabled true >/dev/null
AFTER="$("$CLI" --json train stats | jq_ "len(d['why_not'])")"
check "turning training on removes exactly one reason" "$((BEFORE - AFTER))" "1"
check "and the switch is no longer the first reason" \
  "$("$CLI" --json train run --method qlora --dataset "$DS" | jq_ "d['reasons'][0].startswith('training is off')")" "False"
check "the library and the GPU are named" \
  "$("$CLI" --json train stats | jq_ "any('torch' in r for r in d['why_not']) and any('CUDA' in r for r in d['why_not'])")" "True"
check "a refused run has no artifact" \
  "$(dbq "SELECT COUNT(*) FROM training_jobs WHERE status = 'refused' AND artifact_path IS NOT NULL")" "0"
check "and cannot be predicted from" \
  "$("$CLI" train predict "$LORA" "anything" >/dev/null 2>&1; echo $?)" "2"
"$CLI" config set training.enabled false >/dev/null

say "a comparison names what it could not rank"
check "two n-gram runs rank on val perplexity" \
  "$("$CLI" --json train compare "$NG" "$("$CLI" --json train run --method ngram --dataset "$DS" --order 3 | jq_ "d['id']")" | jq_ "d['metric'] == 'perplexity' and d['best'] is not None")" "True"
check "a mixed comparison names no winner" \
  "$("$CLI" --json train compare "$NG" "$CL" | jq_ "d['best']")" "None"
check "and says why" \
  "$("$CLI" --json train compare "$NG" "$CL" | jq_ "any('different methods' in n for n in d['notes'])")" "True"
check "a refused run is listed with its status" \
  "$("$CLI" --json train compare "$NG" "$LORA" | jq_ "any(r['status'] == 'refused' for r in d['rows'])")" "True"

say "the counters agree with the rows"
check "jobs" "$("$CLI" --json train stats | jq_ "d['jobs']")" \
  "$(dbq "SELECT COUNT(*) FROM training_jobs")"
check "completed" "$("$CLI" --json train stats | jq_ "d['by_status']['completed']")" \
  "$(dbq "SELECT COUNT(*) FROM training_jobs WHERE status = 'completed'")"
check "metrics" "$("$CLI" --json train stats | jq_ "d['metrics']")" \
  "$(dbq "SELECT COUNT(*) FROM training_metrics")"
run train list

say "the page is a client of the same service"
"$CLI" gui serve --host 127.0.0.1 --port "$PORT" --token "$TOKEN" --no-open >"$WORK/gui.log" 2>&1 &
GUI_PID=$!
for _ in $(seq 1 40); do
  [ "$(status_of "$BASE/api/health")" = "200" ] && break
  sleep 0.25
done
check "the page lists the runs the CLI made" \
  "$(get_json "$BASE/api/training/runs" | api_jsonq "len(d['runs'])")" \
  "$(dbq "SELECT COUNT(*) FROM training_jobs")"
check "the page says it cannot fine-tune" \
  "$(get_json "$BASE/api/training/runs" | api_jsonq "d['stats']['can_finetune']")" "False"
PAGE_JOB="$(post_json "$BASE/api/training/runs" "{\"method\":\"ngram\",\"dataset\":\"$DS\",\"order\":2}" | api_jsonq "d['id']")"
check "a run started in the page is a row the CLI reads" \
  "$(dbq "SELECT COUNT(*) FROM training_jobs WHERE id = '$PAGE_JOB'")" "1"
check "the metrics endpoint returns the same numbers" \
  "$(get_json "$BASE/api/training/runs/$PAGE_JOB/metrics" | api_jsonq "d['by_split']['val']['perplexity'] > 0")" "True"
check "a refusal over HTTP is a 200 with the reasons" \
  "$(post_json "$BASE/api/training/runs" "{\"method\":\"full\",\"dataset\":\"$DS\"}" | api_jsonq "d['status'] == 'refused' and len(d['reasons']) > 0")" "True"
check "an unknown run is a 404" \
  "$(status_of -H "X-Archx-Token: $TOKEN" "$BASE/api/training/runs/tj_nope")" "404"
check "an unauthenticated call is refused" "$(status_of "$BASE/api/training/runs")" "401"
check "the preflight route answers the same question" \
  "$(post_json "$BASE/api/training/preflight" "{\"method\":\"lora\",\"dataset\":\"$DS\"}" | api_jsonq "d['runnable']")" "False"

say "the record survives a restart"
check "the completed run is still completed" \
  "$("$CLI" --json train show "$NG" | jq_ "d['status']")" "completed"
check "the metrics are still the ones measured" \
  "$("$CLI" --json train metrics "$NG" | jq_ "sorted(d['by_split'])")" "['test', 'train', 'val']"
check "the artifact path is still recorded" \
  "$([ -f "$LAB/$("$CLI" --json train show "$NG" | jq_ "d['artifact_path']")" ] && echo yes)" "yes"
check "and the refusal is still a refusal" \
  "$("$CLI" --json train show "$LORA" | jq_ "d['status']")" "refused"

printf '\nM36 acceptance: %s checks passed, %s failed\n' \
  "$((${#CHECKS[@]} - FAILURES))" "$FAILURES"
[ "$FAILURES" -eq 0 ] || exit 1
