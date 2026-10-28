"""RM-258 residual: the item-269 sibling-pollution hotfix writes through core.polled_json.

`main()` in tools/hotfix_sibling_pollution_item269.py rewrote
data/champion_loadouts.json through a fixed `<name>.json.tmp` scratch file
plus a bare os.replace: no fsync before the rename, no WinError 5 retry, and
a scratch file left behind when the rename failed.

Each test points the tool's `_LOADOUTS` at a copy in tmp_path and spies on
`core.polled_json.atomic_write_bytes`, so the real data file is never read or
written.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import polled_json
from tools import hotfix_sibling_pollution_item269 as tool

_THIN = ["Blade of The Ruined King", "Berserker's Greaves",
         "Lord Dominik's Regards", "Runaan's Hurricane"]


def _seed(tmp_path: Path, monkeypatch) -> Path:
    gwen = [
        {"key": "ap-bruiser", "label": "AP Bruiser", "_is_primary": True,
         "items": ["Trinity Force", "Sterak's Gage"]},
    ]
    khazix = [
        {"key": "lethality", "label": "Lethality", "_is_primary": True,
         "items": ["Youmuu's Ghostblade"]},
        {"key": "sr-mage", "label": "Mage", "items": ["Luden's Echo"]},
    ]
    ashe = [
        {"key": "aram-carry", "label": "Carry", "_is_primary": True,
         "items": list(_THIN)},
    ]
    data = {
        "champions": {
            "Kai" + chr(0x2019) + "Sa": {"variants": {}},
            "Gwen": {"variants": {"aram-collapsed": {"build_paths": gwen}}},
            "Kha'Zix": {"variants": {"sr-collapsed": {"build_paths": khazix}}},
            "Ashe": {"variants": {"aram-collapsed": {"build_paths": ashe}}},
        },
    }
    out = tmp_path / "champion_loadouts.json"
    out.write_bytes((json.dumps(data, indent=2) + "\n").encode("utf-8"))
    monkeypatch.setattr(tool, "_LOADOUTS", out)
    return out


def _expected(out: Path) -> bytes:
    data = json.loads(out.read_text(encoding="utf-8"))
    assert tool.apply(data) == 3
    return (json.dumps(data, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


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
    want = _expected(out)

    tool.main()

    assert [p for p, _ in spy] == [out]
    assert spy[0][1] == out.read_bytes() == want
    assert b"\r\n" not in out.read_bytes()
    assert all(b < 0x80 for b in out.read_bytes())
    assert sorted(p.name for p in tmp_path.iterdir()) == [out.name]
    champs = json.loads(out.read_text(encoding="utf-8"))["champions"]
    gwen = champs["Gwen"]["variants"]["aram-collapsed"]
    _key, label, items = tool._AP[("Gwen", "aram-collapsed", "ap-bruiser")]
    assert gwen["build_paths"][0]["items"] == items
    assert gwen["build_paths"][0]["label"] == label
    assert gwen["items"] == items
    kz = champs["Kha'Zix"]["variants"]["sr-collapsed"]["build_paths"]
    assert [p["key"] for p in kz] == ["lethality"]
    ashe = champs["Ashe"]["variants"]["aram-collapsed"]
    assert ashe["items"] == tool._ARAM_CARRY["Ashe"]


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
        tool.main()
    assert len(fired) == 1
    assert out.read_bytes() == prior
    assert sorted(p.name for p in tmp_path.iterdir()) == [out.name]


def test_rerun_rewrites_the_same_bytes(tmp_path, monkeypatch, spy):
    out = _seed(tmp_path, monkeypatch)
    tool.main()
    written = out.read_bytes()
    tool.main()
    assert len(spy) == 2
    assert spy[1][1] == written == out.read_bytes()
    assert sorted(p.name for p in tmp_path.iterdir()) == [out.name]


def test_tool_carries_no_hand_rolled_rename():
    text = Path(tool.__file__).read_text(encoding="utf-8")
    assert "os.replace" not in text
    assert ".json.tmp" not in text
    assert "polled_json.atomic_write_bytes(" in text
