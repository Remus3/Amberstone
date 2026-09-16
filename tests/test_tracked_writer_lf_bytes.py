"""RM-441: writers of TRACKED files must put LF bytes on disk.

On Windows a text-mode write (``Path.write_text`` or ``open(..., "w")`` with
no ``newline=``) rewrites every LF as CRLF. Commit 585295446 fixed the main
outputs of scripts/data_pipeline.py; this module pins the sibling writers of
tracked files that still went through ``write_text``:

    scripts/data_pipeline.py        cmd_aram_builds -> aram_champion_builds.json
    scripts/patch_champion.py       save_builds     -> aram_champion_builds.json
    scripts/merge_refresh_builds.py merge_aram / merge_sr / merge_arena
    tools/gen_archmap.py            _update_file    -> docs/ARCHITECTURE.md
    tools/gen_state_schema.py       main            -> web/js/lib/state_schema.js
    tools/hotfix_ranged_only_melee_loadouts.py main -> data/champion_loadouts.json

CI runs on Linux, where ``write_text`` never translates, so a bare "no CR
bytes" assertion would pass against the unfixed code there. The ``force_crlf``
fixture therefore reproduces the Windows translation on every platform by
defaulting ``Path.write_text`` to ``newline="\\r\\n"``; the positive control
proves that harness makes a plain text-mode write FAIL the assertion.

Every path is redirected into ``tmp_path``; no network, no real repo file is
written.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

import scripts.data_pipeline as dp
import scripts.merge_refresh_builds as mrb
import scripts.patch_champion as pc
import tools.gen_archmap as gam
import tools.gen_state_schema as gss
import tools.hotfix_ranged_only_melee_loadouts as hotfix


@pytest.fixture
def force_crlf(monkeypatch):
    """Make ``Path.write_text`` translate LF -> CRLF, as it does on Windows."""
    orig = pathlib.Path.write_text

    def _windows_like(self, data, encoding=None, errors=None, newline=None):
        return orig(self, data, encoding=encoding, errors=errors,
                    newline="\r\n" if newline is None else newline)

    monkeypatch.setattr(pathlib.Path, "write_text", _windows_like)


def _assert_lf_only(path: pathlib.Path) -> bytes:
    raw = path.read_bytes()
    assert raw, f"{path.name} is empty"
    # Anchor: content with no newline would pass the CR check vacuously.
    assert raw.count(b"\n") > 1, f"{path.name} has no line structure to check"
    n_crlf = raw.count(b"\r\n")
    assert n_crlf == 0, f"{path.name} carries {n_crlf} CRLF sequence(s)"
    return raw


# -- positive control ------------------------------------------------------------

def test_force_crlf_harness_makes_a_text_mode_write_fail(tmp_path, force_crlf):
    target = tmp_path / "control.json"
    target.write_text(json.dumps({"a": 1, "b": 2}, indent=2), encoding="utf-8")
    with pytest.raises(AssertionError, match="CRLF"):
        _assert_lf_only(target)


# -- scripts/data_pipeline.py cmd_aram_builds ----------------------------------------

def test_data_pipeline_aram_builds_writes_lf(tmp_path, monkeypatch, force_crlf):
    builds_file = tmp_path / "data" / "meta_build" / "aram_champion_builds.json"
    builds_file.parent.mkdir(parents=True)
    builds_file.write_bytes(json.dumps({
        "_note": "old",
        "Ahri": {"aram_tier": "C"},
        "Aatrox": {"aram_tier": "B"},
    }, indent=2).encode("utf-8"))
    meta = tmp_path / "data" / "meta"
    meta.mkdir(parents=True)
    (meta / "ddragon_champions.json").write_bytes(json.dumps({
        "data": {"Ahri": {"id": "Ahri", "key": "103"},
                 "Aatrox": {"id": "Aatrox", "key": "266"}},
    }).encode("utf-8"))
    monkeypatch.setattr(dp, "ROOT", tmp_path)
    monkeypatch.setattr(dp, "_get_live_version", lambda: "99.1.1")
    monkeypatch.setattr(dp, "_fetch_json",
                        lambda url, timeout=15: [[103, 0, 0, 56.0], [266, 0, 0, 50.0]])
    monkeypatch.setattr(sys, "argv", ["data_pipeline.py", "aram_builds"])

    assert dp.cmd_aram_builds(force=True) is True
    raw = _assert_lf_only(builds_file)
    doc = json.loads(raw.decode("utf-8"))
    assert doc["Ahri"]["aram_tier"] == "S"
    assert list(tmp_path.rglob("*.tmp")) == []


# -- scripts/patch_champion.py save_builds ------------------------------------------

def test_patch_champion_save_builds_writes_lf(tmp_path, monkeypatch, force_crlf):
    builds_file = tmp_path / "aram_champion_builds.json"
    monkeypatch.setattr(pc, "BUILDS_FILE", builds_file)
    payload = {"Ahri": {"aram_tier": "S", "core": ["Luden's Echo"]}}
    pc.save_builds(payload)
    raw = _assert_lf_only(builds_file)
    assert json.loads(raw.decode("utf-8")) == payload
    assert list(tmp_path.glob("*.tmp")) == []


# -- scripts/merge_refresh_builds.py -------------------------------------------------

@pytest.fixture
def _merge_tree(tmp_path, monkeypatch):
    refresh = tmp_path / "refresh"
    meta_build = tmp_path / "meta_build"
    refresh.mkdir()
    meta_build.mkdir()
    entry = {"champions": {"Ahri": {"core": ["Luden's Echo"], "tier": "S"}}}
    for mode in ("aram", "sr", "arena"):
        (refresh / f"{mode}_top30.json").write_bytes(json.dumps(entry).encode("utf-8"))
    for mode in ("aram", "sr"):
        (meta_build / f"{mode}_champion_builds.json").write_bytes(
            json.dumps({"Aatrox": {"core": []}}).encode("utf-8"))
    monkeypatch.setattr(mrb, "REFRESH_DIR", refresh)
    monkeypatch.setattr(mrb, "META_BUILD", meta_build)
    return meta_build


@pytest.mark.parametrize("fn_name, out_name", [
    ("merge_aram", "aram_champion_builds.json"),
    ("merge_sr", "sr_champion_builds.json"),
    ("merge_arena", "arena_champion_builds.json"),
])
def test_merge_refresh_builds_writes_lf(_merge_tree, force_crlf, fn_name, out_name):
    getattr(mrb, fn_name)(dry_run=False)
    raw = _assert_lf_only(_merge_tree / out_name)
    assert "Ahri" in json.loads(raw.decode("utf-8"))


# -- tools/gen_archmap.py _update_file -----------------------------------------------

def test_gen_archmap_update_file_writes_lf(tmp_path, force_crlf):
    doc = tmp_path / "ARCHITECTURE.md"
    doc.write_bytes(b"# Title\n\n<!-- archmap:start -->\nold\n<!-- archmap:end -->\ntail\n")
    new_block = "<!-- archmap:start -->\nrow one\nrow two\n<!-- archmap:end -->"
    assert gam._update_file(doc, "<!-- archmap:start", "<!-- archmap:end -->",
                            new_block, check=False) is True
    raw = _assert_lf_only(doc)
    assert b"row one\nrow two\n" in raw
    assert list(tmp_path.glob("*.tmp")) == []


# -- tools/gen_state_schema.py main --------------------------------------------------

def test_gen_state_schema_main_writes_lf(tmp_path, monkeypatch, force_crlf):
    out = tmp_path / "web" / "js" / "lib" / "state_schema.js"
    out.parent.mkdir(parents=True)
    monkeypatch.setattr(gss, "ROOT", tmp_path)
    monkeypatch.setattr(gss, "OUTPUT", out)
    monkeypatch.setattr(sys, "argv", ["gen_state_schema.py"])
    assert gss.main() == 0
    raw = _assert_lf_only(out)
    assert raw.decode("utf-8") == gss._generate()


# -- tools/hotfix_ranged_only_melee_loadouts.py main --------------------------------

def test_hotfix_ranged_only_melee_main_writes_lf(tmp_path, monkeypatch, force_crlf):
    loadouts = tmp_path / "champion_loadouts.json"
    payload = {"Garen": {"paths": {"default": {"items": ["Sunfire Aegis"]}}}}
    loadouts.write_bytes(json.dumps(payload).encode("utf-8"))
    monkeypatch.setattr(hotfix, "_LOADOUTS", loadouts)
    monkeypatch.setattr(hotfix, "apply", lambda data: 0)
    hotfix.main()
    raw = _assert_lf_only(loadouts)
    assert raw.endswith(b"}\n")
    assert json.loads(raw.decode("utf-8")) == payload
    assert list(tmp_path.glob("*.tmp")) == []
