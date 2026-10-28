# The CI run that proves this, kept in the repository

This is the output of run **20261028T115458Z-5e67bd9** (GitHub run #4), triggered by editing
`.ci/trigger` and pushing - no Actions API call anywhere. The complete folder lives on the
`ci-logs` branch at `ci/runs/20261028T115458Z-5e67bd9/`; what is here is the part worth reading
without fetching a branch.

```bash
./scripts/ci_logs.sh --run 20261028T115458Z-5e67bd9
git fetch origin ci-logs && git show FETCH_HEAD:ci/runs/20261028T115458Z-5e67bd9/console.log
```

`status.tsv` - one row per step, written as each step finished:

```text
# run 20261028T115458Z-5e67bd9

step	status	seconds
install	ok	19
pytest	ok	258
sdks	ok	2
llama-cpp	ok	1
model-download	ok	2
serve	ok	1
completion	ok	0
sdk-matrix	ok	11
ollama	ok	62
tunnel	ok	7
```

A real 135M model answered on a GitHub runner (`docs/ci/model-proof.json`):

```json
{
  "text": "A tunnel is a sealed, underground passageway that connects two points, often through a physical barrier or artificial entrance.",
  "usage": {
    "completion_tokens": 24,
    "prompt_tokens": 40,
    "total_tokens": 64,
    "prompt_tokens_details": {
      "cached_tokens": 0
    }
  }
}```

## Every official client against that one endpoint

`scripts/remote_model.sh http://127.0.0.1:8080` - llama.cpp serving SmolLM2-135M Q4_K_M:

```text
### the same endpoint through each official SDK

--- openai
OK    'Hello, welcome to my little corner of the internet!'
      tokens in/out 36/12  finish stop
      base http://127.0.0.1:8080/v1  ->  /chat/completions
      streamed 6 chunk(s), 22 chars: "I'm counting to three."

--- anthropic
OK    '"Hi! Hello! Hello again!"'
      tokens in/out 12/9  finish stop
      base http://127.0.0.1:8080  ->  /v1/messages
      streamed 6 chunk(s), 21 chars: 'Okay, here are three.'

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
OK    'Hello!'
      tokens in/out 36/3  finish stop
      base http://127.0.0.1:8080  ->  /v1/chat/completions
      streamed 4 chunk(s), 15 chars: 'Count to three.'

--- cohere
SKIP  no /v2/chat here; the cohere client has nothing to talk to

--- ollama
SKIP  no /api/tags here; the ollama client has nothing to talk to

### summary
### summary
4 SDK(s) completed a turn, 0 failed
```

Four clients completed a turn **and streamed** it; the four skips say exactly why. `groq` is the
interesting one: its client hard-codes an `/openai/v1` prefix, so it cannot drive a llama.cpp
server at all, and calling that a failure would be wrong.

## A real Ollama daemon, its own client, and the app

`docker run ollama/ollama` + `ollama pull smollm2:135m`, then the ollama client and then Archx
itself - where the daemon is keyless, which is the rule this repository had to get right:

```text
### the same endpoint through each official SDK

--- ollama
OK    "Hello, I'm a helpful AI assistant named SmolLM, trained by Hugging Face"
      tokens in/out 36/19  finish stop
      base http://127.0.0.1:11434  ->  /api/chat
      streamed 32 chunk(s), 84 chars: 'Yes, I can do that. Here are three:\n\n1. "Yes, I can do that."\n2. "Yes, I can do that'

### summary
1 SDK(s) completed a turn, 0 failed

### and through Archx itself (the app, not just the SDK)
home /tmp/archx-remote-2tUumB

$ archx-agent models add-sdk --name remote-ollama --sdk ollama --model local --base-url http://127.0.0.1:11434
  registered remote-ollama (mdl_0001m61650x6000000002f6e2e42007b03b4) provider=ollama runtime=sdk
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
      latency 169.5 ms
      state now unsupported (probe failed)
      this drove the runtime; the result is recorded and the router will use it
registered ollama-local (mdl_0001m61651t90000000076d3a24cc5b345ce) provider=ollama runtime=sdk
  sdk      ollama (`ollama`)
  model    smollm2:135m
  endpoint http://127.0.0.1:11434
  key      read at use time from secret://env/OLLAMA_API_KEY (never stored)
  sdk      installed
  runtime  ready - ready: a local Ollama needs no key (no data leaves this machine)
note: capabilities are claims until measured with `archx-agent models probe`
chat: passed  (40 chars, finish_reason=stop)
  latency 283.3 ms
  state now verified (probe passed)
  this drove the runtime; the result is recorded and the router will use it
I'm afraid I'm not an AI, but I can tell you that one of the most common colours is blue.

[model ollama-local (ollama) | 322ms | context 52/130304 tokens | strategy oldest_first]
[warning] no embedding index is configured; semantic search is unavailable and results are keyword-only
```

## A public URL

cloudflared quick tunnel in front of the same server:

```text

url=https://somebody-guided-exclude-rca.trycloudflare.com
public chat HTTP 200
{"choices":[{"finish_reason":"length","index":0,"message":{"role":"assistant","content":"I'm ready for any question and request. Just go ahead and ask your query"}}],"created":1793188866,"model":"/home/runner/model/SmolLM2-135M-Instruct-Q4_K_M.gguf","system_fingerprint":"b11954-f1a7dea99","object":"chat.completion","usage":{"completion_tokens":16,"prompt_tokens":31,"total_tokens":47,"prompt_tokensopenai SDK via the public URL: Hi, hello.

```
