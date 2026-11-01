"""RM-1328: a bad integer in a DS POST body falls to the default, never a 500.

The POST body reaches the handlers through ``json.loads``, which accepts
the bare ``NaN`` / ``Infinity`` / ``-Infinity`` tokens and turns ``1e400``
into inf. Measured on the base before the fix:

- ``_serve_ds_preview_post`` parsed ``level = int(payload.get("level") or 6)``
  outside any narrow catch. ``Infinity`` raised OverflowError, ``NaN`` and
  ``"abc"`` raised ValueError, ``[]``-shaped truthy values (``[1]``, ``{"a": 1}``)
  raised TypeError; all of them fell to the outer ``except Exception`` and the
  preview answered 500.
- ``_serve_build_order_post`` (the same-root sibling in the same module) did
  the same for ``level`` (default 11) and ``slots`` (default 6).
- ``_serve_console_error_post`` did the same for ``lineno`` / ``colno``
  (default 0), so a client error report with a non-integer line number was
  dropped as a 500 instead of logged.

Choice recorded: FALL TO THE DEFAULT, not a 400. Every in-tree caller sends a
JSON integer (web/js/panels/active_match.js, champ_select.js, build_order.js
and dashboard/routes_build_plan.py's composed seed calls), and the in-tree
precedent for the same field is a fall-to-default:
``dashboard/routes_build_plan.py`` already wraps its ``level`` parse in a
``(TypeError, ValueError, OverflowError)`` catch that falls to 11, and
``dashboard/routes_ds_sweep.py`` ``_parse_int`` falls to its default. A JSON
boolean is not a level either, so it also takes the default (``int(True)``
used to read as level 1).

Client half: ``core/daemon_slayer_client.py`` ``rank_enchanter_for``
forwarded a non-finite ``caster_missing_hp_pct`` (NaN is truthy) and both
``rank_enchanter_for`` and ``hps_for`` forwarded a non-finite
``targets_per_proc_override``. The engine's ``_opt_float`` /
``_opt_targets_override`` answer 400 to a non-finite value, ``_post_json``
maps that to None, and the caller reads it as "engine unavailable" - the whole
ranking goes dark for one bad optional seam. The client now drops a non-finite
or unparseable optional seam, so the engine default applies.
"""
from __future__ import annotations

import json
import math
import unittest
from unittest import mock

from core import daemon_slayer_client as dsc
from dashboard import routes_state
from dashboard.routes_state import (
    _serve_build_order_post,
    _serve_console_error_post,
    _serve_ds_preview_post,
)

# Raw JSON texts, parsed the way the dispatcher parses a POST body.
_BAD_INT_TOKENS = ("NaN", "Infinity", "-Infinity", "1e400", '"abc"', '"6.5"',
                   "[1]", '{"a": 1}', "true")
_TARGET = ('"target_armor": 50, "target_mr": 40, "target_max_hp": 2000, '
           '"target_bonus_hp": 0')


class _Handler:
    def __init__(self) -> None:
        self.status = 0
        self.body = b""
        self.headers: dict = {}

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.status = status
        self.body = body


def _ok_preview() -> dict:
    return {"ok": True, "scorer": "dps", "archetype": "carry",
            "ranked": [], "fell_back": False}


class _FakePlan:
    def to_dict(self) -> dict:
        return {"order": []}


class DsPreviewLevelTests(unittest.TestCase):
    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    def test_bad_level_falls_to_default_6_never_500(self, mock_disp):
        mock_disp.return_value = _ok_preview()
        for tok in _BAD_INT_TOKENS:
            with self.subTest(tok=tok):
                mock_disp.reset_mock()
                body = json.loads(
                    '{"champion": "Ahri", "mode": "SR", "archetype": "carry", '
                    f'"level": {tok}, {_TARGET}}}')
                h = _Handler()
                _serve_ds_preview_post(h, body)
                self.assertEqual(h.status, 200, h.body[:200])
                self.assertEqual(mock_disp.call_count, 1)
                self.assertEqual(mock_disp.call_args.kwargs["level"], 6)

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    def test_good_level_still_parses_and_clamps(self, mock_disp):
        # Positive control: the guard must not swallow a legal value.
        mock_disp.return_value = _ok_preview()
        for raw, want in (("9", 9), ('"12"', 12), ("40", 18), ("-3", 1),
                          ("7.9", 7), ("0", 6), ("null", 6)):
            with self.subTest(raw=raw):
                body = json.loads(
                    '{"champion": "Ahri", "mode": "SR", "archetype": "carry", '
                    f'"level": {raw}, {_TARGET}}}')
                h = _Handler()
                _serve_ds_preview_post(h, body)
                self.assertEqual(h.status, 200, h.body[:200])
                self.assertEqual(mock_disp.call_args.kwargs["level"], want)


