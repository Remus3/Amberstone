"""Tests for the champ-select team AD/AP damage-mix accessor + route.

LIFT 1b (2026-06-22): a physical-vs-magic damage-lean meter for the
operator's ally team in SR champ-select. Two layers:

  - PURE function (``dashboard.routes_pickban._compute_team_damage_mix``):
    sums info.attack / info.magic over a team and returns physical/magical
    percentages + a per-champ lean. No HTTP, no DB.

  - Route (``dashboard.routes_pickban._serve_team_damage_mix``): 200
    happy-path shape driven through a stub handler that captures ``_send``
    (mirrors test_aram_balance_grid.StubHandler).

Ground truth (VERIFIED on disk, data/meta/ddragon_champions.json):
  Aatrox  key 266  info.attack 8  info.magic 3
  Ahri    key 103  info.attack 3  info.magic 8
  Lux     key  99  info.attack 2  info.magic 9
We resolve the numeric ids from the JSON in-test (no hardcoded id->stat
guess) and assert on COMPUTED quantities only - never fragile cross-champ
magnitudes (CLAUDE.md "Testing Discipline").
"""
from __future__ import annotations

import json
import pathlib
import unittest
from typing import Optional

from dashboard import routes_pickban as rp


# ---------------------------------------------------------------------
# Stub request handler (mirrors test_aram_balance_grid.StubHandler)
# ---------------------------------------------------------------------

class StubHandler:
    def __init__(self, path: str = ""):
        self.path = path
        self.last_status: Optional[int] = None
        self.last_body: Optional[bytes] = None
        self.last_ct: Optional[str] = None

    def _send(self, status, body, content_type):
        self.last_status = status
        self.last_body = body
        self.last_ct = content_type

    def parsed(self) -> dict:
        return json.loads(self.last_body.decode("utf-8")) if self.last_body else {}


