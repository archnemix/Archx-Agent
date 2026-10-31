"""Researcher Mode: decompose a question, read real sources, and report only what they say.

The failure mode of an AI researcher is confident prose with no evidence behind it, so this
module is built around four rules:

**The plan is data, and it says who made it.** ``planned_by`` is ``model`` only when a model
returned a plan that parsed and passed validation; otherwise it is ``rules`` and the report
says so. A rules plan is deterministic - the same question produces the same plan - which is
also what makes the whole run reproducible when no model is configured.

**Every claim carries a citation, and citations are checked.** The report is assembled from
quoted excerpts and each quote is tagged ``[S<n>]``. A citation that names a source that does
not exist is a defect the verifier reports. Prose from a model is *demoted*, not trusted: any
paragraph without a valid citation is moved into a section titled "statements I could not tie
to a source" instead of being presented as a finding.

**A source that could not be read is still recorded.** Fetch failures are rows with
``status = 'failed'`` and an error, they appear in Limitations, and they never count towards
coverage. The user can see what the run tried.

**Coverage is computed, not asserted.** ``coverage`` is the fraction of subquestions with at
least one usable source. A report with coverage 0 says "I found no evidence" in its first
line, and the CLI exits 3 rather than 0.

Web research goes through the ``net.fetch`` tool, which means through the permission centre:
the first attempt queues an approval and nothing is fetched until the user decides.

Public compatibility surface. Implementation responsibilities live in sibling modules.
"""

from .runner import ResearchRunner as ResearchRunner
from .constants import (
    EVIDENCE_KINDS as EVIDENCE_KINDS,
    _STOPWORDS as _STOPWORDS,
    _CITE_RE as _CITE_RE,
)
from .records import ResearchBlocked as ResearchBlocked, SourceDoc as SourceDoc
from .text import (
    _terms as _terms,
    _coverage as _coverage,
    _sentences as _sentences,
    _excerpt as _excerpt,
    _subject as _subject,
    _short as _short,
    _clean as _clean,
    _quote as _quote,
    _host as _host,
    _sha256 as _sha256,
    _query_for as _query_for,
    _assign_subquestion as _assign_subquestion,
    _best_subquestion as _best_subquestion,
    _settings_of as _settings_of,
)
from .parsing import (
    _parse_plan as _parse_plan,
    _parse_judgement as _parse_judgement,
    _extract_json as _extract_json,
)
from .planning_rules import _rules_plan as _rules_plan
from .formatting import _to_html as _to_html, citation_numbers as citation_numbers


__all__ = [
    "EVIDENCE_KINDS",
    "ResearchBlocked",
    "ResearchRunner",
    "SourceDoc",
]
