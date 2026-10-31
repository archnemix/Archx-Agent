"""The tool registry: what a tool is, what it may do, and the record of it doing it.

Every tool declares:

* the **capability** it needs (or ``None`` for a read-only tool that touches
  nothing outside the process),
* its **risk** and its **side effects** (what the user is consenting to),
* its **inputs** with types, so a hallucinated argument is a clear validation
  error instead of a silently ignored parameter,
* whether it supports a **dry run**.

The registry is code, not data. A tool cannot appear because a model asked for
it, and a tool cannot change its own capability: the capability comes from
:data:`BUILTIN_SPECS`, and the permission centre reads only that. Extensions and
MCP servers (M23) add specs through their own registration path with their trust
level attached.

Execution order is fixed and observable:

1. validate the request (unknown tool, unknown/invalid arguments);
2. refuse a dry run on a tool that cannot do one;
3. preflight hard denials (e.g. the shell denylist) - these cannot be approved;
4. ask the permission centre, consuming a single-use grant **before** the work;
5. run the operation, then record the run row and its trace events.

Public compatibility surface. Implementation responsibilities live in sibling modules.
"""

from .manager import ToolManager as ToolManager
from .constants import (
    TOOL_TABLES as TOOL_TABLES,
    BUILTIN_SPECS as BUILTIN_SPECS,
    BUILTIN_TOOLS as BUILTIN_TOOLS,
)
from .records import (
    ToolSpec as ToolSpec,
    ToolContext as ToolContext,
    ToolRun as ToolRun,
)
from .validation import _type_ok as _type_ok, _coerce as _coerce
from .outcomes import (
    _result_ok as _result_ok,
    _failure_reason as _failure_reason,
    _elapsed_ms as _elapsed_ms,
)


__all__ = [
    "BUILTIN_SPECS",
    "BUILTIN_TOOLS",
    "TOOL_TABLES",
    "ToolContext",
    "ToolManager",
    "ToolRun",
    "ToolSpec",
]
