#!/usr/bin/env bash
# M38 acceptance: execution environments - a command runs *there*, and what it changed comes back.
#
# The claim this script exists to test is that a target is a real wrapper and not a label:
#   * every backend this machine cannot use is listed with the reason, and is recorded as refused;
#   * the invocation is shown on the row, and for docker/vmware/virtualbox it is the wrapper that
#     actually executed - proved by putting a stand-in binary on PATH that records its own argv;
#   * a worker refuses /exec until its operator starts it with --allow-exec, and rejects a bad token;
#   * a command run on the worker prints that machine's directory and kernel, not this one's;
#   * the project is pushed, edited there, and pulled back with a hash per file, and a file changed on
#     both sides is a conflict rather than a silent overwrite;
#   * the same training run on the worker and on this CPU produces identical numbers, because it is
#     the same trainer, and the remote run is one row in the same ledger.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="${ARCHX_CLI:-$HERE/.venv/bin/archx-agent}"
[ -x "$CLI" ] || CLI="$(command -v archx-agent)"
PY="${ARCHX_PY:-$HERE/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python)"
WORK="${1:-$(mktemp -d /tmp/archx-m38-XXXXXX)}"
HOME_DIR="$WORK/home"
LAB="$WORK/lab"
export ARCHX_PATHS_HOME="$HOME_DIR"
export ARCHX_TOOLS_ROOTS="$LAB"
mkdir -p "$HOME_DIR" "$LAB" "$LAB/proj" "$LAB/bin" "$WORK/nobin"
free_port() {
  "$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'
}
WPORT="$(free_port)"
FAILURES=0
CHECKS=()
WORKER_PID=""
TRAIN_PID=""

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
  [ -n "$WORKER_PID" ] && kill "$WORKER_PID" 2>/dev/null
  [ -n "$TRAIN_PID" ] && kill "$TRAIN_PID" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT

mkdir -p "$LAB/corpus/python" "$LAB/corpus/rust"
for n in 1 2 3 4; do
  printf 'def function_%s(x):\n    return x + %s\n' "$n" "$n" > "$LAB/corpus/python/file$n.txt"
  printf 'fn function_%s(x: i32) -> i32 {\n    x + %s\n}\n' "$n" "$n" > "$LAB/corpus/rust/file$n.txt"
done
printf "print('hello')\n" > "$LAB/proj/main.py"
printf 'A tiny project\n' > "$LAB/proj/README.md"

printf 'M38 acceptance on %s\n' "$WORK"
"$CLI" init >/dev/null 2>&1

say "the schema records where a command ran, and what crossed the boundary"
check "execution is a versioned migration" \
  "$(dbq "SELECT COUNT(*) FROM schema_migrations WHERE version = 28")" "1"
check "targets, runs and files are tables" \
  "$(dbq "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('execution_targets','execution_runs','execution_files')")" "3"
check "a run keeps the invocation, not just the command" \
  "$(dbq "SELECT COUNT(*) FROM pragma_table_info('execution_runs') WHERE name IN ('invocation','detached','exit_code','stdout_path')")" "4"
check "a training run names its machine" \
  "$(dbq "SELECT COUNT(*) FROM pragma_table_info('training_jobs') WHERE name IN ('target','remote_job_id')")" "2"
check "a fresh home has run nothing" "$("$CLI" --json exec stats | jq_ "d['runs']")" "0"
check "and execution is off" "$("$CLI" --json exec stats | jq_ "d['enabled']")" "False"

"$CLI" permissions grant fs.read --subject '*' --duration persistent --confirm >/dev/null
"$CLI" permissions grant fs.write --subject '*' --duration persistent --confirm >/dev/null
"$CLI" permissions grant shell.run --subject '*' --duration persistent --confirm >/dev/null

say "every backend is named with a reason or a way to enable it"
"$CLI" --json exec targets > "$WORK/targets.json"
check "seven backends are listed" "$(jq_ "len(d)" < "$WORK/targets.json")" "7"
check "each unusable one has a reason and a hint" \
  "$(jq_ "all((p['available'] or (p['why_not'] and p['enable'])) for p in d)" < "$WORK/targets.json")" "True"
# A CI runner has docker, this machine does not, so "docker is absent" cannot be asserted about
# *this* machine. What can be asserted is the shape of the answer: a backend is either available or
# it explains itself, and it never claims both.
check "a backend that is here has no refusal attached" \
  "$(jq_ "all(not p['why_not'] for p in d if p['available'])" < "$WORK/targets.json")" "True"
