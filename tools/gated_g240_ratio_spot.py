"""gated_g240_ratio_spot.py - read-only sampler + grader for G2-40.

G2-40 asks for a spot verify of DS ability ratio blocks against Practice Tool
target dummies: does the number DS would use for an ability match the number
the game actually deals? "Sample a handful per session, never a bulk pass."

Facts measured at source (s144 lane gated c50) that shape the check:

- The filed "~174/577" is a 2026-06-08 census (item 351) and cannot be
  re-derived from tracked data: ``tools/daemon_slayer_cdragon_ratio_extract.py``
  writes ``resolution`` and ``calc_type`` per block, NOT the fallback reason, so
  the "live-state" class is not separable from the emission-guard class. The
  ``census`` sub-command prints what the sidecar does hold at the current patch.
- A sidecar block with ``resolution=fallback`` carries NO ratios, and its
  ``name`` does not pair to an engine block name. So the sample unit is the
  ABILITY: "the sidecar has a fallback block for this key" means DS may be
  reading Meraki there, and the number under test is the engine's own block.
- The prediction comes from the engine's ``ability_dps._evaluate_block`` over
  ``AbilitiesSnapshot.load()`` and ``AbilityContext.from_build``, mitigated by
  ``dps._armor_factor``, never a re-implemented formula, so a pass cannot be a
  second copy agreeing with itself. That bare ``load()`` is the route default;
  the ability-base-overrides flag is OFF there and is not modelled here.

A prediction is COMPUTE and is never evidence. The evidence is the post-mitigation
number the GAME showed in combat text, read by the operator (or off a timestamped
frame) and handed to ``grade``. This tool cannot see that number.

Why a control. A wrong dummy resist, a rune proc or a stale stat read would make
every number miss, and that would read as a DS defect. So each session needs a
CONTROL sample: an ability on the same champion, target and game whose one sidecar
block is mechanical and whose engine form has one damage block, which is the pair
the engine re-sources directly. A control proves the resist of ITS OWN damage type
only, so a MAGIC or PHYSICAL sample needs a control of that type (a TRUE sample has
no resist; any control serves). It must also predict at least CONTROL_MIN_PREDICTED:
below that the ABS_TOL floor is wider than REL_TOL, so a wrong resist passes the
control and then misses on a bigger sample. A control that misses voids the group
instead of filing a finding against DS. Among the reasons ``grade`` lists, a block
is UNPREDICTABLE when it or a sibling in its form scales on target state, because no control proves a typed dummy
max HP and a "Minimum" block is the floor of such a sibling, and when its name
repeats in its form, because one name cannot say which number it is.
``plan`` lists what a session can grade, and ``census`` counts the champions where
nothing is.

Why every ratio must show. G2-40 is about ratios, and a term multiplied by zero
tests nothing: at 0 AP an AP-ratio block predicts its base alone, and beside an AD
ratio the AP one would still go untested. A MATCH where ANY ratio on the block
contributes within the tolerance is BASE_ONLY and does not count. A miss there still
counts, as a candidate. ``capture`` prints ``weakest_ratio_part`` before the cast,
so the operator can raise the stat first.

Penetration. Combat text is post-penetration and the prediction is not, so a resist
above 0 needs penetration proven absent, not assumed: flat fields must read 0 and
percent fields must read 0.0 or 1.0. Whether the client reports "none" as 0.0 or as
a remaining multiplier of 1.0 is unmeasured; both ends are safe to read as none,
because neither can mean a real full penetration on an item-free champion.

Sub-commands (READ-ONLY: only GETs to the relay, and only ``capture --out`` writes,
to a new path it creates; no LCU write, no restart, no tick):

  census
      Offline. Sidecar block counts by resolution and calc_type, the sample pools.
  plan [--champion ID | --snapshot FILE]
      The champion's fallback and control abilities, in Q W E R order, with each
      engine damage block. Cast in this order; do not pick the ones that look good.
  capture --key K --block NAME --target-armor A --target-mr M --target-max-hp H
          [--form N] [--snapshot FILE] [--out NEW_FILE]
      Lock the prediction for one block from the live relay BEFORE the cast. Refuses
      (exit 2, nothing written): not Practice Tool, a stale relay read, a stat or
      level the payload does not carry, rank 0, a block that is not a damage block,
      an ability neither fallback nor control, a negative or non-finite target, a
      resist above 0 without penetration proven absent, an existing ``--out`` path.
      ``--snapshot`` is a REHEARSAL: the record says ``source: file`` and ``grade``
      never counts it, so a saved or tuned payload cannot pose as a live lock.
  grade FILE=OBSERVED [FILE=OBSERVED ...]
      OBSERVED is the combat-text number. Each record is re-derived from the engine
      first (role, type, prediction; a different DS patch is refused). Per sample:
      MATCH, BASE_ONLY, MISMATCH, WEAK (a control too small to prove a resist),
      NEAR_MISS (outside the tolerance but inside NEAR_MISS_FACTOR times it),
      UNPREDICTABLE (the engine marks the block unparsed, the type is unknown or MIXED,
      it or a sibling scales on target state, or its name repeats; a match or a miss
      there says nothing, with or without a control), VOID (a rehearsal, or any other
      sample with no clean passing same-type control from the same game in its group).
      Overall: SAMPLE_OK, FINDING, INCOMPLETE. Over
      MAX_FALLBACK_SAMPLES fallback samples is refused as a bulk pass.

MATCH = |observed - predicted| <= max(ABS_TOL, REL_TOL * predicted), stated before
any game. The near-miss band exists because a control that just passes can still
hide up to the tolerance of resist error, plus rounding if combat text is whole
numbers, and a sample then misses by about that much with no DS defect. Past
NEAR_MISS_FACTOR times the tolerance that excuse is spent. Exit 0 = census / plan /
capture done, or SAMPLE_OK; 3 = FINDING or INCOMPLETE; 2 = a refusal, an unreadable
input or a bad argument.

SAMPLE_OK never ticks G2-40 (the row is DS-batch scoped and stays open). FINDING is
a CANDIDATE: this tool models one block on a clean dummy, not every floor, proc or
stack in the game, so a human reads the ability's in-game text before a DS defect
is filed on that ability. It does not re-pitch a calc-graph resolver, which stays
closed (docs/DS_COMPLETENESS_GAP.md b1).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents.daemon_slayer.abilities import (  # noqa: E402
    AbilitiesSnapshot,
    _read_cdragon_sidecar_doc,
)
from agents.daemon_slayer.ability_dps import (  # noqa: E402
    _SCALING_TARGETS,
    AbilityContext,
    _evaluate_block,
)
from agents.daemon_slayer.data_loader import DataSnapshot  # noqa: E402
from agents.daemon_slayer.dps import _armor_factor  # noqa: E402
from agents.daemon_slayer.stats import scaled  # noqa: E402

TOOL = "gated_g240_ratio_spot"
ABS_TOL = 2.0
REL_TOL = 0.03
CONTROL_MIN_PREDICTED = ABS_TOL / REL_TOL
NEAR_MISS_FACTOR = 2.0
MAX_FALLBACK_SAMPLES = 5
MAX_SNAPSHOT_AGE_S = 15.0
SESSION_SKEW_S = 120.0
MAX_LEVEL = 30
MAX_RANK = 6
PRACTICE_MODE = "PRACTICETOOL"
KEYS = ("Q", "W", "E", "R")
SOURCE_RELAY = "relay"
SOURCE_FILE = "file"
_RAW_PREFIX = "game_character_displayname_"
_DAMAGE_TYPES = ("MAGIC", "PHYSICAL", "TRUE")
_STAT_FIELDS = {"ad": "attackDamage", "ap": "abilityPower", "hp": "maxHealth",
                "armor": "armor", "mr": "magicResist", "mp": "resourceMax",
                "ms": "moveSpeed"}
# (required, optional): required is what the repo's own normalizer reads.
_FLAT_PEN = {"PHYSICAL": (("physicalLethality",), ("armorPenetrationFlat",)),
             "MAGIC": (("magicPenetrationFlat",), ("magicLethality",))}
_PCT_PEN = {"PHYSICAL": (("armorPenetrationPercent",), ("bonusArmorPenetrationPercent",)),
            "MAGIC": (("magicPenetrationPercent",), ("bonusMagicPenetrationPercent",))}
_TARGET_STATE_FIELDS = ("target_max_hp_pct", "target_missing_hp_pct",
                        "target_current_hp_pct", "target_bonus_hp_pct",
                        "target_armor_pct")
_NUMERIC_RECORD_KEYS = ("raw", "predicted", "ratio_part", "weakest_ratio_part",
                        "target_armor", "target_mr", "target_max_hp",
                        "game_time_s", "captured_at")
_TEXT_RECORD_KEYS = ("ds_patch", "champion", "block")
_RECORD_KEYS = ("tool", "form", "key", "role", "rank", "level", "damage_type", "stats",
                "unpredictable", "source") + _NUMERIC_RECORD_KEYS + _TEXT_RECORD_KEYS


class Refused(ValueError):
    """A capture or grade input the tool will not turn into a record."""


def _finite(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:  # an integer too large for a float
        return False


def load_data() -> tuple[AbilitiesSnapshot, DataSnapshot, dict]:
    """The engine's default ability snapshot, base stats and sidecar champions."""
    abilities = AbilitiesSnapshot.load()
    data = DataSnapshot.load()
    doc = _read_cdragon_sidecar_doc(Path(abilities.data_root), abilities.patch) or {}
    champs = doc.get("champions")
    return abilities, data, champs if isinstance(champs, dict) else {}


