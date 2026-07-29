"""Canonical melee/ranged classification by base attackrange (RM-123).

One boolean fact - is a champion melee or ranged - was historically encoded as
a magic attackrange threshold in four engine sites (ehp, rank, burst, dps) with
two DIFFERENT values (250 and 350) and three different comparison operators.
The 250 sites mis-classified the three champions whose base attackrange lands in
the 250 < ar <= 350 band (Rakan 300 melee, Lillia 325 melee, Urgot 350 ranged).

A full 173-champion roster scan shows the only champions between 250 and 450 are
Rakan (300), Lillia (325), Urgot (350), Graves (425), Yuumi (425). The single
rule below classifies every one of the 173 correctly and matches real League:

    ranged  iff  base attackrange >= 350.0
    melee   iff  base attackrange <  350.0

This module is a zero-dependency leaf so every scorer (including ``dps``, which
must not import ``rank``) can share the one constant without an import cycle.
"""

# Ranged when base attackrange is AT OR ABOVE this value; melee when below it.
# Nilah (225) is the longest short-melee; Urgot (350) is the shortest ranged;
# nothing sits in (325, 350) or (350, 425), so the >= 350 boundary is exact.
MELEE_RANGED_ATTACKRANGE_SPLIT: float = 350.0


def attackrange_is_ranged(attackrange) -> bool:
    """True iff ``attackrange`` classifies as a ranged champion.

    Fails CLOSED to False (melee) on a missing / malformed value, matching the
    historical callers: a missing champ record must never over-classify a
    champion as ranged (which would, e.g., let a melee champ be offered
    ranged-only items).
    """
    try:
        return float(attackrange or 0.0) >= MELEE_RANGED_ATTACKRANGE_SPLIT
    except (TypeError, ValueError):
        return False
