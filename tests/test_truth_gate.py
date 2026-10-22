"""Tests for tools/truth_gate.py - pure reconciliation logic, no live suite runs."""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.truth_gate import (
    parse_pytest_summary,
    check_file_claims,
    load_claims,
    reconcile,
)


def test_load_claims_tolerates_powershell_bom(tmp_path):
    p = tmp_path / "claims.json"
    p.write_bytes(b'\xef\xbb\xbf{"run_id": "bom", "slices": []}')
    assert load_claims(p)["run_id"] == "bom"


# --- parse_pytest_summary ---

def test_parse_summary_all_passed():
    s = parse_pytest_summary("1397 passed, 2 skipped, 1 xfailed in 61.32s")
    assert s["passed"] == 1397
    assert s["failed"] == 0
    assert s["errors"] == 0
    assert s["skipped"] == 2


def test_parse_summary_failures():
    s = parse_pytest_summary("2 failed, 1395 passed in 60.1s")
    assert s["failed"] == 2
    assert s["passed"] == 1395


def test_parse_summary_error():
    s = parse_pytest_summary("1 error in 0.5s")
    assert s["errors"] == 1
    assert s["passed"] == 0


def test_parse_summary_banner_form():
    s = parse_pytest_summary("==== 5629 passed, 3 warnings in 120.00s ====")
    assert s["passed"] == 5629
    assert s["failed"] == 0


def test_parse_summary_no_tests_ran():
    s = parse_pytest_summary("no tests ran in 0.01s")
    assert s["passed"] == 0
    assert s["no_tests_ran"] is True


def test_parse_summary_takes_last_line(tmp_path):
    text = "FAILED tests/x.py::t - boom\n1 failed, 9 passed in 2.0s\n"
    s = parse_pytest_summary(text)
    assert s["failed"] == 1
    assert s["passed"] == 9


# --- check_file_claims ---

def test_file_claim_missing_path(tmp_path):
    obs = check_file_claims(
        [{"path": str(tmp_path / "ghost.py"), "must_contain": []}]
    )
    assert obs[0]["exists"] is False


