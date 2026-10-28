# Providers, privacy metadata and consent

Archx is local-first, not local-only. Remote providers are supported, but **nothing is
sent off the machine unless the user has done three things**:

1. turned off `model.local_only` (default `true`);
2. confirmed what the provider does with the data (or used a loopback endpoint, where the
   answer is derived from the URL rather than from a claim);
3. recorded explicit consent for that provider, at the current consent version.

All three are enforced in `Workspace.assert_remote_allowed`, not in the UI, so a new
interface or a future tool cannot bypass them.

## The model

```
providers
  id, name, slug, kind (local|cloud|custom), api_style (openai|anthropic|gemini|custom)
  base_url, model_family
  credential_ref          -- secret://env/NAME, never the key
  is_local                -- derived from a loopback URL, not from a label
  privacy                 -- JSON: vendor CLAIMS
  privacy_confirmed       -- JSON: what the USER confirmed
  claim_source            -- where the claims came from
  verified                -- were the claims independently checked? (normally 0)
  consent_at, consent_version
  price_in_per_1k, price_out_per_1k, currency, quotas
provider_checks  -- timestamped availability results (reachable/auth_failed/unreachable/...)
provider_usage   -- append-only per-request events (tokens, success, error)
```

Three ideas are deliberately separated:

| thing | where it lives | trust |
|-------|----------------|-------|
| what the vendor documents | `privacy` + `claim_source` | **claim**, may be wrong or out of date |
| what the user confirmed | `privacy_confirmed` | user statement, wins over the claim |
| what the endpoint is | `base_url`, `is_local` | fact, derived mechanically |

The effective view (`Provider.effective_privacy`) merges them and reports the source of
each field, so a UI can render *"data leaves device: yes (you confirmed)"* rather than a
bare boolean that hides where the belief came from.

## Local versus remote

* A **loopback** `base_url` (`127.0.0.0/8`, `localhost`, `::1`) is local. `data_leaves_device`
  is derived as `false` from the URL; consent is not required, and asking for consent is a
  recorded no-op rather than a fake ceremony.
* Anything else is remote. Registration *starts blocked*: the vendor claims are shown but
  the provider cannot be used until the user confirms the terms.

Contradictions are refused: you cannot confirm "data leaves device: yes" for a loopback
endpoint, and you cannot register `kind=local` with a non-loopback URL.

## Reading the CLI

```bash
archx-agent providers catalogue                 # templates: claims + where they came from
archx-agent providers add cloud --template openai --auth-ref secret://env/OPENAI_KEY
archx-agent providers privacy                   # table with the source of each belief
archx-agent providers confirm cloud --data-leaves-device yes \
    --retention "vendor: up to 30 days" --training-use "vendor: not used for training"
archx-agent providers consent cloud --note "accepted remote processing for this project"
archx-agent providers check cloud               # GET /models only; never prompt content
archx-agent providers quota cloud --requests-per-day 200 --tokens-per-day 500000
archx-agent providers usage cloud --by-day
archx-agent providers revoke cloud              # takes effect immediately
```

`providers check` exits `0` when healthy, `3` when the probe failed (degraded) and `2` on
a usage error, so scripts can tell "unreachable" apart from "bad arguments".

## Quotas and cost

* A declared daily quota is enforced by Archx *before* a request would exceed it
  (`QuotaExhaustedError`), independent of whether the provider would also enforce one.
* Cost is only ever an **estimate** and only when the user supplies prices; without
  prices `estimated_cost` is `null` and `cost_is_estimate` is `false`. Archx does not
  carry a price list that would silently go stale.
* Usage is recorded per request with prompt/completion tokens as reported by the
  provider, plus errors, so a provider that starts failing is visible in the same table.

## What is verified, and what is not

Verified in this repository:

* the privacy/consent state machine, including version bumps and revocation
  (`tests/test_providers_m20.py::TestConsent`);
* availability probing against a real HTTP server: reachable, 401, 404, 429, 500,
  connection refused, missing secret (`TestAvailability`);
* that the auth header is actually sent from a `secret://` reference and never stored;
* that a remote model is refused while `model.local_only` is true, refused when its
  endpoint has no registered provider, and refused when the provider lacks confirmation or
  consent (`TestWorkspaceEnforcement`);
* end-to-end chat through a real OpenAI-compatible HTTP server
  (`scripts/openai_protocol_stub.py`), with usage attributed to the provider
  (`scripts/acceptance_m20.sh`, transcript in `docs/VERIFICATION.md`).

Not verified here:

* no vendor API was called - there are no keys in this environment. The templates'
  privacy claims are transcribed from vendor documentation and marked as unverified;
  they must not be presented as audited facts;
