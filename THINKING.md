# Design decisions

## 1.0.0: replace the implementation, not just its appearance

The user explicitly chose the supplied Node-based Archx Agent 1.9.0 as the new
foundation. The Python implementation, its twenty-mode UI, its tests and its
milestone documentation have been removed from the active tree. They remain in
Git history at f5e013a. This is not a second frontend over the old backend.

The imported source archive has SHA-256
`9a263ec54307cfa555b38625a8d8bb35c2dadeb5d1e35afc69b559753b09a68e`.
Its MIT licence is retained. Product/package/desktop versions restart at 1.0.0;
this does not downgrade its existing database schema or erase reference features.

Preserve the reference's five-page navigation, provider setup, model curation,
reasoning, stable streaming blocks, Stop, branches and web tools. Add requirements
through complete user journeys, not a menu of internal modules. Do not silently
claim that the old Python features remain implemented.

## First adaptation: chat-owned concurrent work

Inspection found single-target browser save/paint timers despite per-chat streams.
The first changes give each chat a place in the save queue, keep paints per element,
keep tool/debug/meta updates with their originating conversation, and retain partial
answers on stream failure. An interrupted stream must not silently count as complete
or trigger automatic resubmission. These changes preserve the reference layout.

Provider/search tests use explicit local fixtures. They are not real-inference or
live-internet certification. Desktop packaging remains inherited and unverified.

## Verified corrections and remaining boundary

The first SQLite round-trip test failed because the inherited branch writer omitted
an existing column. Correct the writer, not the test. Keep tool/failure fields in
namespaced metadata rather than resetting the database or overwriting answer text.
All 28 Node tests now pass. A real Chromium run using a local provider fixture also
passed setup, concurrent streams, reasoning/code, interrupted answer, Stop, reload
and mobile width with zero page errors. This validates plumbing, not live inference.

Historical documentation is explicitly marked as inherited; Windows compatibility
claims cannot be transferred to the removed Python database. The five-item reset
scope is complete; autonomous research and original product goals are not.
