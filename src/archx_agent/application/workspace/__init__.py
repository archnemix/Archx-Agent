"""The workspace: one opened Archx environment (database, trace, managers, runtimes).

Opening a workspace is explicit and ordered:

1. resolve configuration (file + env + overrides);
2. create directories;
3. open the primary database;
4. back it up before a schema upgrade, then migrate;
5. open the trace database (separate file, best effort);
6. create the shared write coordinator, wire managers and register write kinds;
7. replay interrupted intents, then recover consumers and restore plugins.

Failure at any step raises a domain error with enough context to act on, and
never leaves a half-initialised workspace silently usable.

Public compatibility surface. Implementation responsibilities live in sibling modules.
"""

from .workspace import Workspace as Workspace
from .constants import NETWORK_RUNTIMES as NETWORK_RUNTIMES
from .embeddings import _build_embedding_provider as _build_embedding_provider
from .tools import _build_tool_runtime as _build_tool_runtime
from .opening import open_workspace as open_workspace


__all__ = ["Workspace", "open_workspace"]
