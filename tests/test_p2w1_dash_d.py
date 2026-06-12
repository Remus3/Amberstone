# arch: deep-audit cycle 8 P2 W1 dashboard slice D regression tests | section=tests | frozen=no
"""Regression tests for deep-audit cycle 8 slice D (DS dashboard routes).

One test class per fixed behavior; every test was written FAILING first
against the pre-fix route code (TDD). API surfaces verified before writing:

  * routes_ds_statcheck._serve_ds_statcheck / _reset_caches / _load_engine
    (dashboard/routes_ds_statcheck.py:193 / 64 / 72)
  * routes_ds_combo._serve_ds_combo / _parse_float / _parse_level
    (dashboard/routes_ds_combo.py:331 / 165 / 154)
  * routes_ds_knobs._serve_ds_knobs / _parse_float / _parse_budget
    (dashboard/routes_ds_knobs.py:289 / 149 / 162)
  * routes_ds_relscore._serve_ds_relscore (dashboard/routes_ds_relscore.py:214)
  * routes_ds_matchup._serve_ds_matchup / _compute
    (dashboard/routes_ds_matchup.py:208 / 156)
  * routes_ds_profile._serve_ds_profile / _compute
    (dashboard/routes_ds_profile.py:385 / 366)
  * routes_spike_curve._serve_spike_curve / _load_snapshot
    (dashboard/routes_spike_curve.py:422 / 146)
  * routes_damage_mix._serve_damage_mix (dashboard/routes_damage_mix.py:60);
    DataSnapshot.load (agents/daemon_slayer/data_loader.py:67)
  * routes_archetype._serve_archetype_post + module-level
    save_archetype_pick import (dashboard/routes_archetype.py:71 / 33)
  * stats.clamp_level RAISES on out-of-range (agents/daemon_slayer/stats.py:126)

Covers:
  * statcheck - level clamped (out-of-range no longer mislabeled as
    "unknown champion"); level=inf no longer crashes the handler
    (OverflowError escaped pre-fix); nan/inf floats rejected; 503 bodies
    no longer leak raw exception text.
  * ds-combo - mode uppercased (lowercase aram silently skipped the ARAM
    multiplier pre-fix); inf target stat / inf level no longer 5xx.
  * ds-knobs - nan override no longer emits NaN JSON (browser JSON.parse
    rejects it); budget=inf / level=inf no longer 500.
  * ds-relscore - level=inf no longer 500.
  * ds-matchup / ds-profile / spike-curve - 503 bodies carry a generic
    degraded-mode message, never raw exception text.
  * damage-mix - DataSnapshot memoized (was re-loaded from disk per request).
  * archetype POST - 500 body no longer leaks the raw save exception.

No asyncio anywhere. ASCII only. Live DS snapshot assumed present (same
contract as tests/test_routes_ds_statcheck.py and siblings).
"""
from __future__ import annotations

import json
import unittest
from typing import Any, Optional

from dashboard import routes_archetype
from dashboard import routes_damage_mix
from dashboard import routes_ds_combo
from dashboard import routes_ds_knobs
from dashboard import routes_ds_matchup
from dashboard import routes_ds_profile
from dashboard import routes_ds_relscore
from dashboard import routes_ds_statcheck
from dashboard import routes_spike_curve

_LEAK_TOKEN = "secret-detail-xyz-C-Users-path"


class StubHandler:
    """Sibling-test _send-style stub (mirrors tests/test_routes_ds_knobs.py)."""

    def __init__(self, path: str = ""):
        self.path = path
        self.last_status: Optional[int] = None
        self.last_body: Optional[bytes] = None
        self.last_ct: Optional[str] = None

    def _send(self, status, body, content_type, cache_control=None):
        self.last_status = status
        self.last_body = body
        self.last_ct = content_type

    def parsed(self) -> dict:
        return json.loads(self.last_body.decode("utf-8")) if self.last_body else {}


