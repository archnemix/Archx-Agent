<!-- Purpose: Records the exact documentation validation command, inputs, and observed output. -->
# Documentation validation

## 2026-11-09: documentation setup

Input: the 18 repository files present at validation, including `Docs/Files_Info.json`, `Docs/Research.json`, and all Markdown files. No application code or runtime test input exists yet.

Command (run from repository root):

```sh
python -c 'import json,pathlib; root=pathlib.Path("."); files={p.as_posix() for p in root.rglob("*") if p.is_file() and ".git" not in p.parts}; manifest=json.loads((root/"Docs/Files_Info.json").read_text()); research=json.loads((root/"Docs/Research.json").read_text()); assert set(manifest["files"])==files,(sorted(files-set(manifest["files"])),sorted(set(manifest["files"])-files)); assert all(p.read_text().startswith("<!-- Purpose:") for p in root.rglob("*.md") if ".git" not in p.parts); assert all((d/"README.md").is_file() for d in [root,*root.rglob("*")] if d.is_dir() and ".git" not in d.parts); assert list(manifest)[0]==list(research)[0]=="_description"; print(f"PASS: {len(files)} inventoried files; Markdown purpose comments, folder READMEs, and JSON validated")'
git diff --check
```

Observed output:

```text
PASS: 18 inventoried files; Markdown purpose comments, folder READMEs, and JSON validated
PASS: git diff --check
```

Both commands exited successfully. Documentation-only validation ran locally; no application tests or cross-platform runner results are claimed.

## 2026-11-09: interface discussion documentation update

Input: `Docs/Plan/Architecture.md` and `Docs/Thinking.md` after documenting the provisional interface direction.

Commands (run from repository root):

```sh
python -c 'from pathlib import Path; files=[Path("Docs/Plan/Architecture.md"),Path("Docs/Thinking.md")]; assert all(p.read_text().startswith("<!-- Purpose:") for p in files); print("PASS: 2 updated Markdown files have purpose headers")'
git diff --check
```

Observed output:

```text
PASS: 2 updated Markdown files have purpose headers
PASS: git diff --check
```

Both commands exited successfully locally; no application or cross-platform tests were run.

## 2026-11-09: Iced framework decision documentation update

Input: `Docs/Plan/Architecture.md`, `Docs/Technical.md`, `Docs/Thinking.md`, and `Docs/Research.json` after recording the framework selection and source checks.

Commands (run from repository root):

```sh
python -c 'import json; from pathlib import Path; paths=[Path("Docs/Plan/Architecture.md"),Path("Docs/Technical.md"),Path("Docs/Thinking.md")]; assert all(p.read_text().startswith("<!-- Purpose:") for p in paths); topics=json.loads(Path("Docs/Research.json").read_text())["topics"]; assert len(topics)==4 and all(t["summary"] and t["url"].startswith("https://") for t in topics.values()); print("PASS: 3 Markdown headers and 4 research entries validated")'
git diff --check
```

Observed output:

```text
PASS: 3 Markdown headers and 4 research entries validated
PASS: git diff --check
```

Both commands exited successfully locally; no application or cross-platform tests were run.

## 2026-11-09: cross-platform UI concern documentation update

Input: `Docs/Plan/Architecture.md` and `Docs/Thinking.md` after clarifying the webview-rendering concern.

Commands (run from repository root):

```sh
python -c 'from pathlib import Path; files=[Path("Docs/Plan/Architecture.md"),Path("Docs/Thinking.md")]; assert all(p.read_text().startswith("<!-- Purpose:") for p in files); print("PASS: 2 updated Markdown purpose headers")'
git diff --check
```

Observed output:

```text
PASS: 2 updated Markdown purpose headers
PASS: git diff --check
```

Both commands exited successfully locally; no application or cross-platform tests were run.

## 2026-11-09: superapp scope and rules documentation update

