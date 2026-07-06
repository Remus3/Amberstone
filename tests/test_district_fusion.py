# arch: tests for core.district_fusion API-over-CV fusion | section=tests | frozen=no
"""Tests for core.district_fusion - ZOI Wave 2 spec C (agent-fusion).

Spec: docs/ZOI_DISTRICT_ORCHESTRATION_PLAN.md section 4 Wave 2 + section 5.
Ground truth grep-confirmed before scaffolding:
- dashboard/_liveclient.py:97 lc["game_time_s"]
- dashboard/_liveclient.py:176-185 lc["players"] rows
  {position, team ("ORDER"/"CHAOS"), creep_score, is_active} - NO
  isDead/respawnTimer surfaced today; fusion reads them fail-soft IF present
- dashboard/_liveclient.py:230-241 lc["inhib_events"] [{down_at_s, name}]
- dashboard/_liveclient.py:246-257 lc["turret_events"] [{down_at_s, name}]
- dashboard/_liveclient.py:265-301 lc["objective_events"]
  [{name: dragon/baron/herald, killer_team: ally/enemy/unknown, down_at_s}]
- core/event_callouts.py:104 lane tokens L/C/R -> top/mid/bot; :441-454
  inhib names Barracks_T2_L1; turret names Turret_T2_L_03_A (bare L/C/R part)
- config/minimap_grids/sr.json district ids incl. top_lane/mid_lane/bot_lane/
  dragon_pit/baron_pit; aram.json incl. aram_bridge
- core/mode_capabilities.py:80-95 has_capability fail-CLOSED
  (SR has_wards True; ARAM/ARENA/BRAWL/TFT False)
"""

import copy

import core.district_fusion as df
from core.district_fusion import OBJ_FUSE_WINDOW_S, fuse_districts


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _row(did, ally=0, enemy=0):
    """A presence-vector row in the agent-presence contract shape."""
    return {
        "id": did,
        "team_present": {"ally": ally, "enemy": enemy},
        "missing_since_s": {"ally": None, "enemy": None},
        "last_seen_t": {"ally": None, "enemy": None},
    }


def _sr_vector(**counts):
    ids = [
        "blue_base", "red_base", "baron_pit", "dragon_pit", "top_river",
        "bot_river", "mid_lane", "top_lane", "bot_lane", "jungle_top_blue",
        "jungle_top_red", "jungle_bot_blue", "jungle_bot_red",
    ]
    rows = []
    for did in ids:
        ally, enemy = counts.get(did, (0, 0))
        rows.append(_row(did, ally, enemy))
    return rows


def _aram_vector(**counts):
    rows = []
    for did in ["blue_base", "red_base", "aram_bridge", "brush_north",
                "brush_south"]:
        ally, enemy = counts.get(did, (0, 0))
        rows.append(_row(did, ally, enemy))
    return rows


def _players(ally_dead=0, enemy_dead=0, ally_side="ORDER", dead_key="is_dead"):
    """10 scoreboard rows; active player on ally_side. dead_key picks the
    spelling used to flag dead rows (fusion must accept several)."""
    enemy_side = "CHAOS" if ally_side == "ORDER" else "ORDER"
    rows = []
    for i in range(5):
        r = {"position": "", "team": ally_side, "creep_score": 0,
             "is_active": i == 0}
        if i < ally_dead:
            r[dead_key] = True if dead_key in ("is_dead", "isDead") else 12.5
        rows.append(r)
    for i in range(5):
        r = {"position": "", "team": enemy_side, "creep_score": 0,
             "is_active": False}
        if i < enemy_dead:
            r[dead_key] = True if dead_key in ("is_dead", "isDead") else 12.5
        rows.append(r)
    return rows


def _by_id(fused):
    return {r.get("id"): r for r in fused}


# ---------------------------------------------------------------------------
# constants + row-shape stability
# ---------------------------------------------------------------------------

def test_window_constant():
    assert OBJ_FUSE_WINDOW_S == 8.0


def test_row_shape_additive_and_input_not_mutated():
    vec = _sr_vector(mid_lane=(2, 3))
    snapshot = copy.deepcopy(vec)
    fused = fuse_districts(vec, {}, "sr", 600.0)
    assert vec == snapshot, "input vector must not be mutated"
    assert len(fused) == len(vec)
    for src, out in zip(vec, fused):
        for k, v in src.items():
            assert out[k] == v, "every input key survives untouched"
        extra = set(out) - set(src)
        assert extra == {"fused_present", "fusion_notes"}
        assert isinstance(out["fused_present"], dict)
        assert isinstance(out["fusion_notes"], list)


