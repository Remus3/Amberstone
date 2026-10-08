"""MAIN 0839 ORDER (FLEET-KIT v10) step 5: every RC headless path rides the kit.

Ruled by MAIN in the same note: "RC lane workers off the kit spawn and the
fleet_route effort knob (RC: route lanes through spawn / the CLI, use
effort=)". Three things are pinned here, all with fakes (no process, no
registry read, no socket, no live claude):

1. `ops/loop/fleet_route.py` is a THIN pass-through for the kit's own
   `model=` / `effort=` / `stdin=` (whole prompt on stdin) / `session_id=` /
   `resume=` parameters, on the Python call and on its CLI. RC adds no second
   effort policy: omitted, the kit's `pick_effort` decides.
2. The lane worker runner `ops/loop/run_lane.ps1` starts the worker through
   that CLI (kit spawn), never `claude -p` directly, with the operator's
   effort from `ops/loop/config.json` passed as `--effort`.
3. The loop executor's sdk channel (`ops/loop/executor.py`) starts its cycle
   through `fleet_route.spawn` with `effort=` from the config instead of the
   RC-local `--effort` argv knob, and inherits the kit's fail-closed route,
   budget, usage line, hidden console and process-tree kill.

Every run that goes through the kit gets the kit's `child_env`, which sets
FLEET_SUBAGENT_FIRST=off (v10: a headless run is exempt from the
SUBAGENT-FIRST hook). That is ASSERTED here, never re-implemented.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from subprocess import CompletedProcess

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops.loop import executor  # noqa: E402
from ops.loop import fleet_route  # noqa: E402
from ops.loop import headless_env as he  # noqa: E402
from tests import _kit_platform  # noqa: E402
from tests._kit_platform import assert_kit_killed  # noqa: E402

kit_platform = _kit_platform.kit_platform  # fixture, registered by module attribute

FAKE_URL = "http://127.0.0.1:65530"  # the conftest's fake open route
RUN_LANE = REPO / "ops" / "loop" / "run_lane.ps1"
DONE = {"sha": "a" * 40, "tests_pass": "1", "regressions": False, "summary": "s"}


class _Rec:
    """subprocess.run stand-in. The conftest forwards the kit's launch here."""

    def __init__(self, stdout='{"result": "done"}', rc=0):
        self.stdout, self.rc = stdout, rc
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw))
        return CompletedProcess(args=argv, returncode=self.rc, stdout=self.stdout, stderr="")

    def claude_calls(self):
        return [(a, k) for a, k in self.calls if a and a[0] == "claude-fake.exe"]


@pytest.fixture
def rec(monkeypatch):
    r = _Rec()
    monkeypatch.setattr(subprocess, "run", r)
    return r


def _usage(root):
    path = Path(root) / "ops/loop/control/headless_usage.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="ascii").splitlines()]


# ---------------------------------------------------------------------------
# 1. fleet_route: thin pass-through to the kit's effort= / model= / stdin=
# ---------------------------------------------------------------------------


def test_effort_and_model_reach_the_kit(rec, tmp_path):
    fleet_route.spawn("T", caller="t", note="lane-x", effort="high",
                      model="claude-opus-5-5", root=tmp_path)
    (argv, kw), = rec.claude_calls()
    assert argv[argv.index("--effort") + 1] == "high"
    assert argv[argv.index("--model") + 1] == "claude-opus-5-5"
    assert argv.count("--effort") == 1, "one effort flag, the kit's"
    (line,) = _usage(tmp_path)
    assert line["effort"] == "high" and line["model"] == "claude-opus-5-5"


def test_effort_omitted_is_the_kits_own_pick(rec, tmp_path, monkeypatch):
    seen = {}
    real = fleet_route.kit().spawn

    def _spy(*a, **kw):
        seen.update(kw)
        return real(*a, **kw)

    monkeypatch.setattr(fleet_route, "_kit_spawn", _spy)
    fleet_route.spawn("T", caller="t", note="lane-x", root=tmp_path)
    assert "effort" not in seen and "model" not in seen, \
        "no RC default: the pre-v10 call shape reaches the kit unchanged"
    (argv, _kw), = rec.claude_calls()
    assert argv[argv.index("--effort") + 1] == fleet_route.kit().pick_effort("lane-x")


