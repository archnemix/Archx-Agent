# Review of the user's reference interface

## What was actually retrieved and checked

The supplied Google Drive file is a **289,724-byte gzip tar archive** containing
**Archx Agent 1.9.0**, a Node.js application with a browser UI and a Tauri wrapper.
SHA-256: `9a263ec54307cfa555b38625a8d8bb35c2dadeb5d1e35afc69b559753b09a68e`.
There are 74 archive entries, including directories. Retrieval succeeded through
GitHub Actions runs 41201959447 and 41202010796. The first inspection detected gzip
rather than ZIP; the second supported tar and returned the source and small original.

The reference was retained outside the Python application's source tree, under
`/home/user/reference-ui/archx-agent`. Its original archive is at
`/home/user/professional-ui-reference.tar.gz`. The runner temporarily committed bounded
transport files on the session branch because direct Drive and artifact-host access
are restricted; those transport files have been removed from the current tree and
ignored. They remain in Git history. Main was not changed. Publishing the current
saved source was necessary to install the retrieval workflow on the session branch.
An unrelated model-matrix run triggered by that checkpoint was cancelled.

After source inspection, dependencies were installed with lifecycle scripts disabled.
The reference was opened in Chromium using an isolated memory-only server, a scrubbed
environment, no API keys and separate configuration paths. External provider-model
fetches and tool calls were blocked/stubbed for the browser review. Observed screens:
Chat/no-provider onboarding, Settings/General, model picker and Memory. There were no
browser page errors in that review. This does **not** independently certify all provider,
media, web-search, storage migration or desktop-wrapper operations.

## The difference is product design, not decoration

The reference organizes the interface around a user's next action. The Python version
largely exposed internal subsystems as twenty equal destinations. Collapsing seventeen
items into a menu improves clutter but does not fix that underlying product model.
A feature catalogue and many passing route tests are not a coherent user experience.

| Area | Reference implementation | Gap in the Python implementation |
|---|---|---|
| Main navigation | Chat, Studio, Memory, Debug, Settings; history belongs to Chat | Too many subsystem-oriented workspaces; no coherent Settings surface |
| First run | Explicit no-provider state with Add a provider/Open settings | Generic welcome and a Models page still biased toward Gemini/SDK registration |
| Provider setup | Browser-based provider presets, endpoint/key configuration, test connection | Local Ollama registration still requires CLI setup |
| Model selection | Provider → curated model picker, filter, explicit refresh | Flat catalogue selector added only in the previous correction |
| Generation controls | Stop/abort and per-chat stream controllers | One globally guarded turn; no Stop control |
| Thinking | Integrated, stable disclosure surface; automatically follows during generation unless reader intervenes | Recently added returned-thinking panel, but not the complete reading/streaming interaction |
| Streaming code/tables | Incremental block painting keeps scroll surfaces alive | Answer content still cleared/rebuilt on each chunk and final paint |
| Reading long answers | Pin/unpin scrolling and Jump to latest | Near-bottom heuristic only; no explicit return-to-latest control |
| Editing a conversation | Edit/resend, regenerate, archived continuations and branch switch | No equivalent browser conversation editing/branch flow |
| Diagnostics | Per-chat debug on demand; request/tool separation | Workspace/task implementation details still leak into the main experience |
| Prompts/settings | Dedicated system prompt management and effective prompt preview | No comparable coherent browser settings workflow |
| Web assistance | Composer Web toggle, search-engine chain, source/tool cards, supplied-page reads | Research remains a supplied-source report workflow, not conversational discovery |
| Visual system | Written spacing/typography/component/behaviour rules in UI-RULES.md | CSS changes without a sufficiently explicit product-level interaction contract |

The reference paths above are relative to its extracted root, not this repository:
`public/index.html`, `public/js/chat.js`, `public/js/blocks.js`, `public/js/render.js`,
`public/js/ui.js`, `public/css/base.css`, `lib/server.js` and `lib/websearch.js`.

## Behaviour verified beyond screenshots

A Chromium check invoked the reference's actual `paintBlocks` implementation using
explicit test text, then extended a pending code block and its reasoning. Both the
existing `<pre>` and thinking `<details>` retained DOM identity. This is a concrete
behavioural advantage: the user can read/scroll generated material without the scroll
surface disappearing on every token. The Python chat painter still reconstructs its
answer contents. No real model was involved in this check.

The source confirms per-chat AbortController ownership, Stop, regeneration/branch
handling, cached/in-flight-deduplicated model lists and live tool cards. These were
code-inspected, not all exercised end-to-end against live providers in this review.
The reference's own UI-RULES.md has some historical statements (three pages/single engine)
that newer code supersedes (five main destinations/per-chat concurrent streams).
The implemented code, not an older comment, is the comparison baseline.

## Web-search distinction

The reference already searches from the user's question without requiring a URL:
when Web is enabled, the server uses the last user message (up to 300 characters),
tries the configured search-engine chain, inserts source snippets and emits tool/source
cards. It separately reads up to two URLs supplied in that message. This is materially
closer to the requested conversational research experience than the Python report form.
It is not evidence of iterative model-planned query expansion, autonomous reading of all
search results or full research verification. External search was not live-tested here.

## What should change next

1. Use the reference's information architecture and interaction contracts as the baseline,
   rather than inventing another cosmetic arrangement of the existing twenty workspaces.
2. Complete the primary journey: first run → connect local/provider endpoint → select
   model → send/stop → read thinking/code → reopen/edit/regenerate a conversation.
3. Keep advanced engines accessible through purposeful grouped screens, not a raw module list.
4. Preserve stable stream surfaces, reader-controlled scrolling and chat-owned generation.
5. Define completion through those user journeys, including failures and reloads. Do not
   substitute milestone counts, cleanup percentages or route smoke for feature acceptance.

This review does not port the reference into the Python product, delete the current
backend or claim a new redesign is complete. The user's request here was retrieval and
analysis; the next implementation should follow this concrete baseline.
