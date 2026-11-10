<!-- Purpose: Records the exact cross-platform GUI test inputs, commands, outputs, screenshots, and build. -->
# Home-shell GUI validation — 2026-11-09

Source input: commit `f252d2b` (`Cargo.lock` pinned); CI run `42850017311` on GitHub Actions. Linux, Windows, and macOS ran sequentially. The common UI starts at a requested 1280 × 800 logical window. No model calls, credentials, user data, or database inputs were used.

| Runner | Commands from `.github/workflows/gui.yml` | Observed test output | Screenshot output |
| --- | --- | --- | --- |
| Linux | `cargo generate-lockfile`; `cargo test --locked`; `cargo build --release --locked`; `xvfb-run -a env ARCHX_SNAPSHOT=Docs/Test_Results/Unreleased/visual/linux.png ./target/release/archx-ai-lab`; `test -s Docs/Test_Results/Unreleased/visual/linux.png` | `test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out`; release build succeeded; PNG nonempty. Full stdout/stderr: `build/linux.log`. | `visual/linux.png`, 1280 × 800, SHA-256 `6583efef524eae0f43bee4137548c423f4939baea4747ae4c4bcfd43d75b3c99` |
| Windows | `cargo test --locked`; `cargo build --release --locked`; `ARCHX_SNAPSHOT=Docs/Test_Results/Unreleased/visual/windows.png ./target/release/archx-ai-lab.exe`; `test -s Docs/Test_Results/Unreleased/visual/windows.png`; copy exe into `deliverables/Unreleased/windows/` | Same test result (1 passed), release build succeeded, PNG nonempty, executable copied. Full stdout/stderr: `build/windows.log`. | `visual/windows.png`, 1280 × 800, SHA-256 `f59196c3b3b9ee3876b4abcdb06ba38953c817e3b377e7cdbb616929ed6ce549` |
| macOS | `cargo test --locked`; `cargo build --release --locked`; `ARCHX_SNAPSHOT=Docs/Test_Results/Unreleased/visual/macos.png ./target/release/archx-ai-lab`; `test -s Docs/Test_Results/Unreleased/visual/macos.png` | Same test result (1 passed), release build succeeded, PNG nonempty. Full stdout/stderr: `build/macos.log`. | `visual/macos.png`, 1024 × 642, SHA-256 `c080e1d2207c98bccfd950f7e055abe02a65fb1b219e6d1b5b417fbdf9804ebd` |

Windows downloadable output: `deliverables/Unreleased/windows/archx-ai-lab.exe` (11,540,480 bytes), SHA-256 `a06e180f70aa52a03c5fc568abcb3068989497a01d4535cf145f5fa69d11ae60`. It is portable and unsigned, not an installer.

**Visual inspection:** All three captures show the same dark launcher composition and readable Manrope text without apparent clipping in the visible viewport. The macOS runner's available display limited the screenshot to 1024 × 642, so the lower destination cards are below the fold and must be scrolled into view there; no byte-identical screenshot or full-page macOS visual claim is made. Actual Windows user interaction remains for the user's hands-on review before moving to the chat UI.

Earlier attempts are not erased: first Linux compilation errors are in Git revision `eb65c61:Docs/Test_Results/Unreleased/build/linux.log`; the later missing X11 runtime error is in `e983642:Docs/Test_Results/Unreleased/build/linux.log`. Both earlier runs failed and skipped Windows/macOS. The final success logs are the current versions of each `build/*.log` file.
