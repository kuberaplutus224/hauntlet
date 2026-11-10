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


#: Where the CLI writes reports by default (``--out``); ``hauntlet serve`` reads
#: fact-log copies from here too (approved change D32, ``HAUNTLET_REPORTS_DIR``).
DEFAULT_REPORTS_DIR = "reports"


def reports_parlor_facts_path(reports_dir: Path, run_id: str) -> Path:
    """Where ``hauntlet parlor finalize`` keeps the Parlor fact log after teardown (D32)."""
    return Path(reports_dir) / f"parlor-facts-{run_id}.jsonl"


def scratch_root_beside(db_path: Path) -> Path:
    """Root of real-client workspaces: a fixed directory beside the shared store."""
    return Path(db_path).resolve().parent / SCRATCH_DIRNAME
