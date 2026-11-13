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

- Launch: `src/main.rs::main` → `src/app.rs::App::new` (reads optional `ARCHX_SNAPSHOT`) → `src/app.rs::App::view` → `src/home.rs::view` → sidebar + home or about widgets; `src/main.rs::brand_icon` decodes the bundled brand PNG into the native window icon during app startup (a corrupt image prevents startup); `build.rs` embeds the Windows executable icon and descriptive version fields during Windows build. `src/agent_visual.rs::{hero,tile}` renders the six-mode kinetic Agent typography in both placements; `src/app_tile.rs::view` builds the inert three-app shelf from the Agent text panel and two clipped model-workspace typography panels; `src/style.rs::nav` supplies the gradient/shadow selected state and other styles. Output: native window. Failure: Iced startup returns an error.
- Available navigation: Home/About click → `src/app.rs::Message::Navigate` → `App::update` stores `Page` → `App::view` redraws requested page. Future destinations do not emit messages. Test: `src/app.rs` focused navigation unit test; runner logs under `Docs/Test_Results/Unreleased/non_visual/`.
- Opt-in visual review: `ARCHX_SNAPSHOT=<path>` (optionally `ARCHX_SNAPSHOT_PAGE=about`, or `ARCHX_SNAPSHOT_HOVER=training|tuning` and `ARCHX_SNAPSHOT_PHASE=0|1|2` to freeze a text-card state) → `App::subscription` waits five seconds → `Message::SnapshotTick` → `window::latest` → `window::screenshot` → `App::update(Message::SnapshotReady)` writes a PNG using `image::save_buffer` → closes window. Failure: screenshot directory/PNG write error stops the process; CI treats a missing PNG as failure.
- Text-card hover (model workspaces only): pointer enters `src/app_tile.rs::view` mouse area → `Message::TileHover(Art, true)` → `src/app.rs::App::update` stores hovered tile and resets phase → `App::subscription` batches a hover-only 700ms timer → `Message::Animate` advances phase 0→1→2→0 → `App::view`/`src/home.rs::home` passes the selected phase to the hovered card; its central display word and three-part marker change (Model Forge: DESIGN/TRAIN/EVALUATE; Refinement Studio: SELECT/ADAPT/VALIDATE). Pointer exits → `TileHover(Art, false)` clears hover and phase; navigation to About also clears it. Agent has no hover event yet. No persistence, network input, model work or click action is involved. Focused transition tests are in `src/app.rs`; frozen phase screenshots in GUI CI show distinct render states but do not simulate pointer movement.
- Agent typographic artwork: Home visible → `App::subscription` ticks every 1500ms → `Message::AgentPulse` → `App::update` advances `agent_phase` modulo six → `App::view` → `src/home.rs::home` and `src/agent_visual.rs::{hero,tile}` re-render a mode label and one of six progress-like **position markers**, not real mode execution. Timer stops on About; in screenshot mode Agent phase is frozen (optional `ARCHX_SNAPSHOT_AGENT_PHASE=0..5`), enabling consistent CI phase comparisons. No storage or backend execution.

## Agent/Settings UI navigation (Step 2 preview)

- Launcher rail **Archx Agent** or featured **Open Agent UI** → `Message::Navigate(Page::Agent)` → `App::update` switches page → `home::view` keeps Lab rail and mounts `agent::view` with the transient draft list. **New draft** appends a fresh, empty session-only `ChatDraft`, **Draft NN** selects an existing ID; bad IDs are ignored. Mode buttons set only the selected draft's preview mode (index `< MODE_COUNT`); no message/history conversion occurs. Text input emits `Message::EditDraft(id, String)` on typing, targeting only the selected draft ID; Clear empties only that draft. Enter has no submit binding and there is **no Send event**, so no message is transmitted or stored.
- Lab rail **Settings** → `Page::Settings` → `settings::view` renders shared Memory Light/Heavy/Custom preview. Selection updates only `App::memory_preview`; Custom's Agent toggle updates only `App::keep_agent_preview`. All values reset on process restart. No RAM management, persistence or OS startup integration is implemented. Returning Home does not mutate the approved Agent artwork.
- `ARCHX_SNAPSHOT_PAGE=agent|settings` with `ARCHX_SNAPSHOT=<path>` selects those pages for native screenshot capture; previously supported Home/About and frozen visual phases remain supported. A snapshot is evidence of a rendered page, not proof of interactive pointer/key behavior.

