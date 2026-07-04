"""Seam-flag forwarding tests for coach_integration.archetype_dispatch.

Tier-2 DS build (Client Agent B). These tests mock the engine call
(``core.daemon_slayer_client.rank_for_primary_archetype``) so they never
touch the live :8893 server. They assert dispatch_for_coach:

  1. forwards each seam flag verbatim to rank_for_primary_archetype,
  2. converts caster HP -> caster_missing_hp_pct = max(0, min(1, 1 - hp/hp_max)),
  3. guards absent / zero-max HP to caster_missing_hp_pct 0.0 (flag OFF),
  4. stays behavior-preserving: a flagless call adds no seam kwargs.
"""

from __future__ import annotations

import pytest

from coach_integration import archetype_dispatch as ad
from coach_integration.enemy_stats import EnemyStats
from core import daemon_slayer_client as ds


def _enemy():
    return EnemyStats(armor=50.0, mr=40.0, max_hp=2000.0, bonus_hp=500.0)


@pytest.fixture
def captured_kwargs(monkeypatch):
    """Capture the kwargs dispatch_for_coach passes to the engine and
    return a minimal engine-ok dict so the dispatcher builds a result."""
    seen: dict = {}

    def fake_rank(**kwargs):
        seen.clear()
        seen.update(kwargs)
        return {
            "ok": True,
            "scorer": "dps",
            "archetype": kwargs.get("archetype", "carry"),
            "ranked": [],
            "fell_back": False,
        }

    monkeypatch.setattr(ds, "rank_for_primary_archetype", fake_rank)
    # Pin archetype to a deterministic value so the test is comp-agnostic.
    monkeypatch.setattr(
        ad, "get_archetype_for", lambda *_a, **_k: {"primary": "enchanter"},
        raising=False,
    )
    return seen


# Some installs resolve get_archetype_for via a local import inside
# dispatch_for_coach (from core.archetype_picks import get_archetype_for).
# Patch that source too so the monkeypatch lands regardless of binding.
@pytest.fixture(autouse=True)
def _pin_archetype(monkeypatch):
    import core.archetype_picks as picks
    monkeypatch.setattr(
        picks, "get_archetype_for",
        lambda *_a, **_k: {"primary": "enchanter"},
        raising=False,
    )


def test_dispatch_forwards_seam_flags(captured_kwargs):
    ad.dispatch_for_coach(
        "Soraka",
        mode_engine="SR",
        level=11,
        item_ids=["1001"],
        enemy_stats=_enemy(),
        exempt_offclass_by_win=True,
        prefer_kit_axis_by_win=True,
        cost_ceiling=3000,
        prefer_survivability_by_win=True,
        assume_magic_burst=True,
        assume_passive_as_stacks=True,
        apply_target_vuln=True,
        assume_missing_hp_heal_amp=True,
    )
    assert captured_kwargs["exempt_offclass_by_win"] is True
    assert captured_kwargs["prefer_kit_axis_by_win"] is True
    assert captured_kwargs["cost_ceiling"] == 3000
    assert captured_kwargs["prefer_survivability_by_win"] is True
    assert captured_kwargs["assume_magic_burst"] is True
    assert captured_kwargs["assume_passive_as_stacks"] is True
    assert captured_kwargs["apply_target_vuln"] is True
    assert captured_kwargs["assume_missing_hp_heal_amp"] is True


def test_dispatch_r5_missing_hp_conversion(captured_kwargs):
    # hp=7% of max -> caster_missing_hp_pct ~= 0.93.
    ad.dispatch_for_coach(
        "Soraka",
        mode_engine="SR",
        level=11,
        item_ids=["1001"],
        enemy_stats=_enemy(),
        caster_hp=70.0,
        caster_hp_max=1000.0,
    )
    assert captured_kwargs["caster_missing_hp_pct"] == pytest.approx(0.93)


def test_dispatch_absent_hp_guard_off(captured_kwargs):
    # hp_max=0 -> guard yields 0.0 and the key is NOT forwarded (default).
    ad.dispatch_for_coach(
        "Soraka",
        mode_engine="SR",
        level=11,
        item_ids=["1001"],
        enemy_stats=_enemy(),
        caster_hp=70.0,
        caster_hp_max=0.0,
    )
    assert captured_kwargs.get("caster_missing_hp_pct", 0.0) == 0.0
    assert "caster_missing_hp_pct" not in captured_kwargs


def test_dispatch_no_hp_args_forwards_only_kit_axis_default(captured_kwargs):
    # Flagless, HP-less call. Since the C4 flip (2026-07-04) prefer_kit_axis_by_win
    # (DSP11) defaults ON, so a flagless dispatch forwards it =True (the live
    # build-chooser floats a champ's WIN-anchored kit-axis items). EVERY OTHER
    # seam stays default-OFF (byte-identical to pre-seam dispatch).
    ad.dispatch_for_coach(
        "Soraka",
        mode_engine="SR",
        level=11,
        item_ids=["1001"],
        enemy_stats=_enemy(),
    )
    # C4 default-ON: prefer_kit_axis_by_win IS forwarded on a flagless call.
    assert captured_kwargs["prefer_kit_axis_by_win"] is True
    # All other seams remain default-OFF - not forwarded.
    still_off = {
        "exempt_offclass_by_win", "cost_ceiling",
        "prefer_survivability_by_win", "assume_magic_burst",
        "assume_passive_as_stacks", "apply_target_vuln",
        "assume_missing_hp_heal_amp", "caster_missing_hp_pct",
    }
    assert still_off.isdisjoint(captured_kwargs.keys())


def test_dispatch_full_hp_no_missing_pct(captured_kwargs):
    # caster at full HP -> missing pct 0.0 -> not forwarded.
    ad.dispatch_for_coach(
        "Soraka",
        mode_engine="SR",
        level=11,
        item_ids=["1001"],
        enemy_stats=_enemy(),
        caster_hp=1000.0,
        caster_hp_max=1000.0,
    )
    assert "caster_missing_hp_pct" not in captured_kwargs
