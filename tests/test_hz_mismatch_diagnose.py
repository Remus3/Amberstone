"""HZ-mismatch-diagnose tests. Pins the net_swing parse, the bucketing, the
mechanical per-class CALIBRATION-vs-MODEL-ERROR verdict, the partition guard
(class counts sum to exactly the genuine-mismatch population the shadow report
reports), the engine-drift block, and the pure/deterministic markdown render.

All synthetic, tmp_path, ASCII-only. Mirrors tests/test_hz_shadow_report.py.
"""
from __future__ import annotations

import json
import sqlite3

from tools import hz_mismatch_diagnose as diag
from tools import hz_shadow_report as rep
from tools import replay_matchup_validate as rv


def _write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


# ---- net_swing / expected_outcome parse ----


def test_parse_expected_outcome_happy():
    out = diag.parse_expected_outcome(
        "net swing -0.12; you remove 30% of Caitlyn, they remove 42% of you"
    )
    assert out == {"net_swing": -0.12, "pct_enemy_removed": 0.30,
                   "pct_my_removed": 0.42}


def test_parse_expected_outcome_spaced_enemy_name():
    out = diag.parse_expected_outcome(
        "net swing +0.07; you remove 50% of Aurelion Sol, they remove 43% of you"
    )
    assert out["net_swing"] == 0.07
    assert out["pct_enemy_removed"] == 0.50
    assert out["pct_my_removed"] == 0.43


def test_parse_expected_outcome_garbage_is_none():
    assert diag.parse_expected_outcome("") is None
    assert diag.parse_expected_outcome(None) is None
    assert diag.parse_expected_outcome("no scalar here") is None
    assert diag.parse_expected_outcome(123) is None


# ---- bucket_index boundaries (the 12 pinned cases) ----


def test_bucket_index_boundaries():
    cases = {
        -0.6: 0, -0.5: 0, -0.49: 1, -0.18: 1, -0.17: 2, -0.05: 2,
        -0.04: 3, 0.0: 3, 0.01: 4, 0.09: 4, 0.10: 5, 0.5: 5,
    }
    for swing, want in cases.items():
        assert diag.bucket_index(swing) == want, swing


def test_bucket_index_clamps_extremes():
    assert diag.bucket_index(-99.0) == 0
    assert diag.bucket_index(99.0) == 5


# ---- record_scalars from a log record ----


def test_record_scalars_from_choices():
    rec = {"choices": [{"key": "A", "label": "Back off Caitlyn",
                        "expected_outcome": "net swing -0.12; you remove 30% "
                        "of Caitlyn, they remove 42% of you"}]}
    out = diag.record_scalars(rec)
    assert out == {"net_swing": -0.12, "pct_enemy_removed": 0.30,
                   "pct_my_removed": 0.42}


def test_record_scalars_empty_choices_none():
    assert diag.record_scalars({"choices": []}) is None
    assert diag.record_scalars({}) is None
    assert diag.record_scalars({"choices": [{"label": "x"}]}) is None  # no EO


# ---- genuine-mismatch fixtures: verify they classify to the intended pair ----


def _bo_to_hold_rec(swing, enemy="Caitlyn"):
    """A covered back_off precompute vs a Haiku 'hold' native -> genuine
    mismatch class (back_off, hold). The A-label classifies to back_off, the
    native_action to hold; record_agreement returns a non-agreeing pair."""
    pct_e, pct_m = 30, 42
    eo = (f"net swing {swing:+.2f}; you remove {pct_e}% of {enemy}, "
          f"they remove {pct_m}% of you")
    return {"mode": "aram", "my_champion": "Annie", "enemy": enemy,
            "covered": True,
            "choices": [{"key": "A", "label": f"Back off {enemy}",
                         "expected_outcome": eo}],
            "native_action": "hold and farm", "native_choices": []}


def _bo_to_allin_rec(swing, enemy="Caitlyn"):
    """A covered back_off precompute vs a Haiku 'all_in' native -> class
    (back_off, all_in)."""
    eo = (f"net swing {swing:+.2f}; you remove 30% of {enemy}, "
          f"they remove 42% of you")
    return {"mode": "aram", "my_champion": "Annie", "enemy": enemy,
            "covered": True,
            "choices": [{"key": "A", "label": f"Back off {enemy}",
                         "expected_outcome": eo}],
            "native_action": "all in now", "native_choices": []}


def test_fixtures_classify_to_intended_pair():
    # Guard: the synthetic records actually land in the pair the tests assume.
    p1 = rep.record_agreement(_bo_to_hold_rec(-0.12))
    assert p1 == {"precompute": "back_off", "native": "hold", "agree": False}
    p2 = rep.record_agreement(_bo_to_allin_rec(-0.6))
    assert p2 == {"precompute": "back_off", "native": "all_in", "agree": False}


