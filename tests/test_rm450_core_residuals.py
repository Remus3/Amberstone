"""RM-450 - the five core/ load-path residuals left open by RM-443.

1. augment_external_source.get_priors / get_augment_meta cached a NETWORK
   failure (the degraded table) under an unchanged mtime until restart. Now:
   served during a backoff window, retried at most once per window, and the
   window is long against the HTTP timeout so the augment tick does not pay a
   timeout per call.
2. augment_recommender.load_own_history ran the LCU row-count query (db open +
   full LIKE count) on EVERY call, before its cache check. Now the count is
   memoised under a cheap stat signature with a TTL; a new game still
   invalidates.
3. vision_template_match._atlas cached a MISSING (or empty) category folder as
   an empty atlas forever. The folders are tracked in git and filled by the
   icon pipeline, which can run while RC is up, so absence is a failure state,
   not a design state: not cached, retried after the backoff.
4. minimap_identity._masked_template re-read an unreadable icon on every call.
   Now gated per icon stem.
5. replay_history._load_champ_index raised AttributeError on non-object JSON
   (the data.get sat outside the try) and treated an empty index as loaded, so
   match_detail cached name-less results.

No network (HTTP seams are stubbed), no live ports; cv2 and numpy are stubbed
through sys.modules so the file runs on a CI host without opencv. The clock is
advanced by patching ``time.monotonic``.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

import pytest

import core.augment_external_source as aes
import core.augment_recommender as ar
import core.minimap_identity as mmi
import core.replay_history as rh
import core.vision_template_match as vtm
from core.failed_load_gate import FailedLoadGate

_PATCH = "9.9.9"
_PAST_BACKOFF = 3600.0
_MODULES = (aes, ar, vtm, mmi, rh)


def _reset_all() -> None:
    aes.reset_cache()
    ar.reset_cache()
    vtm._reset_caches()
    mmi._reset_caches()
    rh._MATCH_DETAIL_CACHE.clear()
    rh._id_to_champ.clear()
    # Gates found by TYPE (the RM-443 lesson: a name-suffix rule leaked a
    # backoff between tests).
    for mod in _MODULES:
        for obj in list(vars(mod).values()):
            if isinstance(obj, FailedLoadGate):
                obj.reset()
            elif isinstance(obj, dict) and any(
                isinstance(v, FailedLoadGate) for v in list(obj.values())
            ):
                obj.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_all()
    yield
    _reset_all()


class _Clock:
    def __init__(self) -> None:
        self.now = 2_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(time, "monotonic", c)
    return c


def _warnings(caplog, name: str) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.name == name and r.levelno >= logging.WARNING]


# -- 1. augment_external_source ------------------------------------------------

_PRIORS_PAYLOAD = {"data": [
    {"augment_id": "1088", "patch": "16.10", "stats": {"win_rate": 0.5}},
]}
_CHERRY_PAYLOAD = [{"id": 1103, "nameTRA": "Bread And Butter", "rarity": "kGold"}]


def _point_aes(tmp_path: Path, monkeypatch) -> Path:
    ds = tmp_path / "daemon_slayer"
    (ds / _PATCH).mkdir(parents=True)
    (ds / "current.txt").write_text(_PATCH, encoding="utf-8")
    monkeypatch.setattr(aes, "_DS_DATA_DIR", ds)
    monkeypatch.setattr(aes, "_PATCH_FILE", ds / "current.txt")
    return ds


class _Net:
    """Stub for an HTTP seam: raises AugmentSourceError while ``fail``."""

    def __init__(self, payload) -> None:
        self.payload = payload
        self.fail = True
        self.calls = 0

    def __call__(self, url, timeout_s):
        self.calls += 1
        if self.fail:
            raise aes.AugmentSourceError("fetch failed: timed out")
        return self.payload


def test_priors_backoff_is_written_against_the_tick_timeout():
    """The retry window must dwarf one HTTP timeout, or a dead host costs the
    augment tick a timeout on (nearly) every call."""
    assert aes._NETWORK_RETRY_AFTER_S >= 10 * aes._HTTP_TIMEOUT_S


def test_priors_network_failure_is_retried_after_the_backoff(
    tmp_path, monkeypatch, clock, caplog,
):
    _point_aes(tmp_path, monkeypatch)
    net = _Net(_PRIORS_PAYLOAD)
    monkeypatch.setattr(aes, "_http_get_json", net)
    caplog.set_level(logging.DEBUG)

    assert not aes.get_priors("mayhem").has_data
    assert net.calls == 1
    for _ in range(5):  # augment ticks inside the window: no HTTP
        clock.advance(aes._HTTP_TIMEOUT_S + 5.0)
        assert not aes.get_priors("mayhem").has_data
    assert net.calls == 1, "a tick inside the backoff paid an HTTP attempt"

    clock.advance(_PAST_BACKOFF)
    assert not aes.get_priors("mayhem").has_data  # still down
    assert net.calls == 2
    assert len(_warnings(caplog, aes._log.name)) == 1, "warn once per streak"

    net.fail = False
    clock.advance(_PAST_BACKOFF)
    table = aes.get_priors("mayhem")
    assert table.has_data and table.win_rate(1088) == 0.5
    assert net.calls == 3
    assert aes.get_priors("mayhem").has_data  # success is cached
    clock.advance(_PAST_BACKOFF)
    assert aes.get_priors("mayhem").has_data
    assert net.calls == 3


def test_priors_degraded_snapshot_is_served_then_replaced(
    tmp_path, monkeypatch, clock,
):
    ds = _point_aes(tmp_path, monkeypatch)
    old = ds / "9.9.8"
    old.mkdir()
    (old / "mayhem_augment_stats.json").write_text(json.dumps(
        {"rc_patch": "9.9.8", "augments": {"1": {"win_rate": 0.4}}}),
        encoding="utf-8")
    net = _Net(_PRIORS_PAYLOAD)
    monkeypatch.setattr(aes, "_http_get_json", net)

    assert aes.get_priors("mayhem").rc_patch == "9.9.8"
    assert aes.get_priors("mayhem").rc_patch == "9.9.8"
    assert net.calls == 1
    net.fail = False
    clock.advance(_PAST_BACKOFF)
    assert aes.get_priors("mayhem").rc_patch == _PATCH


def test_priors_file_landing_inside_the_backoff_is_read_without_network(
    tmp_path, monkeypatch, clock,
):
    """The gate blocks the NETWORK only: a snapshot written by another process
    during the window is picked up by the mtime check at once."""
    ds = _point_aes(tmp_path, monkeypatch)
    net = _Net(_PRIORS_PAYLOAD)
    monkeypatch.setattr(aes, "_http_get_json", net)
    assert not aes.get_priors("mayhem").has_data
    (ds / _PATCH / "mayhem_augment_stats.json").write_text(json.dumps(
        {"rc_patch": _PATCH, "augments": {"7": {"win_rate": 0.6}}}),
        encoding="utf-8")
    assert aes.get_priors("mayhem").win_rate(7) == 0.6
    assert net.calls == 1


def test_meta_network_failure_is_retried_after_the_backoff(
    tmp_path, monkeypatch, clock, caplog,
):
    _point_aes(tmp_path, monkeypatch)
    net = _Net(_CHERRY_PAYLOAD)
    monkeypatch.setattr(aes, "_http_get", net)
    caplog.set_level(logging.DEBUG)

    assert not aes.get_augment_meta().has_data
    clock.advance(aes._HTTP_TIMEOUT_S + 5.0)
    assert not aes.get_augment_meta().has_data
    assert net.calls == 1

    clock.advance(_PAST_BACKOFF)
    aes.get_augment_meta()
    assert net.calls == 2
    assert len(_warnings(caplog, aes._log.name)) == 1

    net.fail = False
    clock.advance(_PAST_BACKOFF)
    meta = aes.get_augment_meta()
    assert meta.resolve_id("bread and butter") == 1103
    assert net.calls == 3
    clock.advance(_PAST_BACKOFF)
    assert aes.get_augment_meta().has_data
    assert net.calls == 3


def test_refresh_cache_contract_unchanged(tmp_path, monkeypatch, clock):
    """The explicit refresh path is not gated: force raises, non-force
    degrades, every call attempts the network."""
    _point_aes(tmp_path, monkeypatch)
    net = _Net(_PRIORS_PAYLOAD)
    monkeypatch.setattr(aes, "_http_get_json", net)
    assert not aes.refresh_cache("mayhem").has_data
    assert not aes.refresh_cache("mayhem").has_data
    assert net.calls == 2
    with pytest.raises(aes.AugmentSourceError):
        aes.refresh_cache("mayhem", force=True)


# -- 2. augment_recommender row count --------------------------------------------

def _raw(aug: int = 101) -> str:
    return json.dumps({"tracked_puuid": "P", "lcu_match_detail": {
        "gameMode": "KIWI", "queueId": 2400,
        "participantIdentities": [{"participantId": 1, "player": {"puuid": "P"}}],
        "participants": [{"participantId": 1,
                          "stats": {"playerAugment1": aug, "win": True}}],
    }})


def _history_db(tmp_path: Path, journal: str = "delete") -> Path:
    db = tmp_path / "match_history.db"
    conn = sqlite3.connect(db)
    conn.execute(f"PRAGMA journal_mode={journal}")
    conn.execute("CREATE TABLE matches (id INTEGER PRIMARY KEY, raw_data TEXT)")
    conn.execute("INSERT INTO matches (raw_data) VALUES (?)", (_raw(),))
    conn.commit()
    conn.close()
    return db


def _count_queries(monkeypatch) -> dict:
    seen = {"count": 0, "scan": 0}
    real_connect = sqlite3.connect

    class _Conn:
        def __init__(self, real) -> None:
            self._real = real

        def execute(self, sql, *a):
            if sql.startswith("SELECT COUNT"):
                seen["count"] += 1
            elif sql.startswith("SELECT raw_data"):
                seen["scan"] += 1
            return self._real.execute(sql, *a)

        def __getattr__(self, name):
            return getattr(self._real, name)

    monkeypatch.setattr(sqlite3, "connect",
                        lambda *a, **kw: _Conn(real_connect(*a, **kw)))
    return seen


@pytest.mark.parametrize("journal", ["delete", "wal"])
def test_row_count_query_is_not_run_on_every_call(journal, tmp_path, monkeypatch):
    db = _history_db(tmp_path, journal)
    keep = sqlite3.connect(db)  # a live RC holds the db open (MatchDB)
    keep.execute("SELECT 1 FROM matches").fetchone()  # ...and has read it
    try:
        seen = _count_queries(monkeypatch)
        for _ in range(6):
            assert ar.load_own_history("mayhem", db_path=db).n_matches == 1
        assert seen["count"] == 1, f"row count ran {seen['count']} times"
        assert seen["scan"] == 1
    finally:
        keep.close()


# The writes below are deliberately SMALL rows, back to back: a same-size
# page rewrite inside one mtime tick is exactly what a stat signature misses.

@pytest.mark.parametrize("journal", ["delete", "wal"])
def test_small_new_game_invalidates_every_time(journal, tmp_path):
    db = _history_db(tmp_path, journal)
    writer = sqlite3.connect(db)  # held open across back-to-back writes
    try:
        for n in range(2, 12):
            writer.execute("INSERT INTO matches (raw_data) VALUES (?)", (_raw(),))
            writer.commit()
            hist = ar.load_own_history("mayhem", db_path=db)
            assert hist.n_matches == n and hist.games == {101: n}
    finally:
        writer.close()


@pytest.mark.parametrize("journal", ["delete", "wal"])
def test_in_place_update_invalidates(journal, tmp_path):
    """The live ingest (dashboard LCU stamp) UPDATEs an existing row, which
    need not change the row count - the cache must still move."""
    db = _history_db(tmp_path, journal)
    writer = sqlite3.connect(db)
    try:
        assert ar.load_own_history("mayhem", db_path=db).games == {101: 1}
        for aug in (202, 303, 404):
            writer.execute("UPDATE matches SET raw_data = ? WHERE id = 1", (_raw(aug),))
            writer.commit()
            assert ar.load_own_history("mayhem", db_path=db).games == {aug: 1}
    finally:
        writer.close()


def test_no_exact_signal_falls_back_to_counting(tmp_path, monkeypatch):
    """WAL with no -shm (no connection open anywhere) has no exact change
    token; the loader must then count on every call rather than guess."""
    db = _history_db(tmp_path, "wal")
    assert ar._change_token(db) is None
    monkeypatch.setattr(ar, "_change_token", lambda p: None)
    seen = _count_queries(monkeypatch)
    for _ in range(3):
        assert ar.load_own_history("mayhem", db_path=db).n_matches == 1
    assert seen["count"] == 3
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO matches (raw_data) VALUES (?)", (_raw(),))
    conn.commit()
    conn.close()
    assert ar.load_own_history("mayhem", db_path=db).n_matches == 2


@pytest.mark.parametrize("mutate", ["torn-shm", "uninitialised-shm", "not-sqlite"])
def test_change_token_refuses_an_unreliable_read(mutate, tmp_path):
    db = _history_db(tmp_path, "wal")
    keep = sqlite3.connect(db)
    try:
        keep.execute("SELECT 1 FROM matches").fetchone()
        assert ar._change_token(db) is not None
        real = ar._read_head

        def fake(path, n):
            data = bytearray(real(path, n))
            if path.endswith("-shm") and mutate == "torn-shm":
                data[8] ^= 0xFF  # first header copy only
            elif path.endswith("-shm") and mutate == "uninitialised-shm":
                data[12] = data[60] = 0
            elif not path.endswith(("-shm", "-wal")) and mutate == "not-sqlite":
                data[0:16] = b"x" * 16
            return bytes(data)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ar, "_read_head", fake)
            assert ar._change_token(db) is None
    finally:
        keep.close()


# -- 3. vision_template_match missing category folder --------------------------

class _FakeCv2:
    IMREAD_COLOR = 1
    COLOR_BGR2RGB = 4
    INTER_AREA = 3
    fail = False
    reads = 0

    @classmethod
    def imread(cls, path, flag):
        cls.reads += 1
        return None if cls.fail else "img:" + Path(path).stem

    @staticmethod
    def cvtColor(img, code):
        return img

    @staticmethod
    def resize(img, size, interpolation=None):
        return img


class _Arr:
    """Just enough ndarray surface for _masked_template's mask arithmetic."""

    def __sub__(self, o):
        return self

    def __add__(self, o):
        return self

    def __pow__(self, o):
        return self

    def __le__(self, o):
        return self

    def __mul__(self, o):
        return self

    def astype(self, t):
        return self


