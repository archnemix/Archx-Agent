# SDK transports - completion report

## 1. What was asked

> "for paid-based checking, for Anthropic, Google SDK and OpenAI SDK, and any other if there is
> any like Mistral, Z.ai … than just download a local model like a 125-million-param small model,
> run it in GitHub Actions and use a Cloudflare tunnel to expose a url, put it in a file, then use
> that url as a base_url and try all the SDKs you want so you can know it works … use the model in
> 4 bit or smaller because we just want to test it works"

So: (a) drive real vendor SDKs, not only our hand-written HTTP; (b) stand up a real, tiny,
4-bit model behind a public URL and point every SDK at it.

## 2. What shipped

| Piece | Where |
|-------|-------|
| the transports | `src/archx_agent/adapters/sdk_transport.py` (8 clients, one taxonomy, one streaming parser each) |
| the runtime | `src/archx_agent/adapters/sdk_runtime.py` (`runtime_id = "sdk"`) |
| one registration path | `Workspace.register_sdk` |
| CLI | `models sdks`, `models add-sdk` |
| HTTP API | `GET /api/sdks`, `POST /api/models` with `transport` |
| the page | transport picker in *Connect Gemini*; SDK name on each model card |
| the runner path | `.github/workflows/model-matrix.yml` (push-triggered), `scripts/remote_model.sh`, `scripts/ci_logs.sh` |
| evidence | `tests/test_sdk_m22.py` (61), `scripts/acceptance_sdk.sh` (86) |

Eight clients, one contract:

| sdk | constructor | token budget | system prompt | key |
|-----|-------------|--------------|---------------|-----|
| openai | `OpenAI(api_key, base_url)` | `max_completion_tokens` if known, else `max_tokens` | in `messages` | required |
| anthropic | `Anthropic(api_key, base_url)` | `max_tokens` | top-level `system` | required |
| google | `genai.Client(api_key, http_options.base_url)` | `max_output_tokens` | `system_instruction` | required |
| mistral | `Mistral(api_key, server_url)` | `max_tokens` | in `messages` | required |
| groq | `Groq(api_key, base_url)` — base is the **origin**, the client adds `/openai/v1` | `max_completion_tokens` | in `messages` | required |
| together | `Together(api_key, base_url)` — base is the **origin**, the client adds `/v1` | `max_tokens` | in `messages` | required |
| cohere | `ClientV2(api_key, base_url)` | `max_tokens` | a `system` message | required |
| ollama | `Client(host=…)` | `options.num_predict` | a `system` message | **optional, loopback only** |

The Ollama row is the only one where a credential must be *absent*: a local daemon refuses one it
did not issue and needs none to be given. `SdkSpec.key_required` states the vendor's rule,
`transport.available()` allows the keyless case only when `is_loopback()` is true, and
`Workspace.runtime_availability` reports `ready: a local Ollama needs no key (no data leaves this
machine)` rather than demanding a `secret://` reference that would never resolve. The same client
aimed at a remote host is refused before the socket opens.

## 3. What the tests found (and why the SDK path is worth having)

Three real bugs, all of which the hand-written clients would never have surfaced:

1. **`anthropic` 2.x removed `temperature` and `top_p` from `messages.create`.** Passing them is
   a `TypeError` before any request exists - which reads as "the provider is down". The transport
   now inspects each call's signature and sends only what the installed client accepts.
2. **OpenAI's client knows both `max_tokens` and `max_completion_tokens`.** Sending both is a 400
   on newer models, and picking the wrong one silently truncates. One is chosen, by name.
3. **Status codes live in different places.** OpenAI/Anthropic set `status_code`; `google-genai`
   raises `ClientError("401 None. …")`; `mistralai` raises `SDKError("API error occurred: Status
   401 …")`. The first version classified all three as a generic `ProviderError`, so a bad key
   was indistinguishable from an outage. The classifier now reads the class name *and* the text.

That is the argument for the whole exercise: a second implementation of the same protocol is a
test of the first one.

## 4. Evidence (run here, in this sandbox)

```text
$ pytest tests/test_sdk_m22.py -o addopts="" -q
61 passed, 1 warning in 37.1s

$ pytest tests/ -o addopts="" -q
1251 passed, 1 warning in 289.42s (0:04:49)

$ ./scripts/acceptance_sdk.sh
SDK acceptance: 86 checks passed

$ ./scripts/remote_model.sh http://127.0.0.1:8451 --sdk openai
--- openai
OK    '[PROTOCOL-STUB] this reply came from a test HTTP server, not a model. …'
      tokens in/out 6/26  finish stop
```

