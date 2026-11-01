"""RM-1255 (first slice): integer query-parameter 400s never echo the caller's value.

Before the fix seven dashboard routes built their 400 text from the
caller's own value:

- ``/api/duration-winrate``, ``/api/op-score-curve``, ``/api/perf-curve``
  and ``/api/player-profile``: ``champion must be an integer, got 'zz'``
  (a full, unclipped repr of whatever was sent);
- ``/api/player-profile``: ``window must be an integer, got 'zz'`` and
  ``window must be 1..100, got 987654``;
- ``/api/patch-impact``: ``top must be an integer, got 'zz'`` (same for
  ``min_games``) and ``top must be between 1 and 50, got 987654``;
- ``/api/playstyle-labels``: ``queue must be integers, got 'zz'`` and
  ``min_games must be an integer, got 'zz'``;
- ``/api/ward-heat``: ``window_s must be numeric, got 'zz'`` and
  ``window_s must be in [5, 600], got 987654.0``.

That is the RM-1233 echo (``/api/ban-suggest``), which now names only the
parameter and the expected shape. Acceptance pinned here: every one of
these 400s names the parameter and the expected shape, the distinctive
junk the caller sent is absent from the raw body, and two different junk
values give byte-identical bodies. Each case is driven through the route
entry point with its compute patched, so a value that slipped past
validation would show up as a 200, never as a fixture-dependent 503.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from dashboard import routes_duration_winrate as rdw
from dashboard import routes_op_score as ros
from dashboard import routes_patch_impact as rpi
from dashboard import routes_perf_curve as rpc
from dashboard import routes_player_profile as rpp
from dashboard import routes_playstyle_labels as rpl
from dashboard import routes_ward_heat as rwh


class _Harness:
    def __init__(self, path: str, qs: str):
        self.path = f"{path}?{qs}"
        self.sent_status = None
        self.sent_body = b""

    def _send(self, status, body, content_type):
        self.sent_status = status
        self.sent_body = body


_OK = {"ok": True}

# route key -> (module, url path, entry point name, compute target to patch)
_ROUTES = {
    "duration": (rdw, "/api/duration-winrate", "_serve_duration_winrate",
                 "dashboard.routes_duration_winrate.duration_winrate."
                 "compute_duration_winrate"),
    "op_score": (ros, "/api/op-score-curve", "_serve_op_score",
                 "dashboard.routes_op_score.op_score_curve."
                 "compute_op_score_curve"),
    "perf": (rpc, "/api/perf-curve", "_serve_perf_curve",
             "dashboard.routes_perf_curve.perf_curve.compute_perf_curve"),
    "profile": (rpp, "/api/player-profile", "_serve_player_profile",
                "dashboard.routes_player_profile._compute"),
    "patch": (rpi, "/api/patch-impact", "_serve_patch_impact",
              "dashboard.routes_patch_impact.patch_impact."
              "compute_patch_impact"),
    "playstyle": (rpl, "/api/playstyle-labels", "_serve_playstyle_labels",
                  "dashboard.routes_playstyle_labels.playstyle_labels."
                  "compute_playstyle_labels"),
    "ward": (rwh, "/api/ward-heat", "_serve_ward_heat",
             "dashboard.routes_ward_heat._build_payload"),
}

# Literal copies, not imports of module constants, so a message that
# regains the caller's value fails here.
_CHAMP = "champion must be an integer"

# (route key, query string, junk the body must not hold, exact error text)
_CASES = [
    ("duration", "champion=zzJUNKzz", "zzJUNKzz", _CHAMP),
    ("op_score", "champion=zzJUNKzz", "zzJUNKzz", _CHAMP),
    ("perf", "champion=zzJUNKzz", "zzJUNKzz", _CHAMP),
    ("profile", "champion=zzJUNKzz", "zzJUNKzz", _CHAMP),
    # a long junk value was echoed whole (no clip at all)
    ("duration", "champion=" + "Q" * 300, "QQQQQQ", _CHAMP),
    ("profile", "window=zzJUNKzz", "zzJUNKzz", "window must be an integer"),
    # out of range: the parsed integer was echoed back
    ("profile", "window=987654", "987654", "window must be 1..100"),
    ("profile", "window=-987654", "987654", "window must be 1..100"),
    ("patch", "top=zzJUNKzz", "zzJUNKzz", "top must be an integer"),
    ("patch", "min_games=zzJUNKzz", "zzJUNKzz",
     "min_games must be an integer"),
    ("patch", "top=987654", "987654", "top must be between 1 and 50"),
    ("patch", "min_games=987654", "987654",
     "min_games must be between 1 and 500"),
    ("playstyle", "queue=420,zzJUNKzz", "zzJUNKzz",
     "queue must be comma-separated integers"),
    ("playstyle", "min_games=zzJUNKzz", "zzJUNKzz",
     "min_games must be an integer"),
    ("ward", "window_s=zzJUNKzz", "zzJUNKzz", "window_s must be numeric"),
    ("ward", "window_s=987654", "987654", "window_s must be in [5, 600]"),
    ("ward", "window_s=-987654.5", "987654", "window_s must be in [5, 600]"),
]


def _serve(route: str, qs: str) -> _Harness:
    mod, path, entry, compute = _ROUTES[route]
    mod._reset_caches()
    h = _Harness(path, qs)
    try:
        with patch(compute, return_value=dict(_OK)) as comp, \
                patch("dashboard.routes_patch_impact.patch_impact."
                      "available_patches", return_value=["16.13.1"]):
            getattr(mod, entry)(h)
    finally:
        mod._reset_caches()
    comp.assert_not_called()
    return h


class NoCallerValueEchoTests(unittest.TestCase):
    def test_each_400_names_the_shape_and_never_the_value(self):
        for route, qs, junk, expected in _CASES:
            with self.subTest(route=route, qs=qs[:40]):
                h = _serve(route, qs)
                self.assertEqual(h.sent_status, 400)
                raw = h.sent_body.decode("utf-8")
                self.assertNotIn(junk, raw)
                self.assertEqual(json.loads(raw),
                                 {"ok": False, "error": expected})

    def test_two_different_junk_values_give_identical_bodies(self):
        pairs = [
            ("duration", "champion=aaJUNK", "champion=bbOTHER"),
            ("op_score", "champion=aaJUNK", "champion=bbOTHER"),
            ("perf", "champion=aaJUNK", "champion=bbOTHER"),
            ("profile", "champion=aaJUNK", "champion=bbOTHER"),
            ("profile", "window=aaJUNK", "window=bbOTHER"),
            ("profile", "window=101", "window=555555"),
            ("patch", "top=aaJUNK", "top=bbOTHER"),
            ("patch", "top=51", "top=555555"),
            ("patch", "min_games=aaJUNK", "min_games=bbOTHER"),
            ("patch", "min_games=0", "min_games=555555"),
            ("playstyle", "queue=aaJUNK", "queue=bbOTHER"),
            ("playstyle", "min_games=aaJUNK", "min_games=bbOTHER"),
            ("ward", "window_s=aaJUNK", "window_s=bbOTHER"),
            ("ward", "window_s=601", "window_s=555555"),
        ]
        for route, qs_a, qs_b in pairs:
            with self.subTest(route=route, a=qs_a, b=qs_b):
                a = _serve(route, qs_a)
                b = _serve(route, qs_b)
                self.assertEqual(a.sent_status, 400)
                self.assertEqual(a.sent_body, b.sent_body)

    def test_valid_values_still_pass(self):
        for route, qs in [("duration", "champion=64"),
                          ("op_score", "champion=64"),
                          ("perf", "champion=64"),
                          ("profile", "champion=64&window=20"),
                          ("patch", "top=10&min_games=5"),
                          ("playstyle", "queue=420,450&min_games=5"),
                          ("ward", "window_s=60")]:
            with self.subTest(route=route):
                mod, path, entry, compute = _ROUTES[route]
                mod._reset_caches()
                h = _Harness(path, qs)
                try:
                    with patch(compute, return_value=dict(_OK)) as comp, \
                            patch("dashboard.routes_patch_impact."
                                  "patch_impact.available_patches",
                                  return_value=["16.13.1"]):
                        getattr(mod, entry)(h)
                finally:
                    mod._reset_caches()
                self.assertEqual(h.sent_status, 200)
                comp.assert_called_once()


if __name__ == "__main__":
    unittest.main()
