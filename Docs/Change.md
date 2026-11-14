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

## 2026-11-09 — Agent kinetic typography and transparent smaller sidebar mark

- **Correction:** The user rejected the Agent sculpture as too generic. They want the Agent hero/shelf to read as a designed animated **text visual**, more distinctive than the model-workspace typography, instead of an image or 3D object. The supplied Archnemix logo was too large and its black-backed square looked wrong on the rail; keep alpha transparency and display a smaller crop.
- **Implementation slice:** Use a six-mode kinetic type identity for Agent on Home, replacing both generated sculpture assets; crop the user-supplied transparent logo without recompositing on black, display at 116 × 116. The two model-workspace hover panels and three-app shelf remain. CI captures Agent phase 1/3 on each OS; no feature becomes clickable or functional. Step 1 still needs three-OS evidence and hands-on user approval; signing remains separate and blocked.

## 2026-11-09 — Agent typography validation

- **Result:** Run `43200600325` passed Linux/Windows/macOS (six tests per OS, release builds, Home/About plus five synthetic phase captures per OS). Reviewed six representative PNGs: old Agent artwork is gone, synchronized six-mode labels and markers fit in hero/shelf, and sidebar logo background is transparent and size reduced. Windows PE GUI subsystem and Archnemix descriptive metadata pass; digital signature remains absent. See `Docs/Test_Results/Unreleased/Gui_Validation.md` for exact commands, outputs, hashes and limitations.
- **Gate:** The user's normal Windows experience and design acceptance are still required; motion smoothness is not proven by frozen screenshots. Chat UI remains unstarted.

## 2026-11-09 — Final workbench-art, font and evidence-directory correction

- **Feedback:** The Agent animation looks good and should not be changed. The Training/Fine-tuning cards are still too plain: a small text change in the corner is insufficient. Rename their *visual concepts* (not yet working destinations) to **Model Forge** and **Refinement Studio**, enlarge the changing word to the center of each card, and add a three-part animated marker. Replace the generic `THE COLLECTION / Your AI apps` section with `EXPLORE / AI workspaces`.
- **Typography:** After reviewing Space Grotesk from Google Fonts, use it selectively for display headings and the two workbench cards while keeping Manrope body/navigation and the accepted Agent artwork. `Docs/design.md` is the one visual-token specification: font weight budget, contrast roles, major spacing steps and hierarchy. No font is chosen solely by trend or applied everywhere.
- **Evidence:** Route CI build/test/PE logs to `Docs/Test_Results/Unreleased/non_visual/` and screenshots to `.../visual/`. Maintain three-OS tests/captures and Windows GUI build; inspect visuals before offering Step 1 for acceptance. Signing remains a separate unresolved prerequisite.

## 2026-11-09 — Agent UI and shared Lab settings

- User accepts proceeding from launcher design to the Archx Agent destination. Prioritize **sleek, professional, minimal** chat and mode-navigation UI *before* backend logic. UI-only navigation may create temporary empty chats and select a draft mode; do not simulate responses, send messages or imply an AI model is installed. No decision yet on how edited-message trees and existing-history mode conversions work; defer until real chat behavior is scoped.
- There is **one** app, not two editions. Settings belong to the AI Lab launcher and grow with each destination, not isolated per-app settings pages. A future Memory area should offer Memory Light, Memory Heavy and Custom: Custom chooses what stays loaded versus unloads on exit. For the first UI slice cover Agent only, and label controls honestly as UI preview, not real RAM optimization or persisted preference; real resources do not exist to load/unload yet.

## 2026-11-09 — Continue Step 2 without backend

User asked for a progress summary and to continue. Keep work inside the Agent UI step: make the composer editable for **unsent per-draft, in-session text**, allow clearing it, and keep Send unavailable. Do not select a model, add simulated responses, persist chat history or implement message-tree editing/conversion. This allows hands-on review of typing and switching drafts without implying a functional AI agent.

## 2026-11-09 — Collapsible global rail, then provider settings

