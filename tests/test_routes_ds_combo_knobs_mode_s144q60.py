"""RM-1330 (part) - /api/ds-combo and /api/ds-knobs refuse an unsupported mode.

Defect (measured 2026-11-01 on the lane base, real DataSnapshot, Caitlyn L11):
  * /api/ds-knobs took ``mode`` verbatim. ``rank_items`` applies NO per-mode
    item filter to a mode outside ``MODE_MAP_ID``, so ``mode=ZZQ`` ranked
    map-illegal items (Ultra Hydra, Void Immolation) above Runaan's Hurricane,
    on the SR resist curve, with ok=true and the label echoed back.
  * /api/ds-combo took ``mode`` verbatim too. ``mode=ZZQ`` scored exactly as SR
    (total_mitigated 278.2 for both) and echoed the label as if it had applied.

Contract pinned here (the RM-1327 routes_ds_sweep discipline):
  * a mode outside SR / ARAM / ARENA / BRAWL is a 400 with a fixed text and the
    supported list, never the caller's value;
  * the engine is not called and nothing is cached for it;
  * a supported mode in any case reaches the engine upper-cased;
  * a blank or absent mode still defaults to SR.

The engine is stubbed (``mod._compute``), so these tests pin the route contract,
not combo / rank numbers. The one real consumer that could send another value
(active_match.js, the combo card) is pinned by
web/js/panels/ds_mode_allowlist_s144q60.test.mjs.
"""
from __future__ import annotations

import json
import unittest

from dashboard import routes_ds_combo as combo
from dashboard import routes_ds_knobs as knobs

_SUPPORTED = ["SR", "ARAM", "ARENA", "BRAWL"]
_MARKER = "zzqmode"


class _Harness:
    def __init__(self, path: str) -> None:
        self.path = path
        self.status: int | None = None
        self.body: bytes = b""

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.status = status
        self.body = body

    def parsed(self) -> dict:
        return json.loads(self.body.decode("utf-8"))


class _ModeContract:
    """The shared contract; each subclass names its route and its stub."""

    mod = None
    url = ""

    def _serve(self, h: _Harness) -> None:
        raise NotImplementedError

    def _do(self, query: str) -> _Harness:
        h = _Harness(f"{self.url}{query}")
        self._serve(h)
        return h

    def test_unknown_mode_is_400_with_fixed_text(self) -> None:
        h = self._do(f"&mode={_MARKER}")
        self.assertEqual(h.status, 400)
        body = h.parsed()
        self.assertIs(body["ok"], False)
        self.assertEqual(body["error"], "unsupported mode")
        self.assertEqual(body["supported"], _SUPPORTED)

    def test_unknown_mode_is_not_echoed(self) -> None:
        raw = self._do(f"&mode={_MARKER}").body.decode("utf-8")
        self.assertNotIn(_MARKER, raw.lower())

    def test_unknown_mode_never_reaches_the_engine(self) -> None:
        self._do(f"&mode={_MARKER}")
        self.assertEqual(self.calls, [])

    def test_unknown_mode_is_not_cached(self) -> None:
        self._do("&mode=URF")
        self.assertEqual(len(self.mod._CACHE), 0)

    def test_lcu_spellings_are_not_aliases(self) -> None:
        # CLASSIC / CHERRY / KIWI miss MODE_MAP_ID, so the engine would run them
        # with no item filter. The consumers fold them first.
        for raw in ("CLASSIC", "CHERRY", "KIWI", "TFT", "CLIENT"):
            with self.subTest(mode=raw):
                self.assertEqual(self._do(f"&mode={raw}").status, 400)
        self.assertEqual(self.calls, [])

    def test_supported_modes_reach_engine_uppercased(self) -> None:
        for raw in ("sr", "Aram", "ARENA", "brawl", " aram "):
            with self.subTest(mode=raw):
                self.mod._reset_caches()
                self.calls.clear()
                h = self._do(f"&mode={raw.replace(' ', '%20')}")
                self.assertEqual(h.status, 200)
                self.assertEqual(self.calls, [raw.strip().upper()])
                self.assertEqual(h.parsed()["mode"], raw.strip().upper())

    def test_blank_and_absent_mode_default_to_sr(self) -> None:
        for query in ("", "&mode=", "&mode=%20"):
            with self.subTest(query=query):
                self.mod._reset_caches()
                self.calls.clear()
                h = self._do(query)
                self.assertEqual(h.status, 200)
                self.assertEqual(self.calls, ["SR"])


class ComboModeTests(_ModeContract, unittest.TestCase):
    mod = combo
    url = "/api/ds-combo?champion=Champ&seq=Q,W"

    def setUp(self) -> None:
        combo._reset_caches()
        self.calls: list[str] = []
        self._orig = combo._compute

        def _fake(champion, level, items, seq, target_armor, target_mr,
                  target_max_hp, target_bonus_hp, mode, runes):
            self.calls.append(mode)
            return {"ok": True, "champion": champion, "mode": mode,
                    "hits": [], "count": 0}

        combo._compute = _fake

    def tearDown(self) -> None:
        combo._compute = self._orig
        combo._reset_caches()

    def _serve(self, h: _Harness) -> None:
        combo._serve_ds_combo(h)

    def test_bad_mode_is_refused_before_the_empty_sequence_reply(self) -> None:
        # seq=, resolves to zero tokens, which is a 200 ok=false empty_sequence.
        # A bad mode is a bad request whatever the sequence holds.
        h = _Harness(f"/api/ds-combo?champion=Champ&seq=,&mode={_MARKER}")
        combo._serve_ds_combo(h)
        self.assertEqual(h.status, 400)
        self.assertEqual(h.parsed()["error"], "unsupported mode")

    def test_missing_seq_still_wins_over_a_bad_mode(self) -> None:
        h = _Harness(f"/api/ds-combo?champion=Champ&mode={_MARKER}")
        combo._serve_ds_combo(h)
        self.assertEqual(h.status, 400)
        self.assertEqual(h.parsed()["error"], "seq param required")


class KnobsModeTests(_ModeContract, unittest.TestCase):
    mod = knobs
    url = "/api/ds-knobs?champion=Champ"

    def setUp(self) -> None:
        knobs._reset_caches()
        self.calls: list[str] = []
        self._orig = knobs._compute

        def _fake(champion, mode, items, level, armor_override, mr_override,
                  budget, fight_length=None):
            self.calls.append(mode)
            return {"ok": True, "champion": champion, "mode": mode,
                    "rows": [], "count": 0}

        knobs._compute = _fake

    def tearDown(self) -> None:
        knobs._compute = self._orig
        knobs._reset_caches()

    def _serve(self, h: _Harness) -> None:
        knobs._serve_ds_knobs(h)

    def test_bad_mode_is_refused_before_the_build_complete_reply(self) -> None:
        from agents.daemon_slayer.rank import DEFAULT_SLOT_COUNT

        items = ",".join(str(3000 + i) for i in range(DEFAULT_SLOT_COUNT))
        h = _Harness(f"{self.url}&items={items}&mode={_MARKER}")
        knobs._serve_ds_knobs(h)
        self.assertEqual(h.status, 400)
        self.assertEqual(h.parsed()["error"], "unsupported mode")


if __name__ == "__main__":
    unittest.main()
