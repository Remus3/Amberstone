"""Tests for core.lead_projection - deterministic lead-projection generator.

Covers state classification (ahead/even/behind), magnitude scaling, phase
appropriateness, ARAM weighting (no CS signal), the <=10-word ASCII line
contract, fail-soft on garbage input, and the always-4-keys / exhaustive-state
guarantees.
"""

from __future__ import annotations

import pytest

from core.lead_projection import project_lead

_KEYS = {"state", "magnitude", "line", "source_tag"}
_STATES = {"ahead", "even", "behind"}
_MAGNITUDES = {"slight", "clear", "large"}


def _gs(*, t_s, cs=0, gold=0, level=1, kda="0/0/0"):
    """Build a minimal game-state dict with the live-available fields only."""
    return {
        "game_time_s": t_s,
        "cs": cs,
        "gold": gold,
        "level": level,
        "kda": kda,
    }


# --- core state classification --------------------------------------------

def test_clearly_ahead_returns_ahead():
    # minute 10: cs well over bench, fed KDA, high level -> ahead.
    out = project_lead(_gs(t_s=600, cs=120, gold=4500, level=12, kda="6/0/4"))
    assert out["state"] == "ahead"
    # an ahead directive should read like pressing the lead, not surviving.
    assert "Behind" not in out["line"]


def test_clearly_behind_returns_behind():
    # minute 10: cs far under bench, death-heavy KDA, low level -> behind.
    out = project_lead(_gs(t_s=600, cs=40, gold=1500, level=4, kda="0/6/0"))
    assert out["state"] == "behind"
    assert out["line"].startswith("Behind")


def test_neutral_returns_even():
    # exactly on every benchmark + a near-even KDA -> even.
    out = project_lead(_gs(t_s=600, cs=80, gold=3500, level=6, kda="2/2/2"))
    assert out["state"] == "even"
    assert out["line"].startswith("Even")


# --- magnitude scaling -----------------------------------------------------

def test_magnitude_scales_slight_vs_large_ahead():
    # a small edge -> slight; a blowout -> large. Same direction (ahead).
    slight = project_lead(_gs(t_s=600, cs=90, gold=3700, level=7, kda="2/1/1"))
    large = project_lead(_gs(t_s=600, cs=140, gold=5500, level=13, kda="9/0/6"))
    assert slight["state"] == "ahead"
    assert large["state"] == "ahead"
    order = {"slight": 0, "clear": 1, "large": 2}
    assert order[large["magnitude"]] > order[slight["magnitude"]]
    assert large["magnitude"] == "large"


def test_magnitude_scales_slight_vs_large_behind():
    slight = project_lead(_gs(t_s=600, cs=70, gold=3200, level=5, kda="1/2/1"))
    large = project_lead(_gs(t_s=600, cs=20, gold=800, level=3, kda="0/8/0"))
    assert slight["state"] == "behind"
    assert large["state"] == "behind"
    order = {"slight": 0, "clear": 1, "large": 2}
    assert order[large["magnitude"]] > order[slight["magnitude"]]
    assert large["magnitude"] == "large"


# --- phase appropriateness -------------------------------------------------

def test_phase_lines_differ_early_vs_late_same_state():
    # same ahead+magnitude verdict but different game phase -> different line.
    early = project_lead(_gs(t_s=300, cs=60, gold=2200, level=7, kda="5/0/3"))
    late = project_lead(_gs(t_s=1800, cs=360, gold=12000, level=18, kda="9/0/6"))
    assert early["state"] == "ahead"
    assert late["state"] == "ahead"
    # early lead -> last-hit/press language; late lead -> objective/end language.
    assert early["line"] != late["line"]


@pytest.mark.parametrize(
    "t_s,phase_vocab",
    [
        # early ahead lines use laning/farm vocabulary across magnitudes.
        (60, ("last-hitting", "farm", "deny", "dive", "roam", "snowball", "zone")),
        # late ahead lines use objective/closing vocabulary across magnitudes.
        (1800, ("objective", "baron", "end", "group")),
    ],
)
def test_phase_specific_language(t_s, phase_vocab):
    # An ahead verdict early vs late surfaces phase-correct vocabulary,
    # regardless of which magnitude band the composite lands in.
    out = project_lead(_gs(t_s=t_s, cs=(t_s / 60.0) * 12, gold=int((t_s / 60.0) * 500), level=3 + (t_s / 60.0) * 0.6, kda="6/0/3"))
    assert out["state"] == "ahead"
    assert any(word in out["line"] for word in phase_vocab), out["line"]


# --- ARAM weighting (no CS signal) -----------------------------------------

def test_aram_ignores_cs_kills_drive_verdict():
    # In ARAM, CS is zero-weighted. A stellar KDA + level should read ahead
    # even though cs is low (an ARAM player rarely last-hits like a laner).
    out = project_lead(
        _gs(t_s=600, cs=10, gold=4000, level=11, kda="12/1/8"), mode="ARAM"
    )
    assert out["state"] == "ahead"


