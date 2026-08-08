"""RM-101 rune NUMERATOR seams wired into compute_ehp (R136, ENGINE 1.225.0).

The half R132 deliberately did not build. R132 shipped the rune RESIST feed - a
DENOMINATOR add folded into ``eff_armor`` / ``eff_mr``. These two seams are both
NUMERATOR-side, and they reuse the SAME ``rune_ids`` transport R132 already
plumbed, so no new ids parameter lands on any entry point:

  * ``apply_rune_health_grants`` - Overgrowth 8451 permanent max health, plus
    Grasp 8437's SELF side (heal + permanent health). ``rune_procs.py:606``
    scores Grasp's DAMAGE and admits verbatim "(heal + permanent-HP sides not
    modeled)", so the self side earned ZERO before this slice.
  * ``apply_rune_hsp_amp`` - Revitalize 8453's flat 5% Heal and Shield Power.
    ``_hsp_amp.sum_wielder_hsp_pct`` sums ``heal_shield_amp_pct`` across EQUIPPED
    ITEMS ONLY, so a rune could never reach it.

Verbatim DDragon 16.14.1 ``runesReforged.json`` longDescs, the authoritative
source reproduced rather than paraphrased (the R132 Aftershock-cap lesson):

  * 8451 Overgrowth: "Absorb life essence from monsters or enemy minions that die
    near you, permanently gaining 3 maximum health for every 8.<br><br>When
    you've absorbed 120 monsters or enemy minions, gain an additional 3.5%
    maximum health."
  * 8437 GraspOfTheUndying: "Every 4s in combat, your next basic attack on a
    champion will:<li>Deal bonus magic damage equal to 3.5% of your max health
    <li>Heal you for 1.3% of your max health<li>Permanently increase your health
    by 5<br><rules><i>Ranged Champions:</i> Damage, healing, and permanent health
    gained are 40% effective.</rules>"
  * 8453 Revitalize: "Gain 5% Heal and Shield Power.<br><br>Heals and shields you
    cast or receive are 10% stronger on targets below 40% health."

Revitalize's SECOND clause is deliberately NOT modelled: "targets below 40%
health" is a TARGET-STATE conditional and that arc is operator-CLOSED. Only the
flat 5% ships.

Font of Life 8463 is NOT wired and must not be - its base heal is an unresolved
``@BaseHeal@`` template variable in live DDragon, confirmed present in ALL FOUR
vendored patch snapshots (16.11.1 / 16.12.1 / 16.13.1 / 16.14.1). That is a
genuine data ceiling; inventing a number is the exact failure mode the R132
lesson exists to prevent. ``test_font_of_life_is_not_credited`` pins the absence
so a future cycle cannot quietly seed a guess.

Contract:
  * OFF (default) -> BYTE-IDENTICAL to 1.224.0, including when ``rune_ids``
    carries a full Resolve page. Passing ids alone does NOT arm either seam.
  * The two flags are INDEPENDENT - arming one must not move the other's term.
  * ON -> strictly greater EHP (both seams are numerator adds).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp

_SNAP = None

# A full Resolve page: the two R136 health runes, Revitalize, the three R132
# resist runes, and the two runes that must never be credited.
_FULL_PAGE = ["8451", "8437", "8453", "8439", "8429", "8242", "8463", "8465"]


def _snap():
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


# Sunfire Aegis + Thornmail: a pure-resist tank build carrying NO self-shield.
_TANK_BUILD = ["3068", "3075"]
# Sterak's Gage + Thornmail. Heal/Shield Power amplifies the SHIELD pool, so the
# rune-HSP seam is only OBSERVABLE on a build that owns a self-shield - on
# _TANK_BUILD the shield pool is 0.0 and the amp multiplies nothing. That is
# correct engine behavior (see _hsp_amp.py: the wielder's own ItemShield pool),
# not an inert seam, and test_hsp_amp_needs_a_shield_to_amplify pins the
# distinction so a future reader does not "fix" a working seam.
_SHIELD_BUILD = ["3053", "3075"]


def _ehp(*, health=False, hsp=False, runes=(), champ="Ornn", level=13,
         items=None):
    return compute_ehp(
        _snap(), champion_id=champ, level=level,
        item_ids=list(items if items is not None else _TANK_BUILD), mode="SR",
        apply_rune_health_grants=health,
        apply_rune_hsp_amp=hsp,
        rune_ids=list(runes),
    )


class DefaultOffInertnessTests(unittest.TestCase):
    """OFF is byte-identical, and ids alone do not arm the seam."""

    def test_engine_version_pinned(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.275.1")

    def test_omitting_the_flags_matches_explicit_false(self) -> None:
        implicit = compute_ehp(
            _snap(), champion_id="Ornn", level=13,
            item_ids=["3068", "3075"], mode="SR",
        )
        explicit = _ehp(health=False, hsp=False)
        for field in ("physical_ehp", "magical_ehp", "true_ehp"):
            with self.subTest(field=field):
                self.assertEqual(
                    getattr(implicit, field), getattr(explicit, field),
                    msg="explicit False must equal omitting the kwarg entirely",
                )

    def test_rune_ids_alone_do_not_arm_either_seam(self) -> None:
        # The R132 inertness contract, extended: supplying a full Resolve page
        # with both flags OFF must not move a single EHP field.
        bare = _ehp(health=False, hsp=False, runes=())
        paged = _ehp(health=False, hsp=False, runes=_FULL_PAGE)
        for field in ("physical_ehp", "magical_ehp", "true_ehp"):
            with self.subTest(field=field):
                self.assertEqual(getattr(bare, field), getattr(paged, field))


class RuneHealthGrantSeamTests(unittest.TestCase):
    """apply_rune_health_grants raises the numerator; ranged is discounted."""

    def test_health_grants_raise_every_per_type_ehp(self) -> None:
        off = _ehp(health=False, runes=_FULL_PAGE)
        on = _ehp(health=True, runes=_FULL_PAGE)
        for field in ("physical_ehp", "magical_ehp", "true_ehp"):
            with self.subTest(field=field):
                self.assertGreater(getattr(on, field), getattr(off, field))

    def test_unknown_runes_leave_the_seam_inert_even_when_armed(self) -> None:
        # Arming the flag with a page carrying NO credited rune must stay
        # byte-identical - the credit comes from the registry, not the flag.
        off = _ehp(health=False, runes=["8005", "8010"])
        on = _ehp(health=True, runes=["8005", "8010"])
        self.assertEqual(on.physical_ehp, off.physical_ehp)

    def test_ranged_champion_gets_less_grasp_credit_than_melee(self) -> None:
        # Grasp's <rules> clause: healing and permanent health are 40% effective
        # on ranged. Overgrowth has NO such clause, so it is NOT discounted -
        # which is why this asserts a strict inequality on the DELTA, not a ratio.
        grasp_only = ["8437"]
        melee_delta = (
            _ehp(health=True, runes=grasp_only, champ="Ornn").physical_ehp
            - _ehp(health=False, runes=grasp_only, champ="Ornn").physical_ehp
        )
        ranged_delta = (
            _ehp(health=True, runes=grasp_only, champ="Caitlyn").physical_ehp
            - _ehp(health=False, runes=grasp_only, champ="Caitlyn").physical_ehp
        )
        self.assertGreater(melee_delta, 0.0)
        self.assertGreater(ranged_delta, 0.0)
        self.assertLess(ranged_delta, melee_delta)


class RuneHspAmpSeamTests(unittest.TestCase):
    """apply_rune_hsp_amp reaches the shield pool a rune could not reach before."""

    def test_hsp_amp_raises_ehp_when_revitalize_is_on_the_page(self) -> None:
        off = _ehp(hsp=False, runes=["8453"], items=_SHIELD_BUILD)
        on = _ehp(hsp=True, runes=["8453"], items=_SHIELD_BUILD)
        self.assertGreater(on.physical_ehp, off.physical_ehp)

    def test_hsp_amp_is_inert_without_revitalize(self) -> None:
        off = _ehp(hsp=False, runes=["8439", "8429"], items=_SHIELD_BUILD)
        on = _ehp(hsp=True, runes=["8439", "8429"], items=_SHIELD_BUILD)
        self.assertEqual(on.physical_ehp, off.physical_ehp)

    def test_hsp_amp_needs_a_shield_to_amplify(self) -> None:
        # Heal/Shield Power scales the shield pool. On a shieldless build there is
        # nothing to scale, so arming the seam is correctly a no-op - the credit
        # comes from the build owning a self-shield, not from the flag.
        off = _ehp(hsp=False, runes=["8453"], items=_TANK_BUILD)
        on = _ehp(hsp=True, runes=["8453"], items=_TANK_BUILD)
        self.assertEqual(on.physical_ehp, off.physical_ehp)


class SeamIndependenceTests(unittest.TestCase):
    """The two flags are separately flippable - one must not carry the other."""

    def test_arming_health_alone_differs_from_arming_hsp_alone(self) -> None:
        # Run on the shield build so BOTH seams have something to move.
        kw = {"runes": _FULL_PAGE, "items": _SHIELD_BUILD}
        base = _ehp(**kw).physical_ehp
        health_only = _ehp(health=True, **kw).physical_ehp
        hsp_only = _ehp(hsp=True, **kw).physical_ehp
        both = _ehp(health=True, hsp=True, **kw).physical_ehp
        self.assertGreater(health_only, base)
        self.assertGreater(hsp_only, base)
        self.assertGreater(both, health_only)
        self.assertGreater(both, hsp_only)


class DataBlockedRunesStayUncreditedTests(unittest.TestCase):
    """Font of Life and Guardian must earn nothing - one data-blocked, one AP-blind."""

    def test_font_of_life_is_not_credited(self) -> None:
        # 8463's magnitude is an unresolved @BaseHeal@ template var in every
        # vendored patch. Crediting it would mean inventing the number.
        off = _ehp(health=False, hsp=False, runes=["8463"])
        on = _ehp(health=True, hsp=True, runes=["8463"])
        self.assertEqual(on.physical_ehp, off.physical_ehp)

    def test_guardian_is_not_credited(self) -> None:
        # 8465's shield carries a "+20% of your ability power" term and ehp.py is
        # AP-blind (zero AP references), so a partial credit would systematically
        # under-count. Spec'd unbuilt rather than shipped wrong.
        off = _ehp(health=False, hsp=False, runes=["8465"])
        on = _ehp(health=True, hsp=True, runes=["8465"])
        self.assertEqual(on.physical_ehp, off.physical_ehp)


if __name__ == "__main__":
    unittest.main()
