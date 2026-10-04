"""Y-02 (external reference K): one operator-notify path.

MEASURED DEFECT this pins: three copy-pasted `_toast` functions interpolated
title/body straight into toast XML. A `&` or `<` made LoadXml throw, a bare
except swallowed it, and the toast silently never showed. core/operator_notify
replaces all three: every notifier returns (ok, detail) and never raises, the
toast XML is escaped, a jsonl file is the floor, a chain tries notifiers in
order and joins every attempt's detail, and RC_NOTIFY_HOLD=1 (set by
tests/conftest.py) stops anything that would reach a person.
"""
from __future__ import annotations

import ast
import base64
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from core import operator_notify as on

ROOT = Path(__file__).resolve().parents[1]

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008


class _FakeRun:
    """Stands in for subprocess.run; records every call."""

    def __init__(self, returncode=0, stdout="shown", stderr=""):
        self.calls: list[tuple[list, dict]] = []
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr

    def __call__(self, args, **kw):
        self.calls.append((list(args), kw))
        return subprocess.CompletedProcess(args, self.returncode,
                                           self.stdout, self.stderr)


def _decode_ps(args: list) -> str:
    i = args.index("-EncodedCommand")
    return base64.b64decode(args[i + 1]).decode("utf-16-le")


def _xml_from_ps(script: str) -> str:
    m = re.search(r"FromBase64String\('([A-Za-z0-9+/=]+)'\)", script)
    assert m, "toast script carries no base64 XML payload"
    return base64.b64decode(m.group(1)).decode("utf-8")


@pytest.fixture
def win_host(monkeypatch):
    """The spawn contract is host-independent once subprocess.run is faked;
    fake a Windows host so CI's Linux runner exercises it instead of
    short-circuiting on "not windows" (CI run 37183631213)."""
    monkeypatch.setattr(on, "_on_windows", lambda: True)


@pytest.fixture
def unheld(monkeypatch):
    monkeypatch.delenv("RC_NOTIFY_HOLD", raising=False)


# --- escape ----------------------------------------------------------------

def test_escape_title_with_amp_and_lt_yields_valid_xml():
    title = 'A & B <c> "d"'
    body = "x > y & z < w\x01ctl"
    doc = on.build_toast_xml(title, body)
    root = ET.fromstring(doc)  # raises on the unescaped defect
    texts = [t.text for t in root.iter("text")]
    assert texts[0] == title
    assert texts[1] == "x > y & z < wctl"  # XML-1.0-illegal control char dropped


def test_escape_link_attribute_is_valid_xml():
    doc = on.build_toast_xml("t", "b", link='https://127.0.0.1:8888/?a=1&b="2"')
    root = ET.fromstring(doc)
    assert root.get("launch") == 'https://127.0.0.1:8888/?a=1&b="2"'
    assert root.get("activationType") == "protocol"


def test_wintoast_ships_escaped_xml_in_one_hidden_powershell(monkeypatch, unheld, win_host):
    fake = _FakeRun()
    monkeypatch.setattr(on.subprocess, "run", fake)
    ok, detail = on.WinToastNotifier().notify(on.Notification("A & B <c>", "1 < 2"))
    assert ok, detail
    assert len(fake.calls) == 1
    args, kw = fake.calls[0]
    flags = kw.get("creationflags", 0)
    assert flags & CREATE_NO_WINDOW
    assert not flags & DETACHED_PROCESS
    script = _decode_ps(args)
    assert on.DEFAULT_APP_ID in script
    ET.fromstring(_xml_from_ps(script))  # the payload LoadXml will see is valid


def test_wintoast_nonzero_exit_is_false_with_detail(monkeypatch, unheld, win_host):
    fake = _FakeRun(returncode=1, stdout="", stderr="LoadXml boom")
    monkeypatch.setattr(on.subprocess, "run", fake)
    ok, detail = on.WinToastNotifier().notify(on.Notification("t", "b"))
    assert ok is False
    assert "LoadXml boom" in detail


def test_wintoast_app_id_is_configurable(monkeypatch, unheld, win_host):
    fake = _FakeRun()
    monkeypatch.setattr(on.subprocess, "run", fake)
    on.WinToastNotifier(app_id="Some.App!Id").notify(on.Notification("t", "b"))
    assert "Some.App!Id" in _decode_ps(fake.calls[0][0])


# --- chain -------------------------------------------------------------------

