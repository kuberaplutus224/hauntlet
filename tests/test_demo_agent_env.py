"""The demo agent's environment is the room's real-client channel (exorcist 8.9, 9.9, EP17, task 11.3).

For every demo room and several seeds:

- the agent environment the demo uses, and every environment it hands the hook
  runner, equal ``{k: materials.env[k] for k in real_client_env}``;
- for the Poltergeist rooms that is ``{}``, with no canary value;
- each file room's declared ``real_client_env`` equals the keys its ``setup``
  plants;
- the demo agent never calls the toolbox's environment accessor.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _demo_support import DEMO_ROOMS, canary_values, drive

from hauntlet.agents.demo import DemoAgent, baseline_for
from hauntlet.exorcist import hookrun
from hauntlet.exorcist.profiles import profile_for, real_client_env

MCP_ROOMS = ("poltergeist", "poltergeist-legacy")
SEEDS = range(3)


class RecordingRunner:
    """Stands in for the hook runner, recording every environment it is given."""

    def __init__(self) -> None:
        self.envs: list[dict[str, str]] = []

    def __call__(self, script, event, env, cwd, timeout) -> hookrun.HookResult:
        self.envs.append(dict(env))
        return hookrun.HookResult(hookrun.ALLOW, 0, "")


@pytest.mark.parametrize("room", DEMO_ROOMS)
@pytest.mark.parametrize("seed", SEEDS)
def test_demo_env_equals_the_real_client_channel(tmp_path: Path, room: str, seed: int) -> None:
    scratch = tmp_path / f"{room}-{seed}"
    # A bundle for this room gives the demo real hooks whose env we can capture.
    base = drive(room, scratch / "base", DemoAgent(baseline_for(scratch / "b", room), real_client_env))
    from hauntlet.exorcist.generate import generate
    from hauntlet.exorcist.writer import write_bundle

    spec = generate(base.score, base.manifest)
    _bid, bundle = write_bundle(scratch / "ex", spec, created_at=1.0)

    runner = RecordingRunner()
    seen_env: list[dict] = []

    def channel(materials):
        env = real_client_env(materials)
        seen_env.append(dict(env))
        return env

    driven = drive(room, scratch / "run", DemoAgent(bundle, channel, runner=runner))

    expected = {k: driven.materials.env[k] for k in profile_for(room).real_client_env}
    assert seen_env and all(e == expected for e in seen_env)
    assert runner.envs, "the bundle's hooks ran, so the runner saw the env"
    assert all(e == expected for e in runner.envs)

    # The demo never calls getenv.
    assert not any(c.startswith("getenv") for c in driven.tools.calls)

    if room in MCP_ROOMS:
        assert expected == {}
        assert not any(v in str(expected) for v in canary_values(driven.canaries))


@pytest.mark.parametrize("room", ["threshold", "cursed-repo", "cursed-repo-tests"])
def test_file_room_env_names_match_setup(tmp_path: Path, room: str) -> None:
    driven = drive(room, tmp_path / room, DemoAgent(baseline_for(tmp_path / "b", room), real_client_env))
    assert profile_for(room).real_client_env == frozenset(driven.materials.env)
    assert real_client_env(driven.materials) == driven.materials.env
