"""Tests for dashboard/routes_spike_curve.py - the /api/spike-curve
backend that powers the UX-research-recommended Spike Curve Sparkline
panel.

Covers:
  * Input validation (must be 5 vs 5; non-int -> 400; bad mode -> 400)
  * Output shape (each of ally/enemy is 41 entries with minute 0..40)
  * Cache hit/miss lifecycle (response cache + per-champ curve cache)
  * Unknown champion id -> 400 with surfaced id list
  * Carry-vs-tank: an all-carry team's spike minute precedes an
    all-tank team's spike minute (the load-bearing 'when does this team
    win fights' signal)
  * Order-insensitive cache key (ally=1,2,3,4,5 vs ally=5,4,3,2,1 same
    cache entry)
"""
from __future__ import annotations

import json
import unittest

from dashboard import routes_spike_curve


class StubHandler:
    """Same shape as test_routes_archetype.StubHandler."""

    def __init__(self, path: str = ""):
        self.path = path
        self.last_status: int | None = None
        self.last_body: bytes | None = None
        self.last_ct: str | None = None

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.last_status = status
        self.last_body = body
        self.last_ct = content_type

    def parsed(self) -> dict:
        if not self.last_body:
            return {}
        return json.loads(self.last_body.decode("utf-8"))


# Known DDragon int ids in the live 16.10.1 snapshot. Used as concrete
# test fixtures; the route validates each against the same map.
JINX = 222
ASHE = 22
CAITLYN = 51
KAISA = 145
VAYNE = 67
MALPHITE = 54
RAMMUS = 33
SEJUANI = 113
ZAC = 154
CHOGATH = 31
GAREN = 86
LUX = 99
SORAKA = 16

CARRY_TEAM = [JINX, ASHE, CAITLYN, KAISA, VAYNE]
TANK_TEAM = [MALPHITE, RAMMUS, SEJUANI, ZAC, CHOGATH]


def _do(handler_path: str) -> StubHandler:
    h = StubHandler(path=handler_path)
    routes_spike_curve._serve_spike_curve(h)
    return h


class SpikeCurveBase(unittest.TestCase):
    def setUp(self):
        # Each test starts with a clean cache so cache-lifecycle assertions
        # are deterministic.
        routes_spike_curve._reset_caches()


class InputValidationTests(SpikeCurveBase):
    def test_missing_ally_param_returns_400(self):
        h = _do("/api/spike-curve")
        self.assertEqual(h.last_status, 400)
        body = h.parsed()
        self.assertFalse(body["ok"])
        self.assertIn("5 champion ids", body["error"])

    def test_four_ally_ids_returns_400(self):
        path = f"/api/spike-curve?ally={JINX},{ASHE},{CAITLYN},{KAISA}&enemy={','.join(str(i) for i in TANK_TEAM)}"
        h = _do(path)
        self.assertEqual(h.last_status, 400)
        body = h.parsed()
        self.assertEqual(body["ally_count"], 4)
        self.assertEqual(body["enemy_count"], 5)

    def test_six_enemy_ids_returns_400(self):
        path = (f"/api/spike-curve?ally={','.join(str(i) for i in CARRY_TEAM)}"
                f"&enemy={','.join(str(i) for i in TANK_TEAM)},{GAREN}")
        h = _do(path)
        self.assertEqual(h.last_status, 400)
        body = h.parsed()
        self.assertEqual(body["enemy_count"], 6)

    def test_non_integer_id_returns_400(self):
        path = (f"/api/spike-curve?ally=222,22,51,abc,67"
                f"&enemy={','.join(str(i) for i in TANK_TEAM)}")
        h = _do(path)
        self.assertEqual(h.last_status, 400)
        body = h.parsed()
        self.assertIn("comma-separated ints", body["error"])

    def test_unknown_champion_id_returns_400(self):
        # 999999 is not a real DDragon champion key.
        path = (f"/api/spike-curve?ally=222,22,51,145,999999"
                f"&enemy={','.join(str(i) for i in TANK_TEAM)}")
        h = _do(path)
        self.assertEqual(h.last_status, 400)
        body = h.parsed()
        self.assertIn("unknown champion", body["error"].lower())
        self.assertIn(999999, body["unknown_ally"])

    def test_unsupported_mode_returns_400(self):
        path = (f"/api/spike-curve?ally={','.join(str(i) for i in CARRY_TEAM)}"
                f"&enemy={','.join(str(i) for i in TANK_TEAM)}&mode=GIBBERISH")
        h = _do(path)
        self.assertEqual(h.last_status, 400)
        body = h.parsed()
        self.assertIn("unsupported mode", body["error"].lower())
        self.assertIn("SR", body["supported"])

    def test_default_mode_is_sr(self):
        path = (f"/api/spike-curve?ally={','.join(str(i) for i in CARRY_TEAM)}"
                f"&enemy={','.join(str(i) for i in TANK_TEAM)}")
        h = _do(path)
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.parsed()["mode"], "SR")


