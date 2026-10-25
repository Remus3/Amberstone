"""tft/engine/milestones.py - the "milestone decisions used on average" of
docs/TFT_PROGRAM.md section 5 output 2, mined from the per-round store.

PER MATCH (mine_match), from the operator's own per-round rows:
  * level_reached  - the round label at which levels 4..9 were first reached.
                     Credited only when an EARLIER observed round shows a lower
                     level (otherwise the level was reached before capture
                     began: it goes to censored_levels, never invented) and the
                     NEXT observed round does not contradict it (an isolated
                     high read is a misread, not a level-up).
  * rolldowns      - rounds with >= ROLLDOWN_MIN_REROLLS rerolls or
                     >= ROLLDOWN_MIN_GOLD gold spent on rerolls (shop_refresh
                     rows with cause 'reroll'; gold from their gold_before /
                     gold_after deltas). A big spend with fewer rerolls - a
                     level-up plus a 5-cost buy - is not a roll-down.
  * first_slam     - the first round a unit holds an item crafted from
                     components (unit_obs rows); censored when the first
                     observed round already shows one.
  * gold_at / hp_at - planning-start gold at 3-2 and 4-1, HP at 4-1.
  * star_ups       - when each unit first reached 2 and 3 stars.
  * opener         - board units at the last observed stage-2 round.
Only values that count as evidence are used (comps.envelope_value: no
'absent', no 'llm_fallback', conf >= FIELD_MIN_CONF).

PER COMP (milestones_by_comp), over the comp's TOP-4 matches only by default:
round labels aggregate as the LOWER median and nearest-rank quartiles of the
(stage, round) order - always a real label, never an interpolated one, and no
round schedule is needed (Set 18's schedule is still being verified, LT-01).
Gold and HP aggregate as median / quartiles / IQR of the numbers.

INPUT SHAPE (TFT-01 schema v1, section 1.5) - a match record as in comps.py,
with:
  "rounds":         [round rows: round_seq, stage, round, label, level,
                     gold_start, gold_end, hp_start, each with _conf / _src]
  "shop_refreshes": [shop_refresh rows: round_seq, refresh_idx, cause,
                     gold_before, gold_after, conf, src]
  "units":          [unit_obs rows of the LOCAL player: round_seq, phase, zone,
                     champion_api, star, items_json, conf, src]
records_from_store() builds these records from the TFT-01 read API
(list_matches / get_match / iter_rounds; the real store nests unit_obs and
shop_refresh rows in each round bundle, so they are flattened from there) and
takes the final board from TFT-08 ground truth (tft/rounds/ground_truth.py
final_boards, else the match's gt_board rows); a record without rounds (match
history cold start) still feeds the catalogue and simply mines nothing.
"""
from __future__ import annotations

import math
import sqlite3
import statistics
from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping, Optional

from tft.engine import engine_meta
from tft.engine.comps import (
    TOP4_MAX_PLACEMENT,
    SetData,
    as_int,
    canonical,
    comp_units,
    envelope_value,
    normalize_unit,
    ordered_records,
    placement_of,
    record_id,
    row_is_evidence,
)

LEVELS = (4, 5, 6, 7, 8, 9)
ROLLDOWN_MIN_REROLLS = 3
ROLLDOWN_MIN_GOLD = 20
GOLD_CHECKPOINTS = ("3-2", "4-1")
HP_CHECKPOINTS = ("4-1",)
OPENER_STAGE = 2
OPENER_SHARE = 0.5
STAR_TARGETS = (2, 3)
SKIP_PHASES = frozenset({"carousel"})
BOARD_ZONES = frozenset({"board", "bench"})
GT_SOURCE_ORDER = ("lcu_eog", "lcu_mh", "match_v1", "eog_file_final")
_STORE_ERRORS = (OSError, ValueError, TypeError, KeyError, AttributeError, LookupError, sqlite3.Error)


# ------------------------------------------------------------------ labels

