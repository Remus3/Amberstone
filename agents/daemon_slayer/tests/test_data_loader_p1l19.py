"""P1-L19 audit: non-item DataSnapshot construction fidelity + integrity.

A prior pass verified ITEM stat ingestion (DDragon items.json -> engine,
bit-exact). This lane covers the REST of snapshot construction:

* champion base-stat fidelity (every scaling-rule / passthrough field 1:1
  vs the vendored ``champions.json``; attackspeedperlevel scale; nothing
  defaulted instead of read; no champion dropped),
* scenario/rotation inputs the DPS layer consumes load correctly and
  completely (no scenario silently empty that the engine treats as 0),
* snapshot integrity (counts vs manifest, no duplicate champion keys,
  loaded patch == ``current.txt``, and - the bug this file pins - a
  structurally-wrong vendored file fails LOUDLY via the module's defined
  error rather than yielding a degenerate empty snapshot).

Expected values are read from the vendored source files IN THE TEST. No
hardcoded magic numbers; no fragile cross-record comparison asserts.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agents.daemon_slayer.abilities import AbilitiesNotFound, AbilitiesSnapshot
from agents.daemon_slayer.data_loader import DataSnapshot, SnapshotNotFound
from agents.daemon_slayer.dps import _phase_rotations
from agents.daemon_slayer.engine import build_champion
from agents.daemon_slayer.hps import (
    EnchanterFormulasNotFound,
    EnchanterFormulasSnapshot,
)
from agents.daemon_slayer.stats import (
    CHAMPION_SCALING_RULES,
    PASSTHROUGH_STAT_FIELDS,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DS_DATA = _REPO_ROOT / "data" / "daemon_slayer"


def _current_patch() -> str:
    return (_DS_DATA / "current.txt").read_text(encoding="utf-8").strip()


def _raw_champions() -> dict:
    patch = _current_patch()
    doc = json.loads(
        (_DS_DATA / patch / "champions.json").read_text(encoding="utf-8")
    )
    return doc["data"]


def _raw_scenarios() -> dict:
    patch = _current_patch()
    return json.loads(
        (_DS_DATA / patch / "scenarios.json").read_text(encoding="utf-8")
    )


# A deliberately wide spread: melee/ranged, manaless, energy, multi-form,
# new champs, enchanter, ADC, tank, marksman-with-no-mana, etc.
_SAMPLE = (
    "Aatrox", "Lux", "Garen", "Jhin", "Senna", "Aphelios", "Kindred",
    "Thresh", "Yuumi", "Zeri", "Naafiri", "Briar", "Smolder", "Velkoz",
    "Sett", "Rengar", "Sona", "Karthus", "Viego", "Gnar",
)


class ChampionBaseStatFidelity(unittest.TestCase):
    """Snapshot champion stats == vendored champions.json, 1:1."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()
        cls.raw = _raw_champions()

    def test_sample_champions_present(self) -> None:
        for cid in _SAMPLE:
            self.assertIn(cid, self.raw, f"{cid} absent from vendored source")
            self.assertIn(cid, self.snap.champions, f"{cid} dropped by loader")

    def test_every_scaled_and_passthrough_stat_is_one_to_one(self) -> None:
        """hp/mp/regen/armor/mr/ad/as/crit + per-level + ms/range, exact."""
        for cid in _SAMPLE:
            raw_stats = self.raw[cid]["stats"]
            snap_stats = self.snap.champion(cid)["stats"]
            for rule in CHAMPION_SCALING_RULES:
                for fld in (rule.base_field, rule.perlevel_field):
                    self.assertIn(
                        fld, raw_stats,
                        f"{cid}: scaling field {fld} missing from source",
                    )
                    self.assertEqual(
                        snap_stats[fld], raw_stats[fld],
                        f"{cid}.{fld}: snapshot {snap_stats.get(fld)!r} "
                        f"!= source {raw_stats[fld]!r}",
                    )
            for _canonical, ddragon_field in PASSTHROUGH_STAT_FIELDS.items():
                self.assertIn(ddragon_field, raw_stats, f"{cid}:{ddragon_field}")
                self.assertEqual(
                    snap_stats[ddragon_field], raw_stats[ddragon_field],
                    f"{cid}.{ddragon_field} passthrough mismatch",
                )

    def test_attackspeedperlevel_scale_is_percent_points(self) -> None:
        """DDragon ships attackspeedperlevel as percent points (0..~6).

        stats.attack_speed_scaling divides by 100. If the loader/source
        ever shipped it as a unit fraction the magnitude would collapse
        to <0.1 and AS growth would be ~100x too small. Pin the band
        from the vendored source itself (no magic literal).
        """
        vals = [
            c["stats"]["attackspeedperlevel"] for c in self.raw.values()
        ]
        self.assertTrue(all(v >= 0 for v in vals))
        # At least one champion has a meaningful (>1.0 percent-point)
        # AS-per-level; that is impossible if the value were a fraction.
        self.assertGreater(
            max(vals), 1.0,
            "attackspeedperlevel max <=1.0 - looks fraction-scaled, "
            "expected percent points",
        )

    def test_leveled_base_ad_matches_riot_quadratic_from_source(self) -> None:
        """build_champion's leveled base AD == base + per*growth(level).

        Growth formula itself is settled/verified elsewhere; here we only
        assert the LOADED base/per-level inputs feed the engine unaltered
        by recomputing from the raw source and comparing at L1 and L18
        (the two exact endpoints) plus a mid level.
        """
        from agents.daemon_slayer.stats import growth_multiplier

        for cid in ("Garen", "Lux", "Aatrox"):
            rs = self.raw[cid]["stats"]
            base = float(rs["attackdamage"])
            per = float(rs["attackdamageperlevel"])
            for lvl in (1, 9, 18):
                res = build_champion(self.snap, cid, lvl, item_ids=[])
                expected = base + per * growth_multiplier(lvl)
                self.assertAlmostEqual(
                    res.base_stats["ad"], expected, places=6,
                    msg=f"{cid} L{lvl} leveled base AD off",
                )


