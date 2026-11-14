"""Lane model change log (MAIN ORDER 2026-11-14 0930 section 3, Fleet Insights W46).

When a lane's model differs from its previous run, write ONE line (lane, old model, new
model, reason, date) to ops/loop/control/lanes/model_changes.jsonl; the s144 rotator
merges the last lines into the lane status file (ops/loop/control/progress/s144-lanes.json)
as "model_changes" after each write_progress.

PREVIOUS RUN. Both models come from the kit usage ledger
(ops/loop/control/headless_usage.jsonl, one row per run, note "lane-s144-<lane>", field
"model" = the id the runner passed): this run's row, and the newest earlier row with the
same note. So a change is measured on what ran, whoever picked it.

REASON. Who picked the new model, from the runner's own start line in the lane log
("lane start ... model=<m> kit_lane_model=<k> ...", ops/loop/run_lane.ps1):
  - kit lane_model: <k> is set and equals <m> (MAIN's ~/.fleet/lanes.json lane_model);
  - RC trial RC_LANE_MODEL: the driver set the FLEET-1b override (lane_run_ledger.MODEL_TRIAL);
  - config.json executor_model: neither (ops/loop/config.json, the runner's default).
A change recorded in KNOWN_CHANGES (the measured history, with its commit and LEDGER
entry) carries that reason instead; backfill() writes those history lines once.

WHY DS AND RESEARCH MOVED TO OPUS (recorded here because MAIN asked for it): on
2026-11-08 commit f1954a39d (s155 C7, RM-1267, LEDGER 2077) ended the FLEET-1b sonnet
trial for ds and research and kept it for repo only. The adjudicator measured USD per
lane commit against the opus baseline of 2026-10-31: repo 2.86 -> 0.95 (kept on sonnet to
2026-12-08), ds 2.49 -> 14.12 (mostly 580 "order exhausted" no-op cycles), research 3.62
-> 9.23 on 2 commits after 51 empty refills; extending the trial for a starved lane would
only measure starvation again. The first opus rows after it: ds 2026-11-08T11:29:16,
research 2026-11-08T11:58:19 (usage ledger).

Stdlib plus core/ (atomic write, append), ASCII only; imported by the gitignored driver as
ops.loop.lane_model_log.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

from ops.loop.lane_backoff import append_line

LEDGER_REL = Path("ops/loop/control/lanes/model_changes.jsonl")
USAGE_REL = Path("ops/loop/control/headless_usage.jsonl")
STATUS_REL = Path("ops/loop/control/progress/s144-lanes.json")
NOTE_PREFIX = "lane-s144-"
USAGE_TAIL_BYTES = 16 << 20
SRC_KIT = "kit lane_model (~/.fleet/lanes.json, MAIN's)"
SRC_TRIAL = "RC trial RC_LANE_MODEL (ops/loop/lane_run_ledger.py MODEL_TRIAL)"
SRC_CONFIG = "config.json executor_model (ops/loop/config.json, the runner default)"
_START_RE = re.compile(r"^lane start \S+ .*?\bmodel=(\S*) kit_lane_model=(\S*)")

_WHY_TRIAL_START = ("FLEET-1b sonnet trial started: commit a30d17b25 (MAIN ORDER 2026-11-01 "
                    "1233, LEDGER 2010), lane_run_ledger.MODEL_TRIAL")
_WHY_1267 = ("RM-1267 adjudicated (s155 C7): commit f1954a39d, LEDGER 2077 - USD per lane "
             "commit vs opus 2026-10-31: ds 2.49 -> 14.12 (580 no-op cycles), research 3.62 -> "
             "9.23 on 2 commits; repo 2.86 -> 0.95 kept on sonnet to 2026-12-08")
# (lane, day, old model family, new model family) -> reason; families match by substring.
KNOWN_CHANGES = {
    ("ds", "2026-11-01", "opus", "sonnet"): _WHY_TRIAL_START,
    ("research", "2026-11-01", "opus", "sonnet"): _WHY_TRIAL_START,
    ("repo", "2026-11-01", "opus", "sonnet"): _WHY_TRIAL_START,
    ("ds", "2026-11-08", "sonnet", "opus"): _WHY_1267,
    ("research", "2026-11-08", "sonnet", "opus"): _WHY_1267,
}


def _family(model) -> str:
    m = str(model or "")
    for fam in ("opus", "sonnet", "haiku"):
        if fam in m:
            return fam
    return m


def known_reason(lane: str, day: str, old, new):
    return KNOWN_CHANGES.get((lane, day, _family(old), _family(new)))


def append(ledger_path, rec: dict) -> None:
    append_line(Path(ledger_path), json.dumps(rec, sort_keys=True))


def read_ledger(ledger_path) -> list:
    try:
        text = Path(ledger_path).read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for ln in text.splitlines():
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def format_line(rec: dict) -> str:
    return (f"{rec.get('date')} {rec.get('lane')} model {rec.get('old')} -> {rec.get('new')} "
            f"({rec.get('reason')})")


# ------------------------------------------------------------------ sources

def start_line_models(log_path):
    """(model, kit_lane_model) from the runner's "lane start" line; (None, None) when
    the log is absent or has no such line. The log is UTF-8 with a BOM, CRLF."""
    try:
        with open(log_path, "rb") as fh:
            head = fh.read(8192)
    except (OSError, TypeError):
        return None, None
    for ln in head.decode("utf-8-sig", "replace").splitlines():
        m = _START_RE.match(ln.lstrip(chr(0xFEFF)))
        if m:
            return m.group(1), m.group(2)
    return None, None


def model_source(model, kit_model, override) -> str:
    if kit_model and kit_model == model:
        return SRC_KIT
    if override and override == model:
        return SRC_TRIAL
    return SRC_CONFIG


def _ts(row) -> float | None:
    try:
        return datetime.datetime.fromisoformat(str(row.get("ts"))).timestamp()
    except (ValueError, TypeError):
        return None


def usage_rows(usage_path, tail_bytes: int = USAGE_TAIL_BYTES) -> list:
    try:
        with open(usage_path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - tail_bytes))
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return []
    out = []
    for ln in text.splitlines():
        try:
            row = json.loads(ln)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def previous_row(rows, note: str, before: float):
    """The newest row with `note` and ts strictly before `before`, or None."""
    best, best_ts = None, None
    for row in rows:
        if row.get("note") != note:
            continue
        ts = _ts(row)
        if ts is None or ts >= before:
            continue
        if best_ts is None or ts >= best_ts:
            best, best_ts = row, ts
    return best


# ------------------------------------------------------------------ the check

def check_cycle(root, lane: str, rec: dict, row, *, usage_path=None, ledger_path=None,
                source=None):
    """After a cycle: `row` is this run's kit usage row (None when the run left none).
    Writes and returns the change record when the model differs from the lane's
    previous run, else None. `source` is who picked this run's model (model_source)."""
    root = Path(root)
    if not isinstance(row, dict) or not row.get("model") or _ts(row) is None:
        return None
    usage_path = Path(usage_path) if usage_path else root / USAGE_REL
    ledger_path = Path(ledger_path) if ledger_path else root / LEDGER_REL
    note = str(row.get("note") or (NOTE_PREFIX + lane))
    prev = previous_row(usage_rows(usage_path), note, _ts(row))
    if prev is None or not prev.get("model") or prev.get("model") == row.get("model"):
        return None
    ts = str(row.get("ts"))
    day = ts[:10]
    reason = known_reason(lane, day, prev.get("model"), row.get("model")) or \
        f"picked by {source or 'unknown source'}"
    change = {"ts": ts, "date": day, "lane": lane, "old": prev.get("model"),
              "new": row.get("model"), "reason": reason, "source": source,
              "run_id": (rec or {}).get("run_id"), "prev_ts": prev.get("ts")}
    append(ledger_path, change)
    return change


