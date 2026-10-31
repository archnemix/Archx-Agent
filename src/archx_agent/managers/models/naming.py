"""ModelManager naming."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from archx_agent.managers.models.constants import _QUANT_RE


def parse_gguf_name(filename: str) -> dict[str, Any]:
    """Extract *claims* from a filename. These are claims, never facts."""
    stem = Path(filename).stem
    claims: dict[str, Any] = {"source": "filename"}
    quant = _QUANT_RE.search(stem)
    if quant:
        claims["quantization"] = quant.group(1).upper()
    params = re.search(r"(?i)(\d+(?:\.\d+)?)\s*[bB](?![a-z])", stem)
    if params:
        claims["param_count"] = f"{params.group(1)}B"
    if re.search(r"(?i)instruct|chat|it\b", stem):
        claims["chat"] = True
    if re.search(r"(?i)vision|vl\b|llava", stem):
        claims["vision"] = "claimed"
    if re.search(r"(?i)embed|bge|gte", stem):
        claims["embeddings"] = "claimed"
    return claims
