"""Lane run ledger: the tested logic behind the s144 lane driver (MAIN ORDER items
RC-3, RC-4, FLEET-1b).

The s144 driver is a gitignored one-off under ops/loop/control/lane_prompts/, so CI
never sees it. Everything a test pins lives here; the driver imports this module
with a fallback, so a fault in it can never stop a rotator or a lane child.

RC-3, exit tags. Measured: the kit usage row (ops/loop/control/headless_usage.jsonl)
carries "rc", "subtype" and "is_error". A worker can exit rc 1 with subtype "success"
and is_error true: the claude result record says success while the result text is an
API error. The lane log holds no subtype, only the result text as its final line. The
tag separates those runs from real crashes (non-zero rc with any other subtype or with
no usage row at all). A tag never changes a cycle's outcome.

RC-4, the daily line. Runs and USD come from the usage rows, commits from the driver's
s144_<lane>_cycles.jsonl ("own_commits"). THOSE COMMITS ARE LANE-LOCAL: made on
lane/<x> and not yet landed on main, and a merger may still drop them. So the keys and
the line say lane_commits and usd_per_lane_commit, never landed. A row's day is
ts[:10], the same reading as the kit's fleet_lanes.spent_today, so the tree USD figure
is the one a daily_usd_ceiling compares against.

FLEET-1b, the per-lane model trial. The lane model is decided by ops/loop/run_lane.ps1:
its fallback, then ops/loop/config.json executor_model, for every lane alike. The
driver sets RC_LANE_MODEL in its own environment before it starts the runner, and the
runner lets that exact id win. Through MODEL_TRIAL_END (inclusive, local day) the
MODEL_TRIAL lanes run sonnet; afterwards lane_model returns None and the config default
is back with no edit. MODEL_TRIAL_MEASURE names what the trial is judged on. The "before"
baseline is the 7 days ending the day before MODEL_TRIAL_START.

Stdlib plus core/polled_json.py (the repo's atomic-write contract), ASCII only;
importable by file path or as ops.loop.lane_run_ledger.
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import statistics
import sys
from pathlib import Path

# Plain import first, absolute-path bind as the fallback for a load by file path, where
# the repo root is not on sys.path (same shape as ops/loop/inbox_tick.py).
try:
    from core.polled_json import atomic_write_bytes as _atomic_write_bytes
except ModuleNotFoundError:
    _PJ_NAME = "rc_core_polled_json"
    if _PJ_NAME in sys.modules:
        _atomic_write_bytes = sys.modules[_PJ_NAME].atomic_write_bytes
    else:
        _pj_spec = importlib.util.spec_from_file_location(
            _PJ_NAME, Path(__file__).resolve().parents[2] / "core" / "polled_json.py")
        _pj = importlib.util.module_from_spec(_pj_spec)
        sys.modules[_PJ_NAME] = _pj
        _pj_spec.loader.exec_module(_pj)
        _atomic_write_bytes = _pj.atomic_write_bytes

USAGE_REL = Path("ops/loop/control/headless_usage.jsonl")
CYCLES_REL = Path("ops/loop/control/lane_prompts")
STATUS_REL = Path("ops/loop/control/progress/s144-lanes.json")
LANE_NOTE_PREFIX = "lane-s144-"
USAGE_TAIL_BYTES = 16 << 20

SONNET_ID = "claude-sonnet-5-5"
MODEL_TRIAL = {"ds": SONNET_ID, "repo": SONNET_ID, "research": SONNET_ID}
MODEL_TRIAL_START = "2026-11-01"
MODEL_TRIAL_END = "2026-11-08"
MODEL_TRIAL_MEASURE = (
    "per lane, before vs during: USD per run, lane commits per run and USD per lane "
    "commit (trial_measure), plus zero-commit runs; and from the merger's records, "
    "verifier-rejected and reverted commits per lane. Keep sonnet on a lane only if "
    "its USD per lane commit falls and its rejected-or-reverted count does not rise.")

CLEAN = "clean"
FAILED_REPORTS_SUCCESS = "failed_reports_success"
CRASH = "crash"
REFUSED = "refused"
KILLED = "killed"
NO_EXIT_CODE = "no_exit_code"
KILLED_OUTCOMES = ("timeout_killed", "kill_failed")
REFUSED_RC = 3


# ------------------------------------------------------------------ RC-3 exit tags

def exit_tag(rc, row, outcome=None) -> str:
    """The tag for one worker exit. `row` is its kit usage row, or None."""
    if outcome in KILLED_OUTCOMES:
        return KILLED
    if rc is None:
        return NO_EXIT_CODE
    if rc == 0:
        return CLEAN
    if rc == REFUSED_RC:
        return REFUSED
    if isinstance(row, dict) and row.get("subtype") == "success":
        return FAILED_REPORTS_SUCCESS
    return CRASH


def exit_record(rc, row, outcome, last_result: str, exit_marker: str) -> dict:
    """The fields a cycle record gains: the tag, and on any failed exit the last
    result text and the exit path (runner marker, kit row, driver outcome)."""
    tag = exit_tag(rc, row, outcome)
    has_row = isinstance(row, dict)
    rec = {"exit_tag": tag, "usage_model": row.get("model") if has_row else None,
           "usage_cost_usd": row.get("cost_usd") if has_row else None}
    if tag == CLEAN:
        return rec
    kit = (f"kit rc={row.get('rc')} subtype={row.get('subtype')} "
           f"is_error={row.get('is_error')} turns={row.get('num_turns')} "
           f"usd={row.get('cost_usd')} error={row.get('error')}"
           if has_row else "kit no usage row")
    rec["last_result"] = " ".join(str(last_result or "").split())[:400]
    rec["exit_path"] = (f"{exit_marker or 'no lane exit marker'} | {kit} | "
                        f"driver rc={rc} outcome={outcome}")[:400]
    return rec


def exit_marker(log) -> str:
    """The runner's last "lane exit <iso> code=<n>" line in a lane log, or ""."""
    if not log:
        return ""
    try:
        path = Path(log)
        with open(path, "rb") as fh:
            size = path.stat().st_size
            if size > (64 << 10):
                fh.seek(-(64 << 10), 2)
            text = fh.read().decode("utf-8-sig", "replace")
    except OSError:
        return ""
    for line in reversed(text.splitlines()):
        if line.startswith("lane exit "):
            return line.strip()
    return ""


