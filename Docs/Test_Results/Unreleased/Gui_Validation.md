<!-- Purpose: Records current three-OS GUI test commands, outputs, screenshots, visual review, and Windows delivery. -->
# AI Lab launcher validation — current review build

Source input: commit `731206d`, locked dependencies in `Cargo.lock`, four embedded 800 × 480 shelf covers plus original Agent feature art. GitHub Actions run `43020392009` on Linux, Windows, macOS sequentially. No model, user data, secrets, backend, or network UI input was used. The exact command output is in `build/linux.log`, `build/windows.log`, and `build/macos.log`.

| Runner | Exact commands and inputs | Observed output |
| --- | --- | --- |
| Linux | `cargo generate-lockfile`; `cargo test --locked`; `cargo build --release --locked`; `xvfb-run -a env ARCHX_SNAPSHOT=Docs/Test_Results/Unreleased/visual/linux.png ./target/release/archx-ai-lab`; `test -s Docs/Test_Results/Unreleased/visual/linux.png`; `xvfb-run -a env ARCHX_SNAPSHOT_PAGE=about ARCHX_SNAPSHOT=Docs/Test_Results/Unreleased/visual/linux-about.png ./target/release/archx-ai-lab`; `test -s Docs/Test_Results/Unreleased/visual/linux-about.png`. | `test result: ok. 4 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out`; release build passed, both PNGs nonempty. |
| Windows | `cargo test --locked`; `cargo build --release --locked`; PE subsystem assertion below; `ARCHX_SNAPSHOT=Docs/Test_Results/Unreleased/visual/windows.png ./target/release/archx-ai-lab.exe`; `test -s` Home PNG; `ARCHX_SNAPSHOT_PAGE=about ARCHX_SNAPSHOT=Docs/Test_Results/Unreleased/visual/windows-about.png ./target/release/archx-ai-lab.exe`; `test -s Docs/Test_Results/Unreleased/visual/windows-about.png`; copy `target/release/archx-ai-lab.exe` to `deliverables/Unreleased/windows/`. | Same test result (4 passed), `PASS: Windows GUI subsystem 2 (no console)`, release build and both PNGs succeeded; exe copied. |
| macOS | `cargo test --locked`; `cargo build --release --locked`; `ARCHX_SNAPSHOT=Docs/Test_Results/Unreleased/visual/macos.png ./target/release/archx-ai-lab`; `test -s` Home PNG; `ARCHX_SNAPSHOT_PAGE=about ARCHX_SNAPSHOT=Docs/Test_Results/Unreleased/visual/macos-about.png ./target/release/archx-ai-lab`; `test -s Docs/Test_Results/Unreleased/visual/macos-about.png`. | Same test result (4 passed), release build passed, both PNGs nonempty. |

Windows GUI-subsystem assertion, run against the actual release binary:

```sh
python -c 'import pathlib,struct; data=pathlib.Path("target/release/archx-ai-lab.exe").read_bytes(); pe=struct.unpack_from("<I",data,0x3c)[0]; subsystem=struct.unpack_from("<H",data,pe+92)[0]; assert subsystem==2, f"Expected GUI subsystem 2, found {subsystem}"; print("PASS: Windows GUI subsystem 2 (no console)")'
```

| Output | Pixels | SHA-256 |
| --- | --- | --- |
| `visual/linux.png` | 1280 × 800 | `22f09962a2d368a1aeac3c3558d8793de5efe042c3db1a9c8eb32c864605a2df` |
| `visual/linux-about.png` | 1280 × 800 | `cdfaac537dd9e7da3f2d2d635f4e2220a3c0c66a90dea6ad39d971e8eef1dc03` |
| `visual/windows.png` | 1280 × 800 | `6e3f2f172d4156a592bba19ebf447a3ceefad65d11008d323d6d2b351f41dc36` |
| `visual/windows-about.png` | 1280 × 800 | `87f640149ccaa666b731da273153884e25b2cd4ee23a7293685a9ce66a60a1c2` |
| `visual/macos.png` | 1024 × 642 | `d5307772afcfde3ffc835c58927adf1c9c50e3c22521460baefa30e0a0935a55` |
| `visual/macos-about.png` | 1024 × 645 | `5228ed2e2af9e5a9b1a53d2390bd83255de8e9af9de674d8d060debb0bf51ace` |

Download: `deliverables/Unreleased/windows/archx-ai-lab.exe` (20,461,056 bytes), SHA-256 `caa9fc5b52b9884bf5f6f56b62dfd5dabe55f88e01253d3ab37831be166362e7`. Portable and unsigned, not an installer.

**Visual inspection:** Previous run `43016569988` exposed blank shelf covers on Windows/macOS and overflowed images on Linux, despite passing tests; it is **not** counted as a visually successful iteration. The current screenshots show all four covers bounded above their labels on Windows and Linux, with consistent black/silver selected navigation on Home and About. The macOS runner's smaller viewport shows the hero and upper shelf only; the remaining content is scrollable but not fully visible in that screenshot. Pixel-identical output and normal user interaction are not claimed. Await the user's Windows hands-on approval before Step 2.

Prior logs/results remain inspectable in Git history: `eb65c61` (Linux compiler failure), `e983642` (missing X11 runtime), `ea2d690` (first review build), `f11f4cf` (console fix), `40082d9` (first app launcher), and `8478e7f` (failed visual inspection with new covers). Current full runner output is the latest `build/*.log` files.
