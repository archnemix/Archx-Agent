<!-- Purpose: Records concise work-round decisions, rationale, problems, and resolutions. -->
# Decision and work log

## Documentation setup (2026-11-09)

- The repository initially contained only a root README. Created the requested working-document structure without guessing the product or stack.
- Kept JSON valid by using a first `_description` field instead of a comment; JSON comments would break parsers.
- Reserved `internels/` for helper material. No skill, workflow, or release version is needed before there is a concrete use for one.
- Added a pre-release test-evidence directory to satisfy the requirement to record the documentation validation command, inputs, and output without inventing a release.
- Validated JSON, file-inventory coverage, Markdown purpose headers, folder READMEs, and whitespace locally. No application tests or runner results are claimed.
- Next: discuss the product with the user, record the agreed plan, then derive an ordered roadmap.

## Interface direction discussion (2026-11-09)

- The user described Archx Agent as an AI agent product aiming for strong usability, reliability, and security, and expressed a preference for an app rather than a website.
- Recommended a desktop-first interface conditionally on the need for local file and process access. Kept the agent core independent of the UI as a design direction, not a committed architecture.
- Deferred stack and roadmap choices until supported operating systems, local-versus-remote execution, and concrete capabilities are clarified.

## GUI framework selection (2026-11-09)

- The user selected Iced for the Rust desktop UI, preferring to avoid an OS-provided webview or a bundled browser; updated the plan and technical overview accordingly.
- Checked official sources: COSMIC's libcosmic is based on Iced and Tauri does use different platform webviews. Corrected one premise gently: egui's own README says idle egui does not repaint continuously. No performance or reliability benchmark has been run, and no GPUI feature claim was verified.
- No UI code or version pin is warranted before product behavior, deployment model, and target OS scope are decided.

## Cross-platform UI concern (2026-11-09)

- The user clarified that the objection to OS webviews is inconsistent rendering between engines, citing a launcher UI that looked different across operating systems.
- Recorded this as a design priority without attributing that launcher's implementation to Tauri. Iced avoids a system-webview dependency, but platform appearance and behavior still need explicit cross-OS checks.

## Superapp scope discussion (2026-11-09)

- Recorded Archx as short for Archnemix; accepted Windows, macOS, and Linux as first-class targets from the beginning and kept Iced as the chosen UI framework.
- Structured the user's proposed five interaction modes, transitions, selective memory types, context compaction, approval/provenance rule, optional backup ideas, and settings in the architecture plan. These are product directions, not implemented behavior.
- Added `Docs/Logic.md` for **actual** call flows once code exists, rather than inventing functions now. Added a provisional roadmap sequence, with the first vertical slice dependent on unresolved decisions.
- Flagged the arithmetic mismatch in the example context budget (1k + 5k + 3k exceeds 8k), and the need to clarify whether every AI-generated summary/persistent write requires interactive approval. Also flagged tool-result visibility, mode transitions, and memory privacy as design decisions; do not guess solutions.
- No code was written in this round. Next: resolve the highest-impact consent and execution-model questions before any implementation.

## Roadmap ordering and general agent (2026-11-09)

- The user explicitly requested a general task agent and the order home screen → chat UI/mode navigation → working modes one at a time. Updated the plan, change log, and roadmap without starting product code.
- Split interface milestones from functionality so a completed home screen or chat shell can be delivered and tested without implying unimplemented modes work. Proposed the general task agent after common permission/memory groundwork, then research, coding, learning, and play; mode order remains user-adjustable.
- Added an end-of-each-GUI-step Windows download gate and three-OS validation. Binary distribution must be agreed before the first GUI step: repeated large binaries in Git would degrade repository health, while build logs/results still need to be retained as required.
- The first implementable task is Step 0's focused decisions and acceptance criteria, followed by the home screen. Do not invent model/provider or consent policy merely to start the UI.

## Archx AI Lab home shell implementation attempt (2026-11-09)

