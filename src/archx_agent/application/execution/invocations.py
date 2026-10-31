"""Invocations operations for execution targets."""

from __future__ import annotations

import platform
import shlex
from pathlib import Path
from typing import Any

from archx_agent.helpers.exceptions import (
    ValidationError,
)
from archx_agent.managers.execution import ExecutionTarget


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
        shell_parts = (
            ["cmd", "/c", command]
            if platform.system() == "Windows"
            else ["sh", "-lc", command]
        )
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
            "docker",
            "run",
            "--rm",
            "--network",
            network,
            "-v",
            f"{host}:/work",
            "-w",
            "/work",
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


def sandbox_config(
    target: ExecutionTarget,
    command: str,
    *,
    host_dir: str,
    guest_dir: str = "C:\\archx",
) -> str:
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
