# arch: PKG-6b bundle ships the updater's ownership baseline | section=tests | frozen=no
"""PKG-6b: tools/build_portable.py writes backend-manifest.json at the bundle
root - the install's ownership baseline the PKG-2 updater reads
(ops/launcher/updater.py INSTALLED_MANIFEST, read_installed / plan_apply).

Found while wiring PKG-6b: the updater's docstring says the bundle ships it
(PKG-4), but no builder wrote it. Without it a real install has no installed
version (every release reads as newer) and NO ownership baseline, so
plan_apply refuses any update that changes a file the install already has -
the backend could never live-update a real build.

  M1 the build writes it; it parses under the updater's own schema check
     (files only, no archive) and names every payload-eligible shipped file
     with its sha256 and size, and nothing the updater would refuse
  M2 version: --backend-version, else the bundle version when it is semver,
     else 0.0.0 (a local build: every published release is newer); a bad
     explicit version refuses the build
  M3 end to end: an update that CHANGES a shipped file plans cleanly on the
     built bundle (the refusal this closes)
  M4 the post-build verify accepts it (a generated file, like BUILD_MANIFEST)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ops.launcher import updater as up
from tests import test_build_portable_bundle_pkg as pkg4
from tests.test_launcher_updater import build_release
from tools import build_portable as bp


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """The PKG-4 suite's tiny RC-shaped git repo (same files, same commit)."""
    root = tmp_path / "repo"
    root.mkdir()
    for rel, text in pkg4.TRACKED.items():
        pkg4._write(root, rel, text)
    pkg4._git(root, "init", "-q")
    pkg4._git(root, "add", "-A")
    pkg4._commit(root)
    for rel, text in pkg4.UNTRACKED.items():
        pkg4._write(root, rel, text)
    pkg4._replace_lfs_with_real(root)
    return root


def _built(repo, tmp_path, **kw) -> Path:
    out = tmp_path / "out"
    assert bp.build(repo, out, embed="none", **kw) == 0
    return out


def _manifest(out: Path) -> dict:
    return json.loads((out / bp.INSTALLED_MANIFEST).read_text(encoding="ascii"))


def test_m1_the_bundle_ships_a_parseable_ownership_baseline(repo, tmp_path):
    out = _built(repo, tmp_path, version="9.9.9")
    assert bp.INSTALLED_MANIFEST == up.INSTALLED_MANIFEST
    raw = (out / bp.INSTALLED_MANIFEST).read_bytes()
    assert raw.isascii()
    man = up.parse_manifest_bytes(raw, require_archive=False)
    assert man.version == "9.9.9" and man.channel == "stable"
    files = man.file_map()
    for rel in ("main.py", "core/util.py", "web/index.html", "data/static.json",
                "dashboard/server.py", "LICENSE"):
        assert rel in files, rel
        data = (out / rel).read_bytes()
        assert files[rel].sha256 == hashlib.sha256(data).hexdigest()
        assert files[rel].size == len(data)
    # Shipped but never updatable by a payload: not in the baseline.
    for rel in ("start.bat", ".gitignore"):
        assert (out / rel).is_file(), rel
        assert rel not in files, rel
    for entry in man.files:
        up.check_payload_path(entry.path)
    assert up.installed_version(out) == "9.9.9"


@pytest.mark.parametrize("kw, want", [
    ({}, "0.0.0"),
    ({"version": "20261026"}, "0.0.0"),
    ({"version": "1.2.3"}, "1.2.3"),
    ({"version": "20261026", "backend_version": "2.0.0-rc.1"}, "2.0.0-rc.1"),
    # fix round: a release tag spelling (leading v) is the same version
    ({"version": "v1.2.3"}, "1.2.3"),
    ({"backend_version": "V2.0.1"}, "2.0.1"),
])
def test_m2_backend_version_rules(repo, tmp_path, kw, want):
    out = _built(repo, tmp_path, **kw)
    doc = _manifest(out)
    assert doc["version"] == want
    assert doc["channel"] == ("dev" if "-" in want else "stable")
    assert json.loads((out / bp.MANIFEST_NAME).read_text(encoding="utf-8"))[
        "backend_version"] == want


def test_m2_a_bad_explicit_backend_version_refuses_the_build(repo, tmp_path):
    assert bp.build(repo, tmp_path / "out", embed="none",
                    backend_version="v1") == 1


def test_m3_an_update_changing_a_shipped_file_plans_on_the_built_bundle(repo, tmp_path):
    out = _built(repo, tmp_path, version="1.0.0")
    new = {"core/helper.py": b"X = 2\n", "web/index.html": b"<html>v2</html>\n"}
    rel_dir = build_release(tmp_path / "rel", "1.0.1", new)
    src = up.LocalSource(rel_dir)
    staged = up.stage(out, src, src.release("1.0.1"))
    plan = up.plan_apply(out, staged, hot_reload_active=True)
    assert sorted(plan.changed) == ["core/helper.py", "web/index.html"]
    assert plan.created == ()
    assert plan.restart.app == "hot_reload"


def test_m4_verify_bundle_accepts_the_generated_baseline(repo, tmp_path):
    out = _built(repo, tmp_path)
    assert bp.INSTALLED_MANIFEST in bp.GENERATED_FILES
    assert bp.verify_bundle(out) == []
