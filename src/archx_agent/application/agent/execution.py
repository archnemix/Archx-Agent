"""AgentRunner: execution operations."""

from __future__ import annotations

import time
from typing import Any, Callable
from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    ConflictError,
    ValidationError,
)

from .records import MAX_OUTPUT, RunResult, WorkflowFailed, RunPaused, _walk

class AgentRunnerExecutionMixin:
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

        # Resolve the public override hook at call time, as before the package split.
        from archx_agent.application.agent import Budget

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

    def _next_seq(self, workflow_id: str) -> int:
        return len(self.ws.workflows.steps(workflow_id)) + 1
