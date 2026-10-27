"""tools/gated_tft15_planner.py - the TFT-15 read-back (s144 lane gated cycle 6).

Read-only plumbing for a live TFT session; nothing here ticks a row. All data is
synthetic: unit names are placeholders, team ids and titles are made up, and the
codes below are H1-shaped test inputs, NOT codes the client produced.
"""
from __future__ import annotations

import ast
import calendar
import json
from pathlib import Path

import pytest

from tools import gated_tft15_planner as g

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "gated_tft15_planner.py"
STAMP = "[2026.01.02-03.04.05:006][123]"
T_STAMP = calendar.timegm((2026, 1, 2, 3, 4, 5)) + 0.006  # STAMP, UTC epoch


@pytest.fixture
def meta(tmp_path: Path) -> Path:
    (tmp_path / "tft_set18_champion_codes.json").write_text(
        json.dumps({"UnitA": 1001, "UnitB": 1002, "UnitC": 1085}), encoding="utf-8")
    return tmp_path


def _code(*codes: int, width: int = 10, tail: str = "TFTSet18", prefix: str = "02") -> str:
    return g.encode_h1(prefix, list(codes), width, tail)


# -- decode --------------------------------------------------------------------

def test_parse_h1_splits_prefix_slots_and_tail():
    p = g.parse_h1(_code(1001, 1002))
    assert p["ok"] and p["prefix"] == "02" and p["tail"] == "TFTSet18"
    assert p["slots"][:3] == ["3e9", "3ea", "000"] and len(p["slots"]) == 10


def test_decode_pass_reports_units_and_order(meta):
    res = g.decode(_code(1001, 1085), None, ["UnitA", "UnitC"], meta)
    assert res["verdict"] == "PASS", res["why"]
    assert res["units"] == ["UnitA", "UnitC"] and res["order_matches"] is True
    assert res["set"] == "TFTSet18" and res["slot_count"] == 10 and res["filled"] == 2
    assert res["round_trip"] is True


def test_decode_multiset_match_passes_with_order_reported(meta):
    res = g.decode(_code(1001, 1002), None, ["UnitB", "UnitA"], meta)
    assert res["verdict"] == "PASS" and res["order_matches"] is False


def test_decode_upper_case_hex_round_trips(meta):
    code = g.encode_h1("02", [1001, 1085], 10, "TFTSet18", upper=True)
    assert "3E9" in code
    assert g.decode(code, None, ["UnitA", "UnitC"], meta)["verdict"] == "PASS"


@pytest.mark.parametrize("code, expect, why", [
    ("02" + "3e9" + "3ea" + "00" + "TFTSet18", ["UnitA"], "multiple of 3"),
    ("02" + "zz9" + "000" + "TFTSet18", ["UnitA"], "hex"),
    ("02TFTSet18", ["UnitA"], "shorter"),
])
def test_decode_fails_when_h1_does_not_parse(meta, code, expect, why):
    res = g.decode(code, None, expect, meta)
    assert res["verdict"] == "FAIL" and why in res["why"]


def test_decode_fails_on_unknown_code(meta):
    res = g.decode(_code(1001, 0x7FF), None, ["UnitA"], meta)
    assert res["verdict"] == "FAIL" and res["unknown_codes"] == [0x7FF]


def test_decode_fails_when_units_differ(meta):
    res = g.decode(_code(1001, 1002), None, ["UnitA", "UnitC"], meta)
    assert res["verdict"] == "FAIL" and "differ" in res["why"]


def test_decode_fails_when_an_empty_slot_sits_between_units(meta):
    code = "02" + "3e9" + "000" + "3ea" + "000" * 7 + "TFTSet18"
    res = g.decode(code, None, ["UnitA", "UnitB"], meta)
    assert res["verdict"] == "FAIL" and res["empty_between"] is True
    assert res["round_trip"] is False


def test_decode_incomplete_without_expect_or_set(meta):
    assert g.decode(_code(1001), None, None, meta)["verdict"] == "INCOMPLETE"
    res = g.decode(_code(1001, tail=""), None, ["UnitA"], meta)
    assert res["verdict"] == "INCOMPLETE" and "--set" in res["why"]
    assert g.decode(_code(1001, tail=""), "TFTSet18", ["UnitA"], meta)["verdict"] == "PASS"


def test_decode_incomplete_when_the_set_has_no_codes_file(meta):
    res = g.decode(_code(1001, tail="TFTSet99"), None, ["UnitA"], meta)
    assert res["verdict"] == "INCOMPLETE" and "TFTSet99" in res["why"]


