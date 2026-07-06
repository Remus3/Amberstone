# Tests for core.arena_deterministic_coach - the Stage 2 pure assembler.
#
# build_block assembles the 7 deterministic Arena coach fields (action,
# round_strategy, fight_rule, augment_advice, anvil_advice,
# target_priority, risk - the live artifact keys written at
# coaches/arena_coach.py:781-787). It is PURE (primitives in, dict out),
# fail-soft (never raises), and partial-read friendly (works from
# whatever inputs are present on a given tick).
from __future__ import annotations

from core.arena_deterministic_coach import build_block

_KEYS = (
    "action",
    "round_strategy",
    "fight_rule",
    "augment_advice",
    "anvil_advice",
    "target_priority",
    "risk",
    "choices",
)

# The seven string columns; choices is the eighth (a list, not a str) and is
# asserted separately wherever the all-str / all-"" invariants are checked.
_STR_KEYS = tuple(k for k in _KEYS if k != "choices")

# A realistic enemy_cc_threat_line (core.aram_fight_risk parses this
# ranked-string form; the first chunk is the top threat).
_CC_LINE = "Enemy CC threats: Ashe 3.0s stun (R), Annie 1.5s stun (R)"


class _Nasty:
    """Garbage object that breaks every coercion path an input can hit."""

    def __bool__(self):
        raise RuntimeError("boom")

    def __float__(self):
        raise RuntimeError("boom")

    def __int__(self):
        raise RuntimeError("boom")

    def __iter__(self):
        raise RuntimeError("boom")

    def __str__(self):
        raise RuntimeError("boom")


def test_no_args_returns_exactly_the_eight_keys_all_empty() -> None:
    block = build_block()
    assert set(block) == set(_KEYS)
    for key in _STR_KEYS:
        assert block[key] == ""
    # choices is the list column: no action signal -> no A/B pair.
    assert block["choices"] == []


def test_partial_read_only_cc_threat_line() -> None:
    block = build_block(cc_threat_line=_CC_LINE)
    assert "Ashe" in block["fight_rule"]
    assert "Ashe" in block["risk"]
    for key in _STR_KEYS:
        if key in ("fight_rule", "risk"):
            continue
        assert block[key] == ""
    # No action signal (cc line only) -> no A/B pair.
    assert block["choices"] == []


def test_camp_phase_alone_is_a_real_action_signal() -> None:
    # BUY ITEMS needs no HP: a truthy camp_phase alone must not be gated
    # into the empty-action path.
    block = build_block(camp_phase=True)
    assert block["action"] == "BUY ITEMS"


def test_garbage_hp_without_camp_yields_empty_action() -> None:
    for hp in (None, "garbage", float("nan"), float("inf")):
        block = build_block(hp_pct=hp)
        assert block["action"] == ""
        assert block["round_strategy"] == ""


def test_action_labels_from_hp_bands() -> None:
    assert build_block(hp_pct=10)["action"] == "KITE BACK"
    assert build_block(hp_pct=50)["action"] == "FIGHT SMART"
    assert build_block(hp_pct=90)["action"] == "PLAY AGGRO"
    assert build_block(hp_pct=90, low_opp_count=1)["action"] == "ALL IN"


def test_augment_advice_always_empty_v1() -> None:
    # Documented v1 degrade: no honest per-tick deterministic augment
    # source exists, so the field is "" across every input shape.
    shapes = (
        {},
        {"hp_pct": 90, "camp_phase": True, "alive_teams": 4},
        {"cc_threat_line": _CC_LINE, "build_remaining": ["Infinity Edge"]},
        {"alive_opponents": ["Jinx"], "frontline_names": set()},
    )
    for kwargs in shapes:
        assert build_block(**kwargs)["augment_advice"] == ""


def test_anvil_advice_from_build_remaining_head() -> None:
    block = build_block(build_remaining=["Infinity Edge", "Bloodthirster"])
    assert block["anvil_advice"] == "Build toward Infinity Edge next."


def test_anvil_advice_degrades_to_empty() -> None:
    assert build_block(build_remaining=[])["anvil_advice"] == ""
    assert build_block(build_remaining=[""])["anvil_advice"] == ""
    assert build_block(build_remaining="Infinity Edge")["anvil_advice"] == ""
    assert build_block(build_remaining={"a": 1})["anvil_advice"] == ""
    assert build_block(build_remaining=[42, "Infinity Edge"])["anvil_advice"] == ""