class RawHandler:
    """send_response-style stub for routes_ds_statcheck's private _send
    (mirrors tests/test_routes_ds_statcheck.py _FakeHandler)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.chunks: list[bytes] = []
        self._status: Optional[int] = None
        self._headers: dict[str, str] = {}

    def send_response(self, code: int) -> None:
        self._status = code

    def send_header(self, k: str, v: str) -> None:
        self._headers[k] = v

    def end_headers(self) -> None:
        pass

    @property
    def wfile(self) -> Any:
        return self

    def write(self, b: bytes) -> None:
        self.chunks.append(b)

    def parsed(self) -> dict:
        raw = b"".join(self.chunks)
        return json.loads(raw.decode("utf-8")) if raw else {}


def _statcheck(path: str) -> RawHandler:
    h = RawHandler(path)
    routes_ds_statcheck._serve_ds_statcheck(h)
    return h


class StatcheckLevelClampTests(unittest.TestCase):
    def setUp(self) -> None:
        routes_ds_statcheck._reset_caches()

    def test_out_of_range_level_clamps_not_unknown_champion(self) -> None:
        """Pre-fix: level=25 reached clamp_level which RAISES ValueError,
        misclassified by the (KeyError, ValueError) handler as
        'unknown champion: Caitlyn'. Post-fix the route clamps to 18."""
        h = _statcheck("/api/ds-statcheck?champion=Caitlyn&level=25")
        body = h.parsed()
        self.assertEqual(h._status, 200)
        self.assertTrue(body.get("ok"), body)
        self.assertEqual(body["inputs"]["level"], 18)

    def test_negative_level_clamps_to_floor(self) -> None:
        h = _statcheck("/api/ds-statcheck?champion=Caitlyn&level=-5")
        body = h.parsed()
        self.assertEqual(h._status, 200)
        self.assertTrue(body.get("ok"), body)
        self.assertEqual(body["inputs"]["level"], 1)

    def test_inf_level_does_not_crash_handler(self) -> None:
        """Pre-fix: int(float('inf')) raised OverflowError which escaped the
        handler entirely (no outer try) - the client got a dropped
        connection. Post-fix: parsed as garbage -> default 11."""
        h = _statcheck("/api/ds-statcheck?champion=Caitlyn&level=inf")
        self.assertEqual(h._status, 200)
        self.assertTrue(h.parsed().get("ok"), h.parsed())

    def test_nan_target_stat_is_rejected_not_cached_forever(self) -> None:
        """Pre-fix: _as_float('nan') returned nan -> auto-resolve skipped,
        NaN flowed into engine math + JSON. Post-fix: non-finite -> None
        -> auto-resolved curve (source echoes 'auto')."""
        h = _statcheck("/api/ds-statcheck?champion=Caitlyn&target_armor=nan")
        body = h.parsed()
        self.assertEqual(h._status, 200)
        self.assertTrue(body.get("ok"), body)
        self.assertEqual(body["inputs"]["armor_source"], "auto")
        self.assertNotIn(b"NaN", b"".join(h.chunks))


class StatcheckErrorLeakTests(unittest.TestCase):
    def setUp(self) -> None:
        routes_ds_statcheck._reset_caches()
        self._orig_load = routes_ds_statcheck._load_engine

    def tearDown(self) -> None:
        routes_ds_statcheck._load_engine = self._orig_load
        routes_ds_statcheck._reset_caches()

    def test_engine_load_failure_does_not_leak_exception_text(self) -> None:
        def _boom():
            raise RuntimeError(_LEAK_TOKEN)
        routes_ds_statcheck._load_engine = _boom
        h = _statcheck("/api/ds-statcheck?champion=Caitlyn")
        body = h.parsed()
        self.assertEqual(h._status, 503)
        self.assertNotIn(_LEAK_TOKEN, json.dumps(body))

    def test_compute_failure_does_not_leak_exception_text(self) -> None:
        def _raiser(*a, **kw):
            raise RuntimeError(_LEAK_TOKEN)
        routes_ds_statcheck._load_engine = lambda: (object(), _raiser)
        h = _statcheck("/api/ds-statcheck?champion=Caitlyn")
        body = h.parsed()
        self.assertEqual(h._status, 503)
        self.assertNotIn(_LEAK_TOKEN, json.dumps(body))


class ComboModeAndFiniteTests(unittest.TestCase):
    def setUp(self) -> None:
        routes_ds_combo._reset_caches()

    def _do(self, path: str) -> StubHandler:
        h = StubHandler(path)
        routes_ds_combo._serve_ds_combo(h)
        return h

    def test_lowercase_mode_is_uppercased(self) -> None:
        """Pre-fix the route passed mode verbatim; the engine compares
        mode == 'ARAM' case-sensitively (agents/daemon_slayer/burst.py:539)
        so mode=aram silently skipped the ARAM multiplier."""
        h = self._do("/api/ds-combo?champion=Lux&seq=Q&mode=aram")
        body = h.parsed()
        self.assertEqual(h.last_status, 200)
        self.assertEqual(body.get("mode"), "ARAM", body)

    def test_inf_target_hp_falls_to_default_not_503(self) -> None:
        """Pre-fix: inf passed _parse_float's v >= 0 gate, then
        math.ceil(inf/x) in _compute_ttk raised OverflowError -> 503."""
        h = self._do("/api/ds-combo?champion=Lux&seq=Q&target_max_hp=inf")
        self.assertEqual(h.last_status, 200)

    def test_inf_level_falls_to_default_not_500(self) -> None:
        """Pre-fix: int(float('inf')) OverflowError was not in
        _parse_level's except tuple -> outer 500."""
        h = self._do("/api/ds-combo?champion=Lux&seq=Q&level=inf")
        body = h.parsed()
        self.assertEqual(h.last_status, 200)
        self.assertEqual(body.get("level"), 11, body)


