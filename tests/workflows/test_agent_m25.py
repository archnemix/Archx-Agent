"""M25: agent workflows (user-directed and model-proposed) with subagents.

Built in the order the milestone was built: the definition format and its refusals, then
template rendering, then execution of each step kind, then budgets/cancellation, then the
planner (a real HTTP round trip against the protocol stub), then the console script.
"""

from __future__ import annotations

from tests.paths import REPO_ROOT

import json
import os
import subprocess
import sys

import socket

import pytest

from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from archx_agent.managers.workflows import (
    STEP_KINDS,
    TEMPLATES,
    count_steps,
    parse_steps,
    render,
    render_inputs,
    render_value,
    validate_definition,
)

CLI = os.path.join(os.path.dirname(sys.executable), "archx-agent")


@pytest.fixture()
def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHX_ALLOW_SIMULATED", "1")
    with open_workspace(home=str(tmp_path / "home"), env={}) as workspace:
        yield workspace


@pytest.fixture()
def model(ws):
    record = ws.models.register_remote(
        "sim", provider="test-double", runtime="scripted", model_ref="simulated",
        capabilities=["chat"],
    )
    # The test double echoes; give it a script so model output is recognisable.
    runtime = ws.runtime_for(record)
    runtime.script = {"summari": "SUMMARY: the file mentions alpha.", "check": "CHECKED: fine."}
    return record


def _grant(ws, capability, subject):
    return ws.permissions.grant(capability, subject=subject, duration="persistent", confirm=True)


def _read_tool(ws, name="notes.txt", text="alpha beta\n"):
    root = ws.tool_roots()[0]
    with open(os.path.join(root, name), "w", encoding="utf-8") as handle:
        handle.write(text)
    _grant(ws, "fs.read", "fs.read")
    return name


def _definition(**overrides):
    base = {
        "name": "demo",
        "goal": "do the thing",
        "steps": [{"kind": "note", "title": "start", "text": "hello"}],
    }
    base.update(overrides)
    return base


def _run(ws, definition, *, approve=False, status="approved"):
    workflow = ws.workflows.create(definition, status=status)
    return workflow, ws.agent.run(workflow.id, approve=approve)


# --------------------------------------------------------------------------
# definition format
# --------------------------------------------------------------------------
class TestDefinitionValidation:
    def test_minimal_definition_is_normalised(self, ws):
        definition = validate_definition(_definition())
        assert definition["mode"] == "user"
        assert definition["steps"][0]["kind"] == "note"
        assert definition["steps"][0]["title"] == "start"

    def test_every_kind_is_recognised(self):
        assert set(STEP_KINDS) == {"model", "tool", "memory", "note", "checkpoint", "subagent"}

    def test_unknown_workflow_field_is_rejected(self, ws):
        with pytest.raises(ValidationError) as exc:
            validate_definition(_definition(surprise=1))
        assert "surprise" in exc.value.message

    def test_name_is_required(self, ws):
        with pytest.raises(ValidationError):
            validate_definition(_definition(name="  "))

    def test_name_length_is_bounded(self, ws):
        with pytest.raises(ValidationError):
            validate_definition(_definition(name="x" * 121))

    def test_unknown_mode_is_rejected(self, ws):
        with pytest.raises(ValidationError) as exc:
            validate_definition(_definition(mode="autonomous"))
        assert "user" in exc.value.message and "ai" in exc.value.message

    def test_steps_are_required(self, ws):
        with pytest.raises(ValidationError):
            validate_definition(_definition(steps=[]))

    def test_unknown_step_kind_is_rejected(self, ws):
        with pytest.raises(ValidationError) as exc:
            validate_definition(_definition(steps=[{"kind": "shell"}]))
        assert "shell" in exc.value.message

    @pytest.mark.parametrize(
        "step, need",
        [
            ({"kind": "model"}, "prompt"),
            ({"kind": "tool"}, "tool name"),
            ({"kind": "memory"}, "query"),
            ({"kind": "note"}, "text"),
            ({"kind": "subagent"}, "goal"),
        ],
    )
    def test_each_kind_requires_its_input(self, ws, step, need):
        with pytest.raises(ValidationError) as exc:
            validate_definition(_definition(steps=[step]))
        assert need in exc.value.message

    def test_unknown_step_field_is_rejected(self, ws):
        with pytest.raises(ValidationError) as exc:
            validate_definition(_definition(steps=[{"kind": "note", "text": "x", "shell": "rm"}]))
        assert "shell" in exc.value.message

    def test_nested_steps_only_belong_to_subagents(self, ws):
        with pytest.raises(ValidationError):
            validate_definition(
                _definition(steps=[{"kind": "note", "text": "x", "steps": [{"kind": "note", "text": "y"}]}])
            )

    def test_args_must_be_an_object(self, ws):
        with pytest.raises(ValidationError):
            validate_definition(_definition(steps=[{"kind": "tool", "tool": "archx.info", "args": [1]}]))

    def test_metadata_must_be_an_object(self, ws):
        with pytest.raises(ValidationError):
            validate_definition(_definition(metadata=[1]))

    def test_tool_must_exist_in_the_registry(self, ws):
        with pytest.raises(ValidationError) as exc:
            validate_definition(
                _definition(steps=[{"kind": "tool", "tool": "nope.nope"}]),
                tools=ws.tools,
            )
        assert "nope.nope" in exc.value.message

    def test_step_cap_is_enforced(self, ws):
        steps = [{"kind": "note", "text": "x"} for _ in range(4)]
        with pytest.raises(ValidationError) as exc:
            validate_definition(_definition(steps=steps), max_steps=3)
        assert "agent.max_steps" in exc.value.message

    def test_nested_steps_count_towards_the_cap(self, ws):
        steps = [
            {"kind": "subagent", "goal": "g", "steps": [{"kind": "note", "text": "a"}]},
            {"kind": "note", "text": "b"},
        ]
        parsed = parse_steps(steps)
        assert count_steps(parsed) == 3

    def test_memory_limit_bounds(self, ws):
        with pytest.raises(ValidationError):
            validate_definition(_definition(steps=[{"kind": "memory", "query": "x", "limit": 0}]))

    def test_titles_are_derived_when_missing(self, ws):
        definition = validate_definition(
            _definition(steps=[{"kind": "tool", "tool": "archx.info", "args": {}}])
        )
        assert definition["steps"][0]["title"] == "archx.info"