def _damage_blocks(form: Any) -> list:
    return [b for b in form.damage_blocks if b.attribute_kind == "damage"]


def classify(sidecar_key_blocks: Any, forms: tuple) -> str:
    """``fallback``, ``control`` or ``other`` for one ability key.

    fallback: the sidecar has a fallback block and the engine has a damage block.
    control: exactly one sidecar block, mechanical, and one form with exactly one
    damage block, of a known non-mixed type, fully parsed. A wider mechanical set
    can leave the engine on Meraki, so it is not called a control.
    """
    blocks = [b for b in (sidecar_key_blocks or []) if isinstance(b, dict)]
    if not forms or not any(_damage_blocks(f) for f in forms):
        return "other"
    res = [b.get("resolution") for b in blocks]
    if "fallback" in res:
        return "fallback"
    if res != ["mechanical"] or len(forms) != 1:
        return "other"
    dmg = _damage_blocks(forms[0])
    if len(dmg) == 1 and _unpredictable_reason(forms[0], dmg[0]) is None:
        return "control"
    return "other"


def _covered(damage_type: Any, control_types: set) -> bool:
    """Whether a control of these types proves the setup for this damage type."""
    if damage_type == "TRUE":
        return bool(control_types)
    return damage_type in control_types


def _roster_row(abilities: AbilitiesSnapshot, sidecar: dict, champion: str) -> list[dict]:
    """Per key: role, forms and, for a fallback, whether a control can cover it."""
    per_key = sidecar.get(champion) or {}
    rows = []
    for key in KEYS:
        forms = abilities.get_abilities(champion).get(key) or ()
        role = classify(per_key.get(key), forms)
        if role != "other":
            rows.append({"key": key, "role": role, "forms": [
                {"form": f.form_index, "damage_type": f.damage_type,
                 "blocks": [b.attribute for b in _damage_blocks(f)],
                 "gradeable": [b.attribute for b in _damage_blocks(f)
                               if _unpredictable_reason(f, b) is None]}
                for f in forms if _damage_blocks(f)]})
    control_types = {f["damage_type"] for r in rows if r["role"] == "control"
                     for f in r["forms"]}
    for row in rows:
        if row["role"] == "fallback":
            row["covered"] = any(f["gradeable"]
                                 and _covered(f["damage_type"], control_types)
                                 for f in row["forms"])
    return rows


