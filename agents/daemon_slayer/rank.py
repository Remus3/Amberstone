"""Phase 2 step 3 - item ranker.

Score every purchasable, mode-legal item in the snapshot by the DPS it
would add to a champion's current build. Filter via ``maps`` (mode
validity), ``gold.total`` (must be a real purchase), and ``into`` (skip
non-terminal components by default - ranking Long Sword above Bloodthirster
is rarely useful). Sort by absolute ``delta_dps`` (default) or by
``dps_per_gold``.

This is pure Python on top of ``compute_dps`` - NxDPS where N is the
filtered candidate count (~125-175 in 16.9.1 for the common modes).
Sub-second on a warm snapshot. No conditional effects (passives,
on-hit) - those live in Phase 4 alongside ability damage.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from ._burst_off_axis import champion_burst_axis, is_off_axis_candidate
from ._melee_ranged import (
    MELEE_RANGED_ATTACKRANGE_SPLIT,
    attackrange_is_ranged,
)
from .data_loader import DataSnapshot
from .dps import _select_phase, compute_dps
from .effects import ITEM_EFFECTS
from .kit_axis_credit import kit_axis_item_ids, kit_axis_item_names
from .kit_conversion import conversion_factor, damage_objective, kit_conversion
from .stats import clamp_level

# Mode -> DDragon map id. Items whose ``maps[map_id]`` is False are unbuyable
# in that mode (e.g. ARAM bans non-completed components like Phage). Modes
# without a wired map id pass through with no validity filter.
#
# BRAWL is DDragon map 35. coaches/brawl_coach.py._ds_engine_mode("BRAWL")
# returns the literal "BRAWL" (URF/NexusBlitz/etc ride the SR identity;
# only true Brawl is map 35 - see tests/test_cross_mode_ds_p1l6.py
# CrossModeBrawlRoutingTests), so rank_items genuinely receives
# mode="BRAWL" for real Brawl games. Without this entry _is_legal_in_mode
# was a silent no-op for the entire mode, admitting ~281 map-35-illegal
# items (Doran's, jungle companions, the 22-prefixed Arena-mirror set)
# into Brawl recommendations (audit P1-L23).
MODE_MAP_ID: dict[str, str] = {
    "SR": "11",
    "ARAM": "12",
    "ARENA": "30",
    "BRAWL": "35",
}

DEFAULT_SLOT_COUNT = 6
DEFAULT_TOP_N = 20
SORT_KEYS: tuple[str, ...] = ("delta", "efficiency")

# Arena gives every player Arcane Sweeper as a trinket - it occupies the
# trinket slot, not an item slot, but the live game's inventory polling
# returns it alongside the 6 build slots. Strip these from current_item_ids
# when mode=ARENA so the slot-count check passes and the baseline DPS
# isn't padded with a zero-stat record. The candidate pool already
# excludes them via _is_purchasable (gold.purchasable=False).
ARENA_TRINKET_IDS: frozenset[str] = frozenset({"3348"})

# Ranged-marksman off-class item pollution filter (item 213, 2026-05-28).
#
# The DPS scorer ranks every purchasable, mode-legal item by raw DPS delta.
# That surfaces melee-bruiser / tank / skirmisher items (Trinity Force,
# Heartsteel, Bastionbreaker, Umbral Glaive, ...) high for a ranged marksman
# because they add big raw AD / AS / Health stats - items the operator never
# plays on a Caitlyn / Jinx / Ezreal class ADC. The candidate pool is
# class-agnostic by design; this is a CONSUMER-side filter that fires only
# for ranged marksmen routed through the DPS scorer (the carry / dps / adc
# axis). Mages route through the mage scorer (untouched); melee fighters /
# tanks are NOT ranged marksmen so the gate never fires for them.
#
# Data-driven, NOT per-champion: the gate is the snapshot's own champion
# record (Marksman tag + attackrange >= RANGED_MARKSMAN_RANGE_FLOOR). The
# deny-set is by NAME - alias-proof (the Arena 22/32/44/66-prefixed mirror
# IDs all share the canonical name) and patch-stable (names drift far less
# than ids). Bruiser-skirmisher + tank-frontline + AP-bruiser items that a
# ranged ADC should never build as a core item. ADC on-hit / crit / lethality
# completes (BorK, IE, LDR, Yun Tal, Runaan's, Kraken, Wit's End, Eclipse,
# Opportunity, Serylda's, Edge of Night, Profane Hydra) are NOT in this set.
RANGED_MARKSMAN_RANGE_FLOOR: int = 500

OFFCLASS_MARKSMAN_ITEM_NAMES: frozenset[str] = frozenset({
    # Sheen / bruiser-skirmisher mythic-class
    "Trinity Force",
    "Sundered Sky",
    "Divine Sunderer",
    "Iceborn Gauntlet",
    "Stridebreaker",
    "Goredrinker",
    # Bruiser / fighter cores
    "Black Cleaver",
    "Sterak's Gage",
    "Bastionbreaker",
    "Hullbreaker",
    "Experimental Hexplate",
    "Spear of Shojin",
    "Maw of Malmortius",
    "Hexdrinker",
    "Overlord's Bloodmail",
    # Health-stacking bruiser / tank-skirmisher
    "Heartsteel",
    "Titanic Hydra",
    "Ravenous Hydra",
    "Warmog's Armor",
    # Bruiser hydras / support lethality tool (ward-clear, not ADC core)
    "Profane Hydra",
    "Umbral Glaive",
    # Tank-frontline armor / MR (a ranged ADC never builds these as DPS)
    "Sunfire Aegis",
    "Hollow Radiance",
    "Dead Man's Plate",
    "Frozen Heart",
    "Thornmail",
    "Randuin's Omen",
    "Jak'Sho, The Protean",
    "Force of Nature",
    "Abyssal Mask",
    "Spirit Visage",
    "Kaenic Rookern",
    "Unending Despair",
    "Winter's Approach",
    "Fimbulwinter",
    # AP-bruiser / mage-bruiser (off-class for an AD marksman scorer)
    "Riftmaker",
    "Cosmic Drive",
})


# RM-04 A-01 (2026-07-24) - CARRY CANDIDATE-POOL WIDEN set (DEFAULT-OFF seam).
#
# MEASURED premise, in-process + live :8893 at ENGINE 1.241.0 / patch 16.14.1:
# the SR carry pool is 108 items (the ROADMAP filing's "111" does not
# reproduce) and is SET-IDENTICAL across Caitlyn / Jinx / Ashe / Sivir /
# Senna / Smolder / Ezreal, because the deny above is class-wide by NAME with
# no per-champion axis. Verified BY ID, not by name (the Arena mirrors 223071
# / 223161 / 226631 / 223053 share the display names and are maps["11"]=False,
# so they never reach SR anyway):
#   3071 Black Cleaver   - denied by name
#   3161 Spear of Shojin - denied by name
#   6631 Stridebreaker   - denied by name
#   3053 Sterak's Gage   - denied by name
#   3877 Bloodsong       - denied by _SR_EXCLUDED_ITEM_IDS (RM-93 support
#                          quest), a DIFFERENT mechanism, NOT widened here
#   6692 Eclipse         - admitted at the default (control)
#
# This set is the smallest defensible widen: exactly the four ROADMAP-named
# items that the off-class NAME deny actually strips. It is deliberately
# NARROWER than the full deny-set (Heartsteel / Thornmail / Warmog's stay
# stripped - a ranged ADC does not build tank frontline as a DPS slot) and
# BROADER than the pre-existing DSP2 ``exempt_offclass_by_win`` table, which
# is per-champion (only Corki / Ezreal / Senna / Smolder) and carries no
# Stridebreaker or Sterak's Gage entry for anyone.
#
# Consumed ONLY by ``rank_items(widen_carry_pool=True)``. Default False is a
# byte-identical no-op (pinned by tests/test_rank_carry_pool_widen_rm04.py).
CARRY_POOL_WIDEN_ITEM_NAMES: frozenset[str] = frozenset({
    "Black Cleaver",     # 3071 - armor shred, Senna/Smolder empirical core
    "Spear of Shojin",   # 3161 - ability-haste caster-marksman core
    "Stridebreaker",     # 6631 - AD/HP + slow, no exemption-table entry
    "Sterak's Gage",     # 3053 - AD/HP lifeline, no exemption-table entry
})


# Non-coachable joke / meme / anvil items that DDragon mis-flags as buyable
# on real maps (e.g. Golden Spatula carries maps['12']=True for ARAM with a
# full all-stats block, so the DPS scorer ranked it #2 for a live ARAM Varus).
# Item 213 stripped these from the curated champion_loadouts.json but the live
# rank pool reads the DDragon maps flag directly, so they leaked back into
# daemon_slayer_picks. Deny by stable item id (unconditional, every mode +
# every scorer) - these are never a real recommendation in any mode.
#
# SIBLING-COMPLETE since RM-04 A-27b (2026-07-24). Item 213 / item 243 denied
# ONE id per family - the id it happened to see in a live ARAM game - and the
# identical pollution then recurred one map over. DDragon 16.14.1 ships FOUR
# Golden Spatula rows and TWO Talisman of Ascension rows in separate map-mirror
# id namespaces; the pre-A-27b deny caught exactly one of each, so the Arena
# twins 224403 + 443064 stayed reachable (MEASURED: 224403 sits at slot index 2
# of ad_heavy / ap_heavy / balanced for 82 of 173 champions in
# build_orders_arena.json - 246 branch instances; SR + ARAM carry it zero
# times). Full sweep, by id + maps + purchasable, all six rows:
#   994403 Golden Spatula                 maps 12  2500g purchasable  DENIED
#   224403 The Golden Spatula             maps 30  2500g purchasable  DENIED (new)
#     4403 The Golden Spatula             maps 21  7187g purchasable  DENIED (new)
#   664403 The Golden Spatula             maps 11  2500g NOT purchasable
#   663064 Veigar's Talisman of Ascension maps 11   900g purchasable  DENIED
#   443064 Talisman Of Ascension          maps 30  2750g purchasable  DENIED (new)
# 664403 needs no entry: purchasable=False already self-excludes it, and
# tests/test_non_coachable_arena_spatula_a27b.py fails loudly if a patch
# re-extract ever flips that flag.
#
# Meraki rank is NOT a usable pollution test here: 224403 reads ["DISTRIBUTED"],
# but so does the entire legitimate Arena prismatic pool (Galeforce 446671,
# Darksteel Talons 443054, ...). Deny stays by stable item id.
_NON_COACHABLE_ITEM_IDS: frozenset[str] = frozenset({
    "994403",  # Golden Spatula - Arena anvil/joke (all 13 stats); maps['12']=True
    "224403",  # The Golden Spatula - Arena twin; maps['30']=True, 2500g, buyable
    "4403",    # The Golden Spatula - Nexus Blitz twin; maps['21']=True, 7187g
    "663064",  # Veigar's Talisman of Ascension - "no stats, 100% XP" meme item
    "443064",  # Talisman Of Ascension - Arena twin; maps['30']=True, 2750g, statless
})


# Deny set for items that are SR-LEGAL but are NOT free-slot shop purchases, so a
# "which item should I buy for this slot" ranking must never surface them. Two
# classes of items live here, and both are QUEST-REWARD classes:
#
# 1. World Atlas support-quest line (3865 + the five Bounty of Worlds upgrades).
#    NOTE (RM-93, 2026-07-18): the original comment here claimed these were
#    "ARAM-only ... maps[11]=True upstream bug". That was WRONG - DDragon carries
#    maps["11"]=True AND maps["12"]=False for all eight line items, i.e. the data
#    correctly says SR-legal / ARAM-illegal (the World Atlas support quest is a
#    Summoner's Rift system; Howling Abyss has no support quest). The real reason
#    to deny them is the one already pinned for the enchanter pool in
#    tests/test_enchanter_pool_hsp_rm90.py:31-36: they are 400g MUTUALLY EXCLUSIVE
#    quest-progression upgrades (you pick exactly one when Bounty of Worlds 3867
#    completes), so ranking them against 3000g legendaries is a category error.
#    Admitting them was MEASURED to put Bloodsong at rank #2 for Vel'Koz and #3
#    for Jinx - an RM-92 (non-output item) mispricing, not a real recommendation.
# 2. SR role-quest T3 boot upgrades (3170-3175) - DDragon marks ``purchasable=true``
#    but in-game these are quest-reward upgrades of the champion's existing T2 boots
#    (Mid lane: "Upgrade boots to tier 3"; Bot lane: "A bonus item slot for your
#    boots"). You can never buy them directly from the shop - the quest completes
#    and auto-upgrades your equipped boots. Recommending them as regular purchase
#    candidates is a dead end (operator 2026-07-08: Gunmetal Greaves #1 meta build
#    for Aphelios Bottom, unobtainable via shop).
#
# Deny unconditionally on SR (every scorer), like the non-coachable + Ornn-
# masterwork gates. Modes other than SR use the DDragon maps flag directly (no-op
# there).
_SR_EXCLUDED_ITEM_IDS: frozenset[str] = frozenset({
    # ---- World Atlas support-quest line (SR-legal, quest reward not free slot) ----
    # SIBLING-COMPLETE (RM-93): the starter + ALL FIVE 3867 "into" upgrades. Denying
    # a strict subset (the pre-RM-93 state denied only 3871 + 3877) let the other
    # three rank as a contiguous bottom block on every SR route.
    "3865",  # World Atlas - support quest starter (400g, auto-upgrades)
    "3869",  # Celestial Opposition - Bounty of Worlds upgrade choice
    "3870",  # Dream Maker - Bounty of Worlds upgrade choice
    "3871",  # Zaz'Zak's Realmspike - Bounty of Worlds upgrade choice
    "3876",  # Solstice Sleigh - Bounty of Worlds upgrade choice
    "3877",  # Bloodsong - Bounty of Worlds upgrade choice
    # ---- SR role-quest T3 boot upgrades (purchasable=true upstream bug) ----
    "3170",  # Swiftmarch - T3 Boots of Swiftness (quest reward, not direct-buy)
    "3171",  # Crimson Lucidity - T3 Ionian Boots (quest reward, not direct-buy)
    "3172",  # Gunmetal Greaves - T3 Berserker's (quest reward, not direct-buy)
    "3173",  # Chainlaced Crushers - T3 Mercury's Treads (quest reward)
    "3174",  # Armored Advance - T3 Plated Steelcaps (quest reward)
    "3175",  # Spellslinger's Shoes - T3 Sorcerer's Shoes (quest reward)
})

# DDragon-override deny set for items the DDragon ``maps["12"]=True`` flag wrongly
# admits onto Howling Abyss (upstream mislabel). These are Arena-only prismatic
# mega-items (6000g, 223xxx mirror namespace) - deny unconditionally on ARAM
# (every scorer), like the SR-exclude + Ornn-masterwork gates. Modes other than
# ARAM use the DDragon maps flag directly (no-op there).
_ARAM_EXCLUDED_ITEM_IDS: frozenset[str] = frozenset({
    "223069",  # Void Immolation - Arena prismatic mega-item (6000g, map 30)
})


# Ranged-ONLY item purchasability gate (2026-07-02, patch 16.13.1).
#
# A live practice-SR drain surfaced Runaan's Hurricane (3085) ranked #1 in the
# DPS scorer for Irelia, a MELEE champ. Runaan's carries "Can only be purchased
# on ranged champions" (wiki.leagueoflegends.com, verified 2026-07-02) - the
# in-game shop hard-BLOCKS the purchase for melee - so recommending it is a
# recommendation the champ literally cannot buy. The candidate pool
# (_filter_candidates) had no gate for this class of shop restriction.
#
# This is a PURCHASABILITY gate (the game shop rule), DISTINCT from:
#   * _is_ranged_marksman (below) - a MARKSMAN off-class deny (Trinity /
#     Heartsteel stripped from a crit ADC), a different axis that fires only
#     for ranged marksmen through the DPS scorer.
#   * dps.apply_melee_aa_gate (default-OFF) - zeroes only the Runaan BOLT DPS
#     contribution on a melee wielder, never excludes it from the pool.
#
# DATA GAP: DDragon item.json carries NO structured ranged-only flag - not in
# ``tags`` (NonbootsMovement is shared with melee-buyable Navori Flickerblade),
# ``maps``, ``effect``, ``stats``, or a ``requiredChampion`` field (absent). The
# only textual signal is the ``plaintext`` prose "Ranged attacks fire two bolts"
# on the canonical id 3085 (EMPTY on the Arena-mirror alias 223085), and prose-
# scraping false-positives on Tiamat / Ravenous Hydra ("Melee attacks hit...")
# which ARE melee-buyable. So this is the smallest defensible EXPLICIT id set,
# anchored on wiki ground truth, alias-inclusive (3085 canonical + 223085 Arena
# mirror - the same alias-proof doctrine as OFFCLASS_MARKSMAN_ITEM_NAMES).
#
# Runaan's is the ONLY purchase-restricted crit / attack-speed item at 16.13.1;
# the wiki confirms Rapid Firecannon (3094) and Statikk Shiv (3087) are NOT
# restricted ("Limited to 1" only), so they are deliberately EXCLUDED from the
# deny set (a narrow-but-correct set - a wider guess would wrongly strip items
# melee genuinely builds). Add to this set only on wiki-verified evidence for a
# future patch.
RANGED_ONLY_ITEM_IDS: frozenset[str] = frozenset({
    "3085",     # Runaan's Hurricane - canonical (SR / ARAM / Brawl)
    "223085",   # Runaan's Hurricane - Arena-mirror alias (map 30)
})

# Melee/ranged purchasability split. A champion is MELEE (and therefore blocked
# from the ranged-only items above) when its base attackrange is BELOW the shared
# canonical split (``_melee_ranged.MELEE_RANGED_ATTACKRANGE_SPLIT`` = 350). RM-123
# (2026-07-29) raised this from 250 -> 350: the old 250 value wrongly classified
# Rakan (300) and Lillia (325) - both MELEE, both shop-blocked from Runaan's - as
# ranged and offered them ranged-only items. 350 still classifies Graves (425) /
# Kindred (500) as ranged marksmen (shop lets them buy Runaan's) while correctly
# blocking Rakan/Lillia. Urgot (350) is ranged (>= split). Melee at 16.14.1:
# Irelia 200, Yasuo/Yone/Kayle 175, Jax/Camille 125, Rakan 300, Lillia 325.
MELEE_ATTACKRANGE_CEILING: float = MELEE_RANGED_ATTACKRANGE_SPLIT


def _is_ranged_marksman(champ_rec: dict) -> bool:
    """True iff this champion is a ranged marksman - the only class for
    which the off-class item deny-set fires through the DPS scorer.

    Data-driven gate: ``Marksman`` in tags AND attackrange at or above the
    ranged floor. Melee fighters / tanks (175 range) and ranged mages (no
    Marksman tag, and they route through the mage scorer anyway) are excluded.
    """
    if not isinstance(champ_rec, dict):
        return False
    tags = champ_rec.get("tags") or ()
    if "Marksman" not in tags:
        return False
    rng = (champ_rec.get("stats") or {}).get("attackrange", 0) or 0
    try:
        return float(rng) >= RANGED_MARKSMAN_RANGE_FLOOR
    except (TypeError, ValueError):
        return False


# Arena/Cherry augments that CONVERT the wielder to melee - after which the
# ranged-only items in ``RANGED_ONLY_ITEM_IDS`` are non-functional (Runaan's
# bonus bolts do nothing in melee form), so a converted ranged champ must be
# gated exactly like a base-melee one. The base-range gate keys only on the
# champion's BASE attackrange and is otherwise augment-blind. Keyed by BOTH
# apiName (stable) and numeric id (16.13.1 ``arena_augments.json``) so every
# caller form - ``134`` / ``"134"`` / ``"DrawYourSword"`` / the record dict -
# resolves without a snapshot lookup. Add to these sets only on wiki/data-
# verified evidence for a future patch (mirrors ``RANGED_ONLY_ITEM_IDS``).
_MELEE_CONVERSION_AUGMENT_APINAMES: frozenset[str] = frozenset({
    "DrawYourSword",  # id 134 (rarity 2, arena_augments.json): "You are now melee."
})
_MELEE_CONVERSION_AUGMENT_IDS: frozenset[int] = frozenset({134})


def _augment_forces_melee(augments: Optional[Iterable]) -> bool:
    """True iff any active Arena/Cherry augment converts the wielder to melee.

    Accepts the same heterogeneous augment-list shapes the ranker threads
    (``Augment`` instances, cdragon record dicts, or id/apiName ``int``|``str``
    refs) and matches them against the id + apiName conversion sets - no
    snapshot lookup needed (both forms of the sole entry are registered).
    ``None`` / empty -> False, so a non-Arena (SR/ARAM) call is a byte-identical
    no-op and a non-conversion augment never forces melee (no over-filter of a
    real ranged carry's ranged-only pool).
    """
    if not augments:
        return False
    for entry in augments:
        if isinstance(entry, bool):
            continue
        if isinstance(entry, int):
            if entry in _MELEE_CONVERSION_AUGMENT_IDS:
                return True
            continue
        if isinstance(entry, str):
            if entry in _MELEE_CONVERSION_AUGMENT_APINAMES:
                return True
            if entry.isdigit() and int(entry) in _MELEE_CONVERSION_AUGMENT_IDS:
                return True
            continue
        if isinstance(entry, dict):
            if str(entry.get("apiName") or "") in _MELEE_CONVERSION_AUGMENT_APINAMES:
                return True
            try:
                if int(entry.get("id")) in _MELEE_CONVERSION_AUGMENT_IDS:
                    return True
            except (TypeError, ValueError):
                pass
            continue
        api = getattr(entry, "api_name", None)
        if api is not None and str(api) in _MELEE_CONVERSION_AUGMENT_APINAMES:
            return True
    return False


def _champion_is_melee(
    champ_rec: Optional[dict], augments: Optional[Iterable] = None
) -> bool:
    """True iff this champion is MELEE - blocked by the in-game shop from the
    ranged-only items in ``RANGED_ONLY_ITEM_IDS``.

    Data-driven: base attackrange BELOW the shared canonical split
    (350, ``ehp._is_ranged`` - see ``_melee_ranged``). An unknown / malformed
    record fails CLOSED to False (treated as ranged), so a missing champ record
    never over-filters a real ranged carry's pool; the live bug (a known melee
    champ, real record) is still caught.

    ALSO melee when an active Arena/Cherry augment converts the wielder to melee
    (``_augment_forces_melee``; currently only "Draw Your Sword" / id 134). The
    ``augments`` argument defaults ``None`` so every SR/ARAM + base-melee caller
    is byte-identical; the conversion check is evaluated FIRST so it holds even
    if the base champ record is missing/malformed.
    """
    if _augment_forces_melee(augments):
        return True
    if not isinstance(champ_rec, dict):
        return False
    rng = (champ_rec.get("stats") or {}).get("attackrange", 0) or 0
    return not attackrange_is_ranged(rng)


# DSP2 Cluster-B off-class WIN-exemption seam (DEFAULT-OFF, 2026-06-17).
#
# The OFFCLASS_MARKSMAN_ITEM_NAMES deny-set strips Sheen-line / on-hit-caster
# items (Trinity Force, Spear of Shojin, Black Cleaver) from EVERY ranged
# marksman - correct for a pure crit ADC (Caitlyn / Jinx / Sivir) but WRONG for
# an ability / Sheen caster-marksman (Ezreal, Corki, Smolder, Senna) whose
# actual winning build IS those items. The DSP1 WIN-anchor surfaced Ezreal SR
# -39 (the worst outcome-divergent champ-mode) precisely because Trinity Force,
# his most-built item (ARAM n=219), was hard excluded from the candidate pool.
#
# There is no clean kit-data axis for "wants Sheen" (lolmath.damage_distribution
# is AD/AP only - it cannot separate Ezreal's ability-physical damage from
# Caitlyn's auto-physical), so the exemption is anchored on the swarm's ground
# truth: the per-champ rewind WIN+usage data, distilled offline into
# ``marksman_offclass_exempt.json`` by
# ops/audit/ds_perm_swarm/build_marksman_offclass_exempt.py. An off-class item
# is exempted (un-stripped) for a champ when the player base genuinely builds it
# (usage n + a loose win band). The seam is DEFAULT-OFF and byte-identical when
# off (the DSV1-4 precedent); the live default-ON flip is EXCLUDED ->
# docs/LIVE_GAME_GATED_SYNC.md. Fail-soft: a missing / unreadable table yields an
# empty map so the seam is a no-op even when requested.
_OFFCLASS_EXEMPT_PATH = Path(__file__).resolve().parent / "marksman_offclass_exempt.json"
_OFFCLASS_EXEMPT_CACHE: Optional[dict[str, frozenset[str]]] = None


def _load_offclass_exemptions() -> dict[str, frozenset[str]]:
    """champion key (DDragon id / name) -> frozenset of exempt item names.

    Loaded once and cached. Fail-soft to ``{}`` on any read / parse error so the
    seam degrades to a no-op rather than raising.
    """
    global _OFFCLASS_EXEMPT_CACHE
    if _OFFCLASS_EXEMPT_CACHE is not None:
        return _OFFCLASS_EXEMPT_CACHE
    out: dict[str, frozenset[str]] = {}
    try:
        raw = json.loads(_OFFCLASS_EXEMPT_PATH.read_text(encoding="utf-8"))
        for champ, names in (raw.get("champions") or {}).items():
            fs = frozenset(n for n in (names or ()) if isinstance(n, str))
            if fs:
                out[str(champ)] = fs
    except Exception:  # noqa: BLE001 - fail-soft, no exemption on any error
        out = {}
    _OFFCLASS_EXEMPT_CACHE = out
    return out


def _offclass_win_exemptions(
    champion_id: str, champ_rec: Optional[dict]
) -> frozenset[str]:
    """Exempt item names for this champion, by DDragon id then display name."""
    tbl = _load_offclass_exemptions()
    hit = tbl.get(str(champion_id))
    if hit:
        return hit
    name = (champ_rec or {}).get("name") if isinstance(champ_rec, dict) else None
    if name:
        return tbl.get(str(name), frozenset())
    return frozenset()


def strip_arena_trinkets(
    current_ids: tuple[str, ...], mode: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (kept_ids, stripped_ids). No-op outside ARENA.

    ``mode`` matched case-insensitively (item 244): a lowercase ``arena``
    from the route body must still strip the Arcane Sweeper trinket.
    """
    if mode.upper() != "ARENA" or not current_ids:
        return current_ids, ()
    kept: list[str] = []
    stripped: list[str] = []
    for i in current_ids:
        if i in ARENA_TRINKET_IDS:
            stripped.append(i)
        else:
            kept.append(i)
    return tuple(kept), tuple(stripped)