- User's Windows screenshot shows the launcher rail taking up a full 220px on every view. Add an explicit compact/open control to the **shared** Lab rail, preserving navigation and the approved Agent typography. Verify full and collapsed states across Linux, Windows and macOS before a model-integration step.
- Next requested model Settings/providers: **OpenRouter, xAI Grok, and Gemini**. Support multiple user-entered API keys per provider with deliberate round-robin choice, provider model catalog plus manually entered model IDs, opt-in add/remove models rather than importing the whole catalog, and separate free variants where the provider actually exposes them. The user wants safe storage, masked keys with a 15-second reveal, and three test approaches (availability/usage stats where supported, catalog listing, and one explicit small possibly billable generation). This is a future *security-critical* slice; do not implement an unencrypted fallback or claim mocked CI requests are live provider tests.
- Keys must be entered locally in the desktop app, never in chat, Git, screenshots or CI logs. OS-backed credential storage is preferable to a custom encryption scheme. Key material necessarily becomes transient plaintext during an authorized request; the request that it never appear whole in memory, even briefly, is not technically guaranteeable with normal HTTP/TLS libraries. Fail closed where secure storage is unavailable. Live requests cannot be executed in the current sandbox because provider hosts are blocked; verify via unit/mock tests and user-initiated tests on their machine.

## 2026-11-09 — Credential in-memory hardening request and security boundary

User reiterates that decrypted API-key bytes must remain split across randomly moved memory locations, encryption/decryption keys must be protected, plaintext must never be stored on disk, and reveal must last exactly 15 seconds. We cannot honestly guarantee that an in-process HTTP/TLS client, GUI reveal, OS swap/crash dumps or a process-memory reader will never contain/recover a whole key: the credential must be assembled transiently for an Authorization header. Moving fragments every few seconds is not a verified security control and could increase copies/exposure. Do not implement or market such a guarantee. Provider integration remains blocked pending acceptance of a realistic threat model: OS-backed credential storage without plaintext application files, deliberate short-lived access, redaction, bounded reveal and best-effort zeroization, while explicitly documenting limitations.

## 2026-11-09 — Plain chat first and rail affordance correction
The user rejected the awkward Hide/Open rail controls and requested visual review on every new visual change; use a consistent bottom-edge expand/collapse control with clear labels and test both states on native runners. They prioritized a simple working API-backed Chat mode and navigable multi-page Settings, not speculative tools, database or memory. No model call should happen until an explicit send action and user-selected provider/model; do not mislabel UI previews as functioning chat.

## 2026-11-09 — Session-only API experiment before archive/memory
The user now explicitly prioritizes a simple working Chat API test and says no database or memory at this stage; the plain-chat slice may be implemented directly after provider key setup, with no persistence or tool execution. Multi-page Settings must make provider keys and manual model IDs navigable. A live provider call is user-initiated and may be billable. Catalog/stats remain provider-dependent follow-up; do not treat synthetic contract tests as a live test.

## 2026-11-09 — Intentional icon rail and Settings hierarchy
The user rejected the collapsed Lab rail as a cramped expanded sidebar: text labels, tiny logo, full-width selected Settings pill, ungrouped blank space and an unrelated expand button. Their image is a *layout reference*, not a brand/asset source. Collapse must switch to an icon-only, fixed-size navigation rail with meaningful grouping, right-side hover labels and an integrated icon expand control; the user-supplied Archnemix logo remains the identity. Attached HTML/CSS/JS is a *visual reference* for professional Settings organization, not a request to execute/copy its JS or introduce its unsupported tools/storage pages. Keep the native Rust/Iced app, current Chat security boundaries and accepted Agent artwork.

## 2026-11-09 — Catalog discovery and broader provider request

User requests searchable, explicitly added provider catalogs; a separate free section including the OpenRouter automatic free router; reasoning indicators only from provider metadata; safe Markdown chat; and staged support for Groq, local Ollama, OpenAI API, Anthropic API, Mistral, Z.ai and user-configured compatible/generic endpoints. OpenAI API is distinct from the ChatGPT website. Generic endpoints must not use a fixed remote-domain allowlist; before exposing arbitrary headers or credentials, establish an explicit per-destination network/secret permission boundary and test it. User accepts tested slices. First slice covers only the existing three providers' catalog discovery and selection; it does not silently enable new destinations or Markdown rendering.
