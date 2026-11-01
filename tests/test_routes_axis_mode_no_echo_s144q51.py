"""RM-1255 (residue slice): the axis / mode 400s never echo the caller's value.

Before the fix two dashboard GET routes built their 400 text from an
unclipped repr of the caller's own query value:

- ``/api/ds-sweep``: ``unsupported axis 'zz...'`` (the lower-cased raw
  ``axis`` value, any length);
- ``/api/spike-curve``: ``unsupported mode 'ZZ...'`` (the upper-cased raw
  ``mode`` value, any length).

That is the RM-1233 echo the first slice (``1836a1923``) removed from seven
integer routes. Acceptance pinned here: each 400 carries a fixed error
text plus its fixed ``supported`` list, the distinctive junk the caller
sent is absent from the raw body (in any case), and two different junk
values give byte-identical bodies. A valid value still reaches the
compute, which is patched, so a value that slipped past validation would
show up as a 200, never as a fixture-dependent 503.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from dashboard import routes_ds_sweep as rds
from dashboard import routes_spike_curve as rsc


class _Harness:
    def __init__(self, path: str):
        self.path = path
        self.sent_status = None
        self.sent_body = b""

    def _send(self, status, body, content_type):
        self.sent_status = status
        self.sent_body = body


# Literal copies, not imports of module constants, so a message that
# regains the caller's value fails here.
_AXIS_ERR = "unsupported axis"
_AXIS_SUPPORTED = ["armor", "mr", "level"]
_MODE_ERR = "unsupported mode"

_JUNK = ("zzqjunkvalue", "QxJunk<script>9", "yy" * 300, "a'b\"c")

_TEAM = "1,2,3,4,5"


def _sweep(axis: str) -> _Harness:
    h = _Harness(f"/api/ds-sweep?champion=Caitlyn&axis={axis}")
    with patch.object(rds, "_resolve_champion", return_value="Caitlyn"), \
            patch.object(rds, "_compute", return_value={"ok": True}):
        rds._reset_caches()
        rds._serve_ds_sweep(h)
    return h


def _spike(mode: str) -> _Harness:
    h = _Harness(f"/api/spike-curve?ally={_TEAM}&enemy={_TEAM}&mode={mode}")
    # A valid mode goes on to the id->slug map; an empty map is a fixed
    # 503 that proves validation passed without touching the DS engine.
    with patch.object(rsc, "_load_id_to_slug", return_value={}):
        rsc._serve_spike_curve(h)
    return h


def _assert_no_junk(tc: unittest.TestCase, body: bytes, junk: str) -> None:
    low = body.decode("utf-8", "replace").lower()
    tc.assertNotIn(junk.lower(), low)
    # json.dumps escapes a quote; check the escaped spelling too.
    tc.assertNotIn(json.dumps(junk)[1:-1].lower(), low)


class DsSweepAxisNoEchoTests(unittest.TestCase):
    def test_bad_axis_is_fixed_400(self) -> None:
        for junk in _JUNK:
            with self.subTest(junk=junk[:20]):
                h = _sweep(junk)
                self.assertEqual(h.sent_status, 400)
                body = json.loads(h.sent_body)
                self.assertEqual(body["ok"], False)
                self.assertEqual(body["error"], _AXIS_ERR)
                self.assertEqual(body["supported"], _AXIS_SUPPORTED)
                _assert_no_junk(self, h.sent_body, junk)

    def test_two_junk_values_give_identical_bodies(self) -> None:
        self.assertEqual(_sweep("zzqjunkvalue").sent_body,
                         _sweep("other_axis_x").sent_body)

    def test_valid_axes_still_reach_compute(self) -> None:
        for axis in ("armor", "MR", "level", "target_armor", "target_mr"):
            with self.subTest(axis=axis):
                self.assertEqual(_sweep(axis).sent_status, 200)


class SpikeCurveModeNoEchoTests(unittest.TestCase):
    def test_bad_mode_is_fixed_400(self) -> None:
        for junk in _JUNK:
            with self.subTest(junk=junk[:20]):
                h = _spike(junk)
                self.assertEqual(h.sent_status, 400)
                body = json.loads(h.sent_body)
                self.assertEqual(body["ok"], False)
                self.assertEqual(body["error"], _MODE_ERR)
                self.assertEqual(body["supported"],
                                 sorted(rsc._MODE_PROFILE.keys()))
                self.assertIn("SR", body["supported"])
                _assert_no_junk(self, h.sent_body, junk)

    def test_two_junk_values_give_identical_bodies(self) -> None:
        self.assertEqual(_spike("zzqjunkvalue").sent_body,
                         _spike("OTHERMODEX").sent_body)

    def test_valid_modes_pass_validation(self) -> None:
        for mode in sorted(rsc._MODE_PROFILE.keys()) + ["sr", ""]:
            with self.subTest(mode=mode):
                h = _spike(mode)
                self.assertEqual(h.sent_status, 503)
                self.assertEqual(json.loads(h.sent_body)["error"],
                                 "champion id->slug map unavailable")


if __name__ == "__main__":
    unittest.main()
