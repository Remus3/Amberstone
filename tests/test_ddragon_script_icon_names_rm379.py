"""RM-379: three `scripts/` DDragon downloaders joined a wire-supplied
`image.full` / rune `icon` straight into a filesystem path with no
validator - including `scripts/data_pipeline.py`, run by the registered
RC-PatchRefresh scheduled task.

Every site now routes the name through `lib.icons.downloader._safe_basename`
(the RM-359 validator) before the WRITE CALL; a hostile name is skipped, and
a legitimate multi-segment rune icon path still downloads (flattened to its
basename, as before) - the load-bearing half, since a validator that rejects
every rune path would silently turn the downloader into a no-op.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

import scripts.data_pipeline as dp

_ROOT = Path(__file__).resolve().parent.parent
HOSTILE = [".", "..", "../../x.png", "..\\..\\x.png", "sub/x.png", ".hidden.png"]


@pytest.fixture()
def dirs(tmp_path, monkeypatch):
    meta, icons = tmp_path / "meta", tmp_path / "icons"
    meta.mkdir()
    icons.mkdir()
    monkeypatch.setattr(dp, "META", meta)
    monkeypatch.setattr(dp, "ICONS", icons)
    monkeypatch.setattr(dp, "_get_live_version", lambda: "16.14.1")
    calls = []
    monkeypatch.setattr(dp, "_download_icon",
                        lambda url, dest, label="": calls.append(dest) or True)
    return meta, icons, calls


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


@pytest.mark.parametrize("bad", HOSTILE)
def test_cmd_icons_skips_hostile_image_full(dirs, bad):
    meta, icons, calls = dirs
    data = {"data": {"Evil": {"image": {"full": bad}},
                     "Ahri": {"image": {"full": "Ahri.png"}}}}
    (meta / "ddragon_champions.json").write_text(json.dumps(data))
    (meta / "ddragon_summoner_spells.json").write_text(json.dumps(data))
    dp.cmd_icons()
    assert all(_within(d, icons) and d.name not in (".", "..") for d in calls)
    assert sorted(d.name for d in calls) == ["Ahri.png", "Ahri.png"]


def test_cmd_runes_keeps_multi_segment_rune_paths(dirs):
    meta, icons, calls = dirs
    runes = [{"icon": "perk-images/Styles/7200_Domination.png", "name": "Dom",
              "slots": [{"runes": [
                  {"icon": "perk-images/Styles/Domination/Electrocute/Electrocute.png",
                   "name": "Electrocute"},
                  {"icon": "..", "name": "Evil"},
              ]}]}]
    (meta / "ddragon_runes.json").write_text(json.dumps(runes))
    (meta / "ddragon_runes_version.json").write_text(json.dumps({"version": "16.14.1"}))
    dp.cmd_runes()
    names = sorted(d.name for d in calls)
    assert names == ["7200_Domination.png", "Electrocute.png"]
    assert all(_within(d, icons) for d in calls)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, _ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("bad", HOSTILE)
def test_cache_ddragon_assets_skips_hostile_image_full(tmp_path, monkeypatch, bad):
    cda = _load("cache_ddragon_assets_rm379", "scripts/cache_ddragon_assets.py")
    vdir = tmp_path / "data" / "meta_build" / "ddragon"
    (vdir / "16.14.1").mkdir(parents=True)
    (vdir / "_index.json").write_text(json.dumps({"latest_pulled": "16.14.1"}))
    (vdir / "16.14.1" / "item.json").write_text(json.dumps(
        {"data": {"1": {"image": {"full": bad}}, "2": {"image": {"full": "2.png"}}}}))
    (vdir / "16.14.1" / "champion.json").write_text(json.dumps(
        {"data": {"Ahri": {"image": {"full": "Ahri.png"}}}}))
    monkeypatch.setattr(cda, "ROOT", tmp_path)
    monkeypatch.setattr(cda, "VERSION_DIR", vdir)
    calls = []
    monkeypatch.setattr(cda, "fetch", lambda url, dest, **k: calls.append(dest) or False)
    cda.main()
    root = tmp_path / "web" / "data" / "ddragon" / "16.14.1"
    assert sorted(d.name for d in calls) == ["2.png", "Ahri.png"]
    assert all(_within(d, root) for d in calls)


def test_audit_download_refuses_unsafe_id(tmp_path):
    mod = _load("audit_ddragon_items_rm379", "scripts/audit_ddragon_items.py")
    assert mod.safe_icon_dest(tmp_path, "../../evil") is None
    assert mod.safe_icon_dest(tmp_path, "3089") == tmp_path / "3089.png"
