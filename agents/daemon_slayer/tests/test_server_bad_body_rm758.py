"""RM-758 - :8860 bad JSON bodies get a 400 with one fixed message.

MEASURED 2026-10-22 on the live :8860 (POST /stats, pre-fix):
  - ``{not-json``            -> 400 "invalid JSON body: Expecting property
                                name enclosed in double quotes: line 1
                                column 2 (char 1)" (decoder text echoed)
  - invalid UTF-8 bytes      -> 400 "invalid JSON body: 'utf-8' codec can't
                                decode byte 0xff ..." (codec text echoed)
  - ``[`` x 100000 + ``]`` x 100000 -> 500 (RecursionError reached the
                                do_POST catch-all, traceback in the DS log)
  - a 5000-digit integer     -> 500 (the int-digit-limit ValueError is not
                                a JSONDecodeError, so it escaped too)

Contract: each of those is a 400 whose body is exactly the generic
``invalid JSON body`` (no decoder, codec or exception text), the raw error
is logged at WARNING, a non-object body keeps its own 400, and the handler
still serves the next request.
"""
from __future__ import annotations

import http.client
import json
import logging
import threading
import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.server import start_server

_GENERIC = "invalid JSON body"

# Fragments that only a decoder / codec / interpreter message would carry.
_LEAK_MARKERS = (
    "Expecting", "line 1", "char ", "codec", "0xff", "utf-8",
    "recursion", "Exceeds", "4300", "digits",
)

_DEEP_NEST = b"[" * 100000 + b"]" * 100000
_BIG_INT = b'{"champion": "Aatrox", "level": ' + b"9" * 5000 + b"}"


class BadJsonBodyTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        snap = DataSnapshot.load()
        cls.srv = start_server(host="127.0.0.1", port=0, snapshot=snap)
        cls.host, cls.port = cls.srv.server_address
        cls._t = threading.Thread(target=cls.srv.serve_forever, daemon=True,
                                  name="RM758BadBodyServer")
        cls._t.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.shutdown()
        cls.srv.server_close()

    def _post_raw(self, path: str, raw: bytes) -> tuple[int, dict]:
        conn = http.client.HTTPConnection(self.host, self.port, timeout=30)
        try:
            conn.request("POST", path, body=raw,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            return resp.status, json.loads(resp.read().decode("utf-8"))
        finally:
            conn.close()

    def _assert_generic_400(self, raw: bytes, expect_log: str) -> None:
        with self.assertLogs("daemon_slayer.server", level="WARNING") as cm:
            status, body = self._post_raw("/stats", raw)
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], _GENERIC)
        wire = json.dumps(body)
        for marker in _LEAK_MARKERS:
            self.assertNotIn(marker, wire)
        # The raw error is kept for the operator, in the log only.
        warnings = [r for r in cm.records if r.levelno == logging.WARNING]
        self.assertTrue(warnings, "expected one WARNING with the raw error")
        self.assertIn(expect_log, "\n".join(r.getMessage() for r in warnings))

    def test_malformed_json_is_generic_400(self) -> None:
        self._assert_generic_400(b"{not-json", "Expecting")

    def test_invalid_utf8_is_generic_400(self) -> None:
        self._assert_generic_400(b'{"champion": "\xff\xfe"}', "0xff")

    def test_deeply_nested_body_is_generic_400_not_500(self) -> None:
        self._assert_generic_400(_DEEP_NEST, "RecursionError")

    def test_over_long_integer_is_generic_400_not_500(self) -> None:
        self._assert_generic_400(_BIG_INT, "ValueError")

    def test_non_object_body_keeps_its_own_400(self) -> None:
        status, body = self._post_raw("/stats", b"[]")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "JSON body must be an object")

    def test_next_request_is_served_after_bad_bodies(self) -> None:
        logging.getLogger("daemon_slayer.server").disabled = True
        try:
            for raw in (_DEEP_NEST, _BIG_INT, b"{not-json"):
                status, _ = self._post_raw("/stats", raw)
                self.assertEqual(status, 400)
        finally:
            logging.getLogger("daemon_slayer.server").disabled = False
        status, body = self._post_raw(
            "/stats", json.dumps({"champion": "Aatrox", "level": 1}).encode())
        self.assertEqual(status, 200)
        self.assertEqual(body["champion_id"], "Aatrox")


if __name__ == "__main__":
    unittest.main()
