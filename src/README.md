<!-- Purpose: Explains the launcher's source directory and what belongs in it. -->
# Launcher source

Three files. Nothing about any individual app belongs here.

| File | Contents |
| --- | --- |
| `main.rs` | Window, fonts, brand icon, and the iced application wiring |
| `app.rs` | Launcher state: page, apps from manifests, transition, per-area text scale, memory scope, wiping, snapshot support |
| `navigation.rs` | Rail, Discover tiles, About, and the launcher's own `Lab settings` page |
| `transition.rs` | Time-based launcher↔app transition (220 ms, ease-out cubic) |

## Rules

- **Never name an app in this folder.** Apps arrive through
  `archx_shared::apps::discover()`; a tile, its category, status and modes all come
  from `apps/<id>/app.toml`. Adding an app is adding a folder.
- **Never reach into an app's state.** The launcher talks to the Agent through
  `archx_agent::app::Message` and a surface id (`"agent"`, `"settings"`, `"debug"`),
  and reads back only `left_for_launcher`.
- **Launcher settings stay here.** Per-area text scale, the memory scope handed to
  the Agent, the apps folder and wiping are launcher concerns; everything else
  belongs to the app that owns it.
- Shared code (vault, transports, storage, tokens) lives in `shared/`; do not copy
  it into `src/`.
