"""Command line: ``hauntlet run | selftest | serve | sample-report``."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from hauntlet.agents import get_agent
from hauntlet.core.levels import COMPROMISE_THRESHOLD, Level
from hauntlet.core.report import render_report
from hauntlet.core.runner import run_once, run_repeated
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.rooms import default_rooms


def _service() -> RangeService:
    return RangeService(Store(":memory:"), default_rooms())


def _scratch() -> Path:
    root = Path(".hauntlet/scratch")
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="run-", dir=root))


def cmd_run(args: argparse.Namespace) -> int:
    service = _service()
    agent = get_agent(args.agent)
    results, aggs = run_repeated(service, args.room, agent, args.repeat, _scratch())
    for r in results:
        print(f"run {r.score.run_id}: {r.score.overall_worst.name} {r.score.overall_worst.label}")
    for a in aggs:
        pk = ", ".join(f"pass^{k}={v:.2f}" for k, v in a.pass_k)
        print(
            f"[{a.room}] n={a.n} worst={a.worst_level.name} compromised={a.compromise_rate:.0%} "
            f"clean={a.clean_rate:.0%} detected={a.detected_rate:.0%} task={a.task_rate:.0%} {pk}"
        )
    worst = max(results, key=lambda r: r.score.overall_worst)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"autopsy-{args.room}-{args.agent}-{worst.score.run_id}.html"
    path.write_text(
        render_report(worst.score, worst.manifest, aggs if args.repeat > 1 else (), agent.name),
        encoding="utf-8",
    )
    print(f"report: {path}")
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    service = _service()
    failures: list[str] = []
    for room in service.rooms:
        naive, _ = run_repeated(service, room, get_agent("naive"), args.n, _scratch())
        for r in naive:
            if r.score.overall_worst < COMPROMISE_THRESHOLD:
                failures.append(f"{room}: naive scored {r.score.overall_worst.name}, expected >= L3")
        hardened, _ = run_repeated(service, room, get_agent("hardened"), args.n, _scratch())
        for r in hardened:
            rs = r.score.room(room)
            assert rs is not None
            if rs.worst_level != Level.L0:
                failures.append(f"{room}: hardened scored {rs.worst_level.name}, expected L0")
            if not rs.detected:
                failures.append(f"{room}: hardened did not get Detected credit")
            if not rs.task_completed:
                failures.append(f"{room}: hardened did not complete the task")
            if rs.false_positives:
                failures.append(f"{room}: hardened triggered controls {rs.false_positives}")
    if failures:
        print("selftest FAILED", *sorted(set(failures)), sep="\n  ", file=sys.stderr)
        return 1
    print(f"selftest passed: {len(service.rooms)} room(s), naive >= L3 and hardened L0+Detected over n={args.n}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from hauntlet.server import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port)
    return 0


def cmd_sample_report(args: argparse.Namespace) -> int:
    service = _service()
    result = run_once(service, "threshold", get_agent("naive"), _scratch())
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(result.score, result.manifest, (), "naive"), encoding="utf-8")
    print(f"sample report: {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hauntlet", description="A haunted house for AI agents.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a reference agent through a room")
    r.add_argument("--room", default="threshold")
    r.add_argument("--agent", default="naive")
    r.add_argument("--repeat", type=int, default=1)
    r.add_argument("--out", default="reports")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("selftest", help="assert naive >= L3 and hardened L0+Detected in every room")
    s.add_argument("-n", type=int, default=3)
    s.set_defaults(func=cmd_selftest)

    v = sub.add_parser("serve", help="start the HTTP range")
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8666)
    v.set_defaults(func=cmd_serve)

    sr = sub.add_parser("sample-report", help="render a sample autopsy report")
    sr.add_argument("--out", default="docs/sample-report.html")
    sr.set_defaults(func=cmd_sample_report)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
