"""R113 (2026-07-13) - Tiamat-tree item-active TOTAL-AD physical AoE burst.

The DSV8 ``assume_physical_burst`` seam (R74) credited ONLY Goredrinker's
Thirsting Slash active ("175% '''base''' AD" physical, Meraki 16.13.1,
pinned ``physical_burst_base_ad_ratio=1.75`` on Arena 226630). Its four
Tiamat-tree siblings each fire a once-per-cast physical AoE active off
TOTAL AD (Meraki writes plain "AD" = base + bonus, NOT "base AD") that the
burst scorer never credited:

- Tiamat 3077 "Crescent": 75% AD  -> 0.75  (SR only; no 223077 mirror)
- Ravenous Hydra 3074 "Ravenous Crescent": 80% AD -> 0.80 (+ Arena 223074)
- Profane Hydra 6698 "Heretical Cleave": 80% AD -> 0.80 (+ Arena 226698)
- Stridebreaker 6631 "Breaking Shockwave": 80% AD -> 0.80 (+ Arena 226631)

This seam adds a NEW END-appended TOTAL-AD field
``physical_burst_total_ad_ratio`` riding the SAME default-OFF
``assume_physical_burst`` flag (no new flag). The burst consumer folds
``physical_burst_total_ad_ratio * (ctx.base_ad + ctx.bonus_ad)`` into the
physical burst window - armor-mitigated (PHYSICAL routing) x mode_mult,
NO amp layer, exactly like the Goredrinker base-AD path beside it. Because
this IS physical damage the delta is armor-SENSITIVE and mode_mult-
SENSITIVE (contrast the DSV9 shield-cut seam, which is insensitive to
both).

Titanic Hydra 3748/223748 is EXCLUDED: its active is a %max-HP empowered
basic attack, a different mechanic. Goredrinker 226630 stays on the
BASE-AD field (``physical_burst_base_ad_ratio=1.75``, total-AD field 0.0).
The helper ``total_physical_burst_damage`` gained a 3rd defaulted
``caster_total_ad`` arg so 2-arg callers (the compute_ability_dps inert
path) stay byte-identical - a 2-arg call folds ratio * 0.0 = 0.0 for the
new term. Default 0.0 keeps every existing item + caller byte-identical.
"""
from __future__ import annotations

import dataclasses
import inspect
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from agents import daemon_slayer
from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.ability_dps import (
    _mitigation_factor,
    compute_ability_dps,
)
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.effects import (
    ITEM_EFFECTS,
    ItemEffect,
    collect_effects,
    total_physical_burst_damage,
)
from agents.daemon_slayer.engine import build_champion

_PATCH = "16.13.1"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_MERAKI_PATH = (
    _REPO_ROOT / "data" / "daemon_slayer" / _PATCH / "items_meraki.json"
)
_ITEMS_POOL_PATH = (
    _REPO_ROOT / "data" / "daemon_slayer" / _PATCH / "items.json"
)

# Tiamat-tree carriers (base + Arena mirror where one exists).
_TIAMAT = "3077"          # SR only - no Arena mirror
_TIAMAT_PHANTOM = "223077"  # NOT in the 16.13.1 pool
_RAVENOUS_SR = "3074"
_RAVENOUS_ARENA = "223074"
_PROFANE_SR = "6698"
_PROFANE_ARENA = "226698"
_STRIDE_SR = "6631"
_STRIDE_ARENA = "226631"

_HYDRA_08_IDS = (
    _RAVENOUS_SR, _RAVENOUS_ARENA,
    _PROFANE_SR, _PROFANE_ARENA,
    _STRIDE_SR, _STRIDE_ARENA,
)

# Base-AD path (unchanged) + excluded max-HP mechanic.
_GOREDRINKER_ARENA = "226630"
_TITANIC_SR = "3748"
_TITANIC_ARENA = "223748"

# Non-carrier siblings - must stay off the new field.
_KRAKEN = "6672"
_WITS_END = "3091"

_MELEE_CHAMP = "Darius"
_HYDRA_SR_BUILD = ["3047", _RAVENOUS_SR]  # Plated Steelcaps + Ravenous


