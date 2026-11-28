<!-- Purpose: Index for the Model Training (`apps/training/`) documentation, architecture, decisions, and CI evidence. -->
# Model Training — Documentation

`apps/training/` (`crate = "archx-training"`) is the native-Rust model-creation workspace inside **Archx AI Lab**. It focuses exclusively on **creating and training brand-new models from scratch** inside the desktop application with zero external Python or C++ installation required, while sibling workspace `Model Surgery` handles modifying, merging, adapting, and quantizing existing pretrained checkpoints.

## Documents in This Folder

| Document | Purpose |
| --- | --- |
| [Architecture.md](Architecture.md) | Composable 4-axis model taxonomy, module map, UI surfaces, optimizations, and Slice 1 (Text Autoregressive Transformer) specification |
| [Decisions.md](Decisions.md) | Engineering decisions, verified Rust ML crate choices, deterministic seeding, and zero-overhead telemetry |
| [Roadmap.md](Roadmap.md) | Ordered vertical-slice implementation plan starting with Text Generation · Autoregressive Transformer |
| [Research.json](Research.json) | Authoritative crate and API research records |
| [Test_Results/Unreleased/](Test_Results/Unreleased/README.md) | Automated GitHub Actions `App harness` build and test logs |

## Lab-Wide Contract Followed Here

1. **Zero launcher edits:** All code and docs live under `apps/training/` (plus the single `"apps/training"` workspace member entry in root `Cargo.toml`).
2. **Shared infrastructure from `archx-shared`:** Uses `archx_shared::style` tokens, `archx_shared::credentials::Vault` for optional dataset tokens, `archx_shared::persist::TextScale`, and app-scoped persistence via `archx_shared::storage::{save_app, load_app_body, wipe_app}("training", ...)`.
3. **Host lifecycle (§7b):** Exports `home::view` and implements `App::{new, update, enter_surface, leave_app, prepare_snapshot}` plus `left_for_launcher`.
