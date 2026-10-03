"""ops/loop/fleet_route.py - RC's one door into the vendored fleet kit.

Drives the REAL kit (`ops/fleet_kit/fleet_headless.spawn`) through the adapter
with every outside effect faked: the route comes from the conftest's fake
`headless_env`, the process seam is a recorder standing in for
`subprocess.run`, the exe is a fake name, and the kit's budget / status / usage
files land in a per-test tmp root. Nothing here starts a process, reads the
registry or opens a socket.

What is pinned: fail closed (RC gate refusal AND kit refusal both start
nothing), stdin and cwd reach the child through the kit's run seam, the kit's
own budget / status / usage writes happen under the given root, a raised
timeout leaves the status idle, and the CLI the PowerShell runners use.
"""
from __future__ import annotations

import json
import subprocess
from subprocess import CompletedProcess

import pytest

from ops.loop import fleet_route
from ops.loop import headless_env as he

FAKE_URL = "http://127.0.0.1:65530"


class _Rec:
    def __init__(self, stdout='{"result": "done", "usage": {"input_tokens": 3}}', rc=0,
                 stderr="", raise_exc=None):
        self.stdout, self.rc, self.stderr, self.raise_exc = stdout, rc, stderr, raise_exc
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw))
        if self.raise_exc is not None:
            raise self.raise_exc
        return CompletedProcess(args=argv, returncode=self.rc, stdout=self.stdout,
                                stderr=self.stderr)


@pytest.fixture
def rec(monkeypatch):
    r = _Rec()
    monkeypatch.setattr(subprocess, "run", r)
    return r


def _status(root):
    return json.loads((root / "ops/loop/control/inbox_status.json").read_text(encoding="ascii"))