- The user clarified that the launcher is **Archx AI Lab**, the AI/ML product entrance; **Archx Agent** is its chat area. Future training, fine-tuning, and model observation destinations are shown as unavailable until built.
- Recorded a restrained graphite visual system in `Docs/design.md` and bundled Manrope with its original license. Used native Iced widgets, no browser/blur/animation; the selected rail item uses an inexpensive gray solid surface rather than costly backdrop effects.
- Checked Iced 0.14 tagged examples, font source, screenshot API, and image 0.25 dependency before writing GUI code. Split the initial app into entry, navigation/snapshot state, home rendering, and visual style.
- The sandbox lacks `rustc` and `cargo`; a source-triggered GitHub workflow is set up to compile/test and take running-app screenshots sequentially on Linux, Windows, and macOS, saving logs/screenshots and a repository-hosted Windows executable. Until runner results are inspected and issues fixed, Step 1 is **not complete** and no cross-OS pixel match is claimed.

## First Linux runner feedback (2026-11-09)

- CI installed the toolchain and produced a lockfile, then failed at compilation: Iced button messages require `Clone`; the theme callback needed an explicit `&App` argument type. Fixed those two source issues before re-running. Windows/macOS were skipped by the workflow because Linux did not pass; no build is yet downloadable.

## Linux runtime dependency discovered (2026-11-09)

- The corrected Iced shell compiled and its focused unit test passed on Linux. Snapshot launch under Xvfb failed because the runner lacked `libxkbcommon-x11.so`, not because of Rust compilation. Added `libxkbcommon-x11-0` to the Linux workflow setup; must rerun to prove the app launches and captures a screenshot before Windows/macOS jobs can proceed.

## Home shell cross-platform review (2026-11-09)

- The third workflow attempt succeeded: one focused navigation test passed on each of Linux, Windows, and macOS, each release build completed, running-app screenshots were saved, and an 11.5 MB portable Windows executable was committed to the requested repository path.
- Inspected all three screenshots. Windows/Linux captured 1280 × 800; the macOS runner restricted its display and captured 1024 × 642, with lower content reachable by scrolling rather than visible in that frame. The shared graphite layout, selected gray rail item, and Manrope typography look consistent in the visible area; exact pixel identity is neither expected nor claimed.
- Recorded exact commands, log paths, screenshot dimensions/checksums, binary checksum, and prior failed-run Git revisions in `Docs/Test_Results/Unreleased/Gui_Validation.md`. Next: user tests the Windows executable and gives UI feedback before starting the chat interface.

## Windows console and launcher redesign (2026-11-09)

- The user tested the Windows build: a Command Prompt remained open and the home looked too much like a generic dashboard. The executable used Rust's default console subsystem. Set the Windows release binary to the GUI subsystem; the workflow now checks the PE subsystem is 2 in addition to running the app.
- Reworked the direction toward an AI app launcher with a black main canvas, restrained grey/white surfaces, selected gray-glass-like rail item, featured Agent art, and a shelf of app destinations. Kept unavailable apps inert and labeled. Created original monochrome Agent artwork as a bundled resource.
- The repository checkout arrived at the original base commit with last turn's files as untracked snapshot contents; fetched and reset the **current branch only** to its existing remote tip, preserving those files, and restored the CI logs omitted from workspace snapshots because their directory is named `build`. No branch was switched.
- The first build's success does not cover this revision. Re-run all three OS builds, unit/integration checks, screenshots, and Windows subsystem verification before claiming the fix is complete.

## Launcher screenshot refinement (2026-11-09)

- First redesigned CI run passed both focused tests and release/snapshot checks on all three OSes; the Windows PE subsystem is 2 (GUI, no console), but screenshots revealed two layout problems before handoff: app names were below the initial Windows/Linux viewport, and the Agent artwork was cropped on the smaller macOS runner display. Linux also wrapped the inert Library label awkwardly.
- Reduced unused vertical space and app-cover height so names can appear above the fold at 1280 × 800, changed the Agent artwork to `Contain` to preserve its silhouette, and simplified sidebar labels without OS-dependent glyphs. A new three-OS build/screenshot review is required before claiming the layout fixes.

## Launcher correction ready for user review (2026-11-09)

- After the screenshot refinement, CI run `42992545976` passed two focused tests and the release/snapshot gates on all three OSes. Windows CI inspected the actual executable and confirmed PE subsystem 2, correcting the prior console-subsystem defect.
- Reviewed all three images: Windows/Linux at 1280 × 800 now show Agent artwork plus all four app names/statuses without scrolling; macOS at its runner-limited 1024 × 642 shows uncropped Agent artwork and the shelf beginning below it. The GUI is intentionally black/grey/white with an app-launcher composition, not the earlier dashboard.
- Updated the current GUI evidence record and retained prior outputs in Git history. Step 1 remains pending the user's actual Windows hands-on review; do not start chat UI until accepted or remaining issues are fixed.

