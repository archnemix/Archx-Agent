"""AgentRunner: steps operations."""

from __future__ import annotations

from typing import Any
from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    ValidationError,
)
from archx_agent.helpers.jsonio import json_text
from archx_agent.managers.tools import ToolContext
from archx_agent.managers.workflows import (
    StepSpec,
    Workflow,
    render_value,
)

from .records import MAX_OUTPUT, Budget, WorkflowFailed

class AgentRunnerStepsMixin:
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
