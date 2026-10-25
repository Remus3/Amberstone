"""tft/engine/recommend.py - live recommendations (docs/TFT_PROGRAM.md section 5
output 3) and the prior-top-4 team-planner picker payload (section 6, TFT-14).

All of it is arithmetic over the operator's own catalogue (comps.py), their
top-4 milestones (milestones.py), set game data and the shop-odds model in
tft/tft_roll_odds.py. No LLM, no network, no third-party comp or tier data.

LIVE STATE (one dict, every key optional):
    {"label": "3-2", "level": 5, "gold": 30,
     "board": [unit, ...], "bench": [unit, ...],     # comps.py unit shapes
     "items": [item apiName, ...],                    # the item bench
     "offers": [{"slot": 0, "champion_api": str, "cost": int, "kind": str}],
     "target_comp_id": str}                           # the comp the player picked
lobby_boards = the other players' boards (lists of units), e.g. the 8 boards of
the per-round EoG file minus the local one: they drive contest counts and the
copies-taken arguments of the odds model.

ODDS: shop_hit_probability / rolls_for_confidence read the constants bundle
the caller passes, else tft_roll_odds.default_constants(). odds_stale is True
whenever that bundle is not in-client verified or was written for another set
than the engine's - the numbers are then shown, but marked STALE (until LT-02
closes, which a parallel slice is doing in tft/tft_data.py; nothing here
hard-codes a table).
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Optional

from tft import tft_roll_odds
from tft.engine import engine_meta
from tft.engine.comps import SetData, as_int, as_units, copies, jaccard, trait_signature
from tft.engine.milestones import LEVELS, parse_label

NEAREST_LIMIT = 3
SLAM_LIMIT = 5
PLANNER_LIMIT = 8
DIGEST_MAX_LINES = 6
DIGEST_MAX_CHARS = 64
CORE_WEIGHT = 0.6
POOL_WEIGHT = 0.3
TRAIT_WEIGHT = 0.1
ROLL_CONFIDENCE = 0.5
SKIP_OFFER_KINDS = frozenset({"empty", "special"})

# Shop pick priority (lower first).
_PRIORITY = {("star_up", True): 0, ("core", True): 1, ("star_up", False): 2, ("core_copy", True): 3,
             ("flex", False): 4}


def _owned(state: Mapping, setdata: SetData) -> Counter:
    held: Counter = Counter()
    for zone in ("board", "bench"):
        for unit in as_units(state.get(zone) or [], setdata):
            held[unit.api] += copies(unit.star)
    return held


def _comp_by_id(catalogue: Mapping, comp_id: Any) -> Optional[dict]:
    for comp in (catalogue or {}).get("comps") or []:
        if comp.get("comp_id") == comp_id:
            return comp
    return None


def _core(comp: Mapping) -> list:
    return [c["api"] for c in comp.get("core") or []]


def _flex(comp: Mapping) -> list:
    return [c["api"] for c in comp.get("flex") or []]


# ------------------------------------------------------------ nearest comps

def nearest_comps(state: Mapping, catalogue: Mapping, setdata: SetData, *, limit: int = NEAREST_LIMIT) -> list:
    """Catalogue comps closest to the current board + bench, best first."""
    held = _owned(state or {}, setdata)
    if not held:
        return []
    owned = set(held)
    units = as_units(list((state or {}).get("board") or []) + list((state or {}).get("bench") or []), setdata)
    sig = trait_signature(units, setdata)
    rows = []
    for comp in (catalogue or {}).get("comps") or []:
        core = set(_core(comp))
        if not core:
            continue
        pool = core | set(_flex(comp))
        score = (CORE_WEIGHT * len(owned & core) / len(core) + POOL_WEIGHT * jaccard(owned, pool)
                 + TRAIT_WEIGHT * jaccard(sig, comp.get("signature") or []))
        if score <= 0:
            continue
        rows.append({"comp_id": comp["comp_id"], "label": comp["label"], "score": round(score, 3),
                     "core_owned": sorted(owned & core), "core_missing": sorted(core - owned),
                     "games": comp.get("games"), "avg_placement": comp.get("avg_placement"),
                     "top4_rate": comp.get("top4_rate")})
    rows.sort(key=lambda r: (-r["score"], -(r["top4_rate"] or 0), r["comp_id"]))
    return rows[:limit]


# --------------------------------------------------------------- shop picks

def _consts(consts):
    return consts if consts is not None else tft_roll_odds.default_constants()


def odds_stale(consts, setdata: SetData) -> bool:
    return (not consts.verified_in_client) or consts.set_number != setdata.set_id


def _lobby_copies(lobby_boards: Any, setdata: SetData) -> Counter:
    taken: Counter = Counter()
    for board in lobby_boards or []:
        for unit in as_units(board or [], setdata):
            taken[unit.api] += copies(unit.star)
    return taken


def _odds(level, cost, target_taken, cost_taken, consts) -> tuple:
    if level is None or cost is None:
        return None, None
    try:
        p = tft_roll_odds.shop_hit_probability(level, cost, target_copies_taken=target_taken,
                                               cost_copies_taken=cost_taken, consts=consts)
        rolls = tft_roll_odds.rolls_for_confidence(level, cost, confidence=ROLL_CONFIDENCE,
                                                   target_copies_taken=target_taken,
                                                   cost_copies_taken=cost_taken, consts=consts)
    except ValueError:
        return None, None
    return round(p, 4), rolls


def shop_picks(state: Mapping, comp: Mapping, setdata: SetData, *, lobby_boards: Any = None,
               consts=None) -> dict:
    """Which current offers advance the target comp, plus hit odds for the core units still missing."""
    state = state or {}
    consts = _consts(consts)
    held = _owned(state, setdata)
    core, flex = set(_core(comp)), set(_flex(comp))
    picks, offered = [], set()
    for offer in state.get("offers") or []:
        if not isinstance(offer, Mapping) or offer.get("kind") in SKIP_OFFER_KINDS:
            continue
        key = offer.get("champion_api") or offer.get("name_text") or offer.get("name")
        api = setdata.resolve_unit_api(key) or (key.strip() if isinstance(key, str) and key.strip() else None)
        if not api:
            continue
        offered.add(api)
        have = held.get(api, 0)
        in_core = api in core
        if have % 3 == 2:
            reason = "star_up"
        elif in_core and have == 0:
            reason = "core"
        elif in_core and have < copies(3):
            reason = "core_copy"
        elif api in flex and have == 0:
            reason = "flex"
        else:
            continue
        cost = as_int(offer.get("cost"))
        picks.append({"slot": as_int(offer.get("slot")), "api": api, "name": setdata.unit_name(api),
                      "cost": cost if cost is not None else setdata.unit_cost(api), "reason": reason,
                      "_p": _PRIORITY.get((reason, in_core), 5)})
    picks.sort(key=lambda p: (p["_p"], p["slot"] if p["slot"] is not None else 99, p["api"]))
    for p in picks:
        p.pop("_p")

    lobby = _lobby_copies(lobby_boards, setdata)
    everyone = held + lobby
    level = as_int(state.get("level"))
    wanted = []
    for api in sorted(core - set(held) - offered):
        cost = setdata.unit_cost(api)
        cost_taken = sum(n for a, n in everyone.items() if setdata.unit_cost(a) == cost) if cost else 0
        p, rolls = _odds(level, cost, everyone.get(api, 0), cost_taken, consts)
        wanted.append({"api": api, "name": setdata.unit_name(api), "cost": cost,
                       "copies_taken": everyone.get(api, 0), "contested": lobby.get(api, 0) > 0,
                       "p_shop": p, "rolls_50": rolls})
    wanted.sort(key=lambda w: (-(w["cost"] or 0), w["api"]))
    return {"picks": picks, "wanted": wanted, "odds_stale": odds_stale(consts, setdata),
            "odds_source": consts.source}


# --------------------------------------------------------------- item slams

def item_slams(held_items: Iterable, comp: Optional[Mapping], setdata: SetData, *, limit: int = SLAM_LIMIT) -> list:
    """Completed items buildable from the held components, ranked by the comp's own usage."""
    components = Counter(api for api in (setdata.resolve_item_api(i) for i in held_items or [])
                         if api and setdata.item_kind(api) == "component")
    carry = (comp or {}).get("carry") or {}
    carry_freq = carry.get("item_freq") or {}
    comp_freq = (comp or {}).get("item_freq") or {}
    out = []
    for item, recipe in setdata.recipes.items():
        need = Counter(recipe)
        if all(components[c] >= n for c, n in need.items()):
            out.append({"item": item, "name": setdata.item_name(item), "components": list(recipe),
                        "on": carry.get("api"), "carry_games": carry_freq.get(item, 0),
                        "comp_games": comp_freq.get(item, 0)})
    out.sort(key=lambda r: (-r["carry_games"], -r["comp_games"], r["item"]))
    return out[:limit]


