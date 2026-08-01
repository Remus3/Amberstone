"""RM-04 A-01c: widen_carry_pool must reach the LIVE per-tick coach path.

Item A-01b wired ``widen_carry_pool`` through
``core.daemon_slayer_client.rank_for`` / ``rank_for_primary_archetype``,
but ``coach_integration.archetype_dispatch.dispatch_for_coach`` assembles
an EXPLICIT whitelist kwargs dict, so a coach had no way to turn the seam
on. These tests pin the dispatcher half of the seam:

  1. DEFAULT-OFF: a flagless dispatch emits NO ``widen_carry_pool`` key
     (byte-identical to pre-seam behavior, mirroring every other seam),
  2. opt-in: ``widen_carry_pool=True`` forwards the key verbatim,
  3. the flag composes with the neighbouring carry seams.

The engine call is mocked - these never touch the live DS :8860 server.
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
    """Capture the kwargs dispatch_for_coach passes to the engine."""
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
    return seen


@pytest.fixture(autouse=True)
def _pin_archetype(monkeypatch):
    """Pin the archetype to carry - widen_carry_pool is CARRY-ONLY."""
    import core.archetype_picks as picks

    monkeypatch.setattr(
        picks, "get_archetype_for",
        lambda *_a, **_k: {"primary": "carry"},
        raising=False,
    )
    monkeypatch.setattr(
        ad, "get_archetype_for",
        lambda *_a, **_k: {"primary": "carry"},
        raising=False,
    )


def test_dispatch_signature_accepts_widen_carry_pool():
    """The seam is reachable from a coach at all (keyword-only, defaulted)."""
    import inspect

    sig = inspect.signature(ad.dispatch_for_coach)
    assert "widen_carry_pool" in sig.parameters
    param = sig.parameters["widen_carry_pool"]
    assert param.default is False
    assert param.kind is inspect.Parameter.KEYWORD_ONLY


def test_default_off_does_not_forward_widen_carry_pool(captured_kwargs):
    """DEFAULT-OFF: a flagless dispatch must not emit the body key."""
    result = ad.dispatch_for_coach(
        "Vayne",
        mode_engine="SR",
        level=11,
        item_ids=["1001"],
        enemy_stats=_enemy(),
    )
    assert result is not None
    assert "widen_carry_pool" not in captured_kwargs


def test_true_forwards_widen_carry_pool(captured_kwargs):
    """Opt-in: True reaches rank_for_primary_archetype verbatim."""
    result = ad.dispatch_for_coach(
        "Vayne",
        mode_engine="SR",
        level=11,
        item_ids=["1001"],
        enemy_stats=_enemy(),
        widen_carry_pool=True,
    )
    assert result is not None
    assert captured_kwargs["widen_carry_pool"] is True


def test_explicit_false_still_omits_key(captured_kwargs):
    """Explicit False is the same as omitting - no key, no behavior change."""
    ad.dispatch_for_coach(
        "Vayne",
        mode_engine="SR",
        level=11,
        item_ids=["1001"],
        enemy_stats=_enemy(),
        widen_carry_pool=False,
    )
    assert "widen_carry_pool" not in captured_kwargs


def test_composes_with_neighbouring_carry_seams(captured_kwargs):
    """The widen seam does not displace the other carry seam flags."""
    ad.dispatch_for_coach(
        "Vayne",
        mode_engine="SR",
        level=11,
        item_ids=["1001"],
        enemy_stats=_enemy(),
        exempt_offclass_by_win=True,
        assume_passive_as_stacks=True,
        apply_target_vuln=True,
        cost_ceiling=3000,
        widen_carry_pool=True,
    )
    assert captured_kwargs["widen_carry_pool"] is True
    assert captured_kwargs["exempt_offclass_by_win"] is True
    assert captured_kwargs["assume_passive_as_stacks"] is True
    assert captured_kwargs["apply_target_vuln"] is True
    assert captured_kwargs["cost_ceiling"] == 3000


def test_downstream_client_accepts_the_forwarded_kwarg():
    """The A-01b half: the dispatcher's target actually takes the kwarg."""
    import inspect

    sig = inspect.signature(ds.rank_for_primary_archetype)
    assert "widen_carry_pool" in sig.parameters
    assert sig.parameters["widen_carry_pool"].default is False
