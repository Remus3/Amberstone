"""DEEP-AUDIT cycle 9 P2-W1 slice A - coaches/ regression tests.

Covers (TDD - each test was written failing-first against the live bug):
  1. BaseCoach poll tick passed the CURRENT state as `prev` into
     _maybe_coach (prev is state), so the hp-drop / new-kill fast path
     could never fire (dead since ARCH-002).
  2. Non-finite (NaN/inf) Live Client numerics crash all three mode
     parsers with ValueError/OverflowError (json.loads accepts NaN).
  3. aram_coach._handle_augment_select still used the pre-2026-05-03
     '"MAYHEM" in gm' check that never matches the live "KIWI" value.
  4. arena_coach._augment_name_map picked the patch snapshot dir by
     reverse LEXICOGRAPHIC sort ("16.9.1" beats "16.10.1").
  5. aram_team_analyzer leaked the raw exception type name into the
     user-facing `reason` field (hard rule: friendly degrade only).
  6. tft_coach / tft_pbe_coach wrote data files non-atomically
     (path.write_text) - hard rule is tmp.write_text + tmp.replace.
  7. safe_write concurrency smoke (two writer threads share one .tmp
     name; serialized via module lock).
  8. replay_coach._load_match characterization (missing/corrupt db).

No network, no live API calls - Anthropic + trackers are stubbed.
"""
from __future__ import annotations

import json
import math
import threading
import time
import types

import pytest

from coaches._base_coach import BaseCoach, finite, safe_write


# -- shared stubs --------------------------------------------------------------

class _StubCoach(BaseCoach):
    _MODE_NAME = "aram"

    def _blank_artifact_data(self) -> dict:
        return {}

    def _parse_raw_state(self, raw: dict) -> dict:
        return raw

    def _run_coach(self, state: dict) -> None:
        pass

    def _run_vision(self) -> None:
        pass


def _bare_coach(tmp_path) -> _StubCoach:
    # __new__ skips __init__ so no poll/vision threads or Anthropic client.
    c = _StubCoach.__new__(_StubCoach)
    c._running = True
    c._lock = threading.Lock()
    c._last_state = {}
    c._last_coach = 0.0
    c._vision_state = {}
    c._last_vision = 0.0
    c._last_force_check = 0.0
    c._overlay = {}
    c._debug = False
    c._client = None
    c._api_key = ""
    c._data_file = tmp_path / "in.json"
    c._out = tmp_path / "out.json"
    return c


def _kill_cost_tracker(monkeypatch):
    """Force the cost-tracker gates down the except-pass branch."""
    import core.cost_tracker as ct

    def _boom():
        raise RuntimeError("tracker disabled for test")

    monkeypatch.setattr(ct, "get_tracker", _boom)


class _FakeContent:
    def __init__(self, text: str):
        self.text = text


class _FakeResp:
    def __init__(self, text: str):
        self.content = [_FakeContent(text)]
        self.usage = None
        self.model = "stub-model"


class _CaptureClient:
    """Stub anthropic client capturing messages.create kwargs."""

    def __init__(self, reply: str):
        self.calls: list[dict] = []
        self._reply = reply
        outer = self

        class _Messages:
            def create(self, **kw):
                outer.calls.append(kw)
                return _FakeResp(outer._reply)

        self.messages = _Messages()


# ==============================================================================
# 1. fast-path prev-state bug (dead hp-drop/kill debounce bypass)
# ==============================================================================

def test_fast_path_fires_on_hp_drop_between_polls(tmp_path, monkeypatch):
    """Two poll ticks with a 40% HP drop inside the debounce window must
    dispatch a coach run via the fast path. Pre-fix, _poll_loop assigned
    self._last_state = state BEFORE _maybe_coach, so prev was the same
    object as state and the fast path never fired."""
    _kill_cost_tracker(monkeypatch)
    c = _bare_coach(tmp_path)

    ran = threading.Event()
    c._run_coach = lambda state: ran.set()

    ticks = [
        {"hp_pct": 100, "dead_enemies": []},
        {"hp_pct": 60, "dead_enemies": []},
    ]
    it = iter(ticks)
    c._fetch_game_data = lambda: next(it, None)

    # First tick establishes _last_state; pretend we just coached so the
    # normal debounce (8s) blocks but the fast-path window (5s) is open.
    c._last_coach = time.time()
    c._poll_tick()
    assert not ran.is_set()

    c._last_coach = time.time() - 6.0  # 6s ago: > FAST_PATH_MIN_S, < DEBOUNCE_S
    c._poll_tick()
    assert ran.wait(2.0), "fast path did not dispatch on 40% HP drop"


