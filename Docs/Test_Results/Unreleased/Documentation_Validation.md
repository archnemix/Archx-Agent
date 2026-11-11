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
