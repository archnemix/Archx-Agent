"""Agent workflow execution: user-directed plans and model-proposed plans.

The runner is deliberately boring. It walks the steps of a stored workflow definition,
executes each one through the machinery that already exists (chat for model steps, the tool
registry for tool steps, memory search for memory steps), records the outcome, and stops on
the first failure unless the step says otherwise.

What it will not do:

* run a plan a model proposed without a human approving it (``--approve``);
* let a step grant a permission - tool steps go through :class:`ToolManager` and therefore
  through the permission centre, exactly like a hand-run tool;
* exceed the configured budgets (steps, wall clock, tokens) - it stops and says which;
* report a cancelled run as completed, even if the cancel arrived from another process.

Budgets and cancellation are checked *before* each step, which is the last moment at which
stopping is clean. A step already running is allowed to finish; a hang inside a step is
bounded by the job deadline the scheduler passes in (M26), not by killing a thread here.

Resumption is step granularity. A paused run leaves the workflow ``running`` with the step
rows it finished; ``run(resume=True)`` continues from the first step without a succeeded
row, reusing those outputs. It never replays a step that already ran, because replaying a
tool step could repeat a side effect.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    ArchxError,
    ConflictError,
    ValidationError,
)
from archx_agent.helpers.jsonio import json_text
from archx_agent.managers.tools import ToolContext
from archx_agent.managers.workflows import (
    StepSpec,
    Workflow,
    render_value,
    validate_definition,
)

PLAN_SYSTEM_PROMPT = (
    "You are a planner for a local-first assistant. Reply with ONE JSON object and nothing "
    "else. The object has keys: name (short), goal, and steps (a list). Each step has a "
    "kind: 'model' (with 'prompt'), 'tool' (with 'tool' and 'args'), 'memory' (with "
    "'query'), 'note' (with 'text'), or 'subagent' (with 'goal'). Use {{goal}} and "
    "{{step.N.output}} inside prompts to refer to earlier results. Only name tools from "
    "the provided list. Never invent capabilities; the user still has to grant them."
)

MAX_OUTPUT = 8000


@dataclass
class Budget:
    max_steps: int
    max_seconds: float
    token_budget: int
    max_subagents: int
    steps_done: int = 0
    tokens: int = 0
    subagents: int = 0
    started: float = field(default_factory=time.perf_counter)

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self.started

    def check(self) -> None:
        if self.elapsed > self.max_seconds:
            raise ValidationError(
                f"the workflow exceeded agent.max_wall_seconds={int(self.max_seconds)}s "
                f"after {self.steps_done} step(s)"
            )
        if self.tokens > self.token_budget:
            raise ValidationError(
                f"the workflow used {self.tokens} tokens, above agent.token_budget={self.token_budget}"
            )


@dataclass
class RunResult:
    workflow_id: str
    task_id: str
    status: str
    steps: list[dict[str, Any]]
    summary: str
    tokens: int
    elapsed_ms: float
    cancelled: bool = False
    approval_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "task_id": self.task_id,
            "status": self.status,
            "steps": self.steps,
            "summary": self.summary,
            "tokens": self.tokens,
            "elapsed_ms": self.elapsed_ms,
            "cancelled": self.cancelled,
            "approval_id": self.approval_id,
        }


class AgentRunner:
    """Executes stored workflows against this workspace."""

    def __init__(self, workspace) -> None:
        self.ws = workspace

    # -- entry points ------------------------------------------------------
    def run(
        self,
        ref: str,
        *,
        approve: bool = False,
        resume: bool = False,
        control: "Callable[[int], str | None] | None" = None,
    ) -> RunResult:
        """Execute a workflow.

        ``control`` is called before each step with the number of steps already finished
        and may return ``"pause"`` (stop cleanly at this boundary, raising
        :class:`RunPaused`), ``"cancel"``, or ``None`` to continue. It may also raise to
        abort the run (the scheduler uses that for a hard deadline).
        """
        workflow = self.ws.workflows.require(ref)
        if workflow.terminal:
            raise ConflictError(f"workflow {workflow.id} already {workflow.status}")
        if workflow.status == "running" and not resume:
            raise ConflictError(f"workflow {workflow.id} is already running")
        if workflow.status == "proposed" and not approve:
            raise ApprovalRequiredError(
                f"workflow {workflow.id} was proposed by a model and has not been approved; "
                f"review it with `archx-agent agent show {workflow.id}` and run with --approve"
            )
        if workflow.status == "proposed" and approve:
            self.ws.workflows.approve(workflow.id, by="user:cli (run --approve)")

        done: dict[int, Any] = {}
        if resume:
            if workflow.status != "running":
                raise ConflictError(
                    f"cannot resume workflow {workflow.id}: it is {workflow.status}"
                )
            for record in self.ws.workflows.steps(workflow.id):
                if record.status == "succeeded":
                    done[record.seq] = record
            found = self.ws.tasks.find(workflow.task_id) if workflow.task_id else None
            task = found.value if found is not None and found.is_ok else None
            if task is None or task.terminal:
                # The record of the first attempt is closed (a crash sweep marks it
                # interrupted). Continue under a fresh task instead of writing into a
                # finished one, and keep the link back to the attempt that was lost.
                task = self.ws.tasks.create(
                    "agent",
                    f"{workflow.name} (resumed): {workflow.goal or ''}".strip(": ")[:200],
                    start=True,
                    model_id=workflow.model_id,
                    metadata={
                        "workflow_id": workflow.id,
                        "mode": workflow.mode,
                        "resumed_from": workflow.task_id,
                    },
                )
                workflow = self.ws.workflows.mark_running(workflow.id, task_id=task.id)
            conversation_id = workflow.conversation_id
            if not conversation_id:
                conversation = self.ws.conversations.create(
                    title=f"workflow: {workflow.name}"[:200], model_id=workflow.model_id
                )
                conversation_id = conversation.id
                workflow = self.ws.workflows.mark_running(
                    workflow.id, conversation_id=conversation_id
                )
            self.ws.tasks.log(task.id, "resumed", detail=f"from step {len(done) + 1}")
        else:
            # A checkpoint is an *up-front* gate. Refusing here means nothing has run, so
            # re-running with --approve cannot repeat a side effect from an earlier attempt.
            checkpoints = [step for step in _walk(workflow.steps) if step.kind == "checkpoint"]
            if checkpoints and not approve:
                raise ApprovalRequiredError(
                    f"workflow {workflow.id} contains {len(checkpoints)} checkpoint(s) and has not "
                    f"been approved; review it with `archx-agent agent show {workflow.id}` and run "
                    "with --approve"
                )
            task = self.ws.tasks.create(
                "agent",
                f"{workflow.name}: {workflow.goal or ''}".strip(": ")[:200],
                start=True,
                model_id=workflow.model_id,
                metadata={"workflow_id": workflow.id, "mode": workflow.mode},
            )
            conversation = self.ws.conversations.create(
                title=f"workflow: {workflow.name}"[:200],
                model_id=workflow.model_id,
            )
            conversation_id = conversation.id
            workflow = self.ws.workflows.mark_running(
                workflow.id, task_id=task.id, conversation_id=conversation_id
            )
            self.ws.tasks.link(task.id, conversation_id=conversation_id)

        budget = Budget(
            max_steps=int(self.ws.config.get("agent.max_steps")),
            max_seconds=float(self.ws.config.get("agent.max_wall_seconds")),
            token_budget=int(self.ws.config.get("agent.token_budget")),
            max_subagents=int(self.ws.config.get("agent.max_subagents")),
        )
        started = time.perf_counter()
        steps: list[dict[str, Any]] = []
        outputs: dict[str, str] = {}
        context: dict[str, Any] = {
            "goal": workflow.goal,
            "workflow.id": workflow.id,
            "workflow.name": workflow.name,
            "task.id": task.id,
        }
        summary = ""
        try:
            for index, step in enumerate(workflow.steps, start=1):
                budget.check()
                signal = control(len(steps)) if control is not None else None
                if signal == "pause":
                    raise RunPaused(
                        f"paused before step {index}",
                        workflow_id=workflow.id,
                        task_id=task.id,
                        conversation_id=conversation_id,
                        cursor=len(steps),
                        steps=steps,
                    )
                if index in done:
                    finished = done[index]
                    steps.append(finished.to_dict())
                    value = finished.output or ""
                    outputs[f"step.{index}.output"] = value
                    context[f"step.{index}.output"] = value
                    summary = value
                    budget.steps_done += 1
                    budget.tokens += finished.tokens
                    continue
                current = self.ws.workflows.get(workflow.id)
                if signal == "cancel" and current.status != "cancelled":
                    current = self.ws.workflows.cancel(
                        workflow.id, reason="cancelled while running as a scheduled job"
                    )
                if current.status == "cancelled":
                    self.ws.tasks.cancel(task.id, "the workflow was cancelled")
                    self.ws.workflows.finish(workflow.id, status="cancelled", error="cancelled")
                    return RunResult(
                        workflow_id=workflow.id, task_id=task.id, status="cancelled",
                        steps=steps, summary=summary, tokens=budget.tokens,
                        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
                        cancelled=True,
                    )
                if budget.steps_done >= budget.max_steps:
                    raise ValidationError(
                        f"the workflow reached agent.max_steps={budget.max_steps} before step {index}"
                    )
                budget.steps_done += 1
                record = self.ws.workflows.add_step(
                    workflow.id, seq=self._next_seq(workflow.id), kind=step.kind,
                    title=step.title, spec=step.to_dict(), task_id=task.id,
                )
                self.ws.tasks.log(task.id, "step", detail=f"{index}. {step.kind}: {step.title}")
                try:
                    output, tokens, metadata = self._run_step(
                        step, context, workflow, task.id, conversation_id,
                        budget, index, approve=approve, depth=0,
                    )
                except BaseException as exc:
                    message = getattr(exc, "message", None) or str(exc)
                    approval_id = getattr(exc, "approval_id", None)
                    record = self.ws.workflows.finish_step(
                        record.id, status="failed", error=message, tokens=0,
                        metadata={"approval_id": approval_id} if approval_id else None,
                    )
                    steps.append(record.to_dict())
                    self.ws.tasks.log(task.id, "step_failed", detail=f"{index}: {message}")
                    if step.continue_on_error:
                        outputs[f"step.{index}.output"] = ""
                        context[f"step.{index}.output"] = ""
                        continue
                    raise
                budget.tokens += tokens
                value = output[:MAX_OUTPUT]
                record = self.ws.workflows.finish_step(
                    record.id, status="succeeded", output=value, tokens=tokens, metadata=metadata
                )
                steps.append(record.to_dict())
                outputs[f"step.{index}.output"] = value
                context[f"step.{index}.output"] = value
                summary = value
        except RunPaused:
            # A pause is not a failure: the workflow stays running and the step rows
            # already written are what a later resume continues from.
            self.ws.tasks.log(task.id, "paused", detail=f"at step {len(steps)}")
            raise
        except BaseException as exc:
            message = getattr(exc, "message", None) or str(exc)
            approval_id = getattr(exc, "approval_id", None)
            self.ws.workflows.finish(workflow.id, status="failed", error=message)
            failed = self.ws.tasks.fail(task.id, exc)
            self.ws.tasks.log(task.id, "workflow_failed", detail=message)
            if isinstance(exc, ApprovalRequiredError):
                raise
            raise WorkflowFailed(
                message, workflow_id=workflow.id, task_id=failed.id,
                approval_id=approval_id, steps=steps,
            ) from exc

        tokens = budget.tokens
        metadata = {
            "steps": len(steps),
            "tokens": tokens,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "subagents": budget.subagents,
        }
        self.ws.workflows.finish(workflow.id, status="completed", metadata=metadata)
        self.ws.tasks.log(task.id, "workflow_completed", detail=f"{len(steps)} step(s)")
        self.ws.tasks.complete(
            task.id,
            summary=summary[:500],
            outputs=[workflow.id],
            resource_use=metadata,
        )
        return RunResult(
            workflow_id=workflow.id,
            task_id=task.id,
            status="completed",
            steps=steps,
            summary=summary,
            tokens=tokens,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    # -- steps -------------------------------------------------------------
    def _run_step(
        self,
        step: StepSpec,
        context: dict[str, Any],
        workflow: Workflow,
        task_id: str,
        conversation_id: str,
        budget: Budget,
        index: int,
        *,
        approve: bool,
        depth: int,
    ) -> tuple[str, int, dict[str, Any]]:
        if step.kind == "model":
            prompt = render_value(step.prompt or "", context)
            reply = self.ws.chat.send(
                prompt,
                conversation_id=conversation_id,
                task_id=task_id,
                model_id=step.model or workflow.model_id,
            )
            tokens = reply.prompt_tokens + reply.completion_tokens
            return reply.text, tokens, {"model_id": reply.model.get("model_id"), "simulated": reply.simulated}
        if step.kind == "tool":
            arguments = render_value(dict(step.args), context)
            run = self.ws.tools.execute(
                str(step.tool),
                arguments,
                context=ToolContext(
                    task_id=task_id,
                    conversation_id=conversation_id,
                    purpose=f"workflow {workflow.id} step {index}",
                ),
                requester="agent",
            )
            return json_text(run.result or {}), 0, {"run_id": run.id, "status": run.status}
        if step.kind == "memory":
            query = render_value(step.query or "", context)
            outcome = self.ws.memory.search(str(query), limit=int(step.limit))
            lines = [
                f"- {hit.memory.title}: {hit.memory.content[:300]}"
                for hit in outcome.hits[: int(step.limit)]
            ]
            text = "\n".join(lines) or "(no memory matched)"
            return text, 0, {"hits": len(outcome.hits), "mode": outcome.mode, "degraded": outcome.degraded}
        if step.kind == "note":
            return str(render_value(step.text or "", context)), 0, {}
        if step.kind == "checkpoint":
            if not approve:
                raise ApprovalRequiredError(
                    f"step {index} is a checkpoint ({step.title}); nothing past it runs without "
                    "--approve"
                )
            return f"checkpoint {index} approved: {render_value(step.text or step.title, context)}", 0, {
                "checkpoint": True
            }
        if step.kind == "subagent":
            return self._run_subagent(
                step, context, workflow, task_id, budget, index, approve=approve, depth=depth
            )
        raise ValidationError(f"unknown step kind {step.kind!r}")  # pragma: no cover

    def _run_subagent(
        self,
        step: StepSpec,
        context: dict[str, Any],
        workflow: Workflow,
        parent_task_id: str,
        budget: Budget,
        index: int,
        *,
        approve: bool,
        depth: int,
    ) -> tuple[str, int, dict[str, Any]]:
        if depth + 1 > 2:
            raise ValidationError("subagent nesting is limited to two levels")
        budget.subagents += 1
        if budget.subagents > budget.max_subagents:
            raise ValidationError(
                f"the workflow started more than agent.max_subagents={budget.max_subagents} subagents"
            )
        goal = str(render_value(step.goal or "", context))
        child = self.ws.tasks.create(
            "agent",
            f"subagent: {step.title}"[:200],
            parent_task_id=parent_task_id,
            start=True,
            metadata={"workflow_id": workflow.id, "subagent": True, "depth": depth + 1},
        )
        conversation = self.ws.conversations.create(
            title=f"subagent: {step.title}"[:200], model_id=step.model or workflow.model_id
        )
        self.ws.tasks.link(child.id, conversation_id=conversation.id)
        child_context: dict[str, Any] = {
            "goal": goal,
            "workflow.id": workflow.id,
            "workflow.name": workflow.name,
            "task.id": child.id,
        }
        child_context.update({key: value for key, value in context.items() if key.startswith("input.")})
        steps = step.steps or [StepSpec(kind="model", title="answer", prompt=goal)]
        tokens = 0
        summary = ""
        try:
            for position, nested in enumerate(steps, start=1):
                budget.check()
                budget.steps_done += 1
                record = self.ws.workflows.add_step(
                    workflow.id, seq=self._next_seq(workflow.id), kind=nested.kind,
                    title=f"{step.title} / {nested.title}", spec=nested.to_dict(),
                    task_id=child.id,
                )
                output, used, metadata = self._run_step(
                    nested, child_context, workflow, child.id, conversation.id,
                    budget, index, approve=approve, depth=depth + 1,
                )
                tokens += used
                summary = output[:MAX_OUTPUT]
                child_context[f"step.{position}.output"] = summary
                self.ws.workflows.finish_step(
                    record.id, status="succeeded", output=summary, tokens=used, metadata=metadata
                )
        except BaseException as exc:
            message = getattr(exc, "message", None) or str(exc)
            self.ws.tasks.fail(child.id, exc)
            raise WorkflowFailed(message, workflow_id=workflow.id, task_id=child.id) from exc
        self.ws.tasks.complete(child.id, summary=summary[:500], outputs=[workflow.id])
        self.ws.tasks.log(parent_task_id, "subagent", detail=f"{step.title}: {summary[:120]}")
        return summary, tokens, {"subagent": True, "child_task_id": child.id, "steps": len(steps)}

    def _next_seq(self, workflow_id: str) -> int:
        return len(self.ws.workflows.steps(workflow_id)) + 1

    # -- planning ----------------------------------------------------------
    def plan(self, goal: str, *, model_id: str | None = None, name: str | None = None) -> Workflow:
        """Ask a model for a plan, validate it, and store it as ``proposed``.

        The model's reply is data. If it is not JSON, or names a tool that does not exist,
        nothing is stored and the planning task fails with the reason - we never turn prose
        into steps by guessing.
        """
        goal = (goal or "").strip()
        if not goal:
            raise ValidationError("a plan needs a goal")
        task = self.ws.tasks.create("agent", f"plan: {goal}"[:200], start=True, model_id=model_id)
        conversation = self.ws.conversations.create(title=f"plan: {goal}"[:200], model_id=model_id)
        self.ws.tasks.link(task.id, conversation_id=conversation.id)
        prompt = (
            f"Goal: {goal}\n\nAvailable tools (name: capability): "
            + ", ".join(
                f"{spec.name}: {spec.capability or 'none'}" for spec in self.ws.tools.specs()
            )
            + "\n\nReply with the JSON plan only."
        )
        try:
            reply = self.ws.chat.send(
                prompt,
                conversation_id=conversation.id,
                task_id=task.id,
                model_id=model_id,
                system_prompt=PLAN_SYSTEM_PROMPT,
            )
            definition = self._parse_plan(reply.text, goal=goal, name=name)
            definition = validate_definition(
                definition,
                tools=self.ws.tools,
                max_steps=int(self.ws.config.get("agent.max_steps")),
            )
        except BaseException as exc:
            self.ws.tasks.fail(task.id, exc)
            raise
        workflow = self.ws.workflows.create(
            definition,
            mode="ai",
            status="proposed",
            model_id=reply.model.get("model_id") or model_id,
            goal=goal,
            metadata={"plan_task_id": task.id, "planned_by": reply.model.get("model_id"), "simulated": reply.simulated},
        )
        self.ws.tasks.complete(
            task.id,
            summary=f"proposed workflow {workflow.id} with {len(workflow.steps)} step(s)",
            outputs=[workflow.id],
            resource_use={"prompt_tokens": reply.prompt_tokens, "completion_tokens": reply.completion_tokens},
        )
        self.ws.tasks.log(task.id, "plan", detail=f"workflow {workflow.id}: {len(workflow.steps)} step(s)")
        return workflow

    def _parse_plan(self, text: str, *, goal: str, name: str | None) -> dict[str, Any]:
        raw = (text or "").strip()
        candidate = raw
        if not candidate.startswith("{"):
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start == -1 or end <= start:
                raise ValidationError(
                    "the model did not return a plan: no JSON object was found in its reply. "
                    "Nothing was saved."
                )
            candidate = candidate[start : end + 1]
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ValidationError(
                f"the model's plan is not valid JSON ({exc}); nothing was saved"
            ) from exc
        if not isinstance(data, dict):
            raise ValidationError("the model's plan must be a JSON object; nothing was saved")
        data.setdefault("goal", goal)
        if name:
            data["name"] = name
        data.setdefault("name", f"plan: {goal}"[:120])
        data["mode"] = "ai"
        return data


class WorkflowFailed(ArchxError):
    """A run stopped because a step failed.

    Carries the workflow and task ids so a caller can report them without re-querying, and
    the approval id when the failure was a missing permission (the run is resumable after
    approval because nothing was granted and nothing ran).
    """

    def __init__(
        self,
        message: str,
        *,
        workflow_id: str | None = None,
        task_id: str | None = None,
        approval_id: str | None = None,
        steps: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.workflow_id = workflow_id
        self.task_id = task_id
        self.approval_id = approval_id
        self.steps = steps or []


class RunPaused(Exception):
    """A run stopped at a step boundary because a pause was requested.

    Everything already written stays: the workflow is still ``running``, the task is
    still open, and ``cursor`` says how many steps are done - which is exactly what
    ``run(resume=True)`` needs.
    """

    def __init__(
        self,
        message: str,
        *,
        workflow_id: str,
        task_id: str,
        conversation_id: str | None,
        cursor: int,
        steps: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.workflow_id = workflow_id
        self.task_id = task_id
        self.conversation_id = conversation_id
        self.cursor = cursor
        self.steps = steps or []


def _walk(steps):
    for step in steps:
        yield step
        yield from _walk(step.steps)


__all__ = [
    "AgentRunner",
    "Budget",
    "MAX_OUTPUT",
    "PLAN_SYSTEM_PROMPT",
    "RunPaused",
    "RunResult",
    "WorkflowFailed",
]
