"""P2-W2 DS-F slice - regression tests for the Daemon Slayer engine audit.

Cycle 11, wave W2 (DS combat-math engine + :8893 HTTP server). Each test
pins a behavior FIXED in this slice; it FAILS on the pre-fix code and PASSES
on the post-fix code.

Covered:
  * server.py do_GET / do_POST 500 path - the raw exception string must NOT
    leak into the HTTP response body (standing finding class 3:
    "never leak a stack/exc string in a 500 body"). The full traceback is
    still logged via ``_log.exception``; only the wire body is sanitized.

The server fixture mirrors ``agents/daemon_slayer/tests/test_server.py``
(``start_server`` on an ephemeral port in a daemon thread, hit via stdlib
``urllib.request``). A throwaway route is injected into ``_POST_ROUTES`` /
``_GET_DISPATCH_ROUTES`` so the test forces the generic 500 path without
mutating any real route, and the dispatch tables are restored on teardown.
"""
from __future__ import annotations

import json
import logging
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agents.daemon_slayer import server
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.server import start_server

# A sensitive marker that the raw exception carries. The pre-fix 500 path
# interpolated ``f"internal error: {e}"`` straight into the JSON body, so this
# marker WOULD appear on the wire. The fixed path must keep it out of the body.
_SECRET_MARKER = "SECRET_INTERNAL_PATH_C:/Riot Commander/API-Key-Claude.txt"
_BOOM_ROUTE = "/p2w2-boom"


def _boom_route(body: dict) -> dict:
    # A non-ApiError, non-KeyError, non-ValueError exception -> the generic
    # 500 handler. RuntimeError is deliberately outside the 404/422 mapping.
    raise RuntimeError(_SECRET_MARKER)


