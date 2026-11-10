"""tests/test_gated_g601_shell_fresh.py.

`tools/gated_g601_shell_fresh.py` answers the G6-01 precondition (the Electron
MAIN process started after its newest `rc-shell/src` change, as a dev-profile
checkout launch). Pinned here: only a no-`--type=` shell process counts as MAIN,
a packaged or foreign-checkout shell never passes, a start at or before the
source bound is STALE, the mtime half of the bound can only fail closed, a
failed query is UNKNOWN (never NO_SHELL), and every subprocess runs windowless.
No test reads a real process or the real checkout's rc-shell tree.
"""
from __future__ import annotations

import inspect
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import gated_g601_shell_fresh as g6

REPO = Path("/x/repo")
EXE = str(Path(REPO, "rc-shell", "node_modules", "electron", "dist", "electron.exe"))
SRC_OK = {"bound": "2026-11-05T06:12:31+00:00", "error": None}


def _main(created="2026-11-06T10:00:00.1234567Z", cmd=None, exe=EXE, name="electron.exe"):
    if cmd is None:
        cmd = f'"{exe}" . --profile dev'
    return {"pid": 10, "ppid": 1, "name": name, "created": created, "exe": exe, "cmd": cmd}


def test_pass_when_dev_checkout_main_started_after_bound():
    out = g6.grade([_main()], SRC_OK, REPO)
    assert out["verdict"] == g6.PASS
    assert g6.exit_code(out["verdict"]) == 0


def test_equals_form_profile_also_passes():
    out = g6.grade([_main(cmd=f'"{EXE}" . --profile=dev')], SRC_OK, REPO)
    assert out["verdict"] == g6.PASS


def test_stale_at_or_before_bound():
    for created in ("2026-11-05T06:12:31Z", "2026-11-01T01:33:09Z"):
        out = g6.grade([_main(created=created)], SRC_OK, REPO)
        assert out["verdict"] == "STALE"
        assert g6.exit_code("STALE") == 2


def test_packaged_never_passes_even_when_fresh():
    out = g6.grade([_main(name="Amberstone Shell.exe", exe="/p/Amberstone Shell.exe",
                          cmd='"/p/Amberstone Shell.exe"')], SRC_OK, REPO)
    assert out["verdict"] == "PACKAGED"


def test_foreign_checkout_is_wrong_checkout():
    other = str(Path("/x/lane", "rc-shell", "node_modules", "electron", "dist", "electron.exe"))
    out = g6.grade([_main(exe=other, cmd=f'"{other}" . --profile dev')], SRC_OK, REPO)
    assert out["verdict"] == "WRONG_CHECKOUT"


def test_packaged_profile_on_checkout_is_not_dev():
    out = g6.grade([_main(cmd=f'"{EXE}" . --profile packaged')], SRC_OK, REPO)
    assert out["verdict"] == "WRONG_CHECKOUT"


def test_unnamed_profile_is_incomplete_not_fail():
    out = g6.grade([_main(cmd=f'"{EXE}" .')], SRC_OK, REPO)
    assert out["verdict"] == "PROFILE_UNNAMED"
    assert g6.exit_code("PROFILE_UNNAMED") == 1


def test_no_shell_vs_failed_query():
    assert g6.grade([], SRC_OK, REPO)["verdict"] == "NO_SHELL"
    assert g6.grade(None, SRC_OK, REPO)["verdict"] == "UNKNOWN"
    assert g6.exit_code("NO_SHELL") == 1
    assert g6.exit_code("UNKNOWN") == 1


def test_multiple_main_fails():
    out = g6.grade([_main(), _main()], SRC_OK, REPO)
    assert out["verdict"] == "MULTIPLE_MAIN"


def test_unreadable_exe_is_unknown_not_fail():
    for exe in (None, ""):
        row = _main()
        row["exe"] = exe
        assert g6.grade([row], SRC_OK, REPO)["verdict"] == "UNKNOWN"


@pytest.mark.parametrize("cmd,expect", [
    ('"e.exe" . --profile packaged --profile dev', "dev"),
    ('"e.exe" . --profile=dev --profile=packaged', "packaged"),
    ('"e.exe" . --profile --inspect', None),
    ('"e.exe" . --profile', None),
    ('"e.exe" . --profile dev --profile', None),
    ('"e.exe" . --profile "dev x"', "dev x"),
    ('"e.exe" . "--profile=dev x"', "dev x"),
    ('"e.exe" . "--profile dev"', None),
    ('"e.exe" . --x "a --profile dev"', None),
    ('"e.exe" . --profile=" dev"', "dev"),
    ('"e.exe" . --profile " dev"', "dev"),
    ('"e.exe" . --profile=--x', "--x"),
    ('"e.exe" . --profile --profile dev', "dev"),
    ('"e.exe" """" --profile dev', None),
    ('"e.exe" . --profile=dev\x1f', "dev\x1f"),
    ('"e.exe" . --profile=dev\u00a0', "dev"),
    ('"/a b/electron.exe" . --profile dev', "dev"),
])
def test_argv_profile_last_wins_and_dash_value_is_none(cmd, expect):
    assert g6.argv_profile(cmd) == expect


@pytest.mark.parametrize("cmd,argv", [
    ('a b', ["a", "b"]),
    ('"a b" c', ["a b", "c"]),
    ('a\\\\"b c"', ['a\\b c']),
    ('a\\"b', ['a"b']),
    ('a\\b', ['a\\b']),
    ('a\\\\\\"b', ['a\\"b']),
    ('"\\\\"', ['\\']),
    ('"a""b"', ['a"b']),
    ('"a""b c"', ['a"b', 'c']),
    ('x """" --profile dev', ['x', '" --profile dev']),
    ('  ', []),
    ('""', [""]),
])
def test_split_cmdline_windows_rules(cmd, argv):
    assert g6.split_cmdline(cmd) == argv


