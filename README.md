<!-- Purpose: Introduces the repository layout, the app model and where each record lives. -->
# Archx AI Lab

Archx AI Lab is a native Rust/Iced desktop launcher with one or more app
workspaces inside it. Today it hosts **Archx Agent** — chat with a provider of
your choice, vault-held keys with rotation, paged model management, a request
Debug page, and persisting transcripts. **Model Training** is a separate app
folder whose code and docs are being written by its owner.

The Windows GUI executable is unsigned and has no publisher verification; it does
not open a console. **Live provider calls and interactive OS-vault journeys are
not validated by CI.** [Download the unsigned Windows build](deliverables/Unreleased/windows/archx-ai-lab.exe),
or read the [three-OS validation record](apps/archx-agent/docs/Test_Results/Unreleased/Gui_Validation.md).

## Repository layout

```
Cargo.toml              workspace: launcher binary + two library crates
src/                    launcher: Discover, rail, transition, launcher settings
shared/                 archx-shared: vault, transports, diagnostics, storage, tokens
shared/assets/          brand, fonts, icons, model metadata (embedded by both crates)
apps/archx-agent/       Archx Agent: app.toml, src/, assets/, docs/, tests
apps/training/          Model Training: app.toml + docs/ (code comes later)
internels/              internal helper material and the web reference
```

## How an app joins the Lab

An app is a folder with an `app.toml`. The launcher scans `apps/*/app.toml` at
start-up (`shared/src/apps.rs`), renders one Discover tile per manifest, and opens
only those whose `status = "live"`. No launcher code names an app, so adding a
folder is the whole integration. The contract and the settings split are written
down in [Plan/Architecture.md](apps/archx-agent/docs/Plan/Architecture.md).

## Where things are documented

- [apps/archx-agent/docs/](apps/archx-agent/docs/README.md) — the Agent's records:
  rules, design system, decisions ([Thinking](apps/archx-agent/docs/Thinking.md)),
  technical map, and CI evidence under `Test_Results/Unreleased/`.
- [apps/training/docs/](apps/training/docs/README.md) — the second app's reserved
  space, including the rules every app in the Lab follows.
- [internels/](internels/README.md) — internal helper material, including the
  read-only web reference in `internels/reference/web/archx-agent/`.

## Building

There is no local toolchain requirement for review: CI builds and tests on Linux,
Windows and macOS. Locally, `cargo run --release` starts the launcher once the
system has the Iced prerequisites (on Linux: `libxkbcommon-dev libwayland-dev`).