class _Stub(on.Notifier):
    def __init__(self, name, result, log):
        self.name, self._result, self._log = name, result, log

    def _send(self, n):
        self._log.append(self.name)
        return self._result


class _Raiser(on.Notifier):
    name = "raiser"

    def _send(self, n):
        raise RuntimeError("kaboom")


def test_chain_tries_in_order_stops_at_first_ok_and_joins_details():
    log: list[str] = []
    chain = on.FirstThatWorks([_Stub("a", (False, "a-down"), log),
                               _Stub("b", (True, "b-sent"), log),
                               _Stub("c", (True, "c-sent"), log)])
    ok, detail = chain.notify(on.Notification("t", "b"))
    assert ok is True
    assert log == ["a", "b"]
    assert detail == "a: a-down; b: b-sent"


def test_chain_all_fail_is_false_with_every_detail():
    log: list[str] = []
    chain = on.FirstThatWorks([_Stub("a", (False, "x"), log),
                               _Stub("b", (False, "y"), log)])
    assert chain.notify(on.Notification("t", "b")) == (False, "a: x; b: y")


def test_empty_chain_is_false_not_silent():
    ok, detail = on.FirstThatWorks([]).notify(on.Notification("t", "b"))
    assert ok is False and detail


def test_default_chain_is_toast_then_jsonl_floor():
    chain = on.default_chain()
    kinds = [type(n) for n in chain.notifiers]
    assert kinds == [on.WinToastNotifier, on.JsonlNotifier]


# --- never raises ------------------------------------------------------------

def test_raising_notifier_returns_false_never_raises():
    ok, detail = _Raiser().notify(on.Notification("t", "b"))
    assert ok is False
    assert "RuntimeError" in detail and "kaboom" in detail


def test_chain_survives_raising_member_and_reaches_next():
    log: list[str] = []
    chain = on.FirstThatWorks([_Raiser(), _Stub("ok", (True, "fine"), log)])
    ok, detail = chain.notify(on.Notification("t", "b"))
    assert ok is True
    assert "raiser:" in detail and "kaboom" in detail and "ok: fine" in detail


def test_module_notify_never_raises_even_if_notify_itself_raises():
    class _Broken(on.Notifier):
        def notify(self, n):  # bypasses the base guard on purpose
            raise ValueError("broken")

    ok, detail = on.notify("t", "b", notifier=_Broken())
    assert ok is False and "broken" in detail


def test_non_windows_host_spawns_nothing(monkeypatch, unheld):
    fake = _FakeRun()
    monkeypatch.setattr(on.subprocess, "run", fake)
    monkeypatch.setattr(on, "_on_windows", lambda: False)
    ok, detail = on.WinToastNotifier().notify(on.Notification("t", "b"))
    assert ok is False and detail == "not windows"
    assert fake.calls == []


def test_wintoast_spawn_oserror_is_false(monkeypatch, unheld, win_host):
    def _boom(*a, **k):
        raise FileNotFoundError("no powershell")
    monkeypatch.setattr(on.subprocess, "run", _boom)
    ok, detail = on.WinToastNotifier().notify(on.Notification("t", "b"))
    assert ok is False and "no powershell" in detail


# --- HOLD --------------------------------------------------------------------

def test_hold_makes_toast_send_nothing(monkeypatch):
    monkeypatch.setenv("RC_NOTIFY_HOLD", "1")
    fake = _FakeRun()
    monkeypatch.setattr(on.subprocess, "run", fake)
    ok, detail = on.WinToastNotifier().notify(on.Notification("t", "b"))
    assert ok is False
    assert detail.startswith("held: ")
    assert fake.calls == []


def test_hold_does_not_stop_the_file_floor(monkeypatch, tmp_path):
    monkeypatch.setenv("RC_NOTIFY_HOLD", "1")
    p = tmp_path / "n.jsonl"
    ok, _ = on.JsonlNotifier(p).notify(on.Notification("t", "b"))
    assert ok is True and p.exists()


def test_conftest_sets_hold_and_redirects_floor():
    hold = os.environ.get("RC_NOTIFY_HOLD")
    assert hold == "1"
    floor = Path(os.environ["RC_NOTIFY_JSONL"]).resolve()
    assert ROOT.resolve() not in floor.parents, floor


