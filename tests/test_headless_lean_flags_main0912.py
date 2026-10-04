"""MAIN 0912 item A (and 0850 section 2): every RC pre-kit headless spawn carries
the kit's lean flags - `--strict-mcp-config` and `--setting-sources project,local`.

The kit composes them in `ops/fleet_kit/fleet_headless.py` `build_argv` (non-bare
arm: `--strict-mcp-config`, `--setting-sources`, `DEFAULT_SOURCES`). The three
pre-kit spawn paths are the inbox responder (`tools/inbox_responder_spawn.py`
`CLAUDE_ARGV_TAIL`), the loop executor (`ops/loop/executor.py` `build_argv`) and
the detached lane runner (`ops/loop/run_lane.ps1`). Expectations are literals on
purpose: an expectation imported from the module it checks cannot fail.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ops.fleet_kit import fleet_headless as kit  # noqa: E402
from ops.loop import executor  # noqa: E402
from tools import inbox_responder_spawn as spawn  # noqa: E402

SOURCES = "project,local"


def _pair(argv, flag):
    assert flag in argv, (flag, argv)
    return argv[argv.index(flag) + 1]


def test_kit_lean_shape_is_what_rc_matches():
    """Anchor: if the kit's own lean shape moves, this pin says so first."""
    argv = kit.build_argv("claude", "p", "sonnet", "low")
    assert "--strict-mcp-config" in argv
    assert _pair(argv, "--setting-sources") == SOURCES
    assert kit.DEFAULT_SOURCES == SOURCES


@dataclass
class _Cfg:
    max_turns: int = 5
    model: str = "sonnet"


def test_responder_tail_carries_both_lean_flags():
    tail = spawn.CLAUDE_ARGV_TAIL(_Cfg())
    assert "--strict-mcp-config" in tail
    assert _pair(tail, "--setting-sources") == SOURCES


def _sdk(tmp_path: Path, **over):
    cfg = {"channel": "sdk", "repo_root": str(tmp_path), "cycle_deadline_sec": 60,
           "executor_cmd": "claude.cmd"}
    cfg.update(over)
    return executor.build(cfg, tmp_path, log=lambda m: None, stop=lambda m: None,
                          awrite=lambda p, t: None)


def test_loop_executor_argv_carries_both_lean_flags(tmp_path: Path):
    argv = _sdk(tmp_path).build_argv(1)
    assert "--strict-mcp-config" in argv
    assert _pair(argv, "--setting-sources") == SOURCES


def test_loop_executor_lean_flags_survive_resume(tmp_path: Path):
    ex = _sdk(tmp_path, clear_each_cycle=False)
    ex.session_id = "abc"
    argv = ex.build_argv(2)
    assert "--resume" in argv and "--strict-mcp-config" in argv
    assert _pair(argv, "--setting-sources") == SOURCES


def _run_lane_claude_line() -> str:
    text = (REPO_ROOT / "ops" / "loop" / "run_lane.ps1").read_text(encoding="ascii")
    lines = [ln for ln in text.splitlines()
             if re.search(r"&\s*\$claude\b", ln) and not ln.lstrip().startswith("#")]
    assert len(lines) == 1, lines
    return lines[0]


def test_run_lane_invocation_carries_both_lean_flags():
    line = _run_lane_claude_line()
    assert "--strict-mcp-config" in line, line
    # PowerShell parses a bare `project,local` as an ARRAY, so the value must be
    # a quoted string to reach the CLI as one argument.
    assert re.search(r"--setting-sources\s+(['\"])project,local\1", line), line
