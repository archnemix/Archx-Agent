<!-- Purpose: Tracks the new user-supplied 1.9.0 app reference and native migration gaps; previous screenshot reference was removed on request. -->
# Current Agent UI comparison target

The previous screenshot set and its comparison were superseded and removed on request. The binding reference is now the user-supplied MIT-licensed **Archx Agent 1.9.0** archive and extracted source in `internels/reference/web/` (hash and file list in `archive-inventory.txt`). The web reference can run locally on port 4173 with an isolated temporary data area; it is not the native application. Native UI remains Rust/Iced by explicit user instruction.

| Feature in tar | Native implementation / current gap |
| --- | --- |
| Launcher separate from Agent app | Launcher navigation is being separated from the Agent's own Chat/Settings sidebar; Agent Back to launcher returns to the shelf. |
| Model-import dialog with filter, select matching/all, optional testing, manual ID, explicit add | Native dialog is being introduced, with imported IDs excluded from available results, selection and import no longer capped at 10/32, and 60 rendered rows/page for responsiveness. It does **not** yet match the web reference's concurrency, automatic test-on-only-working, retries, status detail or full modal styling. |
| Returned reasoning | Shown only if the provider returns it. Native streaming panel says Thinking and displays while streaming; completed panel is collapsed and can be reopened with a small disclosure. It does not reproduce CSS dashed borders or text shaping exactly. |
| Rich Markdown/code/table/chat tools | Native Iced renderer remains less capable than the bundled markdown-it/highlight.js UI (syntax colour, CSV exports, edit/regenerate, debug, persisted chats, profiles, etc.). These are remaining work, not implicitly imported by storing the tar. |

A **new same-size screenshot comparison against the running 1.9.0 app is still needed** after the native build succeeds; old screenshots cannot establish pixel parity. The tar is a reference only. Do not use its web server/key derivation to handle native credentials without separate review. CI capture fixtures are offline/synthetic, not live vendor-model validation.
