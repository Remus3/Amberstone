"""s144 true-audit cycle 122: modules/cache_engine.py, the SR auto-coach
decision cache that ``coach_integration/_coach.py`` reads before every Haiku
call and writes after every paid response (RM-1582 and the provisional S144-T-205..-215).

The cache is an OPTIMISATION. Every finding below is a way it could instead
take the coach down, throw away a response already paid for, or keep paying
for one it already holds:

  T-204  get() raised on a locked / corrupt / tableless database, which aborts
         the whole coach turn before the Haiku call.
  T-205  set() raised AFTER the paid call, so ``_run`` never wrote the fields.
  T-206  the constructor raised on a corrupt database or an unmakeable parent,
         which takes ``CoachIntegration`` (all SR coaching) down with it.
  T-207  flag_bad() raised into the context-menu action.
  T-208  ``with sqlite3.connect(...)`` commits but never closes: every call
         left its connection (and its Windows file handle) to the GC.
  T-209  make_cache_key raised on merely wrong input: None / scalar / mixed
         lists, a non-dict lane_matchup or objective_timers, a None or text
         clock, a text HP or mana, a non-JSON value. A well-typed state (name
         / id lists, an int / float clock, an int / float / None HP and mana,
         a dict of timers) keeps its exact
         digest; a str or dict where a list belongs now reads as [] (it used
         to be iterated as characters / keys), so only junk changes key.
  T-210  NaN HP read as "critical", NaN mana as "oom", a NaN / inf clock as
         "late", a bool as a number.
  T-211  a row that hit max_use_count was retired FOREVER: the refresh set()
         kept the old use_count, so every recurrence paid a Haiku call and
         cached an answer that was never served (33 such rows in the live DB,
         measured read-only 2026-11-05).
  T-212  a NULL / text confidence or use_count (SQLite stores a NaN product as
         NULL) raised TypeError in get(); bump_confidence accepted NaN.
  T-213  bump_confidence absorbed ANY exception; now only sqlite3.Error /
         OSError, so a programming error surfaces.
  T-214  a non-dict state raised AttributeError in every method.
  T-215  set() cached an empty or non-text response.
"""
from __future__ import annotations

import logging
import math
import sqlite3

import pytest

import modules.cache_engine as ce
from modules.cache_engine import CacheEngine, make_cache_key


def _state(**over):
    s = {
        "champion": "Jinx",
        "ally_comp": ["Thresh", "Ahri", "Garen", "Vi"],
        "lane_matchup": {"enemy_adc": "Caitlyn"},
        "game_time_s": 905,
        "wave_state": "pushing",
        "my_hp_pct": 0.55,
        "my_mana_pct": 0.3,
        "my_items": [3031, 1055, 3006],
        "objective_timers": {"dragon": 45, "baron": None},
        "nearby_enemies": ["Vi", "Caitlyn"],
        "patch_version": "current",
    }
    s.update(over)
    return s


@pytest.fixture()
def eng(tmp_path):
    return CacheEngine(tmp_path / "d.db")


def _raw(eng):
    c = sqlite3.connect(str(eng.db_path))
    try:
        return c.execute(
            "SELECT confidence, use_count, response FROM decisions").fetchall()
    finally:
        c.close()


# -- characterisation: valid input keeps its key ------------------------------

def test_valid_state_digests_are_unchanged():
    """Digests captured from the pre-audit code; a change re-keys every live row."""
    assert make_cache_key(_state()) == "e36ccfe6b73e3fb5a4ee"
    assert make_cache_key({}) == "212223438a87e69caafe"
    assert make_cache_key({"ally_comp": [1, 2], "my_items": ["a"],
                           "game_time_s": 0.0}) == "0ff4f04e8dca9febd1c7"


