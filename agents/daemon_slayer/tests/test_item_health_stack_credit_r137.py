"""Item-side PERMANENT-HP-STACK (Heartsteel "Colossal Consumption") credit to the
EHP numerator (RM-99 / R137).

RED-first coverage for the NEW default-OFF ``assume_item_health_stacks`` seam on
``compute_ehp``. Today Heartsteel (3084 + Arena mirror 223084) earns EHP credit for
its proc DAMAGE only; the half that grants PERMANENT bonus max health equal to a
percent of that proc damage earns ZERO, and ``_effects_data.py`` disclaims it
verbatim in-line ("The HP-on-damage permanent stack ... is not modeled - that's
stat-side, not proc-side").

The structural reason is the familiar one. The champion-side twin
(``_passive_health_overrides.passive_health_stack_hp``, R46) is EXACTLY this axis
but is keyed by ``(champion_id, ability_key, form_index)`` so an item can never
match it, and the two item-side HP-numerator lanes that DO exist
(``_item_mana_health`` R105, ``_item_bonus_hp_amp`` R107) are both EXACT
conversions of an already-resolved stat and cannot express ``procs x hp_per_proc``.

Contract:
  * OFF (default) -> item_health_stack_hp == 0.0 -> physical/magical/true/blended/
    cc_blended/sustain EHP BYTE-IDENTICAL to an explicit ``False`` run.
  * ON + a Heartsteel build -> item_health_stack_hp ==
    pct * assumed_procs_at(level) * proc_damage(caster_max_hp), and
    physical/magical/true/blended EHP all STRICTLY RISE (a real max-HP pool add).
  * The credit is a PROXY (an assumed proc count), not an exact conversion - hence
    the ``assume_`` prefix it shares with its nearest sibling
    ``assume_passive_health_stacks``, rather than the ``apply_`` prefix the exact
    R105/R107 conversions carry.
  * A non-family build with the flag ON does NOT leak credit - not even one that
    carries large item bonus HP from OTHER items (Warmog's + Sunfire, no Heartsteel).
  * The proc-damage formula must not silently drift from the ``_effects_data`` 3084
    PeriodicProc it is derived from (pinned by a cross-check test below).

Magnitudes are asserted RELATIONALLY against the module's own registry constants,
never as hardcoded numbers, so a later coefficient re-source cannot leave a stale
literal passing in this file.
"""
from __future__ import annotations

import inspect
import math
import unittest