def backfill(usage_path, ledger_path) -> list:
    """Write a change line for every lane-s144 model change in the usage ledger that the
    change ledger does not hold yet (keyed by lane + ts). Returns the lines written."""
    have = {(r.get("lane"), r.get("ts")) for r in read_ledger(ledger_path)}
    prev: dict = {}
    wrote = []
    for row in usage_rows(usage_path):
        note = str(row.get("note") or "")
        if not note.startswith(NOTE_PREFIX) or not row.get("model"):
            continue
        lane = note[len(NOTE_PREFIX):]
        old = prev.get(lane)
        prev[lane] = row
        if old is None or old.get("model") == row.get("model"):
            continue
        ts = str(row.get("ts"))
        if (lane, ts) in have:
            continue
        day = ts[:10]
        change = {"ts": ts, "date": day, "lane": lane, "old": old.get("model"),
                  "new": row.get("model"),
                  "reason": known_reason(lane, day, old.get("model"), row.get("model"))
                  or "backfilled from the usage ledger; reason not recorded",
                  "source": "backfill", "run_id": None, "prev_ts": old.get("ts")}
        append(ledger_path, change)
        have.add((lane, ts))
        wrote.append(change)
    return wrote


def stamp(root, *, status_path=None, ledger_path=None, last: int = 10) -> dict:
    """Merge the last `last` change lines into the lane status file as
    "model_changes", atomically. Raises OSError / ValueError; the caller swallows them."""
    from core.polled_json import atomic_write_bytes  # noqa: PLC0415
    root = Path(root)
    path = Path(status_path) if status_path else root / STATUS_REL
    ledger_path = Path(ledger_path) if ledger_path else root / LEDGER_REL
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"status file is not an object: {path}")
    rows = read_ledger(ledger_path)[-last:]
    block = {"lines": [format_line(r) for r in rows], "count": len(rows),
             "ledger": str(LEDGER_REL).replace("\\", "/")}
    doc["model_changes"] = block
    atomic_write_bytes(path, json.dumps(doc).encode("ascii", "replace"))
    return block


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--backfill", action="store_true",
                    help="write the history's change lines missing from the ledger")
    args = ap.parse_args(argv)
    root = Path(args.root)
    if args.backfill:
        wrote = backfill(root / USAGE_REL, root / LEDGER_REL)
        sys.stdout.write(f"backfilled {len(wrote)} line(s)\n")
    for rec in read_ledger(root / LEDGER_REL):
        sys.stdout.write(format_line(rec) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
