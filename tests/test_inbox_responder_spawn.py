"""The responder's spawn seam - argv, exe resolution, child env, result taxonomy.

WHY THIS EXISTS. The spawn is the one place where a sender-controlled note
reaches a subprocess, so the arms here pin the properties that make that safe
and the ones that make a failure legible.

Three of them are worth naming. The argv tail is asserted against literal
strings spelled out IN THIS FILE rather than imported, so a change to the
module cannot quietly re-bless itself - and the absence of any dollar-cap flag
is asserted, because a cap on a notional Max-subscription figure is what
retired a note in the design this build replaces. `resolve_claude_exe` reads
PATH only from the mapping it is handed, because a scheduled task inherits
MACHINE-scope environment only and a resolver that silently fell back to the
process environment would pass in an interactive dry cycle and fail in the
task. And the `no-structured-output` vs `schema-mismatch` split is asserted
both ways, because collapsing them is how an absent proposal reads as the
reassuring `exhausted` label.

No test here creates a real process. The one arm that drives `real_spawner`
replaces the seam's own spawn call with a recorder and asserts the replacement
happened BEFORE the drive.
"""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import inbox_responder_procs as procs  # noqa: E402
from tools import inbox_responder_spawn as spawn  # noqa: E402

# Spelled out here from literals on purpose: an imported expectation cannot
# fail when the module it is imported from changes.
EXPECTED_FLAGS = [
    "-p",
    "--restricted",
    "--tools",
    "Read,Glob,Grep",
    "--strict-mcp-config",
    "--no-session-persistence",
    "--max-turns",
    "--model",
    "--output-format",
    "json",
    "--json-schema",
    "--system-prompt",
]

EXE_TAIL = Path("node_modules/@anthropic-ai/claude-code/bin/claude.exe")


@dataclass
class StandInConfig:
    """A minimal stand-in for `RunnerConfig`, which lands with the runner slice.

    Field-for-field the section 3 shape, so the "no attribute contains budget"
    census means something here and stays true when the real one arrives.
    """

    claude_exe: Optional[Path] = None
    model: str = "claude-sonnet-4-5"
    max_turns: int = 2
    spawn_timeout_s: int = 120
    export_timeout_s: int = 60
    export_max_bytes: int = 2 * 1024 * 1024 * 1024
    measure_timeout_s: int = 30
    precheck_timeout_s: int = 15
    git_exe: str = "git"
    max_slots: int = 2
    spawn_exe_source: Optional[str] = None


@pytest.fixture
def cfg() -> StandInConfig:
    return StandInConfig()


@pytest.fixture(autouse=True)
def _pin_prompt_constants(monkeypatch):
    """Pin the two prompt-module constants for every arm in this file.

    `tools/inbox_responder_prompt.py` is a parallel slice. The tail must carry
    whatever that module exports, and these arms are about the tail's SHAPE,
    so they pin the two values rather than depending on the other slice.
    """
    monkeypatch.setattr(spawn, "SYSTEM_PROMPT", "SYSTEM-PROMPT-SENTINEL")
    monkeypatch.setattr(spawn, "PROPOSAL_SCHEMA", '{"schema": "sentinel"}')


def _module_source() -> str:
    return (ROOT / "tools" / "inbox_responder_spawn.py").read_text(encoding="utf-8")


def _make_exe(base: Path) -> Path:
    exe = base / EXE_TAIL
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("binary", encoding="utf-8")
    return exe


def _result_json(**overrides) -> str:
    body = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "terminal_reason": "completed",
        "num_turns": 2,
        "duration_ms": 9000,
        "duration_api_ms": 8000,
        "total_cost_usd": 0.0123,
        "usage": {
            "input_tokens": 11,
            "output_tokens": 22,
            "cache_creation_input_tokens": 33,
            "cache_read_input_tokens": 44,
        },
        "permission_denials": [],
        "structured_output": {"actions": [{"kind": "reply"}]},
    }
    body.update(overrides)
    return json.dumps(body)


# --------------------------------------------------------------------------
# CLAUDE_ARGV_TAIL
# --------------------------------------------------------------------------


