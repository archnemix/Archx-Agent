"""The permission centre: who may do what, for how long, and who said so.

Rules this module exists to enforce:

* **Authority is explicit.** A capability is allowed only because a recorded
  grant says so, or because an approval was recorded for exactly that request.
  Nothing in the tool registry, an extension manifest or a model's arguments can
  create a grant.
* **A grant is narrow by construction.** It names one capability, one subject and
  one duration. Scope is *checked*, not assumed: a conversation grant does not
  apply in another conversation, and a task grant does not outlive its task.
* **An approval cannot be widened.** Approving requests exactly the capability,
  subject and scope that the user saw; there is deliberately no API to approve
  "and also allow writes".
* **Denials are recorded.** A refused operation leaves a `permission` trace event
  and (for tools) a `tool_runs` row, because "it silently did nothing" is the
  worst possible answer.

Durations, in increasing breadth:

``once``         consumed by the first successful check
``task``         valid while the same task id is in context
``conversation`` valid inside the conversation it was granted in
``project``      valid for the project it was granted in
``persistent``   valid until revoked (optionally time-boxed with ``hours``)

Public compatibility surface. Implementation responsibilities live in sibling modules.
"""

from .manager import PermissionManager as PermissionManager
from .constants import (
    PERMISSION_TABLES as PERMISSION_TABLES,
    DURATIONS as DURATIONS,
    CAPABILITIES as CAPABILITIES,
    RISK_LEVELS as RISK_LEVELS,
    APPROVAL_STATUSES as APPROVAL_STATUSES,
)
from .records import (
    Capability as Capability,
    Grant as Grant,
    Approval as Approval,
    PermissionDecision as PermissionDecision,
    _grant_from_row as _grant_from_row,
    _approval_from_row as _approval_from_row,
)
from .capabilities import (
    capability_names as capability_names,
    _validate_capability as _validate_capability,
)


__all__ = [
    "CAPABILITIES",
    "Capability",
    "DURATIONS",
    "Approval",
    "Grant",
    "PermissionDecision",
    "PermissionManager",
    "RISK_LEVELS",
    "capability_names",
]