# --------------------------------------------------------------------------
# templating
# --------------------------------------------------------------------------
class TestRendering:
    def test_render_substitutes_known_values(self):
        context = {"goal": "ship it", "step.1.output": '{"a": 1}'}
        assert render("goal={{goal}} out={{step.1.output}}", context) == 'goal=ship it out={"a": 1}'

    def test_unknown_variable_is_an_error_listing_what_exists(self):
        with pytest.raises(ValidationError) as exc:
            render("{{step.9.output}}", {"goal": "x"})
        assert "step.9.output" in exc.value.message and "goal" in exc.value.message

    def test_render_value_walks_containers(self):
        context = {"goal": "g"}
        rendered = render_value({"a": "{{goal}}", "b": ["{{goal}}", 3]}, context)
        assert rendered == {"a": "g", "b": ["g", 3]}

    def test_render_inputs_leaves_run_time_placeholders_alone(self):
        definition = {"steps": [{"kind": "model", "prompt": "{{input.topic}} then {{step.1.output}}"}]}
        rendered = render_inputs(definition, {"topic": "databases"})
        assert rendered["steps"][0]["prompt"] == "databases then {{step.1.output}}"

    def test_missing_input_is_named(self):
        with pytest.raises(ValidationError) as exc:
            render_inputs({"prompt": "{{input.path}}"}, {})
        assert "--input path" in exc.value.message

    def test_templates_are_valid_definitions(self, ws):
        for name, definition in TEMPLATES.items():
            normalised = validate_definition(definition, tools=ws.tools)
            assert normalised["name"] == name


