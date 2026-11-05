"""gated_lx09_mark_check.py - grade one real game's "mark this moment" presses for the LX-09 drain.

LX-09 (RM-638) asks four things of a real game: a Ctrl+Shift+K press lands a
row in ``ops/runtime/moment_marks.jsonl`` with a real game id; a press during
the loading screen is dropped and logged; after the game the marks attach to
that game (``ops/runtime/moment_marks_by_game/<gameId>.json``); and they show
as "you flagged" pins in Replay and PGR. This tool grades the first three from
the files the live code wrote. The fourth is a RENDER question: the route field
``you_flagged`` and the drawn pin are separate checks, and neither is graded
here.

It is READ-ONLY: it reads the marks file, the per-game pin file and the
listener log, and prints. It never writes, moves, locks or deletes any of them.
It makes no network call, and it never ticks a row. Its output is the INPUT to
the four-part evidence contract in ``docs/LIVE_GAME_GATED_SYNC.md``, never the
evidence itself. Rows written by the real ``core.moment_marks`` helpers from a
hand-built gamestats body pass these checks just as well. That is the
substitution the LX-09 row names.

THE PRESS LEDGER. ``tools/hotkey_listener.py`` ``handle_moment_mark`` logs
exactly ONE outcome line per press that reaches the dispatch worker. It is
either ``moment mark: game_id=<id> game_time_s=<t>`` (recorded) or
``moment mark dropped: <reason>``; the hook itself logs nothing per key. (A
game-id provider that RAISES adds a ``game_id unknown`` line before the
recorded one; the default provider never raises.) So
``presses_seen`` = recorded + dropped lines in the window. A press that never
reached the hook leaves no trace, which is why ``--expect-presses`` takes the
operator's own count.

THE CLOCK ZERO. Each mark row carries ``wall_ts`` (epoch at the press) and
``game_time_s`` (the :2999 game clock), so ``wall_ts - game_time_s`` is the
wall time of game clock zero. That is the end of the loading screen, since the
Live Client clock starts there. The rows of one game agree on it to within
the :2999 read latency (``offset_spread_s``). A mark whose ``game_time_s`` is
under ``NEAR_ZERO_S`` is reported as near-zero. It may be a load-screen press
that :2999 answered, which would refute the "dropped" claim.

THE LOAD DROP needs BOTH bounds. A drop line stamped BEFORE clock zero may be
a loading-screen drop, but a press in champ select or the lobby is dropped the
same way. So it counts only at or after the first GameStart / InProgress time,
taken from an LX-01 phase tape (``--phase-tape``) or ``--game-start``. Without
one, a drop before clock zero reads ``LOAD_DROP_UNBOUNDED``, never
``LOAD_DROP_SEEN``.

NO GAME ID IS EVER PRINTED (RM-906). ``--game-id`` (the LCU gameId read while
InProgress) is an INPUT. Every id the tool meets, in a row, a log line or a
pin file name, prints as a ROLE: ``match`` (equals ``--game-id``), ``other``
or ``null``.

USAGE (from the main checkout, after the game ends and the post-game collector
has run)
    python tools/gated_lx09_mark_check.py --since <epoch|iso> --until <epoch|iso>
        --game-id <LCU gameId> --expect-presses <n> --phase-tape <LX-01 tape>
        [--log 'logs/hotkey_listener.log*'] [--json]

Exit 2 = --since / --until / --game-start does not parse, the named tape or a
log file exists but cannot be read, or an argparse usage error. A missing marks file, pin file or log is a
reading (reported), never an exit 2.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import moment_marks  # noqa: E402
from tools.gated_lx01_draft_check import (  # noqa: E402
    GAME_PHASES, _in, expand_logs, load_tape, parse_when,
)

DEFAULT_LOG = str(_ROOT / "logs" / "hotkey_listener.log*")
NEAR_ZERO_S = 1.0
OFFSET_SLACK_S = 3.0

# Verbatim fragments of tools/hotkey_listener.py log calls (pinned by the tests).
START_FRAG = "hotkey_listener starting ("
CHORD_FRAG = "Ctrl+Shift+K"
RECORDED_RE = re.compile(r"moment mark: game_id=(\S+) game_time_s=(-?\d+(?:\.\d+)?)")
DROP_FRAG = "moment mark dropped: "
DROP_KINDS = {
    "gamestats_unavailable": "moment mark dropped: :2999 gamestats unavailable",
    "no_game_time": "moment mark dropped: gamestats carried no usable gameTime",
}
OTHER_FRAGS = {
    "game_id_unknown": "moment mark: game_id unknown",
    "replay_hook_failed": "moment mark: replay-buffer hook failed",
    "hook_proc_error": "low-level hook proc error",
}
_LINE_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}),(\d{3}) ")


def _role(gid: Any, game_id: Optional[str]) -> str:
    g = moment_marks._norm_game_id(gid)
    if g is None:
        return "null"
    return "match" if game_id is not None and g == game_id else "other"


def _line_time(line: str) -> Optional[float]:
    m = _LINE_TS.match(line)
    return parse_when(f"{m.group(1)}T{m.group(2)}.{m.group(3)}") if m else None


# -- marks -------------------------------------------------------------------------

def grade_marks(path: Path, since: float, until: float, game_id: Optional[str]) -> dict:
    out: dict = {"file": "present" if path.is_file() else "missing"}
    try:
        moment_marks.read_marks_strict(path)
        out["strict"] = "ok"
    except moment_marks.MarksUnreadable as exc:
        # A category and a line number only: never a path or a row's content.
        msg = str(exc)
        ln = re.search(r":(\d+): not ", msg)
        kind = ("not_json" if msg.endswith("not JSON") else
                "not_a_mark_row" if msg.endswith("not a mark row") else "unreadable")
        out["strict"] = kind + (f" at line {ln.group(1)}" if ln else "")
    rows = moment_marks.read_marks(path)
    win = [r for r in rows if _in(r["wall_ts"], since, until)]
    roles = {"match": 0, "other": 0, "null": 0}
    for r in win:
        roles[_role(r["game_id"], game_id)] += 1
    offsets = [r["wall_ts"] - r["game_time_s"] for r in win]
    out.update({
        "rows_total": len(rows),
        "rows_in_window": len(win),
        "id_roles": roles,
        "match_outside_window": sum(1 for r in rows if game_id is not None
                                    and r["game_id"] == game_id
                                    and not _in(r["wall_ts"], since, until)),
        "game_time_s": [r["game_time_s"] for r in win],
        "near_zero": sum(1 for r in win if r["game_time_s"] < NEAR_ZERO_S),
        "clock_zero": round(statistics.median(offsets), 3) if offsets else None,
        "offset_spread_s": round(max(offsets) - min(offsets), 3) if offsets else None,
    })
    if not win:
        verdict = "NONE"
    elif game_id is None:
        verdict = "ID_SET" if roles["null"] == 0 else (
            "NULL_ONLY" if roles["null"] == len(win) else "MIXED")
    elif roles["match"] == len(win):
        verdict = "REAL_ID"
    elif roles["null"] == len(win):
        verdict = "NULL_ONLY"
    elif roles["other"]:
        verdict = "WRONG_ID"
    else:
        verdict = "MIXED"
    out["verdict"] = verdict
    out["offset_consistent"] = (None if out["offset_spread_s"] is None
                                else out["offset_spread_s"] <= OFFSET_SLACK_S)
    out["_window_rows"] = win
    return out


# -- listener log ------------------------------------------------------------------

def scan_log(paths: list, since: float, until: float, game_id: Optional[str],
             clock_zero: Optional[float], game_start: Optional[float] = None) -> dict:
    """Per-file outcome counts in the window, plus the newest listener start at or
    before ``since``. Raises OSError when an existing file cannot be read."""
    files = []
    recorded: list = []
    drops: list = []
    other = dict.fromkeys(OTHER_FRAGS, 0)
    starts_before: list = []
    starts_in = 0
    for p in paths:
        pp = Path(p)
        if not pp.is_file():
            files.append({"name": pp.name, "missing": True})
            continue
        n_rec = n_drop = 0
        for line in pp.read_text(encoding="utf-8", errors="replace").splitlines():
            t = _line_time(line)
            if t is None:
                continue
            if START_FRAG in line:
                if t < since:
                    starts_before.append((t, CHORD_FRAG in line))
                elif t <= until:
                    starts_in += 1
                continue
            if not _in(t, since, until):
                continue
            m = RECORDED_RE.search(line)
            if m:
                n_rec += 1
                gid = None if m.group(1) == "None" else m.group(1)
                recorded.append({"t": t, "role": _role(gid, game_id),
                                 "game_time_s": float(m.group(2))})
                continue
            if DROP_FRAG in line:
                n_drop += 1
                kind = next((k for k, f in DROP_KINDS.items() if f in line), "other")
                drops.append({"t": t, "kind": kind})
                continue
            for k, f in OTHER_FRAGS.items():
                if f in line:
                    other[k] += 1
        files.append({"name": pp.name, "recorded": n_rec, "dropped": n_drop})
    last = max(starts_before) if starts_before else None
    for d in drops:
        d["vs_clock_zero"] = (None if clock_zero is None
                              else ("before" if d["t"] < clock_zero else "after"))
        d["minus_clock_zero_s"] = (None if clock_zero is None
                                   else round(d["t"] - clock_zero, 1))
        d["before_game_start"] = None if game_start is None else d["t"] < game_start
    before = [d for d in drops if d["kind"] == "gamestats_unavailable"
              and d["vs_clock_zero"] == "before"]
    # A champ-select or lobby press is dropped the same way: a load drop also
    # needs the lower bound, at or after the first game phase.
    load = [d for d in before if d["before_game_start"] is False]
    if clock_zero is None:
        load_verdict = "UNKNOWN_NO_CLOCK_ZERO"
    elif load:
        load_verdict = "LOAD_DROP_SEEN"
    elif before and game_start is None:
        load_verdict = "LOAD_DROP_UNBOUNDED"
    else:
        load_verdict = "NO_LOAD_DROP"
    return {
        "files": files,
        "listener_start_before_window": None if last is None else round(last[0], 3),
        "listener_start_lists_chord": None if last is None else last[1],
        "listener_starts_in_window": starts_in,
        "recorded": len(recorded),
        "recorded_roles": {r: sum(1 for x in recorded if x["role"] == r)
                           for r in ("match", "other", "null")},
        "dropped": {k: sum(1 for d in drops if d["kind"] == k)
                    for k in (*DROP_KINDS, "other")},
        "drops": [{"t": round(d["t"], 3), "kind": d["kind"],
                   "vs_clock_zero": d["vs_clock_zero"],
                   "minus_clock_zero_s": d["minus_clock_zero_s"],
                   "before_game_start": d["before_game_start"]} for d in drops],
        "other": other,
        "presses_seen": len(recorded) + len(drops),
        "load_drop": load_verdict,
        "_recorded": recorded,
    }


# -- attach ------------------------------------------------------------------------

def grade_attach(pins_dir: Path, game_id: Optional[str], win: list, until: float) -> dict:
    if game_id is None:
        return {"verdict": "NO_GAME_ID"}
    try:
        pins = moment_marks.pins_for_match_strict(game_id, pins_dir)
    except moment_marks.MarksUnreadable:
        return {"verdict": "UNREADABLE"}
    if pins is None:
        return {"verdict": "NO_PIN_FILE"}
    doc = json.loads((pins_dir / f"{game_id}.json").read_text(encoding="utf-8"))

    def key(d: dict) -> Optional[tuple]:
        gt, wt = moment_marks._finite(d.get("game_time_s")), moment_marks._finite(d.get("wall_ts"))
        return None if gt is None or wt is None else (round(gt, 3), round(wt, 3))

    own = [r for r in win if r["game_id"] in (game_id, None)]
    want = {key(r) for r in own}
    have = [key(p) for p in pins]
    missing = len(want - set(have))
    extra = sum(1 for k in have if k not in want)
    attached_at = moment_marks._finite(doc.get("attached_at")) if isinstance(doc, dict) else None
    last = max((r["wall_ts"] for r in own), default=None)
    verdict = "ATTACHED" if not missing and not extra else ("EXTRA" if extra else "PARTIAL")
    return {
        "verdict": verdict,
        "pins": len(pins),
        "expected": len(want),
        "missing": missing,
        "extra": extra,
        "labels_ok": all(p.get("label") == moment_marks.PIN_LABEL for p in pins),
        "clock_s_ok": all(key(p) is not None and p.get("clock_s") == int(key(p)[0])
                          for p in pins),
        "attached_after_last_mark_s": (None if attached_at is None or last is None
                                       else round(attached_at - last, 1)),
        "attached_minus_until_s": (None if attached_at is None
                                   else round(attached_at - until, 1)),
    }


def first_game_phase(tape: dict, since: float, until: float) -> Optional[float]:
    """The first GameStart / InProgress / Reconnect time inside the window on an
    LX-01 phase tape (``load_tape`` output)."""
    return next((t for t, ph in tape.get("phases", [])
                 if ph in GAME_PHASES and _in(t, since, until)), None)


def grade(marks: Path, pins_dir: Path, logs: list, since: float, until: float,
          game_id: Optional[str], expect: Optional[int],
          game_start: Optional[float] = None, game_start_source: str = "none") -> dict:
    gid = moment_marks._norm_game_id(game_id)
    m = grade_marks(marks, since, until, gid)
    lg = scan_log(logs, since, until, gid, m["clock_zero"], game_start) if logs else None
    s: dict = {"window_s": round(until - since, 1), "game_id_given": gid is not None,
               "game_start": None if game_start is None else round(game_start, 3),
               "game_start_source": "none" if game_start is None else game_start_source,
               "marks": m, "log": lg,
               "attach": grade_attach(pins_dir, gid, m["_window_rows"], until)}
    if lg is not None:
        s["rows_vs_log"] = ("AGREE" if lg["recorded"] == m["rows_in_window"]
                            and lg["recorded_roles"] == m["id_roles"] else "DISAGREE")
    if expect is not None:
        seen = lg["presses_seen"] if lg is not None else None
        s["presses"] = {"expected": expect, "seen": seen,
                        "verdict": "UNKNOWN_NO_LOG" if seen is None
                        else ("MATCH" if seen == expect else "MISMATCH")}
    m.pop("_window_rows")
    if lg is not None:
        lg.pop("_recorded")
    return s


def render(s: dict) -> str:
    m, a = s["marks"], s["attach"]
    lines = [
        f"window {s['window_s']} s, game id given: {s['game_id_given']}, "
        f"game start: {s['game_start']} ({s['game_start_source']})",
        f"marks: file={m['file']} strict={m['strict']} rows={m['rows_in_window']}/"
        f"{m['rows_total']} roles={m['id_roles']} verdict={m['verdict']}",
        f"  game_time_s={m['game_time_s']} near_zero={m['near_zero']} "
        f"clock_zero={m['clock_zero']} spread={m['offset_spread_s']} "
        f"consistent={m['offset_consistent']} match_outside_window={m['match_outside_window']}",
    ]
    lg = s["log"]
    if lg is not None:
        lines += [
            f"log: start_before={lg['listener_start_before_window']} "
            f"lists_K={lg['listener_start_lists_chord']} starts_in_window="
            f"{lg['listener_starts_in_window']} files={lg['files']}",
            f"  recorded={lg['recorded']} roles={lg['recorded_roles']} dropped={lg['dropped']} "
            f"other={lg['other']} presses_seen={lg['presses_seen']} load_drop={lg['load_drop']}",
            f"  drops={lg['drops']}",
            f"rows_vs_log={s['rows_vs_log']}",
        ]
    if "presses" in s:
        lines.append(f"presses: {s['presses']}")
    lines.append(f"attach: {a}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="read-only LX-09 check of the mark-this-moment hotkey")
    ap.add_argument("--since", required=True, help="epoch or ISO; naive = local")
    ap.add_argument("--until", required=True)
    ap.add_argument("--game-id", default=None, help="the LCU gameId (input only, never printed)")
    ap.add_argument("--expect-presses", type=int, default=None)
    gs = ap.add_mutually_exclusive_group()
    gs.add_argument("--phase-tape", default=None,
                    help="an LX-01 tape; its first game phase bounds a load drop from below")
    gs.add_argument("--game-start", default=None,
                    help="epoch or ISO of the first GameStart / InProgress, if no tape")
    ap.add_argument("--marks", default=str(moment_marks.marks_path()))
    ap.add_argument("--pins-dir", default=str(moment_marks.attached_dir()))
    ap.add_argument("--log", action="append", default=None,
                    help="a log file or quoted glob (repeatable); default logs/hotkey_listener.log*")
    ap.add_argument("--no-log", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    since, until = parse_when(a.since), parse_when(a.until)
    if since is None or until is None or until < since:
        print("--since / --until: not a time, or until before since", file=sys.stderr)
        return 2
    logs = [] if a.no_log else expand_logs(a.log or [DEFAULT_LOG])
    game_start, source = None, "none"
    if a.game_start is not None:
        game_start, source = parse_when(a.game_start), "flag"
        if game_start is None:
            print("--game-start: not a time", file=sys.stderr)
            return 2
    try:
        if a.phase_tape:
            tape = load_tape(Path(a.phase_tape))
            game_start, source = first_game_phase(tape, since, until), "tape"
        s = grade(Path(a.marks), Path(a.pins_dir), logs, since, until,
                  a.game_id, a.expect_presses, game_start, source)
    except OSError as exc:
        print(f"unreadable: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(s, indent=2, sort_keys=True) if a.json else render(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
