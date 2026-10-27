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

## Adding a provider

1. `providers add <name> --template <slug>` (or `--base-url` for anything custom);
2. `providers confirm ...` with the terms *you* read;
3. `providers consent <name>`;
4. `models add-http --name <model> --base-url <url> --model <model_ref>`;
5. `archx-agent chat` - and if the provider is remote, `model.local_only` must be `false`
   first, which is a deliberate, visible change rather than a silent default.
