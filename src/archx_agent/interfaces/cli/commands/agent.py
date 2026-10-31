"""Agent command: argument registration and execution."""

from __future__ import annotations

import argparse


import json


import sys


from pathlib import Path


from typing import Any


from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
)


from archx_agent.helpers.jsonio import json_text


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    table,
    fail,
    _workspace,
    _pairs,
    EXIT_OK,
    EXIT_ERROR,
    EXIT_USAGE,
    EXIT_DENIED,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    agent = sub.add_parser(
        "agent", help="agent workflows: user-directed and model-proposed plans"
    )
    ag_sub = agent.add_subparsers(dest="agent_command", required=True)
    ag_plan = ag_sub.add_parser(
        "plan", help="ask a model for a plan (stored unapproved)"
    )
    ag_plan.add_argument("goal")
    ag_plan.add_argument("--model")
    ag_plan.add_argument("--name")
    ag_list = ag_sub.add_parser("list", help="workflow records")
    ag_list.add_argument("--status")
    ag_list.add_argument("--mode")
    ag_list.add_argument("--limit", type=int, default=20)
    ag_show = ag_sub.add_parser("show", help="definition, steps and subagent tasks")
    ag_show.add_argument("workflow")
    ag_run = ag_sub.add_parser("run", help="run a stored workflow")
    ag_run.add_argument("workflow")
    ag_run.add_argument(
        "--approve",
        action="store_true",
        help="approve a model-proposed plan and pass checkpoints",
    )
    ag_file = ag_sub.add_parser(
        "run-file", help="run a user-written workflow definition (JSON)"
    )
    ag_file.add_argument("path")
    ag_file.add_argument("--approve", action="store_true")
    ag_template = ag_sub.add_parser(
        "run-template", help="run a built-in workflow template"
    )
    ag_template.add_argument("template")
    ag_template.add_argument(
        "--input", action="append", default=[], metavar="key=value"
    )
    ag_template.add_argument("--approve", action="store_true")
    ag_sub.add_parser("templates", help="built-in user-directed workflows")
    ag_approve = ag_sub.add_parser(
        "approve", help="approve a proposed plan without running it"
    )
    ag_approve.add_argument("workflow")
    ag_reject = ag_sub.add_parser("reject", help="reject a proposed plan")
    ag_reject.add_argument("workflow")
    ag_reject.add_argument("--reason")
    ag_cancel = ag_sub.add_parser("cancel", help="cancel a workflow")
    ag_cancel.add_argument("workflow")
    ag_cancel.add_argument("--reason")
    ag_rerun = ag_sub.add_parser("rerun", help="start a NEW run of the same definition")
    ag_rerun.add_argument("workflow")
    ag_rerun.add_argument("--approve", action="store_true")
    ag_steps = ag_sub.add_parser("steps", help="step records for a workflow")
    ag_steps.add_argument("workflow")
    ag_sub.add_parser("stats", help="workflow counts")


