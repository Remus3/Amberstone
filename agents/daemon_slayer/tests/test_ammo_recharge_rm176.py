"""RM-176 - charge (ammo) recharge remainder preservation + gate invariants.

The defect: ``mana_sim._recharge_to`` snapped ``last_t`` to the poll clock on
the no-gain path, discarding the sub-recharge remainder. A charge slot polled
more often than its own recharge interval therefore accrued NOTHING however
long the fight ran, because every poll restarted the accrual window. The
full-charges snap was kept deliberately - banking time while capped would
refund a spent charge instantly - so this file pins BOTH halves: the remainder
must survive a below-max poll, and the snap must still fire at max.

Classes 1-3 are the regression fence (mutation-checked against the pre-fix
form). Classes 4-5 are standing invariants swept over live snapshot data.

Grounded against the live snapshot (patch 16.15.1 at authoring, 173 champions,
24 ammo-bearing slots). Both sweeps run in well under 1s wall clock, so no
sampling / narrowing is applied - every ammo slot and every champion is
covered.

Field provenance (grepped before use):
  * ``DataSnapshot.spell_ammo`` -> data_loader.py:314, returns
    ``{"max": [...], "recharge": [...]}`` or None.
  * ``ManaBoundedResult`` fields -> mana_sim.py:145-177 (mana_pool,
    mana_regen_per_s, mana_spent, duration_s, casts_allowed, total_mitigated,
    bounded_dps, unbounded_dps, oom_at_t, hits).
  * The unbounded reference pass is never ammo-gated -> mana_sim.py:519-528.
  * ``_recharge_to`` is reached through the module so a mutation probe can
    rebind it -> mana_sim.py:346 resolves the module global at call time.
"""

from __future__ import annotations

import math
import unittest
from pathlib import Path

from agents.daemon_slayer import mana_sim
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.mana_sim import compute_mana_bounded_combo

_SNAP = DataSnapshot.load()

_SLOTS = ("Q", "W", "E", "R")

# The shared target used by every sweep below - a mid-game bruiser-ish dummy.
_TARGET = {
    "target_armor": 100.0,
    "target_mr": 60.0,
    "target_max_hp": 2500.0,
    "target_bonus_hp": 1200.0,
    "mode": "SR",
}


def _ammo_slots(snap: DataSnapshot):
    """Every (champ_id, slot) in the snapshot whose spell carries a charge model."""
    out = []
    for champ_id in sorted(snap.champions):
        for slot in _SLOTS:
            if snap.spell_ammo(champ_id, slot):
                out.append((champ_id, slot))
    return tuple(out)


_AMMO_SLOTS = _ammo_slots(_SNAP)


def _slot_state(charges, max_charges, recharge, last_t=0.0):
    """Build the per-slot ledger dict shape ``_ammo_slot_state`` returns."""
    return {
        "charges": float(charges),
        "max": float(max_charges),
        "recharge": float(recharge),
        "last_t": float(last_t),
    }


class RechargeRemainderTests(unittest.TestCase):
    """REGRESSION - a below-max poll keeps the sub-recharge remainder."""

    def test_frequent_polling_matches_one_shot_poll(self):
        polled = _slot_state(0.0, 10.0, 10.0)
        for tick in range(5, 65, 5):
            mana_sim._recharge_to(polled, float(tick))

        one_shot = _slot_state(0.0, 10.0, 10.0)
        mana_sim._recharge_to(one_shot, 60.0)

        self.assertEqual(polled["charges"], 6.0)
        self.assertEqual(one_shot["charges"], 6.0)
        self.assertEqual(polled["charges"], one_shot["charges"])

    def test_non_divisor_cadence_accrues(self):
        # A 7s cadence against a 10s recharge never lands on an interval
        # boundary, so it rules out "the cadence happened to divide evenly" as
        # the explanation for the case above. Two whole intervals close by
        # t=28 (at t=20), the remaining 8s is carried, not discarded.
        st = _slot_state(0.0, 10.0, 10.0)
        for tick in (7.0, 14.0, 21.0, 28.0):
            mana_sim._recharge_to(st, tick)
        self.assertEqual(st["charges"], 2.0)
        self.assertEqual(st["last_t"], 20.0)

    def test_sub_interval_poll_alone_gains_nothing(self):
        # The remainder is carried, not rounded up: one 5s poll on a 10s
        # recharge is still zero charges.
        st = _slot_state(0.0, 10.0, 10.0)
        mana_sim._recharge_to(st, 5.0)
        self.assertEqual(st["charges"], 0.0)
        self.assertEqual(st["last_t"], 0.0)

    def test_zero_recharge_slot_never_regenerates(self):
        st = _slot_state(0.0, 3.0, 0.0)
        for tick in (10.0, 100.0, 1000.0):
            mana_sim._recharge_to(st, tick)
        self.assertEqual(st["charges"], 0.0)

    def test_accrual_is_capped_at_max(self):
        st = _slot_state(0.0, 2.0, 10.0)
        mana_sim._recharge_to(st, 500.0)
        self.assertEqual(st["charges"], 2.0)


