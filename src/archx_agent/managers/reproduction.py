"""Reproduction records: can this task be run again, and what would it take?

A reproduction record is an honest statement, not a promise. It captures the environment
the task ran in (application version, Python, schema, model identity, tools and their
abilities, the settings that change behaviour) and it *re-derives* whether that
environment still exists.

Three answers, and only three:

``exact``
    Every ingredient is still present and deterministic: the same model file, the same
    tools, the same settings, nothing simulated, nothing waiting on the user.
``partial``
    The task can be attempted again, but something will not be identical - a remote
    provider, a simulated test double, a consumed single-use grant, an unanswered
    question, settings that changed since the record.
``impossible``
    Something essential is gone: the model file or registration, a tool that no longer
    exists, a dynamic server that is no longer trusted.

The classification is computed from evidence at capture time and recomputed by
``verify``; it is never inferred from the fact that a record exists.
"""

from __future__ import annotations

import json
import platform
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text, keyed_hash
from archx_agent.helpers.result import Result
from archx_agent.helpers.timeutil import iso_now, new_id

from .base import BaseManager

REPRODUCTION_TABLES = ("reproduction_records",)

FIDELITIES = ("exact", "partial", "impossible")
_RANK = {"exact": 0, "partial": 1, "impossible": 2}

#: Settings that change what a task would do, so a change is a reproduction caveat.
_SENSITIVE_SETTINGS = (
    "model.temperature",
    "model.output_budget",
    "model.context_limit",
    "model.local_only",
    "context.strategy",
    "context.reserve_tokens",
    "router.require_verified",
    "router.fallback",
    "tools.timeout_seconds",
    "tools.roots",
    "tasks.max_version_bytes",
)


@dataclass
class Issue:
    level: str  # "blocker" | "caveat"
    code: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"level": self.level, "code": self.code, "detail": self.detail}


@dataclass
class Reproduction:
    id: str
    task_id: str
    fidelity: str
    issues: list[dict[str, str]]
    environment: dict[str, Any]
    commands: list[str]
    created_at: str
    app_version: str = ""
    recorded_by: str = "user"

    @property
    def blockers(self) -> list[dict[str, str]]:
        return [issue for issue in self.issues if issue["level"] == "blocker"]

    @property
    def caveats(self) -> list[dict[str, str]]:
        return [issue for issue in self.issues if issue["level"] == "caveat"]

    def to_dict(self, *, with_environment: bool = True) -> dict[str, Any]:
        data = {
            "id": self.id,
            "task_id": self.task_id,
            "fidelity": self.fidelity,
            "issues": list(self.issues),
            "blockers": self.blockers,
            "caveats": self.caveats,
            "commands": list(self.commands),
            "created_at": self.created_at,
            "app_version": self.app_version,
            "recorded_by": self.recorded_by,
        }
        if with_environment:
            data["environment"] = dict(self.environment)
        return data


def _load(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):  # pragma: no cover - defensive
        return default


def _from_row(row: dict[str, Any]) -> Reproduction:
    return Reproduction(
        id=row["id"],
        task_id=row["task_id"],
        fidelity=row["fidelity"],
        issues=_load(row.get("blockers"), []),
        environment=_load(row.get("environment"), {}),
        commands=_load(row.get("commands"), []),
        created_at=row["created_at"],
        app_version=row.get("app_version") or "",
        recorded_by=row.get("recorded_by") or "user",
    )


