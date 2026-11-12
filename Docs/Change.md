<!-- Purpose: Tracks user-requested product scope changes and their roadmap effects. -->
# Requested changes

## 2026-11-09 — General task agent and delivery order

- **Request:** Add a general task agent alongside simple chat, coding, learning, research, and play. Begin with the home screen, then the chat interface and mode navigation, then implement each mode completely in sequence.
- **Roadmap effect:** Added the general task agent as a distinct milestone after the shared agent/memory foundation; separated the home shell and chat UI from the modes' working behavior. Mode order after the foundation can be revisited with the user.
- **Delivery condition:** After each GUI step, provide a downloadable Windows build for hands-on testing, while running relevant checks on Windows, Linux, and macOS. Agree how large build downloads are distributed before Step 1.
- **Open:** Define general-task tool/memory boundaries and whether simple chat can convert to general task mode. No agent feature has been implemented yet.

## 2026-11-09 — AI Lab identity and home-screen design

- **Request:** Name the AI/ML launcher **Archx AI Lab**; reserve **Archx Agent** for the chat destination. Include future entries for model training, fine-tuning, and model observation. Use a sleek, minimal graphite/black style, professional typeface, and restrained gray glass-like menu selection. Capture/inspect the running UI on Windows, Linux, and macOS; the user chose repository-hosted Windows builds.
- **Roadmap effect:** Step 1 is the AI Lab home shell with the future areas visibly unavailable. Their actual capabilities remain later scope. Cross-platform screenshots and a Windows executable are part of the Step 1 completion gate.
- **Open:** Actual functionality and naming of future model workspaces are not yet approved; no claim of pixel-identical OS chrome or successful build before runner review.

## 2026-11-09 — Windows console fix and app-launcher redesign

- **Request:** The portable Windows GUI must not leave a Command Prompt open. Replace the generic dark dashboard look with a proper app-launcher entrance inspired by Epic/LDPlayer browsing: true black, restrained grey/white, selected smoky-grey menu state, and clearly app-based AI destinations.
- **Roadmap effect:** Reopen Step 1 for correction; do not start Step 2 until the updated Windows executable is delivered and three-OS builds, snapshots, and Windows GUI-subsystem assertion pass.
- **Design:** Updated `Docs/design.md`. The artwork is original monochrome Agent cover imagery, not copied launcher art or neon UI.

## 2026-11-09 — Reference-led active state and less generic app shelf

- **Request:** Replace the flat selected About/Discover rectangle with a sleek dark pill and soft silver-grey bottom glow like the supplied reference. Make the overall launcher more distinctive, cleaner, glassier and less generic without making it dense or flashy.
- **Roadmap effect:** Step 1 stays open for a new three-OS UI review and Windows build; do not start chat. Inspect selected states on both available pages.
- **Design:** Use an inexpensive native Iced gradient, thin rim and subtle shadow; add four distinct monochrome app cover images so destinations read as separate apps. Keep them inert until built.

## 2026-11-09 — Bounded covers and current review evidence

- **Visual finding:** The reference-led run `43016569988` passed all three OS tests but its Home screenshots showed blank shelf art on Windows/macOS and art overlapping text on Linux. This was a cross-renderer layout issue, not a successful review build.
- **Change:** Normalized four app tile images to 800 × 480, added a cropped Agent tile, clipped each cover within a fixed-height container, waited five seconds before CI snapshots, and tested decoding all four bundled covers. Kept the original full-width Agent feature image.
- **Validation:** Run `43020392009` passed all three jobs (4 tests each), captured Home/About on each platform and asserted Windows GUI subsystem `2`. Reviewed the updated Home PNGs: covers and names are visible without overlap on 1280 × 800 Windows/Linux; compact macOS shows the shelf art but its names remain below the fold, reachable by scrolling. About PNGs from the immediately preceding run show the same glass selected state; the workflow produced new About PNGs for this run. Exact evidence and limitations are recorded in `Docs/Test_Results/Unreleased/Gui_Validation.md`.
- **Pending:** User hands-on review and approval of the Windows launcher. Step 2 remains blocked.