def test_guard_under_hold_no_test_reaches_toast_subprocess(monkeypatch):
    # No delenv/setenv here: this runs under exactly the env conftest gives
    # every test. Every spawn primitive is trapped, then the real default path
    # is driven end to end.
    calls: list = []

    def _trap(*a, **k):
        calls.append((a, k))
        raise AssertionError("toast subprocess reached under RC_NOTIFY_HOLD")

    for attr in ("run", "Popen", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, attr, _trap)
    ok, detail = on.notify("guard & <probe>", "body", priority="high",
                           tags=("test",))
    assert calls == []
    assert "held: " in detail
    assert ok is True  # the jsonl floor (redirected by conftest) caught it
    rows = Path(os.environ["RC_NOTIFY_JSONL"]).read_text(encoding="utf-8")
    assert "guard & <probe>" in rows


# --- jsonl floor -------------------------------------------------------------

@pytest.mark.parametrize("use_win32", [True, False])
def test_jsonl_appends_one_row_per_call(tmp_path, use_win32):
    if use_win32 and sys.platform != "win32":
        pytest.skip("Win32 FILE_APPEND_DATA path is Windows-only")
    p = tmp_path / "sub" / "n.jsonl"
    n = on.JsonlNotifier(p, use_win32=use_win32)
    assert n.notify(on.Notification("one", "b1", priority="high",
                                    link="x", tags=("a", "b")))[0]
    assert n.notify(on.Notification("two", "b2"))[0]
    rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]
    assert [r["title"] for r in rows] == ["one", "two"]
    assert rows[0]["priority"] == "high" and rows[0]["tags"] == ["a", "b"]
    assert rows[0]["link"] == "x"


def test_jsonl_default_path_is_ops_runtime(monkeypatch):
    monkeypatch.delenv("RC_NOTIFY_JSONL", raising=False)
    assert on.JsonlNotifier().path == ROOT / "ops" / "runtime" / "operator_notify.jsonl"


def test_jsonl_unwritable_is_false_not_raise(tmp_path):
    d = tmp_path / "is_a_dir"
    d.mkdir()
    ok, detail = on.JsonlNotifier(d).notify(on.Notification("t", "b"))
    assert ok is False and detail


# --- repr --------------------------------------------------------------------

def test_repr_hides_any_token():
    class _Net(on.Notifier):
        holdable = True

        def __init__(self):
            self.token = "tk_supersecret123"
            self.url = "https://example.invalid/topic"

        def _send(self, n):
            return True, "sent"

    r = repr(_Net())
    assert "tk_supersecret123" not in r
    assert "***" in r and "example.invalid" in r


def test_holdable_subclass_is_held_by_env(monkeypatch):
    # The insertion contract a later network notifier relies on: set
    # holdable=True and the base class enforces RC_NOTIFY_HOLD before _send.
    monkeypatch.setenv("RC_NOTIFY_HOLD", "1")
    log: list[str] = []

    class _Net(_Stub):
        holdable = True

    ok, detail = _Net("net", (True, "sent"), log).notify(on.Notification("t", "b"))
    assert (ok, log) == (False, [])
    assert detail.startswith("held: ")


# --- one module, zero _toast copies -----------------------------------------

_WATCHERS = ("tools/claude_quota_watch.py", "tools/lcu_push_watcher.py",
             "tools/live_flip_watcher.py")


def _toast_defs(paths, root: Path = ROOT) -> list[str]:
    out = []
    for p in paths:
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name == "_toast":
                out.append(f"{p.relative_to(root).as_posix()}:{node.lineno}")
    return out


def _scan_set() -> list[Path]:
    return sorted(p for d in ("tools", "core", "ops", "app", "dashboard")
                  for p in (ROOT / d).rglob("*.py"))


def test_zero_toast_copies_left():
    paths = _scan_set()
    assert len(paths) > 50, "enumeration came back empty - the guard is blind"
    assert _toast_defs(paths) == []


def test_toast_copy_guard_positive_control(tmp_path):
    planted = tmp_path / "tools" / "planted.py"
    planted.parent.mkdir()
    planted.write_text("def _toast(title, body):\n    pass\n", encoding="utf-8")
    assert _toast_defs([planted], root=tmp_path) == ["tools/planted.py:1"]


@pytest.mark.parametrize("rel", _WATCHERS)
def test_watchers_route_through_operator_notify(rel):
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert "operator_notify" in src
    assert "ToastNotificationManager" not in src
