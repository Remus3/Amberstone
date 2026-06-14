"""Phase 8 step 2 - engine-backed 3-profile generator.

The integration test against a live engine on :8893 lives at the bottom
and skips when the engine isn't reachable (mirrors phase2_smoke
patterns). The unit tests stub urllib so they're fast and deterministic.
"""
import json
import sys
import unittest
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from coaches import sr_draft_profile
from coaches.sr_draft_profile import (
    _normalize_role,
    _profile_from_beam,
    _split_skeleton,
    _team_sig,
    build_profile,
    clear_cache,
)


# Canonical fake beam response - mirrors the live engine shape we just probed.
_FAKE_BEAM = {
    "champion_id": "Tristana",
    "champion_name": "Tristana",
    "engine_version": "0.9.3",
    "ranked": [
        {
            "item_ids": ["3031", "3036", "3085", "3033", "6672", "3032"],
            "item_names": [
                "Infinity Edge", "Lord Dominik's Regards", "Runaan's Hurricane",
                "Mortal Reminder", "Kraken Slayer", "Yun Tal Wildarrows",
            ],
            "total_gold": 18550,
            "final_dps": 814.86,
            "baseline_dps": 37.01,
            "delta_dps": 777.85,
            "dps_per_1k_gold": 41.93,
        }
    ],
}


def _fake_urlopen(resp_body: dict | bytes, code: int = 200):
    """Return a context-manager-compatible stub for urllib.request.urlopen."""
    if isinstance(resp_body, dict):
        payload = json.dumps(resp_body).encode("utf-8")
    else:
        payload = resp_body
    class _Resp:
        def read(self_inner):
            return payload
        def __enter__(self_inner):
            return self_inner
        def __exit__(self_inner, *args):
            return False
    return _Resp()


class TestRoleNormalize(unittest.TestCase):
    def test_canonical_passthrough(self):
        for r in ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"):
            self.assertEqual(_normalize_role(r), r)

    def test_aliases(self):
        self.assertEqual(_normalize_role("MID"), "MIDDLE")
        self.assertEqual(_normalize_role("BOT"), "BOTTOM")
        self.assertEqual(_normalize_role("ADC"), "BOTTOM")
        self.assertEqual(_normalize_role("SUPPORT"), "UTILITY")
        self.assertEqual(_normalize_role("sup"), "UTILITY")
        self.assertEqual(_normalize_role("jg"), "JUNGLE")

    def test_unknown_returns_none(self):
        self.assertIsNone(_normalize_role(""))
        self.assertIsNone(_normalize_role("FILL"))
        self.assertIsNone(_normalize_role(None))
        self.assertIsNone(_normalize_role(42))  # type: ignore[arg-type]


class TestTeamSig(unittest.TestCase):
    def test_order_invariant(self):
        a = [{"championId": 18, "cellId": 0}, {"championId": 222, "cellId": 1}]
        b = [{"championId": 222, "cellId": 1}, {"championId": 18, "cellId": 0}]
        self.assertEqual(_team_sig(a), _team_sig(b))

    def test_skip_garbage(self):
        a = [{"championId": 18}, "not a dict", {}, {"championId": 0}]  # type: ignore[list-item]
        # Zero IDs (unpicked) drop too.
        self.assertEqual(_team_sig(a), (18,))

    def test_none(self):
        self.assertEqual(_team_sig(None), ())


class TestSplitSkeleton(unittest.TestCase):
    def test_canonical_2_2_2_split(self):
        names = ["A", "B", "C", "D", "E", "F"]
        ids   = ["1", "2", "3", "4", "5", "6"]
        presets = {"skeleton_split": {"start": [0, 2], "core": [2, 4], "final": [4, 6]}}
        out = _split_skeleton(names, ids, presets)
        self.assertEqual([x["name"] for x in out["start"]], ["A", "B"])
        self.assertEqual([x["name"] for x in out["core"]],  ["C", "D"])
        self.assertEqual([x["name"] for x in out["final"]], ["E", "F"])
        self.assertEqual(out["start"][0]["id"], "1")

    def test_short_build(self):
        # If beam returns <6 items, slices clip naturally - no crash.
        out = _split_skeleton(["A", "B", "C"], ["1", "2", "3"],
                              {"skeleton_split": {"start": [0, 2], "core": [2, 4], "final": [4, 6]}})
        self.assertEqual(len(out["start"]), 2)
        self.assertEqual(len(out["core"]), 1)
        self.assertEqual(len(out["final"]), 0)


