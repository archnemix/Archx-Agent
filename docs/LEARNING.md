# Learning Mode (M30)

Learning Mode is a goal, a deck of items, a grade that says who graded it, and a schedule
that explains itself. It is built on the same managers as everything else: a learning goal
is a row, a session is a task, a plan is a proposal with a named author.

The design constraint is that a tutor is the easiest place in this app to lie. "Great job,
you understand it now" is unfalsifiable and free to say. The module refuses that in four
specific places, and each refusal is visible in the output.

## 1. The record

Five tables (v19 adds two of them to the v8 learning tables):

| table | what a row is |
|-------|---------------|
| `learning_goals` | a goal: title, objective, level, success criteria, status, `planned_by` |
| `learning_lessons` | an **item**: the question (`topic`), expected answer, hint ladder, explanation, position, and its own schedule (status, ease, interval, streak, lapses, due date, counts) |
| `learning_sessions` | one sitting: goal, mode (`practice`/`review`/`explain`), status, counts, the task it belongs to |
| `learning_attempts` | one answer: text, correct, `graded_by`, self rating, hints used, feedback, the interval and due date it produced |
| `learning_events` | the v8 event log, still the audit trail |

Every write is a coordinator operation, so a crash between the attempt row and the item's
new schedule cannot leave them disagreeing. Deleting a goal deletes its items, sessions and
attempts in the same operation.

## 2. Grading: two ways, both honest

`grade_answer()` has exactly two paths.

* **`expected` set** → normalised comparison (`normalise()`: lower-cased, punctuation to
  spaces, whitespace collapsed). An exact match and a "every term of the expected answer
  appears in yours" match both grade correct; the record says `graded_by = "exact"` and the
  feedback says which rule fired.
* **`expected` absent** → the learner rates 1–5, `>= 3` counts as known, and the record says
  `graded_by = "self"` with the sentence *"Archx did not check the answer."*

There is no model in either path. A model grading free text would be a claim the app cannot
verify and cannot reproduce, so it is not offered. An item with neither an expected answer
nor a rating is a `ValidationError`, not a guess.

## 3. Hints: a ladder you have to climb

* Hints are ordered. `--hint` can be repeated; `learning item edit --hint` replaces the
  ladder, `--add-hint` appends one rung, `--clear-hints` removes them. The ladder is capped
  by `learning.max_hints` (5) in both `add_item` and `update_item` — a ladder that long is
  the answer.
* `learning.try_first` (on by default) refuses any hint for an item with **no attempts**.
  The CLI exits **3** and prints the refusal plus the exact `learning answer` command that
  opens the ladder; the GUI answers **409** `try_first`.
* Revealing is per level: `learning hint <item> --level 2` shows rungs 1–2. Asking for a
  level past the end is a `ValidationError` that names the range.

## 4. The schedule: SM-2-lite, spelled out

`LearningService.schedule()` is a pure function of the item and whether the answer was
correct. It returns *and stores* every number, plus a sentence explaining it:

| outcome | interval | ease | streak | status | due |
|---------|----------|------|--------|--------|-----|
| correct, streak 1 | 1 day | +0.1 (cap 3.0) | 1 | `review` | tomorrow |
| correct, streak 2 | 3 days | +0.1 | 2 | `review` | +3 days |
| correct, streak ≥ 3 | `max(interval, 1) × ease` | +0.1 | n+1 | `review` | +interval |
| mastered | — | — | ≥ `learning.mastery_streak` (4) **and** interval ≥ 14 | `mastered` | +interval |
| wrong | 0 | −0.2 (floor `learning.min_ease` 1.3) | 0 | `learning` | **now** |

A wrong answer comes back immediately — that is the point of a lapse — and mastery needs
both a streak and a real interval, so four lucky guesses a minute apart do not master an
item. The new values are stored on the item and the attempt row keeps the interval it
produced, so the history of "what did Archx think of this item on that day" is intact.

## 5. Choosing what to study

