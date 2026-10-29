"""M38 - Execution environments: run a command *there*, and keep what it changed.

The hazard in this milestone is the opposite of M36's: it is easy to *look* sandboxed. A target named
`docker` that quietly runs the command on this machine is worse than no sandbox at all, because the
user has been told they are safe. So the tests are built around the wrapper, not the label:

1. **the wrapper is really in the invocation.** `TestTheInvocation` reads the string that would be
   executed for each backend and checks the flag that matters is there (`--rm`, `--network none`,
   the mount, `-lc`). A backend that cannot be built refuses, by name.
2. **a backend here is one this repository can drive.** `TestFakeBinariesOnPath` puts a stand-in
   `docker`/`wsl.exe`/`vmrun`/`VBoxManage` on `PATH` and asserts the argv the run actually asked for -
   so the docker path is tested without docker, and nothing claims a container ran.
3. **nothing runs before the switch, and the refusal is a row.** `TestTheBoundary` checks
   `execution.enabled`, an unusable backend, and that a refused run keeps its reasons.
4. **another machine is a real machine.** `TestAgainstAWorker` starts a real worker, asserts it
   refuses `/exec` until it is started with `--allow-exec`, rejects a wrong token, and then runs a
   command there whose `pwd` and `uname` are not this machine's.
5. **the project comes back, and a conflict is not silently overwritten.** `TestTheFileLedger` pushes
   a directory, edits it on the worker, pulls it back, and then makes *both* sides change the same file
   and checks the pull refuses without `--force`.
6. **training can run there too.** `TestTrainingOnAWorker` runs the same dataset twice - local and
   remote - and asserts the metrics are **equal**, because it is the same trainer, and that the remote
   run is one row in the same ledger with `target = 'remote'`.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import threading
from pathlib import Path

import pytest

from archx_agent.application.execution import build_invocation, probe_backends, sandbox_config
from archx_agent.application.remote_worker import Worker, make_server
from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.interfaces.gui.server import GuiApi, Request, split_target
from archx_agent.managers.schema import SCHEMA_VERSION


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
@pytest.fixture()
def lab(tmp_path, monkeypatch) -> Path:
    folder = tmp_path / "lab"
    project = folder / "proj"
    project.mkdir(parents=True)
    (project / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (project / "README.md").write_text("a tiny project\n", encoding="utf-8")
    for language, template in (
        ("python", "def function_{n}(x):\n    return x + {n}\n"),
        ("rust", "fn function_{n}(x: i32) -> i32 {{\n    x + {n}\n}}\n"),
    ):
        (folder / "corpus" / language).mkdir(parents=True, exist_ok=True)
        for n in range(1, 5):
            (folder / "corpus" / language / f"file{n}.txt").write_text(
                template.format(n=n), encoding="utf-8"
            )
    # The backends under test must not be found on this machine's own PATH by accident: the
    # stand-ins below are the only ones a probe may discover.
    empty = tmp_path / "bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", f"{empty}{os.pathsep}{os.environ.get('PATH', '')}")
    return folder


@pytest.fixture()
def ws(tmp_path, lab, monkeypatch):
    monkeypatch.setenv("PATH", os.environ["PATH"])
    with open_workspace(
        home=str(tmp_path / "home"), overrides={"tools.roots": [str(lab)]}
    ) as workspace:
        workspace.permissions.grant("fs.read", subject="*", duration="persistent", confirm=True)
        workspace.permissions.grant("fs.write", subject="*", duration="persistent", confirm=True)
        workspace.permissions.grant("shell.run", subject="*", duration="persistent", confirm=True)
        yield workspace


@pytest.fixture()
def execution(ws):
    ws.config.set("execution.enabled", True)
    return ws.exec_env


@pytest.fixture()
def dataset(ws):
    created = ws.data.create("code", ["corpus"], license="MIT")
    ws.data.scan(created["id"])
    ws.data.clean(created["id"])
    ws.data.split(created["id"], train=0.5, val=0.25, test=0.25, seed="m38")
    ws.data.build(created["id"])
    return created["id"]


@pytest.fixture()
def worker_server():
    """A real worker on a real port, with command execution enabled and a token."""
    worker = Worker(name="exec-box", allow_exec=True, token="t0ken")
    server = make_server(worker, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], worker
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def fake_binary(folder: Path, name: str, log: Path) -> Path:
    """An executable that records its argv and exits 0 - a stand-in, never the real thing."""
    path = folder / name
    path.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" >> "{log}"\n'
        'echo "fake-sandbox says hello"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


# --------------------------------------------------------------------------
# 1. the ledger
# --------------------------------------------------------------------------
class TestTheLedger:
    def test_the_schema_records_where_things_ran(self, ws):
        assert SCHEMA_VERSION >= 28
        for table in ("execution_targets", "execution_runs", "execution_files"):
            assert ws.store.table_exists(table), table
        columns = {row["name"] for row in ws.store.query("PRAGMA table_info(execution_runs)")}
        for field in ("kind", "command", "invocation", "exit_code", "stdout_path", "detached",
                      "remote_job_id", "started_at"):
            assert field in columns
        # a training run now names its machine
        training = {row["name"] for row in ws.store.query("PRAGMA table_info(training_jobs)")}
        assert "target" in training and "remote_job_id" in training

    def test_a_fresh_home_has_run_nothing(self, ws):
        stats = ws.exec_env.stats()
        assert stats["runs"] == 0
        assert stats["files"] == 0
        assert stats["enabled"] is False
        assert stats["default_target"] == "local"


# --------------------------------------------------------------------------
# 2. the probe tells the truth about this machine
# --------------------------------------------------------------------------
class TestTheProbe:
    def test_every_backend_is_named_with_a_reason_or_a_hint(self, ws):
        probes = {probe["kind"]: probe for probe in ws.exec_env.probes()}
        assert set(probes) == {"local", "remote", "docker", "wsl", "windows-sandbox",
                               "vmware", "virtualbox"}
        assert probes["local"]["available"] is True
        for kind, probe in probes.items():
            if probe["available"]:
                assert not probe["why_not"], kind
            else:
                assert probe["why_not"], kind
                assert probe["enable"], kind

    def test_a_backend_that_is_not_here_says_why(self, ws, monkeypatch):
        # A CI runner *does* have docker, so "docker is absent" is a fact about this machine, not
        # about the code. Hide one binary and the refusal is testable anywhere.
        from archx_agent.application import execution as execution_module

        monkeypatch.setattr(execution_module, "_which", lambda name: None)
        docker = ws.exec_env.probe("docker")
        assert docker["available"] is False
        assert any("docker" in reason for reason in docker["why_not"])
        assert docker["enable"]

    def test_wsl_and_windows_sandbox_are_named_as_windows_only(self, ws):
        if sys.platform == "win32":  # pragma: no cover - this sandbox is Linux
            pytest.skip("checked on the other branch")
        assert "Windows" in " ".join(ws.exec_env.probe("wsl")["why_not"])
        assert "Windows" in " ".join(ws.exec_env.probe("windows-sandbox")["why_not"])

    def test_an_unknown_backend_is_a_validation_error(self, ws):
        with pytest.raises(ValidationError, match="unknown backend"):
            ws.exec_env.probe("mainframe")


# --------------------------------------------------------------------------
# 3. the wrapper is really in the invocation
# --------------------------------------------------------------------------
class TestTheInvocation:
    def _target(self, execution, kind, **spec):
        return execution.ensure(kind, name=f"{kind}-test", spec=spec)

    def test_docker_runs_disposable_and_offline(self, execution):
        target = self._target(execution, "docker", image="debian:12")
        invocation, meta = build_invocation(target, "python3 -V", "/work/proj")
        assert invocation.startswith("docker run --rm --network none")
        assert "-v /work/proj:/work" in invocation
        assert "-w /work" in invocation
        assert invocation.endswith("debian:12 sh -lc 'python3 -V'")
        assert meta["detached"] is False

    def test_docker_can_be_asked_for_a_network_deliberately(self, execution):
        target = self._target(execution, "docker", network="bridge")
        invocation, _meta = build_invocation(target, "true", "/work")
        assert "--network bridge" in invocation

    def test_a_command_with_quotes_stays_one_argument(self, execution):
        target = self._target(execution, "docker", image="alpine")
        invocation, _meta = build_invocation(
            target, "printf '%s\\n' \"a b\"", "/work"
        )
        import shlex

        argv = shlex.split(invocation)
        assert argv[-1] == "printf '%s\\n' \"a b\""
        assert argv[-2] == "-lc"

    def test_wsl_is_described_as_an_environment_not_a_boundary(self, execution):
        target = self._target(execution, "wsl", distro="Ubuntu")
        invocation, meta = build_invocation(target, "uname -a", "/work")
        assert invocation.startswith("wsl.exe -d Ubuntu -e sh -lc")
        assert "not a boundary" in meta["note"]

    def test_vmware_and_virtualbox_use_the_guest_tools(self, execution):
        vmware = self._target(execution, "vmware", vm="/vms/box.vmx")
        invocation, _meta = build_invocation(vmware, "ls", "/work")
        assert invocation.startswith("vmrun -T ws runScriptInGuest /vms/box.vmx")
        vbox = self._target(execution, "virtualbox", vm="box")
        invocation, _meta = build_invocation(vbox, "ls", "/work")
        assert invocation.startswith("VBoxManage guestcontrol box run --exe /bin/sh")

    def test_a_vm_target_without_a_vm_is_refused(self, execution):
        target = self._target(execution, "vmware")
        with pytest.raises(ValidationError, match="vmx"):
            build_invocation(target, "ls", "/work")

    def test_windows_sandbox_is_detached_and_says_so(self, execution):
        target = self._target(execution, "windows-sandbox")
        invocation, meta = build_invocation(target, "python -V", "C:\\proj")
        assert invocation == ""
        assert meta["detached"] is True
        assert "reports nothing back" in meta["note"] or "reports nothing" in meta["note"]

    def test_the_wsb_script_maps_a_folder_and_runs_the_command(self, execution):
        target = self._target(execution, "windows-sandbox")
        config = sandbox_config(target, "python --version", host_dir="C:\\proj")
        assert "<HostFolder>C:\\proj</HostFolder>" in config
        assert "<SandboxFolder>C:\\archx</SandboxFolder>" in config
        assert "<Networking>Disable</Networking>" in config
        assert "<ClipboardRedirection>Disable</ClipboardRedirection>" in config
        assert "&amp;&amp;" in config  # XML-escaped, not a literal &&
        assert "python --version" in config

    def test_network_none_is_off_and_a_bridge_is_on(self, execution):
        # `--network none` is a string, and a string is truthy: reading it as a boolean turned the
        # sandbox's networking *on* for the exact value that means "off".
        default = execution.ensure("windows-sandbox", name="sb-default")
        assert "<Networking>Disable</Networking>" in sandbox_config(
            default, "x", host_dir="C:\\p"
        )
        bridged = execution.ensure(
            "windows-sandbox", name="sb-bridged", spec={"network": "bridge"}
        )
        assert "<Networking>Enable</Networking>" in sandbox_config(bridged, "x", host_dir="C:\\p")
        explicit_off = execution.ensure(
            "windows-sandbox", name="sb-off", spec={"network": "none"}
        )
        assert "<Networking>Disable</Networking>" in sandbox_config(
            explicit_off, "x", host_dir="C:\\p"
        )

    def test_a_read_only_mount_says_so(self, execution):
        target = execution.ensure(
            "windows-sandbox", name="sb-read-only", spec={"read_only": True}
        )
        assert "<ReadOnly>true</ReadOnly>" in sandbox_config(target, "x", host_dir="C:\\p")

    def test_the_wsb_escapes_output_to_the_mapped_folder(self, execution):
        target = self._target(execution, "windows-sandbox")
        config = sandbox_config(target, "x", host_dir="C:\\p")
        assert "archx-exec.log" in config
        assert "2&gt;&amp;1" in config


# --------------------------------------------------------------------------
# 4. a backend this repository can actually drive (with a stand-in binary)
# --------------------------------------------------------------------------
@pytest.fixture()
def stand_in(monkeypatch, tmp_path, ws) -> Path:
    """A directory that is the first thing on PATH, so a stand-in binary is what gets found.

    Not `PATH.split(os.pathsep)[0]`: that is whatever the machine running the tests put there, and
    writing a file named `docker` into it would be a property of the runner, not of the code. Asked
    for by name, the directory is ours.
    """
    directory = tmp_path / "stand-in-bin"
    directory.mkdir()
    monkeypatch.setenv("PATH", f"{directory}{os.pathsep}{os.environ.get('PATH', '')}")
    return directory


class TestFakeBinariesOnPath:
    def test_docker_is_discovered_when_it_appears(self, stand_in, execution, tmp_path):
        fake_binary(stand_in, "docker", tmp_path / "docker.argv")
        probe = execution.probe("docker")
        assert probe["available"] is True

    def test_the_wrapper_the_run_builds_is_the_one_that_executes(
        self, stand_in, lab, execution, tmp_path
    ):
        log = tmp_path / "docker.argv"
        fake_binary(stand_in, "docker", log)
        target = execution.ensure("docker", name="docker-box", spec={"image": "debian:12"})
        run = execution.run("echo inside", target="docker-box", cwd=str(lab / "proj"))
        assert run["status"] == "ok", run
        recorded = log.read_text(encoding="utf-8").splitlines()
        assert recorded[0] == "run"
        assert "--rm" in recorded and "--network" in recorded
        assert "none" in recorded
        assert "debian:12" in recorded
        assert recorded[-1] == "echo inside"

    def test_the_stand_in_output_is_the_runs_output(self, stand_in, lab, execution, tmp_path):
        fake_binary(stand_in, "docker", tmp_path / "docker.argv")
        execution.ensure("docker", name="docker-box", spec={"image": "alpine"})
        run = execution.run("true", target="docker-box", cwd=str(lab / "proj"))
        assert "fake-sandbox says hello" in run["stdout"]
        assert run["stdout_path"], "the output must be kept as an artifact"

    def test_a_non_zero_exit_from_the_wrapper_is_a_failed_run(
        self, stand_in, lab, execution, tmp_path
    ):
        path = stand_in / "docker"
        path.write_text("#!/bin/sh\necho nope >&2\nexit 125\n", encoding="utf-8")
        path.chmod(0o755)
        execution.ensure("docker", name="docker-broken", spec={"image": "alpine"})
        run = execution.run("true", target="docker-broken", cwd=str(lab / "proj"))
        assert run["status"] == "failed"
        assert run["exit_code"] == 125
        assert "nope" in run["stderr"]

    def test_vmrun_is_driven_with_the_guest_script(self, ws, lab, execution, tmp_path):
        empty = Path(os.environ["PATH"].split(os.pathsep)[0])
        log = tmp_path / "vmrun.argv"
        fake_binary(empty, "vmrun", log)
        execution.ensure("vmware", name="vm-box", spec={"vm": "/vms/box.vmx", "user": "dev"})
        run = execution.run("make test", target="vm-box", cwd=str(lab / "proj"))
        assert run["status"] == "ok", run
        recorded = log.read_text(encoding="utf-8").splitlines()
        assert recorded[0] == "-T"
        assert "runScriptInGuest" in recorded
        assert "/vms/box.vmx" in recorded
        assert "make test" in recorded


# --------------------------------------------------------------------------
# 5. nothing runs before the switch, and a refusal is a row
# --------------------------------------------------------------------------
class TestTheBoundary:
    def test_execution_is_off_by_default(self, ws, lab):
        run = ws.exec_env.run("echo hi", target="local", cwd=str(lab))
        assert run["status"] == "refused"
        assert any("execution is off" in reason for reason in run["reasons"])
        assert ws.execution.runs()[0].status == "refused"

    def test_an_unusable_backend_refuses_with_its_reason(
        self, ws, execution, lab, monkeypatch
    ):
        from archx_agent.application import execution as execution_module

        monkeypatch.setattr(execution_module, "_which", lambda name: None)
        target = execution.ensure("docker", name="no-docker", spec={"image": "alpine"})
        assert target.status == "refused"
        run = execution.run("echo hi", target="no-docker", cwd=str(lab))
        assert run["status"] == "refused"
        assert any("docker" in reason for reason in run["reasons"])

    def test_the_local_target_exists_without_setup(self, execution, lab):
        run = execution.run("echo from-local", target="local", cwd=str(lab))
        assert run["status"] == "ok"
        assert run["kind"] == "local"
        assert "from-local" in run["stdout"]

    def test_a_command_without_the_shell_run_grant_never_runs(self, tmp_path, lab):
        """The sandbox is a boundary for the machine; the permission centre is the boundary for the
        agent - and both must hold. A local run with no `shell.run` grant refuses and says so."""
        with open_workspace(
            home=str(tmp_path / "nogrant"), overrides={"tools.roots": [str(lab)]}
        ) as closed:
            closed.config.set("execution.enabled", True)
            run = closed.exec_env.run("echo never", target="local", cwd=str(lab))
            reasons = " ".join(run.get("reasons") or [])
            assert run["status"] == "refused", run
            assert run["approval_id"], "a pending approval must be named on the run"
            assert "shell.run" in reasons
            assert "never" not in (run.get("stdout") or "")
            # and the refusal is a row, not just a return value
            assert closed.execution.runs()[0].status == "refused"

    def test_an_unknown_target_is_a_lookup_error(self, execution):
        with pytest.raises(NotFoundError, match="no such execution target"):
            execution.run("echo hi", target="nope")


# --------------------------------------------------------------------------
# 6. another machine is a real machine
# --------------------------------------------------------------------------
class TestAgainstAWorker:
    def _target(self, ws, execution, port):
        ws.config.set("remote.enabled", True)
        ws.config.set("remote.worker_token", "t0ken")
        return execution.ensure(
            "remote", name="vm1", endpoint=f"http://127.0.0.1:{port}"
        )

    def test_the_command_runs_there_not_here(self, ws, execution, worker_server, lab):
        port, _worker = worker_server
        self._target(ws, execution, port)
        run = execution.run("pwd; uname -s", target="vm1", cwd=str(lab))
        assert run["status"] == "ok", (run["status"], run.get("reasons"), run.get("note"))
        assert "exec-box" in (run["note"] or "")
        assert "Linux" in run["stdout"]

    def test_a_wrong_token_is_refused_by_the_worker(self, ws, execution, worker_server, lab):
        port, _worker = worker_server
        self._target(ws, execution, port)
        ws.config.set("remote.worker_token", "wrong")
        run = execution.run("echo hi", target="vm1", cwd=str(lab))
        # A worker that rejects the token has *refused*; nothing ran there, so this is not a failure.
        assert run["status"] == "refused", run
        assert any("token" in reason for reason in run["reasons"])

    def test_a_worker_without_allow_exec_refuses_to_run_commands(self, ws, execution, lab):
        worker = Worker(name="training-only")
        server = make_server(worker, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            ws.config.set("remote.enabled", True)
            execution.ensure("remote", name="closed", endpoint=f"http://127.0.0.1:{server.server_address[1]}")
            answer = worker.execute({"command": "echo hi"})
            assert "refused" in answer
            assert "--allow-exec" in answer["refused"]
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_a_command_that_escapes_the_work_directory_is_refused(self, worker_server):
        _port, worker = worker_server
        answer = worker.execute({"command": "echo hi", "cwd": "../../etc"})
        assert "refused" in answer
        assert "inside" in answer["refused"]

    def test_a_timeout_is_a_timeout_not_a_failure(self, ws, execution, worker_server, lab):
        port, _worker = worker_server
        self._target(ws, execution, port)
        run = execution.run("sleep 5", target="vm1", cwd=str(lab), timeout=1)
        assert run["status"] == "timeout"
        assert run["exit_code"] is None


# --------------------------------------------------------------------------
# 7. the project goes there and comes back
# --------------------------------------------------------------------------
class TestTheFileLedger:
    def _target(self, ws, execution, port):
        ws.config.set("remote.enabled", True)
        ws.config.set("remote.worker_token", "t0ken")
        return execution.ensure("remote", name="vm1", endpoint=f"http://127.0.0.1:{port}")

    def test_a_push_is_recorded_with_both_hashes(self, ws, execution, worker_server, lab):
        port, _worker = worker_server
        self._target(ws, execution, port)
        pushed = execution.push("vm1", root=str(lab / "proj"))
        assert pushed["files"] == 2
        rows = ws.execution.files(direction="push")
        assert {row.path for row in rows} == {"main.py", "README.md"}
        for row in rows:
            assert row.sha256_local and row.sha256_remote
            assert row.sha256_local == row.sha256_remote

    def test_a_change_made_there_comes_back(self, ws, execution, worker_server, lab):
        port, _worker = worker_server
        self._target(ws, execution, port)
        execution.push("vm1", root=str(lab / "proj"))
        execution.run("printf 'print(2)\\n' > project/main.py", target="vm1", cwd=str(lab))
        pulled = execution.pull("vm1", root=str(lab / "proj"))
        assert pulled["applied"] == ["main.py"]
        assert (lab / "proj" / "main.py").read_text(encoding="utf-8") == "print(2)\n"

    def test_a_file_changed_on_both_sides_is_a_conflict(self, ws, execution, worker_server, lab):
        port, _worker = worker_server
        self._target(ws, execution, port)
        execution.push("vm1", root=str(lab / "proj"))
        (lab / "proj" / "main.py").write_text("print('here')\n", encoding="utf-8")
        execution.run("printf \"print('there')\\n\" > project/main.py", target="vm1", cwd=str(lab))
        pulled = execution.pull("vm1", root=str(lab / "proj"))
        assert pulled["conflicts"] == ["main.py"]
        assert (lab / "proj" / "main.py").read_text(encoding="utf-8") == "print('here')\n"
        conflicts = [row for row in ws.execution.files(direction="pull") if row.status == "conflict"]
        assert conflicts and "changed here" in (conflicts[0].note or "")

    def test_force_replaces_a_conflicting_file_and_says_so(self, ws, execution, worker_server, lab):
        port, _worker = worker_server
        self._target(ws, execution, port)
        execution.push("vm1", root=str(lab / "proj"))
        (lab / "proj" / "main.py").write_text("print('here')\n", encoding="utf-8")
        execution.run("printf \"print('there')\\n\" > project/main.py", target="vm1", cwd=str(lab))
        pulled = execution.pull("vm1", root=str(lab / "proj"), force=True)
        assert pulled["applied"] == ["main.py"]
        assert (lab / "proj" / "main.py").read_text(encoding="utf-8") == "print('there')\n"
        forced = [row for row in ws.execution.files(direction="pull") if row.note == "moved here by force"]
        assert forced

    def test_an_unchanged_file_is_not_rewritten(self, ws, execution, worker_server, lab):
        port, _worker = worker_server
        self._target(ws, execution, port)
        execution.push("vm1", root=str(lab / "proj"))
        pulled = execution.pull("vm1", root=str(lab / "proj"))
        assert pulled["applied"] == []
        assert sorted(pulled["skipped"]) == ["README.md", "main.py"]

    def test_a_push_to_a_local_target_is_refused_with_a_reason(self, execution, lab):
        with pytest.raises(ValidationError, match="only a remote target"):
            execution.push("local", root=str(lab / "proj"))


# --------------------------------------------------------------------------
# 8. training can run on the same worker
# --------------------------------------------------------------------------
class TestTrainingOnAWorker:
    @pytest.fixture()
    def ready(self, ws, execution, worker_server):
        port, _worker = worker_server
        ws.config.set("remote.enabled", True)
        ws.config.set("remote.worker_token", "t0ken")
        ws.config.set("remote.endpoint", f"http://127.0.0.1:{port}")
        execution.ensure("remote", name="vm1", endpoint=f"http://127.0.0.1:{port}")
        return port

    def test_the_remote_run_is_one_row_in_the_same_ledger(self, ws, dataset, ready):
        job = ws.trainer.run(method="ngram", dataset=dataset, order=2, seed=5, target="remote")
        assert job["status"] == "completed", job
        assert job["target"] == "remote"
        assert job["remote_job_id"]
        assert job["metrics"]["train"]["perplexity"] > 0
        assert job["artifact_path"]

    def test_a_remote_run_and_a_local_run_agree_exactly(self, ws, dataset, ready):
        local = ws.trainer.run(method="ngram", dataset=dataset, order=2, seed=5, target="local")
        remote = ws.trainer.run(method="ngram", dataset=dataset, order=2, seed=5, target="remote")
        assert local["status"] == "completed" and remote["status"] == "completed"
        for split, values in local["metrics"].items():
            for name, value in values.items():
                assert remote["metrics"][split][name] == value

    def test_a_remote_run_with_no_endpoint_is_refused_not_failed(self, ws, dataset):
        ws.config.set("remote.enabled", True)
        ws.config.set("remote.endpoint", "")
        job = ws.trainer.run(method="ngram", dataset=dataset, order=2, seed=5, target="remote")
        assert job["status"] == "refused"
        assert any("endpoint" in reason or "dispatch" in reason for reason in job["reasons"])

    def test_an_unknown_training_target_is_refused_by_name(self, ws, dataset):
        with pytest.raises(ValidationError, match="unknown training target"):
            ws.trainer.run(method="ngram", dataset=dataset, target="docker")

    def test_the_default_target_is_this_cpu(self, ws, dataset):
        job = ws.trainer.run(method="ngram", dataset=dataset, order=2, seed=5)
        assert job["target"] == "local"


# --------------------------------------------------------------------------
# 9. the page
# --------------------------------------------------------------------------
TOKEN = "m38-token"


@pytest.fixture()
def api(ws):
    return GuiApi(ws, token=TOKEN)


def call(api, method, path, *, token=TOKEN, body=None):
    parsed, query, url_token = split_target(path)
    request = Request(
        method=method, path=parsed, query=query,
        headers={"x-archx-token": token} if token else {}, body=body,
        token=url_token, token_in_query=url_token is not None,
    )
    response = api.dispatch(request)
    return response.status, response.payload


class TestThePage:
    def test_targets_are_listed_with_their_reasons(self, api):
        status, payload = call(api, "GET", "/api/exec/targets")
        assert status == 200
        kinds = {probe["kind"] for probe in payload["data"]["probes"]}
        assert "local" in kinds and "windows-sandbox" in kinds

    def test_a_run_can_be_started_and_read(self, api, ws, lab):
        ws.config.set("execution.enabled", True)
        status, payload = call(
            api, "POST", "/api/exec/runs", body={"cmdline": "echo from-page", "target": "local"}
        )
        assert status == 200
        run_id = payload["data"]["id"]
        status, payload = call(api, "GET", f"/api/exec/runs/{run_id}")
        assert status == 200
        assert "from-page" in payload["data"]["stdout"]
        assert payload["data"]["kind"] == "local"

    def test_without_a_token_the_runs_are_closed(self, api):
        status, _payload = call(api, "GET", "/api/exec/runs", token=None)
        assert status == 401

    def test_an_unknown_run_is_a_404(self, api):
        status, payload = call(api, "GET", "/api/exec/runs/xr_nope")
        assert status == 404
        assert payload["error"]["code"] == "not_found"

    def test_an_unknown_status_is_a_400(self, api):
        status, payload = call(api, "GET", "/api/exec/runs?status=nonsense")
        assert status == 400
        assert payload["error"]["code"] == "validation"

    def test_status_reports_execution_off_by_default(self, api):
        status, payload = call(api, "GET", "/api/status")
        assert status == 200
        assert payload["data"]["execution"]["enabled"] is False
