"""The coding workspace: edit, run and test code, with every step going through the tool layer.

The rule this module exists to keep
-----------------------------------
**A coding session is not a way around the permission centre.** Every file read, every write and
every command goes through :meth:`ToolManager.execute`, which means the same capabilities, the same
grants and the same approvals as `archx-agent tools run fs.write`. There is no private back door
for the editor: if `fs.write` is not granted, `code write` is refused, and the refusal names the
approval rather than half-writing the file.

What that buys
--------------
* **Edits are reviewable.** Each one is a row with a unified diff, the checksums either side of
  it, and an artifact attached to the session's task. `code diff` prints the session's whole patch.
* **Commands are recorded.** The runner stores the command as typed, the argv that actually ran,
  the directory, the exit code, the duration and the output - and refusals too, because "this was
  attempted and denied" is evidence.
* **Sessions are reproducible.** A run can be replayed by id (`code rerun`), and the session's
  task is an ordinary task, so `tasks reproduce` works on it unchanged.

Session roots
-------------
A session opens on a directory *inside the tool roots*. That is not a formality: the tools resolve
every path against those roots, so the session's boundary is the same boundary as everything else,
and a path that escapes it is refused by the tool runtime rather than by a second implementation
of the same rule here.

Public compatibility surface. Implementation responsibilities live in sibling modules.
"""

from .service import CodingWorkspace as CodingWorkspace
from .constants import CHECKS_FILE as CHECKS_FILE, _CHECK_NAME as _CHECK_NAME
from .records import Check as Check
from .checks import _parse_checks as _parse_checks, _timeout_of as _timeout_of
from .patches import _unified_diff as _unified_diff
