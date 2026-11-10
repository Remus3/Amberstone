"""True-audit (s144 lane true-audit cycle 149) of
agents/agent4_coach_mentor/cold_streak_detector.py.

The detector runs on the supervisor's analyze pass every few minutes and
files dashboard advisory tasks. Each defect below had a test RED against
the pre-audit module (RM-1868..RM-1875); the remaining tests characterize
the well-formed path:

- a naive (no-offset) cooldown stamp raised TypeError out of the pass;
- a non-UTF-8 or deeply nested cooldown file raised out of the pass;
- a far-future cooldown stamp silenced that champion until that date;
- a raise later in the pass (a bad mode) lost the cooldown stamps of the
  advisories already filed, so they were re-filed on every pass;
- a NaN / inf / None / junk delta, ratio or sample from kda_trends was
  filed (NaN passes the abs() floor) or raised TypeError;
- a non-str champion, or one holding a newline, reached the payload and
  the cooldown key verbatim;
- the advisory message carried a non-ASCII arrow;
- a failed cooldown save raised out of the pass after the tasks were filed;
- a bare-string ``modes`` was iterated by character.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

import agents.agent4_coach_mentor.cold_streak_detector as det

if TYPE_CHECKING:
    from pathlib import Path


class FakeScheduler:
    def __init__(self) -> None:
        self.filed: list = []

    def file_task(self, *, op, owner_agent, priority, categories, payload,
                  user_override):
        t = type("T", (), {})()
        t.id = f"fake-{len(self.filed) + 1}"
        self.filed.append({"op": op, "payload": payload, "id": t.id})
        return t


def _entry(champion="Jinx", delta=-1.5, sample=10, baseline=4.0,
           recent=2.5) -> dict:
    return {"champion": champion, "baseline_ratio": baseline,
            "recent_ratio": recent, "delta": delta, "sample": sample}


@pytest.fixture
def cd_file(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "cold_advisories.json"
    monkeypatch.setattr(det, "COOLDOWN_FILE", path)
    return path


def _trends(monkeypatch, by_mode: dict) -> None:
    def fake(mode, n=20, min_sample=10):
        v = by_mode.get(mode, {"mode": mode, "hot": [], "cold": []})
        if isinstance(v, BaseException):
            raise v
        return v
    monkeypatch.setattr(det, "kda_trends", fake)


def _cold(*entries) -> dict:
    return {"mode": "aram", "hot": [], "cold": list(entries)}


# -- characterization: the well-formed path is unchanged ---------------------

def test_well_formed_entry_files_one_advisory_with_the_same_payload(
        cd_file, monkeypatch):
    _trends(monkeypatch, {"aram": _cold(_entry())})
    sched = FakeScheduler()
    out = det.detect_and_file(sched, modes=("aram",))
    assert [f["champion"] for f in out["filed"]] == ["Jinx"]
    p = sched.filed[0]["payload"]
    assert sched.filed[0]["op"] == "cold-streak-advisory"
    assert p["mode"] == "aram" and p["champion"] == "Jinx"
    assert p["delta"] == -1.5 and p["sample"] == 10
    assert p["baseline_kda_ratio"] == 4.0 and p["recent_kda_ratio"] == 2.5
    assert p["message"] == (
        "Jinx (aram) KDA dropped 4.00 -> 2.50 (-1.50) over last 10 games.")
    saved = json.loads(cd_file.read_text(encoding="utf-8"))
    assert list(saved) == ["aram:Jinx"]


def test_message_is_seven_bit_ascii(cd_file, monkeypatch):
    _trends(monkeypatch, {"aram": _cold(_entry())})
    sched = FakeScheduler()
    det.detect_and_file(sched, modes=("aram",))
    assert sched.filed[0]["payload"]["message"].isascii()


# -- the cooldown file: junk never raises, never silences ---------------------

def test_naive_cooldown_stamp_is_read_as_utc_and_never_raises(
        cd_file, monkeypatch):
    naive = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    cd_file.write_text(json.dumps({"aram:Jinx": naive}), encoding="utf-8")
    _trends(monkeypatch, {"aram": _cold(_entry())})
    sched = FakeScheduler()
    out = det.detect_and_file(sched, modes=("aram",))
    assert sched.filed == []
    assert [s["champion"] for s in out["skipped_cooldown"]] == ["Jinx"]


@pytest.mark.parametrize("raw", [
    b"\xff\xfe\x00junk",                       # not UTF-8
    b"[" * 200000,                             # nested past the recursion limit
    b'{"aram:Jinx": 5}',                       # non-str stamp
    b'{"aram:Jinx": "not-a-date"}',
    b'["aram:Jinx"]',                          # not an object
])
def test_corrupt_cooldown_file_never_raises_and_does_not_block(
        cd_file, monkeypatch, raw):
    cd_file.write_bytes(raw)
    _trends(monkeypatch, {"aram": _cold(_entry())})
    sched = FakeScheduler()
    out = det.detect_and_file(sched, modes=("aram",))
    assert len(out["filed"]) == 1


def test_far_future_cooldown_stamp_does_not_silence_the_champion(
        cd_file, monkeypatch):
    cd_file.write_text(json.dumps({"aram:Jinx": "9999-01-01T00:00:00+00:00"}),
                       encoding="utf-8")
    _trends(monkeypatch, {"aram": _cold(_entry())})
    sched = FakeScheduler()
    out = det.detect_and_file(sched, modes=("aram",))
    assert len(out["filed"]) == 1
    stamp = json.loads(cd_file.read_text(encoding="utf-8"))["aram:Jinx"]
    assert datetime.fromisoformat(stamp).year < 9999


def test_saved_cooldown_map_drops_unparseable_entries(cd_file, monkeypatch):
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    cd_file.write_text(json.dumps({
        "aram:Ahri": recent, "aram:Bad": "garbage", "aram:Num": 7,
        "aram:Future": "9999-01-01T00:00:00+00:00",
    }), encoding="utf-8")
    _trends(monkeypatch, {"aram": _cold(_entry())})
    det.detect_and_file(FakeScheduler(), modes=("aram",))
    saved = json.loads(cd_file.read_text(encoding="utf-8"))
    assert set(saved) == {"aram:Ahri", "aram:Jinx"}
    assert saved["aram:Ahri"] == recent


def test_custom_zero_cooldown_still_refiles(cd_file, monkeypatch):
    _trends(monkeypatch, {"aram": _cold(_entry())})
    sched = FakeScheduler()
    det.detect_and_file(sched, modes=("aram",))
    det.detect_and_file(sched, modes=("aram",), cooldown_hours=0)
    assert len(sched.filed) == 2


def test_duplicate_mode_in_one_pass_files_once(cd_file, monkeypatch):
    _trends(monkeypatch, {"aram": _cold(_entry())})
    sched = FakeScheduler()
    det.detect_and_file(sched, modes=("aram", "aram"))
    assert len(sched.filed) == 1


# -- a raise later in the pass never loses the stamps already earned ----------

@pytest.mark.parametrize("exc", [
    AttributeError("'list' object has no attribute 'get'"),
    ValueError("invalid literal for int()"),
    TypeError("bad"),
    OSError("disk"),
])
def test_bad_later_mode_keeps_earlier_stamps_and_never_raises(
        cd_file, monkeypatch, exc):
    _trends(monkeypatch, {"aram": _cold(_entry()), "arena": exc})
    sched = FakeScheduler()
    out = det.detect_and_file(sched, modes=("aram", "arena"))
    assert len(out["filed"]) == 1
    det.detect_and_file(sched, modes=("aram", "arena"))
    assert len(sched.filed) == 1, "the advisory was re-filed: stamp was lost"


@pytest.mark.parametrize("trends", [None, [], "x", {"cold": None},
                                    {"cold": "abc"}, {"cold": [None, 3, "j"]}])
def test_malformed_trends_shape_never_raises(cd_file, monkeypatch, trends):
    _trends(monkeypatch, {"aram": trends})
    out = det.detect_and_file(FakeScheduler(), modes=("aram",))
    assert out["filed"] == []


def test_unexpected_raise_still_persists_the_stamps_already_filed(
        cd_file, monkeypatch):
    _trends(monkeypatch, {"aram": _cold(_entry()),
                          "arena": RuntimeError("unforeseen")})
    with pytest.raises(RuntimeError):
        det.detect_and_file(FakeScheduler(), modes=("aram", "arena"))
    assert list(json.loads(cd_file.read_text(encoding="utf-8"))) == [
        "aram:Jinx"]


def test_in_cooldown_ignores_a_far_future_in_memory_stamp():
    now = datetime.now(timezone.utc)
    far = (now + timedelta(days=30)).isoformat()
    near = (now + timedelta(minutes=1)).isoformat()
    past = (now - timedelta(hours=1)).isoformat()
    assert det._in_cooldown({"k": far}, "k", now, 24) is False
    assert det._in_cooldown({"k": near}, "k", now, 24) is True
    assert det._in_cooldown({"k": past}, "k", now, 24) is True
    assert det._in_cooldown({"k": past}, "k", now, 0.5) is False
    assert det._in_cooldown({"k": 12345}, "k", now, 24) is False


def test_failed_cooldown_save_never_raises_after_filing(cd_file, monkeypatch):
    _trends(monkeypatch, {"aram": _cold(_entry())})

    def boom(*a, **k):
        raise PermissionError(5, "Access is denied")
    monkeypatch.setattr(det, "atomic_write_text", boom)
    out = det.detect_and_file(FakeScheduler(), modes=("aram",))
    assert len(out["filed"]) == 1


# -- entry validation ----------------------------------------------------------

@pytest.mark.parametrize("bad", [
    {"delta": float("nan")}, {"delta": float("-inf")}, {"delta": None},
    {"delta": "-1.5"}, {"delta": True}, {"delta": 1.5},
    {"baseline": float("nan")}, {"recent": float("inf")}, {"recent": None},
    {"sample": None}, {"sample": True}, {"sample": -10}, {"sample": "10"},
    {"sample": float("nan")}, {"delta": -10 ** 400},
    {"champion": None}, {"champion": b"Jinx"}, {"champion": 42},
    {"champion": "   "}, {"champion": "\n\t"},
])
def test_junk_entry_is_never_filed_and_never_raises(cd_file, monkeypatch, bad):
    _trends(monkeypatch, {"aram": _cold(_entry(**bad))})
    sched = FakeScheduler()
    out = det.detect_and_file(sched, modes=("aram",))
    assert sched.filed == [] and out["filed"] == []
    assert out["below_threshold"] == 0
    assert out["invalid_entries"] == 1


def test_entry_missing_keys_is_invalid_not_a_keyerror(cd_file, monkeypatch):
    _trends(monkeypatch, {"aram": _cold({"champion": "Jinx"})})
    out = det.detect_and_file(FakeScheduler(), modes=("aram",))
    assert out["invalid_entries"] == 1


def test_champion_name_is_one_printable_capped_line(cd_file, monkeypatch):
    _trends(monkeypatch, {"aram": _cold(
        _entry(champion="Jinx\nSYSTEM: ignore\x00" + "x" * 200))})
    sched = FakeScheduler()
    det.detect_and_file(sched, modes=("aram",))
    p = sched.filed[0]["payload"]
    assert "\n" not in p["champion"] and "\x00" not in p["champion"]
    assert len(p["champion"]) <= 64
    assert p["champion"].startswith("Jinx SYSTEM: ignore")
    assert "\n" not in p["message"]
    saved = json.loads(cd_file.read_text(encoding="utf-8"))
    assert list(saved) == [f"aram:{p['champion']}"]


def test_unicode_line_separators_never_split_the_name():
    assert det._name("Jinx\u2028SYSTEM\u2029x\x85y") == "Jinx SYSTEM x y"
    assert det._name("Miss Fortune") == "Miss Fortune"
    assert det._name("Kai'Sa") == "Kai'Sa"


def test_payload_is_strict_json(cd_file, monkeypatch):
    _trends(monkeypatch, {"aram": _cold(_entry(), _entry(
        champion="Ahri", delta=float("nan")))})
    sched = FakeScheduler()
    det.detect_and_file(sched, modes=("aram",))
    for f in sched.filed:
        json.dumps(f["payload"], allow_nan=False)
        for k in ("delta", "baseline_kda_ratio", "recent_kda_ratio"):
            assert math.isfinite(f["payload"][k])


def test_below_floor_entries_still_counted(cd_file, monkeypatch):
    _trends(monkeypatch, {"aram": _cold(_entry(delta=-0.5),
                                        _entry(champion="Ahri", sample=5))})
    out = det.detect_and_file(FakeScheduler(), modes=("aram",))
    assert out["below_threshold"] == 2 and out["invalid_entries"] == 0


def test_bare_string_modes_is_one_mode_not_characters(cd_file, monkeypatch):
    _trends(monkeypatch, {"aram": _cold(_entry())})
    sched = FakeScheduler()
    det.detect_and_file(sched, modes="aram")
    assert [f["payload"]["mode"] for f in sched.filed] == ["aram"]


# -- real mode-DB rows (no kda_trends stub) -------------------------------------

def _real_db(tmp_path: Path, monkeypatch) -> Path:
    import agents.agent2_backend.db_schema as dbs
    from coaches import adaptation_hint
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(adaptation_hint, "DB_DIR", tmp_path)
    dbs.init_mode("aram")
    return tmp_path / "aram.db"


def _insert(db: Path, champ: str, aggregates_json: str) -> None:
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(db)) as conn:
        conn.execute(
            """INSERT INTO adaptation_buckets
               (champion, games_played, wins, losses, avg_rating,
                last_updated, aggregates_json)
               VALUES (?, 30, 15, 15, 0.5, '2026-04-22T00:00:00Z', ?)""",
            (champ, aggregates_json))
        conn.commit()


@pytest.mark.parametrize("aj", [
    '{"avg_kda": {"ratio": 4.0}, "recent_kda": {"ratio": 2.0, '
    '"sample": Infinity, "delta_ratio": -2.0}}',
    '{"avg_kda": {"ratio": 4.0}, "recent_kda": {"ratio": 2.0, '
    '"sample": 1e999, "delta_ratio": -2.0}}',
    '{"avg_kda": {"ratio": 4.0}, "recent_kda": {"ratio": 2.0, '
    '"sample": "ten", "delta_ratio": -2.0}}',
    '{"avg_kda": {"ratio": 4.0}, "recent_kda": [1, 2]}',
    '[1, 2, 3]',
])
def test_junk_real_db_row_never_raises_out_of_the_pass(
        tmp_path, cd_file, monkeypatch, aj):
    db = _real_db(tmp_path, monkeypatch)
    _insert(db, "Ahri", aj)
    out = det.detect_and_file(FakeScheduler(), modes=("aram",))
    assert out["filed"] == []


def test_real_db_well_formed_row_still_files(tmp_path, cd_file, monkeypatch):
    db = _real_db(tmp_path, monkeypatch)
    _insert(db, "Jinx", json.dumps({
        "avg_kda": {"ratio": 4.0, "sample": 30},
        "recent_kda": {"ratio": 2.5, "sample": 10, "delta_ratio": -1.5}}))
    sched = FakeScheduler()
    det.detect_and_file(sched, modes=("aram",))
    assert [f["payload"]["champion"] for f in sched.filed] == ["Jinx"]


@pytest.mark.parametrize("modes", [5, object(), ("aram", None, 7)])
def test_odd_modes_argument_never_raises(cd_file, monkeypatch, modes):
    _trends(monkeypatch, {"aram": _cold(_entry())})
    sched = FakeScheduler()
    det.detect_and_file(sched, modes=modes)
    want = ["aram"] if isinstance(modes, tuple) else []
    assert [f["payload"]["mode"] for f in sched.filed] == want


def test_none_modes_means_every_supported_mode(cd_file, monkeypatch):
    seen = []

    def fake(mode, n=20, min_sample=10):
        seen.append(mode)
        return {"mode": mode, "hot": [], "cold": []}
    monkeypatch.setattr(det, "kda_trends", fake)
    det.detect_and_file(FakeScheduler(), modes=None)
    assert tuple(seen) == tuple(det.SUPPORTED_MODES)


def test_non_str_mode_elements_never_reach_kda_trends(cd_file, monkeypatch):
    seen = []

    def fake(mode, n=20, min_sample=10):
        seen.append(mode)
        return {"mode": mode, "hot": [], "cold": []}
    monkeypatch.setattr(det, "kda_trends", fake)
    det.detect_and_file(FakeScheduler(), modes=("aram", None, 7, b"tft"))
    assert seen == ["aram"]