Input: all 19 repository files, including the new `Docs/Logic.md`, the revised rules, architecture, roadmap, technical overview, file inventory, and work log. Documentation only.

Commands (run from repository root):

```sh
python -c 'import json,pathlib; r=pathlib.Path("."); files={p.as_posix() for p in r.rglob("*") if p.is_file() and ".git" not in p.parts}; inventory=json.loads((r/"Docs/Files_Info.json").read_text()); json.loads((r/"Docs/Research.json").read_text()); assert files==set(inventory["files"]),(files-set(inventory["files"]),set(inventory["files"])-files); assert all(p.read_text().startswith("<!-- Purpose:") for p in r.rglob("*.md") if ".git" not in p.parts); assert all((d/"README.md").is_file() for d in [r,*r.rglob("*")] if d.is_dir() and ".git" not in d.parts); print(f"PASS: {len(files)} files inventoried; JSON, Markdown headers, folder READMEs valid")'
git diff --check
```

Observed output:

```text
PASS: 19 files inventoried; JSON, Markdown headers, folder READMEs valid
PASS: git diff --check
```

Both commands exited successfully locally. No application tests or Windows/macOS/Linux runner tests were run: there is still no application code.

## 2026-11-09: sequenced roadmap and general task agent

Input: all 19 repository files; changed `Docs/Roadmap.md`, `Docs/Plan/Architecture.md`, `Docs/Change.md`, and `Docs/Thinking.md`. Documentation only.

Commands (run from repository root):

```sh
python -c 'import json,pathlib; r=pathlib.Path("."); files={p.as_posix() for p in r.rglob("*") if p.is_file() and ".git" not in p.parts}; inventory=json.loads((r/"Docs/Files_Info.json").read_text()); assert files==set(inventory["files"]); paths=[r/p for p in ("Docs/Roadmap.md","Docs/Plan/Architecture.md","Docs/Change.md","Docs/Thinking.md")]; assert all(p.read_text().startswith("<!-- Purpose:") for p in paths); print(f"PASS: {len(files)} files inventoried; 4 updated Markdown purpose headers valid")'
git diff --check
```

Observed output:

```text
PASS: 19 files inventoried; 4 updated Markdown purpose headers valid
PASS: git diff --check
```

Both commands exited successfully locally. No GUI or cross-platform tests exist yet.

## 2026-11-09: staged roadmap decision gates

Input: `Docs/Roadmap.md` after narrowing Step 0 to the home-screen slice and moving model/tool decisions to the steps that need them.

Commands (run from repository root):

```sh
python -c 'from pathlib import Path; p=Path("Docs/Roadmap.md"); t=p.read_text(); assert t.startswith("<!-- Purpose:") and "Do **not** block the home screen" in t and "First agree on initial model source" in t; print("PASS: roadmap header and staged decision gates valid")'
git diff --check
```

Observed output:

```text
PASS: roadmap header and staged decision gates valid
PASS: git diff --check
```

Both commands exited successfully locally; no application tests were run.

## 2026-11-09: AI Lab design and initial GUI source validation

Input: all 40 repository source/documentation/assets files, excluding `.git`. This validates inventory coverage and documentation structure, **not** compilation or GUI behavior. `assets/fonts/Manrope.ttf` is binary; `assets/fonts/OFL.txt` is an unmodified license.

Commands (run from repository root):

```sh
python -c 'import json,pathlib; r=pathlib.Path("."); files={p.as_posix() for p in r.rglob("*") if p.is_file() and ".git" not in p.parts}; index=json.loads((r/"Docs/Files_Info.json").read_text())["files"]; json.loads((r/"Docs/Research.json").read_text()); assert files==set(index),(files-set(index),set(index)-files); assert all(p.read_text().startswith("<!-- Purpose:") for p in r.rglob("*.md") if ".git" not in p.parts); assert all((d/"README.md").is_file() for d in [r,*r.rglob("*")] if d.is_dir() and ".git" not in d.parts); print(f"PASS: {len(files)} inventoried files, valid JSON, Markdown headers, folder READMEs")'
git diff --check
```