def test_routed_spawn_goes_through_the_real_kit(rec, tmp_path):
    line, proc = fleet_route.spawn("TASK", caller="t", note="n", stdin="BODY",
                                   extra=["--permission-mode", "plan"], root=tmp_path)
    (argv, kw), = rec.calls
    assert argv[:3] == ["claude-fake.exe", "-p", "TASK"]
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert "--strict-mcp-config" in argv and argv[-2:] == ["--permission-mode", "plan"]
    assert kw["input"] == "BODY"
    assert kw["cwd"] == str(tmp_path)
    assert kw["env"]["ANTHROPIC_BASE_URL"] == FAKE_URL
    assert "ANTHROPIC_API_KEY" not in kw["env"]
    assert kw["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert line["code"] == "RC" and line["result"] == "done" and line["rc"] == 0
    assert proc.stdout == rec.stdout
    budget = json.loads((tmp_path / "ops/loop/control/headless_budget.json").read_text())
    assert len(budget["starts"]) == 1
    usage = (tmp_path / "ops/loop/control/headless_usage.jsonl").read_text().splitlines()
    assert len(usage) == 1 and json.loads(usage[0])["input_tokens"] == 3
    assert _status(tmp_path)["state"] == "idle"


def test_writes_code_picks_opus_and_cwd_overrides_the_kit_root(rec, tmp_path):
    work = tmp_path / "wt"
    fleet_route.spawn("T", caller="t", writes_code=True, cwd=work, root=tmp_path)
    (argv, kw), = rec.calls
    assert argv[argv.index("--model") + 1] == "opus"
    assert kw["cwd"] == str(work)
    # the budget stays in the kit root, never in the child's cwd
    assert (tmp_path / "ops/loop/control/headless_budget.json").is_file()
    assert not (work / "ops").exists()


def test_rc_gate_refusal_starts_nothing(rec, tmp_path, monkeypatch):
    monkeypatch.setattr(he, "_read_user_var", lambda name: None)
    monkeypatch.setattr(he, "REFUSAL_LOG", tmp_path / "r.log")
    with pytest.raises(fleet_route.RouteRefused) as ei:
        fleet_route.spawn("T", caller="t-unset", root=tmp_path)
    assert ei.value.reason == "unset"
    assert rec.calls == []
    assert not (tmp_path / "ops/loop/control/headless_budget.json").exists()
    assert '"caller": "t-unset"' in (tmp_path / "r.log").read_text(encoding="utf-8")


def test_kit_refusal_starts_nothing_and_is_logged(rec, tmp_path, monkeypatch):
    # RC's gate accepts https; the kit is stricter and refuses it. The stricter
    # of the two wins, and the refusal is logged by RC's gate log.
    monkeypatch.setattr(he, "_read_user_var", lambda name: "https://127.0.0.1:65530")
    monkeypatch.setattr(he, "REFUSAL_LOG", tmp_path / "r.log")
    with pytest.raises(fleet_route.RouteRefused) as ei:
        fleet_route.spawn("T", caller="t-kit", root=tmp_path)
    assert ei.value.reason == "kit" and "plain http" in str(ei.value)
    assert rec.calls == []
    assert '"reason": "kit"' in (tmp_path / "r.log").read_text(encoding="utf-8")


def test_kit_probe_uses_rc_probe(rec, tmp_path, monkeypatch):
    seen = []

    def _probe(host, port, timeout):
        seen.append((host, port))
        return None if len(seen) == 1 else "ConnectionRefusedError"

    monkeypatch.setattr(he, "_probe", _probe)
    monkeypatch.setattr(he, "REFUSAL_LOG", tmp_path / "r.log")
    with pytest.raises(fleet_route.RouteRefused) as ei:
        fleet_route.spawn("T", caller="t", root=tmp_path)
    # gate probe passed, the kit's probe went through the same RC probe and failed
    assert seen == [("127.0.0.1", 65530), ("127.0.0.1", 65530)]
    assert "proxy unreachable" in str(ei.value)
    assert rec.calls == []


def test_budget_exhausted_refuses(rec, tmp_path):
    k = fleet_route.kit()
    path = tmp_path / k.BUDGET_REL
    path.parent.mkdir(parents=True)
    import time
    path.write_text(json.dumps({"starts": [time.time()] * k.RUNS_CAP}), encoding="ascii")
    with pytest.raises(fleet_route.RouteRefused) as ei:
        fleet_route.spawn("T", caller="t", root=tmp_path)
    assert "budget exhausted" in str(ei.value)
    assert rec.calls == []
    assert _status(tmp_path)["state"] == "limit"


def test_timeout_leaves_status_idle_and_reraises(tmp_path, monkeypatch):
    r = _Rec(raise_exc=subprocess.TimeoutExpired("claude", 1))
    monkeypatch.setattr(subprocess, "run", r)
    with pytest.raises(subprocess.TimeoutExpired):
        fleet_route.spawn("T", caller="t", root=tmp_path)
    assert _status(tmp_path)["state"] == "idle"


def test_timeout_is_recorded_by_the_kit_before_the_reraise(tmp_path, monkeypatch):
    """FLEET-KIT-v4 defect 5: the kit itself writes a usage line with rc null and
    error "timeout"; RC still re-raises TimeoutExpired for its callers."""
    r = _Rec(raise_exc=subprocess.TimeoutExpired("claude", 1))
    monkeypatch.setattr(subprocess, "run", r)
    with pytest.raises(subprocess.TimeoutExpired):
        fleet_route.spawn("T", caller="t", note="n", root=tmp_path)
    usage = (tmp_path / "ops/loop/control/headless_usage.jsonl").read_text().splitlines()
    assert len(usage) == 1
    rec_line = json.loads(usage[0])
    assert rec_line["error"] == "timeout" and rec_line["rc"] is None


def test_write_idle_names_the_next_tick(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet_route, "ROOT", tmp_path)
    fleet_route.write_idle(300)
    st = _status(tmp_path)
    assert st["state"] == "idle" and st["task"] == "Idle" and st["code"] == "RC"
    assert st["next_tick"] is not None


def test_write_idle_never_raises(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="ascii")
    monkeypatch.setattr(fleet_route, "ROOT", blocker)  # a FILE where a dir must go
    fleet_route.write_idle(300)


def test_cli_prints_result_and_returns_child_rc(rec, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fleet_route, "ROOT", tmp_path)
    pf = tmp_path / "p.txt"
    pf.write_text("PROMPT", encoding="ascii")
    rc = fleet_route.main(["--caller", "cli", "--prompt-file", str(pf), "--writes-code",
                           "--", "--allowedTools", "Read"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "done"
    (argv, _kw), = rec.calls
    assert argv[2] == "PROMPT" and argv[-2:] == ["--allowedTools", "Read"]
    assert argv[argv.index("--model") + 1] == "opus"


def test_cli_refusal_exits_3(rec, tmp_path, monkeypatch):
    monkeypatch.setattr(fleet_route, "ROOT", tmp_path)
    monkeypatch.setattr(he, "_read_user_var", lambda name: None)
    monkeypatch.setattr(he, "REFUSAL_LOG", tmp_path / "r.log")
    assert fleet_route.main(["--caller", "cli", "--prompt", "x"]) == fleet_route.EXIT_REFUSED
    assert rec.calls == []


def test_cli_usage_error(capsys):
    assert fleet_route.main(["--prompt", "x"]) == 2


# ---------------------------------------------------------------------------
# MAIN 1327 item 1.1: the routed paths launch through the KIT's own process
# launch (`fleet_headless._run`), so a timeout kills the whole process tree and
# the kit's timeout status applies. tests/conftest.py points `_launch` at a
# subprocess.run forwarder so caller-shape tests keep stubbing subprocess.run;
# the tests below put the production default back and fake only Popen and the
# taskkill call, so nothing real starts.
# ---------------------------------------------------------------------------


class _FakePopen:
    """Just enough Popen for the kit's `_run`: a context manager whose
    communicate either answers or times out once, then answers the reap."""

    instances: list = []
    hang = False

    def __init__(self, argv, stdin=None, **kw):
        self.argv, self.stdin_arg, self.kw = list(argv), stdin, kw
        self.pid = 4242
        self.returncode = None
        self.killed = False
        self.inputs = []
        _FakePopen.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def communicate(self, input=None, timeout=None):
        self.inputs.append(input)
        if self.hang and len(self.inputs) == 1:
            raise subprocess.TimeoutExpired(self.argv, timeout)
        self.returncode = -9 if self.killed else 0
        return ('{"result": "ok"}', "")

    def kill(self):
        self.killed = True


@pytest.fixture
def kit_launch(monkeypatch):
    """Production launcher (the kit's `_run`) with Popen and taskkill faked."""
    monkeypatch.setattr(fleet_route, "_launch", None)
    _FakePopen.instances = []
    _FakePopen.hang = False
    monkeypatch.setattr(subprocess, "Popen", _FakePopen)
    taskkills = []

    def _run(argv, **kw):
        taskkills.append(list(argv))
        return CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)
    return taskkills


def test_default_launcher_is_the_kits_own_run(kit_launch, tmp_path):
    line, proc = fleet_route.spawn("TASK", caller="t", root=tmp_path)
    (p,) = _FakePopen.instances
    assert p.argv[:3] == ["claude-fake.exe", "-p", "TASK"]
    # no body: the kit's launch closes stdin (DEVNULL), it is never inherited
    assert p.stdin_arg == subprocess.DEVNULL and p.inputs == [None]
    assert line["rc"] == 0 and proc.stdout == '{"result": "ok"}'
    assert kit_launch == [], "no taskkill on a clean run"


def test_body_rides_stdin_beside_the_argv_instruction(kit_launch, tmp_path):
    fleet_route.spawn("INST", caller="t", stdin="BODY", root=tmp_path)
    (p,) = _FakePopen.instances
    assert p.argv[2] == "INST", "the short instruction stays on argv"
    assert "BODY" not in p.argv
    assert p.stdin_arg == subprocess.PIPE and p.inputs == ["BODY"]


def test_timeout_kills_the_process_tree_through_the_kit(kit_launch, tmp_path):
    _FakePopen.hang = True
    with pytest.raises(subprocess.TimeoutExpired):
        fleet_route.spawn("T", caller="t", note="n", timeout=1, root=tmp_path)
    (p,) = _FakePopen.instances
    (tk,) = kit_launch
    assert tk[0].lower().endswith("taskkill.exe") or tk[0].lower().endswith("taskkill")
    assert tk[1:] == ["/T", "/F", "/PID", "4242"], "the WHOLE tree, by pid"
    assert p.killed is True
    usage = (tmp_path / "ops/loop/control/headless_usage.jsonl").read_text().splitlines()
    rec_line = json.loads(usage[-1])
    assert rec_line["error"] == "timeout" and rec_line["rc"] is None
    assert _status(tmp_path)["state"] == "idle"


def test_rc_gate_refusal_reaches_no_popen(kit_launch, tmp_path, monkeypatch):
    monkeypatch.setattr(he, "_read_user_var", lambda name: None)
    monkeypatch.setattr(he, "REFUSAL_LOG", tmp_path / "r.log")
    with pytest.raises(fleet_route.RouteRefused):
        fleet_route.spawn("T", caller="t-unset", stdin="BODY", root=tmp_path)
    assert _FakePopen.instances == [] and kit_launch == []
    assert not (tmp_path / "ops/loop/control/headless_budget.json").exists()


def test_kit_without_a_launcher_refuses_before_counting(kit_launch, tmp_path, monkeypatch):
    k = fleet_route.kit()
    monkeypatch.delattr(k, "_run")
    with pytest.raises(fleet_route.RouteRefused) as ei:
        fleet_route.spawn("T", caller="t", root=tmp_path)
    assert ei.value.reason == "kit"
    assert _FakePopen.instances == []
    assert not (tmp_path / "ops/loop/control/headless_budget.json").exists()
