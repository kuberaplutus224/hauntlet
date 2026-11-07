"""Cursed Repo: a small Python repository with one failing function and traps
planted in the files a coding agent reads.

Registered as two rooms sharing one implementation, ``CursedRepoRoom``:
``cursed-repo`` (five traps on five surface kinds, config ``CURSED_REPO``) and
``cursed-repo-tests`` (one trap in the failing test file, config
``CURSED_REPO_TESTS``).
"""

from __future__ import annotations

from hauntlet.rooms.cursed_repo.config import CURSED_REPO, CURSED_REPO_TESTS
from hauntlet.rooms.cursed_repo.room import CursedRepoRoom

__all__ = ["CURSED_REPO", "CURSED_REPO_TESTS", "CursedRepoRoom"]
