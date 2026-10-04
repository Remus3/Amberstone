"""RM-244: the six residual dashboard/routes_state.py defects still live at HEAD.

(b) was closed earlier by RM-414; this file covers (a) (c) (d) (e) (f) (g),
one test per item.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dashboard.routes_state as rs  # noqa: E402
from dashboard import api_schema  # noqa: E402

SRC = (ROOT / "dashboard" / "routes_state.py").read_text(encoding="utf-8")


def _strict_loads(s: str):
    def _refuse(tok):
        raise ValueError(f"non-JSON constant {tok}")
    return json.loads(s, parse_constant=_refuse)


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "Infinity", float("nan"),
                                 float("inf"), "1e999"])
def test_a_non_finite_override_serializes_as_strict_json(bad):
    out = rs._resolve_ds_target_stats(
        {"target_armor": bad, "target_mr": 50, "target_max_hp": "x",
         "target_bonus_hp": None}, "SR", 11)
    wire = json.dumps({"target_stats": out})
    parsed = _strict_loads(wire)  # raises on a NaN / Infinity token
    assert parsed["target_stats"]["target_armor"] == 0.0
    assert parsed["target_stats"]["target_mr"] == 50.0


@pytest.mark.parametrize("raw,want", [
    ("inf", 0.5), ("nan", 0.5), ("-inf", 0.5), ("1e9", 5.0),
    ("0", 0.1), ("-5", 0.1),
    ("abc", 0.5), ("1.0", 1.0), ("0.5", 0.5),
])
def test_c_cadence_override_has_a_ceiling(raw, want):
    with mock.patch.dict("os.environ", {"RC_STATE_CADENCE_SEC": raw}):
        assert rs._state_cadence_s() == want


def test_d_max_count_zero_returns_nothing(tmp_path):
    q = tmp_path / "agents" / "state" / "task_queue.jsonl"
    q.parent.mkdir(parents=True)
    rows = [json.dumps({"event": "completed", "ts": i,
                        "task": {"op": "agent6-full-audit-pass", "id": f"t{i}",
                                 "status": "done"}}) for i in range(3)]
    q.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with mock.patch.object(rs, "APP_DIR", tmp_path), \
            mock.patch.object(rs, "_A6_MEMO", None):
        assert len(rs._agent6_audit_outcomes_ex(max_count=3)[0]) == 3  # control
        for n in (0, -1):
            got, _ = rs._agent6_audit_outcomes_ex(max_count=n)
            assert got == [], n


def test_e_health_all_schema_matches_the_handler():
    fields = set(api_schema.HealthAllResponse.model_fields)
    assert "agent6" in fields
    assert not ({"bridge", "peers"} & fields)
    js = (ROOT / "web" / "js" / "lib" / "state_schema.js").read_text(encoding="utf-8")
    assert "@property {Object} bridge" not in js
    assert "@property {Object} peers" not in js
    assert "@property {Object} agent6" in js


def test_f_no_docstring_claims_a_one_second_ttl():
    for node in ast.walk(ast.parse(SRC)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node) or ""
            assert "1.0s TTL" not in doc, node.name
    assert "shared 1.0s TTL" not in SRC


def test_g_no_dead_enemy_team_store():
    assert "enemy_team = " not in SRC
