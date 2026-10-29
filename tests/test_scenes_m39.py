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


def test_scene_api(ws):
    from archx_agent.interfaces.gui.server import GuiApi, Request
    api = GuiApi(ws, token="scene-token")

    def call(method, path, body=None, token="scene-token"):
        return api.dispatch(Request(method=method, path=path, query={},
            headers={"x-archx-token": token}, body=body))

    assert call("POST", "/api/scenes", {"name": "demo"}, token="wrong").status == 401
    created = call("POST", "/api/scenes", {"name": "demo"})
    assert created.status == 200
    scene_id = created.payload["data"]["id"]
    base = f"/api/scenes/{scene_id}"
    assert call("POST", base + "/add", {"primitive": "cube", "params": []}).status == 400
    added = call("POST", base + "/add", {"primitive": "cube"})
    assert added.payload["data"]["measured"]["volume"] == 8
    assert call("GET", base).payload["data"]["measured"]["triangles"] == 12
    assert call("POST", base + "/preview", {}).payload["data"]["svg"].startswith("<svg")
    assert call("POST", base + "/export", {"kind": "stl"}).status == 200
    assert call("POST", base + "/verify", {}).payload["data"]["ok"]
    ws.config.set("blender.executable", "")
    assert call("POST", base + "/render", {}).payload["data"]["status"] == "refused"
    assert call("POST", base + "/unknown", {}).status == 400
    assert len(call("GET", "/api/scenes").payload["data"]["scenes"]) == 1


def test_cli_validation_exit_is_two(tmp_path, capsys):
    from archx_agent.interfaces.cli.main import main
    home = str(tmp_path / "home")
    assert main(["--home", home, "scene", "add", "missing", "cube", "--params", "["]) == 2
    assert "error" in capsys.readouterr().err.lower()


@pytest.mark.parametrize("field,value", [
    ("camera", None), ("objects", {}), ("format", "unknown"), ("units", "feet"),
    ("engine", "unknown"), ("name", "line\nbreak"),
    ("camera.fov", 0), ("camera.fov", float("nan")), ("camera.fov", True),
    ("camera.resolution", [0, 480]), ("camera.resolution", [480.5, 480]),
    ("camera.location", [0, 0]), ("camera.location", [0, 0, 0]),
    ("camera.up", [0, 0, 0]), ("camera.up", [4, -4, 3]),
    ("light.energy", -1), ("light.location", [1e100, 0, 0]),
])
def test_malformed_document_rejected(field, value):
    from archx_agent.application.scenes import empty_document
    from archx_agent.application.scene_validation import validate_document
    doc = empty_document("demo")
    if "." in field:
        parent, key = field.split(".")
        doc[parent][key] = value
    else:
        doc[field] = value
    with pytest.raises(ValidationError):
        validate_document(doc)


@pytest.mark.parametrize("params,transform", [
    ({"size": True}, {}), ({"size": "2"}, {}), ({"size": 1e100}, {}),
    ({}, {"scale": [True, 1, 1]}), ({}, {"scale": "111"}),
    ({}, {"rotation": [0, float("inf"), 0]}), ({}, {"scale": None}),
])
def test_invalid_add_leaves_file_and_rows_unchanged(ws, params, transform):
    svc = ws.scene_workflow
    svc.create("demo")
    path = ws.tools.runtime.resolve("scenes/demo.json")
    original = path.read_bytes()
    with pytest.raises(ValidationError):
        svc.add("demo", "cube", params=params, transform=transform)
    assert path.read_bytes() == original
    assert ws.scenes.objects(svc.scene("demo").id) == []


def test_scene_budget_checked_without_generating_mesh(monkeypatch):
    from archx_agent.application.scenes import empty_document
    from archx_agent.application.scene_validation import validate_document
    doc = empty_document("demo")
    doc["objects"] = [{"name": f"torus{i}", "primitive": "torus", "params": {
        "major_segments": 256, "minor_segments": 256}, "transform": {}} for i in range(4)]
    monkeypatch.setattr(g, "build", lambda *args: pytest.fail("must not allocate a mesh"))
    with pytest.raises(ValidationError, match="budget"):
        validate_document(doc)
    doc["objects"] = [{}] * 129
    with pytest.raises(ValidationError, match="at most"):
        validate_document(doc)


