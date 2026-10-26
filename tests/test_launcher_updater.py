"""PKG-2: the launcher's backend updater (docs/PACKAGING_PLAN.md 3.4).

Acceptance (slice PKG-2, docs/PACKAGING_PLAN.md section 4), one group each:

  U1 manifest parse with a schema check
  U2 a sha256 mismatch, or a path outside the allow-list, refuses the WHOLE
     update (nothing staged, no partial left behind)
  U3 staging is atomic (a finished staging dir or none; restage replaces)
  U4 the deploy request verifies with the per-install key - checked with the
     REAL deploy worker (ops/rc_transactional_deploy.py verify_request and its
     own containment pass), and applied end to end through its do_deploy
  U5 apply is deferred while a game is live (no request written)
  U6 no network in tests: local fixture releases, an injected GitHub fetch,
     and socket creation made to fail
  U7 the needs-restart classifier (asset -> none, watched .py -> hot reload,
     frozen / unwatched / data -> supervised restart, out-of-process service
     code / supervisor / launcher / dependencies -> relaunch of the named
     services), pinned against core/hot_reload.py so the mirror cannot drift
  U8 rollback re-deploys the verified pre-update backup; files the update
     created are moved to a quarantine folder, never deleted

Every root is tmp_path; no test touches the live tree or the network.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import socket
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

from ops.launcher import updater as up

ROOT = Path(__file__).resolve().parent.parent
UPDATER_PY = ROOT / "ops" / "launcher" / "updater.py"
SERVICES_JSON = ROOT / "ops" / "launcher" / "services.json"
BUILDER_YML = ROOT / "rc-shell" / "electron-builder.yml"
KEY = "ab" * 32

BASE_FILES = {
    "core/a.py": b"A = 1\n",
    "web/js/main.js": b"// v1\n",
    "data/x.json": b"{}\n",
}
NEW_FILES = {
    "core/a.py": b"A = 2\n",
    "web/js/main.js": b"// v1\n",
    "data/x.json": b"{}\n",
    "core/b.py": b"B = 1\n",
}


def no_game() -> None:
    return None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------- fixtures


def build_release(dirpath: Path, version: str, files: dict, *, channel="stable",
                  min_shell=None, manifest_files=None, zip_files=None,
                  zip_extra=None, archive_sha=None, mutate=None) -> Path:
    """Write backend-<ver>.zip + backend-<ver>.json into `dirpath`."""
    dirpath.mkdir(parents=True, exist_ok=True)
    zpath = dirpath / f"backend-{version}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, data in (zip_files if zip_files is not None else files).items():
            zf.writestr(rel, data)
        for rel, data in (zip_extra or {}).items():
            zf.writestr(rel, data)
    blob = zpath.read_bytes()
    entries = manifest_files if manifest_files is not None else [
        {"path": rel, "sha256": _sha(d), "size": len(d)}
        for rel, d in sorted(files.items())]
    doc = {"schema": 1, "kind": "amberstone-backend", "version": version,
           "channel": channel,
           "archive": {"name": zpath.name, "sha256": archive_sha or _sha(blob),
                       "size": len(blob)},
           "files": entries}
    if min_shell:
        doc["min_shell_version"] = min_shell
    if mutate:
        mutate(doc)
    (dirpath / f"backend-{version}.json").write_bytes(
        json.dumps(doc, indent=1).encode("ascii"))
    return dirpath


def make_root(tmp_path: Path, live=None, *, key=True, shipped="1.0.0",
              ignore=True) -> Path:
    """An installed backend root: live files, a deploy key, the bundle's
    shipped backend-manifest.json naming the files it owns, and the shipped
    ignore list (the repo's real .gitignore, byte for byte)."""
    root = tmp_path / "install"
    (root / "ops" / "runtime").mkdir(parents=True)
    if ignore:
        (root / ".gitignore").write_bytes((ROOT / ".gitignore").read_bytes())
    if key:
        (root / "ops" / "runtime" / "deploy_request.key").write_text(
            KEY + "\n", encoding="ascii")
    live = BASE_FILES if live is None else live
    for rel, data in live.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    if shipped:
        doc = {"schema": 1, "kind": "amberstone-backend", "version": shipped,
               "channel": "stable",
               "files": [{"path": rel, "sha256": _sha(d), "size": len(d)}
                         for rel, d in sorted(live.items())]}
        (root / up.INSTALLED_MANIFEST).write_text(json.dumps(doc), encoding="ascii")
    return root


def staged_root(tmp_path, files=None, version="1.1.0", **kw):
    root = make_root(tmp_path)
    rel_dir = build_release(tmp_path / "rel", version, NEW_FILES if files is None else files, **kw)
    src = up.LocalSource(rel_dir)
    staged = up.stage(root, src, src.release(version), shell_version="9.9.9")
    return root, staged


def _no_partials(root: Path) -> None:
    sdir = root / "ops" / "runtime" / "staging"
    if sdir.is_dir():
        left = [p.name for p in sdir.iterdir() if p.name.startswith(".")]
        assert left == [], left


def _requests(root: Path) -> list:
    d = root / "ops" / "runtime" / "deploy_requests"
    return sorted(d.iterdir()) if d.is_dir() else []


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """U6: any socket a test opens fails loudly."""
    def refuse(*_a, **_k):
        raise AssertionError("updater tests must not open a socket")
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


# ------------------------------------------------------------- U1 manifest


def _doc(**over):
    doc = {"schema": 1, "kind": "amberstone-backend", "version": "1.2.3",
           "channel": "stable",
           "archive": {"name": "backend-1.2.3.zip", "sha256": "0" * 64, "size": 10},
           "files": [{"path": "core/a.py", "sha256": "1" * 64, "size": 3}]}
    doc.update(over)
    return doc


def test_u1_valid_manifest_parses():
    m = up.parse_manifest(_doc())
    assert m.version == "1.2.3"
    assert m.channel == "stable"
    assert m.archive_name == "backend-1.2.3.zip"
    assert [f.path for f in m.files] == ["core/a.py"]


@pytest.mark.parametrize("over", [
    {"schema": 2},
    {"schema": "1"},
    {"kind": "something-else"},
    {"version": "1.2"},
    {"version": "v1.2.3"},
    {"version": "01.2.3"},
    {"channel": "nightly"},
    {"files": []},
    {"files": "core/a.py"},
    {"files": [{"path": "core/a.py", "sha256": "xyz", "size": 3}]},
    {"files": [{"path": "core/a.py", "sha256": "1" * 63, "size": 3}]},
    {"files": [{"path": "core/a.py", "sha256": "1" * 64, "size": -1}]},
    {"files": [{"path": "core/a.py", "sha256": "1" * 64, "size": True}]},
    {"files": [{"path": "core/a.py", "sha256": "1" * 64}]},
    {"files": [{"path": "core/a.py", "sha256": "1" * 64, "size": 3},
               {"path": "core/a.py", "sha256": "2" * 64, "size": 3}]},
    {"files": [{"path": "core/A.py", "sha256": "1" * 64, "size": 3},
               {"path": "core/a.py", "sha256": "2" * 64, "size": 3}]},
    {"archive": {"name": "backend-9.9.9.zip", "sha256": "0" * 64, "size": 10}},
    {"archive": {"name": "backend-1.2.3.zip", "sha256": "0" * 64}},
    {"archive": None},
    {"min_shell_version": "latest"},
])
def test_u1_schema_violations_refuse(over):
    with pytest.raises(up.ManifestError):
        up.parse_manifest(_doc(**over))


def test_u1_installed_manifest_needs_no_archive():
    doc = _doc()
    del doc["archive"]
    assert up.parse_manifest(doc, require_archive=False).version == "1.2.3"
    with pytest.raises(up.ManifestError):
        up.parse_manifest(doc)


def test_u1_non_object_and_bad_json_refuse():
    with pytest.raises(up.ManifestError):
        up.parse_manifest([1, 2])
    with pytest.raises(up.ManifestError):
        up.parse_manifest_bytes(b"{not json")
    with pytest.raises(up.ManifestError):
        up.parse_manifest_bytes(json.dumps(_doc()).encode("utf-16"))


@pytest.mark.parametrize("a,b", [
    ("1.10.0", "1.9.0"),
    ("1.0.0", "1.0.0-dev.1"),
    ("1.0.0-dev.2", "1.0.0-dev.1"),
    ("1.0.0-dev.10", "1.0.0-dev.9"),
    ("2.0.0", "1.99.99"),
    ("1.0.0-rc.1", "1.0.0-dev.1"),
])
def test_u1_version_ordering(a, b):
    assert up.version_key(a) > up.version_key(b)


# ------------------------------------------------------- payload path policy


@pytest.mark.parametrize("rel", [
    "core/x.py", "web/js/main.js", "main.py", "data/daemon_slayer/a.json",
    "data/champion_profiles/Kai'Sa.json", "data/champion_profiles/Nunu & Willump.json",
    "data/event_captures/.gitkeep", "ops/launcher/updater.py", "LICENSE",
    "LICENSES/x.txt", "requirements.txt", "vision_server/a.py",
])
def test_payload_path_allowed(rel):
    assert up.check_payload_path(rel) == rel


@pytest.mark.parametrize("rel", [
    "", "../x.py", "core/../../x.py", "/core/x.py", "C:/Windows/x.py", "c:x.py",
    "core\\x.py", "core//x.py", "core/./x.py", "core/x.py/", "core/x.py.",
    "core/ x.py", "core/a:b.py", "core/a?.py", "core/con.py", "core/NUL.txt",
    "core/x\x00.py", "core/\x7f.py",
    "tests/test_x.py", "core/tests/x.py", "core/__pycache__/a.cpython-314.pyc",
    "ops/runtime/health.json", "ops/runtime/deploy_request.key",
    "ops/backups/x/core/a.py", "ops/loop/x.py", "ops/fleet_kit/x.py",
    "ops/tls/rc.pem", "ops/local_hosts.json", "ops/moon_sync_repos.json",
    "ops/install_startup.bat", "API-Key-Claude.txt", "core/api-key-riot.txt",
    "data/x.jsonl", "logs/2026-10-26.log", "data/recordings/a.mp4",
    "data/aram_coaching_data.json", "restart_trigger.txt",
    ".git/config", "core/.git/x", "x.py", "conftest.py", "docs/a.md",
    "rc-shell/src/main.js", "python-embed/python.exe", "Core/x.py",
    "core/x.pyc", "web/node_modules/a.js", "a" * 10 + "/" + "b" * 250,
])
def test_payload_path_refused(rel):
    with pytest.raises(up.PayloadPathError):
        up.check_payload_path(rel)


def test_payload_path_non_string_refused():
    with pytest.raises(up.PayloadPathError):
        up.check_payload_path(None)  # type: ignore[arg-type]


# ------------------------------------------- U2 + U3 staging and integrity


def test_u3_stage_writes_a_complete_staging_dir(tmp_path):
    root, staged = staged_root(tmp_path)
    payload = staged.directory / "payload"
    assert staged.version == "1.1.0"
    assert staged.directory == root / "ops" / "runtime" / "staging" / "1.1.0"
    for rel, data in NEW_FILES.items():
        assert (payload / rel).read_bytes() == data
    meta = json.loads((staged.directory / "staged.json").read_text(encoding="ascii"))
    assert meta["version"] == "1.1.0"
    assert meta["manifest_sha256"] == staged.manifest_sha256
    _no_partials(root)
    assert up.verify_staged(root, "1.1.0").manifest_sha256 == staged.manifest_sha256


def test_u2_path_outside_allow_list_refuses_the_whole_update(tmp_path):
    root = make_root(tmp_path)
    files = dict(NEW_FILES, **{"ops/runtime/evil.json": b"{}"})
    rel_dir = build_release(tmp_path / "rel", "1.1.0", files)
    src = up.LocalSource(rel_dir)
    with pytest.raises(up.PayloadPathError):
        up.stage(root, src, src.release("1.1.0"), shell_version="9.9.9")
    assert not (root / "ops" / "runtime" / "staging" / "1.1.0").exists()
    _no_partials(root)


def test_u2_one_file_sha_mismatch_refuses_the_whole_update(tmp_path):
    root = make_root(tmp_path)
    entries = [{"path": rel, "sha256": _sha(d), "size": len(d)}
               for rel, d in sorted(NEW_FILES.items())]
    entries[1]["sha256"] = _sha(b"something else")
    rel_dir = build_release(tmp_path / "rel", "1.1.0", NEW_FILES, manifest_files=entries)
    src = up.LocalSource(rel_dir)
    with pytest.raises(up.IntegrityError):
        up.stage(root, src, src.release("1.1.0"), shell_version="9.9.9")
    assert not (root / "ops" / "runtime" / "staging" / "1.1.0").exists()
    _no_partials(root)


def test_u2_archive_sha_mismatch_refuses_before_unpacking(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    rel_dir = build_release(tmp_path / "rel", "1.1.0", NEW_FILES, archive_sha="f" * 64)
    src = up.LocalSource(rel_dir)

    def boom(*_a, **_k):
        raise AssertionError("the archive was opened before its sha256 checked out")
    monkeypatch.setattr(up.zipfile, "ZipFile", boom)
    with pytest.raises(up.IntegrityError):
        up.stage(root, src, src.release("1.1.0"), shell_version="9.9.9")
    _no_partials(root)


def test_u2_size_mismatch_refuses(tmp_path):
    root = make_root(tmp_path)
    entries = [{"path": rel, "sha256": _sha(d), "size": len(d)}
               for rel, d in sorted(NEW_FILES.items())]
    entries[0]["size"] += 1
    rel_dir = build_release(tmp_path / "rel", "1.1.0", NEW_FILES, manifest_files=entries)
    src = up.LocalSource(rel_dir)
    with pytest.raises(up.IntegrityError):
        up.stage(root, src, src.release("1.1.0"), shell_version="9.9.9")
    _no_partials(root)


def test_u2_zip_member_not_in_manifest_refuses(tmp_path):
    root = make_root(tmp_path)
    rel_dir = build_release(tmp_path / "rel", "1.1.0", NEW_FILES,
                            zip_extra={"core/smuggled.py": b"x = 1\n"})
    src = up.LocalSource(rel_dir)
    with pytest.raises(up.IntegrityError):
        up.stage(root, src, src.release("1.1.0"), shell_version="9.9.9")
    _no_partials(root)


def test_u2_manifest_file_missing_from_zip_refuses(tmp_path):
    root = make_root(tmp_path)
    zip_files = {k: v for k, v in NEW_FILES.items() if k != "core/b.py"}
    rel_dir = build_release(tmp_path / "rel", "1.1.0", NEW_FILES, zip_files=zip_files)
    src = up.LocalSource(rel_dir)
    with pytest.raises(up.IntegrityError):
        up.stage(root, src, src.release("1.1.0"), shell_version="9.9.9")
    _no_partials(root)


def test_u2_symlink_member_refuses(tmp_path):
    root = make_root(tmp_path)
    rel_dir = build_release(tmp_path / "rel", "1.1.0", NEW_FILES)
    zpath = rel_dir / "backend-1.1.0.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        for rel, data in NEW_FILES.items():
            info = zipfile.ZipInfo(rel)
            if rel == "core/b.py":
                info.create_system = 3
                info.external_attr = (0o120777 << 16)
            zf.writestr(info, data)
    blob = zpath.read_bytes()
    man = json.loads((rel_dir / "backend-1.1.0.json").read_text(encoding="ascii"))
    man["archive"].update(sha256=_sha(blob), size=len(blob))
    (rel_dir / "backend-1.1.0.json").write_text(json.dumps(man), encoding="ascii")
    src = up.LocalSource(rel_dir)
    with pytest.raises(up.IntegrityError):
        up.stage(root, src, src.release("1.1.0"), shell_version="9.9.9")
    _no_partials(root)


def test_u2_pinned_manifest_hash(tmp_path):
    root = make_root(tmp_path)
    rel_dir = build_release(tmp_path / "rel", "1.1.0", NEW_FILES)
    src = up.LocalSource(rel_dir)
    good = _sha((rel_dir / "backend-1.1.0.json").read_bytes())
    with pytest.raises(up.IntegrityError):
        up.stage(root, src, src.release("1.1.0"), pin_sha256="0" * 64,
                 shell_version="9.9.9")
    staged = up.stage(root, src, src.release("1.1.0"), pin_sha256=good,
                      shell_version="9.9.9")
    assert staged.manifest_sha256 == good


def test_u2_min_shell_version_gates(tmp_path):
    root = make_root(tmp_path)
    rel_dir = build_release(tmp_path / "rel", "1.1.0", NEW_FILES, min_shell="2.0.0")
    src = up.LocalSource(rel_dir)
    rel = src.release("1.1.0")
    with pytest.raises(up.ManifestError):
        up.stage(root, src, rel, shell_version="1.9.9")
    with pytest.raises(up.ManifestError):
        up.stage(root, src, rel, shell_version=None)
    assert up.stage(root, src, rel, shell_version="2.0.0").version == "1.1.0"


def test_u2_manifest_version_must_match_the_release(tmp_path):
    root = make_root(tmp_path)
    rel_dir = build_release(tmp_path / "rel", "1.1.0", NEW_FILES)
    src = up.LocalSource(rel_dir)
    rel = src.release("1.1.0")
    bad = up.Release(version="1.2.0", prerelease=False, manifest=rel.manifest,
                     archive=rel.archive, origin=rel.origin)
    with pytest.raises(up.ManifestError):
        up.stage(root, src, bad, shell_version="9.9.9")


def test_u2_stable_channel_refuses_a_dev_manifest(tmp_path):
    root = make_root(tmp_path)
    rel_dir = build_release(tmp_path / "rel", "1.1.0", NEW_FILES, channel="dev")
    src = up.LocalSource(rel_dir)
    with pytest.raises(up.ManifestError):
        up.stage(root, src, src.release("1.1.0"), channel="stable", shell_version="9.9.9")
    assert up.stage(root, src, src.release("1.1.0"), channel="dev",
                    shell_version="9.9.9").version == "1.1.0"


def test_u3_restage_replaces_atomically(tmp_path):
    root, first = staged_root(tmp_path)
    marker = first.directory / "payload" / "core" / "a.py"
    assert marker.read_bytes() == b"A = 2\n"
    files = dict(NEW_FILES, **{"core/a.py": b"A = 3\n"})
    rel_dir = build_release(tmp_path / "rel2", "1.1.0", files)
    src = up.LocalSource(rel_dir)
    up.stage(root, src, src.release("1.1.0"), shell_version="9.9.9")
    assert marker.read_bytes() == b"A = 3\n"
    _no_partials(root)


def test_u3_a_failed_restage_keeps_the_previous_staging(tmp_path):
    root, first = staged_root(tmp_path)
    entries = [{"path": rel, "sha256": _sha(d), "size": len(d)}
               for rel, d in sorted(NEW_FILES.items())]
    entries[0]["sha256"] = "e" * 64
    rel_dir = build_release(tmp_path / "rel2", "1.1.0", NEW_FILES, manifest_files=entries)
    src = up.LocalSource(rel_dir)
    with pytest.raises(up.IntegrityError):
        up.stage(root, src, src.release("1.1.0"), shell_version="9.9.9")
    assert up.verify_staged(root, "1.1.0").manifest_sha256 == first.manifest_sha256
    _no_partials(root)


@pytest.mark.parametrize("damage", ["modify", "extra", "missing", "manifest"])
def test_u2_verify_staged_detects_a_dirty_staging(tmp_path, damage):
    root, staged = staged_root(tmp_path)
    payload = staged.directory / "payload"
    if damage == "modify":
        (payload / "core" / "a.py").write_bytes(b"A = 666\n")
    elif damage == "extra":
        (payload / "core" / "evil.py").write_bytes(b"x\n")
    elif damage == "missing":
        (payload / "core" / "b.py").unlink()
    else:
        (staged.directory / "manifest.json").write_bytes(b"{}")
    with pytest.raises(up.UpdateError):
        up.verify_staged(root, "1.1.0")


def test_u2_verify_staged_ignores_the_worker_pycache(tmp_path):
    root, staged = staged_root(tmp_path)
    cache = staged.directory / "payload" / "core" / "__pycache__"
    cache.mkdir()
    (cache / "a.cpython-314.pyc").write_bytes(b"\x00")
    assert up.verify_staged(root, "1.1.0").version == "1.1.0"


def test_stage_refuses_a_linked_git_checkout(tmp_path):
    root = make_root(tmp_path)
    (root / ".git").write_text("gitdir: elsewhere\n", encoding="ascii")
    rel_dir = build_release(tmp_path / "rel", "1.1.0", NEW_FILES)
    src = up.LocalSource(rel_dir)
    with pytest.raises(up.StateError):
        up.stage(root, src, src.release("1.1.0"), shell_version="9.9.9")


def test_verify_staged_without_staging_is_a_state_error(tmp_path):
    root = make_root(tmp_path)
    with pytest.raises(up.StateError):
        up.verify_staged(root, "1.1.0")
    with pytest.raises(up.PayloadPathError):
        up.verify_staged(root, "../../x")


# --------------------------------------------------- check / sources (U6)


def test_check_local_source_channels(tmp_path):
    rel_dir = tmp_path / "rel"
    build_release(rel_dir, "1.1.0", NEW_FILES)
    build_release(rel_dir, "1.2.0-dev.1", NEW_FILES, channel="dev")
    build_release(rel_dir, "1.0.5", NEW_FILES)
    (rel_dir / "backend-2.0.0.json").write_text("{}", encoding="ascii")  # no zip
    src = up.LocalSource(rel_dir)
    assert [r.version for r in src.releases()] == ["1.0.5", "1.1.0", "1.2.0-dev.1"]
    assert up.check(src, channel="stable", current_version="1.0.0").version == "1.1.0"
    assert up.check(src, channel="dev", current_version="1.0.0").version == "1.2.0-dev.1"
    assert up.check(src, channel="stable", current_version="1.1.0") is None
    assert up.check(src, channel="stable", current_version=None).version == "1.1.0"
    with pytest.raises(up.UpdateError):
        up.check(src, channel="nightly", current_version="1.0.0")


def test_installed_version_reads_record_then_shipped_manifest(tmp_path):
    root = make_root(tmp_path, shipped="1.0.0")
    assert up.installed_version(root) == "1.0.0"
    bare = make_root(tmp_path / "b", shipped=None)
    assert up.installed_version(bare) is None


def _gh_releases():
    def asset(name):
        return {"name": name, "size": 1,
                "browser_download_url": f"https://github.com/o/r/releases/download/t/{name}"}
    return [
        {"tag_name": "v1.3.0", "draft": True, "prerelease": False,
         "assets": [asset("backend-1.3.0.json"), asset("backend-1.3.0.zip")]},
        {"tag_name": "v1.2.0-dev.1", "draft": False, "prerelease": True,
         "assets": [asset("backend-1.2.0-dev.1.json"), asset("backend-1.2.0-dev.1.zip")]},
        {"tag_name": "v1.1.0", "draft": False, "prerelease": False,
         "assets": [asset("backend-1.1.0.json"), asset("backend-1.1.0.zip"),
                    asset("Amberstone-Setup.exe")]},
        {"tag_name": "v1.0.9", "draft": False, "prerelease": False,
         "assets": [asset("backend-1.0.9.json")]},
    ]


def test_u6_github_source_uses_the_injected_fetch_only(tmp_path):
    rel_dir = build_release(tmp_path / "rel", "1.1.0", NEW_FILES)
    blobs = {
        "https://api.github.com/repos/o/r/releases?per_page=30":
            json.dumps(_gh_releases()).encode("ascii"),
        "https://github.com/o/r/releases/download/t/backend-1.1.0.json":
            (rel_dir / "backend-1.1.0.json").read_bytes(),
        "https://github.com/o/r/releases/download/t/backend-1.1.0.zip":
            (rel_dir / "backend-1.1.0.zip").read_bytes(),
    }
    calls = []

    def fetch(url, max_bytes):
        calls.append(url)
        assert url.startswith("https://")
        return blobs[url]

    src = up.GitHubSource("o", "r", fetch=fetch)
    assert [r.version for r in src.releases()] == ["1.1.0", "1.2.0-dev.1"]
    rel = up.check(src, channel="stable", current_version="1.0.0")
    assert rel.version == "1.1.0"
    root = make_root(tmp_path)
    staged = up.stage(root, src, rel, shell_version="9.9.9")
    assert staged.version == "1.1.0"
    assert calls[0].startswith("https://api.github.com/repos/o/r/releases")


def test_u6_github_source_refuses_a_non_https_asset_url():
    def fetch(url, max_bytes):
        raise AssertionError("must not fetch")
    rel = up.Release(version="1.1.0", prerelease=False, manifest="backend-1.1.0.json",
                     archive="backend-1.1.0.zip", origin="github",
                     urls=(("backend-1.1.0.json", "http://github.com/x"),))
    with pytest.raises(up.SourceError):
        up.GitHubSource("o", "r", fetch=fetch).read(rel, "backend-1.1.0.json", 10)


def test_u6_https_get_refuses_plain_http_without_a_connection():
    with pytest.raises(up.SourceError):
        up.https_get("http://example.invalid/x", max_bytes=10)
    with pytest.raises(up.SourceError):
        up.https_get("file:///etc/passwd", max_bytes=10)


def test_default_github_slug_matches_the_shell_publish_feed():
    text = BUILDER_YML.read_text(encoding="utf-8")
    owner = re.search(r"^\s+owner:\s*(\S+)\s*$", text, re.M).group(1)
    repo = re.search(r"^\s+repo:\s*(\S+)\s*$", text, re.M).group(1)
    assert (up.DEFAULT_GITHUB_OWNER, up.DEFAULT_GITHUB_REPO) == (owner, repo)


# ------------------------------------------------- U5 live-game deferral


def _health(root: Path, **flags) -> Path:
    p = root / "ops" / "runtime" / "health.json"
    p.write_text(json.dumps(dict({"alive": True}, **flags)), encoding="ascii")
    return p


def test_u5_game_live_reads_fresh_health_flags(tmp_path):
    root = make_root(tmp_path)
    quiet = lambda: frozenset({"explorer.exe"})  # noqa: E731
    assert up.game_live(root, process_names=quiet) is None
    _health(root, has_game=False, tft_mode=False)
    assert up.game_live(root, process_names=quiet) is None
    for flag in up.LIVE_GAME_FLAGS:
        _health(root, **{flag: True})
        assert flag in (up.game_live(root, process_names=quiet) or "")


def test_u5_stale_health_is_no_evidence(tmp_path):
    root = make_root(tmp_path)
    p = _health(root, has_game=True)
    old = time.time() - up.HEALTH_FRESH_S - 60
    os.utime(p, (old, old))
    assert up.game_live(root, process_names=lambda: frozenset()) is None


def test_u5_game_process_is_live_and_a_failed_probe_defers(tmp_path):
    root = make_root(tmp_path)
    hit = up.game_live(root, process_names=lambda: {"League of Legends.exe", "x.exe"})
    assert hit == "process league of legends.exe"

    def broken():
        raise OSError("snapshot failed")
    assert up.game_live(root, process_names=broken).startswith("game check failed")


@pytest.mark.skipif(sys.platform != "win32", reason="Toolhelp32 is Windows only")
def test_u5_real_process_scan_sees_this_interpreter():
    names = up.running_process_names()
    assert Path(sys.executable).name.lower() in names


def test_u5_apply_is_deferred_while_a_game_is_live(tmp_path):
    root, _ = staged_root(tmp_path)
    with pytest.raises(up.GameLiveError):
        up.apply(root, "1.1.0", game_check=lambda: "process league of legends.exe")
    assert _requests(root) == []
    assert up.read_state(root).get("pending") is None


def test_u5_rollback_is_deferred_while_a_game_is_live(tmp_path):
    root, _ = _applied(tmp_path)
    with pytest.raises(up.GameLiveError):
        up.rollback(root, game_check=lambda: "lcu phase InProgress")
    assert _requests(root) == []


# ------------------------------------------------- U4 apply + the real worker


def _rtd():
    from ops import rc_transactional_deploy as rtd
    return rtd


def test_u4_request_verifies_with_the_per_install_key(tmp_path):
    root, staged = staged_root(tmp_path)
    res = up.apply(root, "1.1.0", game_check=no_game)
    assert res.status == "requested"
    req = json.loads(res.request_path.read_text(encoding="ascii"))
    rtd = _rtd()
    rtd.verify_request(req, root / "ops" / "runtime" / "deploy_request.key")
    entries, _ = rtd._validate_files(req["files"], Path(req["project_root"]).resolve(),
                                     Path(req["staging_root"]).resolve(),
                                     list(rtd.DEFAULT_EXCLUDED_NAMES))
    assert sorted(e["live"] for e in entries) == ["core/a.py", "core/b.py"]
    assert Path(req["project_root"]) == root.resolve()
    assert Path(req["staging_root"]) == (staged.directory / "payload").resolve()
    assert res.request_path.parent == root / "ops" / "runtime" / "deploy_requests"
    assert res.request_path.stem == req["request_id"]
    # A tampered request no longer verifies.
    req["files"].append({"live": "core/x.py", "staged": "core/a.py"})
    with pytest.raises(rtd.DeployAuthError):
        rtd.verify_request(req, root / "ops" / "runtime" / "deploy_request.key")


def test_u4_no_deploy_key_fails_closed(tmp_path):
    root, _ = staged_root(tmp_path)
    (root / "ops" / "runtime" / "deploy_request.key").unlink()
    with pytest.raises(up.DeployKeyError):
        up.apply(root, "1.1.0", game_check=no_game)
    assert _requests(root) == []
    assert up.read_state(root).get("pending") is None


def test_u4_short_key_fails_closed(tmp_path):
    root, _ = staged_root(tmp_path)
    (root / "ops" / "runtime" / "deploy_request.key").write_text("abc\n", encoding="ascii")
    with pytest.raises(up.DeployKeyError):
        up.apply(root, "1.1.0", game_check=no_game)


def test_u4_apply_refuses_a_dirty_staging(tmp_path):
    root, staged = staged_root(tmp_path)
    (staged.directory / "payload" / "core" / "b.py").write_bytes(b"import os\n")
    with pytest.raises(up.IntegrityError):
        up.apply(root, "1.1.0", game_check=no_game)
    assert _requests(root) == []


def test_u4_apply_refuses_while_an_operation_is_pending(tmp_path):
    root, _ = staged_root(tmp_path)
    up.apply(root, "1.1.0", game_check=no_game)
    with pytest.raises(up.StateError):
        up.apply(root, "1.1.0", game_check=no_game)


def test_u3_stage_refuses_while_an_operation_is_pending(tmp_path):
    root, _ = staged_root(tmp_path)
    up.apply(root, "1.1.0", game_check=no_game)
    rel_dir = build_release(tmp_path / "rel2", "1.1.0", dict(NEW_FILES, **{"core/a.py": b"A = 9\n"}))
    src = up.LocalSource(rel_dir)
    with pytest.raises(up.StateError):
        up.stage(root, src, src.release("1.1.0"), shell_version="9.9.9")
    assert (root / "ops" / "runtime" / "staging" / "1.1.0" / "payload" / "core" / "a.py") \
        .read_bytes() == b"A = 2\n"


def test_u4_apply_refuses_to_overwrite_an_unowned_live_file(tmp_path):
    live = dict(BASE_FILES, **{"core/b.py": b"# a file the install never shipped\n"})
    root = make_root(tmp_path, live=live)
    doc = json.loads((root / up.INSTALLED_MANIFEST).read_text(encoding="ascii"))
    doc["files"] = [f for f in doc["files"] if f["path"] != "core/b.py"]
    (root / up.INSTALLED_MANIFEST).write_text(json.dumps(doc), encoding="ascii")
    rel_dir = build_release(tmp_path / "rel", "1.1.0", NEW_FILES)
    src = up.LocalSource(rel_dir)
    up.stage(root, src, src.release("1.1.0"), shell_version="9.9.9")
    with pytest.raises(up.PayloadPathError):
        up.apply(root, "1.1.0", game_check=no_game)
    assert _requests(root) == []


def test_u4_noop_when_every_file_is_already_live(tmp_path):
    root = make_root(tmp_path)
    rel_dir = build_release(tmp_path / "rel", "1.0.1", BASE_FILES)
    src = up.LocalSource(rel_dir)
    up.stage(root, src, src.release("1.0.1"), shell_version="9.9.9")
    res = up.apply(root, "1.0.1", game_check=no_game)
    assert res.status == "noop"
    assert res.plan.restart.level == "none"
    assert _requests(root) == []
    assert up.installed_version(root) == "1.0.1"


def test_u4_request_is_written_through_a_tmp_scratch(tmp_path, monkeypatch):
    root, _ = staged_root(tmp_path)
    seen = []
    real = os.replace

    def spy(src, dst):
        seen.append((str(src), str(dst)))
        return real(src, dst)
    monkeypatch.setattr(up.os, "replace", spy)
    res = up.apply(root, "1.1.0", game_check=no_game)
    hits = [s for s, d in seen if Path(d) == res.request_path]
    assert hits and all(s.endswith(".tmp") for s in hits)


def test_u4_deployed_files_carry_a_fresh_mtime_for_hot_reload(tmp_path):
    # core/hot_reload.py:590 fires only on an mtime newer than it knew; the
    # worker now writes the hashed bytes into a fresh file (no copy2).
    root, staged = staged_root(tmp_path)
    os.utime(staged.directory / "payload" / "core" / "a.py", (1_000_000, 1_000_000))
    before = time.time() - 1
    res = up.apply(root, "1.1.0", game_check=no_game)
    assert run_worker(root, res.request_path)["ok"]
    assert (root / "core" / "a.py").stat().st_mtime >= before


def test_u4_force_restart_follows_the_classifier(tmp_path):
    # core/*.py only -> hot reload (watcher active) -> no force_restart.
    root, _ = staged_root(tmp_path)
    _hot_reload_status(root, watching=True)
    res = up.apply(root, "1.1.0", game_check=no_game)
    req = json.loads(res.request_path.read_text(encoding="ascii"))
    assert res.plan.restart.app == "hot_reload"
    assert req["force_restart"] is False


def test_u4_halted_hot_reload_escalates_to_a_supervised_restart(tmp_path):
    root, _ = staged_root(tmp_path)
    _hot_reload_status(root, watching=True)
    (root / "ops" / "runtime" / "hot_reload_halt.txt").write_text("x", encoding="ascii")
    res = up.apply(root, "1.1.0", game_check=no_game)
    req = json.loads(res.request_path.read_text(encoding="ascii"))
    assert res.plan.restart.app == "restart"
    assert req["force_restart"] is True


def _hot_reload_status(root: Path, *, watching: bool) -> None:
    (root / "ops" / "runtime" / "hot_reload.json").write_text(
        json.dumps({"watching": watching}), encoding="ascii")


class _Heartbeat:
    """Keeps root/ops/runtime/health.json fresh while the real worker waits."""

    def __init__(self, root: Path) -> None:
        self.path = root / "ops" / "runtime" / "health.json"
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.path.write_text(json.dumps({"alive": True, "run_id": "r1"}),
                                     encoding="ascii")
            except OSError:
                pass
            self._stop.wait(0.05)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join(5)


def run_worker(root: Path, request_path: Path) -> dict:
    """What the frozen supervisor does with a request (ops/rc_supervisor.py
    process_deploy_requests): rename to .deploying, run the worker, write the
    result as deploy_results/<stem>.json. The worker is the REAL module."""
    rtd = _rtd()
    stem = request_path.stem
    deploying = request_path.with_suffix(".deploying")
    request_path.rename(deploying)
    with _Heartbeat(root):
        result = rtd.do_deploy(deploying, key_path=root / "ops" / "runtime" / "deploy_request.key")
    rtd.atomic_write_json(root / "ops" / "runtime" / "deploy_results" / f"{stem}.json", result)
    deploying.unlink()
    return result


def _applied(tmp_path):
    root, staged = staged_root(tmp_path)
    res = up.apply(root, "1.1.0", game_check=no_game)
    result = run_worker(root, res.request_path)
    assert result["ok"], result
    fin = up.finish(root)
    assert fin.status == "ok", fin
    return root, staged


def test_u4_end_to_end_through_the_real_worker(tmp_path):
    root, _ = _applied(tmp_path)
    for rel, data in NEW_FILES.items():
        assert (root / rel).read_bytes() == data
    assert up.installed_version(root) == "1.1.0"
    rec = up.read_installed(root)
    assert rec["created"] == ["core/b.py"]
    assert set(rec["pre_hashes"]) == {"core/a.py"}
    assert Path(rec["backup_root"]).is_relative_to((root / "ops" / "backups").resolve())
    assert rec["previous"]["version"] == "1.0.0"
    assert up.read_state(root).get("pending") is None


def test_finish_states(tmp_path):
    root, _ = staged_root(tmp_path)
    assert up.finish(root).status == "none"
    res = up.apply(root, "1.1.0", game_check=no_game)
    assert up.finish(root).status == "pending"
    # A failed deploy: the worker already rolled back; the record is unchanged.
    stem = res.request_path.stem
    res.request_path.unlink()
    up_results = root / "ops" / "runtime" / "deploy_results"
    up_results.mkdir(parents=True)
    (up_results / f"{stem}.json").write_text(json.dumps(
        {"ok": False, "phase": "health_check", "rollback": True}), encoding="ascii")
    fin = up.finish(root)
    assert fin.status == "failed"
    assert fin.result["phase"] == "health_check"
    assert up.installed_version(root) == "1.0.0"
    assert up.read_state(root).get("pending") is None


def test_finish_reports_a_lost_request(tmp_path):
    root, _ = staged_root(tmp_path)
    t = [1_000_000.0]
    res = up.apply(root, "1.1.0", game_check=no_game, now=lambda: t[0])
    res.request_path.unlink()
    assert up.finish(root, now=lambda: t[0] + 10).status == "pending"
    assert up.finish(root, now=lambda: t[0] + up.LOST_AFTER_S + 1).status == "lost"
    assert up.read_state(root).get("pending") is None


# ------------------------------------------------------------ U8 rollback


def test_u8_rollback_redeploys_the_backup_and_quarantines_created(tmp_path):
    root, _ = _applied(tmp_path)
    res = up.rollback(root, game_check=no_game)
    assert res.status == "requested"
    req = json.loads(res.request_path.read_text(encoding="ascii"))
    _rtd().verify_request(req, root / "ops" / "runtime" / "deploy_request.key")
    assert [f["live"] for f in req["files"]] == ["core/a.py"]
    result = run_worker(root, res.request_path)
    assert result["ok"], result
    fin = up.finish(root)
    assert fin.status == "ok"
    assert (root / "core" / "a.py").read_bytes() == b"A = 1\n"
    assert not (root / "core" / "b.py").exists()
    moved = list((root / "ops" / "runtime" / "launcher" / "quarantine").rglob("b.py"))
    assert len(moved) == 1 and moved[0].read_bytes() == b"B = 1\n"
    assert up.installed_version(root) == "1.0.0"
    with pytest.raises(up.StateError):
        up.rollback(root, game_check=no_game)   # one level only


def test_u8_rollback_refuses_a_tampered_backup(tmp_path):
    root, _ = _applied(tmp_path)
    rec = up.read_installed(root)
    (Path(rec["backup_root"]) / "core" / "a.py").write_bytes(b"A = 'evil'\n")
    with pytest.raises(up.IntegrityError):
        up.rollback(root, game_check=no_game)
    assert _requests(root) == []


def test_u8_rollback_refuses_a_backup_outside_ops_backups(tmp_path):
    root, _ = _applied(tmp_path)
    rec = up.read_installed(root)
    rec["backup_root"] = str(tmp_path)
    up._write_json(up.installed_record_path(root), rec)
    with pytest.raises(up.PayloadPathError):
        up.rollback(root, game_check=no_game)


def test_u8_rollback_without_a_record_is_a_state_error(tmp_path):
    root = make_root(tmp_path)
    with pytest.raises(up.StateError):
        up.rollback(root, game_check=no_game)


def test_u8_rollback_of_a_created_only_update_is_direct(tmp_path):
    root = make_root(tmp_path)
    files = dict(BASE_FILES, **{"web/js/new.js": b"// new\n"})
    rel_dir = build_release(tmp_path / "rel", "1.0.1", files)
    src = up.LocalSource(rel_dir)
    up.stage(root, src, src.release("1.0.1"), shell_version="9.9.9")
    res = up.apply(root, "1.0.1", game_check=no_game)
    assert res.plan.restart.level == "none"
    assert run_worker(root, res.request_path)["ok"]
    assert up.finish(root).status == "ok"
    rb = up.rollback(root, game_check=no_game)
    assert rb.status == "done"
    assert not (root / "web" / "js" / "new.js").exists()
    assert up.installed_version(root) == "1.0.0"


# ------------------------------------- U8 recover (app down after update)


def _sup_requests(root: Path) -> list:
    d = root / "ops" / "runtime" / "supervisor_requests"
    return sorted(p for p in d.glob("launcher-recover-*.json")) if d.is_dir() else []


def test_u8_recover_asks_the_supervisor_to_reset_then_roll_back(tmp_path):
    root, _ = _applied(tmp_path)
    out = up.recover(root, now=lambda: 1_000_000.0)
    reqs = _sup_requests(root)
    # The supervisor handles requests in sorted-name order: reset first.
    assert [json.loads(p.read_text(encoding="ascii"))["type"] for p in reqs] == \
        ["reset_circuit_breaker", "rollback"]
    assert [str(p) for p in reqs] == out["requests"]
    assert out["to_version"] == "1.0.0"
    assert not (root / "core" / "b.py").exists()
    assert out["quarantine"]["moved"] == ["core/b.py"]
    assert up.installed_version(root) == "1.0.0"
    # What the supervisor's _do_rollback then restores: the NEWEST backup.
    backups = sorted((root / "ops" / "backups").iterdir(), reverse=True)
    assert (backups[0] / "core" / "a.py").read_bytes() == b"A = 1\n"


def test_u8_recover_refuses_when_a_later_backup_exists(tmp_path):
    root, _ = _applied(tmp_path)
    (root / "ops" / "backups" / "99991231-235959-someone-else").mkdir()
    with pytest.raises(up.StateError):
        up.recover(root)
    assert _sup_requests(root) == []
    assert up.installed_version(root) == "1.1.0"


def test_u8_recover_refuses_a_tampered_backup(tmp_path):
    root, _ = _applied(tmp_path)
    rec = up.read_installed(root)
    (Path(rec["backup_root"]) / "core" / "a.py").write_bytes(b"evil\n")
    with pytest.raises(up.IntegrityError):
        up.recover(root)
    assert _sup_requests(root) == []


def test_u8_recover_of_a_created_only_update_restarts(tmp_path):
    root = make_root(tmp_path)
    files = dict(BASE_FILES, **{"core/new.py": b"N = 1\n"})
    rel_dir = build_release(tmp_path / "rel", "1.0.1", files)
    src = up.LocalSource(rel_dir)
    up.stage(root, src, src.release("1.0.1"), shell_version="9.9.9")
    res = up.apply(root, "1.0.1", game_check=no_game)
    assert run_worker(root, res.request_path)["ok"]
    assert up.finish(root).status == "ok"
    up.recover(root)
    assert [json.loads(p.read_text(encoding="ascii"))["type"] for p in _sup_requests(root)] \
        == ["reset_circuit_breaker", "restart"]
    assert not (root / "core" / "new.py").exists()


def test_u8_recover_without_a_record_is_a_state_error(tmp_path):
    with pytest.raises(up.StateError):
        up.recover(make_root(tmp_path))


def test_app_health_and_run_id_before(tmp_path):
    root = make_root(tmp_path)
    assert up.app_health(root) == {"alive": False, "run_id": None, "age_s": None}
    p = root / "ops" / "runtime" / "health.json"
    p.write_text(json.dumps({"alive": True, "run_id": "r7"}), encoding="ascii")
    h = up.app_health(root)
    assert h["alive"] is True and h["run_id"] == "r7"
    old = time.time() - up.HEALTH_FRESH_S - 60
    os.utime(p, (old, old))
    assert up.app_health(root)["alive"] is False
    os.utime(p, None)
    rel_dir = build_release(tmp_path / "rel", "1.1.0", NEW_FILES)
    src = up.LocalSource(rel_dir)
    up.stage(root, src, src.release("1.1.0"), shell_version="9.9.9")
    up.apply(root, "1.1.0", game_check=no_game)
    assert up.finish(root).run_id_before == "r7"


# ------------------------------------------------------- U7 classifier


@pytest.mark.parametrize("rel,app,services", [
    ("web/js/panels/champ_select.js", "none", ()),
    ("web/index.html", "none", ()),
    ("web/img/logo.png", "none", ()),
    ("core/x.py", "hot_reload", ()),
    ("dashboard/routes_state.py", "hot_reload", ()),
    ("web_dashboard.py", "hot_reload", ()),
    ("tools/some_tool.py", "hot_reload", ()),
    ("coaches/aram_coach.py", "restart", ()),
    ("modes/x.py", "restart", ()),
    ("lcu/x.py", "restart", ()),
    ("app/_snapshot.py", "restart", ()),
    ("main.py", "restart", ()),
    ("app/_loop.py", "restart", ()),
    ("core/game_snapshot.py", "restart", ()),
    ("lcu/lcu_client.py", "restart", ()),
    ("data/x.json", "restart", ()),
    ("config/settings.json", "restart", ()),
    ("ops/rc_supervisor.py", "none", ("supervisor",)),
    ("ops/rc_self_monitor.py", "hot_reload", ("supervisor",)),
    ("ops/rc_config.json", "restart", ("supervisor",)),
    ("ops/rc_transactional_deploy.py", "hot_reload", ()),
    ("ops/launcher/service_host.py", "none", ("app",)),
    ("ops/launcher/services.json", "none", ("app",)),
    ("tools/lcu_agent.py", "hot_reload", ("lcu_agent",)),
    ("tools/liveclient_relay.py", "hot_reload", ("liveclient_relay",)),
    ("tools/hotkey_listener.py", "hot_reload", ("hotkey_listener",)),
    ("agents/supervisor.py", "hot_reload", ("phase3_supervisor",)),
    ("agents/_supervisor_http.py", "hot_reload", ("phase3_supervisor",)),
    ("agents/agent1_lead/a.py", "hot_reload", ("phase3_supervisor",)),
    ("moon_vision_server.py", "none", ("vision",)),
    ("vision_server/_frame.py", "none", ("vision",)),
    ("agents/daemon_slayer/dps.py", "hot_reload", ("ds",)),
    ("data/daemon_slayer/current.txt", "restart", ("ds",)),
    ("requirements.txt", "restart", ("app",)),
    ("rc-shell/src/main.js", "none", ("shell",)),
    ("docs/PACKAGING_PLAN.md", "none", ()),
    ("tests/test_x.py", "none", ()),
    ("LICENSE", "none", ()),
])
def test_u7_classify_path(rel, app, services):
    c = up.classify_path(rel)
    assert (c.app, c.services) == (app, services), c


def test_u7_plan_takes_the_max_and_unions_services():
    plan = up.classify_paths(["web/js/main.js", "core/x.py", "tools/lcu_agent.py",
                              "vision_server/a.py"])
    assert plan.app == "hot_reload"
    assert plan.services == ("lcu_agent", "vision")
    assert plan.level == "relaunch"
    assert plan.needs_restart
    assert plan.stale_check
    assert up.classify_paths([]).level == "none"
    assert not up.classify_paths(["web/js/main.js"]).needs_restart
    assert up.classify_paths(["web/js/main.js", "main.py"]).level == "restart"
    assert up.classify_paths(["core/x.py"], hot_reload_active=False).app == "restart"


def test_u7_levels_are_ordered():
    assert up.LEVELS == ("none", "hot_reload", "restart", "relaunch")


def test_u7_mirrors_match_core_hot_reload():
    from core import hot_reload as hr
    from core import live_game_gate as lg
    assert up.FROZEN_PATHS == frozenset(hr._FROZEN_PATHS)
    assert up.HOT_RELOAD_WATCH_DIRS == hr._WATCH_DIRS
    assert up.HOT_RELOAD_SKIP_DIRS == hr._SKIP_DIRS
    assert up.GAME_PROCESS_NAMES == hr.GAME_PROCESS_NAMES
    assert up.LIVE_GAME_FLAGS == lg.LIVE_GAME_FLAGS


@pytest.mark.parametrize("rel", [
    "core/x.py", "core/sub/y.py", "dashboard/a.py", "ops/a.py", "tools/a.py",
    "agents/agent1_lead/a.py", "web_dashboard.py", "overlay.py", "coaches/a.py",
    "modes/a.py", "lcu/a.py", "app/a.py", "game_reader/a.py", "lib/a.py",
    "core/tests/x.py", "ops/runtime/x.py", "ops/loop/control/x.py", "data/x.py",
    "main.py", "app/_loop.py", "core/log_setup.py", "web/a.py",
])
def test_u7_python_classification_agrees_with_hot_reload_should_watch(rel):
    from core import hot_reload as hr
    assert not up.main_never_imports(rel)
    c = up.classify_path(rel)
    if hr._should_watch(rel):
        assert c.app == "hot_reload", rel
    else:
        assert c.app != "hot_reload", rel


def test_u7_named_services_exist_in_the_launcher_manifest():
    names = {s["name"] for s in json.loads(SERVICES_JSON.read_text(encoding="utf-8"))["services"]}
    # vision / ds run under RC's own watchdogs; app / shell are the whole app.
    known = names | {"vision", "ds", "app", "shell"}
    assert set(up.ALL_SERVICE_NAMES) <= known
    assert {"supervisor", "lcu_agent", "liveclient_relay", "hotkey_listener",
            "phase3_supervisor"} <= set(up.ALL_SERVICE_NAMES)


# ------------------------------------- fix round (independent check, s141)


def _stage_into(root: Path, tmp_path: Path, version: str, files: dict):
    rel_dir = build_release(tmp_path / f"rel-{version}", version, files)
    src = up.LocalSource(rel_dir)
    return up.stage(root, src, src.release(version), shell_version="9.9.9")


# F1 ownership fails CLOSED without a baseline


def test_f1_no_baseline_refuses_to_overwrite_an_existing_file(tmp_path):
    root = make_root(tmp_path, shipped=None)
    assert up.read_installed(root) is None
    _stage_into(root, tmp_path, "1.1.0", NEW_FILES)
    with pytest.raises(up.PayloadPathError):
        up.apply(root, "1.1.0", game_check=no_game)
    assert _requests(root) == []
    assert (root / "core" / "a.py").read_bytes() == b"A = 1\n"


def test_f1_no_baseline_still_creates_new_files(tmp_path):
    root = make_root(tmp_path, shipped=None)
    files = dict(BASE_FILES, **{"core/b.py": b"B = 1\n"})
    _stage_into(root, tmp_path, "1.1.0", files)
    res = up.apply(root, "1.1.0", game_check=no_game)
    assert res.status == "requested"
    assert res.plan.changed == ("core/b.py",) and res.plan.created == ("core/b.py",)


# F2 secrets and ignored paths never travel; deny wins over allow


@pytest.mark.parametrize("rel", [
    "config/vision_token.txt", "config/mission_control_token.txt",
    "tools/mcp_token.txt", "tools/vision_token.txt", "ops/local_paths.json",
    "ops/runtime/dash_token.txt", "ops/runtime/deploy_request.key",
    "core/certs/ca.txt", "web/tls/leaf.txt", "web/x.pfx", "core/x.p12",
    "config/.env", "config/.env.local", "core/x.salt", "API-Key-Riot-TFT.txt",
])
def test_f2_explicit_secret_deny_list(rel):
    with pytest.raises(up.PayloadPathError):
        up.check_payload_path(rel)


@pytest.mark.parametrize("rel", [
    "config/vision_token.txt", "data/tft_scouting.json", "data/cold_advisories.json",
    "data/ratings/last_rank.json",
])
def test_f2_a_gitignored_payload_path_refuses_the_whole_update(tmp_path, rel):
    root = make_root(tmp_path)
    files = dict(NEW_FILES, **{rel: b"x\n"})
    with pytest.raises(up.PayloadPathError):
        _stage_into(root, tmp_path, "1.1.0", files)
    assert not (root / "ops" / "runtime" / "staging" / "1.1.0").exists()
    _no_partials(root)


def test_f2_no_shipped_ignore_list_fails_closed(tmp_path):
    root = make_root(tmp_path, ignore=False)
    with pytest.raises(up.StateError):
        _stage_into(root, tmp_path, "1.1.0", NEW_FILES)


def test_f2_ignore_rules_semantics(tmp_path):
    (tmp_path / ".gitignore").write_text(
        "# comment\n*.log\n/top.txt\nbuild/\ndata/*\n!data/keep.json\n"
        "deep/**/secret.txt\nlocked/\n!locked/inside.txt\n\\#hash.txt\n",
        encoding="ascii")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / ".gitignore").write_text("local.txt\n!keep.log\n", encoding="ascii")
    rules = up.IgnoreRules(tmp_path)
    ignored = ["a.log", "x/y/a.LOG", "top.txt", "build/a.py", "x/build/a.py",
               "data/x.json", "deep/secret.txt", "deep/a/b/secret.txt",
               "locked/inside.txt", "sub/local.txt", "#hash.txt"]
    kept = ["x/top.txt", "builder/a.py", "data/keep.json", "deep/a/other.txt",
            "core/a.py", "sub/keep.log", "other/local.txt"]
    for rel in ignored:
        assert rules.ignored(rel), rel
    for rel in kept:
        assert not rules.ignored(rel), rel


def test_f2_ignore_matcher_agrees_with_git_check_ignore():
    import shutil as _sh
    import subprocess
    if not _sh.which("git") or not (ROOT / ".git").exists():
        pytest.skip("needs the git checkout")
    sample = [
        "config/vision_token.txt", "config/mission_control_token.txt",
        "tools/mcp_token.txt", "API-Key-Claude.txt", "core/x.key", "ops/runtime/x.json",
        "data/tft_scouting.json", "data/aram_coaching_data.json", "data/x_shadow.jsonl",
        "data/ratings/last_x.json", "data/coaching/death_patterns.json", "logs/a.log",
        "ops/local_hosts.json", "ops/tls/a.png", ".env", ".env.local", ".env.example",
        "core/a.py", "web/js/main.js", "data/vision_regions.json", "data/coaching/x.json",
        "ops/launcher/updater.py", "rc-shell/node_modules/a.js", "rc-shell/src/main.js",
        "ops/audit/lolmath_ds_sweep/out.json", "data/external/x.json",
        "data/external/101qq_hero_rank_double_tier200_capture_20260525.json",
    ]
    # Bytes, not text: text-mode stdin on Windows would send CRLF and git
    # would check paths ending in a carriage return.
    proc = subprocess.run(
        ["git", "-c", "core.excludesFile=", "check-ignore", "--no-index", "--stdin"],
        cwd=str(ROOT), input=("\n".join(sample) + "\n").encode("ascii"),
        capture_output=True, check=False)
    assert proc.returncode in (0, 1), proc.stderr
    git_ignored = set(proc.stdout.decode("ascii").split())
    rules = up.IgnoreRules(ROOT)
    mine = {p for p in sample if rules.ignored(p)}
    assert mine == git_ignored, (sorted(mine - git_ignored), sorted(git_ignored - mine))
    assert "config/vision_token.txt" in mine and "core/a.py" not in mine


def test_f2_ignore_matcher_agrees_with_git_over_the_index():
    """Every tracked file git's patterns ignore (force-added ones included)
    plus a stride of the rest: the matcher must agree on all of them."""
    import shutil as _sh
    import subprocess
    if not _sh.which("git") or not (ROOT / ".git").exists():
        pytest.skip("needs the git checkout")
    listed = subprocess.run(["git", "-c", "core.quotepath=off", "ls-files", "-z"],
                            cwd=str(ROOT), capture_output=True, check=True).stdout
    tracked = [p for p in listed.decode("utf-8").split("\0") if p and p.isascii()
               and "\n" not in p]
    assert len(tracked) > 1000
    proc = subprocess.run(
        ["git", "-c", "core.excludesFile=", "check-ignore", "--no-index", "--stdin", "-z"],
        cwd=str(ROOT), input=("\0".join(tracked) + "\0").encode("ascii"),
        capture_output=True, check=False)
    assert proc.returncode in (0, 1), proc.stderr
    git_ignored = {p for p in proc.stdout.decode("ascii").split("\0") if p}
    assert len(git_ignored) > 10
    sample = sorted(git_ignored) + tracked[::7]
    rules = up.IgnoreRules(ROOT)
    mine = {p for p in sample if rules.ignored(p)}
    assert mine == git_ignored & set(sample), (
        sorted(mine - git_ignored)[:10], sorted((git_ignored & set(sample)) - mine)[:10])


# F3 8.3 short names and other aliases


@pytest.mark.parametrize("rel", ["ops/FLEET_~1/evil.py", "PROGRA~1/x.py", "core/A~12.py"])
def test_f3_short_name_segment_refused(rel):
    with pytest.raises(up.PayloadPathError):
        up.check_payload_path(rel)


def _short_name(path: Path):
    if sys.platform != "win32":
        return None
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, 1024)
    short = Path(buf.value).name if n else None
    return short if short and short.lower() != path.name.lower() else None


