"""Contract tests for /api/coach-choice POST endpoint."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from dashboard import routes_coach_choice as rcc


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


class HappyPath(unittest.TestCase):
    def test_minimum_valid_body_logs_choice(self):
        h = _Handler()
        with mock.patch.object(rcc, "_store") as mk:
            mk.return_value.record_coach_choice.return_value = {
                "type": "coach_choice", "ts_unix": 1234567890.0,
                "choice_key": "A", "choice_label": "Contest",
                "confidence": "mid", "source_tag": "synth", "game_context": {},
            }
            rcc._serve_coach_choice(h, {"choice_key": "A", "choice_label": "Contest"})
        self.assertEqual(h.status, 200)
        self.assertTrue(h.json()["ok"])

    def test_full_body_round_trip(self):
        h = _Handler()
        captured = {}
        def fake_record(**kw):
            captured.update(kw)
            return {"ts_unix": 999.0}
        with mock.patch.object(rcc, "_store") as mk:
            mk.return_value.record_coach_choice.side_effect = fake_record
            rcc._serve_coach_choice(h, {
                "choice_key": "B",
                "choice_label": "Disengage",
                "confidence": "high",
                "source_tag": "archetype",
                "game_context": {"champion": "Lux", "level": 11},
            })
        self.assertEqual(h.status, 200)
        self.assertEqual(captured["choice_key"], "B")
        self.assertEqual(captured["choice_label"], "Disengage")
        self.assertEqual(captured["confidence"], "high")
        self.assertEqual(captured["source_tag"], "archetype")
        self.assertEqual(captured["game_context"], {"champion": "Lux", "level": 11})


class ValidationContract(unittest.TestCase):
    def test_non_dict_body_400(self):
        h = _Handler()
        rcc._serve_coach_choice(h, "not a dict")
        self.assertEqual(h.status, 400)

    def test_missing_choice_key_400(self):
        h = _Handler()
        rcc._serve_coach_choice(h, {"choice_label": "x"})
        self.assertEqual(h.status, 400)

    def test_missing_choice_label_400(self):
        h = _Handler()
        rcc._serve_coach_choice(h, {"choice_key": "A"})
        self.assertEqual(h.status, 400)

    def test_bad_confidence_normalizes_to_mid(self):
        h = _Handler()
        captured = {}
        def fake_record(**kw):
            captured.update(kw)
            return {"ts_unix": 0.0}
        with mock.patch.object(rcc, "_store") as mk:
            mk.return_value.record_coach_choice.side_effect = fake_record
            rcc._serve_coach_choice(h, {
                "choice_key": "A", "choice_label": "x", "confidence": "ULTRA",
            })
        self.assertEqual(h.status, 200)
        self.assertEqual(captured["confidence"], "mid")

    def test_bad_game_context_defaults_to_empty(self):
        h = _Handler()
        captured = {}
        def fake_record(**kw):
            captured.update(kw)
            return {"ts_unix": 0.0}
        with mock.patch.object(rcc, "_store") as mk:
            mk.return_value.record_coach_choice.side_effect = fake_record
            rcc._serve_coach_choice(h, {
                "choice_key": "A", "choice_label": "x", "game_context": "not a dict",
            })
        self.assertEqual(h.status, 200)
        self.assertEqual(captured["game_context"], {})

    def test_choice_key_truncated_to_one_char(self):
        h = _Handler()
        captured = {}
        def fake_record(**kw):
            captured.update(kw)
            return {"ts_unix": 0.0}
        with mock.patch.object(rcc, "_store") as mk:
            mk.return_value.record_coach_choice.side_effect = fake_record
            rcc._serve_coach_choice(h, {
                "choice_key": "AAAA", "choice_label": "x",
            })
        self.assertEqual(captured["choice_key"], "A")


class RouteRegistrationTests(unittest.TestCase):
    def test_coach_choice_route_registered(self):
        matchers = [m for (m, _fn) in rcc.POST_ROUTES]
        self.assertTrue(
            any(m("/api/coach-choice") for m in matchers),
            "/api/coach-choice not in POST_ROUTES",
        )

    def test_coach_choice_bound_to_serve_coach_choice(self):
        for m, fn in rcc.POST_ROUTES:
            if m("/api/coach-choice"):
                self.assertIs(fn, rcc._serve_coach_choice)
                return
        self.fail("route not found")

    def test_dispatch_includes_coach_choice(self):
        from dashboard import _dispatch
        _dispatch._POST_CACHE = None  # force re-gather
        post = _dispatch._gather_post()
        matchers = [m for (m, _fn) in post]
        self.assertTrue(any(m("/api/coach-choice") for m in matchers))


class ServerErrorHandling(unittest.TestCase):
    def test_record_exception_returns_500(self):
        h = _Handler()
        with mock.patch.object(rcc, "_store") as mk:
            mk.return_value.record_coach_choice.side_effect = RuntimeError("disk full")
            rcc._serve_coach_choice(h, {"choice_key": "A", "choice_label": "x"})
        self.assertEqual(h.status, 500)


if __name__ == "__main__":
    unittest.main()