def test_tracked_set18_codes_file_loads_and_fits_three_hex_digits():
    codes = g.load_codes("TFTSet18")
    assert codes and all(0 < v <= 0xFFF for v in codes.values())


# -- TFT.log scan ------------------------------------------------------------------

LOG_LINES = [
    STAMP + "TFT: [Client] TFTPlannerSubsystem_7: Set dat loaded for DefaultSet: TFTSet18, EventSet: .",
    STAMP + "TFT: [Client] TFTPlannerSubsystem_7: Player TeamPlanner Data received",
    STAMP + "TFT: [Client] TFTPlannerSubsystem_7: Player TeamPlanner data saved.",
    STAMP + "TFT: [Client] TFTPlannerSubsystem_7: Saved TeamPlanner PlayerPreferences.",
    STAMP + "TFT: [Client] TFTPlannerSubsystem_7: Deferring player data SECRET-OTHER-TEXT",
    STAMP + "LogChat: SECRET-CHAT-LINE TFTPlannerSubsystem_7: Player TeamPlanner Data received",
    "no stamp TFT: [Client] TFTPlannerSubsystem_7: Player TeamPlanner Data received",
]


def test_scan_keeps_allowlisted_kinds_only():
    ev = g.scan_log_lines([ln + "\r\n" for ln in LOG_LINES])
    assert [e["kind"] for e in ev] == ["set_loaded", "data_received", "data_saved", "prefs_saved"]
    assert ev[0]["set"] == "TFTSet18" and ev[1]["ts"] == pytest.approx(T_STAMP)
    assert ev[1]["iso"].startswith("2026-01-02T03:04:05.006")
    assert "SECRET" not in json.dumps(ev)


def test_scan_accepts_bytes_and_drops_lines_before_since():
    raw = [ln.encode("utf-8") for ln in LOG_LINES]
    assert len(g.scan_log_lines(raw)) == 4
    assert g.scan_log_lines(raw, since=T_STAMP + 1) == []


def test_scan_log_reads_a_file_and_reports_an_unreadable_one(tmp_path):
    f = tmp_path / "TFT.log"
    f.write_bytes("\n".join(LOG_LINES).encode("utf-8"))
    res = g.scan_log(f, None)
    assert res["readable"] and res["counts"] == {"set_loaded": 1, "data_received": 1,
                                                  "data_saved": 1, "prefs_saved": 1}
    gone = g.scan_log(tmp_path / "missing.log", None)
    assert gone["readable"] is False and gone["events"] == []


# -- planner summary / snapshot ------------------------------------------------------

TEAM_A = {"id": "team-uuid-secret-1", "title": "SECRET-TITLE",
          "champions": [{"championId": "TFT18_UnitA"}, {"championId": "TFT18_UnitB"}]}
TEAM_B = {"id": "team-uuid-secret-2", "title": "Other", "champions": ["TFT18_UnitC"]}


@pytest.mark.parametrize("dirty, shape", [
    ({"TFTSet18": [TEAM_A, TEAM_B]}, "by_set"),
    ({"TFTSet18": {"teams": [TEAM_A, TEAM_B]}}, "by_set"),
    ([TEAM_A, TEAM_B], "flat_list"),
])
def test_summary_keeps_units_and_digests_never_titles_or_ids(dirty, shape):
    s = g.summarise_planner({"setId": "TFTSet18", "optionalTeamId": "x"}, dirty)
    assert s["dirty_shape"] == shape and s["context_set"] == "TFTSet18"
    teams = next(iter(s["sets"].values()))["teams"]
    assert sorted(t["units"] for t in teams.values()) == [["TFT18_UnitA", "TFT18_UnitB"],
                                                          ["TFT18_UnitC"]]
    blob = json.dumps(s)
    assert "SECRET" not in blob and "team-uuid" not in blob


def test_summary_marks_an_unrecognised_shape():
    assert g.summarise_planner(None, "text")["dirty_shape"] == "unrecognised"
    assert g.summarise_planner(None, {"TFTSet18": 3})["dirty_shape"] == "unrecognised"


def test_summary_survives_a_scalar_champions_field():
    s = g.summarise_planner({}, {"TFTSet18": [{"id": "t", "champions": 7}]})
    assert next(iter(s["sets"]["TFTSet18"]["teams"].values()))["units"] == []