def parse_label(label: Any) -> Optional[tuple]:
    """'3-2' -> (3, 2); anything else -> None."""
    if not isinstance(label, str):
        return None
    parts = label.strip().split("-")
    if len(parts) != 2:
        return None
    stage, rnd = as_int(parts[0]), as_int(parts[1])
    if stage is None or rnd is None or stage < 1 or rnd < 1:
        return None
    return (stage, rnd)


def format_label(key: tuple) -> str:
    return f"{key[0]}-{key[1]}"


def _round_key(row: Mapping) -> Optional[tuple]:
    key = parse_label(row.get("label"))
    if key is not None:
        return key
    stage, rnd = as_int(envelope_value(row, "stage")), as_int(envelope_value(row, "round"))
    if stage is None or rnd is None or stage < 1 or rnd < 1:
        return None
    return (stage, rnd)


def _rows(value: Any) -> list:
    """The Mapping rows of a list-valued record field; anything else is no rows."""
    if not isinstance(value, (list, tuple)):
        return []
    return [r for r in value if isinstance(r, Mapping)]


def _timeline(record: Mapping) -> list:
    """[(round_seq, (stage, round), row)] in round_seq order, labelled rows only.

    Two rows for one round_seq resolve by content (canonical text), never by
    input order, so a duplicated round cannot make the result order-dependent.
    """
    rows = []
    for row in _rows(record.get("rounds")):
        seq = as_int(row.get("round_seq"))
        key = _round_key(row)
        if seq is None or key is None:
            continue
        rows.append((seq, key, canonical(row), row))
    rows.sort(key=lambda t: (t[0], t[1], t[2]))
    out, seen = [], set()
    for seq, key, _text, row in rows:
        if seq not in seen:
            seen.add(seq)
            out.append((seq, key, row))
    return out


# ------------------------------------------------------------------ levels

def _levels(timeline: list) -> tuple:
    observed = []
    for _seq, key, row in timeline:
        lvl = as_int(envelope_value(row, "level"))
        if lvl is not None and 1 <= lvl <= 10:
            observed.append((key, lvl))
    reached, censored = {}, []
    for target in LEVELS:
        for i, (key, lvl) in enumerate(observed):
            if lvl < target:
                continue
            nxt = observed[i + 1][1] if i + 1 < len(observed) else None
            if nxt is not None and nxt < target:
                continue  # an isolated high read: the next round contradicts it
            if any(prev < target for _k, prev in observed[:i]):
                reached[str(target)] = format_label(key)
            else:
                censored.append(target)
            break
    level_at = {format_label(k): lvl for k, lvl in observed}
    return reached, censored, level_at


# --------------------------------------------------------------- rolldowns

def _rolldowns(timeline: list, refreshes: Iterable) -> list:
    by_seq: dict = defaultdict(list)
    for row in _rows(refreshes):
        if row_is_evidence(row) and as_int(row.get("round_seq")) is not None:
            by_seq[as_int(row["round_seq"])].append(row)
    out = []
    for seq, key, row in timeline:
        rows = sorted(by_seq.get(seq, []), key=lambda r: (as_int(r.get("refresh_idx")) or 0, canonical(r)))
        rolls = [r for r in rows if r.get("cause") == "reroll"]
        gold = 0
        last_after = None
        for r in rolls:
            before, after = as_int(r.get("gold_before")), as_int(r.get("gold_after"))
            if before is not None and after is not None:
                gold += max(0, before - after)
            if after is not None:
                last_after = after
        if len(rolls) < ROLLDOWN_MIN_REROLLS and gold < ROLLDOWN_MIN_GOLD:
            continue
        gold_end = as_int(envelope_value(row, "gold_end"))
        out.append({"label": format_label(key), "rerolls": len(rolls), "reroll_gold": gold,
                    "gold_start": as_int(envelope_value(row, "gold_start")),
                    "gold_end": gold_end if gold_end is not None else last_after})
    return out


