"""Remote operations for execution targets."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from archx_agent.helpers.exceptions import (
    ValidationError,
)
from archx_agent.managers.execution import ExecutionTarget


class ExecutionServiceRemoteMixin:
    """Remote responsibility for ExecutionService."""

    def _run_remote(
        self,
        target: ExecutionTarget,
        command: str,
        workdir: str,
        timeout: int | None,
        task_id: str | None,
    ) -> dict[str, Any]:
        endpoint = (
            target.endpoint or str(self.ws.config.get("remote.endpoint", "") or "")
        ).rstrip("/")
        if not endpoint:
            raise ValidationError("this remote target has no endpoint recorded")
        row = self.manager.begin(
            kind="remote",
            command=command,
            target_id=target.id,
            cwd=workdir,
            invocation=f"POST {endpoint}/exec",
            task_id=task_id,
        )
        body = json.dumps(
            {
                "command": command,
                "cwd": target.spec.get("cwd") or ".",
                "timeout": int(
                    timeout or self.ws.config.get("execution.timeout", 60) or 60
                ),
            }
        ).encode("utf-8")
        try:
            answer = self._post(f"{endpoint}/exec", body)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            finished = self.manager.finish(
                row.id,
                status="failed",
                note=f"the endpoint could not be reached: {exc}",
            )
            payload = self._view(finished)
            payload["reasons"] = [f"{endpoint} could not be reached: {exc}"]
            return payload
        if answer.get("refused"):
            finished = self.manager.finish(
                row.id, status="refused", note=str(answer["refused"])
            )
            payload = self._view(finished)
            payload["reasons"] = [str(answer["refused"])]
            return payload
        artifacts = self._write_outputs(row.id, answer)
        finished = self.manager.finish(
            row.id,
            status="timeout"
            if answer.get("timed_out")
            else ("ok" if int(answer.get("exit_code") or 0) == 0 else "failed"),
            exit_code=answer.get("exit_code"),
            duration_ms=answer.get("duration_ms"),
            stdout=str(answer.get("stdout") or ""),
            stderr=str(answer.get("stderr") or ""),
            stdout_path=artifacts.get("stdout"),
            stderr_path=artifacts.get("stderr"),
            truncated=bool(answer.get("truncated")),
            note=f"ran on {answer.get('machine') or endpoint}",
        )
        payload = self._view(finished)
        payload["machine"] = answer.get("machine")
        return payload

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        token = str(self.ws.config.get("remote.worker_token", "") or "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _post(
        self, url: str, body: bytes, *, timeout: float | None = None
    ) -> dict[str, Any]:
        limit = float(timeout or self.ws.config.get("remote.timeout", 10) or 10)
        request = urllib.request.Request(
            url, data=body, method="POST", headers=self._headers()
        )
        try:
            with urllib.request.urlopen(request, timeout=limit) as response:  # noqa: S310 - http(s)
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # A 401/403 from the worker is an answer, not a network failure: the body says why.
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except ValueError:
                raise
            payload.setdefault(
                "refused", f"the worker answered {exc.code}: {raw[:200]}"
            )
            return payload

    def _get(self, url: str, *, timeout: float | None = None) -> dict[str, Any]:
        limit = float(timeout or self.ws.config.get("remote.timeout", 10) or 10)
        request = urllib.request.Request(url, method="GET", headers=self._headers())
        with urllib.request.urlopen(request, timeout=limit) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))

    def _endpoint(self, target: ExecutionTarget) -> str:
        endpoint = (
            target.endpoint or str(self.ws.config.get("remote.endpoint", "") or "")
        ).rstrip("/")
        if not endpoint:
            raise ValidationError("this remote target has no endpoint recorded")
        return endpoint
