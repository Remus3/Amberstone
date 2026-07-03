"""Tests for core.arena_coach_shadow - the Arena deterministic-vs-Haiku writer.

log_arena_coach appends ONE record per distinct coarse game state to
data/arena_coach_shadow.jsonl, capturing the deterministic Arena block beside
the live Haiku block so the operator can eyeball them. Mirrors
core.aram_coach_shadow: same fail-soft contract (never raises), same per-path
dedup, same item-386 live-game gate (lc["champion"] present). The Arena sig is
ROUND-AWARE: the same action label re-logs on a new round, because Arena
rounds legitimately repeat labels like "FIGHT" back to back.

Each test uses its own tmp_path target so the module-level per-path dedup
cache is isolated between cases.
"""

from __future__ import annotations

import json

from core.arena_coach_shadow import log_arena_coach

_NOW = "2026-07-03T00:00:00+00:00"

_KEYS = (
    "action",
    "round_strategy",
    "fight_rule",
    "augment_advice",
    "anvil_advice",
    "target_priority",
    "risk",
)

_DET = {
    "action": "ALL-IN",
    "round_strategy": "Force the fight on the anvil side early.",
    "fight_rule": "Commit only after Zed burns R.",
    "augment_advice": "Take Goliath for the bruiser spike.",
    "anvil_advice": "Roll the prismatic anvil at 3000g.",
    "target_priority": "Zed first, Lulu last.",
    "risk": "Zed R burst before your shield is up.",
}

_LIVE = {
    "action": "POKE",
    "round_strategy": "Kite the pillar; do not face-check.",
    "fight_rule": "Trade only while Flash is up.",
    "augment_advice": "Prefer Lightning Strike this roll.",
    "anvil_advice": "Bank for a stat anvil next round.",
    "target_priority": "Lulu first to strip the polymorph.",
    "risk": "Getting chunked before the fight starts.",
}


def _read_lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def test_fresh_write_returns_record_and_one_json_line(tmp_path):
    target = tmp_path / "arena_coach_shadow.jsonl"
    lc = {"champion": "Kalista", "enemy_team": ["Ashe", "Zed"]}

    rec = log_arena_coach(
        _DET, _LIVE, lc, "arena", round_label=3, path=target, now_iso=_NOW
    )

    assert rec is not None
    lines = _read_lines(target)
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["ts"] == _NOW
    assert row["mode"] == "arena"
    assert row["champ"] == "Kalista"
    assert row["round"] == 3
    assert row["enemy_comp"] == ["Ashe", "Zed"]
    # Both sides are the full 7-key all-str columns, verbatim.
    for side in ("deterministic", "live_haiku"):
        assert tuple(row[side].keys()) == _KEYS
        assert all(isinstance(v, str) for v in row[side].values())
    assert row["deterministic"] == _DET
    assert row["live_haiku"] == _LIVE


def test_dedup_same_sig_writes_once(tmp_path):
    target = tmp_path / "arena_coach_shadow.jsonl"
    lc = {"champion": "Kalista", "enemy_team": ["Ashe"]}

    first = log_arena_coach(
        _DET, _LIVE, lc, "arena", round_label=3, path=target, now_iso=_NOW
    )
    second = log_arena_coach(
        _DET, _LIVE, lc, "arena", round_label=3, path=target, now_iso=_NOW
    )

    assert first is not None
    assert second is None
    assert len(_read_lines(target)) == 1


def test_round_change_re_logs_same_action(tmp_path):
    # The Arena-specific sig ingredient: a new round re-logs even when the
    # action label repeats (the ARAM sig has no round and would dedup this).
    target = tmp_path / "arena_coach_shadow.jsonl"
    lc = {"champion": "Kalista", "enemy_team": ["Ashe"]}

    log_arena_coach(_DET, _LIVE, lc, "arena", round_label=3, path=target, now_iso=_NOW)
    log_arena_coach(_DET, _LIVE, lc, "arena", round_label=4, path=target, now_iso=_NOW)

    assert len(_read_lines(target)) == 2


def test_action_change_re_logs_same_round(tmp_path):
    target = tmp_path / "arena_coach_shadow.jsonl"
    lc = {"champion": "Kalista", "enemy_team": ["Ashe"]}

    log_arena_coach(_DET, _LIVE, lc, "arena", round_label=3, path=target, now_iso=_NOW)
    det2 = dict(_DET, action="FALL BACK")
    log_arena_coach(det2, _LIVE, lc, "arena", round_label=3, path=target, now_iso=_NOW)

    assert len(_read_lines(target)) == 2


