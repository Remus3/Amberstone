"""F1 P1+P2: the executor seam (ops/loop/executor.py).

The ahk channel is a REFACTOR ONLY, so the tests that matter most here are the
byte-equality ones: directive_payload must produce exactly what the controller
used to inline, because the AHK bridge skips line 1 and types line 2 as a slash
command. A shape change there does not crash - it silently types `/clear` as
prose, which is a scar this channel already carries.

The sdk channel is new behavior, so it is tested against a stub `claude` that
prints a real result envelope on stdout.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "rc_loop_executor_under_test", ROOT / "ops" / "loop" / "executor.py")
executor = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = executor
_spec.loader.exec_module(executor)


# ---- byte-equality with the pre-seam inline strings -------------------------

def test_director_payload_is_byte_identical_to_the_inline_original():
    assert executor.directive_payload(3, "ignored body", "director") == (
        "CYCLE=3\n/clear\n"
        "/gemini-headless-upgrade and Read the file ops/loop/control/directive.md and fully execute it now. "
        "No questions; auto-pick the recommended option and proceed."
    )


def test_cycle_command_and_fixed_type_the_body_verbatim():
    assert executor.directive_payload(1, "/RC2-Continue", "cycle_command") == \
        "CYCLE=1\n/clear\n/RC2-Continue"
    assert executor.directive_payload(9, "noop", "fixed") == "CYCLE=9\n/clear\nnoop"


def test_clear_each_cycle_false_drops_the_clear_line_only():
    assert executor.directive_payload(2, "x", "fixed", clear_each_cycle=False) == \
        "CYCLE=2\nx"


def test_cycle_header_is_always_the_first_line():
    """The AHK bridge skips line 1; a body on line 1 would never be typed."""
    for src in ("director", "cycle_command", "fixed"):
        assert executor.directive_payload(7, "b", src).splitlines()[0] == "CYCLE=7"


# ---- channel dispatch -------------------------------------------------------

def _deps():
    return dict(log=lambda m: None, stop=lambda m: None, awrite=lambda p, t: None,
                wait_for=lambda *a, **k: True, wait_gone=lambda *a, **k: True,
                rjson=lambda p, d=None: d, stall_action=lambda n: "stop",
                stall_recovery_directive=lambda c: "")


def test_build_defaults_to_ahk(tmp_path: Path):
    assert executor.build({}, tmp_path, **_deps()).name == "ahk"


def test_build_selects_sdk(tmp_path: Path):
    assert executor.build({"channel": "sdk"}, tmp_path, **_deps()).name == "sdk"


def test_unknown_channel_fails_loud_rather_than_falling_back(tmp_path: Path):
    """A typo must not quietly run the singleton channel during a concurrent run."""
    with pytest.raises(ValueError, match="unknown executor channel"):
        executor.build({"channel": "skd"}, tmp_path, **_deps())


# ---- ahk channel ------------------------------------------------------------

class _Rec:
    """Minimal controller-shaped dependency recorder."""

    def __init__(self, ctl: Path, done: dict):
        self.ctl = ctl
        self.done = done
        self.written: dict = {}
        self.logs: list = []
        self.stopped: list = []

    def deps(self):
        return dict(
            log=self.logs.append,
            stop=self.stopped.append,
            awrite=lambda p, t: self.written.__setitem__(Path(p).name, t),
            wait_for=lambda p, d, watch_bridge=False: True,
            wait_gone=lambda p, d: True,
            rjson=lambda p, d=None: self.done,
            stall_action=lambda n: "stop",
            stall_recovery_directive=lambda c: f"recover {c}")


def test_ahk_run_writes_the_payload_and_maps_the_done_record(tmp_path: Path):
    r = _Rec(tmp_path, {"sha": "a" * 40, "tests_pass": "13061",
                        "regressions": False, "summary": "ok"})
    ex = executor.build({"channel": "ahk", "cycle_deadline_sec": 5}, tmp_path, **r.deps())
    rec = ex.run(4, "body", "fixed")
    assert r.written["gemini.ready"] == "CYCLE=4\n/clear\nbody"
    assert rec.sha == "a" * 40
    assert rec.tests_pass == "13061"
    assert rec.regressions is False
    assert rec.raw == r.done
    # the ahk channel returns no receipt - this is why the controller still scrapes
    assert rec.cost_usd == 0.0 and rec.session_id is None


def test_ahk_stops_when_the_bridge_never_types(tmp_path: Path):
    r = _Rec(tmp_path, {})
    deps = r.deps()
    deps["wait_gone"] = lambda p, d: False
    ex = executor.build({"channel": "ahk", "cycle_deadline_sec": 5}, tmp_path, **deps)
    ex.run(2, "body", "fixed")
    assert r.stopped and "never typed" in r.stopped[0]


def test_ahk_passes_watch_bridge_to_the_done_wait(tmp_path: Path):
    """RC-specific: the deadline wait watches the AHK heartbeat, LW's does not."""
    seen = {}
    r = _Rec(tmp_path, {"sha": "b" * 40})
    deps = r.deps()

    def wait_for(p, d, watch_bridge=False):
        seen["watch_bridge"] = watch_bridge
        return True

    deps["wait_for"] = wait_for
    executor.build({"channel": "ahk", "cycle_deadline_sec": 5}, tmp_path, **deps).run(
        1, "b", "fixed")
    assert seen["watch_bridge"] is True


