"""Agent workflows: a definition (data) plus ordered step records.

A workflow is *not* a program. It is JSON that names steps; the step kinds are fixed and
every step that can touch the machine goes through the tool registry, which means through
the permission centre. A workflow cannot grant itself a capability, cannot invent a tool,
and cannot widen a scope. That is the whole safety story, and it is why the definition
format is deliberately small.

Two modes:

``user``
    the user wrote (or picked) the steps; running it needs no model approval.
``ai``
    a model proposed the steps. The plan is stored as ``proposed`` and cannot run until a
    human approves it. The model is a planner, never an authority.

Step kinds:

``model``      ask a model a prompt (through the ordinary chat path, with its budgets)
``tool``       run a registry tool with arguments (rendered templates allowed)
``memory``     search the six memory systems and use the hits as the step output
``note``       a literal piece of text, useful for stitching prompts together
``checkpoint`` a human gate: the run refuses to pass it without explicit approval
``subagent``   a child task with its own conversation and steps, returning its summary
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from archx_agent.helpers.exceptions import ConflictError, NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now, new_id

from .base import BaseManager

WORKFLOW_TABLES = ("workflows", "workflow_steps")

STEP_KINDS = ("model", "tool", "memory", "note", "checkpoint", "subagent")
MODES = ("user", "ai")
STATUSES = ("proposed", "approved", "running", "completed", "failed", "cancelled")
TERMINAL = frozenset({"completed", "failed", "cancelled"})

MAX_DEPTH = 2
_TEMPLATE_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.\-]+)\s*\}\}")


@dataclass
class StepSpec:
    kind: str
    title: str = ""
    prompt: str | None = None
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    query: str | None = None
    text: str | None = None
    goal: str | None = None
    steps: list["StepSpec"] = field(default_factory=list)
    model: str | None = None
    continue_on_error: bool = False
    limit: int = 5

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind, "title": self.title or self.kind}
        for key in ("prompt", "tool", "query", "text", "goal", "model"):
            value = getattr(self, key)
            if value is not None:
                data[key] = value
        if self.args:
            data["args"] = self.args
        if self.steps:
            data["steps"] = [step.to_dict() for step in self.steps]
        if self.continue_on_error:
            data["continue_on_error"] = True
        if self.kind == "memory" and self.limit != 5:
            data["limit"] = self.limit
        return data


@dataclass
class Workflow:
    id: str
    name: str
    mode: str
    status: str
    definition: dict[str, Any]
    created_at: str
    updated_at: str
    goal: str = ""
    model_id: str | None = None
    task_id: str | None = None
    conversation_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def steps(self) -> list[StepSpec]:
        return parse_steps(self.definition.get("steps"))

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL

    def to_dict(self, *, with_definition: bool = True) -> dict[str, Any]:
        data = {
            "id": self.id,
            "name": self.name,
            "mode": self.mode,
            "status": self.status,
            "goal": self.goal,
            "model_id": self.model_id,
            "task_id": self.task_id,
            "conversation_id": self.conversation_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "metadata": dict(self.metadata),
            "step_count": len(self.steps),
        }
        if with_definition:
            data["definition"] = dict(self.definition)
        return data


@dataclass
class WorkflowStep:
    id: str
    workflow_id: str
    seq: int
    kind: str
    status: str
    title: str = ""
    spec: dict[str, Any] = field(default_factory=dict)
    started_at: str | None = None
    ended_at: str | None = None
    output: str | None = None
    error: str | None = None
    task_id: str | None = None
    tokens: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "seq": self.seq,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "spec": dict(self.spec),
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "output": self.output,
            "error": self.error,
            "task_id": self.task_id,
            "tokens": self.tokens,
            "metadata": dict(self.metadata),
        }


# --------------------------------------------------------------------------
# parsing + validation
# --------------------------------------------------------------------------
_STEP_KEYS = {
    "kind", "title", "prompt", "tool", "args", "query", "text", "goal", "steps",
    "model", "continue_on_error", "limit",
}


def parse_step(raw: Mapping[str, Any], *, index: int = 0) -> StepSpec:
    if not isinstance(raw, Mapping):
        raise ValidationError(f"step {index + 1} must be an object, got {type(raw).__name__}")
    unknown = sorted(set(raw) - _STEP_KEYS)
    if unknown:
        raise ValidationError(
            f"step {index + 1} has unknown field(s): {', '.join(unknown)} "
            f"(known: {', '.join(sorted(_STEP_KEYS))})"
        )
    kind = str(raw.get("kind") or "").strip().lower()
    if kind not in STEP_KINDS:
        raise ValidationError(
            f"step {index + 1} has unknown kind {kind!r} (known: {', '.join(STEP_KINDS)})"
        )
    title = str(raw.get("title") or "").strip()
    step = StepSpec(
        kind=kind,
        title=title,
        prompt=_text_or_none(raw.get("prompt")),
        tool=_text_or_none(raw.get("tool")),
        query=_text_or_none(raw.get("query")),
        text=_text_or_none(raw.get("text")),
        goal=_text_or_none(raw.get("goal")),
        model=_text_or_none(raw.get("model")),
        continue_on_error=bool(raw.get("continue_on_error")),
        limit=_limit(raw.get("limit")),
    )
    args = raw.get("args") or {}
    if not isinstance(args, Mapping):
        raise ValidationError(f"step {index + 1} ({kind}) args must be an object")
    step.args = {str(key): value for key, value in args.items()}
    nested = raw.get("steps") or []
    if not isinstance(nested, list):
        raise ValidationError(f"step {index + 1} ({kind}) steps must be a list")
    step.steps = [parse_step(item, index=position) for position, item in enumerate(nested)]
    if step.kind == "model" and not step.prompt:
        raise ValidationError(f"step {index + 1} is a model step without a prompt")
    if step.kind == "tool" and not step.tool:
        raise ValidationError(f"step {index + 1} is a tool step without a tool name")
    if step.kind == "memory" and not step.query:
        raise ValidationError(f"step {index + 1} is a memory step without a query")
    if step.kind == "note" and not step.text:
        raise ValidationError(f"step {index + 1} is a note step without text")
    if step.kind == "subagent" and not step.goal:
        raise ValidationError(f"step {index + 1} is a subagent step without a goal")
    if step.kind != "subagent" and step.steps:
        raise ValidationError(f"step {index + 1} ({kind}) cannot contain nested steps")
    if step.limit < 1 or step.limit > 50:
        raise ValidationError(f"step {index + 1} limit must be between 1 and 50")
    if not step.title:
        step.title = _default_title(step)
    return step


def _limit(value: Any) -> int:
    if value is None:
        return 5
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"step limit must be an integer, got {value!r}") from exc


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text.strip() else None


def _default_title(step: StepSpec) -> str:
    if step.kind == "model":
        return (step.prompt or "model")[:60]
    if step.kind == "tool":
        return f"{step.tool}"
    if step.kind == "memory":
        return f"recall: {step.query}"
    if step.kind == "subagent":
        return f"subagent: {step.goal}"[:60]
    return step.kind


def parse_steps(raw: Any) -> list[StepSpec]:
    if raw in (None, ""):
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:  # pragma: no cover - callers parse first
            raise ValidationError(f"steps are not valid JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise ValidationError("steps must be a list")
    return [parse_step(item, index=position) for position, item in enumerate(raw)]


def count_steps(steps: Sequence[StepSpec]) -> int:
    total = 0
    for step in steps:
        total += 1
        total += count_steps(step.steps)
    return total


def validate_definition(
    definition: Mapping[str, Any],
    *,
    tools=None,
    max_steps: int = 40,
    existing_workflows: set[str] | None = None,
) -> dict[str, Any]:
    """Validate a workflow definition and return a normalised copy.

    ``tools`` is the live registry (or ``None`` to skip the tool-existence check). A tool
    that does not exist is refused here rather than silently skipped at run time: a plan
    that names a tool the machine does not have is wrong, not merely unlucky.
    """
    if not isinstance(definition, Mapping):
        raise ValidationError("a workflow definition must be a JSON object")
    known = {"name", "goal", "mode", "steps", "model", "metadata", "description"}
    unknown = sorted(set(definition) - known)
    if unknown:
        raise ValidationError(
            f"unknown workflow field(s): {', '.join(unknown)} (known: {', '.join(sorted(known))})"
        )
    name = str(definition.get("name") or "").strip()
    if not name:
        raise ValidationError("a workflow needs a name")
    if len(name) > 120:
        raise ValidationError("a workflow name must be 120 characters or fewer")
    goal = str(definition.get("goal") or "").strip()
    mode = str(definition.get("mode") or "user").strip().lower()
    if mode not in MODES:
        raise ValidationError(f"unknown workflow mode {mode!r} (known: {', '.join(MODES)})")
    steps = parse_steps(definition.get("steps"))
    if not steps:
        raise ValidationError("a workflow needs at least one step")
    total = count_steps(steps)
    if total > max_steps:
        raise ValidationError(
            f"the workflow has {total} steps, above agent.max_steps={max_steps}"
        )
    metadata = definition.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        raise ValidationError("workflow metadata must be an object")
    model = _text_or_none(definition.get("model"))

    if tools is not None:
        for step in _walk(steps):
            if step.kind != "tool":
                continue
            try:
                tools.spec(str(step.tool))
            except Exception as exc:  # noqa: BLE001 - ToolNotFoundError is the normal case
                message = getattr(exc, "message", None) or str(exc)
                raise ValidationError(
                    f"step '{step.title}' names a tool that is not registered: {message}"
                ) from exc

    return {
        "name": name,
        "goal": goal,
        "mode": mode,
        "model": model,
        "steps": [step.to_dict() for step in steps],
        "metadata": dict(metadata),
    }


def _walk(steps: Sequence[StepSpec]):
    for step in steps:
        yield step
        yield from _walk(step.steps)


def render(template: str, context: Mapping[str, Any]) -> str:
    """Substitute ``{{name}}`` placeholders, refusing anything unknown.

    A silently-rendered-as-empty placeholder would let a plan run with an argument the
    author did not intend, so an unknown name is a validation error naming what is
    available.
    """

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context:
            available = ", ".join(sorted(context)) or "none"
            raise ValidationError(
                f"unknown template variable {{{{{key}}}}} (available: {available})"
            )
        value = context[key]
        return value if isinstance(value, str) else json_text(value)

    return _TEMPLATE_RE.sub(replace, template)


def render_inputs(value: Any, inputs: Mapping[str, Any]) -> Any:
    """Substitute only ``{{input.*}}`` placeholders, leaving run-time ones alone.

    Templates are rendered twice in their life: inputs when the workflow is created, and
    step references when a step actually runs. Replacing everything now would fail on
    ``{{step.1.output}}`` - which is not known yet - so this pass is deliberately partial.
    """

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if not key.startswith("input."):
            return match.group(0)
        name = key[len("input."):]
        if name not in inputs:
            raise ValidationError(
                f"template needs --input {name}=... (given: {', '.join(sorted(inputs)) or 'none'})"
            )
        value = inputs[name]
        return value if isinstance(value, str) else json_text(value)

    if isinstance(value, str):
        return _TEMPLATE_RE.sub(replace, value)
    if isinstance(value, Mapping):
        return {key: render_inputs(item, inputs) for key, item in value.items()}
    if isinstance(value, list):
        return [render_inputs(item, inputs) for item in value]
    return value


def render_value(value: Any, context: Mapping[str, Any]) -> Any:
    if isinstance(value, str):
        return render(value, context)
    if isinstance(value, Mapping):
        return {key: render_value(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [render_value(item, context) for item in value]
    return value


# --------------------------------------------------------------------------
# manager
# --------------------------------------------------------------------------
def _workflow_from_row(row: Mapping[str, Any]) -> Workflow:
    return Workflow(
        id=row["id"],
        name=row["name"],
        mode=row["mode"],
        status=row["status"],
        definition=json.loads(row["definition"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        goal=row.get("goal") or "",
        model_id=row.get("model_id"),
        task_id=row.get("task_id"),
        conversation_id=row.get("conversation_id"),
        started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
        error=row.get("error"),
        metadata=json.loads(row["metadata"]) if row.get("metadata") else {},
    )


def _step_from_row(row: Mapping[str, Any]) -> WorkflowStep:
    return WorkflowStep(
        id=row["id"],
        workflow_id=row["workflow_id"],
        seq=int(row["seq"]),
        kind=row["kind"],
        status=row["status"],
        title=row.get("title") or "",
        spec=json.loads(row["spec"]) if row.get("spec") else {},
        started_at=row.get("started_at"),
        ended_at=row.get("ended_at"),
        output=row.get("output"),
        error=row.get("error"),
        task_id=row.get("task_id"),
        tokens=int(row.get("tokens") or 0),
        metadata=json.loads(row["metadata"]) if row.get("metadata") else {},
    )


class WorkflowManager(BaseManager):
    """Definition records, status transitions and ordered step rows."""

    tables = WORKFLOW_TABLES

    def __init__(self, store, coordinator, *, events=None, config=None, tools=None) -> None:
        self.config = config
        self.tools = tools
        super().__init__(store, coordinator, events=events)

    def _cfg(self, key: str, default: Any) -> Any:
        if self.config is None:
            return default
        try:
            return self.config.get(key)
        except Exception:  # noqa: BLE001
            return default

    def register_handlers(self) -> None:
        self.coordinator.register("workflow.create", self._apply_create)
        self.coordinator.register("workflow.update", self._apply_update)
        self.coordinator.register("workflow.step", self._apply_step)
        self.coordinator.register("workflow.step_update", self._apply_step_update)

    def _apply_create(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        w = payload["workflow"]
        tx.execute(
            "INSERT INTO workflows(id, name, mode, status, goal, definition, model_id, task_id,"
            " conversation_id, created_at, updated_at, started_at, finished_at, error, metadata)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                w["id"], w["name"], w["mode"], w["status"], w.get("goal"),
                json_text(w["definition"]), w.get("model_id"), w.get("task_id"),
                w.get("conversation_id"), w["created_at"], w["updated_at"],
                w.get("started_at"), w.get("finished_at"), w.get("error"),
                json_text(w.get("metadata") or {}),
            ),
        )
        return {"id": w["id"]}

    def _apply_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        fields = dict(payload["fields"])
        if "definition" in fields:
            fields["definition"] = json_text(fields["definition"])
        if "metadata" in fields:
            fields["metadata"] = json_text(fields["metadata"] or {})
        sets = ", ".join(f"{key} = ?" for key in fields)
        tx.execute(
            f"UPDATE workflows SET {sets}, updated_at = ? WHERE id = ?",
            [*fields.values(), iso_now(), payload["id"]],
        )
        return {"id": payload["id"]}

    def _apply_step(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        s = payload["step"]
        tx.execute(
            "INSERT INTO workflow_steps(id, workflow_id, seq, kind, title, spec, status,"
            " started_at, ended_at, output, error, task_id, tokens, metadata)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                s["id"], s["workflow_id"], s["seq"], s["kind"], s.get("title"),
                json_text(s.get("spec") or {}), s["status"], s.get("started_at"),
                s.get("ended_at"), s.get("output"), s.get("error"), s.get("task_id"),
                int(s.get("tokens") or 0), json_text(s.get("metadata") or {}),
            ),
        )
        return {"id": s["id"], "seq": s["seq"]}

    def _apply_step_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        fields = dict(payload["fields"])
        for key in ("metadata", "spec"):
            if key in fields:
                fields[key] = json_text(fields[key] or {})
        sets = ", ".join(f"{key} = ?" for key in fields)
        tx.execute(
            f"UPDATE workflow_steps SET {sets} WHERE id = ?",
            [*fields.values(), payload["id"]],
        )
        return {"id": payload["id"]}

    # -- creation ----------------------------------------------------------
    def create(
        self,
        definition: Mapping[str, Any],
        *,
        mode: str | None = None,
        status: str = "approved",
        model_id: str | None = None,
        goal: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Workflow:
        normalised = validate_definition(
            {**dict(definition), "mode": mode or definition.get("mode") or "user"},
            tools=self.tools,
            max_steps=int(self._cfg("agent.max_steps", 40)),
        )
        if status not in STATUSES:
            raise ValidationError(f"unknown workflow status {status!r}")
        now = iso_now()
        workflow = Workflow(
            id=new_id("wf_"),
            name=normalised["name"],
            mode=normalised["mode"],
            status=status,
            definition=normalised,
            created_at=now,
            updated_at=now,
            goal=(goal if goal is not None else normalised.get("goal")) or "",
            model_id=model_id or normalised.get("model"),
            metadata={**normalised.get("metadata", {}), **(metadata or {})},
        )
        self._write("workflow.create", {"workflow": workflow.to_dict()})
        self.trace(
            "agent_run",
            "workflow.created",
            status="ok",
            task_id=workflow.task_id,
            payload={
                "workflow_id": workflow.id,
                "name": workflow.name,
                "mode": workflow.mode,
                "status": workflow.status,
                "steps": len(workflow.steps),
            },
        )
        return self.get(workflow.id)

    # -- state transitions -------------------------------------------------
    def _update(self, workflow_id: str, **fields: Any) -> Workflow:
        self.get(workflow_id)
        self._write("workflow.update", {"id": workflow_id, "fields": fields})
        return self.get(workflow_id)

    def approve(self, workflow_id: str, *, by: str = "user:cli") -> Workflow:
        wf = self.get(workflow_id)
        if wf.status != "proposed":
            raise ConflictError(f"workflow {workflow_id} is {wf.status}, not proposed")
        self._trace_status(wf, "workflow.approved", {"by": by})
        return self._update(workflow_id, status="approved", metadata={**wf.metadata, "approved_by": by})

    def reject(self, workflow_id: str, *, reason: str = "rejected by the user") -> Workflow:
        wf = self.get(workflow_id)
        if wf.terminal:
            raise ConflictError(f"workflow {workflow_id} already {wf.status}")
        self._trace_status(wf, "workflow.rejected", {"reason": reason}, status="warning")
        return self._update(
            workflow_id, status="cancelled", error=reason, finished_at=iso_now()
        )

    def cancel(self, workflow_id: str, *, reason: str = "cancelled by the user") -> Workflow:
        wf = self.get(workflow_id)
        if wf.terminal:
            raise ConflictError(f"workflow {workflow_id} already {wf.status}")
        self._trace_status(wf, "workflow.cancelled", {"reason": reason}, status="warning")
        return self._update(
            workflow_id, status="cancelled", error=reason, finished_at=iso_now()
        )

    def mark_running(self, workflow_id: str, *, task_id: str | None = None,
                     conversation_id: str | None = None) -> Workflow:
        wf = self.get(workflow_id)
        if wf.terminal:
            raise ConflictError(f"workflow {workflow_id} already {wf.status}")
        fields: dict[str, Any] = {"status": "running", "started_at": wf.started_at or iso_now()}
        if task_id:
            fields["task_id"] = task_id
        if conversation_id:
            fields["conversation_id"] = conversation_id
        self._trace_status(wf, "workflow.started", {"task_id": task_id})
        return self._update(workflow_id, **fields)

    def finish(
        self,
        workflow_id: str,
        *,
        status: str = "completed",
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Workflow:
        if status not in ("completed", "failed", "cancelled"):
            raise ValidationError(f"a workflow cannot finish as {status!r}")
        wf = self.get(workflow_id)
        fields: dict[str, Any] = {"status": status, "finished_at": iso_now(), "error": error}
        if metadata:
            fields["metadata"] = {**wf.metadata, **metadata}
        self._trace_status(
            wf, f"workflow.{status}", {"error": error}, status="ok" if status == "completed" else "error"
        )
        return self._update(workflow_id, **fields)

    def _trace_status(self, wf: Workflow, name: str, payload: dict[str, Any], *, status: str = "ok") -> None:
        self.trace(
            "agent_run",
            name,
            status=status,
            task_id=wf.task_id,
            payload={"workflow_id": wf.id, "name": wf.name, **payload},
        )

    # -- steps -------------------------------------------------------------
    def add_step(self, workflow_id: str, *, seq: int, kind: str, title: str,
                 spec: Mapping[str, Any] | None = None, status: str = "running",
                 task_id: str | None = None) -> WorkflowStep:
        self.get(workflow_id)
        step = WorkflowStep(
            id=new_id("ws_"),
            workflow_id=workflow_id,
            seq=int(seq),
            kind=kind,
            title=title,
            spec=dict(spec or {}),
            status=status,
            started_at=iso_now() if status == "running" else None,
            task_id=task_id,
        )
        self._write("workflow.step", {"step": step.to_dict()})
        return self.step(step.id)

    def finish_step(
        self,
        step_id: str,
        *,
        status: str,
        output: str | None = None,
        error: str | None = None,
        tokens: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> WorkflowStep:
        if status not in ("succeeded", "failed", "skipped"):
            raise ValidationError(f"a step cannot finish as {status!r}")
        fields: dict[str, Any] = {
            "status": status,
            "ended_at": iso_now(),
            "output": (output or "")[:20000] or None,
            "error": (error or "")[:2000] or None,
            "tokens": int(tokens),
        }
        if metadata:
            fields["metadata"] = metadata
        self._write("workflow.step_update", {"id": step_id, "fields": fields})
        return self.step(step_id)

    def step(self, step_id: str) -> WorkflowStep:
        row = self.store.query_one("SELECT * FROM workflow_steps WHERE id = ?", (step_id,))
        if row is None:
            raise NotFoundError(f"no workflow step {step_id}")
        return _step_from_row(row)

    def steps(self, workflow_id: str) -> list[WorkflowStep]:
        rows = self.store.query(
            "SELECT * FROM workflow_steps WHERE workflow_id = ? ORDER BY seq", (workflow_id,)
        )
        return [_step_from_row(row) for row in rows]

    # -- reads -------------------------------------------------------------
    def get(self, workflow_id: str) -> Workflow:
        row = self.store.query_one("SELECT * FROM workflows WHERE id = ?", (workflow_id,))
        if row is None:
            raise NotFoundError(f"no workflow {workflow_id}")
        return _workflow_from_row(row)

    def find(self, ref: str) -> Workflow | None:
        row = self.store.query_one("SELECT * FROM workflows WHERE id = ?", (ref,))
        if row is None:
            row = self.store.query_one(
                "SELECT * FROM workflows WHERE name = ? ORDER BY rowid DESC LIMIT 1", (ref,)
            )
        return _workflow_from_row(row) if row else None

    def require(self, ref: str) -> Workflow:
        workflow = self.find(ref)
        if workflow is None:
            raise NotFoundError(f"no workflow {ref}")
        return workflow

    def list(self, *, status: str | None = None, mode: str | None = None,
             limit: int = 20) -> list[Workflow]:
        sql = "SELECT * FROM workflows"
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            if status not in STATUSES:
                raise ValidationError(f"unknown workflow status {status!r}")
            clauses.append("status = ?")
            params.append(status)
        if mode:
            if mode not in MODES:
                raise ValidationError(f"unknown workflow mode {mode!r}")
            clauses.append("mode = ?")
            params.append(mode)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY rowid DESC LIMIT ?"
        params.append(int(limit))
        return [_workflow_from_row(row) for row in self.store.query(sql, params)]

    def stats(self) -> dict[str, Any]:
        rows = self.store.query(
            "SELECT status, COUNT(*) AS n FROM workflows GROUP BY status", ()
        )
        return {
            "total": sum(int(row["n"]) for row in rows),
            "by_status": {row["status"]: int(row["n"]) for row in rows},
            "steps": self.table_count("workflow_steps"),
        }


# --------------------------------------------------------------------------
# built-in user-directed templates
# --------------------------------------------------------------------------
TEMPLATES: dict[str, dict[str, Any]] = {
    "summarise-file": {
        "name": "summarise-file",
        "goal": "Read a file and summarise it",
        "mode": "user",
        "steps": [
            {"kind": "tool", "title": "read the file", "tool": "fs.read",
             "args": {"path": "{{input.path}}", "max_lines": 400}},
            {"kind": "model", "title": "summarise",
             "prompt": "Summarise the following file in three bullet points. Do not invent facts.\n\n{{step.1.output}}"},
            {"kind": "note", "title": "provenance", "text": "source: {{input.path}}"},
        ],
    },
    "check-and-report": {
        "name": "check-and-report",
        "goal": "Check the workspace facts and record a short report",
        "mode": "user",
        "steps": [
            {"kind": "tool", "title": "workspace facts", "tool": "archx.info", "args": {}},
            {"kind": "checkpoint", "title": "human gate", "text": "review the facts before reporting"},
            {"kind": "model", "title": "report",
             "prompt": "Write a five-line status report from these facts:\n{{step.1.output}}"},
        ],
    },
}


__all__ = [
    "MODES",
    "STEP_KINDS",
    "STATUSES",
    "StepSpec",
    "TEMPLATES",
    "WORKFLOW_TABLES",
    "Workflow",
    "WorkflowManager",
    "WorkflowStep",
    "count_steps",
    "parse_step",
    "parse_steps",
    "render",
    "render_inputs",
    "render_value",
    "validate_definition",
]