class BuildOrderLevelSlotsTests(unittest.TestCase):
    @mock.patch("core.build_order.plan_build_order")
    def test_bad_level_and_slots_fall_to_defaults_never_500(self, mock_plan):
        mock_plan.return_value = _FakePlan()
        for key, default in (("level", 11), ("slots", 6)):
            for tok in _BAD_INT_TOKENS:
                with self.subTest(key=key, tok=tok):
                    mock_plan.reset_mock()
                    body = json.loads(
                        '{"champion": "Ahri", "mode": "SR", '
                        f'"archetype": "carry", "{key}": {tok}, {_TARGET}}}')
                    h = _Handler()
                    _serve_build_order_post(h, body)
                    self.assertEqual(h.status, 200, h.body[:200])
                    self.assertEqual(mock_plan.call_count, 1)
                    self.assertEqual(mock_plan.call_args.kwargs[key], default)

    @mock.patch("core.build_order.plan_build_order")
    def test_good_level_and_slots_still_parse_and_clamp(self, mock_plan):
        mock_plan.return_value = _FakePlan()
        body = json.loads(
            '{"champion": "Ahri", "mode": "SR", "archetype": "carry", '
            f'"level": 14, "slots": 9, {_TARGET}}}')
        h = _Handler()
        _serve_build_order_post(h, body)
        self.assertEqual(h.status, 200, h.body[:200])
        self.assertEqual(mock_plan.call_args.kwargs["level"], 14)
        self.assertEqual(mock_plan.call_args.kwargs["slots"], 6)


class ConsoleErrorLinenoTests(unittest.TestCase):
    # The route throttles to 10 Hz across all clients; each call here
    # resets the clock so the throttle never answers in place of the parse.
    def setUp(self) -> None:
        p = mock.patch.object(routes_state, "_CE_LAST_TS", 0.0)
        p.start()
        self.addCleanup(p.stop)

    def test_bad_lineno_colno_still_logs_never_500(self):
        for key in ("lineno", "colno"):
            for tok in _BAD_INT_TOKENS:
                with self.subTest(key=key, tok=tok):
                    body = json.loads(
                        f'{{"kind": "error", "message": "m", "{key}": {tok}}}')
                    h = _Handler()
                    routes_state._CE_LAST_TS = 0.0
                    with self.assertLogs("rc", level="WARNING") as cm:
                        _serve_console_error_post(h, body)
                    self.assertEqual(h.status, 200, h.body[:200])
                    self.assertTrue(
                        any("client-console" in r for r in cm.output))

    def test_good_lineno_is_logged(self):
        h = _Handler()
        with self.assertLogs("rc", level="WARNING") as cm:
            _serve_console_error_post(
                h, {"kind": "error", "message": "m", "source": "a.js",
                    "lineno": 12, "colno": 7})
        self.assertEqual(h.status, 200)
        self.assertTrue(any("a.js:12:7" in r for r in cm.output), cm.output)


class _CapturePost:
    def __init__(self) -> None:
        self.bodies: list = []

    def __call__(self, path, body, timeout=None):
        self.bodies.append((path, body))
        return None


class ClientOptionalSeamTests(unittest.TestCase):
    _BAD = (float("nan"), float("inf"), float("-inf"), "abc")

    def _enchanter(self, **kw) -> dict:
        cap = _CapturePost()
        with mock.patch.object(dsc, "_post_json", cap):
            dsc.rank_enchanter_for("Soraka", level=11, item_ids=[], **kw)
        self.assertEqual(len(cap.bodies), 1)
        body = cap.bodies[0][1]
        # The wire body must be valid strict JSON.
        json.dumps(body, allow_nan=False)
        return body

    def _hps(self, **kw) -> dict:
        cap = _CapturePost()
        with mock.patch.object(dsc, "_post_json", cap):
            dsc.hps_for("Soraka", level=11, item_ids=[], **kw)
        self.assertEqual(len(cap.bodies), 1)
        body = cap.bodies[0][1]
        json.dumps(body, allow_nan=False)
        return body

    def test_enchanter_drops_non_finite_caster_missing_hp_pct(self):
        for bad in self._BAD:
            with self.subTest(bad=bad):
                body = self._enchanter(caster_missing_hp_pct=bad)
                self.assertNotIn("caster_missing_hp_pct", body)

    def test_enchanter_and_hps_drop_non_finite_targets_override(self):
        for bad in self._BAD:
            with self.subTest(bad=bad):
                self.assertNotIn(
                    "targets_per_proc_override",
                    self._enchanter(targets_per_proc_override=bad))
                self.assertNotIn(
                    "targets_per_proc_override",
                    self._hps(targets_per_proc_override=bad))

    def test_finite_optional_seams_still_forward(self):
        # Positive control: the guard must not drop a legal value.
        body = self._enchanter(caster_missing_hp_pct=0.4,
                               targets_per_proc_override=1)
        self.assertEqual(body["caster_missing_hp_pct"], 0.4)
        self.assertEqual(body["targets_per_proc_override"], 1.0)
        self.assertTrue(math.isfinite(body["caster_missing_hp_pct"]))
        self.assertNotIn("caster_missing_hp_pct",
                         self._enchanter(caster_missing_hp_pct=0.0))
        self.assertEqual(
            self._hps(targets_per_proc_override="2")["targets_per_proc_override"],
            2.0)


if __name__ == "__main__":
    unittest.main()