def test_ahk_stall_recovery_reinjects_then_stops_on_the_second_breach(tmp_path: Path):
    r = _Rec(tmp_path, {"sha": "c" * 40})
    deps = r.deps()
    breaches = {"n": 0}

    def wait_for(p, d, watch_bridge=False):
        breaches["n"] += 1
        return breaches["n"] > 2  # miss twice, then land

    deps["wait_for"] = wait_for
    deps["stall_action"] = lambda n: "stop" if n >= 2 else "recover"
    ex = executor.build({"channel": "ahk", "cycle_deadline_sec": 5}, tmp_path, **deps)
    ex.run(6, "body", "fixed")
    assert r.written["gemini.ready"] == "recover 6", "the recovery directive should be re-typed"
    assert r.stopped and "hard hang" in r.stopped[0]


# ---- sdk channel ------------------------------------------------------------

def _stub_claude(tmp_path: Path, payload: str, rc: int = 0) -> list:
    """A fake `claude` that prints a fixed envelope and exits."""
    p = tmp_path / "stub_claude.py"
    p.write_text(
        "import sys\n"
        "sys.stdin.read()\n"
        f"sys.stdout.write({payload!r})\n"
        f"sys.exit({rc})\n", encoding="utf-8")
    return [sys.executable, str(p)]


def _sdk(tmp_path: Path, **over):
    cfg = {"channel": "sdk", "repo_root": str(tmp_path), "cycle_deadline_sec": 60}
    cfg.update(over)
    return executor.build(cfg, tmp_path, log=lambda m: None, stop=lambda m: None,
                          awrite=lambda p, t: None)


def test_sdk_argv_carries_schema_model_and_budget(tmp_path: Path):
    argv = _sdk(tmp_path, executor_cmd="claude.cmd", executor_model="claude-opus-5",
                cycle_budget_usd=25.0).build_argv(1)
    assert argv[0] == "claude.cmd"
    assert "-p" in argv and "--output-format" in argv
    assert argv[argv.index("--model") + 1] == "claude-opus-5"
    assert argv[argv.index("--max-budget-usd") + 1] == "25.0"
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert schema["required"] == ["sha", "tests_pass", "regressions", "summary"]


def test_sdk_starts_a_fresh_session_when_clear_each_cycle(tmp_path: Path):
    ex = _sdk(tmp_path, clear_each_cycle=True)
    ex.session_id = "prior"
    assert "--session-id" in ex.build_argv(2) and "--resume" not in ex.build_argv(2)