def cmd_agent(args: argparse.Namespace) -> int:
    from archx_agent.managers.workflows import TEMPLATES

    with _workspace(args) as ws:
        manager = ws.workflows
        command = args.agent_command
        if command == "templates":
            rows = [
                {
                    "name": name,
                    "goal": definition.get("goal"),
                    "steps": len(definition.get("steps") or []),
                }
                for name, definition in TEMPLATES.items()
            ]
            emit_json(rows) if args.json else emit(
                table(
                    [[r["name"], r["steps"], r["goal"]] for r in rows],
                    ["template", "steps", "goal"],
                )
            )
            return EXIT_OK
        if command == "plan":
            try:
                workflow = ws.agent.plan(args.goal, model_id=args.model, name=args.name)
            except ApprovalRequiredError:
                raise
            if args.json:
                emit_json(workflow.to_dict())
            else:
                emit(
                    f"{workflow.id}  proposed  {workflow.name}  ({len(workflow.steps)} steps)"
                )
                for index, step in enumerate(workflow.steps, start=1):
                    emit(f"  {index}. {step.kind:<10} {step.title}")
                emit("")
                emit(
                    f"a model proposed this plan. Review it, then: archx-agent agent run {workflow.id} --approve"
                )
            return EXIT_OK
        if command == "list":
            rows = manager.list(status=args.status, mode=args.mode, limit=args.limit)
            if args.json:
                emit_json([row.to_dict(with_definition=False) for row in rows])
            else:
                if not rows:
                    emit("no workflows")
                else:
                    emit(
                        table(
                            [
                                [
                                    row.id,
                                    row.mode,
                                    row.status,
                                    len(row.steps),
                                    row.name[:44],
                                    row.created_at[11:19],
                                ]
                                for row in rows
                            ],
                            ["workflow", "mode", "status", "steps", "name", "created"],
                        )
                    )
            return EXIT_OK
        if command == "show":
            workflow = manager.require(args.workflow)
            steps = manager.steps(workflow.id)
            children = ws.tasks.children(workflow.task_id) if workflow.task_id else []
            data = {
                **workflow.to_dict(),
                "steps": [step.to_dict() for step in steps],
                "children": [child.to_dict() for child in children],
            }
            if args.json:
                emit_json(data)
            else:
                emit(
                    f"{workflow.id}  {workflow.mode}  [{workflow.status}]  {workflow.name}"
                )
                if workflow.goal:
                    emit(f"  goal: {workflow.goal}")
                if workflow.task_id:
                    emit(f"  task: {workflow.task_id}")
                if workflow.error:
                    emit(f"  error: {workflow.error}")
                emit("")
                emit("  plan:")
                for index, step in enumerate(workflow.steps, start=1):
                    emit(f"   {index}. {step.kind:<10} {step.title}")
                    if step.tool:
                        emit(f"      tool={step.tool} args={json_text(step.args)}")
                    if step.prompt:
                        emit(f"      prompt: {step.prompt[:120]}")
                    if step.goal:
                        emit(
                            f"      goal: {step.goal[:120]} ({len(step.steps)} nested step(s))"
                        )
                    if step.continue_on_error:
                        emit("      continue_on_error: true")
                if steps:
                    emit("")
                    emit(
                        table(
                            [
                                [
                                    step.seq,
                                    step.kind,
                                    step.status,
                                    step.tokens,
                                    (step.error or step.output or "")[:40],
                                ]
                                for step in steps
                            ],
                            ["seq", "kind", "status", "tokens", "output / error"],
                        )
                    )
                if children:
                    emit("")
                    emit(
                        f"  subagent tasks: {', '.join(child.id for child in children)}"
                    )
            return EXIT_OK
        if command == "rerun":
            original = manager.require(args.workflow)
            replacement = manager.create(
                original.definition,
                mode=original.mode,
                status="approved",
                model_id=original.model_id,
                goal=original.goal,
                metadata={"replaces": original.id, "mode": original.mode},
            )
            workflow = replacement
            code, result = _execute_workflow(ws, workflow, approve=args.approve)
            if args.json:
                emit_json(
                    {**result, "workflow": ws.workflows.get(workflow.id).to_dict()}
                )
            else:
                emit(
                    f"new run {workflow.id} (replaces {original.id})  {result['status']}"
                )
                for step in result["steps"]:
                    emit(
                        f"   {step['seq']:>3}  {step['kind']:<10} {step['status']:<10} "
                        f"{(step.get('output') or step.get('error') or '')[:60]}"
                    )
                if result.get("summary"):
                    emit("")
                    emit(result["summary"][:800])
                if result.get("approval_id"):
                    emit(
                        f"approve with: archx-agent approvals approve {result['approval_id']}"
                    )
            return code
        if command in ("run", "run-file", "run-template"):
            if command == "run-file":
                path = Path(args.path).expanduser()
                if not path.is_file():
                    return fail(f"no workflow file at {path}", EXIT_USAGE)
                try:
                    definition = json.loads(path.read_text())
                except json.JSONDecodeError as exc:
                    return fail(f"{path} is not valid JSON: {exc}", EXIT_USAGE)
                workflow = manager.create(
                    definition, status="approved", goal=definition.get("goal")
                )
            elif command == "run-template":
                template = TEMPLATES.get(args.template)
                if template is None:
                    return fail(
                        f"unknown template {args.template!r} (known: {', '.join(sorted(TEMPLATES))})",
                        EXIT_USAGE,
                    )
                inputs = _pairs(args.input, flag="--input")
                definition = _render_definition(template, inputs)
                workflow = manager.create(
                    definition, status="approved", goal=definition.get("goal")
                )
            else:
                workflow = manager.require(args.workflow)
            code, result = _execute_workflow(ws, workflow, approve=args.approve)
            if args.json:
                emit_json(
                    {**result, "workflow": ws.workflows.get(workflow.id).to_dict()}
                )
            else:
                emit(f"workflow {result['workflow_id']}  {result['status']}")
                emit(
                    f"  task {result['task_id']}   steps {len(result['steps'])}   tokens {result['tokens']}"
                    f"   {result['elapsed_ms']}ms"
                )
                for step in result["steps"]:
                    mark = "ok" if step["status"] == "succeeded" else step["status"]
                    emit(
                        f"   {step['seq']:>3}  {step['kind']:<10} {mark:<10} {(step.get('output') or step.get('error') or '')[:64]}"
                    )
                if result.get("summary"):
                    emit("")
                    emit("summary:")
                    emit(result["summary"][:1200])
                if result.get("approval_id"):
                    emit("")
                    emit(
                        f"approve with: archx-agent approvals approve {result['approval_id']}"
                    )
            return code
        if command == "approve":
            workflow = manager.approve(manager.require(args.workflow).id)
            emit_json(workflow.to_dict()) if args.json else emit(
                f"{workflow.id} approved; run it with: archx-agent agent run {workflow.id}"
            )
            return EXIT_OK
        if command == "reject":
            workflow = manager.reject(
                args.workflow, reason=args.reason or "rejected by the user"
            )
            emit_json(workflow.to_dict()) if args.json else emit(
                f"{workflow.id} rejected: {workflow.error}"
            )
            return EXIT_OK
        if command == "cancel":
            workflow = manager.cancel(
                args.workflow, reason=args.reason or "cancelled by the user"
            )
            emit_json(workflow.to_dict()) if args.json else emit(
                f"{workflow.id} cancelled"
            )
            return EXIT_OK
        if command == "steps":
            workflow = manager.require(args.workflow)
            rows = manager.steps(workflow.id)
            if args.json:
                emit_json([step.to_dict() for step in rows])
            else:
                emit(
                    table(
                        [
                            [
                                step.seq,
                                step.kind,
                                step.status,
                                step.tokens,
                                (step.error or "")[:40],
                            ]
                            for step in rows
                        ],
                        ["seq", "kind", "status", "tokens", "error"],
                    )
                )
            return EXIT_OK
        if command == "stats":
            data = manager.stats()
            emit_json(data) if args.json else emit(
                f"workflows: {data['total']}  steps: {data['steps']}\n"
                + "\n".join(
                    f"  {status:<10} {count}"
                    for status, count in sorted(data["by_status"].items())
                )
            )
            return EXIT_OK
    return EXIT_USAGE


