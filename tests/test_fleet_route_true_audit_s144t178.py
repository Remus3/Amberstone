"""ops/loop/fleet_route.py CLI (`main`) - s144 true-audit cycle 178.

The CLI is the door tools/headless_run.ps1, tools/weekly_hygiene_run.ps1 and
ops/loop/run_lane.ps1 call. Pinned here:

- A result, a child stderr or a refusal detail holding a character the
  stdout / stderr encoding cannot carry never crashes the CLI. Measured: a
  python whose stdout is a pipe writes cp1252 on this box (only run_lane.ps1
  sets PYTHONIOENCODING), so "a<U+2192>b" raised UnicodeEncodeError AFTER the
  run had finished: exit 1, the result lost, a traceback in the log.
- A malformed --timeout / --last is the usage exit 2 before anything starts,
  never a ValueError traceback; a nan, inf, zero or negative timeout is
  refused rather than handed to the kit.
- A token consumed as a flag's VALUE is never also read as a flag
  ("--prompt --prompt-stdin" used to set prompt_on_stdin), a value flag with
  no value, an unknown flag (a typo such as --prompt_stdin used to be ignored
  and the run went ahead without it) and a repeated flag are usage errors.
- An unreadable or non-UTF-8 prompt file is the usage exit 2 with a message
  that quotes none of the file, and a UTF-8 BOM is not sent to the model.
  An empty prompt is the usage exit too (it would still spend a run).
- An empty --cwd / --model / --effort / --kind means "not given".
- A non-string result or a bool rc from the kit never crashes the CLI.

Every test stubs `fleet_route.spawn`, so nothing here starts a process.
"""
from __future__ import annotations

import io
import sys

import pytest

from ops.loop import fleet_route


class _Spawn:
    def __init__(self, line=None, proc=None, exc=None):
        self.line = {"result": "done", "rc": 0} if line is None else line
        self.proc, self.exc = proc, exc
        self.calls = []

    def __call__(self, prompt, **kw):
        self.calls.append((prompt, kw))
        if self.exc is not None:
            raise self.exc
        return self.line, self.proc


class _Proc:
    def __init__(self, stdout="", stderr=""):
        self.stdout, self.stderr = stdout, stderr


@pytest.fixture
def spawn(monkeypatch):
    fake = _Spawn()
    monkeypatch.setattr(fleet_route, "spawn", fake)
    return fake


def _cp1252_streams(monkeypatch):
    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="\n")
    err = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="\n")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    return out, err


def _bytes(stream) -> bytes:
    stream.flush()
    return stream.buffer.getvalue()


# -- output encoding -------------------------------------------------------


def test_a_non_ascii_result_on_a_cp1252_pipe_is_printed_not_a_crash(spawn, monkeypatch):
    spawn.line = {"result": "a\u2192b\u4e2d", "rc": 0}
    out, _err = _cp1252_streams(monkeypatch)
    assert fleet_route.main(["--caller", "c", "--prompt", "x"]) == 0
    assert _bytes(out) == b"a\\u2192b\\u4e2d\n"


def test_a_cp1252_character_still_prints_as_itself(spawn, monkeypatch):
    spawn.line = {"result": "caf\u00e9", "rc": 0}
    out, _err = _cp1252_streams(monkeypatch)
    assert fleet_route.main(["--caller", "c", "--prompt", "x"]) == 0
    assert _bytes(out) == b"caf\xe9\n"


def test_a_non_ascii_child_stderr_is_written_not_a_crash(spawn, monkeypatch):
    spawn.line = {"result": "ok", "rc": 5}
    spawn.proc = _Proc(stderr="warn \u2192 x\n")
    _out, err = _cp1252_streams(monkeypatch)
    assert fleet_route.main(["--caller", "c", "--prompt", "x"]) == 5
    assert _bytes(err) == b"warn \\u2192 x\n"


