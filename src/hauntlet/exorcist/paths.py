"""Where the Exorcist keeps bundles: beside the shared ``HAUNTLET_DB`` (Requirement 3.1).

The same pattern as ``hauntlet.paths.scratch_root_beside``, which is left
unchanged.
"""

from __future__ import annotations

from pathlib import Path

EXORCIST_DIRNAME = "exorcist"


def exorcist_root(db_path: Path | str) -> Path:
    """Root of all bundles: a fixed directory beside the shared store."""
    return Path(db_path).resolve().parent / EXORCIST_DIRNAME
