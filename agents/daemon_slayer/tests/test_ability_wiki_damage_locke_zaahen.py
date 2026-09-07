"""RM wiki-damage injection - Locke + Zaahen ability-keyspace hole.

MEASURED DEFECT (2026-07-25). The DS champion roster is 173
(``data/daemon_slayer/16.14.1/champions.json``) but the ability keyspace is
171 (``champion_abilities.json``). The set difference is exactly
``['Locke', 'Zaahen']`` - the Meraki bulk snapshot never shipped them. Every
other champion has at least one ``attribute_kind == "damage"`` block, so these
two are the ONLY total fall-throughs, and they fall through to zero:

* ``compute_burst_damage`` returns ``total_burst_damage == 0.0`` and every cast
  carries ``notes == ("ability data unavailable",)`` / ``form_index == -1``.
* ``rank_items(..., fight_length=...)`` therefore reads ``baseline_burst 0.0``,
  and every candidate's ``delta_burst`` is 0.0 - the whole ranked table is
  degenerate.

The fix is the hand-authored ``_ability_wiki_damage_registry``, injected into
the snapshot's ``data`` container KEYS-NOT-PRESENT-ONLY. This file pins:

* RED 1 - both champions reach ``champion_ids()``.
* RED 2 - Locke Q carries a damage block with a non-empty ``base``.
* ACCEPTANCE - both champions score ``total_burst_damage > 0.0`` (the exact
  quantity ``rank.baseline_burst`` reads, see ``rank.py:1118-1131``).
* NEGATIVE CONTROLS - Zed stays EXACTLY 807.3862433862435 and Aphelios stays
  in its 259.5 band at the measured probe params, and the full-roster sweep is
  byte-identical on all 171 pre-existing champions between flag OFF and ON.
* ANTI-VACUITY - the registry is non-empty and every champion it claims
  actually lands in the snapshot with at least one evaluable damage block.

The probe params are the ones the live ``:8860`` defect was measured with:
``items=["3142","6691","3814"], level=13, target_armor=140, target_mr=90,
target_hp=2800``.

No ``core.*`` import at module level (deliberate - keeps this file runnable
against the engine package alone, with no host application present).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer._ability_wiki_damage_registry import (
    WIKI_ABILITY_DAMAGE_CHAMPIONS,
    iter_injectable_champions,
)
from agents.daemon_slayer.abilities import AbilitiesSnapshot, reset_default_cache
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot

# The two champions the Meraki snapshot never shipped.
_MISSING = ("Locke", "Zaahen")

# Live-measured probe params (:8860 POST /rank-assassin + POST /burst).
_PROBE = dict(
    level=13,
    item_ids=("3142", "6691", "3814"),
    mode="sr",
    target_armor=140.0,
    target_mr=90.0,
    target_max_hp=2800.0,
)

# Named negative controls, measured on this tree at the params above BEFORE the
# registry existed. Zed is strict-exact; Aphelios is pinned to its band.
_ZED_EXACT = 807.3862433862435
_APHELIOS_BAND = (259.0, 260.0)


def _data_snapshot() -> DataSnapshot:
    reset_default_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


def _abilities(on: bool) -> AbilitiesSnapshot:
    return AbilitiesSnapshot.load(apply_wiki_ability_damage=on)


def _burst(ds: DataSnapshot, champion: str, abil: AbilitiesSnapshot) -> float:
    return compute_burst_damage(
        ds, champion_id=champion, abilities_snapshot=abil, **_PROBE
    ).total_burst_damage


class KeyspaceHoleTests(unittest.TestCase):
    """RED 1 - the two champions must reach the snapshot at all."""

    def test_missing_champions_present_by_default(self) -> None:
        snap = AbilitiesSnapshot.load()
        ids = set(snap.champion_ids())
        for cid in _MISSING:
            self.assertIn(cid, ids, f"{cid} absent from the ability keyspace")

    def test_flag_off_reproduces_the_hole(self) -> None:
        """The seam is real: OFF still has the 171-key hole."""
        ids = set(_abilities(False).champion_ids())
        for cid in _MISSING:
            self.assertNotIn(cid, ids)

    def test_default_is_on(self) -> None:
        """Ship DEFAULT-ON - a champion the snapshot lacks has no prior behavior."""
        self.assertEqual(
            set(AbilitiesSnapshot.load().champion_ids()),
            set(_abilities(True).champion_ids()),
        )

    def test_injection_adds_exactly_the_missing_two(self) -> None:
        off = set(_abilities(False).champion_ids())
        on = set(_abilities(True).champion_ids())
        self.assertEqual(on - off, set(_MISSING))
        self.assertEqual(off - on, set())


class DamageBlockShapeTests(unittest.TestCase):
    """RED 2 - the injected forms carry real, evaluable damage."""

    def setUp(self) -> None:
        self.snap = _abilities(True)

    def test_locke_q_has_damage_block_with_base(self) -> None:
        form = self.snap.get_ability("Locke", "Q")
        blocks = form.damage_blocks_only()
        self.assertTrue(blocks, "Locke Q has no attribute_kind='damage' block")
        self.assertTrue(
            any(b.base for b in blocks),
            "Locke Q damage blocks all have an empty base tuple",
        )

    def test_zaahen_r_has_damage_block_with_base(self) -> None:
        form = self.snap.get_ability("Zaahen", "R")
        blocks = form.damage_blocks_only()
        self.assertTrue(blocks)
        self.assertTrue(any(b.base for b in blocks))

    def test_first_block_of_every_damage_form_is_kind_damage(self) -> None:
        """``ability_dps._select_blocks`` reads ``damage_blocks[0]`` WITHOUT
        filtering on ``attribute_kind`` - a non-damage block at index 0 would be
        evaluated as damage. The registry orders damage blocks first."""
        for cid in _MISSING:
            for key, forms in self.snap.get_abilities(cid).items():
                for form in forms:
                    if not form.damage_blocks:
                        continue
                    self.assertEqual(
                        form.damage_blocks[0].attribute_kind,
                        "damage",
                        f"{cid} {key} block 0 is "
                        f"{form.damage_blocks[0].attribute_kind!r}, not 'damage'",
                    )

    def test_no_block_carries_two_fields_of_one_stat_family(self) -> None:
        """Repo-wide machine guard (``test_cdragon_ratio_matcher.py:33`` +
        ``test_cdragon_surplus_ad_a29.py:83``): no damage block may hold two
        AD-family or two HP-family fields. Zaahen Q's wiki row carries both a
        total-AD and a bonus-AD ratio, so the registry splits it across
        adjacent blocks - this pins that split."""
        ad = ("total_ad_pct", "bonus_ad_pct")
        hp = ("caster_max_hp_pct", "caster_bonus_hp_pct")
        for cid in _MISSING:
            for key, forms in self.snap.get_abilities(cid).items():
                for form in forms:
                    for block in form.damage_blocks:
                        for family in (ad, hp):
                            n = sum(getattr(block, f) is not None for f in family)
                            self.assertLessEqual(
                                n, 1,
                                f"{cid} {key} {block.attribute} carries "
                                f"{n} fields of one stat family",
                            )

    def test_all_five_keys_present(self) -> None:
        for cid in _MISSING:
            per_key = self.snap.get_abilities(cid)
            for key in ("P", "Q", "W", "E", "R"):
                self.assertIn(key, per_key)
                self.assertTrue(per_key[key], f"{cid} {key} has no form")

    def test_ult_rank_counts_are_three(self) -> None:
        for cid in _MISSING:
            form = self.snap.get_ability(cid, "R")
            self.assertIsNotNone(form.cooldown)
            self.assertEqual(len(form.cooldown or ()), 3, f"{cid} R is not 3-rank")

    def test_scaling_series_lengths_match_rank_count(self) -> None:
        """Every per-rank series is 1 (flat) or the ability's rank count."""
        for cid in _MISSING:
            for key, forms in self.snap.get_abilities(cid).items():
                want = 3 if key == "R" else 5
                for form in forms:
                    for block in form.damage_blocks:
                        for fname in ("base", "total_ad_pct", "bonus_ad_pct",
                                      "ap_pct", "caster_max_hp_pct",
                                      "target_max_hp_pct"):
                            vals = getattr(block, fname)
                            if vals is None:
                                continue
                            self.assertIn(
                                len(vals), (1, want),
                                f"{cid} {key} {block.attribute} {fname} "
                                f"has {len(vals)} entries",
                            )


