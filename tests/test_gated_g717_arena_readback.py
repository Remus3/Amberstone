"""tools/gated_g717_arena_readback.py - the G7-17 read-back (s144 lane gated cycle 7).

Read-only plumbing for the next real Arena game; nothing here ticks a row.
Source pins first (the placeholder predicate and the BUY ITEMS rule the tool
restates; FIX_COMMITTED_UTC is the git committer time of 4d07738aa, read by
hand - a git-history test would break in a shallow clone), then the UTC
cutoff, the five checks and the CLI. All data is synthetic: champion and item names are placeholders and no
Riot id appears anywhere.
"""
from __future__ import annotations

import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools import arena_shadow_report as asr
from tools import gated_g717_arena_readback as g

ROOT = Path(__file__).resolve().parent.parent
CUT = datetime(2026, 10, 27, 13, 0, 0, tzinfo=timezone.utc)


def _row(ts: str, det: str = "FIGHT SMART", haiku: str = "CAMP PHASE", rnd="~3", **extra) -> dict:
    rec = {"ts": ts, "mode": "arena", "champ": "ChampA", "round": rnd, "enemy_comp": [],
           "deterministic": {"action": det}, "live_haiku": {"action": haiku}}
    rec.update(extra)
    return rec


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _tree(tmp_path: Path, shadow=(), anvil=(), coach=None, started="2026-10-27T13:00:00+00:00") -> Path:
    _write_jsonl(tmp_path / g.SHADOW_REL, list(shadow))
    if anvil:
        _write_jsonl(tmp_path / g.ANVIL_REL, list(anvil))
    if coach is not None:
        (tmp_path / g.COACH_REL).write_text(json.dumps(coach), encoding="utf-8")
    (tmp_path / g.HEALTH_REL).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / g.HEALTH_REL).write_text(json.dumps({"started_at": started}), encoding="utf-8")
    return tmp_path


# -- source pins ---------------------------------------------------------------

def test_placeholder_rounds_match_the_shipped_guard():
    tree = ast.parse((ROOT / "dashboard/_deterministic_coaching.py").read_text(encoding="utf-8"))
    vals = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
            and any(getattr(t, "id", "") == "_ARENA_PLACEHOLDER_ROUNDS" for t in n.targets)]
    assert vals == [g.PLACEHOLDER_ROUNDS]


def test_buy_items_comes_only_from_camp_phase():
    from core import arena_action_rule as rule
    assert rule.decide_action(50, True, None) == g.BUY_ITEMS
    for hp in (5, 30, 50, 90):
        assert rule.decide_action(hp, False, None) != g.BUY_ITEMS


def test_shadow_report_string_compares_since():
    # The trap this tool exists to avoid: a local-offset cutoff admits UTC rows
    # stamped before it, because _since_filter compares strings.
    early = _row("2026-10-27T14:00:00+00:00")  # 09:00 local, before an 11:00-05:00 restart
    kept, _ = asr._since_filter([early], "2026-10-27T11:00:00-05:00")
    assert kept == [early]
    assert g.after([early], g.parse_utc("2026-10-27T11:00:00-05:00")) == []


# -- cutoff --------------------------------------------------------------------

def test_parse_utc_normalises_offsets_and_naive_values():
    assert g.parse_utc("2026-10-27T08:00:00-05:00") == CUT
    assert g.parse_utc("2026-10-27T13:00:00Z") == CUT
    assert g.parse_utc("2026-10-27T13:00:00") == CUT
    for bad in (None, "", "not a time", 5):
        assert g.parse_utc(bad) is None


def test_resolve_cutoff_defaults_to_health_started_at(tmp_path):
    root = _tree(tmp_path)
    assert g.resolve_cutoff(None, root) == (CUT, "health.json started_at")
    assert g.resolve_cutoff("2026-10-27T08:00:00-05:00", root) == (CUT, "--since")
    assert g.resolve_cutoff(None, tmp_path / "missing")[0] is None


def test_restart_before_the_fix_fails():
    assert g.check_restart(CUT, "x")["status"] == "PASS"
    assert g.check_restart(g.FIX_COMMITTED_UTC, "x")["status"] == "PASS"
    assert g.check_restart(datetime(2026, 10, 25, 6, 0, tzinfo=timezone.utc), "x")["status"] == "FAIL"
    assert g.check_restart(None, "x")["status"] == "INCOMPLETE"


# -- cohort / camp / anvil -----------------------------------------------------

def test_cohort_pass_needs_buy_items_and_skips_relogs():
    rows = [_row("2026-10-27T13:01:00+00:00", det="BUY ITEMS"),
            _row("2026-10-27T13:02:00+00:00", det="BUY ITEMS", focus_board_relog=True),
            _row("2026-10-27T13:03:00+00:00", det="KITE BACK", haiku="")]
    c = g.check_cohort(rows)
    assert (c["status"], c["samples"], c["relogs"], c["buy_items"]) == ("PASS", 2, 1, 1)
    assert (c["placeholder_rows"], c["blank_haiku_rows"]) == (0, 1)
    assert g.check_cohort([_row("2026-10-27T13:01:00+00:00")])["status"] == "INCOMPLETE"
    assert g.check_cohort([])["status"] == "INCOMPLETE"