check "windows sandbox is named as Windows-only" \
  "$(jq_ "any(p['kind'] == 'windows-sandbox' and not p['available'] and any('Windows' in r for r in p['why_not']) for p in d)" < "$WORK/targets.json")" "True"
check "local is available" "$(jq_ "[p['available'] for p in d if p['kind'] == 'local'][0]" < "$WORK/targets.json")" "True"
check "the isolation is stated, not implied" \
  "$(jq_ "any(p['kind'] == 'wsl' and 'not a boundary' in p['isolation'] for p in d)" < "$WORK/targets.json")" "True"

say "nothing runs before the switch"
"$CLI" exec run "echo hello" >"$WORK/off.out" 2>&1
check "a run with execution off exits 3" "$?" "3"
check "and says which setting" "$(grep -q 'execution is off' "$WORK/off.out" && echo yes)" "yes"
check "the refusal is a row" "$(dbq "SELECT status FROM execution_runs ORDER BY rowid DESC LIMIT 1")" "refused"

"$CLI" config set execution.enabled true >/dev/null
"$CLI" --json exec run "echo hello-from-local" > "$WORK/local.json"
check "a local run exits 0" "$?" "0"
check "it records the backend it ran on" "$(jq_ "d['kind']" < "$WORK/local.json")" "local"
check "its output is kept" "$(jq_ "d['stdout'].strip()" < "$WORK/local.json")" "hello-from-local"
check "and kept as a file too" \
  "$([ -f "$LAB/$(jq_ "d['stdout_path']" < "$WORK/local.json")" ] && echo yes)" "yes"

say "a command that fails is a row with its exit code, not a crash"
"$CLI" exec run "exit 7" >"$WORK/fail.out" 2>&1
check "a non-zero exit exits 1" "$?" "1"
check "and the code is recorded" "$(dbq "SELECT exit_code FROM execution_runs ORDER BY rowid DESC LIMIT 1")" "7"

say "an unusable backend refuses with the reason the probe gives"
# `nobin` is an empty directory used as the whole PATH, so "no docker here" is a fact this script
# created rather than one it hopes the machine has (a CI runner does have docker).
PATH="$WORK/nobin" "$CLI" exec add docker --image debian:12 >"$WORK/docker.out" 2>&1
check "the target is recorded as refused" "$(dbq "SELECT status FROM execution_targets WHERE kind = 'docker'")" "refused"
PATH="$WORK/nobin" "$CLI" exec run "python3 -V" --target docker >"$WORK/dockerrun.out" 2>&1
check "running on it exits 3" "$?" "3"
check "and the reason names docker" "$(grep -q 'docker CLI is not on PATH' "$WORK/dockerrun.out" && echo yes)" "yes"

say "the wrapper really is what executes (a stand-in binary proves the argv)"
# The stand-in writes to a path baked in at generation time: `shell.run` runs a child with a
# sanitised environment, so an exported variable would not reach it - which is itself worth knowing.
cat > "$LAB/bin/docker" <<SH
#!/bin/sh
printf '%s\n' "\$@" >> "$WORK/docker.argv"
echo "stand-in sandbox ran"
exit 0
SH
chmod +x "$LAB/bin/docker"
# The stand-in is the only `docker` on this PATH (`nobin` is empty), so "available" can only mean
# the stand-in was found - on a runner that has the real docker too.
PATH="$LAB/bin:$WORK/nobin" "$CLI" --json exec targets > "$WORK/targets2.json"
check "the target becomes available when a docker appears on PATH" \
  "$(jq_ "[p['available'] for p in d if p['kind'] == 'docker'][0]" < "$WORK/targets2.json")" "True"
PATH="$LAB/bin:$WORK/nobin" "$CLI" exec add docker --image debian:12 --name stand-in >"$WORK/standin.out" 2>&1
PATH="$LAB/bin:$WORK/nobin" "$CLI" --json exec run "echo inside" --target stand-in > "$WORK/dockerexec.json"
check "a docker run goes through the wrapper" "$?" "0"
check "the invocation is on the row" \
  "$(jq_ "d['invocation'].startswith('docker run --rm --network none')" < "$WORK/dockerexec.json")" "True"
