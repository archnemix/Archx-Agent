# MCP and extensions

Archx Agent speaks MCP as a **client** (its own tools can be supplemented by servers you
configure) and, optionally, as a **server** (a whitelist of its tools exposed to another
MCP client). Extensions add tools from a directory with a manifest. Both go through the
same permission centre as the built-in tools.

Nothing in this document is aspirational: every behaviour described here has a test and a
transcript in [VERIFICATION.md](VERIFICATION.md#m23-acceptance).

## MCP client

### Server lifecycle

```
mcp add      -> a record: name, transport, program/URL. Nothing runs.
mcp sync     -> spawn/connect, initialize, tools/list. Tools are recorded either way.
               They are REGISTERED only if the server is trusted AND enabled.
mcp trust    -> "I know what this server is". Registers its recorded tools.
mcp enable   -> "use it for now". Registers its recorded tools.
mcp untrust  -> unregisters everything it advertised; calls fail with "no tool".
mcp remove   -> forgets the server and its tools.
```

Trust and enable are independent on purpose: discovering what a server would expose is
useful and harmless, while *calling* it is not.

### Transports

| transport | how | details |
|-----------|-----|---------|
| `stdio` | `mcp add NAME --command PROG --arg ...` | line-delimited JSON-RPC over the child's stdin/stdout; stderr is captured for error messages; the parent kills it on close |
| `http` | `mcp add NAME --transport http --url https://... [--header Name=value]` | JSON-RPC over POST; accepts `application/json` or `text/event-stream` responses; echoes `Mcp-Session-Id` |

Implementation: `adapters/mcp_client.py`. Requests have a deadline
(`mcp.client_timeout_seconds`, default 20s); a wedged server produces `MCPTimeoutError`
instead of a frozen CLI. Server→client requests are answered (`ping` with `{}`, anything
else with JSON-RPC `method not found`), so a server can never hang waiting on us. A server
that prints logs to stdout is reported as a protocol problem instead of being parsed as a
message.

### Discovered tools

Each discovered tool becomes a registry entry:

```
name        mcp.<server>.<tool>          (names are sanitised for the CLI)
capability  mcp.call                     (medium risk: calls a third-party server)
risk        medium when the server is trusted, high otherwise
inputs      derived from the tool's JSON Schema (string/integer/number/boolean/object)
origin      mcp:<server>
```

Calling one:

```bash
archx-agent mcp call fixture add --arg a=2 --arg b=40
# denied: mcp.call is not granted for 'mcp.fixture.add'; approval ap_… is pending
archx-agent approvals approve ap_…
archx-agent mcp call fixture add --arg a=2 --arg b=40      # -> "42"
```

A remote tool that returns `isError: true` is a **failed run** with the remote message, not
a success with an empty result. Every attempt lands in `tool_runs` and in the trace
(`mcp`, `permission`, `tool_call`).

## The optional MCP server

```bash
archx-agent config set mcp.server_enabled true
archx-agent config set mcp.server_tools fs.read,fs.list,archx.info
archx-agent mcp serve --transport stdio     # or: --transport http --host 127.0.0.1 --port 8848
```

* **Off by default.** `mcp serve` refuses with the exact command that would enable it.
* **Whitelist, not the registry.** Only `mcp.server_tools` are listed or callable; a client
  asking for anything else gets a JSON-RPC error naming what *is* exposed.
* **The caller is a distinct subject.** Every call goes through the tool manager with
  `permission_subject="mcp-server"`. A grant the user made for their own `fs.read` does not
  authorise a remote client; a human must grant `fs.read` to `mcp-server` (or approve the
  request the server queues).
* **stdio keeps stdout clean** - protocol only, log lines on stderr.

Implemented methods: `initialize`, `ping`, `tools/list`, `tools/call`. Everything else is
`method not found`. Resources and prompts are not exposed yet.

The acceptance run drives this server with the project's own MCP client from a real
subprocess, so the two halves are verified against each other.

## Extensions

An extension is a directory:

```
my-extension/
  extension.json
  tool.py
```

```json
{
  "name": "wordcount",
  "version": "1.0.0",
  "description": "count words in text you give it",
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
```

The program reads one JSON object on stdin and prints one JSON object on stdout:

```json
{"extension": "wordcount", "tool": "count", "arguments": {"text": "one two three"}}
```
```json
{"words": 3, "characters": 13}
```

### Install → trust → enable

```bash
archx-agent extensions install ./my-extension     # records the manifest + sha256; nothing runs
archx-agent extensions trust wordcount           # registers the tools
archx-agent extensions enable wordcount          # makes them available
archx-agent extensions call wordcount count --arg "text=one two three"
# denied: process.exec is not granted for 'ext.wordcount.count'; approval ap_… is pending
```

Reinstalling with a *changed* manifest resets trust (the manifest hash changes); installing
the identical manifest twice is refused rather than silently overwriting.

### What a manifest cannot do

| attempt | result |
|---------|--------|
| name a capability this build does not know | `ExtensionError` naming the known set |
| lower the risk of a capability | ignored: the capability's risk is canonical |
| ship a data path outside its own directory | refused (absolute or `../` escape) |
| use an entry type other than `process` | refused, with the supported list |
| declare a required argument that is not an input | refused |
| duplicate a tool name | refused |
| run before the user trusts it | tools are simply not registered |

`argv[0]` may be any program on the machine (an interpreter, typically) - that is what
trusting means. Everything after it is treated as data and must stay inside the extension.

### Execution

An extension tool runs as a subprocess with a **rebuilt** environment (`PATH`, `HOME` = the
extension directory, `LANG`, `LC_ALL`, `TMPDIR`), no shell, `tools.timeout_seconds` and a
capped output. Exit code ≠ 0, non-JSON output or a timeout is a clear error, recorded as a
failed run.

## Records and settings

| table | contents |
|-------|----------|
| `mcp_servers` | transport, command/url, env/headers KEYS only, trust, enabled, protocol, last status/error, tool count |
| `mcp_tools` | discovered tools per server, capability, risk, schema, callable flag |
| `extensions` | manifest, sha256, trust, trusted_by/at, enabled, notes |
| `extension_tools` | each declared tool with its capability, risk and entry |

| setting | default | meaning |
|---------|---------|---------|
| `mcp.client_enabled` | true | allow configured client servers |
| `mcp.client_timeout_seconds` | 20 | request deadline |
| `mcp.server_enabled` | **false** | expose tools as an MCP server |
| `mcp.server_tools` | `fs.read, fs.list, archx.info` | the server whitelist |
| `mcp.server_host` / `mcp.server_port` | 127.0.0.1 / 8848 | HTTP bind |
| `extensions.enabled` | true | allow trusted extensions to register tools |
| `extensions.directory` | `<home>/extensions` | where `install` looks when given a name |

Secrets: a server's `env`/`headers` values are stored so the process can start, but the CLI
only ever prints their **keys**. Provider API keys still belong in
`secret://env/NAME` references (M20), which MCP servers inherit from their own environment.

## Limits, stated plainly

* No remote-hosted MCP **server**: ours binds loopback by default and does not implement
  authentication.
* No OAuth / dynamic client registration for HTTP servers - use a static `--header`.
* Sampling, elicitation and prompts are not implemented on either side.
* An extension's capability gates **the tool call**, not every syscall its program makes.
  A trusted extension that writes files can do so inside its own directory without an
  `fs.write` grant; it cannot read your `~/.archx` database because the process runs with a
  rebuilt environment and no path to it - but it *is* an ordinary process on your machine.
  Trust accordingly.
* No signature verification of extension manifests; the hash is recorded so a change is
  visible, not so authenticity can be proven.