# ---- per-class bucketing + verdict ----


def test_class_back_off_hold_calibration_zone():
    # back_off -> hold with swings clustered in the (-0.18,-0.05] hold zone:
    # buckets[2] dominant, median in calibration zone -> CALIBRATION verdict.
    recs = [_bo_to_hold_rec(s) for s in (-0.06, -0.10, -0.12, -0.15, -0.17)]
    report = diag.diagnose(recs, now="2026-06-21T00:00:00Z")
    cls = _find_class(report, "back_off", "hold")
    assert cls["count"] == 5
    assert cls["buckets"][2] == 5  # all in the hold zone
    assert cls["verdict"].startswith("CALIBRATION")


def test_class_back_off_all_in_model_error_zone():
    # back_off -> all_in with deep-negative swings: buckets[0] dominant,
    # median <= -0.30 -> MODEL-ERROR (enemy-full-combo over-kill).
    recs = [_bo_to_allin_rec(s) for s in (-0.5, -0.6, -0.7, -0.8)]
    # (back_off, all_in) is not a default class -> need --all-classes
    report = diag.diagnose(recs, all_classes=True, now="2026-06-21T00:00:00Z")
    cls = _find_class(report, "back_off", "all_in")
    assert cls["count"] == 4
    assert cls["buckets"][0] == 4
    assert cls["verdict"].startswith("MODEL-ERROR")


def test_class_hold_all_in_under_called_non_negative():
    # A precompute 'hold' (A-label "Hold and farm...") vs a Haiku ALL-IN with a
    # positive swing -> under-called a non-negative trade -> CALIBRATION.
    eo = "net swing +0.13; you remove 55% of Lux, they remove 30% of you"
    recs = [{"mode": "sr", "my_champion": "Garen", "enemy": "Lux",
             "covered": True,
             "choices": [{"key": "A", "label": "Hold and farm this window",
                          "expected_outcome": eo}],
             "native_action": "all in now", "native_choices": []}]
    # confirm the fixture lands in (hold, all_in)
    assert rep.record_agreement(recs[0]) == {
        "precompute": "hold", "native": "all_in", "agree": False}
    report = diag.diagnose(recs, now="2026-06-21T00:00:00Z")
    cls = _find_class(report, "hold", "all_in")
    assert cls["count"] == 1
    assert cls["median_swing"] == 0.13
    assert cls["verdict"].startswith("CALIBRATION (under-called")


def test_classify_class_verdict_table():
    # table-driven over every branch of classify_class_verdict
    passive = ("back_off", "hold")
    # no-data
    assert diag.classify_class_verdict(passive, [0, 0, 0, 0, 0, 0], 0.0) == \
        "no-data"
    # deep>=0.5 -> MODEL-ERROR
    v = diag.classify_class_verdict(passive, [3, 1, 0, 0, 0, 0], -0.4)
    assert v.startswith("MODEL-ERROR")
    # median<=-0.30 (deep<0.5) -> MODEL-ERROR
    v = diag.classify_class_verdict(passive, [1, 3, 0, 0, 0, 0], -0.31)
    assert v.startswith("MODEL-ERROR")
    # clustered near threshold (buckets 2+3+4 >=0.5, median>-0.18) -> CALIBRATION
    v = diag.classify_class_verdict(passive, [0, 0, 3, 1, 0, 0], -0.10)
    assert v.startswith("CALIBRATION (clustered")
    # non-negative median, mass NOT majority in the near-threshold buckets
    # (else the clustered branch wins first) -> CALIBRATION under-called
    v = diag.classify_class_verdict(passive, [0, 0, 0, 0, 0, 2], 0.13)
    assert v.startswith("CALIBRATION (under-called")
    # mixed: deep<0.5, near-threshold buckets not majority, median negative but
    # above the -0.30 model-error gate -> no dominant zone -> MIXED
    v = diag.classify_class_verdict(passive, [0, 1, 0, 0, 0, 1], -0.10)
    assert v.startswith("MIXED")
    # native-more-passive branch: firmly positive -> HAIKU-NOISE/CV-VETO
    v = diag.classify_class_verdict(("trade", "back_off"),
                                    [0, 0, 0, 0, 0, 4], 0.22)
    assert v.startswith("HAIKU-NOISE")
    # native-more-passive, small edge -> AMBIGUOUS
    v = diag.classify_class_verdict(("even", "back_off"),
                                    [0, 0, 1, 1, 0, 0], -0.02)
    assert v.startswith("AMBIGUOUS")


# ---- partition guard: class counts == shadow-report genuine-mismatch count ----