from agents.daemon_slayer._item_health_stack import (
    _ASSUMED_PROCS_BY_LEVEL,
    _ITEM_HEALTH_STACK_PCT,
    _proc_damage,
    item_health_stack_hp,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer.engine import build_champion

_SNAP: DataSnapshot | None = None

_HEARTSTEEL = "3084"
_HEARTSTEEL_ARENA = "223084"
_SUNFIRE = "3068"
_WARMOGS = "3083"

# Sion is the RM-99 measured champion: a tank whose ds.ehp route already ranks
# Heartsteel #3, and a big enough HP pool that the 6%-max-HP proc term is live.
_BUILD = (_HEARTSTEEL, _SUNFIRE)


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _resolved_max_hp(champion_id: str, level: int, items) -> float:
    """Resolved total max HP via the SAME engine build ``compute_ehp`` uses."""
    resolved = build_champion(
        _snap(), champion_id, level, item_ids=list(items), mode="SR",
    )
    return float(resolved.stats.get("hp", 0.0))


def _expected_hp(champion_id: str, level: int, items, item_id: str) -> float:
    """Recompute the credit from the registry constants + the same engine build."""
    pct = _ITEM_HEALTH_STACK_PCT[item_id]
    procs = _ASSUMED_PROCS_BY_LEVEL[level - 1]
    return pct * procs * _proc_damage(_resolved_max_hp(champion_id, level, items))


# ---------------- registry unit ----------------


class ItemHealthStackRegistryTests(unittest.TestCase):
    def test_registered_ids_are_base_plus_arena_mirror(self) -> None:
        self.assertEqual(
            set(_ITEM_HEALTH_STACK_PCT), {_HEARTSTEEL, _HEARTSTEEL_ARENA}
        )

    def test_arena_mirror_carries_the_base_nominal(self) -> None:
        self.assertAlmostEqual(
            _ITEM_HEALTH_STACK_PCT[_HEARTSTEEL_ARENA],
            _ITEM_HEALTH_STACK_PCT[_HEARTSTEEL],
            places=9,
        )

    def test_pct_is_a_credible_fraction(self) -> None:
        # Guards a units slip (8 instead of 0.08) without pinning the coefficient,
        # which is sourced separately and may be re-adjudicated.
        for iid, pct in _ITEM_HEALTH_STACK_PCT.items():
            self.assertGreater(pct, 0.0, msg=iid)
            self.assertLess(pct, 1.0, msg=iid)

    def test_unknown_item_id_yields_zero(self) -> None:
        self.assertEqual(item_health_stack_hp(["9999"], 3000.0, 13), 0.0)

    def test_empty_build_yields_zero(self) -> None:
        self.assertEqual(item_health_stack_hp([], 3000.0, 13), 0.0)

    def test_non_positive_max_hp_yields_zero(self) -> None:
        self.assertEqual(item_health_stack_hp([_HEARTSTEEL], 0.0, 13), 0.0)
        self.assertEqual(item_health_stack_hp([_HEARTSTEEL], -3000.0, 13), 0.0)

    def test_two_family_ids_take_the_max_not_the_sum(self) -> None:
        # Heartsteel's stack is a UNIQUE passive and the base + Arena mirror are
        # mutually exclusive in any real build, so a synthetic double-equip must
        # not double-count (the R107 MAX convention).
        both = item_health_stack_hp([_HEARTSTEEL, _HEARTSTEEL_ARENA], 3000.0, 13)
        one = item_health_stack_hp([_HEARTSTEEL], 3000.0, 13)
        self.assertAlmostEqual(both, one, places=9)

    def test_credit_is_pct_times_procs_times_proc_damage(self) -> None:
        hp = 3000.0
        got = item_health_stack_hp([_HEARTSTEEL], hp, 13)
        want = (
            _ITEM_HEALTH_STACK_PCT[_HEARTSTEEL]
            * _ASSUMED_PROCS_BY_LEVEL[12]
            * _proc_damage(hp)
        )
        self.assertAlmostEqual(got, want, places=9)
        self.assertGreater(got, 0.0)


# ---------------- the assumed-procs curve ----------------


class AssumedProcsCurveTests(unittest.TestCase):
    def test_curve_has_one_entry_per_champion_level(self) -> None:
        self.assertEqual(len(_ASSUMED_PROCS_BY_LEVEL), 18)

    def test_curve_is_monotonic_non_decreasing(self) -> None:
        # The R46 stack-count-proxy convention: a deliberately LOW, monotonic
        # curve, so a flipped-on scorer never OVER-states the pool.
        for i in range(1, len(_ASSUMED_PROCS_BY_LEVEL)):
            self.assertGreaterEqual(
                _ASSUMED_PROCS_BY_LEVEL[i], _ASSUMED_PROCS_BY_LEVEL[i - 1], msg=str(i)
            )

    def test_curve_is_non_negative(self) -> None:
        for i, procs in enumerate(_ASSUMED_PROCS_BY_LEVEL):
            self.assertGreaterEqual(procs, 0.0, msg=str(i))

    def test_higher_level_credits_at_least_as_much(self) -> None:
        hp = 3000.0
        lo = item_health_stack_hp([_HEARTSTEEL], hp, 4)
        hi = item_health_stack_hp([_HEARTSTEEL], hp, 16)
        self.assertGreater(hi, lo)

    def test_level_is_clamped_to_the_curve_bounds(self) -> None:
        hp = 3000.0
        self.assertEqual(
            item_health_stack_hp([_HEARTSTEEL], hp, 0),
            item_health_stack_hp([_HEARTSTEEL], hp, 1),
        )
        self.assertEqual(
            item_health_stack_hp([_HEARTSTEEL], hp, 99),
            item_health_stack_hp([_HEARTSTEEL], hp, 18),
        )


# ---------------- proc-damage anti-drift ----------------


class ProcDamageAgreesWithEffectsDataTests(unittest.TestCase):
    def test_matches_the_effects_data_periodic_proc(self) -> None:
        # _item_health_stack owns its own copy of the proc-damage formula (the
        # registry must not import the effects lambda), so pin the two together:
        # a patch that re-sources one and not the other fails HERE rather than
        # silently mispricing the stack half.
        from agents.daemon_slayer._effects_data import ITEM_EFFECTS

        proc = ITEM_EFFECTS[_HEARTSTEEL].periodics[0]

        class _Ctx:
            caster_max_hp = 3000.0

        self.assertAlmostEqual(
            _proc_damage(3000.0), proc.bonus_damage(_Ctx()), places=9
        )


# ---------------- OFF byte-identical ----------------


class ItemHealthStackOffByteIdenticalTests(unittest.TestCase):
    def _ehp(self, *, on, items=_BUILD, champ="Sion", level=13):
        return compute_ehp(
            _snap(), champion_id=champ, level=level, item_ids=list(items),
            mode="SR", assume_item_health_stacks=on,
        )

    def test_seam_default_is_false(self) -> None:
        param = inspect.signature(compute_ehp).parameters["assume_item_health_stacks"]
        self.assertIs(param.default, False)

    def test_flag_absent_equals_explicit_false(self) -> None:
        absent = compute_ehp(
            _snap(), champion_id="Sion", level=13, item_ids=list(_BUILD), mode="SR",
        )
        off = self._ehp(on=False)
        for field in (
            "physical_ehp", "magical_ehp", "true_ehp", "blended_ehp",
            "cc_blended_ehp", "effective_ehp_with_sustain",
        ):
            self.assertAlmostEqual(
                getattr(absent, field), getattr(off, field), places=9, msg=field
            )

    def test_off_field_is_zero(self) -> None:
        self.assertEqual(self._ehp(on=False).item_health_stack_hp, 0.0)

    def test_ids_alone_do_not_arm_the_seam(self) -> None:
        # Equipping Heartsteel is NOT consent - only the flag is.
        self.assertEqual(self._ehp(on=False).item_health_stack_hp, 0.0)


# ---------------- ON credit (EHP numerator) ----------------


class ItemHealthStackOnCreditTests(unittest.TestCase):
    def _ehp(self, *, on, items=_BUILD, champ="Sion", level=13):
        return compute_ehp(
            _snap(), champion_id=champ, level=level, item_ids=list(items),
            mode="SR", assume_item_health_stacks=on,
        )

    def test_opted_in_is_actually_non_zero(self) -> None:
        # Guards the guard: if the ON path were also 0.0 every other test in this
        # class would pass vacuously.
        self.assertGreater(self._ehp(on=True).item_health_stack_hp, 0.0)

    def test_on_field_equals_the_registry_formula(self) -> None:
        on = self._ehp(on=True)
        expected = _expected_hp("Sion", 13, _BUILD, _HEARTSTEEL)
        self.assertGreater(expected, 0.0)
        self.assertAlmostEqual(on.item_health_stack_hp, expected, places=6)

    def test_on_raises_every_ehp_type(self) -> None:
        off = self._ehp(on=False)
        on = self._ehp(on=True)
        for field in (
            "physical_ehp", "magical_ehp", "true_ehp", "blended_ehp",
        ):
            with self.subTest(field=field):
                self.assertGreater(getattr(on, field), getattr(off, field))

    def test_arena_mirror_also_credits(self) -> None:
        on = compute_ehp(
            _snap(), champion_id="Sion", level=13, item_ids=[_HEARTSTEEL_ARENA],
            mode="SR", assume_item_health_stacks=True,
        )
        self.assertGreater(on.item_health_stack_hp, 0.0)


# ---------------- isolation (no leak) ----------------


class ItemHealthStackIsolationTests(unittest.TestCase):
    def test_other_hp_items_with_flag_on_are_byte_identical(self) -> None:
        # Warmog's (3083) + Sunfire (3068) grant large item bonus HP but NEITHER
        # carries a permanent-HP-per-proc stack. Arming the seam must not leak.
        items = [_WARMOGS, _SUNFIRE]
        off = compute_ehp(
            _snap(), champion_id="Sion", level=13, item_ids=items, mode="SR",
        )
        on = compute_ehp(
            _snap(), champion_id="Sion", level=13, item_ids=items, mode="SR",
            assume_item_health_stacks=True,
        )
        self.assertEqual(on.item_health_stack_hp, 0.0)
        for field in ("physical_ehp", "magical_ehp", "true_ehp", "blended_ehp"):
            self.assertAlmostEqual(
                getattr(on, field), getattr(off, field), places=9, msg=field
            )

    def test_non_hp_build_no_credit(self) -> None:
        off = compute_ehp(
            _snap(), champion_id="Garen", level=13, item_ids=["3075"], mode="SR",
        )
        on = compute_ehp(
            _snap(), champion_id="Garen", level=13, item_ids=["3075"], mode="SR",
            assume_item_health_stacks=True,
        )
        self.assertEqual(on.item_health_stack_hp, 0.0)
        self.assertAlmostEqual(on.blended_ehp, off.blended_ehp, places=9)

    def test_does_not_disturb_the_sibling_hp_lanes(self) -> None:
        # R105 / R107 are independent lanes: arming this seam must leave their
        # fields untouched on a build that carries all three carriers.
        items = [_HEARTSTEEL, _WARMOGS, _SUNFIRE]
        base = compute_ehp(
            _snap(), champion_id="Sion", level=13, item_ids=items, mode="SR",
            apply_item_bonus_hp_amp=True,
        )
        both = compute_ehp(
            _snap(), champion_id="Sion", level=13, item_ids=items, mode="SR",
            apply_item_bonus_hp_amp=True, assume_item_health_stacks=True,
        )
        self.assertAlmostEqual(
            both.item_bonus_hp_amp_hp, base.item_bonus_hp_amp_hp, places=9
        )
        self.assertGreater(both.item_health_stack_hp, 0.0)


# ---------------- to_dict ----------------


class ItemHealthStackToDictTests(unittest.TestCase):
    def test_to_dict_carries_field(self) -> None:
        r = compute_ehp(
            _snap(), champion_id="Sion", level=13, item_ids=list(_BUILD), mode="SR",
            assume_item_health_stacks=True,
        )
        d = r.to_dict()
        self.assertIn("item_health_stack_hp", d)
        self.assertGreater(d["item_health_stack_hp"], 0.0)
        self.assertTrue(
            math.isclose(d["item_health_stack_hp"], r.item_health_stack_hp)
        )


if __name__ == "__main__":
    unittest.main()