Observed output:

```text
PASS: 40 inventoried files, valid JSON, Markdown headers, folder READMEs
PASS: git diff --check
```

Both commands exited successfully locally. No Rust tests or cross-platform build results exist yet. Attempting to install PyYAML in the system-managed Python environment failed with an externally-managed-environment error; no workflow parser result is claimed.

## 2026-11-09: first CI compilation correction

Inputs: all 42 repository files after Linux CI committed `Cargo.lock` and `Docs/Test_Results/Unreleased/build/linux.log`; the previous Linux compiler output reports missing `Clone` for UI messages and a theme callback lifetime. No Windows/macOS result exists yet.

Commands (from repository root):

```sh
python -c 'import json,pathlib; r=pathlib.Path("."); files={p.as_posix() for p in r.rglob("*") if p.is_file() and ".git" not in p.parts}; index=json.loads((r/"Docs/Files_Info.json").read_text())["files"]; assert files==set(index),(files-set(index),set(index)-files); print(f"PASS: {len(files)} files inventoried after Linux CI failure")'
git diff --check
```

Observed output:

```text
PASS: 42 files inventoried after Linux CI failure
PASS: git diff --check
```

Both documentation checks exited successfully. CI compilation was **failed**; its exact compiler output is retained in `build/linux.log` from the first run, not disguised as a passing test.

## 2026-11-09: Linux GUI runtime dependency correction

Input: `.github/workflows/gui.yml` and `Docs/Thinking.md` after Linux CI compiled/tested successfully but screenshot launch failed for missing `libxkbcommon-x11.so`. Full runtime output is retained in `build/linux.log` for that run.

Command (repository root):

```sh
git diff --check && echo 'PASS: workflow dependency and work log diff check'
```

Observed output:

```text
PASS: workflow dependency and work log diff check
```

The documentation check exited successfully; GUI screenshot validation still required a rerun.

## 2026-11-09: successful three-OS GUI review documentation

Input: all 49 repository files, including CI-generated logs, screenshots, Windows executable, and the newly written `Docs/Test_Results/Unreleased/Gui_Validation.md`. This is documentation validation, not a substitute for the runner results.

Commands (repository root):

```sh
python -c 'import json,pathlib; r=pathlib.Path("."); files={p.as_posix() for p in r.rglob("*") if p.is_file() and ".git" not in p.parts}; index=json.loads((r/"Docs/Files_Info.json").read_text())["files"]; assert files==set(index),(sorted(files-set(index)),sorted(set(index)-files)); assert all(p.read_text().startswith("<!-- Purpose:") for p in r.rglob("*.md") if ".git" not in p.parts); print(f"PASS: {len(files)} files inventoried; Markdown purpose headers valid")'
git diff --check
```

Observed output:

```text
PASS: 49 files inventoried; Markdown purpose headers valid
PASS: git diff --check
```

Both commands exited successfully. The three-OS test/build/screenshot commands and outcomes are recorded separately in `Gui_Validation.md` and `build/*.log`.

## 2026-11-09: Windows console fix and launcher redesign (pre-CI)

Input: 51 repository files, including changed Rust source, workflow, generated `assets/agent-cover.png`, design documents, and the **previous** Windows binary. No local Rust toolchain is installed; new compilation requires CI.

Commands (repository root) and observed outputs:

```sh
python - <<'PY'
import pathlib, struct
binary = pathlib.Path('deliverables/Unreleased/windows/archx-ai-lab.exe').read_bytes()
pe = struct.unpack_from('<I', binary, 0x3c)[0]
subsystem = struct.unpack_from('<H', binary, pe + 92)[0]
print(f'Previous Windows PE subsystem: {subsystem} (3=console, 2=GUI)')
PY
# Previous Windows PE subsystem: 3 (3=console, 2=GUI)

python -m venv /home/user/.venv
/home/user/.venv/bin/pip install -q pyyaml
/home/user/.venv/bin/python - <<'PY'
import yaml
from pathlib import Path
workflow=yaml.safe_load(Path('.github/workflows/gui.yml').read_text())
print('PASS: workflow YAML parsed;',len(workflow['jobs']),'OS jobs')
PY
# PASS: workflow YAML parsed; 3 OS jobs

python -c 'import json,pathlib; r=pathlib.Path("."); files={p.as_posix() for p in r.rglob("*") if p.is_file() and ".git" not in p.parts}; index=json.loads((r/"Docs/Files_Info.json").read_text())["files"]; assert files==set(index),(sorted(files-set(index)),sorted(set(index)-files)); assert all(p.read_text().startswith("<!-- Purpose:") for p in r.rglob("*.md") if ".git" not in p.parts); assert (r/"assets/agent-cover.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n"); print(f"PASS: {len(files)} files inventoried; Markdown headers and cover PNG valid")'
git diff --check && echo 'PASS: git diff --check'
# PASS: 51 files inventoried; Markdown headers and cover PNG valid
# PASS: git diff --check
```

All commands above exited successfully. An earlier exploratory one-liner for PE inspection used an invalid constructed `struct` format and exited with `struct.error: bad char in struct format`; it was replaced by the explicit `<H` command above. That exploratory failure did not test the application. No new GUI build is claimed yet.

## 2026-11-09: visual-review layout refinement (pre-CI)

Input: 51 repository files; modified `src/home.rs`, `src/app_tile.rs`, `Docs/design.md`, and `Docs/Thinking.md` after inspecting the first redesigned screenshots. These checks do not verify rendering.

Commands (repository root):

```sh
python -c 'import json,pathlib; r=pathlib.Path("."); files={p.as_posix() for p in r.rglob("*") if p.is_file() and ".git" not in p.parts}; index=json.loads((r/"Docs/Files_Info.json").read_text())["files"]; assert files==set(index); assert (r/"src/home.rs").read_text().startswith("//! Purpose:") and (r/"src/app_tile.rs").read_text().startswith("//! Purpose:"); print(f"PASS: {len(files)} files inventoried; edited source headers valid")'
git diff --check
```

Observed output:

```text
PASS: 51 files inventoried; edited source headers valid
PASS: git diff --check
```

Both checks exited successfully locally. New cross-platform screenshots and GUI tests still need CI.

## 2026-11-09: final launcher correction documentation review

Input: all 51 repository files after CI run `42992545976` and updates to the GUI evidence, roadmap, technical notes, Windows build note, README, and work log. The application tests and screenshot outputs are recorded in `Gui_Validation.md` and per-OS `build/*.log`.

Commands (repository root):

```sh
python -c 'import json,pathlib; r=pathlib.Path("."); files={p.as_posix() for p in r.rglob("*") if p.is_file() and ".git" not in p.parts}; index=json.loads((r/"Docs/Files_Info.json").read_text())["files"]; assert files==set(index); assert all(p.read_text().startswith("<!-- Purpose:") for p in r.rglob("*.md") if ".git" not in p.parts); print(f"PASS: {len(files)} inventoried files and Markdown purpose headers")'
git diff --check
```

Observed output:

```text
PASS: 51 inventoried files and Markdown purpose headers
PASS: git diff --check
```

Both documentation checks exited successfully locally. The actual Windows hands-on review is still pending the user.

## 2026-11-09: reference-led launcher revision (pre-CI)

Input: 54 repository files, including three new monochrome JPEG cover assets, revised Iced navigation style, Home/About capture workflow, and updated design records. No local Rust toolchain; screenshots and compilation require CI.

Commands (repository root):

