"""M30: Learning Mode.

The tests are organised around the four ways a learning feature lies:

* claiming it graded something it never checked;
* handing over the answer before the learner tried;
* reporting progress as a number with no schedule behind it;
* calling a goal finished because sessions happened.

Everything else (goals, items, sessions, reports, the CLI, the GUI routes) is exercised
through the same objects the interfaces use.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from archx_agent.application.learning import (
    HintBeforeAttempt,
    NothingToStudy,
    grade_answer,
    normalise,
    parse_plan_json,
)
from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import ConflictError, NotFoundError, ValidationError
from archx_agent.managers.learning import (
    GOAL_STATUSES,
    ITEM_STATUSES,
    LEVELS,
    SESSION_MODES,
    due_in,
)
from archx_agent.managers.schema import MIGRATIONS, SCHEMA_VERSION

CLI = os.path.join(os.path.dirname(sys.executable), "archx-agent")


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHX_ALLOW_SIMULATED", "1")
    with open_workspace(home=str(tmp_path / "home"), env={}) as workspace:
        yield workspace


@pytest.fixture()
def manager(ws):
    return ws.learning


@pytest.fixture()
def tutor(ws):
    return ws.tutor


@pytest.fixture()
def goal(manager):
    return manager.create_goal(
        "Rust ownership",
        objective="Understand ownership, borrowing and lifetimes",
        topic="rust",
        level="intermediate",
        success_criteria=["Explain a borrow error", "Fix a moved-value error"],
    )


def add(manager, goal, prompt="What does ownership mean?", **kwargs):
    return manager.add_item(goal.id, prompt, **kwargs)


# --------------------------------------------------------------------------
# schema
# --------------------------------------------------------------------------
class TestSchema:
    def test_the_schema_reaches_v19_and_the_versions_are_contiguous(self):
        # Later milestones add migrations on top; what M30 promises is that its own migration
        # exists, is contiguous with the rest, and that the home is at the newest version.
        assert SCHEMA_VERSION >= 19
        assert any(migration.version == 19 and migration.name == "learning-mode"
                   for migration in MIGRATIONS)
        versions = [migration.version for migration in MIGRATIONS]
        assert versions == sorted(versions)
        assert versions == list(range(1, SCHEMA_VERSION + 1))

    def test_the_learning_columns_exist(self, ws):
        columns = {row["name"] for row in ws.store.query("PRAGMA table_info(learning_lessons)")}
        assert {"expected", "hints", "explanation", "ease", "interval_days", "streak",
                "lapses", "due_at", "correct_count", "last_reviewed_at"} <= columns
        goal_columns = {row["name"] for row in ws.store.query("PRAGMA table_info(learning_goals)")}
        assert {"topic", "success_criteria", "priority", "target_date", "completed_at"} <= goal_columns

    def test_the_child_tables_exist_with_their_indexes(self, ws):
        tables = {row["name"] for row in ws.store.query(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"learning_sessions", "learning_attempts"} <= tables
        indexes = {row["name"] for row in ws.store.query(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        assert "idx_learning_items_due" in indexes

    def test_a_v18_database_upgrades_without_losing_rows(self, tmp_path):
        """The migration is additive: a goal written before M30 still reads afterwards."""
        from archx_agent.helpers.sqlite_store import SqliteStore

        path = tmp_path / "old.db"
        store = SqliteStore(path)
        store.migrate([m for m in MIGRATIONS if m.version <= 18])
        store.execute(
            "INSERT INTO learning_goals(id, title, objective, level, status, created_at, updated_at)"
            " VALUES ('lg_old','Old goal','objective','beginner','active','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')"
        )
        store.migrate(MIGRATIONS)
        row = store.query("SELECT * FROM learning_goals WHERE id='lg_old'")[0]
        assert row["title"] == "Old goal"
        assert row["priority"] == 5 and row["success_criteria"] is None
        assert store.schema_version() == SCHEMA_VERSION
        store.close()


# --------------------------------------------------------------------------
# goals
# --------------------------------------------------------------------------
class TestGoals:
    def test_a_goal_starts_active_with_its_criteria(self, manager):
        goal = manager.create_goal(
            "Rust ownership", objective="own it", success_criteria=["explain a borrow error"],
        )
        stored = manager.get_goal(goal.id)
        assert stored.status == "active" and stored.planned_by == "user"
        assert stored.success_criteria == ["explain a borrow error"]
        assert stored.objective == "own it"

    def test_a_goal_needs_a_real_title(self, manager):
        with pytest.raises(ValidationError):
            manager.create_goal("ab")

    @pytest.mark.parametrize("field,value", [("level", "expert"), ("status", "finished"),
                                             ("planned_by", "vibes")])
    def test_invalid_goal_fields_are_refused(self, manager, field, value):
        kwargs = {field: value}
        with pytest.raises(ValidationError):
            manager.create_goal("A real title", **kwargs)

    def test_priority_is_bounded(self, manager):
        with pytest.raises(ValidationError):
            manager.create_goal("A real title", priority=11)

    def test_the_active_goal_limit_is_a_refusal_not_a_silent_archive(self, ws, monkeypatch):
        monkeypatch.setitem(ws.config.values, "learning.active_goal_limit", 1)
        ws.learning.create_goal("First goal")
        with pytest.raises(ConflictError) as caught:
            ws.learning.create_goal("Second goal")
        assert "active_goal_limit" in caught.value.message

    def test_a_paused_goal_does_not_count_against_the_limit(self, ws, monkeypatch):
        monkeypatch.setitem(ws.config.values, "learning.active_goal_limit", 1)
        first = ws.learning.create_goal("First goal")
        ws.learning.update_goal(first.id, status="paused")
        second = ws.learning.create_goal("Second goal")
        assert second.status == "active"

    def test_a_goal_can_be_found_by_title_or_prefix(self, manager, goal):
        assert manager.find_goal("Rust ownership").id == goal.id
        assert manager.find_goal("rust").id == goal.id
        assert manager.find_goal("lg_nope") is None
        assert manager.find_goal(goal.id).id == goal.id

    def test_an_ambiguous_prefix_names_the_problem(self, manager):
        manager.create_goal("Rust ownership")
        manager.create_goal("Rust lifetimes")
        with pytest.raises(ValidationError) as caught:
            manager.find_goal("Rust")
        assert "more than one" in caught.value.message

    def test_goals_list_active_first_then_priority(self, manager):
        low = manager.create_goal("Low priority", priority=1)
        high = manager.create_goal("High priority", priority=9)
        paused = manager.create_goal("Paused one", priority=9)
        manager.update_goal(paused.id, status="paused")
        listed = [goal.id for goal in manager.list_goals()]
        assert listed[0] == high.id and listed[1] == low.id and listed[2] == paused.id

    def test_completing_a_goal_is_explicit_and_dated(self, manager, goal):
        done = manager.complete_goal(goal.id, note="I fixed two borrow errors")
        assert done.status == "completed" and done.completed_at
        assert done.settings["completion_note"] == "I fixed two borrow errors"
        assert done.settings["completed_by"] == "user:cli"

    def test_completing_twice_is_a_conflict(self, manager, goal):
        manager.complete_goal(goal.id)
        with pytest.raises(ConflictError):
            manager.complete_goal(goal.id)

    def test_reopening_a_goal_clears_its_completion(self, manager, goal):
        manager.complete_goal(goal.id)
        reopened = manager.update_goal(goal.id, status="active")
        assert reopened.completed_at is None

    def test_deleting_a_goal_takes_its_children(self, manager, goal, tutor):
        item = add(manager, goal)
        tutor.answer(item.id, "x", self_rating=4)
        manager.create_session(goal.id)
        manager.delete_goal(goal.id)
        assert manager.list_goals() == []
        with pytest.raises(NotFoundError):
            manager.items(goal.id)
        assert ws_count(manager, "learning_lessons") == 0
        assert ws_count(manager, "learning_attempts") == 0
        assert ws_count(manager, "learning_sessions") == 0


def ws_count(manager, table):
    return int(manager.store.scalar(f"SELECT COUNT(*) FROM {table}") or 0)


# --------------------------------------------------------------------------
# items
# --------------------------------------------------------------------------
class TestItems:
    def test_an_item_holds_its_answer_hints_and_explanation(self, manager, goal):
        item = add(manager, goal, "What is a move?", expected="ownership transfers",
                   hints=["think about freeing", "the original is gone"], explanation="A move transfers ownership.")
        assert item.expected == "ownership transfers"
        assert item.hints == ["think about freeing", "the original is gone"]
        assert item.explanation.startswith("A move")
        assert item.status == "new" and item.attempts == 0

    def test_items_are_positioned_in_order(self, manager, goal):
        first = add(manager, goal, "First question here")
        second = add(manager, goal, "Second question here")
        assert (first.position, second.position) == (1, 2)
        assert [item.id for item in manager.items(goal.id)] == [first.id, second.id]

    def test_an_item_needs_a_real_prompt(self, manager, goal):
        with pytest.raises(ValidationError):
            manager.add_item(goal.id, "hi")

    def test_too_many_hints_is_refused(self, ws, manager, goal, monkeypatch):
        monkeypatch.setitem(ws.config.values, "learning.max_hints", 2)
        with pytest.raises(ValidationError) as caught:
            manager.add_item(goal.id, "A question with hints", hints=["a", "b", "c"])
        assert "max_hints" in caught.value.message

    def test_a_closed_goal_takes_no_new_items(self, manager, goal):
        manager.complete_goal(goal.id)
        with pytest.raises(ConflictError):
            add(manager, goal)

    def test_new_items_are_due_immediately(self, manager, goal):
        item = add(manager, goal)
        assert item.due_at is None and item.is_due() is True
        assert [due.id for due in manager.due_items(goal.id)] == [item.id]

    def test_a_scheduled_item_is_not_due_yet(self, manager, goal):
        item = add(manager, goal)
        manager.update_item(item.id, due_at=due_in(3))
        assert manager.get_item(item.id).is_due() is False
        assert manager.due_items(goal.id) == []

    def test_items_can_be_found_by_prefix_and_deleted_with_their_attempts(self, manager, goal, tutor):
        item = add(manager, goal)
        tutor.answer(item.id, "x", self_rating=5)
        assert manager.find_item(item.id[:8]).id == item.id
        manager.delete_item(item.id)
        assert manager.items(goal.id) == []
        assert ws_count(manager, "learning_attempts") == 0

    def test_an_unknown_item_is_a_404(self, manager):
        with pytest.raises(NotFoundError):
            manager.require_item("li_nope")


# --------------------------------------------------------------------------
# grading
# --------------------------------------------------------------------------
class TestGrading:
    def _item(self, manager, goal, expected=None):
        return add(manager, goal, "A checkable question", expected=expected)

    def test_an_exact_answer_is_graded_exact(self, manager, goal):
        item = self._item(manager, goal, "one owner at a time")
        grade = grade_answer(item, "One owner at a time.", self_rating=None)
        assert grade.correct and grade.graded_by == "exact"

    def test_case_and_punctuation_do_not_decide_the_grade(self, manager, goal):
        item = self._item(manager, goal, "Ownership transfers on move")
        assert normalise("Ownership  TRANSFERS, on move!") == "ownership transfers on move"
        assert grade_answer(item, "ownership transfers on move", self_rating=None).correct

    def test_every_expected_term_present_counts_as_correct_but_says_so(self, manager, goal):
        item = self._item(manager, goal, "the value is borrowed")
        grade = grade_answer(item, "the value is borrowed temporarily", self_rating=None)
        assert grade.correct and "not the exact wording" in grade.feedback

    def test_a_wrong_answer_reveals_the_expected_one(self, manager, goal):
        item = self._item(manager, goal, "the value is borrowed")
        grade = grade_answer(item, "no idea", self_rating=None)
        assert grade.correct is False
        assert "the value is borrowed" in grade.feedback

    @pytest.mark.parametrize("rating,correct", [(1, False), (2, False), (3, True), (4, True), (5, True)])
    def test_a_self_rating_is_the_grade_and_the_record_says_so(self, manager, goal, rating, correct):
        item = self._item(manager, goal)
        grade = grade_answer(item, "my attempt", self_rating=rating)
        assert grade.correct is correct and grade.graded_by == "self"
        assert "Archx did not check the answer" in grade.feedback

    def test_without_an_expected_answer_or_a_rating_there_is_no_grade(self, manager, goal):
        item = self._item(manager, goal)
        with pytest.raises(ValidationError) as caught:
            grade_answer(item, "an answer", self_rating=None)
        assert "cannot grade" in caught.value.message

    def test_a_self_rating_outside_one_to_five_is_refused(self, manager, goal):
        item = self._item(manager, goal)
        with pytest.raises(ValidationError):
            grade_answer(item, "x", self_rating=9)

    def test_an_empty_answer_with_no_rating_is_refused(self, manager, goal):
        item = self._item(manager, goal)
        with pytest.raises(ValidationError):
            grade_answer(item, "   ", self_rating=None)

    def test_the_expected_answer_beats_a_generous_self_rating(self, manager, goal, tutor):
        item = self._item(manager, goal, "the value is borrowed")
        result = tutor.answer(item.id, "something else entirely", self_rating=5)
        assert result["grade"]["correct"] is False
        assert result["grade"]["graded_by"] == "exact"


# --------------------------------------------------------------------------
# schedule
# --------------------------------------------------------------------------
class TestSchedule:
    def test_the_first_correct_answer_schedules_one_day_out(self, manager, goal, tutor):
        item = add(manager, goal, expected="yes")
        result = tutor.answer(item.id, "yes")
        assert result["schedule"]["interval_days"] == 1.0
        assert result["schedule"]["streak"] == 1
        assert result["item"]["status"] == "review"
        assert result["item"]["due_at"] == result["schedule"]["due_at"]

    def test_the_second_correct_answer_is_three_days(self, manager, goal, tutor):
        item = add(manager, goal, expected="yes")
        tutor.answer(item.id, "yes")
        second = tutor.answer(item.id, "yes")
        assert second["schedule"]["interval_days"] == 3.0
        assert second["schedule"]["streak"] == 2

    def test_the_third_interval_multiplies_by_ease(self, manager, goal, tutor):
        item = add(manager, goal, expected="yes")
        for _ in range(2):
            tutor.answer(item.id, "yes")
        third = tutor.answer(item.id, "yes")
        assert third["schedule"]["interval_days"] > 3.0
        assert third["schedule"]["ease"] > 2.5

    def test_a_wrong_answer_resets_the_interval_and_is_due_now(self, manager, goal, tutor):
        item = add(manager, goal, expected="yes")
        tutor.answer(item.id, "yes")
        wrong = tutor.answer(item.id, "no")
        assert wrong["schedule"]["interval_days"] == 0.0
        assert wrong["schedule"]["streak"] == 0
        assert wrong["schedule"]["lapses"] == 1
        assert wrong["item"]["status"] == "learning"
        assert wrong["item"]["due_at"] <= wrong["attempt"]["created_at"]

    def test_ease_has_a_floor_so_a_bad_streak_cannot_collapse_it(self, ws, manager, goal, tutor):
        item = add(manager, goal, expected="yes")
        for _ in range(12):
            tutor.answer(item.id, "no")
        assert manager.get_item(item.id).ease == pytest.approx(float(ws.config.get("learning.min_ease")))

    def test_mastery_needs_a_streak_and_a_long_interval(self, manager, goal, tutor):
        item = add(manager, goal, expected="yes")
        statuses = [tutor.answer(item.id, "yes")["item"]["status"] for _ in range(6)]
        assert "mastered" in statuses
        assert statuses[-1] == "mastered"
        stored = manager.get_item(item.id)
        assert stored.streak >= 4 and stored.interval_days >= 14

    def test_every_schedule_change_is_stored_and_explained(self, manager, goal, tutor):
        item = add(manager, goal, expected="yes")
        result = tutor.answer(item.id, "yes")
        stored = manager.get_item(item.id)
        assert stored.streak == result["schedule"]["streak"]
        assert stored.ease == result["schedule"]["ease"]
        assert stored.interval_days == result["schedule"]["interval_days"]
        assert result["schedule"]["why"]


# --------------------------------------------------------------------------
# hints
# --------------------------------------------------------------------------
class TestHints:
    def test_a_hint_before_an_attempt_is_refused_with_the_reason(self, manager, goal, tutor):
        item = add(manager, goal, hints=["a nudge", "the answer"])
        with pytest.raises(HintBeforeAttempt) as caught:
            tutor.hint(item.id)
        assert "try first" in caught.value.message
        assert item.id in caught.value.message

    def test_the_ladder_opens_after_one_attempt(self, manager, goal, tutor):
        item = add(manager, goal, hints=["a nudge", "the answer"])
        tutor.answer(item.id, "x", self_rating=2)
        payload = tutor.hint(item.id, level=2)
        assert payload["hint"] == "the answer" and payload["revealed"] == ["a nudge", "the answer"]
        assert payload["more"] == 0

    def test_hint_levels_are_bounded(self, manager, goal, tutor):
        item = add(manager, goal, hints=["only one"])
        tutor.answer(item.id, "x", self_rating=3)
        with pytest.raises(ValidationError):
            tutor.hint(item.id, level=2)
        with pytest.raises(ValidationError):
            tutor.hint(item.id, level=0)

    def test_an_item_with_no_hints_says_so(self, manager, goal, tutor):
        item = add(manager, goal)
        with pytest.raises(ValidationError) as caught:
            tutor.hint(item.id)
        assert "no hints" in caught.value.message

    def test_try_first_can_be_turned_off_deliberately(self, ws, manager, goal, tutor, monkeypatch):
        monkeypatch.setitem(ws.config.values, "learning.try_first", False)
        item = add(manager, goal, hints=["a nudge"])
        assert tutor.hint(item.id)["hint"] == "a nudge"

    def test_hints_are_used_up_in_order_not_dumped(self, manager, goal, tutor):
        item = add(manager, goal, hints=["one", "two", "three"])
        tutor.answer(item.id, "x", self_rating=1)
        assert tutor.hint(item.id, level=1)["revealed"] == ["one"]
        assert tutor.hint(item.id, level=3)["revealed"] == ["one", "two", "three"]


# --------------------------------------------------------------------------
# sessions
# --------------------------------------------------------------------------
class TestSessions:
    def test_a_session_is_a_task_and_has_a_queue(self, manager, goal, tutor):
        add(manager, goal)
        started = tutor.start_session(goal.id, mode="practice")
        assert started["session"]["mode"] == "practice"
        assert started["task_id"] and manager.get_session(started["session"]["id"]).task_id
        assert len(started["queue"]) == 1
        assert tutor.ws.tasks.get(started["task_id"]).status == "running"

    def test_answering_without_a_session_still_attaches_one(self, manager, goal, tutor):
        item = add(manager, goal, expected="yes")
        result = tutor.answer(item.id, "yes")
        session = result["session"]
        assert session["id"].startswith("ls_")
        assert session["items_attempted"] == 1 and session["items_correct"] == 1

    def test_a_second_answer_joins_the_same_open_session(self, manager, goal, tutor):
        first = add(manager, goal, expected="yes")
        second = add(manager, goal, "Another question", expected="yes")
        one = tutor.answer(first.id, "yes")["session"]["id"]
        two = tutor.answer(second.id, "yes")["session"]["id"]
        assert one == two
        session = manager.get_session(one)
        assert (session.items_attempted, session.items_correct) == (2, 2)

    def test_closing_a_session_summarises_and_completes_its_task(self, manager, goal, tutor):
        item = add(manager, goal, expected="yes")
        started = tutor.start_session(goal.id)
        tutor.answer(item.id, "yes", session_id=started["session"]["id"])
        closed = tutor.end_session(started["session"]["id"])
        assert closed["session"]["status"] == "closed" and closed["session"]["ended_at"]
        assert "1 answered" in closed["summary"]
        assert tutor.ws.tasks.get(started["task_id"]).status == "completed"

    def test_closing_twice_is_idempotent(self, manager, goal, tutor):
        started = tutor.start_session(goal.id)
        first = tutor.end_session(started["session"]["id"])
        second = tutor.end_session(started["session"]["id"])
        assert first["session"]["id"] == second["session"]["id"]

    def test_a_session_needs_an_active_goal(self, manager, goal):
        manager.update_goal(goal.id, status="paused")
        with pytest.raises(ConflictError):
            manager.create_session(goal.id)

    def test_hint_use_is_counted_on_the_session(self, manager, goal, tutor):
        item = add(manager, goal, expected="yes", hints=["a", "b"])
        session = tutor.start_session(goal.id)["session"]["id"]
        tutor.answer(item.id, "no", session_id=session, hints_used=2)
        assert manager.get_session(session).hints_used == 2

    def test_review_with_nothing_due_is_a_named_refusal(self, manager, goal, tutor):
        item = add(manager, goal, expected="yes")
        tutor.answer(item.id, "yes")
        with pytest.raises(NothingToStudy) as caught:
            tutor.review(goal.id)
        assert "nothing is due" in caught.value.message

    def test_a_review_session_holds_what_is_due(self, manager, goal, tutor):
        item = add(manager, goal, expected="yes")
        tutor.answer(item.id, "no")
        outcome = tutor.review(goal.id)
        assert outcome["session"]["mode"] == "review"
        assert item.id in [due["id"] for due in outcome["items"]]


# --------------------------------------------------------------------------
# choosing what is next
# --------------------------------------------------------------------------
class TestNext:
    def test_next_says_why_this_item(self, manager, goal, tutor):
        add(manager, goal)
        payload = tutor.next_item(goal.id)
        assert payload["why"].startswith("new")
        assert payload["item"]["prompt"]

    def test_next_prefers_something_due_over_something_new(self, manager, goal, tutor):
        fresh = add(manager, goal, "A brand new question")
        seen = add(manager, goal, "An old question", expected="yes")
        tutor.answer(seen.id, "no")  # wrong -> due immediately
        assert tutor.next_item(goal.id)["item"]["id"] == seen.id
        assert fresh.id != seen.id

    def test_next_on_an_empty_goal_is_a_named_result(self, manager, goal, tutor):
        with pytest.raises(NothingToStudy) as caught:
            tutor.next_item(goal.id)
        assert "nothing to study" in caught.value.message

    def test_a_paused_goal_cannot_be_studied(self, manager, goal, tutor):
        add(manager, goal)
        manager.update_goal(goal.id, status="paused")
        with pytest.raises(ConflictError):
            tutor.next_item(goal.id)

    def test_ask_hides_the_answer_the_hints_and_the_explanation(self, manager, goal, tutor):
        add(manager, goal, "Explain a move", expected="ownership transfers",
            hints=["think"], explanation="A move transfers ownership.")
        payload = tutor.ask(goal.id)
        assert "expected" not in payload["item"] and "hints" not in payload["item"]
        assert "explanation" not in payload["item"]
        assert payload["item"]["hint_count"] == 1


# --------------------------------------------------------------------------
# planning
# --------------------------------------------------------------------------
class TestAsk:
    def test_ask_removes_the_answer_and_the_ladder(self, manager, goal, tutor):
        item = add(manager, goal, expected="WAL", hints=["a nudge"], explanation="because")
        payload = tutor.ask(goal.id)
        blob = json.dumps(payload)
        assert payload["item"]["id"] == item.id
        assert "expected" not in payload["item"]
        assert "hints" not in payload["item"] and "explanation" not in payload["item"]
        assert "WAL" not in blob and "a nudge" not in blob and "because" not in blob

    def test_ask_keeps_the_reason_and_the_count(self, manager, goal, tutor):
        add(manager, goal, expected="yes", hints=["one", "two"])
        payload = tutor.ask(goal.id)
        assert payload["why"] and payload["due_count"] == 1
        assert payload["item"]["hint_count"] == 2

    def test_ask_with_nothing_to_study_is_the_same_refusal(self, manager, goal, tutor):
        item = add(manager, goal, expected="yes")
        tutor.answer(item.id, "yes")
        with pytest.raises(NothingToStudy):
            tutor.ask(goal.id)


class TestPlan:
    def test_without_a_model_the_plan_is_checkpoints_of_your_own_goal(self, manager, goal, tutor):
        outcome = tutor.plan(goal.id, use_model=False)
        assert outcome["planned_by"] == "rules"
        assert "checkpoints of your own goal" in outcome["why"]
        assert len(outcome["items"]) >= 2
        assert all(item["source"] == "rules" for item in outcome["items"])
        assert manager.get_goal(goal.id).planned_by == "rules"

    def test_the_plan_respects_its_cap(self, manager, goal, tutor):
        outcome = tutor.plan(goal.id, use_model=False, max_items=2)
        assert len(outcome["items"]) == 2

    def test_the_plan_uses_the_criteria_first(self, manager, goal, tutor):
        outcome = tutor.plan(goal.id, use_model=False)
        assert "Explain a borrow error" in outcome["items"][0]["prompt"]

    def test_a_validated_model_plan_is_used(self, ws, manager, goal, tutor, monkeypatch):
        payload = json.dumps([
            {"prompt": "What is a lifetime?", "expected": "a region where a reference is valid",
             "hints": ["think scope"], "explanation": "Lifetimes bound borrows."},
        ])

        class Reply:
            text = payload

        from archx_agent.application.chat import ChatService

        monkeypatch.setattr(ChatService, "send", lambda *a, **k: Reply())
        outcome = tutor.plan(goal.id, use_model=True)
        assert outcome["planned_by"] == "model"
        assert outcome["items"][0]["expected"].startswith("a region")

    def test_an_unusable_model_plan_falls_back_and_says_why(self, ws, manager, goal, tutor, monkeypatch):
        class Reply:
            text = "Sure! Here are some ideas: ..."

        from archx_agent.application.chat import ChatService

        monkeypatch.setattr(ChatService, "send", lambda *a, **k: Reply())
        outcome = tutor.plan(goal.id, use_model=True)
        assert outcome["planned_by"] == "rules"
        assert "unusable" in outcome["why"]

    def test_a_model_that_raises_falls_back_rather_than_failing(self, ws, manager, goal, tutor, monkeypatch):
        def explode(*args, **kwargs):
            raise RuntimeError("no model")

        from archx_agent.application.chat import ChatService

        monkeypatch.setattr(ChatService, "send", explode)
        outcome = tutor.plan(goal.id, use_model=True)
        assert outcome["planned_by"] == "rules" and outcome["items"]

    def test_plan_parsing_keeps_only_usable_items(self):
        items = parse_plan_json(json.dumps([
            {"prompt": "A good question", "expected": "answer", "hints": ["a", "b", "c", "d"]},
            {"prompt": "hi"},
            "not an object",
            {"question": "A question phrased differently"},
        ]))
        assert [item["prompt"] for item in items] == ["A good question", "A question phrased differently"]
        assert len(items[0]["hints"]) == 3

    def test_plan_parsing_rejects_prose(self):
        assert parse_plan_json("here you go: no json") == []
        assert parse_plan_json("") == []


# --------------------------------------------------------------------------
# stats, search and the report
# --------------------------------------------------------------------------
class TestReporting:
    def test_stats_count_items_attempts_and_accuracy(self, manager, goal, tutor):
        first = add(manager, goal, expected="yes")
        second = add(manager, goal, "Second question", expected="yes")
        tutor.answer(first.id, "yes")
        tutor.answer(second.id, "no")
        stats = manager.stats(goal.id)
        assert stats["items"] == 2 and stats["attempts"] == 2 and stats["correct"] == 1
        assert stats["accuracy"] == 0.5
        assert stats["goal_id"] == goal.id

    def test_global_stats_add_up(self, manager, goal, tutor):
        tutor.answer(add(manager, goal, expected="yes").id, "yes")
        stats = manager.stats()
        assert stats["goals"] == 1 and stats["items"] >= 1 and stats["attempts"] == 1

    def test_search_finds_goals_and_items(self, manager, goal):
        add(manager, goal, "What is a dangling reference?")
        hits = manager.search("dangling")
        assert hits and hits[0]["kind"] == "item"
        assert manager.search("ownership")[0]["kind"] == "goal"

    def test_a_one_letter_search_is_refused(self, manager):
        with pytest.raises(ValidationError):
            manager.search("a")

    def test_the_report_states_the_schedule_and_who_grades(self, manager, goal, tutor):
        item = add(manager, goal, "Explain a move", expected="ownership transfers")
        tutor.answer(item.id, "ownership transfers")
        text = tutor.report(goal.id)
        assert text.startswith("# Learning: Rust ownership")
        assert "Success criteria" in text and "Explain a borrow error" in text
        assert "next review" in text
        assert "graded_by = exact" in text and "graded_by = self" in text
        assert "never does it for you" in text

    def test_the_report_says_when_nothing_is_planned(self, manager, goal, tutor):
        assert "nothing planned yet" in tutor.report(goal.id)

    def test_writing_the_report_creates_a_file(self, manager, goal, tutor, tmp_path):
        target = tmp_path / "progress.md"
        path = tutor.write_report(goal.id, str(target))
        assert target.exists() and "Learning: Rust ownership" in target.read_text()
        assert path == str(target)

    def test_the_report_never_completes_a_goal(self, manager, goal, tutor):
        add(manager, goal, expected="yes")
        tutor.report(goal.id)
        assert manager.get_goal(goal.id).status == "active"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def cli(tmp_path, *args):
    env = {**os.environ, "ARCHX_PATHS_HOME": str(tmp_path / "home"), "ARCHX_ALLOW_SIMULATED": "1"}
    return subprocess.run([CLI, *args], capture_output=True, text=True, env=env, timeout=180)


class TestItemEditing:
    def test_editing_cannot_outgrow_the_hint_limit(self, manager):
        goal = manager.create_goal("Rust ownership")
        item = manager.add_item(goal.id, "A question", hints=["one"])
        with pytest.raises(ValidationError, match="at most"):
            manager.update_item(item.id, hints=["a", "b", "c", "d", "e", "f"])
        assert manager.get_item(item.id).hints == ["one"]

    def test_editing_blank_hints_are_dropped(self, manager):
        goal = manager.create_goal("Rust ownership")
        item = manager.add_item(goal.id, "A question")
        updated = manager.update_item(item.id, hints=["  ", "a nudge", ""])
        assert updated.hints == ["a nudge"]

    def test_the_question_can_be_reworded_without_touching_the_schedule(self, manager):
        goal = manager.create_goal("Rust ownership")
        item = manager.add_item(goal.id, "Old wording", expected="answer")
        updated = manager.update_item(item.id, topic="New wording")
        assert updated.prompt == "New wording"
        assert updated.expected == "answer" and updated.status == "new"


class TestCli:
    def test_a_goal_can_be_created_listed_and_shown(self, tmp_path):
        assert cli(tmp_path, "init").returncode == 0
        created = cli(tmp_path, "learning", "goal", "create", "Rust ownership",
                      "--objective", "own it", "--criteria", "explain a borrow error")
        assert created.returncode == 0 and "created goal lg_" in created.stdout
        listing = cli(tmp_path, "learning", "goal", "list", "--json")
        data = json.loads(listing.stdout)
        assert data[0]["title"] == "Rust ownership"
        shown = cli(tmp_path, "learning", "goal", "show", data[0]["id"])
        assert shown.returncode == 0 and "done when" in shown.stdout

    def test_the_whole_loop_works_from_the_cli(self, tmp_path):
        cli(tmp_path, "init")
        created = cli(tmp_path, "learning", "goal", "create", "Rust ownership",
                      "--objective", "ownership and borrows", "--criteria", "explain a borrow error")
        goal_id = created.stdout.split()[2]
        planned = cli(tmp_path, "learning", "plan", goal_id, "--no-model")
        assert planned.returncode == 0 and "by rules" in planned.stdout
        nxt = cli(tmp_path, "--json", "learning", "next", goal_id)
        item_id = json.loads(nxt.stdout)["item"]["id"]
        answered = cli(tmp_path, "learning", "answer", item_id, "an attempt", "--self-rate", "4")
        assert answered.returncode == 0 and "graded by self" in answered.stdout
        assert "next due" in answered.stdout

    def test_a_hint_before_an_attempt_exits_three(self, tmp_path):
        cli(tmp_path, "init")
        created = cli(tmp_path, "learning", "goal", "create", "Rust ownership")
        goal_id = created.stdout.split()[2]
        item = cli(tmp_path, "learning", "item", "add", goal_id, "A question with hints",
                   "--hint", "first nudge", "--expected", "answer").stdout.split()[2]
        refused = cli(tmp_path, "learning", "hint", item)
        assert refused.returncode == 3
        assert "try first" in refused.stdout
        cli(tmp_path, "learning", "answer", item, "answer")
        allowed = cli(tmp_path, "learning", "hint", item)
        assert allowed.returncode == 0 and "first nudge" in allowed.stdout

    def test_ask_shows_the_question_without_the_answer(self, tmp_path):
        cli(tmp_path, "init")
        created = cli(tmp_path, "learning", "goal", "create", "Rust ownership")
        goal_id = created.stdout.split()[2]
        cli(tmp_path, "learning", "item", "add", goal_id, "What is a borrow error?",
            "--expected", "a loan that outlives its owner")
        asked = cli(tmp_path, "learning", "ask", goal_id)
        assert asked.returncode == 0
        assert "What is a borrow error?" in asked.stdout
        assert "a loan that outlives its owner" not in asked.stdout

    def test_next_with_nothing_to_study_exits_three(self, tmp_path):
        cli(tmp_path, "init")
        created = cli(tmp_path, "learning", "goal", "create", "Rust ownership")
        goal_id = created.stdout.split()[2]
        result = cli(tmp_path, "learning", "next", goal_id)
        assert result.returncode == 3 and "nothing to study" in result.stdout

    def test_delete_needs_yes(self, tmp_path):
        cli(tmp_path, "init")
        created = cli(tmp_path, "learning", "goal", "create", "Rust ownership")
        goal_id = created.stdout.split()[2]
        assert cli(tmp_path, "learning", "goal", "delete", goal_id).returncode == 2
        assert cli(tmp_path, "learning", "goal", "delete", goal_id, "--yes").returncode == 0

    def test_an_item_can_be_edited_after_it_was_added(self, tmp_path):
        cli(tmp_path, "init")
        created = cli(tmp_path, "learning", "goal", "create", "Rust ownership")
        goal_id = created.stdout.split()[2]
        item = cli(tmp_path, "learning", "item", "add", goal_id, "A question",
                   "--expected", "answer").stdout.split()[2]
        edited = cli(tmp_path, "learning", "item", "edit", item,
                     "--prompt", "A better question", "--add-hint", "first nudge",
                     "--add-hint", "second nudge")
        assert edited.returncode == 0
        assert "ladder 2 hint(s)" in edited.stdout
        shown = json.loads(cli(tmp_path, "--json", "learning", "item", "list", goal_id).stdout)
        assert shown[0]["prompt"] == "A better question"
        assert shown[0]["hints"] == ["first nudge", "second nudge"]

    def test_clearing_the_ladder_leaves_it_empty(self, tmp_path):
        cli(tmp_path, "init")
        created = cli(tmp_path, "learning", "goal", "create", "Rust ownership")
        goal_id = created.stdout.split()[2]
        item = cli(tmp_path, "learning", "item", "add", goal_id, "A question",
                   "--hint", "a nudge").stdout.split()[2]
        cleared = json.loads(cli(tmp_path, "--json", "learning", "item", "edit", item,
                                 "--clear-hints").stdout)
        assert cleared["hints"] == [] and cleared["hint_count"] == 0
        rebuilt = json.loads(cli(tmp_path, "--json", "learning", "item", "edit", item,
                                 "--clear-hints", "--add-hint", "one").stdout)
        assert rebuilt["hints"] == ["one"]

    def test_editing_with_nothing_to_change_is_a_usage_error(self, tmp_path):
        cli(tmp_path, "init")
        created = cli(tmp_path, "learning", "goal", "create", "Rust ownership")
        goal_id = created.stdout.split()[2]
        item = cli(tmp_path, "learning", "item", "add", goal_id, "A question").stdout.split()[2]
        result = cli(tmp_path, "learning", "item", "edit", item)
        assert result.returncode == 2 and "nothing to change" in result.stderr

    def test_an_unknown_goal_is_a_domain_error(self, tmp_path):
        cli(tmp_path, "init")
        result = cli(tmp_path, "learning", "goal", "show", "lg_nope")
        assert result.returncode == 1 and "no learning goal" in result.stderr

    def test_the_report_can_be_written(self, tmp_path):
        cli(tmp_path, "init")
        created = cli(tmp_path, "learning", "goal", "create", "Rust ownership")
        goal_id = created.stdout.split()[2]
        target = tmp_path / "report.md"
        result = cli(tmp_path, "learning", "report", goal_id, "--write", str(target))
        assert result.returncode == 0 and target.exists()

    def test_completing_a_goal_from_the_cli_says_who_decided(self, tmp_path):
        cli(tmp_path, "init")
        created = cli(tmp_path, "learning", "goal", "create", "Rust ownership")
        goal_id = created.stdout.split()[2]
        done = cli(tmp_path, "learning", "goal", "complete", goal_id, "--note", "I fixed it")
        assert done.returncode == 0
        assert "your call against your criteria" in done.stdout


# --------------------------------------------------------------------------
# GUI routes
# --------------------------------------------------------------------------
class TestGui:
    def _api(self, ws):
        from archx_agent.interfaces.gui.server import GuiApi

        return GuiApi(ws, token="t")

    def _call(self, api, method, path, body=None):
        from archx_agent.interfaces.gui.server import Request

        response = api.dispatch(Request(
            method=method, path=path, headers={"x-archx-token": "t"}, body=body
        ))
        return response.status, response.payload

    def test_the_learning_routes_exist(self, ws):
        api = self._api(ws)
        shapes = {route.pattern.pattern for route in api.routes()}
        assert "^/api/learning$" in shapes
        assert "^/api/learning/goals/(?P<goal_id>[^/]+)/answer$" in shapes

    def test_a_goal_can_be_created_and_read_back(self, ws, goal):
        api = self._api(ws)
        status, payload = self._call(api, "GET", "/api/learning")
        assert status == 200 and payload["data"]["goals"][0]["id"] == goal.id
        detail = self._call(api, "GET", f"/api/learning/goals/{goal.id}")[1]["data"]
        assert detail["goal"]["title"] == goal.title

    def test_creating_a_goal_through_the_api(self, ws):
        api = self._api(ws)
        status, payload = self._call(api, "POST", "/api/learning/goals",
                                     {"title": "Rust ownership", "criteria": ["explain a borrow error"]})
        assert status == 200 and payload["data"]["title"] == "Rust ownership"

    def test_answering_through_the_api_returns_the_schedule(self, ws, manager, goal):
        api = self._api(ws)
        item = add(manager, goal, expected="yes")
        status, payload = self._call(
            api, "POST", f"/api/learning/goals/{goal.id}/answer",
            {"item_id": item.id, "answer": "yes"},
        )
        assert status == 200
        assert payload["data"]["schedule"]["interval_days"] == 1.0
        assert payload["data"]["grade"]["graded_by"] == "exact"

    def test_a_hint_before_an_attempt_is_409_with_the_reason(self, ws, manager, goal):
        api = self._api(ws)
        item = add(manager, goal, hints=["nudge"])
        status, payload = self._call(api, "POST", f"/api/learning/items/{item.id}/hint", {"level": 1})
        assert status == 409 and payload["error"]["code"] == "try_first"

    def test_an_item_from_another_goal_is_refused(self, ws, manager, goal):
        api = self._api(ws)
        other = manager.create_goal("Another goal entirely")
        item = add(manager, other, expected="yes")
        status, payload = self._call(
            api, "POST", f"/api/learning/goals/{goal.id}/answer",
            {"item_id": item.id, "answer": "yes"},
        )
        assert status == 400 and "does not belong" in payload["error"]["message"]

    def test_planning_through_the_api_stores_items(self, ws, manager, goal):
        api = self._api(ws)
        status, payload = self._call(api, "POST", f"/api/learning/goals/{goal.id}/plan",
                                     {"use_model": False})
        assert status == 200 and payload["data"]["planned_by"] == "rules"
        assert len(manager.items(goal.id)) >= 2

    def test_review_with_nothing_due_is_409(self, ws, manager, goal):
        api = self._api(ws)
        item = add(manager, goal, expected="yes")
        manager.record_attempt(item.id, answer="yes", correct=True, graded_by="exact",
                               interval_days=5, due_at=due_in(5), next_status="review")
        status, payload = self._call(api, "POST", f"/api/learning/goals/{goal.id}/review", {})
        assert status == 409 and payload["error"]["code"] == "nothing_due"

    def test_an_item_can_be_added_through_the_api(self, ws, manager, goal):
        api = self._api(ws)
        status, payload = self._call(
            api, "POST", f"/api/learning/goals/{goal.id}/items",
            {"prompt": "Which mode lets readers keep reading?",
             "expected": "WAL", "hints": "three letters\nstarts with W"},
        )
        assert status == 200
        assert payload["data"]["hint_count"] == 2
        assert manager.items(goal.id)[0].expected == "WAL"

    def test_a_hint_ladder_can_be_sent_as_text_from_the_page(self, ws, goal):
        api = self._api(ws)
        _, payload = self._call(
            api, "POST", f"/api/learning/goals/{goal.id}/items",
            {"prompt": "A question with a ladder", "hints": "first\n\n  second  \n"},
        )
        assert payload["data"]["hints"] == ["first", "second"]

    def test_an_item_without_a_question_is_400(self, ws, goal):
        api = self._api(ws)
        status, payload = self._call(api, "POST", f"/api/learning/goals/{goal.id}/items",
                                     {"expected": "yes"})
        assert status == 400 and payload["error"]["code"] == "validation"

    def test_the_cookie_write_guard_is_still_in_force(self, ws, goal):
        api = self._api(ws)
        from archx_agent.interfaces.gui.server import Request

        request = Request(
            method="POST", path=f"/api/learning/goals/{goal.id}/items", query={},
            headers={"cookie": f"archx_gui={api._cookie_value()}"}, body={"prompt": "A question"},
        )
        response = api.dispatch(request)
        assert response.status == 403
        assert response.payload["error"]["code"] == "csrf"

    def test_the_page_has_a_learning_tab_and_section(self):
        from archx_agent.interfaces.gui.server import ASSETS

        html = (ASSETS / "index.html").read_text()
        assert 'data-view="learning"' in html
        assert 'id="view-learning"' in html
        assert 'id="learning-goal-form"' in html


# --------------------------------------------------------------------------
# targeted guards
# --------------------------------------------------------------------------
class TestTargetedGuards:
    def test_an_answer_cannot_mark_a_goal_complete(self, manager, goal, tutor):
        item = add(manager, goal, expected="yes")
        for _ in range(6):
            tutor.answer(item.id, "yes")
        assert manager.get_goal(goal.id).status == "active"

    def test_a_mastered_item_leaves_the_review_queue(self, manager, goal, tutor):
        item = add(manager, goal, expected="yes")
        for _ in range(6):
            tutor.answer(item.id, "yes")
        assert manager.get_item(item.id).status == "mastered"
        assert manager.due_items(goal.id) == []

    def test_the_schedule_is_monotonic_across_answers(self, manager, goal, tutor):
        item = add(manager, goal, expected="yes")
        dues = []
        for _ in range(4):
            dues.append(tutor.answer(item.id, "yes")["schedule"]["due_at"])
        assert dues == sorted(dues)

    def test_a_goal_limit_does_not_silently_drop_the_oldest(self, ws, monkeypatch):
        monkeypatch.setitem(ws.config.values, "learning.active_goal_limit", 1)
        ws.learning.create_goal("First goal")
        with pytest.raises(ConflictError):
            ws.learning.create_goal("Second goal")
        assert len(ws.learning.list_goals()) == 1

    def test_an_item_cannot_be_answered_after_its_goal_is_completed(self, manager, goal, tutor):
        item = add(manager, goal, expected="yes")
        manager.complete_goal(goal.id)
        with pytest.raises(ConflictError):
            tutor.answer(item.id, "yes")

    def test_every_stored_status_is_one_the_manager_declares(self, manager, goal, tutor):
        item = add(manager, goal, expected="yes")
        for answer in ("no", "yes", "yes", "yes", "yes", "yes"):
            tutor.answer(item.id, answer)
        assert manager.get_item(item.id).status in ITEM_STATUSES
        assert manager.get_goal(goal.id).status in GOAL_STATUSES
        session = manager.sessions(goal.id)[0]
        assert session.mode in SESSION_MODES
        assert manager.get_goal(goal.id).level in LEVELS
