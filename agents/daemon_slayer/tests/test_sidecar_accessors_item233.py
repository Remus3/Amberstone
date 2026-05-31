"""Item 233 - data_loader missile_speed + static-CD accessors.

spell_missile_speed (cdragon missile_speed scalar) feeds the missile travel-time
consumer; ability_static_cd (wiki static, name-keyed) is a data-staged cross-source
(no haste model to gate against yet). Both pure reads - byte-identical engine output.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot


class MissileStaticAccessorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_missile_speed_real_projectile(self) -> None:
        # Lux Q is a real projectile -> sensible missile speed (~1200).
        ms = self.snap.spell_missile_speed("Lux", "Q")
        self.assertIsInstance(ms, float)
        self.assertGreater(ms, 400.0)

    def test_missile_speed_absent_returns_none(self) -> None:
        self.assertIsNone(self.snap.spell_missile_speed("Lux", "ZZ"))
        self.assertIsNone(self.snap.spell_missile_speed("NotAChamp", "Q"))

    def test_missile_speed_non_number_is_none(self) -> None:
        # A null missile_speed slot returns None (not a projectile).
        # Aatrox Q carries no missile data.
        self.assertIsNone(self.snap.spell_missile_speed("Aatrox", "Q"))

    def test_static_cd_present(self) -> None:
        # Amumu Bandage Toss carries a static value "3".
        v = self.snap.ability_static_cd("Amumu", "Bandage Toss")
        self.assertIsInstance(v, str)
        self.assertEqual(v, "3")

    def test_static_cd_toggle_marker(self) -> None:
        # Amumu Despair is a toggle -> static "True" (kept as the raw string).
        v = self.snap.ability_static_cd("Amumu", "Despair")
        self.assertEqual(v, "True")

    def test_static_cd_absent_returns_none(self) -> None:
        self.assertIsNone(self.snap.ability_static_cd("Aatrox", "Nope"))
        self.assertIsNone(self.snap.ability_static_cd("NotAChamp", "X"))

    def test_absent_sidecar_byte_identical(self) -> None:
        empty = DataSnapshot(
            patch="x", manifest={}, champions={"Lux": {}}, items={},
            scenarios_by_id={}, scenarios_by_lolmath={},
            arena_augments_by_id={}, arena_augments_by_api={},
            data_root=self.snap.data_root,
        )
        self.assertIsNone(empty.spell_missile_speed("Lux", "Q"))
        self.assertIsNone(empty.ability_static_cd("Amumu", "Bandage Toss"))


if __name__ == "__main__":
    unittest.main()