def test_argv_tail_is_the_literal_read_only_shape(cfg):
    tail = spawn.CLAUDE_ARGV_TAIL(cfg)
    assert tail == [
        "-p",
        "--restricted",
        "--tools",
        "Read,Glob,Grep",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--max-turns",
        str(cfg.max_turns),
        "--model",
        cfg.model,
        "--output-format",
        "json",
        "--json-schema",
        '{"schema": "sentinel"}',
        "--system-prompt",
        "SYSTEM-PROMPT-SENTINEL",
    ]
    for flag in EXPECTED_FLAGS:
        assert flag in tail


def test_argv_tail_carries_no_dollar_cap_and_no_banned_flag(cfg):
    tail = spawn.CLAUDE_ARGV_TAIL(cfg)
    assert not [e for e in tail if e.startswith("--max-budget")]
    assert not [e for e in tail if "budget" in e.lower()]
    assert "--bare" not in tail
    assert "--dangerously-skip-permissions" not in tail


def test_runner_config_shape_carries_no_budget_field(cfg):
    assert not [f.name for f in fields(cfg) if "budget" in f.name.lower()]


def test_max_turns_is_stringified_from_config():
    tail = spawn.CLAUDE_ARGV_TAIL(StandInConfig(max_turns=7, model="model-x"))
    assert tail[tail.index("--max-turns") + 1] == "7"
    assert tail[tail.index("--model") + 1] == "model-x"


# --------------------------------------------------------------------------
# child_env
# --------------------------------------------------------------------------


def test_child_env_pops_the_key_that_is_present_in_the_parent():
    parent = {"ANTHROPIC_API_KEY": "sk-live", "PATH": "C:\\bin", "OTHER": "keep"}
    env = spawn.child_env(parent)
    assert "ANTHROPIC_API_KEY" not in env
    assert env["PATH"] == "C:\\bin"
    assert env["OTHER"] == "keep"
    # The parent mapping is the caller's; the pop is on the copy.
    assert parent["ANTHROPIC_API_KEY"] == "sk-live"


def test_child_env_is_a_copy_and_tolerates_an_absent_key():
    parent = {"PATH": "C:\\bin"}
    env = spawn.child_env(parent)
    assert env == {"PATH": "C:\\bin"}
    env["ADDED"] = "1"
    assert "ADDED" not in parent


def test_child_env_never_reads_the_process_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-process")
    monkeypatch.setenv("RC_RESPONDER_MARKER", "process")
    env = spawn.child_env({"PATH": "C:\\bin"})
    assert env == {"PATH": "C:\\bin"}


# --------------------------------------------------------------------------
# resolve_claude_exe
# --------------------------------------------------------------------------


def test_resolve_prefers_the_configured_exe(tmp_path):
    configured = tmp_path / "configured" / "claude.exe"
    configured.parent.mkdir(parents=True)
    configured.write_text("binary", encoding="utf-8")
    path, source = spawn.resolve_claude_exe(
        StandInConfig(claude_exe=configured), {"PATH": ""}
    )
    assert path == configured
    assert source == "config"


def test_resolve_derives_from_executor_cmd_when_config_is_unset(tmp_path, monkeypatch):
    npm = tmp_path / "npm"
    npm.mkdir()
    (npm / "claude.cmd").write_text("shim", encoding="utf-8")
    exe = _make_exe(npm)
    loop_config = tmp_path / "config.json"
    loop_config.write_text(
        json.dumps({"executor_cmd": str(npm / "claude.cmd")}), encoding="utf-8"
    )
    monkeypatch.setattr(spawn, "LOOP_CONFIG_PATH", loop_config)

    path, source = spawn.resolve_claude_exe(StandInConfig(), {"PATH": ""})
    assert path == exe
    assert source == "executor_cmd"


def test_resolve_falls_through_to_which_over_the_injected_path(tmp_path, monkeypatch):
    npm = tmp_path / "npm"
    npm.mkdir()
    (npm / "claude.cmd").write_text("shim", encoding="utf-8")
    exe = _make_exe(npm)
    missing = tmp_path / "no-such-config.json"
    monkeypatch.setattr(spawn, "LOOP_CONFIG_PATH", missing)
    # The process environment points somewhere useless on purpose.
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))

    path, source = spawn.resolve_claude_exe(StandInConfig(), {"PATH": str(npm)})
    assert path == exe
    assert source == "which"


