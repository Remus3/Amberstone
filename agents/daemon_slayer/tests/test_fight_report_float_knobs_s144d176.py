"""S144-D-176..178 - ``compute_fight_report`` keeps its NEVER-raises contract
for a bad target knob or a bad recharge window, and its report carries only
finite numbers.

Measured at HEAD before the fix (Caitlyn L11, 3031, target 100/60/2500/1200):

* S144-D-176: a non-numeric or overflowing ``target_armor`` / ``target_mr`` /
  ``target_max_hp`` / ``target_bonus_hp`` (None, "x", 10**400) raised
  TypeError / ValueError / OverflowError out of the report constructor (the
  ``float(...)`` echo sits outside every per-section try).
* S144-D-177: a NaN / +-inf target knob was echoed into the report as a
  non-finite number, and the damage sections failed with a misleading
  "burst walker failed" note that never named the knob.
* S144-D-178: the same raise for ``recharge_window_s``; a NaN / +-inf window
  silently dropped every charge slot (Corki R, Caitlyn W) with no note and
  echoed the non-finite window.

Contract pinned here: a target knob or recharge window that is not a finite
number reads as the parameter's own default (0.0 for a target knob, 10.0 for
the window); one note names the knob and carries no part of the value; every
section then computes exactly as it does at that default. A finite value,
negative included, and a numeric string are read as numbers, with no note.
"""
from __future__ import annotations

import logging
import math

import pytest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.fight_report import compute_fight_report

_NAN = float("nan")
_INF = float("inf")
_BAD = [
    pytest.param(_NAN, id="nan"),
    pytest.param(_INF, id="inf"),
    pytest.param(-_INF, id="neg_inf"),
    pytest.param(None, id="none"),
    pytest.param("x", id="str"),
    pytest.param(10 ** 400, id="huge_int"),
]
_TARGET_KNOBS = ("target_armor", "target_mr", "target_max_hp",
                 "target_bonus_hp")
_BASE = {
    "champion": "Caitlyn",
    "level": 11,
    "item_ids": ["3031"],
    "runes": [8005, 8299],
    "target_armor": 100.0,
    "target_mr": 60.0,
    "target_max_hp": 2500.0,
    "target_bonus_hp": 1200.0,
}


@pytest.fixture(scope="module")
def snap():
    return DataSnapshot.load()


@pytest.fixture(autouse=True)
def _quiet_logs():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


def _report(snap, **over):
    kw = dict(_BASE)
    kw.update(over)
    return compute_fight_report(snapshot=snap, **kw)


def _nonfinite_paths(obj, path=""):
    out = []
    if isinstance(obj, float) and not math.isfinite(obj):
        out.append(path)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(_nonfinite_paths(v, f"{path}.{k}"))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out.extend(_nonfinite_paths(v, f"{path}[{i}]"))
    return out


def _without_notes(report):
    d = report.to_dict()
    d.pop("notes", None)
    return d


# ---------------------------------------------------------------- target knobs
@pytest.mark.parametrize("bad", _BAD)
@pytest.mark.parametrize("knob", _TARGET_KNOBS)
def test_bad_target_knob_never_raises_and_reads_default(snap, knob, bad):
    r = _report(snap, **{knob: bad})
    assert getattr(r, knob) == 0.0
    assert _nonfinite_paths(r.to_dict()) == []
    base = _report(snap, **{knob: 0.0})
    assert _without_notes(r) == _without_notes(base)


@pytest.mark.parametrize("bad", _BAD)
@pytest.mark.parametrize("knob", _TARGET_KNOBS)
def test_bad_target_knob_note_names_knob_only(snap, knob, bad):
    r = _report(snap, **{knob: bad})
    named = [n for n in r.notes if n.startswith(f"{knob}:")]
    assert len(named) == 1, r.notes
    assert named[0] == f"{knob}: not a finite number - read as 0"
    assert all("burst walker failed" not in n for n in r.notes), r.notes


@pytest.mark.parametrize("knob", _TARGET_KNOBS)
@pytest.mark.parametrize("good", [-5.0, 0.0, 37.5])
def test_finite_target_knob_unchanged_and_unnoted(snap, knob, good):
    r = _report(snap, **{knob: good})
    assert getattr(r, knob) == good
    assert not any(n.startswith(f"{knob}:") for n in r.notes)


@pytest.mark.parametrize("knob", _TARGET_KNOBS)
def test_numeric_string_target_knob_reads_as_number(snap, knob):
    r = _report(snap, **{knob: "50"})
    assert _without_notes(r) == _without_notes(_report(snap, **{knob: 50.0}))
    assert not any(n.startswith(f"{knob}:") for n in r.notes)


def test_default_report_carries_no_knob_note(snap):
    r = _report(snap)
    assert not any(n.split(":")[0] in _TARGET_KNOBS + ("recharge_window_s",)
                   for n in r.notes)


# ------------------------------------------------------------- recharge window
@pytest.mark.parametrize("bad", _BAD)
@pytest.mark.parametrize("champ", ["Corki", "Caitlyn"])
def test_bad_recharge_window_reads_default_and_keeps_charge_slots(
        snap, champ, bad):
    r = compute_fight_report(champ, 16, snapshot=snap, recharge_window_s=bad)
    base = compute_fight_report(champ, 16, snapshot=snap,
                                recharge_window_s=10.0)
    assert r.recharge_window_s == 10.0
    assert base.recharge_slots, "charge champion lost its slot at default"
    assert r.recharge_slots == base.recharge_slots
    assert _nonfinite_paths(r.to_dict()) == []
    named = [n for n in r.notes if n.startswith("recharge_window_s:")]
    assert named == ["recharge_window_s: not a finite number - read as 10"]


@pytest.mark.parametrize("good", [-5.0, 0.0, 25.0])
def test_finite_recharge_window_unchanged_and_unnoted(snap, good):
    r = compute_fight_report("Corki", 16, snapshot=snap,
                             recharge_window_s=good)
    assert r.recharge_window_s == good
    assert not any(n.startswith("recharge_window_s:") for n in r.notes)
