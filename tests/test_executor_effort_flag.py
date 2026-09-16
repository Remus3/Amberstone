"""The headless lane executor must carry a configured --effort level.

Operator instruction 2026-09-16: the headless lanes run at effort HIGH. The
model half already shipped as `executor_model`; this is the effort half.

Accepted values are MACHINE-VERIFIED against the installed CLI 2.1.251: passing
`--effort bogusvalue` makes it print the valid set - low, medium, high, xhigh,
max - and fall back to the default. `--help` alone only says "<level>", so the
set was determined by probing, not by reading the help text.

The load-bearing arm here is the ABSENT one: a config with no `executor_effort`
key must build the exact argv it built before this feature existed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ops.loop import executor  # noqa: E402


def _sdk(tmp_path: Path, **over):
    """Same construction idiom as tests/test_loop_executor.py::_sdk."""
    cfg = {"channel": "sdk", "repo_root": str(tmp_path), "cycle_deadline_sec": 60}
    cfg.update(over)
    return executor.build(cfg, tmp_path, log=lambda m: None, stop=lambda m: None,
                          awrite=lambda p, t: None)


def test_effort_flag_is_passed_when_configured(tmp_path: Path):
    argv = _sdk(tmp_path, executor_cmd="claude.cmd", executor_effort="high").build_argv(1)
    assert "--effort" in argv, argv
    assert argv[argv.index("--effort") + 1] == "high"


def test_no_effort_flag_when_the_key_is_absent(tmp_path: Path):
    """The regression that matters: an unset key changes nothing at all."""
    argv = _sdk(tmp_path, executor_cmd="claude.cmd", executor_model="claude-opus-5").build_argv(1)
    assert "--effort" not in argv, argv


def test_no_effort_flag_when_the_value_is_empty(tmp_path: Path):
    """Empty string is not a level - it must not become `--effort ''`."""
    argv = _sdk(tmp_path, executor_cmd="claude.cmd", executor_effort="").build_argv(1)
    assert "--effort" not in argv, argv


def test_model_flag_is_unchanged_by_the_effort_branch(tmp_path: Path):
    """Negative control against breaking the neighbouring --model branch."""
    argv = _sdk(tmp_path, executor_cmd="claude.cmd", executor_model="claude-opus-5",
                executor_effort="high").build_argv(1)
    assert argv[argv.index("--model") + 1] == "claude-opus-5"
    argv_no_effort = _sdk(tmp_path, executor_cmd="claude.cmd",
                          executor_model="claude-opus-5").build_argv(1)
    assert argv_no_effort[argv_no_effort.index("--model") + 1] == "claude-opus-5"


def test_shipped_config_carries_opus_5_at_effort_high():
    """Guards the SHIPPED config, so a later edit dropping either key is caught.

    Deliberately has no skip path: the file is tracked, so its absence is a
    failure, not a reason to assert nothing.
    """
    cfg_path = REPO_ROOT / "ops" / "loop" / "config.json"
    assert cfg_path.is_file(), f"missing tracked config: {cfg_path}"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert cfg.get("executor_model") == "claude-opus-5"
    assert cfg.get("executor_effort") == "high"
