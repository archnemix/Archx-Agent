# The CI runs that prove this, kept in the repository

Everything here came from a file-triggered GitHub Actions run - editing `.ci/trigger` and
pushing. No Actions API call is needed to start or to read it.

| run | id | outcome |
|-----|----|---------|
| #3 | `20261028T113602Z-51d2787` | all 10 steps ok, 1251 tests on the runner |
| #4 | `20261028T115458Z-5e67bd9` | all 10 steps ok, SDK matrix clean (4 clients answered *and* streamed) |
| #5 | `20261028T121409Z-41da23e` | all 10 steps ok, 1281 tests on the runner |
| #6 | `20261028T122917Z-20bd680` | all 10 steps ok, **1282 tests on the runner** - the same count as this sandbox |

Runs #1 and #2 are the interesting failures: #1 hung on the `serve` step for nine minutes (a
backgrounded server held the step's pipe open), and #2 never started a job at all because GitHub
rejected the workflow file (`'concurrency' is already defined`) that every local YAML reader
accepted.

```bash
./scripts/ci_logs.sh --list
./scripts/ci_logs.sh --run 20261028T122917Z-20bd680
git fetch origin ci-logs && git show FETCH_HEAD:ci/runs/20261028T122917Z-20bd680/console.log
```

## Status, newest run

```text
# run 20261028T122917Z-20bd680

step	status	seconds
install	ok	20
pytest	ok	334
sdks	ok	2
llama-cpp	ok	7
model-download	ok	1
serve	ok	1
completion	ok	1
sdk-matrix	ok	12
ollama	ok	66
tunnel	ok	8
```

## A real model, on a CPU runner

`docs/ci/model-proof.json`:

```json
{
  "text": "A tunnel is a deep, narrow passageway through a solid surface, typically made of concrete or steel, that allows for access and movement through the material.",
  "usage": {
    "completion_tokens": 32,
    "prompt_tokens": 40,
    "total_tokens": 72,
    "prompt_tokens_details": {
      "cached_tokens": 0
    }
  }
}```

## Every official client against that endpoint

llama.cpp serving SmolLM2-135M Q4_K_M on `127.0.0.1:8080`:

```text
### the same endpoint through each official SDK

--- openai
OK    'Hello, welcome to my little corner of the internet.'
      tokens in/out 36/12  finish stop
      base http://127.0.0.1:8080/v1  ->  /chat/completions
      streamed 3 chunk(s), 12 chars: 'Count three.'

--- anthropic
OK    'Hello!'
      tokens in/out 12/3  finish stop
      base http://127.0.0.1:8080  ->  /v1/messages
      streamed 32 chunk(s), 49 chars: "I'll do it. \n\nCount three: \n3, 3, 3, 3, 3, 3, 3,"

--- google
SKIP  the google client speaks :generateContent; this endpoint does not

--- mistral
OK    'Hello, welcome to my little corner of the internet.'
      tokens in/out 36/12  finish stop
      base http://127.0.0.1:8080  ->  /v1/chat/completions
      streamed 6 chunk(s), 22 chars: "I'm counting to three."

--- groq
SKIP  groq requests /openai/v1/chat/completions; this endpoint answers 404 there (model not found: Error code: 404 - {'error': {'message': 'File Not Found', 'type)

--- together
OK    'Hello, welcome to my little corner of the internet.'
      tokens in/out 36/12  finish stop
      base http://127.0.0.1:8080  ->  /v1/chat/completions
      streamed 6 chunk(s), 22 chars: "I'm counting to three."

--- cohere
SKIP  no /v2/chat here; the cohere client has nothing to talk to

--- ollama
SKIP  no /api/tags here; the ollama client has nothing to talk to

### summary
4 SDK(s) completed a turn, 0 failed

### and through Archx itself (t```

## A real Ollama daemon, its own client, and the app

`docker run ollama/ollama`, `ollama pull smollm2:135m`:

```text
### the same endpoint through each official SDK

--- ollama
OK    'Hello, welcome to our chat.'
      tokens in/out 36/8  finish stop
      base http://127.0.0.1:11434  ->  /api/chat
      streamed 2 chunk(s), 6 chars: 'Three.'

### summary
1 SDK(s) completed a turn, 0 failed

### and through Archx itself (the app, not just the SDK)
home /tmp/archx-remote-uP46kp

$ archx-agent models add-sdk --name remote-ollama --sdk ollama --model local --base-url http://127.0.0.1:11434
  registered remote-ollama (mdl_0001m6186hxs0000000092dd9c85c2d6ef95) provider=ollama runtime=sdk
    sdk      ollama (`ollama`)
    model    local
    endpoint http://127.0.0.1:11434
    key      read at use time from secret://env/OLLAMA_API_KEY (never stored)
    sdk      installed
    runtime  ready - ready: a local Ollama needs no key (no data leaves this machine)
  note: capabilities are claims until measured with `archx-agent models probe`
  (remote: the four consent rungs apply before chat will send anything)
  probe:
    chat: failed  (ModelNotFoundError: model not found: model 'local' not found (status code: 404))
      latency 179.1 ms
      state now unsupported (probe failed)
      this drove the runtime; the result is recorded and the router will use it
registered ollama-local (mdl_0001m6186jzq00000000f36a2997d8987525) provider=ollama runtime=sdk
  sdk      ollama (`ollama`)
  model    smollm2:135m
  endpoint http://127.0.0.1:11434
  key      read at use time from secret://env/OLLAMA_API_KEY (never stored)
  sdk      installed
  runtime  ready - ready: a local Ollama needs no key (no data leaves this machine)
note: capabilities are claims until measured with `archx-agent models probe`
chat: passed  (40 chars, finish_reason=stop)
  latency 294.7 ms
  state now verified (probe passed)
  this drove the runtime; the result is recorded and the router will use it
One colour is blue.

[model ollama-local (ollama) | 191ms | context 52/130304 tokens | strategy oldest_first]
[warning] no embedding index is configured; semantic search is unavailable and results are keyword-only
```

## A public URL

```text
url=https://broadcast-wellington-part-maiden.trycloudflare.com
public chat HTTP 200
print("openai SDK via the public URL:", reply.choices[0].message.content.strip())
{"choices":[{"finish_reason":"length","index":0,"message":{"role":"assistant","content":"\"Hellow, hiya. How are you today?\"\n\nJust like"}}],"created":1793191013,"model":"/home/runner/model/SmolLM2-135M-Instruct-Q4_K_M.gguf","system_fingerprint":"b11954-f1a7dea99","object":"chat.completion","usage":{"completion_tokens":16,"prompt_tokens":31,"total_tokens":47,"prompt_tokens_details":{"cached_tokeopenai SDK via the public URL: "I'm a helpful AI assistant named SmolLM who can help you with anything you need."
```
