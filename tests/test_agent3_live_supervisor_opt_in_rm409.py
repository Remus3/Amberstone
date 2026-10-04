"""RM-409: the agent3 file-task tests mutate whatever answers on :8890, so they
must be OPT-IN, never gated on a liveness probe.

Census of the candidate population (re-derived 2026-10-03, predicate widened to
:8888/:8889/:8890/:8860/:2999, restart_trigger, ops/runtime, urlopen,
create_connection; over agents/agent3_testing/suite AND tools/tests):
  test_file_task_api.py  CONFIRMED live mutator (POST file-task / dismiss) - gated here
  test_round14.py        read-only HEAD /api/env probe - no state written
  test_supervisor.py     hermetic since RM-170 (own free ports + state dir)
  test_agent0.py / _smoke_agent0.py  UNC path STRINGS fed to a pure evaluator
  test_agent7_parser.py  redirects the project root before writing a trigger
  tools/tests            only test_upstream_drift_check, which already redirects
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _mod():
    path = ROOT / "agents" / "agent3_testing" / "suite" / "test_file_task_api.py"
    spec = importlib.util.spec_from_file_location("rc_agent3_file_task_api_rm409", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_open_port_without_opt_in_does_not_arm():
    """The operator-box case: the REAL supervisor is up. Must skip."""
    m = _mod()
    reason = m.live_supervisor_skip_reason({}, lambda: True)
    assert reason and m.LIVE_OPT_IN_ENV in reason


def test_opt_in_with_open_port_arms():
    m = _mod()
    assert m.live_supervisor_skip_reason({m.LIVE_OPT_IN_ENV: "1"}, lambda: True) is None


def test_opt_in_with_closed_port_skips():
    m = _mod()
    assert "not running" in m.live_supervisor_skip_reason(
        {m.LIVE_OPT_IN_ENV: "1"}, lambda: False)


def test_port_is_not_probed_without_opt_in():
    m = _mod()
    probed = []
    m.live_supervisor_skip_reason({}, lambda: probed.append(1) or True)
    assert probed == []