`learning next <goal>` returns the item, the goal, a `why` ("new: it has never been
attempted" / "due for review: it was seen before and its interval has elapsed"), the due
count and the review limit. Ordering is: something already seen and due first, then new
material, then the plan's position. If nothing is due it is not an error — it is
`NothingToStudy`, exit **3**, naming the next due date and the two commands that would add
work. `learning ask` is the same payload with the answer, hints and explanation removed, so
it can be shown without leaking the deck.

`learning review <goal> --limit` starts a **review session** over what is due right now and
queues it; with nothing due it exits 3 instead of opening an empty sitting.

## 6. Sessions are tasks

`learning session start <goal> --mode review` creates a `learning` task, records the
session against it, and queues what is due. `session end` closes it and writes the summary
("review session: 3 answered, 2 correct, 1 hint(s)") onto the row. Answering without a
session still belongs to one: `_auto_session()` opens a practice session for today rather
than recording an unattributed attempt. A session whose task is still `running` shows in
the Tasks panel like any other work.

## 7. Plans: rules first, model second

`learning plan <goal>` proposes items and stores them with `source = planned_by`.

* **`--no-model`** (or no usable model): checkpoints derived from **your own goal words** —
  "Can you show this: &lt;criterion&gt;?", "Explain in your own words: &lt;objective&gt;" — never
  invented facts, and never with an `expected` answer. `planned_by = "rules"` and the `why`
  says the plan is yours to edit.
* **With a model:** the model is asked for JSON items; every field is validated, unparseable
  or empty plans fall back to the checkpoints with the failure named in `why`. This is the
  same policy as Researcher Mode's plan: a proposal that says who wrote it.

## 8. Reporting and completion

`learning stats` counts goals, items, due, attempts, correct, mastered, sessions, per-status
counts and accuracy. `learning report <goal> [--write FILE]` renders a markdown record: the
goal, its criteria, what is scheduled next, recent sessions, the last attempts, and a
section explaining how the record is graded (so a printed report cannot imply a model judged
it).

Completion is **explicit**: `learning goal complete <goal> --note "..."` records who decided
("your call against your criteria"). Neither a full streak nor a full deck completes a goal;
`test_an_answer_cannot_mark_a_goal_complete` is the guard.

## 9. CLI

```
learning goal   create|list|show|edit|complete|delete
learning item   add|list|edit|delete
learning plan   <goal> [--no-model] [--max N] [--model ID]
learning next   <goal>              # what now, and why
learning ask    <goal>              # the question without the answer
learning hint   <item> [--level N]  # 3 until the item has been attempted
learning answer <item> "..." [--self-rate 1-5] [--session ID] [--hints N]
learning session start|list|end     # a sitting, as a task
learning review <goal> [--limit N]  # a review session of everything due
learning stats  [goal]
learning search <query>
learning report <goal> [--write FILE]
```

## 10. GUI

The **Learning** tab lists goals (with item/due counts), and for the selected goal shows:
the criteria, a **Add an item** form (question, expected answer, one hint per line), the
**next up** card with the `why`, a hint button that reveals one rung per click (409
`try_first` before an attempt is shown as a refusal, not an error dialog), an answer form
that posts to the same service as the CLI, the item table with status/due/streak/interval,
the sessions, and buttons for "Propose items (no model)" and "Start a review of what is
due". Creating a goal, adding an item and answering in the browser produce rows the CLI
shows immediately — the acceptance script checks both directions.

## 11. Config

| key | default | meaning |
|-----|---------|---------|
| `learning.active_goal_limit` | 5 | a sixth active goal is refused, not silently created |
| `learning.try_first` | true | hints are refused before the first attempt |
| `learning.daily_review_limit` | 20 | how many due items a review queues |
| `learning.max_hints` | 5 | ladder length cap |
| `learning.mastery_streak` | 4 | consecutive correct answers needed for `mastered` |
| `learning.start_ease` | 2.5 | ease for a new item |
| `learning.min_ease` | 1.3 | floor for ease after lapses |
| `learning.max_plan_items` | 8 | items a plan will create |

## 12. What it does not do

* No model-graded free text, by design (see §2). Prose answers are self-rated.
* No multiple choice, images, audio or generated exercises: an item is a question, an
  optional answer key and a ladder. M34 (voice/multimodal) is where richer media belongs.
* No cross-goal curriculum, no exam mode, no streaks/rewards. The schedule is per item.
* `learning search` is the unified keyword search over goals and items; it is not a
  semantic search over the deck.
* The GUI cannot delete a goal or an item (the CLI can, with `--yes`); the page only adds.
