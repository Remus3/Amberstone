"""tools/gated_g314_tower_input.py - the G3-14 tower-input sampler and grader (s144 lane gated cycle 56).

Read-only plumbing for the next ARAM Mayhem game; nothing here ticks a row.
Source pins first (the keys the tool reads are the keys the shipped code
writes), then the file readers, the sampler against a stub fetch, the grade
predicates and the CLI. All data is synthetic: no Riot id, no champion name.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from tools import gated_g314_tower_input as g

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "gated_g314_tower_input.py"
START = 1_000_000.0  # epoch of game time 0 in the synthetic games
KILL = 400.0         # down_at_s of the first turret kill
ENEMY_TURRET = "Turret_T2_R_03_A"  # CHAOS side; my_team ORDER below
OWN_TURRET = "Turret_T1_C_05_A"


def _iso(epoch: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _s(gt: float | None, *, my=100.0, en=100.0, team="ORDER", turrets=(), hp=900.0,
       frame_age=2.0, mode="aram", lc=True, fresh=True, shadow_ok=True) -> dict:
    t = START + (gt or 0.0)
    return {
        "t": t, "state_ok": True, "mode_key": mode, "liveclient": lc, "game_time_s": gt, "hp": hp,
        "turret_events": [{"down_at_s": d, "name": n} for d, n in turrets],
        "file_mtime": (t - 1.0) if fresh else (START - 86400.0), "file_mode": "aram",
        "my_team": team, "my_tower_hp": my, "enemy_tower_hp": en,
        "shadow_last": {"ts": _iso(t - 5.0 if shadow_ok else START - 86400.0), "mode": "aram",
                        "n_enemy": 5},
        "frame_ts": None if frame_age is None else t - frame_age, "frame_age_s": frame_age,
    }


def _game(values: dict[float, float], *, turret=ENEMY_TURRET, field="en", **kw) -> list[dict]:
    """Samples every 25 s from 300 to 475 game seconds, the kill at 400."""
    out = []
    for gt in range(300, 476, 25):
        ev = [(KILL, turret)] if gt >= KILL else []
        v = values.get(float(gt), 100.0)
        args = {"my": v} if field == "my" else {"en": v}
        out.append(_s(float(gt), turrets=ev, **args, **kw))
    return out


# --- source pins ------------------------------------------------------------

def test_seed_is_100_100_in_blank_artifact():
    src = (ROOT / "coaches" / "aram_coach.py").read_text(encoding="utf-8")
    body = src[src.index("def _blank_artifact_data"):]
    body = body[:body.index("\n    def ", 10)]
    assert '"my_tower_hp": 100, "enemy_tower_hp": 100' in body
    assert g.SEED_HP == 100


def test_run_vision_writes_tower_fields_only_when_not_none():
    src = (ROOT / "coaches" / "aram_coach.py").read_text(encoding="utf-8")
    assert '("my_tower_hp",    state.get("my_tower_hp"))' in src
    assert '("enemy_tower_hp", state.get("enemy_tower_hp"))' in src
    assert re.search(r"if v is not None:\s+cur\[k\] = v", src)


def test_liveclient_emits_turret_events_shape():
    src = (ROOT / "dashboard" / "_liveclient.py").read_text(encoding="utf-8")
    assert 'out["turret_events"] = turret_events' in src
    assert '"name": _str_or(ev.get("TurretKilled"), None)' in src
    assert 'ev.get("EventName") != "TurretKilled"' in src


def test_shadow_record_carries_ts_mode_enemy_comp():
    src = (ROOT / "core" / "aram_coach_shadow.py").read_text(encoding="utf-8")
    rec = src[src.index("record: dict = {"):]
    rec = rec[:rec.index("}")]
    for key in ('"ts": ts', '"mode": str(mode_key or "")', '"enemy_comp": enemy_comp'):
        assert key in rec


def test_frame_meta_route_exists():
    src = (ROOT / "vision_server" / "_http.py").read_text(encoding="utf-8")
    assert '"/latest-frame/meta"' in src


def test_tool_is_read_only_and_ascii():
    raw = TOOL.read_bytes()
    assert raw.decode("ascii") and b"\r" not in raw
    src = raw.decode("ascii")
    for banned in ("write_text", "write_bytes", ".unlink(", "os.remove", "shutil", 'open("w',
                   "'w')", '"w")', '"a")', "subprocess", "restart_trigger"):
        assert banned not in src, banned
    assert src.count(".open(") == 1 and 'path.open("rb")' in src


# --- readers ----------------------------------------------------------------

def test_read_coach_fields_and_missing(tmp_path):
    p = tmp_path / "c.json"
    assert g.read_coach(p) == {}
    p.write_text(json.dumps({"mode": "aram", "my_team": "CHAOS", "my_tower_hp": 55,
                             "enemy_tower_hp": None, "champion": "X"}), encoding="utf-8")
    r = g.read_coach(p)
    assert r["file_mode"] == "aram" and r["my_team"] == "CHAOS"
    assert r["my_tower_hp"] == 55.0 and r["enemy_tower_hp"] is None
    assert "champion" not in r and isinstance(r["file_mtime"], float)
    p.write_text("[1, 2]", encoding="utf-8")
    assert g.read_coach(p) == {}


def test_read_shadow_tail_last_complete_row(tmp_path):
    p = tmp_path / "s.jsonl"
    assert g.read_shadow_tail(p) is None
    rows = [{"ts": "2026-01-01T00:00:00+00:00", "mode": "aram", "enemy_comp": ["a"] * 5}] * 50
    rows.append({"ts": "2026-01-02T00:00:00+00:00", "mode": "aram", "enemy_comp": []})
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n{broken", encoding="utf-8")
    tail = g.read_shadow_tail(p, tail_bytes=300)
    assert tail == {"ts": "2026-01-02T00:00:00+00:00", "mode": "aram", "n_enemy": 0}


def test_side_of():
    assert g.side_of(ENEMY_TURRET) == "CHAOS"
    assert g.side_of(OWN_TURRET) == "ORDER"
    assert g.side_of("Turret_T1_T2_x") is None
    assert g.side_of(None) is None and g.side_of("Obelisk") is None


# --- sampler ----------------------------------------------------------------

def test_sample_with_stub_fetch(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / g.COACH_REL).write_text(json.dumps(
        {"mode": "aram", "my_team": "ORDER", "my_tower_hp": 100, "enemy_tower_hp": 70}),
        encoding="utf-8")
    (tmp_path / g.SHADOW_REL).write_text(json.dumps(
        {"ts": "2026-01-01T00:00:00+00:00", "mode": "aram", "enemy_comp": list("abcde")}) + "\n",
        encoding="utf-8")
    calls = []

    def fetch(url, token):
        calls.append((url, token))
        if url.endswith("/api/state"):
            return {"mode_key": "aram", "liveclient": {
                "game_time_s": 412.5, "hp": 800, "summonerName": "secret",
                "turret_events": [{"down_at_s": 400.0, "name": ENEMY_TURRET}, {"bad": 1}]}}
        return {"ts": 4999.0}

    s = g.sample(fetch=fetch, now=lambda: 5000.0, data_root=tmp_path, token="tok")
    assert calls[0] == (f"{g.DASH_BASE}/api/state", None)
    assert calls[1] == (f"{g.RELAY_BASE}/latest-frame/meta", "tok")
    assert s["game_time_s"] == 412.5 and s["hp"] == 800.0
    assert s["turret_events"] == [{"down_at_s": 400.0, "name": ENEMY_TURRET}]
    assert s["enemy_tower_hp"] == 70.0 and s["my_team"] == "ORDER"
    assert s["shadow_last"]["n_enemy"] == 5 and s["frame_age_s"] == 1.0
    assert "secret" not in json.dumps(s)


def test_sample_degrades_when_everything_is_down(tmp_path):
    s = g.sample(fetch=lambda u, t: None, now=lambda: 1.0, data_root=tmp_path, token="")
    assert s["state_ok"] is False and s["liveclient"] is False
    assert s["my_tower_hp"] is None and s["shadow_last"] is None and s["frame_age_s"] is None
    assert g.grade([s])["verdict"] == "NO_GAME"


# --- grade --------------------------------------------------------------------

def test_no_game():
    r = g.grade([_s(None, lc=False, mode="client")])
    assert r["verdict"] == "NO_GAME" and "writer" not in r["checks"]


def test_pass_enemy_field_moves_below_100():
    r = g.grade(_game({375.0: 40.0, 400.0: 12.0}))
    t = r["checks"]["tower"]
    assert r["verdict"] == "PASS" and t["field"] == "enemy_tower_hp"
    assert t["window_values"] == [12.0, 40.0, 100.0]
    assert "ASSUMED" in t["side_mapping"]


def test_pass_own_side_reads_my_tower_hp():
    r = g.grade(_game({350.0: 60.0}, turret=OWN_TURRET, field="my"))
    assert r["verdict"] == "PASS" and r["checks"]["tower"]["field"] == "my_tower_hp"


def test_chaos_team_flips_the_field():
    r = g.grade(_game({350.0: 60.0}, turret=ENEMY_TURRET, field="my", team="CHAOS"))
    assert r["checks"]["tower"]["field"] == "my_tower_hp" and r["verdict"] == "PASS"


def test_single_held_non_seed_value_is_not_pass():
    vals = {float(gt): 70.0 for gt in range(300, 476, 25)}
    r = g.grade(_game(vals))
    assert r["verdict"] == "NO_RESULT" and r["checks"]["tower"]["window_values"] == [70.0]


def test_held_100_with_full_coverage():
    r = g.grade(_game({}))
    assert r["verdict"] == "HELD_100" and "on screen" in r["checks"]["tower"]["note"]
    assert g.EXIT.get(r["verdict"], 1) == 1


def test_held_100_downgrades_on_dead_stale_or_gap():
    dead = _game({})
    dead[3]["hp"] = 0.0
    assert g.grade(dead)["checks"]["tower"]["state"] == "NO_RESULT"
    stale = _game({}, frame_age=30.0)
    assert "frame" in g.grade(stale)["checks"]["tower"]["reason"]
    unknown = _game({}, frame_age=None)
    assert g.grade(unknown)["checks"]["tower"]["state"] == "NO_RESULT"
    gap = [s for s in _game({}) if s["game_time_s"] not in (375.0, 400.0)]
    assert "gap" in g.grade(gap)["checks"]["tower"]["reason"]
    short = [s for s in _game({}) if s["game_time_s"] >= 375.0]
    assert "covers" in g.grade(short)["checks"]["tower"]["reason"]


def test_no_turret_and_stale_artifact():
    no_kill = [_s(float(gt)) for gt in range(300, 476, 25)]
    assert g.grade(no_kill)["checks"]["tower"]["reason"].startswith("no turret")
    stale = _game({375.0: 40.0}, fresh=False)
    r = g.grade(stale)
    assert r["checks"]["tower"]["state"] == "NO_RESULT" and "my_team" in r["checks"]["tower"]["reason"]


def test_record_after_kill_and_zero():
    r = g.grade(_game({375.0: 40.0, 425.0: 0.0, 450.0: 100.0}))
    rec = r["checks"]["tower"]["record"]
    assert rec["reached_zero"] is True and rec["after_kill_values"] == [0.0, 100.0]


def test_writer_fail_incomplete_and_pass():
    long_dead = [_s(float(gt), shadow_ok=False) for gt in range(100, 476, 25)]
    r = g.grade(long_dead)
    assert r["checks"]["writer"]["state"] == "FAIL" and r["verdict"] == "FAIL"
    assert g.EXIT[r["verdict"]] == 2
    short_dead = [_s(float(gt), shadow_ok=False) for gt in range(300, 401, 25)]
    r = g.grade(short_dead)
    assert r["checks"]["writer"]["state"] == "INCOMPLETE" and r["verdict"] == "INCOMPLETE"
    four = _game({375.0: 40.0})
    for s in four:
        s["shadow_last"]["n_enemy"] = 4
    assert g.grade(four)["checks"]["writer"]["state"] != "PASS"


# --- CLI ----------------------------------------------------------------------

def test_cli_grade_file(tmp_path, capsys):
    p = tmp_path / "ev.jsonl"
    p.write_text("\n".join(json.dumps(s) for s in _game({375.0: 40.0})) + "\nnot json\n",
                 encoding="utf-8")
    assert g.main(["--grade", str(p)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("G3-14 tower input: PASS") and "not a tick" in out
    assert g.main(["--grade", str(p), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "PASS"
    assert g.main(["--grade", str(tmp_path / "missing.jsonl")]) == 1
    assert str(tmp_path) not in capsys.readouterr().err


def test_cli_ctrl_c_grades_the_samples_taken(monkeypatch, capsys):
    taken = iter([_s(300.0)])

    def fake_sample(data_root=None):
        try:
            return next(taken)
        except StopIteration:
            raise KeyboardInterrupt from None

    monkeypatch.setattr(g, "sample", fake_sample)
    monkeypatch.setattr(g.time, "sleep", lambda s: None)
    assert g.main(["--samples", "5", "--interval", "0"]) == 1
    cap = capsys.readouterr()
    assert len(cap.out.strip().splitlines()) == 1
    assert cap.err.startswith("G3-14 tower input: NO_RESULT (1 samples)")


def test_relay_token_falls_back_to_the_main_checkout(monkeypatch):
    seen = []
    monkeypatch.setattr(g, "resolve_token", lambda root: (seen.append(root) or ("tok", "main-config")))
    assert g._relay_token() == "tok" and seen == [g._ROOT]


def test_load_samples_tolerates_non_utf8(tmp_path):
    p = tmp_path / "ev.jsonl"
    p.write_bytes(json.dumps(_s(300.0)).encode("ascii") + b"\n\xff\xfe junk\n")
    assert len(g.load_samples(p)) == 1
