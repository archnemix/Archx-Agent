"""Public ModelRouter API; responsibility owners live in this package."""

from .service import ModelRouter as ModelRouter
from .records import PROBEABLE as PROBEABLE
from .records import ACCEPTED_BY_DEFAULT as ACCEPTED_BY_DEFAULT
from .records import Candidate as Candidate
from .records import RoutingDecision as RoutingDecision
from .records import _is_loopback as _is_loopback
from .records import _probe_prompt as _probe_prompt
from .records import _require_json as _require_json
__all__ = [
    "ModelRouter",
    "Candidate",
    "RoutingDecision",
    "PROBEABLE",
    "ACCEPTED_BY_DEFAULT",
]
