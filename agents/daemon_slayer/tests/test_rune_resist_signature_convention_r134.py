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

OFFLINE ONLY: no live :8860, no network.
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

# R145 (ENGINE 1.232.0) appends the FIRST seam in this chain that is OFFENSIVE:
# apply_rune_offense_grants, the adaptive AD/AP rune stat-grant lane. It rides the
# existing rune_ids transport, so once again no ids parameter lands. It differs
# from every earlier group in ONE respect and the guard has to express it: an
# offense seam has no business on an EHP entry point, so it lands ONLY on the two
# hybrid entry points (and on compute_dps, which is not in this guard's set). The
# invariant is unchanged - seam kwargs live at the END, in order, never
# mid-signature - it is simply no longer the SAME tail on all four functions.
_R145_TAIL = ("apply_rune_offense_grants",)

# RM-98 (2026-07-24) appends the cast-rate propensity prior after R145. Like
# R145 it is an OFFENSE-side seam - it re-bases the ability half of the damage
# axis onto a combat-window cast rate - so it lands ONLY on the two hybrid entry
# points. It adds no ids parameter (the per-spell rows already ride the existing
# item_ids / current_item_ids transport into compute_ability_dps), so every
# earlier group stays adjacent and ordered; R145 is simply no longer the tail.
_RM98_TAIL = ("apply_cast_rate_propensity_prior",)

# RM-87 / row A-18 (2026-07-25) appends the champion RESIST -> DAMAGE coupling
# pair. It is the mirror image of R145 / RM-98: those are offense seams and so
# land on the HYBRID pair only, while this one corrects the TANK objective's
# blindness to a kit that re-spends its own resists as damage, so it lands on the
# EHP pair only. It adds no ids parameter (the champion id is already the first
# argument). The invariant is unchanged - seam kwargs live at the END, in order,
# never mid-signature - so the 1.229.0 pair is simply no longer the EHP tail.
_RM87_TAIL = ("apply_resist_damage_coupling", "resist_coupling_strength")

# ENGINE 1.250.0 appends the three assumed-share seams to ``rank_items_by_ehp``
# ONLY. They already existed on ``compute_ehp`` (mid-signature, index 37 of 59)
# and were merely never exposed on the ranker, so the ranker gains a new tail
# while ``compute_ehp`` keeps the RM-87 pair as its own. That asymmetry is why
# the two EHP entry points are now cased separately below rather than sharing
# one expected tuple. The invariant the guard protects is unchanged: newly
# EXPOSED seam kwargs land at the END, in order, never mid-signature.
_A1250_TAIL = (
    "assume_item_crit_dr",
    "assume_item_aa_dr",
    "assume_item_enemy_as_slow",
)

# RM-115 p4 (ENGINE 1.252.0) appends the RM-86 L1 kit-conversion gate to
# ``rank_items_by_hybrid`` ONLY. This is the HYBRID mirror of the 1.250.0 split
# above: the seam is a SORT-KEY transform (``kit_conversion.py:16-18`` - the
# registry supplies the vector, each ranker scales its own key), and
# ``compute_hybrid`` scores one resolved build and has no sort key, so putting
# the kwarg there would be a signature-tidy pretending to be a capability. The
# two hybrid entry points are therefore cased separately below rather than
# sharing one expected tuple, exactly as the two EHP ones already are. The
# invariant the guard protects is unchanged: seam kwargs land at the END, in
# order, never mid-signature.
_RM115P4_TAIL = ("kit_conversion_strength",)

# R193 slice B (crit-weighted vamp heal pool) appends the crit-weight seam to
# ``compute_ehp`` ONLY. It weights the vamp heal POOL - a magnitude computed
# inside the per-build EHP math - so it belongs on the function that computes
# that pool and nowhere else; ``rank_items_by_ehp`` orders builds and holds no
# heal pool of its own, so exposing it there would be a signature-tidy
# pretending to be a capability (the same reasoning the 1.250.0 and RM-115 p4
# splits above already record, applied in the opposite direction). That is why
# ``compute_ehp`` gains a tail entry the ranker does not. The invariant the
# guard protects is unchanged: seam kwargs land at the END, in order, never
# mid-signature.
_R193_TAIL = ("assume_crit_weighted_vamp",)