def test_resolve_reads_path_only_from_the_injected_mapping(tmp_path, monkeypatch):
    npm = tmp_path / "npm"
    npm.mkdir()
    (npm / "claude.cmd").write_text("shim", encoding="utf-8")
    _make_exe(npm)
    monkeypatch.setattr(spawn, "LOOP_CONFIG_PATH", tmp_path / "absent.json")
    # The real binary IS on the process PATH. The injected mapping has none,
    # so resolution must fail: an S4U task inherits MACHINE scope only.
    monkeypatch.setenv("PATH", str(npm))

    assert spawn.resolve_claude_exe(StandInConfig(), {}) == (None, None)
    assert spawn.resolve_claude_exe(StandInConfig(), {"PATH": ""}) == (None, None)


def test_resolve_returns_none_pair_when_nothing_is_found(tmp_path, monkeypatch):
    monkeypatch.setattr(spawn, "LOOP_CONFIG_PATH", tmp_path / "absent.json")
    assert spawn.resolve_claude_exe(StandInConfig(), {"PATH": str(tmp_path)}) == (
        None,
        None,
    )


def test_resolve_ignores_an_executor_cmd_whose_exe_is_missing(tmp_path, monkeypatch):
    npm = tmp_path / "npm"
    npm.mkdir()
    loop_config = tmp_path / "config.json"
    loop_config.write_text(
        json.dumps({"executor_cmd": str(npm / "claude.cmd")}), encoding="utf-8"
    )
    monkeypatch.setattr(spawn, "LOOP_CONFIG_PATH", loop_config)
    assert spawn.resolve_claude_exe(StandInConfig(), {"PATH": ""}) == (None, None)


def test_resolve_survives_an_unreadable_loop_config(tmp_path, monkeypatch):
    loop_config = tmp_path / "config.json"
    loop_config.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(spawn, "LOOP_CONFIG_PATH", loop_config)
    assert spawn.resolve_claude_exe(StandInConfig(), {"PATH": ""}) == (None, None)


def test_resolve_never_returns_a_bare_name(tmp_path, monkeypatch):
    npm = tmp_path / "npm"
    npm.mkdir()
    (npm / "claude.cmd").write_text("shim", encoding="utf-8")
    _make_exe(npm)
    monkeypatch.setattr(spawn, "LOOP_CONFIG_PATH", tmp_path / "absent.json")
    path, _source = spawn.resolve_claude_exe(StandInConfig(), {"PATH": str(npm)})
    assert path is not None
    assert path.is_absolute()
    assert path.name not in {"claude", "claude.cmd", "claude.ps1"}
    assert path.name == "claude.exe"


def test_module_source_never_names_a_bare_claude_argv_zero():
    source = _module_source()
    assert '"claude"' not in source
    assert "'claude'" not in source


# --------------------------------------------------------------------------
# build_request
# --------------------------------------------------------------------------


def test_build_request_puts_the_pre_resolved_exe_at_argv_zero(tmp_path, cfg):
    exe = tmp_path / "claude.exe"
    exe.write_text("binary", encoding="utf-8")
    cfg.claude_exe = exe
    budget = procs.KillBudget(1)
    req = spawn.build_request(
        cfg,
        b"ENVELOPE-BYTES",
        tmp_path / "export",
        budget,
        env={"PATH": "C:\\bin"},
    )
    assert req.argv[0] == str(exe)
    assert req.argv[1:] == spawn.CLAUDE_ARGV_TAIL(cfg)
    assert req.stdin_bytes == b"ENVELOPE-BYTES"
    assert req.cwd == tmp_path / "export"
    assert req.timeout_s == cfg.spawn_timeout_s
    assert req.kill_budget is budget
    assert req.env == {"PATH": "C:\\bin"}


def test_build_request_keeps_the_note_out_of_argv(tmp_path, cfg):
    cfg.claude_exe = tmp_path / "claude.exe"
    token = "Zq7Kx19PmTt4"
    envelope = f"header\nfrom-RSC-{token}.md\n{token}\n".encode()
    req = spawn.build_request(
        cfg, envelope, tmp_path, procs.KillBudget(1), env={"PATH": "C:\\bin"}
    )
    assert token.encode("utf-8") in req.stdin_bytes
    assert not [e for e in req.argv if token in e]
    assert not [e for e in req.argv if token in str(Path(e))]


