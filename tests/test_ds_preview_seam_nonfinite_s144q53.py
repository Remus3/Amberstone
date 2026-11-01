"""RM-1326: /api/ds-preview drops a non-finite or overflowing numeric seam.

The POST body reaches ``_serve_ds_preview_post`` through ``json.loads``,
which accepts the bare ``NaN`` / ``Infinity`` / ``-Infinity`` tokens, turns
``1e400`` into inf, and turns a 400-digit integer literal into a Python int
that ``float()`` cannot convert (OverflowError).

Measured on the base before the fix:

- ``enemy_ad_share`` / ``enemy_ap_share`` / ``caster_missing_hp_pct`` parsed
  with ``float(raw)`` under a ``(TypeError, ValueError)`` catch, so NaN and
  inf were forwarded to ``rank_for_primary_archetype``. There the share
  resolver's clamp let NaN through (``nan < 0`` and ``nan > 1`` are both
  False), ``json.dumps`` wrote a ``NaN`` token into the DS request body, and
  the engine's ``0.0 <= enemy_ad_share <= 1.0`` check refuses NaN - the
  preview went dark as "DS engine unavailable".
- a 400-digit integer seam raised OverflowError out of ``float()``, and
  ``cost_ceiling`` = ``Infinity`` raised OverflowError out of ``int()``;
  neither was caught, so the whole preview answered 500.

The contract after the fix is the one the function's docstring already
states for every other seam: an unparseable value is DROPPED (the engine
default is inherited); it never 500s the preview and never reaches the
engine. The resolver half is defence in depth for the other callers of
``_resolve_enemy_shares``: a non-finite share is treated as not supplied.
"""
from __future__ import annotations

import json
import math
import unittest
from unittest import mock

from core.daemon_slayer_client import _resolve_enemy_shares
from dashboard.routes_state import (
    _DS_PREVIEW_SEAM_FLOATS,
    _ds_preview_seam_kwargs,
    _serve_ds_preview_post,
)

# Raw JSON texts, parsed the way the dispatcher parses a POST body.
_FLOAT_ONLY_TOKENS = ("NaN", "Infinity", "-Infinity", "1e400", "-1e400")
_NONFINITE_TOKENS = _FLOAT_ONLY_TOKENS + ("1" + "0" * 400,)


class _Handler:
    def __init__(self) -> None:
        self.status = 0
        self.body = b""

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.status = status
        self.body = body


def _ok_response() -> dict:
    return {"ok": True, "scorer": "dps", "archetype": "carry",
            "ranked": [], "fell_back": False}


class SeamKwargsDropNonFiniteTests(unittest.TestCase):
    def test_float_seams_drop_every_non_finite_token(self):
        for key in _DS_PREVIEW_SEAM_FLOATS:
            for tok in _NONFINITE_TOKENS:
                with self.subTest(key=key, tok=tok):
                    payload = json.loads(f'{{"{key}": {tok}}}')
                    seams = _ds_preview_seam_kwargs(payload)
                    self.assertNotIn(key, seams)

    def test_float_seams_still_forward_a_finite_value(self):
        # Positive control: the guard must not drop a legal value.
        for key in _DS_PREVIEW_SEAM_FLOATS:
            with self.subTest(key=key):
                seams = _ds_preview_seam_kwargs({key: 0.25})
                self.assertEqual(seams.get(key), 0.25)
        self.assertEqual(
            _ds_preview_seam_kwargs({"enemy_ad_share": "0.6"}),
            {"enemy_ad_share": 0.6})

    def test_cost_ceiling_drops_non_finite_and_overflow(self):
        # A 400-digit integer is a legal (finite) int for this int seam, so
        # only the float-only tokens apply here.
        for tok in _FLOAT_ONLY_TOKENS:
            with self.subTest(tok=tok):
                payload = json.loads(f'{{"cost_ceiling": {tok}}}')
                seams = _ds_preview_seam_kwargs(payload)
                self.assertNotIn("cost_ceiling", seams)
        self.assertEqual(_ds_preview_seam_kwargs({"cost_ceiling": 3000}),
                         {"cost_ceiling": 3000})


class DsPreviewRouteEntryTests(unittest.TestCase):
    """Route entry: the body as json.loads hands it over, never a 500."""

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    def test_non_finite_seam_never_reaches_the_engine(self, mock_disp):
        mock_disp.return_value = _ok_response()
        cases = [(k, t) for k in _DS_PREVIEW_SEAM_FLOATS
                 for t in _NONFINITE_TOKENS]
        cases += [("cost_ceiling", t) for t in _FLOAT_ONLY_TOKENS]
        for key, tok in cases:
            with self.subTest(key=key, tok=tok):
                mock_disp.reset_mock()
                body = json.loads(
                    '{"champion": "Ahri", "mode": "SR", "level": 6, '
                    f'"archetype": "carry", "{key}": {tok}}}')
                h = _Handler()
                _serve_ds_preview_post(h, body)
                self.assertEqual(h.status, 200, h.body[:200])
                self.assertEqual(mock_disp.call_count, 1)
                kwargs = mock_disp.call_args.kwargs
                self.assertNotIn(key, kwargs)
                for v in kwargs.values():
                    if isinstance(v, float):
                        self.assertTrue(math.isfinite(v), kwargs)


class ResolveEnemySharesNonFiniteTests(unittest.TestCase):
    """A non-finite share is treated as not supplied, never forwarded."""

    def test_nan_alone_is_the_neutral_split(self):
        nan = float("nan")
        self.assertEqual(_resolve_enemy_shares(nan, None), (0.5, 0.5))
        self.assertEqual(_resolve_enemy_shares(None, nan), (0.5, 0.5))
        self.assertEqual(_resolve_enemy_shares(nan, nan), (0.5, 0.5))

    def test_non_finite_partner_derives_from_the_finite_side(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(bad=bad):
                ad, ap = _resolve_enemy_shares(bad, 0.3)
                self.assertAlmostEqual(ad, 0.7)
                self.assertAlmostEqual(ap, 0.3)
                ad, ap = _resolve_enemy_shares(0.8, bad)
                self.assertAlmostEqual(ad, 0.8)
                self.assertAlmostEqual(ap, 0.2)

    def test_result_is_always_finite_and_engine_legal(self):
        vals = (None, 0.0, 0.4, 1.0, 1.7, -0.2, float("nan"), float("inf"),
                float("-inf"))
        for a in vals:
            for b in vals:
                with self.subTest(a=a, b=b):
                    ad, ap = _resolve_enemy_shares(a, b)
                    self.assertTrue(math.isfinite(ad) and math.isfinite(ap))
                    self.assertTrue(0.0 <= ad <= 1.0 and 0.0 <= ap <= 1.0)
                    self.assertLessEqual(ad + ap, 1.0001)

    def test_finite_inputs_are_unchanged(self):
        # Positive control on the existing rules.
        self.assertEqual(_resolve_enemy_shares(None, None), (0.5, 0.5))
        self.assertEqual(_resolve_enemy_shares(0.77, None), (0.77, 1.0 - 0.77))
        self.assertEqual(_resolve_enemy_shares(0.3, 0.2), (0.3, 0.2))
        self.assertEqual(_resolve_enemy_shares(2.0, None), (1.0, 0.0))


if __name__ == "__main__":
    unittest.main()