# --------------------------------------------------------------------------
# execution
# --------------------------------------------------------------------------
class TestUserDirectedRun:
    def test_model_and_note_steps_complete_and_are_recorded(self, ws, model):
        workflow, result = _run(ws, {
            "name": "talk",
            "goal": "say something",
            "steps": [
                {"kind": "model", "title": "ask", "prompt": "summarise the plan"},
                {"kind": "note", "title": "extra", "text": "done"},
            ],
        })
        assert result.status == "completed"
        assert [step["kind"] for step in result.steps] == ["model", "note"]
        assert [step["status"] for step in result.steps] == ["succeeded", "succeeded"]
        assert result.tokens > 0
        task = ws.tasks.get(result.task_id)
        assert task.status == "completed"
        assert task.metadata["workflow_id"] == workflow.id
        run = ws.workflows.get(workflow.id)
        assert run.status == "completed" and run.started_at and run.finished_at
        kinds = [row["kind"] for row in ws.tasks.timeline(task.id)]
        assert kinds[-1] == "completed"
        assert "workflow_completed" in kinds and kinds.index("workflow_completed") < kinds.index("completed")

    def test_a_conversation_holds_the_workflow_transcript(self, ws, model):
        workflow, result = _run(ws, {
            "name": "talk", "goal": "g",
            "steps": [{"kind": "model", "prompt": "summarise this"}],
        })
        conversation = ws.conversations.require(ws.workflows.get(workflow.id).conversation_id)
        messages = ws.conversations.messages(conversation.id)
        assert len(messages) == 2
        assert messages[0].role == "user" and "summarise" in messages[0].content

    def test_tool_step_runs_through_the_permission_centre(self, ws):
        name = _read_tool(ws)
        workflow, result = _run(ws, {
            "name": "read", "goal": "g",
            "steps": [{"kind": "tool", "tool": "fs.read", "args": {"path": name}}],
        })
        assert result.status == "completed"
        assert "alpha beta" in result.summary
        assert ws.tools.runs(tool="fs.read")[0]["task_id"] == result.task_id

    def test_a_denied_tool_fails_the_run_with_an_approval(self, ws):
        root = ws.tool_roots()[0]
        with open(os.path.join(root, "x.txt"), "w") as handle:
            handle.write("x")
        workflow = ws.workflows.create({
            "name": "read", "goal": "g",
            "steps": [{"kind": "tool", "tool": "fs.read", "args": {"path": "x.txt"}}],
        })
        with pytest.raises(ApprovalRequiredError) as exc:
            ws.agent.run(workflow.id)
        approval_id = exc.value.approval_id
        assert approval_id and approval_id.startswith("ap_")
        assert ws.workflows.get(workflow.id).status == "failed"
        failed = ws.tasks.list(kind="agent")[0]
        assert failed.status == "failed"
        step = ws.workflows.steps(workflow.id)[0]
        assert step.status == "failed" and step.metadata["approval_id"] == approval_id

        # The run is terminal, but the definition is not lost: a *new* run is explicit.
        ws.permissions.approve(approval_id)
        again = ws.workflows.create(workflow.definition, status="approved")
        result = ws.agent.run(again.id)
        assert result.status == "completed"

    def test_continue_on_error_keeps_going(self, ws):
        root = ws.tool_roots()[0]
        with open(os.path.join(root, "x.txt"), "w") as handle:
            handle.write("x")
        workflow, result = _run(ws, {
            "name": "tolerant", "goal": "g",
            "steps": [
                {"kind": "tool", "tool": "fs.read", "args": {"path": "x.txt"},
                 "continue_on_error": True},
                {"kind": "note", "text": "after the failure"},
            ],
        })
        assert result.status == "completed"
        assert result.steps[0]["status"] == "failed"
        assert result.steps[1]["status"] == "succeeded"
        assert result.summary == "after the failure"
        assert result.approval_id is None

    def test_memory_step_reads_the_memory_systems(self, ws):
        project = ws.projects.create("deploy")
        ws.memory.add("project", "Deploy checklist", "run the migrations first",
                      category="fact", project_id=project.id).ok_or_raise()
        workflow, result = _run(ws, {
            "name": "recall", "goal": "g",
            "steps": [{"kind": "memory", "query": "migrations", "limit": 3}],
        })
        assert result.status == "completed"
        assert "Deploy checklist" in result.summary
        assert result.steps[0]["metadata"]["hits"] >= 1

    def test_subagent_is_a_child_task_with_its_own_conversation(self, ws, model):
        workflow, result = _run(ws, {
            "name": "delegate", "goal": "g",
            "steps": [{
                "kind": "subagent", "title": "expert", "goal": "check the summary",
                "steps": [{"kind": "model", "prompt": "check this summary"}],
            }],
        })
        assert result.status == "completed"
        child = ws.tasks.children(result.task_id)[0]
        assert child.title == "subagent: expert"
        assert child.status == "completed"
        assert child.conversation_id and child.conversation_id != ws.workflows.get(workflow.id).conversation_id
        assert result.steps[0]["metadata"]["child_task_id"] == child.id
        assert result.steps[0]["metadata"]["subagent"] is True

    def test_subagent_nesting_is_limited(self, ws, model):
        from archx_agent.application.agent import WorkflowFailed

        with pytest.raises(WorkflowFailed) as exc:
            _run(ws, {
                "name": "deep", "goal": "g",
                "steps": [{"kind": "subagent", "goal": "a", "steps": [
                    {"kind": "subagent", "goal": "b", "steps": [
                        {"kind": "subagent", "goal": "c", "steps": [{"kind": "note", "text": "x"}]},
                    ]},
                ]}],
            })
        assert "two levels" in exc.value.message
        workflow = ws.workflows.list()[0]
        assert workflow.status == "failed"
        assert "two levels" in (workflow.error or "")

    def test_checkpoint_refuses_before_anything_runs(self, ws, model):
        workflow = ws.workflows.create({
            "name": "gated", "goal": "g",
            "steps": [
                {"kind": "note", "text": "before"},
                {"kind": "checkpoint", "text": "review this"},
                {"kind": "note", "text": "after"},
            ],
        })
        with pytest.raises(ApprovalRequiredError) as exc:
            ws.agent.run(workflow.id)
        assert "checkpoint" in exc.value.message
        # Nothing ran and nothing was recorded as a step.
        assert ws.workflows.steps(workflow.id) == []
        assert ws.workflows.get(workflow.id).status == "approved"

        result = ws.agent.run(workflow.id, approve=True)
        assert result.status == "completed"
        assert "checkpoint 2 approved" in result.steps[1]["output"]

    def test_a_finished_workflow_cannot_run_twice(self, ws):
        workflow, _ = _run(ws, _definition())
        with pytest.raises(ConflictError):
            ws.agent.run(workflow.id)

    def test_unknown_workflow_reference(self, ws):
        with pytest.raises(NotFoundError):
            ws.agent.run("wf_missing")

    def test_workflow_can_be_found_by_name(self, ws):
        workflow, _ = _run(ws, _definition(name="by name"))
        assert ws.workflows.require("by name").id == workflow.id
        with pytest.raises(ConflictError):
            ws.agent.run("by name")

    def test_stats_and_listing(self, ws):
        _run(ws, _definition(name="one"))
        workflow = ws.workflows.create(_definition(name="two"), status="proposed")
        assert [w.name for w in ws.workflows.list(mode="user")] == ["two", "one"]
        assert ws.workflows.list(status="proposed")[0].id == workflow.id
        stats = ws.workflows.stats()
        assert stats["total"] == 2 and stats["steps"] >= 1
        with pytest.raises(ValidationError):
            ws.workflows.list(status="nonsense")


