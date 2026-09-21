"""F2 (2026-09-21) - champion_block_index.json is a DAMAGE-ORDINAL registry.

The engine consumer ``ability_dps._select_blocks`` (shared by
``compute_ability_dps`` and ``burst.compute_burst_damage``) filters a form's
blocks to ``attribute_kind == "damage"`` FIRST and only then indexes, so every
registry value is an ordinal into that damage-only list. Eighteen entries had
been authored as indexes into the UNFILTERED Meraki block list (heal / slow /
armor rows included). All eighteen pointed past the last damage block and were
rescued - or not - by the silent clamp-to-last:

* 16 landed on the intended block by luck (the intended block was the last
  damage block);
* Malphite W ``[2, 3]`` clamped to ``[1, 1]`` - it double-counted the cone
  "Physical Damage" block and dropped the empowered-AA "Bonus Physical
  Damage" block entirely;
* Briar E ``4`` clamped to damage ordinal 3 "Total Magic Damage". The
  all-blocks reading (``4`` = "Bonus Magic Damage", the terrain-collision
  bonus ALONE) is not what the entry's own rationale describes ("max-charge
  scream + collision-headbutt total", i.e. the fully-charged-plus-impact
  value). Meraki and the wiki both carry the wall bonus as ADDITIVE to the
  80-220 max-charge scream, and Meraki's "Total Magic Damage" row is exactly
  their sum, so ordinal 3 is the entry's intended block. It is now authored
  explicitly instead of reached through the clamp.

This module guards the invariant so the registry never again relies on the
clamp: every value in every entry (int, list element, and every conditional
branch) must be in range for the CURRENT patch's damage-block list of the
engine-resolved form. The clamp itself stays (a caller-supplied HTTP override
or a future re-extract that drops a block must not 500 a ranking route) but it
is no longer silent - it logs a WARNING.
"""
from __future__ import annotations

import logging
import unittest

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer._ability_amp_overrides import _STAGED_AMP_BLOCK_ROUTES
from agents.daemon_slayer.abilities import (
    AbilitiesSnapshot,
    DamageBlock,
    load_default,
    reset_default_cache,
)
from agents.daemon_slayer.ability_dps import (
    AbilityContext,
    _evaluate_block,
    _load_block_index_table,
    _resolve_form_index_overrides,
    _select_blocks,
    compute_ability_dps,
    get_block_index_for,
    reset_block_index_cache,
    reset_form_index_cache,
)
from agents.daemon_slayer.data_loader import DataSnapshot


def _snap() -> DataSnapshot:
    reset_default_cache()
    reset_block_index_cache()
    reset_form_index_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


def _abil() -> AbilitiesSnapshot:
    """The abilities snapshot ``compute_ability_dps`` falls back to."""
    return load_default()


def _leaves(v) -> list[int]:
    if isinstance(v, dict):
        out: list[int] = []
        for cv in v.values():
            out.extend(_leaves(cv))
        return out
    if isinstance(v, int):
        return [v]
    return [int(x) for x in v]


def _engine_form(snap: AbilitiesSnapshot, champ: str, key: str):
    """The form the engine evaluates for ``key`` - same resolution as
    ``compute_ability_dps`` / ``compute_burst_damage`` (form_index registry,
    out-of-range form index falls back to form 0)."""
    forms = snap.get_abilities(champ).get(key, ())
    if not forms:
        return None
    fmap, _ = _resolve_form_index_overrides(champ, None)
    fi = fmap.get(key, 0)
    if fi < 0 or fi >= len(forms):
        fi = 0
    return forms[fi]


def _dmg(form) -> list[DamageBlock]:
    return [b for b in form.damage_blocks if b.attribute_kind == "damage"]


def _ctx() -> AbilityContext:
    return AbilityContext(
        base_ad=0.0, total_ad=0.0, bonus_ad=0.0, ap=0.0,
        caster_max_hp=0.0, caster_bonus_hp=0.0,
        caster_bonus_armor=0.0, caster_bonus_mr=0.0,
        caster_max_mp=0.0, caster_mp_regen_per_5=0.0,
        target_armor=80.0, target_mr=30.0,
        target_max_hp=2000.0, target_current_hp=2000.0,
        target_missing_hp=0.0, target_bonus_hp=0.0,
    )


