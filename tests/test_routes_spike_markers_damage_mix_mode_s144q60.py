"""RM-1330 (part) - /api/spike-markers and /api/damage-mix refuse an unsupported mode.

Defect (measured 2026-11-01 on the lane base, real DataSnapshot, in process, with
items 3031 + 3071 + 3089):
  * /api/damage-mix: ZZQ, CLASSIC, URF, KIWI, CHERRY and TFT each differed from
    SR in mix on 117 of 173 champions (L11) and in total_dps on 147, with ok=true
    under the caller's label; the mix moved by a point or more on 82. Example:
    Garen's true-damage share was 0.0208 under SR and 0.0338 under ZZQ. The route
    also kept the caller's case, so mode=aram was answered under the label "aram".
  * /api/spike-markers: ZZQ and CLASSIC equalled SR on all 173 champions (L8), so
    the mode only reached the engine and the cache key, with ok=true.

Contract pinned here (the RM-1327 routes_ds_sweep discipline):
  * a mode outside SR / ARAM / ARENA / BRAWL is a 400 with a fixed text and the
    supported list, never the caller's value;
  * the engine is not called for it;
  * a missing required parameter still wins over a bad mode, and on /api/damage-mix
    so does a bad level (/api/spike-markers never refuses a level);
  * a supported mode in any case reaches the engine upper-cased;
  * a blank or absent mode still defaults to SR.

The engines are stubbed, so these tests pin the route contract, not the numbers.
What the consumers send is pinned by running them, in
web/js/panels/ds_mode_allowlist_s144q60.test.mjs.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from dashboard import routes_damage_mix as damage_mix
from dashboard import routes_spike_markers as spike_markers

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

    url = ""

    def _serve(self, h: _Harness) -> None:
        raise NotImplementedError

    def _reset(self) -> None:
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

    def test_lcu_spellings_are_not_aliases(self) -> None:
        for raw in ("CLASSIC", "CHERRY", "KIWI", "TFT", "CLIENT"):
            with self.subTest(mode=raw):
                self.assertEqual(self._do(f"&mode={raw}").status, 400)
        self.assertEqual(self.calls, [])

    def test_supported_modes_reach_the_engine_uppercased(self) -> None:
        for raw in ("sr", "Aram", "ARENA", "brawl", " aram "):
            with self.subTest(mode=raw):
                self._reset()
                self.calls.clear()
                h = self._do(f"&mode={raw.replace(' ', '%20')}")
                self.assertEqual(h.status, 200)
                self.assertEqual(self.calls, [raw.strip().upper()])

    def test_blank_and_absent_mode_default_to_sr(self) -> None:
        for query in ("", "&mode=", "&mode=%20"):
            with self.subTest(query=query):
                self._reset()
                self.calls.clear()
                h = self._do(query)
                self.assertEqual(h.status, 200)
                self.assertEqual(self.calls, ["SR"])


class SpikeMarkersModeTests(_ModeContract, unittest.TestCase):
    url = "/api/spike-markers?champion=Aatrox&level=8"

    def setUp(self) -> None:
        spike_markers._reset_caches()
        self.calls: list[str] = []

        def _fake(champion, level, items, mode, item_count, minor):
            self.calls.append(mode)
            return {"ok": True, "champion": champion, "level": level,
                    "item_count_done": 0,
                    "markers": [{"kind": "level", "threshold": 6}],
                    "next": None, "count": 1}

        patcher = mock.patch.object(spike_markers, "_compute", _fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(spike_markers._reset_caches)

    def _serve(self, h: _Harness) -> None:
        spike_markers._serve_spike_markers(h)

    def _reset(self) -> None:
        spike_markers._reset_caches()

    def test_unknown_mode_is_not_cached(self) -> None:
        self._do("&mode=URF")
        self.assertEqual(len(spike_markers._CACHE), 0)

    def test_only_a_supported_mode_resolves_the_champion(self) -> None:
        with mock.patch("core.archetype_picks.canonical_champion_id",
                        return_value="Aatrox") as resolve:
            self._do(f"&mode={_MARKER}")
            resolve.assert_not_called()
            self._do("&mode=SR")
            resolve.assert_called_once_with("Aatrox")

    def test_missing_champion_still_wins_over_a_bad_mode(self) -> None:
        for path in (f"/api/spike-markers?mode={_MARKER}",
                     f"/api/spike-markers?champion=%20&mode={_MARKER}"):
            with self.subTest(path=path):
                h = _Harness(path)
                spike_markers._serve_spike_markers(h)
                self.assertEqual(h.status, 400)
                self.assertEqual(h.parsed()["error"], "champion param required")


class _FakeMix:
    champ_id = "Garen"
    items = ("3074",)

    def __init__(self, mode: str) -> None:
        self.mode = mode

    def to_dict(self) -> dict:
        return {"champ_id": self.champ_id, "mode": self.mode}


class DamageMixModeTests(_ModeContract, unittest.TestCase):
    url = "/api/damage-mix?champ_id=Garen&items=3074"

    def setUp(self) -> None:
        self.calls: list[str] = []
        self.snapshot_loads = 0

        def _fake(snapshot, champ, items, level=11, mode="SR"):
            self.calls.append(mode)
            return _FakeMix(mode), False

        def _fake_snapshot():
            self.snapshot_loads += 1

        for patcher in (
            mock.patch("core.damage_mix.compute_damage_mix", _fake),
            mock.patch.object(damage_mix, "_get_snapshot", _fake_snapshot),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _serve(self, h: _Harness) -> None:
        damage_mix._serve_damage_mix(h)

    def _reset(self) -> None:
        """The route holds no response cache; the engine's is stubbed out."""

    def test_unknown_mode_never_loads_the_snapshot(self) -> None:
        self._do(f"&mode={_MARKER}")
        self.assertEqual(self.snapshot_loads, 0)

    def test_supported_mode_is_labelled_uppercased(self) -> None:
        self.assertEqual(self._do("&mode=aram").parsed()["mode"], "ARAM")

    def test_required_params_and_level_still_win_over_a_bad_mode(self) -> None:
        cases = (
            (f"/api/damage-mix?items=3074&mode={_MARKER}", "champ_id_required"),
            (f"/api/damage-mix?champ_id=Garen&mode={_MARKER}", "items_required"),
            (f"/api/damage-mix?champ_id=Garen&items=3074&level=99&mode={_MARKER}",
             "level_out_of_range:99"),
        )
        for path, error in cases:
            with self.subTest(path=path):
                h = _Harness(path)
                damage_mix._serve_damage_mix(h)
                self.assertEqual(h.status, 400)
                self.assertEqual(h.parsed()["error"], error)


if __name__ == "__main__":
    unittest.main()
