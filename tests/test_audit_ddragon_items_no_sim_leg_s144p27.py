"""RM-1178: scripts/audit_ddragon_items.py audits no data/sim/ fixtures.

The script's "fixtures" leg globbed data/sim/*.json at the repo root. The only
producer of that directory, scripts/rebuild_sim_fixtures.py, was deleted as dead
in RM-1177 (pinned by tests/test_orphan_sim_fixtures_script_s144p26.py), and
data/sim/ is absent from the checkout and from every CI runner, so the leg
always printed "[fixtures] 0 unique item names" and fed nothing into the icon
check. These tests pin the leg as removed and pin what main() still does: it
checks the icon of every item id in the rewind history DB, exits 1 when one is
missing and 0 when none is, and never downloads without --download.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "audit_ddragon_items.py"
_VERSION = "16.14.1"


def _load():
    spec = importlib.util.spec_from_file_location("audit_ddragon_items_s144p27", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_db(path: Path, rows: list[tuple[int, ...]]) -> None:
    conn = sqlite3.connect(path)
    try:
        cols = ", ".join(f"item{i} INTEGER" for i in range(7))
        conn.execute(f"CREATE TABLE participants ({cols})")
        conn.executemany(
            "INSERT INTO participants VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def audit(tmp_path, monkeypatch):
    mod = _load()
    index = tmp_path / "items_index.json"
    index.write_text(json.dumps({
        "version": _VERSION,
        "byId": {"3089": "Rabadon's Deathcap", "3157": "Zhonya's Hourglass"},
    }), encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "INDEX_PATH", index)
    monkeypatch.setattr(mod, "DB_PATH", tmp_path / "rewind_history.db")

    def _no_download(*a, **k):
        raise AssertionError("download_icon called without --download")

    monkeypatch.setattr(mod, "download_icon", _no_download)
    item_dir = tmp_path / "web" / "data" / "ddragon" / _VERSION / "img" / "item"
    item_dir.mkdir(parents=True)
    return mod, item_dir


def test_fixtures_leg_is_gone():
    mod = _load()
    assert not hasattr(mod, "collect_from_fixtures")
    assert not hasattr(mod, "SIM_DIR")
    src = _SCRIPT.read_text(encoding="utf-8")
    assert "data/sim" not in src
    assert '"sim"' not in src


def test_missing_db_icon_exits_1(audit, capsys):
    mod, item_dir = audit
    _make_db(mod.DB_PATH, [(3089, 3157, 0, 0, 0, 0, 0)])
    (item_dir / "3089.png").write_bytes(b"x" * 64)
    assert mod.main() == 1
    out = capsys.readouterr().out
    assert "[fixtures]" not in out
    assert "3157  Zhonya's Hourglass" in out
    assert "3089  " not in out


def test_all_db_icons_present_exits_0(audit, capsys):
    mod, item_dir = audit
    _make_db(mod.DB_PATH, [(3089, 0, 0, 0, 0, 0, 0)])
    (item_dir / "3089.png").write_bytes(b"x" * 64)
    assert mod.main() == 0
    out = capsys.readouterr().out
    assert "[history] 1 unique item ids" in out
    assert "[fixtures]" not in out


def test_no_db_exits_0_with_nothing_to_check(audit, capsys):
    mod, _item_dir = audit
    assert not mod.DB_PATH.exists()
    assert mod.main() == 0
    assert "[history] 0 unique item ids" in capsys.readouterr().out
