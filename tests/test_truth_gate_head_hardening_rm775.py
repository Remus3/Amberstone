"""RM-775: three follow-ups to the RM-757 Windows head check in tools/truth_gate.py.

(a) A head carrying a double quote (after one matched outer layer is stripped)
    is REFUSED unrun. subprocess.list2cmdline escapes an inner quote as `\\"`,
    but CreateProcess reads the module name off the command line without
    honouring that escape, so the program it launches is not the path that
    was validated. No Windows file name can contain `"` anyway.
(b) A shell `.exe` head (`cmd.exe /c ...`) stays ALLOWED by decision: naming a
    shell is an explicit caller choice, `python.exe -c` is just as arbitrary,
    and a shell-name list is the blocklist shape RM-757 dropped. Pinned here so
    a change is deliberate.
(c) `py.test -q` stays REFUSED by decision: a shell-free launch never appends
    `.exe` to a dotted name, so it could not run without cmd.exe's PATHEXT;
    `py.test.exe` and `python.exe -m pytest` are the accepted spellings.

POSIX launches are unchanged by all three. Every subprocess fake is bound to
truth_gate's own `subprocess` name (RM-801), never the shared module.
"""
from __future__ import annotations

import pytest

from tests._module_view import bind_subprocess
from tools import truth_gate

_WIN_PY = r"C:\p\python.exe"


class _FakeRun:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        return type("P", (), {"returncode": 0})()


class _Which:
    """A PATH lookup fake that records every name it was asked for."""

    def __init__(self, table):
        self.table = table
        self.asked = []

    def __call__(self, name, *a, **k):
        self.asked.append(name)
        return self.table.get(name)


def _win(monkeypatch, table=None):
    monkeypatch.setattr(truth_gate, "IS_WINDOWS", True)
    which = _Which(table or {})
    monkeypatch.setattr(truth_gate, "_path_which", which)
    fake = _FakeRun()
    bind_subprocess(monkeypatch, truth_gate, run=fake)
    return fake, which


# --------------------------------------------------------------------------- #
# (a) a double quote inside a head is refused
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("head", [
    r'C:\p\py"thon.exe',
    'C:\\Windows\\calc.exe" C:\\p\\python.exe',
    '"C:\\p\\python.exe',
    r'C:\p\py""thon.exe',
    'py"thon.exe',
])
def test_head_with_a_double_quote_is_refused_unrun(monkeypatch, tmp_path, head):
    fake, _ = _win(monkeypatch, {"py\"thon.exe": _WIN_PY, "python.exe": _WIN_PY})
    obs = truth_gate.run_suite_fresh([head, "a"], tmp_path / "o.txt")
    assert fake.calls == [], f"{head!r} was launched"
    assert obs["head_refused"] is True


def test_quoted_head_after_a_separator_is_refused(monkeypatch, tmp_path):
    fake, _ = _win(monkeypatch)
    obs = truth_gate.run_suite_fresh([_WIN_PY, "w.py", "--", r'C:\p\a"b.exe', "a"],
                                     tmp_path / "o.txt")
    assert fake.calls == []
    assert obs["head_refused"] is True


def test_string_form_head_with_an_inner_quote_is_refused(monkeypatch, tmp_path):
    fake, _ = _win(monkeypatch)
    obs = truth_gate.run_suite_fresh('C:\\p\\a"b.exe x', tmp_path / "o.txt")
    assert fake.calls == []
    assert obs["head_refused"] is True


def test_quoted_head_is_refused_before_any_path_lookup(monkeypatch):
    _, which = _win(monkeypatch, {"py\"thon.exe": _WIN_PY})
    assert truth_gate.refused_head(['py"thon.exe', "a"]) == 'py"thon.exe'
    assert which.asked == []


def test_one_matched_outer_quote_layer_is_still_accepted(monkeypatch):
    """The RM-757 contract for a quoted path with a space is kept."""
    _win(monkeypatch)
    assert truth_gate.refused_head(['"C:\\some dir\\python.exe"', "a"]) is None
    assert truth_gate.refused_head([_WIN_PY, "-c", 'print("x")']) is None


def test_posix_quoted_head_is_unchanged(monkeypatch, tmp_path):
    monkeypatch.setattr(truth_gate, "IS_WINDOWS", False)
    fake = _FakeRun()
    bind_subprocess(monkeypatch, truth_gate, run=fake)
    obs = truth_gate.run_suite_fresh(['./a"b', "x"], tmp_path / "o.txt")
    assert obs["head_refused"] is False
    assert len(fake.calls) == 1


# --------------------------------------------------------------------------- #
# (b) a shell .exe head is allowed by decision
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("argv, table", [
    (["cmd.exe", "/c", "echo", "a"], {"cmd.exe": r"C:\W\System32\cmd.exe"}),
    (["powershell.exe", "-Command", "x"],
     {"powershell.exe": r"C:\W\System32\WindowsPowerShell\v1.0\powershell.exe"}),
    ([_WIN_PY, "-c", "import sys"], {}),
])
def test_shell_exe_heads_are_allowed_by_decision(monkeypatch, tmp_path, argv, table):
    fake, _ = _win(monkeypatch, table)
    obs = truth_gate.run_suite_fresh(argv, tmp_path / "o.txt")
    assert obs["head_refused"] is False
    assert len(fake.calls) == 1
    assert fake.calls[0][1:] == argv[1:], "arguments must reach the child unchanged"


# --------------------------------------------------------------------------- #
# (c) `py.test` is refused by decision; the .exe spellings are accepted
# --------------------------------------------------------------------------- #
def test_dotted_py_test_head_is_refused_before_any_lookup(monkeypatch, tmp_path):
    fake, which = _win(monkeypatch, {"py.test": r"C:\p\Scripts\py.test.exe"})
    obs = truth_gate.run_suite_fresh("py.test -q", tmp_path / "o.txt")
    assert obs["head_refused"] is True
    assert fake.calls == []
    assert which.asked == []


@pytest.mark.parametrize("cmd, table", [
    ("py.test.exe -q", {"py.test.exe": r"C:\p\Scripts\py.test.exe"}),
    ("python.exe -m pytest -q", {"python.exe": _WIN_PY}),
])
def test_exe_spellings_of_pytest_are_accepted(monkeypatch, tmp_path, cmd, table):
    fake, _ = _win(monkeypatch, table)
    obs = truth_gate.run_suite_fresh(cmd, tmp_path / "o.txt", owner="o.1")
    assert obs["head_refused"] is False
    assert len(fake.calls) == 1


def test_decisions_are_recorded_in_the_module_docstring():
    doc = truth_gate.__doc__ or ""
    assert "RM-775" in doc
    assert "double quote" in doc
    assert "cmd.exe /c" in doc and "py.test" in doc
    assert doc.count("Reverses if") >= 2, "each RM-775 decision carries a Reverses if"