# ------------------------------------------------------------- level advice

def level_advice(current: Mapping, agg: Optional[Mapping]) -> dict:
    """The current level against the comp's top-4 median at this round, plus the next milestone."""
    current = current or {}
    label = current.get("label") if isinstance(current.get("label"), str) else None
    key = parse_label(label)
    level = as_int(current.get("level"))
    out = {"status": "unknown", "message": "No top-4 level data yet", "next": None, "roll": None}
    if not agg or key is None:
        return out
    curve = (agg.get("level_curve") or {}).get(label)
    if curve and level is not None:
        med = curve["median"]
        out["status"] = "behind" if level < med else ("ahead" if level > med else "on_curve")
        out["message"] = f"Lv{level} at {label}; your top-4 median is Lv{med} at {label}"
    else:
        out["message"] = f"No top-4 level data at {label} yet"
    if level is not None:
        for lv in LEVELS:
            if lv <= level:
                continue
            med_label = ((agg.get("level_reached") or {}).get(str(lv)) or {}).get("median")
            if med_label and parse_label(med_label) > key:
                out["next"] = {"level": lv, "label": med_label}
                break
    roll = agg.get("first_rolldown") or {}
    if roll.get("n") and parse_label(roll.get("q1")) <= key <= parse_label(roll.get("q3")):
        out["roll"] = {"label": roll["median"], "to_gold": (agg.get("rolldown_gold_end") or {}).get("median"),
                       "games": roll["n"]}
    return out


