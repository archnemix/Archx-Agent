"""Scene command: argument registration and execution."""

from __future__ import annotations

import argparse


import json


from archx_agent.helpers.exceptions import (
    NotFoundError,
    PermissionDeniedError,
    ToolError,
    ValidationError,
)


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    fail,
    _workspace,
    EXIT_OK,
    EXIT_ERROR,
    EXIT_USAGE,
    EXIT_DEGRADED,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    scene = sub.add_parser(
        "scene",
        help="Build and measure 3D scenes, export meshes and render with Blender",
    )
    scene_sub = scene.add_subparsers(dest="scene_command", required=True)
    scene_sub.add_parser("list")
    scene_sub.add_parser("stats")
    sc_create = scene_sub.add_parser("create")
    sc_create.add_argument("name")
    sc_create.add_argument(
        "--task", default=None, help="attach scene and exports to an existing task"
    )
    for action in ("show", "measure", "verify", "preview", "outputs", "render"):
        leaf = scene_sub.add_parser(action)
        leaf.add_argument("scene")
    sc_add = scene_sub.add_parser("add")
    sc_add.add_argument("scene")
    sc_add.add_argument(
        "primitive", choices=["cube", "plane", "uv_sphere", "cylinder", "cone", "torus"]
    )
    sc_add.add_argument("--name")
    sc_add.add_argument(
        "--params", default="{}", help="primitive parameters as a JSON object"
    )
    for field in ("location", "rotation", "scale"):
        sc_add.add_argument("--" + field, nargs=3, type=float)
    sc_remove = scene_sub.add_parser("remove")
    sc_remove.add_argument("scene")
    sc_remove.add_argument("name")
    sc_export = scene_sub.add_parser("export")
    sc_export.add_argument("scene")
    sc_export.add_argument("kind", choices=["obj", "stl", "svg", "script"])


def cmd_scene(args: argparse.Namespace) -> int:
    """Geometry without Blender; rendering only with an explicitly configured binary."""
    try:
        with _workspace(args) as ws:
            svc = ws.scene_workflow
            action = args.scene_command
            if action == "create":
                result = svc.create(args.name, task_id=args.task)
            elif action == "list":
                result = svc.list()
            elif action == "stats":
                result = svc.stats()
            elif action == "add":
                params = json.loads(args.params)
                if not isinstance(params, dict):
                    raise ValidationError("--params must be a JSON object")
                transform = {
                    key: getattr(args, key)
                    for key in ("location", "rotation", "scale")
                    if getattr(args, key) is not None
                }
                result = svc.add(
                    args.scene,
                    args.primitive,
                    name=args.name,
                    params=params,
                    transform=transform,
                )
            elif action == "remove":
                result = svc.remove(args.scene, args.name)
            elif action == "export":
                result = svc.export(args.scene, args.kind)
            else:
                method = svc.view if action == "show" else getattr(svc, action)
                result = method(args.scene)
            if action == "preview" and not args.json:
                emit(result["svg"])
            else:
                emit_json(result)
            if action == "verify" and not result["ok"]:
                return EXIT_DEGRADED
            if action == "render" and result.get("status") != "written":
                return EXIT_DEGRADED if result.get("status") == "refused" else 1
            return EXIT_OK
    except (ValueError, ValidationError) as exc:
        return fail(str(exc), EXIT_USAGE)
    except (ToolError, PermissionDeniedError, NotFoundError) as exc:
        return fail(str(exc), EXIT_ERROR)
