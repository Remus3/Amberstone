"""tft/engine/comps.py - set data view, board normalisation, traits, carry and
the deterministic comp catalogue (docs/TFT_PROGRAM.md section 5, output 1).

INPUTS
------
Set data comes ONLY through tft/tft_set.py (resolve_set + load_cdragon): the
reduced CommunityDragon extract, i.e. game data - units with cost and traits,
trait breakpoints, item recipes (items[].composition) and augment names. The
engine never reads a meta file, a tier list or any third-party statistic
(RM-846); tests/test_tft_engine_guards.py enforces it.

Match records are plain dicts, one per match of the OPERATOR'S OWN history:

    {"match_id": str, "set_id": int, "queue_kind": str | None,
     "placement": int | None,            # optional placement_conf / placement_src
     "final_board": [unit, ...],         # TFT-08 final_boards / gt_board rows
     "augments": [augment apiName, ...], # optional (vision only in Set 18)
     "rounds": [...], "shop_refreshes": [...], "units": [...]}  # milestones.py

A unit row may be any of the measured shapes: the per-round store
(champion_api, star, items_json, cost), the TFTEoGStats.json file
(championName, starLevel, itemNames, price) or the LCU EoG document
(championId, level = star, price, items[] of {nameId}). All of them carry
CommunityDragon apiNames, which join units[].apiName directly.

VALUE ENVELOPES
---------------
A measured scalar X arrives with X_conf / X_src siblings (section 1.1). The
engine treats a value as evidence only when it is present, its src is not
'absent' and not 'llm_fallback' (never an oracle), and its conf, when given,
is at least FIELD_MIN_CONF. envelope_value() is that one rule.

CATALOGUE
---------
Deterministic clustering of final boards in ONE set by unit Jaccard and the
Jaccard of the active-trait signature (active traits, unique one-unit traits
left out), equally weighted. Boards are taken in match_id order (input order
never matters), joined greedily to the most similar cluster leader at or above
JOIN_SIMILARITY, then refined: each cluster's medoid is recomputed and every
board re-assigned to its most similar medoid until nothing moves.

Per comp: id = "c-" + the first 10 hex of SHA-1 over the sorted core apiNames
(so a new flex-only game never moves it), label = top two traits + carry,
games, placed games, average placement, top-4 rate, core units (in at least
CORE_SHARE of its games), flex units, the carry (most-itemised unit, ties to
the higher cost) with its most common item sets, 3-star targets and augments.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

from tft import tft_set
from tft.engine import engine_meta

EMBLEM_SUFFIX = " Emblem"
FIELD_MIN_CONF = 0.6
NOT_EVIDENCE_SRC = frozenset({"absent", "llm_fallback"})

CORE_SHARE = 0.70
FLEX_SHARE = 0.25
THREE_STAR_SHARE = 0.50
SIGNATURE_SHARE = 0.50
JOIN_SIMILARITY = 0.50
UNIT_WEIGHT = 0.50
REFINE_PASSES = 10
TOP4_MAX_PLACEMENT = 4
DEFAULT_EXCLUDED_QUEUE_KINDS = frozenset({"double_up", "hyper_roll"})
MAX_FLEX = 8
MAX_ITEM_SETS = 3
MAX_AUGMENTS = 5
MAX_STAR = 4


# ------------------------------------------------------------------ helpers

def envelope_value(row: Any, name: str, *, min_conf: float = FIELD_MIN_CONF):
    """The value of field `name` in a store row when it counts as evidence, else None."""
    if not isinstance(row, Mapping):
        return None
    value = row.get(name)
    if value is None:
        return None
    src = row.get(name + "_src")
    if isinstance(src, str) and src in NOT_EVIDENCE_SRC:
        return None
    conf = row.get(name + "_conf")
    if conf is not None and not _conf_ok(conf, min_conf):
        return None
    return value


def row_is_evidence(row: Any, *, min_conf: float = FIELD_MIN_CONF) -> bool:
    """Row-level conf / src (unit_obs, shop_refresh, ...) under the same rule."""
    if not isinstance(row, Mapping):
        return False
    src = row.get("src")
    if isinstance(src, str) and src in NOT_EVIDENCE_SRC:
        return False
    conf = row.get("conf")
    return conf is None or _conf_ok(conf, min_conf)


def as_int(value) -> Optional[int]:
    """An int, or None for anything that is not a plain finite number (never raises)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if math.isfinite(value) else None
    if isinstance(value, str):
        s = value.strip()
        body = s[1:] if s.startswith("-") else s
        if body and body.isascii() and body.isdigit():
            return int(s)
    return None


