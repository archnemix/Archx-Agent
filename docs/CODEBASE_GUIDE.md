# Codebase guide — a simple map

This guide explains where to look without assuming you already know the architecture.
For dependency rules, internal composition and review instructions, use the
[technical reviewer guide](TECHNICAL_REVIEW.md).

## The five main places

| Folder | What it owns | What it should not do |
|---|---|---|
| `src/archx_agent/interfaces/` | CLI commands, browser endpoints and MCP entry points | Invent a second implementation of business rules or write domain SQL |
| `src/archx_agent/application/` | Coordinate a user operation across models, tools and stored records | Treat a plan or a scheduled job as permission to execute |
| `src/archx_agent/managers/` | Domain records, validation, queries and durable writes | Own HTTP pages, command-line parsing or application startup |
| `src/archx_agent/adapters/` | Speak to model runtimes, vendor clients and external tools | Decide the user's privacy or task policy |
| `src/archx_agent/helpers/` | Shared configuration, storage, paths, errors and small reusable primitives | Become a miscellaneous home for feature-specific logic |

Think of an operation as **screen or command → application service → permissioned tool
or domain manager → storage/external system**. Different operations use different parts
of that path; there is not one universal call chain.

## Inside a feature folder

A large feature is now a package, rather than one long Python file. For example:

```text
managers/memory/
  __init__.py       familiar public imports
  manager.py        compose the manager and shared configuration
  records.py        the record objects and database-row conversion
  constants.py      the memory vocabulary and limits
  writes.py         transaction handlers
  creation.py       validate and create a memory
  queries.py        lookup and search
  ranking.py        similarity calculations
  lifecycle.py      edits, history, retention and artifact handling
  retrieval.py      choose memory for a model's context budget
  learning.py       learning events and learner summaries
```

These parts share the same manager instance. They are not separate databases or
independently deployed services. The technical guide explains this deliberate
compatibility choice.

The same pattern is used where useful for context, learning, providers, tasks,
permissions, jobs, tools, workflows, the model catalogue and conversations. HTTP
model access and local file/command tools also have their own responsibility folders. Small, cohesive modules remain files; a feature
does not need a package just to match its neighbours.

## Where should I start?

| I want to understand… | Start here |
|---|---|
| How a home/database opens | `application/workspace/lifecycle.py` |
| Which services the workspace makes available | `application/workspace/services.py` |
| Local model files, remote registrations and capability records | `managers/models/` |
| Conversation messages, search, exports and settings | `managers/conversation/` |
| HTTP model responses and connection failures | `adapters/http_runtime/`, then `adapters/chat_payloads.py` |
| External MCP server connection, framing and timeouts | `adapters/mcp_client/`, then `managers/mcp/` for configuration/trust |
| Remote training worker, its HTTP requests and file transfer | `application/remote_worker/` |
| Local file/command limits and timeout handling | `adapters/local_tools/` |
| Model privacy checks and runtime construction | `application/workspace/models/` |
| Extension installation, manifests and trust | `managers/extensions/` |
| Task reproduction assessment and captured history | `managers/reproduction/` |
| Serving local tools over MCP | `interfaces/mcp_server/` |
| Memory creation, search or prompt injection | `managers/memory/` |
| The context-window algorithms | `managers/context/strategies/` |
| Why a tool was refused | `managers/permissions/decisions.py`, then `managers/tools/execution.py` |
| Queueing, cancellation or recovery | `managers/jobs/`, then `application/scheduler.py` |
| A research report and its citations | `application/researcher/` |
| Coding sessions, edits or commands | `application/coding/` |
| Dataset scan, cleanup, splits or exports | `application/datasets/` |
| The two small CPU trainers | `application/training/` |
| Mesh creation, measurements or export bytes | `application/geometry/` |
| Actual Blender execution | `application/scenes/`, then `application/execution/` |
| One vendor client's API shape | `adapters/sdk_transport/vendors/` |
| A CLI command | `interfaces/cli/commands/` |
| A browser endpoint or view | `interfaces/gui/routes/` or `interfaces/gui/assets/view-*.js` |
| A schema change | `managers/schema/__init__.py`, then its numbered migration file |

## Tests are grouped too

`tests/` now has nine suites: architecture, foundation, knowledge, models, interfaces,
tools, workflows, features and system. Shared fixtures stay in `tests/conftest.py`;
`tests/paths.py` supplies paths independently of a test's folder depth. Protocol fixtures
stay in `tests/fixtures/`.

A feature suite can include real files, databases, CLI calls or loopback HTTP services.
“Feature” does not mean “unit tests only.” System tests cover cross-feature integration,
stress, hostile-client and release behaviour.

## Documentation and evidence

- [Document directory](DOCUMENT_GUIDE.md): names and explains every document.
- [Audit report](AUDIT.md): changes, verification and honest remaining work.
- [Known gaps](../GAPS.md): absent capabilities and unverified platforms.
- `docs/audit/`: compact inventories and measured check/coverage results.
- `docs/verification/` and `docs/reports/`: historical evidence, not today's guarantees.

Modular code does not mean the product has acquired missing capabilities. Speech,
transformer fine-tuning, a general 3D editor and managed cloud provisioning are still
separate work; moving code into packages does not implement them.

## What the runtime follow-up changed

A broken model reply now produces a clear model-output error rather than an unrelated
Python crash. Quota failures are not retried as if they were temporary rate limits.
A failed native-model replacement no longer leaves the old model marked as loaded.
Local commands write their output to temporary files, and only a small prefix is read
into memory. This avoids unlimited memory capture, but **does not limit disk growth or
make commands safe to run from untrusted users**. Real native-model inference and
Windows process-tree handling still need separate validation.