* pricing is unverified for the same reason, which is why no default prices ship;
* region/residency claims are stored as text, not interpreted.

## Google Gemini (a second wire protocol)

Google's API is not OpenAI-shaped: it has no `/chat/completions`, no `messages` array and no
`max_tokens`. Rather than translate one vendor's body into another's and hope, a second
runtime speaks it directly - `adapters/gemini_runtime.py` (`runtime_id = "gemini"`,
`provider = "google"`).

```bash
archx-agent models add-gemini --name flash --model gemini-2.0-flash \
    --credential-ref secret://env/GEMINI_API_KEY     # the default, and the only form accepted
archx-agent models probe flash --capability chat     # a real call; a pass is a measurement
archx-agent chat --message "hello" --model flash
```

The endpoint is `https://generativelanguage.googleapis.com/v1beta/models/<id>:generateContent`
(and `:streamGenerateContent?alt=sse` for streaming). What the client builds and parses:

| Archx | Gemini |
|-------|--------|
| `{"role": "system"}` | `systemInstruction.parts[].text` (never a `contents` entry) |
| `user` / `assistant` | `contents[].role` = `user` / `model`; consecutive same-role turns are merged, because the protocol alternates |
| `temperature`, `top_p`, `max_tokens`, `stop` | `generationConfig.{temperature,topP,maxOutputTokens,stopSequences}` |
| the reply | `candidates[0].content.parts[].text`, skipping parts marked `thought: true` |
| `finish_reason` | `STOP` -> `stop`, `MAX_TOKENS` -> `length`, `SAFETY` -> `safety` |
| token counts | `usageMetadata.{promptTokenCount,candidatesTokenCount,totalTokenCount}` |
| a refusal | `promptFeedback.blockReason` is an error, not an empty answer |

The key is sent only as the `x-goog-api-key` header - never in the query string, so it cannot
end up in a URL that gets logged - and it is resolved from the reference at request time,
registered with the redactor, and wiped on `close()`.

### The failure taxonomy

A provider that returns every problem as "something went wrong" is unusable, so each case maps
to its own domain error with its own retry flag:

| upstream | classified as | retried |
|----------|---------------|---------|
| 400/401/403, or a message saying the key is invalid | `AuthDeniedError` | no |
| 404, "model not found" | `ModelNotFoundError` | no |
| 429 naming quota, billing or credits | `QuotaExhaustedError` (`EntitlementError`) | no |
| 429 for a burst limit | `RateLimitedError` | yes |
| 5xx | `ProviderOutageError` | yes |
| a non-JSON body | `MalformedOutputError` | no |
| empty parts together with `SAFETY` | `MalformedOutputError` | no |
| `promptFeedback.blockReason` | `ProviderError`, naming the reason | no |

Gemini reports **both** a per-minute rate limit and an exhausted plan quota as
`429 RESOURCE_EXHAUSTED`, so the split is made on the message. Telling a user to buy capacity
over a burst limit is the kind of advice that costs money.

Google echoes the offending key back inside its "API key not valid" message, so anything that
becomes an error message is redacted to `[REDACTED]` before it is shown, traced or exported;
`[REDACTED]` stays visible rather than being deleted, so a caller can see that the vendor
repeated it. `scripts/acceptance_gemini.sh` asserts exactly this.

### Is any of it verified?

Verified here, against a real socket:

* a real Gemini client driven end to end against `scripts/gemini_protocol_stub.py`, which
  speaks the documented protocol (`pytest tests/test_gemini_m21.py`, 56 tests);
* the four-rung consent ladder applied to this runtime, in the CLI and over HTTP
  (`TestWorkspace`, `TestGui`);
* the error taxonomy above, the redaction, streaming, and the fact that neither the database,
  the trace, the logs nor the page ever contains the key;
* `scripts/acceptance_gemini.sh`, 60 self-checking assertions.

**Not verified:** that Google's service behaves as documented *today*. This sandbox's egress
filter closes the TLS connection to `generativelanguage.googleapis.com`, so no live call was
possible from here. The client's side of the protocol is proven; the vendor's side is not, and
no document in this repository claims otherwise.

### The same four gates, in the page

`GET /api/models` returns each model's `gates`: `consent_policy`, `provider`, `privacy`,
`consent`. They are computed by the same conditions `Workspace.assert_remote_allowed` enforces,
so the page cannot show a green ladder for a call the workspace would refuse. The Models panel
draws one row per rung and offers the button that climbs it
(`POST /api/settings/model.local_only`, `POST /api/models/{id}/provider`,
`POST /api/providers/{id}/privacy`, `POST /api/providers/{id}/consent`). A rung that cannot be
climbed yet stays visible with the reason instead of disappearing.

