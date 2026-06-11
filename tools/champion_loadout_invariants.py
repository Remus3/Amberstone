"""tools/champion_loadout_invariants.py

Item s8 (2026-06-10) - shared invariants for the champion-loadout data
pipeline. Single source for two operator-set rules that every producer
(tools/champion_loadout_autogen.py, tools/champion_loadout_align.py,
tools/champion_loadout_cleanup_pollution_item213.py, the item-s8 sweep)
and the guard test (tests/test_loadout_sweep_guard_item_s8.py) must
agree on:

1. LENGTH RULE (operator directive, verbatim intent): "it should always
   be 7 items in the builds for SR and 6 items in the builds for aram &
   arena". The canonical count lives in the build_paths[].items display
   name lists of data/champion_loadouts.json (the variant-level items
   field mirrors the primary path); item_ids are derived at serve time
   by coaches.loadout_resolver._resolve_item_ids. SR's 7 = 6 legendaries
   + boots at index 1; ARAM's 6 = 5 legendaries + boots at index 1;
   Arena's 6 = 6 legendaries, no boots (Arena has no shop boots).

2. AXIS RULES - per-archetype off-class pollution, driven by item CLASS
   facts read from data/daemon_slayer/<patch>/items.json (stats + tags +
   the "Heal and Shield Power" description stat), never by hand item
   lists where avoidable. A row is STRIPPED only when the off-class call
   is unambiguous; ambiguous candidates are REPORTED untouched, because
   the variant-key token mapping ("poke"/"burst" -> mage) routinely
   labels coherent AD builds as "mage" (Ashe lethal-poke, Riven burst) -
   stripping those would destroy legitimate builds.

Calibrated against the live data 2026-06-10:
  - carry axis: the item-208 range gate (>= 350) over the now-5-item
    CARRY_RANGED_OFFCLASS_ITEM_NAMES set (Divine Sunderer joined the
    original four - 7 arena rows: Jhin / Jinx / Nami / Seraphine /
    Twisted Fate / Ziggs / Zilean).
  - mage/enchanter axis: pure marksman-class offense (any crit chance,
    or flat AD with no AP and no HP) is stripped only from AP-MAJORITY
    rows (>= 2 pure-AP items and strictly more pure-AP than pure-AD
    items) - that is what separates Miss Fortune's real AP row carrying
    a stray Lord Dominik's from Ashe's mislabeled lethality row.
    Marksman-tagged champions are exempt on ENCHANTER rows (fasting
    Senna legitimately mixes heal-shield + crit).
  - tank axis: crit-chance items with no HP/armor/MR (Arena's Force Of
    Entropy is crit + 900 HP by design and stays).
  - assassin axis: heal/shield-power items (fact = the "Heal and Shield
    Power" stat line) never belong on assassin rows.
  - enchanter axis: pure stat-stick tank items (HP/armor/MR with no AP,
    no AD, no heal-shield power, no Aura/Active utility) never belong on
    enchanter rows - Knight's Vow / Locket carry Aura+Active and are
    exempt by fact, not by name.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

_ROOT = Path(__file__).resolve().parent.parent
_DS_DATA_DIR = _ROOT / "data" / "daemon_slayer"

# Operator-set per-mode build length (see module docstring for why SR
# differs). Producers enforce this at generation time; the sweep + guard
# enforce it on the data at rest.
TARGET_LEN: dict[str, int] = {"sr": 7, "aram": 6, "arena": 6}

_AXES = ("carry", "tank", "bruiser", "mage", "assassin", "enchanter")


class ItemFacts(NamedTuple):
    ad: bool
    ap: bool
    crit: bool
    onhit: bool
    heal_shield: bool
    hp: bool
    armor: bool
    mr: bool
    aura: bool
    active: bool
    boots: bool
    mana: bool


class Violation(NamedTuple):
    item: str
    axis: str
    action: str  # "strip" | "report"
    reason: str


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _current_patch() -> str:
    try:
        return (_DS_DATA_DIR / "current.txt").read_text(
            encoding="utf-8"
        ).strip() or "16.12.1"
    except OSError:
        return "16.12.1"


_facts_cache: dict | None = None
_marksman_cache: set | None = None


def load_item_facts() -> dict[str, ItemFacts]:
    """Normalized item name -> class facts, OR-merged across every id
    sharing the name (the 22/44-prefixed arena aliases carry the same
    identity with arena-tuned stats)."""
    global _facts_cache
    if _facts_cache is not None:
        return _facts_cache
    raw = json.loads(
        (_DS_DATA_DIR / _current_patch() / "items.json").read_text(
            encoding="utf-8"
        )
    ).get("data") or {}
    acc: dict[str, dict] = {}
    for _iid, it in raw.items():
        n = _norm(it.get("name", ""))
        if not n:
            continue
        st = it.get("stats") or {}
        tg = set(it.get("tags") or [])
        f = acc.setdefault(n, {k: False for k in ItemFacts._fields})
        f["ad"] |= st.get("FlatPhysicalDamageMod", 0) > 0
        f["ap"] |= st.get("FlatMagicDamageMod", 0) > 0
        f["crit"] |= st.get("FlatCritChanceMod", 0) > 0
        f["onhit"] |= "OnHit" in tg
        f["heal_shield"] |= (
            "Heal and Shield Power" in (it.get("description") or "")
        )
        f["hp"] |= st.get("FlatHPPoolMod", 0) > 0
        f["armor"] |= st.get("FlatArmorMod", 0) > 0
        f["mr"] |= st.get("FlatSpellBlockMod", 0) > 0
        f["aura"] |= "Aura" in tg
        f["active"] |= "Active" in tg
        f["boots"] |= "Boots" in tg
        f["mana"] |= st.get("FlatMPPoolMod", 0) > 0
    _facts_cache = {n: ItemFacts(**f) for n, f in acc.items()}
    return _facts_cache


def marksman_champions() -> set[str]:
    """Normalized champion keys (DDragon id + display name) carrying the
    DDragon Marksman tag - the fact behind the enchanter-row exemption."""
    global _marksman_cache
    if _marksman_cache is not None:
        return _marksman_cache
    raw = json.loads(
        (_DS_DATA_DIR / _current_patch() / "champions.json").read_text(
            encoding="utf-8"
        )
    ).get("data") or {}
    out: set[str] = set()
    for cid, rec in raw.items():
        if "Marksman" in (rec.get("tags") or []):
            out.add(_norm(cid))
            nm = rec.get("name")
            if nm:
                out.add(_norm(str(nm)))
    _marksman_cache = out
    return _marksman_cache


def _is_pure_marksman_offense(f: ItemFacts) -> bool:
    # Crit chance is THE marksman-only stat; flat AD with neither AP nor
    # HP covers the lethality/BT class without touching hybrid (Gunblade)
    # or utility-stat items (Innervating Locket, Edge of Night carry HP).
    # Mana-pool batteries (Manamune/Muramana) are champion-kit items
    # (AP Ezreal still wants Tear) - downgraded to the report path by
    # exclusion here. Boots never participate in axis rules.
    if f.boots:
        return False
    return f.crit or (f.ad and not f.ap and not f.hp and not f.mana)


def _is_tank_stat_stick(f: ItemFacts) -> bool:
    # Boots are exempt by fact - Mercury's Treads (MR + tenacity) is the
    # archetype-DEFAULT boots for enchanters, not a tank stat stick.
    if f.boots:
        return False
    return (
        (f.hp or f.armor or f.mr)
        and not f.ad and not f.ap and not f.heal_shield
        and not f.aura and not f.active
    )


def classify_row(
    champion: str,
    mode: str,
    archetype: str,
    items: list[str],
    *,
    attackrange: float,
    pinned: bool = False,
) -> list[Violation]:
    """Return the axis-rule violations for one row. ``action`` says what
    the sweep does: "strip" only where the call is unambiguous, "report"
    where a human should look (mislabeled-key rows stay untouched).
    Operator-pinned rows always downgrade to report."""
    from core.daemon_slayer_client import (
        CARRY_RANGED_ATTACKRANGE_FLOOR,
        CARRY_RANGED_OFFCLASS_ITEM_NAMES,
    )
    facts = load_item_facts()
    out: list[Violation] = []
    arch = (archetype or "").strip().lower()
    if arch not in _AXES:
        return out

    # Row identity for the mage/enchanter axis: pure-AP core vs pure-AD
    # core. Hybrids (AD+AP) and heal-shield items count for neither side
    # of the majority test.
    ap_core = sum(
        1 for it in items
        if (f := facts.get(_norm(it))) and f.ap and not f.ad
    )
    ad_core = sum(
        1 for it in items
        if (f := facts.get(_norm(it))) and f.ad and not f.ap
    )
    ap_majority = ap_core >= 2 and ap_core > ad_core
    is_mm = _norm(champion) in marksman_champions()

    for it in items:
        f = facts.get(_norm(it))
        if arch == "carry":
            if (
                it in CARRY_RANGED_OFFCLASS_ITEM_NAMES
                and attackrange >= CARRY_RANGED_ATTACKRANGE_FLOOR
            ):
                out.append(Violation(
                    it, "carry",
                    "report" if pinned else "strip",
                    "melee/tank item on ranged carry row (item-208 set)",
                ))
            continue
        if f is None:
            continue
        if arch in ("mage", "enchanter"):
            if _is_pure_marksman_offense(f):
                if pinned or (arch == "enchanter" and is_mm):
                    out.append(Violation(
                        it, arch, "report",
                        "marksman-class item (pinned/Marksman-tag exempt)",
                    ))
                elif ap_majority:
                    out.append(Violation(
                        it, arch, "strip",
                        "marksman-class item on AP-majority row",
                    ))
                else:
                    out.append(Violation(
                        it, arch, "report",
                        "marksman-class item on non-AP-majority row "
                        "(likely mislabeled key, not pollution)",
                    ))
            if arch == "enchanter" and _is_tank_stat_stick(f):
                out.append(Violation(
                    it, "enchanter",
                    "report" if pinned else "strip",
                    "stat-stick tank item with no support utility",
                ))
        elif arch == "tank":
            if f.crit and not (f.hp or f.armor or f.mr):
                out.append(Violation(
                    it, "tank",
                    "report" if pinned else "strip",
                    "pure-offense crit item on tank row",
                ))
        elif arch == "assassin":
            if f.heal_shield:
                out.append(Violation(
                    it, "assassin",
                    "report" if pinned else "strip",
                    "heal/shield-power item on assassin row",
                ))
        elif arch == "bruiser":
            if f.heal_shield:
                # Not in the operator's minimum rule set - report only.
                out.append(Violation(
                    it, "bruiser", "report",
                    "heal/shield-power item on bruiser row",
                ))
    return out
