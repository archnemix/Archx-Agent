#!/usr/bin/env bash
# M23 acceptance: MCP client (real subprocess + real HTTP), MCP server mode,
# and a real extension - in the installed application.
#
# The servers here are real programs and real sockets. The extension is a real
# directory with a real Python program that reads JSON on stdin.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$HERE/.venv/bin/archx-agent"
PY="$HERE/.venv/bin/python"
FIXTURE="$HERE/tests/fixtures/mcp_server.py"
HOME_DIR="${1:-$(mktemp -d /tmp/archx-m23-XXXXXX)}"
export ARCHX_PATHS_HOME="$HOME_DIR"
WORK="$HOME_DIR/workspace"

say() { printf '\n### %s\n' "$*"; }
run() { printf '$ archx-agent %s\n' "$*"; "$CLI" "$@"; printf '[exit %s]\n' "$?"; }
jq_() { "$PY" -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

say "home"; echo "$HOME_DIR"; run init
echo "the example MCP server this script drives:"; echo "  $FIXTURE"

say "registering a server runs nothing: it records a program and a decision to review"
run mcp add fixture --command "$PY" --arg "$FIXTURE"
run mcp servers
run mcp add fixture --command "$PY"

say "discovery happens even untrusted - you can see what it would expose"
run mcp sync fixture
run mcp tools fixture

say "but nothing is registered until it is trusted AND enabled"
run mcp trust fixture
run mcp enable fixture
run mcp sync fixture

say "a discovered tool still needs an mcp.call grant - being trusted is not permission"
run mcp call fixture echo --arg text=hello
APPROVAL=$("$CLI" approvals list --json | jq_ "[a['id'] for a in d if a['capability']=='mcp.call'][0]")
run approvals approve "$APPROVAL"
run mcp call fixture echo --arg text=hello

say "a real call with typed arguments, executed by the server process"
run mcp call fixture add --arg a=2 --arg b=40
say "the grant was single-use, so the next tool needs its own decision"
APPROVAL2=$("$CLI" approvals list --json | jq_ "[a['id'] for a in d if a['capability']=='mcp.call'][0]")
run approvals approve "$APPROVAL2"
run mcp call fixture add --arg a=2 --arg b=40

say "a remote tool that reports an error is a failed run, not a success"
run mcp call fixture explode
APPROVAL3=$("$CLI" approvals list --json | jq_ "[a['id'] for a in d if a['capability']=='mcp.call'][0]")
run approvals approve "$APPROVAL3"
run mcp call fixture explode

say "untrusting a server unregisters everything it advertised"
run mcp untrust fixture
run mcp call fixture echo --arg text=hello

say "a real extension: a directory with a manifest and a program"
EXT="$HOME_DIR/extensions/wordcount"
mkdir -p "$EXT"
cat > "$EXT/count.py" <<'PY'
import json, sys
request = json.load(sys.stdin)
text = request["arguments"].get("text", "")
print(json.dumps({
    "words": len([w for w in text.split() if w.strip()]),
    "characters": len(text),
    "tool": request["tool"],
    "extension": request["extension"],
}))
PY
cat > "$EXT/extension.json" <<'JSON'
{
  "name": "wordcount",
  "version": "1.0.0",
  "description": "count words in text you give it",
  "author": "acceptance script",
  "tools": [
    {
      "name": "count",
      "description": "count words and characters",
      "capability": "process.exec",
      "command": ["python3", "count.py"],
      "inputs": {"text": {"type": "string", "description": "text to measure"}},
      "required": ["text"]
    }
  ]
}
JSON

say "installing records the manifest and its hash; nothing runs, nothing runs yet"
run extensions install "$EXT"
run extensions list
run extensions call wordcount count --arg "text=one two three"

say "trust and enable are separate acts"
run extensions trust wordcount
run extensions enable wordcount
run tools list
say "and the tool still needs its capability"
run extensions call wordcount count --arg "text=one two three"
APPROVAL4=$("$CLI" approvals list --json | jq_ "[a['id'] for a in d if a['capability']=='process.exec'][0]")
run approvals approve "$APPROVAL4"
run extensions call wordcount count --arg "text=one two three"

say "the trusted tool survives a restart because the decision is in the database, not memory"
"$CLI" config set permissions.default_duration persistent >/dev/null
"$CLI" permissions grant process.exec --subject ext.wordcount.count --duration persistent --confirm >/dev/null
run extensions call wordcount count --arg "text=persisted across processes"

say "the extension cannot leave its own directory: an absolute data path is refused"
BAD="$HOME_DIR/extensions/escapee"
mkdir -p "$BAD"
printf 'print("x")\n' > "$BAD/x.py"
cat > "$BAD/extension.json" <<JSON
{"name": "escapee", "version": "0.1.0",
 "tools": [{"name": "leak", "capability": "process.exec",
            "command": ["python3", "/etc/passwd"], "inputs": {}}]}
JSON
run extensions install "$BAD"

say "the optional MCP server is off until asked for"
"$CLI" config set mcp.server_tools 'fs.read,fs.list,archx.info' >/dev/null
run mcp serve --transport stdio
"$CLI" config set mcp.server_enabled true >/dev/null

say "expose this workspace over MCP, then drive it with our own client (a real subprocess)"
printf 'written by the m23 acceptance run\n' > "$WORK/shared.txt"
run mcp add self --command "$CLI" --arg=--home --arg "$HOME_DIR" --arg mcp --arg serve --arg=--transport --arg stdio
run mcp sync self
run mcp trust self
run mcp enable self
run mcp sync self

say "one call needs two independent grants: the client's mcp.call, and the server's fs.read"
run mcp call self fs.read --arg path=shared.txt
APPROVAL5=$("$CLI" approvals list --json | jq_ "[a['id'] for a in d if a['capability']=='mcp.call'][0]")
run approvals approve "$APPROVAL5"
run mcp call self fs.read --arg path=shared.txt
say "the server (a separate process, same database) queued its own request: the caller is 'mcp-server'"
run approvals list
SERVER_APPROVAL=$("$CLI" approvals list --json | jq_ "[a['id'] for a in d if a['capability']=='fs.read' and a['subject']=='mcp-server'][0]")
run approvals approve "$SERVER_APPROVAL"
run mcp call self fs.read --arg path=shared.txt

say "a non-whitelisted tool is not exposed by the server at all"
run mcp call self fs.write --arg path=x.txt --arg content=nope

say "every discovery, decision and call is traced"
run trace list --kind mcp --limit 8
run trace list --kind permission --limit 6
run tools runs --limit 8

say "database integrity after all of it"
run db check

say "done"
echo "home: $HOME_DIR"