## Reference-led launcher refinement (2026-11-09)

- The user provided a screenshot of the flat selected About state and a reference with dark glass pills lit subtly along the lower edge, and said the launcher still looked generic. Treated the references as visual direction, not assets to paste into the app.
- Chose Iced's existing native gradient and shadow styles for a scalable selected-menu pill; generated three small monochrome cover assets to give training, fine-tuning and monitoring distinct app identities instead of repeating letter tiles. Added an About-page CI capture so the requested selected state is inspected on Windows, Linux and macOS, not only the Home state.
- The session checkout again started at the base commit with snapshot files; restored the current branch to its existing remote tip and restored CI logs omitted from snapshots because their folder is named `build`. No new branch or product area was started.
- Code and docs are pending runner validation. Do not claim final visual quality or a working Windows build until CI and screenshot review complete.

## Cross-OS app-cover rendering defect (2026-11-09)

- CI run `43016569988` built the app, passed three focused tests per OS, verified the Windows GUI subsystem and captured Home/About on each OS. Visual inspection caught a real integration defect that the tests did not: the four tile images were invisible on Windows/macOS, while Linux rendered them outside their intended height, overlapping labels. The selected glass pill itself looked consistent.
- Kept Step 1 open. Normalized the art to 800 × 480, added a separate cropped Agent tile, bounded tile imagery in a fixed-height clipping container, and extended the snapshot delay to allow image loading. Added one focused test that decodes each cover. These are hypotheses for the rendering fix, not a claimed solution until the next three-OS screenshots are inspected.

## Branding and 3D review scope (2026-11-09)

- The user chose actual 3D rotation, not a flat picture spinning on hover. A preexisting JPEG cannot reveal unseen surfaces; keep the existing shelf inert rather than claim that a fake 3D animation satisfies the request. A genuine model/renderer and an animation-driven cross-platform test need their own implementation and evidence.
- Applied the provided transparent Archnemix art as a black-backed sidebar mark and derived native/PE icons. Set truthful company metadata only. Windows Authenticode verification requires a suitable signing identity, which the user is not sure they have; never substitute metadata for signing or label an unsigned binary verified.

- The first attempt at a Blender-based real-3D asset workflow in this restricted sandbox could not start: `bpy` 4.5.16 requires `libXrender.so.1`, which is not installed, and `apt-get` cannot reach Debian mirrors here. This is not a UI compile failure. Use an available validated renderer/CI or user-supplied model files for the actual 3D request; do not replace it with a flat 2D spin and mark it finished.
- Run `43031034141` passed Linux/Windows/macOS and Windows product metadata check. Its client-area screenshots show the supplied logo and removed preview copy, but cannot show the titlebar/taskbar icon or animation. PE certificate table `(0, 0)` confirms the binary is still unsigned. The user must not be told it has a verified publisher.

## Text-based launcher correction (2026-11-09)

- The user changed the visual scope: only Archx Agent gets an animated image/model once approved and supplied. Training and Fine-tuning can communicate their different roles with a small typographic stage sequence instead of potentially misleading generated 3D objects. A hover-only timer avoids idle animation work; leaving the card resets its highlight. The words are conceptual, not a real progress indicator. Model Monitor is hidden for now.
- `mouse_area::on_enter/on_exit` and a batched timer subscription in Iced 0.14 provide a small native implementation; CI can capture two frozen phases per OS and test a changed text crop. Synthetic phase captures and unit transitions are evidence for rendering/state, but cannot by themselves prove physical mouse movement or timing smoothness on a user's machine.

- Run `43186966425` passed the three-OS source tests and snapshots. Representative PNGs show three cards, no Model Monitor, and text highlights moving between conceptual stages. macOS captures only the top of the shelf in its smaller desktop, as before. CI synthetic phase captures do not prove actual pointer movement; Windows hands-on review remains necessary. The Agent picture is still explicitly temporary until the user supplies an approved model/animation.

## Agent typographic visual correction (2026-11-09)

- User hands-on screenshot showed a 160px black-backed sidebar square contrasting poorly with the rail, and rejected the Agent sculpture. The crop of the original RGBA mark has transparent corners and is rendered at 116px. Native window/PE icon assets are intentionally left unchanged.
- A dedicated `agent_visual` module gives the hero and shelf a consistent but more editorial typographic hierarchy than the simple Training/Fine-tuning cards. It cycles six actual *mode names* and a six-step marker, not a fictitious operational task/progress bar. One low-frequency Home-only timer advances the phase; CI snapshot mode freezes it for deterministic phase review. Live interaction smoothness still needs human validation.

