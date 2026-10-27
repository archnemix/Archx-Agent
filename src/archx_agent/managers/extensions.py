"""Extensions: a manifest, a directory, and tools that still need permission.

An extension is a folder with ``extension.json`` listing tools. Installing it records the
manifest and its hash; **nothing runs** until the user trusts the extension, and even then
every tool call goes through the same capability check as a built-in tool.

Rules that are enforced here rather than documented and hoped for:

* a manifest cannot invent a capability - it must name one from ``CAPABILITIES``;
* a manifest cannot lower a risk level - the capability's risk is canonical;
* an extension tool may only run a program inside its own directory (no absolute paths
  pointing elsewhere, no ``..`` escapes);
* untrusted or disabled extensions have their tools unregistered, so they cannot be called
  by name at all;
* installing, trusting and enabling are three separate acts, each traced.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from archx_agent.adapters.extension_runtime import ExtensionRuntime
from archx_agent.helpers.exceptions import (
    ConflictError,
    ExtensionError,
    ExtensionTrustError,
    NotFoundError,
    PathEscapesRootError,
    ValidationError,
)
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.paths import is_within
from archx_agent.helpers.timeutil import iso_now, new_id
from archx_agent.managers.permissions import CAPABILITIES, RISK_LEVELS

from .base import BaseManager
from .tools import ToolManager, ToolSpec

EXTENSION_TABLES = ("extensions", "extension_tools")

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")

MANIFEST_NAME = "extension.json"
SUPPORTED_ENTRY = ("process",)


def _safe(value: str) -> str:
    return _SAFE.sub("_", (value or "").strip()).strip("._") or "tool"


@dataclass
class Extension:
    id: str
    name: str
    version: str
    path: str
    manifest: dict[str, Any]
    trust: str
    enabled: bool
    installed_at: str
    updated_at: str
    manifest_hash: str | None = None
    trusted_by: str | None = None
    trusted_at: str | None = None
    notes: str | None = None
    last_error: str | None = None

    @property
    def trusted(self) -> bool:
        return self.trust == "trusted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "path": self.path,
            "trust": self.trust,
            "trusted": self.trusted,
            "enabled": self.enabled,
            "installed_at": self.installed_at,
            "updated_at": self.updated_at,
            "manifest_hash": self.manifest_hash,
            "trusted_by": self.trusted_by,
            "trusted_at": self.trusted_at,
            "notes": self.notes,
            "last_error": self.last_error,
            "tools": [
                t.get("name") for t in (self.manifest.get("tools") or []) if isinstance(t, dict)
            ],
        }


def _extension_from_row(row: dict[str, Any]) -> Extension:
    try:
        manifest = json.loads(row["manifest"]) if row.get("manifest") else {}
    except json.JSONDecodeError:  # pragma: no cover - corrupted row
        manifest = {}
    return Extension(
        id=row["id"],
        name=row["name"],
        version=row["version"],
        path=row.get("path") or "",
        manifest=manifest,
        trust=row.get("trust") or "untrusted",
        enabled=bool(row.get("enabled")),
        installed_at=row["installed_at"],
        updated_at=row["updated_at"],
        manifest_hash=row.get("manifest_hash"),
        trusted_by=row.get("trusted_by"),
        trusted_at=row.get("trusted_at"),
        notes=row.get("notes"),
        last_error=row.get("last_error"),
    )


def validate_manifest(manifest: Mapping[str, Any], *, path: str | None = None) -> dict[str, Any]:
    """Check a manifest and return a normalised copy. Raises ``ExtensionError``."""
    if not isinstance(manifest, Mapping):
        raise ExtensionError("extension.json must be a JSON object")
    name = str(manifest.get("name") or "").strip()
    if not _NAME_RE.match(name):
        raise ExtensionError(
            "extension name must be lowercase letters, digits, '.', '_' or '-' (max 64)"
        )
    version = str(manifest.get("version") or "").strip()
    if not version:
        raise ExtensionError("extension.json needs a version")
    tools = manifest.get("tools")
    if not isinstance(tools, list) or not tools:
        raise ExtensionError("extension.json needs a non-empty 'tools' list")
    normalised: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(tools):
        if not isinstance(raw, Mapping):
            raise ExtensionError(f"tools[{index}] must be an object")
        tool_name = str(raw.get("name") or "").strip()
        if not _NAME_RE.match(tool_name):
            raise ExtensionError(f"tools[{index}].name is not a valid tool name")
        if tool_name in seen:
            raise ExtensionError(f"duplicate tool {tool_name!r} in the manifest")
        seen.add(tool_name)
        capability = str(raw.get("capability") or "").strip()
        if capability not in CAPABILITIES:
            raise ExtensionError(
                f"{tool_name}: capability {capability!r} is not one this build knows "
                f"({', '.join(sorted(CAPABILITIES))})"
            )
        # Two accepted shapes: a flat {command: [...]} (the common case) and an explicit
        # {entry: {type: "process", command: [...]}} so a future entry type has a home.
        entry = raw.get("entry") or {}
        if not isinstance(entry, Mapping):
            raise ExtensionError(f"{tool_name}: 'entry' must be an object")
        entry_type = str(entry.get("type") or raw.get("type") or "process")
        if entry_type not in SUPPORTED_ENTRY:
            raise ExtensionError(
                f"{tool_name}: entry type {entry_type!r} is not supported "
                f"(this build supports {list(SUPPORTED_ENTRY)})"
            )
        command = entry.get("command") or raw.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
            raise ExtensionError(f"{tool_name}: entry.command must be a non-empty list of strings")
        root = Path(path).resolve() if path else None
        # argv[0] is the program (an interpreter, say) and may live anywhere on the
        # machine - the trust decision covers it. Everything after it is data the
        # extension ships and therefore must stay inside its own directory.
        for part in command[1:]:
            if Path(part).is_absolute():
                if root is None or not is_within(root, part):
                    raise ExtensionError(
                        f"{tool_name}: command path {part!r} is outside the extension directory"
                    )
            elif ".." in Path(part).parts and root is not None:
                try:
                    resolved = (root / part).resolve()
                except OSError as exc:  # pragma: no cover
                    raise ExtensionError(f"{tool_name}: bad command path {part!r}: {exc}") from exc
                if not is_within(root, resolved):
                    raise ExtensionError(
                        f"{tool_name}: command argument {part!r} escapes the extension directory"
                    )
        inputs_raw = raw.get("inputs") or {}
        inputs: dict[str, str] = {}
        types: dict[str, str] = {}
        if not isinstance(inputs_raw, Mapping):
            raise ExtensionError(f"{tool_name}: 'inputs' must be an object")
        for arg_name, spec in inputs_raw.items():
            if isinstance(spec, Mapping):
                arg_type = str(spec.get("type") or "string")
                inputs[str(arg_name)] = str(spec.get("description") or arg_name)
            else:
                arg_type = "string"
                inputs[str(arg_name)] = str(spec)
            types[str(arg_name)] = {
                "string": "str",
                "integer": "int",
                "number": "float",
                "boolean": "bool",
                "json": "json",
                "object": "json",
                "array": "json",
            }.get(arg_type, "str")
        required = raw.get("required") or []
        if not isinstance(required, list):
            raise ExtensionError(f"{tool_name}: 'required' must be a list")
        unknown_required = [r for r in required if str(r) not in inputs]
        if unknown_required:
            raise ExtensionError(
                f"{tool_name}: required argument(s) {unknown_required} are not declared in inputs"
            )
        normalised.append(
            {
                "name": tool_name,
                "description": str(raw.get("description") or f"extension tool {tool_name}")[:300],
                "capability": capability,
                "risk": CAPABILITIES[capability].risk,
                "claimed_risk": raw.get("risk"),
                "command": list(command),
                "inputs": inputs,
                "types": types,
                "required": [str(r) for r in required],
                "supports_dry_run": bool(raw.get("supports_dry_run")),
            }
        )
    return {
        "name": name,
        "version": version,
        "description": str(manifest.get("description") or ""),
        "author": str(manifest.get("author") or ""),
        "homepage": str(manifest.get("homepage") or ""),
        "tools": normalised,
    }


class ExtensionManager(BaseManager):
    tables = EXTENSION_TABLES

    def __init__(
        self,
        store,
        coordinator,
        *,
        events=None,
        config=None,
        tools: ToolManager | None = None,
        runtime: ExtensionRuntime | None = None,
    ) -> None:
        self.config = config
        self.tools = tools
        self.runtime = runtime or ExtensionRuntime()
        super().__init__(store, coordinator, events=events)

    def _cfg(self, key: str, default: Any) -> Any:
        if self.config is None:
            return default
        try:
            return self.config.get(key)
        except Exception:  # noqa: BLE001
            return default

    # -- persistence ------------------------------------------------------
    def register_handlers(self) -> None:
        self.coordinator.register("extension.install", self._apply_install)
        self.coordinator.register("extension.update", self._apply_update)
        self.coordinator.register("extension.delete", self._apply_delete)
        self.coordinator.register("extension.tool.upsert", self._apply_tool_upsert)
        self.coordinator.register("extension.tool.delete", self._apply_tool_delete)

    def _apply_install(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        e = payload["extension"]
        tx.execute(
            "INSERT INTO extensions(id, name, version, path, manifest, trust, enabled,"
            " installed_at, updated_at, last_error, manifest_hash, trusted_by, trusted_at, notes)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                e["id"], e["name"], e["version"], e.get("path"), json_text(e["manifest"]),
                e.get("trust", "untrusted"), 1 if e.get("enabled") else 0,
                e["installed_at"], e["updated_at"], e.get("last_error"),
                e.get("manifest_hash"), e.get("trusted_by"), e.get("trusted_at"), e.get("notes"),
            ),
        )
        return {"id": e["id"]}

    def _apply_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        fields = dict(payload["fields"])
        sets, params = [], []
        for key, value in fields.items():
            if key == "manifest":
                value = json_text(value)
            elif key in ("enabled",):
                value = 1 if value else 0
            sets.append(f"{key} = ?")
            params.append(value)
        sets.append("updated_at = ?")
        params.append(payload.get("updated_at") or iso_now())
        params.append(payload["id"])
        tx.execute(f"UPDATE extensions SET {', '.join(sets)} WHERE id = ?", params)
        return {"id": payload["id"]}

    def _apply_delete(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute("DELETE FROM extension_tools WHERE extension_id = ?", (payload["id"],))
        tx.execute("DELETE FROM extensions WHERE id = ?", (payload["id"],))
        return {"id": payload["id"]}

    def _apply_tool_upsert(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        t = payload["tool"]
        tx.execute(
            "INSERT INTO extension_tools(id, extension_id, name, description, capability, risk,"
            " schema, entry, enabled, discovered_at) VALUES (?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(extension_id, name) DO UPDATE SET description=excluded.description,"
            " capability=excluded.capability, risk=excluded.risk, schema=excluded.schema,"
            " entry=excluded.entry, enabled=excluded.enabled, discovered_at=excluded.discovered_at",
            (
                t["id"], t["extension_id"], t["name"], t.get("description") or "",
                t.get("capability"), t.get("risk"), json_text(t.get("schema") or {}),
                json_text(t.get("entry") or {}), 1 if t.get("enabled") else 0,
                t["discovered_at"],
            ),
        )
        return {"id": t["id"]}

    def _apply_tool_delete(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute(
            "DELETE FROM extension_tools WHERE extension_id = ? AND name = ?",
            (payload["extension_id"], payload["name"]),
        )
        return {"extension_id": payload["extension_id"], "name": payload["name"]}

    # -- install / list ---------------------------------------------------
    def install(self, path: str | Path, *, trust: bool = False, enable: bool = False) -> Extension:
        root = Path(path).expanduser().resolve()
        manifest_path = root / MANIFEST_NAME
        if not root.is_dir():
            raise NotFoundError(f"no such directory: {root}")
        if not manifest_path.is_file():
            raise NotFoundError(f"{MANIFEST_NAME} is missing in {root}")
        raw_bytes = manifest_path.read_bytes()
        try:
            manifest = json.loads(raw_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ExtensionError(f"{MANIFEST_NAME} is not valid JSON: {exc}") from exc
        normalised = validate_manifest(manifest, path=str(root))
        digest = hashlib.sha256(raw_bytes).hexdigest()
        existing = self._find(normalised["name"])
        now = iso_now()
        if existing is not None:
            if existing.manifest_hash == digest:
                raise ConflictError(
                    f"extension {normalised['name']!r} is already installed with this exact "
                    f"manifest (id {existing.id})"
                )
            self._write(
                "extension.update",
                {
                    "id": existing.id,
                    "fields": {
                        "version": normalised["version"],
                        "path": str(root),
                        "manifest": normalised,
                        "manifest_hash": digest,
                        "trust": "untrusted",
                        "trusted_by": None,
                        "trusted_at": None,
                        "notes": "reinstalled: trust was reset because the manifest changed",
                    },
                    "updated_at": now,
                },
            )
            updated = self.extension(existing.id)
            self._unregister(updated)
            self._sync_tools(updated)
            self.trace(
                "extension", "reinstalled", payload={"name": updated.name, "hash": digest}
            )
            return self.extension(existing.id)
        extension = Extension(
            id=new_id("ex_"),
            name=normalised["name"],
            version=normalised["version"],
            path=str(root),
            manifest=normalised,
            trust="trusted" if trust else "untrusted",
            enabled=enable,
            installed_at=now,
            updated_at=now,
            manifest_hash=digest,
            trusted_by="user:cli" if trust else None,
            trusted_at=now if trust else None,
        )
        self._write(
            "extension.install",
            {
                "extension": {
                    "id": extension.id,
                    "name": extension.name,
                    "version": extension.version,
                    "path": extension.path,
                    "manifest": normalised,
                    "trust": extension.trust,
                    "enabled": extension.enabled,
                    "installed_at": now,
                    "updated_at": now,
                    "manifest_hash": digest,
                    "trusted_by": extension.trusted_by,
                    "trusted_at": extension.trusted_at,
                }
            },
        )
        stored = self.extension(extension.id)
        self._sync_tools(stored)
        self.trace(
            "extension",
            "installed",
            payload={
                "name": stored.name,
                "version": stored.version,
                "hash": digest,
                "tools": [t["name"] for t in normalised["tools"]],
                "trust": stored.trust,
                "enabled": stored.enabled,
            },
        )
        return self.extension(extension.id)

    def _find(self, ref: str) -> Extension | None:
        row = self.store.query_one("SELECT * FROM extensions WHERE id = ? OR name = ?", (ref, ref))
        return _extension_from_row(row) if row else None

    def extension(self, ref: str) -> Extension:
        found = self._find(ref)
        if found is None:
            raise NotFoundError(f"no extension {ref!r}")
        return found

    def extensions(self) -> list[Extension]:
        return [
            _extension_from_row(row)
            for row in self.store.query("SELECT * FROM extensions ORDER BY name")
        ]

    def trust(self, ref: str, *, trusted: bool = True) -> Extension:
        extension = self.extension(ref)
        self._write(
            "extension.update",
            {
                "id": extension.id,
                "fields": {
                    "trust": "trusted" if trusted else "untrusted",
                    "trusted_by": "user:cli" if trusted else None,
                    "trusted_at": iso_now() if trusted else None,
                },
                "updated_at": iso_now(),
            },
        )
        updated = self.extension(extension.id)
        if trusted:
            self._sync_tools(updated)
        else:
            self._unregister(updated)
        self.trace(
            "extension",
            "trusted" if trusted else "untrusted",
            payload={"name": updated.name, "tools": [t["name"] for t in self.tools_of(updated.id)]},
        )
        return self.extension(extension.id)

    def set_enabled(self, ref: str, *, enabled: bool = True) -> Extension:
        extension = self.extension(ref)
        self._write(
            "extension.update",
            {"id": extension.id, "fields": {"enabled": enabled}, "updated_at": iso_now()},
        )
        updated = self.extension(extension.id)
        if enabled:
            self._sync_tools(updated)
        else:
            self._unregister(updated)
        self.trace(
            "extension", "enabled" if enabled else "disabled", payload={"name": updated.name}
        )
        return self.extension(extension.id)

    def remove(self, ref: str) -> Extension:
        extension = self.extension(ref)
        self._unregister(extension)
        self._write("extension.delete", {"id": extension.id})
        self.trace("extension", "removed", payload={"name": extension.name})
        return extension

    def tools_of(self, extension_id: str) -> list[dict[str, Any]]:
        rows = self.store.query(
            "SELECT * FROM extension_tools WHERE extension_id = ? ORDER BY name", (extension_id,)
        )
        for row in rows:
            for key in ("schema", "entry"):
                if row.get(key):
                    try:
                        row[key] = json.loads(row[key])
                    except json.JSONDecodeError:  # pragma: no cover
                        row[key] = {}
                else:
                    row[key] = {}
        return rows

    # -- registration -----------------------------------------------------
    def _sync_tools(self, extension: Extension) -> list[str]:
        """(Re)register the extension's tools when it is trusted *and* enabled."""
        if self.tools is None:
            return []
        active = extension.trusted and extension.enabled and bool(self._cfg("extensions.enabled", True))
        registered: list[str] = []
        for tool in extension.manifest.get("tools") or []:
            spec = self._spec_for(extension, tool)
            self._write(
                "extension.tool.upsert",
                {
                    "tool": {
                        "id": new_id("et_"),
                        "extension_id": extension.id,
                        "name": tool["name"],
                        "description": tool["description"],
                        "capability": tool["capability"],
                        "risk": tool["risk"],
                        "schema": {"inputs": tool["inputs"], "required": tool["required"]},
                        "entry": {"type": "process", "command": tool["command"]},
                        "enabled": active,
                        "discovered_at": iso_now(),
                    }
                },
            )
            if active:
                self.tools.declare_spec(spec, self._handler(extension, tool))
                registered.append(spec.name)
        if not active:
            self._unregister(extension, keep_rows=True)
        self.trace(
            "extension",
            "tools.synced",
            payload={
                "extension": extension.name,
                "registered": registered,
                "active": active,
                "reason": None if active else self._not_active_reason(extension),
            },
        )
        return registered

    def _not_active_reason(self, extension: Extension) -> str:
        if not self._cfg("extensions.enabled", True):
            return "extensions are disabled (extensions.enabled=false)"
        if not extension.trusted and not extension.enabled:
            return "the extension is untrusted and disabled"
        if not extension.trusted:
            return "the extension is not trusted (archx-agent extensions trust <name>)"
        return "the extension is disabled (archx-agent extensions enable <name>)"

    @staticmethod
    def spec_name(extension_name: str, tool_name: str) -> str:
        return f"ext.{_safe(extension_name)}.{_safe(tool_name)}"

    def _spec_for(self, extension: Extension, tool: Mapping[str, Any]) -> ToolSpec:
        return ToolSpec(
            name=self.spec_name(extension.name, str(tool["name"])),
            summary=str(tool["description"])[:200],
            capability=str(tool["capability"]),
            risk=str(tool["risk"]),
            inputs=dict(tool["inputs"]),
            required=tuple(tool["required"]),
            types=dict(tool["types"]),
            supports_dry_run=bool(tool.get("supports_dry_run")),
            side_effects=f"runs {tool['command'][0]} from extension {extension.name}",
            builtin=False,
            origin=f"extension:{extension.name}",
        )

    def _handler(self, extension: Extension, tool: Mapping[str, Any]):
        argv = list(tool["command"])
        ext_name = extension.name
        tool_name = str(tool["name"])
        root = extension.path

        def call(args: dict[str, Any]) -> dict[str, Any]:
            if not self._cfg("extensions.enabled", True):
                raise ExtensionTrustError("extensions are disabled (extensions.enabled=false)")
            current = self.extension(ext_name)
            if not current.trusted:
                raise ExtensionTrustError(
                    f"extension {ext_name!r} is not trusted; its tools may not run"
                )
            if not current.enabled:
                raise ExtensionTrustError(
                    f"extension {ext_name!r} is disabled (archx-agent extensions enable {ext_name})"
                )
            resolved: list[str] = [argv[0]]  # the program itself (see validate_manifest)
            for part in argv[1:]:
                if Path(part).is_absolute():
                    if not is_within(root, part):
                        raise ExtensionError(f"command path {part!r} is outside the extension")
                    resolved.append(part)
                    continue
                candidate = (Path(root) / part).resolve()
                if ("/" in part or part.endswith(".py")) and not is_within(root, candidate):
                    raise PathEscapesRootError(
                        "extension command escapes its directory", path=part, root=root
                    )
                resolved.append(part)
            request = {"extension": ext_name, "tool": tool_name, "arguments": args}
            result = self.runtime.run(
                resolved,
                request,
                cwd=root,
                timeout=int(self._cfg("tools.timeout_seconds", 60)),
            )
            self.trace(
                "extension",
                "tool.ran",
                payload={"extension": ext_name, "tool": tool_name, "result": result},
            )
            return result

        return call

    def _unregister(self, extension: Extension, *, keep_rows: bool = False) -> None:
        if self.tools is not None:
            for row in self.tools_of(extension.id):
                try:
                    self.tools.unregister_spec(self.spec_name(extension.name, row["name"]))
                except Exception:  # noqa: BLE001 - already gone
                    continue
        if not keep_rows:
            for row in self.tools_of(extension.id):
                self._write(
                    "extension.tool.delete",
                    {"extension_id": extension.id, "name": row["name"]},
                )

    def restore(self) -> dict[str, int]:
        """Re-register trusted, enabled extensions after a restart (no writes)."""
        if not self._cfg("extensions.enabled", True) or self.tools is None:
            return {"extensions": 0, "tools": 0}
        extensions = 0
        tools = 0
        for extension in self.extensions():
            if not (extension.trusted and extension.enabled):
                continue
            if not Path(extension.path).is_dir():
                self.trace(
                    "extension", "restore_skipped", status="error",
                    error=f"directory missing: {extension.path}",
                    payload={"extension": extension.name},
                )
                continue
            registered = 0
            for tool in extension.manifest.get("tools") or []:
                self.tools.declare_spec(self._spec_for(extension, tool), self._handler(extension, tool))
                registered += 1
            if registered:
                extensions += 1
                tools += registered
        return {"extensions": extensions, "tools": tools}

    def status(self) -> list[dict[str, Any]]:
        out = []
        for extension in self.extensions():
            tools = self.tools_of(extension.id)
            out.append(
                {
                    **extension.to_dict(),
                    "tool_count": len(tools),
                    "registered": sum(1 for t in tools if t.get("enabled")),
                }
            )
        return out


__all__ = [
    "EXTENSION_TABLES",
    "MANIFEST_NAME",
    "Extension",
    "ExtensionManager",
    "validate_manifest",
]
