# Progress

Last updated: M22 complete (tool registry + permission centre). Next: M23.

## Verified in this session

Everything below was executed in this environment and observed. Commands and outputs are
reproduced in [docs/VERIFICATION.md](docs/VERIFICATION.md).

| Milestone | What was verified | How |
|-----------|-------------------|-----|
| M01-M09 | package installs, `archx-agent --version`, helper invariants (paths, Result, errors, tokens, redaction, config) | `pytest tests/test_foundation.py tests/test_config.py`, CLI smoke |
| M10 | conversation create/append ordering by sequence, context clear preserves history, restart-safe reading | `pytest tests/test_memory_m17.py::TestConversationBasics` |
| M11 | committed-only success, exactly-once by op id, durable two-phase + replay, backpressure=PENDING, graceful drain, multi-thread safety, **SIGKILL mid-write recovery**, multi-process writes | `pytest tests/test_storage.py` |
| M12 | backup/verify/preview/restore-aside, tamper detection, retention | `pytest tests/test_storage.py::TestBackupRecovery`, `archx-agent db ...` |
| M13 | sequence ordering, capture levels, redaction on write and export, causal tree, retention keeps errors longer | `pytest tests/test_storage.py::TestEvents` |
| M14 | trace filters, errors, summary, JSONL export, retention, tree | `archx-agent trace ...` + CLI tests |
| M15 | discovery of GGUF files, facts/claims split, states, preference per task, verification recording | `archx-agent models ...` (see model tests) |
| M16 | OpenAI-compatible HTTP runtime against a real local server: success, 401/402/404/429-rate/429-quota/500, connection refused, malformed body, key never leaked | `pytest tests/test_application.py::TestHttpRuntimeContract` |
| M17 | all six memory kinds stored/retrieved/edited/deleted through the CLI with scope + provenance, duplicate rejection, slot supersession, artifact checksum, restart survival, crash replay, every write traced | `pytest tests/test_memory_m17.py` + CLI acceptance |
| M18 | float32 vectors with model identity, embedding states, cache checksums, degraded keyword fallback, hybrid ranking, model-change staleness, cross-model refusal, full evaluation report | `pytest tests/test_embeddings_m18.py`; `archx-agent eval retrieval` |
| M19 | five strategies build manifests with reasons; oldest-first preserves history; manual selection; summarise keeps originals + source range; ai_proposed requires approval | `pytest tests/test_context_m19.py`; `archx-agent context ...` |
| M20 | provider catalogue keeps facts/claims/user confirmations apart; loopback = local (derived); remote is blocked until privacy confirmed + consent recorded + `model.local_only=false`; availability probe distinguishes reachable/auth/404/429/500/refused; quotas enforced; usage and cost attributed per request | `pytest tests/test_providers_m20.py` (30); `scripts/acceptance_m20.sh` (real HTTP server) |
| M22 | tools declare capability/risk/dry-run; ungranted operations are refused with an approval id; approval mints exactly the requested grant; scoped grants (once/task/conversation/project/persistent) are checked, single-use grants consumed before the work; sandbox refuses traversal, absolute escapes and symlink escapes; argv-only processes with a denylist, minimal env and timeouts; every attempt (including denials) has a `tool_runs` row and trace events | `pytest tests/test_tools_m22.py` (78) + `tests/test_cli.py::TestCliTools` (13); `scripts/acceptance_m22.sh` (real files and processes) |
| M21 | capability states with evidence (verified/inferred/unverified/unsupported/unavailable); eligibility before score; a model whose runtime is missing is refused; probes record measurements; `require_verified` policy; remote never auto-chosen; fallback is traceable and never silent | `pytest tests/test_router_m21.py` (33); `scripts/acceptance_m21.sh` |

**Test suite: 381 tests, 0 failures, 0 skipped** on Python 3.11.2 (see note in GAPS
about 3.13 and about llama.cpp).

## Acceptance evidence

* M17: `docs/VERIFICATION.md#m17-acceptance` - each of the six kinds added, listed,
  shown with provenance, edited (version 2 + history), searched, retrieved under a budget
  and deleted, with trace events for every write.
* M18: `docs/RETRIEVAL_EVAL.md` - keyword nDCG 0.637, semantic (lexical-hash) 0.839,
  hybrid 0.850, on a 20-item corpus with 12 graded queries.
* M19: `docs/VERIFICATION.md#m19-acceptance` - manifests for all five strategies,
  including omitted reasons and proof that stored history is unchanged.
* M22: `docs/VERIFICATION.md#m22-acceptance` - a real write is refused, approved, then
  really written; the single-use grant is spent; a read in another conversation is
  denied; traversal/absolute/symlink escapes are refused; a real subprocess runs, a real
  failing command is a failed run, a real `sleep 30` is killed at 2s, and `sudo`/`dd` are
  refused in a way that cannot be approved.
* M21: `docs/VERIFICATION.md#m21-acceptance` - a discovered GGUF is refused because
  llama.cpp is missing (not routed to and silently failed), a probe flips `inferred` to
  `verified`, `require_verified` refuses then allows, a remote model is never chosen
  automatically, and a dead endpoint falls back visibly.
* M20: `docs/VERIFICATION.md#m20-acceptance` - a real OpenAI-compatible HTTP server is
  registered as a local provider, probed, chatted through, and charged for; a cloud
  provider is refused until confirmed + consented; a remote model is refused while
  `local_only` is true.

## Next steps (in order)

1. M23: MCP client (real subprocess/stdio + HTTP transports), optional server, extension
   trust boundary.
2. M24: unified task history + version links + reproduction records.
3. M25 onward per PLAN.md.

## Known breakage

None known. `GAPS.md` lists limitations (no reachable model weights, single Python
version, no GUI yet).