class BurstAcceptanceTests(unittest.TestCase):
    """ACCEPTANCE - baseline_burst leaves 0.0."""

    def setUp(self) -> None:
        self.ds = _data_snapshot()
        self.on = _abilities(True)

    def test_missing_champions_burst_is_positive(self) -> None:
        for cid in _MISSING:
            with self.subTest(champion=cid):
                self.assertGreater(_burst(self.ds, cid, self.on), 0.0)

    def test_flag_off_still_zero(self) -> None:
        off = _abilities(False)
        for cid in _MISSING:
            with self.subTest(champion=cid):
                self.assertEqual(_burst(self.ds, cid, off), 0.0)

    def test_no_ability_data_unavailable_note(self) -> None:
        for cid in _MISSING:
            res = compute_burst_damage(
                self.ds, champion_id=cid, abilities_snapshot=self.on, **_PROBE
            )
            for cast in res.per_cast:
                self.assertNotIn("ability data unavailable", cast.notes)


class NegativeControlTests(unittest.TestCase):
    """The injection is keys-not-present-only, so nothing else may move."""

    def setUp(self) -> None:
        self.ds = _data_snapshot()
        self.on = _abilities(True)

    def test_zed_control_is_byte_identical(self) -> None:
        self.assertEqual(_burst(self.ds, "Zed", self.on), _ZED_EXACT)

    def test_aphelios_control_stays_in_band(self) -> None:
        val = _burst(self.ds, "Aphelios", self.on)
        self.assertGreater(val, _APHELIOS_BAND[0])
        self.assertLess(val, _APHELIOS_BAND[1])

    def test_full_roster_sweep_171_byte_identical(self) -> None:
        """The strongest form: sweep every pre-existing champion OFF vs ON and
        require byte-identical floats. Holds by construction (only absent keys
        are added); a failure here means the injection is overwriting."""
        off = _abilities(False)
        on = self.on
        shared = sorted(set(off.champion_ids()))
        self.assertEqual(len(shared), 171)
        moved = []
        for cid in shared:
            a = _burst(self.ds, cid, off)
            b = _burst(self.ds, cid, on)
            if a != b:
                moved.append((cid, a, b))
        self.assertEqual(moved, [], f"{len(moved)} pre-existing champions moved")

    def test_forms_object_graph_unchanged_for_existing_champions(self) -> None:
        off = _abilities(False)
        on = self.on
        for cid in off.champion_ids():
            self.assertEqual(off.champions[cid], on.champions[cid], cid)