def _conf_ok(conf, min_conf: float) -> bool:
    try:
        c = float(conf)
    except (TypeError, ValueError):
        return False
    return math.isfinite(c) and c >= min_conf


def jaccard(a: Iterable, b: Iterable) -> float:
    sa, sb = set(a), set(b)
    union = sa | sb
    if not union:
        return 0.0
    return len(sa & sb) / len(union)


def copies(star: int) -> int:
    """1-star equivalents of one unit at `star` (three combine into the next star)."""
    return 3 ** (max(1, int(star)) - 1)


def placement_of(record: Mapping) -> Optional[int]:
    p = as_int(envelope_value(record, "placement"))
    return p if p is not None and 1 <= p <= 8 else None


def _plain(obj):
    """Mapping keys as strings, recursively, so any record has one canonical text."""
    if isinstance(obj, Mapping):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    return obj


def canonical(obj) -> str:
    return json.dumps(_plain(obj), sort_keys=True, default=str)


# ------------------------------------------------------------------ set data

@dataclass(frozen=True)
class UnitInfo:
    api: str
    name: str
    cost: Optional[int]
    traits: tuple


@dataclass(frozen=True)
class SetData:
    """One set's game data, from the CommunityDragon extract."""

    set_id: Optional[int]
    units: Mapping[str, UnitInfo]
    trait_breakpoints: Mapping[str, tuple]
    recipes: Mapping[str, tuple]
    components: frozenset
    item_names: Mapping[str, str]
    emblem_traits: Mapping[str, str]
    augment_names: Mapping[str, str]
    api_lower: Mapping[str, str] = field(default_factory=dict, repr=False)
    unit_names: Mapping[str, tuple] = field(default_factory=dict, repr=False)
    item_by_name: Mapping[str, str] = field(default_factory=dict, repr=False)

    @classmethod
    def from_cdragon(cls, doc: Any, set_id: Optional[int] = None) -> "SetData":
        doc = doc if isinstance(doc, Mapping) else {}
        sid = set_id if set_id is not None else tft_set.parse_set_id(doc.get("_set"))
        units: dict = {}
        for row in doc.get("units") or []:
            if not isinstance(row, Mapping):
                continue
            api = row.get("apiName")
            if not isinstance(api, str) or not api.strip():
                continue
            name = row.get("name") if isinstance(row.get("name"), str) and row.get("name") else api
            traits = tuple(t for t in (row.get("traits") or []) if isinstance(t, str) and t)
            units[api] = UnitInfo(api=api, name=name, cost=as_int(row.get("cost")), traits=traits)
        breakpoints: dict = {}
        for row in doc.get("traits") or []:
            if not isinstance(row, Mapping) or not isinstance(row.get("name"), str):
                continue
            bps = sorted(b for b in (as_int(x) for x in (row.get("breakpoints") or [])) if b is not None and b > 0)
            breakpoints[row["name"]] = tuple(bps)
        recipes: dict = {}
        components: set = set()
        item_names: dict = {}
        for row in doc.get("items") or []:
            if not isinstance(row, Mapping) or not isinstance(row.get("apiName"), str):
                continue
            api = row["apiName"]
            item_names[api] = row.get("name") if isinstance(row.get("name"), str) and row.get("name") else api
            comp = [c for c in (row.get("composition") or []) if isinstance(c, str) and c]
            if len(comp) >= 2:
                recipes[api] = tuple(sorted(comp))
                components.update(comp)
        emblems = {}
        for api, name in item_names.items():
            if name.endswith(EMBLEM_SUFFIX):
                trait = name[: -len(EMBLEM_SUFFIX)].strip()
                if trait in breakpoints:
                    emblems[api] = trait
        augments = {}
        for row in doc.get("augments") or []:
            if isinstance(row, Mapping) and isinstance(row.get("apiName"), str):
                augments[row["apiName"]] = row.get("name") if isinstance(row.get("name"), str) else row["apiName"]
        names: dict = defaultdict(list)
        for api, info in units.items():
            names[info.name.lower()].append(api)
        item_by_name: dict = {}
        seen_names: Counter = Counter(n.lower() for n in item_names.values())
        for api, name in item_names.items():
            if seen_names[name.lower()] == 1:
                item_by_name[name.lower()] = api
        return cls(
            set_id=sid, units=units, trait_breakpoints=breakpoints, recipes=recipes,
            components=frozenset(components), item_names=item_names, emblem_traits=emblems,
            augment_names=augments, api_lower={a.lower(): a for a in units},
            unit_names={k: tuple(sorted(v)) for k, v in names.items()}, item_by_name=item_by_name)

    def resolve_unit_api(self, key: Any) -> Optional[str]:
        """apiName (exact or any case) or a display name -> the set's apiName."""
        if not isinstance(key, str) or not key.strip():
            return None
        s = key.strip()
        if s in self.units:
            return s
        low = s.lower()
        if low in self.api_lower:
            return self.api_lower[low]
        apis = self.unit_names.get(low)
        if not apis:
            return None
        if len(apis) == 1:
            return apis[0]
        base = [a for a in apis if a.lower().endswith("_base")]
        return base[0] if base else apis[0]

    def resolve_item_api(self, key: Any) -> Optional[str]:
        if not isinstance(key, str) or not key.strip():
            return None
        s = key.strip()
        if s in self.item_names:
            return s
        return self.item_by_name.get(s.lower(), s)

    def unit_name(self, api: str) -> str:
        info = self.units.get(api)
        return info.name if info else api

    def unit_cost(self, api: str) -> Optional[int]:
        info = self.units.get(api)
        return info.cost if info else None

    def item_name(self, api: str) -> str:
        return self.item_names.get(api, api)

    def item_kind(self, api: str) -> str:
        """component | emblem | crafted | other."""
        if api in self.components:
            return "component"
        if api in self.emblem_traits or self.item_name(api).endswith(EMBLEM_SUFFIX):
            return "emblem"
        if api in self.recipes:
            return "crafted"
        return "other"

    def is_unique_trait(self, trait: str) -> bool:
        bps = self.trait_breakpoints.get(trait)
        return bool(bps) and max(bps) <= 1