class KnobsFiniteTests(unittest.TestCase):
    def setUp(self) -> None:
        routes_ds_knobs._reset_caches()

    def _do(self, path: str) -> StubHandler:
        h = StubHandler(path)
        routes_ds_knobs._serve_ds_knobs(h)
        return h

    def test_nan_armor_override_is_rejected_no_nan_json(self) -> None:
        """Pre-fix: nan was accepted as an override -> the response body
        contained the literal 'NaN' token (json.dumps allow_nan default),
        which browser JSON.parse rejects -> dead panel."""
        h = self._do("/api/ds-knobs?champion=Caitlyn&target_armor=nan")
        body = h.parsed()
        self.assertEqual(h.last_status, 200)
        self.assertEqual(body["knobs"]["armor_source"], "auto", body)
        self.assertNotIn(b"NaN", h.last_body or b"")

    def test_inf_budget_falls_to_uncapped_not_500(self) -> None:
        """Pre-fix: int(float('inf')) OverflowError was not in
        _parse_budget's except tuple -> outer 500."""
        h = self._do("/api/ds-knobs?champion=Caitlyn&budget=inf")
        body = h.parsed()
        self.assertEqual(h.last_status, 200)
        self.assertIsNone(body["knobs"]["budget"], body)

    def test_inf_level_falls_to_default_not_500(self) -> None:
        h = self._do("/api/ds-knobs?champion=Caitlyn&level=inf")
        body = h.parsed()
        self.assertEqual(h.last_status, 200)
        self.assertEqual(body["knobs"]["level"], 11, body)


class RelscoreFiniteTests(unittest.TestCase):
    def setUp(self) -> None:
        routes_ds_relscore._reset_caches()

    def test_inf_level_falls_to_default_not_500(self) -> None:
        h = StubHandler("/api/ds-relscore?champion=Caitlyn&level=inf")
        routes_ds_relscore._serve_ds_relscore(h)
        body = h.parsed()
        self.assertEqual(h.last_status, 200)
        self.assertEqual(body["target"]["level"], 11, body)


class MatchupErrorLeakTests(unittest.TestCase):
    def setUp(self) -> None:
        routes_ds_matchup._reset_caches()
        self._orig = routes_ds_matchup._compute

    def tearDown(self) -> None:
        routes_ds_matchup._compute = self._orig
        routes_ds_matchup._reset_caches()

    def test_compute_failure_does_not_leak_exception_text(self) -> None:
        def _boom(*a, **kw):
            raise RuntimeError(_LEAK_TOKEN)
        routes_ds_matchup._compute = _boom
        h = StubHandler("/api/ds-matchup?champ_a=Vayne&champ_b=Lux")
        routes_ds_matchup._serve_ds_matchup(h)
        body = h.parsed()
        self.assertEqual(h.last_status, 503)
        self.assertNotIn(_LEAK_TOKEN, json.dumps(body))


