"""DEEP-AUDIT cycle 10 P2-W1 app-set slice B regression tests.

Covers FIX-NOW findings in:
  - lcu/lcu_postgame_collector.py (champ_name ternary precedence,
    _s NaN/inf coercion, _int JSON-boundary helper, item-event ints)
  - lcu/lcu_client.py (ARAM-family queue ids missing 2400 ARAM Mayhem)
  - lcu/lcu_rune_writer.py (_perk_by_name failure-poisoned cache,
    save_spell_pref serialization + WinError 5 retry)
  - coach_integration/_coach.py (raw exception text leaked to the UI
    status field, reset_state not holding coaching_data_lock)
  - coach_integration/_sr_prompt.py (_vision_tracker_locs int(NaN))
  - coach_integration/archetype_dispatch.py (non-finite deltas reaching
    the coaching_data.json JSON boundary)
  - lib/rewind_live_writer.py (int(NaN gameDuration) violates the
    never-raises contract)

All tests are clean-checkout safe: every file path is monkeypatched to
tmp_path, all network entry points are stubbed, and no gitignored data
is read. No asyncio.run anywhere (suite-level running-loop hazard).
"""
from __future__ import annotations

import inspect
import json
import sqlite3
import threading
import time

import pytest


# =============================================================================
# 1. lcu/lcu_postgame_collector.py
# =============================================================================

def test_parse_player_champion_name_without_champion_key():
    """Ternary precedence bug: championName must win even when the
    'champion' dict key is absent (the match-history-adapted shape and
    most EOG shapes). Pre-fix the else-branch swallowed championName
    and wrote '' into every champion_name DB column."""
    from lcu.lcu_postgame_collector import _parse_player

    row = _parse_player(
        {"championName": "Jinx", "stats": {"KILLS": 3}},
        "WIN", [], [], {}, {}, "ARAM",
    )
    assert row["champion_name"] == "Jinx"
    assert row["kills"] == 3


def test_parse_player_champion_dict_variant_still_works():
    from lcu.lcu_postgame_collector import _parse_player

    row = _parse_player(
        {"champion": {"name": "Vex"}, "stats": {}},
        "LOSS", [], [], {}, {}, "SR",
    )
    assert row["champion_name"] == "Vex"


def test_s_helper_nan_and_inf_fall_through_to_default():
    """_s() must treat NaN/inf as missing (next key / default), not
    return NaN into the DB and not raise OverflowError on inf."""
    from lcu.lcu_postgame_collector import _s

    assert _s({"KILLS": float("nan")}, "KILLS") == 0
    assert _s({"KILLS": float("inf")}, "KILLS") == 0
    assert _s({"KILLS": float("-inf")}, "KILLS", default=5) == 5
    # Existing behavior preserved: numeric strings coerce, text passes through.
    assert _s({"KILLS": "7"}, "KILLS") == 7
    assert _s({"WIN": "Win"}, "WIN", default="") == "Win"


def test_int_helper_json_boundary():
    """New _int() safe coercion for EOG-level numeric fields."""
    from lcu.lcu_postgame_collector import _int

    assert _int(float("nan")) == 0
    assert _int(float("inf"), 7) == 7
    assert _int("12") == 12
    assert _int(12.9) == 12
    assert _int(None) == 0
    assert _int("garbage", 3) == 3