def load_set_data(set_id: Any = None, *, root=None) -> SetData:
    """The resolved set's game data, read through tft/tft_set.py."""
    n = tft_set.resolve_set(set_id, root=root)
    return SetData.from_cdragon(tft_set.load_cdragon(n, root=root), n)


# ------------------------------------------------------------------ boards

@dataclass(frozen=True)
class Unit:
    api: str
    star: int
    items: tuple
    cost: Optional[int]


_UNIT_KEYS = ("champion_api", "championName", "championId", "character_id", "apiName", "api", "name")
_STAR_KEYS = ("star", "starLevel", "tier", "level")
_COST_KEYS = ("cost", "price")


def _raw_items(raw: Mapping) -> list:
    for key in ("items", "itemNames"):
        value = raw.get(key)
        if isinstance(value, list):
            return value
    value = raw.get("items_json")
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _item_api(entry: Any, setdata: SetData) -> Optional[str]:
    if isinstance(entry, Mapping):
        for key in ("nameId", "apiName", "api", "name"):
            if isinstance(entry.get(key), str) and entry.get(key).strip():
                return setdata.resolve_item_api(entry[key])
        return None
    return setdata.resolve_item_api(entry)


def normalize_unit(raw: Any, setdata: SetData) -> Optional[Unit]:
    if isinstance(raw, Unit):
        return raw
    if not isinstance(raw, Mapping):
        return None
    key = next((raw[k] for k in _UNIT_KEYS if isinstance(raw.get(k), str) and raw[k].strip()), None)
    if key is None:
        return None
    api = setdata.resolve_unit_api(key) or key.strip()
    star = next((as_int(raw[k]) for k in _STAR_KEYS if as_int(raw.get(k)) is not None), 1)
    star = min(MAX_STAR, max(1, star))
    items = tuple(sorted(i for i in (_item_api(e, setdata) for e in _raw_items(raw)) if i))
    cost = next((as_int(raw[k]) for k in _COST_KEYS if as_int(raw.get(k)) is not None), None)
    if cost is None:
        cost = setdata.unit_cost(api)
    return Unit(api=api, star=star, items=items, cost=cost)


def normalize_board(raw_units: Any, setdata: SetData) -> tuple:
    if not isinstance(raw_units, (list, tuple)):
        return ()
    units = [x for x in (normalize_unit(r, setdata) for r in raw_units) if x is not None]
    return tuple(sorted(units, key=lambda x: (x.api, -x.star, x.items, x.cost or 0)))


