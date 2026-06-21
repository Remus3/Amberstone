# Tests for core.ward_cue.compute_ward_cue (QA1 overlay ward-ready glyph cue).
#
# The cue is fed by the active player's Live Client items[] block. Live Client
# emits NO ward/trinket cast events (see dashboard/_state_cooldowns.py), so the
# only live ready-signal we have is the per-item ``canUse`` boolean (the same
# field core/ward_producer.py reads): for a ward trinket canUse True means
# off-cooldown / ready to place. Control ward (2055) readiness is "you hold one"
# (count >= 1). This module is the pure extractor; the overlay does the single
# pulse on the not-ready -> ready edge.

from core.ward_cue import (
    CONTROL_WARD_ID,
    WARD_TRINKET_IDS,
    compute_ward_cue,
)


def _default():
    return {
        "trinket_ready": False,
        "trinket_id": None,
        "control_ward": False,
        "control_ward_count": 0,
    }


def test_constants_are_the_documented_ids():
    # 3340 yellow warding totem + 3363 farsight (blue). 3364 sweeper REVEALS,
    # it is not a placeable ward, so it must NOT be a trinket id here.
    assert 3340 in WARD_TRINKET_IDS
    assert 3363 in WARD_TRINKET_IDS
    assert 3364 not in WARD_TRINKET_IDS
    assert CONTROL_WARD_ID == 2055


def test_none_empty_and_non_list_return_the_safe_default():
    assert compute_ward_cue(None) == _default()
    assert compute_ward_cue([]) == _default()
    assert compute_ward_cue("nonsense") == _default()
    assert compute_ward_cue({"itemID": 3340}) == _default()  # dict, not a list


def test_yellow_trinket_off_cooldown_is_ready():
    items = [{"itemID": 3340, "slot": 6, "canUse": True}]
    cue = compute_ward_cue(items)
    assert cue["trinket_ready"] is True
    assert cue["trinket_id"] == 3340


def test_blue_trinket_on_cooldown_is_not_ready_but_still_identified():
    items = [{"itemID": 3363, "slot": 6, "canUse": False}]
    cue = compute_ward_cue(items)
    assert cue["trinket_ready"] is False
    assert cue["trinket_id"] == 3363


def test_sweeper_3364_is_excluded_it_is_not_a_placeable_ward():
    items = [{"itemID": 3364, "slot": 6, "canUse": True}]
    cue = compute_ward_cue(items)
    assert cue["trinket_ready"] is False
    assert cue["trinket_id"] is None


def test_control_ward_in_inventory_is_ready_with_its_count():
    items = [{"itemID": 2055, "count": 2, "canUse": True}]
    cue = compute_ward_cue(items)
    assert cue["control_ward"] is True
    assert cue["control_ward_count"] == 2


def test_control_ward_zero_count_is_not_ready():
    items = [{"itemID": 2055, "count": 0, "canUse": True}]
    cue = compute_ward_cue(items)
    assert cue["control_ward"] is False
    assert cue["control_ward_count"] == 0


def test_full_inventory_resolves_both_signals():
    items = [
        {"itemID": 3006, "slot": 0, "canUse": False},   # boots, ignored
        {"itemID": 2055, "slot": 5, "count": 1, "canUse": True},  # control ward
        {"itemID": 3340, "slot": 6, "canUse": True},     # yellow trinket ready
    ]
    cue = compute_ward_cue(items)
    assert cue == {
        "trinket_ready": True,
        "trinket_id": 3340,
        "control_ward": True,
        "control_ward_count": 1,
    }


def test_canuse_must_be_strict_boolean_true():
    # A truthy-but-not-True canUse (1, "true") must NOT read as ready - the
    # Live Client field is a real bool; anything else is treated conservatively
    # as on-cooldown rather than flashing a false "ready" pulse.
    items = [{"itemID": 3340, "slot": 6, "canUse": 1}]
    cue = compute_ward_cue(items)
    assert cue["trinket_ready"] is False
    assert cue["trinket_id"] == 3340


def test_malformed_entries_are_skipped_without_raising():
    items = [
        None,
        "garbage",
        {"slot": 6},                       # no itemID
        {"itemID": "notanint"},            # non-numeric id
        {"itemID": 3340, "canUse": True},  # the one good entry
    ]
    cue = compute_ward_cue(items)
    assert cue["trinket_ready"] is True
    assert cue["trinket_id"] == 3340


def test_string_item_ids_are_coerced():
    # _liveclient stores ids as ints from itemID, but be defensive: a stringy
    # "3340" should still resolve (Live Client itemID is numeric but JSON can
    # surface either).
    items = [{"itemID": "3340", "canUse": True}]
    cue = compute_ward_cue(items)
    assert cue["trinket_ready"] is True
    assert cue["trinket_id"] == 3340