class RegistryDamageOrdinalInRangeTests(unittest.TestCase):
    """No registry entry may depend on the clamp."""

    @classmethod
    def setUpClass(cls) -> None:
        _snap()
        cls.snap = _abil()
        cls.table = _load_block_index_table()["champions"]

    def test_every_entry_in_range_of_engine_damage_blocks(self) -> None:
        out_of_range: list[str] = []
        checked = 0
        for champ in self.table:
            if champ.startswith("_") or champ not in self.snap.champions:
                continue
            bmap, _ = get_block_index_for(champ)
            for tok, v in bmap.items():
                form = _engine_form(self.snap, champ, tok[0])
                self.assertIsNotNone(form, f"{champ} {tok}: no ability form")
                n = len(_dmg(form))
                for i in _leaves(v):
                    checked += 1
                    if not 0 <= i < n:
                        out_of_range.append(
                            f"{champ} {tok}={v!r}: idx {i} vs {n} damage blocks "
                            f"{[b.attribute for b in _dmg(form)]}"
                        )
        # Anchor: an empty enumeration must not pass silently.
        self.assertGreater(checked, 150, "registry enumeration collapsed")
        self.assertEqual(out_of_range, [], "\n".join(out_of_range))

    def test_every_registry_champion_resolves_in_snapshot(self) -> None:
        missing = [c for c in self.table
                   if not c.startswith("_") and c not in self.snap.champions]
        self.assertEqual(missing, [])

    def test_staged_amp_block_routes_in_range(self) -> None:
        """Sibling damage-ordinal registry (C1 item 246) - same invariant."""
        self.assertTrue(_STAGED_AMP_BLOCK_ROUTES)
        for (champ, key, fi), idx in _STAGED_AMP_BLOCK_ROUTES.items():
            forms = self.snap.get_abilities(champ).get(key, ())
            self.assertLess(fi, len(forms), f"{champ} {key} form {fi}")
            n = len(_dmg(forms[fi]))
            self.assertTrue(0 <= idx < n, f"{champ} {key} f{fi}: {idx} vs {n}")


class LoadBearingEntriesTests(unittest.TestCase):
    """The two entries whose clamped result was not the intended block."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()
        cls.abil = _abil()

    def _labels(self, champ: str, key: str) -> list[str]:
        bmap, _ = get_block_index_for(champ)
        dmg = _dmg(_engine_form(self.abil, champ, key))
        return [dmg[i].attribute for i in _leaves(bmap[key])]

    def _spell(self, champ: str, key: str, overrides=None):
        out = compute_ability_dps(
            self.snap, champ, level=11, item_ids=[], mode="SR",
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            block_index_overrides=overrides,
        )
        return next(s for s in out.per_spell if s.key == key)

    def test_malphite_W_sums_both_distinct_damage_blocks(self) -> None:
        self.assertEqual(
            self._labels("Malphite", "W"),
            ["Bonus Physical Damage", "Physical Damage"],
        )
        s = self._spell("Malphite", "W")
        b0 = self._spell("Malphite", "W", {"W": 0})
        b1 = self._spell("Malphite", "W", {"W": 1})
        self.assertAlmostEqual(
            s.raw_damage_per_cast,
            b0.raw_damage_per_cast + b1.raw_damage_per_cast, places=4,
        )
        # The pre-fix clamp credited block 1 twice.
        self.assertNotAlmostEqual(
            s.raw_damage_per_cast, 2 * b1.raw_damage_per_cast, places=2,
        )

    def test_briar_E_routes_to_total_max_charge_plus_collision(self) -> None:
        self.assertEqual(self._labels("Briar", "E"), ["Total Magic Damage"])
        dmg = _dmg(_engine_form(self.abil, "Briar", "E"))
        by = {b.attribute: b for b in dmg}
        # Total == max-charge scream + terrain-collision bonus (additive).
        for rank in range(5):
            self.assertAlmostEqual(
                by["Total Magic Damage"].base[rank],
                by["Maximum Magic Damage"].base[rank]
                + by["Bonus Magic Damage"].base[rank],
                places=6,
            )


class ClampIsLoudTests(unittest.TestCase):
    """Clamp kept for runtime robustness, but it now logs a WARNING."""

    def setUp(self) -> None:
        from agents.daemon_slayer import ability_dps
        ability_dps._CLAMP_WARNED.clear()
        self.blocks = (
            DamageBlock(attribute="Heal", attribute_kind="heal", base=(99.0,) * 5),
            DamageBlock(attribute="A", attribute_kind="damage", base=(10.0,) * 5),
            DamageBlock(attribute="B", attribute_kind="damage", base=(30.0,) * 5),
        )

    def test_out_of_range_warns_and_clamps_to_last(self) -> None:
        with self.assertLogs("agents.daemon_slayer.ability_dps", "WARNING") as cm:
            got = _select_blocks(self.blocks, 0, _ctx(), "indexed", block_index=2)
        self.assertAlmostEqual(got, _evaluate_block(self.blocks[2], 0, _ctx()))
        self.assertIn("out of range", cm.output[0])

    def test_negative_warns_and_clamps_to_first(self) -> None:
        with self.assertLogs("agents.daemon_slayer.ability_dps", "WARNING"):
            got = _select_blocks(self.blocks, 0, _ctx(), "indexed", block_index=-1)
        self.assertAlmostEqual(got, 10.0)

    def test_in_range_is_silent(self) -> None:
        with self.assertNoLogs("agents.daemon_slayer.ability_dps", "WARNING"):
            got = _select_blocks(self.blocks, 0, _ctx(), "indexed",
                                 block_index=[0, 1])
        self.assertAlmostEqual(got, 40.0)

    def test_warning_is_deduplicated(self) -> None:
        with self.assertLogs("agents.daemon_slayer.ability_dps", "WARNING") as cm:
            for _ in range(5):
                _select_blocks(self.blocks, 0, _ctx(), "indexed", block_index=7)
        self.assertEqual(len(cm.output), 1)


if __name__ == "__main__":
    unittest.main()
