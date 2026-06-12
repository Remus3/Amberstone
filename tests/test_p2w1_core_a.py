"""Deep-audit cycle 7 P2-W1 slice A regression pins (core live-data spine).

TDD-first tests for the FIX-NOW set:

  1. TftSnapshot.from_state_dict must defensively copy raw_state
     (parity with RiftSnapshot/AramSnapshot - the 2026-04-28 audit
     copy landed on Rift+Aram but missed TFT).
  2. liveclient_cache._auth_headers must never fall back to the
     retired hardcoded legacy vision token (vision_token proposal 1.7
     retired the constant; the cache fallback silently un-retired it).
  3. replay_history._load_champ_index must publish a complete index
     (no partial-publish window that poisons the match-detail LRU
     with "?" champion names).
  4. match_metrics.Recorder.flush must not drop buffered rows when the
     DB write fails transiently (sqlite "database is locked" class);
     rows are re-queued, capped, and written on the next flush.
  5. riot_api dead placate hack (`_ = Any`) removed - drift guard.

Plus cheap characterization pins for queue_modes + mayhem_detect.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_LEGACY_VISION_TOKEN = "8e8f131e212b329438218eca27372dde"


# ---------------------------------------------------------------------------
# 1. TftSnapshot raw_state defensive copy (FROZEN-file fix, charter-auth)
# ---------------------------------------------------------------------------

class TestTftSnapshotRawStateCopy:
    def _tft_state(self) -> dict:
        return {
            "game_mode": "TFT",
            "game_time_s": 312.0,
            "level": 6,
            "gold": 34,
            "health": 77,
            "stage": 3,
            "round": 2,
            "stage_round": "3-2",
            "board": [{"name": "Ahri", "tier": 2}],
            "bench": [],
            "shop": [],
            "traits": {"Sorcerer": 4},
            "augments": ["aug1"],
            "items": ["BF Sword"],
        }

    def test_mutating_source_dict_does_not_leak_into_raw_state(self):
        from core.game_snapshot import TftSnapshot
        d = self._tft_state()
        snap = TftSnapshot.from_state_dict(d)
        # Producer keeps mutating its working dict after publish.
        d["gold"] = 9999
        d["board"].append({"name": "Zed", "tier": 3})
        d["traits"]["Sorcerer"] = 6
        assert snap.raw_state is not d
        assert snap.raw_state["gold"] == 34
        assert len(snap.raw_state["board"]) == 1
        assert snap.raw_state["traits"]["Sorcerer"] == 4

    def test_rift_and_aram_parity_already_copy(self):
        # Characterization: the 2026-04-28 copy is in place for SR + ARAM.
        from core.game_snapshot import AramSnapshot, RiftSnapshot
        for cls in (RiftSnapshot, AramSnapshot):
            d = {"game_mode": "X", "gold": 1, "items": ["a"]}
            snap = cls.from_state_dict(d)
            d["gold"] = 2
            assert snap.raw_state is not d
            assert snap.raw_state["gold"] == 1


# ---------------------------------------------------------------------------
# 2. liveclient_cache auth-header hardening
# ---------------------------------------------------------------------------

class TestLiveclientCacheAuthHeaders:
    def test_uses_resolver_token_when_available(self, monkeypatch):
        import core.vision_token as vt
        from core import liveclient_cache
        monkeypatch.setattr(vt, "get_vision_token", lambda: "tok-resolved")
        headers = liveclient_cache._auth_headers()
        assert headers == {"X-RC-Token": "tok-resolved"}

    def test_resolver_failure_never_emits_legacy_constant(self, monkeypatch):
        import core.vision_token as vt
        from core import liveclient_cache

        def _boom():
            raise RuntimeError("vision_token: no token configured")

        monkeypatch.setattr(vt, "get_vision_token", _boom)
        headers = liveclient_cache._auth_headers()
        assert headers.get("X-RC-Token", None) != _LEGACY_VISION_TOKEN
        # Fail-soft contract: header key present, token empty -> server 401s
        # and the poll loop retries; never a silently-authenticating constant.
        assert headers == {"X-RC-Token": ""}

    def test_legacy_hex_absent_from_module_source(self):
        src = (_PROJECT_ROOT / "core" / "liveclient_cache.py").read_text(
            encoding="utf-8")
        assert _LEGACY_VISION_TOKEN not in src


# ---------------------------------------------------------------------------
# 3. replay_history champion-index load (complete-publish)
# ---------------------------------------------------------------------------

class TestReplayHistoryChampIndex:
    def _fixture_json(self, tmp_path: Path) -> Path:
        p = tmp_path / "ddragon_champions.json"
        p.write_text(
            '{"data": {"Ahri": {"key": "103", "name": "Ahri"},'
            ' "TahmKench": {"key": "223", "name": "Tahm Kench"},'
            ' "Bad": {"key": "not-an-int", "name": "Skipped"}}}',
            encoding="utf-8",
        )
        return p

    def test_index_loads_fully_and_is_idempotent(self, monkeypatch, tmp_path):
        from core import replay_history as rh
        monkeypatch.setattr(rh, "_DDR_CHAMPS", self._fixture_json(tmp_path))
        monkeypatch.setattr(rh, "_id_to_champ", {})
        rh._load_champ_index()
        assert rh._id_to_champ[103] == "Ahri"
        assert rh._id_to_champ[223] == "Tahm Kench"
        assert len(rh._id_to_champ) == 2  # malformed key skipped
        # Second call is a no-op (already loaded).
        rh._load_champ_index()
        assert len(rh._id_to_champ) == 2

    def test_corrupt_file_leaves_index_empty_not_partial(self, monkeypatch, tmp_path):
        from core import replay_history as rh
        bad = tmp_path / "ddragon_champions.json"
        bad.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(rh, "_DDR_CHAMPS", bad)
        monkeypatch.setattr(rh, "_id_to_champ", {})
        rh._load_champ_index()
        assert rh._id_to_champ == {}


# ---------------------------------------------------------------------------
# 4. match_metrics flush re-queues rows on transient DB failure
# ---------------------------------------------------------------------------

class TestRecorderFlushRequeue:
    def _fresh_recorder(self, monkeypatch, tmp_path: Path):
        import core.match_metrics as mm
        monkeypatch.setattr(mm, "DB_PATH", tmp_path / "match_metrics.db")
        return mm, mm.Recorder()

    def _record_n(self, rec, n: int) -> None:
        for i in range(n):
            rec.record(match_id="m1", key=f"k{i}", value=i)

    def test_failed_flush_preserves_rows_then_next_flush_writes(
            self, monkeypatch, tmp_path):
        mm, rec = self._fresh_recorder(monkeypatch, tmp_path)
        self._record_n(rec, 2)
        assert rec.buffered() == 2

        real_connect = mm.sqlite3.connect

        def _locked(*a, **k):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(mm.sqlite3, "connect", _locked)
        with pytest.raises(sqlite3.OperationalError):
            rec.flush()
        # Regression pin: pre-fix the swap-out dropped both rows here.
        assert rec.buffered() == 2

        monkeypatch.setattr(mm.sqlite3, "connect", real_connect)
        assert rec.flush() == 2
        assert rec.buffered() == 0
        conn = sqlite3.connect(mm.DB_PATH)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM match_metrics").fetchone()[0]
        finally:
            conn.close()
        assert n == 2

    def test_requeue_is_capped_keeping_newest(self, monkeypatch, tmp_path):
        mm, rec = self._fresh_recorder(monkeypatch, tmp_path)
        monkeypatch.setattr(mm, "_REQUEUE_MAX", 3)
        self._record_n(rec, 5)

        def _locked(*a, **k):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(mm.sqlite3, "connect", _locked)
        with pytest.raises(sqlite3.OperationalError):
            rec.flush()
        assert rec.buffered() == 3
        with rec._lock:
            kept_keys = [row[4] for row in rec._buf]
        assert kept_keys == ["k2", "k3", "k4"]  # oldest dropped, order kept


# ---------------------------------------------------------------------------
# 5. riot_api dead placate hack removed (drift guard)
# ---------------------------------------------------------------------------

class TestRiotApiCleanup:
    def test_placate_hack_gone_and_module_imports(self):
        src = (_PROJECT_ROOT / "core" / "riot_api.py").read_text(
            encoding="utf-8")
        assert "_ = Any" not in src
        import core.riot_api as ra
        assert callable(ra.is_configured)


# ---------------------------------------------------------------------------
# Characterization pins (no behavior change - lock current contracts)
# ---------------------------------------------------------------------------

class TestQueueModesPins:
    def test_edge_cases(self):
        from core.queue_modes import mode_key_from_queue_id
        assert mode_key_from_queue_id(None) is None
        assert mode_key_from_queue_id(0) is None
        assert mode_key_from_queue_id(-5) is None
        assert mode_key_from_queue_id("450") == "aram"
        assert mode_key_from_queue_id("garbage") is None
        assert mode_key_from_queue_id(2400) == "aram"
        assert mode_key_from_queue_id(1750) == "arena"
        assert mode_key_from_queue_id(123456) is None


class TestMayhemDetectPins:
    def test_shapes(self):
        from core.mayhem_detect import is_mayhem
        assert is_mayhem("KIWI") is True
        assert is_mayhem({"game_mode": "kiwi"}) is True
        assert is_mayhem({"gameMode": "ARAM_MAYHEM"}) is True

        class _Snap:
            game_mode = "MAYHEM"

        assert is_mayhem(_Snap()) is True
        assert is_mayhem(None) is False
        assert is_mayhem({"game_mode": "ARAM"}) is False
