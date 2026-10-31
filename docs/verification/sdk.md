# Historical verification: SDK acceptance transcript

This is a recorded run. See the [verification index](../VERIFICATION.md) for context.

## SDK acceptance transcript

The vendor clients, driven over a real socket against one local server that speaks the routes they
actually use (OpenAI-compatible, Anthropic messages, Gemini `generateContent`, Cohere `/v2/chat`,
Ollama `/api/chat`). No vendor host is contacted. Eight clients, 86 checks.

```text
$ ./scripts/acceptance_sdk.sh
### every official client Archx knows about
[ok]   the catalogue lists openai = 1
[ok]   the catalogue lists anthropic = 1
[ok]   the catalogue lists google = 1
[ok]   the catalogue lists mistral = 1
[ok]   the catalogue lists groq = 1
[ok]   the catalogue lists together = 1
[ok]   the catalogue lists cohere = 1
[ok]   the catalogue lists ollama = 1
[ok]   each row says where its key comes from = 1
### each SDK is registered through the CLI, with a reference and never a key
[ok]   add-sdk openai exits 0 = 0
[ok]   openai is registered as runtime=sdk = 1
[ok]   openai's key is a reference = 1
[ok]   openai's output does not contain its key = 0
   … the same four checks for the other seven clients …
[ok]   a literal key is refused = 2
[ok]   an unknown SDK is refused = 2
### each SDK is actually driven, over a real socket
[ok]   openai probe passed = 1
[ok]   anthropic probe passed = 1
[ok]   google probe passed = 1
[ok]   mistral probe passed = 1
[ok]   groq probe passed = 1
[ok]   together probe passed = 1
[ok]   cohere probe passed = 1
[ok]   ollama probe passed = 1
[ok]   openai probe did not substitute a test double = 0
### a local daemon needs no key, and that is not a failure
[ok]   the loopback ollama model is usable without a key = 1
[ok]   and it really answers with no key at all = 1
[ok]   a keyless SDK aimed off this machine is still refused = 1
[ok]   and the refusal never reached the network = 0
### every client streams, and each one streams its own way
[ok]   openai streams and the text arrives whole = 1
[ok]   … the same check for the other seven clients …
### a chat turn through the SDK becomes an ordinary task
[ok]   chat exits 0 = 0
[ok]   it is not labelled simulated = 0
[ok]   the task records tokens from usage = True
### the four consent rungs apply to SDK clients too
[ok]   rung 1: local_only refuses it = 1
[ok]   rung 2: an unregistered endpoint is refused = 1
[ok]   rung 3: unknown privacy terms are refused = 1
[ok]   rung 4: missing consent is refused = 1
### nothing kept the key
[ok]   no file under the home holds any key = 0
[ok]   the database does not contain a key = 0
[ok]   the trace does not contain one = 0

SDK acceptance: 86 checks passed
```

```text
$ .venv/bin/python -m pytest tests/test_sdk_m22.py -o addopts="" -q
61 passed, 1 warning in 37.1s

$ .venv/bin/python -m pytest tests/ -o addopts="" -q
1251 passed, 1 warning in 289.42s (0:04:49)
```

### Streaming, one parser per client

A client can get the request shape right and the deltas wrong, so each parser is driven against a
loopback server that emits that vendor's real event syntax (SSE for six, JSON-lines for Ollama,
a GET for Gemini):

```text
$ .venv/bin/python -m pytest tests/test_sdk_m22.py -o addopts="" -q -k Streaming
11 passed, 50 deselected in 8.62s

$ ./scripts/acceptance_sdk.sh
[ok]   openai streams and the text arrives whole = 1
[ok]   anthropic streams and the text arrives whole = 1
[ok]   google streams and the text arrives whole = 1
[ok]   mistral streams and the text arrives whole = 1
[ok]   groq streams and the text arrives whole = 1
[ok]   together streams and the text arrives whole = 1
[ok]   cohere streams and the text arrives whole = 1
[ok]   ollama streams and the text arrives whole = 1
SDK acceptance: 86 checks passed
```

### What each new client actually sent

One loopback server, four new clients, the request paths read off the wire rather than assumed:

```text
groq      OK  'answer via the openai-shaped client'  tokens=8/3   finish=stop  POST /openai/v1/chat/completions
together  OK  'answer via the openai-shaped client'  tokens=8/3   finish=stop  POST /v1/chat/completions
cohere    OK  'answer via the cohere client'         tokens=13/5  finish=stop  POST /v2/chat
ollama    OK  'answer via the ollama client'         tokens=21/6  finish=stop  POST /api/chat
```

That transcript is also what corrected the catalogue: Groq and Together append
`/chat/completions` to their `base_url`, so the entries carry `/openai/v1` and `/v1`.

### The CI workflow, run eighteen times on GitHub

The workflow is triggered by editing `.ci/trigger` and pushing, and its output is read from the
`ci-logs` branch. It has now actually run; `docs/ci/` keeps the parts worth reading.

