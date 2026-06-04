"""Objective / structure-damage scorer (ENGINE 1.115.0, item 303).

The fourteenth scored axis alongside DPS / burst / EHP / ability-DPS /
healing-throughput / offensive CC-output (item 294) / mobility (item 297) /
sustain (item 298) / scaling (item 299) / wave-clear (item 300) / effective
threat-range (item 301) / zone-control (item 302) / the six archetype scorers.
It quantifies how much pressure a champion can put on the map's OBJECTIVES -
turrets and structures on one side, epic monsters (drake / baron / herald /
grubs) and the neutral jungle on the other - the macro / siege dimension the
prior thirteen axes never measured (they score combat against an enemy CHAMPION
or a piece of GROUND; this one scores throughput against the objects that win
the game).

A high score means a champion who ends games and contests neutrals: tower-shred
identities, hyper-carries whose sustained single-target DPS melts structures and
epics alike, percent-HP on-hit monster-shredders, hands-free summon DPS that
sieges while the champion does other things, or a global / burst nuke that
snipes a Smite contest (Tryndamere / Kog'Maw / Vayne / Ziggs / Heimerdinger /
Shyvana / Nunu / Karthus). A low score means a champion who fights champions but
brings little to a tower dive or a dragon (most enchanters, pure single-target
CC supports, low-DPS control mages).

Purely ADDITIVE: a new standalone scorer and a new ``/objective-damage`` route.
It reads no existing scorer and is read by none, so every existing route is
byte-identical (the opt-in is the new endpoint itself - inert until a caller
invokes it, the section-5 "default inert" contract for a brand-new surface).
Wiring it into a live macro / split-push / objective-setup coach surface is the
separate Phase-D step.

Like the threat-range / wave-clear axes (and unlike the sparse zone-control
axis), this scores the FULL roster: every champion has SOME objective profile
(at minimum their general single-target DPS applied to a structure), so each
champion carries at least one registry row.

Model (each objective-relevant MECHANISM a champion owns contributes a
kind-weighted, scope-scaled value; the headline is their sum):
  * a per-(champion, source) ``ObjDamageEntry`` tags one mechanism with a
    ``kind`` (key of ``_OBJDAMAGE_KIND_WEIGHT`` - WHAT drives the objective
    damage: STRUCTURE_BONUS / MONSTER_BONUS / SUSTAINED_DPS / SUMMON_DPS /
    BURST_SECURE), a ``scope`` (key of ``_OBJDAMAGE_SCOPE_MULT`` - WHICH
    objective it hits: BOTH / MONSTER / STRUCTURE), a ``magnitude`` (0..1 how
    strongly this mechanism pressures its objective), and a ``conditional`` flag
    (needs the ult up / a charge / stacks / an empowered auto).
  * ``compute_objdamage`` folds every mechanism into a single ``objdamage_score``
    = sum of ``kind_weight * scope_mult * magnitude`` (times the conditional
    midpoint when gated). ``top_kind`` labels the kind of the single
    highest-value mechanism (the champion's strongest objective tool);
    ``pressures_structures`` is True when any mechanism that hits structures
    (scope BOTH or STRUCTURE) contributes - the can-actually-take-towers flag a
    siege / split-push consumer keys on (a champion whose only objective tool is
    percent-HP-on-hit pressures MONSTERs but NOT towers, which are immune).

Kinds, scopes and magnitudes are hand-authored from the verbatim patch-16.11
champion kits by the item-303 ten-channel roster fan-out.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_SOURCE_ORDER = ("P", "Q", "W", "E", "R", "BASE")

# Objective-damage kind -> weight. Hand-authored, operator-tunable. Five tiers
# by what drives the pressure on an objective:
#   1.00 STRUCTURE_BONUS - an explicit bonus-damage-to-turrets / structures
#                   mechanism (Ziggs P Short Fuse vs towers); the strongest and
#                   rarest signal - it directly accelerates the win condition
#                   (towers -> inhibs -> nexus) that nothing else on the roster
#                   targets.
#   0.90 MONSTER_BONUS - bonus / percent-HP / true damage to large + epic
#                   monsters (percent-HP on-hit Kog'Maw W / Vayne W / Varus /
#                   Kai'Sa, monster-bonus junglers Shyvana / Nunu Q / Belveth,
#                   true-damage execute) - the drake / baron secure tool.
#   0.70 SUSTAINED_DPS - high continuous single-target DPS that melts a
#                   structure or an epic by itself (hyper-carries, on-hit, AS
#                   bruisers - Tryndamere / Master Yi / Jax / Trundle / Twitch /
#                   Kindred); the baseline objective tool every champion carries
#                   at some magnitude.
#   0.55 SUMMON_DPS - an autonomous pet / turret / plant that adds objective DPS
#                   hands-free while the champion does something else
#                   (Heimerdinger turrets / Yorick ghouls + Maiden / Malzahar
#                   voidlings / Annie Tibbers / Elise spiders / Zyra plants /
#                   Ivern Daisy).
#   0.45 BURST_SECURE - a single large nuke that snipes a Smite contest or
#                   executes a low objective from range (Karthus R global /
#                   big-damage ults / execute finishers); spiky, not sustained,
#                   so the lowest sustained-pressure tier.
_OBJDAMAGE_KIND_WEIGHT: dict[str, float] = {
    "STRUCTURE_BONUS": 1.0,
    "MONSTER_BONUS": 0.9,
    "SUSTAINED_DPS": 0.7,
    "SUMMON_DPS": 0.55,
    "BURST_SECURE": 0.45,
}

# Scope -> multiplier. WHICH objective the mechanism actually hits. A mechanism
# that pressures BOTH structures and monsters (raw physical DPS, an auto-attack
# steroid) is the most broadly useful; a structure-only or monster-only tool is
# discounted equally (each covers half the objective game).
_OBJDAMAGE_SCOPE_MULT: dict[str, float] = {
    "BOTH": 1.0,
    "MONSTER": 0.85,
    "STRUCTURE": 0.85,
}

# A gated (conditional) objective tool - one that needs the ult up, a charge /
# stack, or an empowered auto primed - is credited at this availability
# midpoint, the zone-control / threat-range / waveclear / sustain shape.
_OBJDAMAGE_CONDITIONAL_PROB = 0.5


@dataclass(frozen=True)
class ObjDamageEntry:
    """One registry row: a champion objective-damage mechanism.

    ``source`` is one of ``{"P","Q","W","E","R","BASE"}`` (``BASE`` = an
    objective-damage identity not tied to one ability, e.g. a champion's general
    auto-attack DPS applied to a structure). ``kind`` is a key of
    ``_OBJDAMAGE_KIND_WEIGHT``. ``scope`` is a key of ``_OBJDAMAGE_SCOPE_MULT``.
    ``magnitude`` is the 0..1 strength with which this one mechanism pressures
    its objective. ``conditional`` is True when the mechanism only fires on a
    gate (ult up, charge / stack accrued, an empowered auto primed).
    """

    source: str
    kind: str
    scope: str
    magnitude: float = 0.0
    conditional: bool = False


def _mechanism_value(entry: ObjDamageEntry) -> float:
    """Kind-weighted, scope-scaled value for one mechanism (0 if unknown).

    Returns ``kind_weight * scope_mult * magnitude`` (times the conditional
    midpoint when gated), or ``0.0`` when the kind or scope is unknown.
    """
    weight = _OBJDAMAGE_KIND_WEIGHT.get(entry.kind, 0.0)
    scope_mult = _OBJDAMAGE_SCOPE_MULT.get(entry.scope, 0.0)
    if weight <= 0.0 or scope_mult <= 0.0:
        return 0.0
    value = weight * scope_mult * entry.magnitude
    if entry.conditional:
        value *= _OBJDAMAGE_CONDITIONAL_PROB
    return value


def _build_objdamage_registry() -> dict[str, tuple[ObjDamageEntry, ...]]:
    """Build champion_id -> tuple[ObjDamageEntry] via an append builder.

    Uses ``raw.setdefault(champ, []).append(...)`` so a champion can carry
    several objective mechanisms without dict-literal collision (the threatrange
    / waveclear / zonecontrol builder pattern). Runs ONCE at import. The axis
    scores the full roster - every champion carries at least one row.
    """
    raw: dict[str, list[ObjDamageEntry]] = {}

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
            ObjDamageEntry(
                source=source,
                kind=kind,
                scope=scope,
                magnitude=float(magnitude),
                conditional=bool(cond),
            )
        )

    # Aatrox
    add("Aatrox", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.48)
    # Ahri
    add("Ahri", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.22)
    # Akali
    add("Akali", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.25)
    # Akshan
    add("Akshan", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.52)
    # Alistar
    add("Alistar", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.18)
    # Ambessa
    add("Ambessa", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.5)
    # Amumu
    add("Amumu", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.3)
    # Anivia
    add("Anivia", "R", "SUSTAINED_DPS", "BOTH", magnitude=0.32, cond=True)
    add("Anivia", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.22)
    # Annie
    add("Annie", "R", "SUMMON_DPS", "BOTH", magnitude=0.42, cond=True)
    add("Annie", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.2)
    # Aphelios
    add("Aphelios", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.88)
    # Ashe
    add("Ashe", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.55)
    # AurelionSol
    add("AurelionSol", "R", "BURST_SECURE", "BOTH", magnitude=0.58, cond=True)
    add("AurelionSol", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.45)
    # Aurora
    add("Aurora", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.3)
    # Azir
    add("Azir", "W", "SUMMON_DPS", "BOTH", magnitude=0.62)
    add("Azir", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.38)
    # Bard
    add("Bard", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.17)
    # Belveth
    add("Belveth", "E", "MONSTER_BONUS", "MONSTER", magnitude=0.8)
    add("Belveth", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.85)
    # Blitzcrank
    add("Blitzcrank", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.28)
    # Brand
    add("Brand", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.32)
    # Braum
    add("Braum", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.15)
    # Briar
    add("Briar", "W", "SUSTAINED_DPS", "BOTH", magnitude=0.55)
    add("Briar", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.62)
    # Caitlyn
    add("Caitlyn", "P", "SUSTAINED_DPS", "BOTH", magnitude=0.52, cond=True)
    add("Caitlyn", "R", "BURST_SECURE", "BOTH", magnitude=0.42, cond=True)
    add("Caitlyn", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.58)
    # Camille
    add("Camille", "Q", "SUSTAINED_DPS", "BOTH", magnitude=0.58, cond=True)
    add("Camille", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.6)
    # Cassiopeia
    add("Cassiopeia", "E", "SUSTAINED_DPS", "BOTH", magnitude=0.45)
    add("Cassiopeia", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.35)
    # Chogath
    add("Chogath", "R", "MONSTER_BONUS", "MONSTER", magnitude=0.72, cond=True)
    add("Chogath", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.28)
    # Corki
    add("Corki", "W", "SUSTAINED_DPS", "BOTH", magnitude=0.52, cond=True)
    add("Corki", "R", "BURST_SECURE", "BOTH", magnitude=0.48, cond=True)
    add("Corki", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.6)
    # Darius
    add("Darius", "Q", "SUSTAINED_DPS", "BOTH", magnitude=0.45)
    add("Darius", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.55)
    # Diana
    add("Diana", "P", "SUSTAINED_DPS", "BOTH", magnitude=0.45, cond=True)
    add("Diana", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.42)
    # DrMundo
    add("DrMundo", "E", "SUSTAINED_DPS", "BOTH", magnitude=0.48)
    add("DrMundo", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.55)
    # Draven
    add("Draven", "Q", "SUSTAINED_DPS", "BOTH", magnitude=0.8, cond=True)
    add("Draven", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.78)
    # Ekko
    add("Ekko", "P", "SUSTAINED_DPS", "BOTH", magnitude=0.4, cond=True)
    add("Ekko", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.38)
    # Elise
    add("Elise", "W", "SUSTAINED_DPS", "BOTH", magnitude=0.4)
    add("Elise", "R", "SUMMON_DPS", "BOTH", magnitude=0.38, cond=True)
    add("Elise", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.32)
    # Evelynn
    add("Evelynn", "R", "BURST_SECURE", "BOTH", magnitude=0.48, cond=True)
    add("Evelynn", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.35)
    # Ezreal
    add("Ezreal", "R", "BURST_SECURE", "BOTH", magnitude=0.55, cond=True)
    add("Ezreal", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.48)
    # Fiddlesticks
    add("Fiddlesticks", "W", "SUSTAINED_DPS", "BOTH", magnitude=0.55)
    add("Fiddlesticks", "R", "BURST_SECURE", "BOTH", magnitude=0.5, cond=True)
    add("Fiddlesticks", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.22)
    # Fiora
    add("Fiora", "Q", "SUSTAINED_DPS", "BOTH", magnitude=0.65)
    add("Fiora", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.75)
    # Fizz
    add("Fizz", "R", "BURST_SECURE", "BOTH", magnitude=0.45, cond=True)
    add("Fizz", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.32)
    # Galio
    add("Galio", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.2)
    # Gangplank
    add("Gangplank", "Q", "SUSTAINED_DPS", "BOTH", magnitude=0.52)
    add("Gangplank", "R", "BURST_SECURE", "MONSTER", magnitude=0.5, cond=True)
    add("Gangplank", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.45)
    # Garen
    add("Garen", "E", "SUSTAINED_DPS", "BOTH", magnitude=0.48)
    add("Garen", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.42)
    # Gnar
    add("Gnar", "W", "SUSTAINED_DPS", "BOTH", magnitude=0.45)
    add("Gnar", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.4)
    # Gragas
    add("Gragas", "R", "BURST_SECURE", "BOTH", magnitude=0.42, cond=True)
    add("Gragas", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.22)
    # Graves
    add("Graves", "Q", "SUSTAINED_DPS", "BOTH", magnitude=0.5)
    add("Graves", "R", "BURST_SECURE", "BOTH", magnitude=0.55, cond=True)
    add("Graves", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.6)
    # Gwen
    add("Gwen", "Q", "SUSTAINED_DPS", "BOTH", magnitude=0.5)
    add("Gwen", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.44)
    # Hecarim
    add("Hecarim", "E", "SUSTAINED_DPS", "BOTH", magnitude=0.45)
    add("Hecarim", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.42)
    # Heimerdinger
    add("Heimerdinger", "W", "SUMMON_DPS", "BOTH", magnitude=0.85)
    add("Heimerdinger", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.38)
    # Hwei
    add("Hwei", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.2)
    # Illaoi
    add("Illaoi", "W", "SUSTAINED_DPS", "BOTH", magnitude=0.45)
    add("Illaoi", "E", "SUMMON_DPS", "BOTH", magnitude=0.4)
    add("Illaoi", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.48)
    # Irelia
    add("Irelia", "P", "SUSTAINED_DPS", "BOTH", magnitude=0.58, cond=True)
    add("Irelia", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.5)
    # Ivern
    add("Ivern", "R", "SUMMON_DPS", "BOTH", magnitude=0.55, cond=True)
    add("Ivern", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.18)
    # Janna
    add("Janna", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.15)
    # JarvanIV
    add("JarvanIV", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.42)
    # Jax
    add("Jax", "P", "SUSTAINED_DPS", "BOTH", magnitude=0.82, cond=True)
    add("Jax", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.88)
    # Jayce
    add("Jayce", "Q", "BURST_SECURE", "BOTH", magnitude=0.48, cond=True)
    add("Jayce", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.58)
    # Jhin
    add("Jhin", "P", "SUSTAINED_DPS", "BOTH", magnitude=0.6, cond=True)
    add("Jhin", "R", "BURST_SECURE", "MONSTER", magnitude=0.42, cond=True)
    add("Jhin", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.52)
    # Jinx
    add("Jinx", "R", "BURST_SECURE", "MONSTER", magnitude=0.45, cond=True)
    add("Jinx", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.82)
    # KSante
    add("KSante", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.22)
    # Kaisa
    add("Kaisa", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.78)
    # Kalista
    add("Kalista", "E", "BURST_SECURE", "BOTH", magnitude=0.55, cond=True)
    add("Kalista", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.72)
    # Karma
    add("Karma", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.18)
    # Karthus
    add("Karthus", "R", "BURST_SECURE", "MONSTER", magnitude=0.62, cond=True)
    add("Karthus", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.35)
    # Kassadin
    add("Kassadin", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.22)
    # Katarina
    add("Katarina", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.28)
    # Kayle
    add("Kayle", "E", "SUSTAINED_DPS", "BOTH", magnitude=0.65, cond=True)
    add("Kayle", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.88)
    # Kayn
    add("Kayn", "Q", "MONSTER_BONUS", "MONSTER", magnitude=0.58)
    add("Kayn", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.52)
    # Kennen
    add("Kennen", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.38)
    # Khazix
    add("Khazix", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.32)
    # Kindred
    add("Kindred", "W", "MONSTER_BONUS", "MONSTER", magnitude=0.82)
    add("Kindred", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.75)
    # Kled
    add("Kled", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.48)
    # KogMaw
    add("KogMaw", "W", "MONSTER_BONUS", "MONSTER", magnitude=0.88)
    add("KogMaw", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.85)
    # Leblanc
    add("Leblanc", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.16)
    # LeeSin
    add("LeeSin", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.45)
    # Leona
    add("Leona", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.15)
    # Lillia
    add("Lillia", "P", "MONSTER_BONUS", "MONSTER", magnitude=0.35)
    add("Lillia", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.28)
    # Lissandra
    add("Lissandra", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.22)
    # Lucian
    add("Lucian", "R", "SUSTAINED_DPS", "BOTH", magnitude=0.58, cond=True)
    add("Lucian", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.62)
    # Lulu
    add("Lulu", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.18)
    # Lux
    add("Lux", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.2)
    # Malphite
    add("Malphite", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.3)
    # Malzahar
    add("Malzahar", "W", "SUMMON_DPS", "BOTH", magnitude=0.45)
    add("Malzahar", "R", "SUSTAINED_DPS", "BOTH", magnitude=0.35, cond=True)
    add("Malzahar", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.25)
    # Maokai
    add("Maokai", "Q", "MONSTER_BONUS", "MONSTER", magnitude=0.42)
    add("Maokai", "E", "SUMMON_DPS", "BOTH", magnitude=0.32)
    add("Maokai", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.3)
    # MasterYi
    add("MasterYi", "E", "MONSTER_BONUS", "MONSTER", magnitude=0.72, cond=True)
    add("MasterYi", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.9)
    # Mel
    add("Mel", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.22)
    # Milio
    add("Milio", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.15)
    # MissFortune
    add("MissFortune", "R", "BURST_SECURE", "BOTH", magnitude=0.55, cond=True)
    add("MissFortune", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.6)
    # MonkeyKing
    add("MonkeyKing", "Q", "SUSTAINED_DPS", "STRUCTURE", magnitude=0.55)
    add("MonkeyKing", "W", "SUMMON_DPS", "BOTH", magnitude=0.32, cond=True)
    add("MonkeyKing", "R", "SUSTAINED_DPS", "MONSTER", magnitude=0.4, cond=True)
    add("MonkeyKing", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.7)
    # Mordekaiser
    add("Mordekaiser", "P", "MONSTER_BONUS", "BOTH", magnitude=0.48, cond=True)
    add("Mordekaiser", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.55)
    # Morgana
    add("Morgana", "W", "MONSTER_BONUS", "BOTH", magnitude=0.38)
    add("Morgana", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.2)
    # Naafiri
    add("Naafiri", "P", "SUMMON_DPS", "BOTH", magnitude=0.38)
    add("Naafiri", "W", "SUMMON_DPS", "BOTH", magnitude=0.42, cond=True)
    add("Naafiri", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.5)
    # Nami
    add("Nami", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.15)
    # Nasus
    add("Nasus", "Q", "SUSTAINED_DPS", "STRUCTURE", magnitude=0.82, cond=True)
    add("Nasus", "R", "SUSTAINED_DPS", "BOTH", magnitude=0.62, cond=True)
    add("Nasus", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.7)
    # Nautilus
    add("Nautilus", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.2)
    # Neeko
    add("Neeko", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.28)
    # Nidalee
    add("Nidalee", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.48)
    # Nilah
    add("Nilah", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.82)
    # Nocturne
    add("Nocturne", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.72)
    # Nunu
    add("Nunu", "Q", "MONSTER_BONUS", "MONSTER", magnitude=0.82)
    add("Nunu", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.32)
    # Olaf
    add("Olaf", "E", "SUSTAINED_DPS", "BOTH", magnitude=0.55)
    add("Olaf", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.78)
    # Orianna
    add("Orianna", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.25)
    # Ornn
    add("Ornn", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.28)
    # Pantheon
    add("Pantheon", "P", "SUSTAINED_DPS", "BOTH", magnitude=0.38, cond=True)
    add("Pantheon", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.42)
    # Poppy
    add("Poppy", "Q", "MONSTER_BONUS", "MONSTER", magnitude=0.52)
    add("Poppy", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.35)
    # Pyke
    add("Pyke", "R", "BURST_SECURE", "MONSTER", magnitude=0.45, cond=True)
    add("Pyke", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.22)
    # Qiyana
    add("Qiyana", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.27)
    # Quinn
    add("Quinn", "P", "SUSTAINED_DPS", "BOTH", magnitude=0.48, cond=True)
    add("Quinn", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.62)
    # Rakan
    add("Rakan", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.15)
    # Rammus
    add("Rammus", "R", "BURST_SECURE", "BOTH", magnitude=0.42, cond=True)
    add("Rammus", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.3)
    # RekSai
    add("RekSai", "Q", "SUSTAINED_DPS", "BOTH", magnitude=0.45)
    add("RekSai", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.58)
    # Rell
    add("Rell", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.18)
    # Renata
    add("Renata", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.18)
    # Renekton
    add("Renekton", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.52)
    # Rengar
    add("Rengar", "R", "BURST_SECURE", "BOTH", magnitude=0.42, cond=True)
    add("Rengar", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.45)
    # Riven
    add("Riven", "R", "BURST_SECURE", "BOTH", magnitude=0.52, cond=True)
    add("Riven", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.48)
    # Rumble
    add("Rumble", "R", "BURST_SECURE", "BOTH", magnitude=0.44, cond=True)
    add("Rumble", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.38)
    # Ryze
    add("Ryze", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.44)
    # Samira
    add("Samira", "R", "BURST_SECURE", "BOTH", magnitude=0.55, cond=True)
    add("Samira", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.72)
    # Sejuani
    add("Sejuani", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.2)
    # Senna
    add("Senna", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.38)
    # Seraphine
    add("Seraphine", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.2)
    # Sett
    add("Sett", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.58)
    # Shaco
    add("Shaco", "W", "SUMMON_DPS", "BOTH", magnitude=0.38)
    add("Shaco", "R", "SUMMON_DPS", "BOTH", magnitude=0.35, cond=True)
    add("Shaco", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.42)
    # Shen
    add("Shen", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.28)
    # Shyvana
    add("Shyvana", "W", "SUSTAINED_DPS", "BOTH", magnitude=0.55)
    add("Shyvana", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.72)
    # Singed
    add("Singed", "Q", "SUSTAINED_DPS", "BOTH", magnitude=0.36)
    add("Singed", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.28)
    # Sion
    add("Sion", "R", "BURST_SECURE", "BOTH", magnitude=0.52, cond=True)
    add("Sion", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.48)
    # Sivir
    add("Sivir", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.78)
    # Skarner
    add("Skarner", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.62)
    # Smolder
    add("Smolder", "Q", "SUSTAINED_DPS", "BOTH", magnitude=0.55, cond=True)
    add("Smolder", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.52)
    # Sona
    add("Sona", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.18)
    # Soraka
    add("Soraka", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.15)
    # Swain
    add("Swain", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.42)
    # Sylas
    add("Sylas", "P", "SUSTAINED_DPS", "BOTH", magnitude=0.45, cond=True)
    add("Sylas", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.4)
    # Syndra
    add("Syndra", "R", "BURST_SECURE", "BOTH", magnitude=0.62, cond=True)
    add("Syndra", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.35)
    # TahmKench
    add("TahmKench", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.25)
    # Taliyah
    add("Taliyah", "Q", "SUSTAINED_DPS", "BOTH", magnitude=0.44)
    add("Taliyah", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.38)
    # Talon
    add("Talon", "R", "BURST_SECURE", "BOTH", magnitude=0.42, cond=True)
    add("Talon", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.32)
    # Taric
    add("Taric", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.17)
    # Teemo
    add("Teemo", "E", "SUSTAINED_DPS", "BOTH", magnitude=0.44)
    add("Teemo", "R", "SUMMON_DPS", "MONSTER", magnitude=0.28)
    add("Teemo", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.42)
    # Thresh
    add("Thresh", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.18)
    # Tristana
    add("Tristana", "E", "STRUCTURE_BONUS", "STRUCTURE", magnitude=0.78, cond=True)
    add("Tristana", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.82)
    # Trundle
    add("Trundle", "W", "SUSTAINED_DPS", "BOTH", magnitude=0.82, cond=True)
    add("Trundle", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.78)
    # Tryndamere
    add("Tryndamere", "R", "SUSTAINED_DPS", "BOTH", magnitude=0.92, cond=True)
    add("Tryndamere", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.88)
    # TwistedFate
    add("TwistedFate", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.3)
    # Twitch
    add("Twitch", "R", "SUSTAINED_DPS", "BOTH", magnitude=0.88, cond=True)
    add("Twitch", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.84)
    # Udyr
    add("Udyr", "P", "SUSTAINED_DPS", "BOTH", magnitude=0.82, cond=True)
    add("Udyr", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.78)
    # Urgot
    add("Urgot", "W", "SUSTAINED_DPS", "BOTH", magnitude=0.62)
    # Varus
    add("Varus", "W", "MONSTER_BONUS", "MONSTER", magnitude=0.8)
    add("Varus", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.6)
    # Vayne
    add("Vayne", "W", "MONSTER_BONUS", "MONSTER", magnitude=0.88)
    add("Vayne", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.6)
    # Veigar
    add("Veigar", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.2)
    # Velkoz
    add("Velkoz", "R", "SUSTAINED_DPS", "BOTH", magnitude=0.45, cond=True)
    add("Velkoz", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.22)
    # Vex
    add("Vex", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.22)
    # Vi
    add("Vi", "W", "MONSTER_BONUS", "MONSTER", magnitude=0.58)
    add("Vi", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.52)
    # Viego
    add("Viego", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.58)
    # Viktor
    add("Viktor", "E", "SUSTAINED_DPS", "BOTH", magnitude=0.4)
    add("Viktor", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.24)
    # Vladimir
    add("Vladimir", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.35)
    # Volibear
    add("Volibear", "W", "SUSTAINED_DPS", "BOTH", magnitude=0.55)
    add("Volibear", "R", "STRUCTURE_BONUS", "STRUCTURE", magnitude=0.85, cond=True)
    add("Volibear", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.58)
    # Warwick
    add("Warwick", "P", "MONSTER_BONUS", "MONSTER", magnitude=0.68)
    add("Warwick", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.65)
    # Xayah
    add("Xayah", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.68)
    # Xerath
    add("Xerath", "R", "BURST_SECURE", "BOTH", magnitude=0.58, cond=True)
    add("Xerath", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.18)
    # XinZhao
    add("XinZhao", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.7)
    # Yasuo
    add("Yasuo", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.72)
    # Yone
    add("Yone", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.68)
    # Yorick
    add("Yorick", "E", "SUMMON_DPS", "BOTH", magnitude=0.58)
    add("Yorick", "R", "SUMMON_DPS", "BOTH", magnitude=0.82, cond=True)
    add("Yorick", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.55)
    # Yunara
    add("Yunara", "P", "STRUCTURE_BONUS", "STRUCTURE", magnitude=0.68, cond=True)
    add("Yunara", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.48)
    # Yuumi
    add("Yuumi", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.15)
    # Zac
    add("Zac", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.32)
    # Zed
    add("Zed", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.4)
    # Zeri
    add("Zeri", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.82)
    # Ziggs
    add("Ziggs", "P", "STRUCTURE_BONUS", "STRUCTURE", magnitude=0.92, cond=True)
    add("Ziggs", "Q", "BURST_SECURE", "BOTH", magnitude=0.52)
    add("Ziggs", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.38)
    # Zilean
    add("Zilean", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.18)
    # Zoe
    add("Zoe", "Q", "BURST_SECURE", "BOTH", magnitude=0.45)
    add("Zoe", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.28)
    # Zyra
    add("Zyra", "W", "SUMMON_DPS", "BOTH", magnitude=0.55)
    add("Zyra", "R", "SUMMON_DPS", "BOTH", magnitude=0.38, cond=True)
    add("Zyra", "BASE", "SUSTAINED_DPS", "BOTH", magnitude=0.28)

    return {champ: tuple(entries) for champ, entries in raw.items()}


_OBJDAMAGE_REGISTRY: dict[str, tuple[ObjDamageEntry, ...]] = (
    _build_objdamage_registry()
)


@dataclass(frozen=True)
class ObjDamageSourceEntry:
    """One scored objective-damage mechanism for a champion."""

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
class ObjDamageResult:
    """Aggregate objective / structure-damage for one champion.

    ``objdamage_score`` sums every mechanism's kind-weighted, scope-scaled value
    (higher = more pressure on towers / epics). ``top_kind`` is the kind of the
    single highest-value mechanism (the champion's strongest objective tool,
    ``""`` when none). ``pressures_structures`` is True when at least one
    mechanism that hits structures (scope BOTH or STRUCTURE) contributes - the
    can-actually-take-towers flag a siege / split-push consumer keys on (a
    percent-HP-on-hit monster-shredder pressures epics but NOT structures).
    Returns all-zero with an empty ``sources`` tuple for an unregistered or
    blank champion (never raises).
    """

    champion: str
    mode: str
    objdamage_score: float
    top_kind: str
    pressures_structures: bool
    sources: tuple[ObjDamageSourceEntry, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion": self.champion,
            "mode": self.mode,
            "objdamage_score": round(self.objdamage_score, 4),
            "top_kind": self.top_kind,
            "pressures_structures": self.pressures_structures,
            "sources": [s.to_dict() for s in self.sources],
        }


def _empty_result(champion: str, mode: str) -> ObjDamageResult:
    return ObjDamageResult(
        champion=champion,
        mode=mode,
        objdamage_score=0.0,
        top_kind="",
        pressures_structures=False,
        sources=(),
    )


def _source_sort_key(entry: ObjDamageEntry) -> tuple[int, str]:
    try:
        return (_SOURCE_ORDER.index(entry.source), entry.source)
    except ValueError:
        return (len(_SOURCE_ORDER), entry.source)


def compute_objdamage(champion: str, mode: str = "SR") -> ObjDamageResult:
    """Aggregate a champion's objective-damage mechanisms into one score.

    Reads ``_OBJDAMAGE_REGISTRY``. Each registered mechanism contributes a
    kind-weighted, scope-scaled value (``_mechanism_value``); the values are
    summed into ``objdamage_score``. ``top_kind`` is the kind of the
    highest-value mechanism; ``pressures_structures`` is True when any mechanism
    with scope BOTH or STRUCTURE contributes. ``mode`` is carried on the result
    for parity with the other scorers but does not change output today
    (objective damage is map-independent).

    Returns an all-zero ``ObjDamageResult`` (empty ``sources``) when the champion
    is blank / None or absent from the registry; never raises.
    """
    safe_mode = mode if mode else "SR"
    if not champion:
        return _empty_result("", safe_mode)
    entries = _OBJDAMAGE_REGISTRY.get(champion)
    if not entries:
        return _empty_result(champion, safe_mode)

    scored: list[ObjDamageSourceEntry] = []
    total = 0.0
    best_kind = ""
    best_value = -1.0
    hits_structures = False
    for entry in sorted(entries, key=_source_sort_key):
        value = _mechanism_value(entry)
        total += value
        if value > best_value:
            best_value = value
            best_kind = entry.kind
        if value > 0.0 and entry.scope in ("BOTH", "STRUCTURE"):
            hits_structures = True
        scored.append(
            ObjDamageSourceEntry(
                source_key=entry.source,
                kind=entry.kind,
                scope=entry.scope,
                kind_weight=_OBJDAMAGE_KIND_WEIGHT.get(entry.kind, 0.0),
                scope_mult=_OBJDAMAGE_SCOPE_MULT.get(entry.scope, 0.0),
                magnitude=entry.magnitude,
                conditional=entry.conditional,
                value=value,
            )
        )

    return ObjDamageResult(
        champion=champion,
        mode=safe_mode,
        objdamage_score=total,
        top_kind=best_kind if total > 0.0 else "",
        pressures_structures=hits_structures,
        sources=tuple(scored),
    )


__all__ = [
    "ObjDamageEntry",
    "ObjDamageResult",
    "ObjDamageSourceEntry",
    "compute_objdamage",
    "_OBJDAMAGE_KIND_WEIGHT",
    "_OBJDAMAGE_SCOPE_MULT",
    "_OBJDAMAGE_CONDITIONAL_PROB",
    "_OBJDAMAGE_REGISTRY",
]
