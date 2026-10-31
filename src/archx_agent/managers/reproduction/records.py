"""ReproductionManager records, constants and pure metadata conversion."""

from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Any

REPRODUCTION_TABLES = ("reproduction_records",)

FIDELITIES = ("exact", "partial", "impossible")

_RANK = {"exact": 0, "partial": 1, "impossible": 2}

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


def _is_loopback(url: str | None) -> bool:
    if not url:
        return False
    try:
        from .providers import is_loopback_url

        return bool(is_loopback_url(url))
    except Exception:  # noqa: BLE001 - a bad URL is not loopback
        return False
