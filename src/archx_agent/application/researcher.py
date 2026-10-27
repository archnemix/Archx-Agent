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
"""

from __future__ import annotations

import html
import json
import re
import textwrap
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    ArchxError,
    ModelNotFoundError,
    NotFoundError,
    ValidationError,
)
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.research import MODES, STANCES
from archx_agent.managers.tools import ToolContext

EVIDENCE_KINDS = ("memory", "conversation", "task", "workflow", "file")
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "what", "when", "where", "which",
    "who", "why", "how", "does", "did", "are", "was", "were", "has", "have", "had", "into",
    "about", "would", "should", "could", "can", "you", "your", "our", "its", "their", "them",
    "than", "then", "there", "here", "also", "but", "not", "all", "any", "may", "might",
    "will", "one", "two", "use", "used", "using", "been", "being", "more", "most", "some",
    "such", "only", "other", "over", "under", "between", "because", "while", "after",
}
_CITE_RE = re.compile(r"\[S(\d+)\]")


class ResearchBlocked(ArchxError):
    """The run stopped because a capability it needs is not granted yet."""

    def __init__(self, message: str, *, run_id: str | None, approval_id: str | None) -> None:
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


def _terms(text: str, *, limit: int = 12) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_+-]{2,}", (text or "").lower())
    seen: list[str] = []
    for word in words:
        if word in _STOPWORDS or len(word) < 3:
            continue
        if word not in seen:
            seen.append(word)
        if len(seen) >= limit:
            break
    return seen


def _coverage(terms: Sequence[str], text: str) -> float:
    if not terms or not text:
        return 0.0
    lowered = text.lower()
    found = sum(1 for term in terms if term in lowered)
    return round(found / len(terms), 4)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [" ".join(part.split()) for part in parts if len(part.strip()) > 20]


def _excerpt(text: str, terms: Sequence[str], limit: int) -> str:
    """The most relevant window of a document: deterministic, quote-sized."""
    cleaned = "\n".join(line.strip() for line in (text or "").splitlines() if line.strip())
    if not cleaned:
        return ""
    if len(cleaned) <= limit:
        return cleaned
    sentences = _sentences(cleaned) or [cleaned]
    best_score, window = -1.0, ""
    for index in range(len(sentences)):
        candidate = ""
        score = 0.0
        for follow in sentences[index:]:
            if len(candidate) + len(follow) + 1 > limit:
                break
            candidate = f"{candidate} {follow}".strip()
            score = _coverage(terms, candidate)
            if score >= 1.0:
                break
        if score > best_score or (score == best_score and len(candidate) > len(window)):
            best_score, window = score, candidate
        if best_score >= 1.0:
            break
    if not window:
        window = cleaned[:limit].rsplit(" ", 1)[0]
    return window.strip()


def _subject(question: str) -> str:
    """The noun phrase a question is about, for building subquestions that read naturally."""
    text = " ".join((question or "").strip().rstrip("?.").split())
    text = re.sub(
        r"(?i)^(how do i|how do you|how does|how can i|how to|what is|what are|what does|"
        r"who is|why do|why does|why is|when should i|should i|is it better to|compare|"
        r"explain|describe)\s+",
        "",
        text,
    )
    text = re.sub(
        r"(?i)\s+(work|works|function|functions|behave|behaves|happen|happens|do|does)$", "", text
    )
    # "should I use postgres" reads as "the benefits of using postgres", not "of use postgres".
    gerunds = {
        "use": "using", "choose": "choosing", "adopt": "adopting", "buy": "buying",
        "run": "running", "install": "installing", "migrate": "migrating",
        "switch": "switching", "enable": "enabling", "add": "adding",
        "replace": "replacing", "upgrade": "upgrading", "build": "building",
    }
    head, _, tail = text.partition(" ")
    if head.lower() in gerunds:
        text = gerunds[head.lower()] + (f" {tail}" if tail else "")
    return text.strip() or " ".join((question or "").split())


def _rules_plan(question: str, limit: int) -> list[dict[str, Any]]:
    """A deterministic plan, with the reason for each subquestion.

    The first subquestion is the user's own question, because a plan that never asks the
    thing you asked is a plan that answers something else. The rest are facets chosen by the
    shape of the question. Deliberately plain: it exists so research works without a model,
    and ``planned_by = 'rules'`` says where it came from.
    """
    core = " ".join((question or "").strip().rstrip("?.").split())
    subject = _subject(question)
    lowered = core.lower()
    if lowered.startswith(("should i", "is it better", "compare", "versus", "vs")):
        facets = [
            (f"What are the benefits of {subject}?", "benefits"),
            (f"What are the costs and risks of {subject}?", "costs"),
            ("What alternatives exist, and how do they compare?", "alternatives"),
        ]
    elif lowered.startswith(("how do", "how to", "how can", "how does")):
        facets = [
            (f"What is required to do this, and what are the steps?", "procedure"),
            (f"What commonly goes wrong with {subject}?", "failure modes"),
            (f"What alternatives or better approaches exist for {subject}?", "alternatives"),
        ]
    elif lowered.startswith(("why ", "when ")):
        facets = [
            ("What causes this behaviour?", "causes"),
            (f"When is the opposite true, and what are the exceptions?", "exceptions"),
            (f"What evidence supports this explanation?", "evidence"),
        ]
    elif lowered.startswith(("what ", "who ", "define", "explain", "describe")):
        facets = [
            (f"What are the limits, risks or trade-offs of {subject}?", "limits"),
            (f"What evidence or examples support the answer about {subject}?", "evidence"),
            (f"What is uncertain or disputed about {subject}?", "gaps"),
        ]
    else:
        facets = [
            (f"What is already known about {subject}?", "background"),
            (f"What evidence supports the main claims about {subject}?", "evidence"),
            (f"What is uncertain, disputed or missing about {subject}?", "gaps"),
        ]
    plan = [
        {
            "question": f"{core}?",
            "why": "rule: the question you asked",
            "origin": "rules",
        }
    ]
    for text, reason in facets:
        plan.append({"question": text, "why": f"rule: {reason}", "origin": "rules"})
        if len(plan) >= max(1, int(limit)):
            break
    return plan[: max(1, int(limit))]


class ResearchRunner:
    """Runs a research question end to end, persisting every step as it goes."""

    def __init__(self, ws) -> None:
        self.ws = ws
        self.manager = ws.research

    # -- config -----------------------------------------------------------
    def _cfg(self, key: str, default: Any) -> Any:
        try:
            return self.ws.config.get(key)
        except Exception:  # noqa: BLE001 - a missing key must not break a run
            return default

    # -- plan -------------------------------------------------------------
    def plan(
        self,
        question: str,
        *,
        max_subquestions: int | None = None,
        conversation_id: str | None = None,
        model_id: str | None = None,
        subquestions: Sequence[str] | None = None,
    ) -> tuple[list[dict[str, Any]], str, list[str], dict[str, Any]]:
        """Return ``(plan, planned_by, notes, meta)``. Never raises for a bad model reply."""
        limit = int(max_subquestions or self._cfg("research.max_subquestions", 8))
        limit = max(1, min(limit, 50))
        if subquestions:
            picked = [{"question": _clean(item), "why": "the user asked this",
                       "origin": "user"} for item in subquestions if _clean(item)]
            if not picked:
                raise ValidationError("--subquestion needs at least one non-empty question")
            return picked[:limit], "user", [], {"model_id": None, "simulated": False,
                                               "reason": "the user supplied the subquestions"}
        notes: list[str] = []
        meta: dict[str, Any] = {"model_id": None, "simulated": False, "reason": ""}
        prompt = textwrap.dedent(
            f"""
            You are planning a research run. Break the question into at most {limit}
            subquestions that can each be answered from documents.

            Question: {question}

            Reply with JSON only, no prose, in exactly this shape:
            {{"subquestions": [{{"question": "...", "why": "..."}}]}}
            """
        ).strip()
        try:
            reply = self.ws.chat.send(
                prompt,
                conversation_id=conversation_id,
                model_id=model_id,
                system_prompt=(
                    "You produce research plans as JSON. You never invent sources. "
                    "If the question is unclear, plan subquestions that would clarify it."
                ),
            )
            meta["model_id"] = (reply.model or {}).get("id")
            meta["simulated"] = bool(reply.simulated)
            parsed = _parse_plan(reply.text, limit)
            if parsed:
                meta["reason"] = "a model returned a plan that validated"
                return parsed, "model", notes, meta
            notes.append("the model's plan did not parse or validate, so a rule plan was used")
            meta["reason"] = "the model reply was not a usable plan"
        except ApprovalRequiredError:
            raise
        except ArchxError as exc:
            notes.append(
                f"planning with a model failed ({_short(getattr(exc, 'message', exc))}); "
                "a rule plan was used"
            )
            meta["reason"] = "the model call failed"
        except Exception as exc:  # noqa: BLE001 - planning must not kill the run
            notes.append(f"planning with a model failed ({exc}); rule plan used")
            meta["reason"] = "the model call failed"
        plan = _rules_plan(question, limit)
        if not meta["reason"]:
            meta["reason"] = "no model was available, so the plan came from rules"
        return plan, "rules", notes, meta

    # -- gathering --------------------------------------------------------
    def gather_local(
        self,
        question: str,
        plan: Sequence[Mapping[str, Any]],
        *,
        per_source: int | None = None,
        max_sources: int | None = None,
        exclude_task_id: str | None = None,
        exclude_conversation_id: str | None = None,
    ) -> list[SourceDoc]:
        budget = int(max_sources or self._cfg("research.max_sources", 24))
        per_source = int(per_source or self._cfg("research.per_source_hits", 5))
        merge_limit = int(self._cfg("research.gather_limit", 12))
        docs: list[SourceDoc] = []
        by_ref: dict[str, SourceDoc] = {}
        for index, item in enumerate(plan):
            query = _query_for(question, str(item.get("question") or ""))
            report = self.ws.search.search(
                query, kinds=list(EVIDENCE_KINDS), limit=max(per_source, merge_limit),
                per_source=per_source,
            )
            for hit in report.hits:
                # A run is not its own evidence: the task it created and the conversation its
                # planning used are bookkeeping, not sources.
                if exclude_task_id and hit.kind == "task" and hit.id == exclude_task_id:
                    continue
                if (
                    exclude_conversation_id
                    and hit.kind == "conversation"
                    and hit.id == exclude_conversation_id
                ):
                    continue
                doc = self._load_hit(hit, index)
                if doc is None:
                    continue
                existing = by_ref.get(doc.ref)
                if existing is not None:
                    if index not in existing.also_relevant:
                        existing.also_relevant.append(index)
                    continue
                if len(docs) >= budget:
                    break
                # The subquestion that *found* a document is not necessarily the one it
                # answers: assign by best term match so the plan's gaps mean something.
                doc.subquestion = _assign_subquestion(
                    f"{doc.title}\n{doc.text}", plan, question
                )
                docs.append(doc)
                by_ref[doc.ref] = doc
            if len(docs) >= budget:
                break
        return docs

    def _load_hit(self, hit, subquestion: int) -> SourceDoc | None:
        """Turn a search hit into a document, reading the real content where possible."""
        max_bytes = int(self._cfg("research.max_source_bytes", 262144))
        try:
            if hit.kind == "file":
                path = str((hit.meta or {}).get("path") or "")
                if not path:
                    path = hit.ref.replace("file://", "") if hit.ref.startswith("file://") else ""
                resolved = self._inside_roots(path)
                if resolved is None:
                    return None
                with open(resolved, "rb") as handle:
                    raw = handle.read(max_bytes + 1)
                truncated = len(raw) > max_bytes
                body = raw[:max_bytes].decode("utf-8", errors="replace")
                return SourceDoc(
                    kind="file", ref=hit.ref, url=hit.ref, title=hit.title or resolved,
                    text=body, excerpt="", status="fetched",
                    checksum=_sha256(raw[:max_bytes]), bytes=len(raw[:max_bytes]),
                    truncated=truncated, subquestion=subquestion,
                    credibility="internal", publisher="workspace",
                )
            if hit.kind == "memory":
                stored = self.ws.memory.get(hit.id)
                if stored.is_err:
                    raise stored.error
                memory = stored.value
                body = memory.content
                return SourceDoc(
                    kind="memory", ref=hit.ref, url=f"archx:memory/{memory.id}",
                    title=memory.title, text=body, checksum=_sha256(body.encode()),
                    bytes=len(body.encode()), subquestion=subquestion,
                    credibility="internal", publisher="memory",
                )
            if hit.kind == "conversation":
                messages = self.ws.conversations.messages(hit.id)
                body = "\n\n".join(f"{m.role}: {m.content}" for m in messages)
                body = body[: max_bytes]
                return SourceDoc(
                    kind="conversation", ref=hit.ref, url=f"archx:conversation/{hit.id}",
                    title=hit.title or "conversation", text=body,
                    checksum=_sha256(body.encode()), bytes=len(body.encode()),
                    subquestion=subquestion, credibility="internal", publisher="conversation",
                )
            if hit.kind == "task":
                task = self.ws.tasks.get(hit.id)
                if task.type == "research":
                    # A research task is the record of a run, not a source: its findings live
                    # in that run's report, and citing the task would be citing ourselves.
                    return None
                body = "\n\n".join(
                    part for part in [
                        task.title,
                        str((task.metadata or {}).get("summary") or ""),
                        task.error or "",
                    ]
                    if part
                )
                return SourceDoc(
                    kind="task", ref=hit.ref, url=f"archx:task/{task.id}",
                    title=hit.title or task.title, text=body,
                    checksum=_sha256(body.encode()), bytes=len(body.encode()),
                    subquestion=subquestion, credibility="internal", publisher="tasks",
                )
            if hit.kind == "workflow":
                workflow = self.ws.workflows.get(hit.id)
                body = "\n\n".join(
                    part for part in [
                        workflow.name, workflow.goal or "",
                        str((workflow.metadata or {}).get("summary") or ""),
                    ]
                    if part
                )
                return SourceDoc(
                    kind="workflow", ref=hit.ref, url=f"archx:workflow/{workflow.id}",
                    title=hit.title or workflow.name, text=body,
                    checksum=_sha256(body.encode()), bytes=len(body.encode()),
                    subquestion=subquestion, credibility="internal", publisher="workflows",
                )
        except (NotFoundError, ArchxError, OSError) as exc:
            return SourceDoc(
                kind=hit.kind, ref=hit.ref, url=hit.ref, title=hit.title or hit.ref,
                status="failed", error=getattr(exc, "message", str(exc)),
                subquestion=subquestion, credibility="unknown", publisher=hit.kind,
            )
        return None

    def _inside_roots(self, path: str) -> str | None:
        from pathlib import Path

        if not path:
            return None
        candidate = Path(path).expanduser()
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            return None
        for root in self.ws.tool_roots():
            try:
                resolved.relative_to(Path(root).resolve())
                return str(resolved)
            except ValueError:
                continue
        return None

    def gather_web(
        self,
        urls: Sequence[str],
        question: str,
        plan: Sequence[Mapping[str, Any]],
        *,
        task_id: str | None = None,
        run_id: str | None = None,
        allow_private_hosts: bool | None = None,
    ) -> list[SourceDoc]:
        max_bytes = int(self._cfg("research.max_source_bytes", 262144))
        docs: list[SourceDoc] = []
        for url in urls:
            args: dict[str, Any] = {"url": url, "max_bytes": max_bytes}
            if allow_private_hosts is not None:
                args["allow_private_hosts"] = bool(allow_private_hosts)
            try:
                run = self.ws.tools.execute(
                    "net.fetch", args,
                    context=ToolContext(task_id=task_id, purpose=f"research: {question[:120]}"),
                )
            except ApprovalRequiredError as exc:
                raise ResearchBlocked(
                    "web research needs the net.fetch capability: "
                    f"{getattr(exc, 'message', exc)}",
                    run_id=run_id, approval_id=getattr(exc, "approval_id", None),
                ) from exc
            except ArchxError as exc:
                docs.append(
                    SourceDoc(
                        kind="url", ref=url, url=url, title=url, status="failed",
                        error=getattr(exc, "message", str(exc)), publisher=_host(url),
                        credibility="unknown", subquestion=_best_subquestion(url, plan),
                    )
                )
                continue
            if run.status != "succeeded" or not run.result:
                docs.append(
                    SourceDoc(
                        kind="url", ref=url, url=url, title=url, status="failed",
                        error=run.error or "fetch failed", publisher=_host(url),
                        credibility="unknown", subquestion=_best_subquestion(url, plan),
                    )
                )
                continue
            result = run.result
            text = str(result.get("text") or "")
            title = str(result.get("title") or "") or _host(url)
            doc = SourceDoc(
                kind="url", ref=str(result.get("final_url") or url), url=url, title=title,
                text=text, status="fetched", checksum=result.get("sha256"),
                bytes=int(result.get("bytes") or 0), truncated=bool(result.get("truncated")),
                publisher=_host(url), credibility="unknown",
                subquestion=_best_subquestion(text or title, plan),
            )
            if not doc.text.strip():
                doc.status = "failed"
                doc.error = "the page contained no readable text"
            docs.append(doc)
        return docs

    # -- judging ----------------------------------------------------------
    def judge(
        self,
        docs: Sequence[SourceDoc],
        question: str,
        plan: Sequence[Mapping[str, Any]],
        *,
        conversation_id: str | None = None,
        model_id: str | None = None,
        use_model: bool = True,
    ) -> list[str]:
        """Score relevance and (when a model is available) the stance of each source."""
        notes: list[str] = []
        terms = _terms(question + " " + " ".join(str(item.get("question") or "") for item in plan))
        excerpt_chars = int(self._cfg("research.excerpt_chars", 600))
        for doc in docs:
            if not doc.usable:
                continue
            # The excerpt comes first: it is what the report quotes and what a model judges,
            # so scoring unquoted text would rank a source on words the reader never sees.
            doc.excerpt = _excerpt(doc.text or doc.excerpt, _terms(question), excerpt_chars)
            doc.relevance = max(
                _coverage(terms, doc.text), _coverage(_terms(doc.title), doc.text)
            )
        if not use_model:
            notes.append(
                "no model was configured, so stance was not judged (every source is 'unknown') "
                "and relevance is term overlap, not understanding"
            )
            return notes
        capped = [doc for doc in docs if doc.usable][: int(self._cfg("research.max_judged_sources", 12))]
        if not capped:
            return notes
        for index, doc in enumerate(capped, start=1):
            prompt = textwrap.dedent(
                f"""
                Read this excerpt and judge it against the research question.

                Question: {question}

                Excerpt from "{doc.title}" ({doc.url or doc.ref}):
                \"\"\"{doc.excerpt[:1500]}\"\"\"

                Reply with JSON only:
                {{"stance": "supports|contradicts|background|mixed",
                  "relevance": 0.0-1.0,
                  "claims": [{{"quote": "an exact substring of the excerpt", "why": "short"}}]}}
                """
            ).strip()
            try:
                reply = self.ws.chat.send(
                    prompt, conversation_id=conversation_id, model_id=model_id,
                    system_prompt=(
                        "You classify evidence. Quotes must be copied exactly from the "
                        "excerpt; never paraphrase inside a quote."
                    ),
                )
                judgement = _parse_judgement(reply.text, doc.excerpt)
                if judgement is None:
                    notes.append(f"the model's judgement of source {index} did not validate; left as unknown")
                    continue
                doc.stance = judgement["stance"]
                doc.relevance = max(doc.relevance, float(judgement["relevance"]))
                doc.claims = judgement["claims"]
            except ApprovalRequiredError:
                raise
            except ModelNotFoundError as exc:
                notes.append(
                    "no model was configured, so stance was not judged (every source is "
                    f"'unknown'): {_short(getattr(exc, 'message', exc))}"
                )
                return notes
            except ArchxError as exc:
                if not any("judging" in note for note in notes):
                    notes.append(f"judging with a model failed: {_short(getattr(exc, 'message', exc))}")
        return notes

    # -- report -----------------------------------------------------------
    def synthesize(
        self,
        question: str,
        plan: Sequence[Mapping[str, Any]],
        docs: Sequence[SourceDoc],
        *,
        mode: str,
        run_id: str,
        planned_by: str,
        model_id: str | None = None,
        notes: Sequence[str] = (),
        conversation_id: str | None = None,
        use_model: bool = True,
    ) -> tuple[str, float, list[str], dict[str, Any]]:
        usable = [doc for doc in docs if doc.usable]
        by_sq: dict[int, list[SourceDoc]] = {}
        for doc in usable:
            by_sq.setdefault(doc.subquestion, []).append(doc)
        answered = [index for index in range(len(plan)) if by_sq.get(index)]
        coverage = round(len(answered) / len(plan), 4) if plan else 0.0

        limitations: list[str] = [str(note) for note in notes if note]
        if not usable:
            limitations.append("no usable evidence was found, so there is nothing to report")
        missing = [str(plan[i].get("question")) for i in range(len(plan)) if i not in by_sq]
        if missing:
            limitations.append("no usable evidence for: " + "; ".join(missing))
        failed = [doc for doc in docs if doc.status != "fetched"]
        if failed:
            limitations.append(
                f"{len(failed)} source(s) could not be read: "
                + "; ".join(f"{doc.ref} ({doc.error})" for doc in failed[:5])
            )
        if any(doc.truncated for doc in docs):
            limitations.append(
                f"some sources were truncated at research.max_source_bytes "
                f"({self._cfg('research.max_source_bytes', 262144)} bytes)"
            )
        unknown_stance = [doc for doc in usable if doc.stance == "unknown"]
        if usable and len(unknown_stance) == len(usable):
            limitations.append(
                "no source was judged for or against the question (stance is unknown)"
            )
        if mode == "local":
            limitations.append(
                "only local sources were searched; the web was not consulted "
                "(use --mode web/mixed with explicit URLs to include it)"
            )
        planner_reason = {
            "model": "the plan came from a model and was validated",
            "user": "the user supplied the subquestions, so the plan is your own framing",
            "rules": "the plan came from deterministic rules, not from a model",
        }.get(planned_by, f"the plan came from {planned_by}")
        limitations.append(f"planned by {planned_by}: {planner_reason}")
        limitations.append(
            "credibility is recorded as 'internal' for your own material and 'unknown' for "
            "web pages; Archx does not rate publishers"
        )

        answer_lines: list[str] = []
        for index, item in enumerate(plan):
            candidates = by_sq.get(index) or []
            if not candidates:
                if usable:
                    topic = ", ".join(f"[S{doc.number}]" for doc in usable[:3])
                    answer_lines.append(
                        f"- **{_clean(item.get('question'))}** - no source addresses this "
                        f"facet specifically; the topic evidence is {topic}."
                    )
                else:
                    answer_lines.append(
                        f"- **{_clean(item.get('question'))}** - no usable evidence was found."
                    )
                continue
            best = max(candidates, key=lambda doc: (doc.relevance, -doc.number))
            quote = _quote(best.excerpt, 240)
            answer_lines.append(
                f"- **{_clean(item.get('question'))}** - [S{best.number}] states: {quote}"
            )
        evidence_blocks: list[str] = []
        for index, item in enumerate(plan):
            evidence_blocks.append(f"### {index + 1}. {_clean(item.get('question'))}")
            evidence_blocks.append(f"_{_clean(item.get('why') or 'no stated reason')}_")
            candidates = sorted(by_sq.get(index) or [], key=lambda doc: (-doc.relevance, doc.number))
            if not candidates:
                if usable:
                    evidence_blocks.append(
                        "No source addresses this facet specifically. The documents found "
                        "discuss the topic but not this part of it; that is a gap, not a "
                        "conclusion."
                    )
                else:
                    evidence_blocks.append("No usable evidence. This is a gap, not a conclusion.")
            for doc in candidates[:4]:
                evidence_blocks.append(
                    f"- [S{doc.number}] {_quote(doc.excerpt, 500)}\n"
                    f"  - source: {doc.title} ({doc.url or doc.ref}), "
                    f"stance {doc.stance}, relevance {doc.relevance:.2f}"
                )
                for claim in doc.claims[:2]:
                    evidence_blocks.append(f"  - the model read this as: {_clean(claim.get('why'))}")
            evidence_blocks.append("")

        disagreements: list[str] = []
        stances = {doc.stance for doc in usable}
        if "contradicts" in stances and "supports" in stances:
            supporters = [doc for doc in usable if doc.stance == "supports"]
            contradictors = [doc for doc in usable if doc.stance == "contradicts"]
            disagreements.append(
                "Sources disagree. Supporting: "
                + ", ".join(f"[S{doc.number}]" for doc in supporters)
                + ". Contradicting: "
                + ", ".join(f"[S{doc.number}]" for doc in contradictors)
                + "."
            )
            for doc in contradictors[:3]:
                disagreements.append(f"- [S{doc.number}] {_quote(doc.excerpt, 300)}")
        elif usable:
            disagreements.append(
                "No source was judged to contradict another."
                if "unknown" not in stances
                else "No contradiction was detected, but stance is unknown for at least one "
                     "source, so this is the absence of a judgement - not agreement."
            )

        model_reading: list[str] = []
        demoted: list[str] = []
        meta: dict[str, Any] = {"model_reading": False, "demoted": 0}
        if use_model and usable:
            prose, demoted = self._model_reading(
                question, usable, conversation_id=conversation_id, model_id=model_id
            )
            if prose:
                model_reading = prose
                meta["model_reading"] = True
            meta["demoted"] = len(demoted)
            if demoted:
                limitations.append(
                    f"{len(demoted)} paragraph(s) of model prose were not tied to a source and "
                    "are listed separately instead of being treated as findings"
                )

        sources_block: list[str] = []
        for doc in sorted(usable, key=lambda item: item.number):
            sources_block.append(
                f"{doc.number}. [S{doc.number}] {doc.title} - {doc.url or doc.ref}"
            )
            sources_block.append(
                f"   - kind {doc.kind}, publisher {doc.publisher}, "
                f"sha256 {str(doc.checksum or '')[:16] or 'n/a'}, {doc.bytes or 0} bytes"
            )
            if doc.error:
                sources_block.append(f"   - problem: {doc.error}")
        for doc in failed:
            sources_block.append(
                f"- (not usable) {doc.title} - {doc.url or doc.ref} - {doc.kind} - "
                f"{doc.status}: {doc.error}"
            )

        lines = [
            f"# Research: {_clean(question)}",
            "",
            f"- run `{run_id}` - mode **{mode}** - plan by **{planned_by}** - "
            f"coverage **{coverage:.0%}** ({len(answered)}/{len(plan)} subquestions) - "
            f"{len(usable)} usable source(s)",
        ]
        if not usable:
            lines.append("- **I found no evidence for this question.** Nothing below is a finding.")
        lines += [
            "",
            "## Short answer (extractive, every line cited)",
            "",
            *answer_lines,
            "",
            "## Evidence by subquestion",
            "",
            *evidence_blocks,
        ]
        if not disagreements:
            disagreements = ["Nothing to compare: no usable evidence was found."]

        if model_reading:
            lines += ["## A model's reading (cited paragraphs only)", "", *model_reading, ""]
        if demoted:
            lines += [
                "## Statements I could not tie to a source",
                "",
                "_The model wrote these, but they carry no valid citation, so they are not findings._",
                "",
                *[f"- {text}" for text in demoted],
                "",
            ]
        lines += [
            "## Where the sources disagree",
            "",
            *disagreements,
            "",
            "## What I could not establish",
            "",
            *[f"- {item}" for item in limitations],
            "",
            "## Sources",
            "",
            *sources_block,
            "",
        ]
        return "\n".join(lines).strip() + "\n", coverage, limitations, meta

    def _model_reading(
        self,
        question: str,
        docs: Sequence[SourceDoc],
        *,
        conversation_id: str | None,
        model_id: str | None,
    ) -> tuple[list[str], list[str]]:
        evidence = "\n\n".join(
            f"[S{doc.number}] {doc.title}: {doc.excerpt[:800]}" for doc in docs[:8]
        )
        prompt = textwrap.dedent(
            f"""
            Answer the question using ONLY the numbered evidence below. Every paragraph must
            cite at least one source with its [S<n>] tag. If the evidence does not answer it,
            say so in one paragraph with a citation.

            Question: {question}

            Evidence:
            {evidence}
            """
        ).strip()
        try:
            reply = self.ws.chat.send(
                prompt, conversation_id=conversation_id, model_id=model_id,
                system_prompt=(
                    "You answer from the supplied evidence only, and you cite every paragraph "
                    "with the [S<n>] tags you were given. You never add facts of your own."
                ),
            )
        except ApprovalRequiredError:
            raise
        except ArchxError:
            return [], []
        except Exception:  # noqa: BLE001 - the report must still exist
            return [], []
        valid = {doc.number for doc in docs}
        keep: list[str] = []
        demoted: list[str] = []
        for paragraph in re.split(r"\n\s*\n", reply.text or ""):
            text = " ".join(paragraph.split())
            if not text:
                continue
            cited = {int(match) for match in _CITE_RE.findall(text)} & valid
            if cited:
                keep.append(text)
            else:
                demoted.append(text)
        return keep, demoted

    # -- verification ------------------------------------------------------
    CLAIM_SECTIONS = (
        "## Short answer (extractive, every line cited)",
        "## Evidence by subquestion",
        "## A model's reading (cited paragraphs only)",
    )

    @classmethod
    def verify(cls, report: str, numbers: Iterable[int]) -> dict[str, Any]:
        """Check every citation against the sources that exist, and every claim against a citation.

        Only the *claim* sections are policed: the limitations, the source list and the
        demoted-prose section are explicitly not findings, so demanding citations there
        would be checking the wrong thing.
        """
        known = set(int(number) for number in numbers)
        cited = {int(match) for match in _CITE_RE.findall(report or "")}
        unknown = sorted(cited - known)
        uncited: list[str] = []
        section = ""
        for line in (report or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                section = stripped
                continue
            if section not in cls.CLAIM_SECTIONS or not stripped:
                continue
            # A claim is a short-answer bullet or a paragraph of model reading. Headings,
            # source metadata and the demoted section are not claims.
            is_claim = stripped.startswith("- **")
            if section == "## A model's reading (cited paragraphs only)":
                is_claim = not stripped.startswith(("_", "#"))
            if not is_claim:
                continue
            if _CITE_RE.search(stripped):
                continue
            if "no usable evidence" in stripped.lower() and "topic evidence" not in stripped.lower():
                continue
            uncited.append(stripped[:160])
        return {
            "citations": len(_CITE_RE.findall(report or "")),
            "sources_cited": sorted(cited & known),
            "sources_available": sorted(known),
            "unknown_citations": unknown,
            "uncited_claims": uncited,
            "ok": not unknown and not uncited,
        }

    # -- run ---------------------------------------------------------------
    def run(
        self,
        question: str,
        *,
        mode: str | None = None,
        urls: Sequence[str] = (),
        max_subquestions: int | None = None,
        subquestions: Sequence[str] | None = None,
        model_id: str | None = None,
        out: str | None = None,
        report_format: str | None = None,
        use_model: bool = True,
        allow_private_hosts: bool | None = None,
        task_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        question = (question or "").strip()
        if len(question) < 4:
            raise ValidationError("a research question needs at least four characters")
        mode = mode or str(self._cfg("research.default_mode", "local"))
        if mode not in MODES:
            raise ValidationError(f"mode must be one of {', '.join(MODES)}")
        urls = [str(url).strip() for url in urls if str(url).strip()]
        if mode in {"web", "mixed"} and not urls:
            raise ValidationError(
                f"mode {mode!r} needs at least one --url: Archx does not crawl and does not "
                "query a search engine, so the seeds must come from you"
            )
        if mode == "local" and urls:
            raise ValidationError("--url needs --mode web or --mode mixed (otherwise it is ignored)")
        report_format = report_format or str(self._cfg("research.report_format", "markdown"))
        if report_format not in {"markdown", "md", "html"}:
            raise ValidationError("report format must be markdown or html")

        own_task = task_id is None
        if own_task:
            task = self.ws.tasks.create("research", question[:120], start=True)
            task_id = task.id
        run = self.manager.create(
            question,
            mode=mode,
            report_format="html" if report_format == "html" else "markdown",
            model_id=model_id,
            task_id=task_id,
            settings={"urls": urls, "max_subquestions": max_subquestions,
                      "use_model": use_model, "out": out},
        )
        try:
            return self._execute(
                run.id, question, mode=mode, urls=urls, max_subquestions=max_subquestions,
                subquestions=subquestions,
                model_id=model_id, out=out, report_format=report_format,
                use_model=use_model, allow_private_hosts=allow_private_hosts,
                task_id=task_id, project_id=project_id,
            )
        except ResearchBlocked as blocked:
            self._finish_blocked(run.id, blocked, task_id=task_id)
            raise
        except Exception as exc:  # noqa: BLE001 - a failed run is a record, not a crash
            message = getattr(exc, "message", None) or str(exc)
            try:
                self.manager.finish(
                    run.id, status="failed", error=message,
                    limitations=[f"the run failed: {message}"],
                )
            except Exception:  # noqa: BLE001
                pass
            if task_id:
                self._log(task_id, "research_failed", message)
                try:
                    self.ws.tasks.fail(task_id, message)
                except Exception:  # noqa: BLE001
                    pass
            raise

    def _execute(
        self,
        run_id: str,
        question: str,
        *,
        mode: str,
        urls: Sequence[str],
        max_subquestions: int | None,
        subquestions: Sequence[str] | None,
        model_id: str | None,
        out: str | None,
        report_format: str,
        use_model: bool,
        allow_private_hosts: bool | None,
        task_id: str | None,
        project_id: str | None,
    ) -> dict[str, Any]:
        conversation_id = None
        if use_model:
            conversation = self.ws.conversations.create(title=f"research: {question[:80]}")
            conversation_id = conversation.id
            self.manager.update(run_id, settings={**_settings_of(self.manager, run_id),
                                                  "conversation_id": conversation_id})

        plan, planned_by, plan_notes, plan_meta = self.plan(
            question, max_subquestions=max_subquestions,
            conversation_id=conversation_id, model_id=model_id, subquestions=subquestions,
        )
        self.manager.update(run_id, plan=plan, planned_by=planned_by, status="gathering")
        self._log(task_id, "research_planned", f"{len(plan)} subquestion(s), planned by {planned_by}")

        docs: list[SourceDoc] = []
        if mode in {"local", "mixed"}:
            docs.extend(
                self.gather_local(
                    question, plan, exclude_task_id=task_id,
                    exclude_conversation_id=conversation_id,
                )
            )
        if mode in {"web", "mixed"}:
            docs.extend(
                self.gather_web(
                    urls, question, plan, task_id=task_id, run_id=run_id,
                    allow_private_hosts=allow_private_hosts,
                )
            )
        self.manager.update(run_id, status="reading")
        self._log(task_id, "research_gathered", f"{len(docs)} candidate source(s)")

        judge_notes = self.judge(
            docs, question, plan, conversation_id=conversation_id, model_id=model_id,
            use_model=use_model,
        )

        # Persist every source: successes in reading order (which fixes [S<n>]), failures too.
        for doc in docs:
            stored = self.manager.add_source(
                run_id,
                url=doc.url or doc.ref,
                kind=doc.kind,
                title=doc.title,
                publisher=doc.publisher,
                excerpt=doc.excerpt or None,
                ref=doc.ref,
                status=doc.status,
                error=doc.error,
                checksum=doc.checksum,
                bytes_=doc.bytes,
                relevance=round(doc.relevance, 4),
                credibility=doc.credibility,
                stance=doc.stance,
                claims=doc.claims,
                subquestion=doc.subquestion,
                limitations=None,
            )
            doc.number = stored.id
        usable = [doc for doc in docs if doc.usable]
        for position, doc in enumerate(sorted(usable, key=lambda item: item.number), start=1):
            # [S<n>] is the citation label *within this run*; the row id stays in the table.
            doc.number = position

        self.manager.update(run_id, status="synthesizing")
        report, coverage, limitations, meta = self.synthesize(
            question, plan, docs, mode=mode, run_id=run_id, planned_by=planned_by,
            model_id=model_id, notes=[*plan_notes, *judge_notes],
            conversation_id=conversation_id, use_model=use_model,
        )
        numbers = [doc.number for doc in usable]
        verification = self.verify(report, numbers)
        if verification["unknown_citations"]:
            limitations.append(
                "the report cited sources that do not exist: "
                + ", ".join(f"S{number}" for number in verification["unknown_citations"])
            )
            report = report.replace(
                "## Sources",
                "_Citation check failed for: "
                + ", ".join(f"S{number}" for number in verification["unknown_citations"])
                + "_\n\n## Sources",
            )

        path = self._write_report(run_id, report, report_format=report_format, out=out)
        status = "completed" if usable else "incomplete"
        finished = self.manager.finish(
            run_id, status=status, report=report,
            report_path=path, coverage=coverage, evidence_count=len(usable),
            limitations=limitations,
        )
        if task_id:
            artifact = None
            try:
                artifact = self.ws.tasks.attach_artifact(
                    task_id, path, kind="report", name=f"research-{run_id}"
                )
            except Exception as exc:  # noqa: BLE001 - the report still exists on disk
                self._log(task_id, "research_artifact_failed", str(exc))
            self._log(
                task_id, "research_reported",
                f"{len(usable)} source(s), coverage {coverage:.0%}, report {path}",
            )
            try:
                self.ws.tasks.complete(
                    task_id,
                    summary=(
                        f"research {run_id}: {len(usable)} source(s), coverage {coverage:.0%}"
                    ),
                    outputs=[path],
                )
            except Exception:  # noqa: BLE001 - completed is best-effort here
                pass
        return {
            "run": finished.to_dict(),
            "report_path": path,
            "verification": verification,
            "plan_meta": plan_meta,
            "model_reading": meta,
            "report": report,
        }

    def _finish_blocked(self, run_id: str, blocked: ResearchBlocked, *, task_id: str | None) -> None:
        try:
            self.manager.finish(
                run_id, status="failed", error=blocked.message,
                limitations=[blocked.message],
            )
        except Exception:  # noqa: BLE001
            pass
        if task_id:
            self._log(task_id, "research_blocked", blocked.message)
            try:
                self.ws.tasks.fail(task_id, blocked.message)
            except Exception:  # noqa: BLE001
                pass

    def _write_report(self, run_id: str, report: str, *, report_format: str, out: str | None) -> str:
        from pathlib import Path

        if out:
            target = Path(out).expanduser()
            if target.suffix == "":
                target = target.with_suffix(".html" if report_format == "html" else ".md")
        else:
            base = Path(self.ws.config.path("paths.research"))
            base.mkdir(parents=True, exist_ok=True)
            target = base / f"{run_id}.{'html' if report_format == 'html' else 'md'}"
        target.parent.mkdir(parents=True, exist_ok=True)
        body = _to_html(report) if report_format == "html" else report
        target.write_text(body, encoding="utf-8")
        return str(target)

    # -- helpers -----------------------------------------------------------
    def _log(self, task_id: str | None, kind: str, detail: str) -> None:
        if not task_id:
            return
        try:
            self.ws.tasks.log(task_id, kind, detail=detail[:2000])
        except Exception:  # noqa: BLE001 - logging must never break a run
            pass


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def citation_numbers(sources: Iterable[Any]) -> dict[int, int]:
    """Map source row ids to the ``[S<n>]`` labels used inside a run's report.

    The labels are per run (1..N over the usable sources, in row order) so a report reads
    ``[S1]`` rather than ``[S47]``; the row id stays in the table for anyone who wants it.
    """
    usable = sorted(
        (source for source in sources if getattr(source, "usable", False)),
        key=lambda source: source.id,
    )
    return {source.id: position for position, source in enumerate(usable, start=1)}


def _short(message: Any, limit: int = 200) -> str:
    text = _clean(message)
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "..."


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _quote(text: str, limit: int) -> str:
    body = _clean(text)
    if len(body) > limit:
        body = body[:limit].rsplit(" ", 1)[0] + "..."
    return f"“{body}”" if body else "(no text)"


def _host(url: str) -> str:
    from urllib.parse import urlsplit

    try:
        return urlsplit(url).hostname or "web"
    except ValueError:  # pragma: no cover - urlsplit rarely raises
        return "web"


def _sha256(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def _query_for(question: str, subquestion: str) -> str:
    """Terms for one subquestion, anchored by the question's own terms.

    A facet like "what commonly goes wrong?" has no searchable vocabulary on its own, so the
    question's terms are prepended: the search looks for the topic *and* the facet, which is
    what makes a small local corpus answerable at all.
    """
    terms = _terms(question, limit=6)
    for term in _terms(subquestion, limit=6):
        if term not in terms:
            terms.append(term)
    return " ".join(terms) or question


def _assign_subquestion(
    text: str, plan: Sequence[Mapping[str, Any]], question: str
) -> int:
    """Which subquestion a document answers.

    A facet wins only if the document uses vocabulary the facet added - words that are not
    already in the question. Otherwise the document answers the question itself. The point is
    that "no source addresses this facet" stays a real statement rather than a coin flip
    between rhetorical headings.
    """
    question_terms = set(_terms(question))
    lowered = text.lower()
    best_index, best_score = 0, 0.0
    for index, item in enumerate(plan):
        if index == 0:
            continue
        terms = _terms(str(item.get("question") or ""))
        specific = [term for term in terms if term not in question_terms]
        if not any(term in lowered for term in specific):
            continue
        score = _coverage(terms, text)
        if score > best_score:
            best_index, best_score = index, score
    return best_index


def _best_subquestion(text: str, plan: Sequence[Mapping[str, Any]]) -> int:
    best, score = 0, -1.0
    for index, item in enumerate(plan):
        candidate = _coverage(_terms(str(item.get("question") or "")), text)
        if candidate > score:
            best, score = index, candidate
    return best


def _settings_of(manager, run_id: str) -> dict[str, Any]:
    try:
        return dict(manager.get(run_id).settings)
    except Exception:  # noqa: BLE001
        return {}


def _parse_plan(text: str, limit: int) -> list[dict[str, Any]]:
    """Validate a model's plan. A malformed reply is a failure, not a plan.

    Accepts a bare object or one fenced block, because models wrap JSON in fences; accepts
    ``subquestions`` as a list of strings or objects. Rejects anything that would produce an
    empty or oversized plan.
    """
    data = _extract_json(text)
    if not isinstance(data, dict):
        return []
    items = data.get("subquestions")
    if not isinstance(items, list):
        return []
    plan: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            question, why = item, ""
        elif isinstance(item, dict):
            question = str(item.get("question") or "").strip()
            why = str(item.get("why") or "").strip()
        else:
            continue
        question = _clean(question)
        if len(question) < 8 or question.lower() in seen:
            continue
        seen.add(question.lower())
        plan.append({"question": question, "why": why or "no reason given", "origin": "model"})
        if len(plan) >= max(1, limit):
            break
    return plan


def _parse_judgement(text: str, excerpt: str) -> dict[str, Any] | None:
    data = _extract_json(text)
    if not isinstance(data, dict):
        return None
    stance = str(data.get("stance") or "").strip().lower()
    if stance not in STANCES:
        return None
    try:
        relevance = float(data.get("relevance"))
    except (TypeError, ValueError):
        return None
    relevance = max(0.0, min(1.0, relevance))
    claims: list[dict[str, Any]] = []
    haystack = " ".join(excerpt.split()).lower()
    for item in data.get("claims") or []:
        if not isinstance(item, dict):
            continue
        quote = _clean(item.get("quote"))
        if len(quote) < 8:
            continue
        if " ".join(quote.split()).lower() not in haystack:
            continue  # a quote that is not in the source is not a quote
        claims.append({"quote": quote, "why": _clean(item.get("why"))[:200]})
    return {"stance": stance, "relevance": relevance, "claims": claims}


def _extract_json(text: str) -> Any:
    body = (text or "").strip()
    if not body:
        return None
    fence = re.search(r"(?s)```(?:json)?\s*(.+?)```", body)
    if fence:
        body = fence.group(1).strip()
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        pass
    start = body.find("{")
    end = body.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(body[start: end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _to_html(markdown: str) -> str:
    """A small, safe markdown subset -> HTML. Everything is escaped first."""
    lines = (markdown or "").splitlines()
    out: list[str] = [
        "<!doctype html>",
        '<meta charset="utf-8">',
        "<title>Archx research report</title>",
        "<style>body{font:16px/1.55 system-ui,sans-serif;max-width:52rem;margin:2rem auto;"
        "padding:0 1rem;color:#111}h1,h2,h3{line-height:1.25}code{background:#f3f3f3;"
        "padding:.1em .3em;border-radius:3px}li{margin:.2em 0}</style>",
        "<article>",
    ]
    in_list = False
    for raw in lines:
        line = html.escape(raw)
        if line.startswith("### "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("## "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith(("- ", "  - ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{line.lstrip('- ').strip()}</li>")
        elif not line.strip():
            if in_list:
                out.append("</ul>")
                in_list = False
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<p>{line}</p>")
    if in_list:
        out.append("</ul>")
    out.append("</article>")
    return "\n".join(out) + "\n"


__all__ = [
    "EVIDENCE_KINDS",
    "ResearchBlocked",
    "ResearchRunner",
    "SourceDoc",
]
