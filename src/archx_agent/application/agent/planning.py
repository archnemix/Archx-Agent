"""AgentRunner: planning operations."""

from __future__ import annotations

import json
from typing import Any
from archx_agent.helpers.exceptions import (
    ValidationError,
)
from archx_agent.managers.workflows import (
    Workflow,
    validate_definition,
)

from .records import PLAN_SYSTEM_PROMPT

class AgentRunnerPlanningMixin:
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
