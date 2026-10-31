"""RM-1233: a GET /api/ban-suggest 400 never echoes the caller's value.

Before the fix ``_parse_ids`` built three error strings from the caller's
own token: ``invalid id 'zz...'`` (a clipped repr), ``id 0 is below 1``
and ``duplicate id 777``. The sibling ``/api/post-game-wpa`` 400 already
names only the parameter and the expected shape (``_MATCH_ID_ERROR``).

Acceptance pinned here: every 400 names the parameter and the expected
shape, and a distinctive junk value sent by the caller never appears in
the response body. Each case is driven through the route entry point
``_serve_ban_suggest`` with ``_compute`` patched, so a token that slipped
past validation would show up as a 200 rather than a fixture-dependent
503.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from dashboard import routes_ban_suggest as rbs


class _Harness:
    def __init__(self, qs: str):
        self.path = f"/api/ban-suggest?{qs}"
        self.sent_status = None
        self.sent_body = b""

    def _send(self, status, body, content_type):
        self.sent_status = status
        self.sent_body = body


_OK = {"ok": True, "ally": [], "enemy": [], "candidates": [],
       "queue_ids": []}

# The exact expected-shape text each error class carries. Literal copies,
# not imports of the module's constants, so a message that regains the
# caller's token fails here.
_BAD_TOKEN = "each id must be 1-6 ASCII digits"
_BELOW_MIN = "each id must be 1 or more"
_DUPLICATE = "duplicate ids are not allowed"

# (query string, parameter named in the 400, junk the body must not hold,
#  the exact error text after "<param>: ")
_CASES = [
    # invalid token (not 1-6 ASCII digits)
    ("ally=zzJUNKzz&candidates=64", "ally", "zzJUNKzz", _BAD_TOKEN),
    ("ally=22&enemy=zzJUNKzz&candidates=64", "enemy", "zzJUNKzz", _BAD_TOKEN),
    ("ally=22&candidates=zzJUNKzz", "candidates", "zzJUNKzz", _BAD_TOKEN),
    ("ally=22&candidates=64&queue=zzJUNKzz", "queue", "zzJUNKzz", _BAD_TOKEN),
    # an over-long digit run (was clipped, still echoed in part)
    ("ally=98765432109876&candidates=64", "ally", "987654", _BAD_TOKEN),
    # a non-ASCII digit token
    ("ally=%D9%A3%D9%A3&candidates=64", "ally", "\\u0663", _BAD_TOKEN),
    # below the minimum (champion ids start at 1)
    ("ally=000000&candidates=64", "ally", "000000", _BELOW_MIN),
    ("ally=22&enemy=000000&candidates=64", "enemy", "000000", _BELOW_MIN),
    ("ally=22&candidates=000000", "candidates", "000000", _BELOW_MIN),
    # duplicates
    ("ally=777777,777777&candidates=64", "ally", "777777", _DUPLICATE),
    ("ally=22&enemy=777777,777777&candidates=64", "enemy", "777777",
     _DUPLICATE),
    ("ally=22&candidates=777777,777777", "candidates", "777777", _DUPLICATE),
    ("ally=22&candidates=64&queue=777777,777777", "queue", "777777",
     _DUPLICATE),
]


class NoCallerValueEchoTests(unittest.TestCase):
    def setUp(self):
        rbs._reset_caches()

    def _serve(self, qs: str) -> _Harness:
        h = _Harness(qs)
        with patch.object(rbs, "_compute", return_value=dict(_OK)) as comp:
            rbs._serve_ban_suggest(h)
        comp.assert_not_called()
        return h

    def test_400_names_param_and_shape_never_the_value(self):
        for qs, param, junk, shape in _CASES:
            with self.subTest(qs=qs):
                h = self._serve(qs)
                self.assertEqual(h.sent_status, 400, h.sent_body)
                raw = h.sent_body.decode("utf-8")
                self.assertNotIn(junk, raw)
                body = json.loads(raw)
                self.assertFalse(body["ok"])
                err = body["error"]
                self.assertEqual(err, f"{param}: {shape}")

    def test_count_errors_name_param_and_bounds(self):
        # A count error carries the bounds, never a token.
        h = self._serve("ally=1,2,3,4,5,6&candidates=64")
        self.assertEqual(h.sent_status, 400)
        err = json.loads(h.sent_body)["error"]
        self.assertEqual(err, "ally: expected 1-5 comma-separated ids")
        h = self._serve("ally=22&candidates=64&queue="
                        + ",".join(str(400 + i) for i in range(17)))
        self.assertEqual(h.sent_status, 400)
        self.assertEqual(json.loads(h.sent_body)["error"],
                         "queue: expected 1-16 comma-separated ids")

    def test_error_text_is_a_fixed_set(self):
        # Two different junk tokens of one class produce byte-identical
        # bodies: nothing of the caller's token reaches the reply.
        a = self._serve("ally=zzJUNKzz&candidates=64").sent_body
        b = self._serve("ally=qqOTHERqq&candidates=64").sent_body
        self.assertEqual(a, b)
        c = self._serve("ally=111111,111111&candidates=64").sent_body
        d = self._serve("ally=222222,222222&candidates=64").sent_body
        self.assertEqual(c, d)

    def test_valid_request_still_reaches_compute(self):
        h = _Harness("ally=22&enemy=42&candidates=64&queue=420")
        with patch.object(rbs, "_compute", return_value={
                "ok": True, "ally": [22], "enemy": [42],
                "candidates": [{"champ_id": 64}],
                "queue_ids": [420]}) as comp:
            rbs._serve_ban_suggest(h)
        self.assertEqual(h.sent_status, 200, h.sent_body)
        comp.assert_called_once()


if __name__ == "__main__":
    unittest.main()
