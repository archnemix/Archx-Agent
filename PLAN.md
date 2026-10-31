# Implementation plan

## Completed foundation (5/5 reset deliverables)

- Replace active Python source with the user-selected reference.
- Set npm, lockfile, Cargo and Tauri product versions to 1.0.0.
- Keep the reference UI and working chat/provider/settings flows.
- Replace obsolete documentation and add executable baseline checks.
- First adaptation: correct concurrent chat saving/painting and interrupted replies.

## Next user journeys — not yet complete

1. Complete and validate local Ollama/provider setup, model selection, thinking,
   Stop, persisted conversations, edits/regeneration and branches.
2. Extend conversational web research: contextual queries, automatic reading of
   discovered sources, comparisons, citations and follow-up searches. Existing
   Web search/snippet cards are a starting point, not complete autonomous research.
3. Add the required learning, coding, agent/tool and other capabilities in coherent
   grouped screens only after their end-to-end flows work. The deleted Python
   feature list is a requirements source, not current implementation evidence.
4. Validate Windows installation and the desktop shell before claiming support
   has been freshly certified. Keep existing data areas separate during testing.

No whole-product completion percentage is assigned without a new accepted feature
baseline. Replacement and version reset are bounded operations, not product completion.

## Verification gates

Keep all 28 Node regressions green and rerun `npm run test:browser` for chat changes.
Expand checks for edits, regeneration and branch switching before claiming those
flows newly certified. Add safe-page-fetching tests before autonomous discovered-
URL reading. Never treat inherited memory tables as a completed learning journey.
