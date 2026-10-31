"""Behavior tests for core.auto_accept_pref (LIFT 5).

The NON-frozen ready-check auto-accept flag the frozen lcu_client
_auto_accept_tick reads. Contract:

  - default is_enabled() -> False when the file is absent (s144 true-audit
    cycle 83: it was True, which disagreed with the LCU agent's boot
    default the dashboard control displays).
  - set_enabled(False) -> is_enabled() False; set_enabled(True) -> True.
  - a corrupt / garbage file -> the default False (the live 1 Hz tick must
    never throw; the transient-read-error memo is pinned in
    tests/test_auto_accept_pref_hardening_s144t083.py).
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


def test_default_disabled_when_absent(pref_file):
    assert not pref_file.exists()
    assert mod.is_enabled() is False


def test_set_false_then_true(pref_file):
    assert mod.set_enabled(False) is False
    assert mod.is_enabled() is False
    assert mod.set_enabled(True) is True
    assert mod.is_enabled() is True


def test_corrupt_file_falls_back_to_default_off(pref_file):
    pref_file.write_text("}{not json", encoding="utf-8")
    assert mod.is_enabled() is False


def test_non_dict_json_falls_back_to_default_off(pref_file):
    pref_file.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert mod.is_enabled() is False


def test_missing_enabled_key_falls_back_to_default_off(pref_file):
    pref_file.write_text(json.dumps({"other": "x"}), encoding="utf-8")
    assert mod.is_enabled() is False


def test_non_bool_enabled_falls_back_to_default_off(pref_file):
    pref_file.write_text(json.dumps({"enabled": "yes"}), encoding="utf-8")
    assert mod.is_enabled() is False


def test_stored_true_wins_over_the_default(pref_file):
    pref_file.write_text(json.dumps({"enabled": True}), encoding="utf-8")
    assert mod.is_enabled() is True


def test_persisted_shape_is_enabled_bool(pref_file):
    mod.set_enabled(False)
    data = json.loads(pref_file.read_text(encoding="utf-8"))
    assert data == {"enabled": False}
    mod.set_enabled(True)
    data = json.loads(pref_file.read_text(encoding="utf-8"))
    assert data == {"enabled": True}


def test_set_refuses_non_bool_instead_of_coercing(pref_file):
    # s144 true-audit cycle 83: set_enabled(1) used to store True via bool(),
    # and set_enabled("false") stored True as well. A non-bool is refused.
    with pytest.raises(TypeError):
        mod.set_enabled(1)
    assert not pref_file.exists()


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