def test_well_typed_states_match_the_pre_audit_key_function():
    """The pre-audit make_cache_key, inlined verbatim, against well-typed states."""
    import hashlib
    import json

    def old_key(state):
        def pb(t):
            return "early" if t < 600 else "mid" if t < 1500 else "late"

        def hb(p):
            if p is None: return "unknown"
            if p > 0.75: return "full"
            if p > 0.40: return "half"
            if p > 0.20: return "low"
            return "critical"

        def mb(p):
            if p is None: return "unknown"
            if p > 0.60: return "high"
            if p > 0.25: return "low"
            return "oom"

        def ow(timers):
            if not timers: return "none"
            soonest = None
            for t in timers.values():
                if t is not None and (soonest is None or t < soonest):
                    soonest = t
            if soonest is None: return "none"
            if soonest < 30: return "imminent"
            if soonest < 90: return "soon"
            return "none"

        def ik(items):
            if not items: return "none"
            return "|".join(sorted(str(i) for i in items))

        kd = {
            "champion": state.get("champion", ""),
            "ally_comp": sorted(state.get("ally_comp", [])),
            "enemy_adc": state.get("lane_matchup", {}).get("enemy_adc", ""),
            "game_phase": pb(state.get("game_time_s", 0)),
            "wave_state": state.get("wave_state", "unknown"),
            "hp_bucket": hb(state.get("my_hp_pct")),
            "mana_bucket": mb(state.get("my_mana_pct")),
            "items_key": ik(state.get("my_items", [])),
            "obj_window": ow(state.get("objective_timers", {})),
            "nearby_enemies": sorted(state.get("nearby_enemies", [])),
            "patch_version": state.get("patch_version", ""),
        }
        return hashlib.sha256(json.dumps(kd, sort_keys=True).encode()).hexdigest()[:20]

    states = [
        _state(),
        {},
        _state(ally_comp=(3, 1, 2), my_items=(), game_time_s=1499.9),
        _state(my_hp_pct=None, my_mana_pct=None, objective_timers={}),
        _state(objective_timers={"a": None, "b": 89.5}, game_time_s=0),
        _state(nearby_enemies=[], lane_matchup={}, patch_version="16.11.1"),
        _state(my_hp_pct=1, my_mana_pct=0, game_time_s=3000, my_items=["3031"]),
        _state(champion="Kai'Sa", wave_state="frozen", patch_version=None),
    ]
    for s in states:
        assert make_cache_key(s) == old_key(s), s


def test_round_trip_hit_and_use_count(eng):
    assert eng.get(_state()) is None
    assert eng.set(_state(), "farm wave") is True
    assert eng.get(_state()) == "farm wave"
    assert _raw(eng)[0][1] == 1


def test_valid_buckets_unchanged():
    assert ce.phase_bucket(0) == "early" and ce.phase_bucket(600) == "mid"
    assert ce.phase_bucket(1500) == "late"
    assert ce.hp_bucket(None) == "unknown" and ce.hp_bucket(0.8) == "full"
    assert ce.hp_bucket(0.5) == "half" and ce.hp_bucket(0.3) == "low"
    assert ce.hp_bucket(0.1) == "critical"
    assert ce.mana_bucket(None) == "unknown" and ce.mana_bucket(0.7) == "high"
    assert ce.mana_bucket(0.3) == "low" and ce.mana_bucket(0.1) == "oom"
    assert ce.obj_window({"d": 10}) == "imminent"
    assert ce.obj_window({"d": 60, "b": None}) == "soon"
    assert ce.obj_window({}) == "none" and ce.obj_window({"d": 200}) == "none"


# -- T-204 get() on a broken database -----------------------------------------

def test_get_on_a_corrupt_database_is_a_miss_and_warns(tmp_path, caplog):
    eng = CacheEngine(tmp_path / "d.db")
    eng.db_path.write_bytes(b"this is not a sqlite database" * 64)
    with caplog.at_level(logging.WARNING, logger="cache"):
        assert eng.get(_state()) is None
    assert any("CacheEngine.get" in r.getMessage() for r in caplog.records
               if r.levelno >= logging.WARNING)


