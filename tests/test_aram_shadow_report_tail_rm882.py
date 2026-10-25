"""RM-882 - the ARAM flip report measures the R78 tail fields it gates.

``tools/aram_shadow_report.py`` scored action / fight_rule / risk / reset_item /
item_build / item_build_reasons / choices, but every shadow row since R78
(``8f013ee4``) also carries ``item_extra`` and ``objective`` on both sides
(``core/aram_coach_shadow.py`` ``_BLOCK_KEYS``), and gated row G3-14 is the flip
of exactly those two fields. Two traps sit in those fields:

* the live ARAM prompt has no Objective output field (``coaches/aram_coach.py``
  ``_SYSTEM`` OUTPUT FORMAT) and ``parse_fields`` never asks for "objective",
  so live ``objective`` is always "" - a report that divided by that would
  print 0 % for a field with NO live baseline;
* the deterministic ``item_extra`` is the literal "omit" on every row by design
  (``core/aram_deterministic_coach.py`` ``_safe_item_extra``), so every match
  is omit-vs-omit and the ratio only counts how often Haiku also said "omit" -
  a degenerate dimension, not agreement (the verifier's refutation of the
  first cut, which printed 154/218 = 0.7064 as "meets 70% bar").

This file pins:

1. field presence covers both fields under the same dead-state and
   enemy-less (RM-852) exclusions as every other field;
2. "no live baseline", "no comparable rows" and "degenerate: <side> side
   constant "<value>"" each carry ``agreement_rate`` None (never 0.0, never a
   readiness rate), stay out of the tail gate math and out of the hint's
   percentages;
3. a varied field with both sides populated reports the EXACT and the
   case-folded ratio, and the gate uses the exact one; "omitted" is not "omit";
4. every pre-RM-882 key and number stays as it was (additive only).
"""
from __future__ import annotations

import json

from tools import aram_shadow_report as rep

_ENEMIES = ["Ashe", "Annie", "Leona", "Malphite", "Sett"]
_OBJ = "Poke the enemy tower; do not chase past T1 range without allies."


def _write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n",
                    encoding="utf-8")


def _row(det_action="FALL BACK", live_action="back off", *, det_extra="omit",
         live_extra="", det_obj=_OBJ, live_obj="", enemies=_ENEMIES):
    """One R78-shaped shadow row (both blocks carry item_extra + objective)."""
    row = {
        "mode": "aram", "champ": "Lux",
        "deterministic": {"action": det_action, "item_extra": det_extra,
                          "objective": det_obj},
        "live_haiku": {"action": live_action, "item_extra": live_extra,
                       "objective": live_obj},
    }
    if enemies is not None:
        row["enemy_comp"] = enemies
    return row


def _paired(det_vals, live_vals, **kw):
    """Rows whose item_extra pairs det_vals[i] with live_vals[i]."""
    return [_row(det_extra=d, live_extra=lv, **kw)
            for d, lv in zip(det_vals, live_vals)]


# ---------------------------------------------------------------------------
# 1. Field presence covers the two R78 tail fields.
# ---------------------------------------------------------------------------


def test_field_presence_covers_item_extra_and_objective(tmp_path):
    p = tmp_path / "s.jsonl"
    _write(p, [
        _row(live_extra="omit"),
        _row(live_extra=""),
        # dead-state: Haiku populated both tail fields, must not count
        _row(live_action="WAIT RESPAWN", live_extra="Shard: X", live_obj="x"),
        # enemy-less: not a game tick (RM-852), must not count
        _row(live_extra="omit", live_obj="Push", enemies=[]),
    ])
    fp = rep.build_report(p)["field_presence"]
    assert fp["item_extra"] == {"both": 1, "det_only": 1, "live_only": 0,
                                "neither": 0}
    assert fp["objective"] == {"both": 0, "det_only": 2, "live_only": 0,
                               "neither": 0}


# ---------------------------------------------------------------------------
# 2a. "no live baseline", never 0 %.
# ---------------------------------------------------------------------------


def test_objective_with_live_always_empty_is_no_live_baseline(tmp_path):
    p = tmp_path / "s.jsonl"
    _write(p, [_row(live_extra="omit") for _ in range(3)])
    r = rep.build_report(p)
    obj = r["tail_agreement"]["objective"]
    assert obj["baseline"] == "no live baseline"
    assert obj["agreement_rate"] is None
    assert obj["agreement_rate_exact"] is None
    assert obj["comparable"] == 0
    assert obj["live_present"] == 0
    assert obj["det_present"] == 3
    gate = r["tail_agreement"]["gate"]
    assert gate["excluded_no_live_baseline"] == ["objective"]
    assert "objective" not in gate["measured"]
    hint = r["flip_ready_hint"]
    assert "objective no live baseline" in hint
    assert "objective agreement" not in hint
    assert "excluded from gate math" in hint


