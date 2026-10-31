"""Model catalogue (M15) and discovery.

Three kinds of information are stored **separately** and never conflated:

* ``facts`` - things we observed (file size, hash, path exists, a capability
  test that returned valid output);
* ``claims`` - things a model card, filename or provider says (unverified);
* ``user_metadata`` - what the user chose (preferred for task X, notes, tags).

A model is ``usable`` only when the file exists (local) or the endpoint is
configured (remote). Capabilities are ``verified`` only by a recorded test, or
``inferred`` from metadata, or ``unverified``.

Public compatibility surface. Implementation responsibilities live in sibling modules.
"""

from .manager import ModelManager as ModelManager
from .constants import (
    MODEL_TABLES as MODEL_TABLES,
    STATES as STATES,
    VERIFICATION_STATES as VERIFICATION_STATES,
    CAPABILITY_STATES as CAPABILITY_STATES,
    RUNTIME_BASELINE_CAPABILITIES as RUNTIME_BASELINE_CAPABILITIES,
    _QUANT_RE as _QUANT_RE,
    _PARAM_RE as _PARAM_RE,
)
from .records import ModelRecord as ModelRecord, _from_row as _from_row
from .naming import parse_gguf_name as parse_gguf_name


__all__ = [
    "ModelManager",
    "ModelRecord",
    "parse_gguf_name",
    "STATES",
    "VERIFICATION_STATES",
]
