# Test Archx Agent on your computer

## 1. Use the current source

Use the source archive provided with this conversation and extract `Archx-Agent`, or use
a checkout that actually contains these changes. They have not been published as an
installer or pushed by this testing-guide update. Cloning an older `main` is not equivalent.
Work inside the extracted directory containing `pyproject.toml`.

Requirements: Python **3.11 or newer**, a terminal and a browser. Installation downloads
build/development packages from PyPI. The core GUI needs neither Node.js nor an npm build.
Do not use administrator/root privileges. Keep your GUI on loopback and its token private.

## 2. Install

### Linux/macOS, or Linux inside WSL

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
archx-agent --version
```

On some Linux systems you must install your distribution's Python venv package first.
macOS/native Windows are not covered by the latest Linux platform certification.

### Windows PowerShell

```powershell
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\archx-agent.exe --version
```

Check that the selected Python is at least 3.11. In subsequent commands, replace
`archx-agent` with `.\.venv\Scripts\archx-agent.exe`. Activation is optional; you do not
need to change PowerShell execution policy just to use the executable directly.
For Bash acceptance procedures and POSIX process checks, use a Linux/WSL environment;
that recommendation is about compatibility, not WSL being a security sandbox.

## 3. Safe offline demo — no AI model required

Use a separate `demo-home` directory. This creates real app data but keeps your exploration
apart from your normal home. **The scripted model is simulated, not intelligence or inference.**

```bash
archx-agent --home ./demo-home init
archx-agent --home ./demo-home models add-scripted --name simulated-demo
archx-agent --home ./demo-home --allow-simulated chat --model simulated-demo --message "Hello, this is a local interface test"
archx-agent --home ./demo-home memory add --kind permanent --category preference --title "Metric units" --content "Always use metric units"
archx-agent --home ./demo-home search metric --no-files
archx-agent --home ./demo-home tasks list
archx-agent --home ./demo-home --allow-simulated gui serve --open
```

Expected observations:

- `init` prints paths for config, database and traces, plus schema version 31.
- The chat reply explicitly says `[SIMULATED]` and that no model ran.
- Search finds the stored metric-units memory. Keyword-only/degraded notices without an
  embedding index are expected, not evidence of semantic search.
- Tasks lists the chat turn. In the GUI, inspect Chat, Memory, Tasks and Status.
- Open the local URL/token link printed by the server. If the browser does not open,
  copy that printed link yourself. The default address is `127.0.0.1:8765`.
- Stop with Ctrl+C. Restart the same GUI command and check memory/history persistence.
  A fresh GUI token is expected; do not reuse the old process's token.
- If port 8765 is occupied, add `--port 0` and use the chosen URL it prints.

These core CLI commands were exercised on the current source in a disposable Linux home.
They are not proof of native Windows/macOS or real-model operation. The documented
architecture/worker quick-check command also passed 322 tests in the fresh core/dev
environment (4.68s), without installing the vendor-SDK extras.

## 4. Test real AI using an existing local server

For example, start a model in LM Studio's OpenAI-compatible local server. Use the actual
port and model identifier shown by that server; this app does not download/start it for you.
Ollama or llama.cpp server can also provide a compatible endpoint with different ports/IDs.

```bash
archx-agent --home ./real-ai-home init
archx-agent --home ./real-ai-home models add-http --name local-ai --base-url http://127.0.0.1:1234 --model YOUR_ACTUAL_MODEL_ID
archx-agent --home ./real-ai-home models list
archx-agent --home ./real-ai-home chat --model local-ai --message "Explain the difference between RAM and disk storage."
archx-agent --home ./real-ai-home gui serve --open
```

Do not pass `--allow-simulated` for this test. Use a separate home so the demo model cannot
be mistaken for the real one. Confirm the model server actually received the request.
A connection/refusal message means setup failed, not that AI inference was verified.
Cloud providers are also supported but require credentials, recorded privacy/consent and
explicit remote permission; see [PROVIDERS.md](PROVIDERS.md). Never paste API keys in chat.

## 5. What to try and what not to assume

| Area | What you can test now | Important limit |
|---|---|---|
| Chat/models | Real local/approved remote model connection, streaming, saved conversations | Requires an actually working model; simulated mode is not AI |
| Memory/search | Store/retrieve memories, search across supported records | Default hashing/keyword retrieval is not established semantic-model quality |
| Tasks/versions | Inspect task history, artifacts and reproduction information | A recorded reproduction assessment is not a guarantee of exact replay |
| Tools/access | Attempt a tool, inspect an approval, grant/deny deliberately | Do not approve arbitrary shell/file actions in your real directories |
| Jobs/workflows | Queued work, status, pause/resume and workflow records | Local commands execute with your account's authority |
| Coding/experiments | Sessions, file diffs, permissioned commands and declared metrics | Not a full IDE or autonomous scientific researcher |
| Play | Tic-tac-toe, Connect Four and Nim; rules and replay | Not general game-playing AI |
| Learning | Goals, items, hints, exact/self assessment and schedules | AI/rubric grading is not implemented |
| Research | Analyse existing local/supplied sources and inspect citations | Autonomous web-search AI chat is still unimplemented |
| Voice/media | Supported file measurements and human transcripts | No speech recognition or synthesis |
| Datasets/training | Text corpus preparation and small CPU trainers | No transformer fine-tuning/GPU training |
| Remote/execution | Explicit authenticated workers and supported execution wrappers | No managed cloud, durable worker recovery or OS isolation guarantee |
| Scenes/automations | Primitive scenes/exports and configured triggers | Real rendering needs Blender setup; automation service depth is limited |

Use `archx-agent COMMAND --help` for each area; detailed guides are indexed in
[DOCUMENT_GUIDE.md](DOCUMENT_GUIDE.md). The [feature inventory](FEATURE_STATUS.md) lists
31 roadmap units implemented within recorded scope and ten partial areas; that is not
31 fully accepted original user features.

## 6. Optional automated tests

Inside the same virtual environment:

```bash
python -m pip install -e '.[dev]'
python -m pytest tests/architecture tests/features/test_worker_policy.py
python -m pytest
```

For the optional vendor-client matrix, install `'.[dev,sdks]'` before running the full suite.
Some process/backend tests need Linux tools and Bash; errors/skips without optional
packages are not equivalent to the recorded full Linux environment. Bash acceptance
scripts create disposable homes and can launch workers, servers and shell commands;
review them first and run only in a suitable development environment. `scripts/release_check.sh`
also needs build/wheel/setuptools tools. The preceding recorded runtime gate passed
2,616 tests; this guide does not claim a fresh full-suite/platform run.

Source archives omit `.git` and credentials. Git-based inventory/CI helper scripts need
a local Git repository (for example, `git init` in your extracted test folder); ordinary
app use and the documented quick-check test selection do not need repository history.


## Updating an existing Windows installation with the chat correction

The corrected bundle is named **archx-agent-chat-redesign.zip**. It supersedes the earlier
local-test bundle, but your workspace is separate from the source. Stop `gui serve` with
Ctrl+C before replacing code. Keep your existing `real-ui-home` directory and `.venv`;
never overwrite/delete that workspace to obtain a UI update.

Extract the new archive into a separate directory first, then copy its `Archx-Agent`
contents over the project containing `pyproject.toml`. The archive excludes `.venv`,
workspace databases and credentials. From your existing activated PowerShell environment:

```powershell
python -m pip install -e .
archx-agent --home .\real-ui-home gui serve --open
```

Open the newly printed token URL and use Ctrl+Shift+R if the browser still shows the old
layout. You should see one conversation sidebar, Tools & workspaces collapsed, a model
dropdown at the top and right-aligned user messages. Select your existing `local-ollama`
entry and send a new message. Routine retrieval notes are under Conversation details.
Model thinking appears only if your model emits reasoning fields or a leading think block;
old turns cannot recover previously discarded thinking. Nothing in this update requires
re-downloading your model or enabling simulated inference.

The Arena live preview is a separate **simulated demo workspace**, not your Ollama server.
Its test fixtures and screenshots verify UI behaviour, not answer quality or native Windows
inference. Your previous real Ollama replies remain evidence from your own machine.
