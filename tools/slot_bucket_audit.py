#!/usr/bin/env python
"""RM-504: audit the shared slot bucket WITHOUT depending on any loop log.

RC leaked shared slot locks at least five times, three of them from acquires
that appear in NO log RC keeps, and nothing in RC looked at the bucket - a
channel round found the leaks, RC did not. An acquire/release pairing audit over
`controller.log` cannot see this class at all: the leaking callers never logged.
So this audit reads the BUCKET, not the log.

READ-ONLY BY CONTRACT. It never deletes, rewrites or reaps a lock: clearing a
leaked lock destroys the only artifact of the leak (measured cost, RM-504), and
the bucket is outside this repo (a cross-repo shared store). Reaping stays the
job of `ops/loop/slots.py`'s fail-open protocol.

Verdicts per lock:
  OK          pid alive, ts after the pid's process start, age <= stale_after
  DEAD_PID    the recorded pid is not a live process
  PID_REUSED  the pid is alive but its process started AFTER the lock's ts, so
              the live process is not the holder (needs psutil; otherwise
              reported as UNVERIFIED_START)
  OVER_STALE  live pid, age beyond stale_after. This is the AUDIT's leak call,
              not slots': under ops/loop/slots.py is_stale a readable lock
              with a LIVE pid is kept until age > stale_after *
              HARD_STALE_MULTIPLE (2.0; the ceiling arm, then the pid_alive
              return). The row's `slots_would_reap` says which side of that
              ceiling the lock is on.
  UNREADABLE  empty or non-JSON lock (a half-written or zero-byte leftover)

A lock is RC-AUTHORED when its `repo` is this repo's root (case-insensitive)
or carries an `rc-` prefix (the responder writes `repo="rc-responder"`).
Every row carries `owner`: "rc", "foreign", or "unknown". An UNREADABLE lock
has NO holder record, so its owner is UNKNOWN: it is reported as an
unattributed anomaly, never charged to RC (and never counted as an RC leak).

Hold corpus: `--hold-corpus` re-derives acquire/release pairs from a
controller log and writes them as JSON, so a published worst-hold figure has
a committed, re-runnable basis (RM-504 second acceptance clause). The corpus is
explicitly a FLOOR: it covers the LOGGED population only.

Exit 0 when no RC-authored lock is leaked, 1 when one is, 2 on usage error.
Unattributed (UNREADABLE) locks are printed but do not set the exit code.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_slots():
    spec = importlib.util.spec_from_file_location(
        "rc_slot_bucket_audit_slots", ROOT / "ops" / "loop" / "slots.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


slots = _load_slots()

LEAK_VERDICTS = frozenset({"DEAD_PID", "PID_REUSED", "OVER_STALE", "UNREADABLE"})
OWNER_UNKNOWN = "unknown"


def process_start_time(pid: int) -> float | None:
    """Epoch start time of `pid`, or None when it cannot be determined."""
    try:
        import psutil  # optional: pinned in requirements.txt, absent is tolerated
    except ImportError:
        return None
    try:
        return float(psutil.Process(int(pid)).create_time())
    except Exception:  # noqa: BLE001 - any probe failure is "unknown", never a crash
        return None


def is_rc_authored(rec: dict, repo_root: Path = ROOT) -> bool:
    repo = str(rec.get("repo", "") or "")
    if not repo:
        return False
    if repo.lower().startswith("rc-"):
        return True
    norm = repo.replace("/", "\\").rstrip("\\").lower()
    return norm == str(repo_root).replace("/", "\\").rstrip("\\").lower()


def classify(path: Path, stale_after: float, now: float | None = None,
             alive=None, start_time=None) -> dict:
    """One lock's verdict. `alive` / `start_time` are injectable for tests."""
    alive = alive or slots.pid_alive
    start_time = start_time or process_start_time
    now = time.time() if now is None else now
    try:
        raw = path.read_text(encoding="utf-8")
        mtime = path.stat().st_mtime
    except OSError as exc:
        return {"lock": path.name, "verdict": "UNREADABLE", "detail": str(exc),
                "record": None, "rc_authored": False, "owner": OWNER_UNKNOWN}
    try:
        rec = json.loads(raw)
        if not isinstance(rec, dict):
            raise ValueError("not an object")
    except ValueError:
        return {"lock": path.name, "verdict": "UNREADABLE",
                "detail": f"{len(raw)} bytes, mtime age {int(now - mtime)}s",
                "record": raw[:200], "rc_authored": False, "owner": OWNER_UNKNOWN}
    mine = is_rc_authored(rec)
    out = {"lock": path.name, "record": rec, "rc_authored": mine,
           "owner": "rc" if mine else "foreign"}
    pid = int(rec.get("pid", 0) or 0)
    ts = float(rec.get("ts", 0) or 0)
    age = now - ts
    out["age_s"] = round(age, 1)
    if not alive(pid):
        out.update(verdict="DEAD_PID", detail=f"pid {pid} not alive")
        return out
    started = start_time(pid)
    if started is not None and ts and started > ts + 1.0:
        out.update(verdict="PID_REUSED",
                   detail=f"pid {pid} started {int(started - ts)}s after the lock ts")
        return out
    if age > stale_after:
        # slots.is_stale keeps a live holder until the fail-open ceiling; only
        # past it would slots' own reap reclaim the lock.
        ceiling = stale_after * slots.HARD_STALE_MULTIPLE
        would_reap = age > ceiling
        tail = (f"past slots fail-open ceiling {int(ceiling)}s: slots would reap it"
                if would_reap else
                f"live holder kept by slots until {int(ceiling)}s")
        out.update(verdict="OVER_STALE", slots_would_reap=would_reap,
                   detail=f"age {int(age)}s > {int(stale_after)}s; {tail}")
        return out
    out.update(verdict="OK" if started is not None else "UNVERIFIED_START",
               detail="" if started is not None else "no psutil: start time unknown")
    return out


