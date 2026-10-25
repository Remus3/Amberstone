"""RM-875 item 5: ``data/ds_calibration.jsonl`` rows carry their re-run inputs.

WHY
    Gated row G5-05 CHECK B (``docs/LIVE_GAME_GATED_SYNC.md``) re-runs a logged
    ARENA row through ``dispatch_for_coach`` with the flag ON and OFF and
    compares the ``ds_picks`` order. Before RM-875 a row recorded no enemy
    stats, no augments, no engine version and no flag state, so the re-run was
    approximate and a row could not even say which lane produced it.

WHAT IS PINNED HERE
    1. ``log_ds_run`` without the new kwargs writes EXACTLY the pre-RM-875
       record (same keys, same order) - the ARAM / SR / Brawl callers pass
       none of them, so their rows are unchanged.
    2. With them, the four new keys are APPENDED at the END, in a fixed order,
       so every existing consumer still parses old and new rows alike.
    3. ``enemy_stats_summary`` records the values the dispatcher sends.
    4. The Arena coach row records them, including the flag state ON and OFF.

The autouse ``redirect_prod_write_paths_to_tmp`` fixture in ``tests/conftest.py``
redirects ``core.ds_calibration._LOG_PATH``, so no write here reaches ``data/``.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from coach_integration.enemy_stats import EnemyStats
from core import daemon_slayer_client as dsc
from core import ds_calibration
from core.ds_calibration_agreement import load_records

_OLD_KEYS = ["ts", "champion", "mode", "level", "owned_items", "ds_picks",
             "game_id", "match_key"]
_NEW_KEYS = ["enemy_stats", "augments", "engine_version", "apply_mode_modifiers"]


def _rows() -> list[dict]:
    path = Path(ds_calibration._LOG_PATH)
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip()]


def test_legacy_call_writes_the_exact_pre_rm875_record():
    ds_calibration.log_ds_run(champion="Ahri", mode="ARAM", level=11,
                              owned_items=["3089"], ds_picks=[], match_key="k1")
    rows = _rows()
    assert len(rows) == 1
    assert list(rows[0]) == _OLD_KEYS


def test_new_inputs_are_appended_at_the_end_in_order():
    ds_calibration.log_ds_run(
        champion="Quinn", mode="ARENA", level=9, owned_items=["3006"],
        ds_picks=[], match_key="k2",
        enemy_stats={"armor": 80.0}, augments=["ItsCritical"],
        engine_version="1.290.0", apply_mode_modifiers=True,
    )
    row = _rows()[-1]
    assert list(row) == _OLD_KEYS + _NEW_KEYS
    assert row["enemy_stats"] == {"armor": 80.0}
    assert row["augments"] == ["ItsCritical"]
    assert row["engine_version"] == "1.290.0"
    assert row["apply_mode_modifiers"] is True
    # an existing consumer still parses the widened row
    assert load_records(ds_calibration._LOG_PATH)[-1]["champion"] == "Quinn"


def test_enemy_stats_summary_mirrors_the_dispatcher_inputs():
    es = EnemyStats(armor=112.0, mr=84.0, max_hp=2450.0, bonus_hp=500.0,
                    ad_share=0.6, ap_share=0.4)
    assert ds_calibration.enemy_stats_summary(es) == {
        "armor": 112.0, "mr": 84.0, "max_hp": 2450.0, "bonus_hp": 500.0,
        "ad_share": 0.6, "ap_share": 0.4,
    }
    assert ds_calibration.enemy_stats_summary(None) is None


def test_current_engine_version_is_the_on_disk_engine_version():
    from agents.daemon_slayer import ENGINE_VERSION

    assert ds_calibration.current_engine_version() == str(ENGINE_VERSION)


class _StubClient:
    class messages:  # noqa: N801 - mirrors the anthropic client attribute
        @staticmethod
        def create(*_a, **_k):
            raise RuntimeError("no model call in this test")


def _arena_tick_with_rows(flag: bool) -> dict:
    import coaches.arena_coach as arena_mod

    def _fake_post(path, body, timeout=dsc.DEFAULT_TIMEOUT):
        return {"ranked": [{"item_id": "3031", "item_name": "Infinity Edge",
                            "delta_dps": 300.0, "gold": 3400}]}

    coach = object.__new__(arena_mod.Coach)
    coach._client = _StubClient()
    coach._vision_state = {}
    coach._event_round_count = 4
    state = {
        "champion": "Quinn", "level": 9,
        "items": ["Berserker's Greaves"],
        "enemy_comp": ["Ashe", "Annie"], "game_seconds": 600,
        "teams": [{"name": "You", "is_you": True, "hp_pct": 90}],
        "augments": ["ItsCritical"], "hp": 850, "hp_max": 1000,
    }
    before = len(_rows())
    with mock.patch.object(arena_mod, "_ARENA_MODE_MODIFIERS", flag), \
            mock.patch.object(dsc, "_post_json", _fake_post), \
            mock.patch("core.archetype_picks.get_archetype_for",
                       lambda *_a, **_k: {"primary": "carry"}):
        coach._run_coach(state)
    rows = _rows()
    assert len(rows) == before + 1, "the Arena tick wrote no calibration row"
    return rows[-1]


def test_arena_row_records_rerun_inputs_and_flag_state():
    for flag in (False, True):
        row = _arena_tick_with_rows(flag)
        assert row["mode"] == "ARENA"
        assert list(row)[len(_OLD_KEYS):] == _NEW_KEYS
        assert row["apply_mode_modifiers"] is flag
        assert row["augments"] == ["ItsCritical"]
        assert set(row["enemy_stats"]) == {"armor", "mr", "max_hp", "bonus_hp",
                                           "ad_share", "ap_share"}
        assert row["engine_version"] == ds_calibration.current_engine_version()
