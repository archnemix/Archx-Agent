"""A deterministic simulation, small enough to check.

Conway's life is the classic "sandboxed tinkering" toy: a grid, a rule, a clock. What makes it
worth recording is that it is **reproducible**: the same size, seed and step count produce the same
grid, so a stored hash is a real claim about what happened and a replay either reproduces it or
proves the record wrong.

Two cells wide of caution:

* the rule is fixed and named. There is one rule here, `B3/S23`, and the record says so. A
  simulation whose rule is a mystery produces a picture nobody can check.
* the hash covers the final grid as text, row by row, so a hash match means the same board - not
  "roughly the same shape".
"""

from __future__ import annotations

import hashlib
import random
from typing import Any

from archx_agent.helpers.exceptions import ValidationError

RULE = "B3/S23"
MAX_CELLS = 250_000
MAX_STEPS = 5_000


def step(cells: set[tuple[int, int]]) -> set[tuple[int, int]]:
    """One generation. Live cells have 2-3 neighbours; a dead cell with exactly 3 is born."""
    counted: dict[tuple[int, int], int] = {}
    for x, y in cells:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx or dy:
                    counted[(x + dx, y + dy)] = counted.get((x + dx, y + dy), 0) + 1
    return {
        cell for cell, count in counted.items()
        if (count == 3) or (count == 2 and cell in cells)
    }


def render(cells: set[tuple[int, int]], width: int, height: int) -> list[str]:
    """One string per row, `#` for alive. The grid is the record, not a picture of it."""
    return [
        "".join("#" if (x, y) in cells else "." for x in range(width))
        for y in range(height)
    ]


def digest(rows: list[str]) -> str:
    return hashlib.sha256(("\n".join(rows) + "\n").encode()).hexdigest()


def run(
    *,
    width: int,
    height: int,
    steps: int,
    seed: int,
    density: float = 0.3,
    wrap: bool = False,
) -> dict[str, Any]:
    """Run the simulation and return everything worth recording about it."""
    if not 1 <= int(width) <= 1000 or not 1 <= int(height) <= 1000:
        raise ValidationError("width and height must be between 1 and 1000")
    if int(width) * int(height) > MAX_CELLS:
        raise ValidationError(f"a simulation may have at most {MAX_CELLS} cells")
    if not 0 <= int(steps) <= MAX_STEPS:
        raise ValidationError(f"steps must be between 0 and {MAX_STEPS}")
    if not 0.0 <= float(density) <= 1.0:
        raise ValidationError("density must be between 0 and 1")
    if wrap:
        raise ValidationError("wrapping needs a torus rule that this build does not have yet")

    generator = random.Random(int(seed))
    cells = {
        (x, y)
        for y in range(int(height))
        for x in range(int(width))
        if generator.random() < float(density)
    }
    series = [len(cells)]
    for _ in range(int(steps)):
        cells = step(cells)
        series.append(len(cells))
    rows = render(cells, int(width), int(height))
    return {
        "rule": RULE,
        "width": int(width),
        "height": int(height),
        "steps": int(steps),
        "seed": int(seed),
        "density": float(density),
        "series": series,
        "final_hash": digest(rows),
        "rows": rows,
        "alive": len(cells),
    }


def replay(record: dict[str, Any]) -> dict[str, Any]:
    """Recompute from the parameters alone, so the stored hash can be checked."""
    again = run(
        width=int(record["width"]),
        height=int(record["height"]),
        steps=int(record["steps"]),
        seed=int(record["seed"]),
        density=float(record.get("density", 0.3)),
    )
    again["matches"] = again["final_hash"] == record["final_hash"]
    return again