def test_fast_path_new_kill_between_polls(tmp_path, monkeypatch):
    _kill_cost_tracker(monkeypatch)
    c = _bare_coach(tmp_path)
    ran = threading.Event()
    c._run_coach = lambda state: ran.set()
    ticks = [
        {"hp_pct": 90, "dead_enemies": []},
        {"hp_pct": 90, "dead_enemies": ["Lux"]},
    ]
    it = iter(ticks)
    c._fetch_game_data = lambda: next(it, None)
    c._last_coach = time.time()
    c._poll_tick()
    assert not ran.is_set()
    c._last_coach = time.time() - 6.0
    c._poll_tick()
    assert ran.wait(2.0), "fast path did not dispatch on new enemy death"


def test_poll_tick_noop_without_data(tmp_path, monkeypatch):
    _kill_cost_tracker(monkeypatch)
    c = _bare_coach(tmp_path)
    c._fetch_game_data = lambda: None
    c._poll_tick()
    assert c._last_state == {}


def test_last_state_updated_after_tick(tmp_path, monkeypatch):
    _kill_cost_tracker(monkeypatch)
    c = _bare_coach(tmp_path)
    c._fetch_game_data = lambda: {"hp_pct": 77}
    c._last_coach = time.time()  # debounced - no dispatch
    c._poll_tick()
    assert c._last_state == {"hp_pct": 77}


# ==============================================================================
# 2. non-finite Live Client numerics must not crash the parsers
# ==============================================================================

def test_finite_helper():
    assert finite(5) == 5.0
    assert finite("3.5") == 3.5
    assert finite(float("nan"), 7.0) == 7.0
    assert finite(float("inf"), 1.0) == 1.0
    assert finite(float("-inf")) == 0.0
    assert finite(None, 2.0) == 2.0
    assert finite("garbage", 4.0) == 4.0


def _nan_raw(mode: str) -> dict:
    return {
        "activePlayer": {
            "championStats": {
                "currentHealth": float("nan"),
                "maxHealth": float("inf"),
                "resourceValue": float("nan"),
                "resourceMax": float("-inf"),
            },
            "summonerName": "me",
            "championName": "Lux",
            "currentGold": float("nan"),
            "level": float("inf"),
        },
        "gameData": {"gameTime": float("nan"), "gameMode": mode},
        "allPlayers": [],
    }


def test_aram_parse_state_survives_nan():
    from coaches.aram_coach import _parse_state
    s = _parse_state(_nan_raw("ARAM"))
    assert s["game_seconds"] == 0.0
    assert isinstance(s["hp_pct"], int)
    assert isinstance(s["gold"], int)
    assert isinstance(s["level"], int)
    assert math.isfinite(s["game_seconds"])


def test_arena_parse_state_survives_nan():
    from coaches.arena_coach import _parse_arena_state
    s = _parse_arena_state(_nan_raw("CHERRY"))
    assert isinstance(s["hp_pct"], int)
    assert isinstance(s["gold"], int)
    assert math.isfinite(s["game_seconds"])


def test_brawl_parse_state_survives_nan():
    from coaches.brawl_coach import _parse_brawl_state
    s = _parse_brawl_state(_nan_raw("URF"))
    assert isinstance(s["hp_pct"], int)
    assert isinstance(s["mana_pct"], int)
    assert math.isfinite(s["game_seconds"])


def test_aram_parse_state_normal_values_unchanged():
    from coaches.aram_coach import _parse_state
    raw = {
        "activePlayer": {
            "championStats": {
                "currentHealth": 500, "maxHealth": 1000,
                "resourceValue": 30, "resourceMax": 100,
            },
            "summonerName": "me", "championName": "Lux",
            "currentGold": 1234, "level": 9,
        },
        "gameData": {"gameTime": 600.5, "gameMode": "ARAM"},
        "allPlayers": [],
    }
    s = _parse_state(raw)
    assert s["hp_pct"] == 50
    assert s["mana_pct"] == 30
    assert s["gold"] == 1234
    assert s["level"] == 9
    assert s["game_time"] == "10:00"


# ==============================================================================
# 3. ARAM augment-select Mayhem tag (KIWI mode string)
# ==============================================================================

def _aram_coach_for_select(tmp_path, monkeypatch, reply: str):
    import core.coach_trace as trace_mod
    from coaches import aram_coach as mod
    _kill_cost_tracker(monkeypatch)
    monkeypatch.setattr(trace_mod, "append", lambda **kw: None)
    c = mod.Coach.__new__(mod.Coach)
    c._out = tmp_path / "aram_coaching_data.json"
    c._client = _CaptureClient(reply)
    c._overlay = {}
    return c