The acceptance run starts one local server that speaks the five routes these clients use,
registers all eight SDKs through the CLI, probes each of them (a real socket round trip through
the vendor client), sends a chat turn that lands as an ordinary `chat` task, checks the keyless
Ollama case *and* its remote refusal, then walks the four consent rungs on a remote SDK model. It
finishes by grepping the home directory, the database and the trace for any of the eight keys:
zero hits.

The four new clients were driven one at a time against one loopback server and the paths they
*actually* requested were recorded, which is how the catalogue's base URLs were corrected:

```text
groq      OK  'answer via the openai-shaped client'  tokens=8/3   finish=stop  POST /openai/v1/chat/completions
together  OK  'answer via the openai-shaped client'  tokens=8/3   finish=stop  POST /v1/chat/completions
cohere    OK  'answer via the cohere client'         tokens=13/5  finish=stop  POST /v2/chat
ollama    OK  'answer via the ollama client'         tokens=21/6  finish=stop  POST /api/chat
```

## 5. The runner path: it runs, and it found five bugs

The Actions API will not let this token *dispatch* a workflow, so the workflow is started by
editing `.ci/trigger`, and its output is read from the `ci-logs` branch. Four runs so far:

```text
#1  hung on `serve`   - a backgrounded server held the step's pipe open, so the step never ended
#2  no job at all     - GitHub: "concurrency is already defined" (line 50). Valid YAML, invalid workflow.
#3  all steps ok      - 1251 passed on the runner, model served, 135M model answered
#4  all steps ok      - SDK matrix clean: 4 clients answered AND streamed
```

Run #4, the newest, in full:

```text
install ok · pytest ok (258 s) · sdks ok · llama-cpp ok · model-download ok · serve ok
completion ok · sdk-matrix ok · ollama ok · tunnel ok          0 failed
```

A real SmolLM2-135M Q4_K_M answered on a CPU runner:

```text
text: A tunnel is a sealed, underground passageway that connects two points, often through a
      physical barrier or artificial entrance.
```

Four clients completed a turn *and streamed* against it (OpenAI, Anthropic, Mistral, Together);
Groq, Cohere and Ollama skipped with the reason, because they cannot drive a llama.cpp server.
Then a **real Ollama daemon** (`docker run ollama/ollama`, `ollama pull smollm2:135m`) took the
Ollama client through 32 streamed chunks, and Archx itself through the keyless local path:

```text
runtime  ready - ready: a local Ollama needs no key (no data leaves this machine)
chat: passed  (40 chars, finish_reason=stop)   state now verified (probe passed)
```

And a Cloudflare tunnel, with the OpenAI SDK on the far side of the public URL:

```text
url=https://somebody-guided-exclude-rca.trycloudflare.com
public chat HTTP 200 · openai SDK via the public URL: Hi, hello.
```

The five defects it found are in `docs/PROVIDERS.md`; the two that matter most are:

* **`transport.close()` before streaming.** Every streaming call failed on the runner with a
  missing credential, because `remote_model.sh` closed the transport in a `finally` first.
* **Wrong bases per client, hidden by a lenient stub.** groq appends `/openai/v1`, so giving it
  `…/v1` yields `/v1/openai/v1/chat/completions`. The stub answered 200; llama.cpp answered 404.
  The stub now refuses unknown routes, `TestPaths` pins every client's path, and `TestDefaults`
  asserts `default_base_url + path == the vendor's public URL`.

Evidence kept in the repository: `docs/ci/` (status table, model answer, tunnel url, and every
client's output).

## 6. Still not done

* ~~**Streaming** through the SDKs~~ - done: `SdkTransport.stream` has one parser per client
  (OpenAI deltas, Mistral's `.data` wrapper, Anthropic's `content_block_delta`, Gemini's GET-form
  `streamGenerateContent`, Cohere's `content-delta` events, Ollama's JSON lines) and eleven tests
  drive each of them against a loopback server that emits that vendor's syntax.
* **Tool calling**: `models probe --capability tools` needs a probe that inspects a returned
  tool call; the SDKs expose it, but no probe exists, so the capability is not offered.
* **Z.ai / other OpenAI-compatible vendors**: they work today through `models add-http` (or
  `add-sdk --sdk openai --base-url https://api.z.ai/api/paas/v4`), but there is no dedicated
  template with its privacy claims, and inventing one from memory would be a claim I cannot
  source.
* **A live call to any of the eight vendors.** None was made from this sandbox - the loopback
  servers prove Archx's half of each protocol, and the runner steps are the first opportunity to
  prove the vendors' half. Cohere is the one client with no keyless story at all: it can only be
  validated against the real service, or against a server speaking `/v2/chat` as the acceptance
  stub does.
* **Streaming** through the four new clients: same state as the first four - `stream()` works for
  the raw clients, and the SDK path returns one chunk until the event parsers are measured.
