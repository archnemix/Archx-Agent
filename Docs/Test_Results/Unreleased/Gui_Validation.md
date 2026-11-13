<!-- Purpose: Records current three-OS GUI test commands, outputs, screenshots, visual review, and Windows delivery. -->
# AI Lab launcher validation — collapsible Lab rail

## Current shared navigation revision (2026-11-09)

Source `2c44933`, full GUI run [`43440351034`](https://github.com/archnemix/Archx-Agent/actions/runs/43440351034): Linux and Windows jobs passed `cargo test --locked` (**13 passed; 0 failed** each), `cargo build --release --locked`, expanded Home/Agent/Settings screenshots and three additional compact-state screenshots per OS. Its macOS job **did not run**: runner assignment was cancelled after 15 minutes in queue; this run is therefore **not** a three-OS success. Focused macOS run [`43447873895`](https://github.com/archnemix/Archx-Agent/actions/runs/43447873895) separately passed `cargo test --locked` (**13 passed; 0 failed**), `cargo build --release --locked`, and compact Home/Agent/Settings plus expanded Agent native captures. First focused attempt `43445741356` compiled/tests passed but failed before screenshots due to a shell capture bug; it is not counted as visual evidence. Current per-OS outputs are in `non_visual/{linux,windows,macos}.log`, screenshots only in `visual/`. The Windows log also reports GUI subsystem 2 (no console) and Archnemix product metadata (not a signature).

The shared 220px Lab rail now has **Hide <**; it collapses to an 84px rail with **Open >**, transparent smaller mark and labelled Home/Agent/About/Settings buttons. Its state persists during *this process session* across navigation; no new settings persistence is implied. The separate inner Agent conversation rail is unchanged. CI uses `ARCHX_SNAPSHOT_SIDEBAR=collapsed` with `ARCHX_SNAPSHOT` to capture `visual/{OS}-collapsed.png`, `{OS}-agent-collapsed.png`, and `{OS}-settings-collapsed.png`. A focused state test toggles collapse, navigates Agent → Settings, and reopens without resetting the page. Inspected Windows Home/Agent and macOS Home/Agent compact captures: visible Open control, selected route, typography and reflow stay within their panels. Frozen captures do **not** simulate physical clicks, screen reader use, or user-device interaction.

Latest portable review build: [`deliverables/Unreleased/windows/archx-ai-lab.exe`](../../../deliverables/Unreleased/windows/archx-ai-lab.exe), **19,945,984 bytes**, SHA-256 `041ccf093d4e49c40372515baeb23a6a455002ca56727f488346f7c9b8f4a0bd`. It is **unsigned**, not a verified-publisher build. Provider Settings/API calls are **not in this executable**. They are the next security-critical step and require an honest credential/memory threat model; do not claim connection tests from a mock or inaccessible API.

## Previous evidence (historical; hashes/build sizes below refer to earlier revisions)


## Current Step 2 composer follow-up (2026-11-09)

Source `bfafaf6`, [CI run `43428503990`](https://github.com/archnemix/Archx-Agent/actions/runs/43428503990): sequential Linux, Windows and macOS **all passed**. Each ran `cargo test --locked` (**12 passed; 0 failed**), `cargo build --release --locked`, Home/About, Agent and Settings default/alternate previews, prior frozen animation states, and an Agent UI screenshot with a fixed, nonpersonal **unsent** sentence. Per-OS exact commands/output are in `non_visual/{linux,windows,macos}.log`; all screenshots are in `visual/`. Linux GUI uses `xvfb-run -a env`; Windows uses the `.exe` path. Windows log contains `PASS: Windows GUI subsystem 2 (no console)` and `PASS: Archnemix Windows product metadata (not a digital signature)`.

The composer now accepts text **only into the selected in-memory draft**; Clear empties that draft, while New draft and draft switching retain separate unsent values for this session. It has no Send event or Enter submit handler; nothing is transmitted or stored on disk. The mode selector still changes only the UI preview, not a message's underlying mode; Settings Memory Light/Heavy/Custom choices are likewise non-persistent and do not manage RAM. Focused tests check two drafts retain distinct values, wrong-ID edits/clears do not cross boundaries, and new App construction starts blank.

The screenshot input for each OS (Linux prefixes `xvfb-run -a env`, Windows appends `.exe`) was:

```sh
ARCHX_SNAPSHOT_PAGE=agent ARCHX_SNAPSHOT_DRAFT='Sketch a new idea for a project' ARCHX_SNAPSHOT=Docs/Test_Results/Unreleased/visual/OS-agent-draft.png ./target/release/archx-ai-lab
```

Visual inspection of final Windows and macOS `visual/{os}-agent-draft.png`: unsent text appears within the dark editor, counter is visible, Clear is inside the card, and **SEND UNAVAILABLE / NO MODEL CONNECTED** remains clear without overlap in 1280 × 800 and 1024 × 645 windows. The capture does not prove physical typing or mouse/keyboard accessibility in the user's environment; hands-on review is still needed. The accepted launcher Agent artwork remains unchanged.

Windows portable review binary: [`deliverables/Unreleased/windows/archx-ai-lab.exe`](../../../deliverables/Unreleased/windows/archx-ai-lab.exe), **19,931,648 bytes**, SHA-256 `66b5ac2521762da156c13466601166861b98c44970b101bbe0722333c4fe64e4`. **Unsigned**, not an installer or a verified publisher. Step 2 remains open for user UI acceptance; Step 3 backend decisions are deferred.

## Previous evidence (historical; hashes/build sizes below refer to earlier revisions)


## Current Step 2 UI-only review (2026-11-09)

Source `9038f01`, GitHub Actions run [`43253945098`](https://github.com/archnemix/Archx-Agent/actions/runs/43253945098): sequential **Linux, Windows, macOS all succeeded**, each running `cargo test --locked` (**11 passed; 0 failed**), `cargo build --release --locked`, and native screenshots. Per-OS complete commands/output and native launch errors, if any, are in `non_visual/{linux,windows,macos}.log`; PNGs are in `visual/`. Linux launches under `xvfb-run -a env`; Windows executable uses `.exe`. Windows log also contains `PASS: Windows GUI subsystem 2 (no console)` and `PASS: Archnemix Windows product metadata (not a digital signature)`.

The **shared Lab rail** navigates to Archx Agent and global Settings. Agent has an inner Conversations rail, session-only empty draft navigation, six preview modes, and a disabled charcoal composer with readable placeholder. Settings has Memory Light / Memory Heavy / Custom and the Agent-only custom choice. Neither memory selections nor drafts persist, and none of these controls load/unload an engine, send messages, store conversation history or convert a chat. The user deferred history conversion and edited-message-tree semantics until real chat functionality. Launcher Agent artwork was not revised.

All three OSes captured `visual/{OS}-agent.png`, `{OS}-settings.png`, `{OS}-coding.png` (snapshot-only `ARCHX_SNAPSHOT_PAGE=agent ARCHX_SNAPSHOT_MODE=3`), and `{OS}-custom.png` (snapshot-only `ARCHX_SNAPSHOT_PAGE=settings ARCHX_SNAPSHOT_MEMORY=custom`). Each capture is nonempty. Visually inspected final Windows Coding and Custom plus macOS Coding: selected chips and Custom row are bounded/legible, and the disabled composer no longer shows the bright default disabled style. These captures show initial/alternate states, **not** real pointer or keyboard interaction; state unit tests cover draft selection, mode bounds, Settings-only preview updates and resets on new App construction. No backend, memory allocation measurements, persistence or interaction smoothness is claimed.

Portable unsigned Windows review executable: [`deliverables/Unreleased/windows/archx-ai-lab.exe`](../../../deliverables/Unreleased/windows/archx-ai-lab.exe), **19,922,432 bytes**, SHA-256 `479837025a6f787abfee14d5225a55c05763b17d795fba84cc7ff822afe8580e`. It is **not** an installer or verified-publisher signed build. Step 2 awaits user visual/hands-on approval before Step 3.

## Previous evidence (historical; hashes/build sizes below refer to earlier revisions)


## Current model-workbench revision (2026-11-09)

Source `685b8dc`, CI run [`43239295666`](https://github.com/archnemix/Archx-Agent/actions/runs/43239295666) passed **sequential Linux, Windows and macOS** jobs: each ran `cargo test --locked` (**8 passed; 0 failed**) then `cargo build --release --locked`. Build, test, screenshot and PE outputs reside under `non_visual/{linux,windows,macos}.log`; GUI captures reside only under `visual/`. The Linux job also ran `cargo generate-lockfile` and used `xvfb-run -a env` to launch the native GUI. Windows logged `PASS: Windows GUI subsystem 2 (no console)` and `PASS: Archnemix Windows product metadata (not a digital signature)`. The latest Windows executable is `deliverables/Unreleased/windows/archx-ai-lab.exe`, **19,738,112 bytes**, SHA-256 `b7baa8c187e6a63111c6402b516e0649444ddba6daa13406dc0d44357b43969d`. It is portable and **unsigned**; a verified publisher is not claimed.

The new section reads `EXPLORE / AI workspaces`; Model Training presents **MODEL FORGE** with a large `DESIGN / TRAIN / EVALUATE` sequence, Fine-tuning presents **REFINEMENT STUDIO** with `SELECT / ADAPT / VALIDATE`. Each changing word occupies the tile's primary visual space; the marker and counter follow the same phase. Agent hero/shelf typography remains unchanged. Both model destinations remain labelled `COMING LATER`; the animated phases are conceptual, not live progress. `Docs/design.md` defines fonts, weights, contrast, size and spacing; Linux/Windows use Space Grotesk display roles plus Manrope, while macOS uses Manrope Normal for all roles after two visibly broken font-weight trials. This is a documented rendering fallback, not a claim of cross-platform font identity.

Per OS (`OS=linux|windows|macos`; executable ends `.exe` on Windows), the workflow saved Home and About, Agent frozen phases 1/3, and two frozen hover phases for each model tile:

```sh
cargo test --locked
cargo build --release --locked
ARCHX_SNAPSHOT=Docs/Test_Results/Unreleased/visual/OS.png ./target/release/archx-ai-lab
ARCHX_SNAPSHOT_PAGE=about ARCHX_SNAPSHOT=Docs/Test_Results/Unreleased/visual/OS-about.png ./target/release/archx-ai-lab
for phase in 1 2; do
  ARCHX_SNAPSHOT_HOVER=training ARCHX_SNAPSHOT_PHASE=$phase ARCHX_SNAPSHOT=Docs/Test_Results/Unreleased/visual/OS-training-hover-$phase.png ./target/release/archx-ai-lab
  ARCHX_SNAPSHOT_HOVER=tuning ARCHX_SNAPSHOT_PHASE=$phase ARCHX_SNAPSHOT=Docs/Test_Results/Unreleased/visual/OS-tuning-hover-$phase.png ./target/release/archx-ai-lab
done
```

The workflow also captures Agent phases 1/3 with `ARCHX_SNAPSHOT_AGENT_PHASE=$phase` and checks each capture exists. Local Pillow `ImageChops.difference` confirmed that within the Training and Tuning tile crops **phase 1 differs from phase 2 on all three OSes** (six true differences), beyond the workflow's rest-vs-hover `cmp -s` checks. Visual inspection of final Windows and macOS tuning-phase-2 images shows legible headings, typography and markers inside bounded cards. macOS's smaller 1024 × 645 viewport shows only the upper shelf but is scrollable. Frozen states and timers do **not** verify physical pointer hover or smoothness in an end user's session; hands-on approval remains necessary. In particular, the earlier runs `43227832253`, `43231859324` and `43235460451` **passed tests but had corrupted macOS text**, so they were rejected on visual review. Latest macOS capture is legible again; do not treat success of previous runs as equivalent.

## Previous evidence (historical; hashes/build sizes below refer to earlier revisions)


## Agent typography / transparent sidebar revision (2026-11-09)

Source commit `28b880c`, Actions run `43200600325` passed sequential Linux, Windows, macOS. The user rejected the old Agent sculpture image and large black-backed sidebar logo. Both Agent hero and shelf now render native, six-mode **typographic artwork** instead of a generated image, cycling a mode label and matching segment highlight every 1500ms on Home (paused on About). Training/Fine-tuning retain hover-only type motion; all three destinations remain unavailable. The supplied Archnemix logo now uses a 116 × 116 transparent crop on the rail, while the native window/PE icon assets remain unchanged. No 3D assets or functioning Agent modes are claimed.

Each OS ran `cargo test --locked` (`6 passed; 0 failed`), `cargo build --release --locked`, Home and About screenshots, the prior three text-hover-phase captures, and two new Agent phase captures. Per OS (`OS=linux|windows|macos`, Linux wraps each executable with `xvfb-run -a env`; Windows adds `.exe`):

```sh
for phase in 1 3; do
  ARCHX_SNAPSHOT_AGENT_PHASE=$phase ARCHX_SNAPSHOT=Docs/Test_Results/Unreleased/visual/OS-agent-phase-$phase.png ./target/release/archx-ai-lab
  test -s Docs/Test_Results/Unreleased/visual/OS-agent-phase-$phase.png
  if cmp -s Docs/Test_Results/Unreleased/visual/OS.png Docs/Test_Results/Unreleased/visual/OS-agent-phase-$phase.png; then exit 1; fi
done
```

Observed logs include `PASS: <OS> Agent phase 1 differs from rest`, `PASS: <OS> Agent phase 3 differs from rest`, and prior Training/Tuning hover-state differences on each OS. Windows also logged `PASS: Windows GUI subsystem 2 (no console)` and `PASS: Archnemix Windows product metadata (not a digital signature)`. Reviewed Home and both Agent phases on Windows and Home/phase 3 on macOS plus Home on Linux: typography remains inside its panels and mode/marker move consistently. The macOS runner's smaller viewport shows only the top of the shelf, which remains scrollable. Comparing files and reviewing frozen frames does **not** measure live animation smoothness or prove a user saw every frame. The logo source crop's corner alpha is zero; on each OS, screenshot `(23,23)` matches the rail `(210,35)` at RGB `(13,13,13)`, showing the black backing has been removed from the sidebar mark.

| Agent phase output | Dimensions | SHA-256 |
| --- | --- | --- |
| `visual/linux-agent-phase-1.png` | 1280 × 800 | `eb1e4c78a83e28e33acec9dd945b4f65df2e0138ad6434d71df0f44c7bb24457` |
| `visual/linux-agent-phase-3.png` | 1280 × 800 | `bb12aa885781b11d70e0fb5742a40c22c77dead76c49386da8b65141fb4e29b6` |
| `visual/windows-agent-phase-1.png` | 1280 × 800 | `ba1bdc2c5a94d8f00600928eb2c87c855a6507916943485e67fcb49502029430` |
| `visual/windows-agent-phase-3.png` | 1280 × 800 | `2113e77b528d8136d9eadeabe6e37cb35827ea3800b9f7467dd466b76d52f834` |
| `visual/macos-agent-phase-1.png` | 1024 × 645 | `d35168d0667bbb9e90070007e3be0219e35548584c670be97ad7308feb3459bb` |
| `visual/macos-agent-phase-3.png` | 1024 × 645 | `a9aa1d97fceefa4b1bfe4d8eff884197d6f9394df2d7970591552ffb78bdeef9` |

Windows review executable: `deliverables/Unreleased/windows/archx-ai-lab.exe` (19,562,496 bytes), SHA-256 `0fcd4df555324ee04928c4945161e5e7f96462945e0cc9acb4cebe36343ccff7`. It remains unsigned and is not claimed to be a verified publisher build. User hands-on acceptance is still pending; Step 2 is blocked.

## Three-app text-hover follow-up (2026-11-09)

Source commit `57694f0`, Actions run `43186966425` (passed sequential Linux, Windows, macOS). The user revised scope: only Archx Agent should eventually receive an approved animated model; this run **does not** include that model. The temporary Agent hero/tile art remains unchanged. The current shelf and sidebar show only Agent, Model Training and Fine-tuning; no Model Monitor destination remains. Training and Fine-tuning now have native typography panels with a three-word, hover-only highlight cycle instead of JPEG artwork. Both still say `COMING LATER`; animation represents a concept, not operational progress.

Each runner ran `cargo test --locked` (observed `5 passed; 0 failed`), `cargo build --release --locked`, and normal Home/About screenshot commands documented below. In addition, per OS (replace `OS` with `linux`, `windows`, or `macos`; Linux wraps each run with `xvfb-run -a env`):

```sh
for phase in 1 2; do
  ARCHX_SNAPSHOT_HOVER=training ARCHX_SNAPSHOT_PHASE=$phase ARCHX_SNAPSHOT=Docs/Test_Results/Unreleased/visual/OS-training-hover-$phase.png ./target/release/archx-ai-lab
  test -s Docs/Test_Results/Unreleased/visual/OS-training-hover-$phase.png
done
ARCHX_SNAPSHOT_HOVER=tuning ARCHX_SNAPSHOT_PHASE=1 ARCHX_SNAPSHOT=Docs/Test_Results/Unreleased/visual/OS-tuning-hover-1.png ./target/release/archx-ai-lab
test -s Docs/Test_Results/Unreleased/visual/OS-tuning-hover-1.png
```

Windows uses `./target/release/archx-ai-lab.exe`. The workflow also compares each phase-1 file to its Home rest file using `cmp -s`; all six OS/card comparisons logged `PASS: ... hover phase differs from rest`. This file comparison alone is not a pixel-level animation test; macOS's 1024-wide desktop even varied by three pixels of height between launches. The focused state test exercises pointer-entry/exit messages and timer-driven phase progression. **Visual inspection** of Windows rest/training/tuning, Linux training phase 2 and macOS training phase 1 confirms the highlight visibly moves only on the intended text card and is legible; the compact macOS viewport cuts off below the top of the shelf but remains scrollable. This is not proof of physical mouse-pointer movement or animation smoothness on all user devices. No 3D Agent animation, settings modes or verified Windows publisher is claimed.

Windows also logged `PASS: Windows GUI subsystem 2 (no console)` and `PASS: Archnemix Windows product metadata (not a digital signature)`. Refreshed portable unsigned build: `deliverables/Unreleased/windows/archx-ai-lab.exe`, 21,051,392 bytes, SHA-256 `5f37821710fc11faf4d73b7996fe9e6a1da0dc4d1b1e3a242535bae462b6c0d4`. Full logs and five PNGs per OS (Home, About, Training phases 1/2, Tuning phase 1) are under `non_visual/` and `visual/`. Step 1 remains open pending the Agent asset and user review.

## Brand follow-up (2026-11-09)

Source commit `76db961`, Actions run `43031034141` (passed sequential Linux, Windows and macOS). Each job ran `cargo test --locked` (4 passed, 0 failed), `cargo build --release --locked`, and the Home/About screenshot commands listed in the earlier section below. Windows also ran the PE GUI-subsystem check (output `PASS: Windows GUI subsystem 2 (no console)`) and this metadata check:

```sh
powershell.exe -NoProfile -Command '$info=(Get-Item "target/release/archx-ai-lab.exe").VersionInfo; if ($info.CompanyName -ne "Archnemix" -or $info.ProductName -ne "Archx AI Lab") { throw "Incorrect PE product metadata" }; Write-Output "PASS: Archnemix Windows product metadata (not a digital signature)"'
```

Observed `PASS: Archnemix Windows product metadata (not a digital signature)` in `non_visual/windows.log`. The exact test and build outputs are in `non_visual/{linux,windows,macos}.log`. The latest Home/About PNGs were captured successfully on all three OSes. Visual inspection of Home and Windows About: provided black-backed logo replaces the generic letter badge; `LOCAL PREVIEW` and `PREVIEW 01` are gone; no tile-cover overlap at 1280 × 800 Windows/Linux; macOS still needs scrolling to show tile labels. These screenshots show client content only: they do **not** prove native titlebar/taskbar icon fidelity or hover animation. Command `/home/user/.venv/bin/python` (Pillow) with `ImageChops.difference`/`ImageStat.Stat` on `visual/{windows,linux,macos}.png` 160 × 160 logo crops at `(23,23)` found mean absolute per-channel RGB error of `4.283` for Windows versus Linux and `0.022` for Windows versus macOS; the logo geometry and layout are consistent, but GPU/font sampling differs, so pixel-identical output is not claimed. Exact comparison input/code:

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

Source input: commit `731206d`, locked dependencies in `Cargo.lock`, four embedded 800 × 480 shelf covers plus original Agent feature art. GitHub Actions run `43020392009` on Linux, Windows, macOS sequentially. No model, user data, secrets, backend, or network UI input was used. The exact command output is in `non_visual/linux.log`, `non_visual/windows.log`, and `non_visual/macos.log`.

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

Prior logs/results remain inspectable in Git history: `eb65c61` (Linux compiler failure), `e983642` (missing X11 runtime), `ea2d690` (first review build), `f11f4cf` (console fix), `40082d9` (first app launcher), and `8478e7f` (failed visual inspection with new covers). Current full runner output is the latest `non_visual/*.log` files.

## 2026-11-09 — OS vault foundation compilation (not user-facing)

Source commit `ce15701`, CI run `43462052311`: `cargo test` and release GUI build succeeded on Linux, Windows and macOS (15 passed, 0 failed on each, including two synthetic `credentials` tests). Native GUI screenshot capture and evidence commits succeeded in all three jobs. The repository-hosted Windows executable was refreshed at `deliverables/Unreleased/windows/archx-ai-lab.exe` (SHA-256 `dbff85569379bbc746a858ec9bd84dd49a1a35ff51ce5d416fa23aefb49904b0`, **unsigned**). Logs: `Docs/Test_Results/Unreleased/non_visual/{linux,windows,macos}.log`. This run establishes cross-platform **compilation**, not that an actual OS vault can save/retrieve credentials, a Settings key UI exists, or any provider connection works.

## 2026-11-09 — plain Chat / provider Settings experiment, first green CI

Source `af8fc4d`, run `43477504746`: `cargo test --locked` reported 20 passed / 0 failed and `cargo build --release --locked` succeeded on Linux, Windows and macOS. Native captures include Connections/Models/Agent and both rail states; I inspected the Windows and macOS Settings surfaces. No real OS keychain, key entry, reveal, provider call or click journey was executed by synthetic CI. Windows executable refreshed at `deliverables/Unreleased/windows/archx-ai-lab.exe`, SHA-256 `ac541a6e10e0c181c7f462e47f0cdd0e42d11c0de95527abc419a4eaff098454`, unsigned. Subsequent visual/security corrections to disabled states, Hide and per-window key serialization require fresh CI and screenshots before claims.