def test_build_request_encodes_a_str_envelope_with_surrogatepass(tmp_path, cfg):
    cfg.claude_exe = tmp_path / "claude.exe"
    req = spawn.build_request(
        cfg, "plain text\udcff", tmp_path, procs.KillBudget(1), env={}
    )
    assert req.stdin_bytes == "plain text\udcff".encode("utf-8", "surrogatepass")


# --------------------------------------------------------------------------
# parse_result
# --------------------------------------------------------------------------


def test_parse_result_reads_the_measured_field_list():
    parsed = spawn.parse_result(_result_json())
    assert parsed is not None
    assert parsed["type"] == "result"
    assert parsed["subtype"] == "success"
    assert parsed["is_error"] is False
    assert parsed["terminal_reason"] == "completed"
    assert parsed["num_turns"] == 2
    assert parsed["duration_ms"] == 9000
    assert parsed["duration_api_ms"] == 8000
    assert parsed["total_cost_usd"] == pytest.approx(0.0123)
    assert parsed["input_tokens"] == 11
    assert parsed["output_tokens"] == 22
    assert parsed["cache_creation_input_tokens"] == 33
    assert parsed["cache_read_input_tokens"] == 44
    assert parsed["permission_denials"] == 0
    assert parsed["complete"] is True


def test_parse_result_counts_permission_denials_without_recording_them():
    parsed = spawn.parse_result(
        _result_json(permission_denials=[{"tool": "Bash"}, {"tool": "Write"}])
    )
    assert parsed["permission_denials"] == 2


def test_parse_result_reads_api_error_status_as_optional():
    absent = spawn.parse_result(_result_json())
    assert absent["api_error_status"] is None
    assert absent["complete"] is True

    present = spawn.parse_result(_result_json(api_error_status=529))
    assert present["api_error_status"] == 529
    assert present["complete"] is True


def test_parse_result_marks_incomplete_when_a_field_is_missing():
    body = json.loads(_result_json())
    del body["duration_api_ms"]
    parsed = spawn.parse_result(json.dumps(body))
    assert parsed is not None
    assert parsed["duration_api_ms"] is None
    assert parsed["complete"] is False


def test_parse_result_accepts_bytes_and_rejects_non_json():
    assert spawn.parse_result(_result_json().encode("utf-8")) is not None
    assert spawn.parse_result(b"not json at all") is None
    assert spawn.parse_result(b"[1, 2, 3]") is None
    assert spawn.parse_result(b"") is None


def test_parse_result_distinguishes_absent_from_null_structured_output():
    body = json.loads(_result_json())
    del body["structured_output"]
    absent = spawn.parse_result(json.dumps(body))
    assert absent["structured_output_present"] is False
    assert absent["structured_output"] is None

    nulled = spawn.parse_result(_result_json(structured_output=None))
    assert nulled["structured_output_present"] is True
    assert nulled["structured_output"] is None


# --------------------------------------------------------------------------
# spawn_ok taxonomy
# --------------------------------------------------------------------------


def _result(stdout: bytes = b"", **overrides) -> "spawn.SpawnResult":
    kwargs = {
        "exit_code": 0,
        "stdout": stdout,
        "stderr": b"",
        "exc": None,
        "wall_ms": 12,
        "timed_out": False,
        "survived_kill": False,
        "kill_skipped": False,
    }
    kwargs.update(overrides)
    return spawn.SpawnResult(**kwargs)


def test_spawn_ok_accepts_a_clean_result():
    detail, parsed = spawn.spawn_ok(_result(_result_json().encode("utf-8")))
    assert detail is None
    assert parsed["structured_output"] == {"actions": [{"kind": "reply"}]}


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"exc": "FileNotFoundError"}, "exc:FileNotFoundError"),
        ({"timed_out": True}, "timeout"),
        ({"exit_code": 1}, "exit:1"),
        ({"exit_code": None}, "exit:None"),
    ],
)
def test_spawn_ok_files_process_level_faults(overrides, expected):
    detail, _parsed = spawn.spawn_ok(
        _result(_result_json().encode("utf-8"), **overrides)
    )
    assert detail == expected