def census(abilities: AbilitiesSnapshot, sidecar: dict) -> dict:
    """What the sidecar holds at this patch, and the pools a session samples from."""
    by_res: Counter = Counter()
    by_calc: Counter = Counter()
    pools: Counter = Counter()
    covered = not_covered = 0
    for champ, per_key in sidecar.items():
        for blocks in per_key.values():
            for block in blocks if isinstance(blocks, list) else []:
                by_res[block.get("resolution")] += 1
                if block.get("resolution") == "fallback":
                    by_calc[block.get("calc_type")] += 1
        if not abilities.has_champion(champ):
            continue
        roles = {k: classify(per_key.get(k), abilities.get_abilities(champ).get(k) or ())
                 for k in KEYS}
        pools.update(roles.values())
        fallback = [r for r in _roster_row(abilities, sidecar, champ)
                    if r["role"] == "fallback"]
        if fallback:
            if any(r["covered"] for r in fallback):
                covered += 1
            else:
                not_covered += 1
    return {
        "patch": abilities.patch,
        "blocks_by_resolution": dict(by_res),
        "fallback_by_calc_type": dict(by_calc),
        "abilities_by_role": dict(pools),
        "champions_with_a_covered_fallback": covered,
        "champions_with_no_covered_fallback": not_covered,
        "filed_count_note": "the filed ~174/577 is not derivable: no fallback reason "
                            "is persisted per block",
    }


def resolve_champion(abilities: AbilitiesSnapshot, name: str) -> str:
    """The snapshot's id for ``name``; the client spells some ids in another case."""
    wanted = name.strip().lower()
    for champ in abilities.champion_ids():
        if champ.lower() == wanted:
            return champ
    raise Refused(f"champion not in the ability snapshot: {name!r}")


