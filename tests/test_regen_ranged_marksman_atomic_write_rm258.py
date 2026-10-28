"""RM-258 residual: the item-213 ranged-marksman regen writes through core.polled_json.

`main()` in tools/regen_ranged_marksman_builds_item213.py rewrote
data/champion_loadouts.json through a fixed `<name>.json.tmp` scratch file
plus a bare Path.replace: no fsync before the rename, no WinError 5 retry,
and a scratch file left behind when the rename failed.

Each test points the tool's `_LOADOUTS` at a copy in tmp_path, swaps in a
fake DataSnapshot (champions keyed by display name, so the server's
`_resolve_champion_id` returns the name unchanged), pins
`_is_ranged_marksman`, stubs `_start_worktree_engine` (no temp DS server)
and `_regen_carry_path` (no engine call), and spies on
`core.polled_json.atomic_write_bytes`, so the real data file is never read
or written.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import polled_json
from tools import regen_ranged_marksman_builds_item213 as tool

_TRINITY = "Trinity Force"
_CLEAVER = "Black Cleaver"
_REGEN = ["Kraken Slayer", "Berserker's Greaves", "Infinity Edge",
          "Phantom Dancer", "Lord Dominik's Regards", "Bloodthirster"]
_KOGMAW = "Kog" + chr(0x2019) + "Maw"


class _FakeSnap:
    champions = {
        "Ashe": {"ranged": True},
        _KOGMAW: {"ranged": True},
        "Garen": {"ranged": False},
    }

    @classmethod
    def load(cls):
        return cls()


def _seed(tmp_path: Path, monkeypatch) -> Path:
    data = {
        "champions": {
            "Ashe": {"variants": {"sr-collapsed": {
                "items": [_TRINITY, "Kraken Slayer"],
                "build_paths": [
                    {"key": "adc-crit", "_is_primary": True,
                     "items": [_TRINITY, "Kraken Slayer"]},
                    {"key": "mage-flavor",
                     "items": ["Luden's Echo", _CLEAVER, "Rabadon's Deathcap"]},
                ]}}},
            _KOGMAW: {"variants": {"aram-collapsed": {
                "items": ["Kraken Slayer"],
                "build_paths": [{"key": "adc-onhit", "_is_primary": True,
                                 "items": ["Kraken Slayer"]}]}}},
            "Garen": {"variants": {"sr-collapsed": {
                "items": [_TRINITY, _CLEAVER],
                "build_paths": [{"key": "bruiser", "_is_primary": True,
                                 "items": [_TRINITY, _CLEAVER]}]}}},
        },
    }
    out = tmp_path / "champion_loadouts.json"
    out.write_bytes((json.dumps(data, indent=2) + "\n").encode("utf-8"))
    monkeypatch.setattr(tool, "_LOADOUTS", out)
    monkeypatch.setattr(tool, "DataSnapshot", _FakeSnap)
    monkeypatch.setattr(tool, "_is_ranged_marksman",
                        lambda rec: bool(rec.get("ranged")))
    monkeypatch.setattr(tool, "_start_worktree_engine", lambda port: None)
    monkeypatch.setattr(tool, "_regen_carry_path",
                        lambda champ, mode, boots: list(_REGEN))
    return out


def _expected(out: Path) -> bytes:
    data = json.loads(out.read_text(encoding="utf-8"))
    ashe = data["champions"]["Ashe"]["variants"]["sr-collapsed"]
    # The carry path is two items, one off-class: regenerated whole.
    ashe["build_paths"][0]["items"] = list(_REGEN)
    # The non-carry flavor path keeps its identity, deny item stripped.
    ashe["build_paths"][1]["items"] = ["Luden's Echo", "Rabadon's Deathcap"]
    ashe["items"] = list(_REGEN)
    # The tool's historical text: ensure_ascii, indent 2, one trailing LF.
    return (json.dumps(data, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def _backups(tmp_path: Path) -> list[str]:
    return sorted(p.name for p in tmp_path.iterdir()
                  if ".json.bak-item213-" in p.name)


@pytest.fixture
def spy(monkeypatch):
    calls = []
    real = polled_json.atomic_write_bytes

    def _spy(path, data):
        calls.append((Path(path), data))
        real(path, data)

    monkeypatch.setattr(polled_json, "atomic_write_bytes", _spy)
    return calls


def test_main_writes_through_polled_json(tmp_path, monkeypatch, spy):
    out = _seed(tmp_path, monkeypatch)
    prior = out.read_bytes()
    want = _expected(out)

    assert tool.main([]) == 0

    raw = out.read_bytes()
    assert [p for p, _ in spy] == [out]
    assert spy[0][1] == raw == want
    assert b"\r\n" not in raw
    assert raw.endswith(b"}\n")
    assert all(b < 0x80 for b in raw)
    # The only other file is the timestamped backup of the prior bytes.
    backups = _backups(tmp_path)
    assert len(backups) == 1
    assert (tmp_path / backups[0]).read_bytes() == prior
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [out.name] + backups)
    champs = json.loads(raw.decode("utf-8"))["champions"]
    # A clean ranged row and a non-marksman row are untouched.
    assert champs[_KOGMAW]["variants"]["aram-collapsed"]["items"] == [
        "Kraken Slayer"]
    assert champs["Garen"]["variants"]["sr-collapsed"]["items"] == [
        _TRINITY, _CLEAVER]


def test_dry_run_writes_nothing(tmp_path, monkeypatch, spy):
    out = _seed(tmp_path, monkeypatch)
    prior = out.read_bytes()
    assert tool.main(["--dry-run"]) == 0
    assert spy == []
    assert out.read_bytes() == prior
    assert sorted(p.name for p in tmp_path.iterdir()) == [out.name]


def test_refused_swap_keeps_the_prior_file_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    out = _seed(tmp_path, monkeypatch)
    prior = out.read_bytes()
    fired = []

    def _refuse(a, b):
        fired.append((a, b))
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json, "_replace_with_retry", _refuse)
    with pytest.raises(PermissionError):
        tool.main([])
    assert len(fired) == 1
    assert out.read_bytes() == prior
    backups = _backups(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [out.name] + backups)


def test_rerun_is_a_no_op(tmp_path, monkeypatch, spy):
    out = _seed(tmp_path, monkeypatch)
    tool.main([])
    written = out.read_bytes()
    listing = sorted(p.name for p in tmp_path.iterdir())
    assert tool.main([]) == 0
    assert len(spy) == 1
    assert out.read_bytes() == written
    assert sorted(p.name for p in tmp_path.iterdir()) == listing


def test_tool_carries_no_hand_rolled_rename():
    text = Path(tool.__file__).read_text(encoding="utf-8")
    assert "os.replace" not in text
    assert ".json.tmp" not in text
    assert "tmp.replace(" not in text
    assert "polled_json.atomic_write_bytes(" in text
