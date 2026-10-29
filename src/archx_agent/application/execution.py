"""Execution environments: run a command somewhere else, and keep what it changed.

The distinction this milestone draws is the one people actually mean by "sandbox":

* **the local machine** - a command runs here, and the only boundary is the permission centre. That is
  a real boundary for *the agent*, and not a boundary for the machine: a command with `fs.write`
  granted can still overwrite your files.
* **a sandbox** - a container, a Windows Sandbox, a VM, or another computer. A command runs *there*,
  and the damage it could do is contained by something that is not this process.

So a backend is not a label. Each one is a **wrapper** that is either built into the invocation that
runs, or refused with the reason it cannot be built:

``local``
    the command itself, through `shell.run`.
``docker``
    ``docker run --rm --network none -v <cwd>:/work -w /work <image> sh -lc '<command>'``
``wsl``
    ``wsl.exe -e sh -lc '<command>'`` - a second Linux environment, not a boundary: ``/mnt/c`` is your
    own disk, and the note on the run says so.
``vmware`` / ``virtualbox``
    ``vmrun … runScriptInGuest`` / ``VBoxManage guestcontrol … run`` against a VM the user already
    has, with the guest path mapped through a shared folder.
``windows-sandbox``
    a generated ``.wsb`` file and ``WindowsSandbox.exe``. This one is **detached**: the sandbox reports
    nothing to the process that started it, so the run is recorded as ``detached`` with the mapped
    folder its results land in. A reader is never told "no output" when the truth is "output not
    retrievable".
``remote``
    ``POST /exec`` on an M37 worker started with ``--allow-exec`` (and a token, if it has one). This is
    the "connect another computer" case: every command runs there, and ``exec pull`` brings the
    changed files back.

Nothing here pretends a backend works: each is probed, each refusal names the binary or the switch
that would enable it, and no backend is implemented that this repository cannot drive in a test.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shlex
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    NotFoundError,
    PermissionDeniedError,
    ToolError,
    ValidationError,
)
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.execution import KINDS, ExecutionTarget
from archx_agent.managers.tools import ToolContext

#: How much of a file `exec push` will send. A sync that silently truncated a file would be worse
#: than a sync that refused it.
DEFAULT_MAX_FILES = 200
DEFAULT_MAX_BYTES = 2_000_000


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Probe:
    """Whether a backend can be used here, and what it would take."""

    kind: str
    available: bool
    summary: str
    why_not: list[str]
    enable: str | None = None
    isolation: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "available": self.available,
            "summary": self.summary,
            "why_not": list(self.why_not),
            "enable": self.enable,
            "isolation": self.isolation,
            "this_machine": platform.system(),
        }


# --------------------------------------------------------------------------
# the backends
# --------------------------------------------------------------------------
def _which(name: str) -> str | None:
    return shutil.which(name)


def probe_backends(ws) -> list[Probe]:
    """What could run a command here, in the order a user should consider it."""
    system = platform.system()
    probes: list[Probe] = []

    probes.append(Probe(
        kind="local", available=True,
        summary="this machine, through the permission centre",
        why_not=[],
        isolation="capability grants only - not a boundary for the machine itself",
    ))

    # Whether an *endpoint* is configured is a property of the target, not of this machine: a named
    # remote target carries its own address, so the probe only asks whether sending is allowed at all.
    remote_on = bool(ws.config.get("remote.enabled", False))
    probes.append(Probe(
        kind="remote", available=remote_on,
        summary="another machine running `archx-agent remote worker --allow-exec`",
        why_not=[] if remote_on else [
            "remote compute is off: `archx-agent config set remote.enabled true`"
        ],
        enable=(
            "archx-agent remote worker --host 0.0.0.0 --allow-exec --token … then "
            "archx-agent exec add remote --name vm1 --endpoint http://…"
        ),
        isolation="a separate machine: it can only damage itself",
    ))

    docker = _which("docker")
    probes.append(Probe(
        kind="docker", available=bool(docker),
        summary="a container per command: --rm, --network none, the working directory mounted",
        why_not=[] if docker else [
            "the docker CLI is not on PATH here, so no container can be started",
        ],
        enable="install Docker, then: archx-agent exec add docker --image debian:12",
        isolation="a container: the filesystem you mount and nothing else",
    ))

    wsl = _which("wsl.exe") or _which("wsl")
    probes.append(Probe(
        kind="wsl", available=bool(wsl) and system == "Windows",
        summary="a WSL distribution, as a second Linux environment",
        why_not=[] if (wsl and system == "Windows") else (
            [f"this is {system}; WSL exists only on Windows"] if system != "Windows"
            else ["wsl.exe is not on PATH: enable WSL in Windows features"]
        ),
        enable="wsl --install, then: archx-agent exec add wsl --distro Ubuntu",
        isolation="**not a boundary**: /mnt/c is your own disk (the note on each run says so)",
    ))

    sandbox = _which("WindowsSandbox.exe")
    probes.append(Probe(
        kind="windows-sandbox", available=bool(sandbox) and system == "Windows",
        summary="a disposable Windows VM per run, driven by a generated .wsb",
        why_not=[] if (sandbox and system == "Windows") else (
            [f"this is {system}; Windows Sandbox exists only on Windows 10/11 Pro, Enterprise or Education"]
            if system != "Windows" else [
                "WindowsSandbox.exe is not on PATH: enable 'Windows Sandbox' in "
                "Windows Features (Pro/Enterprise/Education, virtualization enabled in BIOS)"
            ]
        ),
        enable="Turn on Windows Sandbox, then: archx-agent exec add windows-sandbox",
        isolation="a disposable VM: everything is discarded when the sandbox closes",
    ))

    vmrun = _which("vmrun")
    probes.append(Probe(
        kind="vmware", available=bool(vmrun),
        summary="a VMware VM you already have, via vmrun runScriptInGuest",
        why_not=[] if vmrun else ["vmrun is not on PATH (VMware Workstation/Fusion is not installed)"],
        enable="install VMware, then: archx-agent exec add vmware --vm /path/to.vmx",
        isolation="a VM you own: snapshots are yours to take",
    ))

    vbox = _which("VBoxManage")
    probes.append(Probe(
        kind="virtualbox", available=bool(vbox),
        summary="a VirtualBox VM you already have, via VBoxManage guestcontrol run",
        why_not=[] if vbox else ["VBoxManage is not on PATH (VirtualBox is not installed)"],
        enable="install VirtualBox, then: archx-agent exec add virtualbox --vm name",
        isolation="a VM you own",
    ))
    return probes


def build_invocation(
    target: ExecutionTarget, command: str, cwd: str
) -> tuple[str, dict[str, Any]]:
    """The exact string that will be executed, and a note about what boundary it gives.

    Kept as a pure function so each backend's wrapper can be read (and tested) without running
    anything: the difference between a sandbox and a claim is whether the wrapper is really there.
    """
    kind = target.kind
    spec = target.spec or {}
    if kind == "local":
        # A *command line*, not an argv: `exec run "echo a && echo b"` must mean the same thing on the
        # local target as it does inside `sh -lc` on the others. A local run is still a sandbox-less
        # shell, and the note says so.
        shell_parts = ["cmd", "/c", command] if platform.system() == "Windows" else ["sh", "-lc", command]
        return " ".join(shlex.quote(part) for part in shell_parts), {
            "detached": False,
            "note": "ran on this machine - no isolation beyond the permission centre",
        }
    if kind == "docker":
        image = str(spec.get("image") or "debian:12")
        network = str(spec.get("network") or "none")
        # An absolute host path: `-v .:/work` means "wherever docker was started", which is a
        # different directory if the run is ever replayed from somewhere else.
        host = str(Path(cwd).expanduser().resolve())
        parts = [
            "docker", "run", "--rm", "--network", network,
            "-v", f"{host}:/work", "-w", "/work",
        ]
        for name, value in sorted((spec.get("env") or {}).items()):
            parts += ["-e", f"{name}={value}"]
        parts += [image, "sh", "-lc", command]
        return " ".join(shlex.quote(part) for part in parts), {
            "detached": False,
            "note": f"ran in the container image {image} with network {network}",
        }
    if kind == "wsl":
        distro = str(spec.get("distro") or "")
        parts = ["wsl.exe"]
        if distro:
            parts += ["-d", distro]
        parts += ["-e", "sh", "-lc", command]
        return " ".join(shlex.quote(part) for part in parts), {
            "detached": False,
            "note": "ran in WSL - /mnt/c is your own disk, so this is a second environment, not a boundary",
        }
    if kind == "vmware":
        vmx = str(spec.get("vm") or "")
        if not vmx:
            raise ValidationError("a vmware target needs `--vm /path/to.vmx`")
        guest = str(spec.get("guest_script") or "C:\\archx\\run.bat")
        parts = ["vmrun", "-T", str(spec.get("product") or "ws")]
        if spec.get("user"):
            parts += ["-gu", str(spec["user"])]
        parts += ["runScriptInGuest", vmx, guest, command]
        return " ".join(shlex.quote(part) for part in parts), {
            "detached": False,
            "note": "ran inside the VMware guest through vmrun",
        }
    if kind == "virtualbox":
        vm = str(spec.get("vm") or "")
        if not vm:
            raise ValidationError("a virtualbox target needs `--vm <name>`")
        parts = ["VBoxManage", "guestcontrol", vm, "run", "--exe", "/bin/sh"]
        if spec.get("user"):
            parts += ["--username", str(spec["user"])]
        parts += ["--", "/bin/sh", "-c", command]
        return " ".join(shlex.quote(part) for part in parts), {
            "detached": False,
            "note": "ran inside the VirtualBox guest through guestcontrol",
        }
    if kind == "windows-sandbox":
        # There is no argv that streams output back: the sandbox is a separate VM whose process tree
        # is not ours. What we can do is what the platform offers - a .wsb with a mapped folder and a
        # logon command - and then read the folder.
        return "", {
            "detached": True,
            "note": (
                "Windows Sandbox runs the command in a disposable VM and reports nothing back; "
                "results appear in the mapped folder named on this run"
            ),
        }
    raise ValidationError(f"no invocation is defined for the backend {kind!r}")


def sandbox_config(target: ExecutionTarget, command: str, *, host_dir: str,
                   guest_dir: str = "C:\\archx") -> str:
    """The ``.wsb`` for a Windows Sandbox run: a mapped folder, no clipboard, no networking.

    Generated as a pure function because that is the only part of this backend that can be checked on
    a machine that is not Windows - and it is the part that decides whether the result is retrievable
    at all, so it should be readable and tested rather than assembled in place.
    """
    spec = target.spec or {}
    # `--network none` is a *string*, and a string is truthy: reading it as a boolean turned the
    # sandbox's networking on for the exact value that means "off". Only an explicit opt-out of
    # "none" enables it.
    network = str(spec.get("network") or "none").strip().lower()
    networking = "Disable" if network in ("", "none", "off", "false", "0") else "Enable"
    readonly = "true" if spec.get("read_only") else "false"
    log = str(spec.get("log_file") or "archx-exec.log")
    return (
        "<Configuration>\n"
        f"  <Networking>{networking}</Networking>\n"
        "  <ClipboardRedirection>Disable</ClipboardRedirection>\n"
        "  <MappedFolders>\n"
        "    <MappedFolder>\n"
        f"      <HostFolder>{host_dir}</HostFolder>\n"
        f"      <SandboxFolder>{guest_dir}</SandboxFolder>\n"
        f"      <ReadOnly>{readonly}</ReadOnly>\n"
        "    </MappedFolder>\n"
        "  </MappedFolders>\n"
        "  <LogonCommand>\n"
        f"    <Command>cmd.exe /c cd /d {guest_dir} &amp;&amp; {command} &gt; {guest_dir}\\{log} 2&gt;&amp;1</Command>\n"
        "  </LogonCommand>\n"
        "</Configuration>\n"
    )


class ExecutionService:
    """Run a command on a chosen backend, and record where it ran and what came back."""

    def __init__(self, ws) -> None:
        self.ws = ws

    # -- plumbing ---------------------------------------------------------
    @property
    def manager(self):
        return self.ws.execution

    def _execute(self, name: str, arguments: dict[str, Any], purpose: str):
        run = self.ws.tools.execute(
            name, arguments, context=ToolContext(purpose=purpose), requester="execution"
        )
        if run.status == "denied":
            approval = getattr(run, "approval_id", None)
            if approval:
                raise ApprovalRequiredError(
                    f"{name} needs approval: approve {approval} or grant the capability",
                    approval_id=approval,
                )
            raise PermissionDeniedError(run.error or f"{name} was refused")
        if run.status == "failed":
            raise ToolError(run.error or f"{name} failed")
        return run

    def _artifacts_dir(self) -> Path:
        base = Path(self.ws.config.path("paths.artifacts")) / "execution"
        base.mkdir(parents=True, exist_ok=True)
        return base

    # -- probing ----------------------------------------------------------
    def probes(self) -> list[dict[str, Any]]:
        return [probe.to_dict() for probe in probe_backends(self.ws)]

    def probe(self, kind: str) -> dict[str, Any]:
        for probe in probe_backends(self.ws):
            if probe.kind == kind:
                return probe.to_dict()
        raise ValidationError(f"unknown backend {kind!r} (this build knows {', '.join(KINDS)})")

    def ensure(self, kind: str, *, name: str | None = None, endpoint: str | None = None,
               spec: dict[str, Any] | None = None) -> ExecutionTarget:
        """Add a target if it is not there, and refuse to add one this machine cannot use."""
        probed = self.probe(kind)
        existing = [target for target in self.manager.targets() if target.name == (name or kind)]
        if existing:
            return existing[0]
        if not probed["available"] and kind != "local":
            # A target that cannot run is still *recorded* - as refused, with the reason - because
            # "I set this up and it did not work" is exactly the thing a ledger should keep.
            return self.manager.add_target(
                kind=kind, name=name or kind, endpoint=endpoint, spec=spec or {},
                status="refused", refusal="; ".join(probed["why_not"]) or None,
            )
        return self.manager.add_target(
            kind=kind, name=name or kind, endpoint=endpoint, spec=spec or {}, status="probed"
        )

    def blockers(self, target: ExecutionTarget) -> list[str]:
        """Why this target cannot run *now*. The probe is reality; the row's refusal is history.

        A target recorded while a backend was missing must start working when the backend arrives -
        otherwise the first probe would be a life sentence - so the stored refusal only speaks when
        the fresh probe still fails, and then it speaks with the probe's own words.
        """
        reasons: list[str] = []
        if not self.ws.config.get("execution.enabled", False):
            reasons.append(
                "execution is off: `archx-agent config set execution.enabled true` "
                "(a command in a sandbox is still a command)"
            )
        if target.kind != "local":
            probed = self.probe(target.kind)
            reasons.extend(probed["why_not"])
        if target.kind == "remote" and not (
            target.endpoint or str(self.ws.config.get("remote.endpoint", "") or "").strip()
        ):
            reasons.append(
                "this remote target has no endpoint: `archx-agent exec add remote --name vm1 "
                "--endpoint http://host:9001`, or set remote.endpoint"
            )
        # The same sentence twice is noise: a recorded refusal and a failed probe usually agree.
        seen: set[str] = set()
        unique: list[str] = []
        for reason in reasons:
            if reason in seen:
                continue
            seen.add(reason)
            unique.append(reason)
        return unique

    # -- running ----------------------------------------------------------
    def _resolve(self, wanted: str | None) -> ExecutionTarget:
        """A target by name or kind; `local` always exists, even before a row is written."""
        name = (wanted or str(self.ws.config.get("execution.target", "local") or "local")).strip()
        try:
            return self.manager.target(name)
        except NotFoundError:
            if name != "local":
                raise
            return self.ensure("local")

    def run(
        self,
        command: str,
        *,
        target: str | None = None,
        cwd: str | None = None,
        timeout: int | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        resolved = self._resolve(target)
        reasons = self.blockers(resolved)
        if reasons:
            row = self.manager.begin(
                kind=resolved.kind, command=command, target_id=resolved.id, cwd=cwd,
                invocation=None, task_id=task_id,
            )
            finished = self.manager.finish(
                row.id, status="refused", note="; ".join(reasons), exit_code=None
            )
            payload = self._view(finished)
            payload["reasons"] = reasons
            return payload

        workdir = cwd or str(self.ws.config.get("execution.project", "") or ".")
        if resolved.kind == "remote":
            return self._run_remote(resolved, command, workdir, timeout, task_id)

        try:
            invocation, meta = build_invocation(resolved, command, workdir)
        except ValidationError as exc:
            row = self.manager.begin(
                kind=resolved.kind, command=command, target_id=resolved.id, cwd=workdir,
                task_id=task_id,
            )
            finished = self.manager.finish(row.id, status="refused", note=str(exc))
            payload = self._view(finished)
            payload["reasons"] = [str(exc)]
            return payload
        if resolved.kind == "windows-sandbox":
            return self._run_windows_sandbox(resolved, command, workdir, timeout, task_id, meta)

        limit = int(timeout or self.ws.config.get("execution.timeout", 60) or 60)
        row = self.manager.begin(
            kind=resolved.kind, command=command, target_id=resolved.id, cwd=workdir,
            invocation=invocation, task_id=task_id,
        )
        try:
            result = self.ws.tools.execute(
                "shell.run",
                {"command": invocation, "cwd": workdir, "timeout": limit},
                context=ToolContext(purpose=f"exec {resolved.name}: {command[:60]}"),
                requester="execution",
            )
        except (ApprovalRequiredError, PermissionDeniedError, ToolError) as exc:
            # The permission centre refused, so nothing ran. That is a row with the reason and the
            # approval id in it, not an exception that loses the attempt.
            approval = getattr(exc, "approval_id", None)
            detail = str(exc) if not approval else f"{exc}"
            finished = self.manager.finish(row.id, status="refused", note=detail)
            payload = self._view(finished)
            payload["reasons"] = [detail]
            payload["approval_id"] = approval
            return payload
        if result.status == "denied":
            approval = getattr(result, "approval_id", None)
            detail = result.error or "shell.run was refused"
            finished = self.manager.finish(row.id, status="refused", note=detail)
            payload = self._view(finished)
            payload["reasons"] = [detail]
            payload["approval_id"] = approval
            return payload
        payload = dict(result.result or {})
        status = "timeout" if payload.get("timed_out") else (
            "ok" if int(payload.get("exit_code") or 0) == 0 else "failed"
        )
        artifact_paths = self._write_outputs(row.id, payload)
        finished = self.manager.finish(
            row.id,
            status=status,
            exit_code=payload.get("exit_code"),
            duration_ms=payload.get("duration_ms"),
            stdout=str(payload.get("stdout") or ""),
            stderr=str(payload.get("stderr") or ""),
            stdout_path=artifact_paths.get("stdout"),
            stderr_path=artifact_paths.get("stderr"),
            truncated=bool(payload.get("truncated")),
            note=meta.get("note"),
        )
        return self._view(finished)

    def _write_outputs(self, run_id: str, payload: dict[str, Any]) -> dict[str, str]:
        """Keep stdout and stderr as artifacts, so a run's evidence outlives the terminal."""
        paths: dict[str, str] = {}
        for stream in ("stdout", "stderr"):
            text = str(payload.get(stream) or "")
            if not text:
                continue
            try:
                written = self._execute(
                    "fs.write",
                    {"path": f"{run_id}.{stream}.txt", "content": text, "create_parents": True},
                    f"execution {stream} {run_id}",
                )
            except (ToolError, PermissionDeniedError):
                # Losing the copy must not lose the run: the row keeps the text either way.
                continue
            paths[stream] = str((written.result or {}).get("path") or "")
        return paths

    def _run_windows_sandbox(
        self, target: ExecutionTarget, command: str, workdir: str, timeout: int | None,
        task_id: str | None, meta: dict[str, Any],
    ) -> dict[str, Any]:
        probe = self.probe("windows-sandbox")
        config = sandbox_config(target, command, host_dir=workdir)
        row = self.manager.begin(
            kind=target.kind, command=command, target_id=target.id, cwd=workdir,
            invocation="WindowsSandbox.exe <generated>.wsb", task_id=task_id,
        )
        if not probe["available"]:
            finished = self.manager.finish(
                row.id, status="refused", note="; ".join(probe["why_not"]), detached=True
            )
            payload = self._view(finished)
            payload["reasons"] = probe["why_not"]
            return payload
        written = self._execute(
            "fs.write",
            {"path": f"{row.id}.wsb", "content": config, "create_parents": True},
            f"windows sandbox config {row.id}",
        )
        wsb = str((written.result or {}).get("path") or f"{row.id}.wsb")
        launch = f"WindowsSandbox.exe {shlex.quote(workdir)}/{wsb}"
        self.ws.tools.execute(
            "shell.run", {"command": launch, "cwd": workdir, "timeout": int(timeout or 30)},
            context=ToolContext(purpose=f"windows sandbox launch {row.id}"),
            requester="execution",
        )
        finished = self.manager.finish(
            row.id, status="detached", detached=True,
            note=(
                f"{meta.get('note')}; the generated config is {wsb} and the output lands in "
                f"{workdir}/archx-exec.log when the sandbox writes it"
            ),
        )
        return self._view(finished)

    def _run_remote(
        self, target: ExecutionTarget, command: str, workdir: str, timeout: int | None,
        task_id: str | None,
    ) -> dict[str, Any]:
        endpoint = (target.endpoint or str(self.ws.config.get("remote.endpoint", "") or "")).rstrip("/")
        if not endpoint:
            raise ValidationError("this remote target has no endpoint recorded")
        row = self.manager.begin(
            kind="remote", command=command, target_id=target.id, cwd=workdir,
            invocation=f"POST {endpoint}/exec", task_id=task_id,
        )
        body = json.dumps({
            "command": command,
            "cwd": target.spec.get("cwd") or ".",
            "timeout": int(timeout or self.ws.config.get("execution.timeout", 60) or 60),
        }).encode("utf-8")
        try:
            answer = self._post(f"{endpoint}/exec", body)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            finished = self.manager.finish(
                row.id, status="failed", note=f"the endpoint could not be reached: {exc}"
            )
            payload = self._view(finished)
            payload["reasons"] = [f"{endpoint} could not be reached: {exc}"]
            return payload
        if answer.get("refused"):
            finished = self.manager.finish(row.id, status="refused", note=str(answer["refused"]))
            payload = self._view(finished)
            payload["reasons"] = [str(answer["refused"])]
            return payload
        artifacts = self._write_outputs(row.id, answer)
        finished = self.manager.finish(
            row.id,
            status="timeout" if answer.get("timed_out") else (
                "ok" if int(answer.get("exit_code") or 0) == 0 else "failed"
            ),
            exit_code=answer.get("exit_code"),
            duration_ms=answer.get("duration_ms"),
            stdout=str(answer.get("stdout") or ""),
            stderr=str(answer.get("stderr") or ""),
            stdout_path=artifacts.get("stdout"),
            stderr_path=artifacts.get("stderr"),
            truncated=bool(answer.get("truncated")),
            note=f"ran on {answer.get('machine') or endpoint}",
        )
        payload = self._view(finished)
        payload["machine"] = answer.get("machine")
        return payload

    # -- http -------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        token = str(self.ws.config.get("remote.worker_token", "") or "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _post(self, url: str, body: bytes, *, timeout: float | None = None) -> dict[str, Any]:
        limit = float(timeout or self.ws.config.get("remote.timeout", 10) or 10)
        request = urllib.request.Request(url, data=body, method="POST", headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=limit) as response:  # noqa: S310 - http(s)
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # A 401/403 from the worker is an answer, not a network failure: the body says why.
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except ValueError:
                raise
            payload.setdefault("refused", f"the worker answered {exc.code}: {raw[:200]}")
            return payload

    def _get(self, url: str, *, timeout: float | None = None) -> dict[str, Any]:
        limit = float(timeout or self.ws.config.get("remote.timeout", 10) or 10)
        request = urllib.request.Request(url, method="GET", headers=self._headers())
        with urllib.request.urlopen(request, timeout=limit) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))

    # -- the project boundary ---------------------------------------------
    def _endpoint(self, target: ExecutionTarget) -> str:
        endpoint = (target.endpoint or str(self.ws.config.get("remote.endpoint", "") or "")).rstrip("/")
        if not endpoint:
            raise ValidationError("this remote target has no endpoint recorded")
        return endpoint

    def _read_local(self, root: Path, limit: int) -> dict[str, str]:
        files: dict[str, str] = {}
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if any(part.startswith(".") for part in path.relative_to(root).parts):
                continue  # a project's .git is not what a sandbox needs
            if len(files) >= limit:
                break
            if path.stat().st_size > DEFAULT_MAX_BYTES:
                continue
            files[path.relative_to(root).as_posix()] = path.read_text(
                encoding="utf-8", errors="replace"
            )
        return files

    def push(self, target: str, *, root: str | None = None, limit: int | None = None) -> dict[str, Any]:
        """Send the project to the target, and record every file with its hash."""
        resolved = self._resolve(target)
        if resolved.kind != "remote":
            raise ValidationError(
                "only a remote target needs a push: a container, WSL or a VM reads the directory you "
                "mounted, so there is nothing to copy"
            )
        reasons = self.blockers(resolved)
        if reasons:
            raise ValidationError("; ".join(reasons))
        base = Path(root or str(self.ws.config.get("execution.project", "") or ".")).resolve()
        if not base.is_dir():
            raise ValidationError(f"{base} is not a directory")
        files = self._read_local(base, int(limit or DEFAULT_MAX_FILES))
        if not files:
            raise ValidationError(f"there is nothing to push under {base}")
        answer = self._post(
            f"{self._endpoint(resolved)}/files",
            json.dumps({"files": files, "root": resolved.spec.get("workdir") or "project"}).encode(),
            timeout=float(self.ws.config.get("remote.timeout", 10) or 10) * 6,
        )
        written = {item["path"]: item for item in answer.get("written") or []}
        for relpath, text in sorted(files.items()):
            remote = written.get(relpath) or {}
            self.manager.record_file(
                path=relpath, direction="push", status="applied", target_id=resolved.id,
                sha256_local=_sha(text), sha256_remote=remote.get("sha256"),
                size=len(text.encode("utf-8")),
            )
        return {
            "target": resolved.name,
            "root": str(base),
            "files": len(files),
            "bytes": sum(len(text.encode("utf-8")) for text in files.values()),
            "paths": sorted(files),
        }

    def pull(self, target: str, *, root: str | None = None, force: bool = False) -> dict[str, Any]:
        """Bring back what changed, and refuse to clobber an edit made here in the meantime."""
        resolved = self._resolve(target)
        if resolved.kind != "remote":
            raise ValidationError("only a remote target has files to pull back")
        reasons = self.blockers(resolved)
        if reasons:
            raise ValidationError("; ".join(reasons))
        base = Path(root or str(self.ws.config.get("execution.project", "") or ".")).resolve()
        base.mkdir(parents=True, exist_ok=True)
        answer = self._get(
            f"{self._endpoint(resolved)}/files",
            timeout=float(self.ws.config.get("remote.timeout", 10) or 10) * 6,
        )
        remote_files = {item["path"]: item for item in answer.get("files") or []}
        applied: list[str] = []
        skipped: list[str] = []
        conflicts: list[str] = []
        for relpath, item in sorted(remote_files.items()):
            local_path = base / relpath
            local_text = (
                local_path.read_text(encoding="utf-8", errors="replace")
                if local_path.is_file() else None
            )
            local_sha = _sha(local_text) if local_text is not None else None
            remote_sha = str(item.get("sha256") or "")
            pushed = self.manager.last_push(resolved.id, relpath)
            base_sha = pushed.sha256_local if pushed else None
            if local_sha == remote_sha:
                self.manager.record_file(
                    path=relpath, direction="pull", status="unchanged", target_id=resolved.id,
                    sha256_local=local_sha, sha256_remote=remote_sha, size=item.get("bytes"),
                )
                skipped.append(relpath)
                continue
            local_changed = base_sha is not None and local_sha is not None and local_sha != base_sha
            remote_changed = base_sha is None or remote_sha != base_sha
            if local_changed and remote_changed and not force:
                self.manager.record_file(
                    path=relpath, direction="pull", status="conflict", target_id=resolved.id,
                    sha256_local=local_sha, sha256_remote=remote_sha, size=item.get("bytes"),
                    note=(
                        "changed here since it was pushed and changed on the target too; "
                        "not overwritten - `exec pull --force` replaces it, or merge by hand"
                    ),
                )
                conflicts.append(relpath)
                continue
            self._execute(
                "fs.write",
                {"path": str(local_path), "content": str(item.get("content") or ""),
                 "create_parents": True},
                f"execution pull {relpath}",
            )
            self.manager.record_file(
                path=relpath, direction="pull", status="applied", target_id=resolved.id,
                sha256_local=_sha(str(item.get("content") or "")), sha256_remote=remote_sha,
                size=item.get("bytes"),
                note="moved here by force" if (local_changed and force) else None,
            )
            applied.append(relpath)
        return {
            "target": resolved.name,
            "root": str(base),
            "applied": applied,
            "skipped": skipped,
            "conflicts": conflicts,
            "files": len(remote_files),
        }

    # -- reading ----------------------------------------------------------
    def _view(self, run) -> dict[str, Any]:
        payload = run.to_dict()
        payload["sentence"] = self._sentence(run)
        payload["reasons"] = [] if run.status != "refused" else [
            part.strip() for part in (run.note or "").split("; ") if part.strip()
        ]
        return payload

    @staticmethod
    def _sentence(run) -> str:
        where = {
            "local": "on this machine",
            "remote": "on another machine",
            "docker": "in a container",
            "wsl": "in WSL",
            "vmware": "inside a VMware guest",
            "virtualbox": "inside a VirtualBox guest",
            "windows-sandbox": "in a Windows Sandbox",
        }.get(run.kind, f"on a {run.kind} target")
        if run.status == "refused":
            return f"nothing ran: {run.kind} is not usable here"
        if run.status == "detached":
            return f"`{run.command}` was started {where}, which reports nothing back"
        if run.status == "timeout":
            return f"`{run.command}` ran {where} and was killed at the timeout"
        if run.status == "failed" and run.exit_code is None:
            return f"`{run.command}` never ran {where}: {run.note}"
        return f"`{run.command}` ran {where} and exited {run.exit_code}"

    def view(self, wanted: str) -> dict[str, Any]:
        return self._view(self.manager.run_(wanted))

    def runs(self, *, target: str | None = None, status: str | None = None,
             limit: int = 50) -> list[dict[str, Any]]:
        target_id = None
        if target:
            target_id = self.manager.target(target).id
        return [
            run.to_dict() for run in self.manager.runs(
                target_id=target_id, status=status, limit=limit
            )
        ]

    def targets(self) -> list[dict[str, Any]]:
        return [target.to_dict() for target in self.manager.targets()]

    def stats(self) -> dict[str, Any]:
        base = self.manager.stats()
        base["enabled"] = bool(self.ws.config.get("execution.enabled", False))
        base["default_target"] = str(self.ws.config.get("execution.target", "local") or "local")
        base["probes"] = {
            probe["kind"]: probe["available"] for probe in self.probes()
        }
        return base
