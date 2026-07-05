# Tests for core.aram_deterministic_coach - the Stage 2 pure assembler.
#
# build_block assembles the 6 deterministic ARAM coach fields (action,
# fight_rule, risk, reset_item, item_build, item_build_reasons) from the
# Stage 1 rules + the existing ARAM build / hint surfaces. It is PURE
# (primitives in, dict out), fail-soft (never raises), and partial-read
# friendly (works from whatever inputs are present).
#
# No DS-engine network call happens: the build-table + hint reasons are
# passed in as already-resolved primitives by the dashboard wiring layer,
# so these unit tests construct them directly.
from __future__ import annotations

from core.aram_deterministic_coach import build_block

_KEYS = (
    "action",
    "fight_rule",
    "risk",
    "reset_item",
    "item_build",
    "item_build_reasons",
    "choices",
    "item_extra",
    "objective",
)


def test_returns_all_six_keys_always() -> None:
    block = build_block()
    assert set(block.keys()) == set(_KEYS)


def test_normal_inputs_full_block() -> None:
    # A healthy carry, pushed wave, two enemies low, a real CC line, a build
    # path with reasons, and a next-item recall fact.
    cc_line = "Enemy CC threats: Ashe 3.0s stun (R), Annie 1.5s stun (R)"
    block = build_block(
        hp_pct=90.0,
        wave_pct=70.0,
        low_enemy_count=2,
        cc_threat_line=cc_line,
        item_build="Kraken Slayer -> Infinity Edge",
        item_build_reasons={"Kraken": "spear proc"},
        next_item_name="Infinity Edge",
        next_item_remaining_gold=1400,
    )
    # hp>80 + low>=2 promotes to ALL-IN; wave>65 shifts one MORE aggressive,
    # clamped at index 0 -> still ALL-IN.
    assert block["action"] == "ALL-IN"
    # fight_rule / risk name the top CC threat (Ashe R stun).
    assert "Ashe" in block["fight_rule"]
    assert "Ashe" in block["risk"]
    # build fields pass through.
    assert block["item_build"] == "Kraken Slayer -> Infinity Edge"
    assert block["item_build_reasons"] == {"Kraken": "spear proc"}
    # reset_item carries the ARAM-no-recall fact + the next item.
    assert "Infinity Edge" in block["reset_item"]
    # ARAM never has a recall, so the reset line must say so.
    assert "fountain" in block["reset_item"].lower() or "recall" in block["reset_item"].lower()


def test_partial_inputs_only_hp_known() -> None:
    # Only HP is known: action still resolves (no wave shift), every other
    # field degrades to empty rather than raising or guessing.
    block = build_block(hp_pct=50.0)
    assert block["action"] == "HOLD"  # 40..<60 band, no wave shift
    assert block["fight_rule"] == ""
    assert block["risk"] == ""
    assert block["item_build"] == ""
    assert block["item_build_reasons"] == {}
    # No next item known -> reset line is empty (no item to name).
    assert block["reset_item"] == ""


def test_all_missing_returns_empty_strings() -> None:
    block = build_block()
    assert block["action"] == ""
    assert block["fight_rule"] == ""
    assert block["risk"] == ""
    assert block["reset_item"] == ""
    assert block["item_build"] == ""
    assert block["item_build_reasons"] == {}


def test_action_empty_when_hp_unknown_but_other_fields_present() -> None:
    # The action rule's own neutral fallback is HOLD when HP is unusable, but
    # the ASSEMBLER treats a totally-absent hp_pct as "no action signal" and
    # emits "" so the shadow row honestly shows no action was computable.
    block = build_block(
        cc_threat_line="Enemy CC threats: Leona 2.0s stun (R)",
        item_build="Eclipse",
    )
    assert block["action"] == ""
    assert "Leona" in block["fight_rule"]
    assert block["item_build"] == "Eclipse"


def test_fight_risk_from_structured_threats() -> None:
    # build_block accepts the structured ranked-entry form too (same as the
    # Stage 1 aram_fight_risk contract).
    threats = [{"champion": "Malphite", "kind": "knockup", "spell_key": "R"}]
    block = build_block(hp_pct=75.0, cc_threat_line=threats)
    assert "Malphite" in block["fight_rule"]
    assert "Malphite" in block["risk"]


def test_reset_item_no_recall_fact_without_next_item() -> None:
    # When the next item is unknown the reset line is empty (we only assert the
    # ARAM no-recall fact when we actually have an item to anchor it to).
    block = build_block(hp_pct=60.0, next_item_name=None)
    assert block["reset_item"] == ""


