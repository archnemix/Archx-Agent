"""ExtensionManager public imports; feature responsibilities live in sibling modules."""

from .manager import ExtensionManager as ExtensionManager
from .records import EXTENSION_TABLES as EXTENSION_TABLES
from .records import _NAME_RE as _NAME_RE
from .records import _SAFE as _SAFE
from .records import MANIFEST_NAME as MANIFEST_NAME
from .records import SUPPORTED_ENTRY as SUPPORTED_ENTRY
from .records import _safe as _safe
from .records import Extension as Extension
from .records import _extension_from_row as _extension_from_row
from .manifest import validate_manifest as validate_manifest

__all__ = [
    "EXTENSION_TABLES",
    "MANIFEST_NAME",
    "Extension",
    "ExtensionManager",
    "validate_manifest",
]
