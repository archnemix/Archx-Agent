"""Agent workflows: a definition (data) plus ordered step records.

A workflow is *not* a program. It is JSON that names steps; the step kinds are fixed and
every step that can touch the machine goes through the tool registry, which means through
the permission centre. A workflow cannot grant itself a capability, cannot invent a tool,
and cannot widen a scope. That is the whole safety story, and it is why the definition
format is deliberately small.

Two modes:

``user``
    the user wrote (or picked) the steps; running it needs no model approval.
``ai``
    a model proposed the steps. The plan is stored as ``proposed`` and cannot run until a
    human approves it. The model is a planner, never an authority.

Step kinds:

``model``      ask a model a prompt (through the ordinary chat path, with its budgets)
``tool``       run a registry tool with arguments (rendered templates allowed)
``memory``     search the six memory systems and use the hits as the step output
``note``       a literal piece of text, useful for stitching prompts together
``checkpoint`` a human gate: the run refuses to pass it without explicit approval
``subagent``   a child task with its own conversation and steps, returning its summary

Public compatibility surface. Implementation responsibilities live in sibling modules.
"""

from .manager import WorkflowManager as WorkflowManager
from .constants import (
    WORKFLOW_TABLES as WORKFLOW_TABLES,
    STEP_KINDS as STEP_KINDS,
    MODES as MODES,
    STATUSES as STATUSES,
    TERMINAL as TERMINAL,
    MAX_DEPTH as MAX_DEPTH,
    _TEMPLATE_RE as _TEMPLATE_RE,
    _STEP_KEYS as _STEP_KEYS,
    TEMPLATES as TEMPLATES,
)
from .steps import (
    StepSpec as StepSpec,
    parse_step as parse_step,
    _limit as _limit,
    _text_or_none as _text_or_none,
    _default_title as _default_title,
    parse_steps as parse_steps,
    count_steps as count_steps,
    validate_definition as validate_definition,
    _walk as _walk,
)
from .records import (
    Workflow as Workflow,
    WorkflowStep as WorkflowStep,
    _workflow_from_row as _workflow_from_row,
    _step_from_row as _step_from_row,
)
from .rendering import (
    render as render,
    render_inputs as render_inputs,
    render_value as render_value,
)
from .matching import _terms as _terms


__all__ = [
    "MODES",
    "STEP_KINDS",
    "STATUSES",
    "StepSpec",
    "TEMPLATES",
    "WORKFLOW_TABLES",
    "Workflow",
    "WorkflowManager",
    "WorkflowStep",
    "count_steps",
    "parse_step",
    "parse_steps",
    "render",
    "render_inputs",
    "render_value",
    "validate_definition",
]
