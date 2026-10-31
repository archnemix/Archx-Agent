"""Extension manifest capability, risk, schema and rooted-entry validation."""

from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping
from archx_agent.helpers.exceptions import ExtensionError
from archx_agent.helpers.paths import is_within
from archx_agent.managers.permissions import CAPABILITIES
from .records import _NAME_RE, SUPPORTED_ENTRY


def validate_manifest(
    manifest: Mapping[str, Any], *, path: str | None = None
) -> dict[str, Any]:
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
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(x, str) for x in command)
        ):
            raise ExtensionError(
                f"{tool_name}: entry.command must be a non-empty list of strings"
            )
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
                    raise ExtensionError(
                        f"{tool_name}: bad command path {part!r}: {exc}"
                    ) from exc
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
                "description": str(
                    raw.get("description") or f"extension tool {tool_name}"
                )[:300],
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