def test_never_raises_on_garbage_inputs() -> None:
    # Wholly malformed inputs degrade to the empty block, never raise.
    block = build_block(
        hp_pct="not-a-number",
        wave_pct=object(),
        low_enemy_count=[],
        cc_threat_line=12345,
        item_build=None,
        item_build_reasons="not-a-dict",
        next_item_name=object(),
        next_item_remaining_gold="lots",
    )
    assert set(block.keys()) == set(_KEYS)
    # hp_pct non-coercible -> no action signal.
    assert block["action"] == ""
    assert block["fight_rule"] == ""
    assert block["item_build"] == ""
    assert block["item_build_reasons"] == {}


def test_antitank_hint_appended_to_reasons() -> None:
    # When an anti-tank hint string is supplied it rides into the reasons map
    # under a stable key so the operator sees the build rationale.
    block = build_block(
        hp_pct=80.0,
        item_build="Kraken Slayer",
        item_build_reasons={"Kraken": "core"},
        antitank_hint="Enemy comp tanky (3); itemize anti-tank.",
    )
    assert block["item_build_reasons"].get("Kraken") == "core"
    # the anti-tank reason is present under some key
    assert any(
        "anti-tank" in str(v).lower() for v in block["item_build_reasons"].values()
    )


def test_heal_threat_appended_to_reasons() -> None:
    block = build_block(
        hp_pct=80.0,
        item_build="Kraken Slayer",
        heal_threat_line="Enemy sustain (Soraka) - no anti-heal, buy Grievous",
    )
    assert any(
        "grievous" in str(v).lower() for v in block["item_build_reasons"].values()
    )


# ---------------------------------------------------------------------------
# build_order -> item_build assembly (deterministic fill from the ARAM table).
# Previously item_build was always passed "" by the caller; now the caller
# passes the full ordered completed-item list and build_block joins the first
# 4-6 into a comma-separated string. Empty/None order keeps item_build "".
# ---------------------------------------------------------------------------


def test_build_order_list_joined_into_item_build() -> None:
    # A full 6-item ARAM order joins into a comma-separated string of <=6 items.
    order = [
        "Blade of The Ruined King",
        "Berserker's Greaves",
        "Runaan's Hurricane",
        "Lord Dominik's Regards",
        "Yun Tal Wildarrows",
        "Infinity Edge",
    ]
    block = build_block(hp_pct=80.0, build_order=order)
    items = [s.strip() for s in block["item_build"].split(",")]
    assert items == order
    assert len(items) <= 6
    assert ", " in block["item_build"]


def test_build_order_caps_at_six_items() -> None:
    # A longer-than-6 order is truncated to the first 6 completed items.
    order = [f"Item{i}" for i in range(9)]
    block = build_block(hp_pct=80.0, build_order=order)
    items = [s.strip() for s in block["item_build"].split(",")]
    assert items == [f"Item{i}" for i in range(6)]
    assert len(items) == 6


def test_build_order_skips_blank_and_none_entries() -> None:
    # Components / None / blank entries are skipped; only real completed items
    # land in the joined string, still capped at 6.
    order = ["Eclipse", None, "", "   ", "Serylda's Grudge", "Edge of Night"]
    block = build_block(hp_pct=80.0, build_order=order)
    items = [s.strip() for s in block["item_build"].split(",")]
    assert items == ["Eclipse", "Serylda's Grudge", "Edge of Night"]


def test_build_order_empty_keeps_item_build_empty() -> None:
    # An empty list or None order keeps the fail-soft "" (unchanged behavior).
    assert build_block(hp_pct=80.0, build_order=[]).get("item_build") == ""
    assert build_block(hp_pct=80.0, build_order=None).get("item_build") == ""


def test_build_order_with_reasons_and_hints_coexist() -> None:
    # The assembled item_build coexists with the folded antitank/heal reasons.
    block = build_block(
        hp_pct=80.0,
        build_order=["Kraken Slayer", "Infinity Edge"],
        item_build_reasons={"Kraken": "spear proc"},
        antitank_hint="Enemy comp tanky (3); itemize anti-tank.",
    )
    assert block["item_build"] == "Kraken Slayer, Infinity Edge"
    assert block["item_build_reasons"].get("Kraken") == "spear proc"
    assert any(
        "anti-tank" in str(v).lower() for v in block["item_build_reasons"].values()
    )