def plan(abilities: AbilitiesSnapshot, sidecar: dict, champion: str) -> dict:
    """Fallback and control abilities for ``champion``, in cast order."""
    champion = resolve_champion(abilities, champion)
    rows = _roster_row(abilities, sidecar, champion)
    covered = [r["key"] for r in rows if r.get("covered")]
    return {
        "champion": champion, "patch": abilities.patch, "abilities": rows,
        "sample_order": covered[:MAX_FALLBACK_SAMPLES],
        "uncovered": [r["key"] for r in rows
                      if r["role"] == "fallback" and not r["covered"]],
        "no_control": not any(r["role"] == "control" for r in rows),
    }


def read_snapshot(payload: Any, now: Optional[float] = None) -> dict:
    """Raw allgamedata from an envelope or a bare document.

    ``now`` is the live path, where a stale, future or untimed envelope is refused.
    A file has no ``now``: its age cannot matter, because its record never counts.
    """
    if not isinstance(payload, dict):
        raise Refused("snapshot is not a JSON object")
    data = payload["data"] if isinstance(payload.get("data"), dict) else payload
    if now is not None:
        ts = payload.get("ts") if data is not payload else None
        age = now - ts if _finite(ts) else None
        if age is None or age < 0 or age > MAX_SNAPSHOT_AGE_S:
            raise Refused(f"relay snapshot is stale or untimed (age {age})")
    if not isinstance(data.get("activePlayer"), dict) or not data["activePlayer"]:
        raise Refused("no activePlayer: no game is up")
    return data


def _active_row(data: dict) -> dict:
    """The active player's allPlayers row; riotId first, a name can be shared."""
    ap = data.get("activePlayer") or {}
    players = data.get("allPlayers")
    rows = [r for r in players if isinstance(r, dict)] if isinstance(players, list) else []
    for field in ("riotId", "riotIdGameName", "summonerName"):
        if ap.get(field):
            return next((r for r in rows if r.get(field) == ap[field]), {})
    return {}


def active_champion(data: dict) -> str:
    """The active player's champion id; raw name first, so Wukong is MonkeyKing."""
    raw = str(_active_row(data).get("rawChampionName") or "")
    if raw.lower().startswith(_RAW_PREFIX):
        return raw[len(_RAW_PREFIX):]
    raise Refused("active player's champion is not readable from allPlayers")


def _non_inventory_ids() -> frozenset:
    """Trinkets and consumables grant no penetration. Fail closed: filter nothing."""
    try:
        from core.daemon_slayer_resolver import NON_INVENTORY_IDS
        return frozenset(str(i) for i in NON_INVENTORY_IDS)
    except Exception:  # noqa: BLE001 - an import failure only refuses more captures
        return frozenset()


def _items_owned(row: dict) -> Optional[int]:
    """Real items held; None when the list cannot be read (penetration unknowable)."""
    items = row.get("items")
    if not isinstance(items, list):
        return None
    skip = _non_inventory_ids()
    return sum(1 for it in items
               if not (isinstance(it, dict) and str(it.get("itemID")) in skip))


def live_inputs(data: dict) -> dict:
    """The stats, level and ranks off one allgamedata document; refuses a gap."""
    ap = data["activePlayer"]
    cs = ap.get("championStats") if isinstance(ap.get("championStats"), dict) else {}
    missing = [f for f in _STAT_FIELDS.values() if not _finite(cs.get(f))]
    if missing:
        raise Refused(f"championStats does not carry {missing}")
    level = ap.get("level")
    if not _finite(level) or level != int(level) or not 1 <= level <= MAX_LEVEL:
        raise Refused(f"activePlayer level is not readable: {level!r}")
    abilities = ap.get("abilities") if isinstance(ap.get("abilities"), dict) else {}
    ranks = {}
    for key in KEYS:
        entry = abilities.get(key) if isinstance(abilities.get(key), dict) else {}
        rank = entry.get("abilityLevel")
        whole = _finite(rank) and rank == int(rank) and 0 <= rank <= MAX_RANK
        ranks[key] = int(rank) if whole else 0
    game = data.get("gameData") if isinstance(data.get("gameData"), dict) else {}
    game_time = game.get("gameTime")
    if not _finite(game_time) or game_time < 0:
        raise Refused(f"gameData.gameTime is not readable: {game_time!r}")
    return {
        "level": int(level), "ranks": ranks,
        "stats": {k: float(cs[f]) for k, f in _STAT_FIELDS.items()},
        "champion_stats": cs,
        "items_owned": _items_owned(_active_row(data)),
        "game_mode": str(game.get("gameMode") or ""),
        "game_time_s": float(game_time),
    }