# ------------------------------------------------------------ unit history

def _unit_rounds(record: Mapping, timeline: list, setdata: SetData) -> list:
    """[(key, [Unit on board/bench], [Unit on board])] per observed round, in order."""
    key_of = {seq: key for seq, key, _row in timeline}
    per: dict = defaultdict(lambda: ([], []))
    for row in _rows(record.get("units")):
        if not row_is_evidence(row):
            continue
        phase, zone = row.get("phase"), row.get("zone", "board")
        if (isinstance(phase, str) and phase in SKIP_PHASES) or not isinstance(zone, str) or zone not in BOARD_ZONES:
            continue
        seq = as_int(row.get("round_seq"))
        if seq not in key_of:
            continue
        unit = normalize_unit(row, setdata)
        if unit is None:
            continue
        both, board = per[seq]
        both.append(unit)
        if zone == "board":
            board.append(unit)
    return [(key_of[seq], per[seq][0], per[seq][1]) for seq in sorted(per)]


def _slam(unit_rounds: list, setdata: SetData) -> tuple:
    for i, (key, units, _board) in enumerate(unit_rounds):
        slams = sorted((item, unit.api) for unit in units for item in unit.items if item in setdata.recipes)
        if not slams:
            continue
        if i == 0:
            return None, True
        item, api = slams[0]
        return {"label": format_label(key), "item": item, "unit": api}, False
    return None, False


def _star_ups(unit_rounds: list) -> dict:
    """{api: {"2": label, "3": label}}; a star already held on the first observed round is censored."""
    out: dict = {}
    settled: set = set()
    for i, (key, units, _board) in enumerate(unit_rounds):
        best: dict = {}
        for unit in units:
            best[unit.api] = max(best.get(unit.api, 0), unit.star)
        for api, star in best.items():
            got = out.setdefault(api, {})
            for target in STAR_TARGETS:
                if star < target or (api, target) in settled:
                    continue
                settled.add((api, target))
                if i > 0:
                    got[str(target)] = format_label(key)
    return {api: out[api] for api in sorted(out)}


def _opener(unit_rounds: list) -> list:
    stage2 = [(key, board) for key, _units, board in unit_rounds if key[0] == OPENER_STAGE and board]
    if not stage2:
        return []
    return sorted({u.api for u in stage2[-1][1]})


# ------------------------------------------------------------- per match

def mine_match(record: Mapping, setdata: SetData) -> dict:
    """Every milestone of one match (see the module docstring)."""
    record = record if isinstance(record, Mapping) else {}
    timeline = _timeline(record)
    reached, censored, level_at = _levels(timeline)
    rolldowns = _rolldowns(timeline, record.get("shop_refreshes"))
    by_label = {format_label(key): row for _seq, key, row in timeline}
    gold_at = {}
    for label in GOLD_CHECKPOINTS:
        g = as_int(envelope_value(by_label.get(label), "gold_start"))
        if g is not None and g >= 0:
            gold_at[label] = g
    hp_at = {}
    for label in HP_CHECKPOINTS:
        hp = as_int(envelope_value(by_label.get(label), "hp_start"))
        if hp is not None:
            hp_at[label] = hp
    unit_rounds = _unit_rounds(record, timeline, setdata)
    slam, slam_censored = _slam(unit_rounds, setdata)
    return {
        "match_id": record_id(record),
        "placement": placement_of(record),
        "rounds": len(timeline),
        "first_label": format_label(timeline[0][1]) if timeline else None,
        "last_label": format_label(timeline[-1][1]) if timeline else None,
        "level_at": level_at,
        "level_reached": reached,
        "censored_levels": censored,
        "rolldowns": rolldowns,
        "first_rolldown": rolldowns[0]["label"] if rolldowns else None,
        "first_slam": slam,
        "slam_censored": slam_censored,
        "gold_at": gold_at,
        "hp_at": hp_at,
        "star_ups": _star_ups(unit_rounds),
        "opener": _opener(unit_rounds),
        "has_unit_obs": bool(unit_rounds),
    }


