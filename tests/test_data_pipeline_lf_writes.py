"""scripts/data_pipeline.py must write its TRACKED outputs with LF bytes.

RC-PatchRefresh (weekly, Wed 11:07, `pythonw scripts/data_pipeline.py all`)
rewrites seven tracked files on a patch bump:

    data/meta/ddragon_champions.json
    data/meta/ddragon_items.json
    data/meta/ddragon_summoner_spells.json
    data/meta/ddragon_version.json
    web/data/champions_index.json
    web/data/items_index.json
    web/data/spells_index.json

On Windows `Path.write_text` translates every "\\n" to "\\r\\n", so the
2026-09-16 16.17.1 -> 16.18.1 refresh left all multi-line outputs CRLF on
disk and tripped tests/test_text_line_endings.py
::test_no_normalized_tracked_file_has_crlf_on_disk. The sibling writer
tools/ddragon_mirror_refresh.py already writes bytes for the same reason.

No network and no real repo tree: META / ROOT are redirected into tmp_path
and the two fetchers are stubbed.
"""
from __future__ import annotations

import json

import pytest

import scripts.data_pipeline as dp


_CHAMPS = {
    "type": "champion",
    "version": "99.1.1",
    "data": {
        "Aatrox": {"id": "Aatrox", "key": "266", "name": "Aatrox",
                   "stats": {"armor": 38, "hp": 650}},
        "Ahri": {"id": "Ahri", "key": "103", "name": "Ahri",
                 "stats": {"armor": 21, "hp": 590}},
    },
}
_ITEMS = {
    "type": "item",
    "version": "99.1.1",
    "data": {
        "3124": {"name": "Guinsoo's Rageblade", "gold": {"total": 3000}},
        "1001": {"name": "Boots", "gold": {"total": 300}},
    },
}
_SPELLS = {
    "type": "summoner",
    "version": "99.1.1",
    "data": {
        "SummonerFlash": {"id": "SummonerFlash", "key": "4", "name": "Flash",
                          "cooldown": [300], "image": {"full": "SummonerFlash.png"},
                          "modes": ["CLASSIC"]},
        "SummonerTeleport": {"id": "SummonerTeleport", "key": "12", "name": "Teleport",
                             "cooldown": [360], "image": {"full": "SummonerTeleport.png"},
                             "modes": ["CLASSIC"]},
    },
}


@pytest.fixture
def _tree(tmp_path, monkeypatch):
    meta = tmp_path / "data" / "meta"
    meta.mkdir(parents=True)
    (tmp_path / "web" / "data").mkdir(parents=True)
    monkeypatch.setattr(dp, "ROOT", tmp_path)
    monkeypatch.setattr(dp, "META", meta)
    monkeypatch.setattr(dp, "_get_live_version", lambda: "99.1.1")

    def _fake_fetch(url, timeout=15):
        if url.endswith("/champion.json"):
            return json.loads(json.dumps(_CHAMPS))
        if url.endswith("/item.json"):
            return json.loads(json.dumps(_ITEMS))
        if url.endswith("/summoner.json"):
            return json.loads(json.dumps(_SPELLS))
        raise AssertionError(f"unexpected fetch in test: {url}")

    monkeypatch.setattr(dp, "_fetch_json", _fake_fetch)
    return tmp_path


def _assert_lf_only(path, *, multiline: bool) -> None:
    raw = path.read_bytes()
    assert raw, f"{path.name} is empty"
    n_cr = raw.count(b"\r")
    assert n_cr == 0, f"{path.name} carries {n_cr} CR byte(s)"
    if multiline:
        # Anchor: a file with no newline at all would pass the CR check vacuously.
        assert raw.count(b"\n") > 1, f"{path.name} has no line structure to check"
    json.loads(raw.decode("utf-8"))


def test_cmd_ddragon_writes_meta_files_with_lf_bytes(_tree):
    assert dp.cmd_ddragon(force=True) is True
    meta = _tree / "data" / "meta"
    for name in ("ddragon_champions.json", "ddragon_items.json",
                 "ddragon_summoner_spells.json", "ddragon_version.json"):
        _assert_lf_only(meta / name, multiline=True)


def test_index_commands_write_lf_bytes(_tree):
    assert dp.cmd_ddragon(force=True) is True
    assert dp.cmd_items_index(force=True) is True
    assert dp.cmd_champions_index(force=True) is True
    assert dp.cmd_spells_index(force=True) is True
    web = _tree / "web" / "data"
    _assert_lf_only(web / "items_index.json", multiline=True)
    _assert_lf_only(web / "champions_index.json", multiline=True)
    # spells_index is deliberately compact (one line); still no CR allowed.
    _assert_lf_only(web / "spells_index.json", multiline=False)


def test_writes_leave_no_tmp_sidecar(_tree):
    assert dp.cmd_ddragon(force=True) is True
    assert dp.cmd_items_index(force=True) is True
    assert dp.cmd_champions_index(force=True) is True
    assert dp.cmd_spells_index(force=True) is True
    leftovers = sorted(p.name for p in _tree.rglob("*.tmp"))
    assert leftovers == []


def test_text_is_unchanged_apart_from_line_endings(_tree):
    """The fix must only change line endings, never the serialised text."""
    assert dp.cmd_ddragon(force=True) is True
    got = (_tree / "data" / "meta" / "ddragon_items.json").read_bytes().decode("utf-8")
    expected = json.dumps(dp._drop_throwback_rows("ddragon_items.json", _ITEMS),
                          indent=2, ensure_ascii=False)
    assert got == expected
