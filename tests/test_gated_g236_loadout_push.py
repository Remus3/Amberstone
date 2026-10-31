"""Tests for tools/gated_g236_loadout_push.py (G2-36 PREP, s144 lane gated c41).

Every input is hand-built (RM-906: no real game, match, account or player id).
The tool is a read-only grader; these tests pin its verdicts, that its log
regex reads the exact line shape tools/lcu_agent.py writes, and that the
in-game switcher still pushes items only, as the apply_item_set verb.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from tools import gated_g236_loadout_push as g236

ROOT = Path(__file__).resolve().parent.parent

IN_GAME = {"mode_key": "sr", "lcu": {"phase": "InProgress", "ts": 1},
           "liveclient": {"game_time_s": 612.0}}
IDLE = {"mode_key": "client", "lcu": {"phase": None}, "liveclient": {}}

GOOD = ("2026-01-02 18:10:05,250 INFO   [cmd] apply_item_set -> "
        "{'ok': True, 'set_uid': 'RC-ezreal-sr-ub-1', 'title': 'RC: Ezreal X (SR)'}")


def _rec(line: str) -> dict:
    recs = g236.parse_log_lines([line])
    assert len(recs) == 1
    return recs[0]


def _window(records, before=IN_GAME, after=IN_GAME, prefix=""):
    return g236.grade_log(records, datetime(2026, 1, 2, 18, 10, 0),
                          datetime(2026, 1, 2, 18, 11, 0),
                          g236.grade_state(before), g236.grade_state(after), prefix)


def test_state_in_game_by_phase_or_liveclient():
    assert g236.grade_state(IN_GAME)["verdict"] == "IN_GAME"
    assert g236.grade_state({"lcu": {"phase": "InProgress"}})["verdict"] == "IN_GAME"
    assert g236.grade_state({"liveclient": {"game_time_s": 5}})["verdict"] == "IN_GAME"
    # mode_key alone is never the gate (a TFT game reads "client").
    assert g236.grade_state({"mode_key": "sr"})["verdict"] == "NOT_IN_GAME"
    assert g236.grade_state(IDLE)["verdict"] == "NOT_IN_GAME"
    assert g236.grade_state({"lcu": {"phase": "ChampSelect"}})["verdict"] == "NOT_IN_GAME"
    assert g236.grade_state([1, 2])["verdict"] == "NOT_IN_GAME"
    assert g236.grade_state(IN_GAME)["game_time_s"] == 612.0


def test_parse_reads_the_agent_line_and_result():
    rec = _rec(GOOD)
    assert rec["verb"] == "apply_item_set" and rec["tag"] == "cmd"
    assert rec["when"] == datetime(2026, 1, 2, 18, 10, 5, 250000)
    assert rec["result"]["set_uid"] == "RC-ezreal-sr-ub-1"


def test_batch_verb_is_not_the_single_push_verb():
    rec = _rec("2026-01-02 18:10:05,250 INFO   [cmd] apply_item_sets_batch -> "
               "{'ok': True, 'set_uids': ['RC-A-sr-x'], 'count': 1}")
    res = _window([rec])
    assert res["verdict"] == "NO_PUSH"
    assert res["other_cmds"] == ["apply_item_sets_batch"]


def test_parse_skips_non_cmd_lines_and_keeps_unparsable_results():
    assert g236.parse_log_lines([
        "2026-01-02 18:10:05,250 INFO [lcu] connected port=1",
        "garbage", ""]) == []
    rec = _rec("2026-01-02 18:10:05,250 INFO   [cmd] apply_item_set -> <not a dict")
    assert rec["result"] is None


def test_push_ok_in_window():
    assert _window([_rec(GOOD)])["verdict"] == "PUSH_OK"
    assert _window([_rec(GOOD)], prefix=g236.uid_prefix_for("Ezreal"))["verdict"] == "PUSH_OK"
    assert _window([_rec(GOOD)], prefix=g236.uid_prefix_for("Jinx"))["verdict"] == "PUSH_FAILED"
    assert _window([_rec(GOOD)], prefix=g236.uid_prefix_for(""))["verdict"] == "PUSH_OK"


def test_uid_prefix_is_the_production_norm():
    from coaches import loadout_resolver as lr
    for name in ("Ezreal", "Kai'Sa", "Dr. Mundo", "Nunu & Willump", "Bel'Veth", "MonkeyKing"):
        assert g236.norm_champion(name) == lr._norm(name)
    assert g236.uid_prefix_for("Kai'Sa") == "RC-kaisa-"
    route = (ROOT / "dashboard" / "routes_loadout.py").read_text(encoding="utf-8")
    assert 'f"RC-{_norm(champion)}-{mode_key}-ub-{uid}"' in route
    res = (ROOT / "coaches" / "loadout_resolver.py").read_text(encoding="utf-8")
    assert 'f"RC-{_norm(champion)}-{mode_key}-{_norm(identity)}"' in res


def test_push_outside_window_is_no_push():
    rec = _rec(GOOD.replace("18:10:05", "18:12:05"))
    assert _window([rec])["verdict"] == "NO_PUSH"


def test_failed_results_are_push_failed():
    for line in (
        GOOD.replace("'ok': True", "'ok': False"),
        "2026-01-02 18:10:05,250 INFO   [cmd] apply_item_set -> {'ok': False, 'err': 'no_lcu'}",
        "2026-01-02 18:10:05,250 WARNING   [cmd-exc] apply_item_set -> "
        "{'ok': True, 'set_uid': 'RC-A'}",
        GOOD.replace("'set_uid': 'RC-ezreal-sr-ub-1'", "'set_uid': 'Mine'"),
        GOOD.replace("'ok': True", "'ok': 1"),
    ):
        assert _window([_rec(line)])["verdict"] == "PUSH_FAILED", line


def test_not_mid_game_and_bad_window():
    assert _window([_rec(GOOD)], before=IDLE)["verdict"] == "NOT_MID_GAME"
    assert _window([_rec(GOOD)], after=IDLE)["verdict"] == "NOT_MID_GAME"
    res = g236.grade_log([_rec(GOOD)], datetime(2026, 1, 2, 18, 11), datetime(2026, 1, 2, 18, 10),
                         g236.grade_state(IN_GAME), g236.grade_state(IN_GAME))
    assert res["verdict"] == "BAD_WINDOW"


def test_regex_reads_a_line_from_the_agent_format_and_fstring(tmp_path):
    """Render a line with lcu_agent's own format string and drain f-string."""
    src = (ROOT / "tools" / "lcu_agent.py").read_text(encoding="utf-8")
    fmt = "%(asctime)s %(levelname)s %(message)s"
    assert f'format="{fmt}"' in src
    assert "log.info(f\"  [cmd] {cmd.get('cmd')} -> {result}\")" in src
    assert "log.warning(f\"  [cmd-exc] {cmd.get('cmd')} -> {result}\")" in src
    result = {"ok": True, "set_uid": "RC-ezreal-sr-ub-1", "title": "RC: X"}
    rec = logging.LogRecord("lcu_agent", logging.INFO, __file__, 1,
                            f"  [cmd] apply_item_set -> {result}", None, None)
    line = logging.Formatter(fmt).format(rec)
    parsed = g236.parse_log_lines([line])
    assert len(parsed) == 1 and parsed[0]["result"] == result