def test_get_on_a_dropped_table_is_a_miss(eng):
    c = sqlite3.connect(str(eng.db_path))
    c.execute("DROP TABLE decisions")
    c.commit()
    c.close()
    assert eng.get(_state()) is None


def test_get_heals_a_dropped_table_on_the_next_write(eng):
    c = sqlite3.connect(str(eng.db_path))
    c.execute("DROP TABLE decisions")
    c.commit()
    c.close()
    assert eng.get(_state()) is None
    assert eng.set(_state(), "recall") is True
    assert eng.get(_state()) == "recall"


# -- T-205 set() after the paid call ------------------------------------------

def test_set_on_a_broken_database_returns_false_never_raises(tmp_path):
    eng = CacheEngine(tmp_path / "d.db")
    eng.db_path.write_bytes(b"garbage" * 200)
    assert eng.set(_state(), "paid answer") is False


# -- T-206 constructor ---------------------------------------------------------

def test_constructor_survives_a_corrupt_database(tmp_path, caplog):
    db = tmp_path / "d.db"
    db.write_bytes(b"not sqlite" * 300)
    with caplog.at_level(logging.WARNING, logger="cache"):
        eng = CacheEngine(db)
    assert eng.get(_state()) is None
    assert eng.set(_state(), "x") is False
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


def test_constructor_survives_an_unmakeable_parent(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="ascii")
    eng = CacheEngine(blocker / "sub" / "d.db")
    assert eng.get(_state()) is None
    assert eng.set(_state(), "x") is False


def test_constructor_retries_schema_once_the_db_is_usable(tmp_path):
    db = tmp_path / "d.db"
    db.write_bytes(b"not sqlite" * 300)
    eng = CacheEngine(db)
    db.unlink()
    assert eng.set(_state(), "now usable") is True
    assert eng.get(_state()) == "now usable"


# -- T-207 flag_bad ------------------------------------------------------------

def test_flag_bad_on_a_broken_database_returns_false(tmp_path):
    eng = CacheEngine(tmp_path / "d.db")
    eng.db_path.write_bytes(b"garbage" * 200)
    assert eng.flag_bad(_state()) is False


def test_flag_bad_halves_confidence(eng):
    eng.set(_state(), "r")
    assert eng.flag_bad(_state()) is True
    assert _raw(eng)[0][0] == pytest.approx(0.5)


# -- T-208 every connection is closed ------------------------------------------

def test_every_connection_is_closed(tmp_path, monkeypatch):
    opened = []
    real = sqlite3.connect

    class _Tracked:
        def __init__(self, conn):
            self._c = conn
            self.closed = False
            opened.append(self)

        def close(self):
            self.closed = True
            self._c.close()

        def __getattr__(self, name):
            return getattr(self._c, name)

        def __setattr__(self, name, value):
            if name in ("_c", "closed"):
                object.__setattr__(self, name, value)
            else:
                setattr(self._c, name, value)

        def __enter__(self):
            self._c.__enter__()
            return self

        def __exit__(self, *exc):
            return self._c.__exit__(*exc)

    monkeypatch.setattr(ce.sqlite3, "connect",
                        lambda *a, **k: _Tracked(real(*a, **k)))
    eng = CacheEngine(tmp_path / "d.db")
    eng.get(_state())
    eng.set(_state(), "r")
    eng.get(_state())
    eng.flag_bad(_state())
    eng.bump_confidence(_state(), 1.2)
    assert len(opened) >= 6
    assert all(t.closed for t in opened), [t.closed for t in opened]

    # A corrupt database fails inside _conn (the journal PRAGMA): still closed.
    opened.clear()
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not sqlite" * 300)
    eng2 = CacheEngine(bad)
    eng2.get(_state())
    eng2.set(_state(), "r")
    assert len(opened) >= 3
    assert all(t.closed for t in opened), [t.closed for t in opened]


