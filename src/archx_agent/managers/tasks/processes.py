"""Process liveness checks for task history."""

from __future__ import annotations

import os


def _pid_alive(pid: int) -> bool:
    """Is this pid alive? Used only to avoid declaring someone else's work dead."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:  # pragma: no cover - defensive
        return False
    return True
