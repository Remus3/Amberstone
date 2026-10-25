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
the caller passes, else tft_roll_odds.default_constants() (the tables in
tft/tft_data.py, whatever set they declare). odds_stale is True whenever that
bundle is not in-client verified as a whole or was written for another set
than the engine's - the numbers are then shown, but marked STALE. Nothing here
hard-codes an odds or pool table.

NEAREST COMPS score = CORE_WEIGHT x share of the comp's core owned
+ POOL_WEIGHT x Jaccard(owned units, core + flex) + TRAIT_WEIGHT x Jaccard of
the trait signatures + ITEM_WEIGHT x share of the held-or-buildable items
(recipes completable from held components, plus finished items held that the
set data knows) that the comp itself has used. A comp that shares no unit
with the board is never listed, whatever the items say.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Optional

from tft import tft_roll_odds
from tft.engine import engine_meta
from tft.engine.comps import SetData, as_int, as_units, comp_units, copies, jaccard, trait_signature
from tft.engine.milestones import LEVELS, parse_label

NEAREST_LIMIT = 3
SLAM_LIMIT = 5
PLANNER_LIMIT = 8
DIGEST_MAX_LINES = 6
DIGEST_MAX_CHARS = 64
CORE_WEIGHT = 0.55
POOL_WEIGHT = 0.25
TRAIT_WEIGHT = 0.10
ITEM_WEIGHT = 0.10
ROLL_CONFIDENCE = 0.5
SKIP_OFFER_KINDS = frozenset({"empty", "special"})

# Shop pick priority (lower first).
_PRIORITY = {("star_up", True): 0, ("core", True): 1, ("star_up", False): 2, ("core_copy", True): 3,
             ("flex", False): 4}


def _state(state: Any) -> Mapping:
    return state if isinstance(state, Mapping) else {}


def _list(value: Any) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def _owned(state: Mapping, setdata: SetData) -> Counter:
    held: Counter = Counter()
    for zone in ("board", "bench"):
        for unit in as_units(_list(state.get(zone)), setdata):
            held[unit.api] += copies(unit.star)
    return held


def _comps(catalogue: Any) -> list:
    rows = catalogue.get("comps") if isinstance(catalogue, Mapping) else None
    return [c for c in _list(rows) if isinstance(c, Mapping) and isinstance(c.get("comp_id"), str)]


def _comp_by_id(catalogue: Mapping, comp_id: Any) -> Optional[Mapping]:
    for comp in _comps(catalogue):
        if comp["comp_id"] == comp_id:
            return comp
    return None


def _core(comp: Mapping) -> list:
    return comp_units(comp, "core")


def _flex(comp: Mapping) -> list:
    return comp_units(comp, "flex")


def _completable(held_items: Any, setdata: SetData) -> list:
    """(item, recipe) for every recipe the held components can build now."""
    components = Counter(api for api in (setdata.resolve_item_api(i) for i in _list(held_items))
                         if api and setdata.item_kind(api) == "component")
    out = []
    for item, recipe in setdata.recipes.items():
        if all(components[c] >= n for c, n in Counter(recipe).items()):
            out.append((item, recipe))
    return sorted(out)


# ------------------------------------------------------------ nearest comps