def exit_counts(rows) -> dict:
    """Failed lane runs by tag, from usage rows: rc 1 + subtype success counted apart
    from real crashes. A clean run counts under neither."""
    out = {FAILED_REPORTS_SUCCESS: 0, CRASH: 0, REFUSED: 0, NO_EXIT_CODE: 0}
    for row in rows:
        tag = exit_tag(row.get("rc"), row)
        if tag in out:
            out[tag] += 1
    return out


# ------------------------------------------------------------------ readers

def read_jsonl(path, tail_bytes: int = USAGE_TAIL_BYTES) -> list:
    """Dict rows of a JSONL file; a bad line is skipped, a missing file is []."""
    try:
        path = Path(path)
        with open(path, "rb") as fh:
            if path.stat().st_size > tail_bytes:
                fh.seek(-tail_bytes, 2)
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def usage_rows(root) -> list:
    return read_jsonl(Path(root) / USAGE_REL)


def cycle_rows(root) -> list:
    rows = []
    for path in sorted((Path(root) / CYCLES_REL).glob("s144_*_cycles.jsonl")):
        rows.extend(read_jsonl(path))
    return rows


def _is_lane(row) -> bool:
    return str(row.get("note") or "").startswith(LANE_NOTE_PREFIX)


def _usd(row) -> float:
    cost = row.get("cost_usd")
    return float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else 0.0


