"""RM-1179 (a): audit_ddragon_items --download exits on what is STILL missing.

main(download=True) used to return 0 only when the PRE-download `missing` list
was empty, so a run that fetched every missing icon still exited 1 (and the
run printed "ok all pulled" beside a failing exit code). The exit code now
reflects `still_missing`, the icons absent after the download attempt: 0 when
every one was pulled, 1 when any is still absent. Without --download nothing
changes (pinned by tests/test_audit_ddragon_items_no_sim_leg_s144p27.py).

download_icon is stubbed: no test here touches the network.
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
    spec = importlib.util.spec_from_file_location("audit_ddragon_items_s144p28", _SCRIPT)
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
    item_dir = tmp_path / "web" / "data" / "ddragon" / _VERSION / "img" / "item"
    item_dir.mkdir(parents=True)
    _make_db(mod.DB_PATH, [(3089, 3157, 0, 0, 0, 0, 0)])
    return mod, item_dir


def _stub_download(monkeypatch, mod, pulls: set[str]) -> list[str]:
    """Stub download_icon: write the icon for ids in `pulls`, fail the rest.
    Returns the list of ids it was asked for, in call order."""
    calls: list[str] = []

    def _fake(version, iid, dest):
        calls.append(iid)
        assert version == _VERSION
        if iid in pulls:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"\x89PNG" + b"x" * 64)
            return "ddragon"
        return None

    monkeypatch.setattr(mod, "download_icon", _fake)
    return calls


def test_download_pulling_every_missing_icon_exits_0(audit, monkeypatch, capsys):
    mod, item_dir = audit
    calls = _stub_download(monkeypatch, mod, {"3089", "3157"})
    assert mod.main(download=True) == 0
    assert calls == ["3089", "3157"]
    assert (item_dir / "3089.png").is_file()
    assert (item_dir / "3157.png").is_file()
    assert "ok all pulled" in capsys.readouterr().out


def test_download_leaving_one_missing_exits_1(audit, monkeypatch, capsys):
    mod, item_dir = audit
    calls = _stub_download(monkeypatch, mod, {"3089"})
    assert mod.main(download=True) == 1
    assert calls == ["3089", "3157"]
    out = capsys.readouterr().out
    assert "1 still missing after download attempt" in out
    assert "ok all pulled" not in out


def test_download_pulling_nothing_exits_1(audit, monkeypatch, capsys):
    mod, _item_dir = audit
    _stub_download(monkeypatch, mod, set())
    assert mod.main(download=True) == 1
    assert "2 still missing after download attempt" in capsys.readouterr().out


def test_download_with_nothing_missing_exits_0_without_a_fetch(audit, monkeypatch):
    mod, item_dir = audit
    (item_dir / "3089.png").write_bytes(b"x" * 64)
    (item_dir / "3157.png").write_bytes(b"x" * 64)
    calls = _stub_download(monkeypatch, mod, set())
    assert mod.main(download=True) == 0
    assert calls == []


def test_no_download_still_exits_1_on_a_missing_icon(audit, monkeypatch):
    mod, _item_dir = audit

    def _no_download(*a, **k):
        raise AssertionError("download_icon called without --download")

    monkeypatch.setattr(mod, "download_icon", _no_download)
    assert mod.main() == 1