def test_aram_augment_select_tags_mayhem_for_kiwi(tmp_path, monkeypatch):
    """Live Mayhem reports gameMode=KIWI; the select prompt must carry the
    ' Mayhem' tag. Pre-fix the handler used '"MAYHEM" in gm' which never
    matched (same bug fixed in _run_coach on 2026-05-03)."""
    c = _aram_coach_for_select(
        tmp_path, monkeypatch, "Take: A\nWhy: w\nGameplan: g")
    c._last_state = {
        "game_mode": "KIWI", "champion": "Lux", "hp_pct": 80,
        "ally_comp": ["Ahri"], "enemy_comp": ["Sion"],
    }
    c._handle_augment_select({"augment_choices": ["Aug A", "Aug B"]})
    assert len(c._client.calls) == 1
    prompt = c._client.calls[0]["messages"][0]["content"]
    assert "ARAM Mayhem augment select" in prompt
    written = json.loads(c._out.read_text(encoding="utf-8"))
    assert written["aug_take"] == "A"
    assert written["augment_select"] is True


def test_aram_augment_select_plain_aram_untagged(tmp_path, monkeypatch):
    c = _aram_coach_for_select(
        tmp_path, monkeypatch, "Take: A\nWhy: w\nGameplan: g")
    c._last_state = {"game_mode": "ARAM", "champion": "Lux", "hp_pct": 80}
    c._handle_augment_select({"augment_choices": ["Aug A"]})
    prompt = c._client.calls[0]["messages"][0]["content"]
    assert "Mayhem" not in prompt


def test_vision_postprocess_aliases_is_augment_select():
    """Root cause of the 2026-07-12 ARAM Mayhem augment-reco miss: the live
    vision relay (vision_server/_inference.py TFT prompt) emits the flag as
    `is_augment_select`, but the ARAM/Arena/Brawl coaches gate on
    `augment_select` (aram_coach.py:614), so the augment handler never fired.
    The relay was live-verified to detect the ARAM Mayhem augment cards
    correctly (is_augment_select=True, augment_choices populated) - only the
    field name diverged. _postprocess (the single chokepoint every
    GameVisionReader consumer runs) must alias it."""
    from modes.shared_vision import GameVisionReader
    r = GameVisionReader.__new__(GameVisionReader)
    out = r._postprocess({
        "is_augment_select": True,
        "augment_choices": ["Critical Rhythm", "Celestial Body", "Bread and Cheese"],
    })
    assert out.get("augment_select") is True
    assert out.get("augment_choices") == [
        "Critical Rhythm", "Celestial Body", "Bread and Cheese"]
    # an explicit augment_select is authoritative - never clobber it
    out2 = r._postprocess({"augment_select": False, "is_augment_select": True})
    assert out2.get("augment_select") is False
    # a dict without either flag is unchanged (no spurious key injected)
    out3 = r._postprocess({"hp": 50})
    assert "augment_select" not in out3


# ==============================================================================
# 4. arena augment name map - numeric patch-dir ordering
# ==============================================================================

def test_augment_name_map_prefers_numerically_newest_patch(tmp_path, monkeypatch):
    """16.10.1 must beat 16.9.1 (lexicographic reverse sort picks 16.9.1)."""
    from coaches import arena_coach as mod
    snap = tmp_path / "data" / "daemon_slayer"
    old = snap / "16.9.1"
    new = snap / "16.10.1"
    junk = snap / "build_orders"  # non-patch dir must not break the sort
    for d in (old, new, junk):
        d.mkdir(parents=True)
    (old / "arena_augments.json").write_text(json.dumps({
        "augments": [{"apiName": "OldOnly", "name": "Old Only"}]
    }), encoding="utf-8")
    (new / "arena_augments.json").write_text(json.dumps({
        "augments": [{"apiName": "NewOnly", "name": "New Only"}]
    }), encoding="utf-8")
    monkeypatch.setattr(mod, "_APP_DIR", tmp_path)
    monkeypatch.setattr(mod, "_AUG_NAME_MAP_CACHE", None)
    out = mod._augment_name_map()
    assert out.get("newonly") == "NewOnly", f"stale patch dir won: {out}"
    assert "oldonly" not in out


def test_augment_name_map_missing_dir_returns_empty(tmp_path, monkeypatch):
    from coaches import arena_coach as mod
    monkeypatch.setattr(mod, "_APP_DIR", tmp_path / "nope")
    monkeypatch.setattr(mod, "_AUG_NAME_MAP_CACHE", None)
    assert mod._augment_name_map() == {}


# ==============================================================================
# 5. aram_team_analyzer - no exception type names in user-facing reason
# ==============================================================================