def as_units(board: Any, setdata: SetData) -> tuple:
    if isinstance(board, tuple) and all(isinstance(x, Unit) for x in board):
        return board
    return normalize_board(list(board) if isinstance(board, (list, tuple)) else board, setdata)


# ------------------------------------------------------------------ traits

@dataclass(frozen=True)
class TraitState:
    trait: str
    count: int
    tier: int
    breakpoints: tuple

    @property
    def active(self) -> bool:
        return self.tier > 0


def board_traits(board: Any, setdata: SetData) -> list:
    """Every trait on the board, unique champions counted once, emblems included."""
    holders: dict = defaultdict(set)
    for unit in as_units(board, setdata):
        info = setdata.units.get(unit.api)
        traits = set(info.traits) if info else set()
        for item in unit.items:
            trait = setdata.emblem_traits.get(item)
            if trait:
                traits.add(trait)
        for trait in traits:
            holders[trait].add(unit.api)
    out = []
    for trait, apis in holders.items():
        bps = setdata.trait_breakpoints.get(trait, ())
        count = len(apis)
        out.append(TraitState(trait=trait, count=count, tier=sum(1 for b in bps if b <= count), breakpoints=bps))
    return sorted(out, key=lambda t: (-t.count, -t.tier, t.trait))


def trait_signature(board: Any, setdata: SetData) -> frozenset:
    return frozenset(t.trait for t in board_traits(board, setdata)
                     if t.active and not setdata.is_unique_trait(t.trait))


# ------------------------------------------------------------------- carry

def carry_items(unit: Unit, setdata: SetData) -> tuple:
    """Items that make a carry: completed non-emblem items (components never)."""
    return tuple(sorted(i for i in unit.items if setdata.item_kind(i) in ("crafted", "other")))


def board_carry(board: Any, setdata: SetData) -> Optional[Unit]:
    best, best_key = None, None
    for unit in as_units(board, setdata):
        n = len(carry_items(unit, setdata))
        if not n:
            continue
        key = (-n, -(unit.cost or 0), -unit.star, unit.api)
        if best_key is None or key < best_key:
            best, best_key = unit, key
    return best


# --------------------------------------------------------------- catalogue

@dataclass(frozen=True)
class _Board:
    match_id: str
    placement: Optional[int]
    units: tuple
    unit_set: frozenset
    signature: frozenset
    traits: tuple
    carry: Optional[Unit]
    augments: tuple


def _similarity(a: _Board, b: _Board) -> float:
    return UNIT_WEIGHT * jaccard(a.unit_set, b.unit_set) + (1.0 - UNIT_WEIGHT) * jaccard(a.signature, b.signature)


def record_id(record: Mapping) -> str:
    mid = record.get("match_id")
    if isinstance(mid, (str, int)) and str(mid).strip():
        return str(mid)
    return "anon-" + hashlib.sha1(canonical(record).encode("utf-8")).hexdigest()[:10]


def ordered_records(records: Any) -> list:
    """Records sorted by match id (then content), one per match id."""
    rows = [r for r in (records or []) if isinstance(r, Mapping)]
    keyed = sorted(((record_id(r), canonical(r), r) for r in rows), key=lambda t: (t[0], t[1]))
    out, seen = [], set()
    for mid, _c, rec in keyed:
        if mid in seen:
            continue
        seen.add(mid)
        out.append((mid, rec))
    return out


def _exclusion(record: Mapping, setdata: SetData, excluded: frozenset) -> Optional[str]:
    if setdata.set_id is not None and tft_set.parse_set_id(record.get("set_id")) != setdata.set_id:
        return "other_set"
    queue_kind = record.get("queue_kind")
    if isinstance(queue_kind, str) and queue_kind in excluded:
        return "queue_kind"
    return None


def _board_of(mid: str, record: Mapping, setdata: SetData) -> Optional[_Board]:
    units = normalize_board(record.get("final_board"), setdata)
    if not units:
        return None
    raw_augments = record.get("augments")
    raw_augments = raw_augments if isinstance(raw_augments, (list, tuple)) else []
    augments = tuple(sorted({a for a in raw_augments if isinstance(a, str) and a}))
    return _Board(
        match_id=mid, placement=placement_of(record), units=units,
        unit_set=frozenset(x.api for x in units), signature=trait_signature(units, setdata),
        traits=tuple(t for t in board_traits(units, setdata) if t.active), carry=board_carry(units, setdata),
        augments=augments)