```sh
python -m venv /home/user/.venv
/home/user/.venv/bin/pip install -q pyyaml
/home/user/.venv/bin/python - <<'PY'
import yaml
from pathlib import Path
flow=yaml.safe_load(Path('.github/workflows/gui.yml').read_text())
assert len(flow['jobs'])==3
print('PASS: workflow YAML parsed; 3 OS jobs')
PY
python -c 'import json,pathlib; r=pathlib.Path("."); files={p.as_posix() for p in r.rglob("*") if p.is_file() and ".git" not in p.parts}; index=json.loads((r/"Docs/Files_Info.json").read_text())["files"]; assert files==set(index),(files-set(index),set(index)-files); assert all(p.read_text().startswith("<!-- Purpose:") for p in r.rglob("*.md") if ".git" not in p.parts); print(f"PASS: {len(files)} inventoried files and Markdown headers")'
git diff --check
```

Observed output:

```text
PASS: workflow YAML parsed; 3 OS jobs
PASS: 54 inventoried files and Markdown headers
```

`git diff --check` exited successfully with no output. No Rust/GUI test result is claimed at this point.

## 2026-11-09: bounded app-cover correction (pre-CI)

Inputs: all 58 repository files, including the previous CI Home/About captures, new cropped Agent tile and resized JPEG covers. A first inventory check failed because the three CI-generated About screenshots were not yet indexed: `AssertionError: (['Docs/Test_Results/Unreleased/visual/linux-about.png', 'Docs/Test_Results/Unreleased/visual/macos-about.png', 'Docs/Test_Results/Unreleased/visual/windows-about.png'], [])`. Indexed them before rerunning. No new rendering pass is claimed yet.

Commands (repository root):

```sh
python -c 'import json,pathlib; r=pathlib.Path("."); files={p.as_posix() for p in r.rglob("*") if p.is_file() and ".git" not in p.parts}; index=json.loads((r/"Docs/Files_Info.json").read_text())["files"]; assert files==set(index),(sorted(files-set(index)),sorted(set(index)-files)); assert (r/"src/app_tile.rs").read_text().startswith("//! Purpose:"); print(f"PASS: {len(files)} inventoried files and edited source header")'
git diff --check
```

Observed output:

```text
PASS: 58 inventoried files and edited source header
```

`git diff --check` exited successfully with no output. The first command had previously exited with the missing-About-screenshot assertion described above; after the manifest correction both checks exited successfully.

## 2026-11-09: post-run review records

After run `43020392009`, checked the evidence inventory with:

```sh
python -c 'import json,pathlib; r=pathlib.Path("."); files={p.as_posix() for p in r.rglob("*") if p.is_file() and ".git" not in p.parts}; index=json.loads((r/"Docs/Files_Info.json").read_text())["files"]; assert files==set(index),(sorted(files-set(index)),sorted(set(index)-files)); print(f"PASS: {len(files)} inventoried files")'
git diff --check
```

Observed `PASS: 58 inventoried files`; `git diff --check` exited successfully without output. Render-specific findings and the Windows executable digest are in `Gui_Validation.md`.

## 2026-11-09: brand implementation pre-CI

Input: the user-supplied transparent logo, derived PNG/ICO assets, source, build script, documentation, and current three-OS evidence. Commands:

```sh
python -c 'import json,pathlib; r=pathlib.Path("."); files={p.as_posix() for p in r.rglob("*") if p.is_file() and ".git" not in p.parts}; index=json.loads((r/"Docs/Files_Info.json").read_text())["files"]; assert files==set(index),(sorted(files-set(index)),sorted(set(index)-files)); print(f"PASS: {len(files)} inventoried files")'
git diff --check
```

Observed: `PASS: 64 inventoried files`; diff check had no output and exited successfully. Code compilation, icon in Windows chrome, and cross-platform screenshots still need CI; no animation or Authenticode signature is claimed.

## 2026-11-09: post-brand evidence/plan alignment