def test_build_order_garbage_type_keeps_item_build_empty() -> None:
    # A non-list / non-iterable-of-str build_order degrades to "" (never raises).
    assert build_block(hp_pct=80.0, build_order="not-a-list-but-str").get(
        "item_build"
    ) == ""
    assert build_block(hp_pct=80.0, build_order=12345).get("item_build") == ""
    assert build_block(hp_pct=80.0, build_order=[1, 2, 3]).get("item_build") == ""


# ---------------------------------------------------------------------------
# choices - the deterministic A/B array (the ARAM PRIMARY actionable surface).
# build_block maps ALL 5 canonical ARAM action labels (ALL-IN / POKE / HOLD /
# DISENGAGE / FALL BACK) to an ARAM-appropriate 2-entry A/B via the
# _ARAM_CHOICE_LABELS map (source_tag "aram_rule"), superseding the earlier
# narrow reuse of synthesize_simple_choices (which mapped only ALL-IN + FALL
# BACK). An empty / unknown action still falls back to the synth path (-> []),
# so non-canonical input never regresses.
# ---------------------------------------------------------------------------

# Each canonical action label -> its expected (A label, B label) A/B pair.
_ARAM_LABEL_PAIRS = {
    "ALL-IN": ("All-in", "Poke instead"),
    "POKE": ("Poke", "Hold"),
    "HOLD": ("Hold", "Reposition"),
    "DISENGAGE": ("Disengage", "Trade back"),
    "FALL BACK": ("Fall back", "Hold under turret"),
}

_CHOICE_FIELDS = {"key", "label", "expected_outcome", "confidence", "source_tag"}


def test_choices_key_always_a_list() -> None:
    # Present on the normal path, the fail-soft empty path, AND the garbage path.
    assert isinstance(build_block(hp_pct=90.0, low_enemy_count=2)["choices"], list)
    assert isinstance(build_block()["choices"], list)
    garbage = build_block(
        hp_pct="not-a-number",
        wave_pct=object(),
        low_enemy_count=[],
        cc_threat_line=12345,
        item_build_reasons="not-a-dict",
        next_item_name=object(),
    )
    assert isinstance(garbage["choices"], list)


def test_choices_hold_maps_to_pair() -> None:
    # hp_pct 50 -> action HOLD, which NOW maps to a 2-entry Hold/Reposition A/B
    # (previously [] under the narrow synth reuse).
    block = build_block(hp_pct=50.0)
    assert block["action"] == "HOLD"
    choices = block["choices"]
    assert len(choices) == 2
    assert [e["key"] for e in choices] == ["A", "B"]
    assert [e["label"] for e in choices] == ["Hold", "Reposition"]
    for entry in choices:
        assert entry["source_tag"] == "aram_rule"


def test_choices_two_entries_for_all_in_action() -> None:
    # hp>80 + low>=2 -> ALL-IN, which maps to a 2-entry All-in/Poke instead A/B.
    block = build_block(hp_pct=90.0, low_enemy_count=2)
    assert block["action"] == "ALL-IN"
    choices = block["choices"]
    assert isinstance(choices, list)
    assert len(choices) == 2
    for entry in choices:
        assert isinstance(entry, dict)
        assert _CHOICE_FIELDS.issubset(entry.keys())
        assert entry["source_tag"] == "aram_rule"
    assert [e["key"] for e in choices] == ["A", "B"]
    assert [e["label"] for e in choices] == ["All-in", "Poke instead"]


def test_choices_all_in_pins_aram_map() -> None:
    # Pin the exact ALL-IN A/B labels + source_tag from the ARAM map (no longer
    # equal to the synthesize_simple_choices output, which is now superseded).
    block = build_block(
        hp_pct=90.0,
        low_enemy_count=2,
        cc_threat_line="Enemy CC threats: Ashe 3.0s stun (R)",
    )
    a_lbl, b_lbl = _ARAM_LABEL_PAIRS["ALL-IN"]
    choices = block["choices"]
    assert [e["label"] for e in choices] == [a_lbl, b_lbl]
    assert all(e["source_tag"] == "aram_rule" for e in choices)


def test_choices_hold_pins_aram_map() -> None:
    # Pin the exact HOLD A/B labels + source_tag from the ARAM map.
    block = build_block(hp_pct=50.0)
    a_lbl, b_lbl = _ARAM_LABEL_PAIRS["HOLD"]
    choices = block["choices"]
    assert [e["label"] for e in choices] == [a_lbl, b_lbl]
    assert all(e["source_tag"] == "aram_rule" for e in choices)


