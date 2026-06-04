"""Scaling / power-curve scorer (ENGINE 1.111.0, item 299).

The tenth scored axis alongside DPS / burst / EHP / ability-DPS /
healing-throughput / offensive CC-output (item 294) / mobility (item 297) /
sustain (item 298) / the six archetype scorers. It quantifies a champion's
power TRAJECTORY across the game - how strong she is early vs late and which
way the curve slopes - reduced to an ``early_power`` / ``mid_power`` /
``late_power`` triple plus a signed ``scaling_slope``.

This is distinct from every other scored axis, which all measure a STATIC
snapshot of one capability (burst now, EHP now, mobility now). This axis owns
the TIME dimension the others never measured: a champion who is weak now but a
late-game hypercarry (Veigar / Kassadin / Vayne / Nasus / Kayle) scores a high
late power and a steep positive slope; an early-lane bully who falls off
(Renekton / Draven / Pantheon / Lee Sin / Elise) scores a high early power and
a NEGATIVE slope.

Purely ADDITIVE: a new standalone scorer and a new ``/scaling`` route. It reads
no existing scorer and is read by none, so every existing route is byte-identical
(the opt-in is the new endpoint itself - inert until a caller invokes it, the
section-5 "default inert" contract for a brand-new surface). Wiring it into a
live draft / scaling-mismatch / "play for late" coach surface is the separate
Phase-D step.

Model (each scaling MECHANISM a champion owns contributes a weighted power to
the three stages it is online for):
  * a per-(champion, source) ``ScalingEntry`` tags one scaling mechanism with a
    ``kind`` (key of ``_SCALING_KIND_WEIGHT``), the ``online_stage`` it first
    keys on (EARLY / MID / LATE - nothing contributes before its online stage),
    a ``magnitude`` (0..1 peak strength), and a ``conditional`` flag.
  * ``compute_scaling`` folds every online entry into the three stage powers
    using a per-kind ramp (``_SCALING_STAGE_RAMP``): an INFINITE_STACK / ratio
    / item-reliant mechanism RAMPS UP across stages, a FORM_SPIKE is flat once
    unlocked, an EARLY_FRONTLOAD DECAYS. Conditional mechanisms are credited at
    the ``_SCALING_CONDITIONAL_PROB`` midpoint.
  * ``scaling_score`` = ``late_power`` (the conventional higher-is-stronger
    headline); ``scaling_slope`` = ``late_power - early_power`` (the signed
    trajectory - the number that says "scales up" vs "falls off").

Kinds, online stages and magnitudes are hand-authored from the verbatim
patch-16.11 champion identities by the item-299 ten-channel roster fan-out.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_SOURCE_ORDER = ("P", "Q", "W", "E", "R", "BASE")
_STAGES = ("EARLY", "MID", "LATE")
_STAGE_INDEX: dict[str, int] = {"EARLY": 0, "MID": 1, "LATE": 2}

# Scaling-kind -> weight. Hand-authored, operator-tunable. Five tiers by how
# decisively the mechanism bends a champion's power curve:
#   1.00 INFINITE_STACK  - unbounded permanent growth (Veigar AP / Nasus Q /
#                          Senna souls / Thresh / Cho'Gath / Sion / Kindred);
#                          the strongest scaling identity, never caps.
#   0.80 FORM_SPIKE      - a level / ult-gated power jump that transforms the
#                          kit (Kassadin R / Kayle forms / Jax R / Vladimir);
#                          a discrete leap rather than a smooth ramp.
#   0.80 RATIO_HYPERSCALE- item-ratio driven late dominance (Vayne %HP true /
#                          Jinx + Kog'Maw AS / Karthus / Aurelion Sol); needs a
#                          full build but then outscales.
#   0.50 ITEM_RELIANT    - weak base, needs gold to function (most control
#                          mages / immobile ADCs); scales but not a hypercarry.
#   0.40 EARLY_FRONTLOAD - strong base stats / low-CD lane pressure that DECAYS
#                          (Renekton / Draven / Pantheon / Lee Sin / Elise);
#                          a NEGATIVE-trajectory signal.
_SCALING_KIND_WEIGHT: dict[str, float] = {
    "INFINITE_STACK": 1.0,
    "FORM_SPIKE": 0.8,
    "RATIO_HYPERSCALE": 0.8,
    "ITEM_RELIANT": 0.5,
    "EARLY_FRONTLOAD": 0.4,
}

# Per-kind (early, mid, late) ramp once the mechanism is online. A ramping kind
# grows toward 1.0 late; a FORM_SPIKE is full the moment it unlocks; an
# EARLY_FRONTLOAD decays as the game goes long.
_SCALING_STAGE_RAMP: dict[str, tuple[float, float, float]] = {
    "INFINITE_STACK": (0.3, 0.65, 1.0),
    "FORM_SPIKE": (1.0, 1.0, 1.0),
    "RATIO_HYPERSCALE": (0.25, 0.6, 1.0),
    "ITEM_RELIANT": (0.3, 0.65, 1.0),
    "EARLY_FRONTLOAD": (1.0, 0.55, 0.25),
}

# A gated (conditional) scaling mechanism - one that needs stacks accrued, a
# form active, a target-HP gate - is credited at this availability midpoint,
# the sustain / mobility / cc_output shape.
_SCALING_CONDITIONAL_PROB = 0.5


@dataclass(frozen=True)
class ScalingEntry:
    """One registry row: a champion scaling mechanism.

    ``source`` is one of ``{"P","Q","W","E","R","BASE"}`` (``BASE`` = a base-stat
    growth identity not tied to one ability). ``kind`` is a key of
    ``_SCALING_KIND_WEIGHT``. ``online_stage`` is the first stage the mechanism
    keys on (``EARLY`` / ``MID`` / ``LATE``); it contributes nothing to a stage
    earlier than that. ``magnitude`` is the 0..1 peak strength. ``conditional``
    is True when the mechanism only fires on a gate (stacks accrued, form active,
    target below an HP threshold).
    """

    source: str
    kind: str
    online_stage: str
    magnitude: float = 0.0
    conditional: bool = False


def _stage_contribution(entry: ScalingEntry, stage_idx: int) -> float:
    """Weighted power this entry contributes to one stage (0 if not yet online).

    Returns ``weight * magnitude * ramp[stage]`` (times the conditional midpoint
    when gated), or ``0.0`` when the stage is earlier than the entry's online
    stage or the kind is unknown.
    """
    online_idx = _STAGE_INDEX.get(entry.online_stage, 0)
    if stage_idx < online_idx:
        return 0.0
    weight = _SCALING_KIND_WEIGHT.get(entry.kind, 0.0)
    ramp = _SCALING_STAGE_RAMP.get(entry.kind)
    if weight <= 0.0 or ramp is None:
        return 0.0
    value = weight * entry.magnitude * ramp[stage_idx]
    if entry.conditional:
        value *= _SCALING_CONDITIONAL_PROB
    return value


def _build_scaling_registry() -> dict[str, tuple[ScalingEntry, ...]]:
    """Build champion_id -> tuple[ScalingEntry] via an append builder.

    Uses ``raw.setdefault(champ, []).append(...)`` so a champion can carry
    several scaling mechanisms without dict-literal collision (the sustain /
    mobility / cc_output builder pattern). Runs ONCE at import.
    """
    raw: dict[str, list[ScalingEntry]] = {}

    def add(
        champ: str,
        source: str,
        kind: str,
        *,
        stage: str,
        magnitude: float,
        cond: bool = False,
    ) -> None:
        raw.setdefault(champ, []).append(
            ScalingEntry(
                source=source,
                kind=kind,
                online_stage=stage,
                magnitude=float(magnitude),
                conditional=bool(cond),
            )
        )

    # Aatrox
    add("Aatrox", "Q", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.75)
    add("Aatrox", "R", "FORM_SPIKE", stage="MID", magnitude=0.7)
    # Ahri
    add("Ahri", "R", "FORM_SPIKE", stage="MID", magnitude=0.7)
    add("Ahri", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.6)
    # Akali
    add("Akali", "Q", "RATIO_HYPERSCALE", stage="MID", magnitude=0.75)
    # Akshan
    add("Akshan", "E", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.65)
    add("Akshan", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.65)
    # Alistar
    add("Alistar", "W", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.7)
    # Ambessa
    add("Ambessa", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.8)
    # Amumu
    add("Amumu", "R", "FORM_SPIKE", stage="MID", magnitude=0.75)
    add("Amumu", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.55)
    # Anivia
    add("Anivia", "R", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.75)
    add("Anivia", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.65)
    # Annie
    add("Annie", "P", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.65)
    add("Annie", "R", "FORM_SPIKE", stage="MID", magnitude=0.7)
    add("Annie", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.55)
    # Aphelios
    add("Aphelios", "BASE", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.9)
    # Ashe
    add("Ashe", "R", "FORM_SPIKE", stage="MID", magnitude=0.7)
    add("Ashe", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.6)
    # AurelionSol
    add("AurelionSol", "P", "INFINITE_STACK", stage="EARLY", magnitude=0.95)
    add("AurelionSol", "BASE", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.8)
    # Aurora
    add("Aurora", "R", "FORM_SPIKE", stage="MID", magnitude=0.65)
    add("Aurora", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.6)
    # Azir
    add("Azir", "W", "RATIO_HYPERSCALE", stage="MID", magnitude=0.9)
    add("Azir", "R", "FORM_SPIKE", stage="MID", magnitude=0.8)
    # Bard
    add("Bard", "P", "INFINITE_STACK", stage="EARLY", magnitude=0.75)
    # Belveth
    add("Belveth", "P", "INFINITE_STACK", stage="EARLY", magnitude=0.85)
    add("Belveth", "R", "FORM_SPIKE", stage="MID", magnitude=0.8)
    # Blitzcrank
    add("Blitzcrank", "Q", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.8)
    # Brand
    add("Brand", "P", "RATIO_HYPERSCALE", stage="MID", magnitude=0.65, cond=True)
    add("Brand", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.7)
    # Braum
    add("Braum", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.55)
    # Briar
    add("Briar", "W", "RATIO_HYPERSCALE", stage="MID", magnitude=0.65)
    add("Briar", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.65)
    # Caitlyn
    add("Caitlyn", "R", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.75)
    add("Caitlyn", "BASE", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.75)
    # Camille
    add("Camille", "W", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.65)
    add("Camille", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.65)
    # Cassiopeia
    add("Cassiopeia", "P", "INFINITE_STACK", stage="EARLY", magnitude=0.9)
    add("Cassiopeia", "E", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.85, cond=True)
    # Chogath
    add("Chogath", "R", "INFINITE_STACK", stage="MID", magnitude=1.0)
    # Corki
    add("Corki", "W", "FORM_SPIKE", stage="MID", magnitude=0.55)
    add("Corki", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.6)
    # Darius
    add("Darius", "R", "FORM_SPIKE", stage="MID", magnitude=0.6, cond=True)
    add("Darius", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.9)
    # Diana
    add("Diana", "R", "FORM_SPIKE", stage="MID", magnitude=0.8)
    add("Diana", "BASE", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.75)
    # DrMundo
    add("DrMundo", "R", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.85)
    # Draven
    add("Draven", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.95)
    # Ekko
    add("Ekko", "Q", "RATIO_HYPERSCALE", stage="MID", magnitude=0.75)
    add("Ekko", "R", "FORM_SPIKE", stage="MID", magnitude=0.7)
    # Elise
    add("Elise", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.9)
    # Evelynn
    add("Evelynn", "P", "FORM_SPIKE", stage="MID", magnitude=0.85)
    add("Evelynn", "R", "FORM_SPIKE", stage="MID", magnitude=0.75, cond=True)
    # Ezreal
    add("Ezreal", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.7)
    # Fiddlesticks
    add("Fiddlesticks", "R", "FORM_SPIKE", stage="MID", magnitude=0.85)
    add("Fiddlesticks", "BASE", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.75)
    # Fiora
    add("Fiora", "R", "FORM_SPIKE", stage="LATE", magnitude=0.75)
    add("Fiora", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.65)
    # Fizz
    add("Fizz", "R", "FORM_SPIKE", stage="MID", magnitude=0.75)
    add("Fizz", "BASE", "RATIO_HYPERSCALE", stage="MID", magnitude=0.7)
    # Galio
    add("Galio", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.6)
    # Gangplank
    add("Gangplank", "P", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.85)
    add("Gangplank", "Q", "INFINITE_STACK", stage="EARLY", magnitude=0.7)
    # Garen
    add("Garen", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.75)
    # Gnar
    add("Gnar", "R", "FORM_SPIKE", stage="MID", magnitude=0.8, cond=True)
    add("Gnar", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.65)
    # Gragas
    add("Gragas", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.6)
    # Graves
    add("Graves", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.75)
    # Gwen
    add("Gwen", "P", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.8)
    # Hecarim
    add("Hecarim", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.7)
    # Heimerdinger
    add("Heimerdinger", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.65)
    # Hwei
    add("Hwei", "BASE", "ITEM_RELIANT", stage="LATE", magnitude=0.7)
    # Illaoi
    add("Illaoi", "R", "FORM_SPIKE", stage="MID", magnitude=0.85, cond=True)
    add("Illaoi", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.75)
    # Irelia
    add("Irelia", "P", "RATIO_HYPERSCALE", stage="MID", magnitude=0.8, cond=True)
    # Ivern
    add("Ivern", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.55)
    # Janna
    add("Janna", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.5)
    # JarvanIV
    add("JarvanIV", "P", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.7)
    # Jax
    add("Jax", "R", "FORM_SPIKE", stage="MID", magnitude=0.85)
    add("Jax", "BASE", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.8)
    # Jayce
    add("Jayce", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.85)
    # Jhin
    add("Jhin", "P", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.85)
    # Jinx
    add("Jinx", "P", "RATIO_HYPERSCALE", stage="MID", magnitude=0.9)
    # KSante
    add("KSante", "Q", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.55)
    add("KSante", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.6)
    # Kaisa
    add("Kaisa", "P", "FORM_SPIKE", stage="MID", magnitude=0.75)
    add("Kaisa", "W", "RATIO_HYPERSCALE", stage="MID", magnitude=0.85, cond=True)
    # Kalista
    add("Kalista", "E", "RATIO_HYPERSCALE", stage="MID", magnitude=0.75)
    # Karma
    add("Karma", "Q", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.7)
    add("Karma", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.55)
    # Karthus
    add("Karthus", "Q", "RATIO_HYPERSCALE", stage="MID", magnitude=0.85)
    add("Karthus", "R", "RATIO_HYPERSCALE", stage="MID", magnitude=0.9)
    # Kassadin
    add("Kassadin", "R", "FORM_SPIKE", stage="MID", magnitude=0.95)
    add("Kassadin", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.3)
    # Katarina
    add("Katarina", "R", "RATIO_HYPERSCALE", stage="MID", magnitude=0.8, cond=True)
    add("Katarina", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.6)
    # Kayle
    add("Kayle", "R", "FORM_SPIKE", stage="LATE", magnitude=0.95)
    add("Kayle", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.5)
    # Kayn
    add("Kayn", "R", "FORM_SPIKE", stage="MID", magnitude=0.8, cond=True)
    # Kennen
    add("Kennen", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.6)
    # Khazix
    add("Khazix", "Q", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.8, cond=True)
    add("Khazix", "R", "FORM_SPIKE", stage="MID", magnitude=0.65)
    # Kindred
    add("Kindred", "P", "INFINITE_STACK", stage="EARLY", magnitude=0.85, cond=True)
    # Kled
    add("Kled", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.8)
    # KogMaw
    add("KogMaw", "W", "RATIO_HYPERSCALE", stage="MID", magnitude=0.95)
    # Leblanc
    add("Leblanc", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.8)
    # LeeSin
    add("LeeSin", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.9)
    # Leona
    add("Leona", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.75)
    # Lillia
    add("Lillia", "BASE", "RATIO_HYPERSCALE", stage="MID", magnitude=0.72)
    # Lissandra
    add("Lissandra", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.55)
    # Lucian
    add("Lucian", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.78)
    # Lulu
    add("Lulu", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.45)
    # Lux
    add("Lux", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.6)
    # Malphite
    add("Malphite", "R", "FORM_SPIKE", stage="MID", magnitude=0.72)
    add("Malphite", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.65)
    # Malzahar
    add("Malzahar", "E", "ITEM_RELIANT", stage="MID", magnitude=0.6)
    add("Malzahar", "R", "ITEM_RELIANT", stage="MID", magnitude=0.62, cond=True)
    # Maokai
    add("Maokai", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.6)
    # MasterYi
    add("MasterYi", "Q", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.45, cond=True)
    add("MasterYi", "R", "FORM_SPIKE", stage="MID", magnitude=0.75)
    add("MasterYi", "BASE", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.88)
    # Mel
    add("Mel", "BASE", "RATIO_HYPERSCALE", stage="MID", magnitude=0.7)
    # Milio
    add("Milio", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.42)
    # MissFortune
    add("MissFortune", "R", "RATIO_HYPERSCALE", stage="MID", magnitude=0.65, cond=True)
    add("MissFortune", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.82)
    # MonkeyKing
    add("MonkeyKing", "R", "FORM_SPIKE", stage="MID", magnitude=0.7, cond=True)
    add("MonkeyKing", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.75)
    # Mordekaiser
    add("Mordekaiser", "R", "FORM_SPIKE", stage="MID", magnitude=0.8, cond=True)
    add("Mordekaiser", "BASE", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.85)
    # Morgana
    add("Morgana", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.55)
    # Naafiri
    add("Naafiri", "R", "FORM_SPIKE", stage="MID", magnitude=0.65)
    add("Naafiri", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.76)
    # Nami
    add("Nami", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.4)
    # Nasus
    add("Nasus", "Q", "INFINITE_STACK", stage="EARLY", magnitude=0.95)
    add("Nasus", "R", "FORM_SPIKE", stage="MID", magnitude=0.8)
    # Nautilus
    add("Nautilus", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.55)
    # Neeko
    add("Neeko", "R", "RATIO_HYPERSCALE", stage="MID", magnitude=0.65)
    # Nidalee
    add("Nidalee", "Q", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.82)
    add("Nidalee", "R", "FORM_SPIKE", stage="MID", magnitude=0.55)
    # Nilah
    add("Nilah", "W", "RATIO_HYPERSCALE", stage="MID", magnitude=0.75)
    # Nocturne
    add("Nocturne", "P", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.7)
    add("Nocturne", "R", "FORM_SPIKE", stage="MID", magnitude=0.65)
    # Nunu
    add("Nunu", "Q", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.72)
    add("Nunu", "R", "RATIO_HYPERSCALE", stage="MID", magnitude=0.68, cond=True)
    # Olaf
    add("Olaf", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.88)
    # Orianna
    add("Orianna", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.65)
    # Ornn
    add("Ornn", "P", "ITEM_RELIANT", stage="EARLY", magnitude=0.55)
    add("Ornn", "R", "FORM_SPIKE", stage="LATE", magnitude=0.85)
    # Pantheon
    add("Pantheon", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.9)
    # Poppy
    add("Poppy", "P", "ITEM_RELIANT", stage="MID", magnitude=0.6)
    add("Poppy", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.45)
    # Pyke
    add("Pyke", "R", "INFINITE_STACK", stage="MID", magnitude=0.75, cond=True)
    add("Pyke", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.75)
    # Qiyana
    add("Qiyana", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.82)
    # Quinn
    add("Quinn", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.8)
    # Rakan
    add("Rakan", "R", "FORM_SPIKE", stage="MID", magnitude=0.6)
    add("Rakan", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.5)
    # Rammus
    add("Rammus", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.75)
    # RekSai
    add("RekSai", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.8)
    # Rell
    add("Rell", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.52)
    # Renata
    add("Renata", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.6)
    # Renekton
    add("Renekton", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.9)
    # Rengar
    add("Rengar", "R", "FORM_SPIKE", stage="MID", magnitude=0.7, cond=True)
    add("Rengar", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.75)
    # Riven
    add("Riven", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.85)
    # Rumble
    add("Rumble", "R", "FORM_SPIKE", stage="MID", magnitude=0.8)
    add("Rumble", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.8)
    # Ryze
    add("Ryze", "BASE", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.95)
    # Samira
    add("Samira", "R", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.85, cond=True)
    # Sejuani
    add("Sejuani", "R", "FORM_SPIKE", stage="MID", magnitude=0.75)
    add("Sejuani", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.65)
    # Senna
    add("Senna", "P", "INFINITE_STACK", stage="EARLY", magnitude=0.95)
    # Seraphine
    add("Seraphine", "BASE", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.7, cond=True)
    # Sett
    add("Sett", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.85)
    # Shaco
    add("Shaco", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.85)
    # Shen
    add("Shen", "R", "FORM_SPIKE", stage="MID", magnitude=0.75)
    # Shyvana
    add("Shyvana", "R", "FORM_SPIKE", stage="MID", magnitude=0.8)
    add("Shyvana", "BASE", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.75)
    # Singed
    add("Singed", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.7)
    # Sion
    add("Sion", "P", "INFINITE_STACK", stage="EARLY", magnitude=0.9)
    # Sivir
    add("Sivir", "BASE", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.8)
    # Skarner
    add("Skarner", "R", "FORM_SPIKE", stage="MID", magnitude=0.8)
    add("Skarner", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.6)
    # Smolder
    add("Smolder", "P", "INFINITE_STACK", stage="EARLY", magnitude=0.85)
    add("Smolder", "R", "FORM_SPIKE", stage="LATE", magnitude=0.8, cond=True)
    # Sona
    add("Sona", "P", "ITEM_RELIANT", stage="MID", magnitude=0.55)
    add("Sona", "R", "FORM_SPIKE", stage="MID", magnitude=0.7, cond=True)
    # Soraka
    add("Soraka", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.5)
    # Swain
    add("Swain", "P", "INFINITE_STACK", stage="MID", magnitude=0.7)
    add("Swain", "R", "FORM_SPIKE", stage="MID", magnitude=0.75, cond=True)
    # Sylas
    add("Sylas", "R", "FORM_SPIKE", stage="MID", magnitude=0.75, cond=True)
    add("Sylas", "BASE", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.7)
    # Syndra
    add("Syndra", "P", "RATIO_HYPERSCALE", stage="MID", magnitude=0.8)
    # TahmKench
    add("TahmKench", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.55)
    # Taliyah
    add("Taliyah", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.65)
    # Talon
    add("Talon", "R", "FORM_SPIKE", stage="MID", magnitude=0.6, cond=True)
    add("Talon", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.75)
    # Taric
    add("Taric", "R", "FORM_SPIKE", stage="MID", magnitude=0.75, cond=True)
    add("Taric", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.5)
    # Teemo
    add("Teemo", "E", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.65)
    # Thresh
    add("Thresh", "P", "INFINITE_STACK", stage="EARLY", magnitude=0.75)
    # Tristana
    add("Tristana", "Q", "FORM_SPIKE", stage="MID", magnitude=0.65, cond=True)
    add("Tristana", "BASE", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.85)
    # Trundle
    add("Trundle", "R", "FORM_SPIKE", stage="MID", magnitude=0.8, cond=True)
    add("Trundle", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.65)
    # Tryndamere
    add("Tryndamere", "P", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.7, cond=True)
    add("Tryndamere", "R", "FORM_SPIKE", stage="MID", magnitude=0.9, cond=True)
    add("Tryndamere", "BASE", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.75)
    # TwistedFate
    add("TwistedFate", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.6)
    # Twitch
    add("Twitch", "R", "FORM_SPIKE", stage="MID", magnitude=0.85, cond=True)
    add("Twitch", "BASE", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.9)
    # Udyr
    add("Udyr", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.7)
    # Urgot
    add("Urgot", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.7)
    # Varus
    add("Varus", "Q", "ITEM_RELIANT", stage="MID", magnitude=0.6)
    add("Varus", "W", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.72, cond=True)
    # Vayne
    add("Vayne", "W", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.95)
    # Veigar
    add("Veigar", "P", "INFINITE_STACK", stage="EARLY", magnitude=1.0)
    # Velkoz
    add("Velkoz", "P", "RATIO_HYPERSCALE", stage="MID", magnitude=0.7, cond=True)
    add("Velkoz", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.65)
    # Vex
    add("Vex", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.6)
    # Vi
    add("Vi", "R", "FORM_SPIKE", stage="MID", magnitude=0.65)
    add("Vi", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.65)
    # Viego
    add("Viego", "R", "FORM_SPIKE", stage="MID", magnitude=0.85, cond=True)
    # Viktor
    add("Viktor", "P", "FORM_SPIKE", stage="MID", magnitude=0.7)
    add("Viktor", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.7)
    # Vladimir
    add("Vladimir", "P", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.75)
    add("Vladimir", "R", "FORM_SPIKE", stage="MID", magnitude=0.8)
    add("Vladimir", "BASE", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.75)
    # Volibear
    add("Volibear", "R", "FORM_SPIKE", stage="MID", magnitude=0.7)
    add("Volibear", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.7)
    # Warwick
    add("Warwick", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.65)
    # Xayah
    add("Xayah", "E", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.8)
    add("Xayah", "BASE", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.8)
    # Xerath
    add("Xerath", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.65)
    # XinZhao
    add("XinZhao", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.8)
    # Yasuo
    add("Yasuo", "R", "FORM_SPIKE", stage="MID", magnitude=0.65, cond=True)
    add("Yasuo", "BASE", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.85)
    # Yone
    add("Yone", "E", "FORM_SPIKE", stage="MID", magnitude=0.7)
    add("Yone", "BASE", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.82)
    # Yorick
    add("Yorick", "P", "INFINITE_STACK", stage="EARLY", magnitude=0.65)
    add("Yorick", "R", "FORM_SPIKE", stage="MID", magnitude=0.75)
    # Yunara
    add("Yunara", "R", "FORM_SPIKE", stage="MID", magnitude=0.65, cond=True)
    add("Yunara", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.7)
    # Yuumi
    add("Yuumi", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.55)
    # Zac
    add("Zac", "Q", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.65)
    add("Zac", "E", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.7)
    add("Zac", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.65)
    # Zed
    add("Zed", "BASE", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.85)
    # Zeri
    add("Zeri", "Q", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.9)
    add("Zeri", "R", "FORM_SPIKE", stage="MID", magnitude=0.75, cond=True)
    # Ziggs
    add("Ziggs", "Q", "ITEM_RELIANT", stage="MID", magnitude=0.6)
    add("Ziggs", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.55)
    # Zilean
    add("Zilean", "R", "FORM_SPIKE", stage="MID", magnitude=0.75, cond=True)
    add("Zilean", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.5)
    # Zoe
    add("Zoe", "Q", "RATIO_HYPERSCALE", stage="LATE", magnitude=0.9, cond=True)
    add("Zoe", "E", "EARLY_FRONTLOAD", stage="EARLY", magnitude=0.65, cond=True)
    # Zyra
    add("Zyra", "BASE", "ITEM_RELIANT", stage="MID", magnitude=0.6)

    return {champ: tuple(entries) for champ, entries in raw.items()}


_SCALING_REGISTRY: dict[str, tuple[ScalingEntry, ...]] = (
    _build_scaling_registry()
)


@dataclass(frozen=True)
class ScalingSourceEntry:
    """One scored scaling mechanism for a champion (per-stage breakdown)."""

    source_key: str
    kind: str
    online_stage: str
    kind_weight: float
    magnitude: float
    conditional: bool
    early: float
    mid: float
    late: float

    def to_dict(self) -> dict:
        return {
            "source_key": self.source_key,
            "kind": self.kind,
            "online_stage": self.online_stage,
            "kind_weight": self.kind_weight,
            "magnitude": round(self.magnitude, 4),
            "conditional": self.conditional,
            "early": round(self.early, 4),
            "mid": round(self.mid, 4),
            "late": round(self.late, 4),
        }


@dataclass(frozen=True)
class ScalingResult:
    """Aggregate power-curve for one champion.

    ``early_power`` / ``mid_power`` / ``late_power`` sum every online mechanism's
    weighted contribution at that stage. ``scaling_score`` aliases ``late_power``
    (the conventional higher-is-stronger headline). ``scaling_slope`` =
    ``late_power - early_power`` is the signed trajectory: positive scales up,
    negative falls off, ~0 even. Returns all-zero with an empty ``sources`` tuple
    for an unregistered or blank champion (never raises).
    """

    champion: str
    mode: str
    early_power: float
    mid_power: float
    late_power: float
    scaling_score: float
    scaling_slope: float
    sources: tuple[ScalingSourceEntry, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion": self.champion,
            "mode": self.mode,
            "early_power": round(self.early_power, 4),
            "mid_power": round(self.mid_power, 4),
            "late_power": round(self.late_power, 4),
            "scaling_score": round(self.scaling_score, 4),
            "scaling_slope": round(self.scaling_slope, 4),
            "sources": [s.to_dict() for s in self.sources],
        }


def _empty_result(champion: str, mode: str) -> ScalingResult:
    return ScalingResult(
        champion=champion,
        mode=mode,
        early_power=0.0,
        mid_power=0.0,
        late_power=0.0,
        scaling_score=0.0,
        scaling_slope=0.0,
        sources=(),
    )


def _source_sort_key(entry: ScalingEntry) -> tuple[int, str]:
    try:
        return (_SOURCE_ORDER.index(entry.source), entry.source)
    except ValueError:
        return (len(_SOURCE_ORDER), entry.source)


def compute_scaling(champion: str, mode: str = "SR") -> ScalingResult:
    """Aggregate a champion's scaling mechanisms into a power curve.

    Reads ``_SCALING_REGISTRY``. Each registered mechanism contributes a weighted
    power (``_stage_contribution``) to every stage it is online for; the three
    stage powers are summed, and the signed slope is ``late_power - early_power``.
    ``mode`` is carried on the result for parity with the other scorers but does
    not change output today (scaling identity is target-independent).

    Returns an all-zero ``ScalingResult`` (empty ``sources``) when the champion
    is blank / None or absent from the registry; never raises.
    """
    safe_mode = mode if mode else "SR"
    if not champion:
        return _empty_result("", safe_mode)
    entries = _SCALING_REGISTRY.get(champion)
    if not entries:
        return _empty_result(champion, safe_mode)

    scored: list[ScalingSourceEntry] = []
    early = mid = late = 0.0
    for entry in sorted(entries, key=_source_sort_key):
        e_val = _stage_contribution(entry, 0)
        m_val = _stage_contribution(entry, 1)
        l_val = _stage_contribution(entry, 2)
        early += e_val
        mid += m_val
        late += l_val
        scored.append(
            ScalingSourceEntry(
                source_key=entry.source,
                kind=entry.kind,
                online_stage=entry.online_stage,
                kind_weight=_SCALING_KIND_WEIGHT.get(entry.kind, 0.0),
                magnitude=entry.magnitude,
                conditional=entry.conditional,
                early=e_val,
                mid=m_val,
                late=l_val,
            )
        )

    return ScalingResult(
        champion=champion,
        mode=safe_mode,
        early_power=early,
        mid_power=mid,
        late_power=late,
        scaling_score=late,
        scaling_slope=late - early,
        sources=tuple(scored),
    )


__all__ = [
    "ScalingEntry",
    "ScalingResult",
    "ScalingSourceEntry",
    "compute_scaling",
    "_SCALING_KIND_WEIGHT",
    "_SCALING_STAGE_RAMP",
    "_SCALING_CONDITIONAL_PROB",
    "_SCALING_REGISTRY",
    "_STAGE_INDEX",
]
