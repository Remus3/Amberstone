# arch: cc_conditional ally-pairing join (which allies can enable a conditional CC) | section=daemon_slayer | frozen=no
"""Ally CC-pairing - which conditional CC entries an ALLY can set up.

CS1 (operator batch 2026-06-08). A pure presentation JOIN over data the
engine already owns - NO new compute, NO schema lift, NO new external
dependency, NO ENGINE math change (no scoring output moves; this module
is read-only over the existing ``cc_conditional`` registry):

  * CONDITIONAL CC (which ally ability has a probability-gated lockdown
    AND what condition gates it): ``get_conditional_entries`` from
    ``cc_conditional.py``. Each ``ConditionalCcEntry`` carries the
    canonical DDragon id, the Q/W/E/R slot, the ``cc_kind`` (stun /
    root / fear / ...), the max-rank durations, and a ``condition`` tag
    (one of the ``COND_*`` constants).

The existing ``cc_conditional`` consumers (cc_pressure / compute_ehp /
compute_hybrid / routes_cc_conditional_pressure / coach prompt /
cooldown_watch) all reduce the registry to a SCALAR - the probability-
weighted ``conditional_cc_seconds`` ratio (the balance chip) or the
single highest-threat card (cooldown-watch). NONE of them surface the
PAIRING data: for the operator's OWN team, which conditional CC entries
are ones a TEAMMATE can set up, and what the teammate needs to do.

That is the gap CS1 fills. The ``condition`` tag is the join key: some
conditions are SELF-only (the picking champion sets them up alone -
``nth_hit`` stack accumulation, a ``channel`` they complete, a
``devour`` they cast, a ``gold_card`` they pre-select) while others are
ALLY-ENABLABLE (a teammate's engage / displacement / debuff creates the
condition the conditional CC needs):

  * ``dual_enemy``      - the CC needs 2+ enemies grouped (Sett E
                          Facebreaker). A teammate engage / hard-CC that
                          bunches enemies together enables it.
  * ``debuffed_target`` - the CC fires only on a target already carrying
                          a debuff / mark (Vex E fear, Brand Q stun on a
                          Blaze-stacked target). A teammate who lands the
                          first CC / debuff sets up the follow-up.
  * ``terrain``         - the CC needs the target shoved into / against
                          map geometry (wall slams). A teammate
                          displacement toward a wall enables it.
  * ``traverse``        - the CC fires when an enemy DASHES / IS DISPLACED
                          over a ground zone (Taliyah E). A teammate
                          knock / pull that forces the enemy across the
                          zone enables it.

The remaining tags (``nth_hit`` / ``channel`` / ``devour`` /
``gold_card`` / ``dream_stack`` / ``frenzy_state`` / ``range_gated`` /
``mode_gated`` / ``low_hp_target``) are SELF-set: the picking champion
controls the prerequisite alone, so there is no teammate "pairing" to
surface. They are deliberately EXCLUDED from the pairing view (a
``nth_hit`` Brand R is not something a teammate sets up).

v1 honesty contract:
  * The "enabler" set is a HEURISTIC over the ally roster, NOT a claim of
    a guaranteed combo. A teammate is flagged as a plausible enabler when
    that teammate ALSO has registered first-order CC / displacement that
    plausibly creates the condition. We do NOT model exact ability
    geometry (range / cast time / target overlap) - RC has no live
    ability-geometry sim in champ-select. The flag means "this teammate
    has the tools to set this up", surfaced as a hint, not a promise.
  * The enabler check reuses the SAME two registries the rest of the
    engine reads (the unconditional ``_PER_SPELL_CC_DURATIONS`` hard-CC /
    displacement registry + the conditional registry) so it stays a pure
    read-only join. A teammate counts as an enabler when they carry ANY
    hard-CC or displacement entry (stun / root / knockup / knockback /
    pull / charm / fear / taunt / suppression). Mode-agnostic: the
    pairing fact is intrinsic to the abilities, not the map.

Public surface (mirrors ``cooldown_watch.py``'s dataclass + builder
shape so the dashboard route wires identically):

  * ``CcPairingCard``  - one ally conditional CC entry that a teammate can
    enable, plus the resolved enabler list + the human-readable setup hint.
  * ``CcPairingResult`` - the ordered cards for a roster.
  * ``compute_cc_pairing(roster)`` - the builder.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .ability_dps import _PER_SPELL_CC_DURATIONS
from .cc_conditional import get_conditional_entries

# Most raw roster entries ``_read_roster`` reads; a longer (or unbounded)
# iterable is refused whole. dashboard/_get_caps.MAX_CHAMPION_LIST is 16
# (an Arena lobby), so 64 clears every real roster with headroom.
_MAX_ROSTER_ENTRIES = 64

# Canonical Q-W-E-R order used as the deterministic spell tiebreak.
_SPELL_RANK = {"Q": 0, "W": 1, "E": 2, "R": 3}

# Condition tags an ALLY teammate can plausibly set up. Maps each tag to a
# short imperative setup hint phrased FOR the operator's team. Only entries
# whose condition is in this map surface as a pairing card; every other
# tag is SELF-set and excluded (see module docstring). Keep the hint text
# ASCII + spaced-hyphen only.
_ALLY_ENABLABLE: Dict[str, str] = {
    "dual_enemy": "needs 2+ enemies grouped - have a teammate engage to bunch them",
    "debuffed_target": "fires on a debuffed target - land a teammate CC / mark first",
    "terrain": "needs the target shoved into terrain - pair with a teammate knockback",
    "traverse": "fires when an enemy is forced across it - pair with a teammate knock / pull",
}

# cc_kind values that count a teammate as a plausible ENABLER: any hard CC
# or displacement that can create one of the ally-enablable conditions.
# Slows / blinds / grounds are deliberately excluded (they do not group,
# displace, or hard-lock a target into a follow-up). Free-form lower-cased
# match against the registries' cc_kind strings.
_ENABLER_CC_KINDS = frozenset(
    (
        "stun",
        "root",
        "snare",
        "knockup",
        "knockback",
        "pull",
        "charm",
        "fear",
        "flee",
        "taunt",
        "suppression",
        "knockaside",
        "displacement",
    )
)


@dataclass(frozen=True)
class CcPairingCard:
    """One ally conditional CC entry a teammate can set up.

    ``champion`` / ``spell`` / ``cc_kind`` / ``cc_duration_s`` mirror the
    underlying ``ConditionalCcEntry`` (``cc_duration_s`` is the max-rank
    raw conditional CC seconds, BEFORE any tenacity - this module never
    applies tenacity, matching ``cooldown_watch``). ``condition`` is the
    raw ``COND_*`` tag. ``probability`` is the operator-tunable midpoint
    that the condition lands in a fight. ``setup_hint`` is the human-
    readable imperative from ``_ALLY_ENABLABLE``. ``enablers`` is the
    ordered tuple of teammate DDragon ids on the SAME roster who carry a
    hard-CC / displacement tool that plausibly creates the condition
    (empty tuple when no teammate qualifies - the card still surfaces so
    the operator sees the setup opportunity even on a low-engage team).
    """

    champion: str
    spell: str
    cc_kind: str
    cc_duration_s: float
    condition: str
    probability: float
    setup_hint: str
    enablers: Tuple[str, ...]


@dataclass(frozen=True)
class CcPairingResult:
    """Ally CC-pairing cards for a roster.

    ``cards`` is sorted by ``cc_duration_s`` DESC (longest payoff first),
    tiebroken by champion name then canonical Q-W-E-R slot for
    determinism.
    """

    cards: Tuple[CcPairingCard, ...] = field(default_factory=tuple)


def _is_enabler_kind(cc_kind: str) -> bool:
    """True when a cc_kind string counts as a hard-CC / displacement tool."""
    if not cc_kind:
        return False
    return str(cc_kind).strip().lower() in _ENABLER_CC_KINDS


def _has_enabler_tool(champion: str) -> bool:
    """True when a champion carries ANY hard-CC / displacement ability.

    Reads BOTH registries (unconditional ``_PER_SPELL_CC_DURATIONS`` +
    the conditional registry) so a champion whose only hard CC is itself
    conditional (e.g. a knockup gated on a stack) still counts. The
    unconditional registry stores no ``cc_kind`` (it is a duration-only
    map), so ANY non-empty unconditional CC entry counts as a hard-CC
    tool - the unconditional first-order registry only holds hard CC by
    construction. The conditional registry IS kind-tagged, so it is
    filtered through ``_is_enabler_kind``.
    """
    if not champion:
        return False
    uncond = _PER_SPELL_CC_DURATIONS.get(champion) or {}
    for durs in uncond.values():
        if durs:
            return True
    for entry in get_conditional_entries(champion):
        if entry.durations_s and _is_enabler_kind(entry.cc_kind):
            return True
    return False


def _champ_name(raw: object) -> str:
    """One roster element as an exact, stripped ``str``; ``""`` to skip.

    Only ``str`` elements are champions: ``None`` / bytes / numbers / bools
    are skipped rather than ``str()``-ed (``b"Leona"`` is not ``"b'Leona'"``
    and ``True`` is not a champion). A ``str`` subclass is copied down to an
    exact ``str`` through ``str.__str__`` and stripped through ``str.strip``,
    so an overridden ``__str__`` / ``strip`` / ``__eq__`` / ``__hash__`` can
    neither raise here nor forge a registry match nor carry its own text
    into a card.
    """
    if not isinstance(raw, str):
        return ""
    return str.strip(str.__str__(raw))


def _read_roster(roster: object) -> List[str]:
    """The distinct champion names of ``roster``, in first-seen order.

    Fail-soft by contract (``compute_cc_pairing`` never raises):

      * a bare ``str`` is ONE champion, never iterated character by
        character (``"Sett"`` used to read as ``S`` / ``e`` / ``t`` / ``t``
        and silently surface zero cards);
      * ``None`` and anything non-iterable is no roster; ``bytes`` iterates
        as ints, which ``_champ_name`` skips, so it reads as no roster too;
      * at most ``_MAX_ROSTER_ENTRIES`` raw entries are read - a longer
        (or unbounded) iterable is refused as a whole, so an infinite
        iterator returns instead of hanging the caller;
      * an iterable that raises mid-iteration is refused as a whole: a
        half-read team would under-report its enablers.
    """
    if isinstance(roster, str):
        raw_items: List[object] = [roster]
    else:
        try:
            it = iter(roster)  # type: ignore[call-overload]
            raw_items = list(itertools.islice(it, _MAX_ROSTER_ENTRIES + 1))
        except Exception:  # noqa: BLE001 - caller iterables are untrusted; contract says never raises
            return []
        if len(raw_items) > _MAX_ROSTER_ENTRIES:
            return []
    out: List[str] = []
    for raw in raw_items:
        champ = _champ_name(raw)
        if champ and champ not in out:
            out.append(champ)
    return out


def _resolve_enablers(
    owner: str, distinct: List[str], tool: Dict[str, bool]
) -> Tuple[str, ...]:
    """Ordered teammates (excluding the owner) who can enable a condition.

    ``distinct`` is the de-duplicated roster from ``_read_roster`` and
    ``tool`` its per-call ``_has_enabler_tool`` memo, so a roster of N
    champions costs N registry probes instead of one per card per
    teammate. The owner champion is never its own enabler and roster
    order is preserved for a deterministic hint.
    """
    return tuple(c for c in distinct if c != owner and tool.get(c))


def compute_cc_pairing(roster: List[str]) -> CcPairingResult:
    """Ally CC-pairing cards for the operator's OWN roster.

    For each DISTINCT champion in ``roster`` (first occurrence wins;
    blank / None / non-str entries skipped; a bare string is one
    champion; see ``_read_roster``), emits one card per conditional CC
    entry whose ``condition`` is ALLY-ENABLABLE (in ``_ALLY_ENABLABLE``).
    SELF-set conditions (``nth_hit`` / ``channel`` / ``devour`` / ...) are
    skipped - there is no teammate pairing to surface for them. Each card
    carries the resolved enabler teammates from the SAME roster. Cards are
    sorted by conditional CC duration DESC, then champion, then Q-W-E-R
    slot, for a deterministic render order. Never raises; returns an empty
    result for an empty / all-unknown / all-self-set / non-iterable /
    over-long roster.
    """
    distinct = _read_roster(roster)
    tool = {c: _has_enabler_tool(c) for c in distinct}

    cards: List[CcPairingCard] = []
    for champ in distinct:
        for entry in get_conditional_entries(champ):
            hint = _ALLY_ENABLABLE.get(entry.condition)
            if hint is None:
                # SELF-set condition - no teammate pairing to surface.
                continue
            if not entry.durations_s:
                continue
            enablers = _resolve_enablers(champ, distinct, tool)
            cards.append(
                CcPairingCard(
                    champion=champ,
                    spell=entry.spell,
                    cc_kind=entry.cc_kind,
                    cc_duration_s=float(entry.durations_s[-1]),
                    condition=entry.condition,
                    probability=float(entry.probability),
                    setup_hint=hint,
                    enablers=enablers,
                )
            )
    cards.sort(
        key=lambda c: (-c.cc_duration_s, c.champion, _SPELL_RANK.get(c.spell, 9))
    )
    return CcPairingResult(cards=tuple(cards))


__all__ = [
    "CcPairingCard",
    "CcPairingResult",
    "compute_cc_pairing",
]