def test_choices_empty_action_falls_back_to_synth_empty() -> None:
    # A totally-absent hp_pct yields action "" -> the synth fallback path still
    # returns [] (the reuse fallback still matters for the empty/unknown case).
    block = build_block(cc_threat_line="Enemy CC threats: Leona 2.0s stun (R)")
    assert block["action"] == ""
    assert block["choices"] == []


def test_choices_poke_maps_to_pair() -> None:
    # hp 70 (60..80 band, no wave shift) -> POKE -> Poke/Hold A/B.
    block = build_block(hp_pct=70.0)
    assert block["action"] == "POKE"
    choices = block["choices"]
    assert len(choices) == 2
    assert [e["label"] for e in choices] == ["Poke", "Hold"]
    for entry in choices:
        assert entry["source_tag"] == "aram_rule"


def test_choices_disengage_maps_to_pair() -> None:
    # hp 35 (30..<40 band) -> DISENGAGE -> Disengage/Trade back A/B.
    block = build_block(hp_pct=35.0)
    assert block["action"] == "DISENGAGE"
    choices = block["choices"]
    assert len(choices) == 2
    assert [e["label"] for e in choices] == ["Disengage", "Trade back"]
    for entry in choices:
        assert entry["source_tag"] == "aram_rule"


def test_choices_fall_back_maps_to_pair() -> None:
    # hp 20 (<30 band) -> FALL BACK -> Fall back/Hold under turret A/B.
    block = build_block(hp_pct=20.0)
    assert block["action"] == "FALL BACK"
    choices = block["choices"]
    assert len(choices) == 2
    assert [e["label"] for e in choices] == ["Fall back", "Hold under turret"]
    for entry in choices:
        assert entry["source_tag"] == "aram_rule"


def test_choices_b_outcome_is_fight_rule_when_present() -> None:
    # B.expected_outcome carries the passed fight_rule verbatim (stripped) when
    # it is non-empty.
    block = build_block(
        hp_pct=70.0,
        cc_threat_line="Enemy CC threats: Ashe 3.0s stun (R)",
    )
    assert block["action"] == "POKE"
    fr = block["fight_rule"]
    assert fr  # non-empty for this CC line
    b_entry = block["choices"][1]
    assert b_entry["expected_outcome"] == fr


def test_choices_b_outcome_default_when_no_fight_rule() -> None:
    # With no CC line the fight_rule is "" -> B falls back to the safe default.
    block = build_block(hp_pct=70.0)
    assert block["action"] == "POKE"
    assert block["fight_rule"] == ""
    b_entry = block["choices"][1]
    assert b_entry["expected_outcome"] == "play safe; reassess next tick"


def test_choices_a_outcome_is_follow_the_coach_call() -> None:
    # A.expected_outcome is the fixed "follow the coach call" for every label.
    for hp in (90.0, 70.0, 50.0, 35.0, 20.0):
        block = (
            build_block(hp_pct=hp, low_enemy_count=2)
            if hp > 80
            else build_block(hp_pct=hp)
        )
        assert block["choices"][0]["expected_outcome"] == "follow the coach call"


# ---------------------------------------------------------------------------
# item_extra - the ARAM "7th-item else omit" filler (coaches/aram_coach.py:332).
# The live Haiku emits "omit" when a 7th legendary already fills the slot, else
# a "Pot: X" / "Shard: X" consumable pick. Our deterministic build caps at 6
# completed items, so it NEVER produces a 7th item; rather than fabricate a
# specific consumable (a judgment call we decline - do-not-flip-blind), the
# assembler emits the safe, non-misleading "omit" whenever the owned-item count
# is a known non-negative number, and "" when no item-count signal is present.
# ---------------------------------------------------------------------------


def test_item_extra_key_always_present() -> None:
    # Present on the empty path, the normal path, AND the garbage path.
    assert "item_extra" in build_block()
    assert "item_extra" in build_block(hp_pct=80.0, owned_item_count=3)
    assert "item_extra" in build_block(hp_pct="nope", owned_item_count=object())


def test_item_extra_omit_when_item_count_known() -> None:
    # A usable non-negative owned-item count -> the safe "omit" default (matches
    # the live-observed 'omit' value; never misleads).
    for count in (0, 3, 6, 9):
        block = build_block(hp_pct=80.0, owned_item_count=count)
        assert block["item_extra"] == "omit"


