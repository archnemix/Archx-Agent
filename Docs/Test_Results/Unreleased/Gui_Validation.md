<!-- Purpose: Records current three-OS GUI test commands, outputs, screenshots, visual review, and Windows delivery. -->
# AI Lab launcher validation — brand follow-up and earlier review

## Brand follow-up (2026-11-09)

Source commit `76db961`, Actions run `43031034141` (passed sequential Linux, Windows and macOS). Each job ran `cargo test --locked` (4 passed, 0 failed), `cargo build --release --locked`, and the Home/About screenshot commands listed in the earlier section below. Windows also ran the PE GUI-subsystem check (output `PASS: Windows GUI subsystem 2 (no console)`) and this metadata check:

```sh
powershell.exe -NoProfile -Command '$info=(Get-Item "target/release/archx-ai-lab.exe").VersionInfo; if ($info.CompanyName -ne "Archnemix" -or $info.ProductName -ne "Archx AI Lab") { throw "Incorrect PE product metadata" }; Write-Output "PASS: Archnemix Windows product metadata (not a digital signature)"'
```

Observed `PASS: Archnemix Windows product metadata (not a digital signature)` in `build/windows.log`. The exact test and build outputs are in `build/{linux,windows,macos}.log`. The latest Home/About PNGs were captured successfully on all three OSes. Visual inspection of Home and Windows About: provided black-backed logo replaces the generic letter badge; `LOCAL PREVIEW` and `PREVIEW 01` are gone; no tile-cover overlap at 1280 × 800 Windows/Linux; macOS still needs scrolling to show tile labels. These screenshots show client content only: they do **not** prove native titlebar/taskbar icon fidelity or hover animation. Command `/home/user/.venv/bin/python` (Pillow) with `ImageChops.difference`/`ImageStat.Stat` on `visual/{windows,linux,macos}.png` 160 × 160 logo crops at `(23,23)` found mean absolute per-channel RGB error of `4.283` for Windows versus Linux and `0.022` for Windows versus macOS; the logo geometry and layout are consistent, but GPU/font sampling differs, so pixel-identical output is not claimed. Exact comparison input/code:

```sh
/home/user/.venv/bin/python - <<'PY'
from PIL import Image, ImageChops, ImageStat
from pathlib import Path
root = Path('Docs/Test_Results/Unreleased/visual')
logo = {os: Image.open(root / f'{os}.png').convert('RGB').crop((23, 23, 183, 183)) for os in ('linux', 'windows', 'macos')}
for os in ('linux', 'macos'):
    print(os, ImageStat.Stat(ImageChops.difference(logo['windows'], logo[os])).mean)
PY
``` Product metadata is not a verified publisher.

| Latest screenshot | Dimensions | SHA-256 |
| --- | --- | --- |
| `visual/linux.png` | 1280 × 800 | `133ea8b80d69ac8fb983c65a9cedcb60eb4c183cdae5a85396e04eead2f3a189` |
| `visual/linux-about.png` | 1280 × 800 | `68e9059d229f67f071223e27da22fd572d4f08a751a1f7a3cb80e9d183d64405` |
| `visual/windows.png` | 1280 × 800 | `86b8acc0cc4910995552e9fe182fbc8938483adc5d681d3d12a697795ee6c2c7` |
| `visual/windows-about.png` | 1280 × 800 | `7ea9bb4f594b8163569801c38931bcfd31eb8f5cc4c20de560205223325d6426` |
| `visual/macos.png` | 1024 × 642 | `01027f28ab775f165284de595fcf1d10cf38259dc5e4c97a92a96d0a2a541ec4` |
| `visual/macos-about.png` | 1024 × 645 | `6c71e4963753ea7008a3e05c1c4cd9334ea00b1c938b7f4019898ec836410cfd` |

Windows deliverable `deliverables/Unreleased/windows/archx-ai-lab.exe`: 21,204,992 bytes, SHA-256 `6eb9d153608a9854a654f74f1a25dbc9cc361df5c3d88f58d4f25ce4630a1979`. Local Python `struct.unpack_from('<II', data, directory+8*4)` on the PE32+ certificate-directory entry returned `(0, 0)`; **the executable is unsigned**, so Windows cannot display a verified publisher. The native icon code was built and screenshot launch succeeded, but titlebar/taskbar icon should also be checked hands-on. The requested genuine 3D cover rotation and animation-specific cross-OS tests have **not** been implemented; Step 1 remains open.

## Previous bounded-cover review (historical)

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
