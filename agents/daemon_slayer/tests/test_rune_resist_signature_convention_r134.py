"""R134: machine-enforce the R132 seam conventions that a comment alone did not hold.

Two DISTINCT guards live here, and they exist for opposite reasons: one locks a
drift that DID happen, the other locks a "fix" that must NEVER happen.

GUARD 1 - trailing-kwarg convention (a real drift, corrected by this slice).
``compute_ehp`` appended the R132 pair ``apply_rune_resist_grants`` / ``rune_ids``
at the END of its signature and said so in an inline comment: "Appended at END of
the signature per the no-mid-signature-insert convention". Its three sibling
entry points (``rank_items_by_ehp``, ``compute_hybrid``, ``rank_items_by_hybrid``)
inserted the SAME pair mid-signature, between ``apply_item_resist_grants`` and
``apply_item_bonus_hp_amp``, shifting the positional index of every parameter
after it. Nothing broke - the suite was green, because no caller passes
positionally that deep into a 30-plus parameter signature - so this was latent
convention drift, NOT a functional regression. A comment cannot enforce a
convention; this test can. When the NEXT seam lands it must append after the
R132 pair and update this guard, which is the intended forcing function.

GUARD 2 - the ``total_armor`` contract (a REFUTED "regression", pinned so it stays
refuted). An audit reported that ``compute_ehp`` "misses item bonus_armor" when it
passes ``total_armor=armor`` to the rune lane, and proposed
``total_armor=armor+bonus_armor+ext_armor+item_resist_armor``. That is WRONG on the
identity of every added term:

  * ``armor`` is ``stats["armor"]`` - the RESOLVED build armor, which ALREADY
    contains item armor. Nothing item-side is missing.
  * ``bonus_armor`` (ehp.py, ``bonus_armor, bonus_mr = resist_grants(...)``) is the
    CHAMPION resist-grant registry output - a PEER conditional-grant lane, not a
    stat.
  * ``item_resist_armor`` is the ITEM resist-grant registry output - another peer
    lane, itself derived from ``total_armor=armor``.
  * ``ext_armor`` is an ALLY-conferred external resist, not the champion's own build.

Adding them would feed three peer grant lanes into the fourth, so Aftershock would
take 75 percent of other grants (grant-on-grant compounding), and the result would
depend on the SOURCE ORDER of four peer registries - the last one evaluated is the
only one that sees the other three. ``_rune_resist_grants.rune_resist_grants``
documents the real contract verbatim: ``total_armor`` is "the champion's RESOLVED
build resists (base per-level + items)", and the caller passes "the same values the
champion ``resist_grants`` and the item ``item_resist_grants`` receive". Guard 2
asserts exactly that same-values clause, so applying the proposed change turns this
test RED instead of silently over-crediting the tank cohort the feed exists for.

OFFLINE ONLY: no live :8893, no network.
"""
from __future__ import annotations

import inspect
import unittest
from unittest import mock

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp, rank_items_by_ehp
from agents.daemon_slayer.hybrid import compute_hybrid, rank_items_by_hybrid

_SNAP = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


# The R132 pair, in the order compute_ehp established.
_R132_TAIL = ("apply_rune_resist_grants", "rune_ids")

# R136 (ENGINE 1.225.0) is the NEXT seam this guard's docstring anticipated: the
# RM-101 numerator pair appended AFTER the R132 pair. Both new flags reuse the
# existing ``rune_ids`` transport rather than adding a second ids parameter, so
# the R132 pair stays adjacent and ordered - it is simply no longer the tail.
_R136_TAIL = ("apply_rune_health_grants", "apply_rune_hsp_amp")

# R137 (ENGINE 1.226.0, RM-99) is the next seam appended after the R136 pair: the
# item-side permanent-HP-per-proc stack (Heartsteel). It adds no ids parameter -
# the item ids already ride the existing ``item_ids`` / ``current_item_ids``
# transport - so once again the R132 pair stays adjacent and ordered.
_R137_TAIL = ("assume_item_health_stacks",)

