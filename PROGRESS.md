# Progress and verification

## 1.0.0 foundation reset — 31 October 2026

**5/5 bounded reset deliverables complete (100% of this reset only):**

1. Replace the rejected active implementation with the supplied Node reference.
2. Reset npm, lockfile, Cargo and Tauri product versions to 1.0.0.
3. Start adapting it: concurrent chat saving/rendering and stream-failure handling.
4. Replace obsolete instructions; provide separate everyday and technical guides.
5. Verify the replacement with executable Node and browser checks.

This is not a whole-product percentage. The previous Python source remains in Git
history at f5e013a, not as another active codebase. No npm/desktop release is published.

## Actual results

- `npm ci --ignore-scripts`: 84 dependencies installed.
- `npm test`: **28 passed, 0 failed**. Tests cover byte/chunk SSE parsing,
  incomplete/error streams, independent chat saves, stopped/partial output,
  local HTTP provider integration, memory-only state, SQLite reasoning/branch/
  tool-card/failure-text round trips and version consistency.
- Real Chromium check: provider draft connection → save → model import/selection →
  two concurrent conversations → reasoning/code → truncated reply retaining its
  answer and displaying a separate error → Stop → saved reload. Mobile 390px
  viewport has no horizontal overflow. **0 browser page errors.**
- `npm pack --dry-run` and executable version output checked; all application/test JavaScript syntax and `git diff --check` passed.
- Preview uses a separate, key-free data area; no old Python database is opened.

Browser/provider responses were deliberately local fixtures. These results do not
certify real model quality, internet research, Windows or a Tauri installer.

## Implemented corrections

Chat saves are keyed by conversation, painting by content element, and debug/tool/
model metadata stay with their originating request. Partial text and thinking are
not overwritten on failure. Browser SSE and the OpenAI-compatible upstream adapter
reject unconfirmed EOF without automatically resending the question.

Testing exposed an inherited branch-loss defect: reads included `branches_json`,
but writes omitted it. Writes now preserve it. Tool cards and separate error text
also survive SQLite reload through the existing metadata column. No schema reset.

## Requested journeys still needing completion

- Actual Ollama/cloud inference, edits/regeneration/branch-switching browser flows.
- Iterative autonomous question-driven research: discovering and reading sources,
  safe fetching, grounded citations and contextual follow-up searches. The inherited
  one-shot search/snippets and supplied-link reading are not the finished journey.
- Complete learning, coding, agent/tool and Blender workflows. Blender has **not**
  been run; there is no validated Blender integration in this Node foundation.
- Desktop/Windows packaging and remote-exposure security review.
- Python-to-Node data migration, if required; none exists today.

Inherited Studio/Memory/search features remain visible, not newly certified. Failed
chat saves are reported but not automatically retried. Native adapters other than
OpenAI-compatible need their own truncated-stream audit. Large reference modules
still require incremental responsibility-based extraction, not another UI rewrite.
