"""Tests for the fight-length-reweight knob on GET /api/ds-knobs (item 219 C).

HTTP-contract for the new &fight_length knob via the StubHandler pattern (no
live server, mirrors test_routes_ds_knobs.py): the knob is parsed, echoed in
the knobs dict, included in the cache key, and omitting it matches the prior
(no-reweight) response. Plus a panel DOM grep guard for the new input.

These tests load the live DataSnapshot - patch-stable assertions only (no
hardcoded item names / dps numbers); we assert on STRUCTURE + the reweight
DELTA vs the default ranking.
"""
from __future__ import annotations

import json
import pathlib
import unittest

from dashboard import routes_ds_knobs as rt

_MARKSMAN = "Caitlyn"   # ranged marksman; deep candidate pool re-weights well


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
    rt._serve_ds_knobs(h)
    return h


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        rt._reset_caches()


# ---------------------------------------------------------------------------
# Knob parsing + echo
# ---------------------------------------------------------------------------


class KnobEchoTests(_Base):
    def test_fight_length_echoed(self) -> None:
        h = _do(f"/api/ds-knobs?champion={_MARKSMAN}&fight_length=3")
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["knobs"]["fight_length"], 3.0)

    def test_fight_length_absent_is_null(self) -> None:
        h = _do(f"/api/ds-knobs?champion={_MARKSMAN}")
        self.assertTrue(h.parsed()["ok"])
        self.assertIsNone(h.parsed()["knobs"]["fight_length"])

    def test_fight_length_blank_is_null(self) -> None:
        h = _do(f"/api/ds-knobs?champion={_MARKSMAN}&fight_length=")
        self.assertIsNone(h.parsed()["knobs"]["fight_length"])

    def test_fight_length_non_positive_normalized_to_null(self) -> None:
        h0 = _do(f"/api/ds-knobs?champion={_MARKSMAN}&fight_length=0")
        self.assertIsNone(h0.parsed()["knobs"]["fight_length"])
        hn = _do(f"/api/ds-knobs?champion={_MARKSMAN}&fight_length=-5")
        self.assertIsNone(hn.parsed()["knobs"]["fight_length"])

    def test_fight_length_invalid_is_null(self) -> None:
        h = _do(f"/api/ds-knobs?champion={_MARKSMAN}&fight_length=abc")
        self.assertIsNone(h.parsed()["knobs"]["fight_length"])

    def test_row_carries_effective_score(self) -> None:
        h = _do(f"/api/ds-knobs?champion={_MARKSMAN}&fight_length=5")
        row = h.parsed()["rows"][0]
        self.assertIn("effective_score", row)


# ---------------------------------------------------------------------------
# Cache key includes fight_length
# ---------------------------------------------------------------------------


class CacheKeyTests(_Base):
    def test_cache_key_includes_fight_length(self) -> None:
        k_none = rt._cache_key("Caitlyn", "SR", [], 100.0, None, None, 11, None)
        k_fl = rt._cache_key("Caitlyn", "SR", [], 100.0, None, None, 11, 3.0)
        self.assertNotEqual(k_none, k_fl)

    def test_cache_key_default_arg_matches_explicit_none(self) -> None:
        k_default = rt._cache_key("Caitlyn", "SR", [], 100.0, None, None, 11)
        k_explicit = rt._cache_key("Caitlyn", "SR", [], 100.0, None, None, 11, None)
        self.assertEqual(k_default, k_explicit)

    def test_same_fight_length_is_cache_hit(self) -> None:
        h1 = _do(f"/api/ds-knobs?champion={_MARKSMAN}&target_armor=100&fight_length=3")
        self.assertFalse(h1.parsed()["cached"])
        h2 = _do(f"/api/ds-knobs?champion={_MARKSMAN}&target_armor=100&fight_length=3")
        self.assertTrue(h2.parsed()["cached"])

    def test_different_fight_length_is_not_cache_hit(self) -> None:
        _do(f"/api/ds-knobs?champion={_MARKSMAN}&target_armor=100&fight_length=2")
        h = _do(f"/api/ds-knobs?champion={_MARKSMAN}&target_armor=100&fight_length=20")
        self.assertFalse(h.parsed()["cached"])


# ---------------------------------------------------------------------------
# Omitting fight_length matches the prior (no-reweight) response
# ---------------------------------------------------------------------------


class NoReweightParityTests(_Base):
    def test_omit_matches_explicit_zero(self) -> None:
        b_omit = _do(f"/api/ds-knobs?champion={_MARKSMAN}&target_armor=100").parsed()
        rt._reset_caches()
        b_zero = _do(
            f"/api/ds-knobs?champion={_MARKSMAN}&target_armor=100&fight_length=0"
        ).parsed()
        self.assertTrue(b_omit["ok"] and b_zero["ok"])
        self.assertEqual(
            [r["item_id"] for r in b_omit["rows"]],
            [r["item_id"] for r in b_zero["rows"]],
        )
        # Default path leaves effective_score at 0.0 in serialized rows.
        self.assertTrue(all(r["effective_score"] == 0.0 for r in b_omit["rows"]))

    def test_positive_fight_length_changes_ranking_vs_omit(self) -> None:
        b_omit = _do(f"/api/ds-knobs?champion={_MARKSMAN}&target_armor=100").parsed()
        rt._reset_caches()
        b_fl = _do(
            f"/api/ds-knobs?champion={_MARKSMAN}&target_armor=100&fight_length=2"
        ).parsed()
        self.assertTrue(b_omit["ok"] and b_fl["ok"])
        self.assertNotEqual(
            [r["item_id"] for r in b_omit["rows"]],
            [r["item_id"] for r in b_fl["rows"]],
        )


# ---------------------------------------------------------------------------
# Panel DOM grep guard (ds_knobs.js) for the new input
# ---------------------------------------------------------------------------


class PanelDomTests(unittest.TestCase):
    def setUp(self) -> None:
        self.src = (
            pathlib.Path(__file__).resolve().parents[1]
            / "web" / "js" / "panels" / "ds_knobs.js"
        ).read_text(encoding="utf-8")

    def test_panel_has_fight_length_input(self) -> None:
        self.assertIn('id="dsk-fight-length"', self.src)
        self.assertIn("fight_length", self.src)
        self.assertIn("Fight length", self.src)

    def test_panel_still_has_three_original_knobs(self) -> None:
        for token in ('id="dsk-armor"', 'id="dsk-mr"', 'id="dsk-budget"'):
            self.assertIn(token, self.src)

    def test_panel_ascii_hygiene(self) -> None:
        bad = [b for b in self.src.encode("utf-8", "surrogatepass") if b > 0x7F]
        self.assertEqual(bad, [], "non-ASCII byte in ds_knobs.js")


if __name__ == "__main__":
    unittest.main()
