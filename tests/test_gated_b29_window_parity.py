"""tests/test_gated_b29_window_parity.py

`tools/gated_b29_window_parity.py` gathers design evidence for the (was B29) QA6 +
QA13 row in GATE 2. The contracts pinned here: a process handle opens only for an
allowlisted image, a git failure is never NOT_BUILT, and a sample that cannot
speak to the window state is NO_RESULT rather than AGREE or DISAGREE. No test
reads the real game.cfg or a real game window.
"""
from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from tools import gated_b29_window_parity as gbw

POPUP = 0x80000000
CAPTION = 0x00C00000
OVERLAPPED = CAPTION | 0x00080000
UP = {"elevated": True, "reason": None}
LOW = {"elevated": False, "reason": None}
GONE = {"elevated": None, "reason": "open_error_5"}


def _window(style=POPUP, covers=True, foreground=True, quns=5):
    return {"style": style, "covers_monitor": covers, "foreground": foreground,
            "quns": quns}


@pytest.mark.parametrize("window, state", [
    (_window(quns=3), "exclusive"),
    (_window(style=POPUP, covers=False, quns=3), "exclusive"),
    (_window(style=OVERLAPPED, covers=False), "windowed"),
    (_window(style=POPUP, covers=True), "popup_full"),
    (_window(style=POPUP, covers=False), "unknown"),
    (_window(style=OVERLAPPED, covers=True), "unknown"),
    (_window(style=None), "unknown"),
])
def test_observed_state(window, state):
    assert gbw.observed_state(window) == state


@pytest.mark.parametrize("mode, window, verdict", [
    ("2", _window(), "AGREE"),
    ("1", _window(style=OVERLAPPED, covers=False), "AGREE"),
    ("0", _window(quns=3), "AGREE"),
    ("0", _window(), "AMBIGUOUS"),
    ("2", _window(quns=3), "DISAGREE"),
    ("1", _window(), "DISAGREE"),
    ("2", _window(style=OVERLAPPED, covers=False), "DISAGREE"),
    ("0", _window(style=OVERLAPPED, covers=False), "DISAGREE"),
    ("9", _window(), "NO_RESULT"),
    (None, _window(), "NO_RESULT"),
    ("2", _window(style=POPUP, covers=False), "NO_RESULT"),
    ("2", _window(foreground=False), "NO_RESULT"),
    ("2", None, "NO_RESULT"),
])
def test_grade_window(mode, window, verdict):
    assert gbw.grade_window(mode, window)["verdict"] == verdict


def test_a_background_game_is_no_result_even_with_a_matching_state():
    # QUNS speaks for the foreground app, so this 3 is not the game's.
    grade = gbw.grade_window("0", _window(quns=3, foreground=False))
    assert grade == {"verdict": "NO_RESULT", "why": "game not foreground"}


@pytest.mark.parametrize("overlay, verdict", [
    ([], "OVERLAY_DOWN"),
    ([UP], "NO_BLOCK_POSSIBLE"),
    ([UP, UP], "NO_BLOCK_POSSIBLE"),
    ([LOW], "GAME_TOKEN_NEEDED"),
    ([UP, LOW], "GAME_TOKEN_NEEDED"),
    ([GONE, LOW], "GAME_TOKEN_NEEDED"),
    ([GONE], "UNKNOWN"),
    ([UP, GONE], "UNKNOWN"),
])
def test_grade_uipi(overlay, verdict):
    assert gbw.grade_uipi(overlay) == verdict


def test_the_openable_set_is_exactly_the_shell_and_the_overlay():
    assert set(gbw.OPENABLE_IMAGES) == {
        "explorer.exe", "Amberstone Shell.exe", "electron.exe"}


