"""Feature-specific formatting for evidence-based research."""

from __future__ import annotations

import html
from typing import Any, Iterable


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
