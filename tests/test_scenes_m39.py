"""Geometry and scene workflow checks; no installed Blender is assumed."""
import hashlib
import math
import struct

import pytest

from archx_agent.application import geometry as g
from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import ValidationError


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    with open_workspace(home=str(tmp_path / "home"), overrides={"tools.roots": [str(root)]}) as ws:
        for cap in ("fs.read", "fs.write"):
            ws.permissions.grant(cap, subject="*", duration="persistent", confirm=True)
        yield ws


@pytest.mark.parametrize("primitive", g.PRIMITIVES)
def test_primitive_topology(primitive):
    mesh = g.build(primitive)
    metrics = g.metrics(mesh)
    assert metrics["watertight"] == (primitive != "plane")
    assert metrics["surface_area"] > 0
    if primitive != "plane":
        assert metrics["volume"] > 0


@pytest.mark.parametrize("params", [{"size": 0}, {"size": -1}, {"size": float("nan")}, {"typo": 2}])
def test_bad_parameters(params):
    with pytest.raises(ValueError):
        g.build("cube", params)


def test_cube_arithmetic():
    mesh = g.cube()
    assert g.volume(mesh) == pytest.approx(8)
    assert g.surface_area(mesh) == pytest.approx(24)
    world = mesh.transformed(g.transform_matrix({"location": [10, 0, 0], "scale": [2, 3, 4]}))
    assert g.volume(world) == pytest.approx(192)
    assert g.bounding_box(world)["min"] == [8, -3, -4]


def test_sphere_converges():
    assert g.volume(g.uv_sphere(1, 64, 32)) == pytest.approx(4 * math.pi / 3, rel=.005)


def test_obj_indices_and_normals():
    text = g.to_obj([{"mesh": g.cube(), "name": "cube"}])
    normals = [line for line in text.splitlines() if line.startswith("vn ")]
    faces = [line.split()[1:] for line in text.splitlines() if line.startswith("f ")]
    assert len(normals) == 6
    for face in faces:
        indices = [int(token.split("//")[1]) for token in face]
        assert len(set(indices)) == 1
        assert 1 <= indices[0] <= len(normals)


def test_stl_layout():
    data = g.to_stl([{"mesh": g.cube()}])
    assert struct.unpack_from("<I", data, 80)[0] == 12
    assert len(data) == 84 + 50 * 12


def test_projection():
    point = g.project([0, 0, 0], eye=[4, -4, 3], target=[0, 0, 0], fov_degrees=40, width=480, height=480)
    assert point["x"] == pytest.approx(240)
    assert point["y"] == pytest.approx(240)


def test_scene_exports_and_drift(ws):
    svc = ws.scene_workflow
    scene = svc.create("demo")
    svc.add(scene["id"], "cube")
    assert svc.view("demo")["measured"]["volume"] == 8
    for kind in ("obj", "stl", "svg", "script"):
        output = svc.export("demo", kind)
        data = ws.tools.runtime.resolve(output["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == output["sha256"]
    assert svc.verify("demo")["ok"]
    # Re-exporting an output must not compare it with a historical hash for the same path.
    svc.add("demo", "plane")
    svc.export("demo", "obj")
    assert svc.verify("demo")["ok"]
    path = ws.tools.runtime.resolve("scenes/demo.obj")
    path.write_text("changed")
    assert not svc.verify("demo")["ok"]


def test_duplicate_does_not_overwrite(ws):
    svc = ws.scene_workflow
    svc.create("my scene")
    svc.add("my scene", "cube")
    with pytest.raises(ValidationError):
        svc.create("my_scene")
    assert svc.view("my scene")["measured"]["objects"] == 1


def test_render_refusal_is_recorded(ws):
    svc = ws.scene_workflow
    svc.create("demo")
    svc.add("demo", "cube")
    ws.config.set("blender.executable", "")
    result = svc.render("demo")
    assert result["status"] == "refused"
    assert "no Blender" in result["note"]
    assert svc.renders("demo")[0]["id"] == result["id"]


def test_remove(ws):
    svc = ws.scene_workflow
    svc.create("demo")
    svc.add("demo", "cube")
    svc.remove("demo", "cube")
    assert svc.view("demo")["measured"]["objects"] == 0


def test_binary_dry_run(ws):
    import base64
    result = ws.tools.execute("fs.write_bytes", {"path": "dry.stl", "content_base64": base64.b64encode(b"\x00\xff").decode()}, dry_run=True)
    assert result.dry_run
    assert not ws.tools.runtime.resolve("dry.stl").exists()


def test_zero_exit_without_png_is_not_a_render(ws, tmp_path):
    binary = tmp_path / "fake blender"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    ws.permissions.grant("shell.run", subject="*", duration="persistent", confirm=True)
    ws.config.set("execution.enabled", True)
    ws.config.set("blender.executable", str(binary))
    svc = ws.scene_workflow
    svc.create("demo")
    svc.add("demo", "cube")
    result = svc.render("demo")
    assert result["run"]["status"] == "ok"
    assert result["status"] == "failed"
    assert result["sha256"] is None


def test_cli_scene(tmp_path, capsys):
    from archx_agent.interfaces.cli.main import main
    home = str(tmp_path / "home")
    assert main(["--home", home, "scene", "list", "--json"]) == 0
    assert "[]" in capsys.readouterr().out


def test_rotation_order():
    # X first: (0,1,0)->(0,0,1); Y next ->(1,0,0).
    matrix = g.transform_matrix({"rotation": [90, 90, 0]})
    assert g.transform_point(matrix, [0, 1, 0]) == pytest.approx((1, 0, 0))


def test_binary_permission_and_root_boundary(ws, tmp_path):
    import base64
    from archx_agent.helpers.exceptions import ArchxError
    payload = base64.b64encode(b"\x00\xff").decode()
    with pytest.raises(ArchxError):
        ws.tools.execute("fs.write_bytes", {"path": str(tmp_path / "outside.bin"), "content_base64": payload})
    assert not (tmp_path / "outside.bin").exists()