def test_aram_behind_on_deaths_despite_some_cs():
    # death-heavy ARAM with respectable cs still reads behind (cs zero-weight).
    out = project_lead(
        _gs(t_s=600, cs=90, gold=1200, level=5, kda="0/9/1"), mode="ARAM"
    )
    assert out["state"] == "behind"


def test_aram_cs_does_not_flip_verdict():
    # Two ARAM states identical except CS: verdict must be unchanged because
    # CS is zero-weighted in ARAM.
    lo = project_lead(_gs(t_s=600, cs=5, gold=3000, level=8, kda="3/3/3"), mode="ARAM")
    hi = project_lead(_gs(t_s=600, cs=200, gold=3000, level=8, kda="3/3/3"), mode="ARAM")
    assert lo["state"] == hi["state"]
    assert lo["magnitude"] == hi["magnitude"]
    assert lo["line"] == hi["line"]


def test_sr_cs_does_flip_verdict():
    # On SR, CS IS weighted, so the same two states should diverge.
    lo = project_lead(_gs(t_s=600, cs=20, gold=3500, level=6, kda="2/2/2"))
    hi = project_lead(_gs(t_s=600, cs=160, gold=3500, level=6, kda="2/2/2"))
    assert lo["state"] != hi["state"]


# --- line contract: <=10 words + ASCII -------------------------------------

def _all_sample_outputs():
    """Exercise a spread of (state x phase x magnitude x mode) verdicts."""
    samples = []
    for mode in ("SR", "ARAM"):
        for t_s in (60, 300, 800, 1800, 2400):
            for cs, gold, level, kda in (
                (140, 6000, 14, "9/0/6"),   # ahead
                (80, 3500, 6, "2/2/2"),     # even-ish
                (10, 600, 3, "0/8/0"),      # behind
                (0, 0, 1, "0/0/0"),         # game start
            ):
                samples.append(
                    project_lead(
                        {
                            "game_time_s": t_s,
                            "cs": cs,
                            "gold": gold,
                            "level": level,
                            "kda": kda,
                        },
                        mode=mode,
                    )
                )
    return samples


def test_all_lines_under_ten_words():
    for out in _all_sample_outputs():
        word_count = len(out["line"].split())
        assert word_count <= 10, f"line too long ({word_count}): {out['line']!r}"


def test_all_lines_are_ascii():
    for out in _all_sample_outputs():
        assert out["line"].isascii(), f"non-ascii line: {out['line']!r}"


# --- fail-soft -------------------------------------------------------------

def test_empty_dict_defaults_to_even_no_exception():
    out = project_lead({})
    assert out["state"] == "even"
    assert set(out) == _KEYS


def test_non_dict_input_defaults_to_even():
    for bad in (None, [], "garbage", 42):
        out = project_lead(bad)  # type: ignore[arg-type]
        assert out["state"] == "even"
        assert set(out) == _KEYS


def test_garbage_field_types_do_not_raise():
    out = project_lead(
        {
            "game_time_s": "not-a-number",
            "cs": None,
            "gold": [],
            "level": {"x": 1},
            "kda": 12345,
        }
    )
    assert out["state"] in _STATES
    assert set(out) == _KEYS


def test_malformed_kda_string_neutral():
    # an unparseable kda must not raise and must not skew the verdict hard.
    out = project_lead(_gs(t_s=600, cs=80, gold=3500, level=6, kda="abc/def"))
    assert out["state"] == "even"


def test_negative_game_time_clamped():
    out = project_lead(_gs(t_s=-50, cs=0, gold=0, level=1, kda="0/0/0"))
    assert out["state"] in _STATES
    assert set(out) == _KEYS


# --- structural guarantees -------------------------------------------------

def test_always_returns_all_four_keys():
    for out in _all_sample_outputs():
        assert set(out) == _KEYS


def test_state_is_always_one_of_three():
    for out in _all_sample_outputs():
        assert out["state"] in _STATES


def test_magnitude_is_always_one_of_three():
    for out in _all_sample_outputs():
        assert out["magnitude"] in _MAGNITUDES


def test_source_tag_is_constant():
    for out in _all_sample_outputs():
        assert out["source_tag"] == "lead-proj"


def test_default_mode_is_sr():
    # omitting mode should behave identically to mode="SR".
    state = _gs(t_s=600, cs=20, gold=3500, level=6, kda="2/2/2")
    assert project_lead(state) == project_lead(state, mode="SR")


def test_unknown_mode_falls_back_to_sr():
    state = _gs(t_s=600, cs=20, gold=3500, level=6, kda="2/2/2")
    assert project_lead(state, mode="URF") == project_lead(state, mode="SR")
