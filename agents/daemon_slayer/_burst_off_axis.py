"""RM-41 - kit-axis-aware off-class exclusion for the burst (assassin) ranker.

The ``ds.burst`` scorer is AXIS-AGNOSTIC by design (it serves AD assassins on
lethality AND AP assassins on burst magic), but it ranks every purchasable,
mode-legal item by raw burst-damage delta with no notion of which axis the
champion's kit actually scales on. Measured on the live engine at 1.239.0 with
the sweep-standard squishy target, Akali - 85.5 percent magical damage, an
assassin who builds ZERO AD in any source - was served Essence Reaver #4,
Trinity Force #5, Blade of The Ruined King #7 and Infinity Edge #12, burying
her dominant first item Hextech Gunblade at #11 underneath all of them. The
AD items ride her ability-EMPOWERED AUTO (spellblade / on-hit / crit procs)
while every gold spent on AD is near-dead on a kit that scales with AP.

The mirror defect is RM-35: dead AP items surfacing in an AD burst champ's
list. Both directions are the same missing gate, so this module is symmetric.

Two deliberately TIGHT decisions, per the engine convention of starting with
the narrowest matching set and widening only on test evidence:

* The champion gate is DATA-DRIVEN from the snapshot's own
  ``lolmath.damage_distribution``, using the same dominance / margin
  thresholds as ``core.archetype_picks._axis_from_distribution`` (0.55 / 0.20)
  so the two agree by construction. It is NOT a curated champion list, so it
  cannot drift against a patch. A champion without a decisive split (Shaco,
  0.521 magical / 0.347 physical) resolves to ``None`` and is never stripped.
  The DS package reads the field off the snapshot record rather than importing
  ``core`` - production imports run the other way.

* The item gate keys on the three DDragon OFFENSIVE stat fields only. An item
  is off-axis when it carries offense on the champion's OFF axis and NONE on
  the on axis. That spares hybrids by construction (Hextech Gunblade 80 AP +
  40 AD survives on both axes, and so does Statikk Shiv at 45/45) and spares
  every defensive / utility item and every boot, which carry no offense on
  either axis. Attack speed is deliberately NOT a physical-offense signal:
  it is on-axis for AP on-hit kits (Nashor's, Guinsoo's) and it would drag
  Berserker's Greaves into a strip this seam is not meant to make.
"""
from __future__ import annotations

from typing import Optional

# Mirrors core.archetype_picks._AXIS_DOMINANT_MIN / _AXIS_MARGIN_MIN. Kept as
# local literals rather than an import: the daemon_slayer package does not
# import core in production. tests/test_burst_off_axis_rm41.py pins the two
# resolvers to the same verdict on the AP cohort + the AD fence set.
_AXIS_DOMINANT_MIN: float = 0.55
_AXIS_MARGIN_MIN: float = 0.20

# DDragon offensive stat fields, split by damage axis. Crit is grouped with
# attack damage because a crit multiplier only ever multiplies physical damage.
_PHYSICAL_OFFENSE_KEYS: tuple[str, ...] = (
    "FlatPhysicalDamageMod",
    "FlatCritChanceMod",
)
_MAGIC_OFFENSE_KEYS: tuple[str, ...] = (
    "FlatMagicDamageMod",
)


def champion_burst_axis(champ_rec: Optional[dict]) -> Optional[str]:
    """Return ``"ad"`` / ``"ap"`` for a decisive kit damage split, else ``None``.

    Reads ``lolmath.damage_distribution`` off the snapshot's own champion
    record. Fail-soft: a missing record, a missing block or a non-numeric
    entry all return ``None``, which makes the caller a no-op.
    """
    if not isinstance(champ_rec, dict):
        return None
    dist = (champ_rec.get("lolmath") or {}).get("damage_distribution") or {}
    if not isinstance(dist, dict):
        return None
    try:
        magical = float(dist.get("magical") or 0.0)
        physical = float(dist.get("physical") or 0.0)
    except (TypeError, ValueError):
        return None
    dominant, other, label = (
        (magical, physical, "ap") if magical >= physical else (physical, magical, "ad")
    )
    if dominant >= _AXIS_DOMINANT_MIN and (dominant - other) >= _AXIS_MARGIN_MIN:
        return label
    return None


def _offense(stats: dict, keys: tuple[str, ...]) -> bool:
    """True iff the stat block carries a positive value on any of ``keys``."""
    for key in keys:
        try:
            if float(stats.get(key) or 0.0) > 0.0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def is_off_axis_candidate(item_rec: Optional[dict], axis: Optional[str]) -> bool:
    """True iff this item's offense is ENTIRELY on the champion's off axis.

    ``axis`` is the champion's decisive kit axis from
    :func:`champion_burst_axis`. ``None`` (no decisive split) never strips.
    """
    if axis not in ("ad", "ap") or not isinstance(item_rec, dict):
        return False
    stats = item_rec.get("stats") or {}
    if not isinstance(stats, dict):
        return False
    has_physical = _offense(stats, _PHYSICAL_OFFENSE_KEYS)
    has_magic = _offense(stats, _MAGIC_OFFENSE_KEYS)
    if axis == "ap":
        return has_physical and not has_magic
    return has_magic and not has_physical
