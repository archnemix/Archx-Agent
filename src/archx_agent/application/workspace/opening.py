"""Public workspace-opening entry point for workspace composition."""

from __future__ import annotations

import os
from typing import Any, Mapping

from .workspace import Workspace


def open_workspace(
    *,
    home: str | os.PathLike[str] | None = None,
    config_path: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    overrides: Mapping[str, Any] | None = None,
    allow_test_double: bool | None = None,
) -> Workspace:
    return Workspace.open(
        home=home,
        config_path=config_path,
        env=env,
        overrides=overrides,
        allow_test_double=allow_test_double,
    )
