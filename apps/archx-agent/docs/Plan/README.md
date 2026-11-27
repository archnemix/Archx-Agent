<!-- Purpose: Index of the launcher-owner's docs, and the boundary between them and an app author's docs. -->
# Plan

These are the **launcher owner's** documents. They describe the platform every
app builds on, and they are the contract a second AI is pointed at.

| File | What it is |
| --- | --- |
| [Adding_An_App.md](Adding_An_App.md) | The contract: manifest fields, crate layout, the host hooks the launcher calls (§7b), release vs hold (§8), and how a branch is imported (§7). |
| [handoff-to-other-ai.md](handoff-to-other-ai.md) | The paste-ready message for a second AI, with blanks for one app's id, name and description. |
| [Architecture.md](Architecture.md) | Product scope and architectural decisions behind the platform. |

## Where an app author's docs live

Each app owns its own documentation folder, declared in its manifest
(`docs = "docs"`). For this app that is `apps/archx-agent/docs/`; a second app
writes to `apps/<id>/docs/` and nothing else. That rule is why this folder holds
every document a new app author needs: they can read it on their own branch
without editing it, and their own notes never collide with ours.

The only other shared file is the root `Cargo.toml` members list (add one line,
never reorder). Everything else in the repository belongs to whoever owns it.
