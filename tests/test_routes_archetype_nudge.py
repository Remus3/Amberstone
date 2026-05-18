"""Tests for the s184 archetype-nudge HTTP endpoints in
dashboard/routes_archetype.py.

Two new routes:

* ``GET  /api/archetype-nudge``          - diagnostic snapshot
* ``POST /api/archetype-nudge/dismiss``  - operator dismissed the chip

Stub HTTP handler captures ``_send`` calls. We mock the
``core.archetype_mismatch`` module so the route boundary is the only
thing exercised; mismatch evaluator tests live in
``test_archetype_mismatch``.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from dashboard import routes_archetype


class _StubHandler:
    """Minimal stand-in for the BaseHTTPRequestHandler used by routes."""

    def __init__(self, path: str = "/api/archetype-nudge"):
        self.path = path
        self._sent = []

    def _send(self, status, body, ctype):
        self._sent.append((status, body, ctype))


def _decode_body(handler) -> dict:
    """Pull the last response body off ``_StubHandler._sent``."""
    if not handler._sent:
        return {}
    _, body, _ = handler._sent[-1]
    return json.loads(body.decode("utf-8"))


class ArchetypeNudgeGetTests(unittest.TestCase):

    def test_returns_snapshot(self):
        h = _StubHandler("/api/archetype-nudge")
        with mock.patch.object(
            routes_archetype, "get_nudge_state_snapshot",
            return_value={"Nasus": {"phase": "fired", "fired": True}},
        ):
            routes_archetype._serve_archetype_nudge_get(h)
        body = _decode_body(h)
        self.assertTrue(body["ok"])
        self.assertEqual(body["state"]["Nasus"]["phase"], "fired")
        # Status 200 + JSON content type
        status, _, ctype = h._sent[-1]
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "application/json")

    def test_empty_state(self):
        h = _StubHandler("/api/archetype-nudge")
        with mock.patch.object(routes_archetype, "get_nudge_state_snapshot", return_value={}):
            routes_archetype._serve_archetype_nudge_get(h)
        body = _decode_body(h)
        self.assertEqual(body["state"], {})


class ArchetypeNudgeDismissPostTests(unittest.TestCase):

    def test_happy_path(self):
        h = _StubHandler()
        with mock.patch.object(routes_archetype, "dismiss_nudge", return_value=True) as m:
            routes_archetype._serve_archetype_nudge_dismiss(h, {"champion": "Nasus"})
        m.assert_called_once_with("Nasus")
        body = _decode_body(h)
        self.assertTrue(body["ok"])
        self.assertTrue(body["dismissed"])
        self.assertEqual(body["champion"], "Nasus")
        self.assertEqual(h._sent[-1][0], 200)

    def test_no_entry_returns_dismissed_false(self):
        h = _StubHandler()
        with mock.patch.object(routes_archetype, "dismiss_nudge", return_value=False):
            routes_archetype._serve_archetype_nudge_dismiss(h, {"champion": "Nasus"})
        body = _decode_body(h)
        self.assertTrue(body["ok"])
        self.assertFalse(body["dismissed"])

    def test_400_on_non_dict(self):
        h = _StubHandler()
        routes_archetype._serve_archetype_nudge_dismiss(h, "not a dict")
        self.assertEqual(h._sent[-1][0], 400)
        body = _decode_body(h)
        self.assertIn("error", body)

    def test_400_on_empty_champion(self):
        h = _StubHandler()
        routes_archetype._serve_archetype_nudge_dismiss(h, {"champion": ""})
        self.assertEqual(h._sent[-1][0], 400)

    def test_400_on_missing_champion(self):
        h = _StubHandler()
        routes_archetype._serve_archetype_nudge_dismiss(h, {})
        self.assertEqual(h._sent[-1][0], 400)


class RouteRegistrationTests(unittest.TestCase):
    """Smoke test - the new routes are exposed in GET_ROUTES / POST_ROUTES
    so dispatch picks them up."""

    def test_get_route_registered(self):
        # Each matcher is a closure; test by evaluating against a known path
        matched = any(matcher("/api/archetype-nudge")
                      for matcher, _ in routes_archetype.GET_ROUTES)
        self.assertTrue(matched, "GET /api/archetype-nudge not in GET_ROUTES")

    def test_post_route_registered(self):
        matched = any(matcher("/api/archetype-nudge/dismiss")
                      for matcher, _ in routes_archetype.POST_ROUTES)
        self.assertTrue(matched, "POST /api/archetype-nudge/dismiss not in POST_ROUTES")


if __name__ == "__main__":
    unittest.main()
