"""Argument grammar for learning commands."""

from __future__ import annotations

import argparse

def register_parser(sub: argparse._SubParsersAction) -> None:
    learn = sub.add_parser(
        "learning", help="Learning Mode: goals, reviewable items, sessions"
    )
    ln_sub = learn.add_subparsers(dest="learning_command", required=True)

    ln_goal = ln_sub.add_parser(
        "goal", help="the goal: what you are learning and what counts as done"
    )
    ln_goal_sub = ln_goal.add_subparsers(dest="learning_goal_command", required=True)
    ln_goal_new = ln_goal_sub.add_parser("create", help="create a goal")
    ln_goal_new.add_argument("title")
    ln_goal_new.add_argument(
        "--objective", help="what you want to be able to do (default: the title)"
    )
    ln_goal_new.add_argument(
        "--topic", help="the subject, used by the planner and search"
    )
    ln_goal_new.add_argument(
        "--level", choices=["beginner", "intermediate", "advanced"], default="beginner"
    )
    ln_goal_new.add_argument(
        "--criteria",
        action="append",
        default=[],
        metavar="TEXT",
        help="a success criterion (repeatable). Completion is measured against these",
    )
    ln_goal_new.add_argument(
        "--priority", type=int, default=5, help="0-9, higher sorts first"
    )
    ln_goal_new.add_argument(
        "--target-date", help="when you mean to be done (ISO date)"
    )
    ln_goal_list = ln_goal_sub.add_parser("list", help="goals, active first")
    ln_goal_list.add_argument(
        "--status", choices=["active", "paused", "completed", "abandoned"]
    )
    ln_goal_list.add_argument("--limit", type=int, default=20)
    ln_goal_show = ln_goal_sub.add_parser(
        "show", help="one goal with its items, schedule and stats"
    )
    ln_goal_show.add_argument("goal")
    ln_goal_edit = ln_goal_sub.add_parser("edit", help="change a goal")
    ln_goal_edit.add_argument("goal")
    ln_goal_edit.add_argument("--title")
    ln_goal_edit.add_argument("--objective")
    ln_goal_edit.add_argument("--topic")
    ln_goal_edit.add_argument(
        "--level", choices=["beginner", "intermediate", "advanced"]
    )
    ln_goal_edit.add_argument("--priority", type=int)
    ln_goal_edit.add_argument(
        "--status", choices=["active", "paused", "completed", "abandoned"]
    )
    ln_goal_edit.add_argument("--criteria", action="append", default=[], metavar="TEXT")
    ln_goal_done = ln_goal_sub.add_parser(
        "complete", help="close a goal against your criteria"
    )
    ln_goal_done.add_argument("goal")
    ln_goal_done.add_argument("--note", help="what convinced you it is done")
    ln_goal_del = ln_goal_sub.add_parser(
        "delete", help="delete a goal and everything under it"
    )
    ln_goal_del.add_argument("goal")
    ln_goal_del.add_argument("--yes", action="store_true")

    ln_item = ln_sub.add_parser(
        "item", help="what is studied: a question with an answer, hints and a schedule"
    )
    ln_item_sub = ln_item.add_subparsers(dest="learning_item_command", required=True)
    ln_item_add = ln_item_sub.add_parser("add", help="add one item to a goal")
    ln_item_add.add_argument("goal")
    ln_item_add.add_argument("prompt")
    ln_item_add.add_argument(
        "--expected", help="the answer Archx can check exactly (omit to self-grade)"
    )
    ln_item_add.add_argument(
        "--hint",
        action="append",
        default=[],
        metavar="TEXT",
        help="a hint, ordered; repeat for the ladder",
    )
    ln_item_add.add_argument(
        "--explanation", help="shown after the attempt, right or wrong"
    )
    ln_item_add.add_argument("--subtopic")
    ln_item_list = ln_item_sub.add_parser(
        "list", help="items of a goal, with their schedule"
    )
    ln_item_list.add_argument("goal")
    ln_item_list.add_argument("--due", action="store_true", help="only what is due now")
    ln_item_list.add_argument(
        "--status", choices=["new", "learning", "review", "mastered"]
    )
    ln_item_edit = ln_item_sub.add_parser(
        "edit", help="change an item's question, answer key or hints"
    )
    ln_item_edit.add_argument("item")
    ln_item_edit.add_argument("--prompt", help="reword the question")
    ln_item_edit.add_argument("--expected", help="the answer Archx can check exactly")
    ln_item_edit.add_argument(
        "--hint",
        action="append",
        default=None,
        metavar="TEXT",
        help="replace the whole ladder; repeat for each rung, in order",
    )
    ln_item_edit.add_argument(
        "--add-hint",
        action="append",
        default=[],
        metavar="TEXT",
        help="append one rung to the end of the ladder",
    )
    ln_item_edit.add_argument(
        "--clear-hints", action="store_true", help="remove every hint"
    )
    ln_item_edit.add_argument(
        "--explanation", help="shown after the attempt, right or wrong"
    )
    ln_item_edit.add_argument("--subtopic")
    ln_item_del = ln_item_sub.add_parser("delete", help="delete one item")
    ln_item_del.add_argument("item")
    ln_item_del.add_argument("--yes", action="store_true")

    ln_plan = ln_sub.add_parser(
        "plan", help="propose items for a goal (checkpoints without a model)"
    )
    ln_plan.add_argument("goal")
    ln_plan.add_argument(
        "--no-model", action="store_true", help="use rule checkpoints only"
    )
    ln_plan.add_argument("--max", type=int, dest="max_items")
    ln_plan.add_argument("--model")
    ln_next = ln_sub.add_parser("next", help="what to study now, and why")
    ln_next.add_argument("goal")
    ln_ask = ln_sub.add_parser(
        "ask", help="the next question, with the answer and hints removed"
    )
    ln_ask.add_argument("goal")
    ln_hint = ln_sub.add_parser(
        "hint", help="reveal one hint (refused until you have tried)"
    )
    ln_hint.add_argument("item")
    ln_hint.add_argument("--level", type=int, default=1)
    ln_answer = ln_sub.add_parser(
        "answer", help="answer an item and see the grade and the new schedule"
    )
    ln_answer.add_argument("item")
    ln_answer.add_argument("answer")
    ln_answer.add_argument(
        "--self-rate", type=int, help="1-5, needed when the item has no expected answer"
    )
    ln_answer.add_argument(
        "--session", help="attach to a session (default: the open one, or a new one)"
    )
    ln_answer.add_argument(
        "--hints", type=int, default=0, help="how many hints you used"
    )

    ln_session = ln_sub.add_parser(
        "session", help="a sitting of practice, review or explanation"
    )
    ln_session_sub = ln_session.add_subparsers(
        dest="learning_session_command", required=True
    )
    ln_session_start = ln_session_sub.add_parser(
        "start", help="start a session on a goal"
    )
    ln_session_start.add_argument("goal")
    ln_session_start.add_argument(
        "--mode", choices=["practice", "review", "explain"], default="practice"
    )
    ln_session_list = ln_session_sub.add_parser("list", help="recent sessions")
    ln_session_list.add_argument("--goal")
    ln_session_list.add_argument("--limit", type=int, default=10)
    ln_session_end = ln_session_sub.add_parser(
        "end", help="close a session and summarise it"
    )
    ln_session_end.add_argument("session")

    ln_review = ln_sub.add_parser(
        "review", help="start a review session of everything due"
    )
    ln_review.add_argument("goal")
    ln_review.add_argument("--limit", type=int)
    ln_stats = ln_sub.add_parser("stats", help="progress counts")
    ln_stats.add_argument("goal", nargs="?")
    ln_search = ln_sub.add_parser("search", help="search goals and items")
    ln_search.add_argument("query")
    ln_search.add_argument("--limit", type=int, default=10)
    ln_report = ln_sub.add_parser(
        "report", help="print a progress report (and optionally write it)"
    )
    ln_report.add_argument("goal")
    ln_report.add_argument("--write", help="write the report here")
