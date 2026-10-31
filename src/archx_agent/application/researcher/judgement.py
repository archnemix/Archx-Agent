"""Judgement operations for evidence-based research."""

from __future__ import annotations

import textwrap
from typing import Any, Mapping, Sequence

from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    ArchxError,
    ModelNotFoundError,
)
from archx_agent.application.researcher.records import SourceDoc
from archx_agent.application.researcher.text import _terms, _coverage, _excerpt, _short
from archx_agent.application.researcher.parsing import _parse_judgement


class ResearchRunnerJudgementMixin:
    """Judgement responsibility for ResearchRunner."""

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
        terms = _terms(
            question + " " + " ".join(str(item.get("question") or "") for item in plan)
        )
        excerpt_chars = int(self._cfg("research.excerpt_chars", 600))
        for doc in docs:
            if not doc.usable:
                continue
            # The excerpt comes first: it is what the report quotes and what a model judges,
            # so scoring unquoted text would rank a source on words the reader never sees.
            doc.excerpt = _excerpt(
                doc.text or doc.excerpt, _terms(question), excerpt_chars
            )
            doc.relevance = max(
                _coverage(terms, doc.text), _coverage(_terms(doc.title), doc.text)
            )
        if not use_model:
            notes.append(
                "no model was configured, so stance was not judged (every source is 'unknown') "
                "and relevance is term overlap, not understanding"
            )
            return notes
        capped = [doc for doc in docs if doc.usable][
            : int(self._cfg("research.max_judged_sources", 12))
        ]
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
                    prompt,
                    conversation_id=conversation_id,
                    model_id=model_id,
                    system_prompt=(
                        "You classify evidence. Quotes must be copied exactly from the "
                        "excerpt; never paraphrase inside a quote."
                    ),
                )
                judgement = _parse_judgement(reply.text, doc.excerpt)
                if judgement is None:
                    notes.append(
                        f"the model's judgement of source {index} did not validate; left as unknown"
                    )
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
                    notes.append(
                        f"judging with a model failed: {_short(getattr(exc, 'message', exc))}"
                    )
        return notes