# -- T-209 make_cache_key is total ---------------------------------------------

@pytest.mark.parametrize("over", [
    {"ally_comp": None},
    {"ally_comp": "Ahri"},
    {"ally_comp": ["Ahri", 3, None]},
    {"ally_comp": [{"name": "Ahri"}, {"name": "Vi"}]},
    {"nearby_enemies": None},
    {"nearby_enemies": [1, "Vi"]},
    {"lane_matchup": None},
    {"lane_matchup": "Caitlyn"},
    {"game_time_s": None},
    {"game_time_s": "905"},
    {"my_hp_pct": "0.5"},
    {"my_mana_pct": [0.5]},
    {"objective_timers": None},
    {"objective_timers": [30, 40]},
    {"objective_timers": {"dragon": "45", "baron": 80}},
    {"my_items": 3031},
    {"my_items": [object()]},
    {"champion": object()},
    {"patch_version": {"v": 1}},
    {"ally_comp": [{1: "a", "b": 2}]},
])
def test_make_cache_key_never_raises_on_junk(over):
    key = make_cache_key(_state(**over))
    assert isinstance(key, str) and len(key) == 20


def test_make_cache_key_is_order_insensitive_on_mixed_lists():
    a = make_cache_key(_state(ally_comp=["Ahri", 3, None]))
    b = make_cache_key(_state(ally_comp=[None, "Ahri", 3]))
    assert a == b


def test_obj_window_skips_text_and_non_finite_timers():
    assert ce.obj_window({"dragon": "45", "baron": 80}) == "soon"
    assert ce.obj_window({"dragon": float("nan"), "baron": 20}) == "imminent"
    assert ce.obj_window({"dragon": True}) == "none"
    assert ce.obj_window([30]) == "none"


# -- T-210 non-finite / non-number buckets --------------------------------------

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"),
                                 True, "0.5", [0.5]])
def test_hp_and_mana_buckets_read_junk_as_unknown(bad):
    assert ce.hp_bucket(bad) == "unknown"
    assert ce.mana_bucket(bad) == "unknown"


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), True, "905"])
def test_phase_bucket_reads_junk_as_unknown(bad):
    assert ce.phase_bucket(bad) == "unknown"


def test_nan_hp_does_not_share_the_critical_key():
    assert make_cache_key(_state(my_hp_pct=math.nan)) != \
        make_cache_key(_state(my_hp_pct=0.1))


# -- T-211 a retired row revives on refresh -------------------------------------

def test_refresh_after_max_uses_is_served_again(tmp_path):
    eng = CacheEngine(tmp_path / "d.db", max_use_count=2)
    eng.set(_state(), "old")
    assert eng.get(_state()) == "old"
    assert eng.get(_state()) == "old"
    assert eng.get(_state()) is None          # retired
    assert eng.set(_state(), "fresh") is True  # the paid refresh
    assert eng.get(_state()) == "fresh"


# -- T-212 NULL / text row fields ------------------------------------------------

@pytest.mark.parametrize("col,val", [("confidence", None), ("confidence", "high"),
                                     ("use_count", None), ("use_count", "many")])
def test_null_or_text_row_field_is_a_miss_not_a_type_error(eng, col, val):
    eng.set(_state(), "r")
    c = sqlite3.connect(str(eng.db_path))
    c.execute(f"UPDATE decisions SET {col}=?", (val,))
    c.commit()
    c.close()
    assert eng.get(_state()) is None


def test_null_confidence_row_heals_on_refresh(eng):
    eng.set(_state(), "r")
    c = sqlite3.connect(str(eng.db_path))
    c.execute("UPDATE decisions SET confidence=NULL, use_count=NULL")
    c.commit()
    c.close()
    assert eng.get(_state()) is None
    assert eng.set(_state(), "r2") is True
    assert eng.get(_state()) == "r2"


