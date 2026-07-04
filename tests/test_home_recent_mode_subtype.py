"""A6 data-completeness: Home Recent rows derive ``mode_subtype`` from the
queueId already stored in each row's ``lcu_match_detail`` blob.

Operator ruling (HOME_QA 2026-07-04, item A6): Recent ``mode_subtype`` was a
hardcoded ``None`` passthrough - the "no queue_id store" defect. Ground truth
(probed 2026-07-04): every LCU-ingested row's ``raw_data.lcu_match_detail``
already carries ``queueId`` at top level (98 Mayhem q2400 / 47 Ranked q420 /
2 Draft q400 / 1 event in the live DB), so the sub-variant derives from
existing data - NO queue_id column / schema migration is needed.

Scope per the ruling: the sub-variant split the operator asked for is ARAM
Classic (q450) vs ARAM Mayhem (q2400). Modes with no Classic/Mayhem split
(SR / Arena) stay None. NO display change - the field is populated for
payload-completeness; the FE does not consume it yet.

Fixture pattern mirrors tests/test_home_mode_filter.py:143-167 (_APP_DIR +
_get_lcu_for_rank monkeypatch, temp-dir conn eviction). ASCII-only.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_PUUID = "PUUID-TEST-0001"


def _detail_blob(queue_id: int | None, items=(1001, 3006, 0, 0, 0, 0)) -> str:
    """A raw_data blob shaped like a real LCU-ingested row (the subset
    _lcu_build_items / _lcu_queue_subtype read). queue_id=None -> a
    pre-ingest row (no lcu_match_detail)."""
    if queue_id is None:
        return ""
    stats = {f"item{i}": int(items[i]) for i in range(6)}
    stats["win"] = True
    return json.dumps({
        "tracked_puuid": _PUUID,
        "lcu_match_detail": {
            "queueId": queue_id,
            "participantIdentities": [
                {"participantId": 1, "player": {"puuid": _PUUID}},
            ],
            "participants": [{"participantId": 1, "stats": stats}],
        },
    })


def _make_db(path: Path, rows) -> None:
    # rows: (ts, mode, champion, raw_data)
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE matches ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  timestamp TEXT, mode TEXT, champion TEXT, grade TEXT,"
        "  game_time_s INTEGER, kills INTEGER, deaths INTEGER,"
        "  assists INTEGER, cs INTEGER, cs_per_min REAL,"
        "  gold INTEGER, gold_per_min REAL, kda_str TEXT,"
        "  kp_pct REAL, label TEXT, raw_data TEXT,"
        "  game_id INTEGER DEFAULT 0)"
    )
    for ts, mode, champ, raw in rows:
        conn.execute(
            "INSERT INTO matches (timestamp, mode, champion, grade,"
            " game_time_s, kills, deaths, assists, cs, cs_per_min,"
            " gold_per_min, kda_str, label, raw_data)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts, mode, champ, "A", 1200, 5, 3, 8, 40, 3.0, 600.0,
             "5/3/8", "", raw),
        )
    conn.commit()
    conn.close()


def _seed():
    now = datetime.now()
    t = lambda h: (now - timedelta(hours=h)).strftime("%Y-%m-%d %H:%M:%S")  # noqa: E731
    # newest first -> Recent shows these top 3 (LIMIT 3)
    return [
        (t(1), "ARAM", "Ziggs",  _detail_blob(2400)),   # Mayhem
        (t(2), "ARAM", "Sona",   _detail_blob(450)),    # Classic
        (t(3), "SR",   "Ahri",   _detail_blob(420)),    # Ranked SR -> None
    ]


def _build():
    import dashboard.builders_home as H
    with TemporaryDirectory() as td:
        app_dir = Path(td)
        (app_dir / "data").mkdir()
        _make_db(app_dir / "data" / "match_history.db", _seed())
        try:
            with mock.patch.object(H, "_get_lcu_for_rank", return_value=None):
                with mock.patch.object(H, "_APP_DIR", app_dir):
                    return H._build_home_summary()
        finally:
            from dashboard import _context
            conns = getattr(_context.DB_CONN_LOCAL, "conns", {})
            for k in [k for k in list(conns.keys())
                      if k.startswith(str(app_dir))]:
                c = conns.pop(k, None)
                if c is not None:
                    c.close()


def _recent_by_champ(out, champ):
    for r in out["recent"]:
        if r["champion"] == champ:
            return r
    raise AssertionError(f"{champ} not in recent: {out['recent']}")


def test_aram_mayhem_subtype():
    out = _build()
    assert _recent_by_champ(out, "Ziggs")["mode_subtype"] == "Mayhem"


def test_aram_classic_subtype():
    out = _build()
    assert _recent_by_champ(out, "Sona")["mode_subtype"] == "Classic"


def test_sr_row_has_no_subtype():
    out = _build()
    assert _recent_by_champ(out, "Ahri")["mode_subtype"] is None


def test_pre_ingest_row_subtype_none():
    # A row with no lcu_match_detail blob -> None (unchanged behavior).
    import dashboard.builders_home as H
    assert H._lcu_queue_subtype("") is None
    assert H._lcu_queue_subtype(None) is None
    assert H._lcu_queue_subtype('{"no": "detail"}') is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
