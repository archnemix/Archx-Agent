<!-- Purpose: Records current cross-platform GUI commands, inputs, outputs, screenshots, and Windows subsystem verification. -->
# Home-shell GUI validation — latest review build

Source input: commit `6537b5e` (plus its pinned `Cargo.lock`); GitHub Actions run `42992545976`. No model, account, database, credential, or user data was used. Linux, Windows, and macOS jobs ran sequentially. See `.github/workflows/gui.yml` for complete shell steps and `build/*.log` for exact observed stdout/stderr.

| OS | Exact test/build and capture inputs | Observed output |
| --- | --- | --- |
| Linux | `cargo generate-lockfile`; `cargo test --locked`; `cargo build --release --locked`; `xvfb-run -a env ARCHX_SNAPSHOT=Docs/Test_Results/Unreleased/visual/linux.png ./target/release/archx-ai-lab`; `test -s Docs/Test_Results/Unreleased/visual/linux.png` | `test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out`; release build and screenshot succeeded. `visual/linux.png`: 1280 × 800, SHA-256 `2ccd106e55c1aa161280a20e0cad96131e13ffa2b2003df049251a26dd211c35`. |
| Windows | `cargo test --locked`; `cargo build --release --locked`; Python PE check (below); `ARCHX_SNAPSHOT=Docs/Test_Results/Unreleased/visual/windows.png ./target/release/archx-ai-lab.exe`; `test -s Docs/Test_Results/Unreleased/visual/windows.png`; copy exe to `deliverables/Unreleased/windows/` | `test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out`; `PASS: Windows GUI subsystem 2 (no console)`; release build and screenshot succeeded. `visual/windows.png`: 1280 × 800, SHA-256 `68c42d81ec464c475aa7acb316de45a9141d1f01fe2aa156dbd0a25475c0378c`. |
| macOS | `cargo test --locked`; `cargo build --release --locked`; `ARCHX_SNAPSHOT=Docs/Test_Results/Unreleased/visual/macos.png ./target/release/archx-ai-lab`; `test -s Docs/Test_Results/Unreleased/visual/macos.png` | `test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out`; release build and screenshot succeeded. `visual/macos.png`: 1024 × 642, SHA-256 `6f0728512fa9123a0f86cfe54eb3c353a49b7164703b584e90357303b180b968`. |

The Windows test explicitly reads the PE optional-header subsystem field and asserts GUI subsystem `2`:

```sh
python -c 'import pathlib,struct; data=pathlib.Path("target/release/archx-ai-lab.exe").read_bytes(); pe=struct.unpack_from("<I",data,0x3c)[0]; subsystem=struct.unpack_from("<H",data,pe+92)[0]; assert subsystem==2, f"Expected GUI subsystem 2, found {subsystem}"; print("PASS: Windows GUI subsystem 2 (no console)")'
```

Download output: `deliverables/Unreleased/windows/archx-ai-lab.exe` (20,240,896 bytes), SHA-256 `3f01c4351ee699d0fb346aeabd4a93be207bfc3c9620640e12589c1438974e83`. It is an unsigned portable executable, not an installer.

**Visual inspection:** The latest Windows/Linux captures show the black/grey launcher, full Agent art, app covers **and app names within 1280 × 800**; no console is expected from the new Windows GUI-subsystem build. The macOS runner's 1024 × 642 display shows the same top layout and complete Agent artwork; the app shelf continues below the visible area and is scrollable. This is not a claim of pixel-identical rendering or of a user-run Windows session. The user's hands-on review remains the final Step 1 acceptance gate.

Earlier attempts remain inspectable via Git history: first Linux compiler errors at `eb65c61:Docs/Test_Results/Unreleased/build/linux.log`, Linux missing X11 runtime at `e983642:Docs/Test_Results/Unreleased/build/linux.log`, the original console-subsystem build review at `ea2d690:Docs/Test_Results/Unreleased/Gui_Validation.md`, and the first black launcher capture in CI commits `d7696ff..f11f4cf`. Current full outputs are in `build/linux.log`, `build/windows.log`, and `build/macos.log`.
