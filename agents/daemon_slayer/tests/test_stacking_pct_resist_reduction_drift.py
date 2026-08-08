"""Drift guard for the STACKING percent resist-reduction lane.

Every registry row on this lane stores ONE number - the fully-stacked percent -
while DDragon states TWO: a per-stack percent and a stack cap. The stored
product is therefore a derived value with no machine link back to its source,
so a Riot retune of either factor leaves the registry silently stale. That is
exactly what happened to Obsidian Cleaver (228005): Carve was ``Armor by 7%``
x 5 in the 16.10.1 snapshot the row was authored against, Riot cut it to 6% by
16.12.1, and the row still read 0.35 through 16.15.1 - four consecutive
snapshots of a 5-percentage-point over-credit on an Arena-reachable item
(``maps.30`` is the only true map for 228005).

The guard DERIVES the expected value from the live snapshot rather than pinning
a literal, so the next retune fails here instead of shipping. It is scoped to
rows whose DDragon description actually states both factors in the
"reduces ... by N% ... (stacks M times)" shape; a row that states its cap some
other way (Terminus, Flesheater) is out of scope and is not silently passed -
``test_expected_shape_population`` pins the matched set so a parse regression
that empties it cannot make this file vacuously green.

ONE known trap for a future failure triage: DDragon ships bad numbers. The
16.11.1 snapshot states Obsidian Cleaver's Carve at ``Armor by 500%``. A
failure here is a prompt to read the stat line, not to copy it.

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import re
import unittest

import agents.daemon_slayer as daemon_slayer
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.effects import ITEM_EFFECTS, effective_target_armor

# The four registry fields that store a fully-stacked percent on this lane.
_PCT_FIELDS = (
    "armor_reduction_pct",
    "mr_reduction_pct",
    "armor_pen_pct",
    "magic_pen_pct",
)

# "reduces the target's <scaleArmor>Armor by 6%</scaleArmor> ... (stacks 5 times)"
_PER_STACK = re.compile(r"(?:Armor|Magic Resist)\s+by\s+([0-9.]+)\s*%", re.I)
_STACK_CAP = re.compile(r"stacks\s+([0-9]+)\s+times", re.I)


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or ""))


def _derived_rows(snapshot: DataSnapshot) -> dict[str, tuple[float, float, int]]:
    """Map item id -> (stored_pct, per_stack_pct, stack_cap) for matched rows."""
    out: dict[str, tuple[float, float, int]] = {}
    for iid, eff in ITEM_EFFECTS.items():
        stored = [getattr(eff, f) for f in _PCT_FIELDS if getattr(eff, f)]
        if not stored:
            continue
        record = snapshot.items.get(str(iid))
        if record is None:
            continue
        body = _plain(record.get("description", ""))
        per = _PER_STACK.search(body)
        cap = _STACK_CAP.search(body)
        if not (per and cap):
            continue
        # Every matched row stores the SAME percent in each field it uses
        # (Terminus-style split axes do not reach here), so one value stands
        # for the row.
        if len(set(stored)) != 1:
            raise AssertionError(
                f"{iid} stores differing percents across {_PCT_FIELDS}: {stored}"
            )
        out[str(iid)] = (float(stored[0]), float(per.group(1)), int(cap.group(1)))
    return out


class StackingPctResistReductionDriftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()
        cls.rows = _derived_rows(cls.snap)

    def test_expected_shape_population(self) -> None:
        # Anti-vacuity: the parse must keep finding the Cleaver + Curse family.
        self.assertEqual(
            set(self.rows), {"3071", "223071", "228005", "4010", "8010"}
        )

    def test_every_matched_row_equals_per_stack_times_cap(self) -> None:
        for iid, (stored, per_stack, cap) in sorted(self.rows.items()):
            with self.subTest(item=iid, name=ITEM_EFFECTS[iid].name):
                self.assertAlmostEqual(
                    stored,
                    per_stack * cap / 100.0,
                    places=9,
                    msg=(
                        f"{iid} {ITEM_EFFECTS[iid].name}: registry {stored} vs "
                        f"DDragon {per_stack}% x {cap} stacks on patch "
                        f"{self.snap.patch}"
                    ),
                )

    def test_obsidian_cleaver_matches_its_own_ddragon_line(self) -> None:
        # R161 doctrine B: an Ornn / mode mirror credits its OWN stat line, so
        # 228005 landing on the same 30% as Black Cleaver is the derivation
        # agreeing, not the mirror inheriting the base item's number.
        self.assertAlmostEqual(
            ITEM_EFFECTS["228005"].armor_reduction_pct, 0.30, places=9
        )
        self.assertEqual(self.snap.items["228005"]["maps"]["30"], True)

    def test_effective_armor_over_a_grid_uses_the_derived_keep_factor(self) -> None:
        eff = [ITEM_EFFECTS["228005"]]
        stored, per_stack, cap = self.rows["228005"]
        keep = 1.0 - per_stack * cap / 100.0
        for armor in (0.0, 25.0, 60.0, 100.0, 175.0, 300.0):
            with self.subTest(armor=armor):
                self.assertAlmostEqual(
                    effective_target_armor(armor, eff, level=None),
                    armor * keep,
                    places=9,
                )

    def test_cleaver_pair_composes_multiplicatively_not_additively(self) -> None:
        # Both Cleavers are equippable together in Arena; the shared
        # armor_reduction_pct layer composes as a product of keep-factors.
        pair = [ITEM_EFFECTS["3071"], ITEM_EFFECTS["228005"]]
        a = ITEM_EFFECTS["3071"].armor_reduction_pct
        b = ITEM_EFFECTS["228005"].armor_reduction_pct
        for armor in (40.0, 100.0, 220.0):
            with self.subTest(armor=armor):
                got = effective_target_armor(armor, pair, level=None)
                self.assertAlmostEqual(got, armor * (1.0 - a) * (1.0 - b), places=9)
                self.assertGreater(got, armor * (1.0 - (a + b)))

    def test_engine_version_pin(self) -> None:
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.277.0")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
