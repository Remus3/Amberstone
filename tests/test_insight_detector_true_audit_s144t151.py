"""True-audit (s144 lane true-audit cycle 151) of
agents/agent4_coach_mentor/insight_detector.py.

The detector runs on the supervisor's analyze pass (agents/supervisor.py,
inside ``asyncio.to_thread``) and files a dashboard advisory task for every
``coaching_digest`` insight at or above the severity floor. Each defect
below had a test RED against the pre-audit module (RM-1886..RM-1892); the
remaining tests characterize the well-formed path:

- RM-1886: a non-UTF-8 or deeply nested cooldown file raised out of the
  pass (UnicodeDecodeError / RecursionError are not caught);
- RM-1887: a naive (no-offset) cooldown stamp raised TypeError (naive vs
  aware compare) out of the pass;
- RM-1888: a far-future cooldown stamp silenced that insight until that
  date;
- RM-1889: a raise later in the pass (a mode whose digest raises, or a
  failed cooldown save) lost the stamps of the advisories already filed,
  so they were re-filed on every pass, and the raise escaped the pass;
- RM-1890: a malformed insight (missing type / severity / message, a
  None or str severity, a non-str champion, a non-dict data) raised out of
  the pass, and a NaN severity cleared every floor and was FILED;
- RM-1891: a bare-string ``modes`` was iterated by character (nothing
  filed, silently) and ``modes=None`` raised TypeError; a NaN floor filed
  everything and a NaN cooldown_hours raised;
- RM-1892: the payload was not strict JSON (a non-finite float in
  ``data`` went through), a champion holding a newline reached the payload
  and the cooldown key verbatim, and an insight carrying a "key" field
  overwrote the cooldown key in the skipped list.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import agents.agent4_coach_mentor.insight_detector as det


class FakeScheduler:
    def __init__(self, fail_on: set | None = None) -> None:
        self.filed: list = []
        self.fail_on = fail_on or set()

    def file_task(self, *, op, owner_agent, priority, categories, payload,
                  user_override):
        if payload.get("insight_type") in self.fail_on:
            raise RuntimeError("scheduler down")
        t = type("T", (), {})()
        t.id = f"fake-{len(self.filed) + 1}"
        self.filed.append({"op": op, "payload": payload, "id": t.id,
                           "owner_agent": owner_agent, "priority": priority,
                           "categories": categories,
                           "user_override": user_override})
        return t


def _ins(type_="worst_hour", severity=0.8, mode="aram", message="Slump",
         data=None, **extra) -> dict:
    d = {"type": type_, "severity": severity, "mode": mode,
         "message": message,
         "data": {"hour": 3, "win_rate": 0.1, "games": 6}
         if data is None else data}
    d.update(extra)
    return d


@pytest.fixture
def cd_file(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "insight_cooldowns.json"
    monkeypatch.setattr(det, "COOLDOWN_FILE", path)
    return path


def _digest(monkeypatch, by_mode: dict) -> list:
    calls: list = []

    def fake(mode=None, since_iso=None, top_n=5):
        calls.append(mode)
        v = by_mode.get(mode, [])
        if isinstance(v, BaseException):
            raise v
        return {"mode": mode, "count": len(v), "insights": v}

    monkeypatch.setattr(det, "coaching_digest", fake)
    return calls


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# -- characterization -------------------------------------------------

def test_files_above_floor_with_expected_task_shape(cd_file, monkeypatch):
    _digest(monkeypatch, {"aram": [_ins()]})
    sched = FakeScheduler()
    out = det.detect_insights_and_file(sched, modes=("aram",))
    assert [f["key"] for f in out["filed"]] == ["worst_hour:aram:hour=3"]
    assert out["filed"][0]["task_id"] == "fake-1"
    t = sched.filed[0]
    assert t["op"] == "coaching-insight-advisory"
    assert (t["owner_agent"], t["priority"], t["categories"],
            t["user_override"]) == ("1", 65, [4], True)
    p = t["payload"]
    assert p["insight_type"] == "worst_hour" and p["severity"] == 0.8
    assert p["mode"] == "aram" and p["message"] == "Slump"
    assert p["data"] == {"hour": 3, "win_rate": 0.1, "games": 6}
    saved = json.loads(cd_file.read_text(encoding="utf-8"))
    assert list(saved) == ["worst_hour:aram:hour=3"]


def test_below_floor_and_skip_type_counted(cd_file, monkeypatch):
    _digest(monkeypatch, {"aram": [_ins(severity=0.5),
                                   _ins(type_="cold_streak", severity=1.0,
                                        champion="Ahri")]})
    sched = FakeScheduler()
    out = det.detect_insights_and_file(sched, modes=("aram",))
    assert out["filed"] == [] and sched.filed == []
    assert out["skipped_severity"] == 1 and out["skipped_type"] == 1
    assert not cd_file.exists()


def test_cooldown_blocks_refile_within_window(cd_file, monkeypatch):
    _digest(monkeypatch, {"aram": [_ins()]})
    sched = FakeScheduler()
    det.detect_insights_and_file(sched, modes=("aram",))
    out = det.detect_insights_and_file(sched, modes=("aram",))
    assert len(sched.filed) == 1
    assert [s["key"] for s in out["skipped_cooldown"]] == [
        "worst_hour:aram:hour=3"]


def test_expired_stamp_refiles(cd_file, monkeypatch):
    old = datetime.now(timezone.utc) - timedelta(hours=30)
    cd_file.write_text(json.dumps({"worst_hour:aram:hour=3": _iso(old)}),
                       encoding="utf-8")
    _digest(monkeypatch, {"aram": [_ins()]})
    sched = FakeScheduler()
    out = det.detect_insights_and_file(sched, modes=("aram",))
    assert len(out["filed"]) == 1


def test_scope_fields_make_distinct_keys(cd_file, monkeypatch):
    _digest(monkeypatch, {"aram": [
        _ins(type_="worst_day", data={"weekday": 0, "name": "Mon",
                                      "win_rate": 0.1, "games": 5}),
        _ins(type_="hot_streak", severity=0.9, champion="Ahri", data={}),
        _ins(type_="bad_duration", data={"tier": "long", "win_rate": 0.1,
                                         "games": 5}),
    ]})
    out = det.detect_insights_and_file(FakeScheduler(), modes=("aram",))
    assert sorted(f["key"] for f in out["filed"]) == [
        "bad_duration:aram:tier=long", "hot_streak:aram:Ahri",
        "worst_day:aram:weekday=0"]


def test_scheduler_error_is_logged_not_raised(cd_file, monkeypatch):
    _digest(monkeypatch, {"aram": [_ins()]})
    out = det.detect_insights_and_file(FakeScheduler({"worst_hour"}),
                                       modes=("aram",))
    assert out["filed"] == []
    assert not cd_file.exists()


# -- RM-1886: unreadable cooldown file ---------------------------------

def test_non_utf8_cooldown_file_is_empty_not_raise(cd_file, monkeypatch):
    cd_file.write_bytes(b"\xff\xfe{\x00\x81")
    _digest(monkeypatch, {"aram": [_ins()]})
    out = det.detect_insights_and_file(FakeScheduler(), modes=("aram",))
    assert len(out["filed"]) == 1


def test_deeply_nested_cooldown_file_is_empty_not_raise(cd_file,
                                                       monkeypatch):
    cd_file.write_text("[" * 200000 + "]" * 200000, encoding="utf-8")
    _digest(monkeypatch, {"aram": [_ins()]})
    out = det.detect_insights_and_file(FakeScheduler(), modes=("aram",))
    assert len(out["filed"]) == 1


def test_non_str_stamp_entry_is_dropped(cd_file, monkeypatch):
    cd_file.write_text(json.dumps({"worst_hour:aram:hour=3": 12345,
                                   "x": None}), encoding="utf-8")
    assert det._load_cooldowns() == {}


# -- RM-1887: naive stamp ---------------------------------------------

def test_naive_stamp_read_as_utc_and_still_cools_down(cd_file, monkeypatch):
    naive = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        hours=1)
    cd_file.write_text(json.dumps({"worst_hour:aram:hour=3": _iso(naive)}),
                       encoding="utf-8")
    _digest(monkeypatch, {"aram": [_ins()]})
    sched = FakeScheduler()
    out = det.detect_insights_and_file(sched, modes=("aram",))
    assert sched.filed == []
    assert len(out["skipped_cooldown"]) == 1


# -- RM-1888: far-future stamp ----------------------------------------

def test_far_future_stamp_does_not_silence(cd_file, monkeypatch):
    future = datetime.now(timezone.utc) + timedelta(days=3650)
    cd_file.write_text(json.dumps({"worst_hour:aram:hour=3": _iso(future)}),
                       encoding="utf-8")
    _digest(monkeypatch, {"aram": [_ins()]})
    out = det.detect_insights_and_file(FakeScheduler(), modes=("aram",))
    assert len(out["filed"]) == 1


def test_far_future_stamp_ignored_by_in_cooldown_helper():
    now = datetime.now(timezone.utc)
    cds = {"k": _iso(now + timedelta(days=30)),
           "s": _iso(now + timedelta(minutes=2))}
    assert det._in_cooldown(cds, "k", now, 24) is False
    # Small clock skew is still honoured.
    assert det._in_cooldown(cds, "s", now, 24) is True


# -- RM-1889: part-way failure keeps the stamps ------------------------

def test_raising_mode_is_skipped_and_others_still_file(cd_file,
                                                      monkeypatch):
    _digest(monkeypatch, {"aram": [_ins()],
                          "arena": OSError("db locked"),
                          "sr_ranked": [_ins(mode="sr_ranked")]})
    sched = FakeScheduler()
    out = det.detect_insights_and_file(
        sched, modes=("aram", "arena", "sr_ranked"))
    assert sorted(f["key"] for f in out["filed"]) == [
        "worst_hour:aram:hour=3", "worst_hour:sr_ranked:hour=3"]


def test_unexpected_raise_still_persists_filed_stamps(cd_file, monkeypatch):
    _digest(monkeypatch, {"aram": [_ins()],
                          "arena": MemoryError("boom")})
    sched = FakeScheduler()
    with pytest.raises(MemoryError):
        det.detect_insights_and_file(sched, modes=("aram", "arena"))
    assert len(sched.filed) == 1
    saved = json.loads(cd_file.read_text(encoding="utf-8"))
    assert "worst_hour:aram:hour=3" in saved
    # The next pass does not re-file the advisory already filed.
    _digest(monkeypatch, {"aram": [_ins()]})
    det.detect_insights_and_file(sched, modes=("aram",))
    assert len(sched.filed) == 1


def test_failed_cooldown_save_does_not_raise(cd_file, monkeypatch):
    _digest(monkeypatch, {"aram": [_ins()]})

    def boom(_c):
        raise PermissionError("locked")

    monkeypatch.setattr(det, "_save_cooldowns", boom)
    out = det.detect_insights_and_file(FakeScheduler(), modes=("aram",))
    assert len(out["filed"]) == 1


# -- RM-1890: malformed insights ----------------------------------------

@pytest.mark.parametrize("bad", [
    {"severity": 0.9, "message": "m", "mode": "aram"},          # no type
    {"type": "worst_hour", "message": "m", "mode": "aram"},     # no sev
    {"type": "worst_hour", "severity": None, "message": "m"},
    {"type": "worst_hour", "severity": "0.9", "message": "m"},
    {"type": "worst_hour", "severity": True, "message": "m"},
    {"type": "worst_hour", "severity": float("nan"), "message": "m"},
    {"type": "worst_hour", "severity": float("inf"), "message": "m"},
    {"type": "worst_hour", "severity": 0.9},                    # no msg
    {"type": "worst_hour", "severity": 0.9, "message": 5},
    {"type": 7, "severity": 0.9, "message": "m"},
    {"type": "hot_streak", "severity": 0.9, "message": "m",
     "champion": ["Ahri"]},
    {"type": "worst_hour", "severity": 0.9, "message": "m",
     "data": "hour=3"},
    {"type": "worst_hour", "severity": 0.9, "message": "m", "mode": 3},
    "not a dict",
    None,
])
def test_malformed_insight_counted_never_filed(cd_file, monkeypatch, bad):
    _digest(monkeypatch, {"aram": [bad, _ins()]})
    sched = FakeScheduler()
    out = det.detect_insights_and_file(sched, modes=("aram",))
    assert out["invalid_insights"] == 1
    assert [f["key"] for f in out["filed"]] == ["worst_hour:aram:hour=3"]
    assert len(sched.filed) == 1


def test_non_list_insights_is_no_insight(cd_file, monkeypatch):
    monkeypatch.setattr(det, "coaching_digest",
                        lambda mode=None, since_iso=None, top_n=5:
                        {"insights": "junk"})
    out = det.detect_insights_and_file(FakeScheduler(), modes=("aram",))
    assert out["filed"] == [] and out["invalid_insights"] == 0


# -- RM-1891: argument validation ---------------------------------------

def test_bare_string_modes_is_one_mode(cd_file, monkeypatch):
    calls = _digest(monkeypatch, {"aram": [_ins()]})
    out = det.detect_insights_and_file(FakeScheduler(), modes="aram")
    assert calls == ["aram"]
    assert len(out["filed"]) == 1


def test_none_modes_means_every_supported_mode(cd_file, monkeypatch):
    calls = _digest(monkeypatch, {})
    det.detect_insights_and_file(FakeScheduler(), modes=None)
    assert tuple(calls) == tuple(det.SUPPORTED_MODES)


def test_non_str_mode_elements_skipped(cd_file, monkeypatch):
    calls = _digest(monkeypatch, {"aram": [_ins()]})
    det.detect_insights_and_file(FakeScheduler(), modes=[None, 5, "aram"])
    assert calls == ["aram"]


def test_nan_floor_uses_default_floor(cd_file, monkeypatch):
    _digest(monkeypatch, {"aram": [_ins(severity=0.1)]})
    sched = FakeScheduler()
    out = det.detect_insights_and_file(sched, modes=("aram",),
                                       severity_floor=float("nan"))
    assert sched.filed == [] and out["skipped_severity"] == 1


@pytest.mark.parametrize("hours", [float("nan"), float("inf"), -5, "24"])
def test_junk_cooldown_hours_uses_default(cd_file, monkeypatch, hours):
    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    cd_file.write_text(json.dumps({"worst_hour:aram:hour=3": _iso(recent)}),
                       encoding="utf-8")
    _digest(monkeypatch, {"aram": [_ins()]})
    sched = FakeScheduler()
    det.detect_insights_and_file(sched, modes=("aram",),
                                 cooldown_hours=hours)
    assert sched.filed == []


# -- RM-1892: payload and key hygiene -----------------------------------

def test_payload_is_strict_json(cd_file, monkeypatch):
    _digest(monkeypatch, {"aram": [_ins(data={"hour": 3,
                                              "kda": float("inf"),
                                              "x": float("nan"),
                                              "win_rate": 0.1})]})
    sched = FakeScheduler()
    det.detect_insights_and_file(sched, modes=("aram",))
    p = sched.filed[0]["payload"]
    json.dumps(p, allow_nan=False)
    assert p["data"]["kda"] is None and p["data"]["x"] is None


def test_champion_and_message_are_one_printable_line(cd_file, monkeypatch):
    _digest(monkeypatch, {"aram": [_ins(type_="hot_streak", severity=0.9,
                                        champion="Ah\nri\x00" + "Z" * 200,
                                        message="line1\nline2\x07",
                                        data={})]})
    sched = FakeScheduler()
    out = det.detect_insights_and_file(sched, modes=("aram",))
    key = out["filed"][0]["key"]
    assert "\n" not in key and "\x00" not in key
    p = sched.filed[0]["payload"]
    assert p["champion"].startswith("Ah ri") and len(p["champion"]) <= 64
    assert "\n" not in p["message"] and "\x07" not in p["message"]


def test_skipped_entry_key_is_the_cooldown_key(cd_file, monkeypatch):
    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    cd_file.write_text(json.dumps({"worst_hour:aram:hour=3": _iso(recent)}),
                       encoding="utf-8")
    _digest(monkeypatch, {"aram": [_ins(key="forged")]})
    out = det.detect_insights_and_file(FakeScheduler(), modes=("aram",))
    assert out["skipped_cooldown"][0]["key"] == "worst_hour:aram:hour=3"


def test_load_drops_far_future_entry(cd_file):
    now = datetime.now(timezone.utc)
    cd_file.write_text(json.dumps({
        "far": _iso(now + timedelta(days=30)),
        "near": _iso(now - timedelta(hours=1)),
    }), encoding="utf-8")
    assert list(det._load_cooldowns()) == ["near"]


def test_scope_value_with_newline_is_one_line_key(cd_file, monkeypatch):
    _digest(monkeypatch, {"aram": [_ins(type_="bad_duration",
                                        data={"tier": "lo\nng\r",
                                              "win_rate": 0.1,
                                              "games": 5})]})
    out = det.detect_insights_and_file(FakeScheduler(), modes=("aram",))
    key = out["filed"][0]["key"]
    assert "\n" not in key and "\r" not in key
    assert key.startswith("bad_duration:aram:tier=lo ng")
