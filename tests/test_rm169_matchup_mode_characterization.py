"""RM-169 characterization: the two DS damage paths disagree about ARENA vs SR,
and this file PINS the current behaviour of BOTH so neither can drift silently
and neither can be "fixed" in one path only.

The disagreement, MEASURED 2026-08-06 at ENGINE 1.275.0 / patch 16.15.1:

* ``ability_dps.compute_ability_dps`` DIFFERS between mode="SR" and mode="ARENA"
  for 142 of 173 champions at level 2, itemless.
* ``matchup.compute_matchup`` - which is what
  ``core/laning_scenario_precompute.py:545`` actually calls - is IDENTICAL for
  every probed pair at the same inputs. It never differs.

The received explanation for that gap was that ARENA carries its own DDragon
champion stat line. That is REFUTED here by direct measurement:

* ``engine.build_champion`` returns a BYTE-IDENTICAL stat block for SR and ARENA
  for all 173 champions (``test_build_champion_stat_line_is_mode_blind``).
* Every per-cast raw damage number in ``compute_ability_dps`` is identical
  between the two modes (``test_ability_dps_per_cast_raw_damage_is_mode_blind``).

The SOLE source of the ability-DPS divergence is the per-mode MEASURED cast-rate
table read at ``agents/daemon_slayer/ability_dps.py:1350`` via
``ult_rates.get_spell_casts_per_sec(champion_name, key, mode)``. That is a
casts-per-SECOND quantity. ``compute_matchup`` composes ``compute_burst_damage``,
a per-COMBO model with no casts-per-second term at all, so it has nothing to read
from that table. The two paths are answering different questions.

``compute_matchup`` is NOT mode-blind by omission - it threads ``mode`` into
every scorer it composes (matchup.py:238 / :241 build_champion, :245 / :249
compute_burst_damage, :265 / :268 compute_mana_bounded_combo). It resolves to the
same numbers because every per-mode lane reachable from there is either
ARAM-gated or opt-in:

* ``engine._apply_mode_modifiers`` early-returns for ``mode != "ARAM"``
  (engine.py:254).
* ``burst.py``'s only mode term is ``aramDamageDealt``, gated on
  ``mode == "ARAM"`` (burst.py:674-676), so ``mode_multiplier`` is 1.0 for ARENA.
* The ARENA stat-ADDEND axis exists in the wiki sidecar (45 of 173 champions
  carry an ``ar`` axis) but is reached only through ``build_champion``'s
  ``apply_mode_modifiers`` flag, which defaults False (engine.py:295) and is not
  exposed by ``compute_burst_damage`` / ``compute_ability_dps`` /
  ``compute_matchup`` at all. That default-OFF seam is pinned here too, so
  flipping it becomes a deliberate, test-visible act.

Consequence for the laning table: the arena laning-scenario table is mode-blind
AT THE ITEMLESS CELL because at ``item_state == "none"`` there is nothing
mode-dependent left in the pipeline - not because ARENA equals SR everywhere. At
``one_item`` / ``two_item`` it is emphatically NOT mode-blind: 152 of 173
champions draw different item ids from ``build_orders_arena.json`` than from
``build_orders_sr.json``, and those ids DO move ``pct_enemy_removed``.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents.daemon_slayer.ability_dps import compute_ability_dps  # noqa: E402
from agents.daemon_slayer.data_loader import DataSnapshot  # noqa: E402
from agents.daemon_slayer.engine import build_champion  # noqa: E402
from agents.daemon_slayer.matchup import compute_matchup  # noqa: E402
from agents.daemon_slayer.ult_rates import get_spell_casts_per_sec  # noqa: E402
import core.laning_scenario_precompute as lsp  # noqa: E402

# Level 2, itemless - the exact probe point the RM-169 finding was raised at.
_LEVEL = 2

# A reference champion whose two paths visibly disagree. Kept as an explicit
# anchor so a regression names a champion rather than only a count.
_ANCHOR = "Aatrox"


def _snapshot() -> DataSnapshot:
    return DataSnapshot.load()


class _SharedSnapshot(unittest.TestCase):
    """One shared engine snapshot for the whole module (load is expensive)."""

    snapshot: DataSnapshot

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _snapshot()
        cls.champions = sorted(cls.snapshot.champions)


class MechanismTests(_SharedSnapshot):
    """WHERE the divergence comes from - and where it provably does not."""

    def test_build_champion_stat_line_is_mode_blind_sr_vs_arena(self) -> None:
        """The received "ARENA has its own DDragon stat line" claim, REFUTED.

        engine.build_champion resolves an identical stat block for SR and ARENA
        for every champion at the default apply_mode_modifiers=False. If this
        ever fails, the RM-169 mechanism note above is stale and must be redone
        before any conclusion drawn from it is reused.
        """
        differing = [
            cid
            for cid in self.champions
            if (
                build_champion(
                    self.snapshot, cid, _LEVEL, item_ids=[], mode="SR",
                ).stats
                != build_champion(
                    self.snapshot, cid, _LEVEL, item_ids=[], mode="ARENA",
                ).stats
            )
        ]
        self.assertEqual(differing, [], "ARENA stat line diverged from SR")

    def test_ability_dps_per_cast_raw_damage_is_mode_blind(self) -> None:
        """Per-cast DAMAGE is identical; only the cast RATE moves.

        Pins the half of compute_ability_dps that does NOT vary by mode, so a
        future change that starts varying per-cast damage by mode is loud.
        """
        sr = compute_ability_dps(
            self.snapshot, _ANCHOR, _LEVEL, item_ids=[], mode="SR",
        )
        arena = compute_ability_dps(
            self.snapshot, _ANCHOR, _LEVEL, item_ids=[], mode="ARENA",
        )
        self.assertEqual(len(sr.per_spell), len(arena.per_spell))
        for a, b in zip(sr.per_spell, arena.per_spell):
            self.assertEqual(a.key, b.key)
            self.assertEqual(
                a.raw_damage_per_cast,
                b.raw_damage_per_cast,
                f"{_ANCHOR} {a.key} per-cast raw damage moved with mode",
            )

    def test_mode_multiplier_is_one_outside_aram_on_both_paths(self) -> None:
        """burst.py:674-676 / ability_dps.py:1134-1140 gate on ARAM only.

        ability_dps.py:1134-1140 is a TRUE citation that supports a FALSE
        conclusion: the multiplier really is ARAM-only, but that is not why the
        matchup path is mode-blind.
        """
        for mode in ("SR", "ARENA"):
            res = compute_ability_dps(
                self.snapshot, _ANCHOR, _LEVEL, item_ids=[], mode=mode,
            )
            self.assertEqual(res.mode_multiplier, 1.0, f"mode={mode}")

    def test_cast_rate_table_is_the_sole_divergence_source(self) -> None:
        """ability_dps.py:1350 -> ult_rates.get_spell_casts_per_sec(.., mode).

        At least one spell key must report a different measured casts/sec for
        SR vs ARENA on the anchor champion. This is the mechanism; if it stops
        being true the 142-of-173 count above stops being explained.
        """
        moved = [
            key
            for key in ("Q", "W", "E", "R")
            if get_spell_casts_per_sec(_ANCHOR, key, "SR")
            != get_spell_casts_per_sec(_ANCHOR, key, "ARENA")
        ]
        self.assertTrue(
            moved, f"no {_ANCHOR} spell cast-rate differs between SR and ARENA"
        )

    def test_arena_stat_addend_axis_exists_but_is_default_off(self) -> None:
        """The ONE genuine per-mode stat line, and the flag that withholds it.

        45 of 173 champions carry a wiki ``ar`` mode_modifier axis, and
        apply_mode_modifiers=True changes their resolved stats. Nothing on the
        matchup / burst / ability-dps path exposes that flag, so the axis is
        unreachable there by DESIGN (engine.py:295 default False), not by
        oversight. Asserted as a >= floor so a wiki-sidecar refresh that ADDS
        champions does not fail the suite.
        """
        with_axis = [
            cid
            for cid in self.champions
            if self.snapshot.mode_modifier(cid, "ARENA")
        ]
        self.assertGreaterEqual(len(with_axis), 40)
        moved = 0
        for cid in with_axis:
            off = build_champion(
                self.snapshot, cid, _LEVEL, item_ids=[], mode="ARENA",
                apply_mode_modifiers=False,
            )
            on = build_champion(
                self.snapshot, cid, _LEVEL, item_ids=[], mode="ARENA",
                apply_mode_modifiers=True,
            )
            if off.stats != on.stats:
                moved += 1
        self.assertEqual(
            moved,
            len(with_axis),
            "a champion with an ARENA addend axis resolved no stat delta",
        )


class DisagreementTests(_SharedSnapshot):
    """The disagreement itself, pinned from both sides."""

    def test_ability_dps_DOES_differ_between_sr_and_arena(self) -> None:
        """Path 1 is mode-sensitive. Anchored on a named champion + a floor.

        The 2026-08-06 measurement was 142 of 173 champions differing at level 2
        itemless. Pinned as a floor rather than an equality so a rewind-data
        refresh that shifts a handful of champions does not fail the suite,
        while a collapse to mode-blindness does.
        """
        sr = compute_ability_dps(
            self.snapshot, _ANCHOR, _LEVEL, item_ids=[], mode="SR",
        )
        arena = compute_ability_dps(
            self.snapshot, _ANCHOR, _LEVEL, item_ids=[], mode="ARENA",
        )
        self.assertNotEqual(
            sr.total_ability_dps,
            arena.total_ability_dps,
            f"{_ANCHOR} ability DPS collapsed to mode-blind",
        )
        differing = 0
        for cid in self.champions:
            a = compute_ability_dps(
                self.snapshot, cid, _LEVEL, item_ids=[], mode="SR",
            ).total_ability_dps
            b = compute_ability_dps(
                self.snapshot, cid, _LEVEL, item_ids=[], mode="ARENA",
            ).total_ability_dps
            if a != b:
                differing += 1
        self.assertGreaterEqual(
            differing, 100, f"only {differing} of {len(self.champions)} differ"
        )

    def test_matchup_does_NOT_differ_between_sr_and_arena(self) -> None:
        """Path 2 is mode-INVARIANT at fixed inputs. Full result, not one field.

        Compares the whole MatchupResult so a future per-mode term landing in
        ANY field (verdict, mana gate, notes) trips this rather than only
        net_swing.
        """
        pairs = []
        for i in range(60):
            a = self.champions[i % len(self.champions)]
            b = self.champions[(i * 7 + 3) % len(self.champions)]
            if a == b:
                b = self.champions[(i * 7 + 4) % len(self.champions)]
            pairs.append((a, b))
        for a, b in pairs:
            sr = compute_matchup(
                self.snapshot, a, b, _LEVEL, _LEVEL,
                item_ids_a=[], item_ids_b=[], mode="SR",
            )
            arena = compute_matchup(
                self.snapshot, a, b, _LEVEL, _LEVEL,
                item_ids_a=[], item_ids_b=[], mode="ARENA",
            )
            self.assertEqual(
                sr.to_dict(), arena.to_dict(), f"{a} vs {b} moved with mode"
            )

    def test_matchup_is_mode_invariant_even_with_items(self) -> None:
        """Not an itemless artifact: the same item ids give the same answer.

        This is the control that separates "compute_matchup ignores mode" from
        "the laning table feeds compute_matchup different ITEMS per mode". The
        latter is what actually happens - see the LaningTableTests below.
        """
        ids = lsp.build_for_item_state(_ANCHOR, "two_item", "sr")
        self.assertTrue(ids, "two_item build order resolved empty for the anchor")
        sr = compute_matchup(
            self.snapshot, _ANCHOR, "Garen", 11, 11,
            item_ids_a=list(ids), item_ids_b=list(ids), mode="SR",
        )
        arena = compute_matchup(
            self.snapshot, _ANCHOR, "Garen", 11, 11,
            item_ids_a=list(ids), item_ids_b=list(ids), mode="ARENA",
        )
        self.assertEqual(sr.to_dict(), arena.to_dict())


class LaningTableTests(_SharedSnapshot):
    """Where the arena laning table's mode-sensitivity actually lives."""

    def test_itemless_item_ids_are_identical_across_modes(self) -> None:
        """item_state "none" is itemless in EVERY mode, so the cell is blind."""
        for cid in self.champions:
            self.assertEqual(
                tuple(lsp.build_for_item_state(cid, "none", "sr")),
                tuple(lsp.build_for_item_state(cid, "none", "arena")),
            )

    def test_itemed_item_ids_DO_differ_across_modes(self) -> None:
        """152 of 173 champions at the 2026-08-06 measurement. Floor-pinned.

        This is the reason the arena laning table is NOT globally mode-blind,
        and the reason a "fix compute_matchup" change would double-count.
        """
        for state in ("one_item", "two_item"):
            differing = sum(
                1
                for cid in self.champions
                if tuple(lsp.build_for_item_state(cid, state, "sr"))
                != tuple(lsp.build_for_item_state(cid, state, "arena"))
            )
            self.assertGreaterEqual(
                differing, 100, f"{state}: only {differing} champions differ"
            )

    def test_grid_shape_is_24_cells_per_pair(self) -> None:
        """6912 cells == 288 pairs x 24 cells. Names the 288 for what it is.

        The loose "288 of 6912" difference count reported against
        pct_enemy_removed is the grid's PAIR count, not a difference count -
        6912 / 24 == 288 exactly. See the RM-169 note; do not quote it as a
        measurement of divergence.
        """
        cells = sum(
            len(lsp.item_states_for_band(band))
            * len(lsp.MANA_STATES)
            * len(lsp.CD_STATES)
            for band in lsp.GEN_BANDS
        )
        self.assertEqual(cells, 24)
        self.assertEqual(6912 // cells, 288)


if __name__ == "__main__":
    unittest.main()
