<!-- Purpose: Maps implemented user actions to their component and function call flows for debugging. -->
# Program logic and call flows

Only the launcher shell exists. Add further flows **when they are implemented**, not as speculative call graphs. Keep file paths and function names current when code changes.

For each implemented flow, document:

1. Trigger and user-visible result.
2. Ordered calls: `file::function` → `file::function`, with significant inputs and outputs.
3. Persistent state read/written, permission checks, and failure/recovery paths.
4. Related integration test and where its result is recorded.

Product-level behaviors under discussion (not implemented flows): chat and mode transitions; context compaction; archive and selective memory retrieval; tool execution; and optional backup. Their interfaces and functions are not yet defined.

## Home shell flows (runner-validated; Windows user review pending)

- Launch: `src/main.rs::main` → `src/app.rs::App::new` (reads optional `ARCHX_SNAPSHOT`) → `src/app.rs::App::view` → `src/home.rs::view` → sidebar + home or about widgets; `src/main.rs::brand_icon` decodes the bundled brand PNG into the native window icon during app startup (a corrupt image prevents startup); `build.rs` embeds the Windows executable icon and descriptive version fields during Windows build. `src/app_tile.rs::view` builds the inert three-app shelf from a temporary Agent cover and two clipped typography panels; `src/style.rs::nav` supplies the gradient/shadow selected state and other styles. Output: native window. Failure: Iced startup returns an error.
- Available navigation: Home/About click → `src/app.rs::Message::Navigate` → `App::update` stores `Page` → `App::view` redraws requested page. Future destinations do not emit messages. Test: `src/app.rs` focused navigation unit test; runner logs under `Docs/Test_Results/Unreleased/build/`.
- Opt-in visual review: `ARCHX_SNAPSHOT=<path>` (optionally `ARCHX_SNAPSHOT_PAGE=about`, or `ARCHX_SNAPSHOT_HOVER=training|tuning` and `ARCHX_SNAPSHOT_PHASE=0|1|2` to freeze a text-card state) → `App::subscription` waits five seconds → `Message::SnapshotTick` → `window::latest` → `window::screenshot` → `App::update(Message::SnapshotReady)` writes a PNG using `image::save_buffer` → closes window. Failure: screenshot directory/PNG write error stops the process; CI treats a missing PNG as failure.
- Text-card hover (model workspaces only): pointer enters `src/app_tile.rs::view` mouse area → `Message::TileHover(Art, true)` → `src/app.rs::App::update` stores hovered tile and resets phase → `App::subscription` batches a hover-only 700ms timer → `Message::Animate` advances phase 0→1→2→0 → `App::view`/`src/home.rs::home` passes the selected phase to the hovered card; only its stage text emphasis changes. Pointer exits → `TileHover(Art, false)` clears hover and phase; navigation to About also clears it. Agent has no hover event yet. No persistence, network input, model work or click action is involved. Focused transition tests are in `src/app.rs`; frozen phase screenshots in GUI CI show distinct render states but do not simulate pointer movement.
