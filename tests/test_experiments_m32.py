"""M32 - Experimental Mode: declared commands, declared parameters, honest comparison.

The milestone is about one promise: a number in a results table came from somewhere the
experiment declared, and a run that produced no number says so instead of showing zero. Half of
these tests exist to hold that promise under pressure - bad JSON, a missing file, a non-numeric
value, a command that failed after printing something - and the other half check that the
ordinary path (declare, run, compare) is not made awkward by the care.

As in M31, everything goes through :class:`ExperimentService` exactly as the CLI and the GUI do:
there is no test-only path into the database.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from archx_agent.managers.schema import SCHEMA_VERSION

CLI = [sys.executable, "-m", "archx_agent.interfaces.cli.main"]


def _write(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


@pytest.fixture()
def lab(tmp_path):
    """A directory inside the tool roots, with two scripts: one that prints metrics, one file."""
    folder = tmp_path / "lab"
    folder.mkdir(exist_ok=True)
    _write(
        folder / "emit.py",
        "import json, sys\n"
        "n = int(sys.argv[1])\n"
        "print('working on', n)\n"
        "print(json.dumps({'size': n, 'quality': n / 10}))\n",
    )
    _write(
        folder / "tofile.py",
        "import json, sys\n"
        "json.dump({'accuracy': 0.9, 'loss': 0.25}, open('metrics.json', 'w'))\n"
        "print('wrote metrics.json')\n",
    )
    _write(folder / "noisy.py", "print('this is not json')\n")
    _write(folder / "broken.py", "import sys\nprint('printed something')\nsys.exit(3)\n")
    _write(folder / "notnumber.py", "import json\nprint(json.dumps({'ok': True}))\n")
    _write(folder / "slow.py", "import time\ntime.sleep(5)\n")
    return folder


@pytest.fixture()
def ws(tmp_path, lab):
    with open_workspace(
        home=str(tmp_path / "home"),
        overrides={"tools.roots": [str(lab)]},
        env={"ARCHX_ALLOW_SIMULATED": "1"},
    ) as workspace:
        yield workspace


@pytest.fixture()
def granted(ws):
    """Both capabilities an experiment can need, granted persistently."""
    for capability in ("shell.run", "fs.read"):
        ws.permissions.grant(capability, subject="*", duration="persistent", confirm=True)
    return ws


def emit(ws, name="sorting", *, command="python emit.py {n}", params=None, metrics=None, **kwargs):
    return ws.experiment.create(
        name,
        command,
        params=params if params is not None else [{"name": "n", "default": 10}],
        metrics=metrics if metrics is not None else {"kind": "stdout-json"},
        **kwargs,
    )


# --------------------------------------------------------------------------
# the schema
# --------------------------------------------------------------------------
class TestTheSchema:
    def test_the_experiment_tables_are_part_of_the_schema(self, ws):
        assert SCHEMA_VERSION >= 22
        for table in ("experiment_specs", "experiment_runs", "experiment_metrics"):
            assert ws.store.scalar(
                f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='{table}'"
            ) == 1, table

    def test_the_mode_does_not_reuse_the_older_experiments_table(self, ws):
        """v13 has an `experiments` table nobody reads; M32 must not redefine it under people."""
        columns = {
            row["name"] for row in ws.store.query("PRAGMA table_info(experiments)")
        }
        assert "baseline" in columns, "the v13 table is still itself"
        assert "command" not in columns

    def test_a_fresh_workspace_has_no_experiments(self, ws):
        assert ws.experiment.stats() == {
            "experiments": 0, "open": 0, "runs": 0, "failed_runs": 0, "metrics": 0,
        }


# --------------------------------------------------------------------------
# declaring
# --------------------------------------------------------------------------
class TestDeclaring:
    def test_an_experiment_records_its_command_root_and_parameters(self, ws, lab):
        experiment = emit(ws)
        assert experiment.status == "open"
        assert experiment.command == "python emit.py {n}"
        assert Path(experiment.root) == lab.resolve()
        assert experiment.param_names() == ["n"]
        assert experiment.metrics_source == {"kind": "stdout-json"}

    def test_a_parameter_that_the_command_never_uses_is_refused(self, ws):
        with pytest.raises(ValidationError) as caught:
            emit(ws, params=[{"name": "n"}, {"name": "unused"}])
        assert "never uses" in caught.value.message

    def test_a_placeholder_with_no_declared_parameter_is_refused_by_name(self, ws):
        with pytest.raises(ValidationError) as caught:
            emit(ws, command="python emit.py {depth}")
        assert "{depth}" in caught.value.message

    def test_a_parameter_name_must_look_like_an_identifier(self, ws):
        with pytest.raises(ValidationError):
            emit(ws, params=[{"name": "1n"}])

    def test_two_parameters_cannot_share_a_name(self, ws):
        with pytest.raises(ValidationError):
            emit(ws, params=[{"name": "n"}, {"name": "n"}])

    def test_an_unknown_parameter_field_is_refused(self, ws):
        with pytest.raises(ValidationError) as caught:
            emit(ws, params=[{"name": "n", "type": "int"}])
        assert "type" in caught.value.message

    def test_a_command_is_required(self, ws):
        with pytest.raises(ValidationError):
            emit(ws, command="   ")

    def test_an_unknown_metrics_source_is_refused(self, ws):
        with pytest.raises(ValidationError) as caught:
            emit(ws, metrics={"kind": "vibes"})
        assert "vibes" in caught.value.message

    def test_a_metrics_file_must_stay_inside_the_experiment_directory(self, ws):
        with pytest.raises(ValidationError):
            emit(ws, metrics={"kind": "file", "path": "../../etc/passwd"})

    def test_a_metrics_file_path_is_only_for_the_file_source(self, ws):
        with pytest.raises(ValidationError):
            emit(ws, metrics={"kind": "stdout-json", "path": "metrics.json"})

    def test_a_root_outside_the_tool_roots_is_refused(self, ws, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        with pytest.raises(Exception) as caught:
            emit(ws, root=str(outside))
        assert "outside every tool root" in str(caught.value)

    def test_the_default_root_is_the_first_tool_root(self, ws, lab):
        assert Path(emit(ws).root) == lab.resolve()


# --------------------------------------------------------------------------
# running
# --------------------------------------------------------------------------
class TestRunning:
    def test_a_run_keeps_its_parameters_exit_code_and_metrics(self, granted):
        experiment = emit(granted)
        run = granted.experiment.run(experiment.id)
        assert run.status == "passed"
        assert run.exit_code == 0
        assert run.params == {"n": "10"}
        assert run.metrics == {"size": 10.0, "quality": 1.0}
        assert run.metrics_error is None
        assert run.duration_ms is not None

    def test_an_override_changes_the_command_that_runs(self, granted):
        experiment = emit(granted)
        run = granted.experiment.run(experiment.id, {"n": "42"})
        assert run.params == {"n": "42"}
        assert run.metrics["size"] == 42.0

    def test_a_parameter_with_no_default_must_be_passed(self, granted):
        experiment = emit(granted, params=[{"name": "n"}])
        with pytest.raises(ValidationError) as caught:
            granted.experiment.run(experiment.id)
        assert "no value" in caught.value.message
        assert granted.experiment.run(experiment.id, {"n": "5"}).status == "passed"

    def test_an_unknown_parameter_is_refused(self, granted):
        experiment = emit(granted)
        with pytest.raises(ValidationError) as caught:
            granted.experiment.run(experiment.id, {"depth": "2"})
        assert "depth" in caught.value.message

    def test_a_substituted_value_has_to_be_one_shell_safe_token(self, granted):
        experiment = emit(granted)
        with pytest.raises(ValidationError) as caught:
            granted.experiment.run(experiment.id, {"n": "10; rm -rf /"})
        assert "shell-safe" in caught.value.message

    def test_surrounding_whitespace_is_trimmed_rather_than_rejected(self, granted):
        experiment = emit(granted)
        assert granted.experiment.run(experiment.id, {"n": " 7 "}).params == {"n": "7"}

    def test_a_failing_command_is_recorded_as_a_run_not_an_absence(self, granted):
        experiment = granted.experiment.create(
            "broken", "python broken.py", metrics={"kind": "none"}
        )
        run = granted.experiment.run(experiment.id)
        assert run.status == "failed"
        assert run.exit_code == 3
        assert granted.experiments.get_run(run.id).status == "failed"

    def test_a_timeout_is_its_own_status(self, granted):
        experiment = granted.experiment.create(
            "slow", "python slow.py", metrics={"kind": "none"}
        )
        run = granted.experiment.run(experiment.id, timeout=1)
        assert run.status == "timeout"
        assert run.exit_code is None

    def test_a_run_without_a_grant_is_recorded_as_refused(self, ws):
        experiment = emit(ws)
        with pytest.raises((ApprovalRequiredError, PermissionDeniedError)):
            ws.experiment.run(experiment.id)
        runs = ws.experiment.runs(experiment.id)
        assert len(runs) == 1
        assert runs[0].status == "refused"
        assert "refused" in (runs[0].metrics_error or "")

    def test_a_closed_experiment_cannot_be_run(self, granted):
        experiment = emit(granted)
        granted.experiment.close(experiment.id)
        with pytest.raises(ValidationError) as caught:
            granted.experiment.run(experiment.id)
        assert "closed" in caught.value.message

    def test_every_run_gets_a_task_with_the_number_on_its_timeline(self, granted):
        experiment = emit(granted)
        run = granted.experiment.run(experiment.id, {"n": "3"})
        assert run.task_id
        task = granted.tasks.get(run.task_id)
        assert task.type == "experiment"
        assert task.status == "completed"
        timeline = granted.tasks.timeline(run.task_id)
        assert any(
            entry.get("kind") == "metric" and "size = 3" in (entry.get("detail") or "")
            for entry in timeline
        )

    def test_a_failed_run_leaves_its_task_failed_with_an_unresolved_item(self, granted):
        experiment = granted.experiment.create("broken", "python broken.py", metrics={"kind": "none"})
        run = granted.experiment.run(experiment.id)
        task = granted.tasks.get(run.task_id)
        assert task.status == "failed"
        assert task.unresolved

    def test_the_output_is_kept_as_an_artifact(self, granted):
        experiment = emit(granted)
        run = granted.experiment.run(experiment.id)
        assert run.artifact_id
        artifact = granted.tasks.artifact(run.artifact_id).unwrap()
        assert artifact.kind == "experiment-log"
        assert "working on" in Path(artifact.path).read_text()


# --------------------------------------------------------------------------
# metrics, and what happens when there are none
# --------------------------------------------------------------------------
class TestMetricsAreOnlyWhatWasDeclared:
    def test_no_source_means_no_metrics_and_no_complaint(self, granted):
        experiment = granted.experiment.create("plain", "python emit.py 1", metrics={"kind": "none"})
        run = granted.experiment.run(experiment.id)
        assert run.metrics == {}
        assert run.metrics_error is None

    def test_stdout_that_is_not_json_is_named_not_zeroed(self, granted):
        experiment = granted.experiment.create(
            "noisy", "python noisy.py", metrics={"kind": "stdout-json"}
        )
        run = granted.experiment.run(experiment.id)
        assert run.metrics == {}
        assert "not valid JSON" in (run.metrics_error or "")

    def test_a_boolean_is_not_a_number(self, granted):
        experiment = granted.experiment.create(
            "bools", "python notnumber.py", metrics={"kind": "stdout-json"}
        )
        run = granted.experiment.run(experiment.id)
        assert run.metrics == {}
        assert "non-numeric" in (run.metrics_error or "")

    def test_a_json_array_is_not_a_metrics_object(self, granted, lab):
        _write(lab / "arr.py", "print('[1, 2, 3]')\n")
        experiment = granted.experiment.create(
            "arr", "python arr.py", metrics={"kind": "stdout-json"}
        )
        run = granted.experiment.run(experiment.id)
        assert "JSON object" in (run.metrics_error or "")

    def test_a_file_source_reads_the_file_the_run_wrote(self, granted):
        experiment = granted.experiment.create(
            "filed", "python tofile.py", metrics={"kind": "file", "path": "metrics.json"}
        )
        run = granted.experiment.run(experiment.id)
        assert run.metrics == {"accuracy": 0.9, "loss": 0.25}
        assert run.metrics_error is None

    def test_a_missing_metrics_file_is_named(self, granted):
        experiment = granted.experiment.create(
            "filed", "python tofile.py", metrics={"kind": "file", "path": "nope.json"}
        )
        run = granted.experiment.run(experiment.id)
        assert run.metrics == {}
        assert "nope.json" in (run.metrics_error or "")

    def test_reading_a_metrics_file_needs_fs_read(self, granted):
        experiment = granted.experiment.create(
            "filed", "python tofile.py", metrics={"kind": "file", "path": "metrics.json"}
        )
        granted.permissions.revoke(granted.permissions.grants(capability="fs.read")[0].id)
        run = granted.experiment.run(experiment.id)
        assert "fs.read is not granted" in (run.metrics_error or "")

    def test_metrics_are_rows_so_they_can_be_queried(self, granted):
        experiment = emit(granted)
        granted.experiment.run(experiment.id, {"n": "2"})
        granted.experiment.run(experiment.id, {"n": "8"})
        rows = granted.store.query(
            "SELECT value FROM experiment_metrics WHERE name = 'size' ORDER BY value"
        )
        assert [row["value"] for row in rows] == [2.0, 8.0]

    def test_a_metric_name_is_readable_after_the_runs(self, granted):
        experiment = emit(granted)
        granted.experiment.run(experiment.id)
        assert granted.experiments.metric_names(experiment.id) == ["quality", "size"]


# --------------------------------------------------------------------------
# comparing
# --------------------------------------------------------------------------
class TestComparing:
    def test_the_best_run_is_the_highest_value_by_default(self, granted):
        experiment = emit(granted)
        for value in ("3", "9", "5"):
            granted.experiment.run(experiment.id, {"n": value})
        table = granted.experiment.compare(experiment.id, metric="size")
        assert table["best"]["value"] == 9.0
        assert table["best"]["params"] == {"n": "9"}
        assert table["direction"] == "highest"

    def test_minimise_flips_the_ranking(self, granted):
        experiment = emit(granted)
        for value in ("3", "9", "5"):
            granted.experiment.run(experiment.id, {"n": value})
        table = granted.experiment.compare(experiment.id, metric="size", minimise=True)
        assert table["best"]["value"] == 3.0
        assert table["direction"] == "lowest"

    def test_the_first_metric_is_used_when_none_is_named(self, granted):
        experiment = emit(granted)
        granted.experiment.run(experiment.id)
        assert granted.experiment.compare(experiment.id)["metric"] == "quality"

    def test_an_unknown_metric_is_refused_and_the_known_ones_listed(self, granted):
        experiment = emit(granted)
        granted.experiment.run(experiment.id)
        with pytest.raises(NotFoundError) as caught:
            granted.experiment.compare(experiment.id, metric="speed")
        assert "quality" in caught.value.message

    def test_runs_that_could_not_be_read_are_named_in_the_notes(self, granted):
        experiment = emit(granted)
        granted.experiment.run(experiment.id, {"n": "4"})
        granted.experiment.run(experiment.id, {"n": "notanumber"})
        table = granted.experiment.compare(experiment.id, metric="size")
        assert len(table["runs"]) == 2
        assert any("not ranked" in note for note in table["notes"])
        assert table["best"]["value"] == 4.0

    def test_a_failed_run_is_flagged_in_the_notes(self, granted):
        experiment = granted.experiment.create(
            "mixed", "python broken.py", metrics={"kind": "none"}
        )
        granted.experiment.run(experiment.id)
        notes = granted.experiment.compare(experiment.id)["notes"]
        assert any("did not pass" in note for note in notes)

    def test_an_experiment_with_no_metrics_has_no_best_run_and_says_so(self, granted):
        experiment = granted.experiment.create("plain", "python emit.py 1", metrics={"kind": "none"})
        granted.experiment.run(experiment.id)
        table = granted.experiment.compare(experiment.id)
        assert table["metric"] is None
        assert table["best"] is None

    def test_different_parameter_shapes_are_called_out(self, granted):
        """A row whose parameters do not match its neighbours is flagged, not quietly averaged."""
        experiment = emit(granted)
        first = granted.experiment.run(experiment.id, {"n": "1"})
        granted.store.execute(
            "UPDATE experiment_runs SET params = ? WHERE id = ?",
            (json.dumps({"depth": "2"}), first.id),
        )
        granted.experiment.run(experiment.id, {"n": "2"})
        notes = granted.experiment.compare(experiment.id)["notes"]
        assert any("parameter names" in note for note in notes)


# --------------------------------------------------------------------------
# the record
# --------------------------------------------------------------------------
class TestTheRecord:
    def test_show_carries_the_runs_the_metrics_and_the_counts(self, granted):
        experiment = emit(granted)
        granted.experiment.run(experiment.id, {"n": "1"})
        granted.experiment.run(experiment.id, {"n": "bad"})
        shown = granted.experiment.show(experiment.id)
        assert shown["experiment"]["id"] == experiment.id
        assert len(shown["runs"]) == 2
        assert shown["metric_names"] == ["quality", "size"]
        assert shown["stats"]["runs"] == 2
        assert shown["stats"]["without_metrics"] == 1

    def test_listing_filters_by_status(self, granted):
        first = emit(granted, name="one")
        emit(granted, name="two")
        granted.experiment.close(first.id)
        assert [e.name for e in granted.experiment.list(status="closed")] == ["one"]
        assert [e.name for e in granted.experiment.list(status="open")] == ["two"]

    def test_run_counts_are_one_query_for_the_list_view(self, granted):
        experiment = emit(granted)
        granted.experiment.run(experiment.id)
        granted.experiment.create("broken", "python broken.py", metrics={"kind": "none"})
        other = granted.experiment.list()[0]
        granted.experiment.run(other.id)
        counts = granted.experiments.run_counts()
        assert counts[experiment.id] == {"runs": 1, "failed": 0}
        assert counts[other.id] == {"runs": 1, "failed": 1}

    def test_closing_keeps_everything_readable(self, granted):
        experiment = emit(granted)
        granted.experiment.run(experiment.id)
        closed = granted.experiment.close(experiment.id)
        assert closed.status == "closed"
        assert len(granted.experiment.runs(experiment.id)) == 1

    def test_closing_twice_is_a_validation_error(self, granted):
        experiment = emit(granted)
        granted.experiment.close(experiment.id)
        with pytest.raises(ValidationError):
            granted.experiment.close(experiment.id)

    def test_reopening_lets_it_run_again(self, granted):
        experiment = emit(granted)
        granted.experiment.close(experiment.id)
        granted.experiment.reopen(experiment.id)
        assert granted.experiment.run(experiment.id).status == "passed"

    def test_deleting_takes_its_runs_and_metrics_with_it(self, granted):
        experiment = emit(granted)
        granted.experiment.run(experiment.id)
        granted.experiment.delete(experiment.id)
        assert granted.store.scalar("SELECT COUNT(*) FROM experiment_runs") == 0
        assert granted.store.scalar("SELECT COUNT(*) FROM experiment_metrics") == 0
        with pytest.raises(NotFoundError):
            granted.experiment.get(experiment.id)

    def test_an_unknown_experiment_is_a_not_found(self, ws):
        with pytest.raises(NotFoundError):
            ws.experiment.get("ex_missing")

    def test_the_record_survives_reopening_the_workspace(self, tmp_path, granted):
        experiment = emit(granted)
        granted.experiment.run(experiment.id, {"n": "6"})
        home = str(tmp_path / "home")
        with open_workspace(home=home, env={"ARCHX_ALLOW_SIMULATED": "1"}) as again:
            shown = again.experiment.show(experiment.id)
            assert shown["runs"][0]["metrics"] == {"size": 6.0, "quality": 0.6}


# --------------------------------------------------------------------------
# the GUI is a client of the same service
# --------------------------------------------------------------------------
@pytest.fixture()
def gui(tmp_path, lab):
    """The GUI api over a workspace whose tool root is the lab."""
    from archx_agent.interfaces.gui.server import GuiApi

    with open_workspace(
        home=str(tmp_path / "home"),
        overrides={"tools.roots": [str(lab)]},
        env={"ARCHX_ALLOW_SIMULATED": "1"},
    ) as workspace:
        for capability in ("shell.run", "fs.read"):
            workspace.permissions.grant(
                capability, subject="*", duration="persistent", confirm=True
            )
        yield GuiApi(workspace), workspace


def http(api, method, path, *, body=None):
    """Dispatch one request the way the socket does, without a socket."""
    from archx_agent.interfaces.gui.server import Request, split_target

    parsed_path, query, _token = split_target(path)
    request = Request(
        method=method,
        path=parsed_path,
        query=query,
        headers={"x-archx-token": api.token, "x-archx-request": "gui"},
        body=body,
    )
    response = api.dispatch(request)
    payload = response.payload
    if isinstance(payload, dict) and set(payload) == {"ok", "data"}:
        payload = payload["data"]
    return response.status, payload


class TestTheGuiIsTheSameService:
    def test_an_experiment_declared_in_the_page_is_one_the_cli_can_list(self, gui):
        api, ws = gui
        status, created = http(
            api, "POST", "/api/experiments",
            body={"name": "from the page", "command": "python emit.py {n}",
                  "params": [{"name": "n", "default": 4}], "metrics": {"kind": "stdout-json"}},
        )
        assert status == 200
        assert ws.experiments.get(created["id"]).name == "from the page"
        _, listed = http(api, "GET", "/api/experiments")
        assert [row["name"] for row in listed["experiments"]] == ["from the page"]
        assert listed["experiments"][0]["stats"]["runs"] == 0

    def test_a_run_from_the_page_is_the_row_the_record_has(self, gui):
        api, ws = gui
        _, created = http(
            api, "POST", "/api/experiments",
            body={"name": "run me", "command": "python emit.py {n}",
                  "params": [{"name": "n", "default": 4}], "metrics": {"kind": "stdout-json"}},
        )
        status, run = http(api, "POST", f"/api/experiments/{created['id']}/run", body={})
        assert status == 200
        assert run["status"] == "passed"
        assert run["metrics"] == {"size": 4.0, "quality": 0.4}
        assert ws.experiments.get_run(run["id"]).metrics["size"] == 4.0

    def test_compare_over_the_page_names_the_metric_and_the_best_run(self, gui):
        api, ws = gui
        _, created = http(
            api, "POST", "/api/experiments",
            body={"name": "compare", "command": "python emit.py {n}",
                  "params": [{"name": "n", "default": 2}], "metrics": {"kind": "stdout-json"}},
        )
        for value in (2, 6):
            http(api, "POST", f"/api/experiments/{created['id']}/run", body={"params": {"n": str(value)}})
        status, table = http(api, "GET", f"/api/experiments/{created['id']}/compare")
        assert status == 200
        assert table["metric"] == "quality"
        assert table["best"]["value"] == 0.6

    def test_a_bad_parameter_is_a_400_not_a_failed_run(self, gui):
        api, _ws = gui
        _, created = http(
            api, "POST", "/api/experiments",
            body={"name": "strict", "command": "python emit.py {n}",
                  "params": [{"name": "n", "default": 2}]},
        )
        status, payload = http(
            api, "POST", f"/api/experiments/{created['id']}/run", body={"params": {"n": "2 3"}}
        )
        assert status == 400
        assert payload["error"]["code"] == "validation"

    def test_a_missing_grant_is_a_403_naming_the_approval(self, gui):
        api, ws = gui
        _, created = http(
            api, "POST", "/api/experiments",
            body={"name": "refused", "command": "python emit.py {n}",
                  "params": [{"name": "n", "default": 2}]},
        )
        ws.permissions.revoke(ws.permissions.grants(capability="shell.run")[0].id)
        status, payload = http(api, "POST", f"/api/experiments/{created['id']}/run", body={})
        assert status == 403
        assert payload["error"]["code"] in {"approval_required", "permission_denied"}

    def test_listing_rejects_an_unknown_status(self, gui):
        api, _ws = gui
        status, payload = http(api, "GET", "/api/experiments?status=maybe")
        assert status == 400
        assert payload["error"]["code"] == "validation"

    def test_deleting_over_the_page_removes_the_runs(self, gui):
        api, ws = gui
        _, created = http(
            api, "POST", "/api/experiments",
            body={"name": "gone", "command": "python emit.py {n}",
                  "params": [{"name": "n", "default": 1}]},
        )
        http(api, "POST", f"/api/experiments/{created['id']}/run", body={})
        status, payload = http(api, "DELETE", f"/api/experiments/{created['id']}")
        assert status == 200
        assert payload["deleted"] == created["id"]
        assert ws.store.scalar("SELECT COUNT(*) FROM experiment_runs") == 0


# --------------------------------------------------------------------------
# the command line, which is how a person actually uses it
# --------------------------------------------------------------------------
class TestTheCli:
    @pytest.fixture()
    def env(self, tmp_path):
        home = tmp_path / "home"
        (tmp_path / "lab").mkdir(exist_ok=True)
        subprocess.run([*CLI, "--home", str(home), "init"], capture_output=True, timeout=120)
        subprocess.run(
            [*CLI, "--home", str(home), "config", "set", "tools.roots", str(tmp_path / "lab")],
            capture_output=True, timeout=120,
        )
        for capability in ("shell.run", "fs.read"):
            subprocess.run(
                [*CLI, "--home", str(home), "permissions", "grant", capability,
                 "--duration", "persistent", "--subject", "*", "--confirm"],
                capture_output=True, timeout=120,
            )
        return {"home": str(home), "HOME": str(home)}

    def run_cli(self, env, *args, expect=0):
        result = subprocess.run(
            [*CLI, "--home", env["home"], *args],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == expect, result.stdout + result.stderr
        return result

    def test_declare_run_and_compare_over_the_cli(self, env, lab):
        (lab / "emit.py").write_text(
            "import json, sys\nprint(json.dumps({'size': int(sys.argv[1])}))\n"
        )
        created = self.run_cli(
            env, "experiment", "create", "sizes", "--command", "python emit.py {n}",
            "--param", "n=5", "--metric-source", "stdout-json",
        )
        experiment_id = created.stdout.split()[1]
        self.run_cli(env, "experiment", "run", experiment_id, "--set", "n=9")
        compared = self.run_cli(env, "experiment", "compare", experiment_id)
        assert "size=9" in compared.stdout

    def test_a_failed_run_exits_one(self, env, lab):
        (lab / "broken.py").write_text("import sys\nsys.exit(4)\n")
        created = self.run_cli(
            env, "experiment", "create", "broken", "--command", "python broken.py"
        )
        experiment_id = created.stdout.split()[1]
        self.run_cli(env, "experiment", "run", experiment_id, expect=1)

    def test_an_unsafe_parameter_exits_two_without_running(self, env, lab):
        (lab / "emit.py").write_text("print('hi')\n")
        created = self.run_cli(
            env, "experiment", "create", "unsafe", "--command", "python emit.py {n}",
            "--param", "n=1",
        )
        experiment_id = created.stdout.split()[1]
        result = self.run_cli(env, "experiment", "run", experiment_id, "--set", "n=a b", expect=2)
        assert "shell-safe" in result.stderr

    def test_delete_needs_confirmation(self, env):
        created = self.run_cli(
            env, "experiment", "create", "nothing", "--command", "true"
        )
        experiment_id = created.stdout.split()[1]
        self.run_cli(env, "experiment", "delete", experiment_id, expect=2)
        self.run_cli(env, "experiment", "delete", experiment_id, "--yes")