def test_partition_matches_shadow_report_population():
    records = [
        _bo_to_hold_rec(-0.10),
        _bo_to_hold_rec(-0.12),
        _bo_to_allin_rec(-0.6),
        # an AGREEING tick (not a mismatch) - must NOT appear in any class
        {"mode": "aram", "covered": True,
         "choices": [{"key": "A", "label": "Trade now",
                      "expected_outcome": "net swing -0.02; you remove 40% of "
                      "Ashe, they remove 41% of you"}],
         "native_action": "TRADE", "native_choices": []},
        # a hold->all_in mismatch
        {"mode": "sr", "covered": True,
         "choices": [{"key": "A", "label": "Hold and farm this window",
                      "expected_outcome": "net swing +0.04; you remove 50% of "
                      "Lux, they remove 40% of you"}],
         "native_action": "all in", "native_choices": []},
    ]
    report = diag.diagnose(records, all_classes=True,
                           now="2026-06-21T00:00:00Z")
    summ = rep.summarize_agreement(records)
    expected = summ["comparable_covered"] - summ["agree"]
    total_in_classes = sum(c["count"] for c in report["classes"])
    assert total_in_classes == expected
    assert report["genuine_mismatches"] == expected


def test_non_laning_native_state_excluded():
    records = [
        # dead-state native -> excluded by rep guard, no class
        {"mode": "aram", "covered": True,
         "choices": [{"key": "A", "label": "Back off Ashe",
                      "expected_outcome": "net swing -0.50; you remove 10% of "
                      "Ashe, they remove 60% of you"}],
         "native_action": "WAIT RESPAWN", "native_choices": []},
        # one real mismatch survives
        _bo_to_hold_rec(-0.10),
    ]
    report = diag.diagnose(records, all_classes=True,
                           now="2026-06-21T00:00:00Z")
    assert report["genuine_mismatches"] == 1
    assert _find_class(report, "back_off", "hold")["count"] == 1


def test_native_recall_excluded():
    records = [
        # native recall -> cross-axis, dropped by record_agreement
        {"mode": "sr", "covered": True,
         "choices": [{"key": "A", "label": "Back off Ashe",
                      "expected_outcome": "net swing -0.20; you remove 20% of "
                      "Ashe, they remove 40% of you"},
                     {"key": "B", "label": "Back soon"}],
         "native_action": "RECALL NOW", "native_choices": []},
        _bo_to_hold_rec(-0.10),
    ]
    report = diag.diagnose(records, all_classes=True,
                           now="2026-06-21T00:00:00Z")
    assert report["genuine_mismatches"] == 1


# ---- engine-drift block ----


def test_drift_block_counts_and_warns():
    records = [
        dict(_bo_to_hold_rec(-0.10), engine_version="1.149.0"),
        dict(_bo_to_hold_rec(-0.12), engine_version="1.120.0"),
        dict(_bo_to_hold_rec(-0.15), engine_version="1.120.0"),
    ]
    report = diag.diagnose(records, current_engine="1.149.0",
                           now="2026-06-21T00:00:00Z")
    drift = report["drift"]
    assert drift["current_engine"] == "1.149.0"
    assert drift["logged_under_current"] == 1
    assert drift["logged_under_other"] == 2
    assert drift["by_engine_version"]["1.120.0"] == 2
    assert drift["by_engine_version"]["1.149.0"] == 1
    md = diag.render_markdown(report)
    assert "WARNING" in md  # logged_under_other > 0 surfaces the warning


def test_drift_no_warning_when_all_current():
    records = [dict(_bo_to_hold_rec(-0.10), engine_version="1.149.0")]
    report = diag.diagnose(records, current_engine="1.149.0",
                           now="2026-06-21T00:00:00Z")
    assert report["drift"]["logged_under_other"] == 0


# ---- markdown: pure, deterministic, ASCII, anti-circularity footer ----


def test_render_markdown_ascii_deterministic_and_footer():
    records = [_bo_to_hold_rec(s) for s in (-0.10, -0.12)]
    report = diag.diagnose(records, now="2026-06-21T12:00:00Z")
    md1 = diag.render_markdown(report)
    md2 = diag.render_markdown(report)
    assert md1 == md2  # pure: byte-identical across calls
    assert md1.isascii()  # no em-dash, smart quote, or box-drawing char
    # anti-circularity footer mentions both fix sites + the no-tune caveat
    assert "core/precomputed_laning_coach.py" in md1
    assert "core/laning_scenario_precompute.py" in md1
    assert "ground-truth" in md1.lower()
    assert "2026-06-21T12:00:00Z" in md1  # injected clock in the body


def test_write_markdown_creates_parent_and_file(tmp_path):
    report = diag.diagnose([_bo_to_hold_rec(-0.10)],
                           now="2026-06-21T00:00:00Z")
    target = tmp_path / "nested" / "deep" / "HZ_MISMATCH_DIAGNOSE.md"
    diag.write_markdown(report, target)
    assert target.exists()
    assert target.read_text(encoding="utf-8").isascii()