def test_invalid_camera_rejected_before_create(ws):
    with pytest.raises(ValidationError, match="camera"):
        ws.scene_workflow.create("bad", camera={"fov": 0})
    assert not ws.tools.runtime.resolve("scenes/bad.json").exists()
    assert ws.scenes.scenes() == []


def test_corrupt_document_api_returns_validation_error(ws):
    from archx_agent.interfaces.gui.server import GuiApi, Request
    scene = ws.scene_workflow.create("demo")
    path = ws.tools.runtime.resolve("scenes/demo.json")
    path.write_text("[]")
    api = GuiApi(ws, token="token")
    response = api.dispatch(Request(method="GET", path="/api/scenes/" + scene["id"],
        query={}, headers={"x-archx-token": "token"}))
    assert response.status == 400


def test_scene_outputs_attach_to_task_without_completing_it(ws):
    task = ws.tasks.create("tool", "Model a component", start=True, manual=True)
    svc = ws.scene_workflow
    scene = svc.create("linked", task_id=task.id)
    assert scene["artifact_id"]
    svc.add("linked", "cube")
    output = svc.export("linked", "stl")
    assert output["task_id"] == task.id and output["artifact_id"]
    artifacts = ws.tasks.artifacts(task.id)
    assert {item.kind for item in artifacts} == {"scene", "scene.stl"}
    stl = next(item for item in artifacts if item.kind == "scene.stl")
    assert stl.checksum == output["sha256"]
    assert ws.tasks.get(task.id).status == "running"


def test_unknown_task_refused_before_scene_write(ws):
    from archx_agent.helpers.exceptions import NotFoundError
    with pytest.raises(NotFoundError):
        ws.scene_workflow.create("bad-task", task_id="missing")
    assert not ws.tools.runtime.resolve("scenes/bad-task.json").exists()
    assert not ws.scenes.scenes()


def test_render_refusal_logs_task_but_does_not_fail_it(ws):
    task = ws.tasks.create("tool", "Scene work", start=True, manual=True)
    ws.scene_workflow.create("linked", task_id=task.id)
    ws.scene_workflow.add("linked", "cube")
    result = ws.scene_workflow.render("linked")
    assert result["task_id"] == task.id
    assert result["status"] == "refused"
    assert any(row["kind"] == "scene.render" for row in ws.tasks.timeline(task.id))
    assert ws.tasks.get(task.id).status == "running"


def test_attachment_failure_preserves_output_and_reports_error(ws, monkeypatch):
    from archx_agent.helpers.exceptions import ToolError
    task = ws.tasks.create("tool", "Scene work")
    svc = ws.scene_workflow
    svc.create("linked", task_id=task.id)
    svc.add("linked", "cube")

    def broken(*args, **kwargs):
        raise ToolError("artifact store unavailable")

    monkeypatch.setattr(ws.tasks, "attach_artifact", broken)
    output = svc.export("linked", "obj")
    assert output["status"] == "written"
    assert "artifact store unavailable" in output["artifact_error"]
    assert svc.outputs("linked")[0]["id"] == output["id"]
    assert ws.tools.runtime.resolve(output["path"]).is_file()


def test_stand_in_render_links_execution_and_artifact(ws, tmp_path):
    # A controlled writer tests task bookkeeping, NOT Blender compatibility.
    import sys
    binary = tmp_path / "stand-in-renderer"
    binary.write_text("#!" + sys.executable + '''
import ast, pathlib, sys
module = ast.parse(pathlib.Path(sys.argv[-1]).read_text())
for node in module.body:
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "RENDER_PATH" for t in node.targets):
        pathlib.Path(ast.literal_eval(node.value)).write_bytes(bytes.fromhex("89504e470d0a1a0a") + b"stand-in")
''')
    binary.chmod(0o755)
    ws.permissions.grant("shell.run", subject="*", duration="persistent", confirm=True)
    ws.config.set("execution.enabled", True)
    ws.config.set("blender.executable", str(binary))
    task = ws.tasks.create("tool", "Scene work", start=True, manual=True)
    svc = ws.scene_workflow
    svc.create("linked", task_id=task.id)
    svc.add("linked", "cube")
    result = svc.render("linked")
    assert result["status"] == "written"
    assert result["task_id"] == task.id
    assert result["run"]["task_id"] == task.id
    assert result["artifact_id"]
    assert any(item.kind == "scene.render" and item.checksum == result["sha256"] for item in ws.tasks.artifacts(task.id))
    assert ws.tasks.get(task.id).status == "running"