def test_no_events_counts_pass_through():
    vec = _sr_vector(mid_lane=(2, 3), top_lane=(1, 0))
    fused = _by_id(fuse_districts(vec, {}, "sr", 600.0))
    assert fused["mid_lane"]["fused_present"] == {"ally": 2, "enemy": 3}
    assert fused["top_lane"]["fused_present"] == {"ally": 1, "enemy": 0}
    assert fused["mid_lane"]["fusion_notes"] == []


# ---------------------------------------------------------------------------
# 1. dead-champ weight cap
# ---------------------------------------------------------------------------

def test_dead_cap_enemy_presence():
    vec = _sr_vector(mid_lane=(0, 5))
    lc = {"players": _players(enemy_dead=2)}
    fused = _by_id(fuse_districts(vec, lc, "sr", 600.0))
    assert fused["mid_lane"]["fused_present"]["enemy"] == 3
    assert any(n.startswith("dead_cap:enemy") for n in
               fused["mid_lane"]["fusion_notes"])


def test_dead_cap_ally_and_respawn_timer_spellings():
    # respawnTimer (raw Live Client) and respawn_in_s (vision_tracker) both
    # count as dead when > 0.
    for key in ("respawnTimer", "respawn_in_s", "isDead"):
        vec = _sr_vector(dragon_pit=(4, 0))
        lc = {"players": _players(ally_dead=3, dead_key=key)}
        fused = _by_id(fuse_districts(vec, lc, "sr", 600.0))
        assert fused["dragon_pit"]["fused_present"]["ally"] == 2, key


def test_dead_cap_inert_without_dead_fields():
    # Today's lc players rows carry NO death fields - cap must be inert.
    vec = _sr_vector(bot_lane=(0, 4))
    lc = {"players": _players()}  # no dead flags at all
    fused = _by_id(fuse_districts(vec, lc, "sr", 600.0))
    assert fused["bot_lane"]["fused_present"]["enemy"] == 4
    assert fused["bot_lane"]["fusion_notes"] == []


# ---------------------------------------------------------------------------
# 2. structure reclassify
# ---------------------------------------------------------------------------

def test_turret_kill_pins_lane_district_inside_window():
    vec = _sr_vector()
    lc = {
        "players": _players(),  # active player ORDER (T1) -> T2 kill = ally
        "turret_events": [{"down_at_s": 100.0, "name": "Turret_T2_L_03_A"}],
    }
    fused = _by_id(fuse_districts(vec, lc, "sr", 104.0))
    assert fused["top_lane"]["fused_present"]["ally"] >= 1
    assert any(n.startswith("structure:turret:ally") for n in
               fused["top_lane"]["fusion_notes"])


def test_turret_kill_outside_window_is_ignored():
    vec = _sr_vector()
    lc = {
        "players": _players(),
        "turret_events": [{"down_at_s": 100.0, "name": "Turret_T2_L_03_A"}],
    }
    fused = _by_id(fuse_districts(vec, lc, "sr", 100.0 + OBJ_FUSE_WINDOW_S + 0.1))
    assert fused["top_lane"]["fused_present"]["ally"] == 0
    assert fused["top_lane"]["fusion_notes"] == []


def test_inhib_kill_enemy_side_attribution():
    # Barracks_T1_... = an ORDER structure died; active player is ORDER, so
    # the killer is the enemy team. Lane token C1 -> mid.
    vec = _sr_vector()
    lc = {
        "players": _players(),
        "inhib_events": [{"down_at_s": 900.0, "name": "Barracks_T1_C1"}],
    }
    fused = _by_id(fuse_districts(vec, lc, "sr", 903.0))
    assert fused["mid_lane"]["fused_present"]["enemy"] >= 1
    assert any(n.startswith("structure:inhib:enemy") for n in
               fused["mid_lane"]["fusion_notes"])


def test_structure_reclassify_aram_pins_bridge():
    vec = _aram_vector()
    lc = {
        "players": _players(),
        "turret_events": [{"down_at_s": 300.0, "name": "Turret_T2_C_05_A"}],
    }
    fused = _by_id(fuse_districts(vec, lc, "aram", 302.0))
    assert fused["aram_bridge"]["fused_present"]["ally"] >= 1
    assert any(n.startswith("structure:turret") for n in
               fused["aram_bridge"]["fusion_notes"])


# ---------------------------------------------------------------------------
# 3. objective confirm
# ---------------------------------------------------------------------------

def test_objective_confirm_inside_window():
    vec = _sr_vector()
    lc = {"objective_events": [
        {"name": "dragon", "killer_team": "enemy", "down_at_s": 1200.0},
    ]}
    fused = _by_id(fuse_districts(vec, lc, "sr", 1207.9))
    assert fused["dragon_pit"]["fused_present"]["enemy"] >= 1
    assert any(n.startswith("objective:dragon:enemy") for n in
               fused["dragon_pit"]["fusion_notes"])