The [audit](AUDIT.md#runtime-and-domain-continuation) distinguishes the latest results
from the earlier successful runs and distinguishes fixed findings from remaining risks.

## Settings, model files and restart recovery

Conversation settings now keep separate keys instead of overwriting the last one.
Existing homes upgrade through schema v31 and keep the value that survived the old
bug; previously lost values cannot be reconstructed. On restart, saved write intents
are replayed only after the managers that know how to apply them are registered.

Model discovery refuses directories, notices tiny/restored replacements and remembers
when you deliberately disabled a model. Changed file observations invalidate old
capability proof without deleting its history. File size and filenames still do not
prove that a model can answer a question. See [routing](ROUTING.md) for hashing and
snapshot limits. [The maintenance audit](AUDIT.md#documentation-first-maintenance)
records this follow-up's tests rather than reusing earlier successful results.

## Extension and remote-worker safety

Extensions, local tools and worker commands now share the small process helper that
keeps output memory bounded. It does not decide permissions and does not make code safe
to run from strangers. An extension's whole JSON response must fit its byte limit;
a clipped prefix is never silently accepted as a full answer.

The remote worker has separate files for training, input checks, commands, file transfer,
HTTP and server startup. Bad request bodies and escaping file paths are refused before
work. File and scan budgets are explicit, and a result records the accepted input digest
before computing its own digest. Worker jobs still disappear on restart. See
[remote compute](REMOTE.md#72-request-transfer-and-artifact-safety) and
[the latest safety audit](AUDIT.md#extension-and-worker-safety-continuation) for the
actual limits and results, including why this is not an OS sandbox.

## MCP connections and discovery

The MCP client is now a small folder with separate records, request tracking, tool/result
interpretation and stdio/HTTP transports. A stalled send no longer gets to postpone the
caller's timeout. Bad/oversized messages fail clearly, and diagnostics are bounded rather
than storing a never-ending line. Failed discovery closes its connection instead of
leaving a broken cached client around.

Discovery can now follow several result pages without silently dropping later tools.
Repeated cursors, oversized lists and tool names that collapse to the same registry name
are refused. HTTP redirects are refused so configured credentials are not silently sent
to a different destination. Use the final URL. Starting a chosen MCP program still gives
it the current OS permissions and inherited environment: discovery is not harmless.
A timeout also cannot prove a remote action stopped or was undone. See [MCP](MCP.md) and
[the current audit](AUDIT.md#mcp-transport-lifecycle-continuation).

## Broad manager and browser cleanup

MCP, extension and reproduction managers now have small responsibility folders instead
of mixed 640–687-line files. Their original 75 manager methods and 13 global definitions
are checked against captured ASTs, not rewritten while moving them. Installation, trust,
connections, journalled writes and reproduction assessment/history have named owners.
The optional MCP server separates policy/schema from HTTP and stdio and now validates
framing and bearer authentication before dispatch.

Chat no longer automatically sends a second POST when a stream ends without its final
result. It retains partial output, warns that completion is unconfirmed and asks the user
to refresh history before retrying. Concurrent submissions on the same page are ignored
until the current request settles. This is not an idempotency key, cancellation service
or proof that a disconnected model turn stopped. Browser fault tests cover a missing
final frame, read failure, missing stream reader and successful completion.

## The remaining large owners now have named parts

- Router: candidate eligibility/scoring, selection and actual capability probes.
- Agent: run-loop orchestration, individual/subagent steps, planning and budget/result records.
- Learning tutor: practice, scheduling/sessions, planning and reports. This does not add model grading.
- Scenes: document storage, primitive editing/measurement, exports/verification and rendering.
- Experiments: catalogue/lifecycle, command execution/journals and metric parsing/comparison.
- Research records: queries, lifecycle, source persistence and transaction handlers. Source gathering remains in the researcher.
- GUI: socket-free API/authentication, HTTP framing/SSE, server lifecycle and public compatibility imports.
- Learning/models CLI: separate argument grammar, workspace dispatch and operation groups.

These are responsibility moves, not new speech, fine-tuning, cloud or Blender features.
The fixed cleanup ledger lists 36 named originals: 27 previously accepted and these nine.
Its percentage counts accepted modules equally; it is not effort-weighted or overall product completion.

## Worker credentials and capacity in plain English

A worker that can run commands must have a token. A worker listening beyond numeric
loopback must have one too. A training-only worker on `127.0.0.1` may still run without it.
Use `remote worker --token-env NAME` rather than placing the secret in the command itself.
The environment variable must already exist; do not paste its value into screenshots/logs.

The worker defaults to four running training jobs and 128 retained job/result records.
It refuses new jobs when full; it does not silently throw old results away. Collect results
before a planned restart, because they live in memory. Limits do not constrain shell
commands or make their OS account a sandbox. Implementation: `remote_worker/policy.py`
for credentials/binding, `worker.py` for admission/state, `http.py` for authenticated HTTP.


## Finding the chat correction

- `application/chat.py` coordinates a turn, routing and saved messages.
- `application/chat_stream.py` collects answer and reasoning streams, without owning routing.
- `adapters/reasoning.py` validates returned reasoning fields and separates leading think tags.
- GUI `assets/view-chat.js` owns conversation/model controls and transcript rendering.
- GUI `assets/chat.css` owns chat layout; `assets/style.css` owns shared navigation/components.
- `tests/interfaces/test_chat_reasoning.py` checks provider-output plumbing over loopback
  sockets; `scripts/gui_chat_browser.mjs` checks desktop/mobile rendering in Chromium.

These are not separate chat engines: the CLI and GUI still use the same ChatService.
The browser test uses explicit provider-output fixtures, not a real model.