def _post_json(url: str, body: dict) -> tuple[int, dict]:
    raw = json.dumps(body).encode("utf-8")
    req = Request(url, data=raw, method="POST",
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _get_json(url: str) -> tuple[int, dict]:
    try:
        with urlopen(url, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


class FiveHundredBodyNoLeakTests(unittest.TestCase):
    """The 500 error body must be a friendly fixed string, never the raw exc."""

    @classmethod
    def setUpClass(cls) -> None:
        # Inject the throwaway exploding route into BOTH dispatch tables so we
        # exercise the do_POST and do_GET 500 paths without touching real routes.
        cls._orig_post = dict(server._POST_ROUTES)
        cls._orig_get = set(server._GET_DISPATCH_ROUTES)
        server._POST_ROUTES[_BOOM_ROUTE] = _boom_route
        server._GET_DISPATCH_ROUTES.add(_BOOM_ROUTE)
        # Silence the expected traceback log this test deliberately triggers.
        cls._log = logging.getLogger("daemon_slayer.server")
        cls._prev_level = cls._log.level
        cls._log.setLevel(logging.CRITICAL)

        snap = DataSnapshot.load()
        cls.srv = start_server(host="127.0.0.1", port=0, snapshot=snap)
        cls.host, cls.port = cls.srv.server_address
        cls.base = f"http://{cls.host}:{cls.port}"
        cls._t = threading.Thread(
            target=cls.srv.serve_forever, daemon=True, name="P2W2BoomServer"
        )
        cls._t.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.shutdown()
        cls.srv.server_close()
        # Restore dispatch tables + log level - never leave the throwaway route.
        server._POST_ROUTES.clear()
        server._POST_ROUTES.update(cls._orig_post)
        server._GET_DISPATCH_ROUTES.clear()
        server._GET_DISPATCH_ROUTES.update(cls._orig_get)
        cls._log.setLevel(cls._prev_level)

    def test_post_500_body_does_not_leak_raw_exception(self) -> None:
        status, body = _post_json(self.base + _BOOM_ROUTE, {"champion": "Aatrox"})
        self.assertEqual(status, 500)
        self.assertEqual(body["status"], 500)
        # The whole serialized body must not carry the raw exception text.
        self.assertNotIn(_SECRET_MARKER, json.dumps(body))
        self.assertNotIn(_SECRET_MARKER, body.get("error", ""))
        # Still a friendly, actionable degraded-mode message.
        self.assertIn("internal engine error", body["error"])

    def test_get_500_body_does_not_leak_raw_exception(self) -> None:
        status, body = _get_json(self.base + _BOOM_ROUTE + "?champion=Aatrox")
        self.assertEqual(status, 500)
        self.assertNotIn(_SECRET_MARKER, json.dumps(body))
        self.assertIn("internal engine error", body["error"])

    def test_known_route_4xx_mapping_unaffected(self) -> None:
        # Guard the fix did not disturb the explicit ApiError mapping: an
        # unknown champion is still a 404 with the engine's own message.
        status, body = _post_json(
            self.base + "/stats", {"champion": "NotAChampionXYZ", "level": 1}
        )
        self.assertEqual(status, 404)
        self.assertIn("Unknown champion", body["error"])


class NonFiniteFloatRejectTests(unittest.TestCase):
    """A NaN / +-inf float body field is rejected with a 400; the response is
    valid strict JSON (no bare NaN/Infinity token that breaks JSON.parse).

    Pre-fix, ``_opt_float`` passed ``float("nan")`` straight to the engine and
    the 200 response carried a bare ``NaN`` token (invalid JSON; the dashboard
    DS panel's ``JSON.parse`` would throw). Finding class 1.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._log = logging.getLogger("daemon_slayer.server")
        cls._prev_level = cls._log.level
        cls._log.setLevel(logging.CRITICAL)
        snap = DataSnapshot.load()
        cls.srv = start_server(host="127.0.0.1", port=0, snapshot=snap)
        cls.host, cls.port = cls.srv.server_address
        cls.base = f"http://{cls.host}:{cls.port}"
        cls._t = threading.Thread(
            target=cls.srv.serve_forever, daemon=True, name="P2W2NanServer"
        )
        cls._t.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.shutdown()
        cls.srv.server_close()
        cls._log.setLevel(cls._prev_level)

    def _post_raw(self, path: str, raw_body: str) -> tuple[int, str]:
        # Send a hand-built body so we can test bareword NaN/Infinity tokens
        # too (json.dumps would also emit them, but a string is unambiguous).
        req = Request(
            self.base + path,
            data=raw_body.encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(req, timeout=10) as resp:
                return resp.status, resp.read().decode("utf-8")
        except HTTPError as e:
            return e.code, e.read().decode("utf-8")

    def test_nan_target_armor_is_rejected_400(self) -> None:
        status, body = _post_json(
            self.base + "/dps",
            {"champion": "Aatrox", "level": 11, "target_armor": "nan"},
        )
        self.assertEqual(status, 400)
        self.assertIn("finite", body["error"])

    def test_inf_enemy_share_is_rejected_400(self) -> None:
        status, body = _post_json(
            self.base + "/ehp",
            {"champion": "Aatrox", "level": 11, "enemy_ad_share": "inf"},
        )
        self.assertEqual(status, 400)
        self.assertIn("finite", body["error"])

    def test_no_route_emits_bare_nan_token_in_body(self) -> None:
        # Bareword NaN in the JSON body itself: must 400, and the RESPONSE must
        # be valid strict JSON with no bare NaN/Infinity token.
        status, txt = self._post_raw(
            "/dps", '{"champion":"Aatrox","level":11,"target_mr":NaN}'
        )
        self.assertEqual(status, 400)
        self.assertNotIn("NaN", txt)
        self.assertNotIn("Infinity", txt)
        # Strict-mode parse (what a browser JSON.parse does) must succeed.
        json.loads(
            txt,
            parse_constant=lambda c: (_ for _ in ()).throw(
                AssertionError(f"bare constant in response: {c}")
            ),
        )


if __name__ == "__main__":
    unittest.main()
