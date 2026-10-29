# Hardening and release readiness (M41)

M41 is a tested source/wheel readiness gate, not a published binary release or a security audit
certification. M39/M40 scope and platform limitations remain documented; closing the roadmap does
not imply every feature in GAPS.md exists. There is no automatic publish, tag, installer, signing,
SBOM or reproducible dependency lock in this milestone.

## Release gates

1. Full pytest suite, plus independent stress/hostile-client and integration suites on CI.
2. All milestone acceptance scripts through M40; failed/refused work is checked, not omitted.
3. GUI smoke for all 20 tabs, including scene edits/render refusal and automation enable/tick.
4. A real headless Blender render: official `bpy==4.2.0`, `numpy<2`, native libraries, Cycles CPU.
   `scripts/blender_real_check.py` renders a cube, validates dimensions and byte hash, and verifies
   the scene ledger. The adapter executes Blender's Python runtime, not the standalone Blender
   desktop binary. Other Blender versions/engines/platforms are not validated by this check.
5. `scripts/release_check.sh`: build wheel and sdist, create an isolated venv, install the wheel
   without dependencies or access to the source tree, run `pip check`, CLI/schema smoke and GUI
   asset loading. Build prerequisites: `build`, `wheel`, `setuptools>=68`. Runtime dependencies
   remain empty. Build artifacts and temporary environments are not committed.
6. CI model/SDK interoperability remains a gate independently of local model availability.

## Hardening regressions

- Malformed, negative, duplicate, excessively long or transfer-encoded HTTP body framing is
  refused before reading a body. In particular `Content-Length: -1` cannot become `read(-1)`.
- Oversized base64 file writes are rejected before decoding, then exact decoded byte length is
  checked again by the jailed file runtime.
- Command jobs spool stdout/stderr to temporary files while running instead of leaving output
  pipes undrained. Megabyte output no longer stalls a child until timeout. Only a bounded prefix
  is loaded into memory and the result is explicitly truncated. Spool disk use is bounded by the
  process lifetime, not an enforced byte quota; run untrusted programs in an appropriate boundary.
- Every automation command checks current `shell.run` authority at execution and consumes single-use
  grants. An enqueue-time grant revoked before execution does not authorize the job. A refused
  automated command closes its own task as failed rather than leaving it running.
- Job deadline/cancel/recovery tests continue to pass; scheduling revisions are transactionally
  compared so simultaneous ticks do not duplicate an occurrence.
- GUI HTML/JS/CSS are explicitly included in the built wheel, not merely present in editable installs.
- The repository's declared MIT licensing now has a matching LICENSE file.

## Supported/verified scope

Linux, Python 3.11, local SQLite, local GUI, built-in geometry and explicit polling automations.
A native Blender desktop install, Windows/macOS, multiple Python versions, hardware GPU rendering,
cloud accounts, cron/DST, signed installers and production multi-user deployment are not proven by
this gate. The GUI is local-first, token-protected and not a public multi-tenant service.

Legacy manually submitted `command` jobs remain an explicit trusted local execution interface;
they are not a sandbox. Automation-created jobs add execution-time capability checks. Workflow/tool
operations keep their existing permission paths. Local rendering likewise has local-machine
privileges. Use M38's supported boundaries where applicable; a label is not isolation.

## Operator checklist

- Back up a nonempty home before upgrading; workspace migrations also honor `storage.auto_backup`.
- Install from the reviewed wheel into a clean environment; verify the CI evidence matches its commit.
- Keep tokens private; do not bind the GUI publicly without a reviewed deployment boundary.
- Keep execution disabled and automation definitions disabled until deliberately configured.
- Grant capabilities narrowly; enabling a schedule is not a grant.
- Use bounded timeouts; commands must be idempotent if an operator may retry external side effects.
- Rollback means restoring both the prior application and a matching database backup; schema downgrade
  is not implemented.

Verification logs and exact commit identities: `docs/VERIFICATION.md`, `docs/ci/` and the workflow's
published `ci-logs` branch. No release is claimed green until the final run completes successfully.
