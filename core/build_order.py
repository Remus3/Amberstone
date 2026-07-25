# arch: contextual DS-backed build-ORDER planner | section=coaching | frozen=no
"""Contextual, match-specific item BUILD-ORDER planner (2026-05-17).

Closes the long-standing "always the same items, not match-specific"
complaint and enforces the hard rule: **never recommend two items that
share a unique passive** (Sheen/Spellblade family - Trinity Force +
Essence Reaver invalid together; also Lifeline and Immolate families).

Why the old path produced "always the same items"
-------------------------------------------------
``daemon_slayer_client.rank_for_primary_archetype`` (and the six
underlying ``rank_items_by_*`` scorers) does *greedy single-item
marginal* scoring: for a fixed ``item_ids`` it scores every candidate's
delta when added *alone*, sorts, returns a flat top-N. Coaches surface
that flat list (``coach_integration.archetype_dispatch.display_rows``).
There is no *sequenced* build anywhere - with a near-naked champion the
#1 item is deterministic per (champion, level), so every game shows the
same item. And because dedup only filters candidates colliding with an
*already-owned* item, the flat list can itself contain Trinity Force
**and** Essence Reaver (both ``unique_passive_key="spellblade"``) - a
forbidden double the moment the list is read as a build.

How this layer fixes both
-------------------------
Pure orchestration over the existing, tested engine - *no engine change*:

1. **Order = iterative forward selection.** Call the ranker once per
   slot, appending the chosen item to ``item_ids`` before the next call.
   Each slot is therefore scored against the *accumulated* build + the
   real enemy context (``target_armor/mr/max_hp/bonus_hp`` already
   plumbed from ``enemy_stats``), so the sequence genuinely adapts to
   the match instead of being six copies of "best single item".

2. **No-double rule is engine-authoritative.** ``rank_for_primary_
   archetype`` threads ``filter_shared_uniques=True`` (its default) to
   the DS server, whose ``collect_effects`` / ``current_unique_keys``
   dedup is the source of truth for the 7 unique-passive families:
   spellblade, lifeline, immolate, hydra_cleave (Iter 3, 2026-05-19),
   fiendhunter_barrage, hellfire_char, innervating_fill - each spans
   SR + Arena (CHERRY) mirrors. Once slot 1 is e.g. Trinity Force and
   it is in ``item_ids``, *every* later slot's ranking has
   ``spellblade`` locked - all other spellblade candidates are filtered
   server-side. Enforcing iteratively means we inherit that guarantee
   for the whole sequence without duplicating the family map here
   (which would invite the s173 anti-drift trap). A planner-side
   belt-and-suspenders skip of any ``shares_dead_unique`` row covers
   the off-default (``filter_shared_uniques=False``) caller too, and
   the ``unique_passive_safe`` invariant is then True by construction.

Engine-down / empty-champion semantics mirror ``dispatch_for_coach``:
return ``None`` so callers fall back to "unavailable" without writing
partial state.

Headless-testable: inject ``rank_fn`` (defaults to the real dispatcher)
so the planner can be exercised with a fake engine - no live DS server.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

logger = logging.getLogger("rc.core.build_order")

# Full build is 6 item slots in every mode RC coaches for.
DEFAULT_SLOTS = 6

# Scorer -> human unit, mirrors archetype_dispatch._UNIT_SUFFIX. Kept as a
# tiny independent copy on purpose: this module must not import the coach
# layer (coaches import *this*), and the table is a stable 6-row constant,
# not drift-prone engine data.
_UNIT_SUFFIX: dict[str, str] = {
    "dps":     "dps",
    "ehp":     "ehp",
    "hybrid":  "%",
    "ability": "adps",
    "burst":   "burst",
    "hps":     "hps",
}

# 2026-05-23 (item 164b): boots-slot injection. Every plan_build_order
# call returns a build that contains exactly one boots family entry per
# operator's directive ("boots in EVERY build order on EVERY mode"). The
# inject happens AFTER the engine's iterative selection so subsequent
# slots are still picked greedily against a no-boots accumulated build
# (boots don't share unique-passive families with damage items so the
# no-double rule isn't affected). Boots slot lands at position 2 (after
# the first big item) - matches typical SR timing.
#
# Boots-family IDs (DDragon 16.12.1; verified via data/meta_build/ddragon/
# 16.12.1/item.json). Holds the tier-2 base boots (purchasable + the
# rune-granted Symbiotic Soles) AND the SR-only tier-3 upgrades, so the
# owned-boots ownership scan recognizes whichever form a player already
# holds. (G4 boots-pool refresh, 2026-06-15 - lolmath-parity sweep.)
_BOOTS_IDS: frozenset = frozenset({
    # tier-2 base (map 11 + 12). 3117/3010 are no longer in-store but stay
    # for ownership detection of a legacy / rune-granted hold.
    "3006",   # Berserker's Greaves
    "3009",   # Boots of Swiftness
    "3010",   # Symbiotic Soles (rune-granted)
    "3020",   # Sorcerer's Shoes
    "3047",   # Plated Steelcaps
    "3111",   # Mercury's Treads
    "3117",   # Mobility Boots (removed from store 16.x - detect-only)
    "3158",   # Ionian Boots of Lucidity
    # tier-3 upgrades (SR / map 11 only - no ARAM (12) / Arena (30) form)
    "3013",   # Synchronized Souls (<- Symbiotic Soles)
    "3168",   # Immortal Path (<- Gluttonous Greaves)
    "3170",   # Swiftmarch (<- Boots of Swiftness)
    "3171",   # Crimson Lucidity (<- Ionian Boots)
    "3172",   # Gunmetal Greaves (<- Berserker's Greaves)
    "3173",   # Chainlaced Crushers (<- Mercury's Treads)
    "3174",   # Armored Advance (<- Plated Steelcaps)
    "3175",   # Spellslinger's Shoes (<- Sorcerer's Shoes)
    "3176",   # Forever Forward (<- Synchronized Souls)
    # Arena (map 30) mirrors - the 3xxx tier-2 boots are map30=False, so on
    # Arena the build uses these 22-prefixed map30-legal forms (no tier-3
    # on Arena). Included here for ownership detection + order-filtering.
    "223006",  # Berserker's Greaves (Arena)
    "223009",  # Boots of Swiftness (Arena)
    "223020",  # Sorcerer's Shoes (Arena)
    "223047",  # Plated Steelcaps (Arena)
    "223111",  # Mercury's Treads (Arena)
    "223158",  # Ionian Boots of Lucidity (Arena)
})
_BOOTS_NAMES: dict[str, str] = {
    "3006": "Berserker's Greaves",
    "3009": "Boots of Swiftness",
    "3010": "Symbiotic Soles",
    "3020": "Sorcerer's Shoes",
    "3047": "Plated Steelcaps",
    "3111": "Mercury's Treads",
    "3117": "Mobility Boots",
    "3158": "Ionian Boots of Lucidity",
    "3013": "Synchronized Souls",
    "3168": "Immortal Path",
    "3170": "Swiftmarch",
    "3171": "Crimson Lucidity",
    "3172": "Gunmetal Greaves",
    "3173": "Chainlaced Crushers",
    "3174": "Armored Advance",
    "3175": "Spellslinger's Shoes",
    "3176": "Forever Forward",
    "223006": "Berserker's Greaves",
    "223009": "Boots of Swiftness",
    "223020": "Sorcerer's Shoes",
    "223047": "Plated Steelcaps",
    "223111": "Mercury's Treads",
    "223158": "Ionian Boots of Lucidity",
}
# SR tier-3 boots upgrade REMOVED (operator 2026-07-08). DDragon 16.12.1
# marks the tier-3 boots (3170-3175, 3168, 3013, 3176) as ``purchasable=true``,
# but in-game they are role-QUEST REWARDS - the Mid lane quest auto-upgrades the
# champion's equipped tier-2 boots, and the Bot lane quest moves them to a bonus
# 7th slot. You can never BUY a tier-3 boot directly from the shop (operator:
# "Gunmetal Greaves at slot 2 is impossible to buy because the quest puts boots
# in a 7th bonus slot"). The build-order planner must only recommend directly-
# purchasable items, so the SR tier-3 upgrade is gone - every mode keeps the
# tier-2 boot. The tier-3 IDs are still in _BOOTS_IDS (for owned-item detection
# so an already-upgraded boot is recognized) and _BOOTS_NAMES (for display), but
# they are never a _selection_ target.
#
# The :func:`_select_boots` SR-branch that applied this upgrade is also removed;
# the ``if mode_up in _SR_MODES`` block is now a commented-out record of the
# original tier-2 -> tier-3 mapping (preserved for patch-history reference).
# Retention guard: if any caller still references _BOOTS_SR_UPGRADE, it will
# get a dict and won't NameError - but it will find every tier-2 maps to itself.
_BOOTS_SR_UPGRADE: dict[str, str] = {
    # "3006": "3172",  # Berserker's Greaves -> Gunmetal Greaves           (removed)
    # "3008": "3168",  # Gluttonous Greaves  -> Immortal Path              (removed)
    # "3009": "3170",  # Boots of Swiftness  -> Swiftmarch                 (removed)
    # "3010": "3013",  # Symbiotic Soles     -> Synchronized Souls         (removed)
    # "3020": "3175",  # Sorcerer's Shoes    -> Spellslinger's Shoes       (removed)
    # "3047": "3174",  # Plated Steelcaps    -> Armored Advance            (removed)
    # "3111": "3173",  # Mercury's Treads    -> Chainlaced Crushers        (removed)
    # "3158": "3171",  # Ionian Boots        -> Crimson Lucidity           (removed)
}
# Mode strings treated as Summoner's Rift for the tier-3 boots upgrade.
_SR_MODES: frozenset = frozenset({"SR", "CLASSIC"})
# Arena (map 30) tier-2 boots mirror. The 3xxx tier-2 boots are map30=False
# (illegal on the Arena map); Arena uses the 22-prefixed mirror ids (DDragon
# 16.12.1, each verified map30=True). Symbiotic Soles (3010) is rune-granted
# with no Arena mirror + is never a selection target. Applied by
# _select_boots when mode is Arena/CHERRY (P6-G4 deferred tail; the SR tier-3
# sibling shipped item 423).
_BOOTS_ARENA_MIRROR: dict[str, str] = {
    "3006": "223006",  # Berserker's Greaves
    "3009": "223009",  # Boots of Swiftness
    "3020": "223020",  # Sorcerer's Shoes
    "3047": "223047",  # Plated Steelcaps
    "3111": "223111",  # Mercury's Treads
    "3158": "223158",  # Ionian Boots of Lucidity
}
# Mode strings treated as Arena (map 30) for the boots mirror remap.
_ARENA_MODES: frozenset = frozenset({"ARENA", "CHERRY"})
# Archetype/scorer -> default tier-2 boots family (fallback when enemy
# AD/AP split is balanced); _select_boots upgrades to the tier-3 form on
# SR. Carry/dps/marksman -> Berserker's; mage/burst -> Sorcerer's;
# tank/ehp/bruiser -> Steelcaps; assassin/enchanter/hps/ability -> Ionian.
_DEFAULT_BOOTS_BY_ARCHETYPE: dict[str, str] = {
    "carry":     "3006",
    "marksman":  "3006",
    "adc":       "3006",
    "dps":       "3006",
    "bruiser":   "3047",
    "tank":      "3047",
    "ehp":       "3047",
    "hybrid":    "3047",
    "mage":      "3020",
    "burst":     "3020",
    "assassin":  "3158",   # was 3117 Mobility (out of store 16.x);
                           # Ionian -> Crimson Lucidity on SR (CDR for resets)
    "enchanter": "3158",
    "support":   "3158",
    "hps":       "3158",
    "ability":   "3158",
}
# Champions that traditionally skip boots (operator-flagged exception
# set). Yuumi has no movement-affected kit (attached to ally); Cassiopeia
# has Aspect of the Serpent giving her boots equivalent. Add to this set
# if more exception champs surface.
_BOOTSLESS_CHAMPS: frozenset = frozenset({
    "Yuumi",
    "Cassiopeia",
})


# Per-champion boots override, consulted ONLY in the archetype-default branch of
# boot selection (the situational Mercury/Steelcaps picks still win). Keyed by
# canonical champion name. Jhin -> Boots of Swiftness (3009): his Whisper passive
# locks attack speed (Berserker's is wasted) and his kit is an immobile backline
# carry that leans on the movement speed. Add entries sparingly - only when a
# champion's kit makes a non-default tier-2 boot the clear archetype baseline.
_BOOTS_OVERRIDE_BY_CHAMP: dict[str, str] = {
    "Jhin": "3009",
}

# A-21 / RM-90 Slice S1 (2026-07-25): the ``score_by`` EHP-objective selector.
# ``POST /rank-tank`` has parsed this since ENGINE 1.220.0 (server.py:639-643)
# and ``rank_for_primary_archetype`` has forwarded it since the same bump, but
# NO build-order caller could set it, so no shipped table could emit the Term A
# ally-granted-EHP (``team_blended``) ranking. This is the missing client-side
# half - there is no server change in the slice.
#
# TANK-ONLY by construction: ``rank_for_primary_archetype`` threads ``score_by``
# into the ds.ehp branch and nowhere else, so a carry / mage / bruiser plan is
# unaffected whatever this is set to.
#
# DEFAULT-OFF: ``"blended"`` is today's value AND is never emitted into the
# ranker kwargs at all (see the forward site in :func:`plan_build_order`), so an
# unchanged caller - including an injected test ``rank_fn`` with no ``**kwargs``
# - sees a byte-identical call.
SCORE_BY_DEFAULT = "blended"
SCORE_BY_VALUES: frozenset = frozenset({"blended", "cc_blended", "team_blended"})


def _select_boots_utility(
    arch: str,
    enemy_ad_share: float,
    enemy_ap_share: float,
    champion: str = "",
    enemy_champions: Optional[Iterable[str]] = None,
) -> str:
    """ON-path boot pick: comp-conditioned utility argmax with archetype-default
    hysteresis. Lazy-imports the DS primitive (byte-identical OFF never touches it).

    ``champion`` (default "") consults the per-champion boots override as the
    hysteresis default when present (Jhin -> Swiftness); blank / unlisted
    champions keep the archetype default, so the ON path stays byte-identical.

    ``enemy_champions`` (default None, A-39 v2 input) supplies the real enemy
    roster so the CC axis is fed from ``boot_utility.comp_cc_signal`` (per-champion
    hand-weighted lockdown seconds) instead of the v1 AP-share proxy. None - every
    pre-A-39 caller - keeps the v1 proxy, so the ON path stays byte-identical."""
    from agents.daemon_slayer import boot_utility as bu
    default_id = _BOOTS_OVERRIDE_BY_CHAMP.get(champion) or _DEFAULT_BOOTS_BY_ARCHETYPE.get(arch, "3006")
    # v2 (A-39): real per-champion enemy CC when the caller supplies the roster.
    # The v1 AP-share proxy is the documented fallback - it under-credits an
    # AD-dominant lockdown frontline (measured comp-mean lockdown 3.650 for
    # Nautilus/Amumu/Leona/Sejuani/Malphite against an AP share near 0.25).
    cc_signal = bu.comp_cc_signal(enemy_champions)
    cc_proxy = float(enemy_ap_share) if cc_signal is None else float(cc_signal)
    weights = bu.comp_weights(arch, float(enemy_ad_share), float(enemy_ap_share), cc_proxy)
    return bu.select_boot(bu.SELECTABLE_TIER2, weights, default_id)


def _select_boots(
    archetype: str,
    target_armor: float,
    target_mr: float,
    mode: str = "SR",
    enemy_ad_share: float = 0.5,
    enemy_ap_share: float = 0.5,
    assume_boot_utility: bool = False,
    champion: str = "",
    enemy_champions: Optional[Iterable[str]] = None,
) -> tuple[str, str]:
    """Pick the appropriate boots family given the operator's archetype +
    enemy AD/AP comp signal. Returns ``(item_id, item_name)``.

    Decision order (resolves a tier-2 family, then upgrades on SR):
      1. Strong AP/CC pressure (``target_mr >= 60``) -> Mercury's Treads
         (MR + tenacity). Exception: dps/carry/marksman archetypes keep
         Berserker's even vs heavy AP since the AS loss hurts more than
         MR-pen helps for marksmen.
      2. Strong AD pressure (``target_armor >= 100``) -> Plated Steelcaps
         (armor). Exception: mage/burst/enchanter/hps keep their default
         since CDR/penetration outweighs armor against caster threats.
      3. Default: archetype map (carry -> Berserker, mage -> Sorcerer,
         tank -> Steelcaps, assassin/enchanter -> Ionian).

    The SR tier-3 boots upgrade that previously applied here was REMOVED
    (operator 2026-07-08): the tier-3 boots are role-quest rewards, not
    directly purchasable. Every mode keeps the tier-2 boot; the tier-3
    IDs are still in _BOOTS_IDS (owned-item detection) and _BOOTS_NAMES
    (display), but they are never a _selection_ target.

    Arena (``mode`` in :data:`_ARENA_MODES`, map 30) remaps the resolved
    tier-2 boot to its map30-legal 22-prefixed mirror via
    :data:`_BOOTS_ARENA_MIRROR`.

    ``enemy_champions`` (default None, A-39) is forwarded to the ON path only,
    where it upgrades the CC axis from the v1 AP-share proxy to a real
    per-champion lockdown signal. It is inert on the OFF path and inert when
    None, so every pre-A-39 caller is byte-identical.
    """
    arch = (archetype or "carry").strip().lower() or "carry"
    if assume_boot_utility:
        iid = _select_boots_utility(
            arch, float(enemy_ad_share), float(enemy_ap_share),
            champion=champion,
            enemy_champions=enemy_champions,
        )
    else:
        is_dps_axis = arch in ("dps", "carry", "marksman", "adc")
        is_caster_axis = arch in ("mage", "burst", "enchanter", "hps", "ability", "support")
        if target_mr >= 60.0 and not is_dps_axis:
            iid = "3111"
        elif target_armor >= 100.0 and not is_caster_axis:
            iid = "3047"
        else:
            iid = _BOOTS_OVERRIDE_BY_CHAMP.get(champion) or _DEFAULT_BOOTS_BY_ARCHETYPE.get(arch, "3006")
    mode_up = str(mode).strip().upper()
    # TIER-3 SR UPGRADE REMOVED (2026-07-08): T3 boots are quest rewards,
    # not directly purchasable. The _BOOTS_SR_UPGRADE dict is now an empty
    # tombstone; every mode keeps the tier-2 boot.
    if mode_up in _ARENA_MODES:
        iid = _BOOTS_ARENA_MIRROR.get(iid, iid)
    return (iid, _BOOTS_NAMES.get(iid, "Boots"))


# --------------------------------------------------------------------------- #
# Item IDENTITY for duplicate rejection (2026-07-25, W3).
#
# ``3004`` and ``323004`` are both Manamune; ``6676`` and ``667666`` are both The
# Collector. A raw-string compare therefore does NOT answer "is this item already
# in the build", and the shipped 16.14.1 tables proved it: Viego and Samira both
# shipped orders that bought one item twice, burning a slot.
#
# The single normalizer for this repo is
# ``core.build_planner.kit_synergy.canonical_item_id`` (added 2026-07-25 for the
# Arena spellblade dock). It is imported LAZILY and fail-soft: kit_synergy reads
# the live items.json at import time, and this module is on the coach hot path in
# environments where that data may be absent. On any import failure the identity
# degrades to the raw id, i.e. exactly the pre-fix behavior.
# --------------------------------------------------------------------------- #
def _canonical_id(item_id) -> str:
    """Canonical (SR) id string for ``item_id`` - "" for a blank/None id."""
    sid = str(item_id or "").strip()
    if not sid:
        return ""
    try:
        from core.build_planner.kit_synergy import canonical_item_id
    except Exception:  # noqa: BLE001 - fail-soft to raw-id semantics
        return sid
    try:
        return canonical_item_id(sid) or sid
    except Exception:  # noqa: BLE001
        return sid


@dataclass(frozen=True)
class BuildStep:
    """One slot in the planned order (counts NEW picks only - owned items
    are excluded from the sequence)."""

    slot: int                 # 1-based position among the new picks
    item_id: str
    item_name: str
    delta: float              # scorer delta gained at THIS step vs the
                              # accumulated build immediately before it
    gold: int
    scorer: str               # dps|ehp|hybrid|ability|burst|hps
    unit: str                 # display unit for ``delta``
    # Family of a candidate the engine *excluded* at this slot because its
    # unique passive was already taken (engine-supplied via dead_unique_key
    # - populated opportunistically, never fabricated). Empty when nothing
    # was excluded for a family reason at this slot.
    excluded_family: str = ""
    excluded_example: str = ""
    # Phase 4(d): the family the CHOSEN item at this slot locks in for
    # the rest of the build (engine-supplied unique_passive_key, always
    # populated). Empty when the pick has no unique passive. Positive
    # counterpart to ``excluded_family`` above.
    locked_family: str = ""

    def to_dict(self) -> dict:
        return {
            "slot": self.slot,
            "item_id": self.item_id,
            "item_name": self.item_name,
            "delta": round(self.delta, 2),
            "gold": self.gold,
            "scorer": self.scorer,
            "unit": self.unit,
            "excluded_family": self.excluded_family,
            "excluded_example": self.excluded_example,
            "locked_family": self.locked_family,
        }


@dataclass
class BuildOrderResult:
    champion: str
    archetype: str
    scorer: str
    mode: str
    level: int
    owned: list[str]
    order: list[BuildStep] = field(default_factory=list)
    # The enemy context actually used - proves the order is match-specific
    # (flip these and the order changes; see tests).
    context: dict = field(default_factory=dict)
    # True iff every accepted pick had shares_dead_unique == False, i.e.
    # the hard no-double rule held for the whole sequence. By construction
    # under the default engine dedup; the flag makes it machine-checkable.
    unique_passive_safe: bool = True
    notes: list[str] = field(default_factory=list)

    def order_str(self) -> str:
        """Compact ``Item1 > Item2 > ...`` with per-step delta + gold -
        the form a coach prompt / dashboard pill wants."""
        if not self.order:
            return "none"
        return " > ".join(
            f"{s.item_name}(+{s.delta:.0f}{s.unit},{s.gold}g)"
            for s in self.order
        )

    def to_dict(self) -> dict:
        return {
            "champion": self.champion,
            "archetype": self.archetype,
            "scorer": self.scorer,
            "mode": self.mode,
            "level": self.level,
            "owned": list(self.owned),
            "order": [s.to_dict() for s in self.order],
            "order_str": self.order_str(),
            "context": dict(self.context),
            "unique_passive_safe": self.unique_passive_safe,
            "notes": list(self.notes),
        }


def _pick_top_safe(
    rows: list[dict],
    incumbent_id: Optional[str] = None,
    incumbent_margin: float = 0.03,
) -> tuple[Optional[dict], str, str]:
    """Return (chosen_row, excluded_family, excluded_example).

    Chosen row is the highest-ranked candidate that does NOT share a dead
    unique (rows are already engine-sorted). With the engine default
    (``filter_shared_uniques=True``) no row is flagged, so this is just
    ``rows[0]``; the skip path only matters if a caller turned the engine
    filter off. The first skipped-for-family row's engine-supplied
    ``dead_unique_key`` / ``item_name`` are surfaced as the slot's
    exclusion example (no family map fabricated here).

    Incumbent hysteresis (2026-07-06): when the caller passes ``incumbent_id``
    (the item currently DISPLAYED in this slot) and it is still a legal,
    positive-delta candidate, keep it unless the top challenger beats it by more
    than ``incumbent_margin`` (relative delta). This damps the greedy top-1 flip
    (PD -> Kraken) when a level tick crosses two items that are within noise.
    ADDITIVE: with ``incumbent_id=None`` (every existing caller) the function is
    byte-identical to the old ``rows[0]`` behavior.
    """
    excluded_family = ""
    excluded_example = ""
    chosen: Optional[dict] = None
    for r in rows:
        if r.get("shares_dead_unique"):
            if not excluded_family:
                excluded_family = str(r.get("dead_unique_key") or "")
                excluded_example = str(r.get("item_name") or "")
            continue
        chosen = r
        break
    if chosen is None:
        return None, excluded_family, excluded_example

    if incumbent_id is not None and str(incumbent_id) != str(chosen.get("item_id")):
        inc = next(
            (
                r
                for r in rows
                if str(r.get("item_id")) == str(incumbent_id)
                and not r.get("shares_dead_unique")
            ),
            None,
        )
        if inc is not None:
            inc_delta = float(inc.get("delta", inc.get("delta_dps", 0.0)) or 0.0)
            top_delta = float(chosen.get("delta", chosen.get("delta_dps", 0.0)) or 0.0)
            # Keep a still-valuable incumbent unless the challenger is decisively
            # better; a non-positive incumbent (a regression) always yields.
            if inc_delta > 0.0 and top_delta <= inc_delta * (1.0 + incumbent_margin):
                return inc, excluded_family, excluded_example

    return chosen, excluded_family, excluded_example


def plan_build_order(
    champion: str,
    archetype: str,
    *,
    level: int,
    owned_item_ids: Iterable[str],
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    slots: int = DEFAULT_SLOTS,
    augments: Optional[Iterable[str]] = None,
    sort_by: str = "delta",
    timeout: Optional[float] = None,
    rank_kwargs: Optional[dict] = None,
    rank_fn: Optional[Callable[..., Optional[dict]]] = None,
    inject_boots: bool = True,
    incumbent: Optional[Iterable[str]] = None,
    incumbent_margin: float = 0.03,
    assume_boot_utility: bool = False,
    enemy_champions: Optional[Iterable[str]] = None,
    score_by: str = SCORE_BY_DEFAULT,
) -> Optional[BuildOrderResult]:
    """Plan a contextual, match-specific item ORDER for the remaining slots.

    ``owned_item_ids`` is the build so far (already-purchased). The order
    fills the remaining ``slots - len(owned)`` positions by greedy
    forward selection: each slot is the highest-delta legal item *given
    everything picked so far + the enemy context*, with the unique-passive
    no-double rule enforced by the engine's own dedup (see module docstring).

    Returns ``None`` when the engine is unreachable or ``champion`` is
    blank (mirrors ``dispatch_for_coach``). An engine that is up but has
    nothing left to recommend yields a result with a short ``order`` and
    an explanatory note - not ``None``.

    ``rank_fn`` defaults to
    ``core.daemon_slayer_client.rank_for_primary_archetype`` and is
    injectable for headless tests. ``rank_kwargs`` is splatted into every
    ranker call for scorer-specific extras (``enemy_ad_share`` /
    ``alpha`` / ``max_priority`` / ``combo_sequence`` / ``only_item_ids``
    / ...); the dispatcher silently ignores knobs irrelevant to the
    routed scorer.

    ``enemy_champions`` (default None, A-39) is the enemy roster, forwarded ONLY
    to :func:`_select_boots` so the boot-utility ON path can feed its CC axis from
    real per-champion lockdown data instead of the v1 AP-share proxy. It is NOT
    splatted into the ranker, and None (every pre-A-39 caller) is byte-identical.

    ``score_by`` (default ``"blended"``, A-21 / RM-90 S1) selects the EHP
    objective the TANK route ranks on: ``"blended"`` (own EHP - today),
    ``"cc_blended"``, or ``"team_blended"`` (Term A - also prices the EHP an
    item confers on teammates, gated per champion by ``_champion_ally_reach``).
    It is emitted into the ranker call ONLY when non-default and only when it is
    a recognized value, so every existing caller is byte-identical and an
    unrecognized string can never reach the engine as a 400. A value threaded
    the old way through ``rank_kwargs`` still works; this named parameter wins
    when both are supplied.
    """
    if not champion or not str(champion).strip():
        return None

    if rank_fn is None:
        try:
            from core.daemon_slayer_client import rank_for_primary_archetype as rank_fn  # type: ignore
        except Exception as exc:  # noqa: BLE001
            logger.debug("build_order: cannot import rank_for_primary_archetype: %s", exc)
            return None

    arch = (archetype or "carry").strip().lower() or "carry"
    owned: list[str] = [str(i) for i in (owned_item_ids or ()) if str(i).strip()]
    extra: dict = dict(rank_kwargs or {})

    # A-21 S1: resolve the EHP objective ONCE. Unrecognized -> treated as the
    # default (logged, never raised, never forwarded) so a typo degrades to
    # today's behavior instead of a 400 that reads as "engine down".
    score_by_resolved = str(score_by or SCORE_BY_DEFAULT)
    if score_by_resolved not in SCORE_BY_VALUES:
        logger.debug(
            "build_order: ignoring unrecognized score_by=%r", score_by_resolved
        )
        score_by_resolved = SCORE_BY_DEFAULT

    context = {
        "target_armor": float(target_armor),
        "target_mr": float(target_mr),
        "target_max_hp": float(target_max_hp),
        "target_bonus_hp": float(target_bonus_hp),
        "mode": str(mode),
    }
    result = BuildOrderResult(
        champion=str(champion),
        archetype=arch,
        scorer="",
        mode=str(mode),
        level=int(level),
        owned=list(owned),
        context=context,
    )

    remaining = int(slots) - len(owned)
    if remaining <= 0:
        result.notes.append(
            f"build already full ({len(owned)}/{slots}) - no order to plan"
        )
        return result

    accumulated: list[str] = list(owned)
    # 2026-07-25 (W3): duplicate rejection keys on the CANONICAL item id, not the
    # raw catalog id. DDragon ships one item under several ids (SR canonical +
    # mode-mirror / alias forms), so a raw compare let the same item take two
    # slots - the shipped 16.14.1 SR table had Viego on 3004 + 323004 (both
    # Manamune) and Samira on 6676 + 667666 (both The Collector), i.e. real
    # FIVE-item builds. The engine's own owned-id skip compares raw ids too, so
    # the alias is offered as a fresh candidate and the planner must be the one
    # to reject it. See core/build_planner/kit_synergy.canonical_item_id.
    picked_ids: set[str] = {_canonical_id(i) for i in owned}

    # 2026-05-23 (item 164b): boots-slot pre-determination. Boots get
    # inserted INSIDE the iteration loop (after slot 1) so the engine
    # sees boots in item_ids when scoring slots 3..N - subsequent picks
    # are scored against a build that genuinely commits to boots. Reduces
    # engine_picks_count by 1 to free a total-slot for boots. Skipped for
    # bootsless-champion exception set + when owned already includes a
    # boots family entry.
    champ_name_norm = str(champion).strip()
    boots_already_owned = any(str(iid) in _BOOTS_IDS for iid in owned)
    boots_skip_champ = champ_name_norm in _BOOTSLESS_CHAMPS
    boots_needed = (
        bool(inject_boots)
        and not boots_already_owned
        and not boots_skip_champ
        and remaining >= 2  # need at least 2 slots to inject boots at slot 2
    )
    boots_inserted = False
    if boots_needed:
        # Boots consume one of the remaining slots; engine picks one less.
        engine_picks_count = remaining - 1
    else:
        engine_picks_count = remaining
    boots_id: str = ""
    boots_name: str = ""
    if boots_needed:
        boots_id, boots_name = _select_boots(
            arch,
            float(target_armor),
            float(target_mr),
            mode=str(mode),
            enemy_ad_share=float(extra.get("enemy_ad_share", 0.5)),
            enemy_ap_share=float(extra.get("enemy_ap_share", 0.5)),
            assume_boot_utility=assume_boot_utility,
            champion=champ_name_norm,
            enemy_champions=enemy_champions,
        )

    # next_slot tracks the 1-based slot for the NEXT entry appended to
    # result.order. Engine picks + boots both increment it.
    next_slot = 1

    # Incumbent hysteresis (2026-07-06): the caller may pass the currently
    # DISPLAYED build (item_ids in order) so slot i keeps its shown item unless a
    # challenger beats it by incumbent_margin - damps the PD -> Kraken flip on a
    # level tick. None (default, every existing caller) -> no incumbent ->
    # byte-identical greedy rows[0]. Drop the injected boots id (+ any owned) so
    # the remaining ids line up 1:1 with the engine picks (boots is not one).
    incumbent_ids = [str(i) for i in (incumbent or ()) if str(i).strip()]
    if boots_id:
        incumbent_ids = [i for i in incumbent_ids if i != boots_id]
    if incumbent_ids:
        _owned_set = {str(i) for i in owned_item_ids}
        incumbent_ids = [i for i in incumbent_ids if i not in _owned_set]

    for engine_call_i in range(1, engine_picks_count + 1):
        call_kwargs = dict(
            level=int(level),
            item_ids=list(accumulated),
            mode=str(mode),
            target_armor=float(target_armor),
            target_mr=float(target_mr),
            target_max_hp=float(target_max_hp),
            target_bonus_hp=float(target_bonus_hp),
            sort_by=str(sort_by),
            # Hard rule lives here: the engine's source-of-truth dedup
            # excludes any candidate whose unique-passive family is
            # already in ``accumulated``. Iterating means it holds for
            # the whole sequence. Never flip this off in the planner.
            filter_shared_uniques=True,
        )
        if augments:
            call_kwargs["augments"] = list(augments)
        if timeout is not None:
            call_kwargs["timeout"] = float(timeout)
        call_kwargs.update(extra)
        # Caller-supplied rank_kwargs must never weaken the rule.
        call_kwargs["filter_shared_uniques"] = True
        # A-21 S1: DEFAULT-OFF forward. Absent (not "blended") when unset, so an
        # injected rank_fn without **kwargs keeps working; the named parameter
        # is applied AFTER ``extra`` so it wins over a rank_kwargs backdoor.
        if score_by_resolved != SCORE_BY_DEFAULT:
            call_kwargs["score_by"] = score_by_resolved

        try:
            out = rank_fn(champion, arch, **call_kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "build_order: rank_fn raised at engine call %d: %s",
                engine_call_i, exc,
            )
            out = None

        if out is None:
            if engine_call_i == 1:
                # Engine unreachable before any pick - same contract as
                # dispatch_for_coach: signal None so callers fall back.
                return None
            result.notes.append(
                f"engine stopped responding after engine call {engine_call_i - 1}; "
                f"order truncated"
            )
            break

        scorer = str(out.get("scorer") or "dps")
        if not result.scorer:
            result.scorer = scorer
        rows = [r for r in (out.get("ranked") or []) if r.get("item_id")]
        # Defensive: the engine already skips owned ids, but never let a
        # duplicate slip into the sequence.
        rows = [r for r in rows if _canonical_id(r.get("item_id")) not in picked_ids]
        if not rows:
            result.notes.append(
                f"no further legal items after engine call {engine_call_i - 1} "
                f"(scorer={scorer}) - order complete at "
                f"{len(result.order)} new item(s)"
            )
            break

        inc_id = (
            incumbent_ids[engine_call_i - 1]
            if (engine_call_i - 1) < len(incumbent_ids)
            else None
        )
        chosen, excl_family, excl_example = _pick_top_safe(
            rows, incumbent_id=inc_id, incumbent_margin=float(incumbent_margin)
        )
        if chosen is None:
            result.notes.append(
                f"engine call {engine_call_i}: all candidates collide with a "
                f"locked unique passive - order complete"
            )
            break
        if chosen.get("shares_dead_unique"):
            # Should be impossible (filter on) - record + stop rather
            # than emit a rule-violating pick.
            result.unique_passive_safe = False
            result.notes.append(
                f"engine call {engine_call_i}: engine returned only dead-unique "
                f"rows despite filter - aborting to honor no-double rule"
            )
            break

        item_id = str(chosen.get("item_id"))
        delta = float(chosen.get("delta", chosen.get("delta_dps", 0.0)) or 0.0)
        step = BuildStep(
            slot=next_slot,
            item_id=item_id,
            item_name=str(chosen.get("item_name") or item_id),
            delta=delta,
            gold=int(chosen.get("gold", 0) or 0),
            scorer=scorer,
            unit=_UNIT_SUFFIX.get(scorer, "delta"),
            excluded_family=excl_family,
            excluded_example=excl_example,
            locked_family=str(chosen.get("unique_passive_key") or ""),
        )
        result.order.append(step)
        accumulated.append(item_id)
        picked_ids.add(_canonical_id(item_id))
        next_slot += 1

        # 2026-05-23 (item 164b): boots inject AFTER slot 1 - the engine
        # has now committed the first big item; boots ride next so the
        # remaining engine calls (slots 3..N) score against a build that
        # genuinely includes boots in item_ids. Pre-loop computed
        # engine_picks_count -= 1 to keep total order length == slots.
        if boots_needed and not boots_inserted and engine_call_i == 1:
            boots_step = BuildStep(
                slot=next_slot,
                item_id=boots_id,
                item_name=boots_name,
                # delta/gold/scorer are synthetic - boots aren't engine-
                # ranked at this layer; the rendered card uses scorer
                # = "boots" to surface the synthetic provenance.
                delta=0.0,
                gold=900,
                scorer="boots",
                unit="boots",
                excluded_family="",
                excluded_example="",
                locked_family="",
            )
            result.order.append(boots_step)
            accumulated.append(boots_id)
            picked_ids.add(_canonical_id(boots_id))
            next_slot += 1
            boots_inserted = True
            result.notes.append(
                f"boots slot pinned at position {boots_step.slot}: "
                f"{boots_name} (id={boots_id}, arch={arch}, "
                f"armor={target_armor:.0f}, mr={target_mr:.0f})"
            )

    if not result.scorer:
        result.scorer = "dps"
    # 2026-05-23 (item 164b): note when boots were intentionally
    # skipped (bootsless-champion exception).
    if boots_skip_champ:
        result.notes.append(
            f"boots slot skipped: {champ_name_norm} is in the bootsless-"
            f"champion exception set (operator-flagged)"
        )
    if result.order:
        result.notes.append(
            f"planned {len(result.order)} item(s) by greedy forward "
            f"selection (scorer={result.scorer}, "
            f"context armor={context['target_armor']:.0f}/"
            f"mr={context['target_mr']:.0f}/"
            f"hp={context['target_max_hp']:.0f}); unique-passive no-double "
            f"{'held' if result.unique_passive_safe else 'VIOLATED'}"
        )
    return result