def _render_definition(
    definition: dict[str, Any], inputs: dict[str, Any]
) -> dict[str, Any]:
    """Substitute ``{{input.*}}`` in a template *before* it becomes a workflow."""
    from archx_agent.managers.workflows import render_inputs

    return render_inputs(definition, inputs)


def _execute_workflow(ws, workflow, *, approve: bool) -> tuple[int, dict[str, Any]]:
    from archx_agent.application.agent import WorkflowFailed

    try:
        result = ws.agent.run(workflow.id, approve=approve)
    except ApprovalRequiredError as exc:
        print(f"approval required: {exc.message}", file=sys.stderr)
        current = ws.workflows.get(workflow.id)
        return EXIT_DENIED, {
            "workflow_id": current.id,
            "task_id": current.task_id or "",
            "status": current.status,
            "steps": [],
            "summary": "",
            "tokens": 0,
            "elapsed_ms": 0.0,
            "cancelled": False,
            "approval_id": getattr(exc, "approval_id", None),
        }
    except WorkflowFailed as exc:
        print(f"workflow failed: {exc.message}", file=sys.stderr)
        current = ws.workflows.get(workflow.id)
        return EXIT_ERROR, {
            "workflow_id": current.id,
            "task_id": current.task_id or "",
            "status": current.status,
            "steps": exc.steps,
            "summary": "",
            "tokens": 0,
            "elapsed_ms": 0.0,
            "cancelled": False,
            "approval_id": exc.approval_id,
        }
    return EXIT_OK, result.to_dict()
