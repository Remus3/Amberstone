"""P2-5 - runtime JSON stores in their three states: absent / empty-but-valid /
populated (plus a 0-byte file where a crash or `touch` can leave one).

For each store: the READ result is asserted in every state, and a WRITE is
asserted to round-trip (write, re-read, the key lands) starting from every
state. States are declared once per store via tests/_store_states.py; every
file lives under tmp_path.

Symbols used (file:line at time of writing):
  core/polled_json.py:113 atomic_write_json, :148 read_json_dict,
  core/cost_tracker.py:121 _COACH_CFG, :126 _RC_CFG, :183 _today_str,
    :187 _empty_ledger, :201 _read_config, :209 CostTracker, :241 record_call,
    :311 daily_spend, :336 allow_call, :342 banner_state, :423 coach_disabled,
    :427 set_coach_disabled, :452 note_match_boundary, :514 recent_match_avg
  core/augment_external_source.py:53 _DS_DATA_DIR, :115 has_data, :119 count,
    :150 _current_patch, :219 _http_get, :262 _http_get_json, :270 _normalize,
    :343 refresh_cache, :408 _load_degraded, :523 count (meta), :555 _build_meta,
    :639 _load_degraded_meta, :657 refresh_meta_cache, :754 reset_cache
"""
from __future__ import annotations

import json
import os
import time
from datetime import date

import pytest

from core import augment_external_source as X
from core import cost_tracker as ct
from core.polled_json import atomic_write_json, read_json_dict
from tests._store_states import (
    ABSENT,
    EMPTY,
    JSON_STATES_WITH_ZERO_BYTE,
    POPULATED,
    ZERO_BYTE,
    json_store,
    parametrize_states,
)

# ---------------------------------------------------------------------------
# core.polled_json - the contract every polled runtime JSON file goes through
# ---------------------------------------------------------------------------

POLLED = json_store("polled_json", "runtime/state.json",
                    empty={}, populated={"mode": "aram", "n": 3})
_DEFAULT = {"mode": "client", "log": []}

# What read_json_dict returns per state. EMPTY is a VALID dict, so it comes
# back verbatim - the default is for missing/corrupt files only (:148 doc).
_POLLED_READ = {
    ABSENT: _DEFAULT,
    EMPTY: {},
    POPULATED: {"mode": "aram", "n": 3},
    ZERO_BYTE: _DEFAULT,
}


@parametrize_states(JSON_STATES_WITH_ZERO_BYTE)
def test_polled_read_json_dict_per_state(tmp_path, state):
    path = POLLED.build(tmp_path, state)
    assert read_json_dict(path, _DEFAULT) == _POLLED_READ[state]


def test_polled_valid_empty_list_is_not_a_dict_and_reads_as_default(tmp_path):
    # `[]` is the other valid-but-empty JSON shape a fresh writer can leave.
    path = tmp_path / "runtime" / "state.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"[]")
    assert read_json_dict(path, _DEFAULT) == _DEFAULT


@parametrize_states(JSON_STATES_WITH_ZERO_BYTE)
def test_polled_read_modify_write_round_trips_from_each_state(tmp_path, state):
    # RM-264 removed PolledJsonFile; the read-modify-write is the two helpers.
    path = POLLED.build(tmp_path, state)
    returned = read_json_dict(path, _DEFAULT)
    returned["immediate"] = "All-In"
    atomic_write_json(path, returned)
    reread = read_json_dict(path, {})
    assert reread["immediate"] == "All-In"
    assert reread == returned
    expected = dict(_POLLED_READ[state], immediate="All-In")
    assert reread == expected
    assert not list(path.parent.glob("*.tmp")), "scratch file left behind"


@parametrize_states(JSON_STATES_WITH_ZERO_BYTE)
def test_polled_update_and_atomic_write_round_trip_from_each_state(tmp_path, state):
    path = POLLED.build(tmp_path, state)
    cur = read_json_dict(path, _DEFAULT)
    cur["win_pct"] = 42
    atomic_write_json(path, cur)
    assert read_json_dict(path, {})["win_pct"] == 42
    atomic_write_json(path, {"replaced": True})
    assert read_json_dict(path, {}) == {"replaced": True}


# ---------------------------------------------------------------------------
# core.cost_tracker - daily spend ledger, per-match sidecar, coach config.
# All three are read by the dashboard on a fresh install.
# ---------------------------------------------------------------------------

def _populated_ledger():
    led = ct._empty_ledger()
    led.update({
        "total_usd": 0.5, "calls": 2, "tokens_in": 100, "tokens_out": 50,
        "by_model": {"claude-haiku-4-5-20251001": {
            "calls": 2, "usd": 0.5, "tokens_in": 100, "tokens_out": 50,
            "cache_in": 0, "cache_write": 0}},
        "by_purpose": {"aram_coach": {"calls": 2, "usd": 0.5, "tokens": 150}},
    })
    return led


LEDGER = json_store("spend_ledger", lambda: f"{date.today().isoformat()}.json",
                    empty={}, populated=_populated_ledger)