class TestBudgetsAndCancellation:
    def test_step_budget_stops_before_exceeding(self, ws):
        workflow = ws.workflows.create({
            "name": "long", "goal": "g",
            "steps": [{"kind": "note", "text": str(i)} for i in range(4)],
        })
        ws.config.set("agent.max_steps", 2)
        from archx_agent.application.agent import WorkflowFailed

        with pytest.raises(WorkflowFailed) as exc:
            ws.agent.run(workflow.id)
        assert "agent.max_steps" in exc.value.message
        assert ws.workflows.get(workflow.id).status == "failed"
        assert len(ws.workflows.steps(workflow.id)) == 2

    def test_wall_clock_budget_is_checked_before_a_step(self, ws):
        workflow = ws.workflows.create(_definition())
        ws.config.set("agent.max_wall_seconds", 10)
        # Simulate a run that took too long by moving the budget's start backwards.
        from archx_agent.application import agent as agent_module

        original = agent_module.Budget

        class SlowBudget(original):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.started -= 1000

        agent_module.Budget = SlowBudget
        from archx_agent.application.agent import WorkflowFailed

        try:
            with pytest.raises(WorkflowFailed) as exc:
                ws.agent.run(workflow.id)
        finally:
            agent_module.Budget = original
        assert "agent.max_wall_seconds" in exc.value.message

    def test_token_budget_stops_a_runaway_workflow(self, ws, model):
        long_prompt = "word " * 120
        workflow = ws.workflows.create({
            "name": "chatty", "goal": "g",
            "steps": [{"kind": "model", "prompt": f"step {i} {long_prompt}"} for i in range(15)],
        })
        ws.config.set("agent.token_budget", 1000)
        from archx_agent.application.agent import WorkflowFailed

        with pytest.raises(WorkflowFailed) as exc:
            ws.agent.run(workflow.id)
        assert "token_budget" in exc.value.message

    def test_a_cancel_from_inside_a_step_stops_the_run(self, ws):
        from archx_agent.managers.tools import ToolSpec

        holder = {}

        def cancel(_args):
            ws.workflows.cancel(holder["id"], reason="cancelled by the step")
            return {"cancelled": True}

        ws.tools.declare_spec(
            ToolSpec(name="demo.cancel", summary="cancel the workflow", capability=None,
                     risk="low", inputs={}, builtin=False, origin="test"),
            cancel,
        )
        workflow = ws.workflows.create({
            "name": "self-cancel", "goal": "g",
            "steps": [
                {"kind": "tool", "tool": "demo.cancel", "args": {}},
                {"kind": "note", "text": "should not run"},
            ],
        })
        holder["id"] = workflow.id
        result = ws.agent.run(workflow.id)
        assert result.cancelled is True and result.status == "cancelled"
        assert ws.workflows.get(workflow.id).status == "cancelled"
        assert ws.tasks.get(result.task_id).status == "cancelled"
        assert len(ws.workflows.steps(workflow.id)) == 1

    def test_cancelling_before_a_run_prevents_it(self, ws):
        workflow = ws.workflows.create(_definition())
        ws.workflows.cancel(workflow.id)
        with pytest.raises(ConflictError):
            ws.agent.run(workflow.id)

    def test_reject_and_cancel_are_terminal(self, ws):
        proposed = ws.workflows.create(_definition(), status="proposed")
        rejected = ws.workflows.reject(proposed.id, reason="not useful")
        assert rejected.status == "cancelled"
        with pytest.raises(ConflictError):
            ws.workflows.approve(proposed.id)
        with pytest.raises(ConflictError):
            ws.workflows.cancel(proposed.id)

    def test_approving_a_non_proposed_workflow_is_a_conflict(self, ws):
        workflow = ws.workflows.create(_definition(), status="approved")
        with pytest.raises(ConflictError):
            ws.workflows.approve(workflow.id)


