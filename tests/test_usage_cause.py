"""ops/loop/usage_cause.py + its fleet_route hook: MAIN ORDER 2026-11-14 0930 section 3,
"rc 1 cause". When a headless run exits non-zero but its claude result says subtype
success, the usage row's error field carries the first line of the final result text and
the last tool name. The kit's usage writer is vendored and never edited: RC appends the
cause to the child's stderr inside its own `run` seam, and the kit's v27 stderr tail
puts it into the row. The integration test drives the REAL kit through fleet_route."""
from __future__ import annotations

import json
from subprocess import CompletedProcess

import pytest

from ops.loop import fleet_route
from ops.loop import usage_cause as UC
from tests._module_view import bind_subprocess

SUCCESS = {"type": "result", "subtype": "success", "is_error": True,
           "result": "API Error: 500 overloaded\nsecond line",
           "permission_denials": [{"tool_name": "Bash"}, {"tool_name": "Edit"}]}


def test_cause_names_the_first_result_line_and_the_last_tool():
    line = UC.cause(1, SUCCESS, UC.last_tool(SUCCESS))
    assert line == ("rc-cause: rc 1 with result subtype success; result: API Error: 500 "
                    "overloaded; last tool: Edit")


def test_no_cause_for_a_clean_exit_or_another_subtype():
    assert UC.cause(0, SUCCESS, "Edit") is None
    assert UC.cause(None, SUCCESS, "Edit") is None
    assert UC.cause(1, dict(SUCCESS, subtype="error_max_turns"), "Edit") is None
    assert UC.cause(1, None, None) is None


def test_json_output_without_tool_events_says_so():
    res = {"subtype": "success", "result": "done"}
    assert UC.cause(2, res, UC.last_tool(res)).endswith(
        "last tool: unknown (json result names no tool)")


def test_an_empty_result_and_a_non_ascii_result_are_safe():
    assert "result: (empty)" in UC.cause(1, {"subtype": "success", "result": ""}, None)
    text = "  \n caf" + chr(0xE9) + " " + chr(0x2192) + " x"
    got = UC.cause(1, {"subtype": "success", "result": text}, None)
    got.encode("ascii")
    assert "result: caf? ? x" in got


def test_stream_json_log_gives_the_last_tool_use(tmp_path):
    log = tmp_path / "run.jsonl"
    events = [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result"}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "x"}, {"type": "tool_use", "name": "Bash"}]}},
        {"type": "result", "subtype": "success", "result": "ok then failed"},
    ]
    log.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    assert UC.last_tool_from_log(log) == "Bash"
    assert UC.result_from_log(log)["result"] == "ok then failed"


def test_annotate_appends_one_line_to_stderr():
    proc = CompletedProcess(["c"], 1, stdout=json.dumps(SUCCESS), stderr="warn: x\n")
    line = UC.annotate(proc)
    assert proc.stderr == "warn: x\n" + line + "\n"
    proc2 = CompletedProcess(["c"], 1, stdout=json.dumps(SUCCESS), stderr=None)
    UC.annotate(proc2)
    assert proc2.stderr.startswith("rc-cause: ")
    clean = CompletedProcess(["c"], 0, stdout=json.dumps(SUCCESS), stderr="")
    assert UC.annotate(clean) is None and clean.stderr == ""


class _Rec:
    def __init__(self, stdout, rc, stderr=""):
        self.stdout, self.rc, self.stderr = stdout, rc, stderr

    def __call__(self, argv, **kw):
        return CompletedProcess(args=argv, returncode=self.rc, stdout=self.stdout,
                                stderr=self.stderr)


@pytest.mark.parametrize(("rc", "subtype", "want"), [
    (1, "success", True), (0, "success", False), (1, "error_during_execution", False)])
