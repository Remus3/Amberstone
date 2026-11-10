# Hardening tests for core/objective_playbook.py (s144 true-audit, S144-T-748..752).
#
# The playbook row is built on the live SR coach tick from the eta-sorted
# next_callouts list, the project_lead read and the vision_state.json fog
# summary. vision_state.json is read with json.loads, which accepts NaN and
# Infinity, so a non-finite count is a real input. Each test below names the
# weakness it pins; the original truth table lives in tests/test_objective_playbook.py.
from __future__ import annotations

import json
import logging
import math

import pytest

import core.objective_playbook as op

_LOGGER = "rc.objective_playbook"


def _co(tag: str, eta_s: object) -> dict:
    """Minimal objective callout row as next_callouts emits it."""
    return {"tag": tag, "line": f"{tag} line", "eta_s": eta_s, "kind": "objective"}


_AHEAD = {"state": "ahead"}
_EVEN = {"state": "even"}


# --- S144-T-748: a non-finite vision count read as 0, never loses the row ----

@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_count_non_finite_reads_zero(value: float) -> None:
    assert op._count({"k": value}, "k") == 0


@pytest.mark.parametrize("key", ["missing_count", "dead_count"])
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_vision_count_keeps_the_base_row(key: str, value: float) -> None:
    out = op.playbook_callout([_co("dragon", 30.0)], _AHEAD, {key: value}, "mid")
    assert out is not None
    assert out["line"] == op.OBJECTIVE_PLAYBOOK[("dragon", "ahead")]


def test_json_nan_summary_from_vision_state_keeps_the_row() -> None:
    # The exact bytes json.loads accepts from a vision_state.json writer.
    summary = json.loads('{"missing_count": NaN, "dead_count": Infinity}')
    out = op.playbook_callout([_co("baron", 10.0)], _EVEN, summary, "mid")
    assert out is not None
    assert out["line"] == op.OBJECTIVE_PLAYBOOK[("baron", "even")]


def test_finite_counts_beside_a_nan_still_upgrade() -> None:
    # A NaN dead_count must not hide a real missing_count of 4.
    summary = {"dead_count": math.nan, "missing_count": 4}
    out = op.playbook_callout([_co("dragon", 20.0)], _AHEAD, summary, "mid")
    assert out is not None
    assert out["line"] == "Drake: enemies missing - group and assume contest"


# --- S144-T-749: only a finite real ETA is "near" -----------------------------

@pytest.mark.parametrize("eta", [-math.inf, math.nan, math.inf])
def test_is_near_rejects_non_finite(eta: float) -> None:
    assert op._is_near(eta) is False


def test_is_near_keeps_finite_contract() -> None:
    assert op._is_near(-600.0) is True
    assert op._is_near(0) is True
    assert op._is_near(60.0) is True
    assert op._is_near(60.5) is False


# --- S144-T-750: a schedule row with junk timing never becomes a directive ---

@pytest.mark.parametrize("eta", [None, math.nan, math.inf, -math.inf, "30", True, [5]])
def test_row_with_junk_eta_is_skipped_for_the_next_covered_row(eta: object) -> None:
    rows = [_co("dragon", eta), _co("herald", 45.0)]
    out = op.playbook_callout(rows, _EVEN, None, "mid")
    assert out is not None
    assert out["tag"] == "playbook_herald"
    assert out["eta_s"] == 45.0


@pytest.mark.parametrize("eta", [None, math.nan, "30", False])
def test_only_junk_eta_rows_give_no_row(eta: object) -> None:
    assert op.playbook_callout([_co("dragon", eta)], _EVEN, None, "mid") is None


def test_valid_eta_is_passed_through_unchanged() -> None:
    out = op.playbook_callout([_co("dragon", -12.5)], _EVEN, None, "early")
    assert out is not None
    assert out["eta_s"] == -12.5
    out = op.playbook_callout([_co("dragon", 300)], _EVEN, None, "early")
    assert out is not None
    assert out["eta_s"] == 300
    assert type(out["eta_s"]) is int


# --- S144-T-751: the public tables are read-only ------------------------------

@pytest.mark.parametrize("name", ["OBJECTIVE_PLAYBOOK", "LATE_OBJECTIVE_PLAYBOOK"])
def test_public_tables_cannot_be_mutated(name: str) -> None:
    table = getattr(op, name)
    with pytest.raises(TypeError):
        table[("dragon", "ahead")] = "hijacked"  # type: ignore[index]
    with pytest.raises((TypeError, AttributeError)):
        table.clear()  # type: ignore[attr-defined]
    assert table[("dragon", "ahead")] != "hijacked"


def test_tables_keep_their_entries() -> None:
    assert len(op.OBJECTIVE_PLAYBOOK) == 10
    assert len(op.LATE_OBJECTIVE_PLAYBOOK) == 6
    assert op.OBJECTIVE_PLAYBOOK[("elder", "*")] == "Elder: group as five, full vision - no greed"


# --- S144-T-752: the tag is canonical and the hot-path catch is not silent ----

class _OddTag(str):
    """A str subclass equal to "dragon" whose str() lies."""

    def __str__(self) -> str:  # pragma: no cover - called by the old code only
        return "x<script>"


def test_output_tag_is_the_canonical_constant() -> None:
    out = op.playbook_callout([_co(_OddTag("dragon"), 30.0)], _EVEN, None, "mid")
    assert out is not None
    assert out["tag"] == "playbook_dragon"
    assert type(out["tag"]) is str
    assert out["line"].startswith("Drake:")


def test_unexpected_failure_is_logged_by_type_once(monkeypatch, caplog) -> None:
    def _boom(*_a, **_k):
        raise RuntimeError("raw-detail-that-must-not-be-logged")

    monkeypatch.setattr(op, "_select_objective", _boom)
    monkeypatch.setattr(op, "_LOGGED_FAILURES", set())
    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        assert op.playbook_callout([_co("dragon", 1.0)], _EVEN, None, "mid") is None
        assert op.playbook_callout([_co("dragon", 1.0)], _EVEN, None, "mid") is None
    records = [r for r in caplog.records if r.name == _LOGGER]
    assert len(records) == 1
    text = records[0].getMessage()
    assert "RuntimeError" in text
    assert "raw-detail" not in text
    assert records[0].exc_info is None
