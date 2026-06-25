"""Behavior tests for core.auto_accept_pref (LIFT 5).

The NON-frozen ready-check auto-accept flag the frozen lcu_client
_auto_accept_tick reads. Contract:

  - default is_enabled() -> True when the file is absent (historical
    always-on behavior preserved).
  - set_enabled(False) -> is_enabled() False; set_enabled(True) -> True.
  - a corrupt / garbage file -> default True (fail-soft, the live 1 Hz
    tick must never throw or silently disable itself on an FS hiccup).
  - the persisted shape is exactly {"enabled": bool}.

All IO is redirected at the module-level _PREF_PATH constant so these
tests touch only a tmp dir - the LIVE data/auto_accept_pref.json is never
written here. A belt-and-suspenders teardown asserts the live flag is
still enabled (or absent) so a regression in the redirect can't leave
auto-accept OFF on disk.
"""
from __future__ import annotations

import json

import pytest

from core import auto_accept_pref as mod


@pytest.fixture
def pref_file(tmp_path, monkeypatch):
    p = tmp_path / "auto_accept_pref.json"
    monkeypatch.setattr(mod, "_PREF_PATH", p)
    return p


@pytest.fixture(scope="module", autouse=True)
def _live_pref_bytes_untouched():
    """Real redirect-regression guard: assert this module never WRITES the
    live data/auto_accept_pref.json. Each mutation test monkeypatches
    _PREF_PATH to tmp; if that redirect ever regressed, set_enabled() would
    hit the live file. Snapshot its bytes before any test runs and assert
    byte-identity after - agnostic to the operator's chosen value, since
    auto-accept is a dashboard-toggleable runtime flag (a False on disk is
    legitimate operator state, not a bug)."""
    from pathlib import Path

    live = Path(mod.__file__).resolve().parent.parent / "data" / "auto_accept_pref.json"
    before = live.read_bytes() if live.exists() else None
    yield
    after = live.read_bytes() if live.exists() else None
    assert after == before, (
        "live data/auto_accept_pref.json was modified by the test suite "
        f"(redirect regression): {before!r} -> {after!r}"
    )


def test_default_enabled_when_absent(pref_file):
    assert not pref_file.exists()
    assert mod.is_enabled() is True


def test_set_false_then_true(pref_file):
    assert mod.set_enabled(False) is False
    assert mod.is_enabled() is False
    assert mod.set_enabled(True) is True
    assert mod.is_enabled() is True


def test_corrupt_file_falls_back_to_true(pref_file):
    pref_file.write_text("}{not json", encoding="utf-8")
    assert mod.is_enabled() is True


def test_non_dict_json_falls_back_to_true(pref_file):
    pref_file.write_text("[1, 2, 3]", encoding="utf-8")
    assert mod.is_enabled() is True


def test_missing_enabled_key_falls_back_to_true(pref_file):
    pref_file.write_text(json.dumps({"other": "x"}), encoding="utf-8")
    assert mod.is_enabled() is True


def test_non_bool_enabled_falls_back_to_true(pref_file):
    pref_file.write_text(json.dumps({"enabled": "yes"}), encoding="utf-8")
    assert mod.is_enabled() is True


def test_persisted_shape_is_enabled_bool(pref_file):
    mod.set_enabled(False)
    data = json.loads(pref_file.read_text(encoding="utf-8"))
    assert data == {"enabled": False}
    mod.set_enabled(True)
    data = json.loads(pref_file.read_text(encoding="utf-8"))
    assert data == {"enabled": True}


def test_set_coerces_truthy_to_bool(pref_file):
    # set_enabled(1) -> stored True (bool), not the int 1.
    assert mod.set_enabled(1) is True
    data = json.loads(pref_file.read_text(encoding="utf-8"))
    assert data == {"enabled": True}
    assert isinstance(data["enabled"], bool)


def test_atomic_no_tmp_left(pref_file):
    mod.set_enabled(False)
    mod.set_enabled(True)
    # No stray .tmp sibling left behind by the atomic write.
    assert not list(pref_file.parent.glob("*.tmp"))


def test_live_pref_well_formed():
    """Auto-accept is operator-toggleable via the dashboard (POST
    /api/lcu/auto-accept), so a False on disk is legitimate operator state -
    we do NOT assert the value. The module-scoped _live_pref_bytes_untouched
    fixture above is the real redirect-regression guard (no test writes the
    live file); this only asserts the live file, if present, is well-formed
    {"enabled": bool} and not corrupted."""
    from pathlib import Path

    live = Path(mod.__file__).resolve().parent.parent / "data" / "auto_accept_pref.json"
    if live.exists():
        data = json.loads(live.read_text(encoding="utf-8"))
        assert isinstance(data, dict) and isinstance(data.get("enabled"), bool), (
            f"live auto_accept_pref.json malformed: {data!r}"
        )