def test_save_item_events_bad_numerics_do_not_raise(tmp_path, monkeypatch):
    """A NaN timestamp / string itemId in one timeline event must not
    blow up the whole item-event save (pre-fix: int(NaN) ValueError
    propagated out of _save_item_events)."""
    import lcu.lcu_postgame_collector as pgc

    monkeypatch.setattr(pgc, "_DB_PATH", tmp_path / "pg.db")
    pgc._ensure_schema()
    # Parent match row first - item_events carries an FK to {mode}_matches.
    conn = sqlite3.connect(str(tmp_path / "pg.db"))
    try:
        conn.execute(
            "INSERT INTO aram_matches (match_id, game_mode, captured_at)"
            " VALUES ('M1', 'ARAM', '2026-06-12T00:00:00Z')")
        conn.commit()
    finally:
        conn.close()
    pgc._save_item_events(
        "M1", "ARAM",
        [{"type": "ITEM_PURCHASED", "itemId": "3031",
          "timestamp": float("nan"),
          "summonerName": "x", "championName": "Jinx"}],
        {},
    )
    conn = sqlite3.connect(str(tmp_path / "pg.db"))
    try:
        rows = conn.execute(
            "SELECT item_id, timestamp_s FROM aram_item_events"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [(3031, 0)]


# -----------------------------------------------------------------------------
# 1b. RM-107: the post-game timeline collector called a 404 path and swallowed it
# -----------------------------------------------------------------------------

def test_try_fetch_timeline_uses_canonical_game_timelines_path():
    """RM-107 pin. The old path
    /lol-match-history/v1/products/lol/{puuid}/matches/{gameId}/timeline
    measured HTTP 404 live; the canonical route is keyed on gameId ALONE.
    Pin it so a future edit must consciously break this test."""
    import lcu.lcu_postgame_collector as pgc

    seen = []
    c = object.__new__(pgc.PostgameCollector)
    c._lcu_get_status = lambda path: (seen.append(path), (200, {"frames": []}))[1]
    c._lcu_get = lambda path: (_ for _ in ()).throw(
        AssertionError("must not use the status-blind _lcu_get: " + path))

    c._try_fetch_timeline("4242", "ARAM")

    assert seen == ["/lol-match-history/v1/game-timelines/4242"]
    assert not any("products/lol" in p for p in seen)


def test_try_fetch_timeline_warns_on_non_200(caplog):
    """The 404 must produce a real WARN. Pre-fix _lcu_get collapsed the
    HTTPError into None inside the helper, so the outer bare `except` never
    fired and NOTHING was logged - not even the DEBUG line."""
    import logging

    import lcu.lcu_postgame_collector as pgc

    c = object.__new__(pgc.PostgameCollector)
    c._lcu_get_status = lambda path: (404, None)

    with caplog.at_level(logging.WARNING, logger=pgc._log.name):
        c._try_fetch_timeline("4242", "ARAM")

    assert any(r.levelno >= logging.WARNING and "404" in r.getMessage()
               for r in caplog.records)


def test_try_fetch_timeline_zero_item_events_is_reported_not_silent(caplog):
    """MEASURED 2026-07-19: the canonical LCU route carries no ITEM_* events
    for ANY mode (KIWI 88 CHAMPION_KILL + 7 BUILDING_KILL; PRACTICETOOL 17
    CHAMPION_KILL) - so this is an LCU-timeline property, not a KIWI one, and
    the zero-item outcome is PERMANENT. It must be stated at INFO rather than
    warned every game, and must never reach _save_item_events."""
    import logging

    import lcu.lcu_postgame_collector as pgc

    c = object.__new__(pgc.PostgameCollector)
    c._lcu_get_status = lambda path: (200, {"frames": [
        {"events": [{"type": "CHAMPION_KILL", "timestamp": 1}]},
    ]})

    def _boom(*a, **k):
        raise AssertionError("_save_item_events must not be called with zero item rows")

    with caplog.at_level(logging.INFO, logger=pgc._log.name):
        _orig = pgc._save_item_events
        pgc._save_item_events = _boom
        try:
            c._try_fetch_timeline("4242", "ARAM")
        finally:
            pgc._save_item_events = _orig

    assert any("ITEM_" in r.getMessage() for r in caplog.records)


def test_match_history_fallback_uses_supported_pagination_spelling():
    """MEASURED 2026-07-19: `?begin=0&end=1` returns HTTP 400 from the live
    LCU; the supported spelling is begIndex/endIndex. _lcu_get collapsed that
    400 into None, so this fallback returned False for its whole life - the
    same silent-no-op family as RM-107, in the same file."""
    import lcu.lcu_postgame_collector as pgc

    src = inspect.getsource(pgc.PostgameCollector._capture_via_history)
    assert "begIndex" in src and "endIndex" in src
    assert "begin=0" not in src and "end=1" not in src


# =============================================================================
# 2. lcu/lcu_client.py (frozen - charter-authorized edit)
# =============================================================================

def test_maybe_apply_runes_treats_queue_2400_as_aram(monkeypatch):
    """Item 87 settled truth: ARAM Mayhem reports queueId 2400 (not 920).
    Pre-fix the (450, 920) tuple routed Mayhem champ select to the SR
    rune file."""
    from lcu.lcu_client import LcuClient

    client = LcuClient()
    client._last_locked_champ = ""
    client._last_locked_mode = ""
    session = {
        "localPlayerCellId": 0,
        "myTeam": [{"cellId": 0, "championId": 222, "completed": True}],
        "gameData": {"queue": {"id": 2400}},
    }
    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(client, "get_champ_select", lambda: session)
    monkeypatch.setattr(client, "_champ_id_to_name", lambda cid: "Jinx")
    monkeypatch.setattr(
        client, "apply_recommended_rune_page",
        lambda champ, mode: captured.append((champ, mode)) or True,
    )
    client._maybe_apply_runes()
    assert captured == [("Jinx", "aram")]


# =============================================================================
# 3. lcu/lcu_rune_writer.py
# =============================================================================

def test_perk_by_name_read_failure_is_not_cached(tmp_path, monkeypatch):
    """Cache-poisoning class: a transient read failure must not pin an
    empty perk map for the rest of the process lifetime."""
    import lcu.lcu_rune_writer as rw

    monkeypatch.setattr(rw, "_APP_DIR", tmp_path)
    monkeypatch.setattr(rw, "_PERK_BY_NAME", None)

    # File missing - returns empty WITHOUT caching the failure.
    assert rw._perk_by_name() == {}

    meta = tmp_path / "data" / "meta"
    meta.mkdir(parents=True)
    (meta / "ddragon_runes.json").write_text(json.dumps([
        {"id": 8000, "name": "Precision",
         "slots": [{"runes": [{"id": 9111, "name": "Triumph"}]}]},
    ]), encoding="utf-8")

    # Second call now sees the file (pre-fix: poisoned {} forever).
    assert rw._perk_by_name() == {"Triumph": 9111}


def test_save_spell_pref_serialized_and_atomic(tmp_path, monkeypatch):
    """save_spell_pref must serialize concurrent writers (shared-tmp
    race class from cycle 9) and leave no tmp litter."""
    import lcu.lcu_rune_writer as rw

    prefs = tmp_path / "spell_prefs.json"
    prefs.write_text(json.dumps({"keep_me": "yes"}), encoding="utf-8")
    monkeypatch.setattr(rw, "_SPELL_PREFS_PATH", prefs)

    # Mechanism pin: module-level writer lock exists and is honored.
    lock = rw._SPELL_PREFS_LOCK
    done = threading.Event()

    def _writer():
        rw.save_spell_pref("aram_mode", "exhaust")
        done.set()

    with lock:
        t = threading.Thread(target=_writer, daemon=True)
        t.start()
        time.sleep(0.25)
        before = json.loads(prefs.read_text(encoding="utf-8"))
        assert "aram_mode" not in before, "writer must block on the lock"
    assert done.wait(timeout=5.0)
    t.join(timeout=5.0)

    after = json.loads(prefs.read_text(encoding="utf-8"))
    assert after == {"keep_me": "yes", "aram_mode": "exhaust"}
    assert not list(tmp_path.glob("*.tmp")), "leftover tmp file"


def test_save_spell_pref_retries_transient_permission_error(tmp_path, monkeypatch):
    """os.replace WinError 5 class: one transient PermissionError on
    replace must not silently drop the preference write."""
    import lcu.lcu_rune_writer as rw

    prefs = tmp_path / "spell_prefs.json"
    monkeypatch.setattr(rw, "_SPELL_PREFS_PATH", prefs)

    calls = {"n": 0}
    real_replace = rw.Path.replace

    def _flaky(self, target):
        if str(target) == str(prefs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError(5, "transient lock")
        return real_replace(self, target)

    monkeypatch.setattr(rw.Path, "replace", _flaky)
    rw.save_spell_pref("sr_mode", "ignite")
    assert calls["n"] >= 2, "no retry happened"
    assert json.loads(prefs.read_text(encoding="utf-8")) == {"sr_mode": "ignite"}


# =============================================================================
# 4. coach_integration/_coach.py
# =============================================================================

def test_run_safe_does_not_leak_raw_exception_into_status():
    """Error-leak class (CLAUDE.md Error Handling rule): unexpected
    exception text must never reach the dashboard status field."""
    from coach_integration._coach import CoachIntegration

    c = CoachIntegration.__new__(CoachIntegration)
    c._lock = threading.Lock()

    def _boom(gs):
        raise ValueError("SECRET-sk-ant-12345 raw detail")

    statuses: list[str] = []
    c._run = _boom
    c._write_status_field = statuses.append
    c._run_safe({"champion": "Jinx"})

    assert statuses, "degraded status was not written"
    assert "SECRET" not in statuses[0]
    assert "ValueError" not in statuses[0]
    assert statuses[0] == "(coach paused - internal error)"


def test_reset_state_holds_coaching_data_lock(tmp_path):
    """reset_state writes the blank artifact OUTSIDE coaching_data_lock
    pre-fix, racing _write_fields' read-modify-write (and sharing its
    .tmp name). Post-fix it must block while another thread holds the
    process-local lock."""
    import core.coaching_data_lock as cdl
    from coach_integration._coach import CoachIntegration

    c = CoachIntegration.__new__(CoachIntegration)
    c.data_file = tmp_path / "coaching_data.json"

    done = threading.Event()

    def _resetter():
        c.reset_state()
        done.set()

    cdl._LOCK.acquire()
    try:
        t = threading.Thread(target=_resetter, daemon=True)
        t.start()
        time.sleep(0.25)
        assert not c.data_file.exists(), (
            "reset_state wrote while coaching_data_lock was held"
        )
    finally:
        cdl._LOCK.release()
    assert done.wait(timeout=5.0)
    t.join(timeout=5.0)

    blank = json.loads(c.data_file.read_text(encoding="utf-8"))
    assert blank["mode"] == "game"
    assert blank["action"] == ""
    assert not list(tmp_path.glob("*.tmp")), "leftover tmp file"


# =============================================================================
# 5. coach_integration/_sr_prompt.py
# =============================================================================

def test_vision_tracker_locs_nonfinite_respawn_no_crash(tmp_path, monkeypatch):
    """NaN/Infinity at the vision_state.json boundary: int(NaN) raised
    ValueError pre-fix and killed the whole SR prompt build."""
    import coach_integration._sr_prompt as sp

    p = tmp_path / "vision_state.json"
    p.write_text(
        '{"enemies": {'
        '"Jinx": {"is_dead": true, "respawn_in_s": NaN, "last_seen_zone": "bot"},'
        '"Vex": {"is_dead": true, "respawn_in_s": Infinity},'
        '"Ahri": {"visible": true, "last_seen_zone": "mid"}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(sp, "_VISION_STATE_PATH", p)

    out = sp._vision_tracker_locs()
    assert "Ahri [mid]" in out
    assert "Jinx" in out and "Vex" in out
    assert "nan" not in out.lower()


# =============================================================================
# 6. coach_integration/archetype_dispatch.py
# =============================================================================

def test_row_delta_nonfinite_and_garbage_guard():
    from coach_integration.archetype_dispatch import _row_delta

    assert _row_delta({"delta": float("nan")}, "dps") == 0.0
    assert _row_delta({"delta": float("inf")}, "dps") == 0.0
    assert _row_delta({"hybrid_delta_pct": float("nan")}, "hybrid") == 0.0
    assert _row_delta({"delta": None}, "dps") == 0.0
    # Sane values untouched.
    assert _row_delta({"delta": 54.2}, "dps") == pytest.approx(54.2)


def test_display_rows_survive_nonfinite_and_stay_strict_json():
    """daemon_slayer_picks land in coaching_data.json which the
    dashboard JS JSON.parse()es - NaN/Infinity tokens are fatal there."""
    from coach_integration.archetype_dispatch import _build_display_rows

    rows = _build_display_rows(
        [{"item_id": "3031", "item_name": "IE",
          "delta": float("nan"), "gold": float("inf")}],
        "dps",
    )
    assert rows[0]["delta_dps"] == 0.0
    assert rows[0]["gold"] == 0
    # Must serialize under strict JSON (what the browser accepts).
    json.dumps(rows, allow_nan=False)


# =============================================================================
# 7. lib/rewind_live_writer.py
# =============================================================================

def test_rewind_live_writer_nan_duration_never_raises(tmp_path, monkeypatch):
    """Match-V5 boundary: a non-finite gameDuration must keep the
    never-raises contract (pre-fix int(NaN) ValueError escaped into the
    Timer thread)."""
    import core.riot_api as ra
    import lib.rewind_live_writer as rl

    state = tmp_path / "state.json"
    state.write_text(json.dumps({"puuid": "abc"}), encoding="utf-8")
    monkeypatch.setattr(rl, "STATE_PATH", state)
    monkeypatch.setattr(rl, "DB_PATH", tmp_path / "rewind.db")

    monkeypatch.setattr(ra, "is_configured", lambda: True)
    monkeypatch.setattr(
        ra, "get_recent_matches", lambda puuid, count=1, region="americas": ["NA1_1"])
    monkeypatch.setattr(
        ra, "get_match",
        lambda mid, region="americas": {"info": {"gameDuration": float("nan")}})
    monkeypatch.setattr(
        ra, "get_match_timeline", lambda mid, region="americas": None)

    res = rl._do_live_fetch_and_insert(is_retry=True)
    assert res["status"] == "short_game"
    assert res["duration_s"] == 0
