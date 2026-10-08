"""rc_facts recognises RC-InboxResponder repointed onto the v8 inbox tick.

Item F (2026-10-07): the task's action now runs ops/loop/inbox_tick.py, and the
agreement record is the ONE v8 record (schema rc-inbox-agreement-v8, MAIN
counterparty, budget kit). The legacy runner validator rejects that record
(malformed:counterparties_unmapped), so judging a tick-action task by it
reported a false anomaly. A task whose action runs inbox_tick.py is judged by
the tick's OWN validator (inbox_tick.load_agreement); any other action keeps
the legacy validator, so the inverted polarity is unchanged for the old runner.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from tools import rc_facts

_DAY = 86400.0
_TICK_ACTION = r'"C:\X\ops\loop\inbox_tick.py"'


def _naive(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


def _world(root: Path, now: float, *, expires_in_s: float = 10 * _DAY) -> None:
    cfg = root / "ops" / "moon_sync_repos.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({
        "participants": {"EW": str(root / "ew")},
        "retired": {"LL": ["x"]},
    }), encoding="utf-8")
    rec = root / "ops" / "runtime" / "inbox_responder_agreement.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps({
        "schema": "rc-inbox-agreement-v8",
        "counterparties": ["EW", "MAIN"],
        "main": {"code": "MAIN", "outbox": str(root / "main_outbox")},
        "budget": "kit",
        "expires": _naive(now + expires_in_s),
    }), encoding="utf-8")


def _row(now: float, actions: str | None) -> dict:
    row = {
        "name": "RC-InboxResponder", "state": "Ready", "last_result": 0,
        "last_run": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 300)),
        "next_run": None, "triggers": "MSFT_TaskTimeTrigger",
    }
    if actions is not None:
        row["actions"] = actions
    return row


def _mine(items):
    return [x for x in items if "RC-InboxResponder" in x]


def test_probe_reports_task_actions():
    assert "$_.Actions" in rc_facts.TASK_PROBE_PS
    assert "actions =" in rc_facts.TASK_PROBE_PS


def test_tick_action_with_valid_v8_record_is_armed_not_anomaly(tmp_path):
    now = time.time()
    _world(tmp_path, now)
    lines, anomalies = rc_facts.task_health_lines([_row(now, _TICK_ACTION)], root=tmp_path, now=now)
    assert _mine(anomalies) == [], anomalies
    mine = _mine(lines)
    assert len(mine) == 1, lines
    assert "ARMED by agreement" in mine[0]
    assert "v8" in mine[0]


def test_tick_action_with_expired_v8_record_is_anomaly(tmp_path):
    now = time.time()
    _world(tmp_path, now, expires_in_s=-_DAY)
    _lines, anomalies = rc_facts.task_health_lines([_row(now, _TICK_ACTION)], root=tmp_path, now=now)
    mine = _mine(anomalies)
    assert len(mine) == 1 and "expired" in mine[0], anomalies


def test_tick_action_with_stop_flag_is_never_armed(tmp_path):
    now = time.time()
    _world(tmp_path, now)
    (tmp_path / "ops" / "runtime" / "INBOX_RESPONDER_STOP").write_text("stop", encoding="ascii")
    armed, detail = rc_facts.inbox_tick_agreement_state(tmp_path, now)
    assert armed is False and "stop" in detail
    lines, _a = rc_facts.task_health_lines([_row(now, _TICK_ACTION)], root=tmp_path, now=now)
    assert not any("ARMED by agreement" in ln for ln in lines), lines


def test_legacy_action_keeps_legacy_validator(tmp_path):
    # The old runner cannot read a v8 record: a task still on the runner with
    # only the v8 record present stays the anomaly (polarity unchanged).
    now = time.time()
    _world(tmp_path, now)
    _lines, anomalies = rc_facts.task_health_lines(
        [_row(now, r'"C:\X\tools\inbox_responder_runner.py" --cycle')], root=tmp_path, now=now)
    assert len(_mine(anomalies)) == 1, anomalies
