"""gated_g242_zoi_check.py - read-only grader for G2-42 (ZOI finalization eyeball).

G2-42 asks four live questions of the ZOI minimap stack in a practice SR game
(docs/ZOI_DISTRICT_ORCHESTRATION_PLAN.md section 4 "Live-gated
finalization"): (a) a macro callout fires when >=2 enemies are MIA near a
drake spawn, (b) the district vector populates, (c) OBS frames match the GDI
baseline, (d) MIA rings + the fluid DMZ + the weighted bubbles render. (b) and
(c) were advanced live on 2026-07-20 (doc header) and (c) was flipped on
2026-07-05 (LEDGER 796). This tool grades what a SAVED artifact can say about
(a), (b) and (d), so a drain does not re-derive it mid-game.

Three facts measured at source (s144 lane gated c46) shape the verdicts:

- The fog feed is DEAD on SR. ``core/vision_tracker.py`` ``_compute_enemies``
  derives fog from ``allPlayers[].position`` COORDINATES; the client sends a
  role string, so ``pos`` coerces to ``{}``, ``x == z == 0`` and the first
  sighting never happens: every enemy keeps ``missing_for_s=None``. Nothing
  feeds the minimap identity dots (``zoi.champion_dots``) back into the
  tracker. So (a) and the MIA-ring half of (d) cannot pass in any game until a
  feed is built (``fog`` reports FEED_DEAD vs FEED_LIVE).
- The DMZ is NOT WIRED. ``dashboard/_state_builder.py`` calls
  ``compute_zoi(minimap_dots, my_level=, game_time_s=)`` with no roster, and
  ``core/zoi_influence.compute_zoi`` emits NO ``dmz`` key at all when both
  rosters are None. So the DMZ half of (d) cannot render (DMZ_NOT_WIRED).
- Served callouts are blank in a live game (B4 / RM-189
  ``suppress_live_envelope`` blanks ``callouts``), so "(a) on
  ``/api/state.callouts``" can never be read live. The only record of a macro
  row is the pre-suppression shadow log ``data/det_coach_shadow.jsonl``
  (``core/det_coach_shadow.py``, field ``callouts``, ``kind == "macro"``).

Sub-commands (all READ-ONLY: no network, no write, no tick):

  state FILE [FILE ...]
      Saved ``/api/state`` JSONs. Only in-game SR files count (an SR-equivalent
      ``mode_key`` and a non-empty ``liveclient``). Per check: districts (B_OK when
      ``zoi.districts`` AND ``zoi.districts_fused`` each carry every SR
      district), bubbles, mia, dmz, and the served macro rows (always 0 live).
  fog FILE [FILE ...]
      Saved ``data/vision_state.json`` copies; only SR ``game_mode`` copies
      count (``SR_GAME_MODES``). FEED_LIVE when any ALIVE enemy row carries a
      numeric ``missing_for_s``; FEED_DEAD when SR enemy rows exist and none
      does; NO_ENEMIES (SR copies, no enemy rows); NOT_SR (no SR copy).
      Reports the most alive enemies MIA for at least ``MIN_MIA_S`` at once
      (the macro tree needs 2).
  shadow FILE --since ISO [--until ISO]
      Objective-danger macro rows (``kind == "macro"``, ``tag ==
      OBJECTIVE_TAG``) in the shadow log inside [--since, --until],
      SR-equivalent modes only; other macro rows (the gank warning) are
      counted apart and never pass. MACRO_SEEN / NO_MACRO (SR records, no
      objective row) / NO_RESULT (no SR record in the window).

Nothing printed carries a summoner name or Riot ID (``vision_state.json``
rows hold ``summoner_name``; it is never read here). Champion names only.

Exit 0 = B_OK / FEED_LIVE / MACRO_SEEN; 3 = any other verdict; 2 = an input
file missing or unreadable.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.macro_decision_tree import MIN_MIA_S  # noqa: E402
from core.minimap_districts import load_grid  # noqa: E402
from tools.gated_g239_wave_clock import (  # noqa: E402
    SR_MODE_KEYS,
    _record_time,
    parse_since,
)

# Live Client gameMode values RC treats as SR (restates core/sr_aram_worker.py
# is_sr_mode; pinned by the tests). A vision_state copy from any other mode is
# skipped: in ARAM / KIWI the tracker stamps every alive enemy each tick, so a
# DEAD enemy there carries a numeric missing_for_s that says nothing about the
# SR fog feed.
SR_GAME_MODES = frozenset({"CLASSIC", "RANKED", "PRACTICETOOL", "JADE"})

# The (a) rule: the macro tree's objective-danger row (>= 2 MIA plus a drake or
# baron inside the window). The gank warning is a different rule.
OBJECTIVE_TAG = "macro_objective_danger"


def sr_district_ids() -> frozenset:
    grid = load_grid("sr")
    return frozenset(d.id for d in grid.districts) if grid is not None else frozenset()


def _finite(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _ids(rows: Any) -> set:
    if not isinstance(rows, list):
        return set()
    return {str(r.get("district")) for r in rows if isinstance(r, dict) and r.get("district")}


def grade_states(states: list) -> dict:
    want = sr_district_ids()
    out: dict = {"files": len(states), "in_game_sr": 0, "zoi_present": 0,
                 "districts": "NOT_IN_GAME", "bubbles": "NOT_IN_GAME",
                 "mia": "NOT_IN_GAME", "dmz": "NOT_IN_GAME",
                 "mia_rings_max": 0, "bubbles_max": 0, "served_macro_rows": 0,
                 "sr_districts": len(want)}
    seen_b = seen_bub = seen_rings = seen_mia_key = seen_dmz_key = False
    dmz_ok = False
    for st in states:
        if not isinstance(st, dict):
            continue
        lc = st.get("liveclient")
        if st.get("mode_key") not in SR_MODE_KEYS or not isinstance(lc, dict) or not lc:
            continue
        out["in_game_sr"] += 1
        # dashboard/_state_builder.py gates compute_zoi on mode_key in
        # ("sr", "aram"), so an SR game read under "client" / "game" serves no
        # zoi and lands in ZOI_ABSENT below, never NOT_IN_GAME.
        callouts = st.get("callouts")
        if isinstance(callouts, list):
            out["served_macro_rows"] += sum(
                1 for c in callouts if isinstance(c, dict) and c.get("kind") == "macro")
        zoi = st.get("zoi")
        if not isinstance(zoi, dict):
            continue
        out["zoi_present"] += 1
        if want and want <= _ids(zoi.get("districts")) and want <= _ids(zoi.get("districts_fused")):
            seen_b = True
        bub = zoi.get("bubbles")
        if isinstance(bub, list) and bub:
            seen_bub = True
            out["bubbles_max"] = max(out["bubbles_max"], len(bub))
        if "mia" in zoi:
            seen_mia_key = True
            mia = zoi.get("mia")
            rings = mia.get("rings") if isinstance(mia, dict) else None
            if isinstance(rings, list) and rings:
                seen_rings = True
                out["mia_rings_max"] = max(out["mia_rings_max"], len(rings))
        if "dmz" in zoi:
            seen_dmz_key = True
            dmz = zoi.get("dmz")
            path = dmz.get("path") if isinstance(dmz, dict) else None
            if isinstance(path, list) and len(path) >= 2:
                dmz_ok = True
    if not out["in_game_sr"]:
        return out
    if not out["zoi_present"]:
        for key in ("districts", "bubbles", "mia", "dmz"):
            out[key] = "ZOI_ABSENT"
        return out
    out["districts"] = "B_OK" if seen_b else "B_MISSING"
    out["bubbles"] = "BUBBLES_PRESENT" if seen_bub else "BUBBLES_EMPTY"
    out["mia"] = "MIA_RINGS" if seen_rings else ("MIA_EMPTY" if seen_mia_key else "MIA_ABSENT")
    if dmz_ok:
        out["dmz"] = "DMZ_PRESENT"
    else:
        out["dmz"] = "DMZ_DEGENERATE" if seen_dmz_key else "DMZ_NOT_WIRED"
    return out


def grade_fog(docs: list) -> dict:
    out: dict = {"files": len(docs), "sr_files": 0, "skipped_modes": [],
                 "enemy_rows": 0, "numeric_missing": 0,
                 "mia_ge_min_max": 0, "min_mia_s": MIN_MIA_S, "verdict": "NOT_SR",
                 "champions_mia": []}
    mia_names: list = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        mode = str(doc.get("game_mode") or "").upper()
        if mode not in SR_GAME_MODES:
            if mode not in out["skipped_modes"]:
                out["skipped_modes"].append(mode)
            continue
        out["sr_files"] += 1
        enemies = doc.get("enemies")
        if not isinstance(enemies, dict):
            continue
        at_once = 0
        for row in enemies.values():
            if not isinstance(row, dict):
                continue
            out["enemy_rows"] += 1
            m = _finite(row.get("missing_for_s"))
            # A dead enemy is not MIA: only an alive one proves the fog clock.
            if m is None or row.get("is_dead"):
                continue
            out["numeric_missing"] += 1
            if m >= MIN_MIA_S:
                at_once += 1
                name = str(row.get("champion") or "?")
                if name not in mia_names:
                    mia_names.append(name)
        out["mia_ge_min_max"] = max(out["mia_ge_min_max"], at_once)
    out["champions_mia"] = mia_names
    if out["numeric_missing"]:
        out["verdict"] = "FEED_LIVE"
    elif out["enemy_rows"]:
        out["verdict"] = "FEED_DEAD"
    elif out["sr_files"]:
        out["verdict"] = "NO_ENEMIES"
    return out


def grade_shadow(records: list, since, until=None) -> dict:
    out: dict = {"verdict": "NO_RESULT", "sr_records": 0, "macro_rows": 0,
                 "other_macro_rows": 0, "tag": OBJECTIVE_TAG, "first_macro": None}
    for rec in records:
        if not isinstance(rec, dict) or rec.get("mode") not in SR_MODE_KEYS:
            continue
        rt = _record_time(rec.get("ts"))
        if rt is None or rt < since or (until is not None and rt > until):
            continue
        out["sr_records"] += 1
        callouts = rec.get("callouts")
        if not isinstance(callouts, list):
            continue
        for c in callouts:
            if not isinstance(c, dict) or c.get("kind") != "macro":
                continue
            if c.get("tag") != OBJECTIVE_TAG:
                out["other_macro_rows"] += 1
                continue
            out["macro_rows"] += 1
            if out["first_macro"] is None:
                out["first_macro"] = {"game_time_s": _finite(rec.get("game_time_s")),
                                      "tag": OBJECTIVE_TAG,
                                      "line": str(c.get("line") or "")[:120]}
    if out["macro_rows"]:
        out["verdict"] = "MACRO_SEEN"
    elif out["sr_records"]:
        out["verdict"] = "NO_MACRO"
    return out


def _read_jsonl(path: Path) -> list:
    rows: list = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def _load(paths: list) -> list:
    return [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_st = sub.add_parser("state")
    p_st.add_argument("files", nargs="+", type=Path)
    p_fog = sub.add_parser("fog")
    p_fog.add_argument("files", nargs="+", type=Path)
    p_sh = sub.add_parser("shadow")
    p_sh.add_argument("file", type=Path)
    p_sh.add_argument("--since", required=True)
    p_sh.add_argument("--until", default=None)
    for p in (p_st, p_fog, p_sh):
        p.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "state":
            res = grade_states(_load(args.files))
            good = res["districts"] == "B_OK"
        elif args.cmd == "fog":
            res = grade_fog(_load(args.files))
            good = res["verdict"] == "FEED_LIVE"
        else:
            until = parse_since(args.until) if args.until else None
            res = grade_shadow(_read_jsonl(args.file), parse_since(args.since), until)
            good = res["verdict"] == "MACRO_SEEN"
    except (OSError, ValueError) as exc:
        print(f"unreadable input: {type(exc).__name__}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(res))
    else:
        for key, val in res.items():
            print(f"{key}: {val}")
    return 0 if good else 3


if __name__ == "__main__":
    sys.exit(main())
