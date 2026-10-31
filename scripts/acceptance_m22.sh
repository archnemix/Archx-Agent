#!/usr/bin/env bash
# M22 acceptance: tool registry + permission centre - in the real app.
#
# Everything here runs through the installed console script against a real
# database, a real sandbox directory and real child processes. Nothing is mocked:
# files are created, read and deleted on disk; `echo` and `false` really run.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$HERE/.venv/bin/archx-agent"
PY="$HERE/.venv/bin/python"
HOME_DIR="${1:-$(mktemp -d /tmp/archx-m22-XXXXXX)}"
export ARCHX_PATHS_HOME="$HOME_DIR"
WORK="$HOME_DIR/workspace"

say() { printf '\n### %s\n' "$*"; }
run() { printf '$ archx-agent %s\n' "$*"; "$CLI" "$@"; printf '[exit %s]\n' "$?"; }

say "home"; echo "$HOME_DIR"; run init

say "the registry: every tool declares a capability, a risk and whether it can dry-run"
run tools list

say "protected operations and what the user is consenting to"
run permissions capabilities

say "a write with no grant is refused, and the refusal creates exactly one approval request"
run tools run fs.write --arg path=notes.md --arg "content=archx m22 works"
echo "--- the file must not exist yet:"; ls -1 "$WORK" 2>/dev/null || echo "(workspace is empty)"
run approvals list

APPROVAL=$("$CLI" approvals list --json | "$PY" -c 'import json,sys;print(json.load(sys.stdin)[0]["id"])')
say "approve exactly that request (approval $APPROVAL)"
run approvals approve "$APPROVAL"

say "the same operation now runs - really writes the file - and the grant is single-use"
run tools run fs.write --arg path=notes.md --arg "content=archx m22 works"
echo "--- on disk:"; cat "$WORK/notes.md"; echo
run tools run fs.write --arg path=notes.md --arg "content=second write"

say "reading needs its own capability: a write grant is not a read grant"
run tools run fs.read --arg path=notes.md
run permissions grant fs.read --subject fs.read --duration conversation --conversation demo-1 --reason "inspect the note"
run tools run fs.read --arg path=notes.md --conversation demo-1
say "and that conversation grant does not apply in another conversation"
run tools run fs.read --arg path=notes.md --conversation other-1

say "a dry run needs a grant too, but changes nothing"
run permissions grant fs.delete --subject fs.delete --duration persistent --confirm
run tools run fs.delete --arg path=notes.md --dry-run
echo "--- still on disk:"; ls -1 "$WORK"

say "the sandbox holds: traversal and absolute escapes are refused (with the grant already in hand)"
run tools run fs.read --arg path=../../../../etc/passwd --conversation demo-1
run tools run fs.read --arg path=/etc/passwd --conversation demo-1
run permissions grant fs.write --subject fs.write --duration persistent --confirm
run tools run fs.write --arg path=/tmp/archx-escape.txt --arg content=x
echo "--- nothing was written outside the sandbox:"; ls -1 /tmp/archx-escape.txt 2>&1 || true
run permissions revoke "$("$CLI" permissions list --json --capability fs.write | "$PY" -c 'import json,sys;print([g["id"] for g in json.load(sys.stdin) if g["scope"]=="persistent"][0])')"

say "a process runs only with a shell.run grant; no shell, no inherited secrets"
run tools run shell.run --arg "command=echo hello from a real subprocess"
APPROVAL2=$("$CLI" approvals list --json | "$PY" -c 'import json,sys;print(json.load(sys.stdin)[0]["id"])')
run approvals approve "$APPROVAL2"
run tools run shell.run --arg "command=echo hello from a real subprocess"
say "no shell: the semicolon is an argument, not a second command"
run permissions grant shell.run --subject shell.run --duration persistent --confirm
run tools run shell.run --arg "command=echo one; echo two"
say "a failing command is a failed run with the exit code, not a success"
run tools run shell.run --arg "command=false"
say "a command that never finishes is killed at the timeout"
run tools run shell.run --arg "command=sleep 30" --arg timeout=2
say "the denylist cannot be approved away"
run tools run shell.run --arg "command=sudo ls"
run tools run shell.run --arg "command=dd if=/dev/zero of=/dev/null"
run approvals list

say "denials are history, not silence: every attempt has a row and a sequence"
run tools runs --limit 12

say "the audit trail: permission decisions, tool calls and file changes"
run trace list --kind permission --limit 6
run trace list --kind tool_call --limit 6
run trace list --kind file_change --limit 4

say "revoking the conversation grant takes effect immediately, in that conversation"
GRANT=$("$CLI" permissions list --json --capability fs.read | "$PY" -c 'import json,sys;print([g["id"] for g in json.load(sys.stdin) if g["scope"]=="conversation"][0])')
run permissions revoke "$GRANT" --reason "acceptance cleanup"
run permissions check fs.read --subject fs.read --conversation demo-1

say "nothing was granted by a tool: every grant names its human origin"
"$CLI" permissions list --json --all > "$HOME_DIR/grants.json"
"$PY" - "$HOME_DIR/grants.json" <<'PY'
import json, sys
grants = json.load(open(sys.argv[1]))
for g in grants:
    print(f"  {g['id']}  {g['capability']:<9} -> {g['subject']:<9} scope={g['scope']:<12} by={g['granted_by']}")
assert grants, "expected grants in the acceptance run"
bad = [g["id"] for g in grants if not g["granted_by"].startswith(("user:", "approval:"))]
assert not bad, f"grants without a human origin: {bad}"
print("  every grant names a human origin (user:cli or approval:<id>)")
PY

say "database integrity after all of it"
run db check

say "done"
echo "home: $HOME_DIR"