def test_no_live_baseline_field_does_not_drag_the_tail_gate(tmp_path):
    """item_extra agrees 100 % on varied values; the baseline-less objective
    must not pull the tail gate to "not met" (it would, scored as 0 %)."""
    p = tmp_path / "s.jsonl"
    vals = ["Pot: Ornn", "Shard: Attack Speed", "Pot: Mana", "Shard: Precision"]
    _write(p, _paired(vals, vals))
    gate = rep.build_report(p)["tail_agreement"]["gate"]
    assert gate["measured"] == ["item_extra"]
    assert gate["met"] is True


def test_live_objective_only_on_excluded_rows_is_still_no_baseline(tmp_path):
    """A live objective on a dead-state or enemy-less row is not a baseline."""
    p = tmp_path / "s.jsonl"
    _write(p, [
        _row(),
        _row(live_action="WAIT RESPAWN", live_obj="Push now"),
        _row(live_obj="Push now", enemies=[]),
        _row(live_obj="Push now", enemies=None),
    ])
    r = rep.build_report(p)
    assert r["enemy_less_excluded"] == 2
    assert r["tail_agreement"]["objective"]["baseline"] == "no live baseline"


def test_human_output_says_no_live_baseline_not_zero(tmp_path, capsys):
    p = tmp_path / "s.jsonl"
    _write(p, [_row(live_extra="omit")])
    assert rep.main(["--path", str(p)]) == 0
    out = capsys.readouterr().out
    assert "[tail_agreement]" in out
    obj_lines = [ln for ln in out.splitlines()
                 if ln.strip().startswith("objective:")
                 and "both=" not in ln]
    assert len(obj_lines) == 1
    assert "no live baseline" in obj_lines[0]
    assert "0/0" not in obj_lines[0]
    assert "0.0" not in obj_lines[0]


