#!/usr/bin/env bash
# M39: exercise the shipped CLI, inspect actual exported bytes, then break the evidence.
# No real Blender install is assumed or invoked. The stand-in only proves argv/script plumbing.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${ARCHX_PY:-$HERE/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python)"
CLI="${ARCHX_CLI:-$HERE/.venv/bin/archx-agent}"
[ -x "$CLI" ] || CLI="$(command -v archx-agent)"
WORK="${1:-$(mktemp -d /tmp/archx-m39-XXXXXX)}"
mkdir -p "$WORK"
"$PY" - "$CLI" "$WORK" <<'PY'
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

cli, work = sys.argv[1:]
root = Path(tempfile.mkdtemp(prefix="scene-case-", dir=work)).resolve()
project = root / "project with spaces"
project.mkdir()
env = dict(os.environ, ARCHX_PATHS_HOME=str(root / "home"), ARCHX_TOOLS_ROOTS=str(project))
checks = 0

def check(label, condition):
    global checks
    if not condition:
        raise AssertionError(label)
    checks += 1
    print(f"[ok] {label}")

def call(*args, code=0, json_output=False):
    argv = [cli, *args] + (["--json"] if json_output else [])
    result = subprocess.run(argv, env=env, capture_output=True, text=True)
    print("$ archx-agent", " ".join(args), f"[exit {result.returncode}]")
    check("expected CLI exit", result.returncode == code)
    return json.loads(result.stdout) if json_output else result.stdout

for cap in ("fs.read", "fs.write", "shell.run"):
    call("permissions", "grant", cap, "--subject", "*", "--duration", "persistent", "--confirm")
call("config", "set", "blender.executable", "")
call("scene", "create", "demo", json_output=True)
scene = call("scene", "add", "demo", "cube", "--params", '{"size":2}', json_output=True)
check("measured cube area", scene["measured"]["surface_area"] == 24)
check("measured cube volume", scene["measured"]["volume"] == 8)
check("measured cube triangles", scene["measured"]["triangles"] == 12)
check("cube has closed edge incidence", scene["objects_detail"][0]["watertight"])
for kind in ("obj", "stl", "svg", "script"):
    output = call("scene", "export", "demo", kind, json_output=True)
    data = (project / output["path"]).read_bytes()
    check(f"{kind} recorded byte count", len(data) == output["bytes"])
    check(f"{kind} recorded hash", hashlib.sha256(data).hexdigest() == output["sha256"])
    if kind == "stl":
        check("STL triangle count from binary header", struct.unpack_from("<I", data, 80)[0] == 12)
        check("STL byte layout", len(data) == 84 + 50 * 12)
    if kind == "obj":
        check("OBJ vertices really written", sum(line.startswith(b"v ") for line in data.splitlines()) == 8)
    if kind == "svg":
        check("SVG labelled not a render", b"not a render" in data)
    if kind == "script":
        check("script uses OBJ import", b"bpy.ops.wm.obj_import" in data)
        compile(data, output["path"], "exec")
check("fresh scene verifies", call("scene", "verify", "demo", json_output=True)["ok"])
(project / "scenes/demo.obj").write_text("broken export\n")
check("modified export fails verification", not call("scene", "verify", "demo", code=3, json_output=True)["ok"])
call("scene", "export", "demo", "obj", json_output=True)
check("latest export is verification baseline", call("scene", "verify", "demo", json_output=True)["ok"])
refused = call("scene", "render", "demo", code=3, json_output=True)
check("missing Blender is a recorded refusal", refused["status"] == "refused" and "no Blender" in refused["note"])
call("scene", "create", "demo", code=2)
check("duplicate create leaves objects intact", call("scene", "show", "demo", json_output=True)["measured"]["objects"] == 1)
# A zero-exit stand-in in a path with spaces: actual argv is recorded, but it makes no PNG.
stand_in = root / "fake blender"
record = root / "argv.json"
stand_in.write_text("#!" + sys.executable + "\nimport json,sys\nfrom pathlib import Path\nPath(" + repr(str(record)) + ").write_text(json.dumps(sys.argv[1:]))\n")
stand_in.chmod(0o755)
call("config", "set", "blender.executable", str(stand_in))
call("config", "set", "execution.enabled", "true")
result = call("scene", "render", "demo", code=1, json_output=True)
check("stand-in was executed", result["run"]["status"] == "ok")
check("zero exit without a PNG is not success", result["status"] == "failed" and result["sha256"] is None)
argv = json.loads(record.read_text())
check("Blender flags reached binary", argv[:3] == ["--background", "--factory-startup", "--python"])
check("script path is absolute and exists", Path(argv[3]).is_absolute() and Path(argv[3]).is_file())
call("scene", "remove", "demo", "cube", json_output=True)
check("remove recomputes totals", call("scene", "show", "demo", json_output=True)["measured"]["objects"] == 0)
task = call("tasks", "start", "--type", "tool", "--title", "Scene acceptance", json_output=True)
linked = call("scene", "create", "linked", "--task", task["id"], json_output=True)
check("scene has task artifact", bool(linked.get("artifact_id")))
call("scene", "add", "linked", "cube", json_output=True)
output = call("scene", "export", "linked", "obj", json_output=True)
check("export attached to same task", output["task_id"] == task["id"] and bool(output.get("artifact_id")))
artifacts = call("tasks", "artifacts", task["id"], json_output=True)
check("task lists document and mesh artifacts", {item["kind"] for item in artifacts} == {"scene", "scene.obj"})
call("scene", "create", "invalid-task", "--task", "missing", code=1)
check("unknown task left no scene document", not (project / "scenes/invalid-task.json").exists())
print(f"M39 acceptance: {checks} checks passed, 0 failed")
PY