def _best(board: _Board, leaders: list) -> tuple:
    best_i, best_s = None, -1.0
    for i, leader in enumerate(leaders):
        s = _similarity(board, leader)
        if s > best_s:
            best_i, best_s = i, s
    return best_i, best_s


def _medoid(members: list) -> _Board:
    best, best_key = None, None
    for m in members:
        total = sum(_similarity(m, o) for o in members if o is not m)
        key = (-round(total, 9), m.match_id)
        if best_key is None or key < best_key:
            best, best_key = m, key
    return best


def cluster_boards(boards: list) -> list:
    """Deterministic leader clustering + medoid refinement over boards in match-id order."""
    clusters: list = []
    leaders: list = []
    for b in boards:
        i, s = _best(b, leaders)
        if i is not None and s >= JOIN_SIMILARITY:
            clusters[i].append(b)
        else:
            clusters.append([b])
            leaders.append(b)
    for _ in range(REFINE_PASSES):
        medoids = [_medoid(c) for c in clusters]
        fresh: list = [[] for _ in medoids]
        for b in boards:
            i, _s = _best(b, medoids)
            fresh[i].append(b)
        fresh = [c for c in fresh if c]
        if [[x.match_id for x in c] for c in fresh] == [[x.match_id for x in c] for c in clusters]:
            break
        clusters = fresh
    return clusters


def _unit_row(api: str, setdata: SetData, share: Optional[float] = None) -> dict:
    row = {"api": api, "name": setdata.unit_name(api), "cost": setdata.unit_cost(api)}
    if share is not None:
        row["share"] = round(share, 3)
    return row


def _summarise(members: list, setdata: SetData) -> dict:
    n = len(members)
    placed = [b.placement for b in members if b.placement is not None]
    top4 = sum(1 for p in placed if p <= TOP4_MAX_PLACEMENT)

    def cost_of(api):
        return setdata.unit_cost(api) or 0

    unit_games = Counter(api for b in members for api in b.unit_set)
    ranked = sorted(unit_games.items(), key=lambda kv: (-kv[1], -cost_of(kv[0]), kv[0]))
    core = [api for api, c in ranked if c / n >= CORE_SHARE] or [api for api, _c in ranked[:3]]
    flex = [api for api, c in ranked if api not in core and c / n >= FLEX_SHARE][:MAX_FLEX]

    trait_sum: Counter = Counter()
    trait_games: Counter = Counter()
    for b in members:
        for t in b.traits:
            if not setdata.is_unique_trait(t.trait):
                trait_sum[t.trait] += t.count
                trait_games[t.trait] += 1
    trait_rank = sorted(trait_sum, key=lambda t: (-trait_sum[t], t))
    traits = [{"trait": t, "score": round(trait_sum[t] / n, 3), "share": round(trait_games[t] / n, 3)}
              for t in trait_rank]
    signature = sorted(t for t in trait_games if trait_games[t] / n >= SIGNATURE_SHARE)

    carry_games = Counter(b.carry.api for b in members if b.carry is not None)
    carry = None
    if carry_games:
        carry_api = sorted(carry_games, key=lambda a: (-carry_games[a], -cost_of(a), a))[0]
        sets: Counter = Counter()
        freq: Counter = Counter()
        for b in members:
            for unit in b.units:
                if unit.api == carry_api:
                    held = carry_items(unit, setdata)
                    if held:
                        sets[held] += 1
                    freq.update(held)
                    break
        item_sets = [{"items": list(s), "names": [setdata.item_name(i) for i in s], "games": c}
                     for s, c in sorted(sets.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_ITEM_SETS]]
        carry = dict(_unit_row(carry_api, setdata, carry_games[carry_api] / n), item_sets=item_sets,
                     item_freq={i: freq[i] for i in sorted(freq)})

    item_freq: Counter = Counter()
    for b in members:
        for unit in b.units:
            item_freq.update(i for i in unit.items if setdata.item_kind(i) != "component")
    three = Counter(api for b in members for api in {x.api for x in b.units if x.star >= 3})
    three_star = [_unit_row(a, setdata, c / n) for a, c in sorted(three.items(), key=lambda kv: (-kv[1], kv[0]))
                  if c / n >= THREE_STAR_SHARE]
    aug = Counter(a for b in members for a in b.augments)
    augments = [{"api": a, "name": setdata.augment_names.get(a, a), "games": c}
                for a, c in sorted(aug.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_AUGMENTS]]

    top_traits = [t["trait"] for t in traits[:2]]
    carry_name = carry["name"] if carry else None
    label = " / ".join(top_traits)
    if carry_name:
        label = f"{label} - {carry_name}" if label else carry_name
    if not label:
        label = " / ".join(setdata.unit_name(a) for a in core[:2]) or "Unlabelled"

    return {
        "label": label,
        "games": n,
        "placed_games": len(placed),
        "top4_games": top4,
        "avg_placement": round(sum(placed) / len(placed), 2) if placed else None,
        "top4_rate": round(top4 / len(placed), 3) if placed else None,
        "core": [_unit_row(a, setdata, unit_games[a] / n) for a in core],
        "flex": [_unit_row(a, setdata, unit_games[a] / n) for a in flex],
        "carry": carry,
        "three_star": three_star,
        "augments": augments,
        "traits": traits,
        "signature": signature,
        "item_freq": {i: item_freq[i] for i in sorted(item_freq)},
        "match_ids": sorted(b.match_id for b in members),
        "_core_ids": sorted(core),
    }