class ScenarioRotationCompleteness(unittest.TestCase):
    """The DPS-consumed scenario inputs load correctly + completely."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()
        cls.raw_sc = _raw_scenarios()

    def test_every_champion_has_a_scenario_record(self) -> None:
        missing = [
            cid for cid in self.snap.champions if not self.snap.scenarios(cid)
        ]
        self.assertEqual(missing, [], f"champions with no scenario: {missing}")

    def test_scenarios_by_id_and_lolmath_parity_with_manifest(self) -> None:
        man = self.snap.manifest["lolmath_counts"]["scenarios"]
        self.assertEqual(len(self.snap.scenarios_by_id), man)
        self.assertEqual(len(self.snap.scenarios_by_lolmath), man)
        self.assertEqual(
            len(self.snap.scenarios_by_id), len(self.raw_sc["byDDragonId"])
        )

    def test_dps_phase_rotations_load_with_nonzero_duration(self) -> None:
        """_phase_rotations is what compute_dps actually consumes.

        Every champion must yield non-empty early/mid/late rotation lists
        whose duration > 0 - a duration of 0 makes _rotation_attack_dps
        silently return 0.0 (the 'scenario silently empty -> engine
        treats as 0' failure mode this test guards).
        """
        for cid in _SAMPLE:
            phases = _phase_rotations(self.snap, cid)
            for phase in ("early", "mid", "late"):
                rots = phases[phase]
                self.assertTrue(
                    rots, f"{cid}: {phase} rotation list empty"
                )
                for r in rots:
                    self.assertGreater(
                        float(r.get("duration", 0) or 0), 0.0,
                        f"{cid}/{phase} rotation {r.get('title')!r} "
                        f"has duration<=0 -> DPS silently 0",
                    )
                    for fld in ("basic", "basicTime", "weight"):
                        self.assertIn(
                            fld, r,
                            f"{cid}/{phase} rotation missing {fld!r}",
                        )

    def test_rotation_fields_match_vendored_source_one_to_one(self) -> None:
        """Spot the loaded early[0] rotation against raw scenarios.json."""
        by_id = self.raw_sc["byDDragonId"]
        for cid in ("Aatrox", "Jhin", "Garen"):
            raw_rot = by_id[cid][0]["settings"]["scenario"]["early"][0]
            loaded_rot = _phase_rotations(self.snap, cid)["early"][0]
            for fld in ("basic", "basicTime", "duration", "weight",
                        "numberOfTargets"):
                self.assertEqual(
                    loaded_rot.get(fld), raw_rot.get(fld),
                    f"{cid} early[0].{fld}: loaded {loaded_rot.get(fld)!r} "
                    f"!= source {raw_rot.get(fld)!r}",
                )


class SnapshotIntegrity(unittest.TestCase):
    """Counts, no dup keys, patch consistency, LOUD failure on corruption."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_counts_match_manifest(self) -> None:
        self.assertEqual(
            len(self.snap.champions),
            self.snap.manifest["ddragon_champion_count"],
        )
        self.assertEqual(
            len(self.snap.items),
            self.snap.manifest["ddragon_item_count"],
        )

    def test_no_duplicate_champion_keys_in_vendored_json(self) -> None:
        """json.loads collapses dup keys silently; detect via pairs hook."""
        dups: list[str] = []

        def hook(pairs):
            seen: dict = {}
            for k, v in pairs:
                if k in seen:
                    dups.append(k)
                seen[k] = v
            return seen

        patch = _current_patch()
        json.loads(
            (_DS_DATA / patch / "champions.json").read_text(encoding="utf-8"),
            object_pairs_hook=hook,
        )
        self.assertEqual(dups, [], f"duplicate keys in champions.json: {dups}")

    def test_loaded_patch_equals_pointer_and_manifest(self) -> None:
        self.assertEqual(self.snap.patch, _current_patch())
        self.assertEqual(
            self.snap.manifest["ddragon_version"], self.snap.patch
        )

    # ----- LOUD-failure regression pins (the P1-L19 bug) ----------------

    def _stage(self, tmp: Path) -> Path:
        patch = _current_patch()
        (tmp / "current.txt").write_text(patch, encoding="utf-8")
        dst = tmp / patch
        dst.mkdir()
        for f in (
            "manifest.json", "champions.json", "items.json",
            "scenarios.json", "arena_augments.json",
            "champion_abilities.json", "enchanter_items.json",
        ):
            shutil.copy(_DS_DATA / patch / f, dst / f)
        return dst

    def test_truncated_json_raises_loudly(self) -> None:
        """A truncated (invalid-JSON) vendored file must raise, not empty."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            dst = self._stage(tmp)
            (dst / "champions.json").write_text(
                '{ "data": { "Aatrox": ', encoding="utf-8"
            )
            with self.assertRaises(json.JSONDecodeError):
                DataSnapshot.load(patch=_current_patch(), data_root=tmp)

    def test_champions_missing_data_key_fails_loudly(self) -> None:
        """Valid JSON but no 'data' container -> defined error, NOT a
        silent zero-champion snapshot."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            dst = self._stage(tmp)
            (dst / "champions.json").write_text(
                json.dumps({"version": _current_patch()}), encoding="utf-8"
            )
            with self.assertRaises(SnapshotNotFound):
                DataSnapshot.load(patch=_current_patch(), data_root=tmp)

    def test_items_missing_data_key_fails_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            dst = self._stage(tmp)
            (dst / "items.json").write_text(
                json.dumps({"version": _current_patch()}), encoding="utf-8"
            )
            with self.assertRaises(SnapshotNotFound):
                DataSnapshot.load(patch=_current_patch(), data_root=tmp)

    def test_scenarios_missing_containers_fails_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            dst = self._stage(tmp)
            (dst / "scenarios.json").write_text(
                json.dumps({"version": _current_patch()}), encoding="utf-8"
            )
            with self.assertRaises(SnapshotNotFound):
                DataSnapshot.load(patch=_current_patch(), data_root=tmp)

    def test_abilities_missing_data_key_fails_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            dst = self._stage(tmp)
            (dst / "champion_abilities.json").write_text(
                json.dumps({"version": _current_patch()}), encoding="utf-8"
            )
            with self.assertRaises(AbilitiesNotFound):
                AbilitiesSnapshot.load(patch=_current_patch(), data_root=tmp)

    def test_enchanter_missing_items_key_fails_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            dst = self._stage(tmp)
            (dst / "enchanter_items.json").write_text(
                json.dumps({"_meta": {}}), encoding="utf-8"
            )
            with self.assertRaises(EnchanterFormulasNotFound):
                EnchanterFormulasSnapshot.load(
                    patch=_current_patch(), data_root=tmp
                )

    def test_healthy_snapshot_still_loads(self) -> None:
        """The hardening must not reject a real, complete snapshot."""
        snap = DataSnapshot.load()
        self.assertGreater(len(snap.champions), 0)
        self.assertGreater(len(snap.items), 0)
        self.assertGreater(len(snap.scenarios_by_id), 0)
        AbilitiesSnapshot.load()
        EnchanterFormulasSnapshot.load()


if __name__ == "__main__":
    unittest.main()