class AntiVacuityTests(unittest.TestCase):
    """A registry that silently emptied itself would pass every test above."""

    def test_registry_is_non_empty(self) -> None:
        self.assertTrue(WIKI_ABILITY_DAMAGE_CHAMPIONS)
        self.assertEqual(set(WIKI_ABILITY_DAMAGE_CHAMPIONS), set(_MISSING))

    def test_every_claimed_champion_reaches_the_snapshot(self) -> None:
        snap = _abilities(True)
        claimed = dict(iter_injectable_champions())
        self.assertTrue(claimed)
        for cid, keymap in claimed.items():
            self.assertTrue(snap.has_champion(cid), f"{cid} claimed but absent")
            landed = snap.get_abilities(cid)
            for key, payload_forms in keymap.items():
                self.assertEqual(
                    len(landed.get(key, ())),
                    len(payload_forms),
                    f"{cid} {key} form count did not survive the load",
                )

    def test_every_claimed_champion_has_an_evaluable_damage_block(self) -> None:
        snap = _abilities(True)
        for cid in WIKI_ABILITY_DAMAGE_CHAMPIONS:
            found = False
            for _key, forms in snap.get_abilities(cid).items():
                for form in forms:
                    for block in form.damage_blocks_only():
                        if block.has_damage_scaling():
                            found = True
            self.assertTrue(found, f"{cid} has no evaluable damage block")

    def test_every_entry_cites_its_wiki_source(self) -> None:
        from agents.daemon_slayer._ability_wiki_damage_registry import WIKI_SOURCES

        self.assertTrue(WIKI_SOURCES)
        for cid in WIKI_ABILITY_DAMAGE_CHAMPIONS:
            for key in ("P", "Q", "W", "E", "R"):
                self.assertIn(
                    (cid, key), WIKI_SOURCES, f"{cid} {key} has no cited wiki page"
                )
                page, fetched = WIKI_SOURCES[(cid, key)]
                self.assertTrue(page.startswith("Template:Data "))
                self.assertEqual(fetched, "2026-07-25")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
