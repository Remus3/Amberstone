"""RM-143 P3 - live-path parity runner (REPORT-ONLY by default).

For each fixture, run the SAME body two ways and diff:

  1. in-process: ``server._POST_ROUTES[route](body)`` against a freshly loaded
     snapshot, i.e. what the repo says the answer is;
  2. live: ``POST http://127.0.0.1:8860{route}``, i.e. what the DEPLOYED
     process actually returns.

This is not the same computation run twice. The live leg is a DEPLOYMENT check,
aimed at the measured trap where a long-lived process serves code that no longer
matches the tree: ``project_loop_controller_stale_code`` (a controller ran five
hours of its own fixes unloaded), ``reference_schtasks_end_run_race_ds_8893``,
and the standing CLAUDE.md warning that a mid-suite DS bounce fakes
anchor-mismatch failures.

VERDICTS ARE THREE-VALUED, and that is load-bearing:

  PARITY  engine versions agree and outputs agree
  FAIL    engine versions agree and outputs DIVERGE   <- a real defect
  SKEW    live ENGINE_VERSION != repo ENGINE_VERSION  <- stale deploy, not a bug

A restart-window mismatch must never be reported as FAIL. A gate that cries wolf
during a normal DS bounce is a gate that gets switched off within a week, which
is exactly the reasoning ``tools/stop_claim_gate.py`` used to ship REPORT-ONLY
and arm later. Same discipline here: exit 0 always unless ``--arm``.

Usage:
  python tools/ds_parity_run.py                 # report only, exit 0
  python tools/ds_parity_run.py --arm           # exit 2 on FAIL (never on SKEW)
  python tools/ds_parity_run.py --lint-fixtures # P2: body-key lint, no live call
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "ds_parity_fixtures.jsonl"
DEFAULT_REPORT = ROOT / "ops" / "runtime" / "ds_parity_report.json"
BASE_URL = "http://127.0.0.1:8860"

# Relative tolerance for float comparison. The two legs run identical code on
# identical inputs, so anything beyond float repr noise is a real divergence.
REL_TOL = 1e-9


def load_fixtures(path: Path = FIXTURES) -> list[dict]:
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise SystemExit(f"{path}:{i}: bad JSON - {e}")
    return out


def _diff(a: Any, b: Any, path: str = "") -> list[str]:
    """Recursive compare. Returns human-readable divergence paths."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            if key not in a:
                out.append(f"{path}.{key}: missing in-process")
            elif key not in b:
                out.append(f"{path}.{key}: missing live")
            else:
                out += _diff(a[key], b[key], f"{path}.{key}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: length {len(a)} vs {len(b)}"]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += _diff(x, y, f"{path}[{i}]")
        return out
    if isinstance(a, bool) or isinstance(b, bool):
        return [] if a is b else [f"{path}: {a!r} vs {b!r}"]
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        scale = max(abs(a), abs(b), 1.0)
        return [] if abs(a - b) <= REL_TOL * scale else [f"{path}: {a!r} vs {b!r}"]
    return [] if a == b else [f"{path}: {a!r} vs {b!r}"]


def _post(route: str, body: dict, timeout: float = 60.0) -> dict:
    req = urllib.request.Request(
        BASE_URL + route, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _live_engine_version(timeout: float = 10.0) -> str | None:
    try:
        with urllib.request.urlopen(BASE_URL + "/health", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")).get("engine_version")
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None


def _in_process_setup():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from agents.daemon_slayer import ENGINE_VERSION, server  # noqa: PLC0415
    from agents.daemon_slayer.data_loader import DataSnapshot  # noqa: PLC0415
    server._CACHE.set(DataSnapshot.load())
    return server, ENGINE_VERSION


def lint_fixtures(fixtures: list[dict]) -> list[str]:
    """P2 - a body key the target route does not read is set with no effect.

    This is what makes the ``/rank`` trap unauthorable rather than merely
    documented: POSTing ``enemy_ad_share`` to ``/rank`` returns a plausible
    carry-scored answer with the key silently discarded.
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.ds_parity_map import build_map  # noqa: PLC0415

    m = build_map()
    problems = []
    for fx in fixtures:
        route = fx["route"]
        entry = m.get(route)
        if entry is None:
            problems.append(f"{fx['id']}: unknown route {route}")
            continue
        known = set(entry["body_keys"])
        for key in fx["body"]:
            if key not in known:
                elsewhere = sorted(r for r, e in m.items() if key in e["body_keys"])
                hint = f" (read by {elsewhere})" if elsewhere else ""
                problems.append(
                    f"{fx['id']}: {route} does not read {key!r}{hint}")
    return problems


def run(fixtures: list[dict], settle_retry: bool = True) -> dict:
    server, repo_engine = _in_process_setup()
    live_engine = _live_engine_version()

    if live_engine is not None and live_engine != repo_engine and settle_retry:
        # one settle-and-retry: a bounce may be mid-flight right now
        time.sleep(5)
        live_engine = _live_engine_version()

    results = []
    for fx in fixtures:
        route, body = fx["route"], fx["body"]
        rec = {"id": fx["id"], "route": route}
        if live_engine is None:
            rec["verdict"] = "SKEW"
            rec["detail"] = "live DS :8860 unreachable"
            results.append(rec)
            continue
        if live_engine != repo_engine:
            rec["verdict"] = "SKEW"
            rec["detail"] = f"live {live_engine} != repo {repo_engine}"
            results.append(rec)
            continue
        try:
            got_local = server._POST_ROUTES[route](dict(body))
        except Exception as e:  # noqa: BLE001 - any handler error is a finding
            rec["verdict"] = "ERROR"
            rec["detail"] = f"in-process raised {type(e).__name__}: {e}"
            results.append(rec)
            continue
        try:
            got_live = _post(route, body)
        except Exception as e:  # noqa: BLE001
            rec["verdict"] = "ERROR"
            rec["detail"] = f"live raised {type(e).__name__}: {e}"
            results.append(rec)
            continue

        diffs = _diff(got_local, got_live)
        rec["verdict"] = "PARITY" if not diffs else "FAIL"
        if diffs:
            rec["diffs"] = diffs[:20]
            rec["diff_count"] = len(diffs)
        results.append(rec)

    counts: dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return {
        "repo_engine_version": repo_engine,
        "live_engine_version": live_engine,
        "fixtures": len(fixtures),
        "counts": counts,
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arm", action="store_true",
                    help="exit 2 on FAIL (never on SKEW). P4; default off.")
    ap.add_argument("--lint-fixtures", action="store_true",
                    help="P2 body-key lint only; no live call")
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    ap.add_argument("--fixtures", default=str(FIXTURES))
    args = ap.parse_args(argv)

    fixtures = load_fixtures(Path(args.fixtures))

    if args.lint_fixtures:
        problems = lint_fixtures(fixtures)
        for p in problems:
            print(f"LINT {p}")
        print(f"fixtures: {len(fixtures)}  problems: {len(problems)}")
        return 2 if (problems and args.arm) else 0

    report = run(fixtures)
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2), encoding="utf-8")
    tmp.replace(out)

    print(f"report: {out}")
    print(f"repo {report['repo_engine_version']} | live {report['live_engine_version']}")
    print(f"counts: {report['counts']}")
    for r in report["results"]:
        if r["verdict"] != "PARITY":
            print(f"  {r['verdict']:7s} {r['id']:26s} "
                  f"{r.get('detail') or r.get('diffs', [''])[0]}")

    failed = report["counts"].get("FAIL", 0) + report["counts"].get("ERROR", 0)
    return 2 if (args.arm and failed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