# R194 landed as two independent slices in one round, each appending to a
# DIFFERENT entry point, so the two tails carry slice-suffixed names. Merging
# them under one shared name would let the second definition shadow the first
# and silently retarget both case rows onto one tuple.
#
# R194 slice A (RM-116 part a) appends the item-passive omnivamp credit to
# ``rank_items_by_ehp``. Unlike the 1.250.0 / RM-115 p4 / R193 splits above this
# one does NOT introduce an asymmetry: ``compute_ehp`` has carried the same
# kwarg since 2026-07-10, mid-signature, and is not moved (moving it would break
# every positional construction). The ranker is simply catching up, so the name
# appears once here, on the entry point that newly EXPOSED it. The invariant the
# guard protects is unchanged: newly exposed seam kwargs land at the END, in
# order, never mid-signature.
_R194A_TAIL = ("assume_max_stacks_omnivamp",)

# R194 slice C (RM-116c, lifesteal credit on Ravenous Hydra Cleave + Crescent)
# appends a PAIR to ``compute_ehp`` ONLY, for the same reason R193 did: the
# credit is a magnitude computed inside the per-build heal pool, and
# ``rank_items_by_ehp`` orders builds and holds no heal pool of its own. The
# pair is ordered value-then-gate (``targets_in_rotation`` names the AoE enemy
# count, matching the DPS side's ``CallContext`` field; ``assume_cleave_
# lifesteal`` is the DEFAULT-OFF arm) because passing the value alone must not
# arm the credit. The invariant the guard protects is unchanged: seam kwargs
# land at the END, in order, never mid-signature.
_R194C_TAIL = ("targets_in_rotation", "assume_cleave_lifesteal")

# RM-91 T1 appends the champion HEALTH -> DAMAGE coupling pair to
# ``rank_items_by_ehp`` ONLY. It is the health-axis twin of the RM-87 resist
# pair, and like that pair it is a RANKING-only lever - but unlike RM-87 it is
# not mirrored onto ``compute_ehp`` for signature parity, because nothing in the
# EHP math reads it and an unread kwarg on the scalar entry point is a
# signature-tidy pretending to be a capability (the same reasoning the 1.250.0 /
# RM-115 p4 / R193 splits above already record). The pair is ordered
# gate-then-magnitude, matching RM-87. The invariant the guard protects is
# unchanged: newly exposed seam kwargs land at the END, in order, never
# mid-signature.
_RM91_TAIL = ("apply_health_damage_coupling", "health_coupling_strength")

# RM-91 T2 appends the ITEM caster-HP proc pair after T1's, again to
# ``rank_items_by_ehp`` ONLY and for the same reason: nothing in the EHP math
# reads it, so mirroring it onto ``compute_ehp`` would be a signature-tidy
# pretending to be a capability. T2 is a SEPARATE pair from T1 rather than a
# widening of it because the two credit different payers - T1 the champion's kit
# re-spending the health DELTA, T2 the candidate item re-spending the EXISTING
# pool - so one merged flag would arm a credit the other never earned. Ordered
# gate-then-magnitude, matching both siblings.
_RM91T2_TAIL = ("apply_item_caster_hp_proc", "item_caster_hp_proc_strength")
# RM-118 (2026-07-29): the wielder HSP item amp reaches the EHP ranker, appended
# after the RM-91 T2 pair on rank_items_by_ehp ONLY (compute_ehp already carried
# it since R60, in its own earlier position).
_RM118_TAIL = ("assume_hsp_amp",)

_EHP_ENTRY_POINTS = (compute_ehp, rank_items_by_ehp)
_HYBRID_ENTRY_POINTS = (compute_hybrid, rank_items_by_hybrid)
_SEAM_ENTRY_POINTS = _EHP_ENTRY_POINTS + _HYBRID_ENTRY_POINTS


