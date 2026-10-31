"""Dataset preparation: candidates, cleaning with reasons, stable splits, and a manifest you can check.

Three properties are what make a prepared corpus worth trusting, and each of them is easy to lose
in a pipeline that only *looks* tidy:

**A dataset is its manifest.** :meth:`DatasetService.build` writes a JSONL export and a manifest, and
records a sha256 over the manifest's sorted lines. :meth:`DatasetService.verify` recomputes that
hash from the files on disk and **disagrees out loud** when it does not match - the same instinct as
M33's simulation replay, because a corpus whose contents drifted quietly is worse than no corpus.

**Nothing is dropped silently.** Every candidate is a row, whether it survived cleaning or not, and
a dropped row keeps the rule that dropped it and the reason. Deduplication keeps the first copy by
path and marks the rest, so "two copies of the same document" is visible instead of invisible.

**A split is a function of the record, not of its position.** Records are assigned by hashing
``seed`` together with the record's own sha256, so adding a file tomorrow does not move the files
that are already in ``train``. A positional shuffle would look just as good in a demonstration and
would silently invalidate every model trained on yesterday's split. Identical content is refused
across splits - a leak is a data bug that flatters the evaluation, so it is a refusal with the
pairs named rather than a warning nobody reads.

The fourth property is smaller but decides how the rest is used: **the license is recorded per
source, and "unknown" is written as unknown**. Nothing here infers permission from a directory name.

Public compatibility surface. Implementation responsibilities live in sibling modules.
"""

from .service import DatasetService as DatasetService
from .constants import (
    TEXT_SUFFIXES as TEXT_SUFFIXES,
    RULES as RULES,
    LEAK_TEXT as LEAK_TEXT,
)
from .hashing import _norm_sha as _norm_sha, _sha as _sha