class TestProfileFromBeam(unittest.TestCase):
    def setUp(self):
        self.presets = {
            "rune_defaults_by_role": {
                "BOTTOM": {"primary": "Press the Attack", "alt": "Lethal Tempo", "experimental": "Fleet Footwork"},
            },
            "tree_by_keystone": {
                "Press the Attack": {"primary": "Precision", "secondary": "Domination"},
            },
            "spells_by_role": {"BOTTOM": [4, 7], "_unknown": [4, 14]},
            "skeleton_split": {"start": [0, 2], "core": [2, 4], "final": [4, 6]},
        }
        self.preset = {"label": "Primary", "description": "Balanced",
                       "phase": None, "level": 11, "target_armor": 80, "target_mr": 50}

    def test_canonical_mapping(self):
        out = _profile_from_beam(
            champion="Tristana", role="BOTTOM", kind="primary",
            preset=self.preset, beam_resp=_FAKE_BEAM, presets=self.presets,
        )
        self.assertIsNotNone(out)
        self.assertEqual(out["kind"], "engine")
        self.assertEqual(out["key"], "primary")
        self.assertEqual(out["label"], "Primary")
        self.assertEqual(out["keystone"], "Press the Attack")
        self.assertEqual(out["runes"]["primary"], "Precision")
        self.assertEqual(out["summoner_spells"], [4, 7])
        self.assertEqual(out["item_ids"][0], "3031")
        self.assertEqual(out["item_skeleton"]["start"][0]["name"], "Infinity Edge")
        self.assertEqual(out["engine"]["final_dps"], 814.86)
        self.assertEqual(out["engine"]["phase"], None)

    def test_alt_kind_picks_alt_keystone(self):
        out = _profile_from_beam(
            champion="Tristana", role="BOTTOM", kind="alt",
            preset={**self.preset, "label": "Alt"}, beam_resp=_FAKE_BEAM, presets=self.presets,
        )
        self.assertEqual(out["keystone"], "Lethal Tempo")

    def test_unknown_role_falls_back_to_bottom(self):
        out = _profile_from_beam(
            champion="Tristana", role=None, kind="primary",
            preset=self.preset, beam_resp=_FAKE_BEAM, presets=self.presets,
        )
        # Falls back to BOTTOM defaults
        self.assertEqual(out["keystone"], "Press the Attack")

    def test_empty_ranked_returns_none(self):
        out = _profile_from_beam(
            champion="Tristana", role="BOTTOM", kind="primary",
            preset=self.preset, beam_resp={"ranked": []}, presets=self.presets,
        )
        self.assertIsNone(out)


