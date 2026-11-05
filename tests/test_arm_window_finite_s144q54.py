"""RM-1369: `RC_MC_ARM_WINDOW_S` must yield a FINITE, BOUNDED arm window.

`dashboard/_arm_confirm.window_s` kept `val if val > 0`, so `inf` (and
`1e400`, which `float()` also reads as inf) was accepted: an arm then never
expired (`expires_at = now + inf`), the arm response carried `window_s: inf`
(serialised by `json.dumps` as the non-JSON token `Infinity`) and its detail
read "armed for infs". `nan` already fell to the default, because `nan > 0`
is False; it is pinned here so a rewrite cannot lose it.

The window's job is to bound how long an unattended arm sits live (module
docstring), so a huge FINITE value such as `1e300` is the same defect in
another spelling. Decision recorded for the row's "upper cap?" clause: yes,
`MAX_WINDOW_S`. A value above it CLAMPS to it (the operator asked for a looser
perimeter and gets the loosest one allowed) rather than falling to the 60 s
default; a non-finite value is garbage and falls to the default. That is the
same rule `dashboard/routes_state._state_cadence_s` applies to
`RC_STATE_CADENCE_SEC` (RM-244(c)): non-finite to the default, then a ceiling.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard import _arm_confirm as armgate  # noqa: E402

ENV = "RC_MC_ARM_WINDOW_S"


@pytest.fixture(autouse=True)
def _clean_tables():
    armgate.clear()
    yield
    armgate.clear()


def test_the_cap_exists_and_sits_above_the_default():
    cap = getattr(armgate, "MAX_WINDOW_S", None)
    assert isinstance(cap, float)
    assert math.isfinite(cap)
    assert armgate.DEFAULT_WINDOW_S < cap


@pytest.mark.parametrize("raw", ["inf", "+inf", "-inf", "Infinity", "INF",
                                 "1e400", "nan", "NaN", "-nan"])
def test_a_non_finite_window_falls_to_the_default(monkeypatch, raw):
    monkeypatch.setenv(ENV, raw)
    got = armgate.window_s()
    assert math.isfinite(got)
    assert got == armgate.DEFAULT_WINDOW_S


@pytest.mark.parametrize("raw", ["1e300", "1e9", "86400"])
def test_a_window_above_the_cap_clamps_to_the_cap(monkeypatch, raw):
    monkeypatch.setenv(ENV, raw)
    assert armgate.window_s() == armgate.MAX_WINDOW_S


def test_the_cap_itself_is_accepted(monkeypatch):
    monkeypatch.setenv(ENV, repr(armgate.MAX_WINDOW_S))
    assert armgate.window_s() == armgate.MAX_WINDOW_S


@pytest.mark.parametrize("raw,want", [("5", 5.0), ("0.5", 0.5),
                                      (" 120 ", 120.0)])
def test_an_in_range_window_is_kept_as_given(monkeypatch, raw, want):
    monkeypatch.setenv(ENV, raw)
    assert armgate.window_s() == want


@pytest.mark.parametrize("raw", ["", "   ", "0", "-5", "abc"])
def test_unset_garbage_and_non_positive_still_take_the_default(monkeypatch,
                                                               raw):
    monkeypatch.setenv(ENV, raw)
    assert armgate.window_s() == armgate.DEFAULT_WINDOW_S


@pytest.mark.parametrize("raw", ["inf", "1e300"])
def test_an_arm_under_a_bad_window_still_expires(monkeypatch, raw):
    """End to end through arm(): the record's expiry is finite and bounded."""
    monkeypatch.setenv(ENV, raw)
    before = armgate._now()
    rec = armgate.arm("interrupt", "victims")
    assert math.isfinite(rec["expires_at"])
    assert rec["expires_at"] - before <= armgate.MAX_WINDOW_S + 1.0


def test_the_arm_route_answer_is_strict_json_under_an_inf_window(monkeypatch,
                                                               tmp_path):
    """The route echoes `window_s` and `expires_at`: both must be finite so the
    body survives a strict encoder (`allow_nan=False`), which `Infinity` does
    not."""
    from dashboard import routes_loop_control as mod

    ctl = tmp_path / "control"
    ctl.mkdir()
    monkeypatch.setattr(mod, "CONTROL_DIR", ctl)
    monkeypatch.setenv(ENV, "inf")
    status, payload = mod._handle_arm({"action": "arm",
                                       "target_action": "interrupt",
                                       "target": "victims"})
    assert status == 200
    assert payload["window_s"] == armgate.DEFAULT_WINDOW_S
    json.dumps({"window_s": payload["window_s"],
                "expires_at": payload["expires_at"]}, allow_nan=False)
    assert "inf" not in payload["detail"]
