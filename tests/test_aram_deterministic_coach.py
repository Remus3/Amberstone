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
from core.coach_choices import synthesize_simple_choices, to_jsonable

_KEYS = (
    "action",
    "fight_rule",
    "risk",
    "reset_item",
    "item_build",
    "item_build_reasons",
    "choices",
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
# build_block reuses core.coach_choices.synthesize_simple_choices over its own
# action + fight_rule, so the deterministic choices are shape-identical to the
# served chip synthesizer. Of the 5 ARAM action labels only ALL-IN (->
# Engage/Disengage) and FALL BACK (-> Recall/Stay) map today; POKE / HOLD /
# DISENGAGE yield [] until a later ARAM-specific mapping widens this.
# ---------------------------------------------------------------------------


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


def test_choices_empty_for_hold_action() -> None:
    # hp_pct 50 -> action HOLD, which has no recognizable binary verb -> [].
    block = build_block(hp_pct=50.0)
    assert block["action"] == "HOLD"
    assert block["choices"] == []


def test_choices_two_entries_for_all_in_action() -> None:
    # hp>80 + low>=2 -> ALL-IN, which maps to a 2-entry Engage/Disengage A/B.
    block = build_block(hp_pct=90.0, low_enemy_count=2)
    assert block["action"] == "ALL-IN"
    choices = block["choices"]
    assert isinstance(choices, list)
    assert len(choices) == 2
    _expected_keys = {"key", "label", "expected_outcome", "confidence", "source_tag"}
    for entry in choices:
        assert isinstance(entry, dict)
        assert _expected_keys.issubset(entry.keys())
        assert entry["source_tag"] == "synth"
    assert [e["key"] for e in choices] == ["A", "B"]


def test_choices_reuse_pin_all_in() -> None:
    # ROBUST reuse pin (no hardcoded prose): the block's choices are EXACTLY what
    # the served synthesizer would produce from the block's own action +
    # fight_rule - so the deterministic + served chip UIs stay shape-identical.
    block = build_block(
        hp_pct=90.0,
        low_enemy_count=2,
        cc_threat_line="Enemy CC threats: Ashe 3.0s stun (R)",
    )
    assert block["choices"] == to_jsonable(
        synthesize_simple_choices(
            {"action": block["action"], "fight_rule": block["fight_rule"]}
        )
    )


def test_choices_reuse_pin_hold() -> None:
    # Same reuse pin on a HOLD block (which synthesizes to []): still identical.
    block = build_block(hp_pct=50.0)
    assert block["choices"] == to_jsonable(
        synthesize_simple_choices(
            {"action": block["action"], "fight_rule": block["fight_rule"]}
        )
    )
