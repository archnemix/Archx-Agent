"""Backend availability probes for execution targets."""

from __future__ import annotations

import platform
import shutil

from archx_agent.application.execution.records import Probe


def _which(name: str) -> str | None:
    return shutil.which(name)


def probe_backends(ws) -> list[Probe]:
    """What could run a command here, in the order a user should consider it."""
    system = platform.system()
    probes: list[Probe] = []

    probes.append(
        Probe(
            kind="local",
            available=True,
            summary="this machine, through the permission centre",
            why_not=[],
            isolation="capability grants only - not a boundary for the machine itself",
        )
    )

    # Whether an *endpoint* is configured is a property of the target, not of this machine: a named
    # remote target carries its own address, so the probe only asks whether sending is allowed at all.
    remote_on = bool(ws.config.get("remote.enabled", False))
    probes.append(
        Probe(
            kind="remote",
            available=remote_on,
            summary="another machine running `archx-agent remote worker --allow-exec`",
            why_not=[]
            if remote_on
            else [
                "remote compute is off: `archx-agent config set remote.enabled true`"
            ],
            enable=(
                "archx-agent remote worker --host 0.0.0.0 --allow-exec --token … then "
                "archx-agent exec add remote --name vm1 --endpoint http://…"
            ),
            isolation="a separate machine: it can only damage itself",
        )
    )

    docker = _which("docker")
    probes.append(
        Probe(
            kind="docker",
            available=bool(docker),
            summary="a container per command: --rm, --network none, the working directory mounted",
            why_not=[]
            if docker
            else [
                "the docker CLI is not on PATH here, so no container can be started",
            ],
            enable="install Docker, then: archx-agent exec add docker --image debian:12",
            isolation="a container: the filesystem you mount and nothing else",
        )
    )

    wsl = _which("wsl.exe") or _which("wsl")
    probes.append(
        Probe(
            kind="wsl",
            available=bool(wsl) and system == "Windows",
            summary="a WSL distribution, as a second Linux environment",
            why_not=[]
            if (wsl and system == "Windows")
            else (
                [f"this is {system}; WSL exists only on Windows"]
                if system != "Windows"
                else ["wsl.exe is not on PATH: enable WSL in Windows features"]
            ),
            enable="wsl --install, then: archx-agent exec add wsl --distro Ubuntu",
            isolation="**not a boundary**: /mnt/c is your own disk (the note on each run says so)",
        )
    )

    sandbox = _which("WindowsSandbox.exe")
    probes.append(
        Probe(
            kind="windows-sandbox",
            available=bool(sandbox) and system == "Windows",
            summary="a disposable Windows VM per run, driven by a generated .wsb",
            why_not=[]
            if (sandbox and system == "Windows")
            else (
                [
                    f"this is {system}; Windows Sandbox exists only on Windows 10/11 Pro, Enterprise or Education"
                ]
                if system != "Windows"
                else [
                    "WindowsSandbox.exe is not on PATH: enable 'Windows Sandbox' in "
                    "Windows Features (Pro/Enterprise/Education, virtualization enabled in BIOS)"
                ]
            ),
            enable="Turn on Windows Sandbox, then: archx-agent exec add windows-sandbox",
            isolation="a disposable VM: everything is discarded when the sandbox closes",
        )
    )

    vmrun = _which("vmrun")
    probes.append(
        Probe(
            kind="vmware",
            available=bool(vmrun),
            summary="a VMware VM you already have, via vmrun runScriptInGuest",
            why_not=[]
            if vmrun
            else ["vmrun is not on PATH (VMware Workstation/Fusion is not installed)"],
            enable="install VMware, then: archx-agent exec add vmware --vm /path/to.vmx",
            isolation="a VM you own: snapshots are yours to take",
        )
    )

    vbox = _which("VBoxManage")
    probes.append(
        Probe(
            kind="virtualbox",
            available=bool(vbox),
            summary="a VirtualBox VM you already have, via VBoxManage guestcontrol run",
            why_not=[]
            if vbox
            else ["VBoxManage is not on PATH (VirtualBox is not installed)"],
            enable="install VirtualBox, then: archx-agent exec add virtualbox --vm name",
            isolation="a VM you own",
        )
    )
    return probes
