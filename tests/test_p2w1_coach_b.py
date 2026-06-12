"""P2-W1 coaches/ deep-audit slice B regression tests.

Covers contained hardening fixes in:
  - coaches/sr_draft_profile.py   (cache bound, _team_sig coercion)
  - coaches/adaptation_hint_temporal.py (non-finite duration_sec rows)
  - coaches/adaptation_hint_champion.py (non-finite matchup delta)
  - coaches/loadout_resolver.py   (cache poisoning, int mode keys)
  - coaches/sr_user_builds.py     (deep defensive copies)

No network: engine calls are stubbed; DBs are per-test tmp SQLite.
"""
from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path


# -- helpers ----------------------------------------------------------


def _init_mode_dbs(tmp_path: Path, monkeypatch, modes=("aram",)):
    import agents.agent2_backend.db_schema as dbs
    from coaches import adaptation_hint
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(adaptation_hint, "DB_DIR", tmp_path)
    for mode in modes:
        dbs.init_mode(mode)


def _insert_match(db: Path, champ: str, win, duration_sec,
                  started_at: str, k: int = 5, d: int = 5, a: int = 10):
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO matches
               (started_at, champion, ally_champions, enemy_champions,
                duration_sec, win, source, kills, deaths, assists)
               VALUES (?, ?, '[]', '[]', ?, ?, 'live-phase3', ?, ?, ?)""",
            (started_at, champ, duration_sec, win, k, d, a),
        )
        conn.commit()


def _seed_bucket(db: Path, champ: str, games: int = 20, wr: float = 0.55):
    with sqlite3.connect(db) as conn:
        wins = int(games * wr)
        conn.execute(
            """INSERT INTO adaptation_buckets
               (champion, games_played, wins, losses, avg_rating,
                last_updated, aggregates_json)
               VALUES (?, ?, ?, ?, ?, '2026-06-01T00:00:00Z', '{}')""",
            (champ, games, wins, games - wins, wr),
        )
        conn.commit()


def _seed_matchup(db: Path, champ: str, opp: str, delta, sample: int = 10):
    mj = json.dumps({
        "delta": delta, "observed_wr": 0.7, "baseline_wr": 0.55,
    })
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO matchup_modifiers
               (champion, opponent_signature, sample_count, activated,
                modifier_json, last_updated)
               VALUES (?, ?, ?, 1, ?, '2026-06-01T00:00:00Z')""",
            (champ, opp, sample, mj),
        )
        conn.commit()


# -- sr_draft_profile: profile cache bound ----------------------------


def test_profile_cache_bounded(monkeypatch):
    import coaches.sr_draft_profile as sdp
    sdp.clear_cache()
    monkeypatch.setattr(
        sdp, "_call_beam",
        lambda champion, preset: ({}, "engine unreachable: stub"),
    )
    try:
        for i in range(200):
            sdp.build_profile(f"Champ{i}", role="MIDDLE", queue_id=420)
        assert len(sdp._PROFILE_CACHE) <= sdp._PROFILE_CACHE_MAX
        assert sdp._PROFILE_CACHE_MAX <= 128
    finally:
        sdp.clear_cache()


def test_profile_cache_keeps_fresh_entry_usable(monkeypatch):
    import coaches.sr_draft_profile as sdp
    sdp.clear_cache()
    calls = {"n": 0}

    def _stub(champion, preset):
        calls["n"] += 1
        return ({}, "engine unreachable: stub")

    monkeypatch.setattr(sdp, "_call_beam", _stub)
    try:
        sdp.build_profile("Ahri", role="MIDDLE", queue_id=420)
        first = calls["n"]
        sdp.build_profile("Ahri", role="MIDDLE", queue_id=420)
        assert calls["n"] == first  # second call served from cache
    finally:
        sdp.clear_cache()


# -- sr_draft_profile: _team_sig coercion -----------------------------


def test_team_sig_tolerates_bad_champion_id():
    import coaches.sr_draft_profile as sdp
    sig = sdp._team_sig([
        {"championId": "garbage"},
        {"championId": 12},
        {"championId": None},
        "not-a-dict",
    ])
    assert sig == (12,)


def test_build_profile_survives_bad_champion_id(monkeypatch):
    import coaches.sr_draft_profile as sdp
    sdp.clear_cache()
    monkeypatch.setattr(
        sdp, "_call_beam",
        lambda champion, preset: ({}, "engine unreachable: stub"),
    )
    try:
        env = sdp.build_profile(
            "Ahri", role="MIDDLE",
            my_team=[{"championId": "oops"}],
            their_team=[{"championId": "12.5"}],
            queue_id=420,
        )
        assert env["champion"] == "Ahri"
    finally:
        sdp.clear_cache()


# -- adaptation_hint_temporal: non-finite duration rows ----------------


def test_duration_analysis_skips_nonfinite_duration(tmp_path, monkeypatch):
    _init_mode_dbs(tmp_path, monkeypatch)
    db = tmp_path / "aram.db"
    _insert_match(db, "Ahri", 1, 1200, "2026-06-01T10:00:00+00:00")
    _insert_match(db, "Ahri", 0, float("inf"), "2026-06-01T11:00:00+00:00")
    from coaches.adaptation_hint_temporal import duration_analysis
    out = duration_analysis(mode="aram")
    assert out["total_games"] == 1
    quick = next(b for b in out["buckets"] if b["tier"] == "quick")
    assert quick["games"] == 1