class RuneResistTrailingKwargConventionTests(unittest.TestCase):
    """GUARD 1: the R132 pair must be the LAST two parameters on every entry point."""

    def test_r132_pair_is_the_signature_tail_on_every_entry_point(self) -> None:
        # R136, R137, the 1.227.0 pair then the 1.229.0 pair appended after the
        # R132 pair, then R145 and RM-98 appended after THAT on the hybrid pair
        # only (both are offense-side seams) and RM-87 appended after it on the
        # EHP pair only (a tank-objective seam), then R193 after RM-87 on
        # compute_ehp alone (it weights a per-build heal pool, which only that
        # function holds), then R194 split two ways in one round: slice C after
        # R193 on compute_ehp alone for the same per-build-heal-pool reason, and
        # slice A on rank_items_by_ehp alone because the ranker is the entry
        # point that newly EXPOSED the omnivamp seam. The invariant the guard actually protects is
        # unchanged: these seam kwargs live at the END, in order, never
        # mid-signature.
        shared = (
            _R132_TAIL + _R136_TAIL + _R137_TAIL + _R1227_TAIL + _R1229_TAIL
        )
        hybrid_shared = shared + _R145_TAIL + _RM98_TAIL
        cases = (
            ((compute_ehp,), shared + _RM87_TAIL + _R193_TAIL + _R194C_TAIL),
            (
                (rank_items_by_ehp,),
                shared + _RM87_TAIL + _A1250_TAIL + _R194A_TAIL + _RM91_TAIL
                + _RM91T2_TAIL + _RM118_TAIL,
            ),
            ((compute_hybrid,), hybrid_shared + _RM118_TAIL),
            ((rank_items_by_hybrid,), hybrid_shared + _RM115P4_TAIL + _RM118_TAIL),
        )
        for fns, expected in cases:
            for fn in fns:
                with self.subTest(fn=fn.__name__):
                    names = tuple(inspect.signature(fn).parameters)
                    n = len(expected)
                    self.assertEqual(
                        names[-n:], expected,
                        msg=(
                            f"{fn.__name__} must append the seam kwargs at the "
                            f"END of its signature (compute_ehp's stated "
                            f"convention); got tail {names[-n:]}. A new seam "
                            f"appends AFTER these and updates this guard."
                        ),
                    )

    def test_kit_conversion_gate_is_ranker_only_and_defaults_off(self) -> None:
        """The RM-86 L1 gate belongs on entry points that SORT, and only those.

        It scales a sort key, so a ``compute_*`` entry point - which scores one
        already-resolved build and never orders anything - would carry a kwarg
        that looks like a capability and does nothing. ``rank_items_by_ehp``
        already carried it before RM-115 p4; the p4 slice added the hybrid
        ranker, completing the pair. Asserting the ABSENCE is the load-bearing
        half here.
        """
        for fn in (rank_items_by_ehp, rank_items_by_hybrid):
            with self.subTest(fn=fn.__name__):
                params = inspect.signature(fn).parameters
                for name in _RM115P4_TAIL:
                    self.assertIn(name, params, msg=f"{fn.__name__}.{name}")
                    self.assertEqual(
                        params[name].default, 0.0, msg=f"{fn.__name__}.{name}"
                    )
        for fn in (compute_ehp, compute_hybrid):
            with self.subTest(fn=fn.__name__):
                for name in _RM115P4_TAIL:
                    self.assertNotIn(
                        name, inspect.signature(fn).parameters,
                        msg=f"{fn.__name__}.{name} - this entry point does not sort",
                    )

    def test_r145_offense_seam_is_hybrid_only_and_defaults_off(self) -> None:
        # An OFFENSE seam must never appear on an EHP entry point - that would be
        # a signature-tidy pretending to be an axis. And like every seam before
        # it, it is DEFAULT-OFF.
        for fn in _HYBRID_ENTRY_POINTS:
            with self.subTest(fn=fn.__name__):
                params = inspect.signature(fn).parameters
                for name in _R145_TAIL:
                    self.assertIn(name, params, msg=f"{fn.__name__}.{name}")
                    self.assertIs(
                        params[name].default, False, msg=f"{fn.__name__}.{name}"
                    )
        for fn in _EHP_ENTRY_POINTS:
            with self.subTest(fn=fn.__name__):
                params = inspect.signature(fn).parameters
                for name in _R145_TAIL:
                    self.assertNotIn(name, params, msg=f"{fn.__name__}.{name}")

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