def _name_to_id() -> dict[str, int]:
    """Resolve {slug: numeric id} straight from the live JSON so the test
    never hardcodes a guessed id->stat mapping."""
    path = (pathlib.Path(rp.__file__).resolve().parent.parent
            / "data" / "meta" / "ddragon_champions.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    data = raw.get("data", raw)
    out: dict[str, int] = {}
    for entry in data.values():
        if isinstance(entry, dict) and entry.get("id") and entry.get("key"):
            try:
                out[str(entry["id"])] = int(entry["key"])
            except (TypeError, ValueError):
                continue
    return out


_IDS = _name_to_id()
_AATROX = _IDS["Aatrox"]   # attack 8 magic 3
_AHRI = _IDS["Ahri"]       # attack 3 magic 8
_LUX = _IDS["Lux"]         # attack 2 magic 9


# ---------------------------------------------------------------------
# Accessor: the info-map loader
# ---------------------------------------------------------------------

class LoadChampIdToInfoTests(unittest.TestCase):
    def test_known_champs_present(self):
        info = rp._load_champ_id_to_info()
        self.assertEqual(info.get(_AATROX), (8, 3))
        self.assertEqual(info.get(_AHRI), (3, 8))

    def test_values_are_int_pairs(self):
        info = rp._load_champ_id_to_info()
        self.assertTrue(info, "info map must not be empty")
        # Spot-check a handful so we don't iterate the whole map fragilely.
        for cid in (_AATROX, _AHRI, _LUX):
            pair = info[cid]
            self.assertIsInstance(pair, tuple)
            self.assertEqual(len(pair), 2)
            self.assertIsInstance(pair[0], int)
            self.assertIsInstance(pair[1], int)


class ZeroedInfoOverrideTests(unittest.TestCase):
    """DDragon zeroes info.attack/magic for some champs, so the damage-mix would
    drop them (Seraphine 0/0 -> invisible) or mis-lean them (Qiyana 0/4 -> AP
    despite being an AD assassin). The curated override
    (core.champion_info_overrides) restores their real contribution."""

    def setUp(self):
        rp._CHAMP_ID_TO_INFO = None  # force a reload under the current code

    def test_seraphine_contributes_ap(self):
        info = rp._load_champ_id_to_info()
        a, m = info[_IDS["Seraphine"]]
        self.assertGreater(m, a, "Seraphine must contribute AP, not (0,0)")

    def test_qiyana_leans_ad(self):
        info = rp._load_champ_id_to_info()
        a, m = info[_IDS["Qiyana"]]
        self.assertGreaterEqual(a, m, "Qiyana must contribute AD, not the 0/4 AP lean")


# ---------------------------------------------------------------------
# PURE function: _compute_team_damage_mix
# ---------------------------------------------------------------------

class ComputeTeamDamageMixTests(unittest.TestCase):
    def test_even_split(self):
        # Aatrox(8,3) + Ahri(3,8) -> sums 11/11 -> 50/50, leans AD then AP.
        out = rp._compute_team_damage_mix((_AATROX, _AHRI))
        self.assertTrue(out["ok"])
        self.assertEqual(out["n_champs"], 2)
        self.assertEqual(out["sum_attack"], 11)
        self.assertEqual(out["sum_magic"], 11)
        self.assertEqual(out["physical_pct"], 50)
        self.assertEqual(out["magical_pct"], 50)
        self.assertEqual(out["physical_pct"] + out["magical_pct"], 100)
        leans = {pc["champId"]: pc["lean"] for pc in out["per_champ"]}
        self.assertEqual(leans[_AATROX], "AD")
        self.assertEqual(leans[_AHRI], "AP")

    def test_per_champ_carries_raw_stats(self):
        out = rp._compute_team_damage_mix((_AATROX,))
        self.assertEqual(len(out["per_champ"]), 1)
        pc = out["per_champ"][0]
        self.assertEqual(pc["champId"], _AATROX)
        self.assertEqual(pc["attack"], 8)
        self.assertEqual(pc["magic"], 3)
        self.assertEqual(pc["lean"], "AD")

    def test_ad_heavy_team_exceeds_50(self):
        # Two AD-leaning champs (Aatrox 8/3 x2) -> physical_pct > 50.
        out = rp._compute_team_damage_mix((_AATROX, _AATROX))
        self.assertGreater(out["physical_pct"], 50)
        self.assertLess(out["magical_pct"], 50)
        self.assertEqual(out["physical_pct"] + out["magical_pct"], 100)

    def test_ap_heavy_team_below_50(self):
        # Two AP-leaning champs (Lux 2/9 x2) -> physical_pct < 50.
        out = rp._compute_team_damage_mix((_LUX, _LUX))
        self.assertLess(out["physical_pct"], 50)
        self.assertGreater(out["magical_pct"], 50)

    def test_percentages_complement_to_100(self):
        # Any mixed team's two percentages sum to exactly 100.
        out = rp._compute_team_damage_mix((_AATROX, _AHRI, _LUX))
        self.assertEqual(out["physical_pct"] + out["magical_pct"], 100)

    def test_empty_team(self):
        out = rp._compute_team_damage_mix(())
        self.assertTrue(out["ok"])
        self.assertEqual(out["n_champs"], 0)
        self.assertEqual(out["physical_pct"], 0)
        self.assertEqual(out["magical_pct"], 0)
        self.assertEqual(out["per_champ"], [])

    def test_unknown_ids_skipped(self):
        # An id absent from the info map contributes nothing.
        out = rp._compute_team_damage_mix((999999, 888888))
        self.assertEqual(out["n_champs"], 0)
        self.assertEqual(out["sum_attack"], 0)
        self.assertEqual(out["sum_magic"], 0)
        self.assertEqual(out["per_champ"], [])

    def test_known_plus_unknown_counts_only_known(self):
        out = rp._compute_team_damage_mix((_AATROX, 999999))
        self.assertEqual(out["n_champs"], 1)
        self.assertEqual(out["sum_attack"], 8)
        self.assertEqual(out["sum_magic"], 3)

    def test_team_ids_echoed(self):
        out = rp._compute_team_damage_mix((_AATROX, _AHRI))
        self.assertEqual(list(out["team_ids"]), [_AATROX, _AHRI])

    def test_even_lean_when_attack_equals_magic(self):
        # Synthetic: find any champ whose attack == magic, if present; else
        # assert the lean rule directly via a stubbed info map.
        original = rp._CHAMP_ID_TO_INFO
        try:
            rp._CHAMP_ID_TO_INFO = {7001: (5, 5), 7002: (9, 2)}
            out = rp._compute_team_damage_mix((7001, 7002))
            leans = {pc["champId"]: pc["lean"] for pc in out["per_champ"]}
            self.assertEqual(leans[7001], "EVEN")
            self.assertEqual(leans[7002], "AD")
        finally:
            rp._CHAMP_ID_TO_INFO = original


# ---------------------------------------------------------------------
# Route: _serve_team_damage_mix
# ---------------------------------------------------------------------

class RouteTests(unittest.TestCase):
    def test_happy_path_shape(self):
        h = StubHandler(
            f"/api/champ-select/team-damage-mix?team_ids={_AATROX},{_AHRI}")
        rp._serve_team_damage_mix(h)
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.last_ct, "application/json")
        body = h.parsed()
        self.assertIs(body.get("ok"), True)
        self.assertEqual(body["physical_pct"], 50)
        self.assertEqual(body["magical_pct"], 50)
        self.assertEqual(body["n_champs"], 2)
        self.assertIsInstance(body["per_champ"], list)

    def test_empty_param(self):
        h = StubHandler("/api/champ-select/team-damage-mix")
        rp._serve_team_damage_mix(h)
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertIs(body.get("ok"), True)
        self.assertEqual(body["n_champs"], 0)
        self.assertEqual(body["physical_pct"], 0)

    def test_route_registered(self):
        paths = []
        for matcher, _ in rp.GET_ROUTES:
            if matcher("/api/champ-select/team-damage-mix"):
                paths.append("team-damage-mix")
        self.assertEqual(paths, ["team-damage-mix"])


if __name__ == "__main__":
    unittest.main()