- CI run `43200600325` passed six tests and all build/snapshot jobs on Linux, Windows and macOS. Home/Agent phases show the same lettering and segment movement in the three renderers; macOS still requires scrolling for the lower shelf at its runner resolution. Pixel `(23,23)` in the logo corner equals the rail on all OSes, confirming there is no black sidebar square. This is technical visual evidence, not user acceptance or a timing/frame-rate benchmark.

## Workbench typography and font hierarchy (2026-11-09)

- The accepted Agent kinetic visual is not restyled. The model panels need the same level of editorial intention without becoming identical: a named lab plus a large changing *stage word* and three short markers. Training's DESIGN/TRAIN/EVALUATE communicates making a model; fine-tuning's SELECT/ADAPT/VALIDATE communicates refining one. All are conceptual, never live status.
- Space Grotesk is bundled under SIL OFL for display headings and the two new stage words; Manrope remains default for body, utility and the Agent lettering. A single Semibold role is reserved for the changing model stage word; Medium/Regular do the remaining hierarchy. Increased muted-text contrast from `#757575` to `#919191` and specified an 8/16/24/36px major spacing rhythm in `Docs/design.md` rather than ad hoc card styling.
- Visual screenshots and non-visual test/build evidence now have separate directories. Old CI evidence remains available in Git history; do not claim the new revision passes before inspecting fresh captures.

- First CI attempt `43227366516` failed in Linux compilation before screenshots: shared spacing/type tokens were declared `u16`, but Iced 0.14 `Text::size`/`Space::height` accept `f32`/`u32`, while `Padding` also accepts `f32`. Changed the shared token constants to `f32` (the one type all three APIs accept). Windows/macOS were skipped in that failed run; no success is claimed until the rerun completes.

- Run `43227832253` compiled and captured 8 passing tests on each OS, but visual inspection caught a **macOS font regression**: glyphs across the window overlap after the new variable Space Grotesk registration. Windows screenshot is readable, and the previous macOS screenshot on `1793958` had normal glyph spacing, so passing compilation/PNG size checks did not imply visual acceptance. Generated static 500/600 instances via FontTools varLib.instancer from the bundled OFL variable original and changed Iced registration to those two instances; re-run all OSes and inspect the new macOS capture before accepting the fix.

- Run `43231859324` passed three-OS tests/builds, but static Space Grotesk still distorted **unrelated** macOS text. The old Manrope-only macOS screenshot is legible. Condition font registration and display-family role by OS: retain Space Grotesk static display roles on Linux/Windows, use Manrope Medium/Semibold for the identical hierarchy on macOS. This avoids silently shipping a corrupt macOS GUI; verify in a new macOS screenshot, not just a successful compile.

- Run `43235460451` also passed all eight tests on each OS yet macOS glyphs still overlap with **only** Manrope registered. The changed factor is now explicit Medium/Semibold font-weight requests for the variable Manrope, which were absent in the previously readable macOS build. Map all explicit macOS font roles to Manrope Normal, keeping size/spacing hierarchy; recheck a fresh visual capture. This is a targeted compatibility fallback, not evidence of an identified upstream defect.

- Final run `43239295666` passed Linux/Windows/macOS (8 tests each, release binaries). Visually inspected macOS `tuning-hover-2`: lettering across sidebar, hero and workbench is now legible and spaced correctly again; Windows final capture also looks bounded and legible. Pillow confirmed both model tiles change *within their own panel crops* between frozen phases 1 and 2 on every OS. The macOS fallback trades selective weight/family differences for a functioning UI; it does not change the Agent content or timer. Still await hands-on review of actual motion and approval before Step 2.

## Step 2: Agent UI shell and shared Lab settings (2026-11-09)

