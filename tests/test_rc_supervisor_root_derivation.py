"""The supervisor derives the checkout root; ops/rc_config.json names no machine path.

MAIN 2246 ORDER section 3 (leaks by class, absolute checkout path) and the
operator's chat grant of 2026-10-09 (frozen ops/rc_supervisor.py, leak removal
only): the tracked config carried the checkout's absolute path in four keys,
and the supervisor resolved `project_root` verbatim. RC-Supervisor runs with NO
working directory, so a relative value resolved against the process CWD would
point at the wrong tree. The root is now derived from rc_supervisor.py's own
location; relative config values resolve against it, absolute values stay a
per-host override.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ops import rc_supervisor as sup

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "ops" / "rc_config.json"
_PATH_KEYS = ("project_root", "runtime_dir", "health_file", "deploy_script")


def test_module_root_is_the_checkout():
    assert sup._REPO_ROOT == REPO.resolve()


def test_absent_keys_derive_from_the_file_location(tmp_path):
    got = sup.resolve_config_paths({}, repo_root=tmp_path)
    assert got["project_root"] == tmp_path.resolve()
    assert got["runtime_dir"] == (tmp_path / "ops" / "runtime").resolve()
    assert got["health_file"] == (tmp_path / "ops" / "runtime" / "health.json").resolve()
    assert got["deploy_script"] == (tmp_path / "ops" / "rc_transactional_deploy.py").resolve()


def test_relative_values_resolve_against_the_root_not_the_cwd(tmp_path, monkeypatch):
    elsewhere = tmp_path / "cwd"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    repo = tmp_path / "Example Repo"
    got = sup.resolve_config_paths(
        {"project_root": ".", "runtime_dir": "ops/runtime",
         "health_file": "ops/runtime/health.json",
         "deploy_script": "ops/rc_transactional_deploy.py"},
        repo_root=repo)
    assert got["project_root"] == repo.resolve()
    assert got["runtime_dir"] == (repo / "ops" / "runtime").resolve()
    assert got["health_file"] == (repo / "ops" / "runtime" / "health.json").resolve()
    assert got["deploy_script"] == (repo / "ops" / "rc_transactional_deploy.py").resolve()


def test_absolute_values_stay_a_per_host_override(tmp_path):
    other = tmp_path / "other"
    got = sup.resolve_config_paths(
        {"project_root": str(other), "runtime_dir": str(tmp_path / "rt")},
        repo_root=tmp_path / "ignored")
    assert got["project_root"] == other.resolve()
    assert got["runtime_dir"] == (tmp_path / "rt").resolve()
    assert got["health_file"] == (tmp_path / "rt" / "health.json").resolve()


def test_supervisor_init_uses_the_resolver(tmp_path, monkeypatch):
    # Every directory __init__ creates lives under tmp_path: runtime_dir is an
    # absolute override, so nothing is written into the live tree.
    monkeypatch.chdir(tmp_path)
    cfg = {"project_root": ".", "runtime_dir": str(tmp_path / "rt"),
           "app_cmd": ["pythonw.exe", "main.py"]}
    path = tmp_path / "rc_config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    s = sup.Supervisor(path)
    assert s.project_root == REPO.resolve()
    assert s.runtime_dir == (tmp_path / "rt").resolve()
    assert s.health_file == (tmp_path / "rt" / "health.json").resolve()
    assert s.deploy_script == (REPO / "ops" / "rc_transactional_deploy.py").resolve()


def test_tracked_config_carries_no_absolute_path():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    for key in _PATH_KEYS:
        value = cfg.get(key)
        assert isinstance(value, str), key  # the validator still requires them
        assert not Path(value).is_absolute(), key
        assert not re.match(r"^[A-Za-z]:", value), key
    resolved = sup.resolve_config_paths(cfg)
    assert resolved["project_root"] == REPO.resolve()
    assert resolved["deploy_script"].is_file()