def test_sdk_resumes_the_session_when_clear_each_cycle_is_off(tmp_path: Path):
    ex = _sdk(tmp_path, clear_each_cycle=False)
    ex.session_id = "prior"
    argv = ex.build_argv(2)
    assert argv[argv.index("--resume") + 1] == "prior"


def test_sdk_returns_the_receipt_the_ahk_channel_never_could(tmp_path: Path):
    payload = json.dumps({
        "total_cost_usd": 0.6583, "session_id": "sess-1", "is_error": False,
        "structured_output": {"sha": "e" * 40, "tests_pass": "13061",
                              "regressions": False, "summary": "did the thing"}})
    rec = _sdk(tmp_path, executor_cmd=_stub_claude(tmp_path, payload)).run(1, "b", "fixed")
    assert rec.error is None
    assert rec.sha == "e" * 40
    assert rec.tests_pass == "13061"
    assert rec.cost_usd == 0.6583
    assert rec.session_id == "sess-1"


def test_sdk_missing_structured_output_is_a_failed_cycle_not_an_invented_sha(tmp_path: Path):
    """A fabricated sha would defeat the controller's same-sha no-progress guard."""
    payload = json.dumps({"total_cost_usd": 0.1, "session_id": "s", "is_error": False})
    rec = _sdk(tmp_path, executor_cmd=_stub_claude(tmp_path, payload)).run(1, "b", "fixed")
    assert rec.sha == ""
    assert "structured_output" in rec.error


def test_sdk_incomplete_structured_output_is_rejected(tmp_path: Path):
    payload = json.dumps({"is_error": False, "structured_output": {"sha": "f" * 40}})
    rec = _sdk(tmp_path, executor_cmd=_stub_claude(tmp_path, payload)).run(1, "b", "fixed")
    assert rec.sha == "" and rec.error


def test_sdk_error_envelope_is_surfaced(tmp_path: Path):
    payload = json.dumps({"is_error": True, "result": "credit balance too low",
                          "total_cost_usd": 0.0})
    rec = _sdk(tmp_path, executor_cmd=_stub_claude(tmp_path, payload)).run(1, "b", "fixed")
    assert rec.error == "credit balance too low"


def test_sdk_unparseable_stdout_is_a_failed_cycle(tmp_path: Path):
    rec = _sdk(tmp_path, executor_cmd=_stub_claude(tmp_path, "not json at all")).run(
        1, "b", "fixed")
    assert "unparseable" in rec.error


def test_sdk_nonzero_exit_is_a_failed_cycle(tmp_path: Path):
    payload = json.dumps({"is_error": False, "result": "boom"})
    rec = _sdk(tmp_path, executor_cmd=_stub_claude(tmp_path, payload, rc=1)).run(
        1, "b", "fixed")
    assert rec.error


def test_sdk_timeout_kills_the_tree_and_fails_the_cycle(tmp_path: Path):
    slow = tmp_path / "slow.py"
    slow.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    t0 = time.time()
    rec = _sdk(tmp_path, executor_cmd=[sys.executable, str(slow)],
               cycle_deadline_sec=2).run(1, "b", "fixed")
    assert "timeout" in rec.error
    assert time.time() - t0 < 45, "the timeout path should not wait out the child"


def test_sdk_prompt_drops_the_clear_and_the_cycle_header(tmp_path: Path):
    """`-p` is already a fresh process; /clear is meaningless and the header is prose."""
    p = executor.sdk_prompt(3, "body", "director")
    assert "/clear" not in p and "CYCLE=" not in p
    assert p.startswith("/gemini-headless-upgrade")
    assert "done_sentinel.py" in p, "the sdk channel returns JSON instead of the sentinel"


# ---- commit gate ------------------------------------------------------------

