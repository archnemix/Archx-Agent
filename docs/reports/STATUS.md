# Status report — SDKs, CI, and what is left

Written at the end of the request that asked for: a GitHub-Actions setup driven by editing a file
(rather than by an Actions token) whose every step's output lands in a readable folder; more
vendor SDKs driven against a real model; then an itemised list of the remaining features, with
implementation and a report.

Everything below is either **observed in this environment** or explicitly marked
**written but not executed**. There is no third category.

---

## 1. What is done

### 1.1 Eight official SDK clients, one contract

| sdk | package | wire shape | key needed |
|-----|---------|-----------|------------|
| `openai` | `openai` | OpenAI chat completions | yes |
| `anthropic` | `anthropic` | Messages | yes |
| `google` | `google-genai` | `generateContent` | yes |
| `mistral` | `mistralai` | OpenAI-ish | yes |
| `groq` | `groq` | OpenAI, base must include `/openai/v1` | yes |
| `together` | `together` | OpenAI, base must include `/v1` | yes |
| `cohere` | `cohere` | `POST /v2/chat` via `ClientV2` | yes |
| `ollama` | `ollama` | `POST /api/chat`, `host=` not `base_url=` | **no, when loopback** |

`archx-agent models sdks` lists all eight with their env vars and installed/missing state;
`models add-sdk` registers one; `models probe` drives a real turn.

**The Ollama decision.** Seven vendors reject an anonymous request; a local Ollama daemon requires
the credential to be *absent*. So "has a key" cannot be the readiness rule. `SdkSpec.key_required`
states the vendor's rule, and the keyless path is allowed only while the endpoint is loopback:

* loopback + no key → `ready: a local Ollama needs no key (no data leaves this machine)`;
* remote + no key → refused before the socket opens, naming the variable;
* a model added as `local_only` and aimed at a remote host → refused by the privacy gate first.

### 1.2 Streaming, for real, through every client

`supports_streaming` used to be true while `stream()` returned one chunk. That is now false
advertising no longer: `SdkTransport.stream` has one parser per vendor, and eleven tests drive
each one against a loopback server speaking that vendor's syntax.

| client | how it streams | verified |
|--------|----------------|----------|
| openai / groq / together | `stream=True`, `choices[0].delta.content` | 4 tests |
| mistral | `chat.stream()` → chunks wrapped in `.data` | included above |
| anthropic | `messages.create(stream=True)` → `content_block_delta` | 1 test |
| google | `generate_content_stream` → POST `:streamGenerateContent` | 1 test |
| cohere | `chat_stream()` → `content-delta` events | 1 test |
| ollama | JSON lines, `message.content` | 2 tests (keyless included) |

Plus: a streamed 401 still classifies as `AuthDeniedError`, and `chat --stream` works end to end
through the CLI for all eight.

### 1.3 CI triggered by a file, monitored over git

```
edit .ci/trigger -> push -> .github/workflows/model-matrix.yml (18 steps)
                              -> $LOGDIR/NN-<name>.log per step + status.tsv + console.log
                              -> publisher pushes ci/runs/<id>/ to branch `ci-logs` every 45 s
./scripts/ci_logs.sh  <--------  read it back with plain git
```

* `run.sh` records `ok` / `FAIL(n)` per step and **never** aborts the job, so one run reports
  every problem; a final `verdict` step fails the run if any row is not `ok`.
* `scripts/ci_logs.sh --list | --run <id> | --tail N | --wait S` prints the status table, the
  console tail and the file list, exits 1 if a step failed and 3 if no run exists yet.
* The run itself: pytest, `models sdks`, a real llama.cpp server with SmolLM2-135M Q4_K_M
  (GGUF magic checked), one real completion → `model-proof.json`, `remote_model.sh` across every
  installed client, a **real Ollama daemon in Docker** (`ollama pull smollm2:135m`), and a
  Cloudflare quick tunnel driven by the OpenAI SDK.

---

## 2. What remains (itemised)

