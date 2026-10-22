"""tools/text_first_guard.py - the PreToolUse text-first backstop (MAIN FIX
2026-10-21 1254 item 15, C1b-3 S5).

MAIN's second-machine adoption found the guard's message and escape flag name
RC's own dashboard and runtime dir, useless where those do not exist. The
guard now keeps its deny list, state hint and flag path as constants at the
top, takes per-host overrides from the environment (TEXT_FIRST_STATE_HINT,
TEXT_FIRST_FLAG), and exits 0 silently on any payload it does not recognise -
a payload that is valid JSON but not an object used to crash it with a
traceback (exit 1).

Every case runs the script as Claude Code does: a child process, JSON on
stdin, stdout read back.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "text_first_guard.py"
SCRAPE = "mcp__Windows-MCP__Scrape"
CLIPBOARD = "mcp__computer-use__read_clipboard"


def _load():
    spec = importlib.util.spec_from_file_location("text_first_guard_t", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _run(stdin: str, tmp_path: Path, **env_over: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if k not in ("TEXT_FIRST_STATE_HINT", "TEXT_FIRST_FLAG")}
    # Never let a live escape flag in this checkout decide a test.
    env["TEXT_FIRST_FLAG"] = str(tmp_path / "no-such-flag")
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(env_over)
    return subprocess.run(
        [sys.executable, str(SCRIPT)], input=stdin, cwd=tmp_path, env=env,
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )


def _deny_reason(proc: subprocess.CompletedProcess) -> str:
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert len(lines) == 1, proc.stdout
    out = json.loads(lines[0])
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "deny"
    return hso["permissionDecisionReason"]


@pytest.mark.parametrize("tool", [SCRAPE, CLIPBOARD])
def test_listed_reader_is_denied_with_one_json_line(tool, tmp_path):
    reason = _deny_reason(_run(json.dumps({"tool_name": tool}), tmp_path))
    assert reason.isascii()
    assert "\x1b" not in reason
    assert "\n" not in reason


def test_bom_prefixed_payload_is_still_read(tmp_path):
    # A PowerShell 5.1 pipe prepends a UTF-8 BOM; json.loads rejects it, so an
    # unstripped BOM would turn every deny into a silent allow.
    raw = chr(0xFEFF) + json.dumps({"tool_name": SCRAPE})
    _deny_reason(_run(raw, tmp_path))


def test_unlisted_tool_is_silent(tmp_path):
    proc = _run(json.dumps({"tool_name": "Read"}), tmp_path)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


@pytest.mark.parametrize("raw", ["[]", '"x"', "42", "null", "[1, 2]", "true"])
def test_valid_json_that_is_not_an_object_is_silent(raw, tmp_path):
    proc = _run(raw, tmp_path)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


@pytest.mark.parametrize("raw", ["", "not json", "{", "\ufeff{}"])
def test_unparseable_or_empty_payload_is_silent(raw, tmp_path):
    proc = _run(raw, tmp_path)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


@pytest.mark.parametrize("name", [["x"], 5, None, {"a": 1}])
def test_tool_name_of_the_wrong_type_is_silent(name, tmp_path):
    proc = _run(json.dumps({"tool_name": name}), tmp_path)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


def test_escape_flag_path_comes_from_the_environment(tmp_path):
    flag = tmp_path / "allow.flag"
    flag.write_text("", encoding="ascii")
    proc = _run(json.dumps({"tool_name": SCRAPE}), tmp_path,
                TEXT_FIRST_FLAG=str(flag))
    assert (proc.returncode, proc.stdout) == (0, "")


def test_state_hint_override_replaces_the_rc_dashboard_hint(tmp_path):
    proc = _run(json.dumps({"tool_name": SCRAPE}), tmp_path,
                TEXT_FIRST_STATE_HINT="")
    reason = _deny_reason(proc)
    assert "8888" not in reason
    assert "health.json" not in reason
    assert "Read/Grep" in reason

    proc = _run(json.dumps({"tool_name": SCRAPE}), tmp_path,
                TEXT_FIRST_STATE_HINT="query the local status API")
    assert "query the local status API" in _deny_reason(proc)


def test_parameters_are_constants_at_the_top():
    mod = _load()
    assert set(mod.DENY_TOOLS) == {SCRAPE, CLIPBOARD}
    assert "127.0.0.1:8888" in mod.STATE_HINT
    assert mod.FLAG_REL == "ops/runtime/allow_visual.flag"


def test_default_reason_names_the_default_hint_and_flag(tmp_path):
    reason = _deny_reason(_run(json.dumps({"tool_name": SCRAPE}), tmp_path))
    mod = _load()
    assert mod.STATE_HINT in reason
    assert "TEXT_FIRST_FLAG" in reason or "flag" in reason
