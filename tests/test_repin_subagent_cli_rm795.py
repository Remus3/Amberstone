"""RM-795 - tools/repin_subagent_cli.py: the CLI pin moves only on a pass.

`tests/test_subagent_prompt_flag.py` `PINNED_CLI` goes red on every CLI
auto-update (two hand re-pins in session 126). The tool runs the four RM-684
controls (unknown option, canary, negative, top-level leak) through the
fleet kit's spawn() via `ops/loop/fleet_route.spawn(log_path=...)`, grades the
stream-json each run wrote, and writes the pin ONLY on a full pass, with the
version the passing runs themselves reported.

Everything here is FAKE: the tool's spawn seam is a function argument that
writes a synthetic stream, and the one fleet_route test fakes the process
launch in the route's and the kit's OWN `subprocess` names
(`tests/_module_view.py`, RM-801), with the conftest's fake route and fake exe.
No test here starts a process or reaches the real CLI.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from subprocess import CompletedProcess

import pytest

from ops.loop import fleet_route
from tests._module_view import bind_subprocess
from tools import repin_subagent_cli as repin

FLAG = "--append-subagent-system-prompt"
VERSION = "2.1.399"

PIN_SOURCE = (
    '"""stand-in for the pin module."""\n'
    "# history comment line\n"
    'PINNED_CLI = "2.1.309"\n'
    'FLAG = "--append-subagent-system-prompt"\n'
)


# ---------------------------------------------------------------- fakes


def _codeword_of(extra):
    if FLAG not in extra:
        return None
    value = extra[list(extra).index(FLAG) + 1]
    return value.split(repin.CANARY_KEY, 1)[1].strip()


def _events(version, *, spawn, answer, sub_tools=0, agent_input="", early=""):
    """A stream-json run shaped like the measured 2.1.305 logs."""
    evs = [{"type": "system", "subtype": "init", "claude_code_version": version}]
    if version is None:
        evs[0].pop("claude_code_version")
    if early:
        evs.append({"type": "assistant", "parent_tool_use_id": None,
                    "message": {"content": [{"type": "text", "text": early}]}})
    if spawn:
        evs.append({"type": "assistant", "parent_tool_use_id": None, "message": {
            "content": [{"type": "tool_use", "id": "toolu_A", "name": "Agent",
                         "input": {"prompt": "inspect your prompt" + agent_input}}]}})
        evs.append({"type": "user", "parent_tool_use_id": "toolu_A", "message": {
            "content": [{"type": "text", "text": "inspect your prompt"}]}})
        for _ in range(sub_tools):
            evs.append({"type": "assistant", "parent_tool_use_id": "toolu_A", "message": {
                "content": [{"type": "tool_use", "id": "toolu_S", "name": "Read",
                             "input": {}}]}})
        evs.append({"type": "system", "subtype": "task_notification",
                    "tool_use_id": "toolu_A", "status": "completed", "summary": answer,
                    "usage": {"tool_uses": sub_tools}})
        evs.append({"type": "user", "parent_tool_use_id": None,
                    "tool_use_result": {"totalToolUseCount": sub_tools},
                    "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_A",
                                             "content": [{"type": "text", "text": answer}]}]}})
    evs.append({"type": "assistant", "parent_tool_use_id": None,
                "message": {"content": [{"type": "text", "text": answer}]}})
    evs.append({"type": "result", "subtype": "success", "is_error": False, "result": answer})
    return evs


def _write(log_path, evs):
    with open(log_path, "w", encoding="utf-8", newline="\n") as fh:
        for ev in evs:
            fh.write(json.dumps(ev) + "\n")


class FakeCli:
    """The tool's spawn seam. Honest by default: the flag reaches the
    subagent and nothing else. `broken` names behaviours to break."""

    def __init__(self, version=VERSION, broken=(), versions=None):
        self.version, self.broken, self.versions = version, set(broken), versions or {}
        self.calls = []

    def __call__(self, prompt, *, note, extra, log_path):
        self.calls.append({"prompt": prompt, "note": note, "extra": list(extra),
                           "log_path": str(log_path)})
        extra = list(extra)
        if "--definitely-not-a-flag" in extra:
            rc = 0 if "unknown_accepted" in self.broken else 1
            open(log_path, "w").close()
            err = "" if rc == 0 else "error: unknown option '--definitely-not-a-flag'\n"
            return ({"rc": rc, "result": None, "error": None},
                    CompletedProcess(args=[], returncode=rc, stdout=None, stderr=err))
        cw = _codeword_of(extra)
        spawning = prompt == repin.SPAWN_PROMPT
        name = "canary" if (spawning and cw) else ("neg" if spawning else "leak")
        version = self.versions.get(name, self.version)
        if name == "leak":
            leaked = "leak" in self.broken
            answer = f"CANARY={cw}" if leaked else "NO-CANARY"
            evs = _events(version, spawn=False, answer=answer)
        elif name == "neg":
            answer = "CANARY=QXOTHER" if "neg_leak" in self.broken else "NO-CANARY"
            evs = _events(version, spawn=True, answer=answer)
        else:
            answer = "NO-CANARY" if "flag_dead" in self.broken else f"CANARY={cw}"
            evs = _events(version, spawn=True, answer=answer)
        _write(log_path, evs)
        return ({"rc": 0, "result": answer, "error": None},
                CompletedProcess(args=[], returncode=0, stdout=None, stderr=""))


def _pin_file(tmp_path, text=PIN_SOURCE):
    p = tmp_path / "test_pin_standin.py"
    p.write_bytes(text.encode("ascii"))
    return p


def _measure(tmp_path, cli=None, controls=repin.CONTROLS, codeword="QXTESTCODE01"):
    cli = cli or FakeCli()
    return repin.measure(tmp_path / "ev", controls=controls, spawn_fn=cli,
                         codeword=codeword), cli


# ---------------------------------------------------------------- grading


def _grade(tmp_path, name, evs, rc=0, stderr="", cw="QXTESTCODE01"):
    log = tmp_path / f"{name}.stream.jsonl"
    _write(log, evs)
    return repin.grade(name, cw, rc, stderr, log)


def test_canary_passes_on_the_measured_shape(tmp_path):
    r = _grade(tmp_path, "canary", _events(VERSION, spawn=True, answer="CANARY=QXTESTCODE01"))
    assert r.passed, r.reasons
    assert r.version == VERSION


def test_canary_fails_when_the_codeword_rides_the_agent_input(tmp_path):
    evs = _events(VERSION, spawn=True, answer="CANARY=QXTESTCODE01",
                  agent_input=" QXTESTCODE01")
    r = _grade(tmp_path, "canary", evs)
    assert not r.passed and any("input" in x for x in r.reasons)


def test_canary_fails_when_the_subagent_used_a_tool(tmp_path):
    evs = _events(VERSION, spawn=True, answer="CANARY=QXTESTCODE01", sub_tools=1)
    r = _grade(tmp_path, "canary", evs)
    assert not r.passed and any("tool" in x for x in r.reasons)


def test_canary_fails_when_the_codeword_is_seen_before_the_subagent_returns(tmp_path):
    evs = _events(VERSION, spawn=True, answer="CANARY=QXTESTCODE01", early="QXTESTCODE01")
    r = _grade(tmp_path, "canary", evs)
    assert not r.passed and any("first" in x for x in r.reasons)


def test_canary_fails_without_a_real_spawn(tmp_path):
    r = _grade(tmp_path, "canary", _events(VERSION, spawn=False, answer="CANARY=QXTESTCODE01"))
    assert not r.passed


def test_canary_fails_when_the_flag_delivered_nothing(tmp_path):
    r = _grade(tmp_path, "canary", _events(VERSION, spawn=True, answer="NO-CANARY"))
    assert not r.passed


def test_negative_control_fails_when_the_codeword_reaches_the_stream(tmp_path):
    ok = _grade(tmp_path, "neg", _events(VERSION, spawn=True, answer="NO-CANARY"))
    assert ok.passed, ok.reasons
    bad = _grade(tmp_path, "neg", _events(VERSION, spawn=True, answer="CANARY=QXTESTCODE01"))
    assert not bad.passed


def test_leak_control_fails_when_the_top_level_reads_its_own_prompt(tmp_path):
    ok = _grade(tmp_path, "leak", _events(VERSION, spawn=False, answer="NO-CANARY"))
    assert ok.passed, ok.reasons
    bad = _grade(tmp_path, "leak", _events(VERSION, spawn=False, answer="CANARY=QXTESTCODE01"))
    assert not bad.passed
    spawned = _grade(tmp_path, "leak", _events(VERSION, spawn=True, answer="NO-CANARY"))
    assert not spawned.passed, "the leak control must not spawn"


def test_unknown_option_control_needs_a_nonzero_exit_and_the_message(tmp_path):
    log = tmp_path / "unknown.stream.jsonl"
    log.write_text("", encoding="ascii")
    ok = repin.grade("unknown", "QX", 1, "error: unknown option '--definitely-not-a-flag'\n", log)
    assert ok.passed, ok.reasons
    assert not repin.grade("unknown", "QX", 0, "", log).passed
    assert not repin.grade("unknown", "QX", 1, "something else\n", log).passed


@pytest.mark.parametrize("version", [None, "2.1", "v2.1.309", "2.1.309 (Claude Code)"])
def test_a_model_run_without_a_clean_version_fails(tmp_path, version):
    r = _grade(tmp_path, "neg", _events(version, spawn=True, answer="NO-CANARY"))
    assert not r.passed


# ---------------------------------------------------------------- measure


def test_measure_runs_every_control_in_order_through_the_spawn_seam(tmp_path):
    m, cli = _measure(tmp_path)
    assert [r.name for r in m.results] == list(repin.CONTROLS)
    assert all(r.passed for r in m.results), [r.reasons for r in m.results]
    assert m.refused is None
    with_flag = [c for c in cli.calls if FLAG in c["extra"]]
    assert len(with_flag) == 2, "the flag rides the canary and the leak control only"
    for call in cli.calls:
        assert call["note"].strip()
        assert "QXTESTCODE01" not in call["prompt"], "the codeword rides the flag only"
        assert os.path.dirname(call["log_path"]) == str(tmp_path / "ev")
    assert (tmp_path / "ev" / "summary.json").is_file()


def test_measure_stops_at_the_first_failed_control(tmp_path):
    m, cli = _measure(tmp_path, FakeCli(broken={"unknown_accepted"}))
    assert [r.name for r in m.results] == ["unknown"] and not m.results[0].passed
    assert len(cli.calls) == 1, "every further run is spend - stop at the first failure"


def test_measure_refuses_an_existing_evidence_dir_before_any_spawn(tmp_path):
    (tmp_path / "ev").mkdir()
    cli = FakeCli()
    with pytest.raises(repin.RepinRefused):
        repin.measure(tmp_path / "ev", spawn_fn=cli)
    assert cli.calls == []


def test_spawn_refusal_is_recorded_with_its_code_and_stops(tmp_path):
    calls = []

    def refusing(prompt, *, note, extra, log_path):
        calls.append(note)
        raise fleet_route.RouteRefused("kit", "run budget exhausted", code="budget-spent")

    m = repin.measure(tmp_path / "ev", spawn_fn=refusing)
    assert m.refused == "budget-spent"
    assert m.results == [] and len(calls) == 1


def test_a_timed_out_run_fails_its_control_and_stops(tmp_path):
    calls = []

    def slow(prompt, *, note, extra, log_path):
        calls.append(note)
        raise subprocess.TimeoutExpired(["x"], 240)

    m = repin.measure(tmp_path / "ev", spawn_fn=slow)
    assert [(r.name, r.passed, r.reasons) for r in m.results] == [("unknown", False, ["timeout"])]
    assert len(calls) == 1 and m.refused is None


def test_a_doctored_stderr_refuses_the_write(tmp_path):
    pin = _pin_file(tmp_path)
    m, _cli = _measure(tmp_path)
    (tmp_path / "ev" / "unknown.stderr.txt").write_text("", encoding="ascii")
    with pytest.raises(repin.RepinRefused):
        repin.write_pin(m, pin_file=pin, today="2026-10-23")
    assert pin.read_bytes() == PIN_SOURCE.encode("ascii")


def test_each_measurement_draws_a_fresh_codeword(tmp_path):
    a = repin.measure(tmp_path / "a", controls=("canary",), spawn_fn=FakeCli())
    b = repin.measure(tmp_path / "b", controls=("canary",), spawn_fn=FakeCli())
    assert a.codeword != b.codeword
    assert re.fullmatch(r"QX[0-9A-F]{10}", a.codeword)


# ---------------------------------------------------------------- write


def test_full_pass_writes_the_measured_version_atomically_ascii_lf(tmp_path):
    pin = _pin_file(tmp_path)
    m, _cli = _measure(tmp_path)
    out = repin.write_pin(m, pin_file=pin, today="2026-10-23")
    assert out == {"old": "2.1.309", "new": VERSION, "changed": True}
    data = pin.read_bytes()
    assert data.isascii() and b"\r" not in data
    text = data.decode("ascii")
    assert f'PINNED_CLI = "{VERSION}"' in text and '"2.1.309"' not in text.split("# RE")[0]
    assert len(re.findall(r'^PINNED_CLI = ', text, re.MULTILINE)) == 1
    assert f"RE-MEASURED 2026-10-23 on {VERSION}" in text
    assert text.startswith(PIN_SOURCE.split("PINNED_CLI")[0]), "nothing above the pin moved"
    assert text.endswith('FLAG = "--append-subagent-system-prompt"\n')
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ev", pin.name], "no tmp left"


@pytest.mark.parametrize("controls", [("unknown", "canary", "neg"), ("canary", "neg")])
def test_write_refused_on_a_partial_measurement(tmp_path, controls):
    pin = _pin_file(tmp_path)
    m, _cli = _measure(tmp_path, controls=controls)
    with pytest.raises(repin.RepinRefused):
        repin.write_pin(m, pin_file=pin, today="2026-10-23")
    assert pin.read_bytes() == PIN_SOURCE.encode("ascii")


@pytest.mark.parametrize("broken", ["unknown_accepted", "flag_dead", "neg_leak", "leak"])
def test_write_refused_on_any_failed_control(tmp_path, broken):
    pin = _pin_file(tmp_path)
    m, _cli = _measure(tmp_path, FakeCli(broken={broken}))
    with pytest.raises(repin.RepinRefused):
        repin.write_pin(m, pin_file=pin, today="2026-10-23")
    assert pin.read_bytes() == PIN_SOURCE.encode("ascii")


def test_write_refused_when_the_model_runs_disagree_on_the_version(tmp_path):
    pin = _pin_file(tmp_path)
    m, _cli = _measure(tmp_path, FakeCli(versions={"leak": "2.1.400"}))
    with pytest.raises(repin.RepinRefused):
        repin.write_pin(m, pin_file=pin, today="2026-10-23")
    assert pin.read_bytes() == PIN_SOURCE.encode("ascii")


def test_write_refused_on_a_measurement_whose_evidence_changed(tmp_path):
    """A pin is written from what THIS run measured: the logs are re-graded at
    write time, so a doctored or swapped evidence file refuses."""
    pin = _pin_file(tmp_path)
    m, _cli = _measure(tmp_path)
    log = tmp_path / "ev" / "neg.stream.jsonl"
    _write(log, _events(VERSION, spawn=True, answer="CANARY=QXTESTCODE01"))
    with pytest.raises(repin.RepinRefused):
        repin.write_pin(m, pin_file=pin, today="2026-10-23")
    assert pin.read_bytes() == PIN_SOURCE.encode("ascii")


@pytest.mark.parametrize("text", [
    PIN_SOURCE.replace('PINNED_CLI = "2.1.309"\n', ""),
    PIN_SOURCE + 'PINNED_CLI = "2.1.309"\n',
    PIN_SOURCE.replace("\n", "\r\n"),
])
def test_write_refused_on_a_target_it_cannot_rewrite_exactly(tmp_path, text):
    pin = _pin_file(tmp_path, text)
    m, _cli = _measure(tmp_path)
    with pytest.raises(repin.RepinRefused):
        repin.write_pin(m, pin_file=pin, today="2026-10-23")
    assert pin.read_bytes() == text.encode("ascii")


def test_write_refused_on_a_non_ascii_target(tmp_path):
    pin = tmp_path / "p.py"
    raw = PIN_SOURCE.replace("history", "hist" + chr(0xF6) + "ry").encode("utf-8")
    pin.write_bytes(raw)
    m, _cli = _measure(tmp_path)
    with pytest.raises(repin.RepinRefused):
        repin.write_pin(m, pin_file=pin, today="2026-10-23")
    assert pin.read_bytes() == raw


def test_a_failed_replace_leaves_the_pin_untouched_and_no_tmp(tmp_path):
    pin = _pin_file(tmp_path)
    m, _cli = _measure(tmp_path)

    def boom(src, dst):
        raise OSError("replace failed")

    with pytest.raises(OSError):
        repin.write_pin(m, pin_file=pin, today="2026-10-23", replace=boom)
    assert pin.read_bytes() == PIN_SOURCE.encode("ascii")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ev", pin.name]


def test_the_same_version_is_not_rewritten(tmp_path):
    pin = _pin_file(tmp_path)
    m, _cli = _measure(tmp_path, FakeCli(version="2.1.309"))
    out = repin.write_pin(m, pin_file=pin, today="2026-10-23")
    assert out == {"old": "2.1.309", "new": "2.1.309", "changed": False}
    assert pin.read_bytes() == PIN_SOURCE.encode("ascii")


# ---------------------------------------------------------------- CLI


@pytest.mark.parametrize("arg", ["--pin", "--version", "--set"])
def test_cli_has_no_way_to_supply_a_version(tmp_path, arg, capsys):
    cli = FakeCli()
    with pytest.raises(SystemExit) as ei:
        repin.main([arg, "9.9.9", "--out", str(tmp_path / "ev")], spawn_fn=cli)
    assert ei.value.code == repin.EXIT_USAGE
    assert cli.calls == []


def test_cli_subset_without_check_is_refused_before_any_spawn(tmp_path, capsys):
    cli = FakeCli()
    rc = repin.main(["--controls", "canary,neg", "--out", str(tmp_path / "ev")],
                    spawn_fn=cli, pin_file=_pin_file(tmp_path))
    assert rc == repin.EXIT_USAGE and cli.calls == []


def test_cli_full_pass_writes_and_a_check_never_writes(tmp_path, capsys):
    pin = _pin_file(tmp_path)
    assert repin.main(["--check", "--out", str(tmp_path / "e1")], spawn_fn=FakeCli(),
                      pin_file=pin) == repin.EXIT_PASS
    assert pin.read_bytes() == PIN_SOURCE.encode("ascii")
    assert repin.main(["--out", str(tmp_path / "e2")], spawn_fn=FakeCli(),
                      pin_file=pin) == repin.EXIT_PASS
    assert f'PINNED_CLI = "{VERSION}"' in pin.read_text(encoding="ascii")
    printed = capsys.readouterr().out
    assert printed.isascii()


def test_cli_failed_control_exits_1_and_writes_nothing(tmp_path, capsys):
    pin = _pin_file(tmp_path)
    rc = repin.main(["--out", str(tmp_path / "ev")], spawn_fn=FakeCli(broken={"flag_dead"}),
                    pin_file=pin)
    assert rc == repin.EXIT_FAILED
    assert pin.read_bytes() == PIN_SOURCE.encode("ascii")


def test_cli_refusal_exits_3_and_names_the_code(tmp_path, capsys):
    def refusing(prompt, *, note, extra, log_path):
        raise fleet_route.RouteRefused("unset", "no route")

    rc = repin.main(["--out", str(tmp_path / "ev")], spawn_fn=refusing,
                    pin_file=_pin_file(tmp_path))
    assert rc == repin.EXIT_REFUSED
    assert "unset" in capsys.readouterr().out


# ---------------------------------------------------------------- real wire


def test_the_real_pin_file_has_exactly_one_line_the_tool_rewrites():
    text = repin.PIN_FILE.read_text(encoding="ascii")
    assert repin.PIN_FILE.name == "test_subagent_prompt_flag.py"
    assert len(repin.PIN_RE.findall(text)) == 1, "an empty match would pass vacuously"
    assert "\r" not in text


def test_the_pin_test_names_the_tool_in_its_failure_message():
    text = repin.PIN_FILE.read_text(encoding="ascii")
    assert "tools/repin_subagent_cli.py" in text.split("def test_cli_version_still_matches")[1]


class _Rec:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw))
        return CompletedProcess(args=argv, returncode=0, stdout=None, stderr="")


@pytest.fixture
def rec(monkeypatch):
    r = _Rec()
    for mod in (fleet_route, fleet_route.kit()):
        bind_subprocess(monkeypatch, mod, run=r)
    return r


def test_default_spawn_streams_through_the_fleet_route(rec, tmp_path):
    log = tmp_path / "x.stream.jsonl"
    line, _proc = repin.default_spawn("P", note="repin-subagent-cli-neg",
                                      extra=(FLAG, "V"), log_path=log)
    (argv, kw), = rec.calls
    assert argv[0] == "claude-fake.exe"
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert argv[argv.index("--effort") + 1] == "low"
    assert argv[-2:] == [FLAG, "V"]
    assert kw["stdout"].name == str(log) and kw["stderr"] == subprocess.PIPE
    assert line["kind"] == "build" and line["note"] == "repin-subagent-cli-neg"


def test_fleet_route_log_path_is_passed_only_when_set(rec, tmp_path, monkeypatch):
    seen = []
    real = fleet_route.kit().spawn

    def _spy(*a, **kw):
        seen.append(kw)
        return real(*a, **kw)

    monkeypatch.setattr(fleet_route, "_kit_spawn", _spy)
    fleet_route.spawn("T", caller="t", root=tmp_path)
    fleet_route.spawn("T", caller="t", root=tmp_path, log_path=str(tmp_path / "s.jsonl"))
    assert "log_path" not in seen[0], "an omitted parameter keeps the old call shape"
    assert seen[1]["log_path"] == str(tmp_path / "s.jsonl")
    (a1, _), (a2, _) = rec.calls
    assert a1[a1.index("--output-format") + 1] == "json"
    assert a2[a2.index("--output-format") + 1] == "stream-json"
