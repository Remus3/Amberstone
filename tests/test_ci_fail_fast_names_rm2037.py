"""RM-2037: a CI run names each failing test the moment it fails.

CI run 42383196203 hit its step ceiling at [ 95%] before pytest printed a
summary, so 72 failures were counted from progress characters and never
named. The plugin in tests/_fail_fast_names.py prints, from the controlling
process only (never an xdist worker), one line per failed report:

    RC-FAIL <when> <nodeid> :: <first error line, ASCII, <= 200 chars>

It is on under CI (CI=true or GITHUB_ACTIONS=true) or with
RC_FAIL_FAST_NAMES=1, off by default locally, and RC_FAIL_FAST_NAMES=0 turns
it off even under CI. It never changes an outcome.

The behaviour tests run a real inner pytest through pytester with the plugin
loaded by `-p tests._fail_fast_names` (the inner run does not see this repo's
conftest files); the wiring test pins that the rootdir conftest.py re-exports
the plugin's session hook, which is what turns it on for both suites.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import _fail_fast_names as ffn

pytest_plugins = ["pytester"]

REPO = Path(__file__).resolve().parents[1]
PLUGIN = ("-p", "tests._fail_fast_names", "-p", "no:cacheprovider")
GATE_VARS = ("CI", "GITHUB_ACTIONS", ffn.ENV_SWITCH)

_SUITE = """
import pytest


@pytest.fixture
def broken_setup():
    raise RuntimeError("setup went wrong")


@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("teardown went wrong")


def test_passes():
    assert True


def test_fails():
    assert 1 == 2, "one is not two"


def test_setup_error(broken_setup):
    pass


def test_teardown_error(broken_teardown):
    pass


@pytest.mark.xfail(reason="expected")
def test_expected_failure():
    assert False


@pytest.mark.skip(reason="skipped")
def test_skipped():
    pass
"""


def _gate(monkeypatch, **values):
    for name in GATE_VARS:
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def _rc_lines(result):
    return [ln for ln in result.outlines if ln.startswith(ffn.PREFIX + " ")]


def _assert_outcomes_unchanged(result):
    result.assert_outcomes(passed=2, failed=1, errors=2, xfailed=1, skipped=1)


# ---- behaviour (real inner pytest) -------------------------------------------


def test_each_failure_is_named_while_the_run_is_still_going(pytester, monkeypatch):
    _gate(monkeypatch, **{ffn.ENV_SWITCH: "1"})
    pytester.makepyfile(test_suite=_SUITE)
    result = pytester.runpytest(*PLUGIN, "-q")
    _assert_outcomes_unchanged(result)
    lines = _rc_lines(result)
    assert lines == [
        "RC-FAIL call test_suite.py::test_fails :: AssertionError: one is not two",
        "RC-FAIL setup test_suite.py::test_setup_error :: RuntimeError: setup went wrong",
        "RC-FAIL teardown test_suite.py::test_teardown_error :: RuntimeError: teardown went wrong",
    ], result.outlines
    # Printed as each report arrives, i.e. before the end-of-run sections, so a
    # run killed before its summary still carries every name it reached.
    first = result.outlines.index(lines[0])
    sections = [
        i for i, ln in enumerate(result.outlines) if "FAILURES" in ln or "ERRORS" in ln or "short test summary" in ln
    ]
    assert sections and first < min(sections), result.outlines


@pytest.mark.parametrize("var", ["CI", "GITHUB_ACTIONS"])
def test_ci_environment_turns_it_on(pytester, monkeypatch, var):
    _gate(monkeypatch, **{var: "true"})
    pytester.makepyfile(test_suite=_SUITE)
    result = pytester.runpytest(*PLUGIN, "-q")
    _assert_outcomes_unchanged(result)
    assert len(_rc_lines(result)) == 3, result.outlines


def test_off_by_default_locally(pytester, monkeypatch):
    _gate(monkeypatch)
    pytester.makepyfile(test_suite=_SUITE)
    result = pytester.runpytest(*PLUGIN, "-q")
    _assert_outcomes_unchanged(result)
    assert _rc_lines(result) == [], result.outlines
    assert not any(ffn.PREFIX in ln for ln in result.outlines + result.errlines)


def test_switch_zero_wins_over_ci(pytester, monkeypatch):
    _gate(monkeypatch, CI="true", GITHUB_ACTIONS="true", **{ffn.ENV_SWITCH: "0"})
    pytester.makepyfile(test_suite=_SUITE)
    result = pytester.runpytest(*PLUGIN, "-q")
    _assert_outcomes_unchanged(result)
    assert _rc_lines(result) == [], result.outlines


def test_works_under_xdist_and_names_each_failure_once(pytester, monkeypatch):
    pytest.importorskip("xdist")
    _gate(monkeypatch, **{ffn.ENV_SWITCH: "1"})
    pytester.makepyfile(
        test_alpha="def test_a_ok():\n    pass\n\n\ndef test_a_bad():\n    assert 0, 'alpha broke'\n",
        test_beta="def test_b_ok():\n    pass\n\n\ndef test_b_bad():\n    raise ValueError('beta broke')\n",
    )
    result = pytester.runpytest(*PLUGIN, "-q", "-n", "2", "--dist", "loadfile")
    result.assert_outcomes(passed=2, failed=2)
    # Anchor: the reports really came from xdist workers (each failure header
    # in the long traceback carries its worker id).
    assert any(ln.startswith("[gw") for ln in result.outlines), result.outlines
    lines = sorted(_rc_lines(result))
    assert lines == [
        "RC-FAIL call test_alpha.py::test_a_bad :: AssertionError: alpha broke",
        "RC-FAIL call test_beta.py::test_b_bad :: ValueError: beta broke",
    ], result.outlines


def test_error_text_is_one_ascii_line_of_at_most_200_chars(pytester, monkeypatch):
    _gate(monkeypatch, **{ffn.ENV_SWITCH: "1"})
    pytester.makepyfile(
        test_long="""