class EngineVersion(unittest.TestCase):
    def test_engine_version_bumped(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.260.0")
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.260.0")


class SchemaDefaults(unittest.TestCase):
    """END-appended field defaults 0.0 - every existing item is inert."""

    def test_default_is_zero(self) -> None:
        eff = ItemEffect(item_id="0", name="synthetic")
        self.assertEqual(eff.physical_burst_total_ad_ratio, 0.0)

    def test_field_is_last_appended(self) -> None:
        # Mid-class insert breaks positional construction (repo convention).
        # R113 END-appended after R111's missing_hp_ad_amp_max_pct, so the
        # new field is now the very last one.
        names = [f.name for f in dataclasses.fields(ItemEffect)]
        self.assertEqual(names[-1], "physical_burst_total_ad_ratio")
        self.assertEqual(names[-2], "missing_hp_ad_amp_max_pct")
        # The R74 base-AD pair stays intact earlier in the tail.
        self.assertIn("physical_burst_base_ad_ratio", names)
        self.assertLess(
            names.index("physical_burst_base_ad_ratio"),
            names.index("physical_burst_total_ad_ratio"),
        )


class MerakiTruth(unittest.TestCase):
    """Registry pins derive from vendored Meraki 16.13.1 active text; a
    patch changing the numbers fails HERE instead of silently drifting.

    The Arena mirror ids (223074 / 226698 / 226631) are NOT present in the
    Meraki ``items`` map - they are synthetic pool mirrors that inherit the
    base item's active, so only the base ids are parsed from truth here."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.items = json.loads(
            _MERAKI_PATH.read_text(encoding="utf-8")
        )["items"]

    def _active_text(self, item_id: str, active_name: str) -> str:
        actives = self.items[item_id]["active"]
        entry = next(
            (a for a in actives if a.get("name") == active_name), None
        )
        self.assertIsNotNone(
            entry, f"Meraki {item_id} has no {active_name!r} active"
        )
        return entry["effects"]

    def _parse_total_ad_ratio(self, text: str) -> int:
        # Plain "AD" (total), NOT "'''base''' AD" - the Hydra tree.
        m = re.search(
            r"Deal \{\{as\|(\d+)% AD\}\} \{\{as\|physical damage\}\}",
            text,
        )
        self.assertIsNotNone(m, f"total-AD formula not found in: {text!r}")
        return int(m.group(1))

    def test_tiamat_75_pct(self) -> None:
        text = self._active_text(_TIAMAT, "Crescent")
        self.assertEqual(self._parse_total_ad_ratio(text), 75)

    def test_hydra_80_pct(self) -> None:
        for iid, name in (
            (_RAVENOUS_SR, "Ravenous Crescent"),
            (_PROFANE_SR, "Heretical Cleave"),
            (_STRIDE_SR, "Breaking Shockwave"),
        ):
            text = self._active_text(iid, name)
            self.assertEqual(
                self._parse_total_ad_ratio(text), 80, msg=iid
            )

    def test_goredrinker_is_base_ad_not_total(self) -> None:
        # The distinguishing marker: Goredrinker's active is "'''base''' AD"
        # so the plain-total-AD regex must NOT match it.
        text = self._active_text(_GOREDRINKER_ARENA, "Thirsting Slash")
        self.assertIn("'''base''' AD", text)
        self.assertIsNone(
            re.search(
                r"Deal \{\{as\|\d+% AD\}\} \{\{as\|physical damage\}\}",
                text,
            )
        )

    def test_titanic_is_max_hp_mechanic_not_ad(self) -> None:
        # Titanic's active empowers a basic attack for %MAXIMUM HP - it must
        # NOT be pinned to the AD-ratio field.
        text = self._active_text(_TITANIC_SR, "Titanic Crescent")
        self.assertIn("maximum", text.lower())
        self.assertIsNone(self._plain_total_ad(text))

    def _plain_total_ad(self, text: str):
        return re.search(
            r"Deal \{\{as\|\d+% AD\}\} \{\{as\|physical damage\}\}", text
        )


class RegistryPins(unittest.TestCase):
    """Hand-authored pins on the 16.13.1 registry."""

    def test_tiamat_pin(self) -> None:
        self.assertAlmostEqual(
            ITEM_EFFECTS[_TIAMAT].physical_burst_total_ad_ratio, 0.75
        )

    def test_hydra_80_pins(self) -> None:
        for iid in _HYDRA_08_IDS:
            self.assertAlmostEqual(
                ITEM_EFFECTS[iid].physical_burst_total_ad_ratio,
                0.80,
                msg=iid,
            )

    def test_no_flat_term_on_carriers(self) -> None:
        for iid in (_TIAMAT, *_HYDRA_08_IDS):
            self.assertEqual(
                ITEM_EFFECTS[iid].physical_burst_base, 0.0, msg=iid
            )
            # The Hydra tree rides the TOTAL-AD field only, never base-AD.
            self.assertEqual(
                ITEM_EFFECTS[iid].physical_burst_base_ad_ratio,
                0.0,
                msg=iid,
            )

    def test_no_phantom_tiamat_arena_mirror(self) -> None:
        pool = json.loads(
            _ITEMS_POOL_PATH.read_text(encoding="utf-8")
        )["data"]
        self.assertNotIn(_TIAMAT_PHANTOM, pool)
        self.assertNotIn(_TIAMAT_PHANTOM, ITEM_EFFECTS)

    def test_goredrinker_base_path_preserved(self) -> None:
        eff = ITEM_EFFECTS[_GOREDRINKER_ARENA]
        # Goredrinker stays on the BASE-AD path, untouched by R113.
        self.assertEqual(eff.physical_burst_total_ad_ratio, 0.0)
        self.assertAlmostEqual(eff.physical_burst_base_ad_ratio, 1.75)

    def test_titanic_excluded(self) -> None:
        for iid in (_TITANIC_SR, _TITANIC_ARENA):
            self.assertEqual(
                ITEM_EFFECTS[iid].physical_burst_total_ad_ratio,
                0.0,
                msg=iid,
            )

    def test_non_carrier_siblings_zero(self) -> None:
        for iid in (_KRAKEN, _WITS_END):
            self.assertEqual(
                ITEM_EFFECTS[iid].physical_burst_total_ad_ratio,
                0.0,
                msg=iid,
            )


class PhysicalBurstHelper(unittest.TestCase):
    """``total_physical_burst_damage`` 2-arg vs 3-arg facade math."""

    def test_profane_total_ad_three_arg(self) -> None:
        effs = collect_effects([_PROFANE_SR])
        # 0 + 0.0 * base_ad + 0.80 * 250 = 200.0.
        self.assertAlmostEqual(
            total_physical_burst_damage(effs, 110.0, 250.0), 200.0
        )

    def test_profane_two_arg_stays_inert(self) -> None:
        # The 2-arg call (compute_ability_dps inert path) folds the new term
        # against caster_total_ad=0.0 -> the Hydra active contributes 0.0.
        effs = collect_effects([_PROFANE_SR])
        self.assertEqual(total_physical_burst_damage(effs, 110.0), 0.0)

    def test_goredrinker_unchanged_by_total_arg(self) -> None:
        # Goredrinker rides base-AD; the new total arg does not touch it.
        effs = collect_effects([_GOREDRINKER_ARENA])
        self.assertAlmostEqual(
            total_physical_burst_damage(effs, 110.0, 250.0), 192.5
        )
        # 2-arg is identical (base-AD term only).
        self.assertAlmostEqual(
            total_physical_burst_damage(effs, 110.0), 192.5
        )

    def test_no_carrier_returns_zero(self) -> None:
        effs = collect_effects(["3047"])  # boots, no burst field
        self.assertEqual(
            total_physical_burst_damage(effs, 999.0, 999.0), 0.0
        )


class ComputeBurstSeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _delta(self, *, mode="SR", armor=0.0, **flags) -> float:
        off = compute_burst_damage(
            self.snap, _MELEE_CHAMP, 11, item_ids=_HYDRA_SR_BUILD,
            mode=mode, target_armor=armor, target_max_hp=2000,
            assume_physical_burst=False, **flags,
        )
        on = compute_burst_damage(
            self.snap, _MELEE_CHAMP, 11, item_ids=_HYDRA_SR_BUILD,
            mode=mode, target_armor=armor, target_max_hp=2000,
            assume_physical_burst=True, **flags,
        )
        return on.total_burst_damage - off.total_burst_damage

    def test_default_off_byte_identical(self) -> None:
        base = compute_burst_damage(
            self.snap, _MELEE_CHAMP, 11, item_ids=_HYDRA_SR_BUILD,
            mode="SR", target_armor=60, target_max_hp=2000,
        )
        off = compute_burst_damage(
            self.snap, _MELEE_CHAMP, 11, item_ids=_HYDRA_SR_BUILD,
            mode="SR", target_armor=60, target_max_hp=2000,
            assume_physical_burst=False,
        )
        self.assertEqual(base.total_burst_damage, off.total_burst_damage)

    def test_on_credits_80_pct_total_ad(self) -> None:
        # At armor 0 (PHYSICAL factor 1.0), SR (mode_mult 1.0), no amp, no
        # armor pen on the build, the delta is exactly 0.80 * TOTAL AD.
        resolved = build_champion(
            self.snap, _MELEE_CHAMP, 11, item_ids=_HYDRA_SR_BUILD,
            mode="SR",
        )
        total_ad = float(resolved.stats["ad"])
        base_ad = float(resolved.base_stats["ad"])
        self.assertGreater(total_ad, base_ad)  # build adds bonus AD
        self.assertAlmostEqual(self._delta(), 0.80 * total_ad, places=2)

    def test_armor_sensitive(self) -> None:
        # PHYSICAL burst MUST route through armor (unlike the DSV9 shield
        # cut): raising armor shrinks the delta by the engine's own PHYSICAL
        # mitigation ratio.
        d0 = self._delta(armor=0.0)
        d100 = self._delta(armor=100.0)
        self.assertGreater(d0, 0.0)
        self.assertLess(d100, d0)
        expected_ratio = (
            _mitigation_factor("PHYSICAL", 100.0, 0.0)
            / _mitigation_factor("PHYSICAL", 0.0, 0.0)
        )
        self.assertAlmostEqual(d100, d0 * expected_ratio, places=2)

    def test_mode_sensitive(self) -> None:
        # PHYSICAL burst MUST scale with mode_mult (unlike the DSV9 shield
        # cut). Darius aramDamageDealt=1.05 -> the ARAM delta is the SR
        # delta x that multiplier (same total AD, same armor factor).
        rec = self.snap.champion(_MELEE_CHAMP)
        aram = (rec.get("lolmath") or {}).get("aram_modifiers") or {}
        aram_mult = float(aram.get("aramDamageDealt", 1.0))
        self.assertNotAlmostEqual(aram_mult, 1.0)
        d_sr = self._delta(mode="SR", armor=0.0)
        d_aram = self._delta(mode="ARAM", armor=0.0)
        self.assertNotAlmostEqual(d_sr, d_aram)
        self.assertAlmostEqual(d_aram, d_sr * aram_mult, places=2)

    def test_cross_seam_isolation(self) -> None:
        # The physical delta is unchanged when unrelated burst seams are ON
        # (the Hydra build carries no takedown / magic-burst item, so those
        # flags add nothing and cancel across the on/off pair).
        base = self._delta()
        self.assertAlmostEqual(
            self._delta(assume_takedown=True), base, places=4
        )
        self.assertAlmostEqual(
            self._delta(assume_magic_burst=True), base, places=4
        )

    def test_mr_insensitive(self) -> None:
        # A PHYSICAL burst must not care about MR.
        def delta(mr: float) -> float:
            off = compute_burst_damage(
                self.snap, _MELEE_CHAMP, 11, item_ids=_HYDRA_SR_BUILD,
                mode="SR", target_armor=60, target_mr=mr,
                target_max_hp=2000,
            )
            on = compute_burst_damage(
                self.snap, _MELEE_CHAMP, 11, item_ids=_HYDRA_SR_BUILD,
                mode="SR", target_armor=60, target_mr=mr,
                target_max_hp=2000, assume_physical_burst=True,
            )
            return on.total_burst_damage - off.total_burst_damage

        self.assertAlmostEqual(delta(0.0), delta(200.0), places=4)


class ComputeDpsDoubleCount(unittest.TestCase):
    """The active has NO PeriodicProc; only the pre-existing Cleave
    periodic contributes to compute_dps, which never reads the new field."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_compute_dps_has_no_seam_kwarg(self) -> None:
        self.assertNotIn(
            "assume_physical_burst",
            inspect.signature(compute_dps).parameters,
        )

    def test_dps_byte_identical_with_vs_without_field(self) -> None:
        # Zero the new field on the real Ravenous entry; compute_dps must be
        # byte-identical, proving the burst field does not leak into DPS.
        zeroed = dataclasses.replace(
            ITEM_EFFECTS[_RAVENOUS_SR], physical_burst_total_ad_ratio=0.0
        )

        def _dps():
            return compute_dps(
                self.snap, champion_id=_MELEE_CHAMP, level=11,
                item_ids=_HYDRA_SR_BUILD, mode="SR",
                target_armor=60, target_mr=40, target_max_hp=2000,
            ).weighted_dps

        with_field = _dps()
        with mock.patch.dict(ITEM_EFFECTS, {_RAVENOUS_SR: zeroed}):
            without_field = _dps()
        self.assertEqual(with_field, without_field)


class AbilityDpsInertKwarg(unittest.TestCase):
    """compute_ability_dps accepts assume_physical_burst for API symmetry
    but is DELIBERATELY INERT - the Hydra field must not leak into it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_inert_on_equals_off(self) -> None:
        off = compute_ability_dps(
            self.snap, _MELEE_CHAMP, 11, item_ids=_HYDRA_SR_BUILD,
            mode="SR", target_armor=60, target_max_hp=2000,
            assume_physical_burst=False,
        )
        on = compute_ability_dps(
            self.snap, _MELEE_CHAMP, 11, item_ids=_HYDRA_SR_BUILD,
            mode="SR", target_armor=60, target_max_hp=2000,
            assume_physical_burst=True,
        )
        self.assertEqual(on.total_ability_dps, off.total_ability_dps)


if __name__ == "__main__":
    unittest.main()