def test_json_carries_null_rate_for_no_live_baseline(tmp_path, capsys):
    p = tmp_path / "s.jsonl"
    _write(p, [_row(live_extra="omit")])
    assert rep.main(["--path", str(p), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    obj = out["tail_agreement"]["objective"]
    assert obj["agreement_rate"] is None
    assert obj["baseline"] == "no live baseline"


# ---------------------------------------------------------------------------
# 2b. Degenerate: a constant side is not agreement (the verifier refutation).
# ---------------------------------------------------------------------------


def test_constant_deterministic_side_is_degenerate_not_flip_ready(tmp_path):
    """The live shape in miniature: the deterministic side is "omit" on every
    row and Haiku mostly says "omit" too. Folded that is 8/10 = 0.8, which a
    naive gate calls ready; it must read degenerate and carry no rate."""
    p = tmp_path / "s.jsonl"
    live = ["omit"] * 7 + ["Omit", "Shard: Attack Speed", "Pot: Ornn"]
    _write(p, _paired(["omit"] * 10, live))
    r = rep.build_report(p)
    ie = r["tail_agreement"]["item_extra"]
    assert ie["baseline"] == "degenerate"
    assert ie["degenerate"] == 'deterministic side constant "omit"'
    assert ie["agreement_rate"] is None
    assert ie["agreement_rate_exact"] is None
    assert ie["gate_met"] is None
    assert (ie["det_distinct"], ie["live_distinct"]) == (1, 3)
    # the raw counts stay visible for the reader
    assert (ie["agree"], ie["agree_exact"], ie["comparable"]) == (8, 7, 10)
    gate = r["tail_agreement"]["gate"]
    assert gate["excluded_degenerate"] == ["item_extra"]
    assert gate["measured"] == []
    assert gate["met"] is None
    hint = r["flip_ready_hint"]
    assert 'item_extra degenerate: deterministic side constant "omit"' in hint
    assert "item_extra agreement" not in hint
    assert "meets 70% bar" not in hint
    assert "80%" not in hint


def test_constant_haiku_side_is_degenerate_too(tmp_path):
    p = tmp_path / "s.jsonl"
    _write(p, _paired(["Pot: Ornn", "Shard: Precision", "omit"],
                      ["omit", "omit", "omit"]))
    ie = rep.build_report(p)["tail_agreement"]["item_extra"]
    assert ie["baseline"] == "degenerate"
    assert ie["degenerate"] == 'Haiku side constant "omit"'
    assert ie["agreement_rate"] is None


def test_degenerate_constant_folds_case_and_shows_the_common_spelling(tmp_path):
    """"Omit" and "omit" are one value after folding, so a side that only
    varies by case is still constant; the note shows the commonest spelling."""
    p = tmp_path / "s.jsonl"
    _write(p, _paired(["omit", "omit", "Omit"],
                      ["Pot: Ornn", "omit", "Shard: X"]))
    ie = rep.build_report(p)["tail_agreement"]["item_extra"]
    assert ie["degenerate"] == 'deterministic side constant "omit"'


def test_human_output_degenerate_line_has_no_ratio(tmp_path, capsys):
    p = tmp_path / "s.jsonl"
    _write(p, _paired(["omit"] * 3, ["omit", "omit", "Pot: Ornn"]))
    assert rep.main(["--path", str(p)]) == 0
    out = capsys.readouterr().out
    line = next(ln for ln in out.splitlines()
                if ln.strip().startswith("item_extra: degenerate"))
    assert 'deterministic side constant "omit"' in line
    assert "excluded from gate math" in line
    assert "0.6667" not in line
    assert "item_extra (degenerate)" in out


# ---------------------------------------------------------------------------
# 3. Varied values on both sides -> the exact and the folded ratio.
# ---------------------------------------------------------------------------


def test_item_extra_both_sides_populated_yields_agreement_ratio(tmp_path):
    p = tmp_path / "s.jsonl"
    _write(p, _paired(
        ["Pot: Ornn", "Shard: Attack Speed", "Pot: Mana", "omit"],
        ["Pot: Ornn", "shard: attack speed ", "Shard: Precision", ""],
    ))
    ie = rep.build_report(p)["tail_agreement"]["item_extra"]
    assert ie["baseline"] == "measured"
    assert ie["degenerate"] is None
    assert ie["comparable"] == 3
    assert ie["agree"] == 2
    assert ie["agree_exact"] == 1
    assert ie["agreement_rate"] == round(2 / 3, 4)
    assert ie["agreement_rate_exact"] == round(1 / 3, 4)
    assert ie["live_present"] == 3
    assert ie["det_present"] == 4
    assert ie["gate_met"] is False


def test_gate_uses_the_exact_rate_not_the_folded_one(tmp_path):
    """Folded 8/10 = 0.8 would pass; exact 5/10 = 0.5 does not. The gate
    takes the exact (lower) rate, so case folding cannot carry a field."""
    p = tmp_path / "s.jsonl"
    det = [f"Shard: S{i}" for i in range(10)]
    live = det[:5] + [d.upper() for d in det[5:8]] + ["Pot: A", "Pot: B"]
    _write(p, _paired(det, live))
    r = rep.build_report(p)
    ie = r["tail_agreement"]["item_extra"]
    assert ie["baseline"] == "measured"
    assert (ie["agreement_rate"], ie["agreement_rate_exact"]) == (0.8, 0.5)
    assert ie["gate_met"] is False
    assert r["tail_agreement"]["gate"]["basis"] == "exact"
    assert r["tail_agreement"]["gate"]["met"] is False
    assert ("item_extra agreement 50% exact (80% case-folded) over 10 "
            "comparable rows (below 70% bar)") in r["flip_ready_hint"]


def test_omitted_is_not_omit_but_case_and_space_fold():
    """Deliberate: no synonym table. The prompt asks for the literal "omit"
    and the deterministic side emits it; "omitted" is a format deviation, and
    a synonym map could only raise agreement."""
    assert rep._norm_text("omitted") != rep._norm_text("omit")
    assert rep._norm_text("Omit (6 items + Mortal Reminder)") != "omit"
    assert rep._norm_text(" Omit ") == rep._norm_text("omit")


def test_objective_both_sides_populated_is_measured(tmp_path):
    """If the live coach ever emits an objective, the report measures it."""
    p = tmp_path / "s.jsonl"
    _write(p, [_row(live_extra="omit", live_obj=_OBJ),
               _row(live_extra="omit", det_obj="Defend your tower",
                    live_obj="Push the wave")])
    r = rep.build_report(p)
    obj = r["tail_agreement"]["objective"]
    assert obj["baseline"] == "measured"
    assert (obj["agree"], obj["comparable"]) == (1, 2)
    assert obj["agreement_rate"] == 0.5
    assert obj["agreement_rate_exact"] == 0.5
    gate = r["tail_agreement"]["gate"]
    assert gate["measured"] == ["objective"]
    assert gate["excluded_degenerate"] == ["item_extra"]
    assert gate["excluded_no_live_baseline"] == []
    assert gate["met"] is False
    assert "objective agreement 50% exact (50% case-folded) over 2" in (
        r["flip_ready_hint"])


def test_live_present_but_never_beside_det_is_no_comparable_rows(tmp_path):
    p = tmp_path / "s.jsonl"
    _write(p, [_row(det_obj="", live_obj="Push")])
    obj = rep.build_report(p)["tail_agreement"]["objective"]
    assert obj["baseline"] == "no comparable rows"
    assert obj["agreement_rate"] is None


def test_dead_state_rows_never_enter_tail_agreement(tmp_path):
    p = tmp_path / "s.jsonl"
    _write(p, [_row(live_extra="omit"),
               _row(live_action="WAIT RESPAWN", live_extra="Shard: X")])
    ie = rep.build_report(p)["tail_agreement"]["item_extra"]
    assert ie["non_dead_total"] == 1
    assert (ie["agree"], ie["comparable"]) == (1, 1)


def test_pre_r78_rows_count_as_uninstrumented(tmp_path):
    """Rows logged before R78 carry neither key: not a miss, not a baseline."""
    p = tmp_path / "s.jsonl"
    old = {"enemy_comp": _ENEMIES, "deterministic": {"action": "HOLD"},
           "live_haiku": {"action": "HOLD"}}
    _write(p, [old, _row(live_extra="omit")])
    ie = rep.build_report(p)["tail_agreement"]["item_extra"]
    assert ie["det_instrumented"] == 1
    assert ie["neither"] == 1
    assert ie["comparable"] == 1


# ---------------------------------------------------------------------------
# 4. Additive only: every pre-RM-882 key and number is unchanged.
# ---------------------------------------------------------------------------


def test_pre_rm882_keys_and_numbers_unchanged(tmp_path):
    p = tmp_path / "s.jsonl"
    _write(p, [
        _row("FALL BACK", "back off", live_extra="omit"),
        _row("TRADE", "poke him", live_extra="Pot: Ornn"),
        _row("ALL IN", "WAIT RESPAWN"),
    ])
    r = rep.build_report(p)
    assert r["schema"] == "aram_shadow_report/v1"
    assert (r["total"], r["enemy_less_excluded"], r["gated"],
            r["dead_state"], r["non_dead"]) == (3, 0, 3, 1, 2)
    assert (r["action"]["agree"], r["action"]["comparable"],
            r["action"]["dead_state_excluded"]) == (2, 2, 1)
    assert r["choices"]["non_dead_total"] == 2
    for field in ("action", "fight_rule", "risk", "reset_item", "item_build",
                  "item_build_reasons", "choices"):
        assert set(r["field_presence"][field]) == {
            "both", "det_only", "live_only", "neither"}
    assert r["field_presence"]["action"] == {
        "both": 2, "det_only": 0, "live_only": 0, "neither": 0}
    # the pre-RM-882 hint text is kept verbatim as the prefix
    assert r["flip_ready_hint"].startswith(
        "action agreement 100% over 2 comparable ticks (>=70% gate MET); "
        "deterministic choices coverage 0% over instrumented rows - NOT a "
        "flip authorization (operator gate; live Haiku-retirement stays "
        "live-gated)")


def test_tail_text_never_reads_as_the_action_gate(tmp_path):
    """The action gate string "gate MET" stays the action gate's alone: a
    tail field at 100 % must not put it in a below-gate hint."""
    p = tmp_path / "s.jsonl"
    _write(p, [_row("ALL IN", "back off", det_extra="Pot: A", live_extra="Pot: A"),
               _row("ALL IN", "fall back", det_extra="Pot: B",
                    live_extra="Pot: B")])
    hint = rep.build_report(p)["flip_ready_hint"]
    assert "below 70% gate" in hint
    assert "gate MET" not in hint
    assert "item_extra agreement 100% exact" in hint


def test_early_hints_unchanged(tmp_path):
    assert rep.build_report(tmp_path / "none.jsonl")["flip_ready_hint"] == (
        "no shadow data yet - play real ARAM games to accrue coverage")
    p = tmp_path / "s.jsonl"
    _write(p, [_row("", "", live_extra="omit")])
    assert rep.build_report(p)["flip_ready_hint"].startswith(
        "coverage accruing - no comparable action ticks yet")


def test_empty_log_tail_block_is_no_live_baseline(tmp_path):
    r = rep.build_report(tmp_path / "none.jsonl")
    for field in ("item_extra", "objective"):
        assert r["tail_agreement"][field]["baseline"] == "no live baseline"
        assert r["tail_agreement"][field]["agreement_rate"] is None
    assert r["tail_agreement"]["gate"]["met"] is None


def test_enemy_less_rows_do_not_move_tail_agreement(tmp_path):
    """RM-852 / RM-859: removing enemy-less rows leaves the tail block as is."""
    real = [_row(live_extra="omit"), _row(live_extra="Shard: X")]
    leak = [_row(live_extra="omit", live_obj=_OBJ, enemies=[])
            for _ in range(5)]
    with_leak = tmp_path / "a.jsonl"
    without = tmp_path / "b.jsonl"
    _write(with_leak, real + leak)
    _write(without, real)
    a = rep.build_report(with_leak)
    b = rep.build_report(without)
    assert a["tail_agreement"] == b["tail_agreement"]
    assert a["enemy_less_excluded"] == 5