class FullSlotSnapTests(unittest.TestCase):
    """REGRESSION - a FULL slot banks no time, so a spend is not refunded."""

    def test_full_slot_does_not_bank_time_across_a_spend(self):
        # This pins the half of the old behaviour that was deliberately KEPT.
        # Deleting the ``st["last_t"] = clock`` snap makes the slot carry 50s
        # of unspent credit and hand the charge straight back.
        st = _slot_state(2.0, 2.0, 10.0)
        mana_sim._recharge_to(st, 50.0)
        self.assertEqual(st["last_t"], 50.0)

        st["charges"] -= 1.0
        mana_sim._recharge_to(st, 50.5)
        self.assertEqual(st["charges"], 1.0)

    def test_spent_charge_returns_only_after_a_full_interval(self):
        st = _slot_state(2.0, 2.0, 10.0)
        mana_sim._recharge_to(st, 50.0)
        st["charges"] -= 1.0

        mana_sim._recharge_to(st, 59.9)
        self.assertEqual(st["charges"], 1.0)
        mana_sim._recharge_to(st, 60.0)
        self.assertEqual(st["charges"], 2.0)

    def test_repeated_full_polls_do_not_accumulate_credit(self):
        st = _slot_state(1.0, 1.0, 6.0)
        for tick in (5.0, 25.0, 100.0, 400.0):
            mana_sim._recharge_to(st, tick)
        st["charges"] -= 1.0
        mana_sim._recharge_to(st, 401.0)
        self.assertEqual(st["charges"], 0.0)


class AmmoRechargeEndToEndTests(unittest.TestCase):
    """REGRESSION - the fix is observable through the public entry point."""

    # Rengar Q at 16.15.1: max [1]*7, recharge [6.0, 6.0, 5.5, ...]. Four autos
    # between Q casts put the cast-to-cast gap under the recharge interval, so
    # the pre-fix walk polled the slot faster than it could ever accrue.
    SEQUENCE = ["Q"] + (["AA"] * 4 + ["Q"]) * 8

    @classmethod
    def setUpClass(cls):
        cls.result = compute_mana_bounded_combo(
            "Rengar", 13, item_ids=[], sequence=cls.SEQUENCE,
            snapshot=_SNAP, gate_ammo=True, **_TARGET
        )

    def test_rengar_q_is_an_ammo_slot(self):
        ammo = _SNAP.spell_ammo("Rengar", "Q")
        self.assertIsInstance(ammo, dict)
        self.assertTrue(ammo.get("max"))
        self.assertTrue(ammo.get("recharge"))

    def test_more_than_one_q_lands(self):
        # Pre-fix: exactly 1 ok Q then 8 no_ammo. Measured post-fix: 6 ok.
        ok_q = [
            h for h in self.result.hits
            if h.ability_key == "Q" and h.status == "ok"
        ]
        self.assertGreater(len(ok_q), 2)

    def test_bounded_dps_clears_the_pre_fix_ceiling(self):
        # Pre-fix bounded_dps was 52.59; measured post-fix 65.39. The threshold
        # sits between them with margin on both sides so ordinary engine drift
        # does not flip it, while the regression still trips it.
        self.assertGreater(self.result.bounded_dps, 58.0)

    def test_gate_still_bites_somewhere_in_the_rotation(self):
        # The fix must not have turned the gate off wholesale: Rengar Q holds a
        # single charge, so a rotation this tight still loses casts.
        statuses = [
            h.status for h in self.result.hits if h.ability_key == "Q"
        ]
        self.assertIn("no_ammo", statuses)
        self.assertLessEqual(
            self.result.bounded_dps, self.result.unbounded_dps
        )


