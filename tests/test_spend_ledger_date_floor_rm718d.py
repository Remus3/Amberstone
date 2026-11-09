"""RM-718 (d): the spend writer cannot emit an epoch-dated day ledger, and
data/spend/ has a retention class for one that already exists.

Root cause (measured 2026-08-06, see tests/test_spend_dir_hermeticity.py):
a test patched `time.time` to 1_000_000 while the REAL tracker was bound to
the live `data/spend/`, and `date.today()` reads the clock through
`time.time`, so `core/cost_tracker.py` minted `data/spend/1970-01-12.json`.
The test-isolation half was fixed then (an autouse conftest fixture
re-points the tracker). The WRITER half was not: `CostTracker._spend_path`
still names the file after whatever `date.today()` returns, so any clock
reading 1970 (a patched clock, a CMOS reset) still mints a phantom day.

Pinned here:
  * a day before `cost_tracker.SPEND_LEDGER_MIN_DATE` writes NO file and
    reads as an empty ledger; the call's own cost is still returned;
  * the floor day itself and a real day write normally (positive control,
    so a writer that never writes cannot pass);
  * the measured trigger (a patched `time.time`) is reproduced, with a
    precondition that it really moves `date.today()`;
  * `core.data_retention` classifies a pre-floor or non-calendar day ledger
    under a `spend/` dir as MISDATED_SPEND (recommend-operator, never
    auto-eligible), and leaves real day ledgers, the per-match sidecars and
    a date-named file outside `spend/` as RETAIN.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core.cost_tracker as ct  # noqa: E402
import core.data_retention as dr  # noqa: E402

_MODEL = "claude-haiku-4-5-20251001"


class _FixedDate(date):
    """A `date` whose today() is pinned; everything else is the real date."""

    pinned = date(2026, 11, 8)

    @classmethod
    def today(cls):  # noqa: D401 - mirrors date.today
        return cls.pinned


def _pin_today(monkeypatch, day: date) -> None:
    pinned = type("_Pinned", (_FixedDate,), {"pinned": day})
    monkeypatch.setattr(ct, "date", pinned)


def _files(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir())


# -- the writer ----------------------------------------------------------


def test_floor_constant_is_a_date_and_after_the_epoch():
    assert isinstance(ct.SPEND_LEDGER_MIN_DATE, date)
    assert date(1970, 1, 12) < ct.SPEND_LEDGER_MIN_DATE
    # Every real ledger on the live box is from 2026; the floor must sit
    # at or below the first real day so no genuine day is ever refused.
    assert date(2026, 4, 28) >= ct.SPEND_LEDGER_MIN_DATE


def test_an_epoch_day_writes_no_ledger(tmp_path, monkeypatch):
    _pin_today(monkeypatch, date(1970, 1, 12))
    tr = ct.CostTracker(spend_dir=tmp_path, config_provider=dict)
    out = tr.record_call(model=_MODEL, input_tokens=1000, output_tokens=500)

    assert _files(tmp_path) == []
    # The call's own cost is still reported to the caller.
    assert out["usd"] > 0
    assert out["total_usd"] == 0.0


def test_an_epoch_day_reads_as_an_empty_ledger(tmp_path, monkeypatch):
    _pin_today(monkeypatch, date(1970, 1, 12))
    tr = ct.CostTracker(spend_dir=tmp_path, config_provider=dict)
    tr.record_call(model=_MODEL, input_tokens=1000)
    spend = tr.daily_spend()

    assert spend["total_usd"] == 0.0
    assert spend["calls"] == 0
    assert _files(tmp_path) == []


def test_the_day_before_the_floor_is_refused(tmp_path, monkeypatch):
    floor = ct.SPEND_LEDGER_MIN_DATE
    _pin_today(monkeypatch, date.fromordinal(floor.toordinal() - 1))
    ct.CostTracker(spend_dir=tmp_path, config_provider=dict).record_call(
        model=_MODEL, input_tokens=10)
    assert _files(tmp_path) == []


def test_the_floor_day_itself_is_written(tmp_path, monkeypatch):
    floor = ct.SPEND_LEDGER_MIN_DATE
    _pin_today(monkeypatch, floor)
    ct.CostTracker(spend_dir=tmp_path, config_provider=dict).record_call(
        model=_MODEL, input_tokens=10)
    assert _files(tmp_path) == [floor.isoformat() + ".json"]


def test_a_real_day_is_written_and_accumulates(tmp_path, monkeypatch):
    _pin_today(monkeypatch, date(2026, 11, 8))
    tr = ct.CostTracker(spend_dir=tmp_path, config_provider=dict)
    tr.record_call(model=_MODEL, input_tokens=1000, purpose="aram_coach")
    out = tr.record_call(model=_MODEL, input_tokens=1000, purpose="aram_coach")

    assert _files(tmp_path) == ["2026-11-08.json"]
    doc = json.loads((tmp_path / "2026-11-08.json").read_text("utf-8"))
    assert doc["date"] == "2026-11-08"
    assert doc["calls"] == 2
    assert doc["total_usd"] == out["total_usd"] > 0
    assert tr.daily_spend()["calls"] == 2


def test_a_refused_day_logs_a_warning_once(tmp_path, monkeypatch, caplog):
    _pin_today(monkeypatch, date(1970, 1, 12))
    monkeypatch.setattr(ct, "_misdated_warned", False)
    tr = ct.CostTracker(spend_dir=tmp_path, config_provider=dict)
    with caplog.at_level(logging.WARNING, logger="rc.cost_tracker"):
        tr.record_call(model=_MODEL, input_tokens=10)
        tr.record_call(model=_MODEL, input_tokens=10)
    hits = [r for r in caplog.records if "1970-01-12" in r.getMessage()]
    assert len(hits) == 1, [r.getMessage() for r in caplog.records]


def test_the_measured_trigger_a_patched_time_time_mints_nothing(
        tmp_path, monkeypatch):
    """The 2026-08-06 fingerprint: time.time patched to 1_000_000."""
    monkeypatch.setattr(time, "time", lambda: 1_000_000.0)
    # Precondition: on this interpreter date.today() really reads the
    # patched clock. If it ever stops doing so, this test no longer
    # reproduces the incident and must be re-designed, not skipped.
    assert date.today() == date(1970, 1, 12)
    ct.CostTracker(spend_dir=tmp_path, config_provider=dict).record_call(
        model=_MODEL, input_tokens=10, output_tokens=20)
    assert _files(tmp_path) == []


# -- the retention class -------------------------------------------------


def _write(p: Path, body: str = "{}") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def _classes(root: Path) -> dict[str, str]:
    return {
        c.path.relative_to(root).as_posix(): c.klass
        for c in dr.scan(root, tracked=frozenset())
    }


def test_a_pre_floor_spend_ledger_is_misdated(tmp_path):
    _write(tmp_path / "spend" / "1970-01-12.json")
    assert _classes(tmp_path)["spend/1970-01-12.json"] == dr.CLASS_MISDATED_SPEND


def test_a_non_calendar_spend_ledger_name_is_misdated(tmp_path):
    _write(tmp_path / "spend" / "2026-13-40.json")
    assert _classes(tmp_path)["spend/2026-13-40.json"] == dr.CLASS_MISDATED_SPEND


@pytest.mark.parametrize("rel", [
    "spend/2026-05-01.json",          # a real day ledger
    "spend/_match_open.json",         # per-match sidecar
    "spend/recent_matches.json",      # per-match sidecar
    "elsewhere/1970-01-12.json",      # date-named but not under spend/
    "spend/1970-01-12.json.tmp",      # not a .json day ledger
])
def test_real_ledgers_sidecars_and_other_dirs_stay_retain(tmp_path, rel):
    _write(tmp_path / rel)
    assert _classes(tmp_path)[rel] == dr.CLASS_RETAIN


def test_the_floor_day_ledger_is_retain(tmp_path):
    name = ct.SPEND_LEDGER_MIN_DATE.isoformat() + ".json"
    _write(tmp_path / "spend" / name)
    assert _classes(tmp_path)["spend/" + name] == dr.CLASS_RETAIN


def test_misdated_spend_is_an_operator_call_never_automatic(tmp_path):
    p = _write(tmp_path / "spend" / "1970-01-12.json")
    rplan = dr.plan(tmp_path, tracked=frozenset())

    assert rplan.verdicts[dr.CLASS_MISDATED_SPEND] == dr.VERDICT_RECOMMEND_OPERATOR
    assert rplan.counts_by_class[dr.CLASS_MISDATED_SPEND] == 1
    [cand] = [c for c in rplan.candidates if c.klass == dr.CLASS_MISDATED_SPEND]
    assert cand.eligible is True
    assert "floor" in cand.reason
    # apply() refuses a non-auto-eligible class even with the token.
    res = dr.apply(rplan, confirm=dr.CONFIRM_TOKEN)
    assert p.exists()
    assert res["deleted"] == 0
    assert dr.CLASS_MISDATED_SPEND in res["refused_classes"]


def test_the_report_names_the_misdated_class(tmp_path):
    _write(tmp_path / "spend" / "1970-01-12.json")
    text = dr.render_report(dr.plan(tmp_path, tracked=frozenset()))
    assert dr.CLASS_MISDATED_SPEND in text
    assert text.isascii()
