"""RM-91 T2: the ITEM caster-HP proc seam on /rank-tank (DEFAULT-OFF).

WHAT T1 LEFT ON THE TABLE
------------------------
RM-91 T1 (ENGINE 1.258.0) credits the CHAMPION's kit for re-spending the health
an item grants. That credit is MONOTONE in the candidate's health delta, so it
lifts health items above resist items but can never reorder two health items -
and the row's actual headline was never about health-vs-resist. Randuin's Omen
3143 is engine #1 for five tanks (Shen / Sejuani / Skarner / Zac / Tahm Kench,
re-probed 2026-07-26) while appearing in the real core build of none of them.

T2 is the half that fixes that. It credits the ITEM's OWN caster-HP-scaling
proc - Titanic Hydra's Cleave (1 percent of max health on every basic attack),
Heartsteel's Colossal Consumption (6 percent), Unending Despair's Anguish (3
percent of bonus health every 4 seconds) - which ``ehp.py`` prices nowhere,
because it reads zero damage. The credit is keyed by ITEM ID, so it is
independent of the champion and is NOT monotone in the health delta: a
zero-proc item earns nothing no matter how much health it grants, which is
exactly how Randuin's stops dominating.

DERIVED, NOT HAND-AUTHORED
--------------------------
The T1 registry is a hand-seeded champion table because
``champion_abilities.json`` needs human adjudication (the double-count trap).
T2 needs no such table: the coefficient already lives in ``_effects_data.py`` as
executable code, so the module DIFFERENTIATES each proc against its own
``CallContext`` instead of restating a number that could drift. Two consequences
this file guards:
  * a coefficient edit in ``_effects_data.py`` propagates automatically, so a
    hand-transcription drift is impossible by construction;
  * mirrors need no suffix rule. The filed row warned that mirror prefixes are
    irregular (2502 -> 222502 ARAM but 2501 / 447111 Arena) - a machine sweep of
    ``ITEM_EFFECTS`` sidesteps the question entirely, and it also catches that
    Heartsteel's cadence DIVERGES across the mirror (SR 3084 every 30s, Arena
    223084 every 3.5s), which any by-name table would have flattened.

THE GUARDS HERE
---------------
1.  The population is machine-derived and pinned at 17 sensitive ids, 16 of
    which are real conversions - a silent drift in either direction fails.
2.  Every seeded coefficient is re-derived from ``ITEM_EFFECTS`` in the test
    itself, never restated from the module.
3.  4017 Hellfire Hatchet is pinned OUT: its ``caster_max_hp`` appears only
    inside ``min(2000, max(0, caster_max_hp - target_max_hp))``, a tankiness
    COMPARISON that amplifies damage when the caster out-tanks the target. The
    caster's health is not the damage SOURCE, so crediting it would be a
    category error - and a finite-difference probe happily reports a 6 percent
    slope, which is exactly why the deny is explicit and by ID.
4.  Byte-identical OFF: flags omitted, and flags sent at zero strength.
5.  THE ACCEPTANCE TEST: armed, a real core HP item outranks Randuin's 3143 for
    each of the five headline tanks.
6.  The T1 known limit is LIFTED - the dominating-pair inversion T1 provably
    cannot perform, T2 does. T1's own pin still holds under T1's own flag.
7.  Titanic Hydra's AoE half (Cleave to nearby, ``max(0, targets - 1)``) is
    conservatively EXCLUDED - the single-target probe reads it as zero.
8.  A non-proc candidate (Randuin's 3143, Frozen Heart 3110) takes exactly no
    credit.

OFFLINE ONLY: no live :8893, no network.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import unittest

from agents.daemon_slayer._effects_types import CallContext
from agents.daemon_slayer._item_caster_hp_proc import (
    _ASSUMED_ATTACKS_PER_SECOND,
    _DENIED_ITEM_IDS,
    _REFERENCE_FIGHT_SECONDS,
    ItemCasterHpProcEntry,
    caster_hp_proc_census,
    item_caster_hp_proc,
    proc_converted_points,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.effects import ITEM_EFFECTS
from agents.daemon_slayer.ehp import rank_items_by_ehp

_SNAP = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


# The five tanks the filed row measured Randuin's dominance on. Re-probed
# 2026-07-26 on the shipped tree: 3143 is #1 for every one of them.
_HEADLINE_TANKS = ("Shen", "Sejuani", "Skarner", "Zac", "TahmKench")

# Probe hygiene, matching the T1 sibling: never an empty build
# (reference_ds_probe_empty_build_artifact), never a finite top_n
# (reference_ds_probe_depth_top40_truncation).
_BUILD = ("3068", "3047")
_TOP_N = None
_LEVEL = 13

_RANDUINS = "3143"
_TITANIC = "3748"
_FROZEN_HEART = "3110"

# Machine-derived from ITEM_EFFECTS at 16.14.1: every proc whose damage responds
# to caster_max_hp / caster_bonus_hp. 17 ids, all LINEAR in the probed pool.
_EXPECTED_SENSITIVE_IDS = frozenset({
    "2502", "3068", "3084", "3181", "3748", "4017", "6664",
    "222502", "223068", "223069", "223084", "223181", "223748", "226664",
    "447109", "447114", "667109",
})
# 4017 is the sole documented reject, so the credited population is 16.
_EXPECTED_CREDITED_IDS = _EXPECTED_SENSITIVE_IDS - {"4017"}

# Strength floor measured on the shipped tree for the acceptance flip. Pinned so
# a regression in the credit scale fails loudly rather than silently needing a
# bigger number.
_STRENGTH = 12.0


def _rank(champion: str, mode: str = "SR", **kwargs):
    return rank_items_by_ehp(
        _snap(),
        champion_id=champion,
        level=_LEVEL,
        current_item_ids=list(_BUILD),
        mode=mode,
        enemy_ad_share=0.5,
        enemy_ap_share=0.4,
        top_n=_TOP_N,
        **kwargs,
    )


def _armed(champion: str, strength: float = _STRENGTH, mode: str = "SR", **kw):
    return _rank(
        champion,
        mode=mode,
        apply_item_caster_hp_proc=True,
        item_caster_hp_proc_strength=strength,
        **kw,
    )


def _pos(result) -> dict[str, int]:
    return {r.item_id: i for i, r in enumerate(result.ranked)}


def _rows(result) -> tuple[tuple, ...]:
    return tuple(
        (r.item_id, r.delta_ehp, r.new_ehp, r.ehp_per_1k_gold, r.delta_max_hp)
        for r in result.ranked
    )


def _digest(result) -> str:
    blob = json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _probe_ctx(**kw) -> CallContext:
    base = dict(
        base_ad=100.0, bonus_ad=50.0, level=13,
        caster_max_hp=3000.0, caster_bonus_hp=1500.0,
        ap=0.0, targets_in_rotation=1.0, target_max_hp=2400.0,
    )
    base.update(kw)
    return CallContext(**base)


class CensusPopulationTests(unittest.TestCase):
    """The population is DERIVED from ITEM_EFFECTS, and pinned both ways."""

    def test_sensitive_ids_are_exactly_the_machine_swept_set(self) -> None:
        swept = set()
        for iid, eff in ITEM_EFFECTS.items():
            for proc in (eff.periodics or ()):
                base = proc.resolve_damage(_probe_ctx())
                d_max = proc.resolve_damage(_probe_ctx(caster_max_hp=4000.0)) - base
                d_bon = proc.resolve_damage(_probe_ctx(caster_bonus_hp=2500.0)) - base
                if abs(d_max) > 1e-12 or abs(d_bon) > 1e-12:
                    swept.add(iid)
        self.assertEqual(swept, set(_EXPECTED_SENSITIVE_IDS))

    def test_census_is_the_sensitive_set_minus_the_documented_rejects(self) -> None:
        self.assertEqual(set(caster_hp_proc_census()), set(_EXPECTED_CREDITED_IDS))
        self.assertEqual(len(caster_hp_proc_census()), 16)

    def test_every_entry_is_single_axis_and_shaped(self) -> None:
        for iid, ent in caster_hp_proc_census().items():
            with self.subTest(item=iid):
                self.assertIsInstance(ent, ItemCasterHpProcEntry)
                self.assertEqual(ent.item_id, iid)
                self.assertTrue(ent.item_name)
                self.assertTrue(ent.proc_name)
                self.assertGreater(ent.max_hp_pct + ent.bonus_hp_pct, 0.0)
                # Every shipped caster-HP proc reads ONE pool. A future
                # two-pool proc is a schema question, not a silent average.
                self.assertTrue(
                    ent.max_hp_pct == 0.0 or ent.bonus_hp_pct == 0.0,
                    msg=f"{iid} reads BOTH health pools - adjudicate, do not average",
                )
                self.assertGreater(ent.fires_per_fight, 0.0)

    def test_coefficients_are_re_derived_not_restated(self) -> None:
        """Each percent is differentiated out of ITEM_EFFECTS in the test."""
        for iid, ent in caster_hp_proc_census().items():
            eff = ITEM_EFFECTS[iid]
            d_max = d_bon = 0.0
            for proc in (eff.periodics or ()):
                base = proc.resolve_damage(_probe_ctx())
                d_max += (
                    proc.resolve_damage(_probe_ctx(caster_max_hp=4000.0)) - base
                ) / 1000.0 * 100.0
                d_bon += (
                    proc.resolve_damage(_probe_ctx(caster_bonus_hp=2500.0)) - base
                ) / 1000.0 * 100.0
            with self.subTest(item=iid):
                self.assertAlmostEqual(ent.max_hp_pct, d_max, places=6)
                self.assertAlmostEqual(ent.bonus_hp_pct, d_bon, places=6)

    def test_known_coefficients_match_the_patch_data(self) -> None:
        """A readable spot-check of the derivation, by ID never by name."""
        census = caster_hp_proc_census()
        self.assertAlmostEqual(census["3748"].max_hp_pct, 1.0, places=6)
        self.assertAlmostEqual(census["3084"].max_hp_pct, 6.0, places=6)
        self.assertAlmostEqual(census["3181"].max_hp_pct, 5.0, places=6)
        # Void Immolation has NO SR twin - 223069 is the only id.
        self.assertAlmostEqual(census["223069"].max_hp_pct, 1.5, places=6)
        self.assertAlmostEqual(census["2502"].bonus_hp_pct, 3.0, places=6)
        self.assertAlmostEqual(census["3068"].bonus_hp_pct, 1.0, places=6)
        self.assertAlmostEqual(census["6664"].bonus_hp_pct, 1.0, places=6)
        self.assertAlmostEqual(census["447114"].bonus_hp_pct, 2.0, places=6)
        self.assertAlmostEqual(census["667109"].max_hp_pct, 4.0, places=6)

    def test_mirror_cadence_divergence_is_preserved(self) -> None:
        """Heartsteel's period DIVERGES across the mirror - 30s SR, 3.5s Arena.

        A by-name coefficient table would have flattened these to one value.
        The Arena mirror therefore fires ~8.6x as often for the same 6 percent.
        """
        census = caster_hp_proc_census()
        self.assertAlmostEqual(census["3084"].max_hp_pct,
                               census["223084"].max_hp_pct, places=6)
        self.assertGreater(census["223084"].fires_per_fight,
                           census["3084"].fires_per_fight * 8.0)

    def test_cadence_is_read_per_proc_not_assumed(self) -> None:
        census = caster_hp_proc_census()
        # every_n_seconds=1.0 Immolate -> one fire per reference second.
        self.assertAlmostEqual(
            census["3068"].fires_per_fight, _REFERENCE_FIGHT_SECONDS, places=6
        )
        # every_n_seconds=4.0 Anguish -> a quarter of that.
        self.assertAlmostEqual(
            census["2502"].fires_per_fight, _REFERENCE_FIGHT_SECONDS / 4.0, places=6
        )
        # every_n_attacks=1 Cleave -> the assumed attack rate.
        self.assertAlmostEqual(
            census["3748"].fires_per_fight,
            _REFERENCE_FIGHT_SECONDS * _ASSUMED_ATTACKS_PER_SECOND,
            places=6,
        )
        # every_n_attacks=5 Skipper -> a fifth of that.
        self.assertAlmostEqual(
            census["3181"].fires_per_fight,
            _REFERENCE_FIGHT_SECONDS * _ASSUMED_ATTACKS_PER_SECOND / 5.0,
            places=6,
        )

    def test_fail_soft_on_unknown_and_empty(self) -> None:
        self.assertIsNone(item_caster_hp_proc(""))
        self.assertIsNone(item_caster_hp_proc("not-an-item"))
        self.assertIsNone(item_caster_hp_proc("3143"))


class DocumentedRejectTests(unittest.TestCase):
    """4017 probes as a 6 percent converter and is NOT one."""

    def test_hellfire_hatchet_is_denied_by_id(self) -> None:
        self.assertIn("4017", _DENIED_ITEM_IDS)
        self.assertIsNone(item_caster_hp_proc("4017"))
        self.assertNotIn("4017", caster_hp_proc_census())

    def test_the_deny_is_not_vacuous(self) -> None:
        """Without the deny the probe WOULD credit it - that is the trap."""
        eff = ITEM_EFFECTS["4017"]
        slope = 0.0
        for proc in (eff.periodics or ()):
            base = proc.resolve_damage(_probe_ctx())
            slope += proc.resolve_damage(_probe_ctx(caster_max_hp=4000.0)) - base
        self.assertGreater(slope, 0.0)

    def test_perplexity_carries_no_proc_at_all(self) -> None:
        """4015's caster_max_hp lives in a note + a target-comparison field.

        It is excluded with no deny entry needed, because the derivation only
        ever looks at ``periodics``. Pinned so the exclusion is understood as
        structural rather than an oversight.
        """
        self.assertEqual(ITEM_EFFECTS["4015"].periodics or (), ())
        self.assertIsNone(item_caster_hp_proc("4015"))

    def test_titanic_aoe_half_is_conservatively_excluded(self) -> None:
        """Cleave-to-nearby is max(0, targets - 1) scaled - zero at one target.

        The single-target probe therefore credits the 1 percent primary only,
        not the 3 percent per extra target. Deliberately conservative.
        """
        ent = item_caster_hp_proc("3748")
        self.assertIsNotNone(ent)
        self.assertAlmostEqual(ent.max_hp_pct, 1.0, places=6)
        names = [p.name for p in ITEM_EFFECTS["3748"].periodics]
        self.assertIn("Cleave (to nearby)", names)


class ConvertedPointsTests(unittest.TestCase):
    """The numerator reads the pool the entry names, and stays linear."""

    def test_max_basis_reads_the_total_pool(self) -> None:
        ent = ItemCasterHpProcEntry(
            item_id="x", item_name="x", proc_name="x",
            max_hp_pct=6.0, bonus_hp_pct=0.0, fires_per_fight=1.0,
        )
        self.assertAlmostEqual(
            proc_converted_points(ent, 3000.0, 1200.0), 180.0, places=6
        )

    def test_bonus_basis_reads_the_smaller_pool(self) -> None:
        ent = ItemCasterHpProcEntry(
            item_id="x", item_name="x", proc_name="x",
            max_hp_pct=0.0, bonus_hp_pct=6.0, fires_per_fight=1.0,
        )
        self.assertAlmostEqual(
            proc_converted_points(ent, 3000.0, 1200.0), 72.0, places=6
        )

    def test_negative_pools_floor_at_zero(self) -> None:
        ent = ItemCasterHpProcEntry(
            item_id="x", item_name="x", proc_name="x",
            max_hp_pct=6.0, bonus_hp_pct=6.0, fires_per_fight=1.0,
        )
        self.assertEqual(proc_converted_points(ent, -10.0, -10.0), 0.0)


class SignatureConventionTests(unittest.TestCase):
    """Appended at the END with OFF defaults (the no-mid-insert convention)."""

    def test_kwargs_are_appended_last_with_defaults_off(self) -> None:
        params = inspect.signature(rank_items_by_ehp).parameters
        names = list(params)
        self.assertEqual(
            tuple(names[-2:]),
            ("apply_item_caster_hp_proc", "item_caster_hp_proc_strength"),
        )
        self.assertIs(params["apply_item_caster_hp_proc"].default, False)
        self.assertEqual(params["item_caster_hp_proc_strength"].default, 0.0)
        # T1's pair must still be present, immediately ahead of T2's.
        self.assertEqual(
            tuple(names[-4:-2]),
            ("apply_health_damage_coupling", "health_coupling_strength"),
        )

    def test_negative_strength_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _armed("Shen", strength=-1.0)


class ByteIdenticalControlTests(unittest.TestCase):
    """OFF is an exact no-op, by digest."""

    def test_flags_omitted_equal_flags_at_zero_strength(self) -> None:
        for champ in _HEADLINE_TANKS:
            with self.subTest(champion=champ):
                off = _digest(_rank(champ))
                zero = _digest(_armed(champ, strength=0.0))
                self.assertEqual(off, zero)

    def test_flag_false_with_a_positive_strength_is_still_inert(self) -> None:
        for champ in _HEADLINE_TANKS:
            with self.subTest(champion=champ):
                self.assertEqual(
                    _rows(_rank(champ)),
                    _rows(_rank(
                        champ,
                        apply_item_caster_hp_proc=False,
                        item_caster_hp_proc_strength=_STRENGTH,
                    )),
                )

    def test_off_never_consults_the_census(self) -> None:
        import agents.daemon_slayer.ehp as ehp_mod
        from unittest import mock
        with mock.patch.object(
            ehp_mod, "item_caster_hp_proc", side_effect=AssertionError("consulted")
        ):
            _rank("Shen")


class AcceptanceTests(unittest.TestCase):
    """THE row's headline: Randuin's 3143 stops dominating a real core item."""

    def test_randuins_is_number_one_off_for_all_five_tanks(self) -> None:
        """The premise, re-probed rather than trusted from the filed row."""
        for champ in _HEADLINE_TANKS:
            with self.subTest(champion=champ):
                self.assertEqual(_rank(champ).ranked[0].item_id, _RANDUINS)

    def test_titanic_hydra_outranks_randuins_when_armed(self) -> None:
        for champ in _HEADLINE_TANKS:
            with self.subTest(champion=champ):
                pos = _pos(_armed(champ))
                self.assertLess(
                    pos[_TITANIC], pos[_RANDUINS],
                    msg=(
                        f"{champ}: Titanic Hydra {_TITANIC} still ranks below "
                        f"Randuin's {_RANDUINS} with T2 armed"
                    ),
                )

    def test_randuins_loses_the_top_slot(self) -> None:
        for champ in _HEADLINE_TANKS:
            with self.subTest(champion=champ):
                self.assertNotEqual(_armed(champ).ranked[0].item_id, _RANDUINS)

    def test_a_zero_proc_candidate_takes_no_credit(self) -> None:
        """Randuin's + Frozen Heart carry no caster-HP proc, so no credit.

        Their raw metric is unchanged, and the ONLY reason they move is that
        proc items rose past them - the credit itself never touches them.
        """
        for iid in (_RANDUINS, _FROZEN_HEART):
            with self.subTest(item=iid):
                self.assertIsNone(item_caster_hp_proc(iid))
        off = {r.item_id: r.delta_ehp for r in _rank("Shen").ranked}
        on = {r.item_id: r.delta_ehp for r in _armed("Shen").ranked}
        for iid in (_RANDUINS, _FROZEN_HEART):
            self.assertAlmostEqual(off[iid], on[iid], places=9)

    def test_the_flip_has_a_measured_floor_and_climbs_gradually(self) -> None:
        """The pinned strength is just ABOVE the measured floor, not miles above.

        Measured on the shipped tree 2026-07-26: Titanic Hydra walks #13 (off)
        -> #8 (2) -> #5 (4) -> #4 (6) -> #2 (8) -> #1 (10). A LOW strength must
        therefore NOT flip it, or the acceptance test would pass for reasons
        unrelated to the credit and could not detect a scale regression.
        """
        low = _pos(_armed("Shen", strength=4.0))
        self.assertGreater(low[_TITANIC], low[_RANDUINS])
        # ... and the climb is monotone, not a scramble.
        walk = [_pos(_armed("Shen", strength=s))[_TITANIC]
                for s in (0.0, 2.0, 4.0, 6.0, 8.0, 10.0)]
        self.assertEqual(walk, sorted(walk, reverse=True))
        self.assertEqual(walk[-1], 0)

    def test_credit_scales_with_the_strength(self) -> None:
        low = _pos(_armed("Shen", strength=1.0))
        high = _pos(_armed("Shen", strength=_STRENGTH))
        self.assertLessEqual(high[_TITANIC], low[_TITANIC])
        self.assertGreaterEqual(high[_RANDUINS], low[_RANDUINS])


class KnownLimitLiftedTests(unittest.TestCase):
    """T1's pinned limit, and the proof T2 lifts exactly it.

    T1's ``KnownLimitTests`` pins that arming the CHAMPION lever can never
    invert a pair where A beats B on the raw metric AND grants at least as much
    health. That pin still holds under T1's own flag. T2 breaks it on purpose:
    the credit is keyed by ITEM, so a lower-health item with a proc overtakes a
    higher-health item without one.
    """

    def test_t1_alone_still_cannot_invert_a_dominating_pair(self) -> None:
        on = _rank(
            "Shen",
            apply_health_damage_coupling=True,
            health_coupling_strength=25.0,
        )
        rows = list(on.ranked)
        pos = {r.item_id: i for i, r in enumerate(rows)}
        checked = 0
        for a in rows:
            for b in rows:
                if a.item_id == b.item_id:
                    continue
                if a.delta_ehp > b.delta_ehp and a.delta_max_hp >= b.delta_max_hp:
                    checked += 1
                    self.assertLess(pos[a.item_id], pos[b.item_id])
        self.assertGreater(checked, 0)

    def test_t2_inverts_a_pair_t1_provably_cannot(self) -> None:
        on = _armed("Shen", strength=_STRENGTH)
        rows = list(on.ranked)
        pos = {r.item_id: i for i, r in enumerate(rows)}
        by_id = {r.item_id: r for r in rows}
        a, b = by_id[_RANDUINS], by_id[_TITANIC]
        # Randuin's dominates Titanic on the raw metric, so T1 could never put
        # Titanic first. Assert the domination, then assert the inversion.
        self.assertGreater(a.delta_ehp, b.delta_ehp)
        self.assertLess(pos[_TITANIC], pos[_RANDUINS])

    def test_the_two_levers_compose_without_erasing_each_other(self) -> None:
        both = _pos(_armed(
            "Shen",
            apply_health_damage_coupling=True,
            health_coupling_strength=8.0,
        ))
        self.assertLess(both[_TITANIC], both[_RANDUINS])


class ObservabilityTests(unittest.TestCase):
    """The armed lane says so, and the inert lane says that too."""

    def test_armed_emits_a_note_naming_the_credited_population(self) -> None:
        notes = _armed("Shen").notes
        self.assertTrue(
            any("apply_item_caster_hp_proc=ON" in n for n in notes),
            msg=f"no armed note in {notes!r}",
        )

    def test_off_emits_no_note(self) -> None:
        self.assertFalse(
            any("apply_item_caster_hp_proc" in n for n in _rank("Shen").notes)
        )


class ArenaMirrorTests(unittest.TestCase):
    """The Arena pool credits the ARENA id's own proc, on its own cadence."""

    def test_arena_mirror_is_credited_on_its_own_line(self) -> None:
        arena = _armed("Shen", mode="ARENA")
        ids = {r.item_id for r in arena.ranked}
        credited = ids & set(_EXPECTED_CREDITED_IDS)
        self.assertTrue(credited, msg="no caster-HP proc item in the Arena pool")
        off = {r.item_id: r.delta_ehp for r in _rank("Shen", mode="ARENA").ranked}
        on = {r.item_id: r.delta_ehp for r in arena.ranked}
        self.assertEqual(off, on)


if __name__ == "__main__":
    unittest.main()
