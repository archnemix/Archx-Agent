"""Dispatch operations for tool execution."""

from __future__ import annotations

import base64
from typing import Any

from archx_agent.helpers.exceptions import (
    ToolNotFoundError,
    ToolValidationError,
)
from archx_agent.managers.tools.records import ToolSpec


class ToolManagerDispatchMixin:
    """Dispatch responsibility for ToolManager."""

    def _dispatch(
        self, spec: ToolSpec, args: dict[str, Any], *, dry_run: bool
    ) -> dict[str, Any]:
        runtime = self.runtime
        if spec.name == "fs.read":
            return runtime.read_text(
                args["path"],
                start_line=int(args.get("start_line") or 1),
                max_lines=int(args["max_lines"]) if args.get("max_lines") else None,
            )
        if spec.name == "fs.list":
            return runtime.list_dir(
                args.get("path") or ".", limit=int(args.get("limit") or 500)
            )
        if spec.name == "fs.probe":
            return runtime.probe_file(
                args["path"],
                head_bytes=int(args["head_bytes"]) if args.get("head_bytes") else 4096,
            )
        if spec.name == "fs.write":
            return runtime.write_text(
                args["path"],
                args["content"],
                create_parents=bool(args.get("create_parents", True)),
                append=bool(args.get("append", False)),
                dry_run=dry_run,
            )
        if spec.name == "fs.write_bytes":
            # Refuse before allocating the decoded byte string; the runtime checks exact size too.
            if len(args["content_base64"]) > 4 * ((runtime.max_file_bytes + 2) // 3):
                raise ToolValidationError("binary payload exceeds tools.max_file_bytes")
            try:
                payload = base64.b64decode(args["content_base64"], validate=True)
            except (ValueError, TypeError) as exc:
                raise ToolValidationError(
                    f"content_base64 is not valid base64: {exc}"
                ) from exc
            return runtime.write_bytes(
                args["path"],
                payload,
                create_parents=bool(args.get("create_parents", True)),
                dry_run=dry_run,
            )
        if spec.name == "fs.delete":
            return runtime.delete(args["path"], dry_run=dry_run)
        if spec.name == "shell.run":
            return runtime.run(
                args["command"],
                cwd=args.get("cwd"),
                timeout=int(args["timeout"])
                if args.get("timeout")
                else int(self._cfg("tools.timeout_seconds", 60)),
            )
        if spec.name == "net.fetch":
            from archx_agent.adapters.net_fetch import fetch_limits, fetch_url

            limits = fetch_limits(self.config)
            allow_private = (
                args["allow_private_hosts"]
                if "allow_private_hosts" in args
                else limits["allow_private_hosts"]
            )
            result = fetch_url(
                args["url"],
                timeout=float(args.get("timeout") or limits["timeout_seconds"]),
                max_bytes=int(args.get("max_bytes") or limits["max_bytes"]),
                max_redirects=int(args.get("max_redirects") or limits["max_redirects"]),
                allow_private_hosts=bool(allow_private),
            )
            # The full text can be large; the run result keeps a bounded copy and says so.
            keep = int(self._cfg("tools.fetch_store_chars", 20000))
            if len(result.get("text") or "") > keep:
                result["text"] = result["text"][:keep]
                result["text_truncated"] = True
            else:
                result["text_truncated"] = False
            result["limits"] = limits
            return result
        extra = self._handlers.get(spec.name)
        if extra is not None:
            return extra(args)
        if spec.name == "archx.info":
            info = dict(self._info_provider()) if self._info_provider else {}
            info["tool_limits"] = runtime.limits()
            return info
        raise ToolNotFoundError(
            f"tool {spec.name!r} has no handler"
        )  # pragma: no cover