def audit(root: Path, stale_after: float = slots.DEFAULT_STALE_AFTER,
          now: float | None = None, alive=None, start_time=None) -> list[dict]:
    root = Path(root)
    if not root.is_dir():
        return []
    return [classify(p, stale_after, now, alive, start_time)
            for p in sorted(root.glob("*.lock"))]


def rc_leaks(rows: list[dict]) -> list[dict]:
    """Leaked locks RC must answer for: RC-authored rows with a leak verdict.
    An UNREADABLE lock has no holder record, so it is NOT charged to RC; see
    unattributed()."""
    return [r for r in rows if r["verdict"] in LEAK_VERDICTS and r["rc_authored"]]


def unattributed(rows: list[dict]) -> list[dict]:
    """Anomalous locks whose owner cannot be known (no readable holder record)."""
    return [r for r in rows if r.get("owner") == OWNER_UNKNOWN]


def anomaly_lines(root: Path | None = None) -> list[str]:
    """One line per RC leak and per unattributed lock, for tools/rc_facts.py.
    Never raises."""
    try:
        rows = audit(Path(root) if root else slots.DEFAULT_ROOT)
        lines = [f"slot bucket: {r['lock']} {r['verdict']} (RC-authored)"
                 f" - {r.get('detail', '')}"
                 f" (record {json.dumps(r['record'])[:160]})" for r in rc_leaks(rows)]
        lines += [f"slot bucket: {r['lock']} {r['verdict']} - owner UNKNOWN"
                  f" (no holder record; not attributed to RC) - {r.get('detail', '')}"
                  for r in unattributed(rows)]
        return lines
    except Exception as exc:  # noqa: BLE001 - a facts hook must never fail
        return [f"slot bucket audit failed: {type(exc).__name__}: {exc}"]