class _Ogrid:
    def __getitem__(self, key):
        return _Arr(), _Arr()


class _FakeNp:
    uint8 = "uint8"
    ogrid = _Ogrid()

    @staticmethod
    def ascontiguousarray(x):
        return x


@pytest.fixture
def fake_cv(monkeypatch):
    _FakeCv2.fail = False
    _FakeCv2.reads = 0
    monkeypatch.setitem(sys.modules, "cv2", _FakeCv2)
    monkeypatch.setitem(sys.modules, "numpy", _FakeNp)
    return _FakeCv2


@pytest.mark.parametrize("make_dir", [False, True], ids=["absent", "empty"])
def test_missing_category_folder_is_not_cached_and_recovers(
    make_dir, tmp_path, monkeypatch, clock, caplog, fake_cv,
):
    folder = tmp_path / "items"
    if make_dir:
        folder.mkdir()
    monkeypatch.setitem(vtm._CATEGORY_DIRS, "items", folder)
    caplog.set_level(logging.DEBUG)

    assert vtm._atlas("items") == {}
    assert "items" not in vtm._ATLAS_CACHE
    assert vtm.list_ids("items") == []
    assert "items" not in vtm._INDEX_CACHE

    folder.mkdir(exist_ok=True)
    (folder / "Thornmail.png").write_bytes(b"")
    assert vtm._atlas("items") == {}, "inside the backoff: no rescan"

    clock.advance(_PAST_BACKOFF)
    assert vtm._atlas("items") == {"Thornmail": "img:Thornmail"}
    assert "items" in vtm._ATLAS_CACHE
    assert len(_warnings(caplog, vtm._log.name)) == 1