def test_a_non_ascii_refusal_detail_still_exits_3(spawn, monkeypatch):
    spawn.exc = fleet_route.RouteRefused("kit", "proxy \u2192 down")
    _out, err = _cp1252_streams(monkeypatch)
    assert fleet_route.main(["--caller", "c", "--prompt", "x"]) == fleet_route.EXIT_REFUSED
    assert b"proxy \\u2192 down" in _bytes(err)


# -- numeric options -------------------------------------------------------


@pytest.mark.parametrize("value", ["abc", "nan", "inf", "-inf", "0", "-5", ""])
def test_a_bad_timeout_is_the_usage_exit_and_starts_nothing(spawn, capsys, value):
    assert fleet_route.main(["--caller", "c", "--prompt", "x", "--timeout", value]) == 2
    assert spawn.calls == []
    assert "--timeout" in capsys.readouterr().err


def test_a_good_timeout_reaches_spawn_as_a_float(spawn):
    assert fleet_route.main(["--caller", "c", "--prompt", "x", "--timeout", "90"]) == 0
    assert spawn.calls[0][1]["timeout"] == 90.0


@pytest.mark.parametrize("value", ["x", "1.5", "-1", ""])
def test_a_bad_last_is_the_usage_exit(capsys, value, monkeypatch):
    monkeypatch.setattr(fleet_route, "usage_failures",
                        lambda **kw: pytest.fail("usage_failures must not run"))
    assert fleet_route.main(["--usage-failures", "--last", value]) == 2
    assert "--last" in capsys.readouterr().err


def test_a_good_last_reaches_usage_failures(monkeypatch, capsys, tmp_path):
    seen = {}

    def _uf(root=None, last=300):
        seen.update(root=root, last=last)
        return {"rows": 0}

    monkeypatch.setattr(fleet_route, "usage_failures", _uf)
    assert fleet_route.main(["--usage-failures", "--root", str(tmp_path), "--last", "7"]) == 0
    assert seen == {"root": str(tmp_path), "last": 7}
    assert '"rows": 0' in capsys.readouterr().out


# -- argument parsing ------------------------------------------------------


def test_a_value_that_looks_like_a_flag_is_only_a_value(spawn):
    assert fleet_route.main(["--caller", "c", "--prompt", "--prompt-stdin"]) == 0
    (prompt, kw), = spawn.calls
    assert prompt == "--prompt-stdin" and kw["prompt_on_stdin"] is False


def test_a_note_named_like_a_flag_does_not_set_writes_code(spawn):
    assert fleet_route.main(["--caller", "c", "--note", "--writes-code",
                             "--prompt", "x"]) == 0
    (_prompt, kw), = spawn.calls
    assert kw["note"] == "--writes-code" and kw["writes_code"] is False


def test_a_value_flag_with_no_value_is_the_usage_exit(spawn, capsys):
    assert fleet_route.main(["--caller", "c", "--prompt", "x", "--effort"]) == 2
    assert spawn.calls == []
    assert "--effort" in capsys.readouterr().err


def test_an_unknown_flag_is_the_usage_exit_not_ignored(spawn, capsys):
    assert fleet_route.main(["--caller", "c", "--prompt", "x", "--prompt_stdin"]) == 2
    assert spawn.calls == []
    assert "--prompt_stdin" in capsys.readouterr().err


def test_a_repeated_flag_is_the_usage_exit(spawn):
    assert fleet_route.main(["--caller", "c", "--prompt", "x", "--model", "a",
                             "--model", "b"]) == 2
    assert spawn.calls == []


def test_tokens_after_the_separator_are_extras_never_options(spawn):
    assert fleet_route.main(["--caller", "c", "--prompt", "x", "--",
                             "--writes-code", "--bogus"]) == 0
    (_prompt, kw), = spawn.calls
    assert kw["extra"] == ["--writes-code", "--bogus"] and kw["writes_code"] is False


def test_empty_optional_values_mean_not_given(spawn):
    assert fleet_route.main(["--caller", "c", "--prompt", "x", "--cwd", "",
                             "--model", "", "--effort", "", "--kind", "", "--note", ""]) == 0
    (_prompt, kw), = spawn.calls
    assert kw["cwd"] is None and kw["model"] is None and kw["effort"] is None
    assert kw["kind"] is None and kw["note"] == ""