Commands: `python -c 'import json,pathlib; r=pathlib.Path("."); files={p.as_posix() for p in r.rglob("*") if p.is_file() and ".git" not in p.parts}; index=json.loads((r/"Docs/Files_Info.json").read_text())["files"]; assert files==set(index),(sorted(files-set(index)),sorted(set(index)-files)); print(f"PASS: {len(files)} inventoried files")'` and `git diff --check`. Input: current 64 tracked/file-inventory entries, latest run `43031034141` logs and screenshots, signing/animation limitations. Observed `PASS: 64 inventoried files`; diff check exited successfully without output.

## 2026-11-09: rough-ideas parking lot (documentation only)

Input: `Docs/Rough_Ideas.md`, `Docs/README.md`, and `Docs/Files_Info.json`. Command from repository root:

```sh
python - <<'PY'
import json
from pathlib import Path
root=Path('.'); files={p.as_posix() for p in root.rglob('*') if p.is_file() and '.git' not in p.parts}; indexed=set(json.loads((root/'Docs/Files_Info.json').read_text())['files']); assert files==indexed,(sorted(files-indexed),sorted(indexed-files)); text=(root/'Docs/Rough_Ideas.md').read_text(); assert text.startswith('<!-- Purpose:') and 'Status:** Parked' in text; assert '[Rough ideas](Rough_Ideas.md)' in (root/'Docs/README.md').read_text(); print(f'PASS: {len(files)} inventoried files; rough idea and docs link validated')
PY
git diff --check
```

Observed `PASS: 65 inventoried files; rough idea and docs link validated`. `git diff --check` exited 0 with no output. No GUI code or roadmap milestone changed, so no GUI runner was invoked.

## 2026-11-09: three-card text motion pre-CI

Inputs: new three-card source, three-OS workflow, updated file inventory (62 files). Commands and observed outputs:

```sh
python - <<'PY'
import json
from pathlib import Path
root=Path('.'); files={p.as_posix() for p in root.rglob('*') if p.is_file() and '.git' not in p.parts}; indexed=set(json.loads((root/'Docs/Files_Info.json').read_text())['files']); print(len(files),len(indexed),'missing',sorted(files-indexed),'stale',sorted(indexed-files)); assert files==indexed
PY
# output: 62 62 missing [] stale []
/home/user/.venv/bin/python - <<'PY'
import yaml
with open('.github/workflows/gui.yml') as file: workflow=yaml.safe_load(file)
assert set(workflow['jobs'])=={'linux','windows','macos'}
for os in ('linux','windows','macos'):
    script=next(step['run'] for step in workflow['jobs'][os]['steps'] if step.get('name')=='Build, test, and screenshot')
    assert f'{os}-training-hover-$phase.png' in script
    assert f'{os}-tuning-hover-1.png' in script
print('PASS: three-OS workflow YAML and phase snapshot inputs')
PY
# output: PASS: three-OS workflow YAML and phase snapshot inputs
git diff --check
# output: none; exit 0
```

Rust toolchain remains unavailable locally. Compilation, focused tests, release snapshots, and phase-difference checks still need the triggered three-OS CI run; no runtime or user hover success is claimed by this precheck.

## 2026-11-09: text-motion post-CI inventory

CI generated nine frozen-phase PNGs across Linux, Windows and macOS. Added each to `Docs/Files_Info.json`. From repository root:

```sh
python - <<'PY'
import json
from pathlib import Path
r=Path('.'); files={p.as_posix() for p in r.rglob('*') if p.is_file() and '.git' not in p.parts}; indexed=set(json.loads((r/'Docs/Files_Info.json').read_text())['files']); assert files==indexed,(sorted(files-indexed),sorted(indexed-files)); print('PASS:',len(files),'files inventoried')
PY
# output: PASS: 71 files inventoried
git diff --check
# output: none; exit 0
```

## 2026-11-09: Agent type and transparent sidebar pre-CI

Inputs: cropped alpha logo, Agent visual source and existing three-app shell, updated CI workflow. Commands run in repository root:

