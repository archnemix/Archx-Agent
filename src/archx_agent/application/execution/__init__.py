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

Public compatibility surface. Implementation responsibilities live in sibling modules.
"""

from .service import ExecutionService as ExecutionService
from .constants import (
    DEFAULT_MAX_FILES as DEFAULT_MAX_FILES,
    DEFAULT_MAX_BYTES as DEFAULT_MAX_BYTES,
)
from .records import Probe as Probe
from .probes import _which as _which, probe_backends as probe_backends
from .invocations import (
    build_invocation as build_invocation,
    sandbox_config as sandbox_config,
)
from .hashing import _sha as _sha