def test_spawn_ok_files_stdout_oversize_before_parsing():
    oversize = b"x" * (spawn.STDOUT_CAP_BYTES + 1)
    detail, parsed = spawn.spawn_ok(_result(oversize))
    assert detail == "stdout-oversize"
    assert parsed is None


def test_spawn_ok_stdout_cap_is_four_mib():
    assert spawn.STDOUT_CAP_BYTES == 4 * 1024 * 1024


def test_spawn_ok_files_bad_json():
    detail, parsed = spawn.spawn_ok(_result(b"I could not comply."))
    assert detail == "bad-json"
    assert parsed is None


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"is_error": True}, "is_error:success"),
        ({"is_error": True, "subtype": "error_during_execution"},
         "is_error:error_during_execution"),
        ({"subtype": "error_max_turns"}, "is_error:error_max_turns"),
        ({"terminal_reason": "max_turns"}, "terminal:max_turns"),
    ],
)
def test_spawn_ok_files_result_level_faults(overrides, expected):
    detail, parsed = spawn.spawn_ok(
        _result(_result_json(**overrides).encode("utf-8"))
    )
    assert detail == expected
    assert parsed is not None


def test_spawn_ok_absent_structured_output_is_no_structured_output():
    body = json.loads(_result_json())
    del body["structured_output"]
    detail, parsed = spawn.spawn_ok(_result(json.dumps(body).encode("utf-8")))
    assert detail == "no-structured-output"
    assert "exhaust" not in detail
    assert parsed is not None


def test_spawn_ok_null_structured_output_is_no_structured_output():
    detail, _parsed = spawn.spawn_ok(
        _result(_result_json(structured_output=None).encode("utf-8"))
    )
    assert detail == "no-structured-output"


@pytest.mark.parametrize(
    "value",
    [
        [{"kind": "reply"}],
        {"proposal": {"actions": []}},
        {"actions": {"kind": "reply"}},
        {"actions": ["reply"]},
        {"actions": [{"verb": "reply"}]},
        {"actions": [{"kind": 7}]},
        "actions",
    ],
)
def test_spawn_ok_present_but_wrong_shape_is_schema_mismatch(value):
    detail, _parsed = spawn.spawn_ok(
        _result(_result_json(structured_output=value).encode("utf-8"))
    )
    assert detail == "schema-mismatch"


def test_spawn_ok_accepts_an_empty_actions_list_as_a_clean_spawn():
    """`actions == []` is EXHAUSTED, decided one gate later - not a spawn fault."""
    detail, parsed = spawn.spawn_ok(
        _result(_result_json(structured_output={"actions": []}).encode("utf-8"))
    )
    assert detail is None
    assert parsed["structured_output"] == {"actions": []}


def test_spawn_ok_never_reports_binary_not_found():
    """Gate 10 owns that detail: the spawner is not called, so there is no result."""
    detail, _parsed = spawn.spawn_ok(_result(_result_json().encode("utf-8")))
    assert detail != "binary-not-found"


def test_spawn_ok_imports_no_third_party_validator():
    tree = ast.parse(_module_source())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "jsonschema" not in imported


# --------------------------------------------------------------------------
# real_spawner
# --------------------------------------------------------------------------


class _RecordingPopen:
    """Stands in for the seam's own spawn call. Never starts a process."""

    instances: list = []

    def __init__(self, argv, **kwargs):
        self.argv = list(argv)
        self.kwargs = kwargs
        self.pid = 4242
        self.returncode = None
        self.communicate_kwargs = None
        type(self).instances.append(self)

    def communicate(self, **kwargs):
        self.communicate_kwargs = kwargs
        self.returncode = 0
        return (b'{"type": "result"}', b"")


@pytest.fixture
def popen_recorder(monkeypatch):
    _RecordingPopen.instances = []
    monkeypatch.setattr(procs.subprocess, "Popen", _RecordingPopen)
    # The replacement is asserted BEFORE any drive: no arm in this file may
    # reach a real process.
    assert procs.subprocess.Popen is _RecordingPopen
    return _RecordingPopen


