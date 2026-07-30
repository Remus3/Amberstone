"""R67 (2026-07-03) - Terminus "Juxtaposition" Dark 3-stack pen correction.

Meraki 16.13.1 item 3302 passive "Juxtaposition": basic attacks against
champions alternate Light and Dark hits, each granting a 5s bonus that
stacks up to 3 times. Dark hits grant 10% armor penetration and magic
penetration per stack - "30% resistances penetration at maximum stacks".
The registry encoded only ONE Dark stack (0.10/0.10); per the repo
full-stack sustained-DPS convention (Black Cleaver 3071 5-stack 0.30
shred, Guinsoo 3124 4-stack 0.32 cond-AS - R66) SR 3302 pins at 0.30
armor pen + 0.30 magic pen.

R161 SPLIT THE ARENA MIRROR OFF THAT PIN. Under doctrine B - a DDragon
Arena mirror that states its OWN explicit stat line credits that line
rather than its SR twin's - map-30 mirror 223302 derives from the Arena
feed's 8-percent-per-stack wording, so it pins at 8 x 3 = 0.24 on both
axes while SR keeps 0.30. The convention (per-stack x cap) is unchanged;
only the per-stack INPUT differs between the two maps.

Light hits (6-8 bonus armor+MR per stack, level pp 1;11;14) are
CASTER-side resists and stay out of scope: no item-keyed resist-grant
path exists (_passive_resist_overrides.py is champion-keyed only) and
no schema field is added for it - logged as FUTURE in the changelog.

Shadow (the constant 30 magic on-hit periodic) predates R67 and must
survive the pen change byte-identical.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from agents import daemon_slayer
from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer.dps import _armor_factor
from agents.daemon_slayer.effects import (
    MAGICAL,
    ItemEffect,
    effective_target_armor,
    effective_target_mr,
)

_PATCH = "16.13.1"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_MERAKI_PATH = (
    _REPO_ROOT / "data" / "daemon_slayer" / _PATCH / "items_meraki.json"
)


class EngineVersion(unittest.TestCase):
    def test_engine_version_pinned(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.268.0")
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.268.0")


class JuxtapositionRegistryPins(unittest.TestCase):
    """Full-stack steady-state pins: per-stack x 3 Dark stacks, per map.

    SR 3302 states 10 percent per stack -> 0.30 each axis. Arena 223302
    states 8 percent per stack -> 0.24 each axis (R161 doctrine B).
    """

    def test_terminus_sr_armor_pen(self) -> None:
        eff = ITEM_EFFECTS.get("3302")
        self.assertIsNotNone(eff)
        self.assertAlmostEqual(eff.armor_pen_pct, 0.30, places=6)

    def test_terminus_sr_magic_pen(self) -> None:
        eff = ITEM_EFFECTS.get("3302")
        self.assertIsNotNone(eff)
        self.assertAlmostEqual(eff.magic_pen_pct, 0.30, places=6)

    def test_terminus_arena_armor_pen(self) -> None:
        eff = ITEM_EFFECTS.get("223302")
        self.assertIsNotNone(eff)
        self.assertAlmostEqual(eff.armor_pen_pct, 0.24, places=6)

    def test_terminus_arena_magic_pen(self) -> None:
        eff = ITEM_EFFECTS.get("223302")
        self.assertIsNotNone(eff)
        self.assertAlmostEqual(eff.magic_pen_pct, 0.24, places=6)


class JuxtapositionMerakiTruth(unittest.TestCase):
    """Hermetic drift guard: registry value derives from the vendored
    Meraki 16.13.1 snapshot text, so a future patch changing the Dark
    per-stack pct or the stack cap fails HERE instead of silently
    drifting.
    """

    @classmethod
    def setUpClass(cls) -> None:
        doc = json.loads(_MERAKI_PATH.read_text(encoding="utf-8"))
        passives = doc["items"]["3302"]["passives"]
        juxta = next(
            (p for p in passives if p.get("name") == "Juxtaposition"),
            None,
        )
        assert juxta is not None, "Meraki 3302 has no 'Juxtaposition' passive"
        cls.text = juxta["effects"]

    def test_meraki_stack_cap_is_three(self) -> None:
        m_cap = re.search(r"stacks up to (\d+) times", self.text)
        self.assertIsNotNone(
            m_cap, f"stack cap not found in: {self.text!r}"
        )
        self.assertEqual(int(m_cap.group(1)), 3)

    def test_meraki_dark_per_stack_pct_is_ten(self) -> None:
        # Meraki wiki-markup shape: "''Dark'' hits grant 10%
        # {{as|armor penetration}} and {{as|magic penetration}}".
        m_pct = re.search(
            r"Dark'' hits grant (\d+)% \{\{as\|armor penetration\}\} "
            r"and \{\{as\|magic penetration\}\}",
            self.text,
        )
        self.assertIsNotNone(
            m_pct, f"Dark per-stack pen pct not found in: {self.text!r}"
        )
        self.assertEqual(int(m_pct.group(1)), 10)

    def test_meraki_states_thirty_pct_at_max_stacks(self) -> None:
        self.assertIn(
            "30% resistances penetration at maximum stacks", self.text
        )

    def test_registry_matches_meraki_per_stack_times_cap(self) -> None:
        # SR 3302 ONLY. This file reads the PINNED 16.13.1 Meraki
        # snapshot, whose 22xxxx Arena-mirror coverage is partial and does
        # NOT include 223302, so the Arena magnitude cannot come from
        # Meraki at all - it comes from the DDragon Arena feed. Looping
        # the mirror into this SR-derived expectation is exactly what
        # locked 223302 at the wrong 0.30 before R161.
        pct = int(
            re.search(r"Dark'' hits grant (\d+)%", self.text).group(1)
        )
        cap = int(
            re.search(r"stacks up to (\d+) times", self.text).group(1)
        )
        expected = pct / 100.0 * cap
        eff = ITEM_EFFECTS.get("3302")
        self.assertIsNotNone(eff)
        self.assertAlmostEqual(eff.armor_pen_pct, expected, places=6)
        self.assertAlmostEqual(eff.magic_pen_pct, expected, places=6)

    def test_meraki_snapshot_has_no_terminus_arena_mirror(self) -> None:
        # The reason the assertion above cannot cover 223302, asserted
        # rather than left in a comment. Meraki's Arena-mirror coverage is
        # partial (a handful of 22xxxx ids are present), but Terminus's
        # mirror is absent, so there is no Meraki-derived Arena magnitude
        # to compare against and DDragon is the only source.
        doc = json.loads(_MERAKI_PATH.read_text(encoding="utf-8"))
        self.assertIn("3302", doc["items"])
        self.assertNotIn("223302", doc["items"])

    def test_arena_mirror_credits_its_own_feed_per_stack_times_cap(self) -> None:
        # R161 doctrine B: 223302's per-stack value comes from the ARENA
        # DDragon line ("8% Armor Penetration" per Dark stack), not from
        # SR's 10. Same cap, same convention, different stated input, so
        # the two maps must land on different magnitudes.
        cap = int(
            re.search(r"stacks up to (\d+) times", self.text).group(1)
        )
        arena_per_stack = 8.0
        expected = arena_per_stack / 100.0 * cap
        eff = ITEM_EFFECTS.get("223302")
        self.assertIsNotNone(eff)
        self.assertAlmostEqual(eff.armor_pen_pct, expected, places=6)
        self.assertAlmostEqual(eff.magic_pen_pct, expected, places=6)
        self.assertNotAlmostEqual(
            eff.armor_pen_pct, ITEM_EFFECTS["3302"].armor_pen_pct, places=6
        )


class PenFoldProperty(unittest.TestCase):
    """0.30 pen strictly beats 0.10 pen against a 200-resist target.

    Property-style over the engine's own pen pipeline
    (``effective_target_armor`` / ``effective_target_mr``), not
    data-fragile cross-item numbers: with no reductions and no flat
    pen, % pen alone leaves ``target * (1 - pen)``.
    """

    def test_synthetic_pen_shapes_and_monotone_damage(self) -> None:
        pen30 = ItemEffect(
            item_id="t30", name="pen30",
            armor_pen_pct=0.30, magic_pen_pct=0.30,
        )
        pen10 = ItemEffect(
            item_id="t10", name="pen10",
            armor_pen_pct=0.10, magic_pen_pct=0.10,
        )
        armor_at_30 = effective_target_armor(200.0, [pen30])
        armor_at_10 = effective_target_armor(200.0, [pen10])
        self.assertAlmostEqual(armor_at_30, 200.0 * 0.70, places=6)
        self.assertAlmostEqual(armor_at_10, 200.0 * 0.90, places=6)
        # Lower effective armor -> strictly higher post-mitigation
        # damage factor -> strictly higher effective damage.
        self.assertLess(armor_at_30, armor_at_10)
        self.assertGreater(_armor_factor(armor_at_30),
                           _armor_factor(armor_at_10))

    def test_registry_terminus_folds_to_seventy_pct_resists(self) -> None:
        # The live 3302 entry carries no reduction and no flat pen, so
        # both axes land exactly on target * (1 - 0.30).
        eff = ITEM_EFFECTS["3302"]
        self.assertAlmostEqual(
            effective_target_armor(200.0, [eff]), 200.0 * 0.70, places=6
        )
        self.assertAlmostEqual(
            effective_target_mr(200.0, [eff]), 200.0 * 0.70, places=6
        )


class SiblingGuards(unittest.TestCase):
    """Neighbours keep their own pins; Shadow periodic is untouched."""

    def test_black_cleaver_reduction_unchanged(self) -> None:
        self.assertAlmostEqual(
            ITEM_EFFECTS["3071"].armor_reduction_pct, 0.30, places=6
        )

    def test_ldr_armor_pen_unchanged(self) -> None:
        self.assertAlmostEqual(
            ITEM_EFFECTS["3036"].armor_pen_pct, 0.35, places=6
        )

    def test_terminus_shadow_periodic_unchanged(self) -> None:
        for item_id in ("3302", "223302"):
            periodics = ITEM_EFFECTS[item_id].periodics
            self.assertEqual(len(periodics), 1)
            shadow = periodics[0]
            self.assertEqual(shadow.name, "Shadow")
            self.assertEqual(shadow.bonus_damage, 30.0)
            self.assertEqual(shadow.damage_type, MAGICAL)
            self.assertEqual(shadow.every_n_attacks, 1)


if __name__ == "__main__":
    unittest.main()