# --------------------------------------------------------------------------
# the planner
# --------------------------------------------------------------------------
PLAN = {
    "name": "inspect",
    "goal": "inspect the workspace",
    "steps": [
        {"kind": "tool", "title": "facts", "tool": "archx.info", "args": {}},
        {"kind": "model", "title": "report", "prompt": "report from {{step.1.output}}"},
    ],
}


def _plan_payload(plan: dict | str) -> dict:
    text = plan if isinstance(plan, str) else json.dumps(plan)
    return {
        "id": "chatcmpl-1", "model": "stub-model",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }


class TestPlanner:
    def _http_model(self, ws, base):
        return ws.models.register_remote(
            "planner", provider="local-http", runtime="openai-http", model_ref="stub-model",
            base_url=f"{base}/v1", capabilities=["chat"],
        )

    def test_a_proposed_plan_cannot_run_without_approval(self, ws, stub_server):
        base, handler = stub_server
        handler.routes["POST /v1/chat/completions"] = (200, _plan_payload(PLAN))
        model = self._http_model(ws, base)
        workflow = ws.agent.plan("inspect the workspace", model_id=model.id)
        assert workflow.mode == "ai" and workflow.status == "proposed"
        assert [step.kind for step in workflow.steps] == ["tool", "model"]
        assert ws.workflows.get(workflow.id).metadata["plan_task_id"]

        with pytest.raises(ApprovalRequiredError):
            ws.agent.run(workflow.id)

        result = ws.agent.run(workflow.id, approve=True)
        assert result.status == "completed"
        assert ws.workflows.get(workflow.id).metadata["approved_by"]

    def test_prose_around_the_json_is_tolerated(self, ws, stub_server):
        base, handler = stub_server
        handler.routes["POST /v1/chat/completions"] = (
            200, _plan_payload("Here is the plan you asked for:\n" + json.dumps(PLAN) + "\nGood luck.")
        )
        model = self._http_model(ws, base)
        workflow = ws.agent.plan("do it", model_id=model.id)
        assert len(workflow.steps) == 2

    def test_a_reply_without_json_stores_nothing(self, ws, stub_server):
        base, handler = stub_server
        handler.routes["POST /v1/chat/completions"] = (200, _plan_payload("I would rather chat."))
        model = self._http_model(ws, base)
        with pytest.raises(ValidationError) as exc:
            ws.agent.plan("do it", model_id=model.id)
        assert "no JSON object" in exc.value.message
        assert ws.workflows.stats()["total"] == 0
        assert ws.tasks.list(kind="agent")[0].status == "failed"

    def test_a_plan_naming_a_missing_tool_is_refused(self, ws, stub_server):
        base, handler = stub_server
        bad = {"name": "bad", "goal": "g",
               "steps": [{"kind": "tool", "tool": "shell.rm_rf", "args": {}}]}
        handler.routes["POST /v1/chat/completions"] = (200, _plan_payload(bad))
        model = self._http_model(ws, base)
        with pytest.raises(ValidationError) as exc:
            ws.agent.plan("do it", model_id=model.id)
        assert "shell.rm_rf" in exc.value.message
        assert ws.workflows.stats()["total"] == 0

    def test_a_plan_cannot_widen_permissions(self, ws, stub_server):
        """A plan may name a protected tool; the *run* still needs the grant."""
        base, handler = stub_server
        plan = {"name": "write", "goal": "g",
                "steps": [{"kind": "tool", "tool": "fs.write",
                           "args": {"path": "x.txt", "content": "y"}}]}
        handler.routes["POST /v1/chat/completions"] = (200, _plan_payload(plan))
        model = self._http_model(ws, base)
        workflow = ws.agent.plan("write a file", model_id=model.id)
        with pytest.raises(ApprovalRequiredError) as exc:
            ws.agent.run(workflow.id, approve=True)
        assert exc.value.approval_id
        # Approving the plan did not approve the capability.
        assert ws.permissions.grants(capability="fs.write") == []
        assert ws.tools.runs(tool="fs.write")[0]["status"] == "denied"

    def test_an_empty_goal_is_refused(self, ws):
        with pytest.raises(ValidationError):
            ws.agent.plan("   ")