def test_long():
    raise AssertionError("\\u00e9\\u00b7" * 40 + "x" * 400 + "\\nsecond line")
"""
    )
    result = pytester.runpytest(*PLUGIN, "-q")
    result.assert_outcomes(failed=1)
    (line,) = _rc_lines(result)
    head = "RC-FAIL call test_long.py::test_long :: "
    assert line.startswith(head), line
    msg = line[len(head) :]
    assert line.isascii(), line
    assert len(msg) == ffn.MAX_ERROR_CHARS, (len(msg), msg)
    assert msg.startswith("AssertionError: \\xe9\\xb7\\xe9"), msg
    assert msg.endswith("..."), msg
    assert "second line" not in line


# ---- units --------------------------------------------------------------------


def _report(**kw):
    base = dict(failed=True, when="call", nodeid="tests/t.py::test_x", longrepr=None, longreprtext="")
    base.update(kw)
    return SimpleNamespace(**base)


def test_a_serialized_report_names_its_E_line():
    # Under xdist a non-traceback longrepr (e.g. a missing fixture) arrives as
    # plain text whose first line is the file, not the error.
    text = (
        "file /x/tests/t.py, line 3\n  def test_x(nope):\n"
        "E       fixture 'nope' not found\n>       available fixtures: a, b\n"
    )
    rep = _report(when="setup", longrepr=text, longreprtext=text)
    assert ffn.format_line(rep) == ("RC-FAIL setup tests/t.py::test_x :: fixture 'nope' not found")


def test_control_and_escape_characters_are_made_safe():
    crash = SimpleNamespace(message="\x1b[31mred\x1b[0m\ttab" + chr(0x2603) + "x")
    rep = _report(longrepr=SimpleNamespace(reprcrash=crash))
    assert ffn.format_line(rep) == ("RC-FAIL call tests/t.py::test_x :: red tab" + "\\" + "u2603x")


def test_a_report_without_text_still_names_the_test():
    assert ffn.format_line(_report()) == ("RC-FAIL call tests/t.py::test_x :: (no error text)")


class _Unprintable:
    def __str__(self):
        raise RuntimeError("cannot render")

    @property
    def reprcrash(self):
        raise RuntimeError("cannot render")


def test_a_broken_report_never_raises_and_still_names_the_test(capsys):
    config = SimpleNamespace(pluginmanager=SimpleNamespace(get_plugin=lambda n: None))
    plugin = ffn.FailFastNames(config)
    plugin.pytest_runtest_logreport(_report(longrepr=_Unprintable()))
    err = capsys.readouterr().err
    assert err.startswith("RC-FAIL call tests/t.py::test_x :: "), err


def test_passing_and_skipped_reports_print_nothing(capsys):
    config = SimpleNamespace(pluginmanager=SimpleNamespace(get_plugin=lambda n: None))
    plugin = ffn.FailFastNames(config)
    plugin.pytest_runtest_logreport(_report(failed=False))
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    "env,on",
    [
        ({}, False),
        ({"CI": "true"}, True),
        ({"CI": "True"}, True),
        ({"GITHUB_ACTIONS": "true"}, True),
        ({"CI": "false"}, False),
        ({"CI": "1"}, False),
        ({ffn.ENV_SWITCH: "1"}, True),
        ({ffn.ENV_SWITCH: "0", "CI": "true"}, False),
        ({ffn.ENV_SWITCH: "0", "GITHUB_ACTIONS": "true"}, False),
    ],
)
def test_gate(env, on):
    assert ffn.enabled(env) is on


class _PM:
    def __init__(self):
        self.registered = {}

    def has_plugin(self, name):
        return name in self.registered

    def register(self, plugin, name):
        self.registered[name] = plugin


def test_install_skips_an_xdist_worker_and_registers_once(monkeypatch):
    _gate(monkeypatch, **{ffn.ENV_SWITCH: "1"})
    worker = SimpleNamespace(workerinput={"workerid": "gw0"}, pluginmanager=_PM())
    assert ffn.install(worker) is False
    assert worker.pluginmanager.registered == {}
    controller = SimpleNamespace(pluginmanager=_PM())
    assert ffn.install(controller) is True
    assert ffn.install(controller) is False
    assert list(controller.pluginmanager.registered) == [ffn.PLUGIN_NAME]


def test_install_is_inert_when_the_gate_is_off(monkeypatch):
    _gate(monkeypatch)
    controller = SimpleNamespace(pluginmanager=_PM())
    assert ffn.install(controller) is False
    assert controller.pluginmanager.registered == {}


# ---- wiring -------------------------------------------------------------------


def test_rootdir_conftest_reexports_the_session_hook():
    tree = ast.parse((REPO / "conftest.py").read_text(encoding="utf-8"))
    found = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "tests._fail_fast_names"
        and any(a.name == "pytest_sessionstart" and a.asname in (None, "pytest_sessionstart") for a in node.names)
        for node in ast.walk(tree)
    )
    assert found, "conftest.py must `from tests._fail_fast_names import pytest_sessionstart`"


def test_the_plugin_module_is_loadable_by_name():
    assert importlib.util.find_spec("tests._fail_fast_names") is not None