class ReproductionManager(BaseManager):
    """Assess, record and re-check how a task could be reproduced."""

    tables = REPRODUCTION_TABLES

    def __init__(
        self,
        store,
        coordinator,
        *,
        tasks,
        models=None,
        tools=None,
        conversations=None,
        mcp=None,
        extensions=None,
        config=None,
        events=None,
        home: str | None = None,
        app_version: str = "",
        schema_version: int | None = None,
    ) -> None:
        self.tasks = tasks
        self.models = models
        self.tools = tools
        self.conversations = conversations
        self.mcp = mcp
        self.extensions = extensions
        self.config = config
        self.home = home
        self.app_version = app_version
        self._schema_version = schema_version
        super().__init__(store, coordinator, events=events)

    def register_handlers(self) -> None:
        self.coordinator.register("reproduction.record", self._apply_record)

    def _apply_record(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        r = payload["repro"]
        tx.execute(
            "INSERT INTO reproduction_records(id, task_id, fidelity, blockers, environment,"
            " commands, created_at, app_version, recorded_by) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                r["id"], r["task_id"], r["fidelity"], json_text(r["issues"]),
                json_text(r["environment"]), json_text(r["commands"]), r["created_at"],
                r.get("app_version"), r.get("recorded_by"),
            ),
        )
        return {"id": r["id"], "fidelity": r["fidelity"]}

    # -- environment -------------------------------------------------------
    def _setting(self, key: str) -> Any:
        if self.config is None:
            return None
        try:
            return self.config.get(key)
        except Exception:  # noqa: BLE001 - an unknown key must not break a capture
            return None

    def _settings_snapshot(self) -> dict[str, Any]:
        return {key: self._setting(key) for key in _SENSITIVE_SETTINGS}

    def _model_state(self, model_id: str) -> tuple[dict[str, Any], list[Issue]]:
        issues: list[Issue] = []
        info: dict[str, Any] = {"id": model_id}
        record = None
        if self.models is not None:
            found = self.models.get(model_id)
            record = found.value if found.is_ok else None
        if record is None:
            info.update({"registered": False, "available": False})
            issues.append(
                Issue(
                    "blocker",
                    "model_missing",
                    f"the model {model_id} is no longer registered; a replay would select a different model",
                )
            )
            return info, issues
        runtime = record.runtime
        info.update(
            {
                "registered": True,
                "name": record.name,
                "runtime": runtime,
                "provider": record.provider,
                "path": record.path,
                "size_bytes": record.size_bytes,
                "sha256": record.sha256,
                "context_length": record.context_length,
            }
        )
        if runtime == "scripted":
            info["simulated"] = True
            issues.append(
                Issue(
                    "caveat",
                    "model_simulated",
                    f"{record.name} is a simulated test double: it performs no inference, "
                    "so its answer cannot be reproduced",
                )
            )
        elif runtime == "llama-cpp":
            exists = bool(record.path) and Path(str(record.path)).exists()
            info["path_exists"] = exists
            if not exists:
                info["simulated"] = False
                issues.append(
                    Issue(
                        "blocker",
                        "model_file_missing",
                        f"the model file for {record.name} is missing ({record.path or 'no path'})",
                    )
                )
        else:
            base_url = (record.facts or {}).get("base_url")
            info["base_url"] = base_url
            remote = bool(base_url) and not _is_loopback(base_url)
            info["remote"] = remote
            if remote:
                issues.append(
                    Issue(
                        "caveat",
                        "model_remote",
                        f"{record.name} runs at {base_url}: the provider can change the model "
                        "or its sampling without notice",
                    )
                )
        return info, issues

    def _tool_states(self, task) -> tuple[list[dict[str, Any]], list[Issue]]:
        issues: list[Issue] = []
        states: list[dict[str, Any]] = []
        if not task.tools:
            return states, issues
        for name in task.tools:
            state: dict[str, Any] = {"name": name}
            spec = None
            if self.tools is not None:
                try:
                    spec = self.tools.spec(name)
                except Exception:  # noqa: BLE001 - ToolNotFoundError and friends
                    spec = None
            if spec is None:
                state.update({"registered": False})
                states.append(state)
                issues.append(
                    Issue(
                        "blocker",
                        "tool_missing",
                        f"the tool {name} is no longer registered; the task cannot repeat that step",
                    )
                )
                continue
            state.update(
                {
                    "registered": True,
                    "capability": spec.capability,
                    "risk": spec.risk,
                    "origin": spec.origin,
                    "side_effects": spec.side_effects,
                }
            )
            if spec.capability:
                grants = []
                if self.tools is not None:
                    grants = [
                        g
                        for g in self.tools.permissions.grants(capability=spec.capability, subject=name)
                        if g.active
                    ]
                state["active_grants"] = len(grants)
                if not grants:
                    issues.append(
                        Issue(
                            "caveat",
                            "tool_ungranted",
                            f"{name} has no active grant for {spec.capability}; a replay needs approval again",
                        )
                    )
            if spec.origin.startswith("mcp:"):
                server = spec.origin.split(":", 1)[1]
                status = None
                if self.mcp is not None:
                    try:
                        record = self.mcp.server(server)
                        status = {"trusted": record.trusted, "enabled": record.enabled}
                    except Exception:  # noqa: BLE001
                        status = None
                state["server"] = {"name": server, **(status or {})}
                if not status or not (status["trusted"] and status["enabled"]):
                    issues.append(
                        Issue(
                            "blocker",
                            "mcp_server_inactive",
                            f"the MCP server {server!r} is no longer trusted and enabled, so {name} is gone",
                        )
                    )
            elif spec.origin.startswith("extension:"):
                extension = spec.origin.split(":", 1)[1]
                ext_state = None
                if self.extensions is not None:
                    try:
                        record = self.extensions.extension(extension)
                        ext_state = {"trust": record.trust, "enabled": record.enabled}
                    except Exception:  # noqa: BLE001
                        ext_state = None
                state["extension"] = {"name": extension, **(ext_state or {})}
                if not ext_state or not (ext_state["trust"] == "trusted" and ext_state["enabled"]):
                    issues.append(
                        Issue(
                            "blocker",
                            "extension_inactive",
                            f"the extension {extension!r} is no longer trusted and enabled, so {name} is gone",
                        )
                    )
            if spec.name == "fs.write" or spec.name == "shell.run":
                issues.append(
                    Issue(
                        "caveat",
                        "tool_side_effects",
                        f"replaying {name} repeats its side effects ({spec.side_effects})",
                    )
                )
            states.append(state)
        return states, issues

    def _run_caveats(self, task_id: str) -> list[Issue]:
        issues: list[Issue] = []
        for run in self.tasks.tool_runs(task_id):
            if run.get("dry_run"):
                continue
            if run.get("status") == "denied":
                issues.append(
                    Issue(
                        "caveat",
                        "denied_run",
                        f"the task includes a denied {run['tool_name']} call; a replay stops at the same refusal",
                    )
                )
            permission_id = run.get("permission_id")
            if permission_id and self.tools is not None:
                grant = self.tools.permissions.get(permission_id)
                if grant.is_ok and grant.value.duration == "once":
                    issues.append(
                        Issue(
                            "caveat",
                            "grant_consumed",
                            f"the grant for {run['tool_name']} was single-use and has been used",
                        )
                    )
        return issues

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
                commands.append(f"{prefix} conv show {shlex.quote(task.conversation_id)}")
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

    # -- assessment --------------------------------------------------------
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
                Issue("caveat", "task_cancelled", "the task was cancelled; a replay has no recorded outcome to match")
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
                Issue("caveat", "task_incomplete", f"the task is still {task.status}; there is no outcome yet")
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
                Issue("caveat", "no_tool_runtime", "this workspace has no tool runtime, so tool availability could not be checked")
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
            "schema_version": self._schema_version if self._schema_version is not None else self.store.schema_version(),
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

    # -- writes ------------------------------------------------------------
    def capture(
        self,
        task_id: str,
        *,
        recorded_by: str = "user:cli",
    ) -> Reproduction:
        planned = self.assess(task_id)
        repro = Reproduction(
            id=new_id("rp_"),
            task_id=task_id,
            fidelity=planned["fidelity"],
            issues=planned["issues"],
            environment=planned["environment"],
            commands=planned["commands"],
            created_at=iso_now(),
            app_version=self.app_version,
            recorded_by=recorded_by,
        )
        self._write("reproduction.record", {"repro": repro.to_dict()})
        self.trace(
            "task",
            "task.reproduction",
            status="ok" if repro.fidelity != "impossible" else "warning",
            task_id=task_id,
            payload={
                "reproduction_id": repro.id,
                "fidelity": repro.fidelity,
                "blockers": [b["code"] for b in repro.blockers],
            },
        )
        return repro

    # -- reads -------------------------------------------------------------
    def records(self, task_id: str | None = None, *, limit: int = 20) -> list[Reproduction]:
        if task_id:
            rows = self.store.query(
                "SELECT * FROM reproduction_records WHERE task_id = ?"
                " ORDER BY rowid DESC LIMIT ?",
                (task_id, int(limit)),
            )
        else:
            rows = self.store.query(
                "SELECT * FROM reproduction_records ORDER BY rowid DESC LIMIT ?", (int(limit),)
            )
        return [_from_row(row) for row in rows]

    def latest(self, task_id: str) -> Reproduction | None:
        rows = self.records(task_id, limit=1)
        return rows[0] if rows else None

    def get(self, repro_id: str) -> Result[Reproduction]:
        row = self.store.query_one("SELECT * FROM reproduction_records WHERE id = ?", (repro_id,))
        if row is None:
            return Result.err(NotFoundError(f"no reproduction record {repro_id}"))
        return Result.ok(_from_row(row))

    def verify(self, repro_id: str) -> dict[str, Any]:
        """Re-derive the fidelity now and compare it with the record."""
        record = self.get(repro_id).ok_or_raise()
        current = self.assess(record.task_id)
        recorded_codes = {issue["code"] for issue in record.issues}
        current_codes = {issue["code"] for issue in current["issues"]}
        settings = record.environment.get("settings") or {}
        settings_now = current["environment"]["settings"]
        changed_settings = {
            key: {"recorded": settings.get(key), "now": settings_now.get(key)}
            for key in set(settings) | set(settings_now)
            if settings.get(key) != settings_now.get(key)
        }
        return {
            "reproduction_id": record.id,
            "task_id": record.task_id,
            "recorded": record.fidelity,
            "current": current["fidelity"],
            "changed": _RANK[current["fidelity"]] > _RANK[record.fidelity],
            "improved": _RANK[current["fidelity"]] < _RANK[record.fidelity],
            "new_blockers": sorted(current_codes - recorded_codes),
            "resolved": sorted(recorded_codes - current_codes),
            "changed_settings": changed_settings,
            "issues": current["issues"],
            "commands": current["commands"],
        }

    def stats(self) -> dict[str, Any]:
        rows = self.store.query(
            "SELECT fidelity, COUNT(*) AS n FROM reproduction_records GROUP BY fidelity", ()
        )
        return {"total": sum(int(row["n"]) for row in rows),
                "by_fidelity": {row["fidelity"]: int(row["n"]) for row in rows}}


def _is_loopback(url: str | None) -> bool:
    if not url:
        return False
    try:
        from .providers import is_loopback_url

        return bool(is_loopback_url(url))
    except Exception:  # noqa: BLE001 - a bad URL is not loopback
        return False


__all__ = [
    "FIDELITIES",
    "Issue",
    "REPRODUCTION_TABLES",
    "Reproduction",
    "ReproductionManager",
]
