#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${ARCHX_PY:-$HERE/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python)"
CLI="${ARCHX_CLI:-$HERE/.venv/bin/archx-agent}"
[ -x "$CLI" ] || CLI="$(command -v archx-agent)"
"$PY" - "$CLI" <<'PY'
import json, os, pathlib, subprocess, sys, tempfile
with tempfile.TemporaryDirectory(prefix="archx-m40-") as tmp:
    root = pathlib.Path(tmp)
    project = root / "project"
    project.mkdir()
    env = dict(os.environ, ARCHX_PATHS_HOME=str(root / "home"), ARCHX_TOOLS_ROOTS=str(project))
    checks = 0
    def check(label, condition):
        global checks
        assert condition, label
        checks += 1
        print("[ok]", label)
    def call(*args, code=0):
        result = subprocess.run([sys.argv[1], *args, "--json"], env=env, capture_output=True, text=True)
        check("exit for " + " ".join(args[:2]), result.returncode == code)
        return json.loads(result.stdout) if result.returncode == 0 else None
    argv = json.dumps([sys.executable, "-c", "from pathlib import Path; Path('ran.txt').write_text('done')"])
    first = call("automation", "add", "one", "--argv", argv, "--at", "2020-01-01T00:00:00Z")
    check("starts disabled", not first["enabled"])
    check("disabled tick enqueues nothing", not call("automation", "tick")["dispatched"])
    call("automation", "enable", "one")
    dispatch = call("automation", "tick")
    check("one occurrence enqueued", len(dispatch["dispatched"]) == 1)
    check("tick does not execute", not (project / "ran.txt").exists())
    call("automation", "serve", "--once", code=1)
    check("no execution without grant", not (project / "ran.txt").exists())
    check("refusal observed from job", call("automation", "runs", "one")[0]["status"] == "failed")
    call("permissions", "grant", "shell.run", "--subject", "*", "--duration", "persistent", "--confirm")
    call("automation", "add", "two", "--argv", argv, "--at", "2020-01-01T00:00:00Z")
    call("automation", "enable", "two")
    call("automation", "serve", "--once")
    check("real command side effect", (project / "ran.txt").read_text() == "done")
    check("completion is observed", call("automation", "runs", "two")[0]["status"] == "completed")
    check("one-shot does not repeat", not call("automation", "tick")["dispatched"])
    call("automation", "add", "bad", "--argv", argv, "--interval", "0", code=2)
    (project / "watch.txt").write_text("old")
    call("permissions", "grant", "fs.read", "--subject", "*", "--duration", "persistent", "--confirm")
    call("automation", "add", "watch", "--argv", argv, "--watch", "watch.txt")
    call("automation", "enable", "watch")
    check("unchanged watch quiet", not call("automation", "tick")["dispatched"])
    (project / "watch.txt").write_text("new")
    check("changed watch enqueues", len(call("automation", "tick")["dispatched"]) == 1)
    check("unchanged hash not repeated", not call("automation", "tick")["dispatched"])
    call("automation", "disable", "watch")
    check("disable persists", not call("automation", "show", "watch")["enabled"])
    print(f"M40 acceptance: {checks} checks passed, 0 failed")
PY
