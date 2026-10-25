"""RM-854 - a focus-board re-logged Arena shadow row is never a second sample.

``core.arena_coach_shadow`` re-writes a row ONCE, marked
``"focus_board_relog": true``, when its focus_board column was not ready at the
first write (RM-854 a). The re-logged row has the same tick key and the same
deterministic-vs-Haiku pair; its only new data is the focus_board column. The
report's intent is the action-agreement flip gate (module docstring: "how
often the two sides already AGREE on the primary fight verdict", the
``MIN_SAMPLE`` gate counts live-fight rounds), and it never reads
``focus_board``, so a re-log must not count as a sample anywhere.

Grounded before writing (file:line at main 17ae75595):

* ``tools/arena_shadow_report.py``: ``load_jsonl`` (``:69``), ``is_dead_state``
  (``:140``), ``_coverage_block`` (``:175``, keys total / distinct_champs /
  distinct_rounds / live_fight / dead_state), ``summarize_agreement``
  (``:203``, keys comparable / agree / agreement_rate / dead_state /
  unclassified / by_champion / confusion), ``_flip_readiness`` (``:255``,
  keyed on ``coverage["total"]`` and ``agreement["comparable"]``),
  ``build_report(path, min_sample)`` (``:291``), ``main(argv)`` (``:328``).
* The row schema is the writer's (``tests/test_arena_shadow_report.py`` ``_row``
  builds the same shape); the marker is written by
  ``core/arena_coach_shadow.py`` ``log_arena_coach`` (this change), which reads
  the board through ``core.focus_board_live.board_for_lc(..., background=True)``
  after ``focus_board_live.enabled()`` (``_focus_board_column``).
"""
from __future__ import annotations

import json

from core import arena_coach_shadow as shadow
from core import focus_board_live as fbl
from tools import arena_shadow_report as rep


def _row(champ="Kaisa", rnd="~30", det_action="FIGHT", haiku_action="FIGHT",
         det_strategy="Even fight - commit on your spike"):
    return {
        "ts": "2026-10-25T00:00:00+00:00",
        "mode": "arena",
        "champ": champ,
        "round": rnd,
        "enemy_comp": [],
        "deterministic": {
            "action": det_action, "round_strategy": det_strategy,
            "fight_rule": "", "augment_advice": "", "anvil_advice": "",
            "target_priority": "", "risk": "", "choices": [],
        },
        "live_haiku": {
            "action": haiku_action, "round_strategy": "Go",
            "fight_rule": "", "augment_advice": "", "anvil_advice": "",
            "target_priority": "", "risk": "", "choices": [],
        },
        "focus_board": {"status": "pending", "board_pick": ""},
    }


def _relog(row):
    out = json.loads(json.dumps(row))
    out["focus_board"] = {"status": "ok", "board_pick": "Kaisa"}
    out["focus_board_relog"] = True
    return out


def _write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n",
                    encoding="utf-8")


def test_a_relogged_pair_counts_once(tmp_path):
    first = _row(det_action="FIGHT", haiku_action="CAMP PHASE")
    p = tmp_path / "s.jsonl"
    _write(p, [first, _relog(first)])
    report = rep.build_report(p, min_sample=1)
    cov, agr = report["coverage"], report["agreement"]
    assert cov["total"] == 1
    assert cov["live_fight"] == 1 and cov["dead_state"] == 0
    assert cov["focus_board_relogs"] == 1
    assert agr["comparable"] == 1 and agr["agree"] == 0
    assert agr["by_champion"]["Kaisa"]["comparable"] == 1
    assert agr["confusion"] == [
        {"det": "FIGHT", "haiku": "CAMP PHASE", "n": 1, "agree": False}]
    assert report["flip_readiness"]["comparable"] == 1


def test_relogs_never_reach_the_min_sample_gate(tmp_path):
    rows = []
    for i in range(10):
        r = _row(champ=f"C{i}", rnd=f"~{i}")
        rows += [r, _relog(r)]
    p = tmp_path / "g.jsonl"
    _write(p, rows)
    report = rep.build_report(p, min_sample=11)
    assert report["agreement"]["comparable"] == 10
    assert report["coverage"]["total"] == 10
    assert report["coverage"]["focus_board_relogs"] == 10
    assert report["flip_readiness"]["state"] == "awaiting_accrual"


def test_a_dead_state_relog_is_not_a_second_dead_tick(tmp_path):
    dead = _row(det_action="KITE BACK", haiku_action="SPECTATE ROUND",
                det_strategy="Your HP 0%; 3 teams left - kite, survive")
    assert rep.is_dead_state(dead)
    p = tmp_path / "d.jsonl"
    _write(p, [dead, _relog(dead)])
    report = rep.build_report(p)
    assert report["coverage"]["dead_state"] == 1
    assert report["agreement"]["dead_state"] == 1
    assert report["coverage"]["total"] == 1


def test_only_a_literal_true_marker_is_skipped():
    plain = _row()
    false_marker = dict(_row(champ="Jinx"), focus_board_relog=False)
    str_marker = dict(_row(champ="Lux"), focus_board_relog="true")
    rows = [plain, false_marker, str_marker]
    assert rep._coverage_block(rows)["total"] == 3
    assert rep.summarize_agreement(rows)["comparable"] == 3
    assert rep._coverage_block(rows)["focus_board_relogs"] == 0


def test_the_functions_skip_relogs_on_their_own():
    r = _row()
    rows = [r, _relog(r)]
    assert rep._coverage_block(rows)["total"] == 1
    assert rep.summarize_agreement(rows)["comparable"] == 1


def test_human_summary_names_the_skipped_relogs(tmp_path, capsys):
    r = _row()
    p = tmp_path / "h.jsonl"
    _write(p, [r, _relog(r)])
    assert rep.main(["--path", str(p)]) == 0
    text = capsys.readouterr().out
    assert "[arena shadow] 1 rows" in text
    assert "1 focus-board re-log" in text


def test_the_writer_marker_is_the_one_the_report_skips(tmp_path, monkeypatch):
    # End to end: the real writer produces the transient row and its re-log;
    # the report counts the pair once.
    monkeypatch.delenv(fbl.KILL_SWITCH_ENV, raising=False)
    answers = iter([
        {"status": fbl.STATUS_WARMING, "notes": ["warming"]},
        {"status": fbl.STATUS_OK, "top_kill": {"champion_name": "Kai'Sa"},
         "kill_order": ["Kaisa"], "kill_order_names": ["Kai'Sa"], "notes": []},
    ])
    monkeypatch.setattr(fbl, "board_for_lc", lambda *a, **k: next(answers))
    det = dict(_row()["deterministic"],
               target_priority="Kill Kai'Sa first - squishy threat; tanks last")
    lc = {"champion": "Jinx", "enemy_team": ["Kai'Sa"]}
    target = tmp_path / "w.jsonl"
    shadow._LAST_SIG.pop(str(target), None)
    shadow._LAST_FB_STATUS.pop(str(target), None)
    try:
        assert shadow.log_arena_coach(det, {}, lc, "arena", round_label=4,
                                      path=target) is not None
        relog = shadow.log_arena_coach(det, {}, lc, "arena", round_label=4,
                                       path=target)
    finally:
        shadow._LAST_SIG.pop(str(target), None)
        shadow._LAST_FB_STATUS.pop(str(target), None)
    assert relog is not None and rep.is_focus_board_relog(relog)
    report = rep.build_report(target)
    assert report["coverage"]["total"] == 1
    assert report["coverage"]["focus_board_relogs"] == 1