def test_id_less_team_keys_do_not_shift_when_a_team_is_removed():
    t1 = {"champions": ["TFT18_UnitA"]}
    t2 = {"champions": ["TFT18_UnitB"]}
    both = g.summarise_planner({}, {"TFTSet18": [t1, t2]})["sets"]["TFTSet18"]["teams"]
    one = g.summarise_planner({}, {"TFTSet18": [t2]})["sets"]["TFTSet18"]["teams"]
    key_of_t2 = {k for k, v in both.items() if v["units"] == ["TFT18_UnitB"]}
    assert set(one) == key_of_t2  # t2 keeps its key after t1 (index 0) is removed


def test_snapshot_with_injected_getter(tmp_path):
    answers = {g.CONTEXT_EP: {"setId": "TFTSet18"}, g.DIRTY_EP: {"TFTSet18": [TEAM_A]},
               g.PHASE_EP: "InProgress"}
    calls = []

    def get(ep):
        calls.append(ep)
        return answers[ep]
    res = g.snapshot(get, tmp_path / "none.log", None)
    assert res["verdict"] == "SNAPSHOT" and res["gameflow_phase"] == "InProgress"
    assert res["planner"]["sets"]["TFTSet18"]["team_count"] == 1
    assert res["log"]["readable"] is False
    assert calls == [g.CONTEXT_EP, g.DIRTY_EP, g.PHASE_EP]


def test_snapshot_without_a_planner_read_is_no_lcu(tmp_path):
    res = g.snapshot(lambda ep: None, tmp_path / "none.log", None)
    assert res["verdict"] == "NO_LCU" and res["planner"] is None


# -- diff ------------------------------------------------------------------------------

def _snap(teams, events, ts, phase="InProgress", dirty=None):
    return {"read_at": "x", "read_ts": ts, "gameflow_phase": phase,
            "planner": g.summarise_planner({}, {"TFTSet18": teams} if dirty is None else dirty),
            "log": {"events": events}}


def _ev(kind, ts):
    return {"kind": kind, "ts": ts, "iso": "x"}


EDITED = dict(TEAM_A, champions=[{"championId": "TFT18_UnitC"}])


def test_diff_no_change():
    a = _snap([TEAM_A], [], 100.0)
    assert g.diff(a, _snap([TEAM_A], [_ev("data_saved", 150.0)], 200.0),
                  "game-to-lcu", edit_at=120.0)["verdict"] == "NO_CHANGE"


def test_diff_direction_picks_the_signal_line():
    before = _snap([TEAM_A], [_ev("data_received", 50.0)], 100.0)
    after = _snap([EDITED], [_ev("data_received", 50.0), _ev("data_saved", 150.0)], 200.0)
    res = g.diff(before, after, "game-to-lcu", edit_at=120.0)
    assert res["verdict"] == "PROPAGATED_LOG"
    assert res["changes"][0]["change"] == "edited"
    assert res["changes"][0]["units_after"] == ["TFT18_UnitC"]
    assert [e["kind"] for e in res["new_log_events"]] == ["data_saved"]
    assert g.diff(before, after, "lcu-to-game")["verdict"] == "NO_LOG_SIGNAL"


def test_diff_signal_must_follow_the_edit_time():
    before = _snap([TEAM_A], [], 100.0)
    after = _snap([EDITED], [_ev("data_saved", 150.0)], 200.0)
    assert g.diff(before, after, "game-to-lcu", edit_at=160.0)["verdict"] == "NO_LOG_SIGNAL"


def test_diff_game_to_lcu_needs_the_edit_time():
    before = _snap([TEAM_A], [], 100.0)
    after = _snap([EDITED], [_ev("data_saved", 150.0)], 200.0)
    res = g.diff(before, after, "game-to-lcu")
    assert res["verdict"] == "INCOMPLETE" and "--edit-at" in res["why"]


def test_diff_drops_an_event_already_in_before():
    before = _snap([TEAM_A], [_ev("data_received", 150.0)], 100.0)
    after = _snap([EDITED], [_ev("data_received", 150.0)], 200.0)
    res = g.diff(before, after, "lcu-to-game")
    assert res["verdict"] == "NO_LOG_SIGNAL" and res["new_log_events"] == []


