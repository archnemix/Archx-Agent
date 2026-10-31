"""Parsing operations for evidence-based research."""

from __future__ import annotations

import json
import re
from typing import Any

from archx_agent.managers.research import STANCES
from archx_agent.application.researcher.text import _clean


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
        plan.append(
            {"question": question, "why": why or "no reason given", "origin": "model"}
        )
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
            return json.loads(body[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None
