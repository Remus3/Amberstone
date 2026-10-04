"""RM-372: `scripts/cache_ddragon_assets.py` joined `_index.json`'s
`latest_pulled` into two directory paths (and `fetch` creates them) with no
validation - safe only because today's two writers validate. It now checks
the same `<major>.<minor>.<patch>` shape as
`tools.ddragon_mirror_refresh.validate_version` before any join.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "cache_ddragon_assets_rm372", _ROOT / "scripts" / "cache_ddragon_assets.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


CDA = _load()


@pytest.fixture()
def tree(tmp_path, monkeypatch):
    vdir = tmp_path / "data" / "meta_build" / "ddragon"
    vdir.mkdir(parents=True)
    monkeypatch.setattr(CDA, "ROOT", tmp_path)
    monkeypatch.setattr(CDA, "VERSION_DIR", vdir)
    return tmp_path, vdir


def _dirs(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_dir())


@pytest.mark.parametrize("poison", ["../../../pwned", "maintenance", "16.1",
                                    "16.1.1\n", "", 16, None])
def test_poisoned_index_creates_no_directory(tree, poison, monkeypatch):
    root, vdir = tree
    (vdir / "_index.json").write_text(json.dumps({"latest_pulled": poison}))
    before = _dirs(root)
    fetched = []
    monkeypatch.setattr(CDA, "fetch", lambda url, dest, **k: fetched.append(dest) or False)
    with pytest.raises(ValueError):
        CDA.main()
    assert _dirs(root) == before
    assert fetched == []


def test_valid_version_is_returned(tree):
    _, vdir = tree
    (vdir / "_index.json").write_text(json.dumps({"latest_pulled": "16.14.1"}))
    assert CDA.latest_version() == "16.14.1"


def test_local_check_agrees_with_the_mirror_validator():
    from tools.ddragon_mirror_refresh import validate_version
    for v in ["16.14.1", "1.2.3", "../x", "maintenance", "16.1", "16.1.1\n", "a.b.c"]:
        try:
            validate_version(v)
            mirror_ok = True
        except ValueError:
            mirror_ok = False
        assert CDA.is_valid_version(v) is mirror_ok, v