class GateAmmoDominanceInvariantTests(unittest.TestCase):
    """INVARIANT - gating can only ever remove casts, never add them."""

    SEQUENCES = (
        ("QQQWE", ["Q", "Q", "Q", "W", "E"]),
        ("QWERAAx3", ["Q", "W", "E", "R", "AA"] * 3),
        ("EEEEAAAA", ["E", "E", "E", "E", "AA", "AA"]),
    )
    LEVELS = (6, 11, 18)

    def test_ammo_slots_present_in_snapshot(self):
        self.assertGreater(len(_AMMO_SLOTS), 0)

    def test_gate_on_is_dominated_by_gate_off(self):
        cases = 0
        gated = 0
        for champ_id, slot in _AMMO_SLOTS:
            for level in self.LEVELS:
                for seq_name, seq in self.SEQUENCES:
                    with self.subTest(
                        champ=champ_id, slot=slot, level=level, seq=seq_name
                    ):
                        kwargs = dict(
                            item_ids=[], sequence=seq, snapshot=_SNAP,
                            **_TARGET
                        )
                        on = compute_mana_bounded_combo(
                            champ_id, level, gate_ammo=True, **kwargs
                        )
                        off = compute_mana_bounded_combo(
                            champ_id, level, gate_ammo=False, **kwargs
                        )
                        cases += 1
                        self.assertLessEqual(
                            on.casts_allowed, off.casts_allowed
                        )
                        self.assertLessEqual(
                            on.total_mitigated, off.total_mitigated + 1e-6
                        )
                        # The reference pass is never ammo-gated
                        # (mana_sim.py:519-528) - exact equality, not a bound.
                        self.assertEqual(
                            on.unbounded_dps, off.unbounded_dps
                        )
                        if on.casts_allowed < off.casts_allowed:
                            gated += 1

        self.assertEqual(cases, len(_AMMO_SLOTS) * 9)
        # A dominance sweep that never sees the gate bite would pass against a
        # gate wired to nothing, so require real gating somewhere.
        self.assertGreater(gated, 0)


class ManaConservationInvariantTests(unittest.TestCase):
    """INVARIANT - no champion spends more mana than pool plus regen allows."""

    SEQUENCE = ["Q", "W", "E", "R", "AA"] * 8

    def test_no_champion_overspends_its_mana_budget(self):
        evaluated = 0
        finite_pool = 0
        went_oom = 0
        for champ_id in sorted(_SNAP.champions):
            with self.subTest(champ=champ_id):
                res = compute_mana_bounded_combo(
                    champ_id, 13, item_ids=[], sequence=self.SEQUENCE,
                    snapshot=_SNAP, **_TARGET
                )
                self.assertTrue(res.hits, "no resolvable rotation")
                evaluated += 1
                if res.oom_at_t is not None:
                    went_oom += 1
                if math.isinf(res.mana_pool):
                    # Manaless / infinite-resource champions have no budget to
                    # violate; mana_spent is unconstrained by construction.
                    continue
                finite_pool += 1
                budget = (
                    res.mana_pool
                    + res.mana_regen_per_s * res.duration_s
                    + 1e-3
                )
                self.assertLessEqual(res.mana_spent, budget)

        self.assertEqual(evaluated, len(_SNAP.champions))
        self.assertGreater(finite_pool, 0)
        self.assertGreater(went_oom, 0)


class AsciiHygieneTests(unittest.TestCase):
    """This file carries zero non-ASCII bytes (enforced repo rule)."""

    def test_this_file_is_ascii(self):
        data = Path(__file__).resolve().read_bytes()
        self.assertEqual([b for b in data if b > 0x7F], [])


if __name__ == "__main__":
    unittest.main()