```sh
/home/user/.venv/bin/python - <<'PY'
import yaml
with open('.github/workflows/gui.yml') as fp: jobs=yaml.safe_load(fp)['jobs']
for os in ('linux','windows','macos'):
    run=next(step['run'] for step in jobs[os]['steps'] if step.get('name')=='Build, test, and screenshot')
    assert f'{os}-agent-phase-$phase.png' in run
    assert f'{os}-training-hover-$phase.png' in run
print('PASS: three-OS Agent and model phase capture YAML')
PY
python - <<'PY'
import json
from pathlib import Path
r=Path('.'); files={p.as_posix() for p in r.rglob('*') if p.is_file() and '.git' not in p.parts}; index=set(json.loads((r/'Docs/Files_Info.json').read_text())['files']); assert files==index; assert (r/'src/agent_visual.rs').read_text().startswith('//! Purpose:'); print('PASS:',len(files),'inventoried files and new Rust purpose header')
PY
git diff --check
```

Observed `PASS: three-OS Agent and model phase capture YAML` and `PASS: 70 inventoried files and new Rust purpose header`; `git diff --check` exited successfully with no output. CI compile/test, screenshots and Windows build are **not** yet claimed by this check.

## 2026-11-09: Agent-type post-CI inventory

The CI run added six Agent-phase screenshots. Exact inventory check from the repository root:

```sh
python - <<'PY'
import json
from pathlib import Path
r=Path('.'); files={p.as_posix() for p in r.rglob('*') if p.is_file() and '.git' not in p.parts}; index=set(json.loads((r/'Docs/Files_Info.json').read_text())['files']); assert files==index,(sorted(files-index),sorted(index-files)); print('PASS:',len(files),'inventoried files')
PY
# observed: PASS: 76 inventoried files
git diff --check
# observed: no output; exit 0
```

## 2026-11-09: workbench/font revision pre-CI

Inputs: Space Grotesk binary and unmodified OFL, design tokens, workbench panels, three-OS workflow split between `visual/` and `non_visual/`. Exact checks from repository root:

```sh
/home/user/.venv/bin/python - <<'PY'
import yaml
from pathlib import Path
jobs=yaml.safe_load(Path('.github/workflows/gui.yml').read_text())['jobs']; assert set(jobs)=={'linux','windows','macos'}
for os in jobs:
    script=next(step['run'] for step in jobs[os]['steps'] if step.get('name')=='Build, test, and screenshot')
    assert f'non_visual/{os}.log' in script and f'visual/{os}-tuning-hover-$phase.png' in script
print('PASS: YAML and all three OS visual/non-visual paths')
PY
python - <<'PY'
import json
from pathlib import Path
r=Path('.'); files={p.as_posix() for p in r.rglob('*') if p.is_file() and '.git' not in p.parts}; index=set(json.loads((r/'Docs/Files_Info.json').read_text())['files']); assert files==index,(sorted(files-index),sorted(index-files)); assert 'SIL OPEN FONT LICENSE' in (r/'assets/fonts/SpaceGrotesk-OFL.txt').read_text(); print('PASS:',len(files),'files inventoried; font license present')
PY
git diff --check
```

Observed: `PASS: YAML and all three OS visual/non-visual paths`; `PASS: 78 files inventoried; font license present`; diff check exited 0 without output. These are documentation/config checks, not a claim that the new font renders properly or animation works before CI.

## 2026-11-09: failed first workbench compile and correction

Run `43227366516`, source `111b142`, failed Linux `cargo test --locked` with `error[E0277]: the trait bound iced::Pixels: From<u16> is not satisfied` in `src/app_tile.rs` and `src/home.rs`, and `iced::Length: From<u16>` for spacing. Exact stdout/stderr is preserved in `non_visual/linux.log` at this run's evidence commit `190d02c`; Windows/macOS jobs were skipped. After verifying Iced's `Pixels`, `Length` and `Padding` conversions, shared type/spacing constants were corrected to `f32`. Re-run is required before visual or cross-OS success claims.
