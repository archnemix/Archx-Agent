"""Record types and row conversion for evidence-based research."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from archx_agent.helpers.exceptions import (
    ArchxError,
)


class ResearchBlocked(ArchxError):
    """The run stopped because a capability it needs is not granted yet."""

    def __init__(
        self, message: str, *, run_id: str | None, approval_id: str | None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.run_id = run_id
        self.approval_id = approval_id


@dataclass
class SourceDoc:
    """A document the runner actually read (or tried to)."""

    kind: str
    ref: str
    title: str
    text: str = ""
    excerpt: str = ""
    publisher: str = "workspace"
    url: str = ""
    status: str = "fetched"
    error: str | None = None
    checksum: str | None = None
    bytes: int | None = None
    relevance: float = 0.0
    stance: str = "unknown"
    credibility: str = "internal"
    claims: list[dict[str, Any]] = field(default_factory=list)
    subquestion: int = 0
    truncated: bool = False
    also_relevant: list[int] = field(default_factory=list)
    number: int = 0  # [S<n>] once persisted

    @property
    def usable(self) -> bool:
        """Fetched *and* carrying text. An empty page is not evidence."""
        return self.status == "fetched" and bool((self.excerpt or self.text).strip())