def test_the_runner_shapes_still_parse(spawn, tmp_path):
    pf = tmp_path / "lane.md"
    pf.write_bytes(b"LANE")
    assert fleet_route.main([
        "--caller", "run_lane", "--note", "lane-x", "--kind", "build", "--writes-code",
        "--model", "opus", "--cwd", str(tmp_path), "--timeout", "21600",
        "--prompt-file", str(pf), "--prompt-stdin", "--effort", "high",
        "--", "--dangerously-skip-permissions"]) == 0
    (prompt, kw), = spawn.calls
    assert prompt == "LANE"
    assert kw == {"caller": "run_lane", "note": "lane-x", "writes_code": True,
                  "extra": ["--dangerously-skip-permissions"], "timeout": 21600.0,
                  "kind": "build", "model": "opus", "effort": "high",
                  "cwd": str(tmp_path), "prompt_on_stdin": True}


# -- prompt file -----------------------------------------------------------


def test_a_missing_prompt_file_is_the_usage_exit(spawn, capsys, tmp_path):
    assert fleet_route.main(["--caller", "c", "--prompt-file",
                             str(tmp_path / "nope.md")]) == 2
    assert spawn.calls == []
    assert "prompt file" in capsys.readouterr().err


def test_a_non_utf8_prompt_file_is_the_usage_exit_and_quotes_none_of_it(spawn, capsys,
                                                                       tmp_path):
    pf = tmp_path / "p.md"
    pf.write_bytes(b"SECRET\xff\xfe")
    assert fleet_route.main(["--caller", "c", "--prompt-file", str(pf)]) == 2
    assert spawn.calls == []
    err = capsys.readouterr().err
    assert "UTF-8" in err and "SECRET" not in err and "0xff" not in err


def test_a_nul_in_the_prompt_path_is_the_usage_exit(spawn):
    assert fleet_route.main(["--caller", "c", "--prompt-file", "a\x00b"]) == 2
    assert spawn.calls == []


@pytest.mark.parametrize("body", [b"", b"  \n", b"\xef\xbb\xbf\n"])
def test_an_empty_prompt_file_is_the_usage_exit(spawn, capsys, tmp_path, body):
    pf = tmp_path / "p.md"
    pf.write_bytes(body)
    assert fleet_route.main(["--caller", "c", "--prompt-file", str(pf)]) == 2
    assert spawn.calls == []
    assert "prompt is empty" in capsys.readouterr().err


def test_an_empty_prompt_argument_is_the_usage_exit(spawn):
    assert fleet_route.main(["--caller", "c", "--prompt", ""]) == 2
    assert spawn.calls == []


def test_a_bom_in_the_prompt_file_is_not_sent(spawn, tmp_path):
    pf = tmp_path / "p.md"
    pf.write_bytes(b"\xef\xbb\xbfPROMPT")
    assert fleet_route.main(["--caller", "c", "--prompt-file", str(pf)]) == 0
    assert spawn.calls[0][0] == "PROMPT"


# -- kit result shapes -----------------------------------------------------


def test_a_non_string_result_is_printed_as_json(spawn, capsys):
    spawn.line = {"result": {"k": 1}, "rc": 0}
    assert fleet_route.main(["--caller", "c", "--prompt", "x"]) == 0
    assert capsys.readouterr().out == '{"k": 1}\n'


def test_a_missing_result_falls_back_to_the_child_stdout(spawn, capsys):
    spawn.line = {"rc": 0}
    spawn.proc = _Proc(stdout="RAW")
    assert fleet_route.main(["--caller", "c", "--prompt", "x"]) == 0
    assert capsys.readouterr().out == "RAW\n"


@pytest.mark.parametrize("rc,want", [(True, 1), (False, 1), (None, 1), ("0", 1), (0, 0), (7, 7)])
def test_only_an_int_rc_is_the_exit_code(spawn, rc, want):
    spawn.line = {"result": "", "rc": rc}
    assert fleet_route.main(["--caller", "c", "--prompt", "x"]) == want