def penetration_gap(inputs: dict, damage_type: str) -> Optional[str]:
    """Why penetration is not proven absent for this type; None when it is."""
    cs = inputs["champion_stats"]
    if inputs["items_owned"] != 0:
        return f"items owned reads {inputs['items_owned']}"
    for table, is_clear in ((_FLAT_PEN, lambda v: v == 0), (_PCT_PEN, lambda v: v in (0, 1))):
        required, optional = table[damage_type]
        for field in required + optional:
            if field not in cs and field in optional:
                continue
            if not _finite(cs.get(field)):
                return f"{field} is not readable"
            if not is_clear(cs[field]):
                return f"{field} reads {cs[field]}"
    return None


def base_stats(data: DataSnapshot, champion: str, level: int) -> dict:
    """Base stats at ``level``, so from_build derives bonus AD the way the engine does."""
    st = data.champion(champion)["stats"]

    def num(field: str) -> float:
        return float(st[field]) if _finite(st.get(field)) else 0.0

    out = {key: scaled(num(base), num(grow), level)
           for key, base, grow in (("ad", "attackdamage", "attackdamageperlevel"),
                                   ("hp", "hp", "hpperlevel"),
                                   ("armor", "armor", "armorperlevel"),
                                   ("mr", "spellblock", "spellblockperlevel"),
                                   ("mp", "mp", "mpperlevel"))}
    out["ms"] = num("movespeed")
    return out


def _unpredictable_reason(form: Any, block: Any) -> Optional[str]:
    if form.parse_status != "ok":
        return f"form parse_status {form.parse_status}"
    if block.unparsed_modifiers:
        return "block has unparsed modifiers"
    if form.damage_type not in _DAMAGE_TYPES:
        return f"damage type {form.damage_type}"
    if any(any(getattr(b, f, None) for f in _TARGET_STATE_FIELDS) or b.bilinear_terms
           for b in _damage_blocks(form)):
        return "the form scales on target state, which no control proves"
    if sum(b.attribute == block.attribute for b in _damage_blocks(form)) > 1:
        return "block name repeats in this form"
    return None


def _check_target(armor: Any, mr: Any, max_hp: Any) -> None:
    if not all(_finite(v) and v >= 0 for v in (armor, mr)):
        raise Refused(f"target resist must be finite and not negative: {armor!r}, {mr!r}")
    if not (_finite(max_hp) and max_hp > 0):
        raise Refused(f"target max HP must be finite and positive: {max_hp!r}")


def predict(abilities: AbilitiesSnapshot, data: DataSnapshot, sidecar: dict, *,
            champion: str, key: str, form_index: int, block_name: str, rank: int,
            level: int, stats: dict, target_armor: float, target_mr: float,
            target_max_hp: float) -> dict:
    """The role and the engine's number for one block; the single compute path."""
    _check_target(target_armor, target_mr, target_max_hp)
    champion = resolve_champion(abilities, champion)
    forms = abilities.get_abilities(champion).get(key) or ()
    role = classify((sidecar.get(champion) or {}).get(key), forms)
    if role == "other":
        raise Refused(f"{champion} {key} is neither a fallback nor a control ability")
    form = next((f for f in forms if f.form_index == form_index), None)
    if form is None:
        raise Refused(f"{champion} {key} has no form {form_index}")
    block = next((b for b in _damage_blocks(form) if b.attribute == block_name), None)
    if block is None:
        raise Refused(f"{champion} {key} has no damage block {block_name!r}")
    ctx = AbilityContext.from_build(
        stats, base_stats(data, champion, level), target_armor=target_armor,
        target_mr=target_mr, target_max_hp=target_max_hp, target_bonus_hp=0.0)
    raw = _evaluate_block(block, rank - 1, ctx)
    if not _finite(raw):
        raise Refused(f"prediction is not finite: {raw!r}")
    resist = {"PHYSICAL": target_armor, "MAGIC": target_mr}.get(form.damage_type, 0.0)
    factor = _armor_factor(resist)
    terms = [abs(block.value_at(field, rank - 1) / 100.0 * getattr(ctx, attr, 0.0)) * factor
             for field, attr in _SCALING_TARGETS if block.value_at(field, rank - 1)]
    return {"champion": champion, "role": role, "damage_type": form.damage_type,
            "raw": raw, "predicted": raw * factor, "resist": resist,
            "ratio_part": (raw - block.value_at("base", rank - 1)) * factor,
            "weakest_ratio_part": min(terms, default=0.0),
            "unpredictable": _unpredictable_reason(form, block)}