def test_file_claim_content_hit_and_miss(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("def real_method():\n    return 1\n", encoding="utf-8")
    obs = check_file_claims(
        [{"path": str(f), "must_contain": ["real_method", "phantom_field"]}]
    )
    assert obs[0]["exists"] is True
    assert obs[0]["missing_snippets"] == ["phantom_field"]


def test_file_claim_all_present(tmp_path):
    f = tmp_path / "ok.py"
    f.write_text("alpha beta\n", encoding="utf-8")
    obs = check_file_claims([{"path": str(f), "must_contain": ["alpha"]}])
    assert obs[0]["missing_snippets"] == []


# --- reconcile ---

def _claims(**over):
    base = {
        "run_id": "t",
        "slices": [
            {
                "id": "S1",
                "claim": "did thing",
                "files": [{"path": "x.py", "must_contain": ["y"]}],
                "claimed_passed": 10,
                "claimed_failed": 0,
            }
        ],
    }
    base.update(over)
    return base


def _green_suite():
    return {"passed": 10, "failed": 0, "errors": 0, "skipped": 0,
            "no_tests_ran": False, "exit_code": 0, "cmd": "py -m pytest -q"}


def _ok_files():
    return [{"path": "x.py", "exists": True, "missing_snippets": []}]


def test_reconcile_all_confirm_proceeds():
    rep = reconcile(_claims(), _green_suite(), {"S1": _ok_files()},
                    git_obs={"clean": True, "head": "abc"}, ci_obs={"status": "success"})
    assert rep["verdict"] == "PROCEED"
    assert rep["slices"][0]["verdict"] == "CONFIRM"
    assert rep["quarantined"] == []


def test_reconcile_missing_file_quarantines():
    files = [{"path": "x.py", "exists": False, "missing_snippets": []}]
    rep = reconcile(_claims(), _green_suite(), {"S1": files},
                    git_obs={"clean": True, "head": "abc"}, ci_obs={"status": "success"})
    assert rep["verdict"] == "REFUSE"
    assert rep["slices"][0]["verdict"] == "QUARANTINE"
    assert "S1" in rep["quarantined"]


def test_reconcile_missing_snippet_quarantines():
    files = [{"path": "x.py", "exists": True, "missing_snippets": ["y"]}]
    rep = reconcile(_claims(), _green_suite(), {"S1": files},
                    git_obs={"clean": True, "head": "abc"}, ci_obs={"status": "success"})
    assert rep["verdict"] == "REFUSE"


def test_reconcile_count_mismatch_quarantines():
    suite = dict(_green_suite(), passed=9)
    rep = reconcile(_claims(), suite, {"S1": _ok_files()},
                    git_obs={"clean": True, "head": "abc"}, ci_obs={"status": "success"})
    assert rep["slices"][0]["verdict"] == "QUARANTINE"
    assert any("claimed_passed" in d for d in rep["slices"][0]["discrepancies"])


def test_reconcile_suite_failures_refuse_even_if_slices_confirm():
    claims = _claims()
    claims["slices"][0]["claimed_passed"] = None  # slice makes no count claim
    suite = dict(_green_suite(), failed=2, exit_code=1)
    rep = reconcile(claims, suite, {"S1": _ok_files()},
                    git_obs={"clean": True, "head": "abc"}, ci_obs={"status": "success"})
    assert rep["verdict"] == "REFUSE"


def test_reconcile_ci_failure_refuses():
    rep = reconcile(_claims(), _green_suite(), {"S1": _ok_files()},
                    git_obs={"clean": True, "head": "abc"},
                    ci_obs={"status": "failure"})
    assert rep["verdict"] == "REFUSE"
    assert any("ci" in d.lower() for d in rep["global_discrepancies"])


def test_reconcile_ci_unavailable_is_warning_not_refusal():
    rep = reconcile(_claims(), _green_suite(), {"S1": _ok_files()},
                    git_obs={"clean": True, "head": "abc"},
                    ci_obs={"status": "unavailable"})
    assert rep["verdict"] == "PROCEED"


def test_reconcile_report_is_json_serializable():
    rep = reconcile(_claims(), _green_suite(), {"S1": _ok_files()},
                    git_obs={"clean": True, "head": "abc"}, ci_obs={"status": "success"})
    json.dumps(rep)


def test_default_suite_cmd_interpreter_has_pytest():
    """Regression: 'py -m pytest' resolved to a pytest-less interpreter
    (pythoncore-3.14-64) and zeroed the suite -> blanket REFUSE. The default
    suite command must point at an interpreter that can import pytest."""
    import shlex
    import subprocess
    from tools import truth_gate
    exe = shlex.split(truth_gate.DEFAULT_SUITE_CMD.replace("\\", "/"))[0]
    probe = subprocess.run([exe, "-c", "import pytest"], capture_output=True)
    assert probe.returncode == 0, (
        f"DEFAULT_SUITE_CMD interpreter {exe!r} cannot import pytest: "
        f"{probe.stderr.decode(errors='replace')}")


# --- RM-757: claim commands run without a shell; only whole suites are gated ---

_ECHO = ("import json, sys\n"
         "print('ARGV=' + json.dumps(sys.argv[1:]))\n")


def _echo_script(folder):
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "echo_args.py"
    script.write_text(_ECHO, encoding="utf-8")
    return script


def _argv_from(out_file):
    for line in Path(out_file).read_text(encoding="utf-8").splitlines():
        if line.startswith("ARGV="):
            return json.loads(line[len("ARGV="):])
    raise AssertionError("echo script printed no ARGV line")


def test_shell_metacharacters_reach_the_child_as_literal_args(tmp_path):
    from tools.truth_gate import run_suite_fresh
    script = _echo_script(tmp_path / "s")
    out = tmp_path / "out.txt"
    cmd = f'"{sys.executable}" "{script}" a & b | c ; d'
    obs = run_suite_fresh(cmd, out)
    assert obs["exit_code"] == 0
    assert _argv_from(out) == ["a", "&", "b", "|", "c", ";", "d"]


def test_quoted_script_path_with_a_space_runs(tmp_path):
    from tools.truth_gate import run_suite_fresh
    script = _echo_script(tmp_path / "dir with space")
    out = tmp_path / "out.txt"
    obs = run_suite_fresh(f'"{sys.executable}" "{script}" x', out)
    assert obs["exit_code"] == 0
    assert _argv_from(out) == ["x"]


def test_list_command_runs_as_given(tmp_path):
    from tools.truth_gate import run_suite_fresh
    script = _echo_script(tmp_path / "s")
    out = tmp_path / "out.txt"
    obs = run_suite_fresh([sys.executable, str(script), "a b", "%NOPE%", "&"], out)
    assert obs["exit_code"] == 0
    assert _argv_from(out) == ["a b", "%NOPE%", "&"]


def test_split_cmd_list_is_returned_as_given():
    from tools.truth_gate import split_cmd
    assert split_cmd(["a", "b c", "%X%"]) == ["a", "b c", "%X%"]


@pytest.mark.skipif(os.name != "nt", reason="%VAR% expansion is Windows-only")
def test_split_cmd_expands_percent_var_tokens(monkeypatch):
    from tools.truth_gate import split_cmd
    monkeypatch.setenv("RC_TG_RM757_DIR", r"C:\some dir")
    argv = split_cmd(r'"%RC_TG_RM757_DIR%/python.exe" -m pytest tests/ -q')
    assert argv == [r"C:\some dir/python.exe", "-m", "pytest", "tests/", "-q"]


def test_split_cmd_expands_dollar_var_tokens(monkeypatch):
    from tools.truth_gate import split_cmd
    monkeypatch.setenv("RC_TG_RM757_PY", "pyexe")
    assert split_cmd("$RC_TG_RM757_PY -m pytest -q") == ["pyexe", "-m", "pytest", "-q"]


def test_whole_suite_argv_is_prefixed_by_the_gate():
    from tools.truth_gate import GATE_SCRIPT, gate_argv
    argv = [sys.executable, "-m", "pytest", "-q"]
    assert gate_argv(argv, "o.1") == [sys.executable, str(GATE_SCRIPT), "run",
                                      "--owner", "o.1", "--", *argv]


def test_directory_argv_counts_as_a_whole_suite():
    from tools.truth_gate import gate_argv
    gated = gate_argv(["pytest", "tests/", "-q"], "o.1")
    assert gated[2:6] == ["run", "--owner", "o.1", "--"]
    assert gated[6:] == ["pytest", "tests/", "-q"]


def test_single_file_argv_is_not_gated():
    from tools.truth_gate import gate_argv
    argv = [sys.executable, "-m", "pytest", "tests/test_a.py", "-q"]
    assert gate_argv(argv, "o.1") == argv


def test_non_pytest_argv_is_not_gated():
    from tools.truth_gate import gate_argv
    argv = [sys.executable, "script.py", "a"]
    assert gate_argv(argv, "o.1") == argv


def test_gate_naming_command_is_not_double_wrapped():
    from tools.truth_gate import GATE_SCRIPT, gate_argv
    argv = [sys.executable, str(GATE_SCRIPT), "run", "--owner", "x", "--",
            sys.executable, "-m", "pytest", "-q"]
    assert gate_argv(argv, "o.1") == argv


def test_gate_owner_falls_back_to_the_claim_env(monkeypatch):
    from tools.truth_gate import resolve_owner
    monkeypatch.setenv("FLEET_CLAIM_OWNER", "sess.agent")
    assert resolve_owner(None) == "sess.agent"
    assert resolve_owner("given") == "given"
    monkeypatch.delenv("FLEET_CLAIM_OWNER")
    assert resolve_owner(None) is None


def test_gate_without_an_owner_omits_the_flag(monkeypatch):
    from tools.truth_gate import GATE_SCRIPT, gate_argv
    monkeypatch.delenv("FLEET_CLAIM_OWNER", raising=False)
    argv = ["pytest", "-q"]
    assert gate_argv(argv, None) == [sys.executable, str(GATE_SCRIPT), "run", "--", *argv]


class _FakeRun:
    def __init__(self, rc):
        self.rc = rc
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        return type("P", (), {"returncode": self.rc})()


def test_default_suite_runs_through_the_gate_without_a_shell(monkeypatch, tmp_path):
    from tools import truth_gate
    fake = _FakeRun(0)
    monkeypatch.setattr(truth_gate.subprocess, "run", fake)
    obs = truth_gate.run_suite_fresh(truth_gate.DEFAULT_SUITE_CMD, tmp_path / "o.txt",
                                     owner="o.1")
    (argv, kw), = fake.calls
    assert argv[:6] == [sys.executable, str(truth_gate.GATE_SCRIPT), "run",
                        "--owner", "o.1", "--"]
    assert argv[7:] == ["-m", "pytest", "-q"]
    assert kw.get("shell") is not True
    assert obs["gated"] is True
    assert obs["gate_refused"] is False


def test_gate_exit_3_is_a_suite_gate_refused_discrepancy(monkeypatch, tmp_path):
    from tools import truth_gate
    monkeypatch.setattr(truth_gate.subprocess, "run", _FakeRun(3))
    obs = truth_gate.run_suite_fresh(truth_gate.DEFAULT_SUITE_CMD, tmp_path / "o.txt",
                                     owner="o.1")
    assert obs["gate_refused"] is True
    rep = reconcile(_claims(), obs, {"S1": _ok_files()},
                    git_obs={"clean": True, "head": "abc"}, ci_obs={"status": "success"})
    assert rep["verdict"] == "REFUSE"
    assert any(d.startswith("suite-gate refused") for d in rep["global_discrepancies"])
    assert not any(d.startswith("suite exit_code") for d in rep["global_discrepancies"])
    slice_disc = rep["slices"][0]["discrepancies"]
    assert slice_disc and all("suite-gate refused" in d for d in slice_disc
                              if "claimed_" in d)
    assert not any("observed 0" in d for d in slice_disc)


def test_ungated_exit_3_is_not_a_gate_refusal(monkeypatch, tmp_path):
    from tools import truth_gate
    monkeypatch.setattr(truth_gate.subprocess, "run", _FakeRun(3))
    obs = truth_gate.run_suite_fresh([sys.executable, "-m", "pytest", "tests/test_a.py"],
                                     tmp_path / "o.txt", owner="o.1")
    assert obs["gated"] is False
    assert obs["gate_refused"] is False


def test_missing_executable_is_a_refusal_not_a_crash(tmp_path):
    from tools import truth_gate
    # A .exe name, so Windows launches it (and fails) instead of refusing it unrun.
    obs = truth_gate.run_suite_fresh([str(tmp_path / "no_such.exe"), "x"], tmp_path / "o.txt")
    assert obs["exit_code"] == truth_gate.CANNOT_RUN_EXIT
    rep = reconcile(_claims(), obs, {"S1": _ok_files()},
                    git_obs={"clean": True, "head": "abc"}, ci_obs={"status": "success"})
    assert rep["verdict"] == "REFUSE"


# --- RM-757 follow-up: a .bat / .cmd head runs under cmd.exe, which re-parses argv ---

def _refused(monkeypatch, argv, which=None):
    from tools import truth_gate
    monkeypatch.setattr(truth_gate, "IS_WINDOWS", True)
    if which is not None:
        monkeypatch.setattr(truth_gate.shutil, "which", which)
    return truth_gate.refused_head(argv)


def test_refused_head_literal_path(monkeypatch):
    assert _refused(monkeypatch, [r"C:\x\run.bat", "a"]) == r"C:\x\run.bat"
    assert _refused(monkeypatch, ["tool.cmd"],
                    which=lambda name, *a, **k: r"C:\t\tool.cmd") == "tool.cmd"


def test_refused_head_quoted_path_with_a_space(monkeypatch):
    assert _refused(monkeypatch, ['"C:\\some dir\\run.cmd"', "a"])


def test_refused_head_mixed_case_and_trailing_dot(monkeypatch):
    assert _refused(monkeypatch, [r"C:\t\tool.BaT"])
    assert _refused(monkeypatch, [r"C:\t\tool.CmD"])
    assert _refused(monkeypatch, [r"C:\t\tool.bat.", "a"])


def test_refused_head_allows_exe_heads(monkeypatch):
    assert _refused(monkeypatch, [r"C:\p\python.exe", "-m", "pytest", "-q"]) is None
    assert _refused(monkeypatch, [r"C:\p\PyThOn.ExE", "x.bat"]) is None
    assert _refused(monkeypatch, []) is None


def test_refused_head_sees_the_command_behind_a_gate_wrapper(monkeypatch):
    from tools.truth_gate import GATE_SCRIPT
    assert _refused(monkeypatch, [r"C:\p\python.exe", str(GATE_SCRIPT), "run", "--owner", "o",
                                  "--", r"C:\d\x.cmd", "a"]) == r"C:\d\x.cmd"


@pytest.mark.skipif(os.name != "nt", reason="%VAR% expansion is Windows-only")
def test_refused_head_after_percent_var_expansion(monkeypatch):
    from tools.truth_gate import refused_head, split_cmd
    monkeypatch.setenv("RC_TG_RM757_BAT", r"C:\s\probe.bat")
    assert refused_head(split_cmd("%RC_TG_RM757_BAT% a"))


def test_batch_claim_is_refused_without_running(monkeypatch, tmp_path):
    from tools import truth_gate
    monkeypatch.setattr(truth_gate, "IS_WINDOWS", True)
    fake = _FakeRun(0)
    monkeypatch.setattr(truth_gate.subprocess, "run", fake)
    obs = truth_gate.run_suite_fresh([r"C:\x\run.bat", "a", "&", "b"], tmp_path / "o.txt")
    assert fake.calls == []
    assert obs["head_refused"] is True
    rep = reconcile(_claims(), obs, {"S1": _ok_files()},
                    git_obs={"clean": True, "head": "abc"}, ci_obs={"status": "success"})
    assert rep["verdict"] == "REFUSE"
    assert any(d.startswith("non-exe head refused") for d in rep["global_discrepancies"])
    slice_disc = rep["slices"][0]["discrepancies"]
    assert slice_disc and all("non-exe head refused" in d for d in slice_disc)


@pytest.mark.skipif(os.name != "nt", reason="%VAR% expansion is Windows-only")
def test_percent_var_expanding_to_a_batch_file_is_refused(monkeypatch, tmp_path):
    from tools import truth_gate
    fake = _FakeRun(0)
    monkeypatch.setattr(truth_gate.subprocess, "run", fake)
    monkeypatch.setenv("RC_TG_RM757_BAT", str(tmp_path / "probe.bat"))
    obs = truth_gate.run_suite_fresh("%RC_TG_RM757_BAT% a", tmp_path / "o.txt")
    assert fake.calls == []
    assert obs["head_refused"] is True


def test_posix_batch_named_head_is_not_refused(monkeypatch, tmp_path):
    from tools import truth_gate
    monkeypatch.setattr(truth_gate, "IS_WINDOWS", False)
    fake = _FakeRun(0)
    monkeypatch.setattr(truth_gate.subprocess, "run", fake)
    obs = truth_gate.run_suite_fresh(["./run.bat", "a"], tmp_path / "o.txt")
    assert len(fake.calls) == 1
    assert obs["head_refused"] is False


def _is_windows():
    from tools import truth_gate
    return truth_gate.IS_WINDOWS


@pytest.mark.skipif(not _is_windows(), reason="cmd.exe batch re-parse is Windows-only")
def test_batch_claim_command_never_runs_end_to_end(tmp_path):
    from tools import truth_gate
    folder = tmp_path / "probe dir"
    folder.mkdir()
    marker = tmp_path / "ran.txt"
    bat = folder / "probe.BaT"
    bat.write_text(f'@echo off\r\necho ran> "{marker}"\r\n', encoding="ascii")
    out = tmp_path / "o.txt"
    obs = truth_gate.run_suite_fresh(f'"{bat}" a & echo INJECTED_LINE', out)
    assert obs["head_refused"] is True
    assert not marker.exists()
    assert "INJECTED_LINE" not in out.read_text(encoding="utf-8")


# --- RM-757 round 3: every post-separator command; case-folded gate name ---

def test_refused_head_behind_a_case_variant_gate_name(monkeypatch):
    argv = [r"C:\p\python.exe", r"ops\fleet_kit\FLEET_SUITE_GATE.PY", "run", "--owner", "x",
            "--", r"C:\d\x.bat", "a"]
    assert _refused(monkeypatch, argv) == r"C:\d\x.bat"


def test_refused_head_behind_a_trailing_dot_gate_name(monkeypatch):
    argv = [r"C:\p\python.exe", "ops/fleet_kit/fleet_suite_gate.py.", "run", "--",
            r"C:\d\x.cmd", "a"]
    assert _refused(monkeypatch, argv) == r"C:\d\x.cmd"


def test_refused_head_behind_an_unknown_wrapper(monkeypatch):
    assert _refused(monkeypatch, [r"C:\p\python.exe", "other.py", "--", r"C:\d\x.bat",
                                  "a"]) == r"C:\d\x.bat"


def test_refused_head_after_every_separator(monkeypatch):
    argv = [r"C:\p\python.exe", "w.py", "--", r"C:\p\a.exe", "b", "--", r"C:\d\y.CMD", "c"]
    assert _refused(monkeypatch, argv) == r"C:\d\y.CMD"


def test_case_variant_gate_names_are_not_double_wrapped(monkeypatch):
    from tools import truth_gate
    monkeypatch.setattr(truth_gate, "IS_WINDOWS", True)
    for name in (r"C:\k\FLEET_SUITE_GATE.PY", "C:/k/fleet_suite_gate.py."):
        argv = [sys.executable, name, "run", "--", sys.executable, "-m", "pytest", "-q"]
        assert truth_gate.gate_argv(argv, "o.1") == argv


@pytest.mark.skipif(not _is_windows(), reason="cmd.exe batch re-parse is Windows-only")
def test_batch_behind_an_unknown_wrapper_never_runs_end_to_end(tmp_path):
    from tools import truth_gate
    wrapper = tmp_path / "other.py"
    wrapper.write_text("import subprocess, sys\n"
                       "i = sys.argv.index('--')\n"
                       "sys.exit(subprocess.run(sys.argv[i + 1:]).returncode)\n",
                       encoding="utf-8")
    bat = tmp_path / "x.bat"
    bat.write_text("@echo off\r\n", encoding="ascii")
    inj = tmp_path / "inj.txt"
    cmd = f'"{sys.executable}" "{wrapper}" -- "{bat}" a & echo INJECTED_LINE> "{inj}"'
    obs = truth_gate.run_suite_fresh(cmd, tmp_path / "o.txt")
    assert obs["head_refused"] is True
    assert not inj.exists()


# --- RM-757 round 4: deny-all - on Windows only a resolved .exe head is launched ---

_WIN_PY = r"C:\p\python.exe"


def _win(monkeypatch, which=None):
    from tools import truth_gate
    monkeypatch.setattr(truth_gate, "IS_WINDOWS", True)
    if which is not None:
        monkeypatch.setattr(truth_gate.shutil, "which", which)
    fake = _FakeRun(0)
    monkeypatch.setattr(truth_gate.subprocess, "run", fake)
    return truth_gate, fake


@pytest.mark.parametrize("head", [r"C:\d\x.bat\.", "C:/d/x.bat/.", r"C:\d\tool",
                                  r"C:\d\t.com", r"C:\d\t.ps1", r"C:\d\x.cmd"])
def test_non_exe_path_head_is_refused_unrun(monkeypatch, tmp_path, head):
    tg, fake = _win(monkeypatch)
    obs = tg.run_suite_fresh([head, "a", "&", "b"], tmp_path / "o.txt")
    assert fake.calls == []
    assert obs["head_refused"] is True


def test_dot_segment_bat_head_in_string_form_is_refused(monkeypatch, tmp_path):
    tg, fake = _win(monkeypatch)
    obs = tg.run_suite_fresh(r'"C:\d\x.bat\." a & echo INJECTED_LINE', tmp_path / "o.txt")
    assert fake.calls == []
    assert obs["head_refused"] is True


def test_bare_head_resolving_to_a_cmd_is_refused(monkeypatch, tmp_path):
    tg, fake = _win(monkeypatch, which=lambda name, *a, **k: r"C:\b\zzprobe.CMD")
    obs = tg.run_suite_fresh(["zzprobe", "a", "&", "echo", "INJ"], tmp_path / "o.txt")
    assert fake.calls == []
    assert obs["head_refused"] is True


def test_whole_suite_wrap_never_reaches_a_cmd_head(monkeypatch, tmp_path):
    tg, fake = _win(monkeypatch, which=lambda name, *a, **k: r"C:\b\zzprobe.CMD")
    obs = tg.run_suite_fresh(["zzprobe", "exec", "pytest", "-q", "a", "&", "echo", "INJ"],
                             tmp_path / "o.txt", owner="o.1")
    assert fake.calls == []
    assert obs["head_refused"] is True


def test_npm_style_cmd_shim_is_refused(monkeypatch, tmp_path):
    tg, fake = _win(monkeypatch, which=lambda name, *a, **k: r"C:\n\npm.CMD")
    obs = tg.run_suite_fresh(["npm", "exec", "pytest", "-q"], tmp_path / "o.txt")
    assert fake.calls == []
    assert obs["head_refused"] is True


def test_unresolvable_bare_head_is_refused(monkeypatch, tmp_path):
    tg, fake = _win(monkeypatch, which=lambda name, *a, **k: None)
    obs = tg.run_suite_fresh(["zzghost", "a"], tmp_path / "o.txt")
    assert fake.calls == []
    assert obs["head_refused"] is True


def test_cmd_head_after_a_separator_is_refused(monkeypatch, tmp_path):
    tg, fake = _win(monkeypatch, which=lambda name, *a, **k: r"C:\b\zzprobe.cmd")
    obs = tg.run_suite_fresh([_WIN_PY, "w.py", "--", "zzprobe", "a"], tmp_path / "o.txt")
    assert fake.calls == []
    assert obs["head_refused"] is True


def test_exe_path_heads_are_launched(monkeypatch, tmp_path):
    tg, fake = _win(monkeypatch, which=lambda name, *a, **k: r"C:\p\PYTHON.EXE")
    for argv in ([_WIN_PY, "x.py"], [r"C:\p\PYTHON.EXE", "x.py"], ["python", "x.py"],
                 [_WIN_PY, "w.py", "--", "python", "a"]):
        obs = tg.run_suite_fresh(argv, tmp_path / "o.txt")
        assert obs["head_refused"] is False
    assert len(fake.calls) == 4


@pytest.mark.skipif(not _is_windows(), reason="PATH / PATHEXT resolution is Windows-only")
def test_real_path_cmd_shim_is_refused_and_python_is_allowed(monkeypatch, tmp_path):
    from tools import truth_gate
    fake = _FakeRun(0)
    monkeypatch.setattr(truth_gate.subprocess, "run", fake)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "zzprobe.cmd").write_text("@echo off\r\n", encoding="ascii")
    (bin_dir / "npm.CMD").write_text("@echo off\r\n", encoding="ascii")
    py_dir = str(Path(sys.executable).parent)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + py_dir)
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    for cmd in ("zzprobe a & echo INJ", "zzprobe exec pytest -q a & echo INJ",
                "npm exec pytest -q"):
        obs = truth_gate.run_suite_fresh(cmd, tmp_path / "o.txt", owner="o.1")
        assert obs["head_refused"] is True, cmd
    assert fake.calls == []
    for cmd in ("python x.py", f'"{sys.executable}" x.py'):
        assert truth_gate.run_suite_fresh(cmd, tmp_path / "o.txt")["head_refused"] is False
    p2w5 = json.loads((Path(__file__).parent.parent / "ops" / "audit" /
                       "p2w5_truth_gate_claims.json").read_text(encoding="utf-8"))["suite_cmd"]
    assert truth_gate.run_suite_fresh(p2w5, tmp_path / "o.txt", owner="o.1")["head_refused"] is False
    assert len(fake.calls) == 3


def test_truth_gate_never_passes_shell_true():
    import ast
    src = (Path(__file__).parent.parent / "tools" / "truth_gate.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.keyword) and node.arg == "shell":
            assert not (isinstance(node.value, ast.Constant) and node.value.value is True)
