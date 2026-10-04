"""RM-445 pipeline half: cmd_runes must refresh a stale runes file on a version change.

Before the fix ``cmd_runes`` skipped the runesReforged.json fetch whenever
``data/meta/ddragon_runes.json`` already existed, so runes stayed at whatever
patch first wrote them. The fix records the patch the runes file was fetched
for in a sidecar (``ddragon_runes_version.json``) and refetches when it differs
from the live patch - but does NOT refetch on every run at the same patch.

No network and no real repo file: every path is redirected into tmp_path and
``_fetch_json`` / ``_download_icon`` are stubbed.
"""
from __future__ import annotations

import json

import pytest

import scripts.data_pipeline as dp


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    meta = tmp_path / "meta"
    icons = tmp_path / "icons"
    meta.mkdir()
    icons.mkdir()
    monkeypatch.setattr(dp, "META", meta)
    monkeypatch.setattr(dp, "ICONS", icons)
    monkeypatch.setattr(dp, "_download_icon", lambda *a, **k: False)
    state = {"live": "16.18.1", "fetches": []}

    def _fetch(url, timeout=15):
        state["fetches"].append(url)
        return [{"id": 1, "name": "Tree@" + state["live"], "icon": "", "slots": []}]

    monkeypatch.setattr(dp, "_fetch_json", _fetch)
    monkeypatch.setattr(dp, "_get_live_version", lambda: state["live"])
    return meta, state


def _runes(meta):
    return json.loads((meta / "ddragon_runes.json").read_bytes().decode("utf-8"))


def test_stale_existing_runes_file_is_refreshed_on_version_change(pipeline):
    meta, state = pipeline
    # A runes file left over from an older patch, with no version record.
    (meta / "ddragon_runes.json").write_bytes(
        json.dumps([{"id": 1, "name": "Tree@16.10.1", "icon": "", "slots": []}]).encode("utf-8"))
    assert dp.cmd_runes() is True
    assert _runes(meta)[0]["name"] == "Tree@16.18.1"
    assert len(state["fetches"]) == 1


def test_runes_not_refetched_at_the_same_patch(pipeline):
    meta, state = pipeline
    assert dp.cmd_runes() is True
    assert dp.cmd_runes() is True
    assert len(state["fetches"]) == 1, state["fetches"]


def test_runes_refetched_when_live_patch_moves(pipeline):
    meta, state = pipeline
    assert dp.cmd_runes() is True
    state["live"] = "16.19.1"
    assert dp.cmd_runes() is True
    assert len(state["fetches"]) == 2
    assert _runes(meta)[0]["name"] == "Tree@16.19.1"
    sidecar = json.loads((meta / "ddragon_runes_version.json").read_bytes().decode("utf-8"))
    assert sidecar["version"] == "16.19.1"
