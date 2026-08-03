"""Tests for the /api/ds-relscore FULL-BUILD terminal state (S7 cost sweep,
2026-08-02).

Measured finding: 765 of 823 WARNING lines (93.0 pct) in logs/2026-08-02.log
came from ONE call site, routes_ds_relscore.py:253, rendering
"current_item_ids has {6,7} items; slot_count=6 leaves no room for a new item".

Two distinct defects sit underneath that one message, and they pull in
opposite directions - which is why the log level alone was NOT the fix:

  1. REAL BUG (s156 class, documented core/daemon_slayer_resolver.py:144-151).
     The caller feeds the raw Live-Client inventory, which serializes the
     trinket and consumables inline with shop items (dashboard/_liveclient.py:191
     applies no filter). So 5 real items + a trinket counted as 6 and the route
     refused to rank - going dark in exactly the slot where last-item advice
     matters most. The 7-item variant in the log is the same cause with a full
     build. Demoting the log without fixing this would have BURIED the bug.

  2. EXPECTED STATE. Once the inventory is filtered, a genuine 6-item build is
     a normal terminal outcome, not an engine failure. It was surfacing as a
     503 + WARNING, which no cache would hold (the route caches only on
     success, and the browser at web/js/panels/ds_relscore.js:75 discards a
     non-ok response), so it recomputed and re-logged on every poll forever.

The fix routes the full build through the route's DOCUMENTED terminal shape
(200 / ok=false / reason) so it flows through the EXISTING 300 s success
cache. No negative cache is introduced: the cache key already contains the
filtered item list, so selling an item changes the key and the full-build
entry is never consulted for a different inventory - no stale advice is
reachable.

The catch-all WARNING for genuine compute failures is deliberately preserved
and pinned by GenuineFailureStillWarnsTests.
"""
from __future__ import annotations

import json
import pathlib
import unittest

from dashboard import routes_ds_relscore as rt

_MARKSMAN = "Caitlyn"

# Six legal SR inventory items - a genuinely complete build.
_SIX = ["3031", "3036", "3006", "3072", "3094", "3033"]
# Five of the above, leaving one open slot.
_FIVE = _SIX[:5]
_TRINKET = "3340"       # Stealth Ward - occupies the trinket row, not a slot.
_CONSUMABLE = "2003"    # Health Potion - consumable row, not a slot.


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
    rt._serve_ds_relscore(h)
    return h


def _url(items: list[str]) -> str:
    return f"/api/ds-relscore?champion={_MARKSMAN}&items=" + ",".join(items)


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        rt._reset_caches()


class FullBuildTerminalStateTests(_Base):
    def test_full_build_returns_200_not_503(self) -> None:
        h = _do(_url(_SIX))
        self.assertEqual(h.last_status, 200)

    def test_full_build_reports_ok_false_with_reason(self) -> None:
        payload = _do(_url(_SIX)).parsed()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["reason"], "build_full")

    def test_full_build_keeps_the_documented_terminal_shape(self) -> None:
        payload = _do(_url(_SIX)).parsed()
        for field in ("champion", "target", "rows", "count"):
            self.assertIn(field, payload)
        self.assertEqual(payload["rows"], [])
        self.assertEqual(payload["count"], 0)

    def test_full_build_emits_no_warning(self) -> None:
        with self.assertNoLogs("rc.web_dashboard", level="WARNING"):
            _do(_url(_SIX))