def capture(abilities: AbilitiesSnapshot, data: DataSnapshot, sidecar: dict,
            snapshot: dict, *, key: str, block_name: str, form_index: int,
            target_armor: float, target_mr: float, target_max_hp: float,
            source: str, captured_at: float) -> dict:
    """Lock one prediction. Raises Refused rather than record a void sample."""
    inputs = live_inputs(snapshot)
    if inputs["game_mode"] != PRACTICE_MODE:
        raise Refused(f"not Practice Tool (gameMode {inputs['game_mode']!r})")
    rank = inputs["ranks"].get(key, 0)
    if rank < 1:
        raise Refused(f"{key} is not levelled (rank {rank})")
    args = {"key": key, "form_index": form_index, "block_name": block_name, "rank": rank,
            "level": inputs["level"], "stats": inputs["stats"],
            "target_armor": target_armor, "target_mr": target_mr,
            "target_max_hp": target_max_hp}
    result = predict(abilities, data, sidecar,
                     champion=active_champion(snapshot), **args)
    if result["resist"] > 0:
        gap = penetration_gap(inputs, result["damage_type"])
        if gap:
            raise Refused(f"resist above 0 needs penetration proven absent: {gap}")
    return {
        "tool": TOOL, "ds_patch": abilities.patch, "champion": result["champion"],
        "key": key, "form": form_index, "block": block_name, "role": result["role"],
        "rank": rank, "level": inputs["level"], "damage_type": result["damage_type"],
        "target_armor": target_armor, "target_mr": target_mr,
        "target_max_hp": target_max_hp, "stats": inputs["stats"],
        "items_owned": inputs["items_owned"], "game_mode": inputs["game_mode"],
        "game_time_s": inputs["game_time_s"], "source": source,
        "captured_at": captured_at, "raw": result["raw"],
        "predicted": result["predicted"], "ratio_part": result["ratio_part"],
        "weakest_ratio_part": result["weakest_ratio_part"],
        "unpredictable": result["unpredictable"],
    }


def _tolerance(predicted: float) -> float:
    return max(ABS_TOL, REL_TOL * abs(predicted))


def matches(observed: float, predicted: float) -> bool:
    return abs(observed - predicted) <= _tolerance(predicted)


def near_miss(observed: float, predicted: float) -> bool:
    """Outside the tolerance, but inside what a just-passing control can still hide."""
    return (not matches(observed, predicted)
            and abs(observed - predicted) <= NEAR_MISS_FACTOR * _tolerance(predicted))


def _group(rec: dict) -> tuple:
    return (rec["ds_patch"], rec["champion"], rec["target_armor"], rec["target_mr"],
            rec["target_max_hp"])


def _started_at(rec: dict) -> float:
    """Wall-clock game start: the same game gives nearly the same value."""
    return rec["captured_at"] - rec["game_time_s"]


def check_record(rec: Any) -> dict:
    """Refuse a record that is not this tool's, or holds a value grading cannot use."""
    if not isinstance(rec, dict) or rec.get("tool") != TOOL:
        raise Refused("not a capture record of this tool")
    missing = [k for k in _RECORD_KEYS if k not in rec]
    if missing:
        raise Refused(f"record is missing {missing}")
    if rec["role"] not in ("fallback", "control"):
        raise Refused(f"bad role {rec['role']!r}")
    if rec["source"] not in (SOURCE_RELAY, SOURCE_FILE):
        raise Refused(f"bad source {rec['source']!r}")
    if rec["key"] not in KEYS:
        raise Refused(f"bad key {rec['key']!r}")
    bad = [k for k in _NUMERIC_RECORD_KEYS if not _finite(rec[k])]
    bad += [k for k in _TEXT_RECORD_KEYS if not (isinstance(rec[k], str) and rec[k])]
    bad += [k for k in ("form", "rank", "level")
            if not (isinstance(rec[k], int) and not isinstance(rec[k], bool))]
    stats = rec["stats"]
    if not (isinstance(stats, dict) and all(_finite(stats.get(k)) for k in _STAT_FIELDS)):
        bad.append("stats")
    if not (rec["unpredictable"] is None or isinstance(rec["unpredictable"], str)):
        bad.append("unpredictable")
    if bad:
        raise Refused(f"record has unusable values: {bad}")
    if (not 1 <= rec["rank"] <= MAX_RANK or not 1 <= rec["level"] <= MAX_LEVEL
            or rec["form"] < 0 or rec["game_time_s"] < 0):
        raise Refused("record has an impossible rank, level, form or game time")
    _check_target(rec["target_armor"], rec["target_mr"], rec["target_max_hp"])
    return rec