@dataclass(frozen=True)
class RankedItem:
    item_id: str
    item_name: str
    gold: int
    delta_dps: float            # weighted_dps with item - baseline
    new_dps: float              # weighted_dps with item
    dps_per_1k_gold: float      # delta_dps / (gold/1000); 0 when delta<=0
    is_terminal: bool           # `into` is empty - final-tier item
    tags: tuple[str, ...]
    # Phase 6 step 8 (2026-05-12): candidate's unique passive collides with an
    # item already in current_item_ids - the proc/pen contribution would be
    # zeroed by collect_effects() dedup. Stat block still contributes (the
    # delta_dps reflects this honestly) but the operator gets no value from
    # the unique itself. Default-filter is on in ``rank_items``; consumers
    # can opt out via ``filter_shared_uniques=False`` to surface the flag.
    shares_dead_unique: bool = False
    dead_unique_key: str = ""
    # Phase 4(d): candidate's own unique-passive family key, always set
    # (collision-independent) - the positive "locks <family>" signal.
    unique_passive_key: str = ""
    # Fight-length-reweight knob (item 219 C follow-up, 2026-05-30). 0.0 on the
    # default ranking path (``rank_items(fight_length=None)``) so existing
    # consumers + value pins are unaffected; populated only when ``rank_items``
    # is called with a positive ``fight_length`` and the rows are then sorted
    # by this score instead of ``delta_dps``.
    effective_score: float = 0.0
    # 2026-05-30 mana-valuation knob: bounded mana valuation knob. The DPS scorer
    # values flat mana at ~0 (mana is invisible to auto-attack DPS), so early
    # mana items (Tear 240, Lost Chapter 300) rank below burn/AP items for a
    # mana-dependent caster even when the mana sustain is the point. When
    # ``rank_items(mana_value_per_point=...)`` is set, this carries
    # ``delta_dps + mana_value_per_point * mana_gained`` and the rows sort by
    # it. Both default 0.0 -> byte-identical when the knob is unused.
    mana_adjusted_score: float = 0.0
    mana_gained: float = 0.0
    # DSP11 Cluster-B2 kit-axis credit marker (1.135.0). 0.0 on the default path
    # (``prefer_kit_axis_by_win=False``) so the rows + sort stay byte-identical.
    # When the seam is engaged this is 1.0 on a surfaced (positive-delta) WIN-
    # anchored kit-axis item and 0.0 otherwise; the ranking then sorts by it
    # first, floating those items above the generic AD template.
    kit_axis_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "item_name": self.item_name,
            "gold": self.gold,
            "delta_dps": self.delta_dps,
            "new_dps": self.new_dps,
            "dps_per_1k_gold": self.dps_per_1k_gold,
            "is_terminal": self.is_terminal,
            "tags": list(self.tags),
            "shares_dead_unique": self.shares_dead_unique,
            "dead_unique_key": self.dead_unique_key,
            "unique_passive_key": self.unique_passive_key,
            "effective_score": self.effective_score,
            "mana_adjusted_score": self.mana_adjusted_score,
            "mana_gained": self.mana_gained,
            "kit_axis_score": self.kit_axis_score,
        }


