"""Poltergeist: a small MCP server with a benign tool set that rug-pulls one
tool's description after the client's first tool call.

Registered as two rooms sharing one implementation, differing only in the
protocol revision they speak: ``poltergeist`` (2026-07-28) and
``poltergeist-legacy`` (2025-11-25 and 2025-06-18).
"""

from __future__ import annotations

from hauntlet.rooms.poltergeist.config import POLTERGEIST, POLTERGEIST_LEGACY
from hauntlet.rooms.poltergeist.room import PoltergeistRoom

__all__ = ["PoltergeistRoom", "POLTERGEIST", "POLTERGEIST_LEGACY"]
