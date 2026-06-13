"""P2 cycle-14 slice-A regression tests - cross-Claude BRIDGE family.

Security-focused audit of the bridge tooling. Each test pins a defect the
slice-A audit found and fixed:

  1. Non-finite cost token leak: a peer-controlled `claude --print` result
     with `total_cost_usd: Infinity` (json.loads accepts the bare Infinity /
     NaN tokens by default) used to propagate inf into
     state["tokens_used_today_usd"], which the watcher then serialized into
     bridge_watcher_health.json as a bare `Infinity` JSON token - invalid for
     strict readers (browser JSON.parse, /api/health/all roll-up). The fix
     isfinite-guards the cost at the single parse chokepoint
     (bridge_watcher_actions._parse_claude_json).

  2. bridge_setup.ps1 bare-py launcher: the Game-PC bootstrap ran the ping
     validator via bare `py`, which on Legion resolves to a dep-less
     pymanager runtime (documented incident). The `& py (Join-Path ...)` form
     also evades tests/test_bare_py_ban.py's regex, so it is pinned here.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import tools.bridge_watcher_actions as actions

_REPO_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# 1. Non-finite cost guard (security: bare Infinity/NaN token on the wire)
# --------------------------------------------------------------------------
def _claude_envelope(cost_token: str) -> str:
    """A claude --print --output-format json envelope whose top-level
    total_cost_usd is the given raw JSON token (Infinity / NaN / number)."""
    return (
        '{"type": "result", "total_cost_usd": ' + cost_token + ', '
        '"result": "{\\"status\\": \\"ok\\", \\"summary\\": \\"done\\", '
        '\\"body\\": {\\"answer\\": 42}}"}'
    )


def test_parse_claude_json_infinity_cost_becomes_none():
    # json.loads accepts a bare Infinity token; before the fix this flowed
    # through float() into the cost and on into health.json.
    _action, cost, err = actions._parse_claude_json(_claude_envelope("Infinity"))
    assert err is None
    assert cost is None or math.isfinite(cost), (
        f"non-finite cost leaked from parse: {cost!r}"
    )


def test_parse_claude_json_nan_cost_becomes_none():
    _action, cost, err = actions._parse_claude_json(_claude_envelope("NaN"))
    assert err is None
    assert cost is None or math.isfinite(cost), (
        f"non-finite cost leaked from parse: {cost!r}"
    )


def test_parse_claude_json_negative_infinity_cost_becomes_none():
    _action, cost, err = actions._parse_claude_json(_claude_envelope("-Infinity"))
    assert err is None
    assert cost is None or math.isfinite(cost)


def test_parse_claude_json_finite_cost_preserved():
    # Correct-input behavior MUST be preserved: a normal float still parses.
    action, cost, err = actions._parse_claude_json(_claude_envelope("0.0123"))
    assert err is None
    assert cost is not None and math.isfinite(cost)
    assert abs(cost - 0.0123) < 1e-9
    assert action["status"] == "ok"
    assert action["body"]["answer"] == 42


def test_parse_claude_json_zero_cost_is_none_unchanged():
    # Pre-existing behavior: 0.0 cost folds to None (the `or None` idiom).
    # The isfinite guard must not change this.
    _action, cost, _err = actions._parse_claude_json(_claude_envelope("0.0"))
    assert cost is None


def test_health_serialization_of_guarded_cost_is_strict_json():
    """End-to-end: a guarded cost added to a tokens total must serialize to
    JSON that a strict (allow_nan=False) reader accepts."""
    _action, cost, _err = actions._parse_claude_json(_claude_envelope("Infinity"))
    tokens_total = 0.0 + (cost or 0.0)
    # allow_nan=False raises ValueError on inf/nan; the guarded value must not.
    dumped = json.dumps({"tokens_used_today_usd": tokens_total}, allow_nan=False)
    assert "Infinity" not in dumped and "NaN" not in dumped


# --------------------------------------------------------------------------
# 2. bridge_setup.ps1 must not use the bare-py launcher
# --------------------------------------------------------------------------
def test_bridge_setup_ps1_no_bare_py_launcher():
    text = (_REPO_ROOT / "tools" / "bridge_setup.ps1").read_text(encoding="utf-8")
    # The historical offender form: `& py (Join-Path ...)` or `py <script>`.
    # Bare `py` resolves to the dep-less pymanager runtime on Legion.
    offenders = [
        ln.strip()
        for ln in text.splitlines()
        if ("& py " in ln) or ln.strip().startswith("py ")
    ]
    assert not offenders, (
        "bridge_setup.ps1 uses bare-py launcher (resolve a real interpreter "
        f"instead): {offenders}"
    )