@dataclass(frozen=True)
class RankResult:
    champion_id: str
    champion_name: str
    level: int
    mode: str
    current_item_ids: tuple[str, ...]
    baseline_dps: float
    target_armor: float
    target_mr: float
    target_max_hp: float
    target_bonus_hp: float
    phase: str
    budget: Optional[int]
    slot_count: int
    sort_by: str
    candidates_considered: int      # all items in snapshot
    candidates_evaluated: int       # passed filter
    ranked: tuple[RankedItem, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion_id": self.champion_id,
            "champion_name": self.champion_name,
            "level": self.level,
            "mode": self.mode,
            "current_item_ids": list(self.current_item_ids),
            "baseline_dps": self.baseline_dps,
            "target_armor": self.target_armor,
            "target_mr": self.target_mr,
            "target_max_hp": self.target_max_hp,
            "target_bonus_hp": self.target_bonus_hp,
            "phase": self.phase,
            "budget": self.budget,
            "slot_count": self.slot_count,
            "sort_by": self.sort_by,
            "candidates_considered": self.candidates_considered,
            "candidates_evaluated": self.candidates_evaluated,
            "ranked": [r.to_dict() for r in self.ranked],
            "notes": list(self.notes),
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) - lvl {self.level} "
            f"- mode {self.mode} - phase {self.phase}"
        )
        rows = [head, "-" * len(head)]
        if self.current_item_ids:
            rows.append(f"current items: {', '.join(self.current_item_ids)}")
        else:
            rows.append("current items: (none)")
        rows.append(
            f"target: armor={self.target_armor:.0f}  mr={self.target_mr:.0f}"
            f"  max_hp={self.target_max_hp:.0f}  bonus_hp={self.target_bonus_hp:.0f}"
        )
        budget_label = "unlimited" if self.budget is None else f"{self.budget}"
        rows.append(
            f"budget: {budget_label}  slots: {len(self.current_item_ids)}/{self.slot_count}"
            f"  sort: {self.sort_by}"
        )
        rows.append(
            f"baseline_dps: {self.baseline_dps:.2f}   "
            f"considered/evaluated: {self.candidates_considered}/{self.candidates_evaluated}"
        )
        rows.append("")
        rows.append(f"  {'#':>3}  {'id':>6}  {'name':<28}  "
                    f"{'gold':>5}  {'+dps':>7}  {'new':>7}  {'dps/1k':>7}")
        rows.append("  " + "-" * 78)
        for i, r in enumerate(self.ranked, 1):
            rows.append(
                f"  {i:>3}  {r.item_id:>6}  {r.item_name[:28]:<28}  "
                f"{r.gold:>5}  {r.delta_dps:>7.2f}  {r.new_dps:>7.2f}  {r.dps_per_1k_gold:>7.2f}"
            )
        if self.notes:
            rows.append("")
            for n in self.notes:
                rows.append(f"  note: {n}")
        return "\n".join(rows)


