"""R145 Slice B - machine guard for the PRECISION offensive-rune audit.

AUDIT-ONLY slice. This module pins the CURRENT (2026-07-20, ENGINE 1.231.0)
behaviour of the Daemon Slayer engine with respect to the 13 Precision-tree
runes in DDragon 16.14.1 ``runesReforged.json``. It builds nothing and bumps
nothing - it exists so that the day somebody wires one of the uncredited
Precision stat-grant axes into a DS offensive scorer, this guard TRIPS and the
wiring has to be acknowledged deliberately rather than landing silently.

Findings it pins (full write-up in
``docs/ORCHESTRATION_FINDINGS_R145_PRECISION.md``):

  CREDITED (burst path only, via an explicit ``runes=`` argument)
    8005 Press the Attack  - stacking_amp 1.08 + 40-160 adaptive burst piece
    8008 Lethal Tempo      - per_attack adaptive on-attack damage
    8014 Coup de Grace     - stacking_amp 1.08
    8017 Cut Down          - stacking_amp 1.08
    8299 Last Stand        - caster-hp-ramped amp (no-op at full HP by design)

  UNCREDITED-REAL-GAP
    8010 Conqueror         - registered but proc_type="adaptive", which
                             ``burst.py`` explicitly SKIPS, so its 1.8-4.0
                             adaptive force per stack (x12 stacks) reaches no
                             damage or stat axis anywhere in the engine
    9104 Legend: Alacrity  - absent from the engine entirely; 3% + 1.5%/stack
                             (max 10) attack speed feeds no attack-speed axis
    8008 Lethal Tempo (AS half) - the on-attack damage is credited, the
                             [6% melee || 4% ranged] x6 attack-speed stack is
                             not (it is only ever an INPUT via ``bonus_as``)

  OUT-OF-OFFENSIVE-AXIS / defensive half (closed by R132 / R136 / R142)
    8021 Fleet Footwork, 9111 Triumph, 9103 Legend: Bloodline,
    8009 Presence of Mind (resource axis), 9105 Legend: Haste (ability haste
    was MEASURED INERT as a DS axis - do not re-pitch)

  DATA-BLOCKED
    9101 Absorb Life - longDesc carries an unresolved ``@HealAmount@``
                       placeholder, so no magnitude is derivable from the feed

NO ENGINE_VERSION assertions here (Slice A owns the bump).
"""

from __future__ import annotations

import json
import pathlib
import unittest

from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rune_procs import (
    RUNE_PROCS,
    compute_rune_proc_damage,
    keystone_amp,
)

_REPO = pathlib.Path(__file__).resolve().parents[1]
_DS = _REPO / "agents" / "daemon_slayer"
_FEED = _REPO / "data" / "meta_build" / "ddragon" / "16.14.1" / "runesReforged.json"

# The 13 Precision runes as they appear in DDragon 16.14.1 (id -> name).
_PRECISION = {
    8005: "Press the Attack",
    8008: "Lethal Tempo",
    8021: "Fleet Footwork",
    8010: "Conqueror",
    9101: "Absorb Life",
    9111: "Triumph",
    8009: "Presence of Mind",
    9104: "Legend: Alacrity",
    9105: "Legend: Haste",
    9103: "Legend: Bloodline",
    8014: "Coup de Grace",
    8017: "Cut Down",
    8299: "Last Stand",
}

# Runes whose contribution to the burst total must be STRICTLY POSITIVE today.
_CREDITED_IN_BURST = (8005, 8008, 8014, 8017)

# Runes that reach NO offensive axis today. 8010 is the interesting one - it is
# REGISTERED in RUNE_PROCS yet contributes nothing; the rest are absent outright.
_UNCREDITED_REGISTERED = (8010,)
_UNCREDITED_ABSENT = (8021, 9101, 9111, 8009, 9104, 9105, 9103)

_SNAP = DataSnapshot.load()
_TGT = dict(
    target_armor=80.0,
    target_mr=60.0,
    target_max_hp=2000.0,
    target_bonus_hp=600.0,
)
# A melee bruiser with real AD items so both the ability and the AA halves of
# the burst land non-zero - a zero base would make every amp assertion vacuous.
_CHAMP = "Darius"
_ITEMS = ["3031", "3072"]