def _comp_sort_key(comp: dict) -> tuple:
    avg = comp["avg_placement"] if comp["avg_placement"] is not None else 99.0
    return (-comp["top4_games"], avg, -comp["games"], comp["comp_id"])


def build_catalogue(records: Any, setdata: SetData, *,
                    excluded_queue_kinds: frozenset = DEFAULT_EXCLUDED_QUEUE_KINDS) -> dict:
    """The comp catalogue for setdata's set, from the operator's final boards."""
    skipped = {"other_set": 0, "queue_kind": 0, "no_board": 0}
    boards = []
    for mid, rec in ordered_records(records):
        reason = _exclusion(rec, setdata, frozenset(excluded_queue_kinds))
        if reason:
            skipped[reason] += 1
            continue
        board = _board_of(mid, rec, setdata)
        if board is None:
            skipped["no_board"] += 1
            continue
        boards.append(board)

    comps = []
    for members in cluster_boards(boards):
        comp = _summarise(members, setdata)
        comp["comp_id"] = "c-" + hashlib.sha1("|".join(comp.pop("_core_ids")).encode("utf-8")).hexdigest()[:10]
        comps.append(comp)
    comps.sort(key=_comp_sort_key)
    used: Counter = Counter()
    for comp in comps:
        base = comp["comp_id"]
        used[base] += 1
        if used[base] > 1:
            comp["comp_id"] = f"{base}-{used[base]}"
    assignments = {}
    for comp in comps:
        for mid in comp["match_ids"]:
            assignments[mid] = comp["comp_id"]
    ordered = [dict(comp_id=c["comp_id"], **{k: v for k, v in c.items() if k != "comp_id"}) for c in comps]
    return dict(engine_meta(), set_id=setdata.set_id, games=len(boards), skipped=skipped, comps=ordered,
                assignments={k: assignments[k] for k in sorted(assignments)})


def assign_comp(board: Any, catalogue: Mapping, setdata: SetData) -> Optional[dict]:
    """The catalogue comp a (new) board belongs to, or None below JOIN_SIMILARITY."""
    units = as_units(board, setdata)
    if not units or not isinstance(catalogue, Mapping):
        return None
    unit_set = {x.api for x in units}
    sig = trait_signature(units, setdata)
    best, best_key = None, None
    for comp in catalogue.get("comps") or []:
        if not isinstance(comp, Mapping) or not isinstance(comp.get("comp_id"), str):
            continue
        pool = set(comp_units(comp, "core")) | set(comp_units(comp, "flex"))
        signature = [t for t in comp.get("signature") or [] if isinstance(t, str)]
        s = UNIT_WEIGHT * jaccard(unit_set, pool) + (1.0 - UNIT_WEIGHT) * jaccard(sig, signature)
        key = (-s, comp["comp_id"])
        if best_key is None or key < best_key:
            best, best_key = comp, key
    if best is None or -best_key[0] < JOIN_SIMILARITY:
        return None
    return {"comp_id": best["comp_id"], "label": best.get("label"), "similarity": round(-best_key[0], 3)}


def comp_units(comp: Any, key: str) -> list:
    """The apiNames of a catalogue comp's "core" / "flex" / "three_star" rows (tolerant of junk)."""
    if not isinstance(comp, Mapping):
        return []
    rows = comp.get(key) or []
    return [r["api"] for r in rows if isinstance(r, Mapping) and isinstance(r.get("api"), str)] \
        if isinstance(rows, (list, tuple)) else []
