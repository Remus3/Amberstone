"""S144-T-740: true-audit hardening of core/draft_meta_freshness.py.

The freshness block rides on the pick & ban and ban-suggestion responses. Each
test below was red against the pre-audit module:

- a padded patch passed the validator but was returned with its padding;
- a patch written in non-ASCII digits (e.g. Arabic-Indic) passed ``\\d`` and
  leaked a non-ASCII string into an "ASCII only" payload;
- a BOM-prefixed ddragon_version.json (what PowerShell 5.1 writes) read as
  "current patch unknown", so every list read stale with no patch count;
- a source stamped AHEAD of the live patch reported ``patches_behind`` -1,
  and an ``updated`` date in the future reported a negative ``age_days``;
- ``today`` given as a datetime raised TypeError ("never raises").
"""
from __future__ import annotations

import datetime as dt

import pytest

from core import draft_meta_freshness as f

_TODAY = dt.date(2026, 11, 8)
_KEYS = {"source_patch", "source_updated", "current_patch",
         "patches_behind", "age_days", "stale"}


def _fresh(doc, cur="16.22.1", today=_TODAY):
    return f.meta_freshness(doc, current_patch=cur, today=today)


# --- padded / non-canonical patch strings ----------------------------------

def test_padded_source_patch_is_returned_stripped():
    out = _fresh({"patch": " 16.10.1 \n", "updated": "2026-05-15"})
    assert out["source_patch"] == "16.10.1"
    assert out["patches_behind"] == 12


def test_padded_current_patch_is_returned_stripped():
    out = _fresh({"patch": "16.22.1"}, cur="16.22.1\n")
    assert out["current_patch"] == "16.22.1"
    assert out["stale"] is False


@pytest.mark.parametrize("patch", [
    "\u0661\u0666.\u0661\u0660",          # Arabic-Indic digits
    "\uff11\uff16.\uff11\uff10.1",        # fullwidth digits
    "16.\u0661\u0660.1",                  # mixed
])
def test_non_ascii_digit_patch_is_rejected(patch):
    out = _fresh({"patch": patch, "updated": "2026-05-15"})
    assert out["source_patch"] is None
    assert out["patches_behind"] is None
    assert out["stale"] is True
    assert ascii(out) == repr(out)


def test_non_ascii_digit_current_patch_is_rejected():
    out = _fresh({"patch": "16.22.1"}, cur="\u0661\u0666.22.1")
    assert out["current_patch"] is None
    assert out["stale"] is True


@pytest.mark.parametrize("patch", ["16.10.1\n16.10.1", "16.10.1.2", "16..1",
                                   "16.10.", ".10.1", "1600.1", "16.1000"])
def test_malformed_patch_shapes_still_rejected(patch):
    assert _fresh({"patch": patch})["source_patch"] is None


# --- the DDragon version file ------------------------------------------------

def test_bom_prefixed_version_file_is_read(tmp_path):
    p = tmp_path / "ddragon_version.json"
    p.write_bytes(b'\xef\xbb\xbf{"version": "16.22.1"}')
    assert f.current_ddragon_patch(p) == "16.22.1"


def test_padded_version_in_file_is_returned_stripped(tmp_path):
    p = tmp_path / "ddragon_version.json"
    p.write_bytes(b'{"version": " 16.22.1 "}')
    assert f.current_ddragon_patch(p) == "16.22.1"


@pytest.mark.parametrize("raw", [
    b"", b"\xff\xfe\x00", b"[]", b'{"version": 16.22}', b'{"version": null}',
    b'{"version": "\xd9\xa1\xd9\xa6.22.1"}', b"[" * 100000,
])
def test_bad_version_file_reads_none(tmp_path, raw):
    p = tmp_path / "ddragon_version.json"
    p.write_bytes(raw)
    assert f.current_ddragon_patch(p) is None


def test_live_version_file_read_when_no_override(tmp_path, monkeypatch):
    p = tmp_path / "ddragon_version.json"
    p.write_bytes(b'\xef\xbb\xbf{"version": "16.22.1"}')
    monkeypatch.setattr(f, "_DDRAGON_VERSION", p)
    out = f.meta_freshness({"patch": "16.22.1"}, today=_TODAY)
    assert out["current_patch"] == "16.22.1"
    assert out["stale"] is False


# --- a source stamped ahead of the live patch / dated in the future ----------

def test_source_ahead_of_live_patch_has_no_negative_count():
    out = _fresh({"patch": "16.23.1", "updated": "2026-11-01"})
    assert out["patches_behind"] is None
    assert out["source_patch"] == "16.23.1"
    assert out["stale"] is True


def test_future_updated_date_has_no_negative_age():
    out = _fresh({"patch": "16.22.1", "updated": "2026-11-09"})
    assert out["age_days"] is None
    assert out["source_updated"] == "2026-11-09"
    assert out["stale"] is False


def test_same_day_update_is_age_zero():
    assert _fresh({"updated": "2026-11-08"})["age_days"] == 0


def test_same_patch_different_hotfix_is_zero_behind_and_fresh():
    out = _fresh({"patch": "16.22.2"}, cur="16.22.1")
    assert out["patches_behind"] == 0
    assert out["stale"] is False


# --- the injectable clock -----------------------------------------------------

def test_datetime_today_is_accepted_as_its_date():
    out = _fresh({"updated": "2026-05-15"},
                 today=dt.datetime(2026, 11, 8, 23, 59))
    assert out["age_days"] == 177


@pytest.mark.parametrize("today", ["2026-11-08", 20261108, True, object()])
def test_non_date_today_falls_back_to_the_local_clock(today):
    out = _fresh({"updated": "2026-05-15"}, today=today)
    want = (dt.datetime.now().astimezone().date()
            - dt.date(2026, 5, 15)).days
    assert out["age_days"] in (want, want + 1)


# --- the contract holds on every shape ---------------------------------------

@pytest.mark.parametrize("doc", [
    {"patch": True, "updated": True}, {"patch": ["16.22.1"]},
    {"patch": "16.22.1", "updated": "2026-05-15\n"},
    {"updated": "\uff12\uff10\uff12\uff16-05-15"}, {"updated": 20260515},
])
def test_wrong_typed_fields_keep_the_shape(doc):
    out = _fresh(doc)
    assert set(out) == _KEYS
    assert isinstance(out["stale"], bool)
    assert ascii(out) == repr(out)
