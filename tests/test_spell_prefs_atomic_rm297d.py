"""RM-297d - the two spell_prefs.json writers must use RC's shared atomic writer.

lcu/lcu_rune_writer.save_spell_pref and save_champ_spell_pref hand-rolled the
write: a destination-derived scratch name (`spell_prefs.tmp`), a 45 ms retry
budget (0.015 + 0.030) against core/polled_json._replace_with_retry's 275 ms,
and a give-up arm that logged a WARNING and DROPPED the operator's preference.

Red-first: os.replace raises PermissionError for ~120 ms (longer than the
hand-rolled 45 ms budget, shorter than the shared helper's 275 ms) and the
write must still land.

Already-bad state checked 2026-10-04: no orphaned data/spell_prefs.tmp in the
live checkout before the change.
"""
from __future__ import annotations

import json
import os
import time

import pytest

import core.polled_json as pj
import lcu.lcu_rune_writer as rw


@pytest.fixture
def prefs_path(tmp_path, monkeypatch):
    p = tmp_path / "data" / "spell_prefs.json"
    p.parent.mkdir(parents=True)
    p.write_bytes(json.dumps({"aram_mode": "snowball", "keep": 1}).encode())
    monkeypatch.setattr(rw, "_SPELL_PREFS_PATH", p)
    return p


def _flaky_replace(monkeypatch, hold_s: float):
    real = os.replace
    start = time.monotonic()

    def fake(src, dst):
        if time.monotonic() - start < hold_s:
            raise PermissionError(5, "simulated WinError 5 share-lock")
        return real(src, dst)

    monkeypatch.setattr(pj.os, "replace", fake)


def test_save_spell_pref_rides_out_a_lock_longer_than_45ms(prefs_path, monkeypatch):
    _flaky_replace(monkeypatch, 0.12)
    rw.save_spell_pref("sr_mode", "ignite")
    data = json.loads(prefs_path.read_bytes())
    assert data["sr_mode"] == "ignite"
    assert data["keep"] == 1


def test_save_champ_spell_pref_rides_out_a_lock_longer_than_45ms(prefs_path, monkeypatch):
    _flaky_replace(monkeypatch, 0.12)
    rw.save_champ_spell_pref("Ahri", "CLASSIC", (4, 14))
    data = json.loads(prefs_path.read_bytes())
    assert data["by_champ"]["SR"]["Ahri"] == [4, 14]
    assert data["aram_mode"] == "snowball"


def test_writers_leave_no_scratch_and_write_lf_only(prefs_path):
    rw.save_spell_pref("sr_mode", "exhaust")
    rw.save_champ_spell_pref("Ahri", "ARAM", (4, 32))
    assert sorted(p.name for p in prefs_path.parent.iterdir()) == ["spell_prefs.json"]
    assert b"\r" not in prefs_path.read_bytes()


def test_corrupt_file_reads_as_empty_and_is_repaired(prefs_path):
    prefs_path.write_bytes(b"\xff\xfe not json")
    assert rw.load_champ_spell_pref("Ahri", "CLASSIC") is None
    rw.save_champ_spell_pref("Ahri", "CLASSIC", (4, 12))
    assert rw.load_champ_spell_pref("Ahri", "CLASSIC") == (4, 12)


def test_module_does_not_hand_roll_a_scratch_name():
    src = open(rw.__file__, encoding="utf-8").read()
    assert 'with_suffix(".tmp")' not in src and "with_suffix('.tmp')" not in src
