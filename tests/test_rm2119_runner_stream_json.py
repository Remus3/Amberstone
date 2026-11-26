"""RM-2119: the three runners RM-2116 left in json mode now stream each run as
stream-json into its own per-run `.stream.jsonl` (the kit's log_path=), so the
rc-cause line can name the last tool. Model: test_run_lane_lane_effort.py."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

FAKE_ROUTE = (
    "import json, os, sys\n"
    "with open(os.environ['RC_RM2119_ARGV'], 'w', encoding='ascii') as fh:\n"
    "    json.dump(sys.argv[1:], fh)\n"
)


def _powershell_51():
    root = os.environ.get("SYSTEMROOT")
    exe = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe" \
        if root else None
    return exe if exe is not None and exe.is_file() else None


def _run_script(tmp_path, name):
    (tmp_path / "tools").mkdir()
    (tmp_path / "ops" / "loop").mkdir(parents=True)
    (tmp_path / "tools" / name).write_bytes((ROOT / "tools" / name).read_bytes())
    (tmp_path / "ops" / "loop" / "fleet_route.py").write_text(FAKE_ROUTE, encoding="ascii")
    argv_out = tmp_path / "argv.json"
    env = dict(os.environ)
    env["RC_RM2119_ARGV"] = str(argv_out)
    env["LOCALAPPDATA"] = str(tmp_path / "nolocal")  # force the `python` fallback
    proc = subprocess.run(
        [str(_powershell_51()), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(tmp_path / "tools" / name)],
        env=env, cwd=str(tmp_path), capture_output=True, text=True, timeout=120,
        check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    return json.loads(argv_out.read_text(encoding="ascii"))


def _check(argv, tmp_path):
    assert "--log-path" in argv
    got = argv[argv.index("--log-path") + 1]
    assert got.endswith(".stream.jsonl")
    assert Path(got).parent == tmp_path / "logs"
    assert argv.index("--log-path") < argv.index("--")
    assert not got.endswith(".log")


@pytest.mark.skipif(_powershell_51() is None, reason="Windows PowerShell 5.1 not present")
def test_headless_run_streams_each_attempt_to_its_own_json_log(tmp_path):
    _check(_run_script(tmp_path, "headless_run.ps1"), tmp_path)


@pytest.mark.skipif(_powershell_51() is None, reason="Windows PowerShell 5.1 not present")
def test_weekly_hygiene_streams_the_run_to_its_own_json_log(tmp_path):
    _check(_run_script(tmp_path, "weekly_hygiene_run.ps1"), tmp_path)


def _executor():
    from ops.loop import executor
    return executor


def _sdk(tmp_path):
    ex = _executor()
    return ex.build({"channel": "sdk", "repo_root": str(tmp_path), "cycle_deadline_sec": 60},
                    tmp_path, log=lambda m: None, stop=lambda m: None,
                    awrite=lambda p, t: None)


class _Proc:
    def __init__(self, stdout="", rc=0):
        self.stdout, self.stderr, self.returncode = stdout, "", rc


def _fake_fr(calls, write_result, stdout=""):
    class FR:
        class RouteRefused(Exception):
            reason = "x"

        @staticmethod
        def _usage_cause():
            from ops.loop import usage_cause
            return usage_cause

        @staticmethod
        def spawn(prompt, **kw):
            calls.append(kw)
            if write_result is not None and kw.get("log_path"):
                Path(kw["log_path"]).parent.mkdir(parents=True, exist_ok=True)
                Path(kw["log_path"]).write_text(
                    json.dumps({"type": "system"}) + "\n" + json.dumps(write_result) + "\n",
                    encoding="utf-8")
            return {}, _Proc(stdout)
    return FR


RESULT = {"type": "result", "subtype": "success", "is_error": False,
          "total_cost_usd": 0.5, "session_id": "sess-log",
          "structured_output": {"sha": "a" * 40, "tests_pass": "7",
                                "regressions": False, "summary": "from the log"}}


def test_sdk_executor_passes_log_path_and_reads_the_result_from_the_log(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(_executor(), "_fleet_route_module",
                        lambda: _fake_fr(calls, RESULT))
    rec = _sdk(tmp_path).run(1, "b", "fixed")
    assert calls and calls[0].get("log_path", "").endswith(".stream.jsonl")
    assert rec.error is None
    assert rec.sha == "a" * 40
    assert rec.session_id == "sess-log"
    assert rec.cost_usd == 0.5


def test_sdk_executor_falls_back_to_stdout_when_the_log_is_absent(tmp_path, monkeypatch):
    calls = []
    payload = dict(RESULT)
    payload.pop("type")
    monkeypatch.setattr(_executor(), "_fleet_route_module",
                        lambda: _fake_fr(calls, None, stdout=json.dumps(payload)))
    rec = _sdk(tmp_path).run(1, "b", "fixed")
    assert calls[0].get("log_path")
    assert rec.error is None and rec.sha == "a" * 40