def test_unknown_category_and_absent_opencv_stay_cached(monkeypatch):
    assert vtm._atlas("nonsense") == {}
    assert vtm._ATLAS_CACHE.get("nonsense") == {}
    monkeypatch.setitem(sys.modules, "cv2", None)
    assert vtm._atlas("items") == {}
    assert vtm._ATLAS_CACHE.get("items") == {}


# -- 4. minimap_identity unreadable icon -----------------------------------------

def _point_mmi(tmp_path: Path, monkeypatch) -> None:
    icons = tmp_path / "icons"
    icons.mkdir()
    (icons / "Ashe.png").write_bytes(b"")
    monkeypatch.setattr(mmi, "_ICON_DIR", icons)
    champs = tmp_path / "ddragon_champions.json"
    champs.write_text(json.dumps({"data": {"Ashe": {"id": "Ashe", "name": "Ashe"}}}),
                      encoding="utf-8")
    monkeypatch.setattr(mmi, "_CHAMPS_PATH", champs)


def test_unreadable_icon_is_not_reread_on_every_call(
    tmp_path, monkeypatch, clock, caplog, fake_cv,
):
    _point_mmi(tmp_path, monkeypatch)
    fake_cv.fail = True
    caplog.set_level(logging.DEBUG)

    for _ in range(4):
        assert mmi._masked_template("Ashe", 16) is None
    assert fake_cv.reads == 1, f"icon re-read {fake_cv.reads} times"
    assert mmi._masked_template("Ashe", 20) is None  # same icon, other size
    assert fake_cv.reads == 1

    fake_cv.fail = False
    clock.advance(_PAST_BACKOFF)
    assert mmi._masked_template("Ashe", 16) is not None
    assert fake_cv.reads == 2
    assert mmi._masked_template("Ashe", 16) is not None  # cached
    assert fake_cv.reads == 2
    assert len(_warnings(caplog, mmi._log.name)) == 1


