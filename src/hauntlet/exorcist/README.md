# The Exorcist

The Exorcist reads a finalized run, generates the Kiro guardrails that would
have stopped each trap that fired (steering, hooks, an `mcp.json` and a
`sandbox.json`), applies them, re-runs the same rooms, and reports the
before/after delta. Guardrails are written to a scratch directory, never into
this repository's own `.kiro/` or a user's config.

There are two re-run paths, and the delta report always says which one produced
the after result:

- **real Kiro** — the tester applies the bundle by hand and runs their own
  client; Hauntlet never runs or imitates Kiro;
- **the built-in demo agent** — a deterministic, model-free agent that reads the
  generated config through the interpreter in `interpreter.py` and changes its
  behaviour only through that config.

Guardrails are chosen from each trap's threat class (where its text lives and
what it asks for), never from trap text, so a cleared score means something
outside this range. Every generated item cites the traps it addresses in the
bundle manifest (`EXORCISM.md`), never in a guardrail file.

The hook runner (`hookrun.py`) executes a generated guard script under Kiro's
stdin/exit-code protocol and confines it with an audit hook (no network, no
processes, no writes). That audit hook is defence in depth for our own
generated scripts, not a sandbox for running untrusted user-supplied code.