def _burst(runes=None) -> float:
    return compute_burst_damage(
        _SNAP,
        _CHAMP,
        11,
        item_ids=list(_ITEMS),
        mode="SR",
        runes=runes,
        **_TGT,
    ).total_burst_damage


def _feed_precision() -> dict[int, dict]:
    trees = json.loads(_FEED.read_text(encoding="utf-8"))
    out: dict[int, dict] = {}
    for tree in trees:
        if tree.get("key") != "Precision":
            continue
        for slot in tree.get("slots", []):
            for rune in slot.get("runes", []):
                out[int(rune["id"])] = rune
    return out


class FeedGroundTruthTests(unittest.TestCase):
    """Pin the DDragon 16.14.1 Precision roster so an id drift is loud."""

    def test_feed_file_exists(self):
        self.assertTrue(_FEED.is_file(), f"missing DDragon feed: {_FEED}")

    def test_precision_roster_matches_expected_ids(self):
        feed = _feed_precision()
        self.assertEqual(sorted(feed), sorted(_PRECISION))
        for rid, name in _PRECISION.items():
            self.assertEqual(feed[rid]["name"], name, f"rune {rid} renamed")

    def test_baseline_burst_is_non_trivial(self):
        """Anti-vacuity: every amp assertion below rides on a non-zero base."""
        self.assertGreater(_burst(), 100.0)

    def test_rune_procs_registry_is_populated(self):
        """Anti-vacuity: the absent-id assertions mean nothing on an empty map."""
        self.assertGreater(len(RUNE_PROCS), 10)


class CreditedPrecisionRunesTests(unittest.TestCase):
    """Runes that DO move the burst total today - credit must be exercised."""

    def test_credited_runes_strictly_increase_burst(self):
        base = _burst()
        for rid in _CREDITED_IN_BURST:
            with self.subTest(rune=rid, name=_PRECISION[rid]):
                self.assertIn(rid, RUNE_PROCS)
                self.assertGreater(
                    _burst([rid]),
                    base,
                    f"{_PRECISION[rid]} ({rid}) no longer credits the burst",
                )

    def test_press_the_attack_amp_is_eight_percent(self):
        """DDragon: 'amplifies your damage dealt by 8%'."""
        self.assertAlmostEqual(keystone_amp(8005, 1000.0), 1080.0, places=6)

    def test_coup_de_grace_and_cut_down_amp_is_eight_percent(self):
        """DDragon: both read 'Deal 8% more damage to champions ...'."""
        self.assertAlmostEqual(keystone_amp(8014, 1000.0), 1080.0, places=6)
        self.assertAlmostEqual(keystone_amp(8017, 1000.0), 1080.0, places=6)

    def test_last_stand_is_caster_hp_gated_not_flat(self):
        """DDragon: 'Deal 5% - 11% increased damage ... below 60% health'."""
        # Full HP -> no amp at all, so 8299 is invisible in a default burst.
        self.assertEqual(_burst([8299]), _burst())
        self.assertAlmostEqual(keystone_amp(8299, 1000.0, caster_hp_pct=1.0), 1000.0)
        # Below the gate the ramp is live and reaches the 11% cap at 30% HP.
        self.assertAlmostEqual(
            keystone_amp(8299, 1000.0, caster_hp_pct=0.30), 1110.0, places=6
        )
        self.assertGreater(keystone_amp(8299, 1000.0, caster_hp_pct=0.45), 1000.0)


