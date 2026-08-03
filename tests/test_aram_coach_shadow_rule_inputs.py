"""Rule-input instrumentation on the ARAM shadow row (S4 Step 0).

The ARAM deterministic-vs-Haiku agreement sits at 73 percent and 98.6 percent of
the disagreements are EXACTLY one ladder tier apart - the signature of the one
one-tier operator in core.aram_action_rule, the wave_pct shift. That hypothesis
cannot be tested against the shadow log today: the row schema is
ts / mode / champ / enemy_comp / deterministic / live_haiku and carries NONE of
the raw rule inputs, so no mismatch can be attributed to the state that produced
it.

These tests pin the raw decide_action inputs as top-level shadow columns:
hp_pct / wave_pct / low_enemy_count (passed through from the assembler) plus
lc_hp_pct (derived here from the liveclient tick, the only one of the four
reachable from the current call signature).

Observability only. The blocks, the dedup signature, and therefore which rows
get written at all, must be byte-for-byte what they were.
"""

from __future__ import annotations

import json

from core.aram_coach_shadow import _BLOCK_KEYS, log_aram_coach

_NOW = "2026-08-02T00:00:00+00:00"

_DET = {
    "action": "POKE",
    "fight_rule": "Respect Ashe R before you step up",
    "risk": "Ashe R stun",
    "reset_item": "No fountain trips; save toward Kraken Slayer (900g remaining).",
    "item_build": "Blade of The Ruined King -> Kraken Slayer",
    "item_build_reasons": {"Kraken Slayer": "third-hit true damage"},
    "choices": [{"key": "A", "label": "Poke", "source_tag": "synth"}],
    "item_extra": "omit",
    "objective": "Poke the enemy tower.",
}

_LIVE = {
    "action": "TRADE",
    "fight_rule": "E is up; trade on their W cooldown.",
    "risk": "Annie stun stacks.",
    "reset_item": "No fountain; next BorK (900g remaining).",
    "item_build": "Blade of The Ruined King -> Kraken Slayer",
    "item_build_reasons": {"BorK": "on-hit DPS"},
    "choices": [{"key": "A", "label": "Trade", "source_tag": "haiku"}],
    "item_extra": "Pot: Refillable",
    "objective": "Defend your T1.",
}

_LC = {
    "champion": "Kalista",
    "enemy_team": ["Ashe", "Annie"],
    "hp": 850,
    "hp_max": 1000,
}

_RULE_INPUT_KEYS = ("hp_pct", "wave_pct", "low_enemy_count", "lc_hp_pct")


def _rows(path):
    return [
        json.loads(ln)
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]


def _one_row(path):
    rows = _rows(path)
    assert len(rows) == 1, f"expected exactly one shadow row, got {len(rows)}"
    return rows[0]


# ---------------------------------------------------------------------------
# Present when the inputs exist.
# ---------------------------------------------------------------------------

def test_records_the_raw_rule_inputs_when_supplied(tmp_path):
    target = tmp_path / "aram_coach_shadow.jsonl"

    rec = log_aram_coach(
        _DET, _LIVE, _LC, "aram", path=target, now_iso=_NOW,
        hp_pct=42.5, wave_pct=70, low_enemy_count=2,
    )

    assert rec is not None
    row = _one_row(target)
    assert row["hp_pct"] == 42.5
    assert row["wave_pct"] == 70.0
    assert row["low_enemy_count"] == 2


def test_lc_hp_pct_is_derived_from_the_liveclient_tick(tmp_path):
    """The one rule input reachable from the CURRENT signature.

    Named apart from hp_pct on purpose: the assembler prefers the coach
    artifact's own hp_pct, so an lc-derived percent is a different provenance and
    must never be recorded under the name of the value the rule actually used.
    """
    target = tmp_path / "aram_coach_shadow.jsonl"

    log_aram_coach(_DET, _LIVE, _LC, "aram", path=target, now_iso=_NOW)

    assert _one_row(target)["lc_hp_pct"] == 85.0


# ---------------------------------------------------------------------------
# Absent / malformed inputs degrade to null - never raise, never fabricate.
# ---------------------------------------------------------------------------

def test_rule_inputs_are_null_when_not_supplied(tmp_path):
    target = tmp_path / "aram_coach_shadow.jsonl"

    log_aram_coach(_DET, _LIVE, _LC, "aram", path=target, now_iso=_NOW)

    row = _one_row(target)
    for key in ("hp_pct", "wave_pct", "low_enemy_count"):
        assert key in row, f"{key} column missing - an instrumented row must carry it"
        assert row[key] is None


