"""Context strategy manager (M19).

Five selectable strategies share the same safeguards:

1. ``oldest_first``  - drop old complete turns, newest kept.
2. ``summarize``     - summarise older messages, originals preserved.
3. ``ai_select``     - relevance-picked messages/memories with reasons.
4. ``manual``        - the user decides what is in the window.
5. ``ai_proposed``   - the AI proposes changes; nothing is applied without approval.

Safeguards (applied by every strategy):

* the tokenizer is explicit (exact or documented approximation);
* the budget accounts for the output reservation, prompt overhead, tool schemas
  and the memory share of the window;
* the current user request is never truncated - if it does not fit we raise
  :class:`ContextOverflowError` explaining the numbers;
* pinned content is never dropped silently;
* half a tool call/result pair is never kept (the pair is one unit);
* compaction (summarising / excluding) never deletes stored messages;
* the final manifest is persisted and traced, so "what did the model see" is
  always answerable.

Public compatibility surface. Implementation responsibilities live in sibling modules.
"""

from .manager import ContextManager as ContextManager
from .constants import (
    CONTEXT_TABLES as CONTEXT_TABLES,
    STRATEGIES as STRATEGIES,
    Summarizer as Summarizer,
)
from .records import (
    ContextItem as ContextItem,
    ContextManifest as ContextManifest,
    Proposal as Proposal,
    Summary as Summary,
    _summary_from_row as _summary_from_row,
)
from .formatting import (
    _format_memory as _format_memory,
    _message_units as _message_units,
    _message_units_flat as _message_units_flat,
)


__all__ = [
    "ContextManager",
    "ContextManifest",
    "ContextItem",
    "Proposal",
    "Summary",
    "STRATEGIES",
]
