"""Sustain / vamp-throughput scorer (ENGINE 1.110.0, item 298).

The ninth scored axis alongside DPS / burst / EHP / ability-DPS /
healing-throughput / offensive CC-output (item 294) / mobility (item 297) /
the six archetype scorers. It quantifies how much effective HP a champion
CLAWS BACK during a fight by converting damage to health - lifesteal,
omnivamp, spellvamp, channelled drains - plus self HP-regeneration steroids,
into a single ``sustain_score``.

This is distinct from the healing-throughput axis (``ability_hps`` and the
``_passive_heal_overrides`` registry), which owns flat / ratio ABILITY heals
and shields. This axis owns DAMAGE-CONVERSION sustain (a fraction of damage
dealt returned as HP) and self-regen buffs - the lifelong attrition advantage
those mechanics give, which the heal-throughput axis never measured.

Purely ADDITIVE: a new standalone scorer and a new ``/sustain`` route. It reads
no existing scorer and is read by none, so every existing route is byte-identical
(the opt-in is the new endpoint itself - inert until a caller invokes it, the
section-5 "default inert" contract for a brand-new surface). Wiring it into a
live draft / attrition / dive-threat coach surface is the separate Phase-D step.

Normalisation (everything reduces to effective HP recovered over a fight, then
to sustain-units where ``1.0`` unit = ``_SUSTAIN_HP_UNIT`` HP):
  * vamp kinds (OMNIVAMP / LIFESTEAL / SPELLVAMP / DRAIN) -
    ``hp = vamp_pct * _REF_FIGHT_DAMAGE`` (the share of a representative fight's
    damage output that comes back as health).
  * REGEN - ``hp = pct_max_hp * _REF_MAX_HP + flat_hp`` (a self HP-regen steroid
    credited over a representative fight window).
  * ``sustain_units = hp / _SUSTAIN_HP_UNIT``.

Schema (mirrors the Mobility / CcOutput surface):
  * ``SustainEntry`` - one registry row: spell_key, kind, the raw magnitude
    (``vamp_pct`` for a vamp kind, ``pct_max_hp`` + ``flat_hp`` for a regen
    steroid), the drain ``duration_s`` (informational), and a ``conditional``
    flag. ``conditional=True`` means the sustain only fires on a gate (target
    below an HP threshold, a form / ult-active window, reset-on-takedown, a
    stack requirement, monsters-only) and is credited at the operator-tunable
    ``_SUSTAIN_CONDITIONAL_PROB`` midpoint.
  * ``SustainSpellEntry`` - one scored spell: normalised units, kind weight,
    weighted units (= units * weight, times the conditional midpoint when gated).
  * ``SustainResult`` - the aggregate: ``sustain_score`` (unconditional weighted
    units), ``conditional_sustain_score`` (gated weighted units at the midpoint),
    ``total_sustain_score`` (their sum), and ``raw_sustain_units`` (unweighted
    unconditional units, the kind-agnostic comparable quantity).

Magnitudes and kinds are hand-authored from the verbatim patch-16.11 ability
prose by the item-298 ten-channel roster fan-out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from ._hsp_amp import sum_wielder_hsp_pct

_SPELL_ORDER = ("P", "Q", "W", "E", "R")

# Sustain-kind -> weight. Hand-authored, operator-tunable. Five tiers by how
# reliably the sustain converts a fight's damage / time into health:
#   1.00 OMNIVAMP  - heals off ALL damage (AA + abilities + items); always live
#   0.80 LIFESTEAL - heals off auto-attack / on-hit damage; gated on auto-ing
#   0.80 DRAIN     - channelled % of damage dealt; strong but interruptible
#   0.60 SPELLVAMP - heals off ability damage only; bursty, cooldown-bound
#   0.40 REGEN     - a self HP-regen steroid; steady but slow, often peace-only
_SUSTAIN_KIND_WEIGHT: dict[str, float] = {
    "OMNIVAMP": 1.0,
    "LIFESTEAL": 0.8,
    "DRAIN": 0.8,
    "SPELLVAMP": 0.6,
    "REGEN": 0.4,
}

# A representative single-fight damage-dealt total. A vamp fraction returns this
# share of it as HP (20% omnivamp over a 2000-damage fight = 400 HP).
_REF_FIGHT_DAMAGE = 2000.0
# A representative max HP. A %-max-HP regen steroid is credited against this.
_REF_MAX_HP = 2200.0
# 1.0 sustain-unit = this many effective HP recovered over the fight window.
_SUSTAIN_HP_UNIT = 300.0
# A gated (conditional) sustain source fires only some of the time - it is
# credited at this availability midpoint, the mobility / cc_output shape.
_SUSTAIN_CONDITIONAL_PROB = 0.5


@dataclass(frozen=True)
class SustainEntry:
    """One registry row: a champion spell that returns HP to the caster.

    ``spell`` is one of ``{"P","Q","W","E","R"}``. ``kind`` is a key of
    ``_SUSTAIN_KIND_WEIGHT``. For a vamp kind ``vamp_pct`` is the max-rank decimal
    fraction of damage converted to HP (0.20 = 20%); for ``REGEN`` ``pct_max_hp``
    is the decimal fraction of max HP and ``flat_hp`` the flat HP recovered over a
    representative fight window. ``duration_s`` is the drain channel length
    (informational). ``conditional`` is True when the sustain only fires on a gate.
    """

    spell: str
    kind: str
    vamp_pct: float = 0.0
    pct_max_hp: float = 0.0
    flat_hp: float = 0.0
    duration_s: float = 0.0
    conditional: bool = False


def _normalized_units(entry: SustainEntry) -> float:
    """Reduce a registry row to effective-HP-normalised sustain units.

    A vamp kind returns ``vamp_pct`` of a representative fight's damage as HP; a
    regen steroid returns ``pct_max_hp`` of a representative max HP plus its flat
    term. Both divided by ``_SUSTAIN_HP_UNIT``.
    """
    if entry.kind == "REGEN":
        hp = entry.pct_max_hp * _REF_MAX_HP + entry.flat_hp
    else:
        hp = entry.vamp_pct * _REF_FIGHT_DAMAGE
    return hp / _SUSTAIN_HP_UNIT


def _build_sustain_registry() -> dict[str, tuple[SustainEntry, ...]]:
    """Build champion_id -> tuple[SustainEntry] via an append builder.

    Uses ``raw.setdefault(champ, []).append(...)`` so a champion can carry
    several sustain spells without dict-literal collision (the mobility /
    cc_output builder pattern). Runs ONCE at import.
    """
    raw: dict[str, list[SustainEntry]] = {}

    def add(
        champ: str,
        spell: str,
        kind: str,
        *,
        vamp_pct: float = 0.0,
        pct_max_hp: float = 0.0,
        flat_hp: float = 0.0,
        duration_s: float = 0.0,
        cond: bool = False,
    ) -> None:
        raw.setdefault(champ, []).append(
            SustainEntry(
                spell=spell,
                kind=kind,
                vamp_pct=float(vamp_pct),
                pct_max_hp=float(pct_max_hp),
                flat_hp=float(flat_hp),
                duration_s=float(duration_s),
                conditional=bool(cond),
            )
        )

    # Aatrox
    add("Aatrox", "P", "OMNIVAMP", vamp_pct=1.0)
    add("Aatrox", "E", "SPELLVAMP", vamp_pct=0.16, cond=True)
    # Alistar
    add("Alistar", "P", "REGEN", pct_max_hp=0.05, cond=True)
    # Ambessa
    add("Ambessa", "R", "SPELLVAMP", vamp_pct=0.15)
    # Aphelios
    add("Aphelios", "P", "LIFESTEAL", vamp_pct=0.1775, cond=True)
    # Aurora
    add("Aurora", "P", "REGEN", flat_hp=20.0, cond=True)
    # Belveth
    add("Belveth", "E", "DRAIN", vamp_pct=0.2, duration_s=1.5)
    # Briar
    add("Briar", "P", "SPELLVAMP", vamp_pct=0.25)
    add("Briar", "W", "SPELLVAMP", vamp_pct=0.4, cond=True)
    add("Briar", "E", "REGEN", pct_max_hp=0.16, cond=True)
    add("Briar", "R", "LIFESTEAL", vamp_pct=0.2, cond=True)
    # Camille
    add("Camille", "W", "SPELLVAMP", vamp_pct=1.0, cond=True)
    # Darius
    add("Darius", "Q", "REGEN", pct_max_hp=0.51, cond=True)
    # DrMundo
    add("DrMundo", "P", "REGEN", pct_max_hp=0.023)
    add("DrMundo", "R", "REGEN", pct_max_hp=0.18)
    # Evelynn
    add("Evelynn", "P", "REGEN", flat_hp=150.0, cond=True)
    # Fiddlesticks
    add("Fiddlesticks", "W", "DRAIN", vamp_pct=0.55, duration_s=2.0)
    # Garen
    add("Garen", "P", "REGEN", pct_max_hp=0.0606, cond=True)
    # Gragas
    add("Gragas", "P", "REGEN", pct_max_hp=0.055)
    # Gwen
    add("Gwen", "P", "SPELLVAMP", vamp_pct=0.5, cond=True)
    # Hecarim
    add("Hecarim", "W", "DRAIN", vamp_pct=0.25, duration_s=4.0)
    # KSante
    add("KSante", "R", "OMNIVAMP", vamp_pct=0.2, cond=True)
    # Kayn
    add("Kayn", "P", "SPELLVAMP", vamp_pct=0.25, cond=True)
    add("Kayn", "R", "DRAIN", vamp_pct=0.75, duration_s=2.0, cond=True)
    # LeeSin
    add("LeeSin", "W", "LIFESTEAL", vamp_pct=0.26, cond=True)
    # Lillia
    add("Lillia", "P", "REGEN", flat_hp=540.0, cond=True)
    # Lissandra
    add("Lissandra", "R", "REGEN", flat_hp=200.0, cond=True)
    # Maokai
    add("Maokai", "P", "REGEN", pct_max_hp=0.128, cond=True)
    # MasterYi
    add("MasterYi", "W", "REGEN", flat_hp=330.0, cond=True)
    # MonkeyKing
    add("MonkeyKing", "P", "REGEN", pct_max_hp=0.0126, cond=True)
    # Mordekaiser
    add("Mordekaiser", "W", "SPELLVAMP", vamp_pct=0.2025, cond=True)
    # Morgana
    add("Morgana", "P", "SPELLVAMP", vamp_pct=0.18)
    # Nasus
    add("Nasus", "P", "LIFESTEAL", vamp_pct=0.24)
    # Nilah
    add("Nilah", "Q", "LIFESTEAL", vamp_pct=0.2, cond=True)
    add("Nilah", "R", "DRAIN", vamp_pct=0.5, duration_s=1.0, cond=True)
    # Nocturne
    add("Nocturne", "P", "REGEN", flat_hp=30.0)
    # Olaf
    add("Olaf", "P", "LIFESTEAL", vamp_pct=0.25, cond=True)
    # RekSai
    add("RekSai", "P", "REGEN", pct_max_hp=0.2, cond=True)
    # Sett
    add("Sett", "P", "REGEN", flat_hp=114.0, cond=True)
    # Singed
    add("Singed", "R", "REGEN", flat_hp=57.0)
    # Sion
    add("Sion", "P", "LIFESTEAL", vamp_pct=1.0, cond=True)
    # Soraka
    add("Soraka", "Q", "REGEN", flat_hp=120.0, cond=True)
    # Swain
    add("Swain", "P", "REGEN", pct_max_hp=0.06, cond=True)
    add("Swain", "R", "DRAIN", vamp_pct=0.6, duration_s=8.0)
    # TahmKench
    add("TahmKench", "E", "REGEN", pct_max_hp=0.1, cond=True)
    # Trundle
    add("Trundle", "P", "REGEN", pct_max_hp=0.055, cond=True)
    add("Trundle", "R", "DRAIN", vamp_pct=1.0, duration_s=4.0)
    # Tryndamere
    add("Tryndamere", "Q", "REGEN", flat_hp=300.0, cond=True)
    # Udyr
    add("Udyr", "W", "LIFESTEAL", vamp_pct=0.4, cond=True)
    # Viego
    add("Viego", "Q", "LIFESTEAL", vamp_pct=1.35, cond=True)
    # Vladimir
    add("Vladimir", "W", "DRAIN", vamp_pct=0.3, duration_s=2.0)
    # Warwick
    add("Warwick", "P", "OMNIVAMP", vamp_pct=1.0, cond=True)
    add("Warwick", "Q", "SPELLVAMP", vamp_pct=0.75)
    add("Warwick", "R", "DRAIN", vamp_pct=1.0, duration_s=1.5)
    # XinZhao
    add("XinZhao", "P", "REGEN", pct_max_hp=0.04)
    # Zac
    add("Zac", "P", "REGEN", pct_max_hp=0.08, cond=True)

    return {champ: tuple(entries) for champ, entries in raw.items()}


_SUSTAIN_REGISTRY: dict[str, tuple[SustainEntry, ...]] = (
    _build_sustain_registry()
)


@dataclass(frozen=True)
class SustainSpellEntry:
    """One scored sustain spell for a champion.

    ``sustain_units`` is the effective-HP-normalised magnitude (pre-weight);
    ``weighted_units`` = ``sustain_units * kind_weight`` for an unconditional
    entry, times ``_SUSTAIN_CONDITIONAL_PROB`` when ``conditional`` is True.
    """

    spell_key: str
    kind: str
    sustain_units: float
    kind_weight: float
    conditional: bool
    weighted_units: float

    def to_dict(self) -> dict:
        return {
            "spell_key": self.spell_key,
            "kind": self.kind,
            "sustain_units": round(self.sustain_units, 4),
            "kind_weight": self.kind_weight,
            "conditional": self.conditional,
            "weighted_units": round(self.weighted_units, 4),
        }


@dataclass(frozen=True)
class SustainResult:
    """Aggregate damage-conversion + regen sustain for one champion.

    ``sustain_score`` sums ``weighted_units`` over the UNCONDITIONAL spells;
    ``conditional_sustain_score`` sums them over the gated spells (already
    discounted by the availability midpoint); ``total_sustain_score`` is their
    sum. ``raw_sustain_units`` is the unweighted unconditional unit sum (the
    kind-agnostic comparable quantity). Returns all-zero with an empty
    ``spells`` tuple for an unregistered or blank champion (never raises).
    """

    champion: str
    mode: str
    sustain_score: float
    conditional_sustain_score: float
    total_sustain_score: float
    raw_sustain_units: float
    spells: tuple[SustainSpellEntry, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion": self.champion,
            "mode": self.mode,
            "sustain_score": round(self.sustain_score, 4),
            "conditional_sustain_score": round(
                self.conditional_sustain_score, 4
            ),
            "total_sustain_score": round(self.total_sustain_score, 4),
            "raw_sustain_units": round(self.raw_sustain_units, 4),
            "spells": [s.to_dict() for s in self.spells],
        }


def _empty_result(champion: str, mode: str) -> SustainResult:
    return SustainResult(
        champion=champion,
        mode=mode,
        sustain_score=0.0,
        conditional_sustain_score=0.0,
        total_sustain_score=0.0,
        raw_sustain_units=0.0,
        spells=(),
    )


def _spell_sort_key(entry: SustainEntry) -> tuple[int, str]:
    try:
        return (_SPELL_ORDER.index(entry.spell), entry.spell)
    except ValueError:
        return (len(_SPELL_ORDER), entry.spell)


def compute_sustain(
    champion: str,
    mode: str = "SR",
    item_ids: Optional[Iterable[str | int]] = None,
    assume_hsp_amp: bool = False,
    assume_scaling_hsp_grants: bool = False,
) -> SustainResult:
    """Aggregate a champion's damage-conversion + regen sustain into a score.

    Reads ``_SUSTAIN_REGISTRY``. Each registered sustain spell is reduced to
    effective-HP-normalised units (``_normalized_units``) and scaled by the
    per-kind weight (``_SUSTAIN_KIND_WEIGHT``); conditional spells are discounted
    by ``_SUSTAIN_CONDITIONAL_PROB``. ``mode`` is carried on the result for parity
    with the other scorers but does not change output today (self-sustain is
    target-independent).

    ENGINE 1.171.0 (R60, 2026-07-02): the wielder Heal/Shield Power (HSP) seam.
    ``assume_hsp_amp`` (DEFAULT-OFF) plus ``item_ids`` sums the wielder's own
    ``heal_shield_amp_pct`` (Redemption / Mikael / Ardent / Moonstone / Staff of
    Flowing Water) and amplifies the wielder's kit SELF-HEAL sustain by
    ``(1 + hsp_pct)``. HSP amplifies heals/shields the wielder applies but does
    NOT amplify vamp (LIFESTEAL / OMNIVAMP / SPELLVAMP / DRAIN), so the amp scopes
    strictly to the ``REGEN`` kind - a vamp-only champion is byte-identical even
    with the seam ON. ``assume_hsp_amp=False`` (default) or an empty ``item_ids``
    -> hsp_pct 0.0 -> BYTE-IDENTICAL to 1.170.0. The raw ``raw_sustain_units``
    (kind-agnostic pre-weight quantity) is left UNamped. The live default-ON flip
    is operator-gated (docs/LIVE_GAME_GATED_SYNC.md).

    RM-200: ``assume_scaling_hsp_grants`` (DEFAULT-OFF) folds the SCALING-clause
    HSP grants (Dawncore 6621's First Light) into that same additive sum. It is a
    MODIFIER of ``assume_hsp_amp``, not an independent switch - the helper is
    reached only inside that branch, so arming it alone is byte-identical.

    Returns an all-zero ``SustainResult`` (empty ``spells``) when the champion
    is blank / None or absent from the registry; never raises.
    """
    safe_mode = mode if mode else "SR"
    if not champion:
        return _empty_result("", safe_mode)
    entries = _SUSTAIN_REGISTRY.get(champion)
    if not entries:
        return _empty_result(champion, safe_mode)

    hsp_mult = 1.0
    if assume_hsp_amp and item_ids:
        # RM-200: the scaling half rides the same additive sum. Nested inside the
        # flat lane's branch, so arming it alone leaves hsp_mult at 1.0.
        hsp_mult = 1.0 + sum_wielder_hsp_pct(
            item_ids, assume_scaling_hsp_grants=assume_scaling_hsp_grants
        )

    scored: list[SustainSpellEntry] = []
    sustain = 0.0
    conditional_sustain = 0.0
    raw_uncond_units = 0.0
    for entry in sorted(entries, key=_spell_sort_key):
        weight = _SUSTAIN_KIND_WEIGHT.get(entry.kind, 0.0)
        units = _normalized_units(entry)
        base_weighted = units * weight
        # R60: HSP amplifies the self-heal (REGEN) sustain only. Vamp kinds
        # (LIFESTEAL / OMNIVAMP / SPELLVAMP / DRAIN) are not HSP-affected.
        if entry.kind == "REGEN":
            base_weighted *= hsp_mult
        if entry.conditional:
            weighted = base_weighted * _SUSTAIN_CONDITIONAL_PROB
            conditional_sustain += weighted
        else:
            weighted = base_weighted
            sustain += weighted
            raw_uncond_units += units
        scored.append(
            SustainSpellEntry(
                spell_key=entry.spell,
                kind=entry.kind,
                sustain_units=units,
                kind_weight=weight,
                conditional=entry.conditional,
                weighted_units=weighted,
            )
        )

    return SustainResult(
        champion=champion,
        mode=safe_mode,
        sustain_score=sustain,
        conditional_sustain_score=conditional_sustain,
        total_sustain_score=sustain + conditional_sustain,
        raw_sustain_units=raw_uncond_units,
        spells=tuple(scored),
    )


__all__ = [
    "SustainEntry",
    "SustainResult",
    "SustainSpellEntry",
    "compute_sustain",
    "_SUSTAIN_KIND_WEIGHT",
    "_SUSTAIN_CONDITIONAL_PROB",
    "_SUSTAIN_REGISTRY",
    "_REF_FIGHT_DAMAGE",
    "_REF_MAX_HP",
    "_SUSTAIN_HP_UNIT",
]
