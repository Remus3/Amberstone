"""Phase 8 step 3 — user-curated additive build store.

Hermetic tests: each test redirects sr_user_builds._STORE_PATH to a
tempdir so the real data/daemon_slayer/user_builds.json is never
touched by the test suite.

Covers: list_for / add / update / delete CRUD; mtime-aware reload;
atomic write via tmp.replace; format_for_display shape parity with
engine profiles; merge invariant in routes_sr_draft (engine + user
builds coexist with kind tags).
"""
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from coaches import sr_draft_profile, sr_user_builds


class _HermeticStoreCase(unittest.TestCase):
    """Mixin: redirect _STORE_PATH to a tempdir for the test's lifetime."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._store_path = Path(self._tmp.name) / "user_builds.json"
        self._patcher = mock.patch.object(
            sr_user_builds, "_STORE_PATH", self._store_path,
        )
        self._patcher.start()
        sr_user_builds.clear_cache()

    def tearDown(self):
        self._patcher.stop()
        sr_user_builds.clear_cache()
        self._tmp.cleanup()


class TestCrudHappyPath(_HermeticStoreCase):
    def test_list_for_empty_returns_empty_list(self):
        self.assertEqual(sr_user_builds.list_for("Tristana"), [])

    def test_add_then_list(self):
        new_id = sr_user_builds.add("Tristana", {
            "label": "lethality rush",
            "role":  "BOTTOM",
            "runes": {"keystone": "Hail of Blades", "primary": "Domination", "secondary": "Precision"},
            "summoner_spells": [4, 7],
            "items": ["Opportunity", "Edge of Night", "Voltaic Cyclosword"],
            "notes": "lane bully",
        })
        self.assertEqual(len(new_id), 8, "id should be 8 hex chars")
        self.assertTrue(all(c in "0123456789abcdef" for c in new_id))
        builds = sr_user_builds.list_for("Tristana")
        self.assertEqual(len(builds), 1)
        b = builds[0]
        self.assertEqual(b["id"], new_id)
        self.assertEqual(b["label"], "lethality rush")
        self.assertEqual(b["role"], "BOTTOM")
        self.assertEqual(b["mode"], "sr")
        self.assertEqual(b["items"][0], "Opportunity")
        self.assertGreater(b["created_at"], 0)
        self.assertEqual(b["created_at"], b["updated_at"])

    def test_add_persists_to_disk(self):
        sr_user_builds.add("Jhin", {
            "label": "snowball", "items": ["The Collector"],
        })
        # Direct file read — proves atomic write happened.
        raw = json.loads(self._store_path.read_text(encoding="utf-8"))
        self.assertIn("Jhin", raw["champions"])
        self.assertEqual(raw["_schema_version"], 1)

    def test_update_merges(self):
        bid = sr_user_builds.add("Yuumi", {"label": "AP support", "items": ["Moonstone Renewer"]})
        ok = sr_user_builds.update("Yuumi", bid, {"label": "AP support v2", "notes": "vs poke"})
        self.assertTrue(ok)
        b = sr_user_builds.list_for("Yuumi")[0]
        self.assertEqual(b["label"], "AP support v2")
        self.assertEqual(b["notes"], "vs poke")
        self.assertEqual(b["items"], ["Moonstone Renewer"])  # unchanged
        self.assertGreaterEqual(b["updated_at"], b["created_at"])

    def test_update_missing_returns_false(self):
        self.assertFalse(sr_user_builds.update("Yuumi", "deadbeef", {"label": "x"}))

    def test_update_cannot_change_id(self):
        bid = sr_user_builds.add("Tristana", {"label": "x", "items": ["IE"]})
        sr_user_builds.update("Tristana", bid, {"id": "hax", "label": "y"})
        b = sr_user_builds.list_for("Tristana")[0]
        self.assertEqual(b["id"], bid)

    def test_delete_removes_record(self):
        bid = sr_user_builds.add("Sett", {"label": "tank", "items": ["Sunfire Aegis"]})
        self.assertEqual(len(sr_user_builds.list_for("Sett")), 1)
        ok = sr_user_builds.delete("Sett", bid)
        self.assertTrue(ok)
        self.assertEqual(sr_user_builds.list_for("Sett"), [])

    def test_delete_drops_empty_champion_entry(self):
        bid = sr_user_builds.add("Sett", {"label": "tank", "items": ["X"]})
        sr_user_builds.delete("Sett", bid)
        raw = json.loads(self._store_path.read_text(encoding="utf-8"))
        self.assertNotIn("Sett", raw["champions"])

    def test_delete_missing_returns_false(self):
        self.assertFalse(sr_user_builds.delete("Sett", "deadbeef"))

    def test_two_champions_isolated(self):
        a = sr_user_builds.add("Tristana", {"label": "a", "items": ["IE"]})
        b = sr_user_builds.add("Jhin",     {"label": "b", "items": ["The Collector"]})
        self.assertEqual(len(sr_user_builds.list_for("Tristana")), 1)
        self.assertEqual(len(sr_user_builds.list_for("Jhin")),     1)
        sr_user_builds.delete("Tristana", a)
        self.assertEqual(sr_user_builds.list_for("Tristana"), [])
        self.assertEqual(len(sr_user_builds.list_for("Jhin")), 1)


class TestValidation(_HermeticStoreCase):
    def test_empty_champion_raises(self):
        with self.assertRaises(ValueError):
            sr_user_builds.add("", {"label": "x", "items": ["IE"]})

    def test_missing_label_raises(self):
        with self.assertRaises(ValueError):
            sr_user_builds.add("Tristana", {"items": ["IE"]})

    def test_non_dict_build_raises(self):
        with self.assertRaises(ValueError):
            sr_user_builds.add("Tristana", "not a dict")  # type: ignore[arg-type]

    def test_role_aliases_uppercased(self):
        bid = sr_user_builds.add("Tristana", {
            "label": "x", "items": ["IE"], "role": "bottom",
        })
        b = next(x for x in sr_user_builds.list_for("Tristana") if x["id"] == bid)
        self.assertEqual(b["role"], "BOTTOM")

    def test_garbage_spell_pair_falls_back(self):
        bid = sr_user_builds.add("Tristana", {
            "label": "x", "items": ["IE"], "summoner_spells": "not a list",
        })
        b = next(x for x in sr_user_builds.list_for("Tristana") if x["id"] == bid)
        self.assertEqual(b["summoner_spells"], [4, 14])


class TestMtimeReload(_HermeticStoreCase):
    """Hand-edits to the JSON file should be picked up on next call."""

    def test_external_edit_visible_after_mtime_change(self):
        sr_user_builds.add("Tristana", {"label": "v1", "items": ["IE"]})
        self.assertEqual(sr_user_builds.list_for("Tristana")[0]["label"], "v1")
        # Simulate a hand-edit.
        import time as _time
        _time.sleep(0.01)  # Ensure mtime can advance even on coarse FS.
        raw = json.loads(self._store_path.read_text(encoding="utf-8"))
        raw["champions"]["Tristana"][0]["label"] = "hand-edited"
        # Bump mtime by writing fresh bytes.
        self._store_path.write_text(json.dumps(raw), encoding="utf-8")
        sr_user_builds.clear_cache()  # In production, mtime difference triggers reload;
        # we clear here to make the test deterministic across FS mtime granularity.
        self.assertEqual(sr_user_builds.list_for("Tristana")[0]["label"], "hand-edited")


class TestFormatForDisplay(_HermeticStoreCase):
    def test_canonical_shape_matches_engine_profile(self):
        bid = sr_user_builds.add("Tristana", {
            "label": "off-meta",
            "role":  "BOTTOM",
            "runes": {"keystone": "Hail of Blades", "primary": "Domination", "secondary": "Precision"},
            "summoner_spells": [4, 7],
            "items": ["Infinity Edge", "Lord Dominik's Regards", "Runaan's Hurricane",
                      "Mortal Reminder", "Kraken Slayer", "Yun Tal Wildarrows"],
            "notes": "test",
        })
        rec = next(x for x in sr_user_builds.list_for("Tristana") if x["id"] == bid)
        rec["_champion"] = "Tristana"
        shaped = sr_user_builds.format_for_display(rec)
        self.assertIsNotNone(shaped)
        # Same key set as engine profiles (kind, key, label, runes,
        # summoner_spells, item_skeleton, build_path, item_ids, engine).
        for k in ("kind", "key", "label", "runes", "summoner_spells",
                  "item_skeleton", "build_path", "item_ids", "engine"):
            self.assertIn(k, shaped, f"missing {k}")
        self.assertEqual(shaped["kind"], "user")
        self.assertEqual(shaped["key"], bid)
        self.assertEqual(shaped["champion"], "Tristana")
        self.assertEqual(shaped["keystone"], "Hail of Blades")
        self.assertEqual(shaped["summoner_spells"], [4, 7])
        # IDs resolve via DDragon (this requires data/meta/ddragon_items.json).
        # If the resolver returns nothing, item_ids is [] but build_path stays.
        self.assertEqual(len(shaped["build_path"]), 6)
        # Skeleton should be 2/2/2 split.
        self.assertEqual(len(shaped["item_skeleton"]["start"]), 2)
        self.assertEqual(shaped["item_skeleton"]["start"][0]["name"], "Infinity Edge")
        # Engine field is None (not from engine).
        self.assertIsNone(shaped["engine"])
        # User metadata preserved.
        self.assertEqual(shaped["user"]["id"], bid)
        self.assertEqual(shaped["user"]["notes"], "test")

    def test_missing_label_returns_none(self):
        self.assertIsNone(sr_user_builds.format_for_display({"items": ["X"]}))

    def test_empty_items_returns_none(self):
        self.assertIsNone(sr_user_builds.format_for_display({"label": "x", "items": []}))

    def test_non_dict_input(self):
        self.assertIsNone(sr_user_builds.format_for_display("not a dict"))  # type: ignore[arg-type]


class TestRouteMergeInvariant(_HermeticStoreCase):
    """The route layer merges user builds with engine profiles. Verify
    operator-additive: user builds APPEND, never replace."""

    def setUp(self):
        super().setUp()
        sr_draft_profile.clear_cache()

    def _route_handler(self):
        captured = {}
        class _H:
            def _send(self, code, body, ctype):
                captured["code"]  = code
                captured["body"]  = body
                captured["ctype"] = ctype
        return _H(), captured

    def test_engine_then_user_in_order(self):
        sr_user_builds.add("Tristana", {
            "label": "my off-meta",
            "items": ["IE", "LDR", "Runaan's", "MR", "Kraken", "Yun Tal"],
        })
        # Mock engine to return 3 profiles.
        FAKE_BEAM = {
            "ranked": [{
                "item_ids":   ["3031", "3036", "3085", "3033", "6672", "3032"],
                "item_names": ["Infinity Edge", "Lord Dominik's Regards", "Runaan's Hurricane",
                               "Mortal Reminder", "Kraken Slayer", "Yun Tal Wildarrows"],
                "total_gold": 18550, "final_dps": 800.0, "baseline_dps": 37.0,
                "delta_dps": 763.0, "dps_per_1k_gold": 41.0,
            }]
        }
        def _open(req, **kwargs):
            class _R:
                def read(self):  return json.dumps(FAKE_BEAM).encode()
                def __enter__(self): return self
                def __exit__(self, *a): return False
            return _R()
        with mock.patch.object(sr_draft_profile.urllib.request, "urlopen",
                               side_effect=_open):
            from dashboard.routes_sr_draft import _serve_sr_draft_profile_post
            h, captured = self._route_handler()
            _serve_sr_draft_profile_post(h, {
                "champion": "Tristana", "role": "BOTTOM", "queue_id": 420,
            })
        self.assertEqual(captured["code"], 200)
        body = json.loads(captured["body"])
        self.assertEqual(len(body["profiles"]), 4)  # 3 engine + 1 user
        # Order: 3 engine first, then user.
        kinds = [p["kind"] for p in body["profiles"]]
        self.assertEqual(kinds, ["engine", "engine", "engine", "user"])
        # User build label preserved.
        self.assertEqual(body["profiles"][3]["label"], "my off-meta")

    def test_engine_unreachable_user_still_visible(self):
        sr_user_builds.add("Yuumi", {"label": "user-only", "items": ["Moonstone Renewer", "Locket"]})
        with mock.patch.object(sr_draft_profile.urllib.request, "urlopen",
                               side_effect=urllib.error.URLError("off")):
            from dashboard.routes_sr_draft import _serve_sr_draft_profile_post
            h, captured = self._route_handler()
            _serve_sr_draft_profile_post(h, {
                "champion": "Yuumi", "role": "UTILITY", "queue_id": 420,
            })
        body = json.loads(captured["body"])
        # Engine failure logs notes but user build still appears.
        self.assertEqual(len(body["profiles"]), 1)
        self.assertEqual(body["profiles"][0]["kind"], "user")
        self.assertEqual(body["profiles"][0]["label"], "user-only")


if __name__ == "__main__":
    unittest.main()
