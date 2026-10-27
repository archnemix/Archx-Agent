# Gemini completion report - a real second provider

## 1. Objective

The request was to "build it completely and test it, with this Gemini key". That is a claim about
reality, so the deliverable is not a new menu item; it is a path that either really talks to
Google or says precisely why it cannot:

* `models add-gemini` registers a model whose credential is a **reference**, and refuses a
  literal key;
* a chat turn is built for *Gemini's* protocol, not a translation of the OpenAI one;
* the key never appears in a URL, a database row, a trace, a log or a page;
* every upstream failure becomes its own domain error, with its own retry decision;
* the M20 consent gate covers the new adapter, in the CLI and in the GUI;
* the GUI can register a model, measure it, and walk the consent ladder;
* and where the environment makes a live call impossible, the documentation says so instead of
  implying a success.

## 2. What was built

| Piece | Path |
|-------|------|
| the runtime | `src/archx_agent/adapters/gemini_runtime.py` |
| one registration path for both interfaces | `Workspace.register_gemini` |
| the gate, generalised | `Workspace.NETWORK_RUNTIMES` + `assert_remote_allowed` |
| CLI | `models add-gemini …` |
| HTTP API | `GET /api/models` (`gates`, `provider_id`), `POST /api/models`, `/probe`, `/provider`, `GET /api/providers`, `/privacy`, `/consent`, `POST /api/settings/model.local_only` |
| the page | a *Connect Gemini* form, `test chat`, and the four-rung consent ladder |
| harnesses | `scripts/gemini_protocol_stub.py`, `scripts/acceptance_gemini.sh`, `scripts/gui_smoke.mjs` |
| tests | `tests/test_gemini_m21.py` (56) |

## 3. The decisions worth recording

**D135. A vendor's protocol gets an adapter, not a translation layer.** Rewriting Gemini's
`contents` into `messages` and posting to `/chat/completions` would have hidden
`systemInstruction`, `thought` parts, `promptFeedback` and a 429 that means two different
things.

**D136. One allow-list decides what may touch the network.** `assert_remote_allowed` used to name
the OpenAI-compatible runtimes; a second adapter would have sat outside the gate by default. The
gate now reads `NETWORK_RUNTIMES`, and a test asserts the set covers every network transport.

**D137. The page's ladder is computed by the enforcement code.** `gates` comes from the server,
built beside `assert_remote_allowed`; the acceptance script asserts the ladder reads green
exactly when a call would succeed. A UI that disagrees with the gate teaches the user to expect
a refusal.

**D138. Ambiguous statuses are classified by message.** Gemini returns `429 RESOURCE_EXHAUSTED`
for a burst limit *and* an exhausted plan. Both were tested, in both directions.

**D139. A redaction that deletes the evidence is not a redaction.** The vendor echoes the
offending key in its 400 body; the message is kept and the key becomes `[REDACTED]`. A test
asserts the token is *present*, so a future "cleanup" that drops the message fails.

**D140. One registration path for two interfaces.** The CLI and the panel both call
`Workspace.register_gemini`, so "credentials are references" is enforced once.

## 4. Evidence

```text
pytest -o addopts="" -q                       1190 passed in 253.19s
scripts/acceptance_gemini.sh                  Gemini acceptance: 60 checks passed
scripts/acceptance_m29.sh                     M29 acceptance: 55 checks passed
scripts/acceptance_m30.sh                     M30 acceptance: 90 checks passed
scripts/acceptance_research_close.sh          Research closure acceptance: 35 checks passed
ARCHX_JSDOM_DIR=/tmp/domtest node scripts/gui_smoke.mjs
                                              smoke ok: 10 tabs, 4 rungs, form posts, no page errors
```

The acceptance run starts and stops the protocol stub eight times (ok, 401, 400-echo, 429 burst,
429 quota, 404, blocked, empty, 500) and asserts the classified error each time, then climbs the
ladder rung by rung and checks that the four refusals are distinct sentences. It finishes by
grepping every file under the home for the key: zero hits.

## 5. What is *not* proven

A live call to Google was not possible from this sandbox: TCP to
`generativelanguage.googleapis.com:443` connects and the TLS handshake is closed by the egress
filter (`SSLZeroReturnError`), while `api.github.com` answers normally. That is the environment,
not the client - but it means the vendor's half of the protocol is unverified, and no document
here claims otherwise. On a machine with normal egress:

```bash
export GEMINI_API_KEY=...                                   # the real key, in the environment only
archx-agent models add-gemini --name flash --model gemini-2.0-flash
archx-agent providers add google --template google
archx-agent providers confirm google --data-leaves-device yes
archx-agent providers consent google
archx-agent config set model.local_only false
archx-agent models probe flash --capability chat            # a real measurement
archx-agent chat --message "hello" --model flash
```

If any of that fails, the error names the layer (`AuthDeniedError`, `QuotaExhaustedError`,
`RateLimitedError`, `ModelNotFoundError`, `ProviderOutageError`), which is the difference between
"it doesn't work" and a next step.

## 6. Left undone, on purpose

* No embedding runtime for Gemini: `embedContent` is a different endpoint and nothing in this
  build routes embeddings to a remote provider yet.
* No tool/function calling: `capabilities` would have to be *measured* before it could be
  offered, and `models probe --capability tools` needs a probe that inspects a tool call.
* No vision or audio: no adapter exists, so `models probe` refuses those capabilities by name.