def _day(value) -> str:
    return value[:10] if isinstance(value, str) else ""


def _today() -> str:
    return datetime.date.today().isoformat()


# ------------------------------------------------------------------ RC-4 daily line

def daily_figures(usage, cycles, day: str) -> dict:
    """One local day: lane runs and USD, the whole tree's USD, lane-local commits."""
    rows = [r for r in usage if _day(r.get("ts")) == day]
    lane = [r for r in rows if _is_lane(r)]
    commits = sum(int(c.get("own_commits") or 0) for c in cycles
                  if _day(c.get("ended")) == day)
    usd = sum(_usd(r) for r in lane)
    return {
        "day": day, "lane_runs": len(lane), "lane_usd": round(usd, 2),
        "tree_runs": len(rows), "tree_usd": round(sum(_usd(r) for r in rows), 2),
        "lane_commits": commits,
        "usd_per_lane_commit": round(usd / commits, 2) if commits else None,
        "exits": exit_counts(lane),
    }


def daily_line(fig: dict) -> str:
    each = fig["usd_per_lane_commit"]
    return (f"{fig['day']}: lane runs {fig['lane_runs']}, lane USD {fig['lane_usd']:.2f}, "
            f"lane-local commits {fig['lane_commits']} (not landed on main), USD per "
            f"lane-local commit {'n/a' if each is None else format(each, '.2f')}; tree "
            f"runs {fig['tree_runs']}, tree USD {fig['tree_usd']:.2f}; failed-reports-success "
            f"{fig['exits'][FAILED_REPORTS_SUCCESS]}, crashes {fig['exits'][CRASH]}")


def today_daily(root, day=None) -> dict:
    fig = daily_figures(usage_rows(root), cycle_rows(root), day or _today())
    return dict(fig, line=daily_line(fig))


def stamp_daily(root, day=None, status_path=None) -> dict:
    """Merge today's figures into the lane status file as "daily", atomically. The
    kit's write_progress rewrites that file whole and has no extra-key door, so the
    rotator calls this right after each write_progress. Raises OSError / ValueError;
    the driver's caller swallows them. Returns the figures."""
    path = Path(status_path) if status_path else Path(root) / STATUS_REL
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"status file is not an object: {path}")
    fig = today_daily(root, day)
    doc["daily"] = fig
    _atomic_write_bytes(path, json.dumps(doc).encode("ascii"))
    return fig


def read_daily(root, status_path=None):
    """The "daily" block as the status file holds it now, or None."""
    path = Path(status_path) if status_path else Path(root) / STATUS_REL
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc.get("daily") if isinstance(doc, dict) else None


def usd_by_day(usage) -> dict:
    out: dict = {}
    for row in usage:
        day = _day(row.get("ts"))
        if day:
            out[day] = out.get(day, 0.0) + _usd(row)
    return out


def week_usd(usage, today=None, days: int = 7) -> dict:
    """Tree USD per day over the last `days` local days, today included, with the peak
    and the median (the two figures a daily USD ceiling is set from). Today is partial,
    so the peak and median are given both with it and over complete days only."""
    end = datetime.date.fromisoformat(today or _today())
    span = [(end - datetime.timedelta(days=n)).isoformat() for n in range(days)][::-1]
    per = usd_by_day(usage)
    vals = {d: round(per.get(d, 0.0), 2) for d in span}
    full = [vals[d] for d in span[:-1]]
    return {"days": vals, "peak": max(vals.values()),
            "median": round(statistics.median(vals.values()), 2),
            "peak_complete_days": max(full) if full else None,
            "median_complete_days": round(statistics.median(full), 2) if full else None}


