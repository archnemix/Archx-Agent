"""Learning operations for memory governance."""

from __future__ import annotations

import json
from typing import Any, Sequence

from archx_agent.helpers.exceptions import ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now, new_id


class MemoryManagerLearningMixin:
    """Learning responsibility for MemoryManager."""

    def record_learning_event(
        self,
        *,
        topic: str,
        outcome: str,
        goal_id: str | None = None,
        attempts: int = 1,
        mistakes: Sequence[str] | None = None,
        duration_seconds: int | None = None,
    ) -> str:
        if outcome not in ("passed", "failed", "skipped", "in_progress"):
            raise ValidationError(f"unknown learning outcome {outcome!r}")
        event_id = new_id("lrn_")
        now = iso_now()
        with self.store.write_tx() as tx:
            tx.execute(
                "INSERT INTO learning_events(id, goal_id, topic, outcome, attempts, mistakes,"
                " duration_seconds, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    goal_id,
                    topic,
                    outcome,
                    attempts,
                    json_text(list(mistakes or [])),
                    duration_seconds,
                    now,
                ),
            )
        self.trace(
            "learning",
            "learning.event",
            payload={"topic": topic, "outcome": outcome, "attempts": attempts},
        )
        return event_id

    def learner_profile(self, learner_id: str = "default") -> dict[str, Any]:
        """Summarise progress without permanently labelling the learner.

        A single failure never produces a "weak" label: the profile reports
        observations with counts, and ``needs_practice`` requires repeated
        failures *and* recent evidence.
        """
        rows = self.store.query(
            "SELECT topic, outcome, attempts, mistakes, created_at FROM learning_events ORDER BY created_at"
        )
        per_topic: dict[str, dict[str, Any]] = {}
        for row in rows:
            topic = row["topic"]
            entry = per_topic.setdefault(
                topic,
                {
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "in_progress": 0,
                    "last": None,
                    "mistakes": [],
                },
            )
            entry[row["outcome"]] = entry.get(row["outcome"], 0) + 1
            entry["last"] = row["created_at"]
            mistakes = json.loads(row["mistakes"]) if row["mistakes"] else []
            for mistake in mistakes:
                if mistake not in entry["mistakes"]:
                    entry["mistakes"].append(mistake)
        strengths = [
            topic
            for topic, e in per_topic.items()
            if e["passed"] >= 2 and e["passed"] > e["failed"]
        ]
        needs_practice = [
            topic
            for topic, e in per_topic.items()
            if e["failed"] >= 2 and e["failed"] >= e["passed"]
        ]
        stable = [
            topic
            for topic, e in per_topic.items()
            if e["passed"] >= 3 and e["failed"] == 0
        ]
        unresolved = self.list(
            kinds=["learning"], scope="learner", scope_id=learner_id, limit=100
        )
        return {
            "learner_id": learner_id,
            "topics": per_topic,
            "strengths": sorted(strengths),
            "needs_practice": sorted(needs_practice),
            "stable": sorted(stable),
            "unresolved_concepts": [
                m.title for m in unresolved if m.category == "unresolved_concept"
            ],
            "notes": (
                "Labels are observations with counts, not permanent assessments. "
                "A single failed attempt never creates a weakness label."
            ),
        }
