# Model Training — docs

This folder belongs to the **Model Training** app (`apps/training/`). It is
reserved and intentionally almost empty: the app's code and documentation are
being written by the person who owns it, not by the Launcher.

## What exists today

- `../app.toml` — the manifest the Launcher reads. It is the only contract
  between this app and the rest of the Lab:

  ```toml
  id = "training"
  name = "Model Training"
  category = "BUILD MODELS"
  summary = "…"
  status = "building"     # live | preview | building | planned
  art = "workbench"       # agent | workbench
  modes = ["DESIGN", "TRAIN", "EVALUATE", "SHIP"]
  ```

  `status = "building"` keeps the tile on Discover but not openable. Changing it
  to `live` is what makes the Launcher's "open" path available; no launcher code
  has to change.

## Where to put things

| Kind of document | Path |
| --- | --- |
| Architecture and module map | `docs/Architecture.md` |
| Design decisions and rejected options | `docs/Decisions.md` |
| Progress and validation evidence | `docs/Test_Results/Unreleased/` |
| Per-area text scale, storage, wiping | follows the Archx Agent's `Storage & display` design — see `../../archx-agent/docs/Thinking.md` |

## Rules that apply to every app in the Lab

1. **Never edit the launcher** to add an app. Add a folder with `app.toml`; the
   Launcher discovers it (`shared/src/apps.rs`).
2. **Never fork the launcher.** The Lab is one application with several
   workspaces.
3. **Shared code comes from `archx-shared`** (`shared/src/`): storage locations,
   the OS vault, transports, diagnostics, the debug journal and the design
   tokens. Do not copy those files into an app.
4. **Wiping is per area and always explicit.** An app may wipe only its own
   areas, and must say what it left alone (vault keys are never deleted by a
   wipe).
5. **Evidence, not claims.** Build and test results are recorded under
   `docs/Test_Results/Unreleased/` by CI, not asserted by hand.

## Docs index for the whole Lab

- `../../archx-agent/docs/README.md` — the Agent's documentation index.
- `../../archx-agent/docs/Plan/Architecture.md` — the workspace crate layout.
- `../../../README.md` — repository orientation.
