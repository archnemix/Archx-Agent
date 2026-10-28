# The CI runs that prove this, kept in the repository

Everything here came from a file-triggered GitHub Actions run - editing `.ci/trigger` and
pushing. No Actions API call is needed to start or to read it.

| run | id | outcome |
|-----|----|---------|
| #3 | `20261028T113602Z-51d2787` | all 10 steps ok, 1251 tests on the runner |
| #4 | `20261028T115458Z-5e67bd9` | all 10 steps ok, SDK matrix clean |
| #5 | `20261028T121409Z-41da23e` | all 10 steps ok, **1281 tests on the runner** - the same number as local at that commit |

The complete folder for every run is on the `ci-logs` branch:

```bash
./scripts/ci_logs.sh --list
./scripts/ci_logs.sh --run 20261028T121409Z-41da23e
git fetch origin ci-logs && git show FETCH_HEAD:ci/runs/20261028T121409Z-41da23e/console.log
```

## Status, newest run

```text
# run 20261028T121409Z-41da23e

step	status	seconds
install	ok	29
pytest	ok	316
sdks	ok	2
llama-cpp	ok	3
model-download	ok	1
serve	ok	1
completion	ok	0
sdk-matrix	ok	13
ollama	ok	61
tunnel	ok	9
```

## A real model, on a CPU runner

`docs/ci/model-proof.json`:

```json
{
  "text": "A tunnel is a narrow, winding passageway through a solid surface, often used for transportation or tunnels.",
  "usage": {
    "completion_tokens": 22,
    "prompt_tokens": 40,
    "total_tokens": 62,
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
OK    'Hello, welcome to my little corner of the internet!'
      tokens in/out 36/12  finish stop
      base http://127.0.0.1:8080/v1  ->  /chat/completions
      streamed 4 chunk(s), 15 chars: 'Count to three.'

--- anthropic
OK    "I'm an AI assistant designed to help you with everything from business advice to personal matters."
      tokens in/out 12/19  finish stop
      base http://127.0.0.1:8080  ->  /v1/messages
      streamed 32 chunk(s), 61 chars: "(Counting three)\n\nHere's the countdown:\n\n1. 1000\n\n2. 10000\n\n3"

--- google
SKIP  the google client speaks :generateContent; this endpoint does not

--- mistral
OK    'Hello, welcome to my little corner of the internet.'
      tokens in/out 36/12  finish stop
      base http://127.0.0.1:8080  ->  /v1/chat/completions
      streamed 2 chunk(s), 6 chars: 'Three.'

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
OK    'Hello, welcome to our chat about the latest trends in technology.'
      tokens in/out 36/14  finish stop
      base http://127.0.0.1:11434  ->  /api/chat
      streamed 2 chunk(s), 6 chars: 'Three.'

### summary
1 SDK(s) completed a turn, 0 failed

### and through Archx itself (the app, not just the SDK)
home /tmp/archx-remote-MFinhy

$ archx-agent models add-sdk --name remote-ollama --sdk ollama --model local --base-url http://127.0.0.1:11434
  registered remote-ollama (mdl_0001m617a9y300000000e1a96add68709586) provider=ollama runtime=sdk
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
      latency 182.4 ms
      state now unsupported (probe failed)
      this drove the runtime; the result is recorded and the router will use it
registered ollama-local (mdl_0001m617ab0200000000009550cd2879449b) provider=ollama runtime=sdk
  sdk      ollama (`ollama`)
  model    smollm2:135m
  endpoint http://127.0.0.1:11434
  key      read at use time from secret://env/OLLAMA_API_KEY (never stored)
  sdk      installed
  runtime  ready - ready: a local Ollama needs no key (no data leaves this machine)
note: capabilities are claims until measured with `archx-agent models probe`
chat: passed  (40 chars, finish_reason=stop)
  latency 293.3 ms
  state now verified (probe passed)
  this drove the runtime; the result is recorded and the router will use it
One colour is blue.

[model ollama-local (ollama) | 183ms | context 52/130304 tokens | strategy oldest_first]
[warning] no embedding index is configured; semantic search is unavailable and results are keyword-only
```

## A public URL

```text
url=https://rouge-conditional-satin-centers.trycloudflare.com
public chat HTTP 200
print("openai SDK via the public URL:", reply.choices[0].message.content.strip())
{"choices":[{"finish_reason":"length","index":0,"message":{"role":"assistant","content":"Ping - I'm here to help you with any problem you're facing in"}}],"created":1793190088,"model":"/home/runner/model/SmolLM2-135M-Instruct-Q4_K_M.gguf","system_fingerprint":"b11954-f1a7dea99","object":"chat.completion","usage":{"completion_tokens":16,"prompt_tokens":31,"total_tokens":47,"prompt_tokens_details":{openai SDK via the public URL: "Hi, welcome to my office!"
```