def test_live_game_gate_skips(tmp_path):
    # Item-386 lesson: never log a lobby/idle/Champ0 row. Only a real in-game
    # liveclient tick carries a non-blank champion string.
    target = tmp_path / "arena_coach_shadow.jsonl"

    for lc in (None, {}, {"enemy_team": ["Ashe"]}, {"champion": ""}):
        rec = log_arena_coach(
            _DET, _LIVE, lc, "arena", round_label=1, path=target, now_iso=_NOW
        )
        assert rec is None
    assert not target.exists()


def test_non_dict_blocks_normalize_to_all_empty(tmp_path):
    # A malformed side must still record a complete (empty) 7-key column
    # rather than blocking the row - the shadow file stays uniform.
    target = tmp_path / "arena_coach_shadow.jsonl"
    lc = {"champion": "Lux", "enemy_team": ["Brand"]}
    empty = dict.fromkeys(_KEYS, "")

    # Distinct rounds so the (all-"") action does not dedup the sub-cases.
    for round_label, block in ((1, None), (2, "garbage"), (3, 42)):
        rec = log_arena_coach(
            block, block, lc, "arena",
            round_label=round_label, path=target, now_iso=_NOW,
        )
        assert rec is not None
        row = json.loads(_read_lines(target)[-1])
        assert row["deterministic"] == empty
        assert row["live_haiku"] == empty
    assert len(_read_lines(target)) == 3


def test_extra_keys_dropped_missing_keys_empty(tmp_path):
    target = tmp_path / "arena_coach_shadow.jsonl"
    lc = {"champion": "Lux", "enemy_team": ["Brand"]}
    det = {"action": "FIGHT", "choices": ["a", "b"], "teams": {"x": 1}}

    rec = log_arena_coach(
        det, {}, lc, "arena", round_label=2, path=target, now_iso=_NOW
    )

    assert rec is not None
    row = json.loads(_read_lines(target)[0])
    assert tuple(row["deterministic"].keys()) == _KEYS
    assert row["deterministic"]["action"] == "FIGHT"
    assert "choices" not in row["deterministic"]
    assert all(row["deterministic"][k] == "" for k in _KEYS if k != "action")


def test_per_path_dedup_is_independent(tmp_path):
    # Same sig against two targets must write to both - an explicit test path
    # and the live default never share a dedup slot.
    target_a = tmp_path / "a" / "arena_coach_shadow.jsonl"
    target_b = tmp_path / "b" / "arena_coach_shadow.jsonl"
    lc = {"champion": "Kalista", "enemy_team": ["Ashe"]}

    rec_a = log_arena_coach(
        _DET, _LIVE, lc, "arena", round_label=3, path=target_a, now_iso=_NOW
    )
    rec_b = log_arena_coach(
        _DET, _LIVE, lc, "arena", round_label=3, path=target_b, now_iso=_NOW
    )

    assert rec_a is not None
    assert rec_b is not None
    assert len(_read_lines(target_a)) == 1
    assert len(_read_lines(target_b)) == 1


def test_fail_soft_unwritable_target_returns_none(tmp_path):
    # A directory as the target cannot be opened for append; the writer must
    # swallow the failure (hot path) and report None, never raise.
    lc = {"champion": "Kalista", "enemy_team": ["Ashe"]}

    rec = log_arena_coach(
        _DET, _LIVE, lc, "arena", round_label=3, path=tmp_path, now_iso=_NOW
    )

    assert rec is None


def test_enemy_comp_fail_soft(tmp_path):
    # The gate is on champion, NOT enemy_team: a tick before the scoreboard
    # populates still logs, with enemy_comp degraded to [] / str entries.
    target = tmp_path / "arena_coach_shadow.jsonl"

    rec = log_arena_coach(
        _DET, _LIVE, {"champion": "Lux"}, "arena",
        round_label=1, path=target, now_iso=_NOW,
    )
    assert rec is not None
    assert json.loads(_read_lines(target)[-1])["enemy_comp"] == []

    # Non-list enemy_team degrades to []; a mixed list of dict/str entries
    # (both caller shapes exist) coerces every truthy entry to str.
    rec2 = log_arena_coach(
        _DET, _LIVE, {"champion": "Lux", "enemy_team": "garbage"}, "arena",
        round_label=2, path=target, now_iso=_NOW,
    )
    assert rec2 is not None
    assert json.loads(_read_lines(target)[-1])["enemy_comp"] == []

    rec3 = log_arena_coach(
        _DET, _LIVE,
        {"champion": "Lux", "enemy_team": [{"champion": "Ashe"}, "Zed", None]},
        "arena", round_label=3, path=target, now_iso=_NOW,
    )
    assert rec3 is not None
    comp = json.loads(_read_lines(target)[-1])["enemy_comp"]
    assert len(comp) == 2
    assert all(isinstance(e, str) for e in comp)