def test_objective_confirm_outside_window():
    vec = _sr_vector()
    lc = {"objective_events": [
        {"name": "dragon", "killer_team": "enemy", "down_at_s": 1200.0},
    ]}
    fused = _by_id(fuse_districts(vec, lc, "sr", 1208.5))
    assert fused["dragon_pit"]["fused_present"]["enemy"] == 0
    assert fused["dragon_pit"]["fusion_notes"] == []


def test_baron_and_herald_map_to_baron_pit_unknown_skipped():
    vec = _sr_vector()
    lc = {"objective_events": [
        {"name": "herald", "killer_team": "ally", "down_at_s": 850.0},
        {"name": "baron", "killer_team": "unknown", "down_at_s": 851.0},
    ]}
    fused = _by_id(fuse_districts(vec, lc, "sr", 852.0))
    assert fused["baron_pit"]["fused_present"]["ally"] >= 1
    assert any(n.startswith("objective:herald:ally") for n in
               fused["baron_pit"]["fusion_notes"])
    # killer_team unknown must never force presence
    assert not any("unknown" in n for n in fused["baron_pit"]["fusion_notes"])


# ---------------------------------------------------------------------------
# 4. ward-inference gate (SR-only, has_wards-gated)
# ---------------------------------------------------------------------------

def test_ward_hook_fires_only_on_sr(monkeypatch):
    calls = []

    def _sentinel(rows, lc_events, game_time_s):
        calls.append(True)
        return [("mid_lane", "ward:sentinel")]

    monkeypatch.setattr(df, "_ward_inference", _sentinel)
    fused = _by_id(fuse_districts(_sr_vector(), {}, "sr", 600.0))
    assert calls, "ward hook must run for SR"
    assert "ward:sentinel" in fused["mid_lane"]["fusion_notes"]

    for mode, vec in (("aram", _aram_vector()), ("arena", _sr_vector()),
                      ("KIWI", _aram_vector()), ("CHERRY", _sr_vector()),
                      ("brawl", _sr_vector()), ("garbage", _sr_vector())):
        calls.clear()
        fused = fuse_districts(vec, {}, mode, 600.0)
        assert not calls, f"ward hook must NEVER run for {mode}"
        for row in fused:
            assert not any(str(n).startswith("ward:") for n in
                           row.get("fusion_notes", [])), mode


def test_ward_hook_v0_is_empty():
    assert df._ward_inference([], {}, 600.0) == []


# ---------------------------------------------------------------------------
# 5. arena / brawl no-op + fail-soft
# ---------------------------------------------------------------------------

def test_arena_brawl_noop_even_with_events():
    lc = {
        "players": _players(enemy_dead=5),
        "turret_events": [{"down_at_s": 100.0, "name": "Turret_T2_L_03_A"}],
        "objective_events": [
            {"name": "dragon", "killer_team": "enemy", "down_at_s": 100.0}],
    }
    for mode in ("arena", "brawl", "tft", "CHERRY", None, 42):
        vec = _sr_vector(mid_lane=(2, 3))
        fused = fuse_districts(vec, lc, mode, 101.0)
        assert len(fused) == len(vec)
        for src, out in zip(vec, fused):
            assert out["fused_present"] == dict(src["team_present"]), mode
            assert out["fusion_notes"] == [], mode


def test_fail_soft_garbage_everywhere():
    # None / wrong-typed vectors -> []
    assert fuse_districts(None, {}, "sr", 600.0) == []
    assert fuse_districts("nope", {}, "sr", 600.0) == []
    # non-dict rows are dropped, dict rows survive
    fused = fuse_districts([42, None, _row("mid_lane", 1, 1)], {}, "sr", 600.0)
    assert len(fused) == 1 and fused[0]["id"] == "mid_lane"
    # garbage lc / game_time / event shapes never raise
    junk_lc = {
        "players": "zzz",
        "turret_events": [None, {"down_at_s": "x", "name": 7}, "y"],
        "inhib_events": {"not": "a list"},
        "objective_events": [{"name": "dragon"}, []],
    }
    fused = fuse_districts(_sr_vector(mid_lane=(1, 2)), junk_lc, "sr", "bad")
    assert _by_id(fused)["mid_lane"]["fused_present"] == {"ally": 1, "enemy": 2}
    # rows missing team_present entirely degrade to zeros
    fused = fuse_districts([{"id": "mid_lane"}], {}, "sr", 600.0)
    assert fused[0]["fused_present"] == {"ally": 0, "enemy": 0}
