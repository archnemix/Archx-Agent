#!/usr/bin/env python3
"""Real Blender 4.2 bpy/Cycles CPU smoke, not a stand-in. Requires native Blender libraries.

Install bpy==4.2.0 and numpy<2 in an isolated environment. The small executable adapter maps
Blender CLI flags to the official bpy runtime; it is not a test double. All files stay in a
throwaway directory, and no renderer or native libraries are bundled with Archx Agent.
"""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile

from archx_agent.application.workspace import open_workspace


def main():
    with tempfile.TemporaryDirectory(prefix="archx-real-blender-") as tmp:
        root = Path(tmp)
        project = root / "project with spaces"
        project.mkdir()
        adapter = root / "blender-bpy"
        adapter.write_text("#!" + sys.executable + '''
import bpy, runpy, sys
print("REAL BLENDER", bpy.app.version_string, flush=True)
runpy.run_path(sys.argv[-1], run_name="__main__")
''')
        adapter.chmod(0o755)
        with open_workspace(home=str(root / "home"), overrides={"tools.roots": [str(project)]}) as ws:
            for cap in ("fs.read", "fs.write", "shell.run"):
                ws.permissions.grant(cap, subject="*", duration="persistent", confirm=True)
            ws.config.set("execution.enabled", True)
            ws.config.set("blender.executable", str(adapter))
            svc = ws.scene_workflow
            scene = svc.create("real", camera={"resolution": [64, 64]})
            svc.add("real", "cube")
            # CPU Cycles works on headless machines; Eevee requires a graphics context.
            path = project / scene["path"]
            document = json.loads(path.read_text())
            document["engine"] = "CYCLES"
            path.write_text(json.dumps(document))
            svc.measure("real")
            output = svc.render("real")
            if output["status"] != "written":
                print(json.dumps(output, indent=2))
                raise SystemExit("real Blender render failed")
            raw = (project / output["path"]).read_bytes()
            assert raw[:8] == b"\x89PNG\r\n\x1a\n"
            assert struct.unpack(">II", raw[16:24]) == (64, 64)
            assert hashlib.sha256(raw).hexdigest() == output["sha256"]
            assert "REAL BLENDER 4.2" in output["run"]["stdout"]
            assert svc.verify("real")["ok"]
            print(json.dumps({"renderer": "official bpy 4.2 / Cycles CPU", "resolution": [64, 64],
                "png_bytes": len(raw), "sha256": output["sha256"], "status": "verified"}, sort_keys=True))


if __name__ == "__main__":
    main()