- User approved moving past the visually reviewed launcher and prioritizes Agent chat/mode navigation **UI before backend**. Chat messages, edited-message trees, conversions of existing history, storage and inference remain deferred. Empty drafts exist in memory only and switch among six preview modes; their selection cannot imply modes work. The disabled composer and explicit preview badge make that boundary legible.
- Shared Settings is a Lab destination. Memory Light/Heavy/Custom and Agent's Custom choice are non-persistent preview state; no resource is loaded or released yet. Settings evolves as destinations become real rather than duplicating per-app pages or building two editions. Model Training and Fine-tuning remain unavailable.
- APIs verified against Iced 0.14 source: `button.on_press`, `TextInput::new` with no `on_input` is disabled, `container.center_x/center_y(Length)` and native scrollable/row/column; no new dependency. Local Rust toolchain is unavailable, so focused test and visual validation must run in existing three-OS workflow. Keep launcher Agent animation untouched.

- Initial three-OS run `43250400631` passed 11 tests and both Agent/Settings default captures. Visual inspection found the default Iced disabled input drew a conspicuous light rectangle and low-contrast placeholder against the otherwise charcoal UI. A custom *still-disabled* composer style restores charcoal/legible muted type; snapshot-only `ARCHX_SNAPSHOT_MODE=3` and `ARCHX_SNAPSHOT_MEMORY=custom` now capture the alternate selected states, without changing normal startup state. Await a new run before claiming the revision is final.

- Final source `9038f01` passed all three OS jobs in run `43253945098` (11 tests per OS). Reviewed final Windows Coding/Custom and macOS Coding captures; the styled disabled composer is now charcoal with legible muted text, selected mode and memory choices show correct alternate UI states, no overflow in reviewed 1024/1280 viewports. The CLI capture does not exercise a real pointer or verify screen-reader/keyboard use. Windows artifact is portable, unsigned, 19,922,432 bytes. Await user hands-on Step 2 acceptance before building a backend.

## Step 2 follow-up: typeable unsent drafts (2026-11-09)

- The UI-only Agent workspace was navigable but the entirely disabled composer prevented testing the main typing affordance. A per-draft `String` in transient App state now holds unsent text. `Message::EditDraft(id, value)` and `ClearDraft(id)` are scoped to the selected draft; switching drafts does not merge their inputs. New App starts blank. Enter and Send remain unbound, so this is **not** a chat message or persistence implementation.
- Iced 0.14 `TextInput::on_input` produces current text on edits, while `on_submit` is independent; `button.on_press_maybe(None)` disables Clear if empty. The black/silver style now highlights keyboard focus with a silver border. A screenshot-only fixed sentence exercises the visual populated state across three OSes without exposing user data.

- Follow-up source `bfafaf6` completed CI run `43428503990`: Linux/Windows/macOS each passed 12 tests and release build. Reviewed Windows and macOS populated-draft screenshots at 1280 × 800 and 1024 × 645 respectively: editor text, count and no-Send status are readable and remain bounded. Native UI state tests cover switching unsent drafts and clear without messages; screenshot rendering alone cannot prove physical typing. Latest unsigned Windows portable build SHA-256 `66b5ac2521762da156c13466601166861b98c44970b101bbe0722333c4fe64e4`. Await user Step 2 design feedback; do not silently select a model or start Step 3.

## Global rail and provider security boundary (2026-11-09)

- A shared `ToggleSidebar` state changes the 220px Lab rail to an 84px compact rail on Home, Agent and Settings; compact navigation keeps named Home/Agent/About/Settings buttons and a visible Open control. The state stays in-session across page changes; screenshot-only `ARCHX_SNAPSHOT_SIDEBAR=collapsed` tests alternate layouts. Agent artwork and per-draft state are unchanged.
- The next requested provider slice is security-critical: user wants multiple keys per provider/round-robin, secure at-rest storage, 15-second opt-in reveal, catalog and user-entered IDs, opt-in add/remove, free variants, and three test styles. Do not claim 'scattered' key bytes are cryptographically safe: TLS authentication needs transient plaintext in process memory. No key values in CI or chat. Provider endpoints are blocked from this sandbox, so live tests must happen locally by explicit user click, with mock/contract tests in CI. Implementation waits for validated sidebar and an honest agreed security model.

- First compact-rail three-OS run `43440351034`: Linux and Windows compiled, passed 13 tests each and captured expanded/compact UI states. macOS never received a runner, then GitHub cancelled it at 15 minutes. A separate macOS-only push-triggered workflow is the smallest honest recovery: no model/provider integration proceeds until a real macOS build and visual capture exist. GitHub rerun and workflow_dispatch were unavailable to this integration, so this is a narrowly scoped workaround rather than a test shortcut.
