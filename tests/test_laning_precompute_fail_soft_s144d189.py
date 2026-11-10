"""S144-D-189..193 - core/laning_scenario_precompute.py never reads a failed or
junk engine read as a real one, and its fail-soft helpers never raise.

- D-189: ``_affordable_sequence`` read a soft-failed mana walk (the mana_sim
  ``_empty`` shape: ``hits == ()``, ``mana_pool == 0.0``) as a MANALESS champ,
  which suppressed the low-mana ``recall_now`` verdict. A raised walk already
  returned ``manaless=False``; the two failure shapes now agree.
- D-190: ``cc_threat_verdict`` read an infinite / bool enemy CC as real crowd
  control (``punish_now``), and a NaN own-ult cooldown differently from a
  non-numeric one.
- D-191: ``_enemy_cc_threat_card`` read an infinite rank as the best CC (then
  emitted that spell with a 0.0 duration), let one NaN rank hide the finite
  ones, iterated a string rank char by char, and raised on a non-dict entry.
- D-192: ``spike_timing_cell`` raised (outside its own try) on a junk marker
  threshold, dropping the whole (my, enemy) pair from the sweep, and read a NaN
  ``dps_at`` as a measured 0.0 instead of None.
- D-193: ``lookup`` raised TypeError on an unhashable key instead of ``{}``.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.laning_scenario_precompute as lsp  # noqa: E402
from agents.daemon_slayer import ability_dps  # noqa: E402
from agents.daemon_slayer import mana_sim  # noqa: E402

_BASE = ("Q", "W", "E", "R")


def _failed_walk(*_a, **_k):
    return mana_sim._empty("Ahri", 6, "SR", _BASE, [mana_sim.WALKER_FAILED_NOTE])


def _result(pool, hits):
    return SimpleNamespace(mana_pool=pool, hits=tuple(hits))


def _hit(action, cost=0.0):
    return SimpleNamespace(action=action, cost=cost)


# --------------------------------------------------------------------------- #
# S144-D-189 - a failed mana walk is not a manaless champ
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("budget", [lsp.LOW_MANA_FRACTION, 1.0])
def test_d189_failed_walk_is_not_manaless(monkeypatch, budget):
    monkeypatch.setattr(lsp, "compute_mana_bounded_combo", _failed_walk)
    seq, manaless = lsp._affordable_sequence(
        None, "Ahri", 6, (), _BASE, budget, "SR",
    )
    assert seq == _BASE
    assert manaless is False


def test_d189_failed_walk_matches_raised_walk(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("walker down")

    monkeypatch.setattr(lsp, "compute_mana_bounded_combo", _boom)
    raised = lsp._affordable_sequence(None, "Ahri", 6, (), _BASE, 1.0, "SR")
    monkeypatch.setattr(lsp, "compute_mana_bounded_combo", _failed_walk)
    soft = lsp._affordable_sequence(None, "Ahri", 6, (), _BASE, 1.0, "SR")
    assert soft == raised == (_BASE, False)


@pytest.mark.parametrize("mana_state", ["full", "low"])
def test_d189_derive_sequence_failed_walk_not_manaless(monkeypatch, mana_state):
    monkeypatch.setattr(lsp, "compute_mana_bounded_combo", _failed_walk)
    _, manaless = lsp.derive_sequence(None, "Ahri", 6, mana_state, "all_up")
    assert manaless is False


def test_d189_failed_walk_keeps_low_mana_recall(monkeypatch):
    # The consumer: a failed walk must not suppress the low-mana back verdict.
    monkeypatch.setattr(lsp, "compute_mana_bounded_combo", _failed_walk)
    _, manaless = lsp.derive_sequence(None, "Ahri", 11, "low", "all_up")
    econ = lsp.economy_cell("L11", "low", manaless=manaless)
    assert econ["recall"] == "recall_now"


def test_d189_real_manaless_champ_still_manaless(monkeypatch):
    # Control: a resolved walk with an infinite pool is a real manaless champ.
    monkeypatch.setattr(
        lsp, "compute_mana_bounded_combo",
        lambda *_a, **_k: _result(math.inf, [_hit("Q"), _hit("W")]),
    )
    assert lsp._affordable_sequence(None, "Garen", 6, (), _BASE, 0.35, "SR") == (
        _BASE, True,
    )


def test_d189_nan_pool_is_not_manaless(monkeypatch):
    monkeypatch.setattr(
        lsp, "compute_mana_bounded_combo",
        lambda *_a, **_k: _result(math.nan, [_hit("Q")]),
    )
    _, manaless = lsp._affordable_sequence(None, "Ahri", 6, (), _BASE, 1.0, "SR")
    assert manaless is False


def test_d189_finite_pool_still_truncates(monkeypatch):
    # Control: the affordable-prefix walk is unchanged.
    monkeypatch.setattr(
        lsp, "compute_mana_bounded_combo",
        lambda *_a, **_k: _result(
            400.0, [_hit("Q", 60.0), _hit("W", 70.0), _hit("E", 80.0), _hit("R", 100.0)],
        ),
    )
    assert lsp._affordable_sequence(None, "Ahri", 6, (), _BASE, 0.35, "SR") == (
        ("Q", "W"), False,
    )


# --------------------------------------------------------------------------- #
# S144-D-190 - cc_threat_verdict reads only finite numeric CC as real
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("cc", [math.inf, -math.inf, math.nan, True, False, 10**400])
def test_d190_junk_enemy_cc_is_even(cc):
    assert lsp.cc_threat_verdict(cc, 130.0, "all_up") == "even"


def test_d190_nan_my_cd_reads_like_non_numeric():
    assert lsp.cc_threat_verdict(1.25, math.nan, "all_up") == lsp.cc_threat_verdict(
        1.25, "nope", "all_up",
    ) == "punish_now"


def test_d190_controls_unchanged():
    assert lsp.cc_threat_verdict(1.25, 130.0, "all_up") == "punish_now"
    assert lsp.cc_threat_verdict(1.25, -5.0, "all_up") == "even"
    # +/-inf keep their sign, like a finite cooldown.
    assert lsp.cc_threat_verdict(1.25, -math.inf, "all_up") == "even"
    assert lsp.cc_threat_verdict(1.25, math.inf, "all_up") == "punish_now"
    assert lsp.cc_threat_verdict(math.inf, 130.0, "no_ult") == "wait_cd"


# --------------------------------------------------------------------------- #
# S144-D-191 - _enemy_cc_threat_card skips junk ranks and junk entries
# --------------------------------------------------------------------------- #
def _with_registry(monkeypatch, entry):
    monkeypatch.setattr(ability_dps, "_PER_SPELL_CC_DURATIONS", {"Zed": entry})


def test_d191_infinite_rank_never_wins(monkeypatch):
    _with_registry(monkeypatch, {"Q": (math.inf,), "E": (1.5,)})
    assert lsp._enemy_cc_threat_card("Zed") == lsp.CcThreatCard("E", 1.5)


def test_d191_nan_rank_does_not_hide_finite_ranks(monkeypatch):
    _with_registry(monkeypatch, {"Q": (math.nan, 2.0)})
    assert lsp._enemy_cc_threat_card("Zed") == lsp.CcThreatCard("Q", 2.0)


@pytest.mark.parametrize("ranks", ["12", (True,), (math.inf,), b"\x05"])
def test_d191_junk_ranks_yield_no_card(monkeypatch, ranks):
    _with_registry(monkeypatch, {"Q": ranks})
    assert lsp._enemy_cc_threat_card("Zed") is None


@pytest.mark.parametrize("entry", [[("Q", (1.0,))], "Q", 3.0])
def test_d191_non_dict_entry_never_raises(monkeypatch, entry):
    _with_registry(monkeypatch, entry)
    assert lsp._enemy_cc_threat_card("Zed") is None


def test_d191_mixed_key_types_never_raise(monkeypatch):
    _with_registry(monkeypatch, {"Q": (1.0,), 7: (2.0,)})
    assert lsp._enemy_cc_threat_card("Zed") == lsp.CcThreatCard("7", 2.0)


def test_d191_real_registry_control():
    card = lsp._enemy_cc_threat_card("Ahri")
    assert card is not None and card.spell_key == "E" and card.cc_duration_s > 0.0


# --------------------------------------------------------------------------- #
# S144-D-192 - spike_timing_cell never raises and never reads NaN as measured
# --------------------------------------------------------------------------- #
_SPIKE_KEYS = {"next_kind", "next_threshold", "next_label", "crossed_dps_at", "spike_verdict"}


def _markers(next_threshold, level_threshold, dps_at):
    nm = SimpleNamespace(kind="level", threshold=next_threshold, label="R unlock")
    lm = SimpleNamespace(kind="level", threshold=level_threshold, dps_at=dps_at)
    return SimpleNamespace(next_marker=nm, markers=[lm])


@pytest.mark.parametrize("bad", [math.nan, math.inf, None, "six", object()])
def test_d192_junk_next_threshold_never_raises(monkeypatch, bad):
    monkeypatch.setattr(
        lsp, "compute_spike_markers", lambda *_a, **_k: _markers(bad, 2, 50.0),
    )
    block = lsp.spike_timing_cell("Ahri", "L2", "none", (), "SR")
    assert set(block) == _SPIKE_KEYS
    assert block["next_threshold"] == 0


@pytest.mark.parametrize("bad", [math.nan, math.inf, None, "two"])
def test_d192_junk_marker_threshold_is_skipped(monkeypatch, bad):
    monkeypatch.setattr(
        lsp, "compute_spike_markers", lambda *_a, **_k: _markers(6, bad, 50.0),
    )
    block = lsp.spike_timing_cell("Ahri", "L2", "none", (), "SR")
    assert block["crossed_dps_at"] is None
    assert block["next_threshold"] == 6


@pytest.mark.parametrize("dps", [math.nan, math.inf, "x"])
def test_d192_non_finite_dps_at_is_none(monkeypatch, dps):
    monkeypatch.setattr(
        lsp, "compute_spike_markers", lambda *_a, **_k: _markers(6, 2, dps),
    )
    assert lsp.spike_timing_cell("Ahri", "L2", "none", (), "SR")["crossed_dps_at"] is None


def test_d192_control_reads_real_marker(monkeypatch):
    monkeypatch.setattr(
        lsp, "compute_spike_markers", lambda *_a, **_k: _markers(6, 2, 51.23456),
    )
    block = lsp.spike_timing_cell("Ahri", "L2", "none", (), "SR")
    assert block == {
        "next_kind": "level", "next_threshold": 6, "next_label": "R unlock",
        "crossed_dps_at": 51.2346, "spike_verdict": "play_for_spike",
    }


# --------------------------------------------------------------------------- #
# S144-D-193 - lookup returns {} on an unhashable key
# --------------------------------------------------------------------------- #
_PAYLOAD = {
    "scenarios": {"Ahri": {"Zed": {"L6": {"low": {"all_up": {
        "none": {"verdict": "trade"},
    }}}}}},
}


@pytest.mark.parametrize("pos", range(6))
def test_d193_unhashable_key_returns_empty(pos):
    args = ["Ahri", "Zed", "L6", "low", "all_up", "none"]
    args[pos] = ["unhashable"]
    out = lsp.lookup(_PAYLOAD, *args)
    # item_state falls back to the "none" cell; every other key is a miss.
    assert out == ({"verdict": "trade"} if pos == 5 else {})


def test_d193_control_hit():
    assert lsp.lookup(_PAYLOAD, "Ahri", "Zed", "L6", "low", "all_up") == {"verdict": "trade"}
