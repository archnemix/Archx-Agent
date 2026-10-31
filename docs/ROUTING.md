# Capability-safe routing

A capability is a claim until something measured it. Archx therefore stores, for every
model and every capability, a *state* and the evidence behind it, and the router refuses
to route on anything weaker than the workspace's policy allows.

## Capability states

| state | meaning | evidence | may be routed to |
|-------|---------|----------|------------------|
| `verified` | a probe of **this model** succeeded and is recorded | `model_capability_tests` row with `outcome=passed` | yes |
| `inferred` | our own adapter implements it (a fact about our code) | `RUNTIME_BASELINE_CAPABILITIES` | yes, unless `router.require_verified` |
| `unverified` | it was claimed (filename, catalogue, user) and never exercised | claim only | only for `chat` (default) or with `--allow-unverified` |
| `unsupported` | a probe measured it as broken | `outcome=failed` | **never** |
| `unavailable` | the artifact or runtime is missing here | model state / dependency check | **never** |

Precedence is deliberately strict: a failed probe beats any claim, and a passed probe beats
a label **while the artifact is available and the evidence belongs to its current observed file identity**.

Three things keep this honest:

1. **`inferred` is not `verified`.** "the `llama-cpp` adapter implements chat" says our code
   can drive a model, not that a particular file works. `router.require_verified = true`
   makes the difference visible by refusing `inferred` chat.
2. **Probes are measurements.** `archx-agent models probe <model> --capability chat` loads
   the runtime, sends a tiny prompt, inspects the answer and records the outcome with
   latency. Failures are recorded too (and traced).
3. **Capabilities that cannot be measured are refused.** `models probe … --capability
   vision` is rejected: there is no vision adapter in this build, and inventing a pass
   would be worse than admitting it. OCR, transcription and image generation follow the
   same rule until their adapters exist (M34+).

## Eligibility

A model may be chosen only when **all** of these hold:

* its catalogue state is `usable` (the file exists, or the endpoint is configured);
* its runtime reports it can start here — checked cheaply, without loading weights
  (`Workspace.runtime_availability`);
* every required capability is `verified`/`inferred`, or explicitly allowed;
* if the endpoint is remote: the router is allowed to choose remote models
  (`router.allow_cloud`, default **false**) **and** every privacy gate from M20 passes;
* the context window is at least what the task needs (when the caller states a minimum);
* if it is the simulated test double: `--allow-simulated` was given.

Rejections are recorded per candidate, so `models route` and the trace both answer
"why not that one?".

## Local catalogue observations

`models discover --dir /path/to/gguf` scans GGUF files, not directories named `.gguf`.
With no configured directory the manager does not scan the process cwd accidentally.
`models list` refreshes local observations, and enabling a local row rechecks the file.
A regular file below 1,024 bytes is invalid; 1,024 bytes is only an eligibility threshold,
not proof of a valid GGUF header, loadability or model quality.

Refresh covers the whole catalogue, not just its first 200 display rows. User disablement
survives discovery, disappearance and restoration. Metadata (name, preferred task,
context length) is not reset by re-discovery. Missing/unusable files report unavailable
capabilities even if older probes passed.

Changed observed file identity clears current capability declarations/proof, while the
old probe rows remain in history. A stored probe-row watermark excludes those old rows
from current eligibility. Legacy rows without an identity snapshot are conservatively
revalidated. Signatures use device/inode/size and nanosecond mtime/ctime; they are not
adversarial byte-identity guarantees. If a digest was explicitly recorded, normal
refresh/default re-registration recomputes it. `hash_file='never'` explicitly opts out.
No observation eliminates filesystem races or replaces an actual inference probe.

## Ranking

```
score = 100*verified + 60*inferred + 10*unverified (per required capability)
      + 40 if the user marked the model preferred for this task
      + 20 if it is the configured default model
      + 25 if it is local and router.prefer_local
      - 80 if it is the simulated test double
      -  5 per recorded failure
```

Eligibility is decided first; the score only orders eligible models. That ordering matters:
a scoring function can be tuned, an eligibility list cannot be argued with.

## Decisions are artefacts

Every routing decision is written to the trace (`model.routed` / `model.route_failed`) with
the required capabilities, the chosen model, the fallback chain, and each rejected
candidate's reasons. `ChatReply.model.routing` carries the same structure into the API
response, so the reply explains itself.

## Fallback

`router.fallback` (default true) allows a second model after a **retryable** provider
failure (network failure, rate limit, 5xx). It is not a retry of the same model, and it is
never silent:

* the failure is traced (`model.failed`) and counted against the failing model;
* a `model.fallback` trace event records from → to;
* the reply lists the substitution in `warnings` and sets `model.fallback_from`;
* the conversation switches to the model that actually answered.

Non-retryable failures (401/402/404, unsupported capability) are **not** retried on another
model: a missing key does not become a different key by asking a different provider, and
`403`-style policy errors should surface to the user. A fallback whose context window
cannot hold the manifest that was already built is skipped with a warning rather than
truncating the context silently.

## Commands

```bash
archx-agent models capabilities [model]        # states + the evidence for each
archx-agent models probe <model> --capability chat|tools|json
archx-agent models route [--task chat] [--require ocr] [--min-context 8000]
                        [--allow-unverified] [--allow-cloud] [--model <id>] [--json]
archx-agent chat -m "..." --model <id>         # explicit choice (still subject to consent)
```

Configuration:

| key | default | effect |
|-----|---------|--------|
| `router.require_verified` | `false` | only `verified` capabilities may be routed |
| `router.allow_unverified_chat` | `true` | chat may use a claimed-but-unproven capability (recorded) |
| `router.allow_cloud` | `false` | the router may choose remote models on its own |
| `router.prefer_local` | `true` | local models win ties |
| `router.fallback` | `true` | try the next eligible model after a retryable failure |
| `router.max_fallbacks` | `2` | cap on fallback attempts |

## What is verified, and what is not

Verified in this repository (`tests/models/test_router_m21.py`, 33 tests):

* state precedence, including failed-probe-beats-claim and latest-probe-wins;
* that a missing `llama-cpp-python` makes the model ineligible with that exact reason
  (this environment has no llama.cpp, so the refusal path is exercised for real);
* that a capability the build cannot measure (`vision`, `ocr`) is never invented;
* `require_verified` flipping a decision before and after a probe;
* remote models never chosen without `router.allow_cloud`, and still blocked by the M20
  consent gates when allowed;
* explicit `--model` bypassing the "router chooses only local" policy but **not** the
  consent gates;
* context-window exclusion, unknown-capability rejection, `no usable model` messages
  naming how to add one;
* fallback on a retryable failure with trace events, warnings and `fallback_from`;
* no fallback on a 401;
* every decision traced with rejected candidate reasons.

Not verified here: real model quality, and any capability whose adapter does not exist in
this build (vision, OCR, audio, video). Those are `unavailable`, not "probably fine".
