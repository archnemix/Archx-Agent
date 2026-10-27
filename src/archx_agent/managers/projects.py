"""Project identity.

A project is the mixing boundary for Project Memory, workspace files,
experiments and artifact storage. Two unrelated projects must never share
memory, so every project-scoped record carries ``project_id`` and is filtered
by it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.paths import child_path
from archx_agent.helpers.result import Err, Ok, Result
from archx_agent.helpers.timeutil import iso_now, new_id

from .base import BaseManager

PROJECT_TABLES = ("projects",)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-_.]{0,63}$")


@dataclass
class Project:
    id: str
    slug: str
    name: str
    root_path: str | None
    description: str
    status: str
    created_at: str
    updated_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "root_path": self.root_path,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }


def _from_row(row: dict[str, Any]) -> Project:
    return Project(
        id=row["id"],
        slug=row["slug"],
        name=row["name"],
        root_path=row["root_path"],
        description=row["description"] or "",
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        metadata=json.loads(row["metadata"]) if row["metadata"] else {},
    )


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug or "project")[:64]


class ProjectManager(BaseManager):
    tables = PROJECT_TABLES

    def __init__(self, store, coordinator, *, events=None, projects_root: str | None = None) -> None:
        self.projects_root = projects_root
        super().__init__(store, coordinator, events=events)

    def register_handlers(self) -> None:
        self.coordinator.register("project.create", self._apply_create)
        self.coordinator.register("project.update", self._apply_update)
        self.coordinator.register("project.delete", self._apply_delete)

    def _apply_create(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        p = payload["project"]
        tx.execute(
            "INSERT INTO projects(id, slug, name, root_path, description, status, created_at, updated_at, metadata)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                p["id"],
                p["slug"],
                p["name"],
                p.get("root_path"),
                p.get("description") or "",
                p.get("status", "active"),
                p["created_at"],
                p["updated_at"],
                json_text(p.get("metadata") or {}),
            ),
        )
        return {"id": p["id"], "slug": p["slug"]}

    def _apply_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {"name", "description", "status", "root_path", "metadata"}
        sets, params = [], []
        for key, value in payload["fields"].items():
            if key not in allowed:
                raise ValidationError(f"cannot update project field {key!r}")
            if key == "metadata":
                value = json_text(value or {})
            sets.append(f"{key} = ?")
            params.append(value)
        sets.append("updated_at = ?")
        params.append(iso_now())
        params.append(payload["id"])
        tx.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id = ?", params)
        return {"id": payload["id"]}

    def _apply_delete(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute("UPDATE projects SET status='deleted', updated_at=? WHERE id=?", (iso_now(), payload["id"]))
        return {"id": payload["id"]}

    # -- API --------------------------------------------------------------
    def create(
        self,
        name: str,
        *,
        description: str = "",
        root_path: str | None = None,
        slug: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Project:
        name = (name or "").strip()
        if not name:
            raise ValidationError("project name must not be empty")
        slug = (slug or slugify(name)).strip().lower()
        if not _SLUG_RE.match(slug):
            raise ValidationError(
                "project slug must be lowercase letters, digits, '-' or '_' (max 64 characters)"
            )
        if self.by_slug(slug).is_ok:
            raise ValidationError(f"a project with slug {slug!r} already exists")
        if root_path and self.projects_root:
            child_path(self.projects_root, root_path)  # containment check only
        now = iso_now()
        project = Project(
            id=new_id("proj_"),
            slug=slug,
            name=name,
            root_path=root_path,
            description=description,
            status="active",
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        self._write("project.create", {"project": project.to_dict()})
        self.trace("project", "project.created", project_id=project.id, payload={"slug": slug, "name": name})
        return project

    def get(self, project_id: str) -> Result[Project]:
        row = self.store.query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
        if row is None or row["status"] == "deleted":
            return Err(NotFoundError(f"project {project_id} not found", id=project_id))
        return Ok(_from_row(row))

    def by_slug(self, slug: str) -> Result[Project]:
        row = self.store.query_one("SELECT * FROM projects WHERE slug = ?", (slug,))
        if row is None or row["status"] == "deleted":
            return Err(NotFoundError(f"project slug {slug!r} not found", slug=slug))
        return Ok(_from_row(row))

    def require(self, project_id: str) -> Project:
        return self.get(project_id).ok_or_raise()

    def list(self, *, include_deleted: bool = False, include_archived: bool = False, limit: int = 100) -> list[Project]:
        clauses = []
        if not include_deleted:
            clauses.append("status != 'deleted'")
        if not include_archived:
            clauses.append("status = 'active'")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.store.query(f"SELECT * FROM projects{where} ORDER BY created_at DESC LIMIT ?", (limit,))
        return [_from_row(r) for r in rows]

    def update(self, project_id: str, **fields: Any) -> Project:
        self.require(project_id)
        self._write("project.update", {"id": project_id, "fields": fields})
        return self.require(project_id)

    def rename(self, project_id: str, name: str) -> Result["Project"]:
        name = (name or "").strip()
        if not name:
            return Err(ValidationError("project name must not be empty"))
        if self.get(project_id).is_err:
            return self.get(project_id)
        self.update(project_id, name=name)
        return self.get(project_id)

    def archive(self, project_id: str) -> None:
        self.update(project_id, status="archived")

    def delete(self, project_id: str, *, hard: bool = False) -> str:
        self.require(project_id)
        if hard:
            with self.store.write_tx() as tx:
                tx.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            self.trace("project", "project.hard_deleted", project_id=project_id)
            return "hard_deleted"
        self._write("project.delete", {"id": project_id})
        self.trace("project", "project.deleted", project_id=project_id)
        return "soft_deleted"

    def stats(self) -> dict[str, Any]:
        return {"projects": self.table_count("projects"), "active": len(self.list())}


__all__ = ["ProjectManager", "Project", "slugify"]