# ENGINE 1.227.0 (RM-101 + RM-103) appends the next two seams after R137:
# apply_rune_flat_mitigation (Bone Plating 8473, reusing the existing rune_ids
# transport) and assume_item_proc_heal (Unending Despair 2502 / 222502, riding
# the existing item_ids transport). Neither adds an ids parameter, so once again
# every earlier group stays adjacent and ordered - it is simply no longer the tail.
_R1227_TAIL = ("apply_rune_flat_mitigation", "assume_item_proc_heal")

# ENGINE 1.229.0 (R142) appends the RM-101 RESIDUAL pair: apply_rune_self_heal
# (Second Wind 8444) and apply_rune_shield_grants (Guardian 8465). Both ride the
# existing rune_ids transport, so once again no ids parameter lands and every
# earlier group stays adjacent and ordered - the 1.227.0 pair is simply no longer
# the tail.
_R1229_TAIL = ("apply_rune_self_heal", "apply_rune_shield_grants")

_SEAM_ENTRY_POINTS = (
    compute_ehp,
    rank_items_by_ehp,
    compute_hybrid,
    rank_items_by_hybrid,
)


class RuneResistTrailingKwargConventionTests(unittest.TestCase):
    """GUARD 1: the R132 pair must be the LAST two parameters on every entry point."""

    def test_r132_pair_is_the_signature_tail_on_every_entry_point(self) -> None:
        # R136, R137, the 1.227.0 pair then the 1.229.0 pair appended after the
        # R132 pair, so the pair is now the -9:-7 slice. The invariant the guard
        # actually protects is unchanged: these seam kwargs live at the END, in
        # order, never mid-signature.
        expected = (
            _R132_TAIL + _R136_TAIL + _R137_TAIL + _R1227_TAIL + _R1229_TAIL
        )
        for fn in _SEAM_ENTRY_POINTS:
            with self.subTest(fn=fn.__name__):
                names = tuple(inspect.signature(fn).parameters)
                self.assertEqual(
                    names[-9:], expected,
                    msg=(
                        f"{fn.__name__} must append the seam kwargs at the END "
                        f"of its signature (compute_ehp's stated convention); got "
                        f"tail {names[-9:]}. A new seam appends AFTER these seven "
                        f"and updates this guard."
                    ),
                )

    def test_r137_seam_defaults_off_on_every_entry_point(self) -> None:
        # DEFAULT-OFF, same contract as the R132 / R136 seams: a flipped default is
        # an engine behavior change, never a signature-tidy side effect.
        for fn in _SEAM_ENTRY_POINTS:
            with self.subTest(fn=fn.__name__):
                params = inspect.signature(fn).parameters
                for name in _R137_TAIL:
                    self.assertIs(
                        params[name].default, False, msg=f"{fn.__name__}.{name}"
                    )

    def test_r136_pair_defaults_the_seam_off_on_every_entry_point(self) -> None:
        # Both R136 flags are DEFAULT-OFF; a flipped default is an engine behavior
        # change, never a signature-tidy side effect. Same contract as R132's.
        for fn in _SEAM_ENTRY_POINTS:
            with self.subTest(fn=fn.__name__):
                params = inspect.signature(fn).parameters
                for name in _R136_TAIL:
                    self.assertIs(params[name].default, False, msg=f"{fn.__name__}.{name}")

    def test_r132_pair_is_adjacent_and_ordered(self) -> None:
        for fn in _SEAM_ENTRY_POINTS:
            with self.subTest(fn=fn.__name__):
                names = list(inspect.signature(fn).parameters)
                flag_at = names.index("apply_rune_resist_grants")
                ids_at = names.index("rune_ids")
                self.assertEqual(
                    ids_at, flag_at + 1,
                    msg=f"{fn.__name__}: rune_ids must directly follow its flag",
                )

    def test_every_entry_point_defaults_the_seam_off(self) -> None:
        # The seam is DEFAULT-OFF everywhere; a flipped default is an engine
        # behavior change, never a signature-tidy side effect.
        for fn in _SEAM_ENTRY_POINTS:
            with self.subTest(fn=fn.__name__):
                params = inspect.signature(fn).parameters
                self.assertIs(params["apply_rune_resist_grants"].default, False)
                self.assertEqual(tuple(params["rune_ids"].default), ())


