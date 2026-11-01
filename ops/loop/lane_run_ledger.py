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

Stdlib only, ASCII only; importable by file path or as ops.loop.lane_run_ledger.
"""
from __future__ import annotations

from pathlib import Path

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
