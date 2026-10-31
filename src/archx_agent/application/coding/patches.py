"""Patches operations for coding sessions."""

from __future__ import annotations

import difflib


def _unified_diff(
    relative: str, before: str, after: str, *, before_available: bool = True
) -> tuple[str, int, int]:
    """A patch a human can read, and the line counts that go with it."""
    if not before_available:
        return "", 0, 0
    old = before.splitlines(keepends=True)
    new = after.splitlines(keepends=True)
    # A file that did not end in a newline would otherwise produce a last line without one,
    # which most patch tools accept but which reads as a mistake in a diff.
    if old and not old[-1].endswith("\n"):
        old[-1] += "\n"
    if new and not new[-1].endswith("\n"):
        new[-1] += "\n"
    lines = list(
        difflib.unified_diff(
            old, new, fromfile=f"a/{relative}", tofile=f"b/{relative}", n=3
        )
    )
    added = sum(
        1 for line in lines if line.startswith("+") and not line.startswith("+++")
    )
    removed = sum(
        1 for line in lines if line.startswith("-") and not line.startswith("---")
    )
    return "".join(lines), added, removed