def test_target_priority_wired_through() -> None:
    block = build_block(
        alive_opponents=["Malphite", "Jinx"], frontline_names={"Malphite"}
    )
    assert block["target_priority"].startswith("Kill Jinx first")


def test_round_strategy_full_template() -> None:
    block = build_block(hp_pct=50, alive_teams=4)
    line = block["round_strategy"]
    assert "Your HP 50%" in line
    assert "4 teams left" in line
    assert "trade efficiently and kite" in line
    assert len(line.split()) <= 20


def test_round_strategy_approach_per_action_label() -> None:
    cases = (
        ({"hp_pct": 10}, "kite, disengage, survive"),
        ({"hp_pct": 50}, "trade efficiently and kite"),
        ({"hp_pct": 90}, "make plays, take risks"),
        ({"hp_pct": 90, "low_opp_count": 1}, "trade efficiently and kite"),
        ({"hp_pct": 50, "camp_phase": True}, "spend gold, heal at campfire"),
    )
    for kwargs, approach in cases:
        line = build_block(alive_teams=3, **kwargs)["round_strategy"]
        assert approach in line
        assert len(line.split()) <= 20


def test_round_strategy_omits_teams_clause_when_unusable() -> None:
    for teams in (None, "garbage", float("nan")):
        line = build_block(hp_pct=50, alive_teams=teams)["round_strategy"]
        assert "teams left" not in line
        assert "trade efficiently and kite" in line


def test_round_strategy_buy_items_without_hp() -> None:
    # Camp-only tick: the approach still renders, with no HP clause.
    line = build_block(camp_phase=True, alive_teams=5)["round_strategy"]
    assert "Your HP" not in line
    assert "5 teams left" in line
    assert "spend gold, heal at campfire" in line
    line2 = build_block(camp_phase=True)["round_strategy"]
    assert line2 == "spend gold, heal at campfire"


def test_round_strategy_empty_when_no_action() -> None:
    assert build_block()["round_strategy"] == ""
    assert build_block(cc_threat_line=_CC_LINE)["round_strategy"] == ""


def test_whole_block_fail_soft_on_garbage_everything() -> None:
    block = build_block(
        _Nasty(),
        _Nasty(),
        _Nasty(),
        alive_teams=_Nasty(),
        cc_threat_line=_Nasty(),
        alive_opponents=_Nasty(),
        frontline_names=_Nasty(),
        build_remaining=_Nasty(),
    )
    assert set(block) == set(_KEYS)
    for key in _STR_KEYS:
        assert block[key] == ""
    assert block["choices"] == []


# choices column - the deterministic Arena A/B surface, mirroring
# core.aram_deterministic_coach._safe_choices. Every canonical action label
# maps to a 2-entry A/B tagged source_tag "arena_rule"; an empty / unknown
# action yields [].
def test_choices_present_for_every_canonical_action_label() -> None:
    cases = (
        ({"camp_phase": True}, "BUY ITEMS"),
        ({"hp_pct": 10}, "KITE BACK"),
        ({"hp_pct": 90, "low_opp_count": 1}, "ALL IN"),
        ({"hp_pct": 90}, "PLAY AGGRO"),
        ({"hp_pct": 50}, "FIGHT SMART"),
    )
    for kwargs, expected_action in cases:
        block = build_block(**kwargs)
        assert block["action"] == expected_action
        choices = block["choices"]
        assert isinstance(choices, list) and len(choices) == 2
        assert [c["key"] for c in choices] == ["A", "B"]
        assert all(c["source_tag"] == "arena_rule" for c in choices)
        assert all(c["label"].strip() for c in choices)


def test_choices_b_outcome_carries_fight_rule_when_present() -> None:
    block = build_block(hp_pct=50, cc_threat_line=_CC_LINE)
    b = block["choices"][1]
    # The B branch outcome echoes the computed fight_rule (a real CC line).
    assert b["expected_outcome"] == block["fight_rule"]
    assert b["expected_outcome"]


def test_choices_empty_for_no_action() -> None:
    # No signal at all -> no A/B pair (matches the ARAM synth fallback -> []).
    assert build_block()["choices"] == []
    assert build_block(cc_threat_line=_CC_LINE)["choices"] == []