def test_f3_a_real_short_name_alias_is_detected(tmp_path):
    root = make_root(tmp_path)
    long_dir = root / "ops" / "fleet_kit_with_a_long_name"
    long_dir.mkdir(parents=True)
    short = _short_name(long_dir)
    if short is None:
        pytest.skip("this volume does not generate 8.3 names")
    assert up.live_alias(root.resolve(), f"ops/{short}/evil.py") == \
        "ops/fleet_kit_with_a_long_name/evil.py"
    assert up.live_alias(root.resolve(), "ops/fleet_kit_with_a_long_name/x.py") is None


def test_f3_a_junction_inside_the_install_is_refused(tmp_path):
    try:
        import _winapi
    except ImportError:
        pytest.skip("directory junctions are Windows only")
    root = make_root(tmp_path)
    target = root / "ops" / "runtime" / "planted"
    target.mkdir(parents=True)
    (root / "web" / "js").mkdir(parents=True, exist_ok=True)
    _winapi.CreateJunction(str(target), str(root / "web" / "jslink"))
    files = dict(NEW_FILES, **{"web/jslink/evil.js": b"x\n"})
    _stage_into(root, tmp_path, "1.1.0", files)
    with pytest.raises(up.PayloadPathError):
        up.apply(root, "1.1.0", game_check=no_game)
    assert not (target / "evil.js").exists()
    assert _requests(root) == []


