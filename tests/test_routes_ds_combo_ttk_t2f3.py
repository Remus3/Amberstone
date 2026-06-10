"""T2-F3 (docs/COMPETITOR_LIFT_2026-06-08.md lines 114-121) - headline
time-to-kill line on the ds_combo totals.

simulator tool R surfaces a sustained DPS + time-to-kill headline against a
defended target; RC's combo route already returns the per-hit timeline +
``totals`` (total_raw / total_mitigated / duration_s) but never the
derived TTK scalar. This slice adds an ADDITIVE ``ttk`` block to the
/api/ds-combo response (target effective HP vs the combo's mitigated
total / DPS). The existing ``totals`` block and every existing field stay
BYTE-IDENTICAL; the new block is purely derived.

These tests pin: ttk present + shape, the derived-quantity closed forms
(rotations = ceil(target_hp / combo_mitigated), dps = mitigated /
duration, ttk_s = target_hp / dps), the lethal flag, and the
unavailable-when-no-target-HP fail-soft.
"""
from __future__ import annotations

import json
import math
import unittest

from dashboard import routes_ds_combo as rt


class StubHandler:
    def __init__(self, path: str = ""):
        self.path = path
        self.last_status: int | None = None
        self.last_body: bytes | None = None
        self.last_ct: str | None = None

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.last_status = status
        self.last_body = body
        self.last_ct = content_type

    def parsed(self) -> dict:
        if not self.last_body:
            return {}
        return json.loads(self.last_body.decode("utf-8"))


def _do(path: str) -> StubHandler:
    h = StubHandler(path=path)
    rt._serve_ds_combo(h)
    return h


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        rt._reset_caches()


class TtkPresenceTests(_Base):
    def test_totals_block_unchanged_keys(self) -> None:
        # The pre-existing totals contract must keep exactly its three keys.
        body = _do(
            "/api/ds-combo?champion=Lux&seq=Q,AA,W,E,R"
            "&target_armor=80&target_mr=60&target_max_hp=2000"
        ).parsed()
        tot = body["totals"]
        self.assertEqual(
            set(tot.keys()), {"total_raw", "total_mitigated", "duration_s"}
        )

    def test_ttk_block_present_and_shape(self) -> None:
        body = _do(
            "/api/ds-combo?champion=Lux&seq=Q,AA,W,E,R"
            "&target_armor=80&target_mr=60&target_max_hp=2000"
        ).parsed()
        self.assertIn("ttk", body)
        ttk = body["ttk"]
        for k in (
            "available", "target_hp", "combo_mitigated", "dps",
            "rotations_to_kill", "ttk_s", "lethal",
        ):
            self.assertIn(k, ttk)


class TtkClosedFormTests(_Base):
    def test_derived_quantities_match_totals(self) -> None:
        body = _do(
            "/api/ds-combo?champion=Caitlyn&seq=Q,AA,W,E,R,AA"
            "&target_armor=60&target_mr=40&target_max_hp=2500"
        ).parsed()
        tot = body["totals"]
        ttk = body["ttk"]
        self.assertTrue(ttk["available"])
        self.assertEqual(ttk["target_hp"], 2500.0)
        self.assertAlmostEqual(ttk["combo_mitigated"], tot["total_mitigated"], places=3)
        # dps = mitigated / duration. ttk.dps is the unrounded ratio rounded
        # to 0.1 for display; recomputing from the already-rounded totals
        # drifts by < 0.1, so compare within the display tolerance.
        self.assertAlmostEqual(
            ttk["dps"], tot["total_mitigated"] / tot["duration_s"], delta=0.1
        )
        # rotations = ceil(target_hp / combo_mitigated)
        self.assertEqual(
            ttk["rotations_to_kill"],
            math.ceil(2500.0 / tot["total_mitigated"]),
        )
        # ttk_s = target_hp / dps (within the display rounding tolerance).
        self.assertAlmostEqual(
            ttk["ttk_s"], 2500.0 / ttk["dps"], delta=0.05
        )

    def test_lethal_flag_true_when_one_rotation_kills(self) -> None:
        # Tiny target HP -> a single combo rotation is lethal.
        body = _do(
            "/api/ds-combo?champion=Lux&seq=Q,AA,W,E,R"
            "&target_armor=0&target_mr=0&target_max_hp=50"
        ).parsed()
        ttk = body["ttk"]
        self.assertTrue(ttk["available"])
        self.assertTrue(ttk["lethal"])
        self.assertEqual(ttk["rotations_to_kill"], 1)

    def test_lethal_flag_false_when_multiple_rotations(self) -> None:
        body = _do(
            "/api/ds-combo?champion=Lux&seq=Q,AA,W,E,R"
            "&target_armor=120&target_mr=120&target_max_hp=6000"
        ).parsed()
        ttk = body["ttk"]
        self.assertTrue(ttk["available"])
        self.assertFalse(ttk["lethal"])
        self.assertGreater(ttk["rotations_to_kill"], 1)


class TtkUnavailableTests(_Base):
    def test_no_target_hp_marks_unavailable(self) -> None:
        # Without target_max_hp the TTK is undefined -> available False,
        # numeric fields null/0, but the block still present (stable shape).
        body = _do(
            "/api/ds-combo?champion=Lux&seq=Q,AA,W,E,R&target_armor=80"
        ).parsed()
        ttk = body["ttk"]
        self.assertFalse(ttk["available"])
        self.assertIsNone(ttk["ttk_s"])
        self.assertIsNone(ttk["rotations_to_kill"])
        self.assertFalse(ttk["lethal"])

    def test_empty_sequence_has_no_ttk_or_unavailable(self) -> None:
        # An empty-sequence response is the early-out path; if a ttk block is
        # emitted there it must be unavailable (no combo damage).
        body = _do("/api/ds-combo?champion=Lux&seq=,,").parsed()
        self.assertFalse(body["ok"])
        if "ttk" in body:
            self.assertFalse(body["ttk"]["available"])

    def test_zero_damage_combo_unavailable(self) -> None:
        # Unknown champ -> empty hits -> zero mitigated -> ttk unavailable.
        body = _do(
            "/api/ds-combo?champion=NotAChamp&seq=Q,AA&target_max_hp=2000"
        ).parsed()
        self.assertTrue(body["ok"])
        self.assertIn("ttk", body)
        self.assertFalse(body["ttk"]["available"])


class AsciiHygieneTests(unittest.TestCase):
    def test_this_test_file_is_ascii(self) -> None:
        import pathlib
        src = pathlib.Path(__file__).read_bytes()
        bad = [(i, b) for i, b in enumerate(src) if b > 0x7F]
        self.assertEqual(bad, [], f"non-ASCII: {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
