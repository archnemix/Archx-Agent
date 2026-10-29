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
edit .ci/trigger -> push -> .github/workflows/model-matrix.yml (19 steps, 19 step logs recorded)
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
| ~~1~~ | ~~**Run the CI workflow once**~~ | **Done.** Six runs; #3-#6 are green end to end, #6 with the same 1282 tests as this sandbox. Evidence in `docs/ci/`, full folder on `ci-logs`. | closed |
| 2 | **A live call to a vendor's cloud API** | No vendor key is usable from here, and egress is restricted. What *is* proven now: real clients against a real model served on a runner, including a real Ollama daemon. What is not: reaching `api.openai.com`, `api.cohere.com`, and so on. | needs keys |
| ~~3~~ | ~~**Ollama through a real daemon**~~ | **Done.** `docker run ollama/ollama`, `ollama pull smollm2:135m`, client streamed 32 chunks, and the app probed it keyless (`state now verified`). | closed |
| ~~4~~ | ~~`models probe --capability tools`~~ | **Done.** The runtime offers a tool, parses the call, and the probe distinguishes a call from a prose reply. | closed |
| ~~5~~ | ~~**Streaming into the browser**~~ | **Done.** `POST /api/chat/stream` writes SSE for the same recorded turn; the page paints each chunk and swaps in the stored text at the end. | closed |
| ~~6~~ | ~~**Templates for other OpenAI-compatible vendors**~~ | **Done, without inventing terms.** `--template openai-compatible` requires a base URL and records the privacy block as "unknown - not transcribed", so the consent ladder does the work. Per-vendor terms still need a human. | closed |
| ~~7~~ | ~~**M31 Coding workspace**~~ | **Done.** Sessions on a directory inside the tool roots, every edit and command through the permission centre, diffs as artifacts, a recorded runner with replay, named checks, and an eleventh GUI panel. `docs/CODING.md`, `pytest tests/test_coding_m31.py` (66), `scripts/acceptance_m31.sh` (48). | closed |
| 8 | **Cohere against the real service** | It has no keyless mode at all, so its only proof is a live call (#2) or the `/v2/chat` stub already used. | blocked on #2 |
| ~~9~~ | ~~**M32 Experimental Mode**~~ | **Done.** Declared commands and parameters, metrics read only from the declared source, runs as rows with tasks and artifacts, and a comparison that names what it could not rank. `docs/EXPERIMENTS.md`, `pytest tests/test_experiments_m32.py` (66), `scripts/acceptance_m32.sh` (53). | closed |
| ~~10~~ | ~~**M33 Play Mode**~~ | **Done.** Three games the rules referee, a refused move kept with its reason, an engine that can only choose from the legal moves, and simulations that replay from their parameters (a doctored hash fails its own check). `docs/PLAY.md`, `pytest tests/test_play_m33.py` (77), `scripts/acceptance_m33.sh` (69). | closed |

| ~~11~~ | ~~**M34 Voice and media**~~ | **Done, scoped.** A file is measured from its own bytes (PNG, JPEG, GIF, WAV parsed by hand), the name is a claim kept beside the measurement, unsupported containers are refused with their leading bytes, and asking it to hear or speak is a recorded refusal that names every missing link. Marked `partial`: no microphone, no speech weights and no GPU exist here, so recognition and synthesis are **not implemented in any form**. `docs/VOICE.md`, `pytest tests/test_voice_m34.py` (67), `scripts/acceptance_m34.sh` (88). | closed |
| ~~13~~ | ~~**M35 Dataset preparation**~~ | **Done, scoped.** Candidates kept *and* dropped with their reasons, splits that follow from the record's hash (a resaved document is refused across splits), a manifest hash that `verify` can disagree with, and a license that is recorded rather than inferred. Text corpora only: no training, no tokenisation, no upload. `docs/DATASETS.md`, `pytest tests/test_datasets_m35.py` (60), `scripts/acceptance_m35.sh` (72). | closed |
| ~~14~~ | ~~**M36 Training and model modification**~~ | **Done, scoped.** Two trainers that really run on a CPU (n-gram perplexity, centroid accuracy) with metrics as rows, hashed and versioned artifacts, and a preflight that refuses a corpus which cannot produce a number; fine-tuning refused with a computed chain. No weights, no GPU, no library, so no transformer training in any form. `docs/TRAINING.md`, `pytest tests/test_training_m36.py` (54), `scripts/acceptance_m36.sh` (57). | closed |
| ~~15~~ | ~~**M37 Remote compute and portability**~~ | **Done, scoped.** A bundle carries the corpus and two digests per record, an endpoint is named before anything is sent, a worker re-checks the bundle against itself and runs the same trainer, and the artifact's hash is measured again on arrival - a mismatch is `received`, never `verified`. No cloud, no vendor SDK, no credentials: a worker is a process you start and can see. `docs/REMOTE.md`, `pytest tests/test_remote_m37.py` (45), `scripts/acceptance_m37.sh` (71). | closed |
| ~~16~~ | ~~**M38 Execution environments and sandboxing**~~ | **Done, scoped.** Seven backends known by name, the wrapper built by one function and stored on the run row (so a target called `docker` cannot quietly run the command here), a refusal that is a row with every reason and exit 3 for "nothing ran", a worker that runs commands only with `--allow-exec` and a token, and a push/pull hash ledger that makes a both-sides edit a conflict rather than a silent overwrite. WSL is labelled *not a boundary*, Windows Sandbox is `detached`. No image management, no snapshots, no streaming, no sync into containers/VMs. `docs/EXECUTION.md`, `pytest tests/test_execution_m38.py` (49), `scripts/acceptance_m38.sh` (65). | closed |
| 12 | **Speech recognition or synthesis** | Needs weights and an adapter that no machine here can run; building one would be a claim this repository could not verify. `M36` (training) inherits the same problem. | blocked on hardware |

M39 and M40 are complete within scope: measured scenes and actual Blender 4.2 bpy/Cycles CPU
rendering are verified on CI; interval/once/hash-watch automations dispatch atomically to the
existing queue with execution-time permission checks. M41 hardening and clean-wheel packaging
checks are implemented and await the final combined CI result. Vendor credentials, speech and
transformer training limitations remain explicitly open; roadmap closure does not erase them.

---

## 3. Tests that ran, in this environment

```text
$ .venv/bin/python -m pytest tests/ -o addopts="" -q
1593 passed, 2 warnings in 408.06s (0:06:48)

$ .venv/bin/python -m pytest tests/test_stress.py tests/test_edge_cases.py -o addopts="" -q
91 passed in 44s            (three consecutive runs, same result)

$ .venv/bin/python -m pytest tests/test_integration.py -o addopts="" -q
11 passed in 15.88s

$ .venv/bin/python -m pytest tests/test_sdk_m22.py -o addopts="" -q -k Streaming
11 passed, 50 deselected in 8.62s

$ ./scripts/acceptance_sdk.sh
SDK acceptance: 86 checks passed

$ ./scripts/acceptance_gemini.sh
Gemini acceptance: 60 checks passed

$ ./scripts/acceptance_m29.sh
M29 acceptance: 60 checks passed

$ ./scripts/acceptance_m31.sh
M31 acceptance: 48 checks passed

$ ./scripts/acceptance_m32.sh
M32 acceptance: 53 checks passed, 0 failed

$ ARCHX_JSDOM_DIR=/tmp/domtest node scripts/gui_smoke.mjs
smoke ok: 14 tabs, 4 gate rows, code, experiment, play and voice panels render, forms post, no page errors
```

### 3.1 Seven bugs the new suites found

The stress, edge-case and integration suites were written against the GUI's actual behaviour
rather than its intended behaviour, and they found seven defects that the existing 1282 tests
all passed over. Every one is fixed and has a regression test:

1. `str(request.field(...))` on a non-string `message` stored `"123"`, `"{}"` or `"[1, 2]"` as
   the user's turn and sent it to the model.
2. A non-string `model_id` or `conversation_id` reached SQLite as a bind parameter and produced
   `500 ProgrammingError`.
3. Every `ProviderError` mapped to `500`, so a missing model, a refused key, a rate limit and
   an outage were all "the server broke". `ModelNotFoundError` inherits `ProviderError`, which
   is why the specific cases were invisible.
4. `/api/health` answered `POST`, `PUT` and `DELETE` with a payload, without a token.
5. `PATCH` — and any verb without a `do_*` method — got the stdlib's HTML `501`, the only
   non-JSON response in the app.
6. A 4000-character asset name produced `500 missing_assets`; it is `404`.
7. Refusing an oversize body closed the socket while the client was still uploading, so the
   client saw a connection reset instead of the `413`.

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

**Verified by observation:** the 1384-test suite; 86 SDK acceptance checks over real sockets; 60
Gemini checks; 60 M29 checks; the jsdom smoke of the shipped page; every streaming parser against a loopback server; the exact request
path of all seven HTTP clients (`TestPaths`) and that each default base plus that path equals the
vendor's public URL (`TestDefaults`); the keyless-local / key-required-remote split; the four
consent rungs applying to SDK models.

**Verified on GitHub, by running it:** six workflow runs, the last four green (including one that
ran the exact 1282-test suite recorded above) — a real
SmolLM2-135M Q4_K_M served on a CPU runner, four vendor clients answering and streaming against
it, a real Ollama daemon docker-pulled and driven by both its own client and by Archx, and a
Cloudflare quick tunnel with the OpenAI SDK through the public URL (`docs/ci/`).

**Not verified, and not claimed:** any vendor's live cloud service (no keys, restricted egress).
The loopback servers and the runner's local models prove the client side of every protocol; they
cannot prove what `api.openai.com` does today.
