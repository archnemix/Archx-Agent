# MCP and extensions

Archx Agent speaks MCP as a **client** (its own tools can be supplemented by servers you
configure) and, optionally, as a **server** (a whitelist of its tools exposed to another
MCP client). Extensions add tools from a directory with a manifest. Both go through the
same permission centre as the built-in tools.

The original MCP transcript is [historical evidence](VERIFICATION.md#m23-acceptance).
Current transport hardening and its verification are tracked in [the plan](../PLAN.md) and [progress](../PROGRESS.md);
that old transcript does not certify every current failure or cancellation path.

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
useful, but **not harmless**: stdio discovery starts a chosen program with the current
OS permissions and inherited environment/credentials; HTTP discovery sends real requests.
Tool-call trust and grants do not sandbox the discovery program.

### Transports

| transport | how | details |
|-----------|-----|---------|
| `stdio` | `mcp add NAME --command PROG --arg ...` | byte-bounded UTF-8 line-delimited JSON-RPC; bounded stderr diagnostics; POSIX group termination on close/timeout, Windows direct child only |
| `http` | `mcp add NAME --transport http --url https://... [--header Name=value]` | JSON-RPC over POST; accepts `application/json` or `text/event-stream` responses; echoes `Mcp-Session-Id` |

Implementation: `adapters/mcp_client/`. Public imports remain the same. `records.py`
owns tool/result records, `base.py` owns RPC IDs, pending calls, queues and deadlines,
`surface.py` interprets MCP results/discovery, and `stdio.py` / `http.py` own wire I/O.
No adapter decides trust or grants; `managers/mcp/` owns configured/discovered state.

#### Deadlines, limits and shutdown

Requests start their caller deadline **before sending**, using
`mcp.client_timeout_seconds` (default 20 seconds) or a positive finite per-call override.
A serialized background sender keeps a blocked pipe write or HTTP exchange outside the
waiting caller. Input serialization/validation and best-effort cleanup add overhead; this
is not CPU preemption or an OS-level hard wall-clock kill. A request timeout **closes that client and fails its pending calls**;
it is not a promise that the server stopped work. The manager closes failed discovery
connections and dead cached clients, then creates a fresh connection on a later explicit
operation. It does not automatically replay the failed call, restore sessions, or undo
external side effects. Ordinary remote tool errors do not themselves kill a healthy
connection.

Embedding callers can set `max_message_bytes` (default **8,000,000 bytes**) and
`max_pending` (default **32**) on either transport; the CLI uses defaults. Both incoming
messages/HTTP bodies and outgoing JSON are byte limited. Stdio stdout is strict UTF-8:
oversized/invalid JSON or malformed RPC is a protocol failure, not an ignored line followed
by an unexplained timeout. Stderr is a rolling **200 diagnostic entries**, each drawn from
at most a **4,096-byte chunk**; very long diagnostic lines are split, not retained whole.
It is a bounded diagnostic tail, not a complete stderr transcript. The outbound queue is
also bounded; excess work gets an explicit error. Closing drops queued work and wakes
pending calls. Idle sender threads retire.

On POSIX, stdio servers start in a new session and close/timeout kills their ordinary
process group; Windows only kills the direct process. Raw binary pipes avoid waiting for
buffered-reader locks during shutdown. Deliberately detached descendants, changed OS
permissions or uninterruptible I/O are not contained. A detached descendant holding a pipe
can leave a daemon reader behind until EOF. HTTP DNS/header operations may also outlive
the waiting caller's deadline: Python cannot forcibly cancel every underlying OS/resolver
operation. These limits are not OS isolation, a global resource quota or Windows
certification.

HTTP error diagnostics read only a 300-byte prefix (or the smaller message budget).
Ambiguous response framing and EOF before the declared Content-Length are refused, even
when the received prefix is valid JSON. Complete chunked responses remain supported.
Invalid UTF-8/JSON/SSE fails clearly. Refused redirect responses are closed before storing
the error, avoiding response retention through exception frames. **HTTP redirects are refused**, including same-origin
redirects: configure the final endpoint rather than silently forwarding configured
credentials. URL-embedded credentials and invalid headers are refused. Session headers
are serialized with the corresponding exchanges. Only finite SSE response bodies are
supported; this is not a long-lived subscription, resumable stream, or durable MCP session.
Notifications are queued best-effort and are not acknowledged tool results.

Server→client `ping` is answered with `{}`; unknown methods get `method not found`.
Those responses do not execute local tools. Notifications with valid envelopes are ignored.

### Discovered tools

Each discovered tool becomes a registry entry:

```
name        mcp.<server>.<tool>          (names are sanitised for the CLI)
capability  mcp.call                     (medium risk: calls a third-party server)
risk        medium when the server is trusted, high otherwise
inputs      derived from the tool's JSON Schema (string/integer/number/boolean/object)
origin      mcp:<server>
```

Tool, resource and prompt discovery follows unique pagination cursors, with **100 pages**,
**10,000 items**, an **8,000,000-byte aggregate re-serialized collection budget** by default,
and one timeout budget for the complete list operation. An embedding caller's
`max_message_bytes` also controls that aggregate budget. Over-budget/cyclic/malformed
collections are refused, not silently treated as complete. Duplicate tool names and
registry-name collisions after sanitization are refused before manager updates. This
preflight does not make later SQLite/registry I/O failures transactionally atomic.
Only the documented JSON Schema input subset is translated to registry inputs, not a
complete JSON Schema validator.

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
archx-agent mcp serve --transport stdio     # or: --transport http (configured host/port)
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

HTTP serves `/` and `/mcp`, closes every response, and requires one valid Content-Length;
transfer encoding and ambiguous framing are refused. The default request budget is
8,000,000 bytes with a 10-second socket inactivity timeout (not a total operation deadline).
Invalid UTF-8/deep JSON, non-object RPC/params and truncated bodies fail explicitly before
tool dispatch. Oversized responses are replaced by a small error, not streamed without a
limit. Stdio uses bounded binary line reads, stops after oversized input rather than
interpreting its tail, and reports malformed input without executing it.

Unauthenticated loopback serving remains supported. **Non-loopback binds require a bearer
token**, supplied by an embedding caller's `serve_http(token=...)` or CLI
`--token-env NAME`. Put the value in that environment variable; do not put it in the
command line. Empty/invalid values are refused. Tokens protect requests including GET;
the same `mcp-server` permission subject/whitelist still applies, not per-person accounts.
CLI omitted host/port now use `mcp.server_host` / `mcp.server_port`. No TLS, public-service
certification, global request quotas or transactional rollback of tool side effects is
provided. Protect a private endpoint even when a token is set.

`interfaces/mcp_server/` separates protocol/schema, dispatch/policy, HTTP and stdio.
`managers/mcp/` separately owns records, configuration, journalled writes, connection
cache, discovery, registry restoration and invocation/status. Public imports and wildcard
exports are preserved. Extension manifest validation lives in
`managers/extensions/manifest.py`, apart from installation, trust/lifecycle, registry and
journalled writes. The transport does not grant permissions.

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
failed run. The shared process runner spools input/output to temporary files and reads
at most the configured byte prefix plus a truncation sentinel. Oversized stdout is
**refused**, not parsed as a clipped JSON prefix; invalid UTF-8/deeply malformed JSON
is an extension error. Clipped stderr is marked `stderr_truncated`. Positive integer
size/timeout limits are required, including per-call overrides.

On timeout the POSIX process group is killed; Windows kills only the direct process.
Detached children, or children intentionally left running after the direct process exits,
can survive. There is **no hard spool disk quota or OS filesystem sandbox**. A rebuilt
environment does not revoke the process's OS permissions. Only run extensions you trust.

## Records and settings

| table | contents |
|-------|----------|
| `mcp_servers` | transport, command/url, raw env/header maps for connection use, trust, enabled, protocol, status/error and tool count; standard record serialization shows env/header keys only |
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
record serialization prints their **keys**, not encrypted values. The raw values can
also be present in SQLite write journals/backups; protect the whole home directory. Provider API keys still belong in
`secret://env/NAME` references (M20), which MCP servers inherit from their own environment.

## Limits, stated plainly

* No production public MCP service: non-loopback binds now require an explicit bearer
  token, but TLS, per-person authorization and global admission/rate quotas are not supplied.
* No OAuth / dynamic client registration for HTTP servers - use a static `--header`.
* Sampling, elicitation and prompt execution are not implemented. The client can list
  prompt metadata; the Archx server does not expose prompts.
* An extension's capability gates **the tool call**, not every syscall its program makes.
  A trusted extension that writes files can do so inside its own directory without an
  `fs.write` grant. Rebuilding its environment does **not** block paths such as the
  `~/.archx` database: an extension can access files allowed to its OS account, invoke
  interpreters and spawn processes. Trust review is not an OS filesystem sandbox.
* No signature verification of extension manifests; the hash is recorded so a change is
  visible, not so authenticity can be proven.
