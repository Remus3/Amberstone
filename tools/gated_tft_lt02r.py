"""gated_tft_lt02r.py - LT-02r read-back: which Set 18 shop-odds rows are on disk, and what to pin.

LT-02r (filed s134 M1b, the residual of LT-02) has two halves the session 134
QA game did not read: (1) the Set 18 champion pool sizes per cost and (2) the
shop odds at the levels the HUD was never read at (``tft/tft_data.py``
``TIER_ODDS`` levels outside ``TIER_ODDS_VERIFIED_LEVELS``: L1-L3, L10, L11).
``CONSTANTS_SET_VERIFIED`` stays False until both are read. This tool makes the
drain one command:

  - CONSTANTS: the levels still unpinned, their current (game-data) rows in
    percent, ``POOL_SIZES`` / ``POOL_SIZES_FROM_SET`` and ``UNITS_PER_COST``.
  - FRAMES (read-only index of the tft_qa recorder's match directories under
    ``ops/runtime/tft_qa/``): per unpinned level, the frames a human already
    labelled at that level (``hud_labels_*.csv`` ``level`` column) and, for
    L1 and L10, CANDIDATE frames: the labelled frames before the first L2
    frame of a match (level box not read), and the last game / vision frames
    of a match whose end-of-game board held 10 or more units (``eog_raw.json``
    ``localPlayer.boardPieces``; an INFERENCE - an extra-slot augment also
    gives 10, so a candidate is a frame to look at, never a level reading).
    It prints file names, levels and game times only: never a pixel, a name,
    a game id or a puuid (the frames show player names; they stay on disk),
    and the recorder root as a placeholder (``<main>/ops/runtime/tft_qa``).
  - ROSTER (headless, the compute half): units per cost from the Set 18
    CommunityDragon extract (``data/meta/tft_set18_cdragon.json`` unit costs)
    restricted to the team-planner roster read in a live Set 18 lobby
    (``data/meta/tft_set18_champion_codes.json``, LT-03), against
    ``UNITS_PER_COST``. The planner roster is an in-client list, but whether
    every planner unit is in the shop pool is NOT shown by it.
  - CHECK (``--check-read L=a/b/c/d/e``): a row a human read off a frame's
    odds bar, in percent, compared with the current ``TIER_ODDS`` row (sum to
    100, equal or not, per-cost difference).

POOL SIZES have no in-client surface (the HUD and the shop never show them),
so that half reads ``no_client_surface``: only game data can answer it, which
the doc row records as a reclassification proposal, not a move.

READ-ONLY: it opens files for reading and prints; it never writes, moves,
locks or deletes anything (the recorder directories least of all), and it
never ticks a row - its output is the INPUT to the four-part evidence
contract in ``docs/LIVE_GAME_GATED_SYNC.md``, never the evidence itself.

USAGE (from a worktree it reads the MAIN checkout's ops/runtime/tft_qa)
    python tools/gated_tft_lt02r.py
    python tools/gated_tft_lt02r.py --json
    python tools/gated_tft_lt02r.py --check-read 2=100/0/0/0/0 --check-read 10=5/10/20/40/25
Exit 0 = report (and every --check-read equal to the table), 1 = a
--check-read differs from the table or does not sum to 100, 2 = bad arguments.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.gated_frame_readback import main_checkout  # noqa: E402

QA_REL = Path("ops") / "runtime" / "tft_qa"
EXTRACT_REL = Path("data") / "meta" / "tft_set18_cdragon.json"
CODES_REL = Path("data") / "meta" / "tft_set18_champion_codes.json"
COSTS = (1, 2, 3, 4, 5)
FRAME_KINDS = ("game", "vision")
L10_BOARD = 10
LATE_CANDIDATES = 8


# -- constants ---------------------------------------------------------------

def _pct(row: dict) -> list[int]:
    return [round(float(row.get(c, 0.0)) * 100) for c in COSTS]


def constants(module: Any = None) -> dict[str, Any]:
    """The unpinned TIER_ODDS levels and the pool tables, from tft/tft_data.py."""
    if module is None:
        from tft import tft_data as module
    odds = getattr(module, "TIER_ODDS", {}) or {}
    pinned = set(getattr(module, "TIER_ODDS_VERIFIED_LEVELS", ()) or ())
    unpinned = sorted(lv for lv in odds if lv not in pinned)
    return {
        "constants_set": getattr(module, "CONSTANTS_SET", None),
        "constants_set_verified": bool(getattr(module, "CONSTANTS_SET_VERIFIED", False)),
        "verified_levels": sorted(pinned),
        "unpinned_levels": unpinned,
        "unpinned_rows_pct": {lv: _pct(odds[lv]) for lv in unpinned},
        "pool_sizes": dict(getattr(module, "POOL_SIZES", {}) or {}),
        "pool_sizes_from_set": getattr(module, "POOL_SIZES_FROM_SET", None),
        "units_per_cost": dict(getattr(module, "UNITS_PER_COST", {}) or {}),
    }


# -- check a human read ------------------------------------------------------

def parse_read(spec: str) -> tuple[int, list[int]]:
    """``"10=5/10/20/40/25"`` -> ``(10, [5, 10, 20, 40, 25])``; ValueError if malformed."""
    level_s, sep, row_s = spec.partition("=")
    if not sep:
        raise ValueError(f"expected L=a/b/c/d/e, got {spec!r}")
    level = int(level_s.strip())
    parts = [p.strip() for p in row_s.split("/")]
    if len(parts) != len(COSTS):
        raise ValueError(f"expected {len(COSTS)} percents, got {len(parts)} in {spec!r}")
    row = [int(p) for p in parts]
    if level < 1 or any(v < 0 or v > 100 for v in row):
        raise ValueError(f"level must be >= 1 and each percent 0-100 in {spec!r}")
    return level, row


def check_read(level: int, read: list[int], odds: dict) -> dict[str, Any]:
    """A read row against the TIER_ODDS row at that level."""
    out: dict[str, Any] = {"level": level, "read": read, "sums_to_100": sum(read) == 100}
    if level not in odds:
        out.update(table=None, equal=False, diff=None)
        return out
    table = _pct(odds[level])
    out.update(table=table, equal=table == read,
               diff={c: r - t for c, r, t in zip(COSTS, read, table) if r != t})
    return out


# -- roster (headless compute half) ------------------------------------------

def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def roster(extract: Any, codes: Any, units_per_cost: dict) -> dict[str, Any]:
    """Units per cost over the live team-planner roster, against UNITS_PER_COST."""
    units = extract.get("units") if isinstance(extract, dict) else None
    if not isinstance(units, list) or not isinstance(codes, dict):
        return {"available": False}
    planner = set(codes)
    cost_of: dict[str, int] = {}
    for u in units:
        if isinstance(u, dict) and isinstance(u.get("name"), str) and isinstance(u.get("cost"), int):
            cost_of.setdefault(u["name"], u["cost"])
    on_planner = Counter(c for n, c in cost_of.items() if n in planner)
    measured = {c: on_planner.get(c, 0) for c in COSTS}
    return {
        "available": True,
        "extract_units": len(cost_of),
        "planner_units": len(planner),
        "planner_units_without_cost": len(planner - set(cost_of)),
        "extract_only_units": len(set(cost_of) - planner),
        "units_per_cost_planner": measured,
        "units_per_cost_table": {c: units_per_cost.get(c) for c in COSTS},
        "differs_at": [c for c in COSTS if measured[c] != units_per_cost.get(c)],
    }


# -- recorder frame index ----------------------------------------------------

def _int(text: Any) -> int | None:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


def read_labels(match_dir: Path) -> list[dict[str, Any]]:
    """Hand-labelled frames (``hud_labels_*.csv``): file, gt, level (None = not read)."""
    rows: list[dict[str, Any]] = []
    for path in sorted(match_dir.glob("hud_labels_*.csv")):
        try:
            lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        except OSError:
            continue
        body = [ln for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
        for rec in csv.DictReader(body):
            if rec.get("file"):
                rows.append({"file": rec["file"], "gt": _int(rec.get("gt")),
                             "level": _int(rec.get("level"))})
    return rows


def eog_board_units(match_dir: Path) -> int | None:
    data = _read_json(match_dir / "eog_raw.json")
    local = data.get("localPlayer") if isinstance(data, dict) else None
    pieces = local.get("boardPieces") if isinstance(local, dict) else None
    return len(pieces) if isinstance(pieces, list) else None


def game_frames(match_dir: Path) -> list[dict[str, Any]]:
    """Game / vision frames from ``frames.jsonl`` in capture order (file, gt, el)."""
    out: list[dict[str, Any]] = []
    try:
        lines = (match_dir / "frames.jsonl").read_text(encoding="utf-8-sig",
                                                       errors="replace").splitlines()
    except OSError:
        return out
    for ln in lines:
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("kind") in FRAME_KINDS and rec.get("file"):
            out.append({"file": rec["file"], "kind": rec["kind"], "gt": _int(rec.get("gt")),
                        "el": _int(rec.get("el")), "t": rec.get("t")})
    out.sort(key=lambda r: r["t"] if isinstance(r["t"], (int, float)) else 0.0)
    return out


def scan_match(match_dir: Path, levels: list[int]) -> dict[str, Any]:
    labels = read_labels(match_dir)
    board = eog_board_units(match_dir)
    by_level = {lv: [r["file"] for r in labels if r["level"] == lv] for lv in levels}
    first_l2 = min((r["gt"] for r in labels if r["level"] == 2 and r["gt"] is not None),
                   default=None)
    early = ([r["file"] for r in labels if r["level"] is None and r["gt"] is not None
              and r["gt"] < first_l2] if first_l2 is not None else [])
    l10_hint = board is not None and board >= L10_BOARD
    late = [f["file"] for f in game_frames(match_dir)[-LATE_CANDIDATES:]] if l10_hint else []
    return {"match": match_dir.name, "labelled_frames": len(labels),
            "labelled_by_level": {lv: fs for lv, fs in by_level.items() if fs},
            "l1_candidates": early, "eog_board_units": board, "l10_hint": l10_hint,
            "l10_candidates": late}


def match_dirs(qa_root: Path) -> list[Path]:
    try:
        return sorted(p for p in qa_root.iterdir() if p.is_dir() and (p / "frames.jsonl").is_file())
    except OSError:
        return []


def level_verdicts(levels: list[int], matches: list[dict[str, Any]]) -> dict[int, str]:
    """Per unpinned level: on_disk_labelled / on_disk_candidate / needs_game."""
    out: dict[int, str] = {}
    for lv in levels:
        if any(m["labelled_by_level"].get(lv) for m in matches):
            out[lv] = "on_disk_labelled"
        elif (lv == 1 and any(m["l1_candidates"] for m in matches)) or (
                lv == L10_BOARD and any(m["l10_candidates"] for m in matches)):
            out[lv] = "on_disk_candidate"
        else:
            out[lv] = "needs_game"
    return out


# -- report ------------------------------------------------------------------

def default_qa_root(root: Path = _ROOT) -> Path:
    main = main_checkout(root)
    return (main or root) / QA_REL


def display_root(qa_root: Path, root: Path = _ROOT) -> str:
    """A placeholder label for the recorder root, so a pasted report carries no machine path."""
    if qa_root == default_qa_root(root):
        return "<main>/" + QA_REL.as_posix()
    return "<qa-root>/" + qa_root.name


def build_report(qa_root: Path, root: Path = _ROOT, module: Any = None) -> dict[str, Any]:
    consts = constants(module)
    levels = consts["unpinned_levels"]
    matches = [scan_match(d, levels) for d in match_dirs(qa_root)]
    return {
        "row": "LT-02r",
        "qa_root": display_root(qa_root, root),
        "constants": consts,
        "matches": matches,
        "level_verdicts": level_verdicts(levels, matches),
        "pool_sizes_verdict": "no_client_surface",
        "roster": roster(_read_json(root / EXTRACT_REL), _read_json(root / CODES_REL),
                         consts["units_per_cost"]),
    }


def _text(rep: dict[str, Any]) -> str:
    c = rep["constants"]
    lines = [f"LT-02r read-back over {len(rep['matches'])} recorder match dir(s) at {rep['qa_root']}",
             f"CONSTANTS_SET {c['constants_set']} verified={c['constants_set_verified']} "
             f"pinned levels {c['verified_levels']}"]
    for lv in c["unpinned_levels"]:
        lines.append(f"  L{lv}: table {'/'.join(map(str, c['unpinned_rows_pct'][lv]))} -> "
                     f"{rep['level_verdicts'][lv]}")
    for m in rep["matches"]:
        bits = [f"{m['match']}: labelled {m['labelled_frames']}",
                f"eog board {m['eog_board_units']}"]
        bits += [f"L{lv} {len(fs)} ({fs[0]})" for lv, fs in m["labelled_by_level"].items()]
        if m["l1_candidates"]:
            bits.append(f"L1 candidates {len(m['l1_candidates'])} ({m['l1_candidates'][0]})")
        if m["l10_candidates"]:
            bits.append(f"L10 candidates {len(m['l10_candidates'])} (last {m['l10_candidates'][-1]})")
        lines.append("  " + "; ".join(bits))
    lines.append(f"POOL_SIZES {c['pool_sizes']} from set {c['pool_sizes_from_set']} -> "
                 f"{rep['pool_sizes_verdict']}")
    r = rep["roster"]
    if r.get("available"):
        lines.append(f"UNITS_PER_COST table {r['units_per_cost_table']} vs live planner x game data "
                     f"{r['units_per_cost_planner']} (differs at {r['differs_at']}; "
                     f"{r['extract_only_units']} extract-only variant(s))")
    else:
        lines.append("UNITS_PER_COST: roster files unreadable")
    for chk in rep.get("checks", []):
        lines.append(f"CHECK L{chk['level']} read {chk['read']} table {chk['table']} "
                     f"equal={chk['equal']} sums_to_100={chk['sums_to_100']} diff={chk['diff']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--qa-root", type=Path, default=None)
    ap.add_argument("--check-read", action="append", default=[], metavar="L=a/b/c/d/e")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        reads = [parse_read(s) for s in args.check_read]
    except ValueError as exc:
        print(f"bad --check-read: {exc}", file=sys.stderr)
        return 2
    rep = build_report(args.qa_root or default_qa_root())
    from tft import tft_data
    rep["checks"] = [check_read(lv, row, tft_data.TIER_ODDS) for lv, row in reads]
    print(json.dumps(rep, indent=2, sort_keys=True) if args.json else _text(rep))
    return 0 if all(c["equal"] and c["sums_to_100"] for c in rep["checks"]) else 1


if __name__ == "__main__":
    sys.exit(main())
