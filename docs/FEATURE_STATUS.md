# Current implementation inventory and Research Mode requirement

## Counting rule — do not call milestones original features

This is a working inventory reconstructed from PLAN.md and the implemented limits in
MODES.md/GAPS.md, not a separately approved original specification. Counts use the **41
numbered roadmap units**: M01–M09 contributes nine, each later milestone contributes one.
They mix foundations, features and release work, so they are not 41 equally sized user features.

- **31 units have working implementations within their recorded technical scope.** This
  does not establish that 31 original user features are fully accepted.
- **10 broad areas are partial/incomplete** against the larger product intent. They contain
  multiple missing capabilities; ten areas is not a count of all remaining implementation tasks.
- Dataset preparation is conservatively partial here (as already stated in MODES.md), even
  though PLAN.md's historical M35 checkpoint says done. Historical checkpoint text is not
  silently rewritten. Research explicitly fails the user's clarified requirement below.
- No original-product completion percentage or remaining-hours estimate is inferred.
  The separate 36/36 structural checklist is not this feature inventory.

## Inventory

| Roadmap unit | Recorded area | Counting units | Current assessment |
|---|---|---:|---|
| M01–M09 | Foundations, package, configuration and terminal interfaces | 9 | Implemented within recorded scope |
| M10 | SQLite conversations, `--resume`, `/conversations` | 1 | Implemented within recorded scope |
| M11 | Storage reliability: coordinator, journal, exactly-once, backpressure, backup, preferences | 1 | Implemented within recorded scope |
| M12 | Backup/restore/`--check-db`/preview | 1 | Implemented within recorded scope |
| M13 | Structured events, redaction, capture levels, causal tree, sequence ordering | 1 | Implemented within recorded scope |
| M14 | Debug & Trace interface: filters, summaries, export, retention | 1 | Implemented within recorded scope |
| M15 | Model catalogue + local discovery (facts vs claims vs user metadata) | 1 | Implemented within recorded scope |
| M16 | Provider adapter boundary + catalogue-aware resolution + key hygiene | 1 | Implemented within recorded scope |
| M17 | Memory persistence foundation (six systems) | 1 | Implemented within recorded scope |
| M18 | Embedding + retrieval evaluation | 1 | Implemented within recorded scope |
| M19 | Context Strategy Manager (five strategies) | 1 | Implemented within recorded scope |
| M20 | Cloud provider catalogue + privacy metadata | 1 | Implemented within recorded scope |
| M21 | Capability-safe model router + model management | 1 | Implemented within recorded scope |
| M22 | Tool registry + Permission & Approval Center | 1 | Implemented within recorded scope |
| M23 | MCP client/server + extension foundation | 1 | Implemented within recorded scope |
| M24 | Task history, content versions, reproduction records | 1 | Implemented within recorded scope |
| M25 | Agent workflows: user-directed and model-proposed, with subagents | 1 | Implemented within recorded scope |
| M26 | Resource and job scheduler | 1 | Implemented within recorded scope |
| M27 | Simple Mode and unified search | 1 | Implemented within recorded scope |
| M28 | Researcher Mode | 1 | Partial against broader product scope |
| M29 | GUI core workflows | 1 | Implemented within recorded scope |
| M30 | Learning Mode | 1 | Partial against broader product scope |
| M31 | Coding workspace | 1 | Implemented within recorded scope |
| M32 | Experimental Mode | 1 | Implemented within recorded scope |
| M33 | Play Mode | 1 | Implemented within recorded scope |
| M34 | Voice and multimodal foundation | 1 | Partial against broader product scope |
| M35 | Dataset preparation | 1 | Partial against broader product scope |
| M36 | Training and model modification | 1 | Partial against broader product scope |
| M37 | Remote compute and portability | 1 | Partial against broader product scope |
| M38 | Execution environments and sandboxing | 1 | Partial against broader product scope |
| M39 | Blender and 3D workflows | 1 | Partial against broader product scope |
| M40 | Automations and scheduled tasks | 1 | Partial against broader product scope |
| M41 | Hardening and release readiness | 1 | Partial against broader product scope |

## Ten known partial areas and missing capability examples

| Area | Missing or narrower than requested |
|---|---|
| Research | AI research conversation, autonomous web search/discovery, follow-up searches without requiring URLs |
| Learning | Model/rubric-based assessment and richer generated/media exercises |
| Voice/media | Actual speech recognition/synthesis and broader media handling |
| Datasets | Broader formats, richer cleaning/transforms, tokenisation/chat templates and publishing |
| Training | Transformer fine-tuning, GPU workflows and serving integration |
| Remote/cloud | Managed provisioning, resumable transfers and distributed execution |
| Execution/isolation | Stronger containment and broader real backend/platform certification |
| Blender/3D | Broader editing/animation/rendering workflows, not only measured primitives/export/render path |
| Automations | Cron/timezone scheduling, external triggers and managed service operation |
| Release/hardening | Published installers/releases, broader platform certification and remaining operational hardening |

Operational gaps such as worker/MCP recovery and global quotas also remain; they are not
pretended to fit into a finite missing-feature count just because this table has ten rows.

## Research acceptance criteria — clarified by the user, 31 October 2026

**Status: not implemented.** The current source-report workflow is useful for analysing a
known document set, quoting passages, comparing supplied sources and retaining an audit trail.
It does not satisfy the requested AI research experience, because discovery is left to the user.

The required default experience is:

1. The user enters a question in an AI chat; no URL list is required.
2. The AI generates and revises web-search queries, discovers sources, opens relevant pages
   and compares evidence. Optional supplied URLs constrain or supplement research, not enable it.
3. Responses cite the sources actually retrieved, distinguish sourced facts from inference,
   and disclose failed searches or inaccessible content instead of inventing support.
4. Follow-up questions retain conversation context and can trigger further searches.
5. A configured AI model and working search backend power the normal path. If either is
   unavailable, report that plainly; a deterministic report or model's remembered knowledge
   must not masquerade as live web research.
6. Network consent, capability permissions, privacy controls, query/result/time/cost limits
   and protections for untrusted page content remain in force. Do not promise exhaustive
   coverage of literally every website: "whole internet" means general web-wide discovery,
   rather than only user-supplied URLs or a fixed local corpus.
7. Verification must include question-only search, source opening/citation provenance,
   conversational follow-up and clear backend failures. Stubbed tests do not by themselves
   prove a functioning live internet integration.

This turn records the corrected acceptance requirement and inventory. It does **not** add
web search, claim that Research is fixed, or claim new runtime verification. The previous
2,616-test result remains evidence for the preceding worker-policy code, not this feature.


## Chat usability correction (31 October 2026)

The user's screenshots exposed defects that historical test totals did not catch. The
chat correction implements six bounded repairs: one conversation sidebar, conventional
message alignment/composer, actual model selection, provider-returned thinking with saved
history, collapsed routine diagnostics, and usable phone navigation. This is **6/6 (100%)
of that explicit chat-repair checklist**, not a whole-product completion percentage.

The old adapter discarded separate reasoning fields. The HTTP path now preserves them;
legacy leading think blocks are separated too. No thinking is invented for a model that
returns only an answer. Failure visibility, security checks and no automatic POST replay
remain in place. Original Research web-chat requirements and the other ten partial areas
are not closed by this UI change. The other workspaces retain their existing narrower
flows and require further usability work, not simply successful route smoke checks.