def test_malformed_rule_inputs_degrade_to_null(tmp_path):
    """Strings, bools and containers are not measurements; they read as absent.

    The bool case matters: True is an int in Python, so a naive isinstance check
    would record low_enemy_count=1 out of a flag.
    """
    target = tmp_path / "aram_coach_shadow.jsonl"

    log_aram_coach(
        _DET, _LIVE, _LC, "aram", path=target, now_iso=_NOW,
        hp_pct="80", wave_pct=[], low_enemy_count=True,
    )

    row = _one_row(target)
    assert row["hp_pct"] is None
    assert row["wave_pct"] is None
    assert row["low_enemy_count"] is None


def test_non_finite_rule_inputs_do_not_corrupt_the_log(tmp_path):
    """NaN / Infinity serialize as bare tokens that are not valid JSON.

    json.loads accepts them back, but every other reader of this file does not,
    so a single garbage tick must not poison the corpus.
    """
    target = tmp_path / "aram_coach_shadow.jsonl"

    log_aram_coach(
        _DET, _LIVE, _LC, "aram", path=target, now_iso=_NOW,
        hp_pct=float("nan"), wave_pct=float("inf"), low_enemy_count=1,
    )

    raw = target.read_text(encoding="utf-8")
    assert "NaN" not in raw and "Infinity" not in raw
    row = _one_row(target)
    assert row["hp_pct"] is None
    assert row["wave_pct"] is None
    assert row["low_enemy_count"] == 1


def test_lc_hp_pct_is_null_when_the_tick_carries_no_hp(tmp_path):
    target = tmp_path / "aram_coach_shadow.jsonl"

    log_aram_coach(
        _DET, _LIVE,
        {"champion": "Kalista", "enemy_team": ["Ashe"], "hp": 500, "hp_max": 0},
        "aram", path=target, now_iso=_NOW,
    )

    assert _one_row(target)["lc_hp_pct"] is None


# ---------------------------------------------------------------------------
# Zero behavioural delta: same blocks, same dedup, same rows written.
# ---------------------------------------------------------------------------

def test_new_columns_do_not_leak_into_either_block(tmp_path):
    target = tmp_path / "aram_coach_shadow.jsonl"

    log_aram_coach(
        _DET, _LIVE, _LC, "aram", path=target, now_iso=_NOW,
        hp_pct=42.5, wave_pct=70, low_enemy_count=2,
    )

    row = _one_row(target)
    assert row["deterministic"] == _DET
    assert row["live_haiku"] == _LIVE
    assert set(row["deterministic"]) == set(_BLOCK_KEYS)


def test_rule_inputs_are_not_part_of_the_dedup_signature(tmp_path):
    """A changed hp_pct on an unchanged coarse state must NOT re-log.

    The dedup signature decides which ticks reach the file at all. Folding an
    observability column into it would change the corpus itself, which is
    exactly the delta this slice promises not to introduce.
    """
    target = tmp_path / "aram_coach_shadow.jsonl"

    first = log_aram_coach(
        _DET, _LIVE, _LC, "aram", path=target, now_iso=_NOW, hp_pct=90.0,
    )
    second = log_aram_coach(
        _DET, _LIVE, _LC, "aram", path=target, now_iso=_NOW, hp_pct=10.0,
    )

    assert first is not None
    assert second is None, "a rule-input change must not defeat coarse-state dedup"
    assert len(_rows(target)) == 1


def test_writer_stays_fail_soft_on_a_garbage_tick(tmp_path):
    """The contract that outranks every column here: never raise on a coach tick."""
    target = tmp_path / "aram_coach_shadow.jsonl"

    assert log_aram_coach(
        _DET, _LIVE, object(), "aram", path=target,
        hp_pct=object(), wave_pct=object(), low_enemy_count=object(),
    ) is None


# ---------------------------------------------------------------------------
# Backward compatibility: the historical corpus predates every column above.
# ---------------------------------------------------------------------------

def test_old_shape_rows_still_read_alongside_new_ones(tmp_path):
    """tools.aram_shadow_report must score a mixed-schema log unchanged."""
    from tools import aram_shadow_report as rep

    old_row = {
        "ts": _NOW, "mode": "aram", "champ": "Kalista",
        "enemy_comp": ["Ashe", "Annie"],
        "deterministic": _DET, "live_haiku": _LIVE,
    }
    log = tmp_path / "mixed.jsonl"

    target = tmp_path / "new.jsonl"
    log_aram_coach(
        _DET, _LIVE, _LC, "aram", path=target, now_iso=_NOW,
        hp_pct=42.5, wave_pct=70, low_enemy_count=2,
    )
    new_row = _one_row(target)
    assert set(new_row) > set(old_row), "the new row must be a strict superset"

    log.write_text(
        json.dumps(old_row) + "\n" + json.dumps(new_row) + "\n", encoding="utf-8",
    )

    report = rep.build_report(log)
    assert report["total"] == 2
    assert report["action"]["comparable"] == 2
    # Identical blocks on both rows: the verdicts must score identically, which
    # proves the extra columns are inert to every consumer of this file.
    assert report["action"]["agree"] in (0, 2)
    assert report["choices"]["det_instrumented"] == 2