def test_analyzer_error_reason_is_friendly(tmp_path, monkeypatch):
    import core.aram_comp_verdict as verdict_mod
    import sys
    from coaches import aram_team_analyzer as mod
    _kill_cost_tracker(monkeypatch)
    monkeypatch.setattr(verdict_mod, "comp_verdict", lambda state: {"ok": False})

    class _ExplodingAnthropic(types.ModuleType):
        class Anthropic:  # noqa: D106 - stub
            def __init__(self, *a, **kw):
                raise RuntimeError("AuthenticationError sk-ant-SECRET details")

    monkeypatch.setitem(
        sys.modules, "anthropic", _ExplodingAnthropic("anthropic"))
    state = {
        "my_champion": "Lulu",
        "my_team": ["Lulu", "Yuumi"],
        "their_team": ["Vayne"],
        "bench": ["Vi"],
        "variants": [],
    }
    out = mod.analyze(state, "k")
    assert out["ok"] is False
    assert "RuntimeError" not in out["reason"]
    assert "SECRET" not in out["reason"]
    assert out["reason"] == "(analyzer paused - retrying)"


# ==============================================================================
# 6. TFT coaches - atomic data-file writes
# ==============================================================================

def test_tft_reset_state_uses_atomic_safe_write(tmp_path, monkeypatch):
    from coaches import tft_coach as mod
    written: list = []
    real = safe_write

    def _spy(path, data):
        written.append((path, data))
        # Forward the verdict: safe_write returns bool since lane 8 cycle 34,
        # and a spy that drops it would report a false write failure.
        return real(path, data)

    # Pre-fix this setattr fails: tft_coach had no safe_write binding.
    monkeypatch.setattr(mod, "safe_write", _spy)
    c = mod.Coach.__new__(mod.Coach)
    c._data_file = tmp_path / "x.json"
    c._tft_data_file = tmp_path / "tft_coaching_data.json"
    c._live_data_file = tmp_path / "tft_live_data.json"
    c._worker = None
    c.reset_state()
    paths = {p.name for p, _ in written}
    assert paths == {"tft_coaching_data.json", "tft_live_data.json"}
    data = json.loads(c._tft_data_file.read_text(encoding="utf-8"))
    assert data["mode"] == "tft"
    assert not list(tmp_path.glob("*.tmp")), "leftover tmp file"


def test_tft_pbe_data_files_use_atomic_safe_write(tmp_path, monkeypatch):
    from coaches import tft_pbe_coach as mod
    written: list = []
    real = safe_write

    def _spy(path, data):
        written.append(path)
        return real(path, data)

    monkeypatch.setattr(mod, "safe_write", _spy)
    c = mod.Coach.__new__(mod.Coach)
    c._tft_data_file = tmp_path / "tft_pbe_coaching_data.json"
    c._live_data_file = tmp_path / "tft_pbe_live_data.json"
    c._ensure_data_files()
    assert {p.name for p in written} == {
        "tft_pbe_coaching_data.json", "tft_pbe_live_data.json"}
    data = json.loads(c._tft_data_file.read_text(encoding="utf-8"))
    assert data["mode"] == "tft_pbe"


# ==============================================================================
# 7. safe_write concurrency smoke (shared .tmp name, serialized writers)
# ==============================================================================

def test_safe_write_concurrent_writers_keep_valid_json(tmp_path):
    target = tmp_path / "artifact.json"
    payloads = [{"writer": i, "blob": "x" * 4000} for i in range(6)]
    errs: list = []

    def _hammer(p):
        try:
            for _ in range(25):
                safe_write(target, p)
        except Exception as exc:  # pragma: no cover - failure surface  # noqa: BLE001
            errs.append(exc)

    threads = [threading.Thread(target=_hammer, args=(p,)) for p in payloads]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert not errs
    final = json.loads(target.read_text(encoding="utf-8"))
    assert final in payloads


# ==============================================================================
# 8. replay_coach characterization - db edge cases never raise
# ==============================================================================

def test_replay_load_match_missing_db(tmp_path, monkeypatch):
    from coaches import replay_coach as mod
    monkeypatch.setattr(mod, "_REWIND_DB", tmp_path / "absent.db")
    assert mod._load_match("NA1_123") is None


def test_replay_load_match_corrupt_db(tmp_path, monkeypatch):
    from coaches import replay_coach as mod
    bad = tmp_path / "rewind_history.db"
    bad.write_bytes(b"this is not a sqlite database at all - just bytes")
    monkeypatch.setattr(mod, "_REWIND_DB", bad)
    assert mod._load_match("NA1_123") is None


def test_replay_analyze_match_no_key_friendly():
    from coaches import replay_coach as mod
    out = mod.analyze_match("NA1_123", api_key=None)
    assert out["ok"] is False
    assert out["summary"] == "(API key missing - coach disabled)"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
