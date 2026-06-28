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