def nearest_comps(state: Mapping, catalogue: Mapping, setdata: SetData, *, limit: int = NEAREST_LIMIT) -> list:
    """Catalogue comps closest to the current board + bench + held items, best first."""
    state = _state(state)
    held = _owned(state, setdata)
    if not held:
        return []
    owned = set(held)
    units = as_units(_list(state.get("board")) + _list(state.get("bench")), setdata)
    sig = trait_signature(units, setdata)
    # Items the player has or can build now: completable recipes + finished items already held
    # (known to the set data only - an unrecognised string is not an item and never dilutes the fit).
    buildable = {item for item, _recipe in _completable(state.get("items"), setdata)}
    buildable |= {api for api in (setdata.resolve_item_api(i) for i in _list(state.get("items")))
                  if api in setdata.item_names and setdata.item_kind(api) != "component"}
    rows = []
    for comp in _comps(catalogue):
        core = set(_core(comp))
        if not core:
            continue
        pool = core | set(_flex(comp))
        if not owned & pool:
            continue  # items alone never make a comp "near": it must share a unit
        used = comp.get("item_freq") if isinstance(comp.get("item_freq"), Mapping) else {}
        item_fit = len(buildable & set(used)) / len(buildable) if buildable else 0.0
        signature = [t for t in _list(comp.get("signature")) if isinstance(t, str)]
        score = (CORE_WEIGHT * len(owned & core) / len(core) + POOL_WEIGHT * jaccard(owned, pool)
                 + TRAIT_WEIGHT * jaccard(sig, signature) + ITEM_WEIGHT * item_fit)
        if score <= 0:
            continue
        rows.append({"comp_id": comp["comp_id"], "label": comp.get("label"), "score": round(score, 3),
                     "core_owned": sorted(owned & core), "core_missing": sorted(core - owned),
                     "item_fit": round(item_fit, 3),
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
    boards = lobby_boards.values() if isinstance(lobby_boards, Mapping) else _list(lobby_boards)
    for board in boards:
        for unit in as_units(_list(board), setdata):
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
    """Which current offers advance the target comp, plus hit odds.

    Every pick and every still-missing core unit ("wanted") carries p_shop (at
    least one copy in the next shop) and rolls_50 (shops for a 50 percent hit),
    with copies taken = the player's own + every lobby board's.
    """
    state = _state(state)
    consts = _consts(consts)
    held = _owned(state, setdata)
    lobby = _lobby_copies(lobby_boards, setdata)
    everyone = held + lobby
    level = as_int(state.get("level"))

    def cost_taken(cost):
        return sum(n for a, n in everyone.items() if setdata.unit_cost(a) == cost) if cost else 0

    core, flex = set(_core(comp)), set(_flex(comp))
    picks, offered = [], set()
    for offer in _list(state.get("offers")):
        kind = offer.get("kind") if isinstance(offer, Mapping) else None
        if not isinstance(offer, Mapping) or (isinstance(kind, str) and kind in SKIP_OFFER_KINDS):
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
        cost = cost if cost is not None else setdata.unit_cost(api)
        p, rolls = _odds(level, cost, everyone.get(api, 0), cost_taken(cost), consts)
        picks.append({"slot": as_int(offer.get("slot")), "api": api, "name": setdata.unit_name(api),
                      "cost": cost, "reason": reason, "p_shop": p, "rolls_50": rolls,
                      "_p": _PRIORITY.get((reason, in_core), 5)})
    picks.sort(key=lambda p: (p["_p"], p["slot"] if p["slot"] is not None else 99, p["api"]))
    for p in picks:
        p.pop("_p")

    wanted = []
    for api in sorted(core - set(held) - offered):
        cost = setdata.unit_cost(api)
        p, rolls = _odds(level, cost, everyone.get(api, 0), cost_taken(cost), consts)
        wanted.append({"api": api, "name": setdata.unit_name(api), "cost": cost,
                       "copies_taken": everyone.get(api, 0), "contested": lobby.get(api, 0) > 0,
                       "p_shop": p, "rolls_50": rolls})
    wanted.sort(key=lambda w: (-(w["cost"] or 0), w["api"]))
    return {"picks": picks, "wanted": wanted, "odds_stale": odds_stale(consts, setdata),
            "odds_source": consts.source}


# --------------------------------------------------------------- item slams

def item_slams(held_items: Iterable, comp: Optional[Mapping], setdata: SetData, *, limit: int = SLAM_LIMIT) -> list:
    """Completed items buildable from the held components, ranked by the comp's own usage."""
    comp = comp if isinstance(comp, Mapping) else {}
    carry = comp.get("carry") if isinstance(comp.get("carry"), Mapping) else {}
    carry_freq = carry.get("item_freq") if isinstance(carry.get("item_freq"), Mapping) else {}
    comp_freq = comp.get("item_freq") if isinstance(comp.get("item_freq"), Mapping) else {}
    out = []
    for item, recipe in _completable(held_items, setdata):
        out.append({"item": item, "name": setdata.item_name(item), "components": list(recipe),
                    "on": carry.get("api"), "carry_games": carry_freq.get(item, 0),
                    "comp_games": comp_freq.get(item, 0)})
    out.sort(key=lambda r: (-r["carry_games"], -r["comp_games"], r["item"]))
    return out[:limit]


# ------------------------------------------------------------- level advice

def level_advice(current: Mapping, agg: Optional[Mapping]) -> dict:
    """The current level against the comp's top-4 median at this round, plus the next milestone."""
    current = _state(current)
    label = current.get("label") if isinstance(current.get("label"), str) else None
    key = parse_label(label)
    level = as_int(current.get("level"))
    out = {"status": "unknown", "message": "No top-4 level data yet", "next": None, "roll": None}
    if not isinstance(agg, Mapping) or not agg or key is None:
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
    state = _state(state)
    nearest = nearest_comps(state, catalogue, setdata)
    comp = _comp_by_id(catalogue, state.get("target_comp_id"))
    if comp is None and nearest:
        comp = _comp_by_id(catalogue, nearest[0]["comp_id"])
    target = None
    if comp is not None:
        target = next((n for n in nearest if n["comp_id"] == comp["comp_id"]),
                      {"comp_id": comp["comp_id"], "label": comp.get("label"), "score": None})
    per_comp = milestones_payload.get("comps") if isinstance(milestones_payload, Mapping) else None
    agg = per_comp.get(comp["comp_id"]) if comp is not None and isinstance(per_comp, Mapping) else None
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


def _unit_rows(comp: Mapping, key: str, setdata: SetData) -> list:
    """[{"api", "name", "cost"}] for a comp's core / three_star rows, names and costs from set data when absent."""
    out = []
    for row in _list(comp.get(key)):
        if not isinstance(row, Mapping) or not isinstance(row.get("api"), str):
            continue
        api = row["api"]
        name = row.get("name") if isinstance(row.get("name"), str) else setdata.unit_name(api)
        cost = as_int(row.get("cost"))
        out.append({"api": api, "name": name, "cost": cost if cost is not None else setdata.unit_cost(api)})
    return out


def _carry_row(comp: Mapping, setdata: SetData) -> Optional[dict]:
    carry = comp.get("carry")
    if not isinstance(carry, Mapping) or not isinstance(carry.get("api"), str):
        return None
    api = carry["api"]
    sets = [s for s in _list(carry.get("item_sets")) if isinstance(s, Mapping)]
    items = [a for a in _list(sets[0].get("items")) if isinstance(a, str)] if sets else []
    cost = as_int(carry.get("cost"))
    return {"api": api, "name": carry.get("name") if isinstance(carry.get("name"), str) else setdata.unit_name(api),
            "cost": cost if cost is not None else setdata.unit_cost(api),
            "items": [{"api": a, "name": setdata.item_name(a)} for a in items]}


def _digest(core: list, three_star: list, carry: Optional[Mapping], agg: Optional[Mapping],
            contest: Optional[int], setdata: SetData) -> list:
    lines = ["Core: " + ", ".join(c["name"] for c in core)]
    if three_star:
        lines.append("3-star: " + ", ".join(c["name"] for c in three_star))
    if carry:
        items = ", ".join(i["name"] for i in carry["items"])
        lines.append(f"Carry: {carry['name']}" + (f" - {items}" if items else ""))
    line = _milestone_line(agg if isinstance(agg, Mapping) else None)
    if line:
        lines.append(line)
    opener = agg.get("opener") if isinstance(agg, Mapping) else None
    names = [setdata.unit_name(o["api"]) for o in _list(opener) if isinstance(o, Mapping) and isinstance(o.get("api"), str)]
    if names:
        lines.append("Opener: " + ", ".join(names))
    if contest is not None:
        lines.append(f"Contested: {contest} of {len(core)} core on other boards")
    return [_fit(x) for x in lines[:DIGEST_MAX_LINES]]


def _summary(comp: Mapping) -> str:
    games = as_int(comp.get("games")) or 0
    avg, rate = comp.get("avg_placement"), comp.get("top4_rate")
    if not isinstance(avg, (int, float)) or isinstance(avg, bool):
        return f"{games} games, no placement yet"
    rate = rate if isinstance(rate, (int, float)) and not isinstance(rate, bool) else 0.0
    return f"{games} games, avg {avg:.1f}, top-4 {rate * 100:.0f}%"


def planner_choices(catalogue: Mapping, milestones_payload: Optional[Mapping], setdata: SetData, *,
                    lobby_boards: Any = None, limit: int = PLANNER_LIMIT) -> dict:
    """Up to `limit` comps with at least one top-4 game, each with its hover digest."""
    lobby_apis = set(_lobby_copies(lobby_boards, setdata)) if lobby_boards is not None else None
    payload = milestones_payload if isinstance(milestones_payload, Mapping) else {}
    per_comp = payload.get("comps") if isinstance(payload.get("comps"), Mapping) else {}
    choices = []
    for comp in _comps(catalogue):
        if len(choices) >= limit:
            break
        if (as_int(comp.get("top4_games")) or 0) < 1:
            continue
        agg = per_comp.get(comp["comp_id"]) if payload else None
        core = _unit_rows(comp, "core", setdata)
        three_star = _unit_rows(comp, "three_star", setdata)
        contest = sum(1 for c in core if c["api"] in lobby_apis) if lobby_apis is not None else None
        carry_row = _carry_row(comp, setdata)
        choices.append({
            "comp_id": comp["comp_id"], "label": comp.get("label"), "games": comp.get("games"),
            "top4_games": comp.get("top4_games"), "avg_placement": comp.get("avg_placement"),
            "top4_rate": comp.get("top4_rate"), "summary": _summary(comp), "core": core,
            "three_star": three_star, "carry": carry_row, "milestones": agg, "contest": contest,
            "digest": _digest(core, three_star, carry_row, agg, contest, setdata),
        })
    return dict(engine_meta(), set_id=setdata.set_id, top4_only=payload.get("top4_only", True), choices=choices)