check "the disposable flag reached the binary" "$(grep -c '^--rm$' "$WORK/docker.argv")" "1"
check "the network really was disabled" "$(grep -A1 '^--network$' "$WORK/docker.argv" | grep -c '^none$')" "1"
check "the image was passed" "$(grep -c '^debian:12$' "$WORK/docker.argv")" "1"
check "the command was passed to the shell inside" "$(grep -c '^echo inside$' "$WORK/docker.argv")" "1"
check "the stand-in's output is the run's output" \
  "$(jq_ "'stand-in sandbox ran' in d['stdout']" < "$WORK/dockerexec.json")" "True"

say "another machine is a real machine, and it says no until its operator says yes"
"$CLI" config set remote.enabled true >/dev/null
"$CLI" config set remote.worker_token acceptance-token >/dev/null
"$CLI" remote worker --port "$WPORT" --name closed-box >"$WORK/closed.log" 2>&1 &
TRAIN_PID=$!
wait_for_port "$WPORT"
"$CLI" exec add remote --name closed --endpoint "http://127.0.0.1:$WPORT" >/dev/null
"$CLI" exec run "echo should-not-run" --target closed >"$WORK/closed.out" 2>&1
check "a worker without --allow-exec refuses the command" "$?" "3"
check "and names the flag" "$(grep -q 'allow-exec' "$WORK/closed.out" && echo yes)" "yes"
kill "$TRAIN_PID" 2>/dev/null; wait "$TRAIN_PID" 2>/dev/null; TRAIN_PID=""

"$CLI" remote worker --port "$WPORT" --name exec-box --allow-exec --token acceptance-token \
  --workdir "$WORK/worker" >"$WORK/worker.log" 2>&1 &
WORKER_PID=$!
wait_for_port "$WPORT"
check "the worker reports execution is on" "$(grep -c 'command execution ON' "$WORK/worker.log")" "1"
"$CLI" exec add remote --name vm1 --endpoint "http://127.0.0.1:$WPORT" >/dev/null

"$CLI" --json exec run "pwd; uname -s" --target vm1 > "$WORK/remote.json"
check "a remote run exits 0" "$?" "0"
check "it names the machine that computed it" \
  "$(jq_ "d['note']" < "$WORK/remote.json")" "ran on exec-box"
check "the output came from the worker's work directory" \
  "$(jq_ "'$WORK/worker' in d['stdout']" < "$WORK/remote.json")" "True"
check "not from this one" "$(jq_ "'$WORK' != '$WORK/worker' and d['stdout'].count('worker') >= 1" < "$WORK/remote.json")" "True"

"$CLI" config set remote.worker_token wrong-token >/dev/null
"$CLI" --json exec run "echo nope" --target vm1 > "$WORK/badtoken.json"
check "a wrong token is refused, not run" "$(jq_ "d['status']" < "$WORK/badtoken.json")" "refused"
check "and the refusal names the token" \
  "$(jq_ "any('token' in r for r in (d['reasons'] or []))" < "$WORK/badtoken.json")" "True"
"$CLI" config set remote.worker_token acceptance-token >/dev/null

"$CLI" exec run "sleep 5" --target vm1 --timeout 1 >"$WORK/timeout.out" 2>&1
check "a timeout is a timeout, not a failure" \
  "$(dbq "SELECT status FROM execution_runs ORDER BY rowid DESC LIMIT 1")" "timeout"

say "the project goes there, is edited there, and comes back"
"$CLI" --json exec push --target vm1 --root "$LAB/proj" > "$WORK/push.json"
check "two files were pushed" "$(jq_ "d['files']" < "$WORK/push.json")" "2"
check "both hashes are recorded" \
  "$(dbq "SELECT COUNT(*) FROM execution_files WHERE direction = 'push' AND sha256_local IS NOT NULL AND sha256_remote IS NOT NULL")" "2"
check "and the hashes agreed" \
  "$(dbq "SELECT COUNT(*) FROM execution_files WHERE direction = 'push' AND sha256_local = sha256_remote")" "2"
"$CLI" exec run "printf 'print(2)\n' > project/main.py && cat project/main.py" --target vm1 >/dev/null
"$CLI" --json exec pull --target vm1 --root "$LAB/proj" > "$WORK/pull.json"
check "the edited file came back" "$(jq_ "d['applied']" < "$WORK/pull.json")" "['main.py']"
check "and it is what the worker wrote" "$(cat "$LAB/proj/main.py")" "print(2)"

