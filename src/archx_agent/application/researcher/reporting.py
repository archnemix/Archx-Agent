"""Reporting operations for evidence-based research."""

from __future__ import annotations

import re
import textwrap
from typing import Any, Iterable, Mapping, Sequence

from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    ArchxError,
)
from archx_agent.application.researcher.constants import _CITE_RE
from archx_agent.application.researcher.records import SourceDoc
from archx_agent.application.researcher.text import _clean, _quote


class ResearchRunnerReportingMixin:
    """Reporting responsibility for ResearchRunner."""

    CLAIM_SECTIONS = (
        "## Short answer (extractive, every line cited)",
        "## Evidence by subquestion",
        "## A model's reading (cited paragraphs only)",
    )

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
            limitations.append(
                "no usable evidence was found, so there is nothing to report"
            )
        missing = [
            str(plan[i].get("question")) for i in range(len(plan)) if i not in by_sq
        ]
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
            candidates = sorted(
                by_sq.get(index) or [], key=lambda doc: (-doc.relevance, doc.number)
            )
            if not candidates:
                if usable:
                    evidence_blocks.append(
                        "No source addresses this facet specifically. The documents found "
                        "discuss the topic but not this part of it; that is a gap, not a "
                        "conclusion."
                    )
                else:
                    evidence_blocks.append(
                        "No usable evidence. This is a gap, not a conclusion."
                    )
            for doc in candidates[:4]:
                evidence_blocks.append(
                    f"- [S{doc.number}] {_quote(doc.excerpt, 500)}\n"
                    f"  - source: {doc.title} ({doc.url or doc.ref}), "
                    f"stance {doc.stance}, relevance {doc.relevance:.2f}"
                )
                for claim in doc.claims[:2]:
                    evidence_blocks.append(
                        f"  - the model read this as: {_clean(claim.get('why'))}"
                    )
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
            lines.append(
                "- **I found no evidence for this question.** Nothing below is a finding."
            )
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
            lines += [
                "## A model's reading (cited paragraphs only)",
                "",
                *model_reading,
                "",
            ]
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
                prompt,
                conversation_id=conversation_id,
                model_id=model_id,
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
            if (
                "no usable evidence" in stripped.lower()
                and "topic evidence" not in stripped.lower()
            ):
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