@pytest.mark.parametrize("image", [
    "League of Legends.exe", "LeagueClient.exe", "LeagueClientUx.exe",
    "RiotClientServices.exe", "Riot Client.exe", "RiotClientCrashHandler.exe",
    "vgtray.exe", "vgc.exe", "python.exe",
])
def test_an_unlisted_image_opens_nothing_and_is_not_even_listed(monkeypatch, image):
    def boom(*_a, **_k):
        raise AssertionError("listed or opened an unlisted image")

    monkeypatch.setattr(gbw, "pids_of", boom)
    monkeypatch.setattr(gbw, "_read_elevation", boom)
    assert gbw.tokens_of_image(image) == [{"elevated": None, "reason": "refused_image"}]


def test_a_failed_tasklist_opens_nothing(monkeypatch):
    def boom(_pid):
        raise AssertionError("opened with no listed pid")

    monkeypatch.setattr(gbw, "pids_of", lambda image: [])
    monkeypatch.setattr(gbw, "_read_elevation", boom)
    monkeypatch.setattr(gbw, "_exe_path", boom)
    assert gbw.tokens_of_image(gbw.SHELL_IMAGE) == []
    assert gbw.overlay_tokens() == []


def test_the_tool_takes_no_pid_argument():
    assert "pid" not in inspect.signature(gbw.collect).parameters
    with pytest.raises(SystemExit):
        gbw.main(["--pid", "5"])


def test_collect_opens_only_allowlisted_pids_and_reads_only_the_game_window(monkeypatch):
    images = {gbw.GAME_IMAGE: [100], "LeagueClient.exe": [101], "explorer.exe": [200],
              "Amberstone Shell.exe": [300], "electron.exe": [400, 401]}
    opened, windows = [], []
    listed = []

    def pids(image):
        listed.append(image)
        return images.get(image, [])

    def reader(pid):
        opened.append(pid)
        return UP

    def window(pid):
        windows.append(pid)
        return _window()

    monkeypatch.setattr(gbw, "pids_of", pids)
    monkeypatch.setattr(gbw, "_read_elevation", reader)
    monkeypatch.setattr(gbw, "game_window_facts", window)
    monkeypatch.setattr(gbw, "build_gate", lambda repo: {})
    monkeypatch.setattr(gbw, "uac_policy", dict)
    monkeypatch.setattr(gbw, "read_cfg", lambda: {"window_mode": "2"})
    monkeypatch.setattr(gbw, "_exe_path", {
        400: "<repo>/rc-shell/node_modules/electron/dist/electron.exe",
        401: "<repo>/lane-widget/node_modules/electron/dist/electron.exe"}.__getitem__)

    out = gbw.collect()

    assert sorted(opened) == sorted([os.getpid(), 200, 300, 400])
    assert windows == [100]
    assert "LeagueClient.exe" not in listed
    assert out["elevation"]["overlay"] == [UP, UP]
    assert out["elevation"]["uipi"] == "NO_BLOCK_POSSIBLE"
    assert out["window_grade"]["verdict"] == "AGREE"
    assert out["game_running"] is True


def test_another_electron_app_does_not_stand_in_for_the_overlay(monkeypatch):
    monkeypatch.setattr(gbw, "pids_of",
                        lambda image: [400] if image == "electron.exe" else [])
    monkeypatch.setattr(gbw, "_read_elevation", lambda pid: UP)
    monkeypatch.setattr(gbw, "_exe_path", lambda pid: "<repo>/lane-widget/electron.exe")
    rows = gbw.overlay_tokens()
    assert rows == []
    assert gbw.grade_uipi(rows) == "OVERLAY_DOWN"


@pytest.mark.parametrize("path, want", [
    ("<repo>\\rc-shell\\node_modules\\electron\\dist\\electron.exe", True),
    ("/repo/RC-Shell/node_modules/electron/dist/electron", True),
    ("<repo>\\lane-widget\\node_modules\\electron\\dist\\electron.exe", False),
    ("<repo>\\rc-shell-old\\electron.exe", False),
    ("", False),
    (None, False),
])
def test_is_rc_shell_exe(path, want):
    assert gbw.is_rc_shell_exe(path) is want