## 2026-11-09 — User-supplied mark, production-facing copy, and actual 3D request

- **Request:** Replace the sidebar placeholder with the supplied Archnemix mark, put the same logo on the native window/taskbar and Windows executable, remove preview labels, and replace static generic artwork with high-quality, domain-specific 3D objects that perform a real 360-degree rotation on hover. Validate appearance and animation on all three OSes. Show verified publisher Archnemix on Windows.
- **Now:** Brand assets and Windows product metadata are added without claiming an Authenticode signature. The user is unsure whether a certificate exists; no signing secret, certificate or key has been obtained. Actual 3D assets, rendering/hover and animation tests remain open; a 2D image spin would not satisfy the user's clarification. Keep Step 1 open until this is built, visually checked and user-reviewed.
- **Signing constraint:** A trusted certificate issued to Archnemix plus a secure signing mechanism is needed for Windows to show a verified publisher; visual branding and version-info fields alone cannot do it. No secret values go in chat or Git. See `Docs/Research.json`.

## 2026-11-09 — Brand-only cross-platform evidence

- **Validation:** Actions run `43031034141` passed Linux/Windows/macOS tests/builds/screenshots (4 tests passed per OS) and Windows PE GUI-subsystem and company-metadata checks. Reviewed client screenshots: logo and non-preview copy consistent; compact macOS shelf remains scrollable. Native titlebar/taskbar and 3D animation are not proven by client captures.
- **Delivery:** New unsigned portable Windows build recorded at `deliverables/Unreleased/windows/archx-ai-lab.exe`. PE certificate directory is empty. User requested verified publisher and genuine high-quality rotating 3D covers; both remain open, not silently treated as done.

## 2026-11-09 — Meshy reference mapping and future coding workspace

- **Request:** Explain which reference image belongs to which app before generating any more images. The main Archx Agent image must represent the full six-mode hub (simple chat, general task, research, coding, learning and play), not only a chat bubble. Model Training is a separate launcher destination. A future Coding Agent should eventually include a built-in code editor; this is a later functionality decision, **not** part of Step 1 artwork or an implemented feature.
- **Suggested art mapping for approval:** one six-path Agent core, one training-process artifact, one precise fine-tuning instrument, and one model-observation instrument. Optionally use a 3D rendition of the user-supplied logo in the hero only if it improves the composition; retain the original mark for identity and icons. Do not generate ambiguous imagery or use an independent AI-generated "Archnemix" wordmark.
- **Performance request:** plan two future display modes based on available RAM/CPU and a user choice in Settings; the mode names and thresholds need benchmarking rather than arbitrary assumptions. Real 3D remains unimplemented; prior image-selection previews were skipped, with no selected asset saved.

## 2026-11-09 — Agent-only animated art; text motion for other apps

- **Correction:** The user no longer wants 3D objects for Training or Fine-tuning. Only Archx Agent should ultimately have an approved animated visual; the user has a model to upload later. For now, the Agent shelf/hero retain clearly temporary art. Model Training and Fine-tuning should use text-based animations. Model Monitor/observation is removed from the current launcher, not ruled out permanently.
- **Current slice:** Remove the other three JPEG covers and the Monitor destination; use hover-triggered stage-emphasis typography in the two remaining unavailable model-workspace cards. Keep their labels Coming Later, without claiming that any training is occurring. Do not start chat UI or pretend the Agent asset has been integrated. Three-OS validation is required for this GUI change.

## 2026-11-09 — Three-card text-motion validation

- **Evidence:** Actions run `43186966425` passed 5 focused tests per OS, release builds and 15 screenshots total on Linux/Windows/macOS. Home/About and Training/Tuning synthetic hover phases captured; reviewed representative captures. Windows GUI subsystem `2` and descriptive Archnemix metadata still pass; executable is unsigned. Full commands, outputs and limitations are in `Docs/Test_Results/Unreleased/Gui_Validation.md`.
- **Still open:** Agent animation needs the user's approved 3D/model or image asset; desktop hover smoothness and reduced-motion/low-resource preferences need later design and tests. No chat UI started.
