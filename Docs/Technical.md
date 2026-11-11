<!-- Purpose: Describes the project stack, component responsibilities, and file interfaces. -->
# Technical overview

Iced is the selected Rust desktop UI framework; Windows, macOS, and Linux are first-class targets from the start. The native launcher is implemented, but no AI provider, agent runtime, persistence engine, or product backend has been selected or built. See [Files_Info.json](Files_Info.json) for each file's responsibility and inputs/outputs, [Logic.md](Logic.md) for implemented call flows, and [Plan/Architecture.md](Plan/Architecture.md) for discussed product behavior. Keep these aligned as components are added.

## Home shell in progress

- `Cargo.toml`: Rust 2024 application with Iced 0.14 for native UI and `image` 0.25 PNG support only for opt-in cross-OS screenshot capture. The brand follow-up passed four focused tests, release builds, and Home/About screenshots on each of Linux, Windows, and macOS; Windows CI also verified PE GUI subsystem 2 (no console) and truthful product metadata. See `Test_Results/Unreleased/Gui_Validation.md`. This does not establish future agent functionality or pixel-identical UI rendering.
- `src/main.rs`: initializes the window, Manrope typeface, native window icon, theme, and application callbacks; Windows **release** builds select the GUI subsystem so launching the app does not open a console.
- `src/app.rs`: holds available home/about navigation and optional `ARCHX_SNAPSHOT` capture state; `ARCHX_SNAPSHOT_PAGE=about` selects the About page only when taking a CI screenshot. Snapshot delay is five seconds to allow images to load before capture. No model or persistence yet.
- `src/home.rs`: renders the AI Lab launcher, Agent feature and About view; unfinished destinations are inert.
- `src/app_tile.rs`: renders four unavailable AI apps with cached 800 × 480 cover images, bounded by a clipping container; tests decode all covers.
- `build.rs`: embeds the user-supplied Archnemix ICO and company metadata only on Windows. The metadata is not a digital signature.
- `src/style.rs`: black/grey palette and reusable styles, including a native gradient/shadow selected-menu pill. `assets/fonts/` holds licensed Manrope; `assets/` holds four original monochrome generated images embedded at compile time.
- `.github/workflows/gui.yml`: source-triggered three-OS compilation/test/screenshot review and repository-hosted portable Windows executable. The local sandbox has no Rust toolchain; run `43031034141` supplies brand-stage build/runtime evidence. Its still screenshots do not validate hover/3D animation or native window chrome, and the unsigned binary cannot show a verified publisher.