# -- 5. replay_history champion index -------------------------------------------

_AHRI = json.dumps({"data": {"Ahri": {"key": "103", "name": "Ahri"}}})


@pytest.mark.parametrize("text", [
    "[1, 2]",
    json.dumps({"data": [1, 2]}),
    json.dumps({"data": {}}),
    json.dumps({"data": {"Ahri": "not-an-object"}}),
], ids=["top-level-list", "data-list", "empty-data", "entry-not-object"])
def test_champion_index_bad_shape_does_not_raise_and_is_not_cached(
    text, tmp_path, monkeypatch, clock, caplog,
):
    champs = tmp_path / "ddragon_champions.json"
    champs.write_text(text, encoding="utf-8")
    monkeypatch.setattr(rh, "_DDR_CHAMPS", champs)
    caplog.set_level(logging.DEBUG)

    assert rh._load_champ_index() is False
    assert rh._id_to_champ == {}
    assert rh._load_champ_index() is False
    assert len(_warnings(caplog, rh._log.name)) == 1

    champs.write_text(_AHRI, encoding="utf-8")
    clock.advance(_PAST_BACKOFF)
    assert rh._load_champ_index() is True
    assert rh._id_to_champ == {103: "Ahri"}


def test_list_matches_survives_non_object_champion_json(tmp_path, monkeypatch):
    champs = tmp_path / "ddragon_champions.json"
    champs.write_text("[1, 2]", encoding="utf-8")
    monkeypatch.setattr(rh, "_DDR_CHAMPS", champs)
    monkeypatch.setattr(rh, "_REWIND_DB", tmp_path / "absent.db")
    assert rh.list_matches() == []
