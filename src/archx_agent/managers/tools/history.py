"""History operations for tool execution."""

from __future__ import annotations

from typing import Any

from archx_agent.managers.tools.records import ToolSpec, ToolContext, ToolRun


class ToolManagerHistoryMixin:
    """History responsibility for ToolManager."""

    def _link_task(self, spec: ToolSpec, context: ToolContext, run: ToolRun) -> None:
        """Record a tool call on the task's timeline, if the call belongs to a task."""
        tasks = getattr(self, "tasks", None)
        if tasks is None or not context.task_id:
            return
        try:
            tasks.link(context.task_id, tools=[spec.name])
            detail = f"{spec.name} {run.status}"
            if run.error:
                detail += f": {run.error[:300]}"
            tasks.log(context.task_id, "tool", detail=detail)
        except Exception:  # noqa: BLE001 - bookkeeping must never fail the call
            pass

    def _record_file_change(
        self, spec: ToolSpec, args: dict[str, Any], run: ToolRun, context: ToolContext
    ) -> None:
        if spec.name not in {"fs.write", "fs.write_bytes", "fs.delete"}:
            return
        if run.status != "succeeded" or run.dry_run or not run.result:
            return
        self.trace(
            "file_change",
            run.result.get("path") or args.get("path"),
            status="ok",
            conversation_id=context.conversation_id,
            task_id=context.task_id,
            project_id=context.project_id,
            payload={
                "tool": spec.name,
                "run_id": run.id,
                "path": run.result.get("path"),
                "bytes": run.result.get("bytes_written") or run.result.get("bytes"),
                "sha256": run.result.get("sha256"),
                "previous_sha256": run.result.get("previous_sha256"),
                "deleted": bool(run.result.get("deleted")),
                "dry_run": run.dry_run,
            },
        )