# ------------------------------------------------------------- aggregation

def _rank(n: int, q: float) -> int:
    return max(0, min(n - 1, math.ceil(q * n) - 1))


def label_stats(labels: Iterable) -> dict:
    keys = sorted(k for k in (parse_label(x) for x in labels) if k is not None)
    if not keys:
        return {"median": None, "q1": None, "q3": None, "n": 0}
    n = len(keys)
    return {"median": format_label(keys[(n - 1) // 2]), "q1": format_label(keys[_rank(n, 0.25)]),
            "q3": format_label(keys[_rank(n, 0.75)]), "n": n}


def number_stats(values: Iterable) -> dict:
    vals = sorted(v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool))
    if not vals:
        return {"median": None, "q1": None, "q3": None, "iqr": None, "n": 0}
    n = len(vals)
    q1, q3 = vals[_rank(n, 0.25)], vals[_rank(n, 0.75)]
    return {"median": round(float(statistics.median(vals)), 2), "q1": q1, "q3": q3, "iqr": q3 - q1, "n": n}


def aggregate(mined: Iterable, *, key_units: Optional[Iterable] = None) -> dict:
    """Medians / quartiles over mined matches (the caller picks which: top-4 by default)."""
    rows = list(mined)
    with_rounds = [m for m in rows if m.get("rounds")]
    with_units = [m for m in rows if m.get("has_unit_obs")]
    curve: dict = defaultdict(list)
    for m in with_rounds:
        for label, lvl in m["level_at"].items():
            curve[label].append(lvl)
    level_curve = {}
    for label in sorted(curve, key=lambda x: parse_label(x) or (0, 0)):
        vals = sorted(curve[label])
        level_curve[label] = {"median": vals[(len(vals) - 1) // 2], "n": len(vals)}
    first_roll = label_stats(m["first_rolldown"] for m in with_rounds)
    first_roll["share"] = round(first_roll["n"] / len(with_rounds), 3) if with_rounds else None
    roll_gold = [m["rolldowns"][0]["gold_end"] for m in with_rounds if m["rolldowns"]]
    keys = sorted(set(key_units)) if key_units is not None else sorted(
        {api for m in with_units for api in m["star_ups"]})
    star_ups = {}
    for api in keys:
        star_ups[api] = {str(t): label_stats(m["star_ups"].get(api, {}).get(str(t)) for m in with_units)
                         for t in STAR_TARGETS}
    opener_count = Counter(api for m in with_units for api in m["opener"])
    opener_games = sum(1 for m in with_units if m["opener"])
    opener = [{"api": a, "share": round(c / opener_games, 3)}
              for a, c in sorted(opener_count.items(), key=lambda kv: (-kv[1], kv[0]))
              if opener_games and c / opener_games >= OPENER_SHARE]
    return {
        "games": len(rows),
        "games_with_rounds": len(with_rounds),
        "games_with_units": len(with_units),
        "level_reached": {str(lv): label_stats(m["level_reached"].get(str(lv)) for m in with_rounds)
                          for lv in LEVELS},
        "level_curve": level_curve,
        "first_rolldown": first_roll,
        "rolldown_gold_end": number_stats(roll_gold),
        "rolldowns_per_game": number_stats(len(m["rolldowns"]) for m in with_rounds),
        "first_slam": label_stats((m["first_slam"] or {}).get("label") for m in with_units),
        "gold_at": {label: number_stats(m["gold_at"].get(label) for m in with_rounds) for label in GOLD_CHECKPOINTS},
        "hp_at": {label: number_stats(m["hp_at"].get(label) for m in with_rounds) for label in HP_CHECKPOINTS},
        "star_ups": star_ups,
        "opener": opener,
    }


def milestones_by_comp(records: Any, catalogue: Mapping, setdata: SetData, *, top4_only: bool = True) -> dict:
    """aggregate() per catalogue comp, over its top-4 matches unless top4_only=False."""
    assignments = _section(catalogue, "assignments")
    raw_comps = catalogue.get("comps") if isinstance(catalogue, Mapping) else None
    comps = {c["comp_id"]: c for c in _rows(raw_comps) if isinstance(c.get("comp_id"), str)}
    mined: dict = defaultdict(list)
    for mid, rec in ordered_records(records):
        comp_id = assignments.get(mid)
        if not isinstance(comp_id, str) or comp_id not in comps:
            continue
        place = placement_of(rec)
        if top4_only and (place is None or place > TOP4_MAX_PLACEMENT):
            continue
        mined[comp_id].append(mine_match(rec, setdata))
    out = {}
    for comp_id in sorted(comps):
        comp = comps[comp_id]
        key_units = comp_units(comp, "core")
        carry_api = _section(comp, "carry").get("api")
        if isinstance(carry_api, str) and carry_api not in key_units:
            key_units.append(carry_api)
        out[comp_id] = aggregate(mined.get(comp_id, []), key_units=key_units)
    return dict(engine_meta(), set_id=setdata.set_id, top4_only=top4_only, comps=out)


# ------------------------------------------------- one match versus average

def _order_verdict(this: tuple, median: tuple) -> str:
    return "earlier" if this < median else ("later" if this > median else "same")


def _number_verdict(this, median) -> str:
    return "lower" if this < median else ("higher" if this > median else "same")


def _section(obj: Any, name: str) -> dict:
    value = obj.get(name) if isinstance(obj, Mapping) else None
    return value if isinstance(value, Mapping) else {}


def _is_num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def compare_to_average(mined: Mapping, agg: Mapping) -> list:
    """Rows of this match's milestones next to the comp's top-4 medians (post-match digest)."""
    rows = []

    def order_row(name, this, med):
        a, b = parse_label(this), parse_label(med)
        if a is not None and b is not None:
            rows.append({"milestone": name, "this_match": this, "median": med, "verdict": _order_verdict(a, b)})

    reached, agg_reached = _section(mined, "level_reached"), _section(agg, "level_reached")
    for lv in LEVELS:
        order_row(f"level_{lv}", reached.get(str(lv)), _section(agg_reached, str(lv)).get("median"))
    order_row("first_rolldown", mined.get("first_rolldown") if isinstance(mined, Mapping) else None,
              _section(agg, "first_rolldown").get("median"))
    order_row("first_slam", _section(mined, "first_slam").get("label"), _section(agg, "first_slam").get("median"))
    for group, prefix in (("gold_at", "gold_at_"), ("hp_at", "hp_at_")):
        agg_group = _section(agg, group)
        for label, this in sorted(_section(mined, group).items(), key=lambda kv: str(kv[0])):
            med = _section(agg_group, label).get("median")
            if _is_num(this) and _is_num(med):
                rows.append({"milestone": prefix + str(label), "this_match": this, "median": med,
                             "verdict": _number_verdict(this, med)})
    return rows


# ---------------------------------------------------------- store adapter

def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except _STORE_ERRORS:
        return None


def _listed(fn, arg) -> list:
    return list(fn(arg))


def _board_rows(board: Any) -> list:
    out = []
    for row in board or []:
        if not isinstance(row, Mapping):
            continue
        api = next((row[k] for k in ("champion_api", "championName", "championId", "api")
                    if isinstance(row.get(k), str) and row[k]), None)
        if not api:
            continue
        items = row.get("items")
        entry = {"champion_api": api, "star": as_int(row.get("star", row.get("starLevel"))) or 1}
        if isinstance(items, list):
            entry["items"] = list(items)
        elif isinstance(row.get("items_json"), str):
            entry["items_json"] = row["items_json"]
        else:
            entry["items"] = list(row.get("itemNames") or [])
        if as_int(row.get("cost")) is not None:
            entry["cost"] = as_int(row["cost"])
        out.append(entry)
    return out


def _final_boards_map(final_boards: Any) -> dict:
    if isinstance(final_boards, Mapping):
        return {str(k): v for k, v in final_boards.items()}
    out = {}
    for row in final_boards or []:
        if isinstance(row, Mapping) and row.get("match_id") is not None:
            board = row.get("board", row.get("units", row.get("final_board")))
            out.setdefault(str(row["match_id"]), board)
    return out


def _local_gt_board(detail: Mapping, local_key: Optional[str]) -> list:
    rows = [r for r in (detail.get("gt_board") or []) if isinstance(r, Mapping)]
    if local_key is not None:
        rows = [r for r in rows if r.get("player_key") == local_key]
    for source in GT_SOURCE_ORDER:
        picked = [r for r in rows if r.get("source") == source]
        if picked:
            return picked
    return rows


def _bundled(rounds: list, key: str) -> list:
    """Child rows nested in the TFT-01 round bundles (store.iter_rounds: each
    round row carries its "units" (unit_obs) and "shop" (shop_refresh) lists)."""
    return [row for bundle in rounds if isinstance(bundle, Mapping)
            for row in (bundle.get(key) if isinstance(bundle.get(key), list) else [])
            if isinstance(row, Mapping)]


def _detail(getter, mid: str) -> Any:
    """get_match(mid) without its round bundles when the store supports it
    (they are read once, through iter_rounds), else the plain call."""
    detail = _call(getter, mid, rounds=False)
    return detail if detail is not None else _call(getter, mid)


def records_from_store(store: Any, *, set_id: Any = None, final_boards: Any = None,
                       top4_only: bool = False) -> list:
    """Match records from the TFT-01 read API; fail-soft (a store error yields fewer records).

    The real store (tft/rounds/store.py) nests unit_obs and shop_refresh rows
    inside each round bundle; flat top-level lists (unit_obs / units,
    shop_refresh / shop_refreshes) are read when a store provides them."""
    lister = getattr(store, "list_matches", None)
    matches = _call(lister, set_id=set_id, top4_only=top4_only) if callable(lister) else None
    boards = _final_boards_map(final_boards)
    out = []
    for m in matches or []:
        if not isinstance(m, Mapping) or m.get("match_id") is None:
            continue
        mid = str(m["match_id"])
        getter = getattr(store, "get_match", None)
        rounds_fn = getattr(store, "iter_rounds", None)
        if not callable(getter):
            detail = None
        elif callable(rounds_fn):
            detail = _detail(getter, mid)
        else:
            detail = _call(getter, mid)
        detail = detail if isinstance(detail, Mapping) else {}
        rounds = _call(_listed, rounds_fn, mid) if callable(rounds_fn) else None
        if rounds is None:
            rounds = list(detail.get("rounds") or [])
        players = [p for p in (detail.get("player") or detail.get("players") or []) if isinstance(p, Mapping)]
        local_key = next((p.get("player_key") for p in players if p.get("is_local")), None)
        units = [r for r in (detail.get("unit_obs") or detail.get("units") or []) if isinstance(r, Mapping)]
        if not units:
            units = _bundled(rounds, "units")
        if local_key is not None:
            units = [r for r in units if r.get("player_key") == local_key]
        shop = list(detail.get("shop_refresh") or detail.get("shop_refreshes") or []) or _bundled(rounds, "shop")
        board = boards.get(mid)
        if board is None:
            board = _local_gt_board(detail, local_key)
        rec = {k: m.get(k) for k in ("match_id", "set_id", "queue_kind", "placement", "placement_conf",
                                     "placement_src") if k in m}
        rec.update(match_id=mid, final_board=_board_rows(board), rounds=rounds,
                   shop_refreshes=shop, units=units)
        if isinstance(m.get("augments"), list):
            rec["augments"] = list(m["augments"])
        out.append(rec)
    return out
