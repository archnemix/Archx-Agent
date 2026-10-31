"""Presentation operations for workspace composition."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.schema import SCHEMA_VERSION


class WorkspacePresentationMixin:
    """Presentation responsibility for Workspace."""

    @property
    def allow_test_double(self) -> bool:
        return bool(getattr(self, "_allow_test_double", False))

    def info(self) -> dict[str, Any]:
        return {
            "home": str(self.config.home),
            "database": str(self.store.path),
            "events": str(self.events.path),
            "schema_version": self.store.schema_version(),
            "expected_schema_version": SCHEMA_VERSION,
            "models": len(self.models.list()),
            "conversations": self.conversations.stats()["active_conversations"],
            "memories": self.memory.stats()["total_active"],
            "tasks": self.tasks.stats()["total"] if self.tasks is not None else 0,
            "workflows": self.workflows.stats()["total"]
            if self.workflows is not None
            else 0,
            "warnings": self.warnings,
            "opened_at": iso_now(),
        }

    def tool_roots(self, project_id: str | None = None) -> list[str]:
        """Directories tools may touch: explicit config, else the project, else a sandbox."""
        if self.tools is not None:
            live = self.tools.roots()
            if live:
                return live
        configured = [
            str(x).strip()
            for x in (self.config.get("tools.roots") or [])
            if str(x).strip()
        ]
        if configured:
            return [str(Path(x).expanduser().resolve()) for x in configured]
        if project_id and self.projects is not None:
            record = self.projects.get(project_id)
            if record.is_ok and record.value.root_path:
                return [str(Path(record.value.root_path).expanduser().resolve())]
        return [str(Path(self.config.path("paths.home")) / "workspace")]

    def extensions_dir(self) -> Path:
        configured = self.config.get("extensions.directory")
        directory = (
            Path(configured).expanduser()
            if configured
            else Path(self.config.path("paths.home")) / "extensions"
        )
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def tool_info(self) -> dict[str, Any]:
        info = (
            self.info() if self.tools is not None else {"home": str(self.config.home)}
        )
        return {
            "home": info.get("home", str(self.config.home)),
            "database": info.get("database"),
            "schema_version": info.get("schema_version"),
            "models": info.get("models"),
            "conversations": info.get("conversations"),
            "memories": info.get("memories"),
        }
