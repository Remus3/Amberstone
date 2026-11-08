"""S144-Q-124: a cost_health_watchdog copy made after collection logs to tmp.

`tests/conftest.py` `redirect_spec_loaded_tool_logs_to_tmp` is SESSION scoped:
it repoints `_LOG` on every copy of tools/cost_health_watchdog.py that exists
when the first test runs, once. A copy made LATER kept the checkout path:

- `tests/test_log_appenders_lf_s144p193.py` imports `tools.cost_health_watchdog`
  inside a test body, so run with tests/test_suite_does_not_write_live_tree.py
  in one process, `test_mechanism_is_armed_during_a_test[spec-loaded-tool-logs]`
  and `test_every_fixed_row_has_an_armed_mechanism` failed (2 failed, 40 passed,
  measured 2026-11-08 on the lane base);
- `tests/test_p2w4_tools_h.py::test_main_emits_strict_json_with_poisoned_ledger`
  spec-loads the tool inside the test body and calls `main()`, which appended a
  233-byte BREACH line to the checkout's logs/cost_health_watchdog.log on every
  run (measured the same day). That copy is a local variable, so no scan of
  `sys.modules` or of module attributes can ever reach it.

The fix is the house pattern (RC_HOOK_LOG, RC_SIBLING_SWEEP_RUN_LOG): the tool
reads `RC_COST_HEALTH_WATCHDOG_LOG` when it executes, and conftest sets it at
IMPORT, so every copy, however late and however loaded, resolves to the
per-worker suite log dir. The session scan stays as a backstop.
"""
from __future__ import annotations

import importlib.util
import itertools
import os
import sys

from tests import conftest as rc_conftest
from tests._repo_walk import REPO_ROOT

_ENV = "RC_COST_HEALTH_WATCHDOG_LOG"
_TOOL = REPO_ROOT / "tools" / "cost_health_watchdog.py"
_CHECKOUT_LOG = REPO_ROOT / "logs" / "cost_health_watchdog.log"
_SEQ = itertools.count()


def _fresh_copy():
    """Execute a NEW copy of the tool now, inside the calling test's body -
    the shape the session-scoped redirect cannot see."""
    name = f"_s144q124_chw_copy_{next(_SEQ)}"
    spec = importlib.util.spec_from_file_location(name, str(_TOOL))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _under_repo(path) -> bool:
    try:
        path.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        return False
    return True


def _snapshot(path):
    return path.read_bytes() if path.is_file() else None


def test_conftest_points_the_env_at_the_suite_log_dir():
    expected = str(rc_conftest._SUITE_LOG_DIR / "cost_health_watchdog.log")
    assert os.environ.get(_ENV) == expected, (
        f"tests/conftest.py must set {_ENV} at import to the suite log dir, "
        "so a watchdog copy made inside a test body cannot reach logs/")


def test_a_copy_made_in_a_test_body_resolves_outside_the_repo():
    copy = _fresh_copy()
    assert not _under_repo(copy._LOG), (
        f"a late copy's _LOG is {copy._LOG} - inside the checkout")
    assert copy._LOG == rc_conftest._SUITE_LOG_DIR / "cost_health_watchdog.log"


def test_a_late_copy_logging_leaves_the_checkout_log_untouched():
    """The test_p2w4_tools_h shape: load, then write, with no monkeypatch."""
    before = _snapshot(_CHECKOUT_LOG)
    copy = _fresh_copy()
    marker = f"S144-Q-124 probe {next(_SEQ)}"
    copy._log_line(marker)
    assert _snapshot(_CHECKOUT_LOG) == before, (
        "a late watchdog copy appended to the checkout's "
        "logs/cost_health_watchdog.log")
    assert marker in copy._LOG.read_text(encoding="utf-8")


def test_a_registered_late_copy_passes_the_mechanism_check():
    """The test_log_appenders shape: a copy registered in sys.modules after the
    session redirect ran must still satisfy the census mechanism check."""
    from tests import test_suite_does_not_write_live_tree as census
    copy = _fresh_copy()
    sys.modules[copy.__name__] = copy
    try:
        bad = census._check_spec_loaded_tool_logs()
    finally:
        del sys.modules[copy.__name__]
    assert bad == [], bad


def test_env_names_the_log_and_blank_or_unset_keeps_the_default(tmp_path,
                                                                monkeypatch):
    target = tmp_path / "elsewhere" / "chw.log"
    monkeypatch.setenv(_ENV, str(target))
    assert _fresh_copy()._LOG == target

    default = _TOOL.parent.parent / "logs" / "cost_health_watchdog.log"
    monkeypatch.setenv(_ENV, "   ")
    assert _fresh_copy()._LOG == default
    monkeypatch.delenv(_ENV)
    assert _fresh_copy()._LOG == default