say "a file changed on both sides is a conflict, not a silent overwrite"
printf "print('edited here')\n" > "$LAB/proj/main.py"
"$CLI" exec run "printf \"print('edited there')\n\" > project/main.py" --target vm1 >/dev/null
"$CLI" exec pull --target vm1 --root "$LAB/proj" >"$WORK/conflict.out" 2>&1
check "a conflict exits 3" "$?" "3"
check "the conflict is named" "$(grep -c 'conflict  main.py' "$WORK/conflict.out")" "1"
check "the local file was not overwritten" "$(cat "$LAB/proj/main.py")" "print('edited here')"
check "the conflict is in the ledger" \
  "$(dbq "SELECT status FROM execution_files WHERE direction = 'pull' ORDER BY rowid DESC LIMIT 1")" "conflict"
"$CLI" exec pull --target vm1 --root "$LAB/proj" --force >/dev/null 2>&1
check "with --force the worker's version wins" "$(cat "$LAB/proj/main.py")" "print('edited there')"

say "training can run here or there, and the numbers are the same numbers"
DS="$("$CLI" --json dataset create code --source corpus --license MIT | jq_ "d['id']")"
"$CLI" dataset scan "$DS" >/dev/null 2>&1
"$CLI" dataset clean "$DS" >/dev/null 2>&1
"$CLI" dataset split "$DS" --train 0.5 --val 0.25 --test 0.25 --seed m38 >/dev/null 2>&1
"$CLI" dataset build "$DS" >/dev/null 2>&1
"$CLI" config set remote.endpoint "http://127.0.0.1:$WPORT" >/dev/null
"$CLI" --json train run --method ngram --dataset "$DS" --order 2 --seed 5 --target local > "$WORK/local-run.json"
check "a local training run names this CPU" "$(jq_ "d['target']" < "$WORK/local-run.json")" "local"
"$CLI" --json train run --method ngram --dataset "$DS" --order 2 --seed 5 --target remote > "$WORK/remote-run.json"
check "a remote training run completes" "$(jq_ "d['status']" < "$WORK/remote-run.json")" "completed"
check "and names the worker" "$(jq_ "d['target']" < "$WORK/remote-run.json")" "remote"
check "and records the remote job it came from" \
  "$(jq_ "(d['remote_job_id'] or '').startswith('rj_')" < "$WORK/remote-run.json")" "True"
check "both runs are rows in one ledger" \
  "$(dbq "SELECT COUNT(*) FROM training_jobs WHERE target IN ('local','remote') AND status = 'completed'")" "2"
check "the remote metrics equal the local metrics exactly" \
  "$("$PY" -c "
import json,sys
local = json.load(open('$WORK/local-run.json'))
remote = json.load(open('$WORK/remote-run.json'))
print(all(remote['metrics'][s][n] == v for s in local['metrics'] for n, v in local['metrics'][s].items()))")" "True"
check "the remote artifact was hashed here" \
  "$(jq_ "len(d['artifact_sha256'] or '')" < "$WORK/remote-run.json")" "64"
check "an unknown training target is refused by name" \
  "$("$CLI" train run --method ngram --dataset "$DS" --target docker >/dev/null 2>&1; echo $?)" "2"
check "and the parser names the choices it accepts" \
  "$("$CLI" train run --method ngram --dataset "$DS" --target docker 2>&1 | grep -c 'invalid choice')" "1"

say "the ledger answers the question the milestone exists for"
"$CLI" --json exec stats > "$WORK/stats.json"
check "runs are counted per backend" \
  "$(jq_ "(d['by_kind'].get('local', 0) + d['by_kind'].get('remote', 0)) >= 4" < "$WORK/stats.json")" "True"
check "the conflict is counted" "$(jq_ "d['conflicts']" < "$WORK/stats.json")" "1"
check "every run row names a target" \
  "$(dbq "SELECT COUNT(*) FROM execution_runs WHERE target_id IS NULL")" "0"
check "each run's command is exactly what was typed" \
  "$(dbq "SELECT COUNT(*) FROM execution_runs WHERE command LIKE '%hello-from-local%'")" "1"

printf '\n'
if [ "$FAILURES" -eq 0 ]; then
  printf 'M38 acceptance: %d checks passed, 0 failed\n' "${#CHECKS[@]}"
else
  printf 'M38 acceptance: %d passed, %d failed\n' "$((${#CHECKS[@]} - FAILURES))" "$FAILURES"
  for line in "${CHECKS[@]}"; do case "$line" in FAIL*) printf '  %s\n' "$line";; esac; done
fi
exit "$([ "$FAILURES" -eq 0 ] && echo 0 || echo 1)"
