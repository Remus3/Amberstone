"""MAIN ORDER 2026-11-14 0930 O1: ops/loop/run_lane.ps1 reads the lane's effort from
ops/loop/config.json `lane_effort[<lane>]` and falls back to `executor_effort`. The
lane is the s144 prompt-file stem with its `s144-` prefix cut (note lane-s144-<lane>)."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUN_LANE = ROOT / "ops" / "loop" / "run_lane.ps1"
CONFIG = ROOT / "ops" / "loop" / "config.json"

FAKE_ROUTE = (
    "import json, os, sys\n"
    "with open(os.environ['RC_LANE_EFFORT_ARGV'], 'w', encoding='ascii') as fh:\n"
    "    json.dump(sys.argv[1:], fh)\n"
)


def _code():
    return "\n".join(ln for ln in RUN_LANE.read_text(encoding="ascii").splitlines()
                     if ln.strip() and not ln.lstrip().startswith("#"))


def _powershell_51():
    root = os.environ.get("SYSTEMROOT")
    exe = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe" \
        if root else None
    return exe if exe is not None and exe.is_file() else None


def test_config_carries_both_effort_keys():
    cfg = json.loads(CONFIG.read_text(encoding="ascii"))
    assert cfg["executor_effort"] == "high"
    assert cfg["lane_effort"] == {"ds": "medium", "research": "medium"}


def test_config_trial_matches_the_ledger_trial():
    from ops.loop import lane_run_ledger as RL
    cfg = json.loads(CONFIG.read_text(encoding="ascii"))
    assert cfg["lane_effort"] == RL.EFFORT_TRIAL


def test_runner_reads_lane_effort_after_the_executor_effort_and_before_the_route():
    code = _code()
    fallback = code.index("$cfg.executor_effort")
    lane = code.index("$cfg.lane_effort")
    route = code.index('"--effort", $effort')
    assert fallback < lane < route


def _run(tmp_path, cfg, stem):
    loop = tmp_path / "ops" / "loop"
    loop.mkdir(parents=True)
    (tmp_path / "ops" / "fleet_kit").mkdir()
    (loop / "run_lane.ps1").write_bytes(RUN_LANE.read_bytes())
    (loop / "fleet_route.py").write_text(FAKE_ROUTE, encoding="ascii")
    if cfg is not None:
        (loop / "config.json").write_text(json.dumps(cfg), encoding="ascii")
    prompt = tmp_path / f"{stem}.md"
    prompt.write_text("prompt\n", encoding="ascii")
    argv_out, log = tmp_path / "argv.json", tmp_path / "lane.log"
    env = {k: v for k, v in os.environ.items() if k != "RC_LANE_MODEL"}
    env["RC_LANE_EFFORT_ARGV"] = str(argv_out)
    proc = subprocess.run(
        [str(_powershell_51()), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(loop / "run_lane.ps1"), "-PromptFile", str(prompt), "-Cwd", str(tmp_path),
         "-Log", str(log)],
        env=env, cwd=str(tmp_path), capture_output=True, text=True, timeout=120,
        check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    text = log.read_text(encoding="utf-8-sig", errors="replace")
    assert proc.returncode == 0, (proc.returncode, text, proc.stderr)
    argv = json.loads(argv_out.read_text(encoding="ascii"))
    return argv[argv.index("--effort") + 1] if "--effort" in argv else None, text


BOTH = {"executor_effort": "high", "lane_effort": {"ds": "medium", "research": "medium"}}


@pytest.mark.skipif(_powershell_51() is None, reason="Windows PowerShell 5.1 not present")
@pytest.mark.parametrize(("cfg", "stem", "want"), [
    (BOTH, "s144-ds", "medium"),
    (BOTH, "s144-research", "medium"),
    (BOTH, "s144-repo", "high"),
    (BOTH, "s144-true-audit", "high"),
    (BOTH, "s144-queue", "high"),
    (BOTH, "plain-name", "high"),
    ({"executor_effort": "high"}, "s144-ds", "high"),
    ({"executor_effort": "high", "lane_effort": {"ds": "turbo"}}, "s144-ds", "high"),
    ({"executor_effort": "high", "lane_effort": {"true-audit": "low"}}, "s144-true-audit", "low"),
    ({"lane_effort": {"ds": "medium"}}, "s144-ds", "medium"),
    ({"lane_effort": {"ds": "medium"}}, "s144-repo", None),
    (None, "s144-ds", None),
])
def test_run_lane_under_powershell_51_resolves_lane_effort(tmp_path, cfg, stem, want):
    got, log = _run(tmp_path, cfg, stem)
    assert got == want
    assert re.search(rf"effort={want or ''}( |$)", log.splitlines()[0])


@pytest.mark.skipif(_powershell_51() is None, reason="Windows PowerShell 5.1 not present")
def test_run_lane_streams_each_run_to_its_own_json_log(tmp_path):
    """RM-2116: the lane passes a per-run stream-json log beside its lane log, so the
    rc-cause line can name the last tool; the name never matches lane_launcher's
    lane_<lane>_*.log run count."""
    _run(tmp_path, {"executor_effort": "high"}, "s144-ds")
    argv = json.loads((tmp_path / "argv.json").read_text(encoding="ascii"))
    assert "--log-path" in argv
    got = argv[argv.index("--log-path") + 1]
    assert got == str(tmp_path / "lane.stream.jsonl")
    assert argv.index("--log-path") < argv.index("--")
    assert not got.endswith(".log")
