"""Regression: the Cluster-C degenerate-scenario fallback must fire PER PHASE.

The original fallback (test_dps_aphelios_degenerate_scenario.py) was gated on
``not any(phase_dps.values())`` - it only fired when EVERY phase carried zero
basic-attack DPS. Some champions' lolmath scenario rotations encode
``basic: 0`` / ``basicTime: 0`` in the mid and late blocks but a real
basic-attack rotation in early. For those, the all-phase guard never fired, and
when the SELECTED phase was one of the zero ones ``compute_dps`` returned a
silent, note-free ``weighted_dps == 0.0``.

Measured 2026-07-25 at patch 16.14.1 over the full 173-champion roster (level
13, SR, no items): 3 champions land in the hole and ship ``weighted_dps ==
0.0`` - Azir (raw 94.33), Karthus (raw 63.9), Viktor (raw 70.8). All three are
degenerate in {mid, late} and healthy in early.

Downstream consequence that made this expensive: ``onhit_dps.py`` computes
``onhit_dps = ability_dps + baseline_auto_dps``, so ``/rank-onhit`` silently
degrades to a ``/rank-mage``-identical response for any champion whose
``weighted_dps`` is 0.0, with ``notes == []`` saying nothing about it. That
mechanism caused RM-48 (Azir) to be misdiagnosed for four sessions as a missing
"soldier axis" model.

HONESTY CAVEAT - READ BEFORE CITING THIS COMMIT
-----------------------------------------------
This is a DEGENERATE-VALUE fix, NOT a champion damage model. The fallback
credits AD/crit-scaled auto DPS. For Azir specifically that is the WRONG
damage model: his soldier stabs scale 45-65 pct AP and take ZERO AD scaling. A
counterfactual measured in the same session showed that restoring his auto DPS
makes ``/rank-onhit`` return Yun Tal #1 / Infinity Edge #2 at coherence 0.0,
which is wrong for him. The fix exists because a 0.0 DPS value breaks every
blended scorer that divides by or weights on it - NOT because the soldier
stream is now modelled. Modelling the soldier stream is a schema lift and is
explicitly out of scope. Do NOT cite this file or its commit as "Azir's
soldiers are modelled".

Note on the expected-change set: it is derived AT RUNTIME from the rotation
data (``_phase_rotations`` + the basic/basicTime degeneracy condition), never
hardcoded, so a patch that changes a rotation moves the test with it instead of
decaying into a tautology.

Historical note: an earlier hand-off listed Yunara among the all-phase-degenerate
champions. At patch 16.14.1 that is no longer true (Yunara carries real
basic-attack rotations and is ARAM-enabled, aramDamageDealt=1.0), so this file
keeps it as a real-rotation control rather than a fallback control. That is
exactly why the sets are runtime-derived.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import PHASES, compute_dps, _phase_rotations

# The exact substrings compute_dps writes. Split so the tests can tell the
# legacy all-phase fallback apart from the new per-phase one.
FALLBACK_MARKER = "raw_attack_dps*mode_mult"
PERPHASE_MARKER = "for phase(s)"

LEVEL = 13
ARMOR = 60.0
MR = 50.0


def _degenerate_phases(snap: DataSnapshot, champ: str) -> set[str]:
    """Phases whose rotation data carries NO basic-attack contribution.

    ``_rotation_attack_dps`` computes ``total_attacks = basic + basicTime * AS``
    and ``_phase_weighted_dps`` skips rotations with weight <= 0. So a phase
    yields exactly 0.0 basic-attack DPS iff it has no positively weighted
    rotation, or every positively weighted rotation has ``basic == 0`` AND
    ``basicTime == 0``. This is the degeneracy condition read straight off the
    source data - independent of the fallback code under test.
    """
    by_phase = _phase_rotations(snap, champ)
    out: set[str] = set()
    for p in PHASES:
        rots = [r for r in by_phase[p] if float(r.get("weight", 0) or 0) > 0]
        if not rots or all(
            float(r.get("basic", 0) or 0) == 0.0
            and float(r.get("basicTime", 0) or 0) == 0.0
            for r in rots
        ):
            out.add(p)
    return out


def _selected_phase(level: int) -> str:
    from agents.daemon_slayer.dps import _select_phase

    return _select_phase(level)


class TestPerPhaseDegenerateFallback(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()
        cls.sel = _selected_phase(LEVEL)
        cls.roster = sorted(cls.snap.champions.keys())
        # Runtime-derived partition of the roster.
        cls.all_degenerate: list[str] = []
        cls.selected_only_degenerate: list[str] = []
        for champ in cls.roster:
            degen = _degenerate_phases(cls.snap, champ)
            if degen == set(PHASES):
                cls.all_degenerate.append(champ)
            elif cls.sel in degen:
                cls.selected_only_degenerate.append(champ)

    def _dps(self, champ: str, mode: str = "SR"):
        return compute_dps(
            self.snap, champ, level=LEVEL, item_ids=[], mode=mode,
            target_armor=ARMOR, target_mr=MR,
        )

    # ---------------------------------------------------------------- RED

    def test_selected_phase_degenerate_champs_are_nonzero(self) -> None:
        """The defect: selected-phase-degenerate champs shipped 0.0."""
        self.assertTrue(
            self.selected_only_degenerate,
            "no selected-phase-degenerate champion in the snapshot - the "
            "regression this file guards would be unobservable",
        )
        for champ in self.selected_only_degenerate:
            with self.subTest(champion=champ):
                r = self._dps(champ)
                self.assertGreater(
                    r.weighted_dps, 0.0,
                    f"{champ} weighted_dps collapsed to 0.0 (selected phase "
                    f"{self.sel!r} is degenerate, other phases are not)",
                )

    def test_perphase_fallback_emits_a_note_naming_the_phases(self) -> None:
        for champ in self.selected_only_degenerate:
            with self.subTest(champion=champ):
                r = self._dps(champ)
                hits = [n for n in r.notes if PERPHASE_MARKER in n]
                self.assertEqual(
                    len(hits), 1,
                    f"{champ} must carry exactly one per-phase fallback note; "
                    f"got {r.notes!r}",
                )
                note = hits[0]
                self.assertIn(FALLBACK_MARKER, note)
                for p in sorted(_degenerate_phases(self.snap, champ)):
                    self.assertIn(p, note, f"{champ} note must name phase {p}")

    def test_perphase_fallback_value_is_raw_times_mode_mult(self) -> None:
        for champ in self.selected_only_degenerate:
            with self.subTest(champion=champ):
                r = self._dps(champ)
                self.assertAlmostEqual(
                    r.weighted_dps,
                    r.raw_attack_dps * r.mode_multiplier,
                    places=6,
                )

    def test_healthy_phases_are_not_overwritten(self) -> None:
        """Only the degenerate SELECTED phase is substituted."""
        for champ in self.selected_only_degenerate:
            with self.subTest(champion=champ):
                r = self._dps(champ)
                degen = _degenerate_phases(self.snap, champ)
                healthy = [p for p in PHASES if p not in degen]
                self.assertTrue(healthy, f"{champ} should have a healthy phase")
                fallback = r.raw_attack_dps * r.mode_multiplier
                for p in healthy:
                    self.assertNotAlmostEqual(
                        r.phase_dps[p], fallback, places=6,
                        msg=f"{champ} healthy phase {p} must keep its rotation "
                            "value, not the fallback",
                    )
                    self.assertGreater(r.phase_dps[p], 0.0)

    # ------------------------------------------- negative control class 1
    # Already-falling-back champions: the legacy all-phase branch must be
    # preserved exactly - same value, same single legacy note, no per-phase
    # note, all three phases flattened to the fallback.

    NAMED_ALL_DEGENERATE = ("Aphelios", "Cassiopeia", "Fiddlesticks", "Sylas")

    def test_named_all_degenerate_controls_are_still_all_degenerate(self) -> None:
        for champ in self.NAMED_ALL_DEGENERATE:
            with self.subTest(champion=champ):
                self.assertIn(
                    champ, self.all_degenerate,
                    f"{champ} is a named all-phase-degenerate control but the "
                    "snapshot no longer agrees - re-derive the control list",
                )

    def test_already_falling_back_controls_do_not_double_apply(self) -> None:
        for champ in self.all_degenerate:
            with self.subTest(champion=champ):
                r = self._dps(champ)
                fallback = r.raw_attack_dps * r.mode_multiplier
                self.assertAlmostEqual(r.weighted_dps, fallback, places=6)
                for p in PHASES:
                    self.assertAlmostEqual(r.phase_dps[p], fallback, places=6)
                legacy = [n for n in r.notes
                          if FALLBACK_MARKER in n and PERPHASE_MARKER not in n]
                self.assertEqual(
                    len(legacy), 1,
                    f"{champ} must keep exactly one legacy fallback note; "
                    f"got {r.notes!r}",
                )
                self.assertEqual(
                    [n for n in r.notes if PERPHASE_MARKER in n], [],
                    f"{champ} must NOT also take the per-phase branch",
                )

    # ------------------------------------------- negative control class 2
    # Real basic-attack rotations: untouched, no note of any kind.

    NAMED_REAL_ROTATION = ("Syndra", "Lux", "Zyra", "Jinx", "Yunara")

    def test_real_rotation_controls_are_untouched(self) -> None:
        for champ in self.NAMED_REAL_ROTATION:
            with self.subTest(champion=champ):
                self.assertNotIn(champ, self.all_degenerate)
                self.assertNotIn(champ, self.selected_only_degenerate)
                r = self._dps(champ)
                self.assertEqual(
                    [n for n in r.notes if FALLBACK_MARKER in n], [],
                    f"{champ} has real basic-attack rotations and must not "
                    f"trip any fallback; got {r.notes!r}",
                )
                self.assertGreater(r.weighted_dps, 0.0)
                self.assertAlmostEqual(
                    r.weighted_dps, r.phase_dps[self.sel], places=9)
                self.assertNotAlmostEqual(
                    r.weighted_dps,
                    r.raw_attack_dps * r.mode_multiplier,
                    places=2,
                )

    # ------------------------------------------------------ roster sweep

    def test_roster_sweep_only_the_derived_set_falls_back_per_phase(self) -> None:
        """Every one of the 173 champions: the per-phase branch fires for
        exactly the runtime-derived set, and nothing else moves."""
        fired: list[str] = []
        untouched: list[str] = []
        for champ in self.roster:
            r = self._dps(champ)
            if any(PERPHASE_MARKER in n for n in r.notes):
                fired.append(champ)
                continue
            if any(FALLBACK_MARKER in n for n in r.notes):
                continue  # legacy all-phase branch, covered above
            untouched.append(champ)
            # Byte-identity proof for the untouched majority: weighted_dps is
            # exactly the selected phase's rotation value, so the fallback
            # block provably did not run for them.
            self.assertEqual(
                r.weighted_dps, r.phase_dps[self.sel],
                f"{champ} weighted_dps diverged from its selected-phase "
                "rotation value - the fallback touched a healthy champion",
            )
            self.assertGreater(
                r.weighted_dps, 0.0,
                f"{champ} ships weighted_dps 0.0 with no explanatory note - "
                "that is the exact class of silent defect this fix closes",
            )

        self.assertEqual(
            sorted(fired), sorted(self.selected_only_degenerate),
            "the set of champions taking the per-phase branch must equal the "
            "set the rotation-data degeneracy condition predicts",
        )
        self.assertEqual(
            len(self.roster),
            len(fired) + len(untouched) + len(self.all_degenerate),
            "roster partition must be exhaustive",
        )

    # ----------------------------------------------- ARAM-disabled gate

    def test_mode_disabled_champion_still_reports_zero(self) -> None:
        """``mode_mult > 0.0`` stays load-bearing.

        A champion ARAM-DISABLED at the snapshot patch (aramDamageDealt=0) has
        mode_mult=0 and MUST stay weighted_dps=0 - that is a real "deals no
        damage in this mode" zero, not a scenario gap. No champion carries
        aramDamageDealt=0 at 16.14.1, so the condition is injected onto a
        champion that would otherwise take the new per-phase branch.
        """
        self.assertTrue(self.selected_only_degenerate)
        champ = self.selected_only_degenerate[0]
        snap = DataSnapshot.load()  # private instance - mutated below
        rec = snap.champion(champ)
        lolmath = rec.setdefault("lolmath", {})
        mods = dict(lolmath.get("aram_modifiers") or {})
        mods["aramDamageDealt"] = 0.0
        lolmath["aram_modifiers"] = mods

        r = compute_dps(snap, champ, level=LEVEL, item_ids=[], mode="ARAM",
                        target_armor=ARMOR, target_mr=MR)
        self.assertEqual(r.mode_multiplier, 0.0)
        self.assertEqual(
            r.weighted_dps, 0.0,
            f"{champ} is mode-disabled (aramDamageDealt=0) and must stay at "
            "0.0 - the fallback must not manufacture damage for it",
        )
        self.assertEqual(
            [n for n in r.notes if FALLBACK_MARKER in n], [],
            "a mode-disabled champion must not emit a fallback note",
        )


if __name__ == "__main__":
    unittest.main()