def _is_purchasable(item: dict) -> bool:
    gold = item.get("gold") or {}
    return bool(gold.get("purchasable")) and int(gold.get("total", 0) or 0) > 0


def _is_ornn_masterwork(item: dict) -> bool:
    """True for an Ornn 'masterwork' upgrade (Wooglet's Witchcap etc.) - obtainable
    ONLY when an Ornn ally upgrades your legendary, NEVER purchasable from the shop,
    so never a coachable recommendation in any mode. DDragon marks them
    ``gold.purchasable``=True + ``maps['12']``=True (ARAM), so they leaked into the
    pool and a from-scratch optimal build recommended them (operator 2026-07-06:
    Wooglet's surfaced in ARAM). The definitive marker is the ``<ornnBonus>`` stat
    tag in the description - present on every masterwork, absent on every buyable
    item. (The 228xxx id namespace is NOT a safe marker: it also holds Arena
    22-mirror ids - 228001 Anathema's Chains = "22" + 8001, 228009, 228020 - which
    ARE buyable and must stay in the pool.) Patch-proof - a masterwork added in a
    future data refresh auto-excludes."""
    return "<ornnBonus>" in str(item.get("description") or "")


def _is_terminal(item: dict) -> bool:
    """Final-tier item - has no ``into`` upgrade path.

    DDragon represents an empty/missing ``into`` as ``None`` or ``[]``.
    """
    into = item.get("into")
    return not into