def test_real_spawner_routes_through_the_process_seam(tmp_path, cfg, popen_recorder):
    exe = tmp_path / "claude.exe"
    exe.write_text("binary", encoding="utf-8")
    cfg.claude_exe = exe
    cwd = tmp_path / "export"
    cwd.mkdir()
    budget = procs.KillBudget(1)
    req = spawn.build_request(
        cfg, b"ENVELOPE", cwd, budget, env={"PATH": "C:\\bin"}
    )

    assert not popen_recorder.instances
    result = spawn.real_spawner(req)

    assert len(popen_recorder.instances) == 1
    rec = popen_recorder.instances[0]
    assert rec.argv[0] == str(exe)
    assert rec.argv[1:] == spawn.CLAUDE_ARGV_TAIL(cfg)
    assert rec.kwargs["creationflags"] == procs.CREATION_FLAGS
    assert rec.kwargs["cwd"] == str(cwd)
    assert rec.kwargs["env"] == {"PATH": "C:\\bin"}
    assert "ANTHROPIC_API_KEY" not in rec.kwargs["env"]
    assert rec.communicate_kwargs["input"] == b"ENVELOPE"
    assert rec.communicate_kwargs["timeout"] == cfg.spawn_timeout_s
    assert isinstance(result, spawn.SpawnResult)
    assert result.exit_code == 0
    assert result.stdout == b'{"type": "result"}'
    assert result.timed_out is False
    assert result.kill_skipped is False


def test_real_spawner_passes_the_cycle_kill_budget_through(tmp_path, cfg, monkeypatch):
    calls = {}

    def _recording_popen_capture(argv, **kwargs):
        calls["argv"] = list(argv)
        calls.update(kwargs)
        return procs.ProcResult(
            exit_code=0,
            stdout=b"{}",
            stderr=b"",
            timed_out=False,
            survived_kill=False,
            kill_skipped=False,
            wall_ms=5,
            exc=None,
        )

    tripwire = _RecordingPopen
    tripwire.instances = []
    monkeypatch.setattr(procs.subprocess, "Popen", tripwire)
    monkeypatch.setattr(procs, "popen_capture", _recording_popen_capture)
    assert procs.subprocess.Popen is tripwire
    assert procs.popen_capture is _recording_popen_capture

    cfg.claude_exe = tmp_path / "claude.exe"
    budget = procs.KillBudget(1)
    req = spawn.build_request(cfg, b"E", tmp_path, budget, env={})
    spawn.real_spawner(req)

    assert calls["timeout_s"] == cfg.spawn_timeout_s
    assert calls["kill_budget"] is budget
    assert calls["stdin_bytes"] == b"E"
    assert calls["cwd"] == tmp_path
    assert not tripwire.instances


def test_real_spawner_carries_the_seam_fields_onto_the_result(tmp_path, cfg, monkeypatch):
    def _timed_out(argv, **kwargs):
        return procs.ProcResult(
            exit_code=None,
            stdout=b"partial",
            stderr=b"err",
            timed_out=True,
            survived_kill=True,
            kill_skipped=True,
            wall_ms=120000,
            exc=None,
        )

    monkeypatch.setattr(procs, "popen_capture", _timed_out)
    cfg.claude_exe = tmp_path / "claude.exe"
    req = spawn.build_request(cfg, b"E", tmp_path, procs.KillBudget(1), env={})
    result = spawn.real_spawner(req)

    assert result.timed_out is True
    assert result.survived_kill is True
    assert result.kill_skipped is True
    assert result.wall_ms == 120000
    assert result.stdout == b"partial"
    assert result.stderr == b"err"
    assert result.exit_code is None
    assert result.exc is None


# --------------------------------------------------------------------------
# RealSpawnDisabled and the module census
# --------------------------------------------------------------------------


def test_real_spawn_disabled_is_defined_here_and_raised_by_nothing_here():
    assert issubclass(spawn.RealSpawnDisabled, Exception)
    source = _module_source()
    assert "class RealSpawnDisabled" in source
    tree = ast.parse(source)
    raises = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Raise) and ast.dump(node).count("RealSpawnDisabled")
    ]
    assert raises == []


def test_module_contains_no_literal_process_call():
    tree = ast.parse(_module_source())
    offenders = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in {"subprocess", "os"}
        and node.attr in {"Popen", "run", "system", "spawnv", "execv", "popen"}
    ]
    assert offenders == []


def test_spawner_alias_is_exported():
    assert spawn.Spawner is not None