@pytest.mark.parametrize("rnd", [0, "", None])
def test_cohort_fails_on_a_placeholder_row(rnd):
    rows = [_row("2026-10-27T13:01:00+00:00", det="BUY ITEMS"),
            _row("2026-10-27T13:02:00+00:00", det="PLAY AGGRO", haiku="  ", rnd=rnd)]
    assert g.check_cohort(rows)["status"] == "FAIL"


def test_real_haiku_on_round_zero_is_not_a_placeholder():
    assert not g.is_placeholder(_row("t", rnd=0, haiku="FIGHT"))
    assert not g.is_placeholder(_row("t", rnd="~4", haiku=""))


def test_camp_seen_from_a_fresh_arena_snapshot_or_a_buy_items_row():
    fresh = {"present": True, "mtime_utc": "2026-10-27T13:05:00+00:00", "mode": "arena",
             "camp_phase": True}
    stale = dict(fresh, mtime_utc="2026-10-27T12:00:00+00:00")
    other = dict(fresh, mode="aram")
    assert g.check_camp([fresh], CUT, 0)["status"] == "PASS"
    assert g.check_camp([stale, other, {"present": False}], CUT, 0)["status"] == "NOT_SEEN"
    assert g.check_camp([stale], CUT, 2)["status"] == "PASS"
    assert g.check_camp([dict(fresh, camp_phase="true")], CUT, 0)["status"] == "NOT_SEEN"


def test_anvil_candidate_only_for_an_arena_row():
    assert g.check_anvil([])["status"] == "NO_ROW"
    assert g.check_anvil([{"ts": "t", "mode": "aram"}])["status"] == "NO_ROW"
    a = g.check_anvil([{"ts": "t", "mode": "arena", "champion": "ChampA", "round": "~5",
                        "offered": ["ItemA", "ItemB"], "native": {"take": "ItemA"}}])
    assert a["status"] == "CANDIDATE"
    assert a["last"]["offered"] == ["ItemA", "ItemB"] and a["last"]["take"] == "ItemA"


def test_snapshot_coach_reads_fields_and_survives_a_missing_file(tmp_path):
    assert g.snapshot_coach(tmp_path / "nope.json") == {"present": False}
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"mode": "arena", "camp_phase": True, "round": "~2",
                             "game_time_s": 120, "game_id": 1}), encoding="utf-8")
    s = g.snapshot_coach(p)
    assert s["present"] and s["camp_phase"] is True and s["mode"] == "arena"
    assert "game_id" not in s


# -- whole report / CLI --------------------------------------------------------

def _good_rows():
    rows = [_row("2026-10-27T12:30:00+00:00", det="BUY ITEMS", haiku="", rnd=0)]  # pre-cutoff
    rows += [_row(f"2026-10-27T13:{m:02d}:00+00:00", det="BUY ITEMS", haiku="BUY ITEMS")
             for m in range(1, 4)]
    rows += [_row(f"2026-10-27T13:{m:02d}:00+00:00", det="KITE BACK", haiku="PLAY SAFE")
             for m in range(10, 30)]
    return rows


def test_report_pass_ignores_pre_cutoff_rows(tmp_path):
    anvil = [{"ts": "2026-10-27T13:20:00+00:00", "mode": "arena", "champion": "ChampA",
              "round": "~6", "offered": ["ItemA"], "native": {"take": "ItemA"}}]
    root = _tree(tmp_path, shadow=_good_rows(), anvil=anvil)
    rep = g.report(root, CUT, "health.json started_at", [{"present": False}])
    assert rep["verdict"] == "PASS", rep
    assert rep["checks"]["report"]["before_since"] == 1
    assert rep["checks"]["report"]["state"] in {"ready", "not_ready", "awaiting_accrual"}


def test_report_fail_and_incomplete(tmp_path):
    bad = _tree(tmp_path / "a", shadow=_good_rows() + [_row("2026-10-27T13:40:00+00:00", haiku="",
                                                            rnd="")])
    assert g.report(bad, CUT, "s", [])["verdict"] == "FAIL"
    empty = _tree(tmp_path / "b")
    rep = g.report(empty, CUT, "s", [])
    assert rep["verdict"] == "INCOMPLETE"
    assert rep["checks"]["report"]["status"] == "NO_DATA"
    assert g.report(empty, None, "s", [])["verdict"] == "INCOMPLETE"


def _digest(root: Path) -> dict[str, str]:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_main_exit_codes_and_reads_only(tmp_path, capsys):
    root = _tree(tmp_path, shadow=_good_rows(),
                 coach={"mode": "arena", "camp_phase": True, "game_id": 1})
    before = _digest(root)
    assert g.main(["--data-root", str(root)]) == 1  # no anvil row yet
    out = capsys.readouterr().out
    assert "G7-17 read-back: INCOMPLETE" in out and "Not a tick" in out
    assert g.main(["--data-root", str(root), "--json"]) == 1
    rep = json.loads(capsys.readouterr().out)
    assert rep["checks"]["camp"]["status"] == "PASS"
    assert "game_id" not in json.dumps(rep)
    assert _digest(root) == before
    _write_jsonl(root / g.SHADOW_REL, _good_rows() + [_row("2026-10-27T13:50:00+00:00", haiku="",
                                                           rnd=0)])
    assert g.main(["--data-root", str(root)]) == 2