RECENT = json_store(
    "recent_matches", "recent_matches.json", empty={},
    populated={"matches": [{"ts": 1.0, "by_gate": {"aram": {"usd": 0.2, "tokens": 10}}}]})
COACH_CFG = json_store("coach_settings", "coach_settings.json", empty={},
                       populated={"disabled_coaches": ["sr"], "keep": 1})

_BUDGET_CFG = {"daily_budget_usd": 1.0, "warn_at_fraction": 0.4}


def _tracker(tmp_path, cfg=None):
    return ct.CostTracker(config_provider=lambda: dict(cfg or {}),
                          spend_dir=tmp_path)


@parametrize_states(JSON_STATES_WITH_ZERO_BYTE)
def test_spend_ledger_read_per_state(tmp_path, state):
    LEDGER.build(tmp_path, state)
    t = _tracker(tmp_path, _BUDGET_CFG)
    spend = t.daily_spend()
    if state == POPULATED:
        assert spend["total_usd"] == 0.5 and spend["calls"] == 2
        assert t.banner_state() == "warn"
    elif state == EMPTY:
        assert spend == {}  # valid dict, returned verbatim
        assert t.banner_state() == "ok"
    else:
        assert spend == ct._empty_ledger()
        assert t.banner_state() == "ok"
    assert t.allow_call() is True


@parametrize_states(JSON_STATES_WITH_ZERO_BYTE)
def test_spend_ledger_record_call_round_trips_from_each_state(tmp_path, state):
    LEDGER.build(tmp_path, state)
    t = _tracker(tmp_path)
    prior_calls = 2 if state == POPULATED else 0
    prior_usd = 0.5 if state == POPULATED else 0.0
    t.record_call(model="claude-haiku-4-5-20251001", input_tokens=1_000_000,
                  purpose="aram_coach")
    spend = _tracker(tmp_path).daily_spend()
    assert spend["date"] == date.today().isoformat()
    assert spend["calls"] == prior_calls + 1
    assert spend["total_usd"] == pytest.approx(prior_usd + 0.8)
    assert spend["by_purpose"]["aram_coach"]["calls"] == prior_calls + 1


@parametrize_states()
def test_recent_matches_read_per_state(tmp_path, state):
    RECENT.build(tmp_path, state)
    avg = _tracker(tmp_path).recent_match_avg()
    assert set(avg) == set(ct.GATES)
    if state == POPULATED:
        assert avg["aram"] == {"usd": 0.2, "tokens": 10, "n": 1}
    else:
        assert avg["aram"] == {"usd": 0.0, "tokens": 0, "n": 0}


@parametrize_states()
def test_recent_matches_boundary_round_trips_from_each_state(tmp_path, state):
    path = RECENT.build(tmp_path, state)
    LEDGER.build(tmp_path, POPULATED)
    t = _tracker(tmp_path)
    t.note_match_boundary()
    matches = read_json_dict(path, {})["matches"]
    prior = 1 if state == POPULATED else 0
    assert len(matches) == prior + 1
    assert matches[-1]["by_gate"]["aram"] == {"usd": 0.5, "tokens": 150}
    assert _tracker(tmp_path).recent_match_avg()["aram"]["n"] == prior + 1
    assert read_json_dict(tmp_path / "_match_open.json", {})["by_purpose"]


@pytest.fixture
def coach_cfg_at(tmp_path, monkeypatch):
    """Point both config files at tmp; returns a builder for coach_settings."""
    monkeypatch.setattr(ct, "_RC_CFG", tmp_path / "ops" / "rc_config.json")

    def build(state):
        path = COACH_CFG.build(tmp_path / "config", state)
        monkeypatch.setattr(ct, "_COACH_CFG", path)
        return path
    return build


@parametrize_states()
def test_coach_settings_read_per_state(tmp_path, coach_cfg_at, state):
    coach_cfg_at(state)
    t = ct.CostTracker(spend_dir=tmp_path / "spend")
    assert t.coach_disabled("sr") is (state == POPULATED)
    assert t.coach_disabled("aram") is False


@parametrize_states()
def test_coach_settings_toggle_round_trips_from_each_state(tmp_path, coach_cfg_at, state):
    path = coach_cfg_at(state)
    t = ct.CostTracker(spend_dir=tmp_path / "spend")
    t.set_coach_disabled("aram", True)
    assert ct.CostTracker(spend_dir=tmp_path / "spend").coach_disabled("aram") is True
    saved = read_json_dict(path, {})
    if state == POPULATED:
        assert saved == {"disabled_coaches": ["sr", "aram"], "keep": 1}
    else:
        assert saved == {"disabled_coaches": ["aram"]}


# ---------------------------------------------------------------------------
# core.augment_external_source - patch-pinned prior + meta snapshots
# ---------------------------------------------------------------------------

def _blitz_payload(n=2):
    rows = [
        {"augment_id": "1088", "patch": "16.10",
         "stats": {"win_rate": 0.50, "num_games": 1000}},
        {"augment_id": "1406", "patch": "16.10",
         "stats": {"win_rate": 0.62, "num_games": 800}},
    ]
    return {"data": rows[:n]}