def verify_record(rec: dict, abilities: AbilitiesSnapshot, data: DataSnapshot,
                  sidecar: dict) -> dict:
    """Re-derive role and prediction from the engine; refuses an edited or stale record."""
    check_record(rec)
    if rec["ds_patch"] != abilities.patch:
        raise Refused(f"record is from DS patch {rec['ds_patch']}, not {abilities.patch}")
    fresh = predict(abilities, data, sidecar, champion=rec["champion"], key=rec["key"],
                    form_index=rec["form"], block_name=rec["block"], rank=rec["rank"],
                    level=rec["level"], stats=rec["stats"],
                    target_armor=rec["target_armor"], target_mr=rec["target_mr"],
                    target_max_hp=rec["target_max_hp"])
    same = (fresh["role"] == rec["role"]
            and fresh["damage_type"] == rec["damage_type"]
            and fresh["unpredictable"] == rec["unpredictable"]
            and math.isclose(fresh["predicted"], rec["predicted"], abs_tol=1e-6)
            and math.isclose(fresh["ratio_part"], rec["ratio_part"], abs_tol=1e-6)
            and math.isclose(fresh["weakest_ratio_part"], rec["weakest_ratio_part"],
                             abs_tol=1e-6))
    if not same:
        raise Refused(f"record does not re-derive from the engine: {rec['champion']} "
                      f"{rec['key']} {rec['block']}")
    return rec


def grade(samples: list[tuple[dict, float]]) -> dict:
    """Grade (record, observed) pairs; refuses a bulk pass or a repeated sample."""
    seen = set()
    for rec, observed in samples:
        check_record(rec)
        if not _finite(observed) or observed <= 0:
            raise Refused(f"observed must be a positive finite number, got {observed!r}")
        ident = _group(rec) + (rec["key"], rec["form"], rec["block"], rec["rank"],
                               round(rec["predicted"], 6))
        if ident in seen:
            raise Refused(f"sample repeated: {rec['champion']} {rec['key']} {rec['block']}")
        seen.add(ident)
    n_fallback = sum(rec["role"] == "fallback" for rec, _ in samples)
    if n_fallback > MAX_FALLBACK_SAMPLES:
        raise Refused(f"bulk pass refused: {n_fallback} fallback samples, the cap is "
                      f"{MAX_FALLBACK_SAMPLES} per grade run")

    def first_read(rec: dict, observed: float) -> str:
        if rec["unpredictable"]:
            return "UNPREDICTABLE"
        return "MATCH" if matches(observed, rec["predicted"]) else "MISMATCH"

    def ratio_untested(rec: dict) -> bool:
        return rec["weakest_ratio_part"] <= _tolerance(rec["predicted"])

    def control_read(rec: dict, observed: float) -> str:
        read = first_read(rec, observed)
        return "WEAK" if read == "MATCH" and rec["predicted"] < CONTROL_MIN_PREDICTED else read

    controls = [(rec, control_read(rec, observed)) for rec, observed in samples
                if rec["role"] == "control" and rec["source"] == SOURCE_RELAY]

    def control_reads(rec: dict) -> list[str]:
        return [read for ctl, read in controls
                if _group(ctl) == _group(rec)
                and abs(_started_at(ctl) - _started_at(rec)) <= SESSION_SKEW_S
                and _covered(rec["damage_type"], {ctl["damage_type"]})]

    rows = []
    for rec, observed in samples:
        verdict = first_read(rec, observed)
        reason = None
        if rec["source"] != SOURCE_RELAY:
            verdict, reason = "VOID", "rehearsal capture from a file, not a live lock"
        elif rec["role"] == "control":
            verdict = control_read(rec, observed)
            if verdict == "WEAK":
                reason = (f"predicts under {CONTROL_MIN_PREDICTED:.1f}, where the absolute "
                          "tolerance can hide a wrong resist")
        elif rec["unpredictable"]:
            reason = rec["unpredictable"]  # says nothing, with or without a control
        else:
            reads = control_reads(rec)
            if "MATCH" not in reads:
                verdict, reason = "VOID", ("no passing same-type control from this "
                                           "game and target")
            elif "MISMATCH" in reads:
                verdict, reason = "VOID", "a control missed in this group"
            elif verdict == "MATCH" and ratio_untested(rec):
                verdict, reason = "BASE_ONLY", ("a ratio contributes within the tolerance, "
                                                "so a match does not test it")
            elif verdict == "MISMATCH" and near_miss(observed, rec["predicted"]):
                verdict, reason = "NEAR_MISS", ("within what a just-passing control can "
                                                "hide; neither a pass nor a finding")
        rows.append({"champion": rec["champion"], "key": rec["key"],
                     "block": rec["block"], "role": rec["role"],
                     "predicted": round(float(rec["predicted"]), 2),
                     "observed": observed, "verdict": verdict, "reason": reason})
    counted = [r["verdict"] for r in rows if r["role"] == "fallback"]
    if "MISMATCH" in counted:
        overall = "FINDING"
    elif "NEAR_MISS" in counted or "VOID" in counted:
        overall = "INCOMPLETE"  # a pass must not sit on top of an unexplained sample
    elif "MATCH" in counted:
        overall = "SAMPLE_OK"
    else:
        overall = "INCOMPLETE"
    return {"verdict": overall, "samples": rows, "tolerance":
            {"abs": ABS_TOL, "rel": REL_TOL},
            "note": "not a tick: G2-40 stays open; a prediction alone is not evidence; "
                    "a FINDING is a candidate until a human reads the ability's text"}


