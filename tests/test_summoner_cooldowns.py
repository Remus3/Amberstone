"""Tests for core.summoner_cooldowns - the cooldown ledger backend."""

from __future__ import annotations

import pytest

from core.summoner_cooldowns import (
    COSMIC_INSIGHT_RUNE_ID,
    COSMIC_INSIGHT_SSH,
    HEXTECH_DRAKE_AH_PER_STACK,
    IONIAN_BOOTS_LUCIDITY_ITEM_ID,
    LUCIDITY_AH,
    LUCIDITY_SSH,
    MAGICAL_FOOTWEAR_RUNE_ID,
    MAGICAL_FOOTWEAR_SSH,
    SUMMONER_SPELL_BASE_CD,
    _ability_haste,
    _effective_cd,
    _summoner_haste,
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


def _eff(base: float, haste: float) -> float:
    """Test-side mirror of the haste formula: base / (1 + h/100)."""
    return base / (1.0 + haste / 100.0)


# ---------------------------------------------------------------------------
# Base CDs + zero-haste identity
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


def test_haste_zero_no_runes_no_items():
    """No Cosmic Insight + no Ionian boots + no drakes => 0 haste both lanes."""
    assert _summoner_haste([], []) == 0.0
    assert _ability_haste([], hextech_drakes=0) == 0.0


# ---------------------------------------------------------------------------
# Cosmic Insight: +18 SSH (summoner spells only)
# ---------------------------------------------------------------------------

def test_cosmic_insight_summs_only():
    """Cosmic Insight rune adds 18 Summoner Spell Haste; ult unaffected."""
    h = _summoner_haste([COSMIC_INSIGHT_RUNE_ID], [])
    assert h == pytest.approx(COSMIC_INSIGHT_SSH, abs=1e-9)
    assert _ability_haste([]) == 0.0


def test_cosmic_insight_applied_to_flash():
    """Flash base 300 with 18 SSH -> 300 / 1.18 = ~254.24."""
    events = [{"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
               "summonerSpellId": 4, "gameTime": 0.0}]
    ps = [_p(0, runes=[COSMIC_INSIGHT_RUNE_ID])]
    out = compute_cooldowns(ps, events, now_s=0.0)
    assert out[0]["summs"]["d_ready_at_s"] == pytest.approx(_eff(300.0, 18), abs=1e-6)
    # Sanity: without Cosmic the same flash is ready at 300.
    out_no = compute_cooldowns([_p(0)], events, now_s=0.0)
    assert out_no[0]["summs"]["d_ready_at_s"] == pytest.approx(300.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Lucidity boots: +18 SSH on summoners + +12 AH on ult
# ---------------------------------------------------------------------------

def test_lucidity_summs_haste():
    """Ionian Boots alone => +18 SSH on summoner spells."""
    assert _summoner_haste([], [IONIAN_BOOTS_LUCIDITY_ITEM_ID]) == pytest.approx(LUCIDITY_SSH, abs=1e-9)


def test_lucidity_ult_haste():
    """Ionian Boots alone => +12 AH on the ultimate."""
    assert _ability_haste([IONIAN_BOOTS_LUCIDITY_ITEM_ID]) == pytest.approx(LUCIDITY_AH, abs=1e-9)
    assert _ability_haste([]) == 0.0


def test_lucidity_applied_to_flash():
    """Flash base 300 with 18 SSH -> 300 / 1.18 = ~254.24."""
    events = [{"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
               "summonerSpellId": 4, "gameTime": 0.0}]
    ps = [_p(0, items=[IONIAN_BOOTS_LUCIDITY_ITEM_ID])]
    out = compute_cooldowns(ps, events, now_s=0.0)
    assert out[0]["summs"]["d_ready_at_s"] == pytest.approx(_eff(300.0, 18), abs=1e-6)


def test_lucidity_applied_to_ult():
    """Ult base 120 with 12 AH -> 120 / 1.12 = ~107.14."""
    events = [{"type": "ULTIMATE_USED", "puuid": "puuid-0", "gameTime": 0.0}]
    ps = [_p(0, items=[IONIAN_BOOTS_LUCIDITY_ITEM_ID])]
    out = compute_cooldowns(ps, events, now_s=0.0)
    assert out[0]["ult"]["ready_at_s"] == pytest.approx(_eff(120.0, 12), abs=1e-6)


# ---------------------------------------------------------------------------
# Stacking: haste is additive in haste units; formula compresses the reduction
# ---------------------------------------------------------------------------

def test_stacking_cosmic_and_lucidity_haste_additive():
    """Cosmic 18 + Lucidity 18 = 36 SSH (not 36% reduction)."""
    h = _summoner_haste([COSMIC_INSIGHT_RUNE_ID], [IONIAN_BOOTS_LUCIDITY_ITEM_ID])
    assert h == pytest.approx(COSMIC_INSIGHT_SSH + LUCIDITY_SSH, abs=1e-9)


def test_stacking_applied_to_flash():
    """Flash base 300 with 36 SSH -> 300 / 1.36 = ~220.59.

    Pre-2026-05-20 the additive-percent model gave 300 * 0.72 = 216.0
    here; haste formula compresses high-stack scenarios so the effective
    CD is slightly higher (the percent model double-counts at scale).
    """
    events = [{"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
               "summonerSpellId": 4, "gameTime": 0.0}]
    ps = [_p(0,
              runes=[COSMIC_INSIGHT_RUNE_ID],
              items=[IONIAN_BOOTS_LUCIDITY_ITEM_ID])]
    out = compute_cooldowns(ps, events, now_s=0.0)
    expected = _eff(300.0, COSMIC_INSIGHT_SSH + LUCIDITY_SSH)
    assert out[0]["summs"]["d_ready_at_s"] == pytest.approx(expected, abs=1e-6)
    # Pin the absolute value too so a future change to the constants is loud.
    assert out[0]["summs"]["d_ready_at_s"] == pytest.approx(220.5882, abs=1e-3)


def test_stacking_with_magical_footwear():
    """Cosmic 18 + Lucidity 18 + Magical Footwear 10 = 46 SSH."""
    h = _summoner_haste(
        [COSMIC_INSIGHT_RUNE_ID, MAGICAL_FOOTWEAR_RUNE_ID],
        [IONIAN_BOOTS_LUCIDITY_ITEM_ID],
    )
    assert h == pytest.approx(COSMIC_INSIGHT_SSH + LUCIDITY_SSH + MAGICAL_FOOTWEAR_SSH, abs=1e-9)


def test_magical_footwear_rune_alone_no_haste():
    """Magical Footwear rune WITHOUT the boots purchased gives 0 haste.

    The rune grants free boots later but the haste boost only fires
    once the item shows up in the inventory.
    """
    assert _summoner_haste([MAGICAL_FOOTWEAR_RUNE_ID], []) == 0.0


# ---------------------------------------------------------------------------
# Hextech Drake stack (+5 AH per stack, ult only)
# ---------------------------------------------------------------------------

def test_hextech_drake_one_stack_ult_haste():
    """1 Hextech Drake stack = 5 AH; summoner spells unaffected."""
    assert _ability_haste([], hextech_drakes=1) == pytest.approx(HEXTECH_DRAKE_AH_PER_STACK, abs=1e-9)
    # Summoner spells aren't affected by ability haste sources.
    assert _summoner_haste([], []) == 0.0


def test_hextech_drake_stacks_linearly():
    """3 Hextech stacks = 15 AH (no soul-tier bonus reading from drakes int)."""
    assert _ability_haste([], hextech_drakes=3) == pytest.approx(
        3 * HEXTECH_DRAKE_AH_PER_STACK, abs=1e-9
    )


def test_hextech_drake_plus_lucidity_on_ult():
    """Boots 12 AH + 2 Hextech stacks 10 AH = 22 AH on ult.

    Ult base 120 with 22 AH -> 120 / 1.22 = ~98.36.
    """
    events = [{"type": "ULTIMATE_USED", "puuid": "puuid-0", "gameTime": 0.0}]
    ps = [_p(0, items=[IONIAN_BOOTS_LUCIDITY_ITEM_ID], hextech_drakes=2)]
    out = compute_cooldowns(ps, events, now_s=0.0)
    expected_h = LUCIDITY_AH + 2 * HEXTECH_DRAKE_AH_PER_STACK
    assert out[0]["ult"]["ready_at_s"] == pytest.approx(_eff(120.0, expected_h), abs=1e-6)
    assert out[0]["ult"]["ability_haste"] == pytest.approx(expected_h, abs=1e-9)


def test_hextech_drake_negative_clamped_to_zero():
    """Negative drake count shouldn't subtract haste; clamp at 0 stacks."""
    assert _ability_haste([], hextech_drakes=-3) == 0.0


# ---------------------------------------------------------------------------
# Used spell: ready_at = used_at + eff_cd; remaining = max(0, ready - now)
# ---------------------------------------------------------------------------

def test_used_spell_remaining_in_flight():
    """Flash cast at t=100, now_s=200, no haste -> remaining=200 (300-100)."""
    events = [{"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
               "summonerSpellId": 4, "gameTime": 100.0}]
    ps = [_p(0)]
    out = compute_cooldowns(ps, events, now_s=200.0)
    assert out[0]["summs"]["d_cd_remaining_s"] == pytest.approx(200.0, abs=1e-6)


def test_used_spell_back_up_after_cd():
    """Flash cast at t=0, now_s=400 -> remaining=0 (clamp; was already ready)."""
    events = [{"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
               "summonerSpellId": 4, "gameTime": 0.0}]
    out = compute_cooldowns([_p(0)], events, now_s=400.0)
    assert out[0]["summs"]["d_cd_remaining_s"] == 0.0


def test_recast_takes_latest_timestamp():
    """Multiple casts -> the latest sets the ready timer."""
    events = [
        {"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
         "summonerSpellId": 4, "gameTime": 50.0},
        {"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
         "summonerSpellId": 4, "gameTime": 350.0},
    ]
    out = compute_cooldowns([_p(0)], events, now_s=400.0)
    # ready_at = 350 + 300 = 650; remaining = 250.
    assert out[0]["summs"]["d_cd_remaining_s"] == pytest.approx(250.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Event matching
# ---------------------------------------------------------------------------

def test_event_matches_by_summoner_name_when_no_puuid():
    """Live-Client events lack puuid - fall back to summoner_name."""
    events = [{"type": "SUMMONER_SPELL_USED", "summonerName": "Player0",
               "summonerSpellId": 4, "gameTime": 100.0}]
    out = compute_cooldowns([_p(0, puuid=None)], events, now_s=200.0)
    assert out[0]["summs"]["d_cd_remaining_s"] == pytest.approx(200.0, abs=1e-6)


def test_event_does_not_leak_across_players():
    """Player0's Flash cast does NOT show on Player1's row."""
    events = [{"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
               "summonerSpellId": 4, "gameTime": 100.0}]
    out = compute_cooldowns([_p(0), _p(1)], events, now_s=200.0)
    # Player0 used at 100, now 200 -> remaining 200.
    assert out[0]["summs"]["d_cd_remaining_s"] == pytest.approx(200.0, abs=1e-6)
    # Player1 never cast -> READY (0).
    assert out[1]["summs"]["d_cd_remaining_s"] == 0.0


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------

def test_sort_ready_spells_bubble_to_top():
    """All-READY rows sort by participant index; cast spells sort by remaining."""
    events = [{"type": "SUMMONER_SPELL_USED", "puuid": "puuid-1",
               "summonerSpellId": 4, "gameTime": 100.0}]
    out = compute_cooldowns([_p(0), _p(1)], events, now_s=150.0)
    # Player0 READY (0); Player1 has Flash on 250s remaining.
    assert out[0]["puuid"] == "puuid-0"
    assert out[1]["puuid"] == "puuid-1"


def test_sort_ready_at_top_then_ascending():
    """Multiple READY at top, then ascending remaining.

    Cast D + F + ULT for P0 and P1 so neither has an instantly-ready
    slot; P2 is the only fully-idle participant.
    """
    events = [
        # P0: D/F/ult all cast LATE so ult is not yet ready (min remaining
        # comes from ult: cast at t=110, base 120, now=200 -> rem=30).
        {"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
         "summonerSpellId": 4, "gameTime": 100.0},
        {"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
         "summonerSpellId": 14, "gameTime": 100.0},
        {"type": "ULTIMATE_USED", "puuid": "puuid-0", "gameTime": 110.0},
        # P1: slightly earlier casts so min remaining is smaller than P0
        # (ult cast at t=90 -> 90+120-200 = 10).
        {"type": "SUMMONER_SPELL_USED", "puuid": "puuid-1",
         "summonerSpellId": 4, "gameTime": 70.0},
        {"type": "SUMMONER_SPELL_USED", "puuid": "puuid-1",
         "summonerSpellId": 14, "gameTime": 70.0},
        {"type": "ULTIMATE_USED", "puuid": "puuid-1", "gameTime": 90.0},
    ]
    out = compute_cooldowns([_p(0), _p(1), _p(2)], events, now_s=200.0)
    # Player2 is the only fully-READY participant (min=0) -> top.
    assert out[0]["puuid"] == "puuid-2"
    # Player1 (min ult rem=10) ahead of Player0 (min ult rem=30).
    assert out[1]["puuid"] == "puuid-1"
    assert out[2]["puuid"] == "puuid-0"


def test_sort_uses_min_across_d_f_ult():
    """Sort key is min(d_cd, f_cd, ult.cd) so ult-ready beats slow summs."""
    events = [
        # P0: F cast at 100s -> Ignite rem=130 (180-50=130 at now=150).
        {"type": "SUMMONER_SPELL_USED", "puuid": "puuid-0",
         "summonerSpellId": 14, "gameTime": 50.0},
        # P1: D cast at 50s -> Flash rem=200 (300-100=200 at now=150). Ult ready.
        {"type": "SUMMONER_SPELL_USED", "puuid": "puuid-1",
         "summonerSpellId": 4, "gameTime": 50.0},
    ]
    out = compute_cooldowns([_p(0), _p(1)], events, now_s=150.0)
    # Both have at least one READY (P0 D=Flash, P1 F=Ignite + Ult); tie on min=0.
    # Stable sort -> P0 first.
    assert out[0]["puuid"] == "puuid-0"
    assert out[1]["puuid"] == "puuid-1"


# ---------------------------------------------------------------------------
# Edge cases + payload shape
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
    """Haste edge cases: 0, positive, negative (CC-debuff mode)."""
    assert _effective_cd(300.0, 0.0) == 300.0
    # 100 haste -> halves the cooldown (1 + 100/100 = 2).
    assert _effective_cd(300.0, 100.0) == pytest.approx(150.0, abs=1e-9)
    # Negative haste (event-mode penalty) extends the cooldown.
    assert _effective_cd(300.0, -50.0) == pytest.approx(600.0, abs=1e-9)


def test_payload_shape_matches_spec():
    """Returned row has the expected keys (haste totals included)."""
    out = compute_cooldowns([_p(0)], [], now_s=0.0)
    row = out[0]
    assert set(row.keys()) == {"puuid", "summoner_name", "champion_id",
                                "side", "summs", "ult"}
    s = row["summs"]
    assert set(s.keys()) == {
        "d_id", "d_name", "d_used_at_s", "d_ready_at_s", "d_cd_remaining_s",
        "f_id", "f_name", "f_used_at_s", "f_ready_at_s", "f_cd_remaining_s",
        "summoner_haste",
    }
    u = row["ult"]
    assert set(u.keys()) == {"id", "used_at_s", "ready_at_s",
                              "cd_remaining_s", "ability_haste"}
    # d_name is human-readable for the panel.
    assert s["d_name"] == "Flash"
    assert s["f_name"] == "Ignite"
    # Haste totals exposed for tooltip rendering.
    assert s["summoner_haste"] == 0.0
    assert u["ability_haste"] == 0.0


def test_ten_participants_full_render():
    """Smoke: 10-player game renders 10 rows, all sortable."""
    ps = [_p(i) for i in range(10)]
    out = compute_cooldowns(ps, [], now_s=0.0)
    assert len(out) == 10
    # All idle => all sort to 0 remaining; order should be stable on idx.
    for r, original_idx in zip(out, range(10)):
        assert r["puuid"] == f"puuid-{original_idx}"