class UncreditedPrecisionRunesTests(unittest.TestCase):
    """The gap guards. Any of these failing means somebody wired an axis."""

    def test_conqueror_is_registered_but_credits_nothing(self):
        """8010 Conqueror - REAL GAP.

        DDragon 16.14.1 longDesc: "Basic attacks or spells that deal damage to
        an enemy champion grant 2 stacks of Conqueror for 5s, gaining 1.8-4
        Adaptive Force per stack. Stacks up to 12 times."

        The per-stack value IS computable (the closure exists and returns a
        positive number) but ``burst.py`` skips ``proc_type == "adaptive"``,
        and no other scorer reads it - so up to 12 x 1.8-4.0 adaptive force
        reaches no AD / AP / damage axis anywhere.
        """
        proc = RUNE_PROCS.get(8010)
        self.assertIsNotNone(proc, "Conqueror vanished from RUNE_PROCS")
        self.assertEqual(proc.proc_type, "adaptive")
        # The magnitude is derivable - this is a consumer gap, not a data gap.
        self.assertGreater(compute_rune_proc_damage(8010, 11), 0.0)
        # ... and yet the burst total does not move by a single float ULP.
        self.assertEqual(
            _burst([8010]),
            _burst(),
            "Conqueror now credits the burst - R145 finding is stale, update it",
        )
        # It is not an amp either.
        self.assertEqual(keystone_amp(8010, 1000.0), 1000.0)

    def test_uncredited_runes_are_absent_from_the_proc_registry(self):
        for rid in _UNCREDITED_ABSENT:
            with self.subTest(rune=rid, name=_PRECISION[rid]):
                self.assertNotIn(
                    rid,
                    RUNE_PROCS,
                    f"{_PRECISION[rid]} ({rid}) was added to RUNE_PROCS - "
                    "R145 audit is stale, re-run it",
                )

    def test_uncredited_runes_do_not_move_the_burst_total(self):
        base = _burst()
        for rid in _UNCREDITED_ABSENT + _UNCREDITED_REGISTERED:
            with self.subTest(rune=rid, name=_PRECISION[rid]):
                self.assertEqual(
                    _burst([rid]),
                    base,
                    f"{_PRECISION[rid]} ({rid}) now credits the burst",
                )

    def test_legend_alacrity_attack_speed_is_unmodelled(self):
        """9104 Legend: Alacrity - REAL GAP.

        DDragon 16.14.1 longDesc: "Gain 3% attack speed plus an additional
        1.5% for every Legend stack (max 10 stacks)." That is a flat 18%
        attack speed at cap, feeding nothing.
        """
        self.assertNotIn(9104, RUNE_PROCS)
        self.assertEqual(compute_rune_proc_damage(9104, 11), 0.0)
        self.assertEqual(keystone_amp(9104, 1000.0), 1000.0)

    def test_absorb_life_magnitude_is_data_blocked(self):
        """9101 Absorb Life - DATA-BLOCKED, not a gap.

        DDragon 16.14.1 longDesc: "Killing a target heals you for
        @HealAmount@." The placeholder is unresolved in the feed, so no
        magnitude may be derived without inventing a constant.
        """
        feed = _feed_precision()
        self.assertIn("@HealAmount@", feed[9101]["longDesc"])
        self.assertNotIn(9101, RUNE_PROCS)


class OffensiveScorerRuneBlindnessTests(unittest.TestCase):
    """The structural finding: no rune reaches the item-ranking scorers.

    ``rank.py`` and ``ability_dps.py`` contain ZERO rune references, so the
    Precision credit that does exist lives only in ``burst.py`` behind an
    explicit ``runes=`` argument that the live ``/rank`` path never supplies.
    """

    def test_rank_and_ability_dps_have_no_rune_surface(self):
        for name in ("rank.py", "ability_dps.py"):
            with self.subTest(module=name):
                src = (_DS / name).read_text(encoding="utf-8")
                self.assertNotIn(
                    "rune",
                    src.lower(),
                    f"{name} gained a rune surface - the R145 structural "
                    "finding is stale, re-audit before shipping",
                )

    def test_hybrid_rune_transport_is_defensive_only(self):
        """``hybrid.py`` takes ``rune_ids`` but only to reach ``compute_ehp``."""
        src = (_DS / "hybrid.py").read_text(encoding="utf-8")
        self.assertIn("rune_ids", src)
        for offensive_flag in (
            "apply_rune_adaptive",
            "apply_rune_attack_speed",
            "apply_rune_damage_amp",
        ):
            with self.subTest(flag=offensive_flag):
                self.assertNotIn(offensive_flag, src)

    def test_burst_skips_adaptive_proc_type(self):
        """The exact line that strands Conqueror."""
        src = (_DS / "burst.py").read_text(encoding="utf-8")
        self.assertIn('proc.proc_type == "adaptive"', src)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