class RuneResistTotalArmorContractTests(unittest.TestCase):
    """GUARD 2: the rune lane and the item lane receive the SAME resolved resists."""

    def _spy_both_lanes(self, **kw):
        captured = {}

        def _item_spy(item_ids, **kwargs):
            captured["item"] = kwargs
            return (0.0, 0.0)

        def _rune_spy(rune_ids, **kwargs):
            captured["rune"] = kwargs
            return (0.0, 0.0)

        with mock.patch(
            "agents.daemon_slayer._item_resist_grants.item_resist_grants", _item_spy
        ), mock.patch(
            "agents.daemon_slayer._rune_resist_grants.rune_resist_grants", _rune_spy
        ):
            compute_ehp(
                _snap(), champion_id="Ornn", level=13,
                item_ids=["3068", "3075"], mode="SR",
                apply_item_resist_grants=True,
                apply_rune_resist_grants=True,
                rune_ids=["8439", "8429", "8242"],
                **kw,
            )
        return captured

    def test_rune_lane_receives_the_same_resists_as_the_item_lane(self) -> None:
        captured = self._spy_both_lanes()
        self.assertIn("item", captured, "item resist lane never fired")
        self.assertIn("rune", captured, "rune resist lane never fired")
        for key in ("total_armor", "total_mr", "base_armor", "base_mr"):
            with self.subTest(key=key):
                self.assertAlmostEqual(
                    captured["rune"][key], captured["item"][key], places=9,
                    msg=(
                        f"{key} diverged between the item and rune resist lanes. "
                        f"Both must receive the champion's RESOLVED build resists. "
                        f"Feeding peer grant-lane output (bonus_armor / "
                        f"item_resist_armor / ext_armor) into total_armor is "
                        f"grant-on-grant compounding and is source-order dependent."
                    ),
                )

    def test_total_armor_excludes_ally_conferred_external_resist(self) -> None:
        # An ALLY grant must not inflate the champion's own bonus-resist base, or
        # Aftershock's 75-percent-of-bonus term would pay out on a teammate's aura.
        plain = self._spy_both_lanes()
        with_ally = self._spy_both_lanes(
            external_resist_armor=60.0, external_resist_mr=60.0,
        )
        self.assertAlmostEqual(
            with_ally["rune"]["total_armor"], plain["rune"]["total_armor"], places=9,
        )
        self.assertAlmostEqual(
            with_ally["rune"]["total_mr"], plain["rune"]["total_mr"], places=9,
        )


class RuneResistRankerByteIdentityTests(unittest.TestCase):
    """Moving the kwargs must not move a single ranked row."""

    def _ranked(self, fn, **kw):
        res = fn(
            _snap(), champion_id="Ornn", level=13,
            current_item_ids=["3068"], mode="SR", top_n=10, **kw,
        )
        return [(r.item_id, round(r.gold, 6)) for r in res.ranked]

    def test_rank_items_by_ehp_absent_equals_explicit_off(self) -> None:
        absent = self._ranked(rank_items_by_ehp)
        off = self._ranked(
            rank_items_by_ehp,
            apply_rune_resist_grants=False, rune_ids=["8439", "8429", "8242"],
        )
        self.assertEqual(absent, off)
        self.assertTrue(absent, "ranker returned no rows - fixture is not exercising")

    def test_rank_items_by_hybrid_absent_equals_explicit_off(self) -> None:
        absent = self._ranked(rank_items_by_hybrid)
        off = self._ranked(
            rank_items_by_hybrid,
            apply_rune_resist_grants=False, rune_ids=["8439", "8429", "8242"],
        )
        self.assertEqual(absent, off)
        self.assertTrue(absent, "ranker returned no rows - fixture is not exercising")


if __name__ == "__main__":
    unittest.main()