# ------------------------------------------------------ one-call live payload

def recommend(state: Mapping, catalogue: Mapping, milestones_payload: Optional[Mapping], setdata: SetData, *,
              lobby_boards: Any = None, consts=None) -> dict:
    """The whole live answer: target comp, shop picks, item slams, level / roll advice."""
    state = state or {}
    nearest = nearest_comps(state, catalogue, setdata)
    comp = _comp_by_id(catalogue, state.get("target_comp_id"))
    if comp is None and nearest:
        comp = _comp_by_id(catalogue, nearest[0]["comp_id"])
    target = None
    if comp is not None:
        target = next((n for n in nearest if n["comp_id"] == comp["comp_id"]),
                      {"comp_id": comp["comp_id"], "label": comp["label"], "score": None})
    agg = ((milestones_payload or {}).get("comps") or {}).get(comp["comp_id"]) if comp else None
    return dict(
        engine_meta(), set_id=setdata.set_id, target=target,
        alternatives=[n for n in nearest if target is None or n["comp_id"] != target["comp_id"]],
        shop=shop_picks(state, comp, setdata, lobby_boards=lobby_boards, consts=consts) if comp else None,
        items=item_slams(state.get("items") or [], comp, setdata) if comp else [],
        level=level_advice(state, agg))


# ------------------------------------------------------- planner picker (TFT-14)

def _fit(line: str) -> str:
    line = line.encode("ascii", "replace").decode("ascii")
    return line if len(line) <= DIGEST_MAX_CHARS else line[: DIGEST_MAX_CHARS - 3] + "..."


