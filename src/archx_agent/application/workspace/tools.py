"""Tools operations for workspace composition."""

from __future__ import annotations

from pathlib import Path

from archx_agent.adapters.local_tools import LocalToolRuntime


def _build_tool_runtime(config) -> tuple[LocalToolRuntime | None, str | None]:
    """Create the file/shell sandbox, or explain why tools cannot run."""
    roots = [
        str(Path(x).expanduser())
        for x in (config.get("tools.roots") or [])
        if str(x).strip()
    ]
    if not roots:
        roots = [str(Path(config.path("paths.home")) / "workspace")]
    try:
        for root in roots:
            Path(root).mkdir(parents=True, exist_ok=True)
        runtime = LocalToolRuntime(
            roots=tuple(roots),
            max_file_bytes=int(config.get("tools.max_file_bytes")),
            max_output_bytes=int(config.get("tools.max_output_bytes")),
            timeout_seconds=int(config.get("tools.timeout_seconds")),
            denylist=tuple(str(x) for x in (config.get("tools.shell_denylist") or [])),
            home=str(Path(config.path("paths.home"))),
        )
        return runtime, None
    except Exception as exc:  # noqa: BLE001 - tools are optional, the rest still works
        return None, f"tool runtime unavailable ({exc}); tools will refuse to run"