def _is_legal_in_mode(item: dict, mode: str) -> bool:
    """Items list per-map availability. If we don't recognise the mode, allow.

    ``mode`` is matched case-insensitively: ``MODE_MAP_ID`` keys are
    uppercase, so a lowercase mode from the ``/rank`` body (``mode=aram``)
    would otherwise miss the lookup and fall through to allow-all -
    silently admitting every map-illegal item (item 243/244 hardening).
    """
    map_id = MODE_MAP_ID.get(mode.upper())
    if map_id is None:
        return True
    maps = item.get("maps") or {}
    return bool(maps.get(map_id))


def _filter_candidates(
    snapshot: DataSnapshot,
    mode: str,
    current_ids: set[str],
    budget: Optional[int],
    include_components: bool,
    only_ids: Optional[set[str]],
    exclude_names: Optional[frozenset[str]] = None,
    inject_ids: Optional[set[str]] = None,
    cost_ceiling: Optional[int] = None,
    champion_is_melee: bool = False,
) -> list[tuple[str, dict]]:
    """Return ``[(item_id, item_record), ...]`` passing all filters.

    Filters applied (in order):
      * already-equipped items skipped (``current_ids``)
      * non-coachable joke/anvil items skipped (``_NON_COACHABLE_ITEM_IDS``)
      * ranged-only items skipped when ``champion_is_melee`` (purchasability)
      * ``only_ids`` whitelist - restrict to caller-selected ids when set
      * ``exclude_names`` deny-set by item NAME (alias-proof off-class filter)
      * purchasable + ``gold.total`` > 0
      * mode validity via ``maps`` (only when mode is known)
      * terminal-only (``into`` empty) unless ``include_components``
      * gold <= ``budget`` when budget is set
      * gold <= ``cost_ceiling`` when cost_ceiling is set (F2 cost-aware top)

    ``inject_ids`` is the RF6 (2026-06-17) force-admit set: an id in this set
    bypasses the ``only_ids`` whitelist, the ``exclude_names`` deny, and the
    ``_is_purchasable`` gate, so a WIN-anchored tabled item the pool would otherwise
    drop can still enter. The motivating case is a non-purchasable mana-line
    transform - Fimbulwinter 3121, the upgrade of Winter's Approach, carries
    ``gold.purchasable``=False, so the ehp pool excludes it and the RF3 float has
    nothing to lift. A forced id STILL respects already-equipped, the non-coachable
    deny, mode-legality, terminal-only, and budget. None / empty (the default) is a
    byte-identical no-op - every pre-RF6 caller is unchanged.

    ``cost_ceiling`` is the F2 (2026-06-18) cost-aware-top seam: when a positive
    int, any candidate whose ``gold.total`` STRICTLY exceeds the ceiling is
    dropped from the pool (even a forced id - the ceiling is a hard surface cap,
    applied uniformly like ``budget``). The motivating artifact is the 6000g
    ARAM/Arena mega-item Void Immolation (223069), which the ``sort_by="delta"``
    absolute-gain ranking floats to RANK 1 across every comp cell on the
    hybrid/bruiser + ehp/tank scorers (ops/audit/ds_cross_eval/TIER2_REPORT.md F2).
    None (the default) is a byte-identical no-op.

    ``champion_is_melee`` (2026-07-02) is the ranged-only PURCHASABILITY gate:
    when True, every id in ``RANGED_ONLY_ITEM_IDS`` (Runaan's Hurricane + its
    Arena alias - items the in-game shop blocks for melee champs) is dropped
    from the pool. It fires UNCONDITIONALLY like the ``_NON_COACHABLE_ITEM_IDS``
    deny (every mode, every scorer, BEFORE the ``inject`` force-admit - a
    ranged-only item can never be a legal melee purchase, so no WIN-table inject
    should resurrect it) so a melee build never surfaces an unbuyable item.
    Default False (ranged / unknown) is a byte-identical no-op.
    """
    inject = inject_ids or frozenset()
    out: list[tuple[str, dict]] = []
    for item_id, rec in snapshot.items.items():
        if item_id in current_ids:
            continue
        if item_id in _NON_COACHABLE_ITEM_IDS:
            continue
        # DDragon-override SR-exclude deny (2026-07-06): items DDragon wrongly
        # marks purchasable on SR (support-quest upgrades) - deny unconditionally
        # on SR BEFORE the inject force-admit, like the non-coachable gate.
        if mode.upper() == "SR" and item_id in _SR_EXCLUDED_ITEM_IDS:
            continue
        # DDragon-override ARAM-exclude deny (2026-07-07): items DDragon wrongly
        # marks purchasable on ARAM (Arena prismatic mega-items in the 223xxx
        # mirror namespace) - deny unconditionally on ARAM BEFORE the inject
        # force-admit, like the SR-exclude + non-coachable gates.
        if mode.upper() == "ARAM" and item_id in _ARAM_EXCLUDED_ITEM_IDS:
            continue
        # Ornn masterwork deny (operator 2026-07-06): items obtainable ONLY via an
        # Ornn ally upgrade (Wooglet's Witchcap etc.) are marked gold.purchasable
        # =True + maps['12']=True in DDragon, so they leaked into the (ARAM) pool
        # and a from-scratch optimal recommended them - but they cannot be bought.
        # Deny unconditionally (every mode/scorer, before the inject force-admit),
        # like the non-coachable + ranged-only gates.
        if _is_ornn_masterwork(rec):
            continue
        # Ranged-only purchasability gate: a melee champ cannot buy these in the
        # shop, so they never enter the pool - ahead of the inject force-admit
        # (an unbuyable item must not be resurrected by a WIN-anchored inject).
        if champion_is_melee and item_id in RANGED_ONLY_ITEM_IDS:
            continue
        forced = item_id in inject
        if not forced:
            if only_ids is not None and item_id not in only_ids:
                continue
            if exclude_names and rec.get("name") in exclude_names:
                continue
            if not _is_purchasable(rec):
                continue
        if not _is_legal_in_mode(rec, mode):
            continue
        if not include_components and not _is_terminal(rec):
            continue
        gold = int((rec.get("gold") or {}).get("total", 0) or 0)
        if budget is not None and gold > budget:
            continue
        if cost_ceiling is not None and gold > cost_ceiling:
            continue
        out.append((item_id, rec))
    # DDragon alias-id dedup (operator 2026-07-12): DDragon 16.9.1+ ships the
    # same item under two ids - the real 4-digit id AND a strictly-longer alias
    # variant (the "32xxxx" / "66xxxx" mirror namespaces) that carries
    # maps["11"]=True, so BOTH survive the SR map-filter and the pool
    # double-counts the item (live Jhin SR reco emitted "The Collector" via 6676
    # AND 667666; 21 such SR name-collisions). Keep only the CANONICAL shortest
    # id per item name; a strictly-longer same-name id is a DDragon alias and is
    # dropped. Same-length collisions (Kalista's Black Spear 3599/3600, the
    # jungle-pet tiers 1101-1107 that share a display name) are NOT aliases and
    # are left untouched, so this pass is byte-identical off SR (ARAM/Arena/Brawl
    # have only the same-length collision - the alias namespaces map-filter to a
    # single survivor there).
    min_id_len: dict[str, int] = {}
    for item_id, rec in out:
        name = rec.get("name")
        if name is None:
            continue
        length = len(item_id)
        if name not in min_id_len or length < min_id_len[name]:
            min_id_len[name] = length
    out = [
        (item_id, rec)
        for item_id, rec in out
        if rec.get("name") is None or len(item_id) <= min_id_len[rec.get("name")]
    ]
    return out


def _safe_burst(
    snapshot: DataSnapshot,
    *,
    champion_id: str,
    level: int,
    item_ids: tuple[str, ...],
    mode: str,
    target_armor: float,
    target_mr: float,
    target_max_hp: float,
    target_bonus_hp: float,
    augments: Optional[Iterable],
) -> float:
    """Single-rotation total burst damage for a build, fail-soft to 0.0.

    Used only by the fight-length-reweight knob in ``rank_items``. Imported
    lazily so the default ``rank_items`` path (``fight_length`` omitted) never
    pays the burst-module import cost. Some champions return a zero/empty
    ``total_burst_damage``; the caller treats 0.0 as "burst unavailable" and
    falls back to a delta-only effective score. Never raises.
    """
    try:
        from .burst import compute_burst_damage

        res = compute_burst_damage(
            snapshot,
            champion_id=champion_id,
            level=level,
            item_ids=item_ids,
            mode=mode,
            target_armor=target_armor,
            target_mr=target_mr,
            target_max_hp=target_max_hp,
            target_bonus_hp=target_bonus_hp,
            # L2 (crit-burst fix, ENGINE 1.208.0): arm the kill-state takedown
            # seam for the fight-length burst term so the Collector (6676) execute
            # (5% target max HP true) and the takedown offense credit surface for
            # crit ADCs. Scoped to THIS caller only - compute_burst_damage's
            # global default stays False so every other caller is byte-identical.
            assume_takedown=True,
        )
        return max(0.0, float(getattr(res, "total_burst_damage", 0.0) or 0.0))
    except Exception:
        return 0.0


