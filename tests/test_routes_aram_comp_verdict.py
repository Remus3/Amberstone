"""Contract tests for the /api/aram-comp-verdict POST endpoint.

The route exposes the deterministic ARAM bench verdict engine
(core.aram_comp_verdict.comp_verdict) over HTTP with ZERO Anthropic spend.
Mirrors the style of tests/test_routes_coach_choice.py.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from dashboard import routes_coach as rc


class _Handler:
    def __init__(self) -> None:
        self.status = 0
        self.body = b""
        self.ctype = ""

    def _send(self, status, body, ctype, cache_control=None):
        self.status = status
        self.body = body
        self.ctype = ctype

    def json(self) -> dict:
        return json.loads(self.body.decode())


_VERDICT = {
    "ok": True,
    "recommendation": "swap",
    "swap_to": "Ashe",
    "variant_to": "",
    "reason": "Only 1/3 ranged - swap to Ashe for poke and disengage range.",
    "confidence": "high",
    "factors": {"n": 3, "ranged_count": 1},
}


class HappyPath(unittest.TestCase):
    def test_verdict_passed_through_verbatim(self):
        h = _Handler()
        payload = {"my_team": ["Jinx", "Lux", "Lulu"], "bench": ["Ashe"]}
        with mock.patch(
            "core.aram_comp_verdict.comp_verdict", return_value=_VERDICT
        ) as mk:
            rc._serve_aram_comp_verdict_post(h, payload)
        self.assertEqual(h.status, 200)
        self.assertEqual(h.ctype, "application/json")
        self.assertEqual(h.json(), _VERDICT)
        mk.assert_called_once_with(payload)


class ServerErrorHandling(unittest.TestCase):
    def test_comp_verdict_exception_returns_500(self):
        h = _Handler()
        with mock.patch(
            "core.aram_comp_verdict.comp_verdict",
            side_effect=RuntimeError("boom"),
        ):
            rc._serve_aram_comp_verdict_post(h, {"my_team": ["Jinx"]})
        self.assertEqual(h.status, 500)
        # The raw error never leaks beyond the {"error": ...} envelope.
        body = h.json()
        self.assertEqual(set(body.keys()), {"error"})


class RouteRegistration(unittest.TestCase):
    def test_route_registered(self):
        matchers = [m for (m, _fn) in rc.POST_ROUTES]
        self.assertTrue(
            any(m("/api/aram-comp-verdict") for m in matchers),
            "/api/aram-comp-verdict not in POST_ROUTES",
        )

    def test_route_bound_to_handler(self):
        for m, fn in rc.POST_ROUTES:
            if m("/api/aram-comp-verdict"):
                self.assertIs(fn, rc._serve_aram_comp_verdict_post)
                return
        self.fail("route not found")


class Dispatch(unittest.TestCase):
    def test_dispatch_includes_route(self):
        from dashboard import _dispatch
        _dispatch._POST_CACHE = None  # force re-gather
        post = _dispatch._gather_post()
        matchers = [m for (m, _fn) in post]
        self.assertTrue(any(m("/api/aram-comp-verdict") for m in matchers))


if __name__ == "__main__":
    unittest.main()