def _milestone_line(agg: Optional[Mapping]) -> Optional[str]:
    if not agg:
        return None
    parts = []
    for lv in (6, 8):
        med = ((agg.get("level_reached") or {}).get(str(lv)) or {}).get("median")
        if med:
            parts.append(f"Lv{lv} by {med}")
    roll = (agg.get("first_rolldown") or {}).get("median")
    if roll:
        gold = (agg.get("rolldown_gold_end") or {}).get("median")
        parts.append(f"roll at {roll} to ~{int(round(gold))}g" if gold is not None else f"roll at {roll}")
    slam = (agg.get("first_slam") or {}).get("median")
    if slam:
        parts.append(f"first slam {slam}")
    return ", ".join(parts) or None


def _digest(comp: Mapping, agg: Optional[Mapping], contest: Optional[int], setdata: SetData) -> list:
    lines = ["Core: " + ", ".join(c["name"] for c in comp.get("core") or [])]
    if comp.get("three_star"):
        lines.append("3-star: " + ", ".join(c["name"] for c in comp["three_star"]))
    carry = comp.get("carry")
    if carry:
        sets = carry.get("item_sets") or []
        items = ", ".join(sets[0]["names"]) if sets else ""
        lines.append(f"Carry: {carry['name']}" + (f" - {items}" if items else ""))
    line = _milestone_line(agg)
    if line:
        lines.append(line)
    opener = (agg or {}).get("opener") or []
    if opener:
        lines.append("Opener: " + ", ".join(setdata.unit_name(o["api"]) for o in opener))
    if contest is not None:
        lines.append(f"Contested: {contest} of {len(comp.get('core') or [])} core on other boards")
    return [_fit(x) for x in lines[:DIGEST_MAX_LINES]]


def _summary(comp: Mapping) -> str:
    games = comp.get("games") or 0
    if comp.get("avg_placement") is None:
        return f"{games} games, no placement yet"
    rate = comp.get("top4_rate") or 0.0
    return f"{games} games, avg {comp['avg_placement']:.1f}, top-4 {rate * 100:.0f}%"


def planner_choices(catalogue: Mapping, milestones_payload: Optional[Mapping], setdata: SetData, *,
                    lobby_boards: Any = None, limit: int = PLANNER_LIMIT) -> dict:
    """Up to `limit` comps with at least one top-4 game, each with its hover digest."""
    lobby_apis = set(_lobby_copies(lobby_boards, setdata)) if lobby_boards is not None else None
    per_comp = (milestones_payload or {}).get("comps") or {}
    choices = []
    for comp in (catalogue or {}).get("comps") or []:
        if len(choices) >= limit:
            break
        if (comp.get("top4_games") or 0) < 1:
            continue
        agg = per_comp.get(comp["comp_id"]) if milestones_payload else None
        core = [{"api": c["api"], "name": c["name"], "cost": c["cost"]} for c in comp.get("core") or []]
        contest = sum(1 for c in core if c["api"] in lobby_apis) if lobby_apis is not None else None
        carry = comp.get("carry")
        carry_row = None
        if carry:
            sets = carry.get("item_sets") or []
            carry_row = {"api": carry["api"], "name": carry["name"], "cost": carry["cost"],
                         "items": [{"api": a, "name": setdata.item_name(a)} for a in (sets[0]["items"] if sets else [])]}
        choices.append({
            "comp_id": comp["comp_id"], "label": comp["label"], "games": comp.get("games"),
            "top4_games": comp.get("top4_games"), "avg_placement": comp.get("avg_placement"),
            "top4_rate": comp.get("top4_rate"), "summary": _summary(comp), "core": core,
            "three_star": [{"api": c["api"], "name": c["name"], "cost": c["cost"]} for c in comp.get("three_star") or []],
            "carry": carry_row, "milestones": agg, "contest": contest,
            "digest": _digest(comp, agg, contest, setdata),
        })
    top4_only = (milestones_payload or {}).get("top4_only", True)
    return dict(engine_meta(), set_id=setdata.set_id, top4_only=top4_only, choices=choices)