def _fetch_live() -> dict:
    from tools.gated_frame_readback import resolve_token
    from tools.gated_live_probe import _get_json, _RELAY_BASE
    token = resolve_token()[0]
    body, err = _get_json(f"{_RELAY_BASE}/latest-liveclient", token)
    if body is None:
        raise Refused(f"relay read failed: {err}")
    return read_snapshot(body, now=time.time())


def _load_json(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        raise Refused(f"cannot read {path}: {type(exc).__name__}") from exc


def _snapshot_arg(path: Optional[str]) -> tuple[dict, str]:
    if path:
        return read_snapshot(_load_json(path)), SOURCE_FILE
    return _fetch_live(), SOURCE_RELAY


def _parse_pair(text: str) -> tuple[dict, float]:
    path, sep, value = text.rpartition("=")
    if not sep or not path:
        raise Refused(f"expected FILE=OBSERVED, got {text!r}")
    try:
        observed = float(value)
    except ValueError as exc:
        raise Refused(f"observed is not a number in {text!r}") from exc
    return check_record(_load_json(path)), observed


def _write_new(path: str, text: str) -> None:
    """Create ``path`` or refuse. Never a polled file: a torn one fails check_record."""
    try:
        with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text + "\n")
    except FileExistsError as exc:
        raise Refused(f"will not overwrite an earlier lock: {path}") from exc
    except (OSError, ValueError) as exc:
        raise Refused(f"cannot create {path}: {type(exc).__name__}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="G2-40 ratio-block spot sampler (read-only)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("census")
    p_plan = sub.add_parser("plan")
    p_plan.add_argument("--champion")
    p_plan.add_argument("--snapshot")
    p_cap = sub.add_parser("capture")
    p_cap.add_argument("--key", required=True, choices=KEYS)
    p_cap.add_argument("--block", required=True)
    p_cap.add_argument("--form", type=int, default=0)
    p_cap.add_argument("--target-armor", type=float, required=True)
    p_cap.add_argument("--target-mr", type=float, required=True)
    p_cap.add_argument("--target-max-hp", type=float, required=True)
    p_cap.add_argument("--snapshot")
    p_cap.add_argument("--out")
    p_grade = sub.add_parser("grade")
    p_grade.add_argument("pairs", nargs="+", metavar="FILE=OBSERVED")
    return parser


def run(args: argparse.Namespace) -> int:
    if args.cmd == "grade":
        samples = [_parse_pair(p) for p in args.pairs]
        abilities, data, sidecar = load_data()
        for rec, _observed in samples:
            verify_record(rec, abilities, data, sidecar)
        result = grade(samples)
        print(json.dumps(result, indent=2))
        return 0 if result["verdict"] == "SAMPLE_OK" else 3
    abilities, data, sidecar = load_data()
    if args.cmd == "census":
        print(json.dumps(census(abilities, sidecar), indent=2))
    elif args.cmd == "plan":
        champion = args.champion or active_champion(_snapshot_arg(args.snapshot)[0])
        print(json.dumps(plan(abilities, sidecar, champion), indent=2))
    else:
        snapshot, source = _snapshot_arg(args.snapshot)
        record = capture(
            abilities, data, sidecar, snapshot, key=args.key, block_name=args.block,
            form_index=args.form, target_armor=args.target_armor,
            target_mr=args.target_mr, target_max_hp=args.target_max_hp,
            source=source, captured_at=time.time())
        text = json.dumps(record, indent=2)
        if args.out:
            _write_new(args.out, text)
        print(text)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (ValueError, KeyError, TypeError, OSError, OverflowError, RecursionError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