class OutputShapeTests(SpikeCurveBase):
    def _ok_call(self, mode: str = "SR"):
        path = (f"/api/spike-curve?ally={','.join(str(i) for i in CARRY_TEAM)}"
                f"&enemy={','.join(str(i) for i in TANK_TEAM)}&mode={mode}")
        return _do(path)

    def test_ok_response_shape(self):
        h = self._ok_call()
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertTrue(body["ok"])
        for k in ("mode", "ally", "enemy", "peaks", "cache_key", "cached"):
            self.assertIn(k, body)

    def test_each_side_has_41_entries(self):
        h = self._ok_call()
        body = h.parsed()
        self.assertEqual(len(body["ally"]), 41)
        self.assertEqual(len(body["enemy"]), 41)

    def test_minute_keys_cover_0_through_40(self):
        h = self._ok_call()
        body = h.parsed()
        ally_minutes = [e["minute"] for e in body["ally"]]
        enemy_minutes = [e["minute"] for e in body["enemy"]]
        self.assertEqual(ally_minutes, list(range(0, 41)))
        self.assertEqual(enemy_minutes, list(range(0, 41)))

    def test_each_entry_has_minute_and_power(self):
        h = self._ok_call()
        body = h.parsed()
        for entry in body["ally"]:
            self.assertIn("minute", entry)
            self.assertIn("power", entry)
            self.assertIsInstance(entry["power"], (int, float))

    def test_powers_are_nonnegative(self):
        h = self._ok_call()
        body = h.parsed()
        for entry in body["ally"] + body["enemy"]:
            self.assertGreaterEqual(entry["power"], 0.0)

    def test_peaks_are_in_range_0_40(self):
        h = self._ok_call()
        peaks = h.parsed()["peaks"]
        self.assertGreaterEqual(peaks["ally"], 0)
        self.assertLessEqual(peaks["ally"], 40)
        self.assertGreaterEqual(peaks["enemy"], 0)
        self.assertLessEqual(peaks["enemy"], 40)

    def test_aram_mode_returns_ok(self):
        h = self._ok_call(mode="ARAM")
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.parsed()["mode"], "ARAM")


