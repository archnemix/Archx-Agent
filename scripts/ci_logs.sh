#!/usr/bin/env bash
# Read the CI runs that the `model-matrix` workflow commits back into this repository.
#
# The workflow cannot be *watched* through the Actions API without an `actions: write` token,
# but it pushes `ci/runs/<id>/` to the `ci-logs` branch - and reading a branch only needs
# `contents: read`. This script fetches that branch and prints what happened.
#
#   ./scripts/ci_logs.sh                 # the newest run: status table + the tail of its log
#   ./scripts/ci_logs.sh --list          # every run, newest first
#   ./scripts/ci_logs.sh --run <id>      # one run
#   ./scripts/ci_logs.sh --tail 200      # more console context
#   ./scripts/ci_logs.sh --wait 600      # poll until a run newer than now appears (seconds)
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRANCH="${CI_LOG_BRANCH:-ci-logs}"
REMOTE="${CI_LOG_REMOTE:-origin}"
LINES=60
MODE="latest"
WANT=""
WAIT=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --list) MODE="list"; shift ;;
    --run) MODE="run"; WANT="${2:-}"; shift 2 ;;
    --tail) LINES="${2:-60}"; shift 2 ;;
    --wait) WAIT="${2:-600}"; shift 2 ;;
    -h|--help) sed -n '2,16p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) printf 'unknown argument %s\n' "$1" >&2; exit 2 ;;
  esac
done

# Fetch into FETCH_HEAD, so $REMOTE may be a name (`origin`) or a path to a bare repo, which is
# how this script is tested.
fetch() { git -C "$HERE" fetch -q "$REMOTE" "$BRANCH" 2>/dev/null && REF="FETCH_HEAD"; }

if ! fetch; then
  printf 'no %s branch on %s yet.\n' "$BRANCH" "$REMOTE" >&2
  printf 'Push a change to .ci/trigger to start a run; the workflow publishes its own logs.\n' >&2
  exit 3
fi

if [ "$WAIT" -gt 0 ]; then
  printf 'waiting for a new run (up to %ss)…\n' "$WAIT"
  deadline=$(( $(date +%s) + WAIT ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    fetch || true
    newest="$(git -C "$HERE" ls-tree --name-only "$REF" ci/runs/ 2>/dev/null | sort | tail -1)"
    runs="$(git -C "$HERE" ls-tree --name-only -r "$REF" ci/runs/ 2>/dev/null | head -1)"
    if [ -n "$runs" ]; then break; fi
    sleep 15
  done
fi

runs="$(git -C "$HERE" ls-tree --name-only "$REF" ci/runs/ 2>/dev/null | sed 's#ci/runs/##; s#/$##' | sort)"
if [ -z "$runs" ]; then
  printf 'the %s branch exists but holds no runs yet.\n' "$BRANCH" >&2
  exit 3
fi

case "$MODE" in
  list)
    printf 'runs on %s/%s (newest last):\n' "$REMOTE" "$BRANCH"
    printf '%s\n' "$runs" | sed 's/^/  /'
    exit 0
    ;;
  run)
    [ -n "$WANT" ] || { printf -- '--run needs a run id (see --list)\n' >&2; exit 2; }
    RUN="$WANT"
    ;;
  *)
    RUN="$(printf '%s\n' "$runs" | tail -1)"
    ;;
esac

show() {
  git -C "$HERE" show "$REF:ci/runs/$RUN/$1" 2>/dev/null
}

printf '=== run %s (from %s %s) ===\n\n' "$RUN" "$REMOTE" "$BRANCH"
meta="$(show meta.tsv)"
[ -n "$meta" ] && { printf '%s\n\n' "$meta"; }

status="$(show status.tsv)"
if [ -n "$status" ]; then
  printf '%-34s %-10s %s\n' "step" "status" "seconds"
  printf '%s\n' "$status" | while IFS=$'\t' read -r step st took; do
    case "$st" in ok|FAIL*) printf '%-34s %-10s %s\n' "$step" "$st" "$took" ;; esac
  done
  failed="$(printf '%s\n' "$status" | awk -F'\t' '$2 ~ /^(ok|FAIL)/ && $2 != "ok" {n++} END {print n+0}')"
  printf '\n%s step(s) failed\n' "$failed"
else
  printf '(no status.tsv yet - the run may still be starting)\n'
fi

printf '\n--- console (last %s lines) ---\n' "$LINES"
show console.log | tail -n "$LINES"

printf '\n--- files in this run ---\n'
git -C "$HERE" ls-tree --name-only "$REF" "ci/runs/$RUN/" 2>/dev/null | sed 's#.*/##' | sort | sed 's/^/  /'

if [ "${failed:-0}" != "0" ]; then
  exit 1
fi
exit 0
