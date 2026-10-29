"""The tool registry: what a tool is, what it may do, and the record of it doing it.

Every tool declares:

* the **capability** it needs (or ``None`` for a read-only tool that touches
  nothing outside the process),
* its **risk** and its **side effects** (what the user is consenting to),
* its **inputs** with types, so a hallucinated argument is a clear validation
  error instead of a silently ignored parameter,
* whether it supports a **dry run**.

The registry is code, not data. A tool cannot appear because a model asked for
it, and a tool cannot change its own capability: the capability comes from
:data:`BUILTIN_SPECS`, and the permission centre reads only that. Extensions and
MCP servers (M23) add specs through their own registration path with their trust
level attached.

Execution order is fixed and observable:

1. validate the request (unknown tool, unknown/invalid arguments);
2. refuse a dry run on a tool that cannot do one;
3. preflight hard denials (e.g. the shell denylist) - these cannot be approved;
4. ask the permission centre, consuming a single-use grant **before** the work;
5. run the operation, then record the run row and its trace events.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from archx_agent.adapters.local_tools import LocalToolRuntime
from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    NotFoundError,
    PermissionDeniedError,
    ToolError,
    ToolNotFoundError,
    ToolValidationError,
)
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now, new_id
from archx_agent.managers.permissions import CAPABILITIES, PermissionDecision, PermissionManager

from .base import BaseManager

TOOL_TABLES = ("tool_runs",)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    summary: str
    capability: str | None
    risk: str
    inputs: dict[str, str]
    required: tuple[str, ...] = ()
    types: dict[str, str] = field(default_factory=dict)
    supports_dry_run: bool = False
    side_effects: str = "none"
    builtin: bool = True
    origin: str = "builtin"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "summary": self.summary,
            "capability": self.capability,
            "risk": self.risk,
            "inputs": self.inputs,
            "required": list(self.required),
            "types": self.types or {name: "str" for name in self.inputs},
            "supports_dry_run": self.supports_dry_run,
            "side_effects": self.side_effects,
            "builtin": self.builtin,
            "origin": self.origin,
            "protected": self.capability is not None,
        }


BUILTIN_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="fs.read",
        summary="read a text file inside the tool roots",
        capability="fs.read",
        risk="low",
        inputs={
            "path": "file path, relative to a tool root or absolute inside one",
            "start_line": "first line to return (1-based)",
            "max_lines": "how many lines to return",
        },
        required=("path",),
        types={"path": "str", "start_line": "int", "max_lines": "int"},
        side_effects="reads a file",
    ),
    ToolSpec(
        name="fs.list",
        summary="list a directory inside the tool roots",
        capability="fs.read",
        risk="low",
        inputs={"path": "directory path (default '.')", "limit": "maximum entries"},
        types={"path": "str", "limit": "int"},
        side_effects="reads a directory",
    ),
    ToolSpec(
        name="fs.probe",
        summary="measure a file's bytes - size, hash and container header - without reading it as text",
        capability="fs.read",
        risk="low",
        inputs={
            "path": "file path inside a tool root",
            "head_bytes": "how many leading bytes to return (default 4096, at most 65536)",
        },
        required=("path",),
        types={"path": "str", "head_bytes": "int"},
        side_effects="reads the first bytes of a file and hashes it",
    ),
    ToolSpec(
        name="fs.write",
        summary="create or modify a text file inside the tool roots",
        capability="fs.write",
        risk="medium",
        inputs={
            "path": "file path inside a tool root",
            "content": "text to write",
            "create_parents": "create missing parent directories",
            "append": "append instead of replacing",
        },
        required=("path", "content"),
        types={"path": "str", "content": "str", "create_parents": "bool", "append": "bool"},
        supports_dry_run=True,
        side_effects="writes a file",
    ),
    ToolSpec(
        name="fs.write_bytes",
        summary="write bytes exactly as given (a container, not a document) inside the tool roots",
        capability="fs.write",
        risk="medium",
        inputs={
            "path": "file path inside a tool root",
            "content_base64": "the bytes, base64-encoded (JSON has no byte string)",
            "create_parents": "create missing parent directories",
        },
        required=("path", "content_base64"),
        types={"path": "str", "content_base64": "str", "create_parents": "bool"},
        supports_dry_run=True,
        side_effects="writes a file",
    ),
    ToolSpec(
        name="fs.delete",
        summary="delete a file inside the tool roots",
        capability="fs.delete",
        risk="high",
        inputs={"path": "file path inside a tool root"},
        required=("path",),
        types={"path": "str"},
        supports_dry_run=True,
        side_effects="deletes a file",
    ),
    ToolSpec(
        name="shell.run",
        summary="run a local command (argv form, no shell)",
        capability="shell.run",
        risk="high",
        inputs={
            "command": "command line, split like a shell would but executed without a shell",
            "cwd": "working directory inside the tool roots (default: the first root)",
            "timeout": "seconds before the process is killed",
        },
        required=("command",),
        types={"command": "str", "cwd": "str", "timeout": "int"},
        side_effects="executes a process",
    ),
    ToolSpec(
        name="net.fetch",
        summary="fetch a text document from an http(s) URL",
        capability="net.fetch",
        risk="medium",
        inputs={
            "url": "http(s) URL to fetch",
            "timeout": "seconds before the request is abandoned",
            "max_bytes": "stop after this many bytes",
            "max_redirects": "how many redirects to follow",
            "allow_private_hosts": "permit private/loopback addresses (still needs the grant)",
        },
        required=("url",),
        types={
            "url": "str",
            "timeout": "int",
            "max_bytes": "int",
            "max_redirects": "int",
            "allow_private_hosts": "bool",
        },
        side_effects="reads a remote document; sends the request to that host",
    ),
    ToolSpec(
        name="archx.info",
        summary="report workspace size and tool roots (read-only, no permission needed)",
        capability=None,
        risk="low",
        inputs={},
        side_effects="none",
    ),
)

BUILTIN_TOOLS = {spec.name: spec for spec in BUILTIN_SPECS}


@dataclass
class ToolContext:
    conversation_id: str | None = None
    task_id: str | None = None
    project_id: str | None = None
    purpose: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "task_id": self.task_id,
            "project_id": self.project_id,
            "purpose": self.purpose,
        }


@dataclass
class ToolRun:
    """What happened when a tool was asked to do something.

    A run exists for refusals too: "the agent tried to write a file and was
    denied" is exactly the evidence a permission system must keep.
    """

    id: str
    tool: str
    status: str  # running | succeeded | failed | denied
    arguments: dict[str, Any]
    started_at: str
    ended_at: str | None = None
    duration_ms: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    permission_id: str | None = None
    approval_id: str | None = None
    decision: str | None = None
    dry_run: bool = False
    truncated: bool = False
    seq: int | None = None

    @property
    def ok(self) -> bool:
        return self.status == "succeeded"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool": self.tool,
            "status": self.status,
            "arguments": self.arguments,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "result": self.result,
            "error": self.error,
            "permission_id": self.permission_id,
            "approval_id": self.approval_id,
            "decision": self.decision,
            "dry_run": self.dry_run,
            "truncated": self.truncated,
            "seq": self.seq,
        }


def _type_ok(value: Any, kind: str) -> bool:
    if kind == "str":
        return isinstance(value, str)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "json":
        return isinstance(value, (dict, list, int, float, bool))
    return True


def _coerce(arguments: Mapping[str, Any], spec: ToolSpec) -> dict[str, Any]:
    unknown = sorted(set(arguments) - set(spec.inputs))
    if unknown:
        accepted = ", ".join(sorted(spec.inputs)) or "none"
        raise ToolValidationError(
            f"{spec.name} does not take {', '.join(unknown)} (accepted: {accepted})"
        )
    types = spec.types or {name: "str" for name in spec.inputs}
    cleaned: dict[str, Any] = {}
    for key, value in arguments.items():
        kind = types.get(key, "str")
        if kind == "int" and isinstance(value, str) and value.strip().lstrip("-").isdigit():
            value = int(value)
        elif kind == "bool" and isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on", "0", "false", "no", "off"}:
            value = value.strip().lower() in {"1", "true", "yes", "on"}
        elif kind == "float" and isinstance(value, str):
            try:
                value = float(value)
            except ValueError as exc:
                raise ToolValidationError(f"{spec.name}.{key} expects float, got {value!r}") from exc
        elif kind == "json" and isinstance(value, str):
            import json as _json

            try:
                value = _json.loads(value)
            except _json.JSONDecodeError as exc:
                raise ToolValidationError(
                    f"{spec.name}.{key} expects JSON, got {value[:60]!r}"
                ) from exc
        if not _type_ok(value, kind):
            raise ToolValidationError(f"{spec.name}.{key} expects {kind}, got {type(value).__name__}")
        cleaned[key] = value
    missing = [name for name in spec.required if name not in cleaned]
    if missing:
        raise ToolValidationError(f"{spec.name} requires {', '.join(missing)}")
    return cleaned


class ToolManager(BaseManager):
    """Registers built-in tools and executes them under the permission centre."""

    tables = TOOL_TABLES

    def __init__(
        self,
        store,
        coordinator,
        *,
        permissions: PermissionManager,
        events=None,
        config=None,
        runtime: LocalToolRuntime | None = None,
        info_provider: Callable[[], dict[str, Any]] | None = None,
        specs: tuple[ToolSpec, ...] = BUILTIN_SPECS,
    ) -> None:
        self.permissions = permissions
        self.config = config
        self._runtime = runtime
        self._info_provider = info_provider
        # Optional task history (M24). Set by the composition root after both managers
        # exist; a tool call made inside a task is recorded on that task's timeline.
        self.tasks = None
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        for spec in specs:
            self.register_spec(spec)
        super().__init__(store, coordinator, events=events)

    # -- registry ---------------------------------------------------------
    def register_spec(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ToolValidationError(f"tool {spec.name!r} is already registered")
        if spec.capability is not None and spec.capability not in CAPABILITIES:
            raise ToolValidationError(
                f"tool {spec.name!r} needs unknown capability {spec.capability!r}"
            )
        self._specs[spec.name] = spec

    def register_handler(self, name: str, handler: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        """Attach an executable to a registered spec (used by MCP and extensions).

        The spec - and therefore the capability - must already exist. A handler can be
        replaced on re-sync (a server may change its tool list); a *spec* cannot be
        silently redefined by a remote party, which is why :meth:`register_spec` stays
        strict.
        """
        if name not in self._specs:
            raise ToolValidationError(f"handler for unregistered tool {name!r}")
        self._handlers[name] = handler

    def unregister_spec(self, name: str) -> None:
        """Remove a tool that is no longer advertised (server removed / extension disabled)."""
        spec = self._specs.pop(name, None)
        if spec is None:
            raise ToolNotFoundError(f"no tool {name!r}")
        if spec.builtin:
            raise ToolValidationError(f"{name!r} is a built-in tool and cannot be unregistered")
        self._handlers.pop(name, None)

    def declare_spec(self, spec: ToolSpec, handler: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        """Register a spec and its handler together, replacing a previous version."""
        if spec.name in self._specs:
            self.unregister_spec(spec.name)
        self.register_spec(spec)
        self.register_handler(spec.name, handler)

    def specs(self) -> list[ToolSpec]:
        return [self._specs[name] for name in sorted(self._specs)]

    def roots(self) -> list[str]:
        """The directories this workspace's execution sandbox is confined to."""
        if self._runtime is None:
            return []
        return [str(root) for root in self._runtime.resolved_roots]

    def spec(self, name: str) -> ToolSpec:
        spec = self._specs.get(name)
        if spec is None:
            raise ToolNotFoundError(
                f"no tool {name!r} (known: {', '.join(sorted(self._specs))})"
            )
        return spec

    def registry(self) -> list[dict[str, Any]]:
        """Every tool with its risk and whether a grant currently covers it."""
        out = []
        for spec in self.specs():
            entry = spec.to_dict()
            if spec.capability:
                grants = self.permissions.grants(capability=spec.capability)
                entry["active_grants"] = len(grants)
            else:
                entry["active_grants"] = None
            out.append(entry)
        return out

    # -- runtime ----------------------------------------------------------
    def _cfg(self, key: str, default: Any) -> Any:
        if self.config is None:
            return default
        try:
            return self.config.get(key)
        except Exception:  # noqa: BLE001
            return default

    def roots(self) -> list[str]:
        """The directories this workspace's tools are confined to."""
        if self._runtime is None:
            return []
        return [str(root) for root in self._runtime.resolved_roots]

    @property
    def runtime(self) -> LocalToolRuntime:
        if self._runtime is None:
            raise ToolError("no tool runtime is configured for this workspace")
        return self._runtime

    # -- persistence ------------------------------------------------------
    def register_handlers(self) -> None:
        self.coordinator.register("tool.record", self._apply_record)
        self.coordinator.register("tool.finish", self._apply_finish)

    def _apply_record(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        run = payload["run"]
        seq = int(tx.query("SELECT COALESCE(MAX(seq), 0) + 1 AS s FROM tool_runs")[0]["s"])
        tx.execute(
            "INSERT INTO tool_runs(id, task_id, tool_name, arguments, status, result, started_at,"
            " ended_at, duration_ms, error, permission_id, trace_event_id, approval_id, dry_run,"
            " truncated, seq) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run["id"], run.get("task_id"), run["tool"], json_text(run.get("arguments") or {}),
                run["status"], None, run["started_at"], run.get("ended_at"),
                run.get("duration_ms"), run.get("error"), run.get("permission_id"),
                run.get("trace_event_id"), run.get("approval_id"),
                1 if run.get("dry_run") else 0, 1 if run.get("truncated") else 0, seq,
            ),
        )
        return {"id": run["id"], "seq": seq}

    def _apply_finish(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute(
            "UPDATE tool_runs SET status=?, result=?, ended_at=?, duration_ms=?, error=?,"
            " permission_id=COALESCE(?, permission_id), approval_id=COALESCE(?, approval_id),"
            " trace_event_id=COALESCE(?, trace_event_id), truncated=?"
            " WHERE id=?",
            (
                payload["status"], json_text(payload.get("result") or {}), payload.get("ended_at"),
                payload.get("duration_ms"), payload.get("error"), payload.get("permission_id"),
                payload.get("approval_id"), payload.get("trace_event_id"),
                1 if payload.get("truncated") else 0, payload["id"],
            ),
        )
        return {"id": payload["id"], "status": payload["status"]}

    def runs(self, *, tool: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        sql = "SELECT * FROM tool_runs"
        params: list[Any] = []
        if tool:
            sql += " WHERE tool_name = ?"
            params.append(tool)
        sql += " ORDER BY seq DESC, started_at DESC LIMIT ?"
        params.append(int(limit))
        rows = self.store.query(sql, params)
        for row in rows:
            if row.get("arguments"):
                try:
                    row["arguments"] = json.loads(row["arguments"])
                except json.JSONDecodeError:  # pragma: no cover
                    pass
            if row.get("result"):
                try:
                    row["result"] = json.loads(row["result"])
                except json.JSONDecodeError:  # pragma: no cover
                    pass
        return rows

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self.store.query_one("SELECT * FROM tool_runs WHERE id = ?", (run_id,))
        if row is None:
            raise NotFoundError(f"no tool run {run_id}")
        return row

    # -- execution --------------------------------------------------------
    def execute(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        dry_run: bool = False,
        context: ToolContext | None = None,
        requester: str = "tool",
        permission_subject: str | None = None,
    ) -> ToolRun:
        """Run a tool.

        ``permission_subject`` defaults to the tool's own name. The MCP server passes a
        different subject, so a grant for the tool does not automatically authorise a
        remote caller that happens to ask for it.
        """
        spec = self.spec(name)
        context = context or ToolContext()
        args = _coerce(dict(arguments or {}), spec)
        if dry_run and not spec.supports_dry_run:
            raise ToolValidationError(f"{spec.name} cannot be dry-run (it has no preview)")

        run = ToolRun(
            id=new_id("tr_"),
            tool=spec.name,
            status="running",
            arguments=args,
            started_at=iso_now(),
            dry_run=dry_run,
        )

        blocked = self._preflight(spec, args)
        if blocked is not None:
            return self._refuse(run, spec, blocked, context, approval_id=None, refused_by="denylist")

        decision: PermissionDecision | None = None
        if spec.capability:
            decision = self.permissions.check(
                spec.capability,
                subject=permission_subject or spec.name,
                conversation_id=context.conversation_id,
                task_id=context.task_id,
                project_id=context.project_id,
                consume=True,
                purpose=context.purpose or f"{spec.name} via {requester}",
            )
            if not decision.allowed:
                return self._refuse(
                run, spec, decision.reason, context,
                approval_id=decision.approval_id, refused_by="permission",
            )

        self._write(
            "tool.record",
            {
                "run": {
                    **run.to_dict(),
                    "task_id": context.task_id,
                    "permission_id": decision.grant_id if decision else None,
                    "approval_id": decision.approval_id if decision else None,
                }
            },
        )
        event_id = self.trace(
            "tool_call",
            spec.name,
            status="running",
            conversation_id=context.conversation_id,
            task_id=context.task_id,
            project_id=context.project_id,
            payload={
                "run_id": run.id,
                "tool": spec.name,
                "arguments": args,
                "capability": spec.capability,
                "grant_id": decision.grant_id if decision else None,
                "dry_run": dry_run,
            },
        )
        run.permission_id = decision.grant_id if decision else None
        run.decision = decision.reason if decision else "no capability needed"

        failure: Exception | None = None
        try:
            result = self._dispatch(spec, args, dry_run=dry_run)
            run.result = result
            run.truncated = bool(result.get("truncated"))
            run.status = "succeeded" if _result_ok(spec, result) else "failed"
            if run.status == "failed" and not run.error:
                run.error = _failure_reason(spec, result)
        except Exception as exc:  # noqa: BLE001 - the run must be closed before re-raising
            failure = exc
            run.status = "failed"
            run.error = getattr(exc, "message", None) or str(exc)
            run.result = None
        run.ended_at = iso_now()
        run.duration_ms = _elapsed_ms(run.started_at, run.ended_at)
        self._write(
            "tool.finish",
            {
                "id": run.id,
                "status": run.status,
                "result": run.result,
                "ended_at": run.ended_at,
                "duration_ms": run.duration_ms,
                "error": run.error,
                "permission_id": run.permission_id,
                "approval_id": None,
                "trace_event_id": event_id,
                "truncated": run.truncated,
            },
        )
        self.trace(
            "tool_call",
            spec.name,
            status=run.status,
            conversation_id=context.conversation_id,
            task_id=context.task_id,
            project_id=context.project_id,
            duration_ms=run.duration_ms,
            parent_id=event_id,
            error=run.error,
            payload={
                "run_id": run.id,
                "tool": spec.name,
                "dry_run": dry_run,
                "result": run.result,
                "permission_id": run.permission_id,
            },
        )
        self._record_file_change(spec, args, run, context)
        self._link_task(spec, context, run)
        run.seq = self.get_run(run.id).get("seq")
        if failure is not None:
            failure.run = run  # type: ignore[attr-defined]
            raise failure
        return run

    def _preflight(self, spec: ToolSpec, args: dict[str, Any]) -> str | None:
        if spec.name == "shell.run":
            import shlex
            from pathlib import Path

            command = str(args.get("command") or "")
            try:
                argv = shlex.split(command)
            except ValueError:
                return None  # the runtime reports the parse error
            if argv:
                program = Path(argv[0]).name
                denylist = {str(x) for x in (self._cfg("tools.shell_denylist", []) or [])}
                if program in denylist:
                    return (
                        f"{program!r} is on the shell denylist (tools.shell_denylist); "
                        "this cannot be approved"
                    )
        return None

    def _refuse(
        self,
        run: ToolRun,
        spec: ToolSpec,
        reason: str,
        context: ToolContext,
        *,
        approval_id: str | None,
        refused_by: str,
    ) -> ToolRun:
        run.status = "denied"
        run.error = reason
        run.approval_id = approval_id
        run.ended_at = iso_now()
        run.duration_ms = _elapsed_ms(run.started_at, run.ended_at)
        event_id = self.trace(
            "permission",
            "denied" if refused_by == "permission" else "blocked",
            status="denied",
            conversation_id=context.conversation_id,
            task_id=context.task_id,
            project_id=context.project_id,
            error=reason,
            payload={
                "run_id": run.id,
                "tool": spec.name,
                "capability": spec.capability,
                "arguments": run.arguments,
                "reason": reason,
                "approval_id": approval_id,
                "refused_by": refused_by,
            },
        )
        self._write(
            "tool.record",
            {
                "run": {
                    **run.to_dict(),
                    "task_id": context.task_id,
                    "trace_event_id": event_id,
                }
            },
        )
        self.trace(
            "tool_call",
            spec.name,
            status="denied",
            conversation_id=context.conversation_id,
            task_id=context.task_id,
            project_id=context.project_id,
            parent_id=event_id,
            error=reason,
            payload={"run_id": run.id, "approval_id": approval_id, "refused_by": refused_by},
        )
        self._link_task(spec, context, run)
        run.seq = self.get_run(run.id).get("seq")
        message = f"{spec.name}: {reason}"
        if approval_id:
            exc: PermissionDeniedError = ApprovalRequiredError(message)
        else:
            exc = PermissionDeniedError(message)
        exc.approval_id = approval_id  # type: ignore[attr-defined]
        exc.run = run  # type: ignore[attr-defined]
        exc.capability = spec.capability  # type: ignore[attr-defined]
        raise exc

    def _link_task(self, spec: ToolSpec, context: ToolContext, run: ToolRun) -> None:
        """Record a tool call on the task's timeline, if the call belongs to a task."""
        tasks = getattr(self, "tasks", None)
        if tasks is None or not context.task_id:
            return
        try:
            tasks.link(context.task_id, tools=[spec.name])
            detail = f"{spec.name} {run.status}"
            if run.error:
                detail += f": {run.error[:300]}"
            tasks.log(context.task_id, "tool", detail=detail)
        except Exception:  # noqa: BLE001 - bookkeeping must never fail the call
            pass

    def _record_file_change(
        self, spec: ToolSpec, args: dict[str, Any], run: ToolRun, context: ToolContext
    ) -> None:
        if spec.name not in {"fs.write", "fs.write_bytes", "fs.delete"}:
            return
        if run.status != "succeeded" or run.dry_run or not run.result:
            return
        self.trace(
            "file_change",
            run.result.get("path") or args.get("path"),
            status="ok",
            conversation_id=context.conversation_id,
            task_id=context.task_id,
            project_id=context.project_id,
            payload={
                "tool": spec.name,
                "run_id": run.id,
                "path": run.result.get("path"),
                "bytes": run.result.get("bytes_written") or run.result.get("bytes"),
                "sha256": run.result.get("sha256"),
                "previous_sha256": run.result.get("previous_sha256"),
                "deleted": bool(run.result.get("deleted")),
                "dry_run": run.dry_run,
            },
        )

    def _dispatch(self, spec: ToolSpec, args: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        runtime = self.runtime
        if spec.name == "fs.read":
            return runtime.read_text(
                args["path"],
                start_line=int(args.get("start_line") or 1),
                max_lines=int(args["max_lines"]) if args.get("max_lines") else None,
            )
        if spec.name == "fs.list":
            return runtime.list_dir(args.get("path") or ".", limit=int(args.get("limit") or 500))
        if spec.name == "fs.probe":
            return runtime.probe_file(
                args["path"],
                head_bytes=int(args["head_bytes"]) if args.get("head_bytes") else 4096,
            )
        if spec.name == "fs.write":
            return runtime.write_text(
                args["path"],
                args["content"],
                create_parents=bool(args.get("create_parents", True)),
                append=bool(args.get("append", False)),
                dry_run=dry_run,
            )
        if spec.name == "fs.write_bytes":
            try:
                payload = base64.b64decode(args["content_base64"], validate=True)
            except (ValueError, TypeError) as exc:
                raise ToolValidationError(f"content_base64 is not valid base64: {exc}") from exc
            return runtime.write_bytes(
                args["path"], payload,
                create_parents=bool(args.get("create_parents", True)),
                dry_run=dry_run,
            )
        if spec.name == "fs.delete":
            return runtime.delete(args["path"], dry_run=dry_run)
        if spec.name == "shell.run":
            return runtime.run(
                args["command"],
                cwd=args.get("cwd"),
                timeout=int(args["timeout"]) if args.get("timeout") else int(self._cfg("tools.timeout_seconds", 60)),
            )
        if spec.name == "net.fetch":
            from archx_agent.adapters.net_fetch import fetch_limits, fetch_url

            limits = fetch_limits(self.config)
            allow_private = (
                args["allow_private_hosts"]
                if "allow_private_hosts" in args
                else limits["allow_private_hosts"]
            )
            result = fetch_url(
                args["url"],
                timeout=float(args.get("timeout") or limits["timeout_seconds"]),
                max_bytes=int(args.get("max_bytes") or limits["max_bytes"]),
                max_redirects=int(args.get("max_redirects") or limits["max_redirects"]),
                allow_private_hosts=bool(allow_private),
            )
            # The full text can be large; the run result keeps a bounded copy and says so.
            keep = int(self._cfg("tools.fetch_store_chars", 20000))
            if len(result.get("text") or "") > keep:
                result["text"] = result["text"][:keep]
                result["text_truncated"] = True
            else:
                result["text_truncated"] = False
            result["limits"] = limits
            return result
        extra = self._handlers.get(spec.name)
        if extra is not None:
            return extra(args)
        if spec.name == "archx.info":
            info = dict(self._info_provider()) if self._info_provider else {}
            info["tool_limits"] = runtime.limits()
            return info
        raise ToolNotFoundError(f"tool {spec.name!r} has no handler")  # pragma: no cover


def _result_ok(spec: ToolSpec, result: dict[str, Any]) -> bool:
    if spec.name == "shell.run":
        return result.get("exit_code") == 0 and not result.get("timed_out")
    return True


def _failure_reason(spec: ToolSpec, result: dict[str, Any]) -> str:
    if spec.name == "shell.run":
        if result.get("timed_out"):
            return f"command timed out after {result.get('timeout_seconds')}s"
        return f"command exited with {result.get('exit_code')}"
    return "the tool reported a failure"


def _elapsed_ms(started_at: str, ended_at: str) -> float:
    from archx_agent.helpers.timeutil import parse_iso

    return round((parse_iso(ended_at) - parse_iso(started_at)).total_seconds() * 1000, 3)


__all__ = [
    "BUILTIN_SPECS",
    "BUILTIN_TOOLS",
    "TOOL_TABLES",
    "ToolContext",
    "ToolManager",
    "ToolRun",
    "ToolSpec",
]