| # | Item | Why it is still open | Size |
|---|------|----------------------|------|
| ~~1~~ | ~~**Run the CI workflow once**~~ | **Done.** Four runs; #3 and #4 are green end to end. Evidence in `docs/ci/`, full folder on `ci-logs`. | closed |
| 2 | **A live call to a vendor's cloud API** | No vendor key is usable from here, and egress is restricted. What *is* proven now: real clients against a real model served on a runner, including a real Ollama daemon. What is not: reaching `api.openai.com`, `api.cohere.com`, and so on. | needs keys |
| ~~3~~ | ~~**Ollama through a real daemon**~~ | **Done.** `docker run ollama/ollama`, `ollama pull smollm2:135m`, client streamed 32 chunks, and the app probed it keyless (`state now verified`). | closed |
| ~~4~~ | ~~`models probe --capability tools`~~ | **Done.** The runtime offers a tool, parses the call, and the probe distinguishes a call from a prose reply. | closed |
| ~~5~~ | ~~**Streaming into the browser**~~ | **Done.** `POST /api/chat/stream` writes SSE for the same recorded turn; the page paints each chunk and swaps in the stored text at the end. | closed |
| 6 | **Dedicated templates for other OpenAI-compatible vendors** (Z.ai, DeepSeek, …) | They work today via `add-sdk --sdk openai --base-url …`; a template needs privacy terms I can source rather than invent. | small, needs a source |
| 7 | **M31 Coding workspace** | The next milestone in `PROGRESS.md`: editing, running and testing code under the permission centre, diffs as artifacts, reproducible tasks. | large |
| 8 | **Cohere against the real service** | It has no keyless mode at all, so its only proof is a live call (#2) or the `/v2/chat` stub already used. | blocked on #2 |

Nothing in this list is "implemented but untested" except item 1's runner steps, which are called
out as unexecuted everywhere they appear.

---

## 3. Tests that ran, in this environment

```text
$ .venv/bin/python -m pytest tests/ -o addopts="" -q
1251 passed, 1 warning in 289.42s (0:04:49)

$ .venv/bin/python -m pytest tests/test_sdk_m22.py -o addopts="" -q
61 passed, 1 warning in 37.1s

$ .venv/bin/python -m pytest tests/test_sdk_m22.py -o addopts="" -q -k Streaming
11 passed, 50 deselected in 8.62s

$ ./scripts/acceptance_sdk.sh
SDK acceptance: 86 checks passed

$ ./scripts/acceptance_gemini.sh
Gemini acceptance: 60 checks passed

$ ./scripts/acceptance_m29.sh
M29 acceptance: 55 checks passed
```

Three bugs the CI rehearsal found, which is why it exists: `run.sh` ended with `return` outside a
function (every step would have aborted), the publisher reused a fixed `/tmp/publish` across jobs,
and the verdict counted the `status.tsv` header as a failed step.

Four bugs the SDK work found: Groq and Together append `/chat/completions` to whatever base they
are given (so a bare origin yields `/v1/v1/...`); `Workspace.runtime_availability` demanded a
`secret://` reference for a local Ollama that needs none; `SdkChatRuntime.available()` had its own
key rule that ignored the loopback exception; and the five new provider templates were missing
`privacy_claims`, which `test_providers_m20` caught before a user could.

---

## 4. Verified vs not verified

**Verified by observation:** the 1258-test suite; 86 SDK acceptance checks over real sockets; 60
Gemini checks; 55 M29 checks; every streaming parser against a loopback server; the exact request
path of all seven HTTP clients (`TestPaths`) and that each default base plus that path equals the
vendor's public URL (`TestDefaults`); the keyless-local / key-required-remote split; the four
consent rungs applying to SDK models.

**Verified on GitHub, by running it:** four workflow runs, the last two green — a real
SmolLM2-135M Q4_K_M served on a CPU runner, four vendor clients answering and streaming against
it, a real Ollama daemon docker-pulled and driven by both its own client and by Archx, and a
Cloudflare quick tunnel with the OpenAI SDK through the public URL (`docs/ci/`).

**Not verified, and not claimed:** any vendor's live cloud service (no keys, restricted egress).
The loopback servers and the runner's local models prove the client side of every protocol; they
cannot prove what `api.openai.com` does today.