def _rank_sort_key(
    r: RankedItem,
    *,
    reweight: bool,
    sort_by: str,
    mana_reweight: bool,
) -> tuple:
    """Total-order sort key for a RankedItem (rows are sorted reverse=True).

    The metric branch matches the active knob (fight-length reweight / gold
    efficiency / bounded-mana valuation / the default DPS-delta). ``item_id`` is
    appended as a STABLE final tiebreak so two rows with an EXACT-tie metric
    order deterministically and can never flip across a process / :8893 restart
    (dict iteration order was the only tiebreak before - PD -> Kraken build
    instability, 2026-07-06). Byte-identical to the pre-tiebreak ordering for any
    non-tied pair: item_id is consulted only when the metric tuple is equal.
    """
    if reweight:
        # Fight-length knob engaged: order by total-damage-over-fight model.
        base = (r.effective_score, r.delta_dps)
    elif sort_by == "efficiency":
        base = (r.dps_per_1k_gold, r.delta_dps)
    elif mana_reweight:
        # Bounded mana valuation knob (ENGINE 1.64.0): order by the mana-adjusted
        # score so early mana items surface for mana-dependent casters.
        base = (r.mana_adjusted_score, r.delta_dps)
    else:
        base = (r.delta_dps, r.dps_per_1k_gold)
    return (*base, r.item_id)