def test_pick_window_takes_the_largest_visible_window_of_that_pid():
    rows = [
        (7, True, 1, (0, 0, 5000, 5000)),   # another process, larger
        (9, False, 2, (0, 0, 4000, 4000)),  # hidden
        (9, True, 3, (0, 0, 10, 10)),
        (9, True, 4, (0, 0, 100, 100)),
    ]
    assert gbw.pick_window(rows, 9) == (4, (0, 0, 100, 100))
    assert gbw.pick_window(rows, 8) is None


def test_the_window_call_constants():
    assert gbw._GWL_STYLE == -16
    assert gbw._PROCESS_QUERY_LIMITED_INFORMATION == 0x1000
    assert gbw._TOKEN_ELEVATION_CLASS == 20


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 token read")
def test_real_token_read_of_this_process_and_of_an_invalid_pid():
    assert gbw._read_elevation(os.getpid())["elevated"] in (True, False)
    # Not a just-exited child: while any handle to it lives its token still reads.
    assert gbw._read_elevation(0x7FFFFFF0) == {"elevated": None, "reason": "not_running"}
    assert gbw._exe_path(0x7FFFFFF0) == ""
    assert gbw._exe_path(os.getpid()).lower().endswith(".exe")


def test_no_windows_api_is_reached_off_windows(monkeypatch):
    monkeypatch.setattr(gbw.sys, "platform", "linux")
    assert gbw._read_elevation(1) == {"elevated": None, "reason": "not_windows"}
    assert gbw._exe_path(1) == ""
    assert gbw.game_window_facts(1) is None
    assert gbw._flags() == 0


def test_read_cfg_reads_general_only(tmp_path):
    cfg = tmp_path / "game.cfg"
    cfg.write_text("[HUD]\nWindowMode=1\nWidth=9\n[General]\nWindowMode=2\nWidth=2560\n",
                   encoding="utf-8")
    os.utime(cfg, (1_700_000_000, 1_700_000_000))
    facts = gbw.read_cfg(cfg)
    assert facts["exists"] is True
    assert facts["window_mode"] == "2" and facts["label"] == "borderless"
    assert facts["width_present"] is True and facts["height_present"] is False
    assert facts["mtime"] == time.strftime("%Y-%m-%dT%H:%M:%S",
                                           time.localtime(1_700_000_000))
    assert str(tmp_path) not in json.dumps(facts)


@pytest.mark.parametrize("mode, label", [
    ("0", "fullscreen"), ("1", "windowed"), ("2", "borderless"), ("7", None)])
def test_window_mode_labels_are_the_operator_corrected_encoding(tmp_path, mode, label):
    cfg = tmp_path / "game.cfg"
    cfg.write_text(f"[General]\nWindowMode={mode}\n", encoding="utf-8")
    facts = gbw.read_cfg(cfg)
    assert facts["window_mode"] == mode and facts["label"] == label


def test_read_cfg_decodes_a_utf16_file(tmp_path):
    cfg = tmp_path / "game.cfg"
    cfg.write_bytes("[General]\nWindowMode=0\n".encode("utf-16"))
    assert gbw.read_cfg(cfg)["window_mode"] == "0"


@pytest.mark.parametrize("text", ["[HUD]\nMinimapScale=1\n", "[General]\nWidth=1\n"])
def test_read_cfg_without_the_key_is_none_not_a_default(tmp_path, text):
    cfg = tmp_path / "game.cfg"
    cfg.write_text(text, encoding="utf-8")
    facts = gbw.read_cfg(cfg)
    assert facts["exists"] is True
    assert facts["window_mode"] is None and facts["label"] is None