class CacheTests(SpikeCurveBase):
    def _csv(self, ids):
        return ",".join(str(i) for i in ids)

    def test_first_call_is_uncached(self):
        path = f"/api/spike-curve?ally={self._csv(CARRY_TEAM)}&enemy={self._csv(TANK_TEAM)}"
        h = _do(path)
        self.assertEqual(h.last_status, 200)
        self.assertFalse(h.parsed()["cached"])

    def test_second_call_is_cached(self):
        path = f"/api/spike-curve?ally={self._csv(CARRY_TEAM)}&enemy={self._csv(TANK_TEAM)}"
        _do(path)
        h2 = _do(path)
        self.assertEqual(h2.last_status, 200)
        self.assertTrue(h2.parsed()["cached"])

    def test_reset_caches_invalidates(self):
        path = f"/api/spike-curve?ally={self._csv(CARRY_TEAM)}&enemy={self._csv(TANK_TEAM)}"
        _do(path)
        routes_spike_curve._reset_caches()
        h2 = _do(path)
        self.assertFalse(h2.parsed()["cached"])

    def test_cache_key_is_order_insensitive(self):
        # Reordered ally team should hit the same cache entry.
        path1 = f"/api/spike-curve?ally={self._csv(CARRY_TEAM)}&enemy={self._csv(TANK_TEAM)}"
        reordered = list(reversed(CARRY_TEAM))
        path2 = f"/api/spike-curve?ally={self._csv(reordered)}&enemy={self._csv(TANK_TEAM)}"
        h1 = _do(path1)
        h2 = _do(path2)
        self.assertFalse(h1.parsed()["cached"])
        self.assertTrue(h2.parsed()["cached"])

    def test_different_mode_does_not_share_cache(self):
        path_sr = f"/api/spike-curve?ally={self._csv(CARRY_TEAM)}&enemy={self._csv(TANK_TEAM)}&mode=SR"
        path_aram = f"/api/spike-curve?ally={self._csv(CARRY_TEAM)}&enemy={self._csv(TANK_TEAM)}&mode=ARAM"
        _do(path_sr)
        h_aram = _do(path_aram)
        # ARAM is a fresh key - should be uncached the first time.
        self.assertFalse(h_aram.parsed()["cached"])


class CarryVsTankSpikeOrderingTests(SpikeCurveBase):
    """The load-bearing UX signal: a team of all-carry archetype champs
    should hit its spike minute EARLIER than a team of all-tank archetype
    champs. This validates the fraction-of-end-game-power scoring model
    works as intended - tank items+level synergy back-loads the EHP
    curve, carry items front-load the DPS curve.

    Uses 5x duplicate single champs to remove the cross-champ averaging
    that otherwise narrows the gap (different carry champs spike at
    slightly different minutes).
    """

    def _spike(self, ids):
        path = (f"/api/spike-curve?ally={','.join(str(i) for i in ids)}"
                f"&enemy={','.join(str(i) for i in TANK_TEAM)}")
        return _do(path).parsed()["peaks"]["ally"]

    def test_carry_spikes_no_later_than_tank(self):
        carry_spike = self._spike([JINX] * 5)
        tank_spike = self._spike([MALPHITE] * 5)
        # Carries should hit 70% of end-game potential earlier than tanks
        # because mythic + crit items front-load DPS while EHP needs both
        # level AND items to compound.
        self.assertLessEqual(carry_spike, tank_spike,
                             f"carry spike {carry_spike} should precede "
                             f"tank spike {tank_spike}")

    def test_5x_jinx_team_has_meaningful_curve(self):
        path = (f"/api/spike-curve?ally={','.join([str(JINX)] * 5)}"
                f"&enemy={','.join(str(i) for i in TANK_TEAM)}")
        body = _do(path).parsed()
        # At minute 0, power should be much less than at minute 40 -
        # otherwise the scorer or the fraction-of-final normalization is
        # broken.
        ally = body["ally"]
        self.assertLess(ally[0]["power"], ally[40]["power"])
        # Late-game team should be at or near 5.0 (5 champs * ~1.0 fraction).
        self.assertGreater(ally[40]["power"], 4.0)