def rank_items(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    current_item_ids: Optional[Iterable[str | int]] = None,
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    phase: Optional[str] = None,
    budget: Optional[int] = None,
    slot_count: int = DEFAULT_SLOT_COUNT,
    top_n: int = DEFAULT_TOP_N,
    include_components: bool = False,
    only_item_ids: Optional[Iterable[str | int]] = None,
    sort_by: str = "delta",
    augments: Optional[Iterable] = None,
    filter_shared_uniques: bool = True,
    fight_length: Optional[float] = None,
    mana_value_per_point: Optional[float] = None,
    apply_mode_modifiers: bool = False,
    exempt_offclass_by_win: bool = False,
    prefer_kit_axis_by_win: bool = False,
    cost_ceiling: Optional[int] = None,
    target_current_hp_pct: float = 1.0,
    kit_conversion_strength: float = 0.0,
    widen_carry_pool: bool = False,
    exclude_off_axis_items: bool = False,
    apply_crit_conversion: bool = False,
) -> RankResult:
    """Rank items by DPS contribution when added to ``current_item_ids``.

    Caller supplies the build-so-far in ``current_item_ids`` (or omits for
    naked baseline). Each remaining slot is scored by re-running
    ``compute_dps`` with the candidate appended and subtracting the
    baseline. Results are clipped to ``top_n`` after sorting.

    Sort keys:
      * ``delta``       - absolute DPS gained (default)
      * ``efficiency``  - DPS gained per 1000 gold spent

    ``include_components=True`` keeps non-terminal items in the ranking
    (useful when the player is mid-recipe and just bought a Long Sword).
    ``only_item_ids`` restricts to a caller-provided whitelist (e.g. UI
    pre-filtered by tag).

    ``filter_shared_uniques=True`` (default) drops candidates whose
    ``unique_passive_key`` matches a unique already in
    ``current_item_ids`` - operator gets no value from the second proc
    even though stat-only delta_dps would be positive (Trinity -> ER,
    Sterak's -> Maw, Sunfire -> Hollow Radiance). Pass ``False`` to surface
    them with ``shares_dead_unique=True`` set on the result.

    ``fight_length`` is the OPTIONAL fight-length-reweight knob (item 219 C
    follow-up). When ``None`` (the default), this function behaves EXACTLY as
    before: rows are ranked by ``sort_by`` over ``delta_dps`` /
    ``dps_per_1k_gold`` and ``RankedItem.effective_score`` is left at its 0.0
    default. The output is byte-identical to the pre-knob behavior; the extra
    burst compute is never paid. When a POSITIVE float, each candidate is
    re-scored to model total damage over a fight of that many seconds, blending
    front-loaded BURST with SUSTAINED DPS:

        effective = burst_delta + delta_dps * fight_length

    where ``burst_delta = burst(build + item) - burst(build)`` is the extra
    one-rotation burst the item adds (via ``compute_burst_damage`` ->
    ``BurstResult.total_burst_damage``). Short fights favor high-burst items;
    long fights favor high-sustained-DPS items. Rows are sorted by
    ``effective_score`` DESC (``sort_by`` is ignored while engaged) and the
    value is exposed on each ``RankedItem``. Fail-soft: a candidate whose burst
    is unavailable falls back to a delta-only effective score and never raises.
    Non-positive ``fight_length`` is treated as ``None`` (default ranking).

    ``mana_value_per_point`` is the OPTIONAL bounded mana-valuation knob
    (ENGINE 1.64.0). The auto-attack DPS scorer values flat mana at ~0, so a
    mana-dependent caster (Ziggs, Cassiopeia) sees early mana items (Tear 240
    mana, Lost Chapter 300 mana) rank below burn/AP items even when the mana
    sustain is the actual play. When ``None`` (default) the output is
    byte-identical to before - ``mana_adjusted_score`` / ``mana_gained`` stay
    0.0 and the sort key is unchanged. When a POSITIVE float (DPS-equivalent
    worth of one mana point), each candidate's ``mana_adjusted_score`` becomes
    ``delta_dps + mana_value_per_point * mana_gained`` (mana_gained = the flat
    mana the item adds over the baseline build) and the default ranking sorts
    by it. It has NO effect under ``sort_by="efficiency"`` or when
    ``fight_length`` is engaged (those own the sort key). A sane starting
    value is small (e.g. 0.02); it is operator-tunable, not a claim that mana
    has a fixed DPS price. Non-positive is treated as ``None``.

    ``exempt_offclass_by_win`` is the OPTIONAL DSP2 Cluster-B seam (DEFAULT-OFF).
    When ``False`` (default) the output is byte-identical to before - the
    item-213 ranged-marksman off-class deny-set applies unchanged. When ``True``
    and the champion is a ranged marksman, the off-class items this champ
    genuinely builds per the WIN+usage table
    (``marksman_offclass_exempt.json``: Ezreal/Corki/Smolder Trinity Force +
    Spear of Shojin, Senna Black Cleaver) are un-stripped from the candidate
    pool. Pure crit ADCs (absent from the table) are untouched. The live
    default-ON flip is EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md.

    ``prefer_kit_axis_by_win`` is the OPTIONAL DSP11 Cluster-B2 seam (DEFAULT-OFF).
    The generic auto-attack DPS model ranks a near-fixed AD template (BotRK /
    Kraken / Stormrazor / Trinity / Essence Reaver) for every AD carry because it
    cannot encode a kit's win-axis (Nilah doubles crit, Ezreal Q + Manamune ramp),
    so the items the player base WINS on (the DSP10 buried winners) sink below it.
    When ``False`` (default) the output is byte-identical - ``kit_axis_score``
    stays 0.0 and the sort is unchanged. When ``True`` and the champ has a
    WIN-anchored ``kit_axis_item_credit`` entry: (1) for a ranged marksman, the
    champ's kit-axis items are also un-stripped from the off-class deny set (so
    Ezreal's hard-excluded Trinity Force becomes a candidate), and (2) every
    positive-delta kit-axis item is floated above the generic template (model
    order preserved within each tier). Champs absent from the table are a no-op.
    The live default-ON flip is EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md.

    ``widen_carry_pool`` is the OPTIONAL RM-04 A-01 seam (DEFAULT-OFF). The
    item-213 off-class deny is class-wide by NAME, so the SR carry pool is 108
    items SET-IDENTICAL across every ranged marksman and categorically excludes
    Black Cleaver (3071) / Spear of Shojin (3161) / Stridebreaker (6631) /
    Sterak's Gage (3053) BEFORE scoring runs. When ``True`` and the champion is
    a ranged marksman, ``CARRY_POOL_WIDEN_ITEM_NAMES`` is un-stripped from the
    deny for EVERY ranged marksman - broader than ``exempt_offclass_by_win``,
    which is a 4-champion table with no Stridebreaker / Sterak's entry. NOTE
    Bloodsong (3877) is NOT widened: it is denied by ``_SR_EXCLUDED_ITEM_IDS``
    (the RM-93 support-quest deny, a different mechanism, measured harmful when
    admitted). When ``False`` (default) the output is byte-identical. The live
    default-ON flip is EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md.

    ``exclude_off_axis_items`` is the OPTIONAL RM-35 clause-(2) seam
    (DEFAULT-OFF) - the CARRY-route consumer of the symmetric kit-axis gate
    RM-41 built for ``ds.burst`` (``._burst_off_axis``). It matters here because
    of the ``fight_length`` blend above: the burst half of ``effective_score``
    credits a pure-AP item on an AD marksman even when its sustained
    ``delta_dps`` is exactly ZERO, so engaging ``fight_length`` floats dead AP
    gold into the ranking. MEASURED at 1.246.0, level 13, tanky target, each
    champion at its own shipped depth: Twitch (FL 0.5, already in the shipped
    ``core.ds_champion_fight_length`` allow-map) ranks Lich Bane 3100 at #7 on
    ``delta_dps`` 22.86 vs ``effective_score`` 251.00, and Rabadon's Deathcap
    3089 scores ``effective_score`` 176.21 off ``delta_dps`` 0.000 - the whole
    score is burst term. The gate is DATA-DRIVEN, not a curated list: the
    champion's axis comes from its own ``lolmath.damage_distribution`` and the
    item gate from its own DDragon offensive stat line, so hybrids survive by
    construction (Hextech Gunblade 3146, 80 AP + 40 AD, is NOT stripped) and a
    champion with no decisive split (Shaco) resolves to ``None`` and is a
    byte-identical no-op. When ``False`` (default) the candidate pool and every
    row are byte-identical. The live default-ON flip is EXCLUDED ->
    docs/LIVE_GAME_GATED_SYNC.md.

    ``cost_ceiling`` is the OPTIONAL F2 cost-aware-top seam (DEFAULT-OFF). When a
    positive int, candidates whose ``gold.total`` exceeds it are dropped from the
    pool (forwarded to ``_filter_candidates``), so the 6000g ARAM/Arena mega-item
    Void Immolation (223069) - floated to RANK 1 by the cost-scaling
    ``sort_by="delta"`` surface - is excluded. None (default) is byte-identical.
    The live default-ON flip is EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md.

    ``target_current_hp_pct`` (R55) is the seam that scales the three genuine
    %-CURRENT-HP procs (BotRK 3153 / Hellfire 4017 / Fulmination 443055) by the
    fraction of max HP the target sits at when the proc lands. It is forwarded
    unchanged to every ``compute_dps`` call (baseline + each candidate) so the
    carry (dps) scorer surfaces the same current-HP model the mage/assassin
    scorers already had. Default 1.0 is an identity multiply -> byte-identical.
    """
    if sort_by not in SORT_KEYS:
        raise ValueError(f"sort_by must be one of {SORT_KEYS}, got {sort_by!r}")
    level = clamp_level(level)
    # Bounded mana valuation knob (ENGINE 1.64.0). Only a positive float
    # engages it; None / non-positive -> byte-identical default ranking.
    mana_reweight = mana_value_per_point is not None and mana_value_per_point > 0.0

    # Fight-length-reweight knob (item 219 C). Only a positive float engages
    # the burst reweight; None / non-positive -> default delta-only ranking
    # (the byte-identical pre-knob path that pays nothing for burst compute).
    reweight = fight_length is not None and fight_length > 0.0

    current_ids: tuple[str, ...] = tuple(str(i) for i in (current_item_ids or ()))
    current_ids, stripped_trinkets = strip_arena_trinkets(current_ids, mode)
    current_set = set(current_ids)
    # Collect every unique_passive_key already locked in by the current build.
    # Candidates sharing one of these keys would have their proc/pen effect
    # zeroed by ``collect_effects`` - surface that to consumers via the flag
    # on RankedItem, and filter by default.
    current_unique_keys: set[str] = set()
    for iid in current_ids:
        eff = ITEM_EFFECTS.get(iid)
        if eff is not None and eff.unique_passive_key:
            current_unique_keys.add(eff.unique_passive_key)
    if len(current_ids) >= slot_count:
        raise ValueError(
            f"current_item_ids has {len(current_ids)} items; slot_count={slot_count} "
            f"leaves no room for a new item"
        )

    only_ids: Optional[set[str]] = None
    if only_item_ids is not None:
        only_ids = {str(i) for i in only_item_ids}

    # HOT-01 (2026-07-09): the ranker only reads weighted_dps (the selected
    # phase). Resolve the selected phase HERE - identically to compute_dps's
    # internal ``phase or _select_phase(level)`` for any in-range level - and
    # pass it as only_phase so each compute_dps skips the 2 unused phase
    # convolutions. weighted_dps for the selected phase is byte-identical.
    _selected_phase = phase or _select_phase(level)
    # A-12 / RM-46: the crit-conversion flag must reach BOTH compute_dps calls
    # (this baseline and the per-candidate score below). Feeding only one would
    # subtract a converted score from an unconverted baseline and manufacture a
    # delta out of the seam itself. DEFAULT-OFF -> byte-identical (dps.py:890
    # performs no lookup and no arithmetic when the flag is False).
    baseline = compute_dps(
        snapshot,
        champion_id=champion_id,
        level=level,
        item_ids=current_ids,
        mode=mode,
        target_armor=target_armor,
        target_mr=target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        target_current_hp_pct=target_current_hp_pct,
        phase=phase,
        augments=augments,
        apply_mode_modifiers=apply_mode_modifiers,
        only_phase=_selected_phase,
        apply_crit_conversion=apply_crit_conversion,
    )

    # Baseline burst with the current build (item 219 C). Computed ONCE and
    # ONLY when the fight-length knob is engaged - the default path never pays
    # for the burst module import or the extra engine pass.
    baseline_burst = 0.0
    if reweight:
        baseline_burst = _safe_burst(
            snapshot,
            champion_id=champion_id,
            level=level,
            item_ids=current_ids,
            mode=mode,
            target_armor=target_armor,
            target_mr=target_mr,
            target_max_hp=target_max_hp,
            target_bonus_hp=target_bonus_hp,
            augments=augments,
        )

    # Off-class deny-set (item 213): when the champion is a ranged marksman,
    # drop melee-bruiser / tank / skirmisher items from the DPS candidate
    # pool. This scorer is only routed to for carry / dps / adc archetypes,
    # so a ranged-marksman gate here precisely targets ADC build pollution
    # without touching mage (mage scorer) or melee fighter / tank builds.
    exclude_names: Optional[frozenset[str]] = None
    champ_rec = snapshot.champions.get(str(champion_id))
    # DSP11 (DEFAULT-OFF): resolve the champ's WIN-anchored kit-axis item set.
    # Empty unless the seam is on AND the champ is tabled -> byte-identical no-op.
    kit_axis_ids: frozenset[str] = (
        kit_axis_item_ids(str(champion_id), champ_rec)
        if prefer_kit_axis_by_win else frozenset()
    )
    kit_axis_active = bool(kit_axis_ids)
    if champ_rec is not None and _is_ranged_marksman(champ_rec):
        exclude_names = OFFCLASS_MARKSMAN_ITEM_NAMES
        # DSP2 Cluster-B (DEFAULT-OFF): un-strip the off-class items this
        # caster-marksman genuinely builds per the WIN+usage table, so the
        # ranker stops hard-excluding (Ezreal/Corki/Smolder) Trinity Force /
        # Spear of Shojin. Byte-identical when the seam is off.
        if exempt_offclass_by_win:
            exempt = _offclass_win_exemptions(str(champion_id), champ_rec)
            if exempt:
                exclude_names = OFFCLASS_MARKSMAN_ITEM_NAMES - exempt
        # DSP11 (DEFAULT-OFF): the kit-axis seam ALSO un-strips this champ's
        # WIN-anchored kit-axis items from the off-class deny set, so a
        # caster-ADC's hard-excluded Trinity Force / Muramana becomes a
        # candidate it can then float. Byte-identical when the seam is off.
        if kit_axis_active:
            axis_names = kit_axis_item_names(str(champion_id), champ_rec)
            if axis_names:
                exclude_names = exclude_names - axis_names
        # RM-04 A-01 (DEFAULT-OFF): class-wide widen. Un-strip the four
        # ROADMAP-named off-class items (Black Cleaver / Spear of Shojin /
        # Stridebreaker / Sterak's Gage) for EVERY ranged marksman, not just
        # the four DSP2-tabled champions. Composes with both seams above (set
        # difference is order-independent). Byte-identical when off.
        if widen_carry_pool:
            exclude_names = exclude_names - CARRY_POOL_WIDEN_ITEM_NAMES

    candidates = _filter_candidates(
        snapshot,
        mode=mode,
        current_ids=current_set,
        budget=budget,
        include_components=include_components,
        only_ids=only_ids,
        exclude_names=exclude_names,
        cost_ceiling=cost_ceiling,
        # Ranged-only purchasability gate: drop Runaan's (+ alias) when the
        # champ is melee - the in-game shop blocks the purchase (2026-07-02).
        champion_is_melee=_champion_is_melee(champ_rec, augments),
    )

    # RM-35 clause (2), DEFAULT-OFF: strip candidates whose offense sits
    # ENTIRELY on this champion's OFF axis. Same symmetric gate the RM-41
    # ds.burst ranker uses (agents/daemon_slayer/_burst_off_axis.py), wired
    # here because the fight_length burst term credits a zero-DPS AP item on
    # an AD marksman. Axis resolved ONCE (O(candidates)); an indecisive damage
    # split leaves off_axis None and the comprehension is a no-op.
    off_axis: Optional[str] = (
        champion_burst_axis(champ_rec) if exclude_off_axis_items else None
    )
    if off_axis is not None:
        candidates = [
            (item_id, rec) for item_id, rec in candidates
            if not is_off_axis_candidate(rec, off_axis)
        ]

    ranked: list[RankedItem] = []
    for item_id, rec in candidates:
        # Compute the dead-unique flag BEFORE the expensive compute_dps call
        # so the default-filter path saves the work entirely.
        cand_eff = ITEM_EFFECTS.get(item_id)
        cand_key = cand_eff.unique_passive_key if cand_eff is not None else ""
        shares_dead_unique = bool(cand_key and cand_key in current_unique_keys)
        if shares_dead_unique and filter_shared_uniques:
            continue
        new_build = current_ids + (item_id,)
        try:
            scored = compute_dps(
                snapshot,
                champion_id=champion_id,
                level=level,
                item_ids=new_build,
                mode=mode,
                target_armor=target_armor,
                target_mr=target_mr,
                target_max_hp=target_max_hp,
                target_bonus_hp=target_bonus_hp,
                target_current_hp_pct=target_current_hp_pct,
                phase=phase,
                augments=augments,
                apply_mode_modifiers=apply_mode_modifiers,
                only_phase=_selected_phase,
                apply_crit_conversion=apply_crit_conversion,
            )
        except (KeyError, ValueError):
            continue
        gold = int((rec.get("gold") or {}).get("total", 0) or 0)
        delta = scored.weighted_dps - baseline.weighted_dps
        # Efficiency in DPS per 1000 gold so the column stays in a readable range.
        # Negative or zero deltas zero-out - they're not "efficient", they're regressions.
        eff = (delta / (gold / 1000.0)) if (gold > 0 and delta > 0) else 0.0
        # Fight-length-reweighted effective score (item 219 C). Default path
        # (reweight False) leaves this at 0.0 so the rows stay byte-identical.
        effective = 0.0
        if reweight:
            # fight_length is narrowed positive by ``reweight``.
            trial_burst = _safe_burst(
                snapshot,
                champion_id=champion_id,
                level=level,
                item_ids=new_build,
                mode=mode,
                target_armor=target_armor,
                target_mr=target_mr,
                target_max_hp=target_max_hp,
                target_bonus_hp=target_bonus_hp,
                augments=augments,
            )
            # Fail-soft: if the trial burst is unavailable (0.0), fall back to a
            # delta-only effective score for this candidate (no burst term).
            burst_gain = (trial_burst - baseline_burst) if trial_burst > 0.0 else 0.0
            effective = burst_gain + delta * float(fight_length)
        # Bounded mana valuation (ENGINE 1.64.0). mana_gained is the flat mana
        # this item adds over the baseline build (mana sits in the resolved
        # stat block but contributes ~0 to weighted_dps for most casters).
        # Default path (mana_reweight False) leaves both at 0.0 so the rows
        # stay byte-identical to the pre-1.64.0 output.
        mana_gained = 0.0
        mana_adjusted = 0.0
        if mana_reweight:
            mana_gained = max(
                0.0,
                float(scored.stats.get("mp", 0.0))
                - float(baseline.stats.get("mp", 0.0)),
            )
            mana_adjusted = delta + mana_value_per_point * mana_gained
        # DSP11 kit-axis credit marker: 1.0 on a surfaced (positive-delta)
        # WIN-anchored kit-axis item when the seam is engaged, else 0.0. A
        # non-positive delta is a genuine regression and is NOT floated.
        kit_axis_score = 1.0 if (
            kit_axis_active and item_id in kit_axis_ids and delta > 0.0
        ) else 0.0
        ranked.append(
            RankedItem(
                item_id=item_id,
                item_name=str(rec.get("name", item_id)),
                gold=gold,
                delta_dps=delta,
                new_dps=scored.weighted_dps,
                dps_per_1k_gold=eff,
                is_terminal=_is_terminal(rec),
                tags=tuple(rec.get("tags") or ()),
                shares_dead_unique=shares_dead_unique,
                dead_unique_key=cand_key if shares_dead_unique else "",
                unique_passive_key=cand_key,
                effective_score=effective,
                mana_adjusted_score=mana_adjusted,
                mana_gained=mana_gained,
                kit_axis_score=kit_axis_score,
            )
        )

    # RM-86 L1 kit-conversion gate (DEFAULT-OFF). The registry is consulted ONLY
    # when the lever is engaged, so 0.0 performs no lookup and no arithmetic and
    # is provably byte-identical, not merely numerically equal - the
    # onhit_dps.py:494-496 contract.
    _conv = (
        kit_conversion(str(champion_id), champ_rec)
        if kit_conversion_strength > 0.0 else None
    )
    _conv_objective = damage_objective(snapshot, champion_id) if _conv is not None else ""
    _conv_memo: dict[str, float] = {}

    def _conv_key(value: float, item_id: str) -> float:
        """Sort-only view of ``value`` - never mutates the row itself.

        Only ever LOWERS: a non-positive value is returned unchanged, because
        scaling a negative number toward zero would RAISE, not lower, its rank
        (the onhit_dps.py:501-504 rule).
        """
        if _conv is None or value <= 0.0:
            return value
        factor = _conv_memo.get(item_id)
        if factor is None:
            factor = conversion_factor(
                _conv, item_id, snapshot.items.get(item_id) or {},
                kit_conversion_strength, _conv_objective,
            )
            _conv_memo[item_id] = factor
        return value * factor

    def _key(r: RankedItem) -> tuple:
        base = _rank_sort_key(
            r, reweight=reweight, sort_by=sort_by, mana_reweight=mana_reweight
        )
        if _conv is not None:
            # Scale each METRIC element. The trailing item_id stable tiebreak is
            # a string and must pass through untouched.
            *metrics, tiebreak = base
            base = (*(_conv_key(m, r.item_id) for m in metrics), tiebreak)
        # DSP11: float surfaced kit-axis items above the generic template,
        # preserving the model order within each tier. Byte-identical when off
        # (kit_axis_active False -> the prefix term is never added).
        return (r.kit_axis_score, *base) if kit_axis_active else base

    ranked.sort(key=_key, reverse=True)

    if top_n is not None and top_n > 0:
        ranked = ranked[:top_n]

    notes: list[str] = []
    if mode in MODE_MAP_ID:
        notes.append(f"mode={mode} -> maps id {MODE_MAP_ID[mode]}")
    else:
        notes.append(f"mode={mode} not in MODE_MAP_ID - no per-mode item filter applied")
    if stripped_trinkets:
        notes.append(
            f"mode=ARENA - stripped trinket(s) {list(stripped_trinkets)} from current_item_ids"
        )
    if include_components:
        notes.append("include_components=True - non-terminal items in the ranking")
    if budget is not None:
        notes.append(f"budget={budget}g - items over budget filtered")
    if mana_reweight:
        notes.append(
            f"mana_value_per_point={mana_value_per_point} - mana-adjusted "
            f"ranking (delta_dps + {mana_value_per_point} x mana_gained)"
        )
    if baseline.mode_multiplier == 0.0:
        notes.append(
            "baseline mode_multiplier=0 - all DPS deltas will be 0 (e.g. Yunara in ARAM)"
        )

    return RankResult(
        champion_id=baseline.champion_id,
        champion_name=baseline.champion_name,
        level=level,
        mode=mode,
        current_item_ids=current_ids,
        baseline_dps=baseline.weighted_dps,
        target_armor=target_armor,
        target_mr=target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        phase=baseline.phase,
        budget=budget,
        slot_count=slot_count,
        sort_by=sort_by,
        candidates_considered=len(snapshot.items),
        candidates_evaluated=len(candidates),
        ranked=tuple(ranked),
        notes=tuple(notes),
    )