def peak_rolling_runs(usage, *, lanes=None) -> int:
    """The most kit runs in any rolling 24 h. lanes=False counts non-lane rows only
    (what a lane reserve has to leave room for), True lane rows, None every row."""
    stamps = []
    for row in usage:
        if lanes is not None and _is_lane(row) != lanes:
            continue
        try:
            stamps.append(datetime.datetime.fromisoformat(str(row.get("ts"))).timestamp())
        except ValueError:
            continue
    stamps.sort()
    best = start = 0
    for i, stamp in enumerate(stamps):
        while stamp - stamps[start] > 86400:
            start += 1
        best = max(best, i - start + 1)
    return best


# ------------------------------------------------------------------ FLEET-1b model trial

def lane_model(lane: str, today=None):
    """The trial's exact model id for this lane today, or None: not a trial lane, or
    past MODEL_TRIAL_END (the config default then applies, with no edit)."""
    if (today or _today()) <= MODEL_TRIAL_END:
        return MODEL_TRIAL.get(lane)
    return None


def runs_reserve(cap: int) -> int:
    """Runs a lane rotator leaves free for everything else in the tree: 20 percent of
    the live cap. 500 -> 100, above the measured 99 non-lane runs in a rolling 24 h
    (peak_rolling_runs, 2026-11-01); a config fault's 120 -> 24, the old fixed value."""
    return int(cap) // 5


def trial_measure(usage, cycles, *, start=MODEL_TRIAL_START, end=MODEL_TRIAL_END,
                  before_days: int = 7) -> dict:
    """{lane: {"before": ..., "during": ...}} from the rows on disk. "during" on a
    trial lane counts only runs on the trial model, because the trial's first day also
    holds that lane's earlier runs on the default. The verifier-rejected and reverted
    half of MODEL_TRIAL_MEASURE is the merger's, not here."""
    first = datetime.date.fromisoformat(start)
    before_from = (first - datetime.timedelta(days=before_days)).isoformat()

    def window(lane, lo, hi_exclusive, want=None):
        rows = [r for r in usage if r.get("note") == LANE_NOTE_PREFIX + lane
                and lo <= _day(r.get("ts")) < hi_exclusive
                and (want is None or r.get("model") == want)]
        cyc = [c for c in cycles if c.get("lane") == lane
               and lo <= _day(c.get("ended")) < hi_exclusive
               and (want is None or c.get("model") == want)]
        usd = sum(_usd(r) for r in rows)
        commits = sum(int(c.get("own_commits") or 0) for c in cyc)
        return {
            "runs": len(rows), "usd": round(usd, 2),
            "usd_per_run": round(usd / len(rows), 2) if rows else None,
            "lane_commits": commits,
            "commits_per_run": round(commits / len(rows), 2) if rows else None,
            "usd_per_lane_commit": round(usd / commits, 2) if commits else None,
            "zero_commit_cycles": sum(1 for c in cyc if not c.get("own_commits")),
            "models": sorted({str(r.get("model")) for r in rows}),
        }

    after_end = (datetime.date.fromisoformat(end) + datetime.timedelta(days=1)).isoformat()
    lanes = sorted({str(r["note"])[len(LANE_NOTE_PREFIX):] for r in usage if _is_lane(r)})
    return {lane: {"before": window(lane, before_from, start),
                   "during": window(lane, start, after_end, MODEL_TRIAL.get(lane))}
            for lane in lanes}


# ------------------------------------------------------------------ CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read-only lane ledger figures.")
    ap.add_argument("what", choices=("daily", "read-daily", "week", "measure", "runs"))
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    args = ap.parse_args(argv)
    usage = usage_rows(args.root)
    if args.what == "daily":
        doc = today_daily(args.root)
    elif args.what == "read-daily":
        doc = read_daily(args.root)
    elif args.what == "week":
        doc = week_usd(usage)
    elif args.what == "measure":
        doc = trial_measure(usage, cycle_rows(args.root))
    else:
        doc = {"all": peak_rolling_runs(usage), "lane": peak_rolling_runs(usage, lanes=True),
               "non_lane": peak_rolling_runs(usage, lanes=False)}
    sys.stdout.write(json.dumps(doc, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
