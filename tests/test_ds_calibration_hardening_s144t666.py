"""S144-T-666 (s144 true-audit): core/ds_calibration.py hardening.

``core/ds_calibration.py`` writes one row to ``data/ds_calibration.jsonl``
per coaching tick that produced DS rows (``log_ds_run``), and builds the
RM-875 re-run inputs (``enemy_stats_summary``). The audit found:

1. ``enemy_stats_summary`` claimed to record "the values actually sent", but
   it still read ``float(x or default)``: the dispatcher
   (``coach_integration/archetype_dispatch.py`` ``_stat`` / ``_shares``) was
   fixed to keep a real 0.0 damage share and to read NaN / inf / bool as
   unknown, so an all-AD enemy comp was logged as ap_share 0.5 while the DS
   request carried 0.0, and a NaN armor was logged as NaN while 0.0 was sent.
   A re-run from the row (RM-875, gated G5-05 CHECK B) would replay inputs
   the engine never saw.
2. The module docstring says logging is non-fatal, but ``owned_items=None``
   or a non-iterable raised ``TypeError`` out of ``log_ds_run`` (the record
   is built before the ``try``), a bare-str ``augments`` was stored letter
   by letter, and a value ``json.dumps`` cannot encode raised ``TypeError``
   (only ``OSError`` was caught).
3. A non-finite float (a NaN ``delta_dps``) was written as the bare ``NaN``
   token, which is not JSON: strict readers (``jq``, ``JSON.parse``) reject
   the whole line.
4. A row appended after a torn last line (a crash or a full disk mid-write
   leaves no trailing newline) was fused onto it, so the consumer
   (``core/ds_calibration_agreement.load_records``) dropped the new, good row
   together with the torn one.
5. Every failure was swallowed with no log line at all, so a writer that
   stops (the live file's last row is months old) cannot say why.

Every write here goes to the per-test ``_LOG_PATH`` the root conftest
redirects into tmp_path; nothing reaches ``data/``.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from coach_integration import archetype_dispatch
from core import ds_calibration
from core.ds_calibration_agreement import load_records


def _path() -> Path:
    return Path(ds_calibration._LOG_PATH)


def _rows() -> list[dict]:
    path = _path()
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip()]


def _strict_loads(line: str):
    def _reject(token):
        raise ValueError(f"non-JSON constant {token!r}")
    return json.loads(line, parse_constant=_reject)


def _stats(**fields) -> SimpleNamespace:
    return SimpleNamespace(**fields)


# --- 1. enemy_stats_summary records what the dispatcher sends ---------------

def test_a_real_zero_share_is_kept_not_turned_into_half():
    summary = ds_calibration.enemy_stats_summary(
        _stats(armor=90.0, mr=40.0, max_hp=2000.0, bonus_hp=300.0,
               ad_share=1.0, ap_share=0.0))
    assert summary["ad_share"] == 1.0
    assert summary["ap_share"] == 0.0


def test_non_finite_and_bool_stats_read_as_unknown_zero():
    summary = ds_calibration.enemy_stats_summary(
        _stats(armor=float("nan"), mr=float("inf"), max_hp=True,
               bonus_hp=-float("inf"), ad_share=0.7, ap_share=0.3))
    assert summary["armor"] == 0.0
    assert summary["mr"] == 0.0
    assert summary["max_hp"] == 0.0
    assert summary["bonus_hp"] == 0.0
    assert all(math.isfinite(v) for v in summary.values())


_PARITY_CASES = [
    {},
    {"armor": 112.0, "mr": 84.0, "max_hp": 2450.0, "bonus_hp": 500.0,
     "ad_share": 0.6, "ap_share": 0.4},
    {"ad_share": 1.0, "ap_share": 0.0},
    {"ad_share": 0.0, "ap_share": 0.0},
    {"ad_share": 0.8},
    {"ap_share": 0.25},
    {"ad_share": 1.7, "ap_share": 0.2},
    {"ad_share": float("nan"), "ap_share": 0.9},
    {"armor": "junk", "mr": None, "max_hp": "2100", "bonus_hp": False},
    {"armor": -20.0},
]


@pytest.mark.parametrize("fields", _PARITY_CASES)
def test_summary_equals_the_dispatcher_request_inputs(fields):
    stats = _stats(**fields)
    ad, ap = archetype_dispatch._shares(stats)
    expected = {
        "armor": archetype_dispatch._stat(stats, "armor"),
        "mr": archetype_dispatch._stat(stats, "mr"),
        "max_hp": archetype_dispatch._stat(stats, "max_hp"),
        "bonus_hp": archetype_dispatch._stat(stats, "bonus_hp"),
        "ad_share": ad,
        "ap_share": ap,
    }
    assert ds_calibration.enemy_stats_summary(stats) == expected


def test_summary_of_none_is_still_none():
    assert ds_calibration.enemy_stats_summary(None) is None


# --- 2. log_ds_run never raises ---------------------------------------------

def test_none_owned_items_writes_an_empty_list_instead_of_raising():
    ds_calibration.log_ds_run(champion="Ahri", mode="ARAM", level=9,
                              owned_items=None, ds_picks=[], match_key="k1")
    assert _rows()[-1]["owned_items"] == []


def test_a_non_iterable_owned_items_never_raises():
    ds_calibration.log_ds_run(champion="Ahri", mode="ARAM", level=9,
                              owned_items=3089, ds_picks=[], match_key="k2")
    assert _rows()[-1]["owned_items"] == ["3089"]


def test_a_bare_str_augment_is_one_augment_not_letters():
    ds_calibration.log_ds_run(champion="Quinn", mode="ARENA", level=9,
                              owned_items=[], ds_picks=[], match_key="k3",
                              augments="ItsCritical")
    assert _rows()[-1]["augments"] == ["ItsCritical"]


def test_an_unencodable_pick_value_never_raises_and_still_writes_the_row():
    ds_calibration.log_ds_run(champion="Ahri", mode="ARAM", level=9,
                              owned_items=["3089"],
                              ds_picks=[{"item_id": "3089", "tags": {"a"}}],
                              match_key="k4")
    row = _rows()[-1]
    assert row["match_key"] == "k4"
    assert row["ds_picks"][0]["item_id"] == "3089"


# --- 3. strict JSON ---------------------------------------------------------

def test_a_nan_delta_dps_is_written_as_null_not_the_nan_token():
    ds_calibration.log_ds_run(
        champion="Ahri", mode="ARAM", level=9, owned_items=[],
        ds_picks=[{"item_id": "3089", "delta_dps": float("nan"),
                   "gold": float("inf")}],
        match_key="k5")
    raw = _path().read_text(encoding="utf-8")
    assert "NaN" not in raw
    assert "Infinity" not in raw
    row = _strict_loads(raw.splitlines()[-1])
    assert row["ds_picks"][0]["delta_dps"] is None
    assert row["ds_picks"][0]["gold"] is None


def test_the_word_infinity_inside_an_item_name_is_untouched():
    ds_calibration.log_ds_run(
        champion="Caitlyn", mode="ARAM", level=9, owned_items=[],
        ds_picks=[{"item_id": "3031", "item_name": "Infinity Edge",
                   "delta_dps": 41.5}],
        match_key="k6")
    pick = _rows()[-1]["ds_picks"][0]
    assert pick["item_name"] == "Infinity Edge"
    assert pick["delta_dps"] == 41.5


# --- 4. torn tail -----------------------------------------------------------

def test_a_row_after_a_torn_last_line_is_not_fused_onto_it():
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'{"game_id": "kept"}\n{"game_id": "torn", "ch')
    ds_calibration.log_ds_run(champion="Ahri", mode="ARAM", level=9,
                              owned_items=[], ds_picks=[], match_key="k7")
    raw = path.read_bytes()
    assert raw.endswith(b"\n")
    records = load_records(path)
    assert [r.get("game_id") for r in records][0] == "kept"
    assert records[-1]["match_key"] == "k7"
    assert len(records) == 2


def test_a_clean_file_gets_no_blank_separator_line():
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'{"game_id": "kept"}\n')
    ds_calibration.log_ds_run(champion="Ahri", mode="ARAM", level=9,
                              owned_items=[], ds_picks=[], match_key="k8")
    raw = path.read_bytes()
    assert b"\n\n" not in raw
    assert raw.count(b"\n") == 2


# --- 5. a failure is logged, once -------------------------------------------

def test_a_write_failure_is_logged_once_and_never_raises(tmp_path, monkeypatch,
                                                         caplog):
    blocked = tmp_path / "is_a_directory"
    blocked.mkdir()
    monkeypatch.setattr(ds_calibration, "_LOG_PATH", blocked)
    monkeypatch.setattr(ds_calibration, "_WARNED", set())
    with caplog.at_level(logging.WARNING, logger="core.ds_calibration"):
        for key in ("f1", "f2", "f3"):
            ds_calibration.log_ds_run(champion="Ahri", mode="ARAM", level=9,
                                      owned_items=[], ds_picks=[],
                                      match_key=key)
    warnings = [r for r in caplog.records
                if r.name == "core.ds_calibration"
                and r.levelno >= logging.WARNING]
    assert len(warnings) == 1


def test_an_encode_failure_does_not_hide_a_later_write_failure(tmp_path,
                                                              monkeypatch,
                                                              caplog):
    blocked = tmp_path / "is_a_directory"
    blocked.mkdir()
    monkeypatch.setattr(ds_calibration, "_LOG_PATH", blocked)
    monkeypatch.setattr(ds_calibration, "_WARNED", set())
    circular: list = []
    circular.append(circular)
    with caplog.at_level(logging.WARNING, logger="core.ds_calibration"):
        ds_calibration.log_ds_run(champion="Ahri", mode="ARAM", level=9,
                                  owned_items=[], ds_picks=circular,
                                  match_key="e1")
        ds_calibration.log_ds_run(champion="Ahri", mode="ARAM", level=9,
                                  owned_items=[], ds_picks=[], match_key="w1")
    messages = [r.getMessage() for r in caplog.records
                if r.name == "core.ds_calibration"]
    assert len(messages) == 2
    assert "encoded" in messages[0]
    assert "appending" in messages[1]


def test_plain_dict_keys_serialize_exactly_as_json_dumps_would():
    picks = [{"item_id": "3089", True: 1, None: 2, 7: 3, 1.5: 4}]
    ds_calibration.log_ds_run(champion="Ahri", mode="ARAM", level=9,
                              owned_items=[], ds_picks=picks, match_key="k9")
    line = _path().read_text(encoding="utf-8").splitlines()[-1]
    assert json.dumps(picks) in line


def _raising(exc):
    def _gen():
        yield "3089"
        raise exc
    return _gen()


def test_an_argument_raising_valueerror_drops_the_row_with_a_warning(
        monkeypatch, caplog):
    monkeypatch.setattr(ds_calibration, "_WARNED", set())
    with caplog.at_level(logging.WARNING, logger="core.ds_calibration"):
        ds_calibration.log_ds_run(champion="Ahri", mode="ARAM", level=9,
                                  owned_items=_raising(ValueError("it")),
                                  ds_picks=[], match_key="v1")
    assert _rows() == []
    assert any("encoded" in r.getMessage() for r in caplog.records
               if r.name == "core.ds_calibration")


def test_an_argument_raising_another_error_propagates_as_documented():
    with pytest.raises(RuntimeError):
        ds_calibration.log_ds_run(champion="Ahri", mode="ARAM", level=9,
                                  owned_items=_raising(RuntimeError("bug")),
                                  ds_picks=[], match_key="r1")
