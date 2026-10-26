"""RM-927 (a): the TFT system prompt states only the game-mode rules Riot's
own pages support (s134 queue lane, cycle 14).

Measured before the fix (tft/tft_prompt.py at local main 4486a09bb):
  _RULES LEVEL TIMING (:91-94) and the BOARD HP thresholds plus "Stage 1
      HP=100 (vision error if lower)" (:105-106) were unscoped, so a Hyper
      Roll game was told to buy levels it cannot buy and that its low
      starting HP was a vision error.
  _RULES DOUBLE UP (:98-101) asked for "a donation note every round" and
      "Partner HP<30=donate 2nd tank now", although Double Up has ONE shared
      team HP pool and a unit crosses only when the cannon's 4-round
      (1-star) / 6-round (higher star) cooldown is over (Riot patch 14.1
      notes, Double Up section).
  _OUTPUT (:123, :125) asked for a donation note and "partner HP if
      critical".
  No paragraph covered Hyper Roll at all (Riot's Hyper Roll page: no XP
      purchase, a level-up at each stage, no interest).

Half (b) - the per-call message in tft/tft_coach_engine.py ("Gold cap 10g",
"(PBE)", the partner-HP lines) - is NOT covered here: an in-session agent
owns that file this session. These tests read only the shared rules text and
the mode markers the engine already emits.

Names used, cited:
  tft/tft_prompt.py _RULES, _OUTPUT, build_system_prompt, _CACHE
  tft/tft_coach_engine.py _build_prompt mode lines "MODE: HYPER ROLL"
      (:518) and "MODE: DOUBLE UP" (:529) - read as source text only.
  tft/tft_set.py ENV_PIN, comp_state, clear_live_set (patched as in
      tests/test_tft_prompt_true_audit_s134.py)
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tft import tft_prompt, tft_set

REPO_ROOT = Path(__file__).resolve().parents[1]
STANDARD_SCOPE = "Normal / Ranked"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.delenv(tft_set.ENV_PIN, raising=False)
    monkeypatch.setattr(tft_set, "comp_state", lambda root=None: {})
    tft_set.clear_live_set()
    tft_prompt._CACHE.clear()
    yield
    tft_set.clear_live_set()
    tft_prompt._CACHE.clear()


def _paragraph(text: str, head: str) -> str:
    hits = [p for p in text.split("\n\n") if p.startswith(head)]
    assert len(hits) == 1, (head, len(hits))
    return hits[0]


def _sentences(text: str) -> list:
    """Split on a full stop that ends a sentence (not a decimal point)."""
    return [s for s in re.split(r"(?<=\.)\s+|\n", text) if s.strip()]


# -- standard-queue numbers are scoped ----------------------------------------

def test_level_timing_is_scoped_to_the_standard_queues():
    para = _paragraph(tft_prompt._RULES, "LEVEL TIMING")
    head = para.split(":", 1)[0]
    assert STANDARD_SCOPE in head, head
    assert "Hyper Roll" in head, head  # says out loud it does not apply there


def _assert_standard_scoped(rules: str, at: int, what: str) -> None:
    """The nearest "Normal / Ranked HP:" label before `at` is in the same
    paragraph line, with nothing but HP claims between it and `at`."""
    scope_at = rules.rfind(STANDARD_SCOPE + " HP:", 0, at)
    assert scope_at >= 0, what
    between = rules[scope_at:at]
    assert "\n" not in between, (what, between)
    for other in ("Lv", "Tanks", "carry", "MODE:"):
        assert other not in between, (what, between)


@pytest.mark.parametrize("claim", ["Stage 1 HP=100", "HP<25=critical",
                                   "HP<35=low pressure", "HP>40=fine",
                                   "HP<35=roll now"])
def test_hp_numbers_appear_only_under_the_standard_scope(claim):
    rules = tft_prompt._RULES
    assert rules.count(claim) == 1, claim
    _assert_standard_scoped(rules, rules.index(claim), claim)


def test_every_hp_number_in_the_rules_is_standard_scoped():
    # Catches a future threshold added outside the scope, which the named
    # list above cannot see. Neither mode has a sourced starting HP.
    rules = tft_prompt._RULES
    hits = list(re.finditer(r"HP\s*[<>=]\s*\d", rules))
    assert len(hits) >= 5, len(hits)  # anchor: an empty match set fails
    for m in hits:
        _assert_standard_scoped(rules, m.start(), m.group(0))


# -- Double Up: one shared HP pool, the cannon cooldown ---------------------------

def test_double_up_paragraph_states_shared_hp_and_the_cannon_cooldown():
    para = _paragraph(tft_prompt._RULES, "DOUBLE UP")
    assert "MODE: DOUBLE UP" in para
    low = para.lower()
    assert "shared" in low and "hp" in low
    assert "cannon" in low
    assert re.search(r"\b4\b[^.]*1-star", para), para
    assert re.search(r"\b6\b[^.]*2-star", para), para


@pytest.mark.parametrize("stale", ["Partner HP", "every round", "donat"])
def test_double_up_paragraph_drops_the_unsourced_donation_rules(stale):
    para = _paragraph(tft_prompt._RULES, "DOUBLE UP")
    assert stale.lower() not in para.lower(), stale


@pytest.mark.parametrize("stale", ["partner HP", "donation"])
def test_output_format_asks_for_no_partner_hp_or_donation(stale):
    assert stale.lower() not in tft_prompt._OUTPUT.lower(), stale


# -- Hyper Roll: its own paragraph, no invented number ----------------------------

def test_hyper_roll_paragraph_exists_and_names_its_rules():
    para = _paragraph(tft_prompt._RULES, "HYPER ROLL")
    assert "MODE: HYPER ROLL" in para
    assert "XP" in para and "interest" in para.lower()


def test_hyper_roll_paragraph_invents_no_number():
    para = _paragraph(tft_prompt._RULES, "HYPER ROLL")
    assert not re.search(r"\d", para), para


@pytest.mark.parametrize("marker", ["MODE: HYPER ROLL", "MODE: DOUBLE UP"])
def test_rules_key_on_a_marker_the_engine_really_emits(marker):
    engine = (REPO_ROOT / "tft" / "tft_coach_engine.py").read_text(encoding="utf-8")
    assert marker in engine, marker
    assert f"only when the message says {marker}" in tft_prompt._RULES, marker


# -- the built prompt carries the rules and stays in budget -------------------

@pytest.mark.parametrize("n", [17, 18])
def test_built_prompt_carries_the_scoped_rules_within_budget(n):
    p = tft_prompt.build_system_prompt(n, root=REPO_ROOT)
    assert tft_prompt._RULES in p
    assert len(p) <= tft_prompt.MAX_PROMPT_CHARS, (n, len(p))
    p.encode("ascii")
    assert "\r" not in p
    for s in _sentences(p):
        assert "Partner HP<" not in s, s
