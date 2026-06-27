"""Seam-flag forwarding tests for core.daemon_slayer_client.

Tier-2 DS build (Client Agent B). These tests mock the HTTP transport
(``_post_json``) so they never touch the live :8893 server. They assert
two properties for every rank_* helper plus rank_for_primary_archetype:

  1. BEHAVIOR-PRESERVING: a call that passes no seam flags produces a
     JSON body byte-identical (key-for-key) to today - i.e. none of the
     new seam keys appear when left at their OFF/null/0.0 defaults.
  2. FORWARDING: when a seam flag is set, the matching body key appears
     with the supplied value, routed to the correct archetype branch only.

Seam flag body-key names (EXACT, shared across server/client/dispatch):
  - exempt_offclass_by_win   bool   default False   (carry /rank)
  - prefer_kit_axis_by_win   bool   default False   (carry /rank + /rank-assassin)
  - cost_ceiling             int|None default None  (/rank + /rank-tank + /rank-bruiser)
  - prefer_survivability_by_win bool default False  (bruiser /rank-bruiser + tank /rank-tank + enchanter /rank-enchanter)
  - assume_magic_burst       bool   default False   (assassin /rank-assassin)
  - assume_passive_as_stacks bool   default False   (carry /rank)
  - apply_target_vuln        bool   default False   (carry /rank)
  - assume_missing_hp_heal_amp bool default False   (enchanter /rank-enchanter)
  - caster_missing_hp_pct    float  default 0.0     (enchanter /rank-enchanter)
"""

from __future__ import annotations

import pytest

from core import daemon_slayer_client as ds


# All seam-flag body keys. A baseline (no-flag) call MUST emit none of these.
SEAM_KEYS = frozenset({
    "exempt_offclass_by_win",
    "prefer_kit_axis_by_win",
    "cost_ceiling",
    "prefer_survivability_by_win",
    "assume_magic_burst",
    "assume_passive_as_stacks",
    "apply_target_vuln",
    "assume_missing_hp_heal_amp",
    "caster_missing_hp_pct",
})


@pytest.fixture
def captured(monkeypatch):
    """Monkeypatch _post_json to record (path, body) and return a minimal
    engine-ok payload so the helper parses an empty ranked list."""
    calls: list[tuple[str, dict]] = []

    def fake_post(path, body, timeout=ds.DEFAULT_TIMEOUT):
        calls.append((path, dict(body)))
        return {"ranked": []}

    monkeypatch.setattr(ds, "_post_json", fake_post)
    return calls


def _baseline(captured, fn, **kwargs):
    """Call fn with no seam flags; return the single captured body."""
    captured.clear()
    fn("Ashe", level=11, item_ids=["1001"], **kwargs)
    assert len(captured) == 1
    return captured[0][1]


# ---------------------------------------------------------------------------
# Baseline byte-identity: no seam flag set -> body carries zero seam keys.
# ---------------------------------------------------------------------------

def test_rank_for_baseline_no_seam_keys(captured):
    body = _baseline(captured, ds.rank_for)
    assert SEAM_KEYS.isdisjoint(body.keys())


def test_rank_tank_for_baseline_no_seam_keys(captured):
    body = _baseline(captured, ds.rank_tank_for)
    assert SEAM_KEYS.isdisjoint(body.keys())


def test_rank_bruiser_for_baseline_no_seam_keys(captured):
    body = _baseline(captured, ds.rank_bruiser_for)
    assert SEAM_KEYS.isdisjoint(body.keys())


def test_rank_assassin_for_baseline_no_seam_keys(captured):
    body = _baseline(captured, ds.rank_assassin_for)
    assert SEAM_KEYS.isdisjoint(body.keys())


def test_rank_enchanter_for_baseline_no_seam_keys(captured):
    body = _baseline(captured, ds.rank_enchanter_for)
    assert SEAM_KEYS.isdisjoint(body.keys())