def test_duration_analysis_skips_junk_text_duration(tmp_path, monkeypatch):
    _init_mode_dbs(tmp_path, monkeypatch)
    db = tmp_path / "aram.db"
    _insert_match(db, "Ahri", 1, 1700, "2026-06-01T10:00:00+00:00")
    _insert_match(db, "Ahri", 0, "12abc", "2026-06-01T11:00:00+00:00")
    from coaches.adaptation_hint_temporal import duration_analysis
    out = duration_analysis(mode="aram")
    assert out["total_games"] == 1


# -- adaptation_hint_champion: non-finite matchup delta ----------------


def test_for_champion_excludes_nonfinite_matchup_delta(tmp_path, monkeypatch):
    _init_mode_dbs(tmp_path, monkeypatch)
    db = tmp_path / "aram.db"
    _seed_bucket(db, "Ahri")
    _seed_matchup(db, "Ahri", "Xerath", float("nan"))
    _seed_matchup(db, "Ahri", "Garen", float("inf"))
    _seed_matchup(db, "Ahri", "Lux", 0.25)
    from coaches.adaptation_hint_champion import for_champion
    out = for_champion("Ahri", "aram")
    opps = [c["opponent"] for c in out["counters"]]
    assert opps == ["Lux"]
    assert all(math.isfinite(c["delta"]) for c in out["counters"])


def test_matchup_delta_nan_returns_none(tmp_path, monkeypatch):
    _init_mode_dbs(tmp_path, monkeypatch)
    db = tmp_path / "aram.db"
    _seed_matchup(db, "Ahri", "Xerath", float("nan"))
    _seed_matchup(db, "Ahri", "Lux", 0.25)
    from coaches.adaptation_hint_champion import matchup_delta
    assert matchup_delta("Ahri", "aram", "Xerath") is None
    assert matchup_delta("Ahri", "aram", "Lux") == 0.25


def test_format_hint_line_no_nan_text(tmp_path, monkeypatch):
    _init_mode_dbs(tmp_path, monkeypatch)
    db = tmp_path / "aram.db"
    _seed_bucket(db, "Ahri")
    _seed_matchup(db, "Ahri", "Xerath", float("nan"))
    from coaches.adaptation_hint_champion import format_hint_line
    line = format_hint_line("Ahri", "aram", enemies=["Xerath"])
    assert "nan" not in line.lower()


# -- loadout_resolver: cache poisoning + int mode ----------------------


def test_items_cache_not_poisoned_by_transient_failure(tmp_path, monkeypatch):
    import coaches.loadout_resolver as lr
    items_path = tmp_path / "ddragon_items.json"
    monkeypatch.setattr(lr, "_DDRAGON_ITEMS", items_path)
    monkeypatch.setattr(lr, "_items_by_name_cache", None)
    # First load: file missing -> empty result, but must NOT poison.
    assert lr._load_items_by_name() == {}
    items_path.write_text(
        json.dumps({"data": {"3089": {"name": "Rabadon's Deathcap"}}}),
        encoding="utf-8",
    )
    out = lr._load_items_by_name()
    assert out.get("rabadonsdeathcap") == "3089"


def test_champ_id_cache_not_poisoned_by_transient_failure(tmp_path, monkeypatch):
    import coaches.loadout_resolver as lr
    champs_path = tmp_path / "ddragon_champions.json"
    monkeypatch.setattr(lr, "_DDRAGON_CHAMPS", champs_path)
    monkeypatch.setattr(lr, "_champ_id_by_name_cache", None)
    assert lr._load_champ_id_by_name() == {}
    champs_path.write_text(
        json.dumps({"data": {"Ahri": {"key": "103", "name": "Ahri"}}}),
        encoding="utf-8",
    )
    out = lr._load_champ_id_by_name()
    assert out.get("Ahri") == 103


def test_normalize_mode_accepts_int_queue_ids():
    from coaches.loadout_resolver import _normalize_mode
    assert _normalize_mode(450) == "aram"
    assert _normalize_mode(920) == "aram"
    assert _normalize_mode(1700) == "arena"
    assert _normalize_mode(None) == "sr"
    assert _normalize_mode("ARAM") == "aram"


# -- sr_user_builds: deep defensive copies -----------------------------


def test_list_for_deep_copies(tmp_path, monkeypatch):
    import coaches.sr_user_builds as sub
    monkeypatch.setattr(sub, "_STORE_PATH", tmp_path / "user_builds.json")
    sub.clear_cache()
    try:
        sub.add("Tristana", {
            "label": "test build",
            "runes": {"keystone": "Lethal Tempo", "primary": "Precision",
                      "secondary": "Domination"},
            "items": ["Kraken Slayer", "Runaan's Hurricane"],
        })
        b = sub.list_for("Tristana")[0]
        b["runes"]["keystone"] = "HACKED"
        b["items"].append("junk")
        fresh = sub.list_for("Tristana")[0]
        assert fresh["runes"]["keystone"] == "Lethal Tempo"
        assert fresh["items"] == ["Kraken Slayer", "Runaan's Hurricane"]
    finally:
        sub.clear_cache()