def test_item_extra_empty_when_count_absent() -> None:
    # No owned-item-count signal -> honest empty (nothing computable), NOT a
    # fabricated consumable.
    assert build_block(hp_pct=80.0).get("item_extra") == ""
    assert build_block(hp_pct=80.0, owned_item_count=None).get("item_extra") == ""


def test_item_extra_empty_on_garbage_or_negative_count() -> None:
    # Non-coercible / negative counts degrade to "" (never raises, never guesses).
    assert build_block(hp_pct=80.0, owned_item_count="lots").get("item_extra") == ""
    assert build_block(hp_pct=80.0, owned_item_count=object()).get("item_extra") == ""
    assert build_block(hp_pct=80.0, owned_item_count=-1).get("item_extra") == ""


# ---------------------------------------------------------------------------
# objective - the deterministic ARAM tower-HP state machine, faithful to the
# coaches/aram_coach.py:295-298 OBJECTIVE prompt (your-T1-up defend / enemy-T1-
# dead push to base / enemy-tower-low siege). Keyed purely on my_tower_hp +
# enemy_tower_hp (0-100 percent, null when not visible). Each side that is
# absent / non-coercible just drops out of the routing; neither usable -> "".
# ---------------------------------------------------------------------------


def test_objective_key_always_present() -> None:
    assert "objective" in build_block()
    assert "objective" in build_block(hp_pct=80.0, my_tower_hp=90, enemy_tower_hp=80)
    assert "objective" in build_block(my_tower_hp=object(), enemy_tower_hp="x")


def test_objective_empty_when_no_tower_signal() -> None:
    # No tower HP either side -> honest empty (like wave_pct, tower HP is vision-
    # only and often absent server-side).
    assert build_block(hp_pct=50.0).get("objective") == ""


def test_objective_empty_on_garbage_towers() -> None:
    block = build_block(hp_pct=50.0, my_tower_hp="nope", enemy_tower_hp=object())
    assert block["objective"] == ""


def test_objective_enemy_tower_dead_says_push_their_base() -> None:
    # enemy T1 destroyed (0) -> push to their base (prompt branch 2).
    block = build_block(hp_pct=80.0, my_tower_hp=90, enemy_tower_hp=0)
    assert "their base" in block["objective"].lower()


def test_objective_my_tower_dead_says_hold_inhibitor() -> None:
    # your T1 destroyed (0) -> fall back and hold the inhibitor, group up.
    block = build_block(hp_pct=50.0, my_tower_hp=0, enemy_tower_hp=90)
    assert "inhibitor" in block["objective"].lower()


def test_objective_my_tower_in_danger_says_defend() -> None:
    # your T1 low (<=25) but alive -> defend it; a death to save it is worth it
    # (prompt branch 1).
    block = build_block(hp_pct=50.0, my_tower_hp=15, enemy_tower_hp=90)
    assert "defend" in block["objective"].lower()


def test_objective_enemy_tower_low_says_siege() -> None:
    # enemy T1 low (<=25), yours healthy -> siege it with the team.
    block = build_block(hp_pct=80.0, my_tower_hp=90, enemy_tower_hp=15)
    assert "siege" in block["objective"].lower()


def test_objective_enemy_tower_alive_says_poke_no_chase() -> None:
    # both towers healthy -> poke phase; do not chase past T1 without allies.
    block = build_block(hp_pct=80.0, my_tower_hp=90, enemy_tower_hp=80)
    assert "chase" in block["objective"].lower()


def test_objective_only_my_tower_healthy_holds_for_a_pick() -> None:
    # only your tower HP known and healthy (enemy not visible) -> hold + poke,
    # wait for a pick before committing.
    block = build_block(hp_pct=80.0, my_tower_hp=90)
    assert "pick" in block["objective"].lower()


def test_objective_defensive_priority_when_both_low() -> None:
    # BOTH T1s in danger -> defending yours wins (losing your tower opens your
    # base); the defend branch outranks the enemy-low siege branch.
    block = build_block(hp_pct=50.0, my_tower_hp=15, enemy_tower_hp=15)
    assert "defend" in block["objective"].lower()


def test_item_extra_and_objective_in_total_failure_block() -> None:
    # The total fail-soft path must still carry both new keys as "".
    block = build_block(
        hp_pct="not-a-number",
        my_tower_hp=object(),
        enemy_tower_hp=[],
        owned_item_count={},
    )
    assert block["item_extra"] == ""
    assert block["objective"] == ""
    assert set(block.keys()) == set(_KEYS)
