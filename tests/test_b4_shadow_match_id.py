"""B4-d (RM-189): bind a branch series to ONE match.

The in-game half of B4 is silent capture of decision branch points
(docs/OVERLAY_COMPLIANCE_PLAN.md section 6c), and the post-game review reads
that capture back. It could not, before this: a record in
data/hz_choice_shadow.jsonl was keyed only by wall-clock `ts` plus
`game_time_s`, so nothing tied a series of branches to the match it came from.

Two identifiers land, both appended at the END of the record so every existing
consumer and the 68 MB corpus already on disk keep parsing:

  game_id      - the canonical Riot id, captured from the LCU gameflow session
                 (lcu/snapshot_shape.py:431-439). None when the LCU is not
                 reachable. This works for event modes too: the CLIENT knows
                 the gameId for ARAM Mayhem / queue 2400 even though Match-V5
                 refuses the match afterwards, so no separate event-mode path
                 is needed - which is a simplification against what the design
                 doc originally assumed.
  game_run_id  - ALWAYS present. Equals game_id when known; otherwise a local
                 id minted from the first tick of the game and held for its
                 duration, so a reader can still group a series when the LCU
                 was down.

The local id is minted from the record's own `ts` rather than a counter: a
counter resets to 1 on every RC restart, and a later game would then reuse a
previous game's id, silently merging two matches in the reader.
"""
from __future__ import annotations

import json

from core import hz_choice_shadow as hcs
from dashboard import _deterministic_coaching as dc


