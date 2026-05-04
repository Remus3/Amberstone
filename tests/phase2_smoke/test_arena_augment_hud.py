"""
tests/phase2_smoke/test_arena_augment_hud.py
Augment Vision v2 — HUD reconciliation override semantics (s50).

Verifies the conservative override:
- All HUD slots resolve via _augment_name_map -> overwrite _picked_augments
- Any unresolved slot -> no-op (preserve Haiku list)
- Empty/missing HUD -> no-op
- Vision agrees with Haiku -> source flips to "vision_hud", no list change

Doesn't import the Coach class (which pulls Anthropic + the full BaseCoach
lifecycle). Tests the reconcile method via a thin shim that mirrors its
contract: read slots, resolve, override or skip.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from coaches import arena_coach


class _StubCoach:
    """Minimal stand-in exposing the surface _reconcile_augment_hud uses."""

    def __init__(self, out_path: Path, picked: list[str]):
        self._out = out_path
        self._picked_augments = list(picked)
        # Seed artifact with prior Haiku state.
        out_path.write_text(json.dumps({
            "augments_picked": list(picked),
            "augments_source": "haiku_rec",
        }), encoding="utf-8")

    # Bind the real method so we exercise the shipped code path.
    _reconcile_augment_hud = arena_coach.Coach._reconcile_augment_hud


class ArenaAugmentHudReconcileTests(unittest.TestCase):
    """All assertions go through the real Coach._reconcile_augment_hud."""

    def setUp(self) -> None:
        self._td_obj = tempfile.TemporaryDirectory()
        self._td = Path(self._td_obj.name)
        self._out = self._td / "arena_coaching_data.json"
        # Patch the apiName resolver — independent of cdragon snapshot rotation.
        self._resolver = mock.patch.object(
            arena_coach, "_resolve_augment_apiname",
            side_effect=self._fake_resolver,
        )
        self._resolver.start()

    def tearDown(self) -> None:
        self._resolver.stop()
        self._td_obj.cleanup()

    @staticmethod
    def _fake_resolver(name: str):
        table = {
            "the brutalizer": "TheBrutalizer",
            "thebrutalizer":  "TheBrutalizer",
            "apex inventor":  "ApexInventor",
            "apexinventor":   "ApexInventor",
            "cut down":       "CutDown",
            "cutdown":        "CutDown",
        }
        return table.get((name or "").strip().lower())

    def _read_artifact(self) -> dict:
        return json.loads(self._out.read_text(encoding="utf-8"))

    # ── Happy path: all slots resolve, picks differ from Haiku ────────────
    def test_override_when_all_resolve_and_differs(self) -> None:
        coach = _StubCoach(self._out, picked=["TheBrutalizer"])
        coach._reconcile_augment_hud({"augment_hud_slots": ["The Brutalizer", "Apex Inventor"]})
        self.assertEqual(coach._picked_augments, ["TheBrutalizer", "ApexInventor"])
        art = self._read_artifact()
        self.assertEqual(art["augments_picked"], ["TheBrutalizer", "ApexInventor"])
        self.assertEqual(art["augments_source"], "vision_hud")

    # ── All resolve and matches: source flips, list unchanged ─────────────
    def test_confirm_when_all_resolve_and_matches(self) -> None:
        coach = _StubCoach(self._out, picked=["TheBrutalizer", "CutDown"])
        coach._reconcile_augment_hud({"augment_hud_slots": ["The Brutalizer", "Cut Down"]})
        self.assertEqual(coach._picked_augments, ["TheBrutalizer", "CutDown"])
        art = self._read_artifact()
        self.assertEqual(art["augments_source"], "vision_hud")
        self.assertEqual(art["augments_picked"], ["TheBrutalizer", "CutDown"])

    # ── Partial resolve: no-op, Haiku list preserved ──────────────────────
    def test_partial_resolve_preserves_haiku(self) -> None:
        coach = _StubCoach(self._out, picked=["TheBrutalizer"])
        coach._reconcile_augment_hud(
            {"augment_hud_slots": ["The Brutalizer", "Mystery Augment XYZ"]}
        )
        self.assertEqual(coach._picked_augments, ["TheBrutalizer"])
        art = self._read_artifact()
        self.assertEqual(art["augments_source"], "haiku_rec")
        self.assertEqual(art["augments_picked"], ["TheBrutalizer"])

    # ── Empty HUD: no-op ──────────────────────────────────────────────────
    def test_empty_hud_is_noop(self) -> None:
        coach = _StubCoach(self._out, picked=["TheBrutalizer"])
        coach._reconcile_augment_hud({"augment_hud_slots": []})
        self.assertEqual(coach._picked_augments, ["TheBrutalizer"])
        art = self._read_artifact()
        self.assertEqual(art["augments_source"], "haiku_rec")

    # ── Missing field: no-op ──────────────────────────────────────────────
    def test_missing_field_is_noop(self) -> None:
        coach = _StubCoach(self._out, picked=["TheBrutalizer"])
        coach._reconcile_augment_hud({})
        self.assertEqual(coach._picked_augments, ["TheBrutalizer"])

    # ── Dedupe: vision shows duplicate icons; resolved list dedupes ───────
    def test_dedupes_within_vision_slots(self) -> None:
        coach = _StubCoach(self._out, picked=[])
        coach._reconcile_augment_hud(
            {"augment_hud_slots": ["The Brutalizer", "the brutalizer"]}
        )
        self.assertEqual(coach._picked_augments, ["TheBrutalizer"])

    # ── Player deviation: vision picks differ entirely from Haiku ─────────
    def test_player_deviated_from_haiku(self) -> None:
        coach = _StubCoach(self._out, picked=["CutDown"])
        coach._reconcile_augment_hud({"augment_hud_slots": ["Apex Inventor"]})
        self.assertEqual(coach._picked_augments, ["ApexInventor"])
        art = self._read_artifact()
        self.assertEqual(art["augments_source"], "vision_hud")


if __name__ == "__main__":
    unittest.main()