def test_read_cfg_absent_file(tmp_path):
    assert gbw.read_cfg(tmp_path / "absent.cfg")["exists"] is False


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True,
                   creationflags=gbw._flags())


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    for folder in ("core", "tools", "tests", "agents/x/tests", "rc-shell/test"):
        (tmp_path / folder).mkdir(parents=True)
    (tmp_path / "core" / "plain.py").write_text("x = 1\n", encoding="ascii")
    # Matches in tests and in these gated tools must not count as a build.
    for name in ("tools/gated_probe.py", "tests/test_x.py", "agents/x/tests/test_y.py",
                 "rc-shell/test/z.test.js"):
        (tmp_path / name).write_text("# WindowMode UIPI\n", encoding="ascii")
    # Nor does prose.
    (tmp_path / "notes.md").write_text("WindowMode UIPI\n", encoding="ascii")
    _git(tmp_path, "add", ".")
    return tmp_path


def test_build_gate_not_built_ignores_tests_gated_tools_and_prose(repo):
    out = gbw.build_gate(repo)
    assert out["qa6"] == {"state": "NOT_BUILT", "files": []}
    assert out["qa13"] == {"state": "NOT_BUILT", "files": []}


@pytest.mark.parametrize("key, text", [
    ("qa6", "WindowMode"),
    ("qa6", "window_mode"),
    ("qa6", "GetWindowLong"),
    ("qa6", "GWL_STYLE"),
    ("qa6", "WS_POPUP"),
    ("qa6", "SHQueryUserNotificationState"),
    ("qa6", "Switch to Borderless"),
    ("qa6", "go borderless"),
    ("qa6", "Use Borderless"),
    ("qa13", "TokenElevation"),
    ("qa13", "TOKEN_ELEVATION"),
    ("qa13", "IsUserAnAdmin"),
    ("qa13", "UIPI"),
])
@pytest.mark.parametrize("name", ["core/hint.py", "tools/lcu_hint.py", "root_hint.py",
                                  "rc-shell/src/hint.js"])
def test_build_gate_positive_controls(repo, key, text, name):
    target = repo / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"// {text}\n", encoding="ascii")
    _git(repo, "add", name)
    assert gbw.build_gate(repo)[key] == {"state": "CANDIDATE", "files": [name]}


def test_build_gate_a_borderless_comment_is_not_a_build(repo):
    (repo / "core" / "note.py").write_text("# the game must run Borderless\n",
                                           encoding="ascii")
    _git(repo, "add", "core/note.py")
    assert gbw.build_gate(repo)["qa6"]["state"] == "NOT_BUILT"


def test_build_gate_not_a_repo_is_unknown_never_not_built(tmp_path):
    out = gbw.build_gate(tmp_path)
    assert out["qa6"]["state"] == "UNKNOWN" and out["qa13"]["state"] == "UNKNOWN"


def test_build_gate_git_missing_is_unknown(repo):
    assert gbw.build_gate(repo, git="no-such-git-binary")["qa6"]["state"] == "UNKNOWN"


def test_pids_of_filters_on_the_image_and_matches_it_exactly():
    stdout = ('"League of Legends.exe","4242","Console","1","9 K"\n'
              '"League of Legends.exe.bak","4243","Console","1","9 K"\n'
              'INFO: No tasks are running which match the specified criteria.\n')
    calls = []

    def run(argv, **_kwargs):
        calls.append(argv)
        return SimpleNamespace(stdout=stdout)

    assert gbw.pids_of(gbw.GAME_IMAGE, run=run) == [4242]
    assert calls == [["tasklist", "/FO", "CSV", "/NH", "/FI",
                      "IMAGENAME eq League of Legends.exe"]]


def test_pids_of_on_a_failed_tasklist_is_empty():
    def run(*_a, **_k):
        raise OSError("no tasklist")

    assert gbw.pids_of(gbw.GAME_IMAGE, run=run) == []


def test_main_prints_collect_as_json(monkeypatch, capsys):
    monkeypatch.setattr(gbw, "collect", lambda: {"note": "x"})
    assert gbw.main([]) == 0
    assert json.loads(capsys.readouterr().out) == {"note": "x"}