def test_bad_effort_is_refused_by_the_kit_before_any_start(rec, tmp_path):
    with pytest.raises(fleet_route.RouteRefused) as ei:
        fleet_route.spawn("T", caller="t", effort="turbo", root=tmp_path)
    assert ei.value.reason == "kit" and "effort" in str(ei.value)
    assert rec.claude_calls() == []
    assert not (tmp_path / "ops/loop/control/headless_budget.json").exists()


def test_prompt_on_stdin_sends_the_whole_prompt_on_stdin(rec, tmp_path):
    big = "x" * (fleet_route.kit().ARGV_PROMPT_MAX + 10)
    fleet_route.spawn(big, caller="t", prompt_on_stdin=True, root=tmp_path)
    (argv, kw), = rec.claude_calls()
    assert big not in argv, "the prompt never rides the command line"
    assert kw["input"] == big


def test_prompt_on_stdin_and_a_body_cannot_both_feed_stdin(rec, tmp_path):
    with pytest.raises(ValueError):
        fleet_route.spawn("T", caller="t", prompt_on_stdin=True, stdin="BODY", root=tmp_path)
    assert rec.claude_calls() == []


def test_session_id_and_resume_pass_through(rec, tmp_path):
    fleet_route.spawn("T", caller="t", session_id="s-1", root=tmp_path)
    fleet_route.spawn("T", caller="t", resume="s-2", root=tmp_path)
    (a1, _), (a2, _) = rec.claude_calls()
    assert a1[a1.index("--session-id") + 1] == "s-1" and "--no-session-persistence" not in a1
    assert a2[a2.index("--resume") + 1] == "s-2"


def test_every_kit_run_is_exempt_from_the_subagent_first_hook(rec, tmp_path):
    fleet_route.spawn("T", caller="t", root=tmp_path)
    (_argv, kw), = rec.claude_calls()
    assert kw["env"]["FLEET_SUBAGENT_FIRST"] == "off"
    assert kw["env"]["ANTHROPIC_BASE_URL"] == FAKE_URL


def test_default_launcher_is_the_kits_public_launch():
    k = fleet_route.kit()
    assert fleet_route._kit_launcher(k) is k.launch


def test_cli_passes_effort_model_cwd_kind_and_stdin_prompt(rec, tmp_path, monkeypatch):
    monkeypatch.setattr(fleet_route, "ROOT", tmp_path)
    pf = tmp_path / "lane.md"
    pf.write_text("LANE PROMPT", encoding="ascii")
    wt = tmp_path / "wt"
    rc = fleet_route.main([
        "--caller", "run_lane", "--note", "lane-headless-ds", "--kind", "build",
        "--writes-code", "--model", "claude-opus-5-5", "--effort", "high",
        "--cwd", str(wt), "--timeout", "60", "--prompt-file", str(pf), "--prompt-stdin",
        "--", "--dangerously-skip-permissions"])
    assert rc == 0
    (argv, kw), = rec.claude_calls()
    assert "LANE PROMPT" not in argv and kw["input"] == "LANE PROMPT"
    assert argv[argv.index("--effort") + 1] == "high"
    assert argv[argv.index("--model") + 1] == "claude-opus-5-5"
    assert argv[-1] == "--dangerously-skip-permissions"
    assert kw["cwd"] == str(wt) and kw["timeout"] == 60
    (line,) = _usage(tmp_path)
    assert line["kind"] == "build" and line["note"] == "lane-headless-ds"


def test_cli_timeout_exits_4_like_the_kit_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fleet_route, "ROOT", tmp_path)

    def _hang(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 1)

    monkeypatch.setattr(subprocess, "run", _hang)
    assert fleet_route.main(["--caller", "c", "--prompt", "x", "--timeout", "1"]) == \
        fleet_route.EXIT_TIMEOUT == fleet_route.kit().CLI_TIMEOUT
    assert "timed out" in capsys.readouterr().err
    (line,) = _usage(tmp_path)
    assert line["error"] == "timeout"