def _read(path):
    return [json.loads(ln) for ln in
            path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _log(path, **kw):
    base = dict(mode="aram", my_champion="Annie", enemy="Caitlyn",
                choices=[{"key": "A", "label": "Trade"}], covered=True,
                path=path)
    base.update(kw)
    return hcs.log_precomputed_choices(**base)


# --- the identifiers themselves -------------------------------------------

def test_game_id_is_recorded_and_becomes_the_run_id(tmp_path):
    p = tmp_path / "hz.jsonl"
    r = _log(p, game_id="7412995551", game_time_s=300.0)
    assert r["game_id"] == "7412995551"
    assert r["game_run_id"] == "7412995551"


def test_absent_game_id_still_yields_a_run_id(tmp_path):
    p = tmp_path / "hz.jsonl"
    r = _log(p, game_time_s=300.0, now_iso="2026-08-12T20:00:00+00:00")
    assert r["game_id"] is None
    assert r["game_run_id"] == "local-aram-2026-08-12T20:00:00+00:00"


def test_local_run_id_is_stable_across_ticks_of_one_game(tmp_path):
    """Minted once, then held - so it must NOT track the later tick's ts."""
    p = tmp_path / "hz.jsonl"
    _log(p, game_time_s=300.0, level=6, now_iso="2026-08-12T20:00:00+00:00")
    _log(p, game_time_s=360.0, level=9, now_iso="2026-08-12T20:01:00+00:00")
    rows = _read(p)
    assert len(rows) == 2, "second tick must not be deduped away"
    assert rows[0]["game_run_id"] == rows[1]["game_run_id"]
    assert rows[1]["game_run_id"] == "local-aram-2026-08-12T20:00:00+00:00"


def test_a_new_game_mints_a_new_run_id(tmp_path):
    """game_time_s running BACKWARD is the new-game signal - the same signal
    the module's own freshness guard documents (a new game resets the clock
    below the frozen post-game value)."""
    p = tmp_path / "hz.jsonl"
    _log(p, game_time_s=900.0, level=14, now_iso="2026-08-12T20:00:00+00:00")
    _log(p, game_time_s=45.0, level=2, now_iso="2026-08-12T20:30:00+00:00")
    rows = _read(p)
    assert len(rows) == 2
    assert rows[0]["game_run_id"] != rows[1]["game_run_id"]
    assert rows[1]["game_run_id"] == "local-aram-2026-08-12T20:30:00+00:00"


def test_game_id_appearing_mid_game_takes_over(tmp_path):
    """The LCU can come back after a tick or two. A real id always wins over
    the local stand-in."""
    p = tmp_path / "hz.jsonl"
    _log(p, game_time_s=30.0, level=2, now_iso="2026-08-12T20:00:00+00:00")
    r = _log(p, game_time_s=60.0, level=3, game_id="7412995551")
    assert r["game_run_id"] == "7412995551"


def test_run_ids_do_not_leak_between_targets(tmp_path):
    """Per-target state, matching _LAST_SIG / _LAST_GT - an explicit test path
    and the live default must not share a run."""
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    ra = _log(a, game_time_s=300.0, now_iso="2026-08-12T20:00:00+00:00")
    rb = _log(b, game_time_s=300.0, now_iso="2026-08-12T21:00:00+00:00")
    assert ra["game_run_id"] != rb["game_run_id"]


# --- schema back-compat ----------------------------------------------------

_ORIGINAL_KEYS = {
    "ts", "mode", "my_champion", "enemy", "band", "mana_state", "cd_state",
    "covered", "game_time_s", "level", "item_count", "engine_version",
    "choices", "native_action", "native_choices", "cv_override",
    "verdict_blocks",
}


def test_every_pre_existing_key_survives(tmp_path):
    """68 MB of records already on disk carry exactly these keys; a reader
    written against them must keep working."""
    p = tmp_path / "hz.jsonl"
    r = _log(p, game_time_s=300.0)
    assert _ORIGINAL_KEYS <= set(r)


def test_new_keys_are_appended_last(tmp_path):
    """Append-at-the-end, the same doctrine CLAUDE.md sets for dataclass
    fields - a mid-schema insert breaks positional/ordered consumers."""
    p = tmp_path / "hz.jsonl"
    r = _log(p, game_time_s=300.0)
    assert list(r)[-2:] == ["game_id", "game_run_id"]


# --- wiring ----------------------------------------------------------------

def _cell():
    return {"verdict": "all_in", "net_swing": 0.25,
            "pct_my_removed": 0.3, "pct_enemy_removed": 0.6,
            "economy": {"recall": "recall_now", "next_spike": "first_item",
                        "gold_at_band": 1300.0}}


def _patch_loader(monkeypatch):
    import core.laning_scenario_precompute as lsp
    monkeypatch.setattr(lsp, "load_laning_scenarios",
                        lambda mode="sr", patch=None: {
                            "schema": "laning_scenarios/v3",
                            "scenarios": {"Annie": {"Caitlyn":
                                          {"L6": {"full": {"all_up": _cell()}}}}}})


def _coach_lc():
    return ({"champion": "Annie", "level": 6, "game_time_s": 300.0,
             "action": "Trade with Q"},
            {"champion": "Annie", "enemy_team": ["Zed", "Caitlyn"]})


def test_wiring_threads_game_id_from_the_lcu_snapshot(tmp_path, monkeypatch):
    _patch_loader(monkeypatch)
    p = tmp_path / "hz.jsonl"
    coach, lc = _coach_lc()
    dc.shadow_log_precomputed_choices(coach, lc, "sr", path=p,
                                      lcu_snapshot={"game_id": "7412995551"})
    rows = _read(p)
    assert len(rows) == 1
    assert rows[0]["game_id"] == "7412995551"
    assert rows[0]["game_run_id"] == "7412995551"


def test_wiring_without_an_lcu_snapshot_still_writes(tmp_path, monkeypatch):
    """The parameter is keyword-only with a default: every pre-existing call
    site, including a dozen in tests/, passes three positional args and must
    keep working."""
    _patch_loader(monkeypatch)
    p = tmp_path / "hz.jsonl"
    coach, lc = _coach_lc()
    dc.shadow_log_precomputed_choices(coach, lc, "sr", path=p)
    rows = _read(p)
    assert len(rows) == 1
    assert rows[0]["game_id"] is None
    assert rows[0]["game_run_id"].startswith("local-sr-")


def test_wiring_tolerates_a_garbage_lcu_snapshot(tmp_path, monkeypatch):
    _patch_loader(monkeypatch)
    p = tmp_path / "hz.jsonl"
    for bad in (None, "nope", {"game_id": None}, {"game_id": ""}, {}):
        coach, lc = _coach_lc()
        target = tmp_path / f"hz_{abs(hash(str(bad)))}.jsonl"
        dc.shadow_log_precomputed_choices(coach, lc, "sr", path=target,
                                          lcu_snapshot=bad)
        rows = _read(target)
        assert len(rows) == 1
        assert rows[0]["game_id"] is None
        assert rows[0]["game_run_id"]