class ProfileErrorLeakTests(unittest.TestCase):
    def setUp(self) -> None:
        routes_ds_profile._reset_caches()
        self._orig = routes_ds_profile._compute

    def tearDown(self) -> None:
        routes_ds_profile._compute = self._orig
        routes_ds_profile._reset_caches()

    def test_compute_failure_does_not_leak_exception_text(self) -> None:
        def _boom(*a, **kw):
            raise RuntimeError(_LEAK_TOKEN)
        routes_ds_profile._compute = _boom
        h = StubHandler("/api/ds-profile?champion=Vayne")
        routes_ds_profile._serve_ds_profile(h)
        body = h.parsed()
        self.assertEqual(h.last_status, 503)
        self.assertNotIn(_LEAK_TOKEN, json.dumps(body))


class SpikeCurveErrorLeakTests(unittest.TestCase):
    _ALLY = "1,86,51,99,67"
    _ENEMY = "103,64,11,32,25"

    def setUp(self) -> None:
        routes_spike_curve._reset_caches()
        self._orig = routes_spike_curve._load_snapshot

    def tearDown(self) -> None:
        routes_spike_curve._load_snapshot = self._orig
        routes_spike_curve._reset_caches()

    def test_snapshot_failure_does_not_leak_exception_text(self) -> None:
        def _boom():
            raise RuntimeError(_LEAK_TOKEN)
        routes_spike_curve._load_snapshot = _boom
        h = StubHandler(
            f"/api/spike-curve?ally={self._ALLY}&enemy={self._ENEMY}&mode=SR")
        routes_spike_curve._serve_spike_curve(h)
        body = h.parsed()
        self.assertEqual(h.last_status, 503)
        self.assertNotIn(_LEAK_TOKEN, json.dumps(body))


class DamageMixSnapshotMemoTests(unittest.TestCase):
    def test_snapshot_loaded_once_across_requests(self) -> None:
        """Pre-fix the route called DataSnapshot.load() (a multi-file JSON
        parse) on EVERY request. Post-fix it memoizes at module scope like
        every sibling (routes_ds_knobs._get_snapshot pattern)."""
        from agents.daemon_slayer.data_loader import DataSnapshot

        getattr(routes_damage_mix, "_reset_caches", lambda: None)()
        calls = {"n": 0}
        orig = DataSnapshot.load.__func__

        def _counting(cls, *a, **kw):
            calls["n"] += 1
            return orig(cls, *a, **kw)

        DataSnapshot.load = classmethod(_counting)
        try:
            for _ in range(2):
                h = StubHandler("/api/damage-mix?champ_id=86&items=3071&level=11")
                routes_damage_mix._serve_damage_mix(h)
                self.assertEqual(h.last_status, 200, h.parsed())
        finally:
            DataSnapshot.load = classmethod(orig)
        self.assertEqual(calls["n"], 1,
                         f"snapshot loaded {calls['n']}x for 2 requests")


class ArchetypeSaveErrorLeakTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig = routes_archetype.save_archetype_pick

    def tearDown(self) -> None:
        routes_archetype.save_archetype_pick = self._orig

    def test_save_failure_does_not_leak_exception_text(self) -> None:
        """Pre-fix the 500 body was the raw UNBOUNDED str(exc) (could carry
        file paths from an OSError). Post-fix: generic message; raw stays
        in the log."""
        def _boom(**kw):
            raise RuntimeError(_LEAK_TOKEN)
        routes_archetype.save_archetype_pick = _boom
        h = StubHandler("/api/cs-archetype-pick")
        routes_archetype._serve_archetype_post(
            h, {"champion": "Lux", "primary": "mage"})
        body = h.parsed()
        self.assertEqual(h.last_status, 500)
        self.assertNotIn(_LEAK_TOKEN, json.dumps(body))


class AsciiHygieneTests(unittest.TestCase):
    def test_this_file_is_ascii(self) -> None:
        import pathlib
        raw = pathlib.Path(__file__).read_bytes()
        self.assertTrue(all(b < 128 for b in raw), "non-ASCII byte in test file")


if __name__ == "__main__":
    unittest.main()