## The official SDKs (a second way to reach the same vendors)

Archx speaks two wire protocols itself (`openai-http`, `gemini`). That keeps the dependency
list empty, but it also means "we parse this vendor's response correctly" is only ever checked
against our own reading of the docs. So there is a second path, `runtime=sdk`, which drives the
**vendor's own client**:

| `sdk` | distribution | what the client wants | key variable |
|-------|--------------|-----------------------|--------------|
| `openai` | `openai` | `base_url` (append `/v1` yourself) | `OPENAI_API_KEY` |
| `anthropic` | `anthropic` | `base_url` | `ANTHROPIC_API_KEY` |
| `google` | `google-genai` | `http_options.base_url` | `GEMINI_API_KEY` |
| `mistral` | `mistralai` | `server_url` (module `mistralai.client`) | `MISTRAL_API_KEY` |

```bash
archx-agent models sdks                       # which clients are importable here, and each one's variable
archx-agent models add-sdk --name oai --sdk openai --model gpt-4o-mini
archx-agent models probe oai --capability chat
archx-agent chat --message "hello" --model oai
```

`--credential-ref` defaults to that vendor's own variable, as a `secret://` reference; a
literal key is refused with exit 2, exactly as for Gemini. The SDKs are **optional**: if one is
missing, `models sdks` says so, `models probe` refuses with the `pip install` line, and the
tests for that client skip instead of failing.

Three decisions are baked into `adapters/sdk_transport.py`:

* **no hidden retries.** Every client is constructed with `max_retries=0`. Retrying is the
  router's job - it knows which errors are retryable and records the fallback - and an SDK that
  silently retries twice turns one refused call into three.
* **parameters are feature-detected, not assumed.** Vendors move them: `anthropic` 2.x dropped
  `temperature` from `messages.create`, and OpenAI grew `max_completion_tokens` beside
  `max_tokens`. Passing an unsupported keyword is a `TypeError` instead of a request, so the
  transport asks the client what it accepts and sends exactly one token-budget name.
* **one taxonomy.** `401/403` → `AuthDeniedError`, `404` → `ModelNotFoundError`, `429` with
  quota/billing wording → `QuotaExhaustedError` (else `RateLimitedError`), `5xx` →
  `ProviderOutageError`, connection errors → `NetworkFailureError`, an empty reply →
  `MalformedOutputError`. Clients disagree about where the status lives (`status_code`
  attribute, `401 None.` at the start of a Google message, `Status 401` inside a Mistral
  sentence), so the classifier reads both the class name and the text.

An SDK model is gated exactly like the raw ones: `sdk` is in `Workspace.NETWORK_RUNTIMES`, so
the four rungs (`model.local_only`, registered provider, privacy confirmed, consent) apply
before anything is sent.

## Running a real model on a CI runner and pointing the SDKs at it

`.github/workflows/local-model-tunnel.yml` serves **SmolLM-135M in Q4_K_M** (~100 MB, 4-bit)
with llama.cpp on a GitHub runner, proves a completion, and exposes it through a Cloudflare
quick tunnel; the URL lands in `tunnel-url.txt` (an artifact and the job summary).

```bash
gh workflow run local-model-tunnel.yml -f keep_alive_minutes=10
gh run download --name tunnel-url          # tunnel-url.txt + model-proof.json
./scripts/remote_model.sh                  # reads tunnel-url.txt, tries every SDK
./scripts/remote_model.sh <url> --sdk openai --sdk mistral
```

`remote_model.sh` runs each installed client against that one endpoint and then registers the
same endpoint in Archx (`models add-sdk` + `models probe`) so the app, not just the SDK, has to
work. It exits `0` if at least one client completed a turn and `3` if none did, so CI can tell
"the endpoint is wrong" from "the script broke".

Two honest caveats: a quick tunnel is **unauthenticated and public** for as long as it runs, so
treat the model as exposed; and the runner has no GPU, so the 135M model answers at a few
tokens per second - which is fine, because the question is "did a token come out", not "is it
good".

## Adding a provider

1. `providers add <name> --template <slug>` (or `--base-url` for anything custom);
2. `providers confirm ...` with the terms *you* read;
3. `providers consent <name>`;
4. `models add-http --name <model> --base-url <url> --model <model_ref>`
   (or `models add-gemini` for Google);
5. `archx-agent chat` - and if the provider is remote, `model.local_only` must be `false`
   first, which is a deliberate, visible change rather than a silent default.