class NonInventoryFilterTests(_Base):
    """The s156 bug: trinkets and consumables must not consume a slot."""

    def test_five_items_plus_trinket_still_ranks(self) -> None:
        payload = _do(_url(_FIVE + [_TRINKET])).parsed()
        self.assertTrue(payload["ok"], f"trinket ate a slot: {payload}")
        self.assertGreater(payload["count"], 0)

    def test_five_items_plus_consumable_still_ranks(self) -> None:
        payload = _do(_url(_FIVE + [_CONSUMABLE])).parsed()
        self.assertTrue(payload["ok"], f"consumable ate a slot: {payload}")

    def test_six_items_plus_trinket_is_full_not_an_error(self) -> None:
        h = _do(_url(_SIX + [_TRINKET]))
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.parsed()["reason"], "build_full")

    def test_trinket_is_not_part_of_the_cache_key(self) -> None:
        _do(_url(_FIVE))
        h = _do(_url(_FIVE + [_TRINKET]))
        self.assertTrue(h.parsed()["cached"])

    def test_filtered_items_do_not_reach_the_ranker(self) -> None:
        seen: dict = {}
        import agents.daemon_slayer.rank as rank_mod
        real = rank_mod.rank_items

        def _spy(snapshot, **kw):
            seen["items"] = list(kw.get("current_item_ids") or [])
            return real(snapshot, **kw)

        rank_mod.rank_items = _spy
        try:
            _do(_url(_FIVE + [_TRINKET, _CONSUMABLE]))
        finally:
            rank_mod.rank_items = real
        self.assertNotIn(_TRINKET, seen.get("items", []))
        self.assertNotIn(_CONSUMABLE, seen.get("items", []))


class FullBuildCacheTests(_Base):
    """The whole point of the fix: the 300 s TTL must actually apply."""

    def test_full_build_result_is_cached(self) -> None:
        self.assertFalse(_do(_url(_SIX)).parsed()["cached"])
        self.assertTrue(_do(_url(_SIX)).parsed()["cached"])

    def test_full_build_does_not_recompute_per_poll(self) -> None:
        calls = {"n": 0}
        real = rt._compute

        def _counting(*a, **kw):
            calls["n"] += 1
            return real(*a, **kw)

        rt._compute = _counting
        try:
            for _ in range(5):
                _do(_url(_SIX))
        finally:
            rt._compute = real
        self.assertEqual(calls["n"], 1)

    def test_selling_an_item_is_not_served_the_full_build_answer(self) -> None:
        # Staleness proof: the sold-item inventory is a DIFFERENT cache key,
        # so the cached terminal answer can never be served as live advice.
        self.assertEqual(_do(_url(_SIX)).parsed()["reason"], "build_full")
        payload = _do(_url(_FIVE)).parsed()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["cached"])


class GenuineFailureStillWarnsTests(_Base):
    """A real engine fault must keep its WARNING - the demotion is scoped."""

    def test_unexpected_exception_still_returns_503_and_warns(self) -> None:
        import agents.daemon_slayer.rank as rank_mod
        real = rank_mod.rank_items

        def _boom(*a, **kw):
            raise RuntimeError("engine exploded")

        rank_mod.rank_items = _boom
        try:
            with self.assertLogs("rc.web_dashboard", level="WARNING") as cap:
                h = _do(f"/api/ds-relscore?champion={_MARKSMAN}")
        finally:
            rank_mod.rank_items = real
        self.assertEqual(h.last_status, 503)
        self.assertTrue(any("engine exploded" in m for m in cap.output))

    def test_failure_is_not_cached(self) -> None:
        import agents.daemon_slayer.rank as rank_mod
        real = rank_mod.rank_items

        def _boom(*a, **kw):
            raise RuntimeError("transient blip")

        rank_mod.rank_items = _boom
        try:
            _do(f"/api/ds-relscore?champion={_MARKSMAN}")
        finally:
            rank_mod.rank_items = real
        # Recovery must be immediate, not pinned for the 300 s TTL.
        payload = _do(f"/api/ds-relscore?champion={_MARKSMAN}").parsed()
        self.assertTrue(payload["ok"])


class AsciiHygieneTests(unittest.TestCase):
    def _assert_ascii(self, path: pathlib.Path) -> None:
        src = path.read_bytes()
        bad = [(i, b) for i, b in enumerate(src) if b > 0x7F]
        self.assertEqual(bad, [], f"non-ASCII in {path.name}: {bad[:5]}")

    def test_route_module_is_ascii(self) -> None:
        self._assert_ascii(pathlib.Path(rt.__file__))

    def test_this_test_file_is_ascii(self) -> None:
        self._assert_ascii(pathlib.Path(__file__))


if __name__ == "__main__":
    unittest.main()
