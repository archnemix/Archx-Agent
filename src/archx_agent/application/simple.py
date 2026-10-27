"""Simple Mode: one box, one question, an honest answer.

Simple Mode is a *front door*, not a second application. Every intent it recognises is
executed by the machinery that already exists - chat, memory, search, workflows - and it
refuses, in plain language, anything that needs a decision the user has not made (a
permission, an approval, a missing model).

Two rules shape the design:

**Say what I did and why.** Each result carries ``intent`` and ``why``. A user who typed
"where did I write about database locks" should be able to see that the app searched rather
than guessed, and which sources it could not search.

**Never invent authority.** Simple Mode cannot grant a permission, approve a plan or run a
tool. When a path needs one, it stops and prints the exact command that would grant it.
Guessing here would turn a convenience feature into a privilege escalation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    ArchxError,
    ModelNotFoundError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from archx_agent.managers.workflows import TEMPLATES, render_inputs

INTENTS = ("chat", "search", "recall", "remember", "status", "workflow", "help")

_QUESTION_PREFIXES = (
    "what do you know about", "what have you learned about", "where did i", "where do i",
    "where is", "where are", "what did i", "what do i", "show me", "recall", "find",
    "search", "look for", "which file", "who wrote", "when did i", "do we have",
    "anything about", "is there anything",
)
_STOPWORDS = {
    "a", "about", "all", "an", "and", "any", "anything", "are", "as", "at", "be", "been",
    "did", "do", "does", "for", "from", "had", "has", "have", "how", "i", "in", "is", "it",
    "me", "my", "of", "on", "or", "say", "said", "that", "the", "there", "this", "to",
    "was", "we", "were", "what", "when", "where", "which", "who", "why", "with", "write",
    "wrote", "you", "your",
}
_PREFERENCE_WORDS = ("always", "never", "prefer", "from now on", "don't", "do not", "must")


@dataclass
class SimpleResult:
    intent: str
    why: str
    headline: str
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    next_step: str | None = None
    simulated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "why": self.why,
            "headline": self.headline,
            "detail": self.detail,
            "next_step": self.next_step,
            "simulated": self.simulated,
            "data": self.data,
        }


def _clean(text: str) -> str:
    return " ".join((text or "").split()).strip()


def search_terms(text: str) -> str:
    """Turn a question into search terms, keeping the user's own words.

    "where did I write about database locks?" becomes "database locks". If nothing
    survives the stop-word pass the original text is returned, because an empty query
    would be a worse answer than a noisy one.
    """
    lowered = _clean(text).lower().rstrip("?!.")
    for prefix in _QUESTION_PREFIXES:
        if lowered.startswith(prefix):
            lowered = lowered[len(prefix):].strip()
            break
    words = [word for word in re.split(r"\s+", lowered) if word]
    kept = [word for word in words if word not in _STOPWORDS]
    result = " ".join(kept) or " ".join(words)
    return result.strip(" :,-") or _clean(text)


def detect_intent(text: str) -> tuple[str, str]:
    """Classify a line. Returns ``(intent, why)`` - the why is shown to the user."""
    line = _clean(text)
    if not line:
        raise ValidationError("say something first")
    if line.startswith("/"):
        command, _, rest = line[1:].partition(" ")
        name = command.strip().lower()
        mapping = {
            "search": "search", "find": "search", "remember": "remember",
            "note": "remember", "recall": "recall", "status": "status",
            "help": "help", "chat": "chat", "ask": "chat",
        }
        if name == "quit" or name == "exit":
            return "quit", "you asked to stop"
        if name not in mapping:
            return "help", f"/{name} is not a command I know, so here is the list"
        return mapping[name], f"you used the /{name} command"
    lowered = line.lower()
    if lowered.startswith(("remember that", "remember:", "note that", "note:", "keep in mind")):
        return "remember", "you asked me to remember something"
    if any(word in lowered for word in _PREFERENCE_WORDS) and lowered.startswith(("always", "never", "from now on")):
        return "remember", "you stated a standing preference"
    if lowered.startswith(("recall", "what do you know about", "what have you learned about")):
        return "recall", "you asked what I already know, so I searched memory only"
    if lowered in {"status", "health"} or lowered.startswith(
        ("status", "what's running", "what is running", "what is pending", "what's pending", "queue")
    ):
        return "status", "you asked about the current state, so I read it rather than guessed"
    if "anything about" in lowered:
        return "search", "you are asking whether something exists, so I searched the workspace"
    if lowered.startswith(_QUESTION_PREFIXES) or " where " in f" {lowered} ":
        return "search", "you are looking for something you already have, so I searched the workspace"
    if lowered.startswith(("run template", "run the template", "run workflow", "run the workflow")):
        return "workflow", "you asked to run a stored workflow by name"
    if lowered.startswith("help") or lowered == "?":
        return "help", "you asked for help"
    return "chat", "nothing matched a specific action, so I answered with the model"


class SimpleMode:
    """One entry point: classify, execute through existing services, explain."""

    def __init__(self, workspace) -> None:
        self.ws = workspace

    # -- config ------------------------------------------------------------
    def _cfg(self, key: str, default: Any) -> Any:
        try:
            return self.ws.config.get(key)
        except Exception:  # noqa: BLE001
            return default

    # -- entry points ------------------------------------------------------
    def ask(
        self,
        text: str,
        *,
        model_id: str | None = None,
        conversation_id: str | None = None,
    ) -> SimpleResult:
        intent, why = detect_intent(text)
        if intent == "quit":
            return SimpleResult(intent="quit", why=why, headline="Goodbye.")
        if intent == "help":
            return self.help(why=why)
        if intent == "status":
            result = self.status()
            result.why = why
            return result
        if intent == "search":
            return self.search(text, why=why)
        if intent == "recall":
            return self.recall(text, why=why)
        if intent == "remember":
            return self.remember(text, why=why)
        if intent == "workflow":
            return self.run_workflow(text, why=why, model_id=model_id)
        return self.chat(text, why=why, model_id=model_id, conversation_id=conversation_id)

    def help(self, *, why: str | None = None) -> SimpleResult:
        detail = "\n".join([
            "  ask me anything              - I answer with the configured model",
            "  where did I write about X    - I search conversations, memory, tasks, workflows, files",
            "  remember that X              - I store it in memory (with a duplicate check)",
            "  recall X                     - memory only, nothing else",
            "  status                       - model, memory, queue and recent work",
            "  run template NAME k=v        - run a built-in workflow",
            "  /search, /remember, /recall, /status, /help, /quit",
        ])
        return SimpleResult(
            intent="help",
            why=why or "you asked for help",
            headline="I can do six things plainly:",
            detail=detail,
            data={"intents": list(INTENTS)},
        )

    # -- intents -----------------------------------------------------------
    def search(self, text: str, *, why: str) -> SimpleResult:
        query = search_terms(text)
        report = self.ws.search.search(query, limit=int(self._cfg("search.default_limit", 10)))
        if not report.hits:
            looked = ", ".join(sorted(set(report.counts) | set(self._searchable())))
            detail = f"I looked in: {looked}."
            if report.skipped:
                detail += "\nNot searched: " + "; ".join(
                    f"{kind} ({reason})" for kind, reason in report.skipped.items()
                )
            return SimpleResult(
                intent="search", why=why,
                headline=f"I could not find anything about \"{query}\".",
                detail=detail, data={"report": report.to_dict()},
            )
        lines = []
        for hit in report.hits:
            lines.append(f"  [{hit.kind}] {hit.title}")
            if hit.snippet:
                lines.append(f"      {hit.snippet}")
            if hit.ref:
                lines.append(f"      -> {hit.ref}")
        detail = "\n".join(lines)
        if report.degraded:
            detail += "\nNote: " + "; ".join(report.degraded)
        return SimpleResult(
            intent="search", why=why,
            headline=f"{len(report.hits)} result(s) for \"{query}\" in {report.elapsed_ms:.0f}ms",
            detail=detail, data={"report": report.to_dict()},
        )

    def _searchable(self) -> list[str]:
        from .search import SEARCH_KINDS

        return list(SEARCH_KINDS)

    def recall(self, text: str, *, why: str) -> SimpleResult:
        query = search_terms(text)
        outcome = self.ws.memory.search(query, limit=10)
        if not outcome.hits:
            return SimpleResult(
                intent="recall", why=why,
                headline=f"I have nothing stored about \"{query}\".",
                detail=f"memory search mode: {outcome.mode}"
                + (f" ({outcome.degraded_reason})" if outcome.degraded_reason else ""),
                data={"query": query, "mode": outcome.mode, "degraded": outcome.degraded},
            )
        lines = [
            f"  [{hit.memory.kind}/{hit.memory.category}] {hit.memory.title}: {hit.memory.content[:200]}"
            for hit in outcome.hits
        ]
        return SimpleResult(
            intent="recall", why=why,
            headline=f"{len(outcome.hits)} memory item(s) about \"{query}\"",
            detail="\n".join(lines),
            data={"query": query, "mode": outcome.mode, "degraded": outcome.degraded},
        )

    def remember(self, text: str, *, why: str) -> SimpleResult:
        content = _strip_remember_prefix(text)
        if not content:
            raise ValidationError("there is nothing to remember in that sentence")
        title = content[:80] + ("..." if len(content) > 80 else "")
        preference = any(word in content.lower() for word in _PREFERENCE_WORDS)
        # A statement the user asked to keep is permanent; only the category changes.
        kind = "permanent"
        category = "preference" if preference else "fact"
        result = self.ws.memory.add(
            kind,
            title,
            content,
            category=category,
            source="user",
            provenance={"mode": "simple", "intent": "remember"},
        )
        if not result.is_ok:
            error = result.error
            return SimpleResult(
                intent="remember", why=why,
                headline="I did not store that.",
                detail=getattr(error, "message", None) or str(error),
                data={"duplicate": True, "content": content},
            )
        memory = result.value
        return SimpleResult(
            intent="remember", why=why,
            headline=f"Stored as {memory.kind}/{memory.category}: \"{memory.title}\"",
            detail=f"memory {memory.id} (scope {memory.scope}); it is searchable with /recall",
            data={"memory_id": memory.id, "kind": memory.kind, "category": memory.category},
        )

    def status(self) -> SimpleResult:
        data: dict[str, Any] = {}
        lines: list[str] = []
        models = self.ws.models.list() if self.ws.models is not None else []
        verified = [model for model in models if getattr(model, "verification", None) == "verified"]
        data["models"] = {"total": len(models), "verified": len(verified)}
        lines.append(f"  models: {len(models)} registered, {len(verified)} verified")
        try:
            decision = self.ws.router.route("chat", allow_simulated=True, record_decision=False)
            data["model"] = decision.chosen.id if decision.chosen else None
            chosen = decision.chosen
            simulated = bool(
                chosen is not None
                and (chosen.runtime == "scripted" or bool((chosen.claims or {}).get("simulated")))
            )
            data["simulated"] = simulated
            if simulated:
                lines.append(
                    f"  chatting with: {data['model']} (SIMULATED - no model is run;"
                    " add a real one with `archx-agent models add-http`)"
                )
            else:
                lines.append(f"  chatting with: {data['model']}")
        except Exception as exc:  # noqa: BLE001 - status must never fail
            data["model"] = None
            lines.append(f"  chatting: nothing eligible ({getattr(exc, 'message', exc)})")
        if self.ws.memory is not None:
            stats = self.ws.memory.stats()
            data["memory"] = stats
            lines.append(f"  memory: {stats.get('total_active', 0)} active item(s)")
        if self.ws.tasks is not None:
            task_stats = self.ws.tasks.stats()
            data["tasks"] = task_stats
            running = task_stats.get("by_status", {}).get("running", 0)
            lines.append(f"  tasks: {task_stats.get('total', 0)} recorded, {running} running")
        if self.ws.jobs is not None:
            job_stats = self.ws.jobs.stats()
            data["jobs"] = job_stats
            lines.append(
                f"  jobs: {job_stats.get('queued', 0)} queued, {job_stats.get('running', 0)} running,"
                f" {job_stats.get('paused', 0)} paused"
            )
        return SimpleResult(
            intent="status",
            why="you asked about the current state",
            headline="Here is where things stand:",
            detail="\n".join(lines),
            data=data,
        )

    def run_workflow(self, text: str, *, why: str, model_id: str | None = None) -> SimpleResult:
        match = re.match(
            r"(?i)^run (?:the )?(?:template|workflow) +([\w.-]+)\s*(.*)$", _clean(text)
        )
        if not match:
            raise ValidationError("say `run template NAME key=value`")
        name, rest = match.group(1), match.group(2)
        if name not in TEMPLATES:
            raise NotFoundError(
                f"no template {name!r} (known: {', '.join(sorted(TEMPLATES))})"
            )
        inputs: dict[str, str] = {}
        for token in rest.split():
            if "=" not in token:
                raise ValidationError(f"inputs look like key=value, got {token!r}")
            key, _, value = token.partition("=")
            inputs[key] = value
        definition = render_inputs(dict(TEMPLATES[name]), inputs)
        workflow = self.ws.workflows.create(definition, model_id=model_id)
        try:
            run = self.ws.agent.run(workflow.id)
        except ApprovalRequiredError as exc:
            approval_id = getattr(exc, "approval_id", None)
            if approval_id:
                headline = "A step needs a permission I cannot grant for you, so nothing past it ran."
                next_step = f"archx-agent approvals approve {approval_id}"
            else:
                headline = "That workflow has a checkpoint, so I stopped before doing anything."
                next_step = f"archx-agent agent run {workflow.id} --approve"
            return SimpleResult(
                intent="workflow", why=why,
                headline=headline,
                detail=getattr(exc, "message", str(exc)),
                next_step=next_step,
                data={"workflow_id": workflow.id, "approval_id": approval_id},
            )
        except ArchxError as exc:
            message = getattr(exc, "message", str(exc))
            if "no usable model" in message or isinstance(exc, ModelNotFoundError):
                headline = "The workflow stopped: it has a model step and no model is configured."
                next_step = (
                    "archx-agent models add-http --name ... --base-url ... "
                    "(or: archx-agent --allow-simulated models add-scripted --name sim)"
                )
            elif isinstance(exc, ValidationError):
                headline = "I could not start that workflow."
                next_step = f"archx-agent agent show {workflow.id}"
            else:
                headline = "The workflow stopped before finishing."
                next_step = f"archx-agent agent show {workflow.id}"
            return SimpleResult(
                intent="workflow", why=why,
                headline=headline,
                detail=message,
                next_step=next_step,
                data={"workflow_id": workflow.id, "stopped": type(exc).__name__},
            )
        return SimpleResult(
            intent="workflow", why=why,
            headline=f"Ran {name}: {run.status} ({len(run.steps)} step(s))",
            detail=(run.summary or "")[:500],
            next_step=f"archx-agent agent show {workflow.id}",
            data={"workflow_id": workflow.id, "status": run.status, "steps": len(run.steps)},
        )

    def chat(
        self,
        text: str,
        *,
        why: str,
        model_id: str | None = None,
        conversation_id: str | None = None,
    ) -> SimpleResult:
        try:
            reply = self.ws.chat.send(
                text, conversation_id=conversation_id, model_id=model_id
            )
        except ApprovalRequiredError as exc:
            approval_id = getattr(exc, "approval_id", None)
            return SimpleResult(
                intent="chat", why=why,
                headline="That needs a permission I am not allowed to grant for you.",
                detail=getattr(exc, "message", str(exc)),
                next_step=f"archx-agent approvals approve {approval_id}" if approval_id
                else "archx-agent approvals list",
                data={"approval_id": approval_id},
            )
        except PermissionDeniedError as exc:
            return SimpleResult(
                intent="chat", why=why,
                headline="That is not permitted.",
                detail=getattr(exc, "message", str(exc)),
                next_step="archx-agent permissions list",
            )
        except ModelNotFoundError as exc:
            return SimpleResult(
                intent="chat", why=why,
                headline="I have no model to answer with.",
                detail=getattr(exc, "message", str(exc)),
                next_step="archx-agent models add-http --name local --base-url http://127.0.0.1:8080/v1 --model smollm2",
            )
        except ArchxError as exc:
            return SimpleResult(
                intent="chat", why=why,
                headline="That did not work.",
                detail=f"{type(exc).__name__}: {getattr(exc, 'message', exc)}",
            )
        return SimpleResult(
            intent="chat", why=why,
            headline=reply.text,
            detail=(f"model {reply.model.get('model_id')} - {reply.prompt_tokens}+{reply.completion_tokens} tokens"
                    + (" (simulated)" if reply.simulated else "")),
            simulated=bool(reply.simulated),
            data={
                "conversation_id": reply.conversation_id,
                "model_id": reply.model.get("model_id"),
                "tokens": reply.prompt_tokens + reply.completion_tokens,
                "task": reply.task,
            },
        )


def _strip_remember_prefix(text: str) -> str:
    cleaned = _clean(text)
    lowered = cleaned.lower()
    for prefix in (
        "remember that", "remember:", "remember", "note that", "note:",
        "keep in mind", "/remember", "/note",
    ):
        if lowered.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            break
    return cleaned.strip(" .") or ""


__all__ = ["INTENTS", "SimpleMode", "SimpleResult", "detect_intent", "search_terms"]