def test_switcher_pushes_items_only_as_apply_item_set():
    js = (ROOT / "web" / "js" / "panels" / "item_build.js").read_text(encoding="utf-8")
    body = js[js.index("function _ibPushItems("):js.index("function _ibOnRowClick(")]
    assert "/api/loadout/apply" in body
    assert "push_runes: false, push_summoners: false, push_items: true" in body
    route = (ROOT / "dashboard" / "routes_loadout.py").read_text(encoding="utf-8")
    assert f'"cmd":         "{g236.PUSH_VERB}"' in route
    assert "if push_items: _enqueue(resolved.get(\"item_cmd\"))" in route
    agent = (ROOT / "tools" / "lcu_agent.py").read_text(encoding="utf-8")
    assert f'if name == "{g236.PUSH_VERB}":' in agent
    assert 'return {"ok": True, "set_uid": set_uid, "title": title}' in agent


def test_cli_log_window_from_state_mtimes(tmp_path, capsys):
    f1, f2, log = tmp_path / "s1.json", tmp_path / "s2.json", tmp_path / "lcu_agent.log"
    f1.write_text(json.dumps(IN_GAME), encoding="utf-8")
    f2.write_text(json.dumps(IN_GAME), encoding="utf-8")
    t1 = datetime(2026, 1, 2, 18, 10, 0).timestamp()
    t2 = datetime(2026, 1, 2, 18, 11, 0).timestamp()
    os.utime(f1, (t1, t1))
    os.utime(f2, (t2, t2))
    log.write_text("noise\n" + GOOD + "\n", encoding="utf-8")
    argv = ["log", str(log), "--before-state", str(f1), "--after-state", str(f2), "--json"]
    assert g236.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "PUSH_OK"
    # The operator types the display name; the grader normalises it.
    assert g236.main(argv + ["--champion", "Ezreal"]) == 0
    capsys.readouterr()
    assert g236.main(argv + ["--champion", "Jinx"]) == 3
    assert json.loads(capsys.readouterr().out)["verdict"] == "PUSH_FAILED"
    log.write_text(GOOD.replace("18:10:05", "18:09:05") + "\n", encoding="utf-8")
    assert g236.main(argv) == 3
    assert json.loads(capsys.readouterr().out)["verdict"] == "NO_PUSH"


def test_cli_state_and_missing_file(tmp_path, capsys):
    f = tmp_path / "s.json"
    f.write_text(json.dumps(IDLE), encoding="utf-8")
    assert g236.main(["state", str(f)]) == 3
    assert capsys.readouterr().out.startswith("NOT_IN_GAME")
    f.write_text(json.dumps(IN_GAME), encoding="utf-8")
    assert g236.main(["state", str(f), "--json"]) == 0
    capsys.readouterr()
    assert g236.main(["state", str(tmp_path / "nope.json")]) == 2
    f.write_text("{not json", encoding="utf-8")
    assert g236.main(["state", str(f)]) == 2
