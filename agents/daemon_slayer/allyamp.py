"""Ally-amplification / buff-throughput scorer (ENGINE 1.116.0, item 304).

The fifteenth scored axis alongside DPS / burst / EHP / ability-DPS /
healing-throughput / offensive CC-output (item 294) / mobility (item 297) /
sustain (item 298) / scaling (item 299) / wave-clear (item 300) / effective
threat-range (item 301) / zone-control (item 302) / objective-damage (item 303) /
the six archetype scorers. It quantifies how much a champion AMPLIFIES her
ALLIES - the shields, heals, steroids, hard-saves, and haste she GRANTS to
teammates - the team-buff-throughput dimension the prior fourteen axes never
measured. Every prior axis scores what a champion does to an ENEMY, to a piece
of GROUND, or to her OWN body (sustain, item 298); this one scores the value a
champion pumps OUTWARD into her own team. It is the mirror of the self-sustain
axis pointed at teammates instead of the self.

A high score means a champion built to make her allies stronger and harder to
kill: the dedicated enchanters (Soraka / Lulu / Janna / Sona / Nami / Yuumi /
Milio / Karma / Seraphine / Taric / Renata) and the part-time buffers (Shen /
Tahm Kench / Pyke / Sivir / Ivern / Zilean / Galio / Rakan / Bard); a low score
(or zero) means a champion who pumps no value into her team at all - a selfish
carry, assassin, or solo duelist (Master Yi / Zed / Katarina / Darius / Vayne /
most of the roster).

Purely ADDITIVE: a new standalone scorer and a new ``/ally-amp`` route. It reads
no existing scorer and is read by none, so every existing route is byte-identical
(the opt-in is the new endpoint itself - inert until a caller invokes it, the
section-5 "default inert" contract for a brand-new surface). Wiring it into a
live teamfight / draft / peel-target coach surface is the separate Phase-D step.

Like the sustain / zone-control axes (and unlike the full-roster threat-range /
wave-clear / objective-damage axes), this axis is deliberately SPARSE: a champion
who grants nothing to her allies carries no registry rows and scores ``0.0``
(the empty-result contract).

Model (each ally-amplification MECHANISM a champion owns contributes a
kind-weighted, reach-scaled value; the headline is their sum):
  * a per-(champion, source) ``AllyAmpEntry`` tags one mechanism with a ``kind``
    (key of ``_ALLYAMP_KIND_WEIGHT`` - WHAT is granted: PROTECT / SHIELD / HEAL /
    STEROID / HASTE), a ``scope`` (key of ``_ALLYAMP_SCOPE_MULT`` - how many
    allies it reaches: TEAM / DUO / SINGLE), a ``magnitude`` (0..1 how strongly /
    reliably this mechanism amplifies its target), and a ``conditional`` flag
    (needs the ult up / a charge / a primed setup / a specific ally state).
  * ``compute_allyamp`` folds every mechanism into a single ``allyamp_score`` =
    sum of ``kind_weight * scope_mult * magnitude`` (times the conditional
    midpoint when gated). ``top_kind`` labels the kind of the single
    highest-value mechanism (the champion's strongest ally-buff); ``saves_ally``
    is True when any PROTECT-kind mechanism contributes (the hard-save identity a
    teamfight / peel consumer keys on - can this champion make a teammate
    un-killable).

Kinds, scopes and magnitudes are hand-authored from the verbatim patch-16.11
champion kits by the item-304 ten-channel roster fan-out.

DSP7 (2026-06-17) ally aura/enchanter seam - the OUTWARD-scorer half: this axis
is the GRANTER view (how much combat value a champion pumps into her team) and
is saturated under its one-mechanism-per-(champion, source) schema, so the
enchanter SHIELD / HEAL buckets are already modeled here (Janna E SHIELD, Soraka
W HEAL, ...). The complementary PROTECTED-ALLY view - the flat survivability
(Effective HP) a teammate's shield / heal CONFERS on the ally who receives it -
is the distinct DSP7 lift: ``_passive_ally_grant_overrides.ally_flat_hp_grant``
(the THIRD ally-grant EHP mode, fed into ``ehp.compute_ehp(external_flat_hp=)``).
This scorer measures the buff a champion SENDS; that seam measures the EHP an
ally RECEIVES. Both default-OFF / inert until a Phase-D consumer reads them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_SOURCE_ORDER = ("P", "Q", "W", "E", "R", "BASE")

# Amplification-kind -> weight. Hand-authored, operator-tunable. Five tiers by
# how game-swinging the value granted to an ally is:
#   1.00 PROTECT - a hard save: damage-immunity / invulnerability / untargetable
#                  stasis / a revive / a guaranteed-survival window granted to an
#                  ally (Taric R Cosmic Radiance / Zilean R Chronoshift / Tahm
#                  Kench W+R ally devour-save / Kindred R Lamb's Respite / Bard R
#                  stasis on an ally); the strongest ally amp - it makes a
#                  teammate temporarily un-killable.
#   0.85 SHIELD  - a damage-absorbing shield placed on an ally (Janna E / Karma E
#                  / Lulu E / Orianna E / Taric W / Seraphine W / Rakan W /
#                  Sona aura shield); negates a burst of incoming damage.
#   0.75 HEAL    - direct HP restoration to an ally (Soraka W+R / Sona Q+W / Nami
#                  Q / Yuumi E / Milio W / Taric Q / Seraphine W); sustained team
#                  effective-HP.
#   0.60 STEROID - a combat-power buff to an ally: bonus AD / AP / AS / crit /
#                  on-hit / damage-amp / bonus health / lifesteal (Lulu W+R / Sona
#                  Q+E auras / Nami E / Pyke R / Renata W / Sivir R attack steroid
#                  is haste); raises an ally's combat output.
#   0.45 HASTE   - movement speed / ability-haste / tenacity / slow-cleanse /
#                  out-of-combat utility granted to an ally (Janna P+Q / Sona E /
#                  Yuumi attach MS / Karma E MS / Sivir R MS / Milio P range); the
#                  lowest combat tier - mobility and utility, not power or EHP.
_ALLYAMP_KIND_WEIGHT: dict[str, float] = {
    "PROTECT": 1.0,
    "SHIELD": 0.85,
    "HEAL": 0.75,
    "STEROID": 0.6,
    "HASTE": 0.45,
}

# Scope -> multiplier. How many allies the mechanism reaches. An AoE / aura /
# global team buff is a full-value amp; a small-cluster (line / cone / nearby
# few) buff is nearly so; a single-target buff reaches only one chosen ally and
# is discounted.
_ALLYAMP_SCOPE_MULT: dict[str, float] = {
    "TEAM": 1.0,
    "DUO": 0.8,
    "SINGLE": 0.65,
}

# A gated (conditional) amp - one that needs the ult up, a charge / stack, a
# primed setup, or a specific ally state - is credited at this availability
# midpoint, the zone-control / threat-range / sustain / scaling shape.
_ALLYAMP_CONDITIONAL_PROB = 0.5


@dataclass(frozen=True)
class AllyAmpEntry:
    """One registry row: a champion ally-amplification mechanism.

    ``source`` is one of ``{"P","Q","W","E","R","BASE"}`` (``BASE`` = an
    amplification identity not tied to one ability). ``kind`` is a key of
    ``_ALLYAMP_KIND_WEIGHT``. ``scope`` is a key of ``_ALLYAMP_SCOPE_MULT``.
    ``magnitude`` is the 0..1 strength / reliability with which this one
    mechanism amplifies its ally target. ``conditional`` is True when the
    mechanism only fires on a gate (ult up, charge / stack accrued, a setup
    primed, a specific ally state required).
    """

    source: str
    kind: str
    scope: str
    magnitude: float = 0.0
    conditional: bool = False


def _mechanism_value(entry: AllyAmpEntry) -> float:
    """Kind-weighted, reach-scaled value for one mechanism (0 if unknown).

    Returns ``kind_weight * scope_mult * magnitude`` (times the conditional
    midpoint when gated), or ``0.0`` when the kind or scope is unknown.
    """
    weight = _ALLYAMP_KIND_WEIGHT.get(entry.kind, 0.0)
    scope_mult = _ALLYAMP_SCOPE_MULT.get(entry.scope, 0.0)
    if weight <= 0.0 or scope_mult <= 0.0:
        return 0.0
    value = weight * scope_mult * entry.magnitude
    if entry.conditional:
        value *= _ALLYAMP_CONDITIONAL_PROB
    return value


def _build_allyamp_registry() -> dict[str, tuple[AllyAmpEntry, ...]]:
    """Build champion_id -> tuple[AllyAmpEntry] via an append builder.

    Uses ``raw.setdefault(champ, []).append(...)`` so a champion can carry
    several ally-amplification mechanisms without dict-literal collision (the
    zonecontrol / objdamage / threatrange builder pattern). Runs ONCE at import.
    The axis is sparse - only champions who actually grant value to allies appear.
    """
    raw: dict[str, list[AllyAmpEntry]] = {}

    def add(
        champ: str,
        source: str,
        kind: str,
        scope: str,
        *,
        magnitude: float,
        cond: bool = False,
    ) -> None:
        raw.setdefault(champ, []).append(
            AllyAmpEntry(
                source=source,
                kind=kind,
                scope=scope,
                magnitude=float(magnitude),
                conditional=bool(cond),
            )
        )

    # Akshan
    add("Akshan", "W", "PROTECT", "TEAM", magnitude=0.5, cond=True)
    # Alistar
    add("Alistar", "P", "HEAL", "TEAM", magnitude=0.55, cond=True)
    # Annie
    add("Annie", "E", "SHIELD", "SINGLE", magnitude=0.45)
    # Bard
    add("Bard", "W", "HEAL", "SINGLE", magnitude=0.5)
    add("Bard", "E", "HASTE", "TEAM", magnitude=0.2)
    add("Bard", "R", "PROTECT", "TEAM", magnitude=0.75, cond=True)
    # Braum
    add("Braum", "W", "STEROID", "SINGLE", magnitude=0.5)
    # Fiora
    add("Fiora", "R", "HEAL", "TEAM", magnitude=0.5, cond=True)
    # Galio
    add("Galio", "R", "SHIELD", "TEAM", magnitude=0.7, cond=True)
    # Hwei
    add("Hwei", "W", "SHIELD", "TEAM", magnitude=0.5)
    # Ivern
    add("Ivern", "Q", "HASTE", "TEAM", magnitude=0.3, cond=True)
    add("Ivern", "W", "STEROID", "TEAM", magnitude=0.35, cond=True)
    add("Ivern", "E", "SHIELD", "SINGLE", magnitude=0.6)
    # Janna
    add("Janna", "P", "HASTE", "TEAM", magnitude=0.35)
    add("Janna", "E", "SHIELD", "SINGLE", magnitude=0.65)
    add("Janna", "R", "HEAL", "TEAM", magnitude=0.8, cond=True)
    # JarvanIV
    add("JarvanIV", "E", "STEROID", "TEAM", magnitude=0.45)
    # Jayce
    add("Jayce", "E", "HASTE", "TEAM", magnitude=0.4)
    # Karma
    add("Karma", "E", "SHIELD", "SINGLE", magnitude=0.6)
    add("Karma", "R", "SHIELD", "TEAM", magnitude=0.7, cond=True)
    # Kayle
    add("Kayle", "W", "HEAL", "SINGLE", magnitude=0.5)
    add("Kayle", "R", "PROTECT", "SINGLE", magnitude=0.85, cond=True)
    # Kindred
    add("Kindred", "R", "PROTECT", "TEAM", magnitude=0.85, cond=True)
    # Kled
    add("Kled", "R", "HASTE", "TEAM", magnitude=0.35, cond=True)
    # Lulu
    add("Lulu", "W", "STEROID", "SINGLE", magnitude=0.55)
    add("Lulu", "E", "SHIELD", "SINGLE", magnitude=0.6)
    add("Lulu", "R", "STEROID", "SINGLE", magnitude=0.85, cond=True)
    # Lux
    add("Lux", "W", "SHIELD", "DUO", magnitude=0.5)
    # Milio
    add("Milio", "P", "STEROID", "TEAM", magnitude=0.4)
    add("Milio", "W", "HEAL", "TEAM", magnitude=0.55)
    add("Milio", "E", "SHIELD", "SINGLE", magnitude=0.55)
    add("Milio", "R", "HASTE", "TEAM", magnitude=0.8, cond=True)
    # Morgana
    add("Morgana", "E", "SHIELD", "SINGLE", magnitude=0.65)
    # Nami
    add("Nami", "P", "HASTE", "TEAM", magnitude=0.45)
    add("Nami", "W", "HEAL", "DUO", magnitude=0.55)
    add("Nami", "E", "STEROID", "SINGLE", magnitude=0.5)
    add("Nami", "R", "HASTE", "TEAM", magnitude=0.4, cond=True)
    # Nidalee
    add("Nidalee", "E", "HEAL", "SINGLE", magnitude=0.55)
    # Nilah
    add("Nilah", "P", "HEAL", "TEAM", magnitude=0.35, cond=True)
    add("Nilah", "W", "HASTE", "DUO", magnitude=0.5)
    add("Nilah", "R", "HEAL", "TEAM", magnitude=0.6, cond=True)
    # Nunu
    add("Nunu", "P", "STEROID", "SINGLE", magnitude=0.4)
    # Orianna
    add("Orianna", "E", "SHIELD", "SINGLE", magnitude=0.55)
    # Ornn
    add("Ornn", "BASE", "STEROID", "TEAM", magnitude=0.55, cond=True)
    # Pyke
    add("Pyke", "R", "STEROID", "SINGLE", magnitude=0.45, cond=True)
    # Rakan
    add("Rakan", "Q", "HEAL", "TEAM", magnitude=0.45, cond=True)
    add("Rakan", "E", "SHIELD", "SINGLE", magnitude=0.55)
    # Rell
    add("Rell", "E", "HASTE", "DUO", magnitude=0.5)
    # Renata
    add("Renata", "W", "STEROID", "SINGLE", magnitude=0.6)
    add("Renata", "E", "SHIELD", "DUO", magnitude=0.5)
    # Ryze
    add("Ryze", "R", "HASTE", "TEAM", magnitude=0.3, cond=True)
    # Senna
    add("Senna", "Q", "HEAL", "TEAM", magnitude=0.5)
    add("Senna", "E", "HASTE", "TEAM", magnitude=0.4)
    add("Senna", "R", "SHIELD", "TEAM", magnitude=0.6, cond=True)
    # Seraphine
    add("Seraphine", "W", "SHIELD", "TEAM", magnitude=0.7)
    # Shen
    add("Shen", "W", "PROTECT", "DUO", magnitude=0.55)
    add("Shen", "R", "SHIELD", "SINGLE", magnitude=0.7, cond=True)
    # Sivir
    add("Sivir", "R", "HASTE", "TEAM", magnitude=0.6, cond=True)
    # Sona
    add("Sona", "Q", "STEROID", "TEAM", magnitude=0.35)
    add("Sona", "W", "HEAL", "SINGLE", magnitude=0.55)
    add("Sona", "E", "HASTE", "TEAM", magnitude=0.45)
    # Soraka
    add("Soraka", "W", "HEAL", "SINGLE", magnitude=0.6)
    add("Soraka", "R", "HEAL", "TEAM", magnitude=0.85, cond=True)
    # TahmKench
    add("TahmKench", "R", "PROTECT", "SINGLE", magnitude=0.85, cond=True)
    # Taric
    add("Taric", "Q", "HEAL", "TEAM", magnitude=0.55)
    add("Taric", "W", "SHIELD", "SINGLE", magnitude=0.6)
    add("Taric", "R", "PROTECT", "TEAM", magnitude=0.92, cond=True)
    # Thresh
    add("Thresh", "W", "SHIELD", "SINGLE", magnitude=0.55)
    # Xayah
    add("Xayah", "W", "STEROID", "SINGLE", magnitude=0.35, cond=True)
    # Yuumi
    add("Yuumi", "W", "STEROID", "SINGLE", magnitude=0.45)
    add("Yuumi", "E", "HEAL", "SINGLE", magnitude=0.5)
    add("Yuumi", "R", "HEAL", "TEAM", magnitude=0.65, cond=True)
    # Zilean
    add("Zilean", "E", "HASTE", "SINGLE", magnitude=0.5)
    add("Zilean", "R", "PROTECT", "SINGLE", magnitude=0.9, cond=True)

    return {champ: tuple(entries) for champ, entries in raw.items()}


_ALLYAMP_REGISTRY: dict[str, tuple[AllyAmpEntry, ...]] = _build_allyamp_registry()


@dataclass(frozen=True)
class AllyAmpSourceEntry:
    """One scored ally-amplification mechanism for a champion."""

    source_key: str
    kind: str
    scope: str
    kind_weight: float
    scope_mult: float
    magnitude: float
    conditional: bool
    value: float

    def to_dict(self) -> dict:
        return {
            "source_key": self.source_key,
            "kind": self.kind,
            "scope": self.scope,
            "kind_weight": self.kind_weight,
            "scope_mult": self.scope_mult,
            "magnitude": round(self.magnitude, 4),
            "conditional": self.conditional,
            "value": round(self.value, 4),
        }


@dataclass(frozen=True)
class AllyAmpResult:
    """Aggregate ally-amplification / buff-throughput for one champion.

    ``allyamp_score`` sums every mechanism's kind-weighted, reach-scaled value
    (higher = pumps more value into allies). ``top_kind`` is the kind of the
    single highest-value mechanism (the champion's strongest ally-buff, ``""``
    when none). ``saves_ally`` is True when at least one PROTECT-kind mechanism
    contributes - the hard-save flag a teamfight / peel consumer keys on. Returns
    all-zero with an empty ``sources`` tuple for an unregistered or blank
    champion (never raises); the axis is sparse, so a zero score is the correct,
    common answer for a selfish carry / assassin / solo duelist.
    """

    champion: str
    mode: str
    allyamp_score: float
    top_kind: str
    saves_ally: bool
    sources: tuple[AllyAmpSourceEntry, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion": self.champion,
            "mode": self.mode,
            "allyamp_score": round(self.allyamp_score, 4),
            "top_kind": self.top_kind,
            "saves_ally": self.saves_ally,
            "sources": [s.to_dict() for s in self.sources],
        }


def _empty_result(champion: str, mode: str) -> AllyAmpResult:
    return AllyAmpResult(
        champion=champion,
        mode=mode,
        allyamp_score=0.0,
        top_kind="",
        saves_ally=False,
        sources=(),
    )


def _source_sort_key(entry: AllyAmpEntry) -> tuple[int, str]:
    try:
        return (_SOURCE_ORDER.index(entry.source), entry.source)
    except ValueError:
        return (len(_SOURCE_ORDER), entry.source)


def compute_allyamp(champion: str, mode: str = "SR") -> AllyAmpResult:
    """Aggregate a champion's ally-amplification mechanisms into a buff score.

    Reads ``_ALLYAMP_REGISTRY``. Each registered mechanism contributes a
    kind-weighted, reach-scaled value (``_mechanism_value``); the values are
    summed into ``allyamp_score``. ``top_kind`` is the kind of the highest-value
    mechanism; ``saves_ally`` is True when any PROTECT mechanism contributes.
    ``mode`` is carried on the result for parity with the other scorers but does
    not change output today (ally amplification is map-independent).

    Returns an all-zero ``AllyAmpResult`` (empty ``sources``) when the champion
    is blank / None or absent from the (sparse) registry; never raises.
    """
    safe_mode = mode if mode else "SR"
    if not champion:
        return _empty_result("", safe_mode)
    entries = _ALLYAMP_REGISTRY.get(champion)
    if not entries:
        return _empty_result(champion, safe_mode)

    scored: list[AllyAmpSourceEntry] = []
    total = 0.0
    best_kind = ""
    best_value = -1.0
    has_protect = False
    for entry in sorted(entries, key=_source_sort_key):
        value = _mechanism_value(entry)
        total += value
        if value > best_value:
            best_value = value
            best_kind = entry.kind
        if value > 0.0 and entry.kind == "PROTECT":
            has_protect = True
        scored.append(
            AllyAmpSourceEntry(
                source_key=entry.source,
                kind=entry.kind,
                scope=entry.scope,
                kind_weight=_ALLYAMP_KIND_WEIGHT.get(entry.kind, 0.0),
                scope_mult=_ALLYAMP_SCOPE_MULT.get(entry.scope, 0.0),
                magnitude=entry.magnitude,
                conditional=entry.conditional,
                value=value,
            )
        )

    return AllyAmpResult(
        champion=champion,
        mode=safe_mode,
        allyamp_score=total,
        top_kind=best_kind if total > 0.0 else "",
        saves_ally=has_protect,
        sources=tuple(scored),
    )


__all__ = [
    "AllyAmpEntry",
    "AllyAmpResult",
    "AllyAmpSourceEntry",
    "compute_allyamp",
    "_ALLYAMP_KIND_WEIGHT",
    "_ALLYAMP_SCOPE_MULT",
    "_ALLYAMP_CONDITIONAL_PROB",
    "_ALLYAMP_REGISTRY",
]
