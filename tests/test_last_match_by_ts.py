"""HIST2 backend: parameterize the Post Game Review builder by match
timestamp so a historical match row can be rendered "as if it had just
ended" - WITHOUT changing the live "latest" path.

`_build_last_match()` (no arg) keeps the pre-HIST2 behavior: newest
non-TFT row via ORDER BY timestamp DESC LIMIT 1. `_build_last_match(
match_ts="YYYY-MM-DD HH:MM:SS")` instead resolves the row whose
timestamp matches exactly, so the History / Session match-row click can
open that specific match's detached PGR. The Quick Review baseline
(history rows EXCLUDING the selected one, keyed on the row id) stays
correct for the historical row too.

These tests stand up a throwaway match_history.db with three rows so we
can prove: latest path unchanged, ts path selects the right row, an
unknown ts degrades to found=False (not a silent latest fallback - that
would clobber the operator's expectation), and the baseline excludes the
selected row by id (not by timestamp).

ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


def _make_db(path: Path) -> None:
    """Three non-TFT rows with distinct timestamps + one TFT row that must
    never be selected. raw_data left empty (no LCU enrichment needed - the
    builder degrades enriched to None and the Quick Review still computes)."""
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
    rows = [
        # (ts, mode, champ, grade, kda_str, dur, k, d, a, cs, cspm, gold, gpm, kp)
        ("2026-06-01 12:00:00", "SR",   "Jinx",      "A", "10/2/8",  1800, 10, 2,  8, 200, 6.7, 14000, 467, 62),
        ("2026-06-02 13:30:00", "ARAM", "Lux",       "S", "14/5/22",  900, 14, 5, 22,  60, 4.0, 11000, 733, 70),
        ("2026-06-03 14:45:00", "SR",   "Caitlyn",   "C", "4/9/3",   1500,  4, 9,  3, 180, 7.2, 12500, 500, 45),
        ("2026-06-03 15:10:00", "TFT",  "Comp Name", "-", "0/0/0",   2100,  0, 0,  0,   0, 0.0,     0,   0,  0),
    ]
    for r in rows:
        conn.execute(
            "INSERT INTO matches (timestamp, mode, champion, grade, kda_str,"
            " game_time_s, kills, deaths, assists, cs, cs_per_min, gold,"
            " gold_per_min, kp_pct, label, raw_data)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9],
             r[10], r[11], r[12], r[13], "", ""),
        )
    conn.commit()
    conn.close()


class BuildLastMatchByTsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.app_dir = Path(self._tmp.name)
        (self.app_dir / "data").mkdir()
        _make_db(self.app_dir / "data" / "match_history.db")
        # Point the builder's APP_DIR at our throwaway tree. The module
        # caches _APP_DIR at import, so patch the name on the builder module.
        import dashboard.builders_last_match as blm
        self._patches = [mock.patch.object(blm, "_APP_DIR", self.app_dir)]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        # Cycle 8 slice E: _build_last_match no longer closes the SHARED
        # per-thread cached ro_conn (closing it poisoned the cache for
        # later same-thread callers). Evict + close our db's cached conn
        # here so Windows lets TemporaryDirectory delete the file.
        from dashboard import _context
        cached = getattr(_context.DB_CONN_LOCAL, "conns", {}).pop(
            str(self.app_dir / "data" / "match_history.db"), None)
        if cached is not None:
            cached.close()
        self._tmp.cleanup()

    def _build(self, **kw):
        import dashboard.builders_last_match as blm
        return blm._build_last_match(**kw)

    def test_latest_path_unchanged(self):
        """No match_ts -> newest non-TFT row (Caitlyn 2026-06-03 14:45)."""
        out = self._build()
        self.assertTrue(out["found"])
        self.assertEqual(out["match"]["champion"], "Caitlyn")
        self.assertEqual(out["match"]["timestamp"], "2026-06-03 14:45:00")

    def test_ts_selects_specific_older_row(self):
        """match_ts pins the Jinx game even though two newer rows exist."""
        out = self._build(match_ts="2026-06-01 12:00:00")
        self.assertTrue(out["found"])
        self.assertEqual(out["match"]["champion"], "Jinx")
        self.assertEqual(out["match"]["timestamp"], "2026-06-01 12:00:00")
        self.assertEqual(out["match"]["mode"], "SR")

    def test_ts_selects_middle_aram_row(self):
        out = self._build(match_ts="2026-06-02 13:30:00")
        self.assertTrue(out["found"])
        self.assertEqual(out["match"]["champion"], "Lux")
        self.assertEqual(out["match"]["mode"], "ARAM")

    def test_unknown_ts_returns_not_found(self):
        """A ts with no row must NOT silently fall back to latest - that
        would clobber the operator's selection with the wrong match."""
        out = self._build(match_ts="1999-01-01 00:00:00")
        self.assertFalse(out["found"])
        self.assertIsNone(out["match"])

    def test_ts_never_selects_tft_row(self):
        """Even an exact TFT timestamp is excluded (mode != 'TFT' guard)."""
        out = self._build(match_ts="2026-06-03 15:10:00")
        self.assertFalse(out["found"])

    def test_baseline_excludes_selected_row_by_id(self):
        """The Quick Review baseline must drop the selected row. With the
        Jinx row selected, the 2 other non-TFT rows back the baseline."""
        out = self._build(match_ts="2026-06-01 12:00:00")
        self.assertTrue(out["found"])
        # 3 non-TFT rows total, minus the selected one = 2.
        self.assertEqual(out["history_count"], 2)


if __name__ == "__main__":
    unittest.main()
