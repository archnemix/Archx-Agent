# Agent workflows (M25)

A workflow is a **plan** the application executes step by step, with every step recorded.
There are two ways to get one:

* **user-directed** - you write (or pick a template for) the steps;
* **AI-directed** - a model proposes the steps, and you approve them before anything runs.

```bash
# user-directed
archx-agent agent run-file plan.json
archx-agent agent run-template summarise-file --input path=notes.txt

# AI-directed
archx-agent agent plan "summarise the notes and list the open questions"
archx-agent agent show wf_...          # read the plan
archx-agent agent run wf_... --approve # approve and run

archx-agent agent list
archx-agent agent steps wf_...
archx-agent agent stats
```

## The definition

JSON, deliberately small:

```json
{
  "name": "summarise-notes",
  "goal": "summarise notes.txt",
  "mode": "user",
  "steps": [
    {"kind": "tool", "title": "read", "tool": "fs.read", "args": {"path": "notes.txt"}},
    {"kind": "model", "title": "summarise", "prompt": "Summarise: {{step.1.output}}"},
    {"kind": "checkpoint", "title": "review", "text": "read the summary before continuing"},
    {"kind": "subagent", "title": "reviewer", "goal": "check the summary",
     "steps": [{"kind": "model", "prompt": "Check: {{goal}}"}]}
  ]
}
```

| kind | needs | does |
|------|-------|------|
| `model` | `prompt` | asks a model through the normal chat path (routing, budgets, tracing) |
| `tool` | `tool`, optional `args` | runs a registry tool - so the permission centre decides |
| `memory` | `query`, optional `limit` | searches the six memory systems, output is the hits |
| `note` | `text` | literal text, for stitching prompts together |
| `checkpoint` | optional `text` | a human gate; `--approve` is required before the run starts |
| `subagent` | `goal`, optional `steps` | a child task with its own conversation, returning its summary |

Unknown fields, unknown kinds and unknown template variables are **errors**. A definition
cannot invent a step type, and a plan that names a tool this machine does not have is refused
before anything is stored.

### Templates

`{{goal}}`, `{{step.N.output}}` (1-based), `{{input.NAME}}`, `{{workflow.id}}`, `{{task.id}}`.
An unknown name fails the step and names what was available instead of rendering empty.

## Safety

* A workflow **cannot grant anything.** Tool steps call `ToolManager`, which calls the
  permission centre; the first ungranted capability stops the run with an approval id. The
  acceptance run demonstrates exactly this: approving the *plan* does not approve `fs.write`.
* A model-proposed plan is stored as `proposed` and cannot run until `--approve` (or
  `agent approve`). Planning is itself recorded as a task.
* Checkpoints are checked **before** the run starts, so refusing at a gate can never leave
  half the steps executed and a re-run cannot repeat a side effect from an earlier attempt.
* Budgets: `agent.max_steps`, `agent.max_wall_seconds`, `agent.token_budget`,
  `agent.max_subagents`. They are checked between steps (the last point at which stopping is
  clean) and the failure names the budget.
* Subagents are child tasks with their own conversation, and nesting is limited to two
  levels. They use the same permission centre - a subagent is not more trusted than its
  parent.

## Records

Every run is a **task** (type `agent`) with a conversation, a timeline and resource use, and
every step is a `workflow_steps` row ordered by `seq` (nested steps get their own sequence,
so a subagent cannot collide with its parent's step numbers).

```
workflows        id, name, mode (user|ai), status, goal, definition, task_id, conversation_id
workflow_steps   workflow_id, seq, kind, spec, status, output, error, task_id, tokens
```

Statuses: `proposed` -> `approved` -> `running` -> `completed` | `failed` | `cancelled`.
A failed run is terminal; `agent rerun <id>` starts a **new** run of the same definition and
records `replaces` in its metadata, so the history is not rewritten and earlier side effects
are a visible, deliberate choice.

## Limits (honest list)

* Workflow steps execute sequentially. Scheduler admission, concurrency and job controls
  apply to queued jobs; they do not make arbitrary in-process workflow steps preemptible.
* No looping or conditional steps. A workflow plan is a fixed list; scenes and scheduling
  do not add a general "keep going until X" planner.
* A failed run is not resumed from the failing step - re-running repeats earlier steps.
* Model steps use the ordinary chat path, so a simulated test double is still simulated and
  reproduction records say so (M24).
* Token accounting uses what the runtime reports; a provider that reports nothing looks free.
