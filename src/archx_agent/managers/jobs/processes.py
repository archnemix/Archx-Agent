"""Process liveness checks for durable jobs."""

from __future__ import annotations

import os


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - another user's process
        return True
    except OSError:  # pragma: no cover - defensive
        return False
    return True
