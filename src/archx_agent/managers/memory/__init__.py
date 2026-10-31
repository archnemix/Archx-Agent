"""The six memory systems (M17).

| kind | purpose | scope | injected into prompts | lifecycle |
|------|---------|-------|----------------------|-----------|
| active | current task state: goal, constraints, pending steps, tool state | conversation or task | yes, first | expires (TTL) / cleared when the task ends |
| permanent | user-approved durable preferences and facts | global | yes | explicit only; user edits/deletes |
| archival | historical reference material | any | **never** | retention policy marks expired |
| project | goals, decisions, requirements, known issues, commands | project | yes (project scope only) | lives with the project |
| solution | reusable verified solutions | global or project | yes, verified only | retired when disproven |
| learning | learner progress, mistakes, strengths | learner | yes (adaptive) | decays; never a permanent label |

Invariants enforced here:

* every record has provenance (source + origin) and timestamps;
* nothing is silently overwritten - edits snapshot the previous version;
* duplicates are detected (checksum exact, token similarity fuzzy);
* a *slot* conflict supersedes rather than overwrites;
* secrets are refused for permanent memory unless the caller explicitly opts in;
* an unverified solution can never be stored as ``verified``;
* archival memory is never injected into a prompt;
* every retrieval is logged, so "why was this in my context" is answerable.

Public compatibility surface. Implementation responsibilities live in sibling modules.
"""

from .manager import MemoryManager as MemoryManager
from .constants import (
    MEMORY_TABLES as MEMORY_TABLES,
    KINDS as KINDS,
    SCOPES as SCOPES,
    CATEGORIES as CATEGORIES,
    VERIFICATION_STATES as VERIFICATION_STATES,
    SOURCE_TYPES as SOURCE_TYPES,
    NEVER_INJECTED as NEVER_INJECTED,
    INJECTABLE as INJECTABLE,
    MAX_TITLE as MAX_TITLE,
    MAX_CONTENT as MAX_CONTENT,
    _WORD_RE as _WORD_RE,
    _STOPWORDS as _STOPWORDS,
)
from .records import (
    Memory as Memory,
    SearchHit as SearchHit,
    SearchOutcome as SearchOutcome,
    RetrievalResult as RetrievalResult,
    _row_to_memory as _row_to_memory,
)
from .ranking import (
    _normalize as _normalize,
    tokens_of as tokens_of,
    jaccard as jaccard,
    similarity as similarity,
    _strip_like as _strip_like,
    _is_expired as _is_expired,
)


__all__ = [
    "MemoryManager",
    "Memory",
    "SearchHit",
    "SearchOutcome",
    "RetrievalResult",
    "KINDS",
    "SCOPES",
    "CATEGORIES",
    "VERIFICATION_STATES",
    "INJECTABLE",
    "NEVER_INJECTED",
]