- Additional screenshot-only states: `ARCHX_SNAPSHOT_PAGE=agent ARCHX_SNAPSHOT_MODE=3` selects an empty Coding draft preview; `ARCHX_SNAPSHOT_PAGE=settings ARCHX_SNAPSHOT_MEMORY=custom` shows Agent's Custom memory preview. These environment variables are ignored unless a screenshot path is provided and the corresponding page is selected. `ARCHX_SNAPSHOT_DRAFT='Sketch a new idea for a project'` with an Agent snapshot shows a fixed nonpersonal unsent text state; normal startup remains empty. The composer is editable but Send remains unavailable.

## Shared Lab rail collapse (Step 2 follow-up)

- Expanded **Hide <** / compact **Open >** → `Message::ToggleSidebar` → `App.sidebar_expanded` flips, independently of `Page`; `home::view` renders either `sidebar` or `compact_sidebar`, then the same page content. Compact buttons still navigate to Home, Agent, About, Settings. Navigation does not reset rail state, drafts, or preview Settings. Screenshot-only `ARCHX_SNAPSHOT_SIDEBAR=collapsed` selects compact layout when `ARCHX_SNAPSHOT` is set; normal startup defaults expanded. No disk writes or model calls.

## Provider credential vault foundation (not yet user-facing)

- Future Settings Add Key → validate no whitespace/control chars → `credentials::Vault::add(provider, Zeroizing<String>)` writes the secret under a provider-specific OS credential account and then updates the protected index; failed index write triggers deletion rollback, with explicit partial-failure state if cleanup fails. `list(provider)` reads only IDs, validates version/sorted uniqueness and fails closed on corruption. `remove` deletes the OS credential then updates index, reporting partial removal if index update fails. `with_key(provider,id,callback)` reads one selected secret only for callback duration, then zeroizes its Rust allocation. The current App does **not** call any of these paths; live key entry/reveal/API requests are unimplemented. CI uses fake-store unit tests, never actual keys.

- Navigation rail: clicking `Collapse navigation` or `Expand ›` emits `Message::ToggleSidebar` to `App::update`, flips only the session-local `sidebar_expanded`, and re-renders `home::sidebar` with the same lower-edge toggle. The compact rail remains navigable. No persistent preference or network access.

## Session-only provider configuration and plain Chat experiment

- Settings → Connections → enter masked key → Save emits `Message::SaveKey`, takes and clears input, calls `Vault::add(provider, secret)` on a blocking worker and refreshes only numbered IDs; provider errors are static. Reveal retrieves the chosen ID on a worker; on return `Instant + 15s` is set and a 15s timer invalidates the UI state. Leaving Settings or changing tabs/provider clears it sooner. No screenshot-mode reveal. Key deletion is explicit and OS-backed.
- Settings → Models → type exact manual provider ID → Add selects it in a process-only list. Remove revokes that in-session selection. Catalog and usage checks are not built. Generation test sends only a fixed short synthetic prompt after an explicit click with a cost warning; the response is reported as success/failure but not persisted or displayed. At most 256 output tokens are requested; total tokens/cost are provider-dependent.
- Agent → Chat → Send emits `Message::SendChat` only for the Chat mode and nonempty text. The selected provider/model, recent session turns and one OS-stored key (rotated by per-provider cursor) are used for one fixed-origin TLS POST. The original draft is moved to in-process turns, then the plain reply or static sanitized error is shown; other modes cannot send. Closing the process discards chats/models. No tool access, DB or automatic chat egress.

- During a pending key add/remove, `SettingsState::key_busy` blocks another add/remove and provider switch within the window, then clears on the worker result. Click Hide on a revealed key → `Message::HideKey` → `SettingsState::clear_secret` immediately, cancelling the current reveal nonce. OS vault operations from separate running processes are not synchronized.

- Failed Chat request: `Message::ChatResult(id, Err)` marks the draft idle, pops its unsatisfied user turn and restores its text for a deliberate retry. The transport warning notes the provider may still have processed a timed-out request; no automatic retry or hidden context resend occurs. The composer shows the sanitized error even on the first turn.
