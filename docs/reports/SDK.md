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
| the transports | `src/archx_agent/adapters/sdk_transport.py` (4 clients, one taxonomy) |
| the runtime | `src/archx_agent/adapters/sdk_runtime.py` (`runtime_id = "sdk"`) |
| one registration path | `Workspace.register_sdk` |
| CLI | `models sdks`, `models add-sdk` |
| HTTP API | `GET /api/sdks`, `POST /api/models` with `transport` |
| the page | transport picker in *Connect Gemini*; SDK name on each model card |
| the runner path | `.github/workflows/local-model-tunnel.yml`, `scripts/remote_model.sh` |
| evidence | `tests/test_sdk_m22.py` (40), `scripts/acceptance_sdk.sh` (46) |

Four clients, one contract:

| sdk | constructor | token budget | system prompt |
|-----|-------------|--------------|---------------|
| openai | `OpenAI(api_key, base_url)` | `max_completion_tokens` if known, else `max_tokens` | in `messages` |
| anthropic | `Anthropic(api_key, base_url)` | `max_tokens` | top-level `system` |
| google | `genai.Client(api_key, http_options.base_url)` | `max_output_tokens` | `system_instruction` |
| mistral | `Mistral(api_key, server_url)` | `max_tokens` | in `messages` |

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
40 passed in 22.24s

$ ./scripts/acceptance_sdk.sh
SDK acceptance: 46 checks passed

$ ./scripts/remote_model.sh http://127.0.0.1:8451 --sdk openai
--- openai
OK    '[PROTOCOL-STUB] this reply came from a test HTTP server, not a model. …'
      tokens in/out 6/26  finish stop
```

The acceptance run starts one local server that speaks three protocols, registers all four SDKs
through the CLI, probes each of them (a real socket round trip through the vendor client), sends
a chat turn that lands as an ordinary `chat` task, then walks the four consent rungs on a remote
SDK model. It finishes by grepping the home directory, the database and the trace for any of the
four keys: zero hits.

## 5. The runner path: written, verified as far as this environment allows, **not yet run**

`local-model-tunnel.yml`:
- downloads `bartowski/SmolLM2-135M-Instruct-GGUF` → `SmolLM2-135M-Instruct-Q4_K_M.gguf`
  (~100 MB, 4-bit, 135M params - the "small model, 4-bit or smaller" that was asked for);
- installs llama.cpp from the newest CPU release asset, with a **build-from-source fallback**
  because release assets move (`releases/latest` currently points at a tag with no binary
  asset at all - checked against the live API);
- serves it CPU-only on `127.0.0.1:8080`, proves generation with a real `POST
  /v1/chat/completions`, and keeps that reply plus its token counts as `model-proof.json`;
- opens a Cloudflare quick tunnel, extracts the `trycloudflare.com` URL, **re-checks the model
  through the public URL**, and publishes `tunnel-url.txt` as an artifact and in the job summary;
- holds the tunnel open for N minutes (max 30) and fails loudly if the model dies.

What I could verify here: the YAML parses; the release-asset selection returns a real URL when
run against the live API (`llama-b11951-bin-ubuntu-x64.tar.gz`); `remote_model.sh` works end to
end against a local server, including the Archx-side registration and probes.

What I could **not** do: start the workflow. This session's GitHub credential is an app
installation token without Actions permission - `GET /repos/.../actions/workflows` returns
`total_count: 0` and a dispatch returns `403 Resource not accessible by integration`. So the
workflow has not run, no tunnel URL exists, and no 135M model has answered from here. To run it:

```bash
gh workflow run local-model-tunnel.yml -f keep_alive_minutes=10
gh run watch
gh run download --name tunnel-url        # tunnel-url.txt + model-proof.json
./scripts/remote_model.sh                # every SDK against that URL
```

Two further limits worth stating: Hugging Face is unreachable from this sandbox, so no weights
could be fetched even locally; and `*.trycloudflare.com` is not in the sandbox's egress
allowlist, so a tunnel URL from a runner would not have been reachable from here either.

## 6. Still not done

* **Streaming** through the SDKs: four event-type parsers that nothing measures yet, so
  `supports_streaming` is true but `stream()` yields one chunk. The raw clients do stream.
* **Tool calling**: `models probe --capability tools` needs a probe that inspects a returned
  tool call; the SDKs expose it, but no probe exists, so the capability is not offered.
* **Z.ai / other OpenAI-compatible vendors**: they work today through `models add-http` (or
  `add-sdk --sdk openai --base-url https://api.z.ai/api/paas/v4`), but there is no dedicated
  template with its privacy claims, and inventing one from memory would be a claim I cannot
  source.