```text
run #1  20261028T110927Z-958fc22   hung on `serve` (backgrounded server held the step's pipe)
run #2  1a084f3                    never started a job: "concurrency is already defined" (line 50)
run #3  20261028T113602Z-51d2787   all 10 steps ok; pytest 1251 passed on the runner
run #4  20261028T115458Z-5e67bd9   all 10 steps ok, and the SDK matrix is clean
run #5  20261028T121409Z-41da23e   all 10 steps ok; 1281 tests on the runner, streaming included
run #6  20261028T122917Z-20bd680   all 10 steps ok; 1282 tests on the runner (the local count)
run #7  40700132489              cancelled: the code push started it, then the .ci/trigger push
                                  started #8 and concurrency cancelled the older one
run #8  20261028T135031Z-f506b82   all 12 steps ok; 1384 tests, 91 stress/edge and 11 integration
                                  tests on the runner - the same three counts as this sandbox
run #9  40709272840              cancelled by #10 (the same concurrency rule as #7)
run #10 20261028T144642Z-fc1f92f   all 13 steps ok; 1448 tests in 348 s, 91 stress/edge, 15
                                  integration, and the M31 acceptance (48/48) on the runner
run #11 40714856913              cancelled: the M32 commit touched the workflow file itself (a
                                  trigger path), then the .ci/trigger push started #12
run #12 20261028T152139Z-b0ab8ce   all 14 steps ok; 1515 tests in 310 s, 91 stress/edge, 12
                                  integration, the M31 acceptance (48/48) and the M32 acceptance
                                  (53/53) on the runner
run #13 20261028T153716Z-b62f938   all 14 steps ok; 1516 tests in 313 s, and the same two
                                  acceptance counts
run #14 20261028T162126Z-025f7fe   all 15 steps ok; 1593 tests in 387 s, 91 stress/edge, 11
                                  integration, and all three acceptances on the runner (48/48,
                                  53/53, 69/69)
run #15 20261028T175715Z-87d6a61   all 16 steps ok; 1660 tests in 414 s, 91 stress/edge, 11
                                  integration, and all four acceptances (48/48, 53/53, 69/69,
                                  88/88) - the commit that carries M34. The media containers are
                                  generated on the runner one byte at a time, so the widths, sample
                                  rates and durations are read back from headers that run wrote
run #16 20261028T181313Z-e098a06   all 17 steps ok; 1720 tests in 320 s, 91 stress/edge, 11
                                  integration, and all five acceptances (48/48, 53/53, 69/69,
                                  88/88, 72/72). The dataset acceptance writes its corpus on the
                                  runner, so every hash it checks is arithmetic on content the run
                                  chose - and the manifest is then broken by an edit and a delete
run #26 20261029T164537Z-48dd607   all 24 steps ok; 1951 tests in 536 s, 91 stress/edge, 11
                                  integration, all ten acceptances; scenes 59/59, automation
                                  34/34. Actual bpy 4.2/Cycles CPU render and isolated-wheel
                                  build/install check pass. M39–M41 closure within scope.
                                  GitHub run 40914694127.
run #25 20261029T163024Z-385d386   all 23 steps ok; 1940 tests in 430 s, 91 stress/edge, 11
                                  integration, ten acceptances including scenes 59/59 and
                                  automations 34/34. REAL official Blender 4.2 bpy/Cycles CPU
                                  rendered a 64x64 PNG, 4897 bytes, verified against its hash.
                                  GitHub run 40912224001. Predates M41 hardening/release gate.
run #23 20261029T133321Z-17a4253   all 21 steps ok; 1921 tests in 406 s, 91 stress/edge, 11
                                  integration, and all nine acceptances (scene checks 49/49).
                                  Scene validation runs before allocation/writes. GitHub run
                                  40882983460; this predates task artifact linkage.
run #22 20261029T125336Z-a63016d   all 21 steps ok; 1894 tests in 529 s, 91 stress/edge, 11
                                  integration, nine acceptances (48/48, 53/53, 69/69, 88/88,
                                  72/72, 57/57, 71/71, 65/65, 49/49). M39 scene GUI/API and
                                  CLI/export foundation; the stand-in Blender proves invocation,
                                  not a real render. GitHub run 40877049444.
run #21 20261029T110209Z-ee4dcc6   all 20 steps ok; 1868 tests in 520 s, 91 stress/edge, 11
                                  integration, and eight acceptances (48/48, 53/53, 69/69,
                                  88/88, 72/72, 57/57, 71/71, 65/65) - the commit that carries
                                  M38. The execution acceptance plants a stand-in `docker` on a
                                  two-entry PATH and reads the recorded argv back, so the wrapper
                                  is checked on a runner that has a *real* docker too
run #20 20261029T103134Z-49086f8   **2 failed, 1866 passed**, and the execution acceptance failed
                                  three checks: this was the first M38 run, and ten checks
                                  assumed this machine has no docker CLI. The runner ships
                                  docker. Fixed by manufacturing the absence instead of
                                  asserting it (`THINKING.md` D190) - the failed run is kept here
                                  because that is what it is evidence of
run #19 20261029T101851Z-4b4ec37   cancelled by the trigger push that started #20 (the same
                                  concurrency rule as #7, #9 and #11)
run #18 20261029T090730Z-cce5eef   all 19 steps ok; 1819 tests in 461 s, 91 stress/edge, 11
                                  integration, and seven acceptances (48/48, 53/53, 69/69, 88/88,
                                  72/72, 57/57, 71/71) - the commit that carries M37. The remote
                                  acceptance starts a real worker process on the runner, dispatches
                                  to it, collects the artifact and re-hashes it there, and hands a
                                  lying worker a bundle so the mismatch path runs on CI too
run #17 20261029T083938Z-7a0e67e   all 18 steps ok; 1774 tests in 471 s, 91 stress/edge, 11
                                  integration, and six acceptances (48/48, 53/53, 69/69, 88/88,
                                  72/72, 57/57) - the commit that carries M36. The training
                                  acceptance recomputes the n-gram perplexity with its own
                                  implementation on the runner and fails above a 1e-9 difference,
                                  so the metric is checked against arithmetic rather than itself

$ gh api "repos/archnemix/Archx-Agent/actions/runs?per_page=18" \
    --jq '.workflow_runs[] | {n:.run_number,conclusion}'
{"n":18,"conclusion":"success"}  {"n":17,"conclusion":"success"}
{"n":16,"conclusion":"success"}  {"n":15,"conclusion":"success"}
{"n":14,"conclusion":"success"}
{"n":13,"conclusion":"success"}
{"n":12,"conclusion":"success"}
{"n":11,"conclusion":"cancelled"}
{"n":10,"conclusion":"success"}  {"n":9,"conclusion":"cancelled"}
{"n":8,"conclusion":"success"}   {"n":7,"conclusion":"cancelled"}
{"n":6,"conclusion":"success"}   {"n":5,"conclusion":"success"}
{"n":4,"conclusion":"success"}   {"n":3,"conclusion":"success"}
{"n":2,"conclusion":"failure"}   {"n":1,"conclusion":"cancelled"}

$ ./scripts/ci_logs.sh --run 20261028T115458Z-5e67bd9
run     20261028T115458Z-5e67bd9
commit  5e67bd90bc8409c29fd73b5290e78bc95b4bd8a7
started 2026-10-28T11:54:58Z
finished 2026-10-28T12:01:06Z
failed  0

step                               status     seconds
install                            ok         19
pytest                             ok         258
sdks                               ok         2
llama-cpp                          ok         1
model-download                     ok         2
serve                              ok         1
completion                         ok         0
sdk-matrix                         ok         11
ollama                             ok         62
tunnel                             ok         7
```

