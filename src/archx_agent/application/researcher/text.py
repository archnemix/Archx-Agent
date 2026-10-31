"""Text operations for evidence-based research."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from archx_agent.application.researcher.constants import _STOPWORDS


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
    cleaned = "\n".join(
        line.strip() for line in (text or "").splitlines() if line.strip()
    )
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
        r"(?i)\s+(work|works|function|functions|behave|behaves|happen|happens|do|does)$",
        "",
        text,
    )
    # "should I use postgres" reads as "the benefits of using postgres", not "of use postgres".
    gerunds = {
        "use": "using",
        "choose": "choosing",
        "adopt": "adopting",
        "buy": "buying",
        "run": "running",
        "install": "installing",
        "migrate": "migrating",
        "switch": "switching",
        "enable": "enabling",
        "add": "adding",
        "replace": "replacing",
        "upgrade": "upgrading",
        "build": "building",
    }
    head, _, tail = text.partition(" ")
    if head.lower() in gerunds:
        text = gerunds[head.lower()] + (f" {tail}" if tail else "")
    return text.strip() or " ".join((question or "").split())


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