def _cherry(n=3):
    rows = [
        {"id": 1103, "nameTRA": "Bread And Butter", "rarity": "kGold"},
        {"id": 1011, "nameTRA": "Can't Touch This", "rarity": "kPrismatic"},
        {"id": 1200, "nameTRA": "Third", "rarity": "kSilver"},
    ]
    return rows[:n]


PRIORS = json_store("augment_priors", "tp/mayhem_augment_stats.json", empty={},
                    populated=lambda: X._normalize("mayhem", "tp", _blitz_payload()))
META = json_store("augment_meta", "tp/cherry_augments.json", empty={},
                  populated=lambda: X._build_meta("tp", _cherry()))


def _offline(*_a, **_k):
    raise X.AugmentSourceError("offline")


@pytest.fixture
def ds_root(tmp_path, monkeypatch):
    root = tmp_path / "ds"
    root.mkdir()
    monkeypatch.setattr(X, "_DS_DATA_DIR", root)
    monkeypatch.setattr(X, "_current_patch", lambda: "tp")
    monkeypatch.setattr(X, "_http_get_json", _offline)
    monkeypatch.setattr(X, "_http_get", _offline)
    X.reset_cache()
    yield root
    X.reset_cache()


def _age(path, seconds=3600):
    old = time.time() - seconds
    os.utime(path, (old, old))


@parametrize_states(JSON_STATES_WITH_ZERO_BYTE)
def test_augment_priors_read_per_state_offline(ds_root, state):
    PRIORS.build(ds_root, state)
    table = X.refresh_cache("mayhem")
    assert table.count == (2 if state == POPULATED else 0)


@parametrize_states(JSON_STATES_WITH_ZERO_BYTE)
def test_augment_priors_refresh_round_trips_from_each_state(ds_root, monkeypatch, state):
    path = PRIORS.build(ds_root, state)
    monkeypatch.setattr(X, "_http_get_json", lambda u, t: _blitz_payload())
    X.refresh_cache("mayhem", force=(state == POPULATED))
    assert read_json_dict(path, {})["count"] == 2
    monkeypatch.setattr(X, "_http_get_json", _offline)
    assert X.refresh_cache("mayhem").count == 2


@parametrize_states(JSON_STATES_WITH_ZERO_BYTE)
def test_augment_priors_degrade_skips_an_empty_newer_snapshot(ds_root, state):
    # An older patch holds a real snapshot. A present-but-empty current-patch
    # file is NEWER by mtime and must not shadow it when the fetch fails.
    old = ds_root / "op" / "mayhem_augment_stats.json"
    old.parent.mkdir()
    atomic_write_json(old, X._normalize("mayhem", "op", _blitz_payload(1)))
    _age(old)
    PRIORS.build(ds_root, state)
    table = X.refresh_cache("mayhem")
    assert table.count == (2 if state == POPULATED else 1)


def test_augment_priors_degrade_prefers_the_newest_populated_snapshot(ds_root):
    for patch, n, age in (("p1", 1, 7200), ("p2", 2, 3600)):
        snap = ds_root / patch / "mayhem_augment_stats.json"
        snap.parent.mkdir()
        atomic_write_json(snap, X._normalize("mayhem", patch, _blitz_payload(n)))
        _age(snap, age)
    assert X.refresh_cache("mayhem").count == 2


@parametrize_states(JSON_STATES_WITH_ZERO_BYTE)
def test_augment_meta_read_per_state_offline(ds_root, state):
    META.build(ds_root, state)
    assert X.refresh_meta_cache().count == (3 if state == POPULATED else 0)


@parametrize_states(JSON_STATES_WITH_ZERO_BYTE)
def test_augment_meta_refresh_round_trips_from_each_state(ds_root, monkeypatch, state):
    path = META.build(ds_root, state)
    monkeypatch.setattr(X, "_http_get", lambda u, t: _cherry(2))
    X.refresh_meta_cache(force=True)
    saved = read_json_dict(path, {})
    assert saved["count"] == 2 and saved["rc_patch"] == "tp"
    monkeypatch.setattr(X, "_http_get", _offline)
    assert X.refresh_meta_cache().count == 2


@parametrize_states(JSON_STATES_WITH_ZERO_BYTE)
def test_augment_meta_degrade_skips_an_empty_newer_snapshot(ds_root, state):
    old = ds_root / "op" / "cherry_augments.json"
    old.parent.mkdir()
    atomic_write_json(old, X._build_meta("op", _cherry(1)))
    _age(old)
    META.build(ds_root, state)
    assert X.refresh_meta_cache().count == (3 if state == POPULATED else 1)


def test_store_builder_refuses_a_root_inside_the_repo():
    from tests._store_states import _REPO_ROOT
    with pytest.raises(AssertionError, match="inside the repo"):
        POLLED.build(_REPO_ROOT / "data", ABSENT)