def test_usage_row_error_field_carries_the_cause_through_the_real_kit(
        monkeypatch, tmp_path, rc, subtype, want):
    res = dict(SUCCESS, subtype=subtype)
    rec = _Rec(json.dumps(res), rc, stderr="stderr line\n")
    for mod in (fleet_route, fleet_route.kit()):
        bind_subprocess(monkeypatch, mod, run=rec)
    fleet_route.spawn("TASK", caller="t", note="lane-s144-ds", root=tmp_path)
    rows = (tmp_path / "ops/loop/control/headless_usage.jsonl").read_text(
        encoding="utf-8").splitlines()
    row = json.loads(rows[-1])
    assert row["rc"] == rc and row["subtype"] == subtype
    if want:
        assert row["error"].splitlines()[-1] == (
            "rc-cause: rc 1 with result subtype success; result: API Error: 500 overloaded; "
            "last tool: Edit")
        # Kit v31 (MAIN 2026-11-14 0936, FI-A3): a failed run's "error" reads
        # "<cause>; rc <n>; <detail>", the detail being the v27 stderr tail, and the
        # row gains "cause". The stderr tail (with RC's rc-cause line last) follows
        # the prefix unchanged, so only the first line's prefix is new.
        assert row["error"].splitlines()[0] == f"{row['cause']}; rc 1; stderr line"
    elif rc == 0:
        assert row["error"] is None
    else:
        assert "rc-cause" not in row["error"]


def test_a_fault_in_the_cause_never_fails_the_run(monkeypatch, tmp_path):
    rec = _Rec(json.dumps(SUCCESS), 1)
    for mod in (fleet_route, fleet_route.kit()):
        bind_subprocess(monkeypatch, mod, run=rec)

    def boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(UC, "annotate", boom)
    monkeypatch.setattr(fleet_route, "_usage_cause", lambda: UC)
    line, _proc = fleet_route.spawn("TASK", caller="t", note="n", root=tmp_path)
    assert line["rc"] == 1


# RM-2116: the lanes' default json output names a tool only through a permission
# denial, so a lane run passes a per-run stream-json log (run_lane.ps1 --log-path ->
# fleet_route CLI -> kit log_path=) and the cause line names the last tool_use.
STREAM = [
    {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}]}},
    {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}},
    {"type": "result", "subtype": "success", "is_error": False, "result": "all done"},
]


def _stream_run(rc):
    def run(argv, **kw):
        fh = kw["stdout"]
        fh.write("".join(json.dumps(e) + "\n" for e in STREAM))
        fh.flush()
        return CompletedProcess(args=argv, returncode=rc, stdout=None, stderr="")
    return run


def test_stream_json_run_through_the_real_kit_names_the_last_tool_use(monkeypatch, tmp_path):
    for mod in (fleet_route, fleet_route.kit()):
        bind_subprocess(monkeypatch, mod, run=_stream_run(1))
    log = tmp_path / "logs" / "run.stream.jsonl"
    fleet_route.spawn("TASK", caller="t", note="lane-s144-ds", root=tmp_path,
                      log_path=str(log))
    row = json.loads((tmp_path / "ops/loop/control/headless_usage.jsonl").read_text(
        encoding="utf-8").splitlines()[-1])
    # Kit v31 (FI-A3): the one-line stderr tail now follows "<cause>; rc <n>; ".
    assert row["error"].splitlines()[-1] == (
        f"{row['cause']}; rc 1; "
        "rc-cause: rc 1 with result subtype success; result: all done; last tool: Bash")


def test_route_cli_log_path_reaches_spawn_and_prints_the_result(monkeypatch, tmp_path,
                                                                 capsys):
    log = tmp_path / "run.stream.jsonl"
    log.write_text("".join(json.dumps(e) + "\n" for e in STREAM), encoding="utf-8")
    seen = {}

    def fake_spawn(prompt, **kw):
        seen.update(kw)
        return {"rc": 0}, CompletedProcess(["c"], 0, stdout=None, stderr="")

    monkeypatch.setattr(fleet_route, "spawn", fake_spawn)
    code = fleet_route.main(["--caller", "run_lane", "--prompt", "TASK",
                             "--log-path", str(log)])
    assert code == 0
    assert seen["log_path"] == str(log)
    out = json.loads(capsys.readouterr().out)
    assert out["result"] == "all done" and out["type"] == "result"


def test_route_cli_without_log_path_keeps_json_mode(monkeypatch):
    seen = {}

    def fake_spawn(prompt, **kw):
        seen.update(kw)
        return {"rc": 0}, CompletedProcess(["c"], 0, stdout="{}", stderr="")

    monkeypatch.setattr(fleet_route, "spawn", fake_spawn)
    assert fleet_route.main(["--caller", "t", "--prompt", "TASK"]) == 0
    assert seen.get("log_path") is None
