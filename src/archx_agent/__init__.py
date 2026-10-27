"""Archx Agent - a modular, local-first AI operating environment.

Layering (enforced by tests/test_import_matrix.py):

    interfaces -> application, managers, helpers
    application -> initialization, managers, adapters, helpers
    initialization -> helpers
    managers -> adapters, helpers
    helpers -> helpers
    adapters -> helpers
"""

from __future__ import annotations

__version__ = "0.25.0"
BRAND = "Archx Agent"
CLI_NAME = "archx-agent"