_ACQ = re.compile(r"^(\S+)\s+slots: acquired (\S+) \(run_id=(\w+) cycle=(\d+)\)")
_REL = re.compile(r"^(\S+)\s+slots: released (\S+)")
_REAP = re.compile(r"^(\S+)\s+slots: reaped stale slot (\d+)")


def _ts(text: str) -> float:
    return time.mktime(time.strptime(text[:19], "%Y-%m-%dT%H:%M:%S"))


def hold_corpus(log_lines, stale_after: float = slots.DEFAULT_STALE_AFTER) -> dict:
    """Pair acquire/release lines per slot name. Unpaired acquires are listed,
    not guessed at. The result is a FLOOR on the true worst hold."""
    open_by_slot: dict[str, dict] = {}
    pairs, reaps = [], 0
    acquires = releases = 0
    for line in log_lines:
        m = _ACQ.match(line)
        if m:
            acquires += 1
            prior = open_by_slot.pop(m.group(2), None)
            if prior:
                prior["unpaired_reason"] = "re-acquired without a release"
                pairs.append(prior)
            open_by_slot[m.group(2)] = {"slot": m.group(2), "acquired": m.group(1),
                                        "run_id": m.group(3), "cycle": int(m.group(4))}
            continue
        m = _REL.match(line)
        if m:
            releases += 1
            rec = open_by_slot.pop(m.group(2), None)
            if rec:
                rec["released"] = m.group(1)
                rec["hold_s"] = int(_ts(m.group(1)) - _ts(rec["acquired"]))
                pairs.append(rec)
            continue
        if _REAP.match(line):
            reaps += 1
    unpaired = [r for r in pairs if "hold_s" not in r] + list(open_by_slot.values())
    held = [r["hold_s"] for r in pairs if "hold_s" in r]
    return {
        "basis": "controller.log acquire/release pairs - LOGGED population only; "
                 "a FLOOR on the true maximum, never a ceiling",
        "acquires": acquires, "releases": releases, "reaps": reaps,
        "pairs": len(held),
        "run_ids": sorted({r["run_id"] for r in pairs} |
                          {r["run_id"] for r in open_by_slot.values()}),
        "worst_hold_s": max(held) if held else None,
        "mean_hold_s": int(sum(held) / len(held)) if held else None,
        "stale_after_s": stale_after,
        "unpaired": unpaired,
        "holds": [r for r in pairs if "hold_s" in r],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=Path, default=slots.DEFAULT_ROOT)
    ap.add_argument("--stale-after", type=float, default=slots.DEFAULT_STALE_AFTER)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--hold-corpus", type=Path, metavar="LOG",
                    help="derive a hold corpus from a controller log instead")
    ap.add_argument("--out", type=Path, help="write the corpus JSON here (atomic)")
    args = ap.parse_args(argv)
    if args.hold_corpus:
        if not args.hold_corpus.is_file():
            print(f"no such log: {args.hold_corpus}", file=sys.stderr)
            return 2
        corpus = hold_corpus(args.hold_corpus.read_text(
            encoding="utf-8", errors="replace").splitlines(), args.stale_after)
        text = json.dumps(corpus, indent=1) + "\n"
        if args.out:
            tmp = args.out.with_suffix(args.out.suffix + ".tmp")
            tmp.write_bytes(text.encode("ascii"))
            tmp.replace(args.out)
        else:
            sys.stdout.write(text)
        return 0
    rows = audit(args.root, args.stale_after)
    leaks = rc_leaks(rows)
    unknown = unattributed(rows)
    if args.json:
        print(json.dumps({"root": str(args.root), "locks": rows, "rc_leaks": len(leaks),
                          "unattributed": len(unknown)}, indent=1))
    else:
        for r in rows:
            print(f"{r['lock']}: {r['verdict']} owner={r['owner']} {r.get('detail', '')}")
        print(f"{len(rows)} lock(s), {len(leaks)} RC leak(s),"
              f" {len(unknown)} unattributed in {args.root}")
    return 1 if leaks else 0


if __name__ == "__main__":
    sys.exit(main())