# ---------------------------------------------------------------------------
# Carry / rank_for: DSP2, DSP11, F2, R7, R12.
# ---------------------------------------------------------------------------

def test_rank_for_forwards_carry_flags(captured):
    captured.clear()
    ds.rank_for(
        "Ashe", level=11, item_ids=["1001"],
        exempt_offclass_by_win=True,
        prefer_kit_axis_by_win=True,
        cost_ceiling=3000,
        assume_passive_as_stacks=True,
        apply_target_vuln=True,
    )
    body = captured[0][1]
    assert body["exempt_offclass_by_win"] is True
    assert body["prefer_kit_axis_by_win"] is True
    assert body["cost_ceiling"] == 3000
    assert body["assume_passive_as_stacks"] is True
    assert body["apply_target_vuln"] is True


def test_rank_for_cost_ceiling_zero_is_emitted(captured):
    # cost_ceiling default is None; an explicit 0 is a non-null value and
    # must be emitted (only None means "unset").
    captured.clear()
    ds.rank_for("Ashe", level=11, item_ids=["1001"], cost_ceiling=0)
    body = captured[0][1]
    assert body["cost_ceiling"] == 0


def test_rank_for_off_flags_absent(captured):
    # An explicit False / None for every carry flag must NOT add keys.
    captured.clear()
    ds.rank_for(
        "Ashe", level=11, item_ids=["1001"],
        exempt_offclass_by_win=False,
        prefer_kit_axis_by_win=False,
        cost_ceiling=None,
        assume_passive_as_stacks=False,
        apply_target_vuln=False,
    )
    body = captured[0][1]
    assert SEAM_KEYS.isdisjoint(body.keys())


# ---------------------------------------------------------------------------
# Tank / rank_tank_for: RF3 (prefer_survivability_by_win) + F2 (cost_ceiling).
# ---------------------------------------------------------------------------

def test_rank_tank_for_forwards_flags(captured):
    captured.clear()
    ds.rank_tank_for(
        "Malphite", level=11, item_ids=["1001"],
        prefer_survivability_by_win=True,
        cost_ceiling=2500,
    )
    body = captured[0][1]
    assert body["prefer_survivability_by_win"] is True
    assert body["cost_ceiling"] == 2500


# ---------------------------------------------------------------------------
# Bruiser / rank_bruiser_for: RF1 (prefer_survivability_by_win) + F2.
# ---------------------------------------------------------------------------

def test_rank_bruiser_for_forwards_flags(captured):
    captured.clear()
    ds.rank_bruiser_for(
        "Sett", level=11, item_ids=["1001"],
        prefer_survivability_by_win=True,
        cost_ceiling=2800,
    )
    body = captured[0][1]
    assert body["prefer_survivability_by_win"] is True
    assert body["cost_ceiling"] == 2800


# ---------------------------------------------------------------------------
# Assassin / rank_assassin_for: DSP11 (prefer_kit_axis_by_win) + R30
# (assume_magic_burst).
# ---------------------------------------------------------------------------

def test_rank_assassin_for_forwards_flags(captured):
    captured.clear()
    ds.rank_assassin_for(
        "Zed", level=11, item_ids=["1001"],
        prefer_kit_axis_by_win=True,
        assume_magic_burst=True,
    )
    body = captured[0][1]
    assert body["prefer_kit_axis_by_win"] is True
    assert body["assume_magic_burst"] is True


# ---------------------------------------------------------------------------
# Enchanter / rank_enchanter_for: RF2 (prefer_survivability_by_win) + R5
# (assume_missing_hp_heal_amp + caster_missing_hp_pct).
# ---------------------------------------------------------------------------

def test_rank_enchanter_for_forwards_flags(captured):
    captured.clear()
    ds.rank_enchanter_for(
        "Soraka", level=11, item_ids=["1001"],
        prefer_survivability_by_win=True,
        assume_missing_hp_heal_amp=True,
        caster_missing_hp_pct=0.5,
    )
    body = captured[0][1]
    assert body["prefer_survivability_by_win"] is True
    assert body["assume_missing_hp_heal_amp"] is True
    assert body["caster_missing_hp_pct"] == 0.5


