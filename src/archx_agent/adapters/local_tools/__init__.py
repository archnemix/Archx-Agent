"""Local filesystem and process operations used by the built-in tools.

This module **executes**; it never decides whether it may. Every call is made by
``managers/tools.py`` *after* the permission centre said yes, and the only thing
keeping a path inside the sandbox is :func:`archx_agent.helpers.paths.resolve_within`
- not the caller's good manners.

Deliberate choices:

* No shell. ``shell.run`` splits its command with :func:`shlex.split` and calls
  :func:`subprocess.run` with ``shell=False``, so ``;`` and ``|`` are literal
  arguments rather than a second, unreviewed command line.
* A child process gets a minimal environment: ``PATH``, ``HOME`` (the Archx home,
  not the real one), ``LANG`` and ``TMPDIR``. Nothing else - no API keys, no
  ``ARCHX_*`` overrides, so a tool cannot read the agent's own credentials.
* Output is capped and marked truncated instead of being silently dropped.
* Every operation reports what it touched (path, bytes, hash) so the trace can
  answer "what exactly changed?".

Public compatibility surface. Implementation responsibilities live in sibling modules.
"""

from .runtime import LocalToolRuntime as LocalToolRuntime
from .constants import _BINARY_SNIFF as _BINARY_SNIFF
from .hashing import sha256_bytes as sha256_bytes
from .output import _clip as _clip
from .roots import default_roots as default_roots, ensure_roots as ensure_roots


__all__ = ["LocalToolRuntime", "sha256_bytes", "default_roots", "ensure_roots"]