`pytest` on the runner: **1251 passed** in 290 s — the same number as this sandbox, which is the
point of running the suite there. The model answered (`docs/ci/model-proof.json`):

```text
text: A tunnel is a sealed, underground passageway that connects two points, often through a
      physical barrier or artificial entrance.
usage: {'completion_tokens': 24, 'prompt_tokens': 40, 'total_tokens': 64}
```

Every client against that endpoint (`scripts/remote_model.sh`, llama.cpp on 127.0.0.1:8080):

```text
--- openai     OK  'Hello, welcome to my little corner of the internet!'  36/12  streamed 6 chunk(s)
--- anthropic  OK  '"Hi! Hello! Hello again!"'                            12/9   streamed 6 chunk(s)
--- google     SKIP  the google client speaks :generateContent; this endpoint does not
--- mistral    OK  'Hello, welcome to my little corner of the internet.'  36/12  streamed 6 chunk(s)
--- groq       SKIP  requests /openai/v1/chat/completions; 404 there
--- together   OK  'Hello!'                                               36/3   streamed 4 chunk(s)
--- cohere     SKIP  no /v2/chat here; the cohere client has nothing to talk to
--- ollama     SKIP  no /api/tags here; the ollama client has nothing to talk to
4 SDK(s) completed a turn, 0 failed
```

A real Ollama daemon in Docker, `ollama pull smollm2:135m` (270 MB), then the client and then
the app:

```text
--- ollama
OK    "Hello, I'm a helpful AI assistant named SmolLM, trained by Hugging Face"   36/19
      base http://127.0.0.1:11434  ->  /api/chat
      streamed 32 chunk(s), 84 chars

$ archx-agent models add-sdk --name ollama-local --sdk ollama --model smollm2:135m \
    --base-url http://127.0.0.1:11434
  runtime  ready - ready: a local Ollama needs no key (no data leaves this machine)
$ archx-agent models probe ollama-local --capability chat
chat: passed  (40 chars, finish_reason=stop)   state now verified (probe passed)
$ archx-agent chat --stream --message "Name one colour." --model ollama-local
I'm afraid I'm not an AI, but I can tell you that one of the most common colours is blue.
```

And a public URL through cloudflared:

```text
url=https://somebody-guided-exclude-rca.trycloudflare.com
public chat HTTP 200
openai SDK via the public URL: Hi, hello.
```

Five defects were found by running it (see `docs/PROVIDERS.md`): the pipe-holding server, the
invalid workflow file, the `sdks` extra missing four clients, streaming after `transport.close()`,
and the per-client base URLs. The last two were invisible to a stub that answered any path; that
stub is now strict.