def test_rank_enchanter_for_caster_missing_hp_zero_absent(captured):
    # caster_missing_hp_pct default 0.0 means "no signal" -> not emitted.
    captured.clear()
    ds.rank_enchanter_for("Soraka", level=11, item_ids=["1001"])
    body = captured[0][1]
    assert "caster_missing_hp_pct" not in body
    assert "assume_missing_hp_heal_amp" not in body


# ---------------------------------------------------------------------------
# rank_for_primary_archetype routes each flag to the correct branch only.
# ---------------------------------------------------------------------------

def test_dispatcher_carry_routes_carry_flags(captured):
    captured.clear()
    ds.rank_for_primary_archetype(
        "Ashe", "carry", level=11, item_ids=["1001"],
        exempt_offclass_by_win=True,
        assume_passive_as_stacks=True,
        apply_target_vuln=True,
        cost_ceiling=3000,
    )
    path, body = captured[0]
    assert path == "/rank"
    assert body["exempt_offclass_by_win"] is True
    assert body["assume_passive_as_stacks"] is True
    assert body["apply_target_vuln"] is True
    assert body["cost_ceiling"] == 3000


def test_dispatcher_assassin_routes_assassin_flags(captured):
    captured.clear()
    ds.rank_for_primary_archetype(
        "Zed", "assassin", level=11, item_ids=["1001"],
        assume_magic_burst=True,
        prefer_kit_axis_by_win=True,
    )
    path, body = captured[0]
    assert path == "/rank-assassin"
    assert body["assume_magic_burst"] is True
    assert body["prefer_kit_axis_by_win"] is True


def test_dispatcher_enchanter_routes_r5(captured):
    captured.clear()
    ds.rank_for_primary_archetype(
        "Soraka", "enchanter", level=11, item_ids=["1001"],
        assume_missing_hp_heal_amp=True,
        caster_missing_hp_pct=0.93,
        prefer_survivability_by_win=True,
    )
    path, body = captured[0]
    assert path == "/rank-enchanter"
    assert body["assume_missing_hp_heal_amp"] is True
    assert body["caster_missing_hp_pct"] == pytest.approx(0.93)
    assert body["prefer_survivability_by_win"] is True


def test_dispatcher_tank_routes_survivability_and_cost(captured):
    captured.clear()
    ds.rank_for_primary_archetype(
        "Malphite", "tank", level=11, item_ids=["1001"],
        prefer_survivability_by_win=True,
        cost_ceiling=2500,
    )
    path, body = captured[0]
    assert path == "/rank-tank"
    assert body["prefer_survivability_by_win"] is True
    assert body["cost_ceiling"] == 2500


def test_dispatcher_bruiser_routes_survivability_and_cost(captured):
    captured.clear()
    ds.rank_for_primary_archetype(
        "Sett", "bruiser", level=11, item_ids=["1001"],
        prefer_survivability_by_win=True,
        cost_ceiling=2800,
    )
    path, body = captured[0]
    assert path == "/rank-bruiser"
    assert body["prefer_survivability_by_win"] is True
    assert body["cost_ceiling"] == 2800


def test_dispatcher_baseline_no_seam_keys_all_archetypes(captured):
    # A flagless dispatch for every archetype must produce a body with no
    # seam keys at all - byte-identical to pre-seam behavior.
    for arch in ("carry", "tank", "bruiser", "assassin", "enchanter", "mage"):
        captured.clear()
        ds.rank_for_primary_archetype(
            "Ahri", arch, level=11, item_ids=["1001"],
        )
        assert captured, f"no call captured for {arch}"
        _, body = captured[0]
        assert SEAM_KEYS.isdisjoint(body.keys()), (
            f"{arch} emitted seam keys at baseline: "
            f"{SEAM_KEYS & set(body.keys())}"
        )