def test_cli_moves_an_over_long_prompt_to_stdin_like_the_kit_cli(rec, tmp_path, monkeypatch):
    monkeypatch.setattr(fleet_route, "ROOT", tmp_path)
    big = "y" * (fleet_route.kit().ARGV_PROMPT_MAX + 1)
    pf = tmp_path / "big.md"
    pf.write_text(big, encoding="ascii")
    assert fleet_route.main(["--caller", "c", "--prompt-file", str(pf)]) == 0
    (argv, kw), = rec.claude_calls()
    assert big not in argv and kw["input"] == big


# ---------------------------------------------------------------------------
# 2. run_lane.ps1: the lane worker starts through the kit's door
# ---------------------------------------------------------------------------


def _code_lines(text):
    return [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def test_run_lane_never_starts_claude_itself():
    code = "\n".join(_code_lines(RUN_LANE.read_text(encoding="ascii")))
    assert not re.search(r"&\s*(\$claude|claude)\b", code, re.IGNORECASE)
    assert "Get-Command claude" not in code
    # the pre-kit PowerShell gate is gone with its last caller
    assert "headless_route.ps1" not in code and "Assert-HeadlessRoute" not in code


def test_run_lane_routes_through_the_fleet_route_cli():
    code = "\n".join(_code_lines(RUN_LANE.read_text(encoding="ascii")))
    # resolved next to the runner, i.e. in the MAIN checkout: budget, status and
    # usage land there, never in the lane worktree the child runs in
    assert re.search(r'Join-Path \$PSScriptRoot "fleet_route\.py"', code)
    for token in ('"--caller"', '"run_lane"', '"--writes-code"', '"--kind"', '"build"',
                  '"--cwd"', '$Cwd', '"--prompt-file"', '$PromptFile', '"--prompt-stdin"',
                  '"--model"', '"--timeout"'):
        assert token in code, token
    # the RC permission flag rides the kit's extra=, after the `--` separator
    assert re.search(r'"--"\s*,\s*"--dangerously-skip-permissions"', code)
    # fail closed: a refusal (exit 3) stops the runner, it never retries another way
    assert "$code -eq 3" in code and "exit 3" in code


def test_run_lane_takes_effort_from_the_loop_config_as_the_kits_effort():
    code = "\n".join(_code_lines(RUN_LANE.read_text(encoding="ascii")))
    assert "executor_effort" in code
    # only when set: PowerShell 5.1 drops an empty native argument, which would
    # shift every argument after `--effort` by one
    assert re.search(r'if \(\$effort\)\s*\{\s*\$routeArgs \+= @\("--effort", \$effort\)', code)


def test_run_lane_keeps_the_background_wait_ceiling_for_the_child():
    text = RUN_LANE.read_text(encoding="ascii")
    assert '$env:CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS = "2400000"' in text
    # the kit's child env is a copy of the runner's env: the ceiling survives,
    # the API key and provider switches do not, and the hook exemption is set
    env = fleet_route.kit().child_env(FAKE_URL, parent={
        "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "2400000", "ANTHROPIC_API_KEY": "k",
        "CLAUDE_CODE_USE_BEDROCK": "1"})
    assert env["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"] == "2400000"
    # read the membership into a local first: an `in env` assert operand would
    # render the whole mapping on failure (tests/test_no_environ_in_assert_operands.py)
    leaked = sorted(k for k in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK") if k in env)
    assert leaked == []
    assert env["FLEET_SUBAGENT_FIRST"] == "off"


def test_the_pre_kit_powershell_gate_is_retired():
    assert not (REPO / "ops" / "loop" / "headless_route.ps1").exists()


def test_run_lane_refusal_points_at_the_log_the_refusal_lands_in():
    """A headless_env refusal (unset / bad / non-loopback / down proxy) is
    logged by headless_env._log_refusal to logs/headless_route.log, and a kit
    refusal is logged there by fleet_route too; neither path is guaranteed to
    touch the kit status file, so the runner must not send the reader there."""
    code = "\n".join(_code_lines(RUN_LANE.read_text(encoding="ascii")))
    refused = [ln for ln in code.splitlines() if "lane refused" in ln]
    assert refused, "the refusal line is gone"
    for ln in refused:
        assert "inbox_status.json" not in ln, ln
    assert any(r"logs\headless_route.log" in ln for ln in refused), refused


def test_run_lane_never_reads_an_empty_exit_code_as_success():
    """When python itself cannot start, PowerShell sets no exit code: the old
    script logged "code=" and exited 0. Anything that is not an integer exit
    code from the route must be a fail-closed exit 3 (the old route's code)."""
    code = "\n".join(_code_lines(RUN_LANE.read_text(encoding="ascii")))
    # the stale value of an earlier native call can never be read as this one's
    assert "$global:LASTEXITCODE = $null" in code
    assert re.search(r"-notmatch\s+'\^-\?\\d\+\$'", code), \
        "the exit code must be checked to be an integer before it is trusted"


def _powershell_51():
    root = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT")
    exe = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe" \
        if root else None
    return exe if exe is not None and exe.is_file() else None


@pytest.mark.skipif(_powershell_51() is None, reason="Windows PowerShell 5.1 not present")
def test_run_lane_exits_3_when_python_cannot_start(tmp_path):
    """Executed for real under Windows PowerShell 5.1, with NO python reachable:
    LOCALAPPDATA points at an empty dir (no pinned interpreter) and PATH holds
    System32 only, so `python` cannot resolve. Belt and braces: the prompt file
    does not exist, so even a python that did start would fail on the read
    before any spawn - this test can never start a real claude."""
    root = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT")
    env = dict(os.environ)
    for key in [k for k in env if k.upper() in ("PATH", "LOCALAPPDATA")]:
        del env[key]
    env["PATH"] = str(Path(root) / "System32")
    env["LOCALAPPDATA"] = str(tmp_path / "no_python_here")
    log = tmp_path / "lane.log"
    proc = subprocess.run(
        [str(_powershell_51()), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(RUN_LANE), "-PromptFile", str(tmp_path / "absent_prompt.md"),
         "-Cwd", str(tmp_path), "-Log", str(log)],
        env=env, cwd=str(tmp_path), capture_output=True, text=True, timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    text = log.read_text(encoding="utf-8-sig", errors="replace")
    assert proc.returncode == 3, (proc.returncode, text, proc.stderr)
    assert "lane start" in text and "could not start" in text, text
    assert "code=\n" not in text and not text.rstrip().endswith("code="), text


# ---------------------------------------------------------------------------
# 3. the loop executor's sdk channel rides fleet_route -> kit spawn
# ---------------------------------------------------------------------------


def _sdk(tmp_path, **over):
    # executor_cmd is a harmless interpreter that exits at once. The kit owns
    # the exe now and ignores this key; it is pinned so that a PRE-change
    # executor (the TDD red run) can never start a real `claude` binary.
    cfg = {"channel": "sdk", "repo_root": str(tmp_path), "cycle_deadline_sec": 60,
           "executor_cmd": [sys.executable, "-c", "raise SystemExit(9)"]}
    cfg.update(over)
    return executor.build(cfg, tmp_path, log=lambda m: None, stop=lambda m: None,
                          awrite=lambda p, t: None)


@pytest.fixture
def no_git(monkeypatch):
    # the grounding guard reads HEAD before the spawn; keep the spawn the only call
    monkeypatch.setattr(executor, "_git_head", lambda root: "")


def _receipt(**over):
    body = {"type": "result", "is_error": False, "total_cost_usd": 0.5,
            "session_id": "sess-9", "structured_output": dict(DONE)}
    body.update(over)
    return json.dumps(body)


def test_executor_cycle_goes_through_the_kit_with_effort_from_config(
        rec, no_git, tmp_path):
    rec.stdout = _receipt()
    rec_ = _sdk(tmp_path, executor_effort="high", executor_model="claude-opus-5-5",
                cycle_budget_usd=25.0, permission_mode="bypassPermissions")
    out = rec_.run(1, "BODY", "fixed")
    assert out.error is None and out.sha == "a" * 40 and out.session_id == "sess-9"
    (argv, kw), = rec.claude_calls()
    assert argv[:2] == ["claude-fake.exe", "-p"], "the kit composes the argv"
    assert argv[argv.index("--effort") + 1] == "high" and argv.count("--effort") == 1
    assert argv[argv.index("--model") + 1] == "claude-opus-5-5" and argv.count("--model") == 1
    assert argv.count("--output-format") == 1 and argv.count("--strict-mcp-config") == 1
    assert "--session-id" in argv and "--resume" not in argv
    assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions"
    assert argv[argv.index("--max-budget-usd") + 1] == "25.0"
    assert "--json-schema" in argv and "--add-dir" in argv
    # the whole prompt rides stdin, the command line carries none of it
    assert "BODY" in kw["input"] and not any("BODY" in a for a in argv)
    assert kw["cwd"] == str(tmp_path) and kw["timeout"] == 60.0
    assert kw["env"]["FLEET_SUBAGENT_FIRST"] == "off"
    assert kw["env"]["ANTHROPIC_BASE_URL"] == FAKE_URL
    assert kw["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    (line,) = _usage(fleet_route.ROOT)
    assert line["kind"] == "build" and line["effort"] == "high" and line["code"] == "RC"


def test_executor_without_an_effort_key_takes_the_kits_pick(rec, no_git, tmp_path):
    rec.stdout = _receipt()
    _sdk(tmp_path).run(1, "b", "fixed")
    (argv, _kw), = rec.claude_calls()
    k = fleet_route.kit()
    assert argv[argv.index("--effort") + 1] == k.pick_effort(executor.SDK_NOTE)


def test_executor_resumes_through_the_kit(rec, no_git, tmp_path):
    rec.stdout = _receipt()
    ex = _sdk(tmp_path, clear_each_cycle=False)
    ex.session_id = "prior-1"
    ex.run(2, "b", "fixed")
    (argv, _kw), = rec.claude_calls()
    assert argv[argv.index("--resume") + 1] == "prior-1" and "--session-id" not in argv


def test_executor_refused_route_starts_nothing(rec, no_git, tmp_path, monkeypatch):
    monkeypatch.setattr(he, "_read_user_var", lambda name: None)
    monkeypatch.setattr(he, "REFUSAL_LOG", tmp_path / "r.log")
    out = _sdk(tmp_path).run(1, "b", "fixed")
    assert out.error == "headless route refused: unset"
    assert rec.claude_calls() == []
    assert '"caller": "loop_executor"' in (tmp_path / "r.log").read_text(encoding="utf-8")


def test_executor_bad_effort_is_a_refused_cycle_not_a_crash(rec, no_git, tmp_path):
    out = _sdk(tmp_path, executor_effort="turbo").run(1, "b", "fixed")
    assert out.error.startswith("headless route refused: kit")
    assert rec.claude_calls() == []


def test_executor_source_has_no_process_start_of_its_own():
    text = (REPO / "ops" / "loop" / "executor.py").read_text(encoding="utf-8")
    assert "subprocess.Popen(" not in text
    assert "headless_child_env(" not in text
    assert '"--effort"' not in text, "the RC-local effort knob is retired into effort="
    assert "fleet_route" in text and ".spawn(" in text


class _HangPopen:
    made: list = []

    def __init__(self, argv, stdin=None, **kw):
        self.argv, self.pid, self.returncode, self.n = list(argv), 777, None, 0
        self.killed = False
        _HangPopen.made.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def communicate(self, input=None, timeout=None):
        self.n += 1
        if self.n == 1:
            raise subprocess.TimeoutExpired(self.argv, timeout)
        self.returncode = 1
        return ("", "")

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.killed = True


def test_executor_timeout_kills_the_tree_through_the_kit(
        no_git, kit_platform, tmp_path, monkeypatch):
    monkeypatch.setattr(fleet_route, "_launch", None)  # production: the kit's launch
    _HangPopen.made = []
    monkeypatch.setattr(subprocess, "Popen", _HangPopen)
    kills = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: kills.append(list(argv)) or
                        CompletedProcess(args=argv, returncode=0, stdout="", stderr=""))
    out = _sdk(tmp_path, cycle_deadline_sec=2).run(1, "b", "fixed")
    assert "timeout" in out.error
    (p,) = _HangPopen.made
    assert p.argv[1] == "-p"
    assert_kit_killed(kit_platform, kills, p.killed, 777)
