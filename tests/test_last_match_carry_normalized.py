"""OQ12 slice A: carry_normalized block on the /api/last-match payload.

Mirrors the tests/test_last_match_by_ts.py throwaway-DB pattern (patch
blm._APP_DIR) and proves the FROZEN payload contract the frontend slice
codes against:

  match["dmg_share_pct"]    = float | None
  match["carry_normalized"] = {
    "bench_key": "BOTTOM|mid" | None,
    "kp_pct":         {value, p25, p50, p75, n, band},
    "gold_share_pct": {...},
    "dmg_share_pct":  {...},
  }

Covered: bench_key + band math via a monkeypatched
core.carry_benchmarks.resolve; ARAM enriched row resolves with role=None;
enriched=None SR row falls back to the CLASSIC benchmark with kp the only
computable value; the payload is json.dumps-safe; a missing benchmark file
degrades to the all-null block while found stays True.

ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import core.carry_benchmarks as cb

METRICS = {
    "kp_pct":         {"p25": 41.2, "p50": 52.0, "p75": 63.5, "n": 238},
    "gold_share_pct": {"p25": 19.8, "p50": 21.6, "p75": 23.9, "n": 240},
    "dmg_share_pct":  {"p25": 21.0, "p50": 26.3, "p75": 31.8, "n": 240},
}


def _lcu_detail(game_mode: str, me_timeline: dict | None = None) -> dict:
    """Minimal 3-player LCU match detail the enricher accepts. No
    platformId on purpose - keeps _attach_match_timeline a no-op."""
    me = {
        "participantId": 1, "teamId": 100, "championId": 99,
        "stats": {"win": True, "kills": 14, "deaths": 5, "assists": 22,
                  "goldEarned": 8000,
                  "totalDamageDealtToChampions": 12000},
    }
    if me_timeline is not None:
        me["timeline"] = me_timeline
    return {
        "gameId": 123, "gameMode": game_mode, "queueId": 450, "mapId": 12,
        "gameDuration": 900,
        "participantIdentities": [
            {"participantId": 1, "player": {"puuid": "me-puuid",
                                            "gameName": "Me"}},
            {"participantId": 2, "player": {"puuid": "ally-puuid",
                                            "gameName": "Ally"}},
            {"participantId": 3, "player": {"puuid": "enemy-puuid",
                                            "gameName": "Enemy"}},
        ],
        "participants": [
            me,
            {"participantId": 2, "teamId": 100, "championId": 12,
             "stats": {"win": True, "goldEarned": 2000,
                       "totalDamageDealtToChampions": 4000}},
            {"participantId": 3, "teamId": 200, "championId": 45,
             "stats": {"win": False, "goldEarned": 99999,
                       "totalDamageDealtToChampions": 99999}},
        ],
        "teams": [],
    }


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE matches ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  timestamp TEXT, mode TEXT, champion TEXT, grade TEXT,"
        "  kda_str TEXT, game_time_s INTEGER, game_id INTEGER DEFAULT 0,"
        "  kills INTEGER, deaths INTEGER, assists INTEGER,"
        "  cs INTEGER, cs_per_min REAL, gold INTEGER, gold_per_min REAL,"
        "  kp_pct REAL, label TEXT, raw_data TEXT)"
    )
    aram_raw = json.dumps({
        "lcu_match_detail": _lcu_detail("ARAM"),
        "tracked_puuid": "me-puuid",
    })
    classic_raw = json.dumps({
        "lcu_match_detail": _lcu_detail(
            "CLASSIC", {"lane": "BOTTOM", "role": "DUO_SUPPORT"}),
        "tracked_puuid": "me-puuid",
    })
    rows = [
        # (ts, mode, champ, dur, k, d, a, kp, raw)
        ("2026-06-01 12:00:00", "SR",   "Jinx", 1500, 10, 2,  8, 62.0, ""),
        ("2026-06-02 13:30:00", "ARAM", "Lux",   900, 14, 5, 22, 70.0,
         aram_raw),
        ("2026-06-03 14:45:00", "SR",   "Nami", 1500,  2, 3, 20, 55.0,
         classic_raw),
    ]
    for ts, mode, champ, dur, k, d, a, kp, raw in rows:
        conn.execute(
            "INSERT INTO matches (timestamp, mode, champion, grade, kda_str,"
            " game_time_s, kills, deaths, assists, cs, cs_per_min, gold,"
            " gold_per_min, kp_pct, label, raw_data)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts, mode, champ, "A", f"{k}/{d}/{a}", dur, k, d, a,
             100, 4.0, 11000, 440.0, kp, "", raw),
        )
    conn.commit()
    conn.close()


class LastMatchCarryNormalizedTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.app_dir = Path(self._tmp.name)
        (self.app_dir / "data").mkdir()
        _make_db(self.app_dir / "data" / "match_history.db")
        import dashboard.builders_last_match as blm
        self._patches = [mock.patch.object(blm, "_APP_DIR", self.app_dir)]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        from dashboard import _context
        cached = getattr(_context.DB_CONN_LOCAL, "conns", {}).pop(
            str(self.app_dir / "data" / "match_history.db"), None)
        if cached is not None:
            cached.close()
        self._tmp.cleanup()

    def _build(self, **kw):
        import dashboard.builders_last_match as blm
        return blm._build_last_match(**kw)

    def _resolve_stub(self, bench_key):
        calls = []

        def _fake(role, mode, duration_s):
            calls.append((role, mode, duration_s))
            return bench_key, dict(METRICS)
        return _fake, calls

    def test_contract_bench_key_and_band_math(self):
        """ARAM enriched row: values + percentiles + bands per contract."""
        fake, calls = self._resolve_stub("ARAM|short")
        with mock.patch.object(cb, "resolve", side_effect=fake):
            out = self._build(match_ts="2026-06-02 13:30:00")
        self.assertTrue(out["found"])
        m = out["match"]
        # dmg_share_pct top-level key: 12000 / (12000 + 4000) = 75.0
        self.assertEqual(m["dmg_share_pct"], 75.0)
        cn = m["carry_normalized"]
        self.assertEqual(cn["bench_key"], "ARAM|short")
        self.assertEqual(cn["kp_pct"]["value"], 70.0)
        self.assertEqual(cn["kp_pct"]["p25"], 41.2)
        self.assertEqual(cn["kp_pct"]["p75"], 63.5)
        self.assertEqual(cn["kp_pct"]["n"], 238)
        self.assertEqual(cn["kp_pct"]["band"], "high")     # 70 > 63.5
        # gold share: 8000 / (8000 + 2000) = 80.0 -> high
        self.assertEqual(cn["gold_share_pct"]["value"], 80.0)
        self.assertEqual(cn["gold_share_pct"]["band"], "high")
        self.assertEqual(cn["dmg_share_pct"]["value"], 75.0)
        self.assertEqual(cn["dmg_share_pct"]["band"], "high")  # 75 > 31.8

    def test_aram_row_resolves_with_role_none(self):
        fake, calls = self._resolve_stub("ARAM|short")
        with mock.patch.object(cb, "resolve", side_effect=fake):
            self._build(match_ts="2026-06-02 13:30:00")
        self.assertEqual(len(calls), 1)
        role, mode, duration_s = calls[0]
        self.assertIsNone(role)          # non-CLASSIC -> no role benchmark
        self.assertEqual(mode, "ARAM")   # mode from enriched.game_mode
        self.assertEqual(duration_s, 900)

    def test_classic_row_maps_duo_support_to_utility(self):
        fake, calls = self._resolve_stub("UTILITY|mid")
        with mock.patch.object(cb, "resolve", side_effect=fake):
            out = self._build(match_ts="2026-06-03 14:45:00")
        self.assertEqual(calls[0][0], "UTILITY")
        self.assertEqual(calls[0][1], "CLASSIC")
        self.assertEqual(out["match"]["carry_normalized"]["bench_key"],
                         "UTILITY|mid")

    def test_enriched_none_sr_row_falls_back_to_classic_kp_only(self):
        """SR row without LCU enrichment: mode maps SR->CLASSIC, role None,
        kp is the only populated value (gold/dmg shares need the roster)."""
        fake, calls = self._resolve_stub("CLASSIC|mid")
        with mock.patch.object(cb, "resolve", side_effect=fake):
            out = self._build(match_ts="2026-06-01 12:00:00")
        self.assertTrue(out["found"])
        role, mode, duration_s = calls[0]
        self.assertIsNone(role)
        self.assertEqual(mode, "CLASSIC")
        self.assertEqual(duration_s, 1500)
        m = out["match"]
        self.assertIsNone(m["dmg_share_pct"])
        cn = m["carry_normalized"]
        self.assertEqual(cn["bench_key"], "CLASSIC|mid")
        self.assertEqual(cn["kp_pct"]["value"], 62.0)
        self.assertEqual(cn["kp_pct"]["band"], "avg")      # 41.2 <= 62 <= 63.5
        self.assertIsNone(cn["gold_share_pct"]["value"])
        self.assertIsNone(cn["gold_share_pct"]["band"])    # null value -> null
        self.assertEqual(cn["gold_share_pct"]["p25"], 19.8)
        self.assertIsNone(cn["dmg_share_pct"]["value"])
        self.assertIsNone(cn["dmg_share_pct"]["band"])

    def test_payload_is_json_dumps_safe(self):
        fake, _ = self._resolve_stub("ARAM|short")
        with mock.patch.object(cb, "resolve", side_effect=fake):
            out = self._build(match_ts="2026-06-02 13:30:00")
        json.dumps(out)  # must not raise

    def test_benchmark_file_missing_yields_all_null_block(self):
        """No monkeypatched resolve - the REAL reader pointed at a missing
        file returns (None, {}), so every p/n/band is null but the values
        stay populated and found stays True."""
        with mock.patch.object(cb, "CARRY_BENCHMARKS_PATH",
                               self.app_dir / "does-not-exist.json"), \
             mock.patch.object(cb, "_cache", cb._Cache()):
            out = self._build(match_ts="2026-06-02 13:30:00")
        self.assertTrue(out["found"])
        cn = out["match"]["carry_normalized"]
        self.assertIsNone(cn["bench_key"])
        for metric in ("kp_pct", "gold_share_pct", "dmg_share_pct"):
            for field in ("p25", "p50", "p75", "n", "band"):
                self.assertIsNone(cn[metric][field],
                                  f"{metric}.{field} should be null")
        self.assertEqual(cn["kp_pct"]["value"], 70.0)
        self.assertEqual(cn["gold_share_pct"]["value"], 80.0)
        self.assertEqual(cn["dmg_share_pct"]["value"], 75.0)


if __name__ == "__main__":
    unittest.main()
