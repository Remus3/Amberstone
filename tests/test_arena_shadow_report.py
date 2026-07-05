"""ORUN1 - tools.arena_shadow_report tests.

Pins the deterministic-vs-Haiku action agreement math, the dead-state de-bias
routing, the fail-soft awaiting-accrual empty-state, the min-sample gate, and
the JSON / CLI shape - all over synthetic in-memory / tmp shadow logs (NO
dependency on the live data/ file, no writes to data/).
"""
from __future__ import annotations

import json

from tools import arena_shadow_report as rep


def _row(champ="Kaisa", rnd="~30", det_action="FIGHT", haiku_action="FIGHT",
         det_strategy="Even fight - commit on your spike", haiku_strategy="Go"):
    """Build one synthetic shadow row in the exact writer schema."""
    return {
        "ts": "2026-07-05T00:00:00+00:00",
        "mode": "arena",
        "champ": champ,
        "round": rnd,
        "enemy_comp": [],
        "deterministic": {
            "action": det_action, "round_strategy": det_strategy,
            "fight_rule": "", "augment_advice": "", "anvil_advice": "",
            "target_priority": "", "risk": "",
        },
        "live_haiku": {
            "action": haiku_action, "round_strategy": haiku_strategy,
            "fight_rule": "", "augment_advice": "", "anvil_advice": "",
            "target_priority": "", "risk": "",
        },
    }


def _dead_row(champ="Kaisa", rnd="~30"):
    """A dead-state tick shaped like the live log: HP-0% deterministic + a
    SPECTATE / 'You are dead' Haiku side."""
    return _row(
        champ=champ, rnd=rnd,
        det_action="KITE BACK",
        det_strategy="Your HP 0%; 3 teams left - kite, disengage, survive",
        haiku_action="SPECTATE ROUND",
        haiku_strategy="You are dead. Watch positioning for next respawn.",
    )


def _write(path, records):
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


# --- fail-soft load -------------------------------------------------------

def test_load_jsonl_missing_file(tmp_path):
    assert rep.load_jsonl(tmp_path / "nope.jsonl") == []


def test_load_jsonl_skips_bad_lines(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"a":1}\nNOT JSON\n\n{"b":2}\n', encoding="utf-8")
    assert rep.load_jsonl(p) == [{"a": 1}, {"b": 2}]


def test_absent_file_awaiting_accrual(tmp_path):
    report = rep.build_report(tmp_path / "absent.jsonl")
    assert report["coverage"]["total"] == 0
    fr = report["flip_readiness"]
    assert fr["ready"] is False
    assert fr["state"] == "awaiting_accrual"