# ---- CLI ----


def test_main_json_fail_soft_missing_log(tmp_path, capsys):
    rc = diag.main(["--choice-path", str(tmp_path / "nope.jsonl"),
                    "--json", "--no-write"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["genuine_mismatches"] == 0
    assert out["total_records"] == 0


def test_main_writes_markdown_to_md_path(tmp_path, capsys):
    c = tmp_path / "c.jsonl"
    _write(c, [_bo_to_hold_rec(-0.10), _bo_to_hold_rec(-0.12)])
    md = tmp_path / "out" / "HZ_MISMATCH_DIAGNOSE.md"
    rc = diag.main(["--choice-path", str(c), "--md-path", str(md)])
    assert rc == 0
    assert md.exists()
    body = md.read_text(encoding="utf-8")
    assert body.isascii()
    assert "back_off" in body
    # human summary printed
    out = capsys.readouterr().out
    assert "pre=back_off" in out or "back_off" in out


def test_main_human_summary_runs(tmp_path, capsys):
    c = tmp_path / "c.jsonl"
    _write(c, [_bo_to_hold_rec(-0.10)])
    rc = diag.main(["--choice-path", str(c), "--no-write"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "back_off" in out


# ---- helper ----


def _find_class(report, pre, native):
    for c in report["classes"]:
        if c["precompute"] == pre and c["native"] == native:
            return c
    raise AssertionError(f"class ({pre},{native}) not in report: "
                         f"{[(c['precompute'], c['native']) for c in report['classes']]}")


# ============================================================================
# Rewind ground-truth cross-ref (SR-only, independent signal) tests.
#
# All synthetic, in-memory sqlite, ASCII-only. NEVER reads the real
# data/rewind_history.db (gitignored - a test reading it passes on dev but
# fails on clean checkout / CI). The rewind DB schema below mirrors
# tests/test_replay_matchup_validate.py::_make_db EXACTLY.
# ============================================================================


# ---- SR-mode genuine-mismatch fixtures (existing fixtures use mode="aram") ----


def _sr_bo_to_hold_rec(swing, my="Garen", enemy="Lux"):
    """A covered back_off precompute vs a Haiku 'hold' native on SR -> class
    (back_off, hold), with my_champion/enemy set for the matchup cross-ref."""
    eo = (f"net swing {swing:+.2f}; you remove 30% of {enemy}, "
          f"they remove 42% of you")
    return {"mode": "sr", "my_champion": my, "enemy": enemy, "covered": True,
            "choices": [{"key": "A", "label": f"Back off {enemy}",
                         "expected_outcome": eo}],
            "native_action": "hold and farm", "native_choices": []}


def _sr_trade_to_allin_rec(swing, my="Garen", enemy="Lux"):
    """A covered 'trade' precompute (A-label "Trade...") vs a Haiku 'all_in'
    native on SR -> class (trade, all_in). predicted_my_ahead True (trade)."""
    eo = (f"net swing {swing:+.2f}; you remove 55% of {enemy}, "
          f"they remove 30% of you")
    return {"mode": "sr", "my_champion": my, "enemy": enemy, "covered": True,
            "choices": [{"key": "A", "label": f"Trade with {enemy} now",
                         "expected_outcome": eo}],
            "native_action": "all in now", "native_choices": []}


# ---- hermetic rewind DB builder (mirrors rv test _make_db EXACTLY) ----


def _make_rewind_db(conn, matches, participants, frames, events=None):
    """Build a temp rewind DB in `conn` with the columns the rv harness reads.

    matches: (match_id, game_mode, has_timeline, game_creation_ts)
    participants: (match_id, participant_id, team_id, champion_name, team_position)
    frames: (match_id, timestamp_ms, participant_id, total_gold)
    events: optional (match_id, event_type, killer_id, victim_id, assisting_ids_json)
    """
    conn.execute(
        "CREATE TABLE matches (match_id TEXT, game_mode TEXT, has_timeline INTEGER, "
        "game_creation_ts INTEGER)"
    )
    conn.execute(
        "CREATE TABLE participants (match_id TEXT, participant_id INTEGER, team_id INTEGER, "
        "champion_name TEXT, team_position TEXT)"
    )
    conn.execute(
        "CREATE TABLE timeline_frames (match_id TEXT, timestamp_ms INTEGER, "
        "participant_id INTEGER, total_gold REAL)"
    )
    conn.execute(
        "CREATE TABLE timeline_events (match_id TEXT, event_type TEXT, killer_id INTEGER, "
        "victim_id INTEGER, assisting_ids_json TEXT)"
    )
    conn.executemany("INSERT INTO matches VALUES (?,?,?,?)", matches)
    conn.executemany("INSERT INTO participants VALUES (?,?,?,?,?)", participants)
    conn.executemany("INSERT INTO timeline_frames VALUES (?,?,?,?)", frames)
    if events:
        conn.executemany("INSERT INTO timeline_events VALUES (?,?,?,?,?)", events)
    conn.commit()


_TS10 = 10 * 60 * 1000  # exact 10-min frame (matches _REWIND_GOLD_FRAME_MIN)


def _sr_lane(match_id, lane, champ_a, gold_a, champ_b, gold_b, *, pid_a, pid_b):
    """Rows for ONE lane: a team100 pid + a team200 pid, with a 0-min and a
    10-min frame at 10*60*1000 ms. Returns (participants, frames)."""
    parts = [
        (match_id, pid_a, 100, champ_a, lane),
        (match_id, pid_b, 200, champ_b, lane),
    ]
    frames = [
        (match_id, 0, pid_a, 500.0),
        (match_id, 0, pid_b, 500.0),
        (match_id, _TS10, pid_a, float(gold_a)),
        (match_id, _TS10, pid_b, float(gold_b)),
    ]
    return parts, frames


def _open_rewind(matches, participants, frames, events=None):
    conn = sqlite3.connect(":memory:")
    _make_rewind_db(conn, matches, participants, frames, events)
    return conn


# ---- _canon_champ table ----


def test_canon_champ_table():
    assert diag._canon_champ("Kai'Sa") == "kaisa"
    assert diag._canon_champ("Dr. Mundo") == "drmundo"
    assert diag._canon_champ("Aurelion Sol") == "aurelionsol"
    assert diag._canon_champ("Bel'Veth") == "belveth"
    assert diag._canon_champ("  Garen  ") == "garen"
    assert diag._canon_champ("Cho'Gath") == "chogath"
    assert diag._canon_champ(None) == ""


# ---- _sr_mismatch_matchups: SR collect + ARAM/client exclusion ----


def test_sr_mismatch_matchups_collects_sr_and_excludes_aram_client():
    records = [
        _sr_bo_to_hold_rec(-0.10, my="Garen", enemy="Lux"),
        _bo_to_hold_rec(-0.10),   # mode="aram" -> excluded+counted
        # a client-mode mismatch -> excluded+counted
        {"mode": "client", "my_champion": "Annie", "enemy": "Ashe",
         "covered": True,
         "choices": [{"key": "A", "label": "Back off Ashe",
                      "expected_outcome": "net swing -0.10; you remove 30% of "
                      "Ashe, they remove 42% of you"}],
         "native_action": "hold and farm", "native_choices": []},
    ]
    pairs = diag._genuine_mismatch_pairs(records)
    per_class = diag._sr_mismatch_matchups(pairs)
    bh = per_class[("back_off", "hold")]
    assert ("Garen", "Lux") in bh["matchups"]
    assert bh["excluded"]["aram"] >= 1
    assert bh["excluded"]["client"] >= 1
    # the aram/client rows did NOT enter the matchup set
    assert ("Annie", "Caitlyn") not in bh["matchups"]
    assert ("Annie", "Ashe") not in bh["matchups"]


def test_sr_mismatch_matchups_no_identity_excluded():
    records = [
        # SR but missing enemy -> excluded["no_matchup_identity"]
        {"mode": "sr", "my_champion": "Garen", "enemy": "", "covered": True,
         "choices": [{"key": "A", "label": "Back off",
                      "expected_outcome": "net swing -0.10; you remove 30% of "
                      "Foo, they remove 42% of you"}],
         "native_action": "hold and farm", "native_choices": []},
    ]
    pairs = diag._genuine_mismatch_pairs(records)
    per_class = diag._sr_mismatch_matchups(pairs)
    bh = per_class[("back_off", "hold")]
    assert bh["matchups"] == set()
    assert bh["excluded"]["no_matchup_identity"] >= 1


# ---- _orient_lane_pair ----


def test_orient_lane_pair_my_is_a():
    lp = rv.LanePair("M1", "MIDDLE", "Garen", "Lux", 4000, 3000, pid_a=1, pid_b=6)
    o = diag._orient_lane_pair(lp, "Garen", "Lux")
    assert o["my_is_a"] is True
    assert o["gold_diff"] == 1000.0


def test_orient_lane_pair_my_is_b_flips():
    # rewind stored champ_a=Lux (enemy), champ_b=Garen (me) -> my-gold is gold_b
    lp = rv.LanePair("M1", "MIDDLE", "Lux", "Garen", 3000, 4000, pid_a=1, pid_b=6)
    o = diag._orient_lane_pair(lp, "Garen", "Lux")
    assert o["my_is_a"] is False
    assert o["gold_diff"] == 1000.0  # my(4000) - enemy(3000), positive


def test_orient_lane_pair_non_matching_returns_none():
    lp = rv.LanePair("M1", "TOP", "Darius", "Sett", 4000, 3000, pid_a=1, pid_b=6)
    assert diag._orient_lane_pair(lp, "Garen", "Lux") is None


# ---- _rewind_xref_class / rewind_cross_ref: the 12 scenario cases ----


def test_case1_oriented_my_is_a_agree():
    # class (trade, all_in): predicted_my_ahead True. Rewind: my champ ahead in
    # gold (4000>3000) across 3 lane-games -> real_my_ahead True -> agree.
    records = [_sr_trade_to_allin_rec(0.20, my="Garen", enemy="Lux")]
    matches, parts, frames = [], [], []
    for i in range(3):
        mid = f"SR{i}"
        matches.append((mid, "CLASSIC", 1, 1000 + i))
        p, f = _sr_lane(mid, "MIDDLE", "Garen", 4000, "Lux", 3000, pid_a=3, pid_b=8)
        parts += p
        frames += f
    conn = _open_rewind(matches, parts, frames)
    out = diag.rewind_cross_ref(records, conn=conn)
    conn.close()
    cls = out["classes"]["trade->all_in"]
    assert cls["lane_games"] == 3
    assert cls["matchups_covered"] == 1
    assert cls["mean_gold_diff"] > 0
    assert cls["low_confidence"] is False
    assert cls["agreement"] == "agree"


def test_case2_oriented_my_is_b_agree():
    # Rewind stored the pair reversed (enemy on team100). my-perspective gold_diff
    # must still come out positive -> agree.
    records = [_sr_trade_to_allin_rec(0.20, my="Garen", enemy="Lux")]
    matches, parts, frames = [], [], []
    for i in range(3):
        mid = f"SR{i}"
        matches.append((mid, "CLASSIC", 1, 1000 + i))
        p, f = _sr_lane(mid, "MIDDLE", "Lux", 3000, "Garen", 4000, pid_a=3, pid_b=8)
        parts += p
        frames += f
    conn = _open_rewind(matches, parts, frames)
    out = diag.rewind_cross_ref(records, conn=conn)
    conn.close()
    cls = out["classes"]["trade->all_in"]
    assert cls["lane_games"] == 3
    assert cls["mean_gold_diff"] > 0
    assert cls["agreement"] == "agree"


def test_case3_order_independent_set_match():
    # one stored normal + one stored reversed -> both covered (set match).
    records = [_sr_trade_to_allin_rec(0.20, my="Garen", enemy="Lux")]
    matches, parts, frames = [], [], []
    specs = [("Garen", 4200, "Lux", 3000, 3, 8), ("Lux", 3100, "Garen", 4100, 4, 9)]
    for i, (ca, ga, cb, gb, pa, pb) in enumerate(specs):
        mid = f"SR{i}"
        matches.append((mid, "CLASSIC", 1, 1000 + i))
        p, f = _sr_lane(mid, "MIDDLE", ca, ga, cb, gb, pid_a=pa, pid_b=pb)
        parts += p
        frames += f
    # pad to >= min_samples so it is not low_confidence
    mid = "SR2"
    matches.append((mid, "CLASSIC", 1, 1002))
    p, f = _sr_lane(mid, "MIDDLE", "Garen", 4000, "Lux", 3000, pid_a=3, pid_b=8)
    parts += p
    frames += f
    conn = _open_rewind(matches, parts, frames)
    out = diag.rewind_cross_ref(records, conn=conn)
    conn.close()
    cls = out["classes"]["trade->all_in"]
    assert cls["lane_games"] == 3
    assert cls["mean_gold_diff"] > 0


def test_case4_disagree_direction():
    # class (back_off, hold): predicted_my_ahead False (back_off). Rewind: my
    # champ AHEAD in gold across 3 games -> real_my_ahead True -> disagree.
    records = [_sr_bo_to_hold_rec(-0.10, my="Garen", enemy="Lux")]
    matches, parts, frames = [], [], []
    for i in range(3):
        mid = f"SR{i}"
        matches.append((mid, "CLASSIC", 1, 1000 + i))
        p, f = _sr_lane(mid, "MIDDLE", "Garen", 4500, "Lux", 3000, pid_a=3, pid_b=8)
        parts += p
        frames += f
    conn = _open_rewind(matches, parts, frames)
    out = diag.rewind_cross_ref(records, conn=conn)
    conn.close()
    cls = out["classes"]["back_off->hold"]
    assert cls["lane_games"] == 3
    assert cls["agreement"] == "disagree"


def test_case5_low_sample_insufficient():
    # only 1 lane-game (< _REWIND_MIN_SAMPLES) -> insufficient_data + low_conf.
    records = [_sr_trade_to_allin_rec(0.20, my="Garen", enemy="Lux")]
    p, f = _sr_lane("SR0", "MIDDLE", "Garen", 4000, "Lux", 3000, pid_a=3, pid_b=8)
    conn = _open_rewind([("SR0", "CLASSIC", 1, 1000)], p, f)
    out = diag.rewind_cross_ref(records, conn=conn)
    conn.close()
    cls = out["classes"]["trade->all_in"]
    assert cls["lane_games"] == 1
    assert cls["low_confidence"] is True
    assert cls["agreement"] == "insufficient_data"


def test_case6_zero_coverage_class():
    # the rewind DB has an unrelated matchup only -> covered 0, insufficient.
    records = [_sr_trade_to_allin_rec(0.20, my="Garen", enemy="Lux")]
    p, f = _sr_lane("SR0", "TOP", "Darius", 4000, "Sett", 3000, pid_a=1, pid_b=6)
    conn = _open_rewind([("SR0", "CLASSIC", 1, 1000)], p, f)
    out = diag.rewind_cross_ref(records, conn=conn)
    conn.close()
    cls = out["classes"]["trade->all_in"]
    assert cls["matchups_covered"] == 0
    assert cls["lane_games"] == 0
    assert cls["agreement"] == "insufficient_data"


def test_case7_aram_excluded_and_counted():
    records = [
        _sr_trade_to_allin_rec(0.20, my="Garen", enemy="Lux"),
        _bo_to_hold_rec(-0.10),  # mode aram
    ]
    p, f = _sr_lane("SR0", "MIDDLE", "Garen", 4000, "Lux", 3000, pid_a=3, pid_b=8)
    conn = _open_rewind([("SR0", "CLASSIC", 1, 1000)], p, f)
    out = diag.rewind_cross_ref(records, conn=conn)
    conn.close()
    assert out["excluded_total"]["aram"] >= 1
    # aram champs (Annie/Caitlyn) appear in NO class matchup set
    bh = out["classes"]["back_off->hold"]
    assert ("Annie", "Caitlyn") not in set(
        tuple(m) for m in []  # matchup sets are not serialized; assert via covered
    )
    assert bh["matchups_in_class"] == 0  # the only back_off->hold was aram


def test_case8_client_excluded_and_counted():
    records = [
        _sr_trade_to_allin_rec(0.20, my="Garen", enemy="Lux"),
        {"mode": "client", "my_champion": "Annie", "enemy": "Ashe",
         "covered": True,
         "choices": [{"key": "A", "label": "Back off Ashe",
                      "expected_outcome": "net swing -0.10; you remove 30% of "
                      "Ashe, they remove 42% of you"}],
         "native_action": "hold and farm", "native_choices": []},
    ]
    p, f = _sr_lane("SR0", "MIDDLE", "Garen", 4000, "Lux", 3000, pid_a=3, pid_b=8)
    conn = _open_rewind([("SR0", "CLASSIC", 1, 1000)], p, f)
    out = diag.rewind_cross_ref(records, conn=conn)
    conn.close()
    assert out["excluded_total"]["client"] >= 1


def test_case9_failsoft_missing_db_and_wiring(tmp_path):
    records = [_sr_bo_to_hold_rec(-0.10, my="Garen", enemy="Lux"),
               _bo_to_hold_rec(-0.10)]  # one aram for the excluded tally
    missing = tmp_path / "nope.db"
    out = diag.rewind_cross_ref(records, db_path=missing)
    assert out["available"] is False
    assert out["reason"] == "unavailable (no rewind db)"
    # the excluded tally is still populated even with no DB
    assert out["excluded_total"]["aram"] >= 1
    # wiring through diagnose + render must not raise, must show unavailable
    report = diag.diagnose(records, with_rewind=True, rewind_db=missing,
                           now="2026-06-21T00:00:00Z")
    md = diag.render_markdown(report)
    assert md.isascii()
    assert "Rewind ground-truth cross-ref" in md
    assert "unavailable" in md
    # the v1 buckets are unaffected (anti-circularity footer still present)
    assert "core/precomputed_laning_coach.py" in md


def test_case10_solo_kill_orientation_and_conflict():
    # my champ solo-kills enemy 2-0 -> solo_kills_my == 2.
    records = [_sr_trade_to_allin_rec(0.20, my="Garen", enemy="Lux")]
    matches, parts, frames, events = [], [], [], []
    for i in range(3):
        mid = f"SR{i}"
        matches.append((mid, "CLASSIC", 1, 1000 + i))
        p, f = _sr_lane(mid, "MIDDLE", "Garen", 4000, "Lux", 3000, pid_a=3, pid_b=8)
        parts += p
        frames += f
    # 2 solo kills my(pid3)->enemy(pid8) on the first match
    events += [("SR0", "CHAMPION_KILL", 3, 8, "[]"),
               ("SR0", "CHAMPION_KILL", 3, 8, "[]")]
    conn = _open_rewind(matches, parts, frames, events)
    out = diag.rewind_cross_ref(records, conn=conn)
    conn.close()
    cls = out["classes"]["trade->all_in"]
    assert cls["solo_kills_my"] == 2
    assert cls["solo_kills_enemy"] == 0

    # conflict variant: gold AHEAD but kills BEHIND -> insufficient_data
    records2 = [_sr_trade_to_allin_rec(0.20, my="Garen", enemy="Lux")]
    m2, p2, f2, e2 = [], [], [], []
    for i in range(3):
        mid = f"SR{i}"
        m2.append((mid, "CLASSIC", 1, 1000 + i))
        p, f = _sr_lane(mid, "MIDDLE", "Garen", 4500, "Lux", 3000, pid_a=3, pid_b=8)
        p2 += p
        f2 += f
    # enemy out-solo-kills me 2-0 while my gold is ahead -> gold/kills conflict
    e2 += [("SR0", "CHAMPION_KILL", 8, 3, "[]"),
           ("SR0", "CHAMPION_KILL", 8, 3, "[]")]
    conn2 = _open_rewind(m2, p2, f2, e2)
    out2 = diag.rewind_cross_ref(records2, conn=conn2)
    conn2.close()
    cls2 = out2["classes"]["trade->all_in"]
    assert cls2["solo_kills_enemy"] == 2
    assert cls2["agreement"] == "insufficient_data"


def test_case11_canon_spaced_apostrophe_matchup_covers():
    # matchup with a spaced + apostrophe name; rewind stores the canonical
    # DDragon-ish forms -> canon makes them match.
    rec = {"mode": "sr", "my_champion": "Kai'Sa", "enemy": "Aurelion Sol",
           "covered": True,
           "choices": [{"key": "A", "label": "Trade with Aurelion Sol now",
                        "expected_outcome": "net swing +0.20; you remove 55% of "
                        "Aurelion Sol, they remove 30% of you"}],
           "native_action": "all in now", "native_choices": []}
    records = [rec]
    matches, parts, frames = [], [], []
    for i in range(3):
        mid = f"SR{i}"
        matches.append((mid, "CLASSIC", 1, 1000 + i))
        # rewind champion_name forms (no apostrophe / no space)
        p, f = _sr_lane(mid, "MIDDLE", "Kaisa", 4000, "AurelionSol", 3000,
                        pid_a=3, pid_b=8)
        parts += p
        frames += f
    conn = _open_rewind(matches, parts, frames)
    out = diag.rewind_cross_ref(records, conn=conn)
    conn.close()
    cls = out["classes"]["trade->all_in"]
    assert cls["matchups_covered"] == 1
    assert cls["lane_games"] == 3


def test_case12_schema_v2_and_additive():
    records = [_sr_trade_to_allin_rec(0.20, my="Garen", enemy="Lux")]
    p, f = _sr_lane("SR0", "MIDDLE", "Garen", 4000, "Lux", 3000, pid_a=3, pid_b=8)
    mem = _open_rewind([("SR0", "CLASSIC", 1, 1000)], p, f)
    report = diag.diagnose(records, all_classes=True, with_rewind=True,
                           rewind_conn=mem, now="2026-06-21T00:00:00Z")
    mem.close()
    assert report["schema"] == "hz_mismatch_diagnose/v2"
    # all v1 top-level keys present
    for k in ("generated_at", "total_records", "genuine_mismatches",
              "bucket_labels", "classes", "drift"):
        assert k in report
    # per-class v1 fields unchanged
    cls = _find_class(report, "trade", "all_in")
    for k in ("precompute", "native", "count", "buckets", "median_swing",
              "verdict"):
        assert k in cls
    assert "rewind_xref" in cls  # per-class block attached
    assert "rewind_xref" in report  # top-level block present

    # diagnose WITHOUT with_rewind has NO rewind_xref key (byte-compat)
    plain = diag.diagnose(records, now="2026-06-21T00:00:00Z")
    assert "rewind_xref" not in plain
    for c in plain["classes"]:
        assert "rewind_xref" not in c

    md = diag.render_markdown(report)
    assert md.isascii()
    assert "Rewind ground-truth cross-ref" in md
    # the original anti-circularity footer survives
    assert "metric is the thing under" in md


def test_rewind_cross_ref_schema_v2_constant():
    assert diag.SCHEMA == "hz_mismatch_diagnose/v2"


def test_tool_file_is_ascii_only():
    import pathlib
    tool = pathlib.Path(diag.__file__)
    data = tool.read_bytes()
    non_ascii = [(i, b) for i, b in enumerate(data) if b > 0x7F]
    assert not non_ascii, f"non-ASCII bytes at offsets {non_ascii[:5]}"
