"""Item 225 sidecar wire - ammo (charge) gating in mana_sim, OPT-IN.

Mirrors the item-229/230 ``runes=None`` opt-in precedent exactly: the new
``gate_ammo`` flag on ``compute_mana_bounded_combo`` defaults False and is
BYTE-IDENTICAL to the prior (mana-only) behavior when omitted. When True it
layers a per-slot charge ledger sourced from the ``ammo`` bucket of
``data/daemon_slayer/16.11.1/cdragon_spell_stats.json`` (wired through the
``DataSnapshot.cdragon_spell_stats`` sidecar + the ``spell_ammo`` accessor).

Test champs (real ammo data, patch 16.11.1):
  * Vi E ammo {max:[2,2,2,2,2,2,2], recharge:[12,12,11,10,9,8,8]} - mana,
    damage-dealing -> the gate-on-third-cast fixture.
  * Ahri Q ammo == null - a no-ammo MANA champ control.
  * Akali Q ammo == null - the orchestrator's example was wrong (Akali has no
    charges in this snapshot); used here as a None-accessor control.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.mana_sim import compute_mana_bounded_combo

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SPELL_STATS = (
    _REPO_ROOT / "data" / "daemon_slayer" / "16.11.1" / "cdragon_spell_stats.json"
)
_SRC_FILES = (
    _REPO_ROOT / "agents" / "daemon_slayer" / "data_loader.py",
    _REPO_ROOT / "agents" / "daemon_slayer" / "mana_sim.py",
    Path(__file__),
)

_SNAP = DataSnapshot.load()


class SpellAmmoAccessorTests(unittest.TestCase):
    """``DataSnapshot.spell_ammo`` returns the {max, recharge} dict or None."""

    def test_vi_e_returns_ammo_dict(self):
        ammo = _SNAP.spell_ammo("Vi", "E")
        self.assertIsInstance(ammo, dict)
        self.assertEqual(ammo.get("max"), [2, 2, 2, 2, 2, 2, 2])
        self.assertEqual(
            ammo.get("recharge"), [12.0, 12.0, 11.0, 10.0, 9.0, 8.0, 8.0]
        )

    def test_ahri_q_ammo_is_none(self):
        # Ahri Q has no charge model in this snapshot -> None (byte-identical
        # fallback to mana-only gating).
        self.assertIsNone(_SNAP.spell_ammo("Ahri", "Q"))

    def test_akali_q_ammo_is_none(self):
        # Orchestrator's example was wrong: Akali Q carries no ammo bucket.
        self.assertIsNone(_SNAP.spell_ammo("Akali", "Q"))

    def test_unknown_champ_and_slot_return_none(self):
        self.assertIsNone(_SNAP.spell_ammo("NotAChamp", "Q"))
        self.assertIsNone(_SNAP.spell_ammo("Vi", "Z"))
        self.assertIsNone(_SNAP.spell_ammo("Vi", ""))

    def test_accessor_matches_raw_file(self):
        # The accessor must read the same structure the file ships.
        doc = json.loads(_SPELL_STATS.read_text(encoding="utf-8"))
        raw = doc["champions"]["Vi"]["spells"]["E"]["ammo"]
        self.assertEqual(_SNAP.spell_ammo("Vi", "E"), raw)


class DataSnapshotSidecarTests(unittest.TestCase):
    """The optional sidecar maps champ id -> spells -> slot, absent -> {}."""

    def test_loaded_snapshot_has_champions_map(self):
        self.assertIsInstance(_SNAP.cdragon_spell_stats, dict)
        self.assertIn("Vi", _SNAP.cdragon_spell_stats)

    def test_absent_file_yields_empty_dict_byte_identical(self):
        # A snapshot dir with no cdragon_spell_stats.json -> {} (the accessor
        # then returns None for every lookup, byte-identical to no sidecar).
        import tempfile

        real = _REPO_ROOT / "data" / "daemon_slayer" / "16.11.1"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            patch_dir = root / "16.11.1"
            patch_dir.mkdir(parents=True)
            for name in (
                "manifest.json",
                "champions.json",
                "items.json",
                "scenarios.json",
            ):
                (patch_dir / name).write_text(
                    (real / name).read_text(encoding="utf-8"), encoding="utf-8"
                )
            snap = DataSnapshot.load(patch="16.11.1", data_root=root)
            self.assertEqual(snap.cdragon_spell_stats, {})
            self.assertIsNone(snap.spell_ammo("Vi", "E"))


class GateAmmoByteIdenticalTests(unittest.TestCase):
    """gate_ammo omitted == gate_ammo=False == prior (mana-only) behavior."""

    def _run(self, gate_ammo):
        return compute_mana_bounded_combo(
            "Vi",
            11,
            item_ids=[],
            sequence=["E", "E", "E", "E"],
            snapshot=_SNAP,
            gate_ammo=gate_ammo,
        )

    def test_omitted_defaults_to_false(self):
        # No gate_ammo kwarg -> identical to gate_ammo=False.
        baseline = self._run(False)
        omitted = compute_mana_bounded_combo(
            "Vi",
            11,
            item_ids=[],
            sequence=["E", "E", "E", "E"],
            snapshot=_SNAP,
        )
        self.assertEqual(omitted.casts_allowed, baseline.casts_allowed)
        self.assertEqual(omitted.bounded_dps, baseline.bounded_dps)
        self.assertEqual(omitted.unbounded_dps, baseline.unbounded_dps)

    def test_false_path_unchanged_for_ammo_champ(self):
        # Vi E with the gate OFF must fire all 4 casts (no ammo limiting),
        # matching the prior mana-only walk (Vi mana pool is plenty for 4 E).
        r = self._run(False)
        self.assertEqual(r.casts_allowed, 4)
        statuses = [h.status for h in r.hits]
        self.assertEqual(statuses, ["ok", "ok", "ok", "ok"])
        self.assertGreater(r.bounded_dps, 0.0)

    def test_false_bounded_equals_unbounded_no_mana_gate(self):
        # Vi has plenty of mana for 4 E -> bounded == unbounded with gate off.
        r = self._run(False)
        self.assertEqual(r.bounded_dps, r.unbounded_dps)


class GateAmmoGatesThirdCastTests(unittest.TestCase):
    """A tight rotation past the recharge window gets gated on charge depletion."""

    def test_vi_e_third_cast_gated_when_gate_ammo_true(self):
        # Vi E rank0 (level 11): 2 charges, recharge 12s. Casts spaced 1s.
        # cast0 charge 2->1, cast1 charge 1->0, cast2 at t=2 has 0 charges and
        # only 2s elapsed (< 12s) -> gated. cast3 likewise.
        off = compute_mana_bounded_combo(
            "Vi", 11, item_ids=[], sequence=["E", "E", "E", "E"],
            snapshot=_SNAP, gate_ammo=False,
        )
        on = compute_mana_bounded_combo(
            "Vi", 11, item_ids=[], sequence=["E", "E", "E", "E"],
            snapshot=_SNAP, gate_ammo=True,
        )
        self.assertEqual(off.casts_allowed, 4)
        self.assertEqual(on.casts_allowed, 2)
        statuses = [h.status for h in on.hits]
        self.assertEqual(statuses[:2], ["ok", "ok"])
        self.assertIn("no_ammo", statuses[2:])
        # Gated casts deal no damage -> fewer total + lower bounded dps.
        self.assertLess(on.bounded_dps, off.bounded_dps)

    def test_gated_rows_have_no_ammo_status_and_zero_damage(self):
        on = compute_mana_bounded_combo(
            "Vi", 11, item_ids=[], sequence=["E", "E", "E", "E"],
            snapshot=_SNAP, gate_ammo=True,
        )
        no_ammo = [h for h in on.hits if h.status == "no_ammo"]
        self.assertTrue(no_ammo)
        for h in no_ammo:
            self.assertEqual(h.raw, 0.0)
            self.assertEqual(h.mitigated, 0.0)

    def test_single_e_never_gated(self):
        # One E cast must always fire (1 charge available from 2-max pool).
        on = compute_mana_bounded_combo(
            "Vi", 11, item_ids=[], sequence=["E"],
            snapshot=_SNAP, gate_ammo=True,
        )
        self.assertEqual(on.casts_allowed, 1)
        self.assertEqual([h.status for h in on.hits], ["ok"])


class NonAmmoChampUnaffectedTests(unittest.TestCase):
    """A champ whose slots have ammo==null: gate_ammo=True == gate_ammo=False."""

    def test_ahri_q_byte_identical_with_gate_on(self):
        # Ahri Q has no ammo -> charge gate is a no-op; gate on == gate off.
        off = compute_mana_bounded_combo(
            "Ahri", 11, item_ids=[], sequence=["Q", "Q", "Q", "Q"],
            snapshot=_SNAP, gate_ammo=False,
        )
        on = compute_mana_bounded_combo(
            "Ahri", 11, item_ids=[], sequence=["Q", "Q", "Q", "Q"],
            snapshot=_SNAP, gate_ammo=True,
        )
        self.assertEqual(on.casts_allowed, off.casts_allowed)
        self.assertEqual(on.bounded_dps, off.bounded_dps)
        self.assertEqual(on.unbounded_dps, off.unbounded_dps)
        self.assertEqual(
            [h.status for h in on.hits], [h.status for h in off.hits]
        )

    def test_no_no_ammo_status_for_non_ammo_champ(self):
        on = compute_mana_bounded_combo(
            "Ahri", 11, item_ids=[], sequence=["Q", "Q", "Q", "Q"],
            snapshot=_SNAP, gate_ammo=True,
        )
        self.assertNotIn("no_ammo", [h.status for h in on.hits])


class AsciiHygieneTests(unittest.TestCase):
    """The two source files + this test carry zero non-ASCII bytes."""

    def test_files_are_ascii(self):
        for path in _SRC_FILES:
            data = path.read_bytes()
            non_ascii = [b for b in data if b > 0x7F]
            self.assertEqual(
                non_ascii, [], f"non-ASCII byte(s) in {path.name}"
            )


if __name__ == "__main__":
    unittest.main()
