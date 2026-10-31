# Current feature status

## Position against the requirements

The active product is the supplied Node reference, version 1.0.0. The rejected
Python implementation is absent from the active tree; its historical claims do
not count as product progress. Old milestone/reset percentages are retired.

**Accepted full features: 0/17 (0% accepted, not percentage of code written).**
The complete list and acceptance boundaries are in
[Complete features and acceptance requirements](docs/FEATURE_REQUIREMENTS.md).

## Current feature: Simple Mode — awaiting full verification and user acceptance

Present: provider/key setup, connection/model controls, chat, provider-returned
thinking, streaming, Stop, conversations, edit/regenerate/branches and SQLite storage.
Presence is not acceptance. Previous local checks exercised selected fixture-backed
provider/chat paths, concurrent conversations, failure handling, Stop and reload.
They did not certify real inference or every chat control. Full edit/regeneration/
branch behaviour, real provider use and the user's usability test remain open.

Agent Mode is not implemented. Research is only inherited one-shot search/snippets,
not the required autonomous question-driven research. Other areas are listed plainly
in the feature requirements; database tables and visible pages are not full features.

## Available for personal testing

Port 4173 serves the real reference-based app with its own separate data area and no
seeded provider credentials. The user can enter a key in Settings → Providers, test,
save, select a model and chat. The app sends requests through its backend. Never
paste keys into conversation or point this app at the old Python database.

## Verification policy

Keep meaningful existing checks; add only missing distinct behaviour/risk checks.
Do not use test totals or structural cleanup as feature completion. No new tests or
new product modes were added for this planning reset. User acceptance is the gate.

After this documentation/UI wording cleanup, the existing regression suite and
browser journey were rerun successfully, with no additional tests added. External
provider access can be blocked by this sandbox's outbound network restrictions;
entering a key is supported, but successful real inference is not promised here.