def test_gate_is_active_in_this_repo():
    """RC installs hooks via scripts/install_hooks.py; a live tree must pass."""
    assert executor.gate_inactive_reason(ROOT) is None


def test_unset_hookspath_is_reported_as_ungated(tmp_path: Path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=60)
    (tmp_path / ".githooks").mkdir()
    reason = executor.gate_inactive_reason(tmp_path)
    assert reason and "core.hooksPath" in reason


def test_a_repo_without_githooks_is_not_this_repos_concern(tmp_path: Path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=60)
    assert executor.gate_inactive_reason(tmp_path) is None


# ---- FINAL STEP: one source of truth per channel ----------------------------

def test_ahk_final_step_is_the_sentinel_command_and_no_json_instruction():
    """The ahk controller blocks on control/claude.done - the sentinel IS the signal."""
    s = executor.final_step_instruction("ahk")
    assert "ops/loop/done_sentinel.py --tests <PASS_COUNT> --regressions <0_or_1>" in s
    assert "do NOT run" not in s
    assert "structured_output" not in s and "output schema" not in s


def test_sdk_final_step_is_the_json_instruction_and_no_sentinel_command():
    s = executor.final_step_instruction("sdk")
    assert "do NOT run ops/loop/done_sentinel.py" in s
    assert "output schema" in s
    assert "--tests <PASS_COUNT>" not in s


def test_final_step_defaults_to_ahk_when_the_channel_is_absent():
    """An older config with no `channel` key must keep the legacy completion step."""
    assert executor.final_step_instruction(None) == executor.AHK_FINAL_STEP
    assert executor.final_step_instruction("") == executor.AHK_FINAL_STEP


def test_final_step_rejects_an_unknown_channel_like_build_does():
    with pytest.raises(ValueError, match="unknown executor channel"):
        executor.final_step_instruction("skd")


def test_ahk_final_step_matches_rc_interpreter_path_not_lws():
    """RC's executor.py is a shape-port, not a byte-copy. Copying LW's string here
    would break RC's ahk rollback path, which only a live dry cycle catches."""
    assert r"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" \
        in executor.AHK_FINAL_STEP
    assert "Sibling-A" not in executor.AHK_FINAL_STEP


def test_sdk_prompt_uses_final_step_instruction_so_it_cannot_drift():
    """Pins the no-drift property: the body and the appended step share one source."""
    assert executor.final_step_instruction("sdk") in executor.sdk_prompt(1, "b", "director")


def test_director_prompt_hardcodes_no_channel_specific_completion_step():
    """Regression guard: re-hardcoding the sentinel here re-opens the defect."""
    text = (ROOT / "ops" / "loop" / "director_prompt.md").read_text(encoding="utf-8")
    assert "{{FINAL_STEP}}" in text, "the placeholder is what the controller substitutes"
    assert "done_sentinel.py --tests" not in text


def test_directive_suffix_names_no_channel_specific_step():
    """LW's config re-introduced the contradiction from directive_suffix after the
    prompt was fixed. RC's must stay channel-neutral."""
    cfg = json.loads((ROOT / "ops" / "loop" / "config.json").read_text(encoding="utf-8"))
    suffix = cfg.get("directive_suffix", "")
    assert "done_sentinel" not in suffix
    assert "FINAL STEP" not in suffix


@pytest.mark.parametrize("channel,present,absent", [
    ("ahk", "done_sentinel.py --tests", "do NOT run"),
    ("sdk", "do NOT run ops/loop/done_sentinel.py", "--tests <PASS_COUNT>"),
])
def test_template_substitution_leaves_no_placeholder_on_either_channel(channel, present, absent):
    tmpl = (ROOT / "ops" / "loop" / "director_prompt.md").read_text(encoding="utf-8")
    out = tmpl.replace("{{FINAL_STEP}}", executor.final_step_instruction(channel))
    assert "{{FINAL_STEP}}" not in out
    assert present in out
    assert absent not in out
