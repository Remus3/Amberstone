"""ENGINE 1.171.0 (R60, 2026-07-02) - wielder Heal/Shield Power (HSP) helper.

Sums the caster's own ``heal_shield_amp_pct`` across equipped items - the
curated ``enchanter_items.json`` field, the SAME source ``hps.py`` reads for its
ally-throughput amp. Heal/Shield Power amplifies the heals and shields the
WIELDER applies to itself; it does NOT amplify vamp (lifesteal / omnivamp /
spellvamp / drain).

Used by the DEFAULT-OFF ``assume_hsp_amp`` seams in ``ehp.py`` (the wielder's
own ItemShield pool - Sterak's / Shieldbow / Maw) and ``sustain.py`` (the
wielder's kit REGEN self-heal). The seam callers gate on ``assume_hsp_amp`` and
a 0.0 return keeps their output byte-identical.

The ``.hps`` import is LAZY (inside the function) so importing this module at
another module's top level is cycle-free.
"""
from __future__ import annotations

from typing import Iterable, Optional


def sum_wielder_hsp_pct(
    item_ids: Optional[Iterable[str | int]],
    patch: Optional[str] = None,
) -> float:
    """Sum ``heal_shield_amp_pct`` across the wielder's items (additive, fail-soft).

    Additive per the real-LoL HSP model (Redemption 0.10 + Mikael 0.12 = 0.22),
    matching the directive "(1 + hsp_pct)" convention. Items without an HSP field
    contribute 0.0. Returns 0.0 on an empty / None inventory or any load failure -
    the seam callers gate on ``assume_hsp_amp`` so a 0.0 return is byte-identical.

    ``patch`` defaults to the current-patch cached enchanter formulas; pass an
    explicit patch string to read a specific snapshot.
    """
    ids = [str(i) for i in (item_ids or []) if i is not None and str(i)]
    if not ids:
        return 0.0
    try:
        from .hps import EnchanterFormulasSnapshot, load_default_formulas

        snap = (
            load_default_formulas()
            if patch is None
            else EnchanterFormulasSnapshot.load(patch)
        )
    except Exception:
        return 0.0
    total = 0.0
    for iid in ids:
        formula = snap.formulas.get(iid)
        if formula is not None:
            total += float(formula.heal_shield_amp_pct)
    return total
