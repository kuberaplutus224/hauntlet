"""Filesystem locations shared by separate processes over one event store.

``hauntlet serve``, ``hauntlet mcp`` and ``hauntlet parlor`` run as separate
processes that share the ``HAUNTLET_DB`` file. They agree on where real-client
room workspaces live by deriving it from that file, whatever their working
directories are.
"""

from __future__ import annotations

from pathlib import Path

#: Directory, beside the shared ``HAUNTLET_DB`` file, holding real-client workspaces.
SCRATCH_DIRNAME = "mcp-scratch"


def scratch_root_beside(db_path: Path) -> Path:
    """Root of real-client workspaces: a fixed directory beside the shared store."""
    return Path(db_path).resolve().parent / SCRATCH_DIRNAME