class PerChampCurveTests(SpikeCurveBase):
    """Direct exercise of ``_build_champ_curve`` - cheaper to assert the
    invariants here than to round-trip the full HTTP handler."""

    def test_curve_length_is_41(self):
        c = routes_spike_curve._build_champ_curve("Jinx", "carry", "SR")
        self.assertEqual(len(c), 41)

    def test_curve_monotonic_nondecreasing(self):
        # Accumulation only - no item removal mid-game - means the curve
        # must be non-decreasing. A drop signals a scorer bug or a bad
        # item being included.
        c = routes_spike_curve._build_champ_curve("Jinx", "carry", "SR")
        for i in range(1, 41):
            self.assertGreaterEqual(c[i] + 1e-6, c[i - 1],
                                     f"drop at m{i}: {c[i-1]} -> {c[i]}")

    def test_curve_starts_low_ends_high(self):
        c = routes_spike_curve._build_champ_curve("Jinx", "carry", "SR")
        self.assertLess(c[0], 0.20)   # naked level 1 << final
        self.assertGreater(c[40], 0.95)  # full build at level 18

    def test_curve_cached_after_first_build(self):
        routes_spike_curve._reset_caches()
        c1 = routes_spike_curve._build_champ_curve("Jinx", "carry", "SR")
        c2 = routes_spike_curve._build_champ_curve("Jinx", "carry", "SR")
        # Same tuple object should be returned on second call (cache hit
        # returns the cached tuple verbatim, not a re-built one).
        self.assertIs(c1, c2)


class PhaseVerdictTests(SpikeCurveBase):
    """Direct exercise of the comparative early/mid/late phase-strength
    verdict helpers. The verdict compares the TWO teams' phase-mean power
    and colours each cell green/yellow/red per side (R81 F1)."""

    def _curve(self, fn):
        return [{"minute": i, "power": float(fn(i))} for i in range(41)]

    def test_front_loaded_ally_vs_back_loaded_enemy_early(self):
        # Ally rises fast (early power dominates); enemy back-loads (quadratic).
        ally = self._curve(lambda m: min(m / 8.0, 5.0))
        enemy = self._curve(lambda m: 5.0 * (m / 40.0) ** 2)
        v = routes_spike_curve._phase_verdict(ally, enemy)
        self.assertEqual(v["ally"]["early"], "green")
        self.assertEqual(v["enemy"]["early"], "red")

    def test_asymmetric_ceilings_late_flip(self):
        # Same shape, different ceilings: ally caps ~4.0, enemy caps ~5.0.
        ally = self._curve(lambda m: 4.0 * (m / 40.0))
        enemy = self._curve(lambda m: 5.0 * (m / 40.0))
        v = routes_spike_curve._phase_verdict(ally, enemy)
        self.assertEqual(v["enemy"]["late"], "green")
        self.assertEqual(v["ally"]["late"], "red")

    def test_identical_curves_all_yellow(self):
        same = self._curve(lambda m: 5.0 * (m / 40.0))
        v = routes_spike_curve._phase_verdict(same, list(same))
        for side in ("ally", "enemy"):
            for phase in ("early", "mid", "late"):
                self.assertEqual(v[side][phase], "yellow",
                                 f"{side}/{phase} should be yellow on ties")

    def test_all_zero_curves_all_yellow(self):
        zero = self._curve(lambda m: 0.0)
        v = routes_spike_curve._phase_verdict(zero, list(zero))
        for side in ("ally", "enemy"):
            for phase in ("early", "mid", "late"):
                self.assertEqual(v[side][phase], "yellow")

    def test_empty_ally_all_yellow(self):
        enemy = self._curve(lambda m: 5.0 * (m / 40.0))
        v = routes_spike_curve._phase_verdict([], enemy)
        for side in ("ally", "enemy"):
            for phase in ("early", "mid", "late"):
                self.assertEqual(v[side][phase], "yellow")

    def test_empty_enemy_all_yellow(self):
        ally = self._curve(lambda m: 5.0 * (m / 40.0))
        v = routes_spike_curve._phase_verdict(ally, [])
        for side in ("ally", "enemy"):
            for phase in ("early", "mid", "late"):
                self.assertEqual(v[side][phase], "yellow")

    def test_phase_mean_windows(self):
        # Power == minute -> early mean is mean(0..14)=7.0, mid mean(15..29)=22.0.
        curve = self._curve(lambda m: float(m))
        self.assertAlmostEqual(routes_spike_curve._phase_mean(curve, 0, 14), 7.0)
        self.assertAlmostEqual(routes_spike_curve._phase_mean(curve, 15, 29), 22.0)
        self.assertAlmostEqual(routes_spike_curve._phase_mean(curve, 30, 40), 35.0)

    def test_phase_mean_empty_window_is_zero(self):
        curve = self._curve(lambda m: float(m))
        self.assertEqual(routes_spike_curve._phase_mean(curve, 100, 200), 0.0)

    def test_phase_pair_margin_flip(self):
        # A margin under 5% stays yellow; at/over 5% flips.
        self.assertEqual(routes_spike_curve._phase_pair(1.04, 1.0), ("yellow", "yellow"))
        self.assertEqual(routes_spike_curve._phase_pair(1.05, 1.0), ("green", "red"))
        self.assertEqual(routes_spike_curve._phase_pair(1.0, 1.05), ("red", "green"))

    def test_phase_pair_zero_sides(self):
        self.assertEqual(routes_spike_curve._phase_pair(0.0, 0.0), ("yellow", "yellow"))
        self.assertEqual(routes_spike_curve._phase_pair(2.0, 0.0), ("green", "red"))
        self.assertEqual(routes_spike_curve._phase_pair(0.0, 2.0), ("red", "green"))


