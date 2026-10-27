# arch: PKG-6 packaged smoke - launcher [G] + shell build [H] checks | section=tests | frozen=no
"""PKG-6 (docs/PACKAGING_PLAN.md section 4): tools/run_packaged_smoke.py
gains [G], the launcher chain the shell runs - the bundle's own
ops/launcher/service_host.py started with the shell's argv, a probe service in
its job, the first-run secrets, schema-1 status, a clean exit on the stdin
"stop" line with nothing left behind - and [H], an electron-builder output
carrying the same backend build beside app.asar.

The [G] test runs a REAL host process (stdlib only, any OS; the job-object
assertion applies on Windows only) against a copy of the launcher package in
tmp_path, with this interpreter standing in for the embedded runtime.
"""
from __future__ import annotations

import inspect
import json
import re
import shutil
import sys
from pathlib import Path

from ops.launcher import service_host as sh
from tools import build_portable as bp
from tools import run_packaged_smoke as rps

REPO = Path(__file__).resolve().parent.parent
LAUNCHER = REPO / "ops" / "launcher"
BUILDER_YML = REPO / "rc-shell" / "electron-builder.yml"
SHELL_PKG = REPO / "rc-shell" / "package.json"


def _bundle(tmp_path: Path) -> Path:
    root = tmp_path / "bundle"
    dest = root / "ops" / "launcher"
    dest.mkdir(parents=True)
    for name in ("__init__.py", "service_host.py", "first_run.py", "services.json"):
        shutil.copyfile(LAUNCHER / name, dest / name)
    return root


def test_probe_manifest_is_a_valid_packaged_host_config():
    cfg = sh.parse_config(rps.launcher_probe_manifest(43210), "packaged")
    assert cfg.dashboard_port == 43210
    assert [s.name for s in cfg.services] == [rps.LAUNCHER_PROBE_SERVICE]
    assert cfg.services[0].restart == "never"
    assert cfg.services[0].role == "agent"


def test_launcher_check_fails_closed_without_the_host(tmp_path):
    rps.reset()
    (tmp_path / "bundle").mkdir()
    rps.check_launcher_from_unpacked(tmp_path / "bundle", interpreter=Path(sys.executable),
                                     work_dir=tmp_path)
    assert rps.failures() == ["launcher cannot run"]


def test_launcher_check_runs_the_real_host_and_stops_it(tmp_path):
    rps.reset()
    root = _bundle(tmp_path)
    rps.check_launcher_from_unpacked(root, interpreter=Path(sys.executable), work_dir=tmp_path)
    failures = rps.failures()
    assert failures == [], failures
    status = json.loads((root / "ops" / "runtime" / "launcher_status.json").read_text("utf-8"))
    assert status["mode"] == "owned"
    assert status["state"] == "halted", "the final status records the stop"
    for rel in rps.LAUNCHER_SECRETS:
        assert (root / rel).is_file(), rel


def _fake_shell(tmp_path: Path, bundle_root: Path) -> Path:
    shell = tmp_path / "win-unpacked"
    res = shell / "resources"
    backend = res / rps.SHELL_BACKEND_DIR
    for rel in ("main.py", "ops/launcher/service_host.py", "ops/launcher/services.json",
                "python-embed/python.exe", "python-embed/pythonw.exe"):
        (backend / rel).parent.mkdir(parents=True, exist_ok=True)
        (backend / rel).write_text("x", encoding="utf-8")
    shutil.copyfile(bundle_root / bp.MANIFEST_NAME, backend / bp.MANIFEST_NAME)
    (shell / f"{rps.SHELL_PRODUCT_NAME}.exe").write_bytes(b"MZ")
    (res / "app.asar").write_bytes(b'{"files":{"src":{"files":{"launcher.js":{},'
                                   b'"starting.html":{}}}}}')
    return shell


def test_shell_build_check_accepts_a_complete_output_and_names_each_gap(tmp_path):
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    (bundle_root / bp.MANIFEST_NAME).write_text('{"build": 1}', encoding="utf-8")
    shell = _fake_shell(tmp_path, bundle_root)
    rps.reset()
    rps.check_shell_build(shell, bundle_root)
    assert rps.failures() == []
    (shell / "resources" / rps.SHELL_BACKEND_DIR / "ops" / "runtime").mkdir()
    (bundle_root / bp.MANIFEST_NAME).write_text('{"build": 2}', encoding="utf-8")
    (shell / "resources" / rps.SHELL_BACKEND_DIR / "python-embed" / "python.exe").unlink()
    rps.reset()
    rps.check_shell_build(shell, bundle_root)
    assert set(rps.failures()) == {
        "no ops/runtime in the shipped backend",
        "the shell carries the same backend build as the archive",
        f"resources/{rps.SHELL_BACKEND_DIR}/python-embed/python.exe",
    }


def test_shell_constants_match_the_builder_config():
    yml = BUILDER_YML.read_text(encoding="utf-8")
    product = re.search(r"^productName:\s*(.+?)\s*$", yml, re.M).group(1)
    assert product == rps.SHELL_PRODUCT_NAME
    assert json.loads(SHELL_PKG.read_text(encoding="utf-8"))["productName"] == product
    assert re.search(r"^\s*-?\s*from:\s*\.\./dist/portable_staging\s*$", yml, re.M)
    assert re.search(rf"^\s*to:\s*{rps.SHELL_BACKEND_DIR}\s*$", yml, re.M)


def test_bootstrap_check_treats_restart_clean_as_dev_only_in_a_bundle(tmp_path, monkeypatch):
    from tools import bootstrap_env_check as bec
    assert bp.exclusion_reason("scripts/restart_clean.bat"), "the builder excludes it"
    assert bec.DEV_ONLY_LAUNCHERS == {"scripts/restart_clean.bat"}
    monkeypatch.setattr(bec, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(bec, "_issues", [])
    (tmp_path / bp.MANIFEST_NAME).write_text("{}", encoding="utf-8")
    bec._check_launcher("scripts/restart_clean.bat", "ok", "", "missing", "")
    assert bec._issues == [], "a staged bundle omits it on purpose"
    bec._check_launcher("start.bat", "ok", "", "start.bat missing", "")
    assert bec._issues == [("MISS", "start.bat missing")], "every other launcher still counts"
    (tmp_path / bp.MANIFEST_NAME).unlink()
    monkeypatch.setattr(bec, "_issues", [])
    bec._check_launcher("scripts/restart_clean.bat", "ok", "", "restart_clean missing", "")
    assert bec._issues == [("MISS", "restart_clean missing")], "a dev checkout still needs it"


def test_archmap_never_walks_the_build_output():
    # A local build stages full copies of the tree under dist/portable_staging
    # and rc-shell/dist/win-unpacked/resources/backend; gen_archmap's pre-commit
    # --check then refused every commit (s142). Skipping the names is safe only
    # while no tracked path has such a segment.
    from tests import _repo_walk
    from tools import gen_archmap
    assert {"dist", "build"} <= gen_archmap.SKIP_DIRS
    tracked = _repo_walk.tracked_relpaths()
    assert tracked, "the git index answered"
    hits = [p for p in tracked if {"dist", "build"} & set(p.split("/")[:-1])]
    assert hits == [], hits[:5]


def test_the_launcher_check_runs_after_every_bundle_content_check():
    src = inspect.getsource(rps.run)
    last = src.index("check_launcher_from_unpacked(")
    for earlier in ("check_exclusions(", "check_bootstrap_from_unpacked(",
                    "check_imports_from_unpacked(", "check_shell_build("):
        assert src.index(earlier) < last, earlier
