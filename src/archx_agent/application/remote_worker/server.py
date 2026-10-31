"""Explicit remote worker serving entry point; importing does not start a server."""

from __future__ import annotations
from typing import Any
from .worker import Worker
from .http import make_server
from .protocol import PROTOCOL


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 9001,
    name: str | None = None,
    delay: float = 0.0,
    ready: Any = None,
    allow_exec: bool = False,
    token: str | None = None,
    workdir: str | None = None,
    max_running_jobs: int = 4,
    max_jobs: int = 128,
) -> None:
    worker = Worker(
        name=name, delay=delay, allow_exec=allow_exec, token=token, workdir=workdir,
        max_running_jobs=max_running_jobs, max_jobs=max_jobs
    )
    server = make_server(worker, host=host, port=port)
    if ready is not None:  # pragma: no cover - used by the acceptance script
        ready(server)
    modes = []
    if worker.allow_exec:
        modes.append("command execution ON")
    if worker.token:
        modes.append("bearer token required")
    print(
        f"archx worker {worker.name} on http://{host}:{server.server_address[1]}"
        f" speaking {PROTOCOL}"
        + (
            f" ({', '.join(modes)}; work {worker.workdir})"
            if modes
            else " (training only)"
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - interactive
        pass
    finally:
        server.server_close()
