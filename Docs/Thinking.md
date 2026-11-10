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