def test_empty_file_awaiting_accrual(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    report = rep.build_report(p)
    assert report["coverage"]["total"] == 0
    assert report["flip_readiness"]["state"] == "awaiting_accrual"


# --- dead-state de-bias ---------------------------------------------------

def test_dead_state_detection_both_signals():
    # Haiku SPECTATE alone
    assert rep.is_dead_state(_row(haiku_action="SPECTATE ROUND")) is True
    # deterministic HP 0% alone (Haiku action a normal verdict)
    assert rep.is_dead_state(_row(
        haiku_action="FIGHT",
        det_strategy="Your HP 0%; kite, disengage, survive")) is True
    # a genuine live-fight tick is NOT dead-state
    assert rep.is_dead_state(_row(
        det_action="FIGHT", haiku_action="FIGHT",
        det_strategy="Even fight - commit",
        haiku_strategy="Engage now")) is False


def test_dead_state_routed_out_of_agreement(tmp_path):
    # 2 agreeing live-fight + 1 disagreeing live-fight + 3 dead-state.
    p = tmp_path / "m.jsonl"
    _write(p, [
        _row(det_action="FIGHT", haiku_action="FIGHT"),
        _row(det_action="FIGHT", haiku_action="FIGHT"),
        _row(det_action="KITE BACK", haiku_action="ALL IN"),
        _dead_row(),
        _dead_row(),
        _dead_row(),
    ])
    agr = rep.summarize_agreement(rep.load_jsonl(p))
    assert agr["dead_state"] == 3          # routed out
    assert agr["comparable"] == 3          # only live-fight rounds scored
    assert agr["agree"] == 2               # exact numerator
    assert agr["agreement_rate"] == round(2 / 3, 4)


def test_coverage_partition_live_fight_vs_dead(tmp_path):
    p = tmp_path / "c.jsonl"
    _write(p, [
        _row(champ="Kaisa", rnd="~10"),
        _row(champ="Jinx", rnd="~20"),
        _dead_row(champ="Kaisa", rnd="~30"),
    ])
    cov = rep._coverage_block(rep.load_jsonl(p))
    assert cov["total"] == 3
    assert cov["distinct_champs"] == 2
    assert cov["distinct_rounds"] == 3
    assert cov["live_fight"] == 2
    assert cov["dead_state"] == 1
    # partition is exact
    assert cov["live_fight"] + cov["dead_state"] == cov["total"]


# --- action normalization -------------------------------------------------

def test_action_normalization_case_and_whitespace():
    pair = rep.record_agreement(_row(det_action="kite  back",
                                     haiku_action=" KITE BACK "))
    assert pair is not None
    assert pair["det"] == "KITE BACK"
    assert pair["haiku"] == "KITE BACK"
    assert pair["agree"] is True


def test_missing_action_is_unclassified(tmp_path):
    p = tmp_path / "u.jsonl"
    _write(p, [
        _row(det_action="FIGHT", haiku_action=""),   # haiku blank -> excluded
        _row(det_action="FIGHT", haiku_action="FIGHT"),
    ])
    agr = rep.summarize_agreement(rep.load_jsonl(p))
    assert agr["unclassified"] == 1
    assert agr["comparable"] == 1
    assert agr["agree"] == 1


# --- min-sample gate ------------------------------------------------------

def test_below_min_sample_awaiting(tmp_path):
    p = tmp_path / "below.jsonl"
    _write(p, [_row(det_action="FIGHT", haiku_action="FIGHT") for _ in range(5)])
    report = rep.build_report(p, min_sample=20)
    fr = report["flip_readiness"]
    assert fr["ready"] is False
    assert fr["state"] == "awaiting_accrual"
    assert fr["comparable"] == 5


def test_at_min_sample_ready(tmp_path):
    p = tmp_path / "at.jsonl"
    # 20 live-fight rounds, all agreeing -> gate met at min_sample=20.
    _write(p, [_row(champ=f"C{i}", det_action="FIGHT", haiku_action="FIGHT")
               for i in range(20)])
    report = rep.build_report(p, min_sample=20)
    fr = report["flip_readiness"]
    assert fr["ready"] is True
    assert fr["state"] == "sample_met"
    assert fr["comparable"] == 20
    assert fr["agreement_pct"] == 100


def test_dead_state_does_not_count_toward_gate(tmp_path):
    # 30 dead-state rows but zero live-fight -> gate still not met.
    p = tmp_path / "deadonly.jsonl"
    _write(p, [_dead_row(champ=f"C{i}") for i in range(30)])
    report = rep.build_report(p, min_sample=20)
    fr = report["flip_readiness"]
    assert fr["ready"] is False
    assert fr["state"] == "awaiting_accrual"
    assert report["coverage"]["dead_state"] == 30
    assert report["agreement"]["comparable"] == 0


# --- report / CLI shape ---------------------------------------------------

def test_build_report_json_shape(tmp_path):
    p = tmp_path / "s.jsonl"
    _write(p, [_row(det_action="FIGHT", haiku_action="ALL IN")])
    report = rep.build_report(p, min_sample=20)
    assert report["schema"] == "arena_shadow_report/v1"
    assert set(report) >= {
        "schema", "path", "min_sample", "coverage", "agreement",
        "flip_readiness",
    }
    assert set(report["coverage"]) >= {
        "total", "distinct_champs", "distinct_rounds", "live_fight",
        "dead_state",
    }
    assert set(report["agreement"]) >= {
        "comparable", "agree", "agreement_rate", "dead_state", "unclassified",
        "by_champion", "confusion",
    }
    # confusion carries the single FIGHT->ALL IN mismatch
    assert report["agreement"]["confusion"] == [
        {"det": "FIGHT", "haiku": "ALL IN", "n": 1, "agree": False}
    ]


def test_main_json_exit_zero_absent(tmp_path, capsys):
    rc = rep.main(["--path", str(tmp_path / "absent.jsonl"), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "arena_shadow_report/v1"
    assert out["flip_readiness"]["state"] == "awaiting_accrual"


def test_main_human_exit_zero(tmp_path, capsys):
    p = tmp_path / "h.jsonl"
    _write(p, [_row(det_action="FIGHT", haiku_action="FIGHT")])
    rc = rep.main(["--path", str(p)])
    assert rc == 0
    text = capsys.readouterr().out
    assert "arena shadow" in text
    assert "flip-readiness" in text


def test_main_min_sample_override(tmp_path, capsys):
    p = tmp_path / "o.jsonl"
    _write(p, [_row(champ=f"C{i}", det_action="FIGHT", haiku_action="FIGHT")
               for i in range(3)])
    # override the gate down to 3 -> sample met on only 3 rounds.
    rc = rep.main(["--path", str(p), "--min-sample", "3", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["flip_readiness"]["ready"] is True
    assert out["flip_readiness"]["comparable"] == 3