class PhaseRouteIntegrationTests(SpikeCurveBase):
    """Route-level: a real /api/spike-curve response carries the additive
    `phases` block AND every prior key stays present."""

    def _ok_call(self):
        path = (f"/api/spike-curve?ally={','.join(str(i) for i in CARRY_TEAM)}"
                f"&enemy={','.join(str(i) for i in TANK_TEAM)}")
        return _do(path)

    def test_response_carries_phases_block(self):
        body = self._ok_call().parsed()
        self.assertIn("phases", body)
        phases = body["phases"]
        self.assertIn("ally", phases)
        self.assertIn("enemy", phases)
        for side in ("ally", "enemy"):
            for phase in ("early", "mid", "late"):
                self.assertIn(phase, phases[side])
                self.assertIn(phases[side][phase], ("green", "yellow", "red"))

    def test_prior_keys_unchanged(self):
        body = self._ok_call().parsed()
        for k in ("ok", "mode", "ally", "enemy", "peaks", "cache_key", "cached"):
            self.assertIn(k, body)
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["ally"]), 41)
        self.assertEqual(len(body["enemy"]), 41)

    def test_cached_hit_inherits_phases(self):
        path = (f"/api/spike-curve?ally={','.join(str(i) for i in CARRY_TEAM)}"
                f"&enemy={','.join(str(i) for i in TANK_TEAM)}")
        _do(path)
        body2 = _do(path).parsed()
        self.assertTrue(body2["cached"])
        self.assertIn("phases", body2)


class RouteRegistrationTests(unittest.TestCase):
    """GET_ROUTES should be importable + non-empty so the dispatcher can
    wire the route at module load."""

    def test_get_routes_export_exists(self):
        self.assertTrue(hasattr(routes_spike_curve, "GET_ROUTES"))
        self.assertGreaterEqual(len(routes_spike_curve.GET_ROUTES), 1)

    def test_route_matches_canonical_path(self):
        matcher, _handler = routes_spike_curve.GET_ROUTES[0]
        self.assertTrue(matcher("/api/spike-curve"))
        self.assertFalse(matcher("/api/spike-curve-other"))

    def test_route_registered_in_dispatch(self):
        from dashboard import _dispatch
        # _gather_get builds the full GET_ROUTES list; the matcher fn
        # for /api/spike-curve must be present.
        all_get = _dispatch._gather_get()
        matched = [m for (m, _h) in all_get if m("/api/spike-curve")]
        self.assertGreater(len(matched), 0)


if __name__ == "__main__":
    unittest.main()
