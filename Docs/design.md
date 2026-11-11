<!-- Purpose: Defines the AI app-launcher visual system and cross-platform review criteria. -->
# Archx AI Lab — design system

## Product identity

**Archx AI Lab** is the Archnemix AI/ML app launcher; **Archx Agent** is its future chat-and-agent app. Model Training, Fine-tuning, and Model Monitor are separate future destinations. Unbuilt areas must say *Coming later* or *In development* and never simulate working controls.

The layout takes **navigation patterns**, not artwork or branding, from desktop launchers: a persistent left rail, a featured app display, and a browsable app shelf. Epic's official support material describes Store/Library navigation; the intent here is an original AI-focused launcher, not an Epic or LDPlayer replica.

## Visual system

- **True black** main canvas `#080808`, rail `#0D0D0D`, surfaces `#141414` to `#202020`; crisp near-white `#F4F4F4` type, neutral grey secondary text, hairline grey outlines. No neon, saturated accent, bright gradients, or dashboard-style KPI cards.
- **Selection:** gray translucent-looking selected navigation surface with a subtle border; lightweight solid/alpha fill instead of an expensive backdrop blur. Hover is visibly distinct. Only available pages respond to clicks.
- **Typography:** bundled Manrope (SIL OFL) for consistency across Windows, Linux, macOS. Body 13–16px, prominent clear titles. Preserve the original license under `assets/fonts/OFL.txt`.
- **Editorial artwork:** original generated monochrome sculpture in `assets/agent-cover.png`, embedded into the executable and limited to the Agent feature tile; it has no text or external image request. Other app covers use simple native monochrome letterforms; no distracting icon pack or copying other brands' content.
- **Structure:** compact brand and browsing rail; feature banner for Archx Agent; app shelf with distinct tile covers, titles, categories, and availability labels. At the default 1280 × 800 viewport the app names should be visible without scrolling; on compact displays the remaining shelf can scroll. The Agent art must remain uncropped at narrower widths. The About page is the only second working destination in the first slice. Library and all AI apps remain visibly unavailable.

## Cross-platform review

- Build and run on Windows, Linux, and macOS after each GUI step. Inspect captures of the running app for typography, clipping, contrast, active states, and the full intended viewport. Actual first-run macOS capture was 1024 × 642 despite requesting 1280 × 800; compare visible content at available sizes and check that lower content can scroll. Pixel-identical OS window chrome is not possible; target a consistent **app content** layout.
- Windows releases must use the GUI subsystem and **must not open a Command Prompt**. CI verifies the PE subsystem numeric value 2, a successful GUI snapshot, and the portable executable.
- Keep tests/screenshots for the current and preceding two versions. The user chose repository-hosted Windows downloads; monitor executable growth and don't accumulate unnecessary old builds.

## Deferred

Final training/monitoring UIs, more cover artwork, interactive library search, account systems, and live agent controls belong to their own future milestones. No placeholder is described as a working feature.