@pytest.mark.parametrize("phase_b, phase_a", [("Lobby", "InProgress"), ("InProgress", None)])
def test_diff_needs_both_snapshots_mid_match(phase_b, phase_a):
    before = _snap([TEAM_A], [], 100.0, phase=phase_b)
    after = _snap([EDITED], [_ev("data_received", 150.0)], 200.0, phase=phase_a)
    res = g.diff(before, after, "lcu-to-game")
    assert res["verdict"] == "INCOMPLETE" and "InProgress" in res["why"]


@pytest.mark.parametrize("dirty", [{"TFTSet18": True}, {"TFTSet18": []}, ["TFTSet18"]])
def test_diff_unparsed_planner_is_never_no_change(dirty):
    a = _snap([], [], 100.0, dirty=dirty)
    b = _snap([], [], 200.0, dirty=dirty)
    assert g.diff(a, b, "lcu-to-game")["verdict"] == "INCOMPLETE"


def test_diff_ignores_log_lines_older_than_before():
    before = _snap([TEAM_A], [], 100.0)
    after = _snap([TEAM_A, TEAM_B], [_ev("data_received", 90.0)], 200.0)
    res = g.diff(before, after, "lcu-to-game")
    assert res["verdict"] == "NO_LOG_SIGNAL" and res["changes"][0]["change"] == "added"


def test_diff_incomplete_without_a_planner_read():
    before = {"planner": None, "log": {"events": []}}
    assert g.diff(before, _snap([TEAM_A], [], 1.0), "lcu-to-game")["verdict"] == "INCOMPLETE"


# -- CLI ---------------------------------------------------------------------------------

def test_main_exit_codes(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(g, "META_DIR", tmp_path)
    (tmp_path / "tft_set18_champion_codes.json").write_text('{"UnitA": 1001}', encoding="utf-8")
    assert g.main(["decode", _code(1001), "--expect", "UnitA"]) == 0
    assert g.main(["decode", _code(1001)]) == 1
    assert g.main(["decode", "02TFTSet18", "--expect", "UnitA"]) == 2
    capsys.readouterr()
    b, a = tmp_path / "b.json", tmp_path / "a.json"
    b.write_text(json.dumps(_snap([TEAM_A], [], 100.0)), encoding="utf-8")
    a.write_text(json.dumps(_snap([TEAM_B], [_ev("data_saved", 150.0)], 200.0)),
                 encoding="utf-8")
    assert g.main(["diff", str(b), str(a), "--direction", "game-to-lcu", "--json",
                   "--edit-at", "1970-01-01T00:02:00+00:00"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == "PROPAGATED_LOG" and out["direction"] == "game-to-lcu"
    assert out["edit_at"].startswith("1970-01-01T00:02:00")
    assert g.main(["diff", str(b), str(a), "--direction", "game-to-lcu"]) == 1
    with pytest.raises(SystemExit) as exc:
        g.main(["snapshot", "--since", "not-a-time"])
    assert exc.value.code == 2


# -- source pins ---------------------------------------------------------------------------

def _calls(src: str):
    return [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)]


def test_the_only_lcu_call_is_a_get():
    src = TOOL.read_text(encoding="utf-8")
    req = [c for c in _calls(src)
           if isinstance(c.func, ast.Attribute) and c.func.attr == "_request"]
    assert len(req) == 1
    assert isinstance(req[0].args[0], ast.Constant) and req[0].args[0].value == "GET"
    for verb in ("POST", "PUT", "PATCH", "DELETE"):
        assert f'"{verb}"' not in src and f"'{verb}'" not in src
    # No other LcuClient helper (several wrap a POST) is reachable either.
    on_client = {c.func.attr for c in _calls(src) if isinstance(c.func, ast.Attribute)
                 and isinstance(c.func.value, ast.Name) and c.func.value.id == "client"}
    assert on_client == {"connect", "_request"}


def test_tool_writes_nothing():
    src = TOOL.read_text(encoding="utf-8")
    banned = {"write_text", "write_bytes", "unlink", "rename", "replace", "mkdir", "rmdir",
              "touch", "remove", "rmtree"}
    for c in _calls(src):
        name = c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", "")
        assert name not in banned, name
        if name == "open":
            pytest.fail("a bare open() call found; reads go through _open_shared")


def test_h1_basis_is_still_the_legacy_probe_read():
    """H1's one measured fact: ``code[2:5]`` of a one-unit team is its code in hex."""
    src = (ROOT / "scripts" / "discover_champion_codes.py").read_text(encoding="utf-8")
    assert "prefix = code[2:5]" in src and "int(prefix, 16)" in src
    assert 'if prefix != "000"' in src
