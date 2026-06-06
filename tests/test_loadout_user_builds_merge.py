"""Tests for the operator user-build merge into /api/loadout/list +
/api/loadout/apply (2026-05-28).

Bug: a build saved on the User Builds page (coaches/sr_user_builds ->
data/daemon_slayer/user_builds.json) never surfaced in the LIVE
champ-select build chooser. list_variants() reads champion_loadouts.json
only; format_for_display() was consumed by tests alone; the old merge
surface /api/sr-draft/profile was deleted (item 186). So user builds were
orphaned from every live chooser.

Fix: routes_loadout merges user builds into /api/loadout/list under
namespaced keys "userbuild_<id>" for EVERY champ-select mode (operator
directive - a saved build is selectable whether the game is SR / ARAM /
Arena), and _serve_loadout_apply_post + _resolve_user_build resolve that
key to the rune/item/summoner LCU command trio.

Coverage:
  * UserBuildResolveTests - _resolve_user_build builds the cmd trio,
    set_uid carries ub-<id>, override_summoners wins, unknown id +
    malformed record fail soft.
  * ListMergeTests - user build appears in /api/loadout/list variants
    for sr / aram / arena; namespaced key; absent when no user builds.
  * ApplyRouteTests - apply with "userbuild_<id>" enqueues the trio;
    unknown id -> 404.
  * AsciiHygieneTests - no em/en-dashes or smart quotes in the route
    file or this test file.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dashboard import routes_loadout as rt  # noqa: E402

_UID = "723d445b"
_VARIANT = "userbuild_" + _UID

_REC = {
    "id": _UID,
    "label": "crit max",
    "mode": "sr",
    "role": "BOTTOM",
    "runes": {
        "keystone": "Lethal Tempo",
        "primary": "Precision",
        "secondary": "Domination",
    },
    "summoner_spells": [4, 21],
    "items": ["Infinity Edge", "Berserker's Greaves"],
}

# Shape that the real sr_user_builds.format_for_display would emit, with
# item ids already resolved (patched in so the test does not depend on
# ddragon name resolution).
_SHAPED = {
    "kind": "user",
    "key": _UID,
    "label": "crit max",
    "description": "AS crit cait",
    "champion": "",
    "keystone": "Lethal Tempo",
    "runes": {
        "keystone": "Lethal Tempo",
        "primary": "Precision",
        "secondary": "Domination",
    },
    "summoner_spells": [4, 21],
    "item_skeleton": {},
    "build_path": ["Infinity Edge", "Berserker's Greaves"],
    "item_ids": ["3031", "3006"],
    "engine": None,
    "user": {"id": _UID},
}


class StubHandler:
    def __init__(self, path: str = "") -> None:
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


def _patch_store(recs, shaped=_SHAPED):
    """Patch the lazy-imported sr_user_builds helpers. The route does
    `from coaches.sr_user_builds import list_for, format_for_display`
    inside the function body, so patching the module attributes lands."""
    return (
        mock.patch("coaches.sr_user_builds.list_for", return_value=recs),
        mock.patch("coaches.sr_user_builds.format_for_display",
                   return_value=shaped),
    )


# ---------------------------------------------------------------------
# UserBuildResolveTests - the pure resolver helper.
# ---------------------------------------------------------------------


class UserBuildResolveTests(unittest.TestCase):
    def test_builds_cmd_trio(self) -> None:
        p1, p2 = _patch_store([_REC])
        with p1, p2:
            out = rt._resolve_user_build("Caitlyn", _VARIANT, "sr", None)
        self.assertTrue(out["ok"])
        self.assertEqual(out["label"], "crit max")
        self.assertIsNotNone(out["item_cmd"])
        self.assertIsNotNone(out["summ_cmd"])
        self.assertIsNotNone(out["rune_cmd"])

    def test_set_uid_carries_ub_id(self) -> None:
        p1, p2 = _patch_store([_REC])
        with p1, p2:
            out = rt._resolve_user_build("Caitlyn", _VARIANT, "sr", None)
        self.assertEqual(out["item_cmd"]["set_uid"], "RC-caitlyn-sr-ub-" + _UID)
        # blocks carry the resolved ids
        ids = [it["id"] for it in out["item_cmd"]["blocks"][0]["items"]]
        self.assertEqual(ids, ["3031", "3006"])

    def test_summ_cmd_from_build(self) -> None:
        p1, p2 = _patch_store([_REC])
        with p1, p2:
            out = rt._resolve_user_build("Caitlyn", _VARIANT, "sr", None)
        self.assertEqual(out["summ_cmd"], {"cmd": "set_summoners", "d": 4, "f": 21})

    def test_override_summoners_wins(self) -> None:
        p1, p2 = _patch_store([_REC])
        with p1, p2:
            out = rt._resolve_user_build("Caitlyn", _VARIANT, "sr", [4, 1])
        self.assertEqual(out["summ_cmd"], {"cmd": "set_summoners", "d": 4, "f": 1})

    def test_unknown_id_not_ok(self) -> None:
        p1, p2 = _patch_store([])  # no records for champion
        with p1, p2:
            out = rt._resolve_user_build("Caitlyn", "userbuild_deadbeef", "sr", None)
        self.assertFalse(out["ok"])
        self.assertIn("deadbeef", out["err"])

    def test_malformed_shape_not_ok(self) -> None:
        p1, p2 = _patch_store([_REC], shaped=None)
        with p1, p2:
            out = rt._resolve_user_build("Caitlyn", _VARIANT, "sr", None)
        self.assertFalse(out["ok"])

    def test_aram_mode_is_aram_rune_branch(self) -> None:
        # aram routes through build_perk_ids(is_aram=True) - just assert
        # the resolved entry stays ok + carries mode aram in set_uid.
        p1, p2 = _patch_store([_REC])
        with p1, p2:
            out = rt._resolve_user_build("Caitlyn", _VARIANT, "aram", None)
        self.assertTrue(out["ok"])
        self.assertEqual(out["item_cmd"]["set_uid"], "RC-caitlyn-aram-ub-" + _UID)


# ---------------------------------------------------------------------
# ListMergeTests - /api/loadout/list includes user builds, all modes.
# ---------------------------------------------------------------------


class ListMergeTests(unittest.TestCase):
    def _keys_for(self, mode: str) -> list[str]:
        p1, p2 = _patch_store([_REC])
        with p1, p2:
            h = StubHandler()
            rt._serve_loadout_list_post(h, {"champion": "Caitlyn", "mode": mode})
        self.assertEqual(h.last_status, 200)
        return [v["key"] for v in h.parsed().get("variants", [])]

    def test_user_build_present_sr(self) -> None:
        self.assertIn(_VARIANT, self._keys_for("sr"))

    def test_user_build_present_aram(self) -> None:
        self.assertIn(_VARIANT, self._keys_for("aram"))

    def test_user_build_present_arena(self) -> None:
        self.assertIn(_VARIANT, self._keys_for("arena"))

    def test_user_row_shape(self) -> None:
        p1, p2 = _patch_store([_REC])
        with p1, p2:
            h = StubHandler()
            rt._serve_loadout_list_post(h, {"champion": "Caitlyn", "mode": "sr"})
        row = next(v for v in h.parsed()["variants"] if v["key"] == _VARIANT)
        self.assertEqual(row["label"], "crit max")
        self.assertTrue(row["is_user"])
        self.assertFalse(row["is_default"])
        self.assertEqual(row["item_ids"], ["3031", "3006"])
        self.assertEqual(row["build_paths"], [])
        self.assertEqual(row["summoners"], [4, 21])

    def test_no_user_builds_no_extra_rows(self) -> None:
        p1, p2 = _patch_store([])
        with p1, p2:
            h = StubHandler()
            rt._serve_loadout_list_post(h, {"champion": "Caitlyn", "mode": "sr"})
        keys = [v["key"] for v in h.parsed().get("variants", [])]
        self.assertFalse(any(k.startswith("userbuild_") for k in keys))


# ---------------------------------------------------------------------
# ApplyRouteTests - apply routes the namespaced key.
# ---------------------------------------------------------------------


class ApplyRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        if "web_dashboard" not in sys.modules:
            stub = type(sys)("web_dashboard")
            stub._VISION_TOKEN = "test-token"
            sys.modules["web_dashboard"] = stub
        else:
            sys.modules["web_dashboard"]._VISION_TOKEN = "test-token"

    def _urlopen_mock(self):
        m = mock.MagicMock()
        m.return_value.__enter__ = mock.MagicMock(
            return_value=mock.MagicMock(read=lambda: b'{"ok":true}'))
        m.return_value.__exit__ = mock.MagicMock(return_value=False)
        return m

    def test_apply_enqueues_trio(self) -> None:
        p1, p2 = _patch_store([_REC])
        um = self._urlopen_mock()
        with p1, p2, mock.patch("urllib.request.urlopen", um):
            h = StubHandler()
            rt._serve_loadout_apply_post(
                h, {"champion": "Caitlyn", "variant": _VARIANT, "mode": "sr"})
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(set(body["queued"]),
                         {"apply_runes", "apply_item_set", "set_summoners"})

    def test_apply_unknown_id_404(self) -> None:
        p1, p2 = _patch_store([])
        um = self._urlopen_mock()
        with p1, p2, mock.patch("urllib.request.urlopen", um):
            h = StubHandler()
            rt._serve_loadout_apply_post(
                h, {"champion": "Caitlyn", "variant": "userbuild_deadbeef",
                    "mode": "sr"})
        self.assertEqual(h.last_status, 404)


# ---------------------------------------------------------------------
# AsciiHygieneTests
# ---------------------------------------------------------------------


class AsciiHygieneTests(unittest.TestCase):
    _BANNED = [chr(0x2013), chr(0x2014), chr(0x201C),
               chr(0x201D), chr(0x2018), chr(0x2019)]

    def _scan(self, rel: str) -> None:
        txt = (_PROJECT_ROOT / rel).read_text(encoding="utf-8")
        for ch in self._BANNED:
            self.assertNotIn(ch, txt, f"{rel} contains banned codepoint U+{ord(ch):04X}")

    def test_route_file_ascii(self) -> None:
        self._scan("dashboard/routes_loadout.py")

    def test_test_file_ascii(self) -> None:
        self._scan("tests/test_loadout_user_builds_merge.py")


# ---------------------------------------------------------------------
# MinorRunesTests (item 212) - user minor runes survive format_for_display,
# are honored by build_perk_ids, fall back to defaults when invalid, and
# propagate end-to-end through the apply route.
# ---------------------------------------------------------------------


class MinorRunesTests(unittest.TestCase):
    def test_format_for_display_surfaces_minors(self) -> None:
        from coaches import sr_user_builds as sub
        mp = ["Cheap Shot", "Sixth Sense", "Ultimate Hunter"]
        ms = ["Triumph", "Coup de Grace"]
        rec = {
            "label": "x",
            "items": ["Infinity Edge"],
            "runes": {
                "keystone": "Hail of Blades",
                "primary": "Domination",
                "secondary": "Precision",
                "minor_primary": mp,
                "minor_secondary": ms,
            },
        }
        out = sub.format_for_display(rec)
        self.assertIsNotNone(out)
        self.assertEqual(out["runes"]["minor_primary"], mp)
        self.assertEqual(out["runes"]["minor_secondary"], ms)

    def test_build_perk_ids_honors_user_minors(self) -> None:
        import lcu.lcu_rune_writer as lrw
        name_map = lrw._perk_by_name()
        ids = lrw.build_perk_ids(
            "Hail of Blades", "Domination", "Precision", False,
            minor_primary=["Cheap Shot", "Sixth Sense", "Ultimate Hunter"],
            minor_secondary=["Triumph", "Coup de Grace"],
        )
        self.assertEqual(len(ids), 9)
        self.assertEqual(
            ids[1:4],
            [name_map["Cheap Shot"], name_map["Sixth Sense"],
             name_map["Ultimate Hunter"]],
        )
        self.assertEqual(
            ids[4:6],
            [name_map["Triumph"], name_map["Coup de Grace"]],
        )
        default_ids = lrw.build_perk_ids(
            "Hail of Blades", "Domination", "Precision", False)
        self.assertEqual(ids[0], default_ids[0])       # keystone unchanged
        self.assertEqual(ids[6:9], default_ids[6:9])   # shards unchanged
        self.assertNotEqual(ids[1:4], default_ids[1:4])  # override applied

    def test_build_perk_ids_falls_back_when_minors_invalid(self) -> None:
        import lcu.lcu_rune_writer as lrw
        default_ids = lrw.build_perk_ids(
            "Hail of Blades", "Domination", "Precision", False)
        # Unresolvable primary minors -> primary rows stay default.
        bad_primary = lrw.build_perk_ids(
            "Hail of Blades", "Domination", "Precision", False,
            minor_primary=["Bogus Rune", "x", "y"],
        )
        self.assertEqual(bad_primary[1:4], default_ids[1:4])
        # Wrong-count / unresolvable secondary minors -> secondary stays default.
        bad_secondary = lrw.build_perk_ids(
            "Hail of Blades", "Domination", "Precision", False,
            minor_secondary=["Bogus"],
        )
        self.assertEqual(bad_secondary[4:6], default_ids[4:6])
        # No minor args at all -> identical to the default call.
        none_args = lrw.build_perk_ids(
            "Hail of Blades", "Domination", "Precision", False)
        self.assertEqual(none_args, default_ids)

    def test_route_passes_user_minors_end_to_end(self) -> None:
        import lcu.lcu_rune_writer as lrw
        shaped = {
            "kind": "user",
            "key": _UID,
            "label": "crit max",
            "description": "AS crit cait",
            "champion": "",
            "keystone": "Lethal Tempo",
            "runes": {
                "keystone": "Lethal Tempo",
                "primary": "Precision",
                "secondary": "Domination",
                "minor_primary": ["Presence of Mind", "Legend: Alacrity",
                                  "Coup de Grace"],
                "minor_secondary": ["Cheap Shot", "Treasure Hunter"],
            },
            "summoner_spells": [4, 21],
            "item_skeleton": {},
            "build_path": ["Infinity Edge", "Berserker's Greaves"],
            "item_ids": ["3031", "3006"],
            "engine": None,
            "user": {"id": _UID},
        }
        p1, p2 = _patch_store([_REC], shaped=shaped)
        with p1, p2:
            out = rt._resolve_user_build("Caitlyn", _VARIANT, "sr", None)
        self.assertTrue(out["ok"])
        name_map = lrw._perk_by_name()
        perk = out["rune_cmd"]["perk_ids"]
        self.assertEqual(
            perk[1:4],
            [name_map["Presence of Mind"], name_map["Legend: Alacrity"],
             name_map["Coup de Grace"]],
        )
        self.assertEqual(
            perk[4:6],
            [name_map["Cheap Shot"], name_map["Treasure Hunter"]],
        )


if __name__ == "__main__":
    unittest.main()