@pytest.mark.parametrize("mult", [float("nan"), float("inf"), "1.5", None, True])
def test_bump_confidence_refuses_a_non_finite_or_non_number_multiplier(eng, mult):
    eng.set(_state(), "r")
    eng.bump_confidence(_state(), mult)
    assert _raw(eng)[0][0] == pytest.approx(1.0)


def test_bump_confidence_still_clamps_and_scales(eng):
    eng.set(_state(), "r")
    eng.bump_confidence(_state(), 0.8)
    assert _raw(eng)[0][0] == pytest.approx(0.8)
    eng.bump_confidence(_state(), 1.5)
    assert _raw(eng)[0][0] == pytest.approx(1.0)


def test_get_returns_only_text(eng):
    eng.set(_state(), "r")
    c = sqlite3.connect(str(eng.db_path))
    c.execute("UPDATE decisions SET response=?", (b"\x00\x01",))
    c.commit()
    c.close()
    assert eng.get(_state()) is None


# -- T-213 narrowed except -------------------------------------------------------

def test_bump_confidence_surfaces_a_programming_error(eng):
    def _boom():
        raise RuntimeError("a bug, not a database failure")
    eng._conn = _boom
    with pytest.raises(RuntimeError):
        eng.bump_confidence(_state(), 1.5)


def test_bump_confidence_absorbs_a_database_error(eng, caplog):
    def _boom():
        raise sqlite3.OperationalError("database is locked")
    eng._conn = _boom
    with caplog.at_level(logging.WARNING, logger="cache"):
        eng.bump_confidence(_state(), 1.5)
    assert any("CacheEngine.bump_confidence" in r.getMessage()
               for r in caplog.records)


def test_bump_confidence_ignores_an_int_past_float_range(eng):
    eng.set(_state(), "r")
    eng.bump_confidence(_state(), 10 ** 400)
    assert _raw(eng)[0][0] == pytest.approx(1.0)


def test_get_still_answers_when_only_the_counter_bump_fails(eng, monkeypatch):
    """A row already read is served even if the use_count UPDATE then fails."""
    eng.set(_state(), "keep me")
    real_session = eng._session

    class _Conn:
        def __init__(self, c):
            self._c = c

        def execute(self, sql, *a):
            if sql.startswith("UPDATE"):
                raise sqlite3.OperationalError("database is locked")
            return self._c.execute(sql, *a)

    from contextlib import contextmanager

    @contextmanager
    def _flaky():
        with real_session() as c:
            yield _Conn(c)

    monkeypatch.setattr(eng, "_session", _flaky)
    assert eng.get(_state()) == "keep me"


# -- T-214 non-dict state -------------------------------------------------------

@pytest.mark.parametrize("bad", [None, "Jinx", ["Jinx"], 7])
def test_every_method_refuses_a_non_dict_state(eng, bad):
    assert eng.get(bad) is None
    assert eng.set(bad, "r") is False
    assert eng.flag_bad(bad) is False
    eng.bump_confidence(bad, 1.5)
    assert _raw(eng) == []


# -- T-215 set() refuses an empty / non-text response ----------------------------

@pytest.mark.parametrize("resp", [None, "", "   ", b"bytes", 5, {"a": 1}])
def test_set_refuses_an_empty_or_non_text_response(eng, resp):
    assert eng.set(_state(), resp) is False
    assert _raw(eng) == []


# -- warning rate limit -----------------------------------------------------------

def test_repeated_db_failures_warn_once_per_window(tmp_path, caplog):
    eng = CacheEngine(tmp_path / "d.db")
    eng.db_path.write_bytes(b"garbage" * 200)
    with caplog.at_level(logging.WARNING, logger="cache"):
        for _ in range(5):
            eng.get(_state())
    gets = [r for r in caplog.records
            if r.levelno >= logging.WARNING and "CacheEngine.get" in r.getMessage()]
    assert len(gets) == 1, [r.getMessage() for r in gets]
