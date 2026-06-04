"""Zone-control / area-denial scorer (ENGINE 1.114.0, item 302).

The thirteenth scored axis alongside DPS / burst / EHP / ability-DPS /
healing-throughput / offensive CC-output (item 294) / mobility (item 297) /
sustain (item 298) / scaling (item 299) / wave-clear (item 300) / effective
threat-range (item 301) / the six archetype scorers. It quantifies how much a
champion can make a piece of GROUND dangerous, impassable, or contested for a
DURATION - the spatial area-denial dimension the prior twelve axes never
measured (they score WHAT a champion does to a target; this one scores how it
denies and reshapes SPACE, independent of any single enemy).

A high score means a champion who owns the map's geometry: walls and terrain,
lingering damage fields, armed traps, summoned guardians, or space-clearing
displacement (Anivia / Jarvan IV / Trundle / Heimerdinger / Zyra / Teemo /
Cassiopeia / Gangplank); a low score (or zero) means a champion who threatens a
TARGET but controls no ground at all (Master Yi / Talon / Tryndamere / Yasuo /
Zed / most assassins and single-target duelists).

Purely ADDITIVE: a new standalone scorer and a new ``/zone-control`` route. It
reads no existing scorer and is read by none, so every existing route is
byte-identical (the opt-in is the new endpoint itself - inert until a caller
invokes it, the section-5 "default inert" contract for a brand-new surface).
Wiring it into a live teamfight / objective / draft-zoning coach surface is the
separate Phase-D step.

Unlike the threat-range / wave-clear axes (which classify the FULL roster), this
axis is deliberately SPARSE: a champion with no real area-denial carries no
registry rows and scores ``0.0`` (the empty-result contract), exactly like the
sustain axis (item 298).

Model (each area-denial MECHANISM a champion owns contributes a denial-weighted,
persistence-scaled value; the headline is their sum):
  * a per-(champion, source) ``ZoneControlEntry`` tags one mechanism with a
    ``kind`` (key of ``_ZONECONTROL_KIND_WEIGHT`` - WHAT kind of spatial control:
    TERRAIN / FIELD / TRAP / SUMMON / DISPLACE), a ``persistence`` (key of
    ``_ZONECONTROL_PERSISTENCE_MULT`` - how LONG the footprint holds: SUSTAINED /
    TIMED / BRIEF), a ``magnitude`` (0..1 how strongly / reliably this mechanism
    denies its area), and a ``conditional`` flag (needs the ult up / a charge /
    a setup).
  * ``compute_zonecontrol`` folds every mechanism into a single
    ``zonecontrol_score`` = sum of ``kind_weight * persistence_mult * magnitude``
    (times the conditional midpoint when gated). ``top_kind`` labels the kind of
    the single highest-value mechanism (the champion's strongest area-control);
    ``controls_terrain`` is True when any TERRAIN-kind mechanism contributes (the
    map-reshaping identity a teamfight / objective consumer keys on).

Kinds, persistence and magnitudes are hand-authored from the verbatim patch-16.11
champion kits by the item-302 ten-channel roster fan-out.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_SOURCE_ORDER = ("P", "Q", "W", "E", "R", "BASE")

# Control-kind -> weight. Hand-authored, operator-tunable. Five tiers by how
# strongly the mechanism denies / reshapes the ground:
#   1.00 TERRAIN  - impassable / blocking terrain that physically reshapes
#                   movement and pathing (Anivia W wall / JarvanIV R arena /
#                   Trundle E pillar / Taliyah R Weaver's Wall / Azir R divide /
#                   Yorick W cage / Camille R arena); the absolute strongest
#                   spatial control - it removes ground entirely.
#   0.85 FIELD    - a persistent damaging / slowing / debuffing AREA left on the
#                   ground for a duration (Anivia R Glacial Storm / Rumble R
#                   Equalizer / Cassiopeia W Miasma / Singed Q trail / Gangplank R
#                   barrage / Brand W / Ziggs E minefield / Karthus E Defile);
#                   continuous area-denial you have to walk out of.
#   0.70 TRAP     - an armed, placed device that lies dormant and denies / pops
#                   in an area until sprung or it expires (Caitlyn W / Teemo R
#                   shrooms / Nidalee W / Shaco W / Jinx E chompers / Gangplank E
#                   barrels / Maokai saplings).
#   0.60 SUMMON   - an autonomous / controllable unit, plant, or turret that
#                   holds and contests an area (Heimerdinger Q turrets / Zyra
#                   plants / Yorick ghouls + R Maiden / Malzahar W voidlings /
#                   Annie R Tibbers / Ivern R Daisy / Elise spiders / Illaoi
#                   tentacles / Azir soldiers).
#   0.45 DISPLACE - a knockback / pull / wind-wall whose PRIMARY value is
#                   controlling or CLEARING space rather than locking one target
#                   (Janna R Monsoon / Gragas R cask scatter / Poppy R / Singed E
#                   fling); the lowest-control signal (the per-target lockdown
#                   VALUE of CC is the separate offensive-CC-output axis, item
#                   294 - this credits only the SPACE the displacement controls).
_ZONECONTROL_KIND_WEIGHT: dict[str, float] = {
    "TERRAIN": 1.0,
    "FIELD": 0.85,
    "TRAP": 0.7,
    "SUMMON": 0.6,
    "DISPLACE": 0.45,
}

# Persistence -> multiplier. How LONG the control footprint holds. A toggled /
# channelled / minutes-long zone is a full denial; a standard few-second zone is
# nearly so; a sub-second / one-shot displacement is discounted (it controls the
# space for only an instant).
_ZONECONTROL_PERSISTENCE_MULT: dict[str, float] = {
    "SUSTAINED": 1.0,
    "TIMED": 0.8,
    "BRIEF": 0.55,
}

# A gated (conditional) zone - one that needs the ult up, a charge / stack, or a
# setup primed - is credited at this availability midpoint, the threat-range /
# waveclear / sustain / scaling shape.
_ZONECONTROL_CONDITIONAL_PROB = 0.5


@dataclass(frozen=True)
class ZoneControlEntry:
    """One registry row: a champion area-denial mechanism.

    ``source`` is one of ``{"P","Q","W","E","R","BASE"}`` (``BASE`` = a denial
    identity not tied to one ability). ``kind`` is a key of
    ``_ZONECONTROL_KIND_WEIGHT``. ``persistence`` is a key of
    ``_ZONECONTROL_PERSISTENCE_MULT``. ``magnitude`` is the 0..1 strength /
    reliability with which this one mechanism denies its area. ``conditional``
    is True when the mechanism only fires on a gate (ult up, charge / stack
    accrued, a setup primed).
    """

    source: str
    kind: str
    persistence: str
    magnitude: float = 0.0
    conditional: bool = False


def _mechanism_value(entry: ZoneControlEntry) -> float:
    """Denial-weighted, persistence-scaled value for one mechanism (0 if unknown).

    Returns ``kind_weight * persistence_mult * magnitude`` (times the conditional
    midpoint when gated), or ``0.0`` when the kind or persistence is unknown.
    """
    weight = _ZONECONTROL_KIND_WEIGHT.get(entry.kind, 0.0)
    pers_mult = _ZONECONTROL_PERSISTENCE_MULT.get(entry.persistence, 0.0)
    if weight <= 0.0 or pers_mult <= 0.0:
        return 0.0
    value = weight * pers_mult * entry.magnitude
    if entry.conditional:
        value *= _ZONECONTROL_CONDITIONAL_PROB
    return value


def _build_zonecontrol_registry() -> dict[str, tuple[ZoneControlEntry, ...]]:
    """Build champion_id -> tuple[ZoneControlEntry] via an append builder.

    Uses ``raw.setdefault(champ, []).append(...)`` so a champion can carry
    several area-denial mechanisms without dict-literal collision (the threatrange
    / waveclear / scaling / sustain / mobility builder pattern). Runs ONCE at
    import. The axis is sparse - only champions with real area-denial appear.
    """
    raw: dict[str, list[ZoneControlEntry]] = {}

    def add(
        champ: str,
        source: str,
        kind: str,
        persistence: str,
        *,
        magnitude: float,
        cond: bool = False,
    ) -> None:
        raw.setdefault(champ, []).append(
            ZoneControlEntry(
                source=source,
                kind=kind,
                persistence=persistence,
                magnitude=float(magnitude),
                conditional=bool(cond),
            )
        )

    # Akali
    add("Akali", "W", "FIELD", "TIMED", magnitude=0.4)
    # Anivia
    add("Anivia", "W", "TERRAIN", "TIMED", magnitude=0.82)
    add("Anivia", "R", "FIELD", "SUSTAINED", magnitude=0.78)
    # Annie
    add("Annie", "R", "SUMMON", "SUSTAINED", magnitude=0.65, cond=True)
    # Aphelios
    add("Aphelios", "W", "SUMMON", "TIMED", magnitude=0.55, cond=True)
    # Ashe
    add("Ashe", "W", "FIELD", "BRIEF", magnitude=0.3)
    # AurelionSol
    add("AurelionSol", "R", "FIELD", "TIMED", magnitude=0.72, cond=True)
    # Aurora
    add("Aurora", "R", "FIELD", "TIMED", magnitude=0.6, cond=True)
    # Azir
    add("Azir", "W", "SUMMON", "TIMED", magnitude=0.72)
    add("Azir", "R", "TERRAIN", "TIMED", magnitude=0.88, cond=True)
    # Bard
    add("Bard", "R", "FIELD", "BRIEF", magnitude=0.55, cond=True)
    # Braum
    add("Braum", "R", "FIELD", "TIMED", magnitude=0.65, cond=True)
    # Briar
    add("Briar", "R", "DISPLACE", "BRIEF", magnitude=0.55, cond=True)
    # Caitlyn
    add("Caitlyn", "W", "TRAP", "SUSTAINED", magnitude=0.55)
    # Camille
    add("Camille", "R", "TERRAIN", "SUSTAINED", magnitude=0.85, cond=True)
    # Cassiopeia
    add("Cassiopeia", "W", "FIELD", "TIMED", magnitude=0.55)
    # Chogath
    add("Chogath", "Q", "DISPLACE", "BRIEF", magnitude=0.5)
    # Corki
    add("Corki", "W", "FIELD", "TIMED", magnitude=0.3)
    # Ekko
    add("Ekko", "W", "FIELD", "TIMED", magnitude=0.5)
    # Fiddlesticks
    add("Fiddlesticks", "R", "FIELD", "TIMED", magnitude=0.75, cond=True)
    # Fizz
    add("Fizz", "R", "FIELD", "TIMED", magnitude=0.45, cond=True)
    # Gangplank
    add("Gangplank", "E", "TRAP", "SUSTAINED", magnitude=0.55)
    add("Gangplank", "R", "FIELD", "SUSTAINED", magnitude=0.8, cond=True)
    # Gragas
    add("Gragas", "R", "DISPLACE", "BRIEF", magnitude=0.65)
    # Graves
    add("Graves", "W", "FIELD", "TIMED", magnitude=0.55)
    # Heimerdinger
    add("Heimerdinger", "Q", "SUMMON", "SUSTAINED", magnitude=0.85)
    # Hwei
    add("Hwei", "Q", "FIELD", "TIMED", magnitude=0.5)
    # Illaoi
    add("Illaoi", "P", "SUMMON", "SUSTAINED", magnitude=0.7)
    add("Illaoi", "E", "SUMMON", "TIMED", magnitude=0.7)
    add("Illaoi", "R", "SUMMON", "TIMED", magnitude=0.85, cond=True)
    # Irelia
    add("Irelia", "R", "FIELD", "TIMED", magnitude=0.65, cond=True)
    # Ivern
    add("Ivern", "R", "SUMMON", "SUSTAINED", magnitude=0.65, cond=True)
    # Janna
    add("Janna", "R", "DISPLACE", "SUSTAINED", magnitude=0.75)
    # JarvanIV
    add("JarvanIV", "R", "TERRAIN", "SUSTAINED", magnitude=0.85, cond=True)
    # Jayce
    add("Jayce", "W", "FIELD", "TIMED", magnitude=0.3)
    # Jhin
    add("Jhin", "E", "TRAP", "SUSTAINED", magnitude=0.45)
    # Jinx
    add("Jinx", "E", "TRAP", "SUSTAINED", magnitude=0.45)
    # KSante
    add("KSante", "R", "DISPLACE", "BRIEF", magnitude=0.45, cond=True)
    # Karma
    add("Karma", "Q", "FIELD", "TIMED", magnitude=0.5, cond=True)
    # Karthus
    add("Karthus", "W", "FIELD", "TIMED", magnitude=0.45)
    add("Karthus", "E", "FIELD", "SUSTAINED", magnitude=0.65)
    # Kennen
    add("Kennen", "R", "FIELD", "TIMED", magnitude=0.7, cond=True)
    # Kindred
    add("Kindred", "R", "FIELD", "TIMED", magnitude=0.6, cond=True)
    # Kled
    add("Kled", "R", "FIELD", "TIMED", magnitude=0.4, cond=True)
    # Lux
    add("Lux", "E", "FIELD", "TIMED", magnitude=0.4)
    # Malphite
    add("Malphite", "R", "DISPLACE", "BRIEF", magnitude=0.55, cond=True)
    # Malzahar
    add("Malzahar", "W", "SUMMON", "TIMED", magnitude=0.25)
    # Maokai
    add("Maokai", "E", "TRAP", "SUSTAINED", magnitude=0.45)
    add("Maokai", "R", "FIELD", "TIMED", magnitude=0.55, cond=True)
    # Milio
    add("Milio", "E", "FIELD", "TIMED", magnitude=0.3)
    # MissFortune
    add("MissFortune", "R", "FIELD", "TIMED", magnitude=0.6, cond=True)
    # MonkeyKing
    add("MonkeyKing", "R", "FIELD", "TIMED", magnitude=0.55, cond=True)
    # Mordekaiser
    add("Mordekaiser", "R", "TERRAIN", "TIMED", magnitude=0.7, cond=True)
    # Morgana
    add("Morgana", "W", "FIELD", "TIMED", magnitude=0.55)
    # Naafiri
    add("Naafiri", "P", "SUMMON", "TIMED", magnitude=0.35)
    # Nami
    add("Nami", "R", "DISPLACE", "BRIEF", magnitude=0.5, cond=True)
    # Nidalee
    add("Nidalee", "W", "TRAP", "SUSTAINED", magnitude=0.35)
    # Nocturne
    add("Nocturne", "Q", "FIELD", "BRIEF", magnitude=0.22)
    # Nunu
    add("Nunu", "R", "FIELD", "TIMED", magnitude=0.72, cond=True)
    # Orianna
    add("Orianna", "W", "FIELD", "TIMED", magnitude=0.38)
    # Ornn
    add("Ornn", "R", "DISPLACE", "BRIEF", magnitude=0.45, cond=True)
    # Poppy
    add("Poppy", "W", "FIELD", "TIMED", magnitude=0.62)
    # Rammus
    add("Rammus", "R", "FIELD", "TIMED", magnitude=0.58, cond=True)
    # RekSai
    add("RekSai", "E", "TERRAIN", "SUSTAINED", magnitude=0.42)
    # Rell
    add("Rell", "R", "FIELD", "TIMED", magnitude=0.68, cond=True)
    # Rumble
    add("Rumble", "R", "FIELD", "SUSTAINED", magnitude=0.85, cond=True)
    # Sejuani
    add("Sejuani", "R", "FIELD", "TIMED", magnitude=0.65, cond=True)
    # Shaco
    add("Shaco", "W", "TRAP", "SUSTAINED", magnitude=0.55)
    # Shyvana
    add("Shyvana", "E", "FIELD", "TIMED", magnitude=0.4, cond=True)
    # Singed
    add("Singed", "Q", "FIELD", "TIMED", magnitude=0.6)
    add("Singed", "W", "FIELD", "TIMED", magnitude=0.5)
    # Smolder
    add("Smolder", "E", "FIELD", "TIMED", magnitude=0.3)
    # Swain
    add("Swain", "R", "FIELD", "SUSTAINED", magnitude=0.45, cond=True)
    # Taliyah
    add("Taliyah", "Q", "FIELD", "TIMED", magnitude=0.35)
    add("Taliyah", "W", "DISPLACE", "BRIEF", magnitude=0.4)
    add("Taliyah", "R", "TERRAIN", "SUSTAINED", magnitude=0.92, cond=True)
    # Teemo
    add("Teemo", "R", "TRAP", "SUSTAINED", magnitude=0.78, cond=True)
    # Trundle
    add("Trundle", "E", "TERRAIN", "TIMED", magnitude=0.6)
    # Udyr
    add("Udyr", "Q", "FIELD", "TIMED", magnitude=0.3)
    # Veigar
    add("Veigar", "E", "TERRAIN", "TIMED", magnitude=0.8)
    # Velkoz
    add("Velkoz", "R", "FIELD", "TIMED", magnitude=0.55, cond=True)
    # Viktor
    add("Viktor", "W", "FIELD", "TIMED", magnitude=0.75)
    add("Viktor", "E", "FIELD", "TIMED", magnitude=0.65)
    # Vladimir
    add("Vladimir", "W", "FIELD", "BRIEF", magnitude=0.35)
    # Volibear
    add("Volibear", "R", "FIELD", "SUSTAINED", magnitude=0.6, cond=True)
    # Xerath
    add("Xerath", "R", "FIELD", "TIMED", magnitude=0.55, cond=True)
    # XinZhao
    add("XinZhao", "R", "DISPLACE", "BRIEF", magnitude=0.65, cond=True)
    # Yasuo
    add("Yasuo", "W", "TERRAIN", "TIMED", magnitude=0.85)
    # Yorick
    add("Yorick", "W", "TERRAIN", "TIMED", magnitude=0.7)
    add("Yorick", "R", "SUMMON", "SUSTAINED", magnitude=0.75, cond=True)
    # Yunara
    add("Yunara", "W", "FIELD", "TIMED", magnitude=0.45)
    add("Yunara", "R", "FIELD", "TIMED", magnitude=0.65, cond=True)
    # Yuumi
    add("Yuumi", "R", "FIELD", "SUSTAINED", magnitude=0.6, cond=True)
    # Ziggs
    add("Ziggs", "W", "TRAP", "TIMED", magnitude=0.35)
    add("Ziggs", "E", "TRAP", "TIMED", magnitude=0.6)
    # Zoe
    add("Zoe", "E", "FIELD", "TIMED", magnitude=0.45)
    # Zyra
    add("Zyra", "W", "SUMMON", "SUSTAINED", magnitude=0.65)
    add("Zyra", "R", "FIELD", "TIMED", magnitude=0.7, cond=True)

    return {champ: tuple(entries) for champ, entries in raw.items()}


_ZONECONTROL_REGISTRY: dict[str, tuple[ZoneControlEntry, ...]] = (
    _build_zonecontrol_registry()
)


@dataclass(frozen=True)
class ZoneControlSourceEntry:
    """One scored area-denial mechanism for a champion."""

    source_key: str
    kind: str
    persistence: str
    kind_weight: float
    persistence_mult: float
    magnitude: float
    conditional: bool
    value: float

    def to_dict(self) -> dict:
        return {
            "source_key": self.source_key,
            "kind": self.kind,
            "persistence": self.persistence,
            "kind_weight": self.kind_weight,
            "persistence_mult": self.persistence_mult,
            "magnitude": round(self.magnitude, 4),
            "conditional": self.conditional,
            "value": round(self.value, 4),
        }


@dataclass(frozen=True)
class ZoneControlResult:
    """Aggregate zone-control / area-denial for one champion.

    ``zonecontrol_score`` sums every mechanism's denial-weighted, persistence-
    scaled value (higher = denies more ground for longer). ``top_kind`` is the
    kind of the single highest-value mechanism (the champion's strongest area-
    control, ``""`` when none). ``controls_terrain`` is True when at least one
    TERRAIN-kind mechanism contributes - the map-reshaping flag a teamfight /
    objective consumer keys on. Returns all-zero with an empty ``sources`` tuple
    for an unregistered or blank champion (never raises); the axis is sparse, so
    a zero score is the correct, common answer for a pure target-focused
    champion.
    """

    champion: str
    mode: str
    zonecontrol_score: float
    top_kind: str
    controls_terrain: bool
    sources: tuple[ZoneControlSourceEntry, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion": self.champion,
            "mode": self.mode,
            "zonecontrol_score": round(self.zonecontrol_score, 4),
            "top_kind": self.top_kind,
            "controls_terrain": self.controls_terrain,
            "sources": [s.to_dict() for s in self.sources],
        }


def _empty_result(champion: str, mode: str) -> ZoneControlResult:
    return ZoneControlResult(
        champion=champion,
        mode=mode,
        zonecontrol_score=0.0,
        top_kind="",
        controls_terrain=False,
        sources=(),
    )


def _source_sort_key(entry: ZoneControlEntry) -> tuple[int, str]:
    try:
        return (_SOURCE_ORDER.index(entry.source), entry.source)
    except ValueError:
        return (len(_SOURCE_ORDER), entry.source)


def compute_zonecontrol(champion: str, mode: str = "SR") -> ZoneControlResult:
    """Aggregate a champion's area-denial mechanisms into a zone-control score.

    Reads ``_ZONECONTROL_REGISTRY``. Each registered mechanism contributes a
    denial-weighted, persistence-scaled value (``_mechanism_value``); the values
    are summed into ``zonecontrol_score``. ``top_kind`` is the kind of the
    highest-value mechanism; ``controls_terrain`` is True when any TERRAIN
    mechanism contributes. ``mode`` is carried on the result for parity with the
    other scorers but does not change output today (area-denial is
    map-independent).

    Returns an all-zero ``ZoneControlResult`` (empty ``sources``) when the
    champion is blank / None or absent from the (sparse) registry; never raises.
    """
    safe_mode = mode if mode else "SR"
    if not champion:
        return _empty_result("", safe_mode)
    entries = _ZONECONTROL_REGISTRY.get(champion)
    if not entries:
        return _empty_result(champion, safe_mode)

    scored: list[ZoneControlSourceEntry] = []
    total = 0.0
    best_kind = ""
    best_value = -1.0
    has_terrain = False
    for entry in sorted(entries, key=_source_sort_key):
        value = _mechanism_value(entry)
        total += value
        if value > best_value:
            best_value = value
            best_kind = entry.kind
        if value > 0.0 and entry.kind == "TERRAIN":
            has_terrain = True
        scored.append(
            ZoneControlSourceEntry(
                source_key=entry.source,
                kind=entry.kind,
                persistence=entry.persistence,
                kind_weight=_ZONECONTROL_KIND_WEIGHT.get(entry.kind, 0.0),
                persistence_mult=_ZONECONTROL_PERSISTENCE_MULT.get(
                    entry.persistence, 0.0
                ),
                magnitude=entry.magnitude,
                conditional=entry.conditional,
                value=value,
            )
        )

    return ZoneControlResult(
        champion=champion,
        mode=safe_mode,
        zonecontrol_score=total,
        top_kind=best_kind if total > 0.0 else "",
        controls_terrain=has_terrain,
        sources=tuple(scored),
    )


__all__ = [
    "ZoneControlEntry",
    "ZoneControlResult",
    "ZoneControlSourceEntry",
    "compute_zonecontrol",
    "_ZONECONTROL_KIND_WEIGHT",
    "_ZONECONTROL_PERSISTENCE_MULT",
    "_ZONECONTROL_CONDITIONAL_PROB",
    "_ZONECONTROL_REGISTRY",
]