class TestBuildProfileWithStubbedEngine(unittest.TestCase):
    def setUp(self):
        clear_cache()

    def test_three_profiles_returned(self):
        with mock.patch.object(sr_draft_profile.urllib.request, "urlopen",
                               return_value=_fake_urlopen(_FAKE_BEAM)):
            out = build_profile(
                champion="Tristana", role="BOTTOM",
                my_team=[], their_team=[], queue_id=420,
            )
        self.assertEqual(len(out["profiles"]), 3)
        self.assertEqual(out["engine_version"], "0.9.3")
        self.assertTrue(out["sr_draft"])
        # Each profile differentiates on keystone (different "kind").
        keystones = {p["keystone"] for p in out["profiles"]}
        self.assertEqual(keystones, {"Press the Attack", "Lethal Tempo", "Fleet Footwork"})
        # All flagged as engine.
        for p in out["profiles"]:
            self.assertEqual(p["kind"], "engine")
        # Order preserved primary->alt->experimental.
        self.assertEqual([p["key"] for p in out["profiles"]],
                         ["primary", "alt", "experimental"])

    def test_engine_unreachable(self):
        # Simulate URLError -> empty profiles + notes entry.
        with mock.patch.object(sr_draft_profile.urllib.request, "urlopen",
                               side_effect=urllib.error.URLError("connection refused")):
            out = build_profile(
                champion="Yuumi", role="UTILITY",
                my_team=None, their_team=None, queue_id=420,
            )
        self.assertEqual(out["profiles"], [])
        self.assertIsNone(out["engine_version"])
        self.assertEqual(len(out["notes"]), 3)  # one per preset
        self.assertTrue(all("unreachable" in n for n in out["notes"]))

    def test_engine_http_error_per_preset(self):
        err = urllib.error.HTTPError(
            "http://x", 422, "value error", {},  # type: ignore[arg-type]
            BytesIO(b'{"error":"bad level"}'),
        )
        with mock.patch.object(sr_draft_profile.urllib.request, "urlopen",
                               side_effect=err):
            out = build_profile(
                champion="Sett", role="TOP",
                my_team=None, their_team=None, queue_id=420,
            )
        self.assertEqual(out["profiles"], [])
        self.assertTrue(any("422" in n for n in out["notes"]))

    def test_cache_hit_does_not_re_call(self):
        call_count = {"n": 0}
        def _open(req, **kwargs):
            call_count["n"] += 1
            return _fake_urlopen(_FAKE_BEAM)
        with mock.patch.object(sr_draft_profile.urllib.request, "urlopen",
                               side_effect=_open):
            build_profile(champion="Tristana", role="BOTTOM",
                          my_team=[], their_team=[], queue_id=420)
            first_calls = call_count["n"]
            build_profile(champion="Tristana", role="BOTTOM",
                          my_team=[], their_team=[], queue_id=420)
        # First call: 3 beams. Second call: 0 (served from cache).
        self.assertEqual(first_calls, 3)
        self.assertEqual(call_count["n"], 3)

    def test_cache_miss_on_team_change(self):
        call_count = {"n": 0}
        def _open(req, **kwargs):
            call_count["n"] += 1
            return _fake_urlopen(_FAKE_BEAM)
        with mock.patch.object(sr_draft_profile.urllib.request, "urlopen",
                               side_effect=_open):
            build_profile(champion="Tristana", role="BOTTOM",
                          my_team=[{"championId": 18}], their_team=[], queue_id=420)
            build_profile(champion="Tristana", role="BOTTOM",
                          my_team=[{"championId": 99}], their_team=[], queue_id=420)
        # Different ally sig -> second call hits engine again.
        self.assertEqual(call_count["n"], 6)


class TestLiveEngineIntegration(unittest.TestCase):
    """Integration with the engine on :8893. Skips if engine is down."""

    def setUp(self):
        clear_cache()
        try:
            with urllib.request.urlopen("http://127.0.0.1:8893/health", timeout=1) as r:
                json.loads(r.read())
        except Exception:
            self.skipTest("engine on :8893 unreachable - skipping live integration")

    def test_live_three_profiles(self):
        from agents.daemon_slayer import ENGINE_VERSION
        out = build_profile(
            champion="Tristana", role="BOTTOM",
            my_team=[], their_team=[], queue_id=420,
        )
        self.assertEqual(len(out["profiles"]), 3,
                         f"expected 3 profiles, got notes={out.get('notes')}")
        self.assertEqual(out["engine_version"], ENGINE_VERSION)
        for p in out["profiles"]:
            self.assertGreater(len(p["build_path"]), 0)
            self.assertGreater(len(p["item_ids"]), 0)
            self.assertIn(p["keystone"],
                          {"Press the Attack", "Lethal Tempo", "Fleet Footwork"})


if __name__ == "__main__":
    unittest.main()