def test_quoted_type_switch_still_marks_a_child():
    assert g6.is_main({"name": "electron.exe", "cmd": '"e.exe" "--type=renderer"'}) is False


def test_unreadable_bound_is_unknown():
    out = g6.grade([_main()], {"bound": None, "error": "git exit non-zero"}, REPO)
    assert out["verdict"] == "UNKNOWN"


@pytest.mark.parametrize("cmd,expect", [
    ('"e.exe" --type=renderer --profile dev', False),
    ('"e.exe" --type=gpu-process', False),
    ('"e.exe" . --profile dev', True),
])
def test_is_main_excludes_typed_children(cmd, expect):
    assert g6.is_main({"name": "electron.exe", "cmd": cmd}) is expect


def test_is_main_rejects_other_images_and_missing_cmd():
    assert g6.is_main({"name": "League of Legends.exe", "cmd": "x"}) is False
    assert g6.is_main({"name": "electron.exe", "cmd": None}) is False


def test_parse_ts_handles_seven_fraction_digits_and_naive():
    dt = g6._parse_ts("2026-11-06T10:00:00.1234567Z")
    assert dt is not None and dt.year == 2026 and dt.microsecond == 123456
    assert g6._parse_ts("2026-11-06T10:00:00") is None
    assert g6._parse_ts("garbage") is None


def _fake_run(log_out, files_out, rc=0):
    calls = []

    def run(argv, **kw):
        calls.append((argv, kw))
        if "log" in argv:
            return SimpleNamespace(returncode=rc, stdout=log_out, stderr="")
        return SimpleNamespace(returncode=rc, stdout=files_out, stderr="")
    return run, calls


def test_source_bound_takes_later_of_commit_and_mtime(tmp_path):
    src = tmp_path / "rc-shell" / "src"
    src.mkdir(parents=True)
    f = src / "main.js"
    f.write_text("x\n", encoding="ascii")
    late = 1_800_000_000  # 2027-01-15, after the commit time below
    os.utime(f, (late, late))
    run, calls = _fake_run("abcdef1234567890 2026-11-05T00:12:31-06:00\n", "rc-shell/src/main.js\n")
    out = g6.source_bound(tmp_path, run=run)
    assert out["commit"] == "abcdef123456"
    assert out["mtime_file"] == "rc-shell/src/main.js"
    assert g6._parse_ts(out["bound"]) == g6._parse_ts(out["mtime"])
    assert all(kw.get("creationflags") == g6._flags() for _, kw in calls)


def test_source_bound_commit_wins_when_files_older(tmp_path):
    src = tmp_path / "rc-shell" / "src"
    src.mkdir(parents=True)
    f = src / "main.js"
    f.write_text("x\n", encoding="ascii")
    os.utime(f, (1_700_000_000, 1_700_000_000))  # 2023
    run, _ = _fake_run("abc 2026-11-05T00:12:31-06:00\n", "rc-shell/src/main.js\n")
    out = g6.source_bound(tmp_path, run=run)
    assert out["bound"] == "2026-11-05T06:12:31+00:00"


def test_source_bound_git_failure_has_no_bound(tmp_path):
    run, _ = _fake_run("", "", rc=128)
    out = g6.source_bound(tmp_path, run=run)
    assert out["bound"] is None and out["error"]


def test_list_shell_processes_shapes_and_failures():
    one = json.dumps(_main())

    def ok(argv, **kw):
        assert kw.get("creationflags") == g6._flags()
        assert argv[0] == "powershell.exe"
        return SimpleNamespace(returncode=0, stdout=one, stderr="")
    assert g6.list_shell_processes(run=ok) == [_main()]
    assert g6.list_shell_processes(run=lambda a, **k: SimpleNamespace(returncode=0, stdout="", stderr="")) == []
    assert g6.list_shell_processes(run=lambda a, **k: SimpleNamespace(returncode=1, stdout="", stderr="")) is None
    assert g6.list_shell_processes(run=lambda a, **k: SimpleNamespace(returncode=0, stdout="{bad", stderr="")) is None

    def boom(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 60)
    assert g6.list_shell_processes(run=boom) is None


def test_collect_end_to_end_with_fakes(tmp_path):
    exe = str(Path(tmp_path, "rc-shell", "node_modules", "electron", "dist", "electron.exe"))
    rows = [_main(exe=exe, cmd=f'"{exe}" . --profile dev'),
            _main(exe=exe, cmd=f'"{exe}" --type=renderer')]

    def run(argv, **kw):
        if argv[0] == "powershell.exe":
            return SimpleNamespace(returncode=0, stdout=json.dumps(rows), stderr="")
        if "log" in argv:
            return SimpleNamespace(returncode=0, stdout="abc 2026-11-05T00:12:31-06:00\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    res = g6.collect(tmp_path, run=run)
    assert res["verdict"] == g6.PASS
    assert res["children"] == 1 and len(res["main"]) == 1
    assert res["main"][0]["profile"] == "dev"


def test_tool_is_read_only_by_source():
    src = inspect.getsource(g6)
    for banned in ("write_text", "write_bytes", "unlink(", "taskkill", "Stop-Process",
                   "DETACHED_PROCESS", "open(", "urlopen", "requests."):
        assert banned not in src, banned
