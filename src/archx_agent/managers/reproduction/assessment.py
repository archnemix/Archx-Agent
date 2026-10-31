"""ReproductionManager: assessment operations."""

from __future__ import annotations
import platform
import shlex
from typing import Any
from archx_agent.helpers.jsonio import keyed_hash
from archx_agent.helpers.timeutil import iso_now
from .records import Issue


class ReproductionManagerAssessmentMixin:
    def _output_issues(self, task) -> list[Issue]:
        issues: list[Issue] = []
        for artifact in self.tasks.artifacts(task.id):
            if not artifact.exists:
                issues.append(
                    Issue(
                        "blocker",
                        "artifact_missing",
                        f"the output artifact {artifact.name} is gone ({artifact.path})",
                    )
                )
        return issues

    def _commands(self, task) -> list[str]:
        home = shlex.quote(str(self.home or ""))
        prefix = f"archx-agent --home {home}"
        commands: list[str] = [f"# task {task.id}: {task.type} - {task.title}"]
        prompt = None
        if self.conversations is not None and task.input_refs:
            message = self.conversations.find_message(task.input_refs[0])
            if message is not None:
                prompt = message.content
        if task.conversation_id:
            if prompt:
                commands.append(
                    f"{prefix} chat --conversation {shlex.quote(task.conversation_id)} "
                    f"--message {shlex.quote(prompt[:2000])}"
                )
            else:
                commands.append(
                    f"{prefix} conv show {shlex.quote(task.conversation_id)}"
                )
        for run in self.tasks.tool_runs(task.id):
            if run.get("dry_run"):
                continue
            parts = [f"{prefix} tools run {shlex.quote(run['tool_name'])}"]
            for key, value in (run.get("arguments") or {}).items():
                if isinstance(value, bool):
                    value = "true" if value else "false"
                parts.append(f"--arg {shlex.quote(f'{key}={value}')}")
            commands.append(" ".join(parts))
        commands.append(f"{prefix} tasks show {shlex.quote(task.id)}")
        return commands

    def assess(self, task_id: str) -> dict[str, Any]:
        """Compute fidelity and the plan without writing anything."""
        task = self.tasks.get(task_id)
        issues: list[Issue] = []

        if task.status == "failed":
            issues.append(
                Issue(
                    "caveat",
                    "task_failed",
                    f"the task failed ({task.error or 'no error recorded'}); a replay reproduces the attempt, not a success",
                )
            )
        elif task.status == "cancelled":
            issues.append(
                Issue(
                    "caveat",
                    "task_cancelled",
                    "the task was cancelled; a replay has no recorded outcome to match",
                )
            )
        elif task.status == "interrupted":
            issues.append(
                Issue(
                    "caveat",
                    "task_interrupted",
                    "the task was interrupted; its end state is unknown, so a replay cannot be compared to it",
                )
            )
        elif task.status in ("queued", "running"):
            issues.append(
                Issue(
                    "caveat",
                    "task_incomplete",
                    f"the task is still {task.status}; there is no outcome yet",
                )
            )

        if task.unresolved:
            issues.append(
                Issue(
                    "caveat",
                    "open_questions",
                    f"{len(task.unresolved)} question(s) were never answered: {task.unresolved[0][:160]}",
                )
            )

        model_info: dict[str, Any] | None = None
        if task.model_id:
            model_info, model_issues = self._model_state(task.model_id)
            issues.extend(model_issues)

        tool_states, tool_issues = self._tool_states(task)
        issues.extend(tool_issues)
        issues.extend(self._run_caveats(task.id))
        issues.extend(self._output_issues(task))

        if not task.model_id and not task.tools:
            issues.append(
                Issue(
                    "caveat",
                    "nothing_to_replay",
                    "the task recorded neither a model nor a tool, so there is nothing mechanical to replay",
                )
            )

        if self.tools is None:
            issues.append(
                Issue(
                    "caveat",
                    "no_tool_runtime",
                    "this workspace has no tool runtime, so tool availability could not be checked",
                )
            )

        # De-duplicate while preserving discovery order: the same caveat twice is noise.
        seen: set[tuple[str, str]] = set()
        unique: list[Issue] = []
        for issue in issues:
            key = (issue.code, issue.detail)
            if key in seen:
                continue
            seen.add(key)
            unique.append(issue)
        issues = unique

        has_blocker = any(issue.level == "blocker" for issue in issues)
        fidelity = "impossible" if has_blocker else ("partial" if issues else "exact")

        settings = self._settings_snapshot()
        environment = {
            "captured_at": iso_now(),
            "app_version": self.app_version,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "schema_version": self._schema_version
            if self._schema_version is not None
            else self.store.schema_version(),
            "home": str(self.home) if self.home else None,
            "settings": settings,
            "settings_digest": keyed_hash(settings),
            "model": model_info,
            "tools": tool_states,
            "tool_roots": list(self.tools.roots()) if self.tools is not None else [],
            "simulated": bool(model_info and model_info.get("simulated")),
        }
        return {
            "task": task.to_dict(),
            "fidelity": fidelity,
            "issues": [issue.to_dict() for issue in issues],
            "environment": environment,
            "commands": self._commands(task),
        }
