# arch: PKG-6b packaged smoke - host restart command [G] + backend updater [I] | section=tests | frozen=no
"""PKG-6b (docs/PACKAGING_PLAN.md section 4, WA11): tools/run_packaged_smoke.py
proves the update path on the real artifact:

  [C1] the bundle ships backend-manifest.json (the updater's ownership
       baseline) and it parses under the updater's own schema check
  [G]  the bundle's service host restarts a service on the shell's JSON
       restart command (a new pid, the old process gone, outcome recorded)
  [I]  the bundle's ops/launcher/update_cycle.py, under the embedded runtime
       with `-I`, reads the baseline, reports up-to-date on an empty source,
       then stages a newer local release that CHANGES an owned file and hands
       the supervisor a deploy request that verifies with the per-install
       key the host provisioned in [G] - checked by the bundle's own deploy
       worker (no supervisor runs, so the cycle ends `pending`)

These tests run the REAL host and the REAL cycle as child processes against
a minimal bundle in tmp_path, with this interpreter standing in for the
embedded runtime. No network, no live RC port, no live tree.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import shutil
import sys
from pathlib import Path

from tools import run_packaged_smoke as rps

REPO = Path(__file__).resolve().parent.parent
LAUNCHER = REPO / "ops" / "launcher"


def _bundle(tmp_path: Path) -> Path:
    root = tmp_path / "bundle"
    dest = root / "ops" / "launcher"
    dest.mkdir(parents=True)
    for name in ("__init__.py", "service_host.py", "first_run.py", "services.json",
                 "updater.py", "update_cycle.py"):
        shutil.copyfile(LAUNCHER / name, dest / name)
    (root / "ops" / "__init__.py").write_text("", encoding="ascii")
    shutil.copyfile(REPO / "ops" / "rc_transactional_deploy.py",
                    root / "ops" / "rc_transactional_deploy.py")
    shutil.copyfile(REPO / ".gitignore", root / ".gitignore")
    lic = b"Apache License\n"
    (root / "LICENSE").write_bytes(lic)
    (root / "backend-manifest.json").write_text(json.dumps({
        "schema": 1, "kind": "amberstone-backend", "version": "0.0.0", "channel": "stable",
        "files": [{"path": "LICENSE", "sha256": hashlib.sha256(lic).hexdigest(),
                   "size": len(lic)}]}), encoding="ascii")
    return root


def test_g_the_host_restarts_a_service_on_the_restart_command(tmp_path):
    rps.reset()
    root = _bundle(tmp_path)
    rps.check_launcher_from_unpacked(root, interpreter=Path(sys.executable), work_dir=tmp_path)
    assert rps.failures() == [], rps.failures()
    assert any(p.startswith("host restarted the probe service") for p in rps._passes), rps._passes
    status = json.loads((root / "ops" / "runtime" / "launcher_status.json").read_text("utf-8"))
    rec = next(c for c in status["commands"] if c["id"] == rps.LAUNCHER_RESTART_ID)
    assert rec["results"] == {rps.LAUNCHER_PROBE_SERVICE: "restarted"}


def test_i_the_update_cycle_stages_and_signs_on_the_bundle(tmp_path):
    rps.reset()
    root = _bundle(tmp_path)
    rps.check_launcher_from_unpacked(root, interpreter=Path(sys.executable), work_dir=tmp_path)
    rps.check_updater_from_unpacked(root, interpreter=Path(sys.executable), work_dir=tmp_path)
    assert rps.failures() == [], rps.failures()
    labels = rps._passes
    assert any(p.startswith("updater reads the install's ownership baseline") for p in labels)
    assert any(p.startswith("update cycle: up-to-date on an empty source") for p in labels)
    deferred = any(p.startswith("update cycle deferred") for p in labels)
    if not deferred:   # a League client running on this box defers the apply
        assert any(p.startswith("update cycle staged") for p in labels), labels
        assert any(p.startswith("deploy request verifies with the per-install key")
                   for p in labels), labels
        assert (root / "ops" / "runtime" / "staging" / "0.0.1").is_dir()


def test_i_fails_closed_without_the_cycle(tmp_path):
    rps.reset()
    (tmp_path / "bundle").mkdir()
    rps.check_updater_from_unpacked(tmp_path / "bundle", interpreter=Path(sys.executable),
                                    work_dir=tmp_path)
    assert rps.failures() == ["updater cannot run"]


def test_i_bumps_a_semver_patch():
    assert rps._bump_version("0.0.0") == "0.0.1"
    assert rps._bump_version("1.2.3-rc.1") == "1.2.4"


def test_c1_requires_and_parses_the_backend_manifest(tmp_path):
    assert any(rel == "backend-manifest.json" for rel, _ in rps.REQUIRED_FILES)
    rps.reset()
    root = _bundle(tmp_path)
    rps.check_backend_manifest(root)
    assert rps.failures() == []
    (root / "backend-manifest.json").write_text("{}", encoding="ascii")
    rps.reset()
    rps.check_backend_manifest(root)
    assert rps.failures() == ["backend-manifest.json is not a valid updater baseline"]


def test_the_updater_check_runs_after_the_launcher_check():
    src = inspect.getsource(rps.run)
    assert src.index("check_launcher_from_unpacked(") < src.index("check_updater_from_unpacked(")
    assert src.index("check_manifests(") < src.index("check_backend_manifest(")
