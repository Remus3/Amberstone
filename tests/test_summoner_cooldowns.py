"""Tests for core.summoner_cooldowns - the cooldown ledger backend."""

from __future__ import annotations

import pytest

from core.summoner_cooldowns import (
    COSMIC_INSIGHT_RUNE_ID,
    IONIAN_BOOTS_LUCIDITY_ITEM_ID,
    MAGICAL_FOOTWEAR_RUNE_ID,
    SUMMONER_SPELL_BASE_CD,
    _cdr_summs,
    _cdr_ult,
    _effective_cd,
    compute_cooldowns,
)


def _p(idx: int, **overrides) -> dict:
    """Minimal participant fixture, override per test."""
    base = {
        "puuid": f"puuid-{idx}",
        "summoner_name": f"Player{idx}",
        "champion_id": 100 + idx,
        "side": "blue" if idx < 5 else "red",
        "d_spell_id": 4,   # Flash
        "f_spell_id": 14,  # Ignite
        "ult_id": 999,
        "ult_base_cd": 120.0,
        "runes": [],
        "items": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Base CDR identity
# ---------------------------------------------------------------------------

def test_base_cds_match_spec():
    """Each named spell has the documented patch-16.10 base CD."""
    assert SUMMONER_SPELL_BASE_CD[4] == 300.0   # Flash
    assert SUMMONER_SPELL_BASE_CD[7] == 240.0   # Heal
    assert SUMMONER_SPELL_BASE_CD[14] == 180.0  # Ignite
    assert SUMMONER_SPELL_BASE_CD[11] == 90.0   # Smite
    assert SUMMONER_SPELL_BASE_CD[12] == 360.0  # Teleport
    assert SUMMONER_SPELL_BASE_CD[1] == 210.0   # Cleanse
    assert SUMMONER_SPELL_BASE_CD[21] == 180.0  # Barrier
    assert SUMMONER_SPELL_BASE_CD[3] == 210.0   # Exhaust
    assert SUMMONER_SPELL_BASE_CD[6] == 210.0   # Ghost
    assert SUMMONER_SPELL_BASE_CD[13] == 240.0  # Clarity


def test_base_cdr_zero_no_runes_no_items():
    """No Cosmic Insight + no Ionian boots => 0 percent CDR."""
    assert _cdr_summs([], []) == 0.0
    assert _cdr_ult([]) == 0.0


# ---------------------------------------------------------------------------
# Cosmic Insight: -18 percent
# ---------------------------------------------------------------------------

def test_cosmic_insight_summs_only():
    """Cosmic Insight (rune 8347) reduces summoner CDs by 18 percent."""
    cdr = _cdr_summs([COSMIC_INSIGHT_RUNE_ID], [])
    assert cdr == pytest.approx(0.18, abs=1e-9)
    # Cosmic does NOT touch the ultimate.
    assert _cdr_ult([]) == 0.0


def test_cosmic_insight_applied_to_flash():
    """Flash cd 300 -> 246 with Cosmic Insight."""
    ps = [_p(0, runes=[COSMIC_INSIGHT_RUNE_ID])]
    out = compute_cooldowns(ps, events=[], now_s=0.0)
    # READY spell (never cast) reports 0 remaining but ready_at_s == 0;
    # to verify the effective CD we cast Flash at t=0 and read it back.
    events = [
        {"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
         "summonerSpellId": 4, "gameTime": 0.0},
    ]
    out2 = compute_cooldowns(ps, events, now_s=0.0)
    assert out2[0]["summs"]["d_ready_at_s"] == pytest.approx(246.0, abs=1e-6)
    # Sanity: without Cosmic the same flash is ready at 300.
    out_no = compute_cooldowns([_p(0)], events, now_s=0.0)
    assert out_no[0]["summs"]["d_ready_at_s"] == pytest.approx(300.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Lucidity boots: -10 percent
# ---------------------------------------------------------------------------

def test_lucidity_summs_only():
    """Ionian Boots (item 3158) alone => -10 percent on summs."""
    assert _cdr_summs([], [IONIAN_BOOTS_LUCIDITY_ITEM_ID]) == pytest.approx(0.10, abs=1e-9)


def test_lucidity_ult_only():
    """Ionian Boots also reduces ult CD by 10 percent."""
    assert _cdr_ult([IONIAN_BOOTS_LUCIDITY_ITEM_ID]) == pytest.approx(0.10, abs=1e-9)
    assert _cdr_ult([]) == 0.0


def test_lucidity_applied_to_flash():
    """Flash 300 -> 270 with Lucidity boots."""
    events = [{"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
               "summonerSpellId": 4, "gameTime": 0.0}]
    ps = [_p(0, items=[IONIAN_BOOTS_LUCIDITY_ITEM_ID])]
    out = compute_cooldowns(ps, events, now_s=0.0)
    assert out[0]["summs"]["d_ready_at_s"] == pytest.approx(270.0, abs=1e-6)


def test_lucidity_applied_to_ult():
    """Ult 120 -> 108 with Lucidity boots."""
    events = [{"type": "ULTIMATE_USED", "puuid": "puuid-0", "gameTime": 0.0}]
    ps = [_p(0, items=[IONIAN_BOOTS_LUCIDITY_ITEM_ID])]
    out = compute_cooldowns(ps, events, now_s=0.0)
    assert out[0]["ult"]["ready_at_s"] == pytest.approx(108.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Stacking: Cosmic + Lucidity = -28 percent (ADDITIVE)
# ---------------------------------------------------------------------------

def test_stacking_cosmic_and_lucidity_additive():
    """Cosmic (18) + Lucidity (10) = 28 percent, NOT multiplicative."""
    cdr = _cdr_summs([COSMIC_INSIGHT_RUNE_ID], [IONIAN_BOOTS_LUCIDITY_ITEM_ID])
    assert cdr == pytest.approx(0.28, abs=1e-9)
    # Multiplicative would be 1 - (1-0.18)*(1-0.10) = 0.262
    # We assert the additive value, not the multiplicative one.
    assert cdr != pytest.approx(0.262, abs=1e-3)


def test_stacking_applied_to_flash():
    """Flash 300 -> 216 with Cosmic+Lucidity (300 * 0.72)."""
    events = [{"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
               "summonerSpellId": 4, "gameTime": 0.0}]
    ps = [_p(0,
              runes=[COSMIC_INSIGHT_RUNE_ID],
              items=[IONIAN_BOOTS_LUCIDITY_ITEM_ID])]
    out = compute_cooldowns(ps, events, now_s=0.0)
    assert out[0]["summs"]["d_ready_at_s"] == pytest.approx(216.0, abs=1e-6)


def test_stacking_with_magical_footwear():
    """Cosmic + Magical Footwear rune + boots itemized => 0.18+0.10+0.10=0.38."""
    cdr = _cdr_summs(
        [COSMIC_INSIGHT_RUNE_ID, MAGICAL_FOOTWEAR_RUNE_ID],
        [IONIAN_BOOTS_LUCIDITY_ITEM_ID],
    )
    assert cdr == pytest.approx(0.38, abs=1e-9)


def test_magical_footwear_rune_alone_no_cdr():
    """Magical Footwear rune WITHOUT the boots purchased gives 0 CDR.

    The rune grants free boots later but the CDR only fires once the
    item shows up in the inventory.
    """
    cdr = _cdr_summs([MAGICAL_FOOTWEAR_RUNE_ID], [])
    assert cdr == 0.0


# ---------------------------------------------------------------------------
# Used spell: ready_at = used_at + eff_cd; remaining = max(0, ready - now)
# ---------------------------------------------------------------------------

def test_used_spell_remaining_in_flight():
    """Flash cast at t=100, now_s=200 -> remaining=200 (300-100)."""
    events = [{"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
               "summonerSpellId": 4, "gameTime": 100.0}]
    out = compute_cooldowns([_p(0)], events, now_s=200.0)
    s = out[0]["summs"]
    assert s["d_used_at_s"] == pytest.approx(100.0, abs=1e-6)
    assert s["d_ready_at_s"] == pytest.approx(400.0, abs=1e-6)
    assert s["d_cd_remaining_s"] == pytest.approx(200.0, abs=1e-6)


def test_used_spell_back_up_after_cd():
    """Flash cast at t=0, now_s=400 -> remaining clamped to 0."""
    events = [{"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
               "summonerSpellId": 4, "gameTime": 0.0}]
    out = compute_cooldowns([_p(0)], events, now_s=400.0)
    assert out[0]["summs"]["d_cd_remaining_s"] == 0.0


def test_recast_takes_latest_timestamp():
    """Smite cast at t=50 AND t=150: latest wins for ready_at."""
    events = [
        {"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
         "summonerSpellId": 11, "gameTime": 50.0},
        {"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
         "summonerSpellId": 11, "gameTime": 150.0},
    ]
    ps = [_p(0, d_spell_id=11)]  # Smite on D
    out = compute_cooldowns(ps, events, now_s=160.0)
    # Smite base 90; ready at 150+90=240; now 160 -> 80 remaining.
    assert out[0]["summs"]["d_ready_at_s"] == pytest.approx(240.0, abs=1e-6)
    assert out[0]["summs"]["d_cd_remaining_s"] == pytest.approx(80.0, abs=1e-6)


def test_event_matches_by_summoner_name_when_no_puuid():
    """Live-client events without puuid match on summoner_name."""
    events = [{"type": "SUMMONER_SPELL_USED", "summonerName": "Player0",
               "summonerSpellId": 4, "gameTime": 50.0}]
    ps = [_p(0)]
    out = compute_cooldowns(ps, events, now_s=100.0)
    assert out[0]["summs"]["d_used_at_s"] == 50.0


def test_event_does_not_leak_across_players():
    """Player0's Flash cast does NOT mark Player1's Flash on cooldown."""
    events = [{"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
               "summonerSpellId": 4, "gameTime": 0.0}]
    out = compute_cooldowns([_p(0), _p(1)], events, now_s=100.0)
    p0 = next(r for r in out if r["puuid"] == "puuid-0")
    p1 = next(r for r in out if r["puuid"] == "puuid-1")
    assert p0["summs"]["d_used_at_s"] == 0.0
    assert p1["summs"]["d_used_at_s"] is None
    assert p1["summs"]["d_cd_remaining_s"] == 0.0


# ---------------------------------------------------------------------------
# Sort: ready first, then ascending next-up CD
# ---------------------------------------------------------------------------

def test_sort_ready_spells_bubble_to_top():
    """3 players engineered so the min next-up timer differentiates them.

    To make the sort deterministic each player must have ALL THREE
    spells (D, F, ult) on cooldown, otherwise the untouched spell's
    cd_remaining_s=0 wins the min and everyone ties at 0.
    """
    events = [
        # p0: Flash 250, Ignite 100, ult 100 -> min=100
        {"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
         "summonerSpellId": 4, "gameTime": 0.0},
        {"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
         "summonerSpellId": 14, "gameTime": 30.0},
        {"type": "ULTIMATE_USED", "puuid": "puuid-0", "gameTime": 30.0},
        # p1: Flash 50, Ignite 80, ult 70 -> min=50 (lowest, wins)
        {"type": "SUMMONER_SPELL_USED", "puuid": "puuid-1",
         "summonerSpellId": 4, "gameTime": 0.0},
        {"type": "SUMMONER_SPELL_USED", "puuid": "puuid-1",
         "summonerSpellId": 14, "gameTime": 50.0},
        {"type": "ULTIMATE_USED", "puuid": "puuid-1", "gameTime": 60.0},
        # p2: Flash 200, Ignite 120, ult 110 -> min=110
        {"type": "SUMMONER_SPELL_USED", "puuid": "puuid-2",
         "summonerSpellId": 4, "gameTime": 50.0},
        {"type": "SUMMONER_SPELL_USED", "puuid": "puuid-2",
         "summonerSpellId": 14, "gameTime": 100.0},
        {"type": "ULTIMATE_USED", "puuid": "puuid-2", "gameTime": 110.0},
    ]
    out = compute_cooldowns(
        [_p(0, ult_base_cd=120.0),
         _p(1, ult_base_cd=120.0),
         _p(2, ult_base_cd=120.0)],
        events,
        now_s=130.0,
    )
    # min remaining: p0=100 (Ignite 180-100=80? lets compute) actually:
    # at now=130: p0 Flash ready_at=300, remaining=170; Ignite ready=210,
    # remaining=80; ult ready=150, remaining=20. min=20.
    # p1: Flash ready=300, remaining=170; Ignite ready=230, remaining=100;
    # ult ready=180, remaining=50. min=50.
    # p2: Flash ready=350, remaining=220; Ignite ready=280, remaining=150;
    # ult ready=230, remaining=100. min=100.
    # Expected order: p0 (20), p1 (50), p2 (100).
    assert out[0]["puuid"] == "puuid-0"
    assert out[1]["puuid"] == "puuid-1"
    assert out[2]["puuid"] == "puuid-2"


def test_sort_ready_at_top_then_ascending():
    """A player with everything ready beats one with anything on CD."""
    events = [
        # p0 has Flash on long CD; ult and Ignite untouched (ready).
        {"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
         "summonerSpellId": 4, "gameTime": 100.0},
        # p1 has Flash AND Ignite AND ult all freshly cast.
        {"type": "SUMMONER_SPELL_USED", "puuid": "puuid-1",
         "summonerSpellId": 4, "gameTime": 100.0},
        {"type": "SUMMONER_SPELL_USED", "puuid": "puuid-1",
         "summonerSpellId": 14, "gameTime": 100.0},
        {"type": "ULTIMATE_USED", "puuid": "puuid-1", "gameTime": 100.0},
    ]
    # now=110: p0 Ignite ready, ult ready -> min=0. p1 nothing ready.
    out = compute_cooldowns(
        [_p(0, ult_base_cd=120.0), _p(1, ult_base_cd=120.0)],
        events,
        now_s=110.0,
    )
    assert out[0]["puuid"] == "puuid-0"
    assert out[1]["puuid"] == "puuid-1"


def test_sort_uses_min_across_d_f_ult():
    """Player with ult ready beats a player whose summs are all on long CD."""
    events = [
        # p0 used Flash AND Ignite recently (both on long CD), ult ready.
        {"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
         "summonerSpellId": 4, "gameTime": 100.0},
        {"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
         "summonerSpellId": 14, "gameTime": 100.0},
        # p1 ult on long CD, but Flash ready.
        {"type": "ULTIMATE_USED", "puuid": "puuid-1", "gameTime": 100.0},
    ]
    # ult_base_cd 120; now=110 -> p1 ult remaining 110.
    # p0 Flash remaining 290, Ignite remaining 170, ult ready (0). Min=0.
    # p1 Flash 0, Ignite 0, ult 110. Min=0.
    out = compute_cooldowns(
        [_p(0, ult_base_cd=120.0), _p(1, ult_base_cd=120.0)],
        events,
        now_s=110.0,
    )
    # Both have a 0 in the min; stable sort by original idx -> p0 first.
    assert out[0]["puuid"] == "puuid-0"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_participants_returns_empty():
    """No players -> empty list, regardless of events / now_s."""
    assert compute_cooldowns([], [], now_s=0.0) == []
    assert compute_cooldowns([], [{"type": "SUMMONER_SPELL_USED"}], now_s=999.0) == []


def test_unknown_spell_id_renders_zero_base():
    """Unknown spell id (e.g. removed Mark) renders 0 base; reads as ready."""
    ps = [_p(0, d_spell_id=32)]  # Mark (deprecated)
    out = compute_cooldowns(ps, [], now_s=0.0)
    assert out[0]["summs"]["d_cd_remaining_s"] == 0.0


def test_helper_effective_cd_extremes():
    """CDR fraction edge cases: 0, 1.0, negative, > 1.0."""
    assert _effective_cd(300.0, 0.0) == 300.0
    assert _effective_cd(300.0, 1.0) == 0.0
    assert _effective_cd(300.0, 1.5) == 0.0  # clamp
    # Negative CDR is treated as 0 by the helper.
    assert _effective_cd(300.0, -0.5) == 300.0


def test_payload_shape_matches_spec():
    """Returned row has the exact keys the spec calls for."""
    out = compute_cooldowns([_p(0)], [], now_s=0.0)
    row = out[0]
    assert set(row.keys()) == {"puuid", "summoner_name", "champion_id",
                                "side", "summs", "ult"}
    s = row["summs"]
    assert set(s.keys()) == {
        "d_id", "d_name", "d_used_at_s", "d_ready_at_s", "d_cd_remaining_s",
        "f_id", "f_name", "f_used_at_s", "f_ready_at_s", "f_cd_remaining_s",
    }
    u = row["ult"]
    assert set(u.keys()) == {"id", "used_at_s", "ready_at_s", "cd_remaining_s"}
    # d_name is human-readable for the panel.
    assert s["d_name"] == "Flash"
    assert s["f_name"] == "Ignite"


def test_ten_participants_full_render():
    """Smoke: 10-player game renders 10 rows, all sortable."""
    ps = [_p(i) for i in range(10)]
    out = compute_cooldowns(ps, [], now_s=0.0)
    assert len(out) == 10
    # All idle => all sort to 0 remaining; order should be stable on idx.
    for r, original_idx in zip(out, range(10)):
        assert r["puuid"] == f"puuid-{original_idx}"
