"""Phase 8 step 5 — POST /api/sr-draft/apply route smoke tests.

Mirrors the routes_sr_draft profile-route test pattern: stub `_send`
to capture the response, mock the LCU-cmd HTTP enqueue (urllib.request)
so no port binding / network actually happens. Each test asserts a
specific contract the frontend depends on.

Coverage:
  - 400 on missing champion / key
  - 200 happy path: rune/item/summoner commands enqueue + queued list
  - unique page_name per (champion, key) pair
  - empty item_ids / unrecognised runes degrade gracefully (notes, no crash)
  - push_* flags suppress the corresponding enqueue
"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


class TestApplyRoute(unittest.TestCase):
    def _handler(self):
        captured = {}
        class _H:
            def _send(self, code, body, ctype):
                captured["code"]  = code
                captured["body"]  = body
                captured["ctype"] = ctype
        return _H(), captured

    def setUp(self):
        # Stub _VISION_TOKEN so the apply handler's import doesn't need
        # a fully-booted dashboard.
        self._token_patch = mock.patch.dict(sys.modules, {})
        self._token_patch.start()
        # Inject a minimal web_dashboard module exposing _VISION_TOKEN.
        if "web_dashboard" not in sys.modules:
            stub = type(sys)("web_dashboard")
            stub._VISION_TOKEN = "test-token"
            sys.modules["web_dashboard"] = stub
        else:
            sys.modules["web_dashboard"]._VISION_TOKEN = "test-token"

    def tearDown(self):
        self._token_patch.stop()

    def _full_payload(self):
        return {
            "champion": "Tristana",
            "key":      "primary",
            "label":    "Primary",
            "kind":     "engine",
            "runes": {
                "keystone":  "Press the Attack",
                "primary":   "Precision",
                "secondary": "Domination",
            },
            "summoner_spells": [4, 7],
            "item_ids":        ["6675", "3094", "3036"],
        }

    def test_missing_champion(self):
        from dashboard.routes_sr_draft import _serve_sr_draft_apply_post
        h, captured = self._handler()
        _serve_sr_draft_apply_post(h, {"key": "primary"})
        self.assertEqual(captured["code"], 400)

    def test_missing_key(self):
        from dashboard.routes_sr_draft import _serve_sr_draft_apply_post
        h, captured = self._handler()
        _serve_sr_draft_apply_post(h, {"champion": "Tristana"})
        self.assertEqual(captured["code"], 400)

    def test_happy_path_enqueues_all_three(self):
        from dashboard import routes_sr_draft
        h, captured = self._handler()
        urlopen_mock = mock.MagicMock()
        urlopen_mock.return_value.__enter__ = mock.MagicMock(
            return_value=mock.MagicMock(read=lambda: b'{"ok":true}')
        )
        urlopen_mock.return_value.__exit__ = mock.MagicMock(return_value=False)
        with mock.patch("urllib.request.urlopen", urlopen_mock):
            routes_sr_draft._serve_sr_draft_apply_post(h, self._full_payload())
        self.assertEqual(captured["code"], 200)
        body = json.loads(captured["body"])
        self.assertTrue(body["ok"])
        self.assertEqual(body["champion"], "Tristana")
        self.assertEqual(body["key"], "primary")
        self.assertEqual(set(body["queued"]),
                         {"apply_runes", "apply_item_set", "set_summoners"})
        # Three enqueue calls = three urlopen invocations.
        self.assertEqual(urlopen_mock.call_count, 3)

    def test_unique_page_name_per_variant(self):
        from dashboard.routes_sr_draft import _build_page_name
        a = _build_page_name("Tristana", "primary")
        b = _build_page_name("Tristana", "alt")
        c = _build_page_name("Tristana", "experimental")
        self.assertEqual(len({a, b, c}), 3)
        # Format check — used by the apply route's response field too.
        self.assertEqual(a, "RC: Tristana primary (SR)")
        self.assertEqual(b, "RC: Tristana alt (SR)")

    def test_page_name_truncated_to_75(self):
        from dashboard.routes_sr_draft import _build_page_name
        longish = _build_page_name("A" * 80, "primary")
        self.assertLessEqual(len(longish), 75)

    def test_empty_item_ids_skips_item_cmd(self):
        from dashboard import routes_sr_draft
        h, captured = self._handler()
        payload = self._full_payload()
        payload["item_ids"] = []
        with mock.patch("urllib.request.urlopen") as urlopen_mock:
            urlopen_mock.return_value.__enter__ = mock.MagicMock(
                return_value=mock.MagicMock(read=lambda: b'{"ok":true}')
            )
            urlopen_mock.return_value.__exit__ = mock.MagicMock(return_value=False)
            routes_sr_draft._serve_sr_draft_apply_post(h, payload)
        self.assertEqual(captured["code"], 200)
        body = json.loads(captured["body"])
        self.assertNotIn("apply_item_set", body["queued"])
        self.assertIn("apply_runes", body["queued"])

    def test_unrecognised_keystone_skips_rune_cmd_with_note(self):
        from dashboard import routes_sr_draft
        h, captured = self._handler()
        payload = self._full_payload()
        payload["runes"] = {"keystone": "Bogus", "primary": "Precision",
                            "secondary": "Domination"}
        with mock.patch("urllib.request.urlopen") as urlopen_mock:
            urlopen_mock.return_value.__enter__ = mock.MagicMock(
                return_value=mock.MagicMock(read=lambda: b'{"ok":true}')
            )
            urlopen_mock.return_value.__exit__ = mock.MagicMock(return_value=False)
            routes_sr_draft._serve_sr_draft_apply_post(h, payload)
        self.assertEqual(captured["code"], 200)
        body = json.loads(captured["body"])
        self.assertNotIn("apply_runes", body["queued"])
        self.assertTrue(any("runes" in n for n in body.get("notes", [])))

    def test_push_flags_suppress_enqueues(self):
        from dashboard import routes_sr_draft
        h, captured = self._handler()
        payload = self._full_payload()
        payload["push_runes"] = False
        payload["push_items"] = False
        # Only summoners should fire.
        with mock.patch("urllib.request.urlopen") as urlopen_mock:
            urlopen_mock.return_value.__enter__ = mock.MagicMock(
                return_value=mock.MagicMock(read=lambda: b'{"ok":true}')
            )
            urlopen_mock.return_value.__exit__ = mock.MagicMock(return_value=False)
            routes_sr_draft._serve_sr_draft_apply_post(h, payload)
        body = json.loads(captured["body"])
        self.assertEqual(body["queued"], ["set_summoners"])

    def test_invalid_summoner_spells_skips_summ(self):
        from dashboard import routes_sr_draft
        h, captured = self._handler()
        payload = self._full_payload()
        payload["summoner_spells"] = ["bogus"]
        with mock.patch("urllib.request.urlopen") as urlopen_mock:
            urlopen_mock.return_value.__enter__ = mock.MagicMock(
                return_value=mock.MagicMock(read=lambda: b'{"ok":true}')
            )
            urlopen_mock.return_value.__exit__ = mock.MagicMock(return_value=False)
            routes_sr_draft._serve_sr_draft_apply_post(h, payload)
        body = json.loads(captured["body"])
        self.assertNotIn("set_summoners", body["queued"])

    def test_response_echoes_kind_and_label(self):
        from dashboard import routes_sr_draft
        h, captured = self._handler()
        with mock.patch("urllib.request.urlopen") as urlopen_mock:
            urlopen_mock.return_value.__enter__ = mock.MagicMock(
                return_value=mock.MagicMock(read=lambda: b'{"ok":true}')
            )
            urlopen_mock.return_value.__exit__ = mock.MagicMock(return_value=False)
            routes_sr_draft._serve_sr_draft_apply_post(h, self._full_payload())
        body = json.loads(captured["body"])
        self.assertEqual(body["label"], "Primary")
        self.assertEqual(body["kind"],  "engine")
        self.assertEqual(body["page_name"], "RC: Tristana primary (SR)")


class TestItemSetShape(unittest.TestCase):
    def test_item_set_shape(self):
        from dashboard.routes_sr_draft import _build_item_set
        cmd = _build_item_set("Tristana", "primary", ["6675", "3094"])
        self.assertEqual(cmd["cmd"], "apply_item_set")
        self.assertEqual(cmd["set_uid"], "RC-tristana-sr-primary")
        self.assertIn("Tristana", cmd["title"])
        self.assertEqual(len(cmd["blocks"]), 1)
        self.assertEqual(len(cmd["blocks"][0]["items"]), 2)
        self.assertEqual(cmd["blocks"][0]["items"][0],
                         {"id": "6675", "count": 1})

    def test_item_set_filters_falsy(self):
        from dashboard.routes_sr_draft import _build_item_set
        cmd = _build_item_set("Tristana", "primary", ["6675", "", None, "3094"])
        self.assertEqual(len(cmd["blocks"][0]["items"]), 2)


if __name__ == "__main__":
    unittest.main()