# --------------------------------------------------------------------------
# the installed console script
# --------------------------------------------------------------------------
def _cli(home, *args, timeout=180):
    env = dict(os.environ)
    env.pop("ARCHX_PATHS_HOME", None)
    env["ARCHX_ALLOW_SIMULATED"] = "1"
    return subprocess.run(
        [CLI, "--home", home, *args], capture_output=True, text=True, env=env, timeout=timeout
    )


def _home(tmp_path) -> str:
    home = str(tmp_path / "cli-home")
    assert _cli(home, "init").returncode == 0
    return home


class TestCliAgent:
    def test_run_file_end_to_end(self, tmp_path):
        home = _home(tmp_path)
        assert _cli(home, "models", "add-scripted", "--name", "sim").returncode == 0
        root = os.path.join(home, "workspace")
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, "notes.txt"), "w") as handle:
            handle.write("alpha beta\n")
        assert _cli(home, "permissions", "grant", "fs.read", "--subject", "fs.read",
                    "--duration", "persistent", "--confirm").returncode == 0
        definition = {
            "name": "cli-run", "goal": "read and summarise",
            "steps": [
                {"kind": "tool", "tool": "fs.read", "args": {"path": "notes.txt"}},
                {"kind": "model", "prompt": "summarise {{step.1.output}}"},
            ],
        }
        path = tmp_path / "workflow.json"
        path.write_text(json.dumps(definition))
        result = _cli(home, "agent", "run-file", str(path), "--json")
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "completed"
        assert len(payload["steps"]) == 2
        listed = json.loads(_cli(home, "agent", "list", "--json").stdout)
        assert listed[0]["name"] == "cli-run"
        shown = json.loads(_cli(home, "agent", "show", listed[0]["id"], "--json").stdout)
        assert shown["status"] == "completed"
        assert len(shown["steps"]) == 2
        assert _cli(home, "agent", "show", shown["id"]).returncode == 0
        assert _cli(home, "agent", "stats", "--json").returncode == 0

    def test_run_file_rejects_broken_json(self, tmp_path):
        home = _home(tmp_path)
        path = tmp_path / "bad.json"
        path.write_text("{not json")
        result = _cli(home, "agent", "run-file", str(path))
        assert result.returncode == 2
        assert "not valid JSON" in result.stderr

    def test_checkpoint_exits_with_approval_required(self, tmp_path):
        home = _home(tmp_path)
        path = tmp_path / "gated.json"
        path.write_text(json.dumps({
            "name": "gated", "goal": "g",
            "steps": [
                {"kind": "checkpoint", "text": "look first"},
                {"kind": "note", "text": "after"},
            ],
        }))
        blocked = _cli(home, "agent", "run-file", str(path))
        assert blocked.returncode == 4
        assert "approval required" in blocked.stderr
        approved = _cli(home, "agent", "run-file", str(path), "--approve", "--json")
        assert approved.returncode == 0, approved.stderr
        assert json.loads(approved.stdout)["status"] == "completed"

    def test_plan_requires_approval_and_then_runs(self, tmp_path, free_port):
        home = _home(tmp_path)
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(json.dumps(PLAN))
        stub = subprocess.Popen(
            [sys.executable, "scripts/openai_protocol_stub.py", "--port", str(free_port),
             "--reply-file", str(plan_file)],
            cwd=str(REPO_ROOT),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            import time
            import urllib.request

            for _ in range(100):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{free_port}/v1/models", timeout=1)
                    break
                except Exception:
                    time.sleep(0.1)
            added = _cli(home, "models", "add-http", "--name", "planner",
                         "--base-url", f"http://127.0.0.1:{free_port}/v1",
                         "--provider", "local-http", "--model", "protocol-stub")
            assert added.returncode == 0, added.stderr
            planned = _cli(home, "agent", "plan", "inspect the workspace", "--json")
            assert planned.returncode == 0, planned.stderr
            workflow = json.loads(planned.stdout)
            assert workflow["status"] == "proposed" and workflow["mode"] == "ai"
            blocked = _cli(home, "agent", "run", workflow["id"])
            assert blocked.returncode == 4
            ran = _cli(home, "agent", "run", workflow["id"], "--approve", "--json")
            assert ran.returncode == 0, ran.stderr
            assert json.loads(ran.stdout)["status"] == "completed"
        finally:
            stub.kill()
            stub.wait(timeout=10)

    def test_templates_and_template_run(self, tmp_path):
        home = _home(tmp_path)
        listed = json.loads(_cli(home, "agent", "templates", "--json").stdout)
        names = {row["name"] for row in listed}
        assert {"summarise-file", "check-and-report"} <= names
        root = os.path.join(home, "workspace")
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, "notes.txt"), "w") as handle:
            handle.write("alpha beta\n")
        assert _cli(home, "permissions", "grant", "fs.read", "--subject", "fs.read",
                    "--duration", "persistent", "--confirm").returncode == 0
        assert _cli(home, "models", "add-scripted", "--name", "sim").returncode == 0
        result = _cli(home, "agent", "run-template", "summarise-file",
                      "--input", "path=notes.txt", "--json")
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["status"] == "completed"
        missing_input = _cli(home, "agent", "run-template", "summarise-file")
        assert missing_input.returncode == 2
        assert "input path" in missing_input.stderr

    def test_approve_and_reject_commands(self, tmp_path):
        home = _home(tmp_path)
        home_db = os.path.join(home, "archx.db")
        assert os.path.exists(home_db)
        # A proposed workflow has to come from a model, so seed one with a tiny script.
        script = tmp_path / "seed.py"
        script.write_text(
            "import json, sys\n"
            "from archx_agent.application.workspace import Workspace\n"
            "ws = Workspace.open(home=sys.argv[1], env={}, allow_test_double=True)\n"
            "wf = ws.workflows.create({'name': 'seeded', 'goal': 'g', 'steps': "
            "[{'kind': 'note', 'text': 'x'}]}, status='proposed')\n"
            "print(wf.id)\n"
            "ws.close()\n"
        )
        env = dict(os.environ)
        env["ARCHX_ALLOW_SIMULATED"] = "1"
        created = subprocess.run([sys.executable, str(script), home], capture_output=True,
                                 text=True, env=env)
        assert created.returncode == 0, created.stderr
        workflow_id = created.stdout.strip().splitlines()[-1]
        assert _cli(home, "agent", "reject", workflow_id, "--reason", "not needed").returncode == 0
        shown = json.loads(_cli(home, "agent", "show", workflow_id, "--json").stdout)
        assert shown["status"] == "cancelled"
        assert "not needed" in shown["error"]
