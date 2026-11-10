<!-- Purpose: Describes the project stack, component responsibilities, and file interfaces. -->
# Technical overview

Iced has been selected as the Rust desktop UI framework; Windows, macOS, and Linux are first-class targets from the start. No product code, other stack components, persistence engine, or interfaces have been selected or implemented yet. The repository currently holds documentation and an internal-helper directory only. See [Files_Info.json](Files_Info.json) for each file's responsibility and inputs/outputs, [Logic.md](Logic.md) for implemented call flows, and [Plan/Architecture.md](Plan/Architecture.md) for discussed product behavior. Keep these aligned as components are added.

## Home shell in progress

- `Cargo.toml`: Rust 2024 application with Iced 0.14 for native UI and `image` 0.25 PNG support only for opt-in cross-OS screenshot capture. The home shell's focused unit test, release builds, and running-app screenshots passed the Linux, Windows, and macOS CI workflow; see `Test_Results/Unreleased/Gui_Validation.md`. This does not establish future agent functionality or pixel-identical UI rendering.
- `src/main.rs`: initializes the window, Manrope typeface, theme, and application callbacks.
- `src/app.rs`: holds available home/about navigation and optional `ARCHX_SNAPSHOT` capture state; no model or persistence yet.
- `src/home.rs`: renders the AI Lab launcher, future destination labels, and About view; unfinished destinations are inert.
- `src/style.rs`: palette and reusable native container/button styles. `assets/fonts/` holds licensed Manrope.
- `.github/workflows/gui.yml`: intended source-triggered three-OS compilation/test/screenshot review and repository-hosted portable Windows executable. The local sandbox has no Rust toolchain, so successful build/runtime behavior must be established by runner logs before marking the roadmap step complete.