def test_f3_alias_check_runs_before_any_write(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    _stage_into(root, tmp_path, "1.1.0", NEW_FILES)
    monkeypatch.setattr(up, "live_alias",
                        lambda r, rel: "ops/fleet_kit/b.py" if rel == "core/b.py" else None)
    with pytest.raises(up.PayloadPathError):
        up.apply(root, "1.1.0", game_check=no_game)
    assert _requests(root) == []


# F4 swap-after-sign and replay (the worker enforces both)


def test_f4_signed_request_carries_a_freshness_window(tmp_path):
    root, _ = staged_root(tmp_path)
    t0 = time.time()
    res = up.apply(root, "1.1.0", game_check=no_game)
    req = json.loads(res.request_path.read_text(encoding="ascii"))
    assert t0 - 1 <= req["issued_at"] <= time.time() + 1
    assert req["expires_at"] - req["issued_at"] == up.REQUEST_TTL_S
    assert up.REQUEST_TTL_S <= _rtd().MAX_TTL_S
    assert all(re.fullmatch(r"[0-9a-f]{64}", f["sha256"]) for f in req["files"])


def test_f4_a_staged_file_swapped_after_signing_never_deploys(tmp_path):
    root, staged = staged_root(tmp_path)
    res = up.apply(root, "1.1.0", game_check=no_game)
    (staged.directory / "payload" / "core" / "a.py").write_bytes(b"A = 'evil'\n")
    result = run_worker(root, res.request_path)
    assert result["ok"] is False and result["phase"] == "integrity", result
    assert (root / "core" / "a.py").read_bytes() == b"A = 1\n"
    assert not (root / "core" / "b.py").exists()
    assert up.finish(root).status == "failed"


def test_f4_the_same_signed_bytes_never_deploy_twice(tmp_path):
    root, _ = staged_root(tmp_path)
    res = up.apply(root, "1.1.0", game_check=no_game)
    signed = res.request_path.read_bytes()
    assert run_worker(root, res.request_path)["ok"] is True
    (root / "core" / "a.py").write_bytes(b"A = 1\n")   # an operator fixes a file
    res.request_path.write_bytes(signed)               # ... and the request is replayed
    replay = run_worker(root, res.request_path)
    assert replay["ok"] is False and replay["phase"] == "auth", replay
    assert "already used" in replay["error"]
    assert (root / "core" / "a.py").read_bytes() == b"A = 1\n"


# F5 quarantine never leaves the install root


def test_f5_quarantine_with_a_hostile_record_version_stays_inside(tmp_path):
    root = make_root(tmp_path)
    files = dict(BASE_FILES, **{"web/js/new.js": b"// new\n"})
    _stage_into(root, tmp_path, "1.0.1", files)
    res = up.apply(root, "1.0.1", game_check=no_game)
    assert run_worker(root, res.request_path)["ok"]
    assert up.finish(root).status == "ok"
    rec = up.read_installed(root)
    rec["version"] = "../../../../../escaped"
    up._write_json(up.installed_record_path(root), rec)
    up.rollback(root, game_check=no_game)
    moved = list((root / "ops" / "runtime" / "launcher" / "quarantine").rglob("new.js"))
    assert len(moved) == 1
    assert not any(p.name.startswith("escaped") for p in tmp_path.rglob("*"))


def test_f5_quarantine_dir_is_asserted_inside_the_root(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    monkeypatch.setattr(up, "launcher_state_dir", lambda r: tmp_path / "elsewhere")
    with pytest.raises(up.PayloadPathError):
        up._quarantine(root.resolve(), {"version": "1.0.0", "created": ["core/a.py"],
                                        "files": {"core/a.py": _sha(b"A = 1\n")}},
                       time.time)
    assert (root / "core" / "a.py").exists()


# F6 an unreadable fresh health.json defers


def test_f6_torn_fresh_health_defers(tmp_path):
    root = make_root(tmp_path)
    (root / "ops" / "runtime" / "health.json").write_text('{"has_game": tr', encoding="ascii")
    reason = up.game_live(root, process_names=lambda: frozenset())
    assert reason and "health" in reason and "unreadable" in reason


def test_f6_missing_health_is_still_no_evidence(tmp_path):
    root = make_root(tmp_path)
    assert up.game_live(root, process_names=lambda: frozenset()) is None


# F7 the no-change path checks the game before writing anything


def test_f7_noop_apply_is_deferred_before_any_write(tmp_path):
    root = make_root(tmp_path)
    _stage_into(root, tmp_path, "1.0.1", BASE_FILES)
    with pytest.raises(up.GameLiveError):
        up.apply(root, "1.0.1", game_check=lambda: "process league of legends.exe")
    assert not up.installed_record_path(root).exists()
    assert not up.state_path(root).exists()
    assert up.installed_version(root) == "1.0.0"


# ----------------------------------------------------------------- CLI


def test_cli_classify_and_check(tmp_path, capsys):
    assert up.main(["classify", "web/js/main.js", "core/x.py"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["restart"]["app"] == "hot_reload"
    rel_dir = build_release(tmp_path / "rel", "1.1.0", NEW_FILES)
    root = make_root(tmp_path)
    rc = up.main(["--root", str(root), "check", "--source", f"local:{rel_dir}"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["available"]["version"] == "1.1.0"
    assert out["current"] == "1.0.0"


def test_cli_reports_an_error_code(tmp_path, capsys):
    root = make_root(tmp_path)
    rc = up.main(["--root", str(root), "apply", "--version", "1.1.0"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1 and out["ok"] is False and out["code"] == "state"


# ------------------------------------------------------------- hygiene


def _code_tokens(path: Path) -> list:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                out.append(node.value)
        elif isinstance(node, ast.Name):
            out.append(node.id)
        elif isinstance(node, ast.Attribute):
            out.append(node.attr)
    return out


def test_stdlib_only_imports():
    tree = ast.parse(UPDATER_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative imports: the launcher runs -I"
            mods = [node.module or ""]
        else:
            continue
        for mod in mods:
            top = mod.split(".")[0]
            assert top == "__future__" or top in sys.stdlib_module_names, mod


def test_never_at_boot_and_no_image_kill():
    tokens = [t.lower() for t in _code_tokens(UPDATER_PY)]
    for needle in ("schtasks", "winreg", "currentversion\\run", "openatlogin",
                   "register-scheduledtask", "taskkill", "stop-process"):
        assert not any(needle in t for t in tokens), needle


def test_ascii_and_lf():
    for path in (UPDATER_PY, Path(__file__)):
        raw = path.read_bytes()
        assert b"\r" not in raw, path.name
        raw.decode("ascii")
