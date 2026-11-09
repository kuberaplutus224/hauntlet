"""Scratch-only writes (exorcist Requirement 3, property EP6, task 7.3).

EP6: for any target the writer is asked to use, it either writes inside the
scratch root or refuses with ``WriteRefused``. The targets tried are:

- hostile run IDs and bundle IDs;
- relative paths with ``..``, absolute paths and backslashes;
- symlinks placed in advance at each level;
- a root under a ``.kiro`` directory;
- an existing bundle directory.

It never writes under a ``.kiro`` directory or outside the root.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from hauntlet.core.levels import Level
from hauntlet.core.models import RoomScore, RunManifest, RunScore, TrapScore
from hauntlet.exorcist.generate import generate
from hauntlet.exorcist.paths import exorcist_root
from hauntlet.exorcist.writer import WriteRefused, write_bundle, write_delta, write_into
from hauntlet.rooms import default_rooms

ROOMS = default_rooms()


def _spec(run_id: str = "beforeRUN01"):
    rm = ROOMS["cursed-repo"].manifest()
    per_trap = tuple(
        TrapScore(t.trap_id, t.is_control, Level.L4 if not t.is_control else Level.L0, False, ())
        for t in rm.traps
    )
    score = RunScore(run_id, (RoomScore(rm.room, Level.L4, False, (), per_trap, True, True),), Level.L4)
    return generate(score, RunManifest(run_id, (rm,)))


def _all_files(root: Path) -> set[Path]:
    return {p for p in root.rglob("*")} if root.exists() else set()


def _outside(base: Path, root: Path) -> set[Path]:
    """Everything under ``base`` that is neither the root, an ancestor of it, nor inside it."""
    return {
        p for p in _all_files(base)
        if not (p == root or p in root.parents or p.is_relative_to(root))
    }


def _assert_inside(written: list[Path] | set[Path], root: Path) -> None:
    for p in written:
        assert p.resolve().is_relative_to(root.resolve()), p
        assert ".kiro" not in p.resolve().relative_to(root.resolve()).parts[:1]


hostile_ids = st.one_of(
    st.text(max_size=30),
    st.sampled_from(["..", "../..", "a/b", "/etc", "....../x", "abc\\def", "x" * 65, "short", ".kiro", "a b c d e f"]),
    st.from_regex(r"[A-Za-z0-9_-]{8,64}", fullmatch=True),
)


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(run_id=hostile_ids, bundle_id=hostile_ids)
def test_ep6_hostile_ids_write_inside_or_refuse(tmp_path: Path, run_id: str, bundle_id: str) -> None:
    root = tmp_path / "scratch" / "exorcist"
    outside = tmp_path / "outside"
    outside.mkdir(exist_ok=True)
    before = _outside(tmp_path, root)
    spec = replace(_spec(), before_run_id=run_id)
    try:
        _bid, bdir = write_bundle(root, spec, created_at=1.0, bundle_id=bundle_id)
    except WriteRefused:
        pass
    else:
        assert bdir.resolve().parent.parent == root.resolve()
        _assert_inside(_all_files(bdir), root)
    assert _outside(tmp_path, root) == before, "nothing written outside the root"
    assert not any(outside.iterdir())


@pytest.mark.parametrize(
    "rel",
    ["deltas/../../x.json", "/etc/passwd", "deltas/a\\b.json", "deltas//x", "deltas/./x",
     ".kiro/steering/extra.md", "bundle.json", "deltas/..", "baseline/../../../y"],
)
def test_write_into_refuses_hostile_relative_paths(tmp_path: Path, rel: str) -> None:
    root = tmp_path / "exorcist"
    _bid, bdir = write_bundle(root, _spec(), created_at=1.0)
    before = _all_files(tmp_path)
    with pytest.raises(WriteRefused):
        write_into(bdir, rel, b"x")
    assert _all_files(tmp_path) == before


def test_symlinks_placed_in_advance_are_refused(tmp_path: Path) -> None:
    root = tmp_path / "exorcist"
    outside = tmp_path / "outside"
    outside.mkdir()
    spec = _spec("symlinkRUN1")

    # (1) the run directory is a symlink to somewhere else
    root.mkdir(parents=True)
    (root / spec.before_run_id).symlink_to(outside, target_is_directory=True)
    with pytest.raises(WriteRefused):
        write_bundle(root, spec, created_at=1.0)
    assert not any(outside.iterdir())
    (root / spec.before_run_id).unlink()

    # (2) deltas/ is a symlink inside an otherwise good bundle
    _bid, bdir = write_bundle(root, spec, created_at=1.0)
    (bdir / "deltas").symlink_to(outside, target_is_directory=True)
    with pytest.raises(WriteRefused):
        write_delta(bdir, "afterRUN001", {"json": b"{}"})
    assert not any(outside.iterdir())

    # (3) the scratch root itself is a symlink
    link_root = tmp_path / "linkroot"
    link_root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(WriteRefused):
        write_bundle(link_root, _spec("symlinkRUN2"), created_at=1.0)

    # (4) the bundle directory itself is a symlink
    fake = tmp_path / "fakebundle"
    fake.symlink_to(outside, target_is_directory=True)
    with pytest.raises(WriteRefused):
        write_into(fake, "deltas/x.json", b"{}")
    assert not any(outside.iterdir())


@pytest.mark.parametrize("sub", [".kiro", ".kiro/settings", "deep/.kiro/x"])
def test_root_under_a_kiro_directory_is_refused(tmp_path: Path, sub: str) -> None:
    root = tmp_path / sub / "exorcist"
    with pytest.raises(WriteRefused, match=".kiro"):
        write_bundle(root, _spec(), created_at=1.0)
    assert not root.exists()


def test_repository_and_home_kiro_are_refused(tmp_path: Path) -> None:
    repo_kiro = Path(__file__).resolve().parent.parent / ".kiro"
    for root in (repo_kiro / "exorcist", Path("~/.kiro/exorcist")):
        with pytest.raises(WriteRefused):
            write_bundle(root, _spec(), created_at=1.0)
    assert not (repo_kiro / "exorcist").exists()


def test_existing_bundle_directory_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "exorcist"
    bid, bdir = write_bundle(root, _spec(), created_at=1.0)
    with pytest.raises(WriteRefused, match="exists"):
        write_bundle(root, _spec(), created_at=2.0, bundle_id=bid)
    # deltas are added once per after run; a second write of the same one is refused
    write_delta(bdir, "afterRUN001", {"json": b"{}", "txt": b"t"})
    with pytest.raises(WriteRefused):
        write_delta(bdir, "afterRUN001", {"json": b"{}"})
    with pytest.raises(WriteRefused):
        write_delta(bdir, "afterRUN002", {"exe": b""})


def test_exorcist_root_is_beside_the_db(tmp_path: Path) -> None:
    db = tmp_path / "state" / "range.db"
    assert exorcist_root(db) == (tmp_path / "state" / "exorcist").resolve()


def test_files_are_created_exclusively_and_not_followed(tmp_path: Path) -> None:
    root = tmp_path / "exorcist"
    _bid, bdir = write_bundle(root, _spec(), created_at=1.0)
    for p in _all_files(bdir):
        assert not p.is_symlink()
    target = tmp_path / "victim"
    target.write_text("keep")
    (bdir / "deltas").mkdir()
    os.symlink(target, bdir / "deltas" / "afterRUN009.json")
    with pytest.raises(WriteRefused):
        write_delta(bdir, "afterRUN009", {"json": b"{}"})
    assert target.read_text() == "keep"
