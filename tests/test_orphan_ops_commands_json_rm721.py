"""RM-721 (b) dead-artifact drift guard.

Pins `ops/commands.json` as PERMANENTLY removed (s134 lane 7). It was a
35-byte file holding {"cmd": "set_mode", "mode": "ARAM"}, unchanged since the
initial commit (2026-04-26). Zero consumers at removal time: no tracked .py,
.ps1, .js, .bat, .json or .yml names it (the only hits were the repo-review
finding B19-04 and its BACKLOG row), and the live command channels read the
DIRECTORY `<runtime>/control/commands/` (ops/rc_dev_runtime.py,
ops/rc_self_monitor.py, ops/rc_transactional_deploy.py), never a file under
ops/. The whole file is recoverable from git history.

Same shape as tests/test_orphan_scripts_rm227.py. If you find yourself adding
it back, first confirm a real reader exists.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DELETED = "ops/commands.json"


def test_rm721_ops_commands_json_stays_deleted() -> None:
    assert not (_ROOT / _DELETED).exists(), (
        f"{_DELETED} is back. It had no reader when RM-721 (b) removed it; "
        "the command channel is the <runtime>/control/commands/ directory."
    )


def test_rm721_guard_points_at_a_real_directory() -> None:
    # An absence check under a wrong root passes vacuously: anchor it.
    assert (_ROOT / "ops").is_dir()
    assert (_ROOT / "ops" / "rc_dev_runtime.py").is_file()
