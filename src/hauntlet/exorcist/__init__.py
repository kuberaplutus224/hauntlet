"""The Exorcist: generate Kiro guardrails from a finalized run, re-run, report the delta.

A consumer of scores and a producer of guardrails. It reads ``RunScore`` and
``RunManifest`` through ``RangeService`` and never decides or alters a score.
Nothing in ``hauntlet.core`` changes for it (exorcist spec, Requirement 14).

Public names other packages may import: ``CLASS_TEXT`` (the trap-class texts
the bundle manifest uses; read by the scorecard, scorecard design "D24 note").
"""

from hauntlet.exorcist.manifest import CLASS_TEXT

__all__ = ["CLASS_TEXT"]
