"""
tests/test_calc_win_pct_type_clamp.py - type-clamp on the items loop of
StateAuthority.calc_win_pct (app/_state_authority.py:86-88).

The items comprehension calls ``i.lower()`` on every truthy element of
``state.get("items", [])``. A non-string element (an int, a dict, a list)
raises AttributeError; a bytes element raises TypeError on the ``x in i``
substring test against a str needle. The fix keeps only str/bytes elements,
decodes bytes as utf-8 with ``errors="replace"`` before ``lower()``, and
skips everything else. No other behaviour changes; the function stays a
pure staticmethod.

CORRECTED PREMISE (recorded so the fix is not oversold):

(1) This was never a crash of the poll cycle. The only production caller,
    ``app/_game_lifecycle.py:465-467``, wraps the call::

        try:
            app.data["win_pct"] = StateAuthority.calc_win_pct(state); changed = True
        except Exception:
            pass

    so an int item makes the call raise, the exception is swallowed, and
    ``app.data["win_pct"]`` silently keeps its PREVIOUS value. The failure
    mode is a STALE win_pct (degradation), not a crash.

(2) Ints cannot reach calc_win_pct through the normalizer path at all.
    ``game_reader/snapshot_normalizer.py:357-359`` builds ``my_items`` from
    ``it.get("displayName", "")`` for dict rows only, ``:367`` already does
    ``[i.lower() for i in my_items]`` on that same list (so a non-str would
    have raised THERE first), and ``:532`` emits ``"items": my_items``.
    Other producers of the "items" key: ``game_reader/mode_router.py:111``
    emits a literal ``[]`` for TFT; ``core/game_snapshot.py:226/416/577``
    declare ``self.items: List[str] = []`` (a type ANNOTATION, not enforced
    at runtime) and emit it at ``:349/:500/:661``. So the clamp hardens
    calc_win_pct against a caller that bypasses the normalizer (a test, a
    replay fixture, a future producer) - it does not fix a live defect.

The test named ``*_old_comprehension_*`` carries an inline copy of the
pre-fix comprehension so the RED -> GREEN transition stays visible in the
file after the fix lands: the old shape raises AttributeError on ``[1]``,
the clamped function does not.

(3) Return-type premise, corrected by measurement while writing these
    tests: "an int-valued float" holds only OFF the clamps. The return line
    ``round(min(95, max(5, pct)), 0)`` (``:96`` at HEAD 9706c65c7, ``:99``
    after this slice's three added lines; the line itself is untouched)
    hands back the INT literal ``5`` or ``95`` whenever a clamp fires,
    because ``max``/``min`` return the winning object unchanged and
    ``round(int, 0)`` is an int. Interior results are floats (``54.0``).
    Measured: ``isinstance(5, float)`` is False at the lower clamp. This is
    pre-existing behaviour, not introduced or changed here, and the tests
    below pin it as found rather than papering over it.
"""
import math
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest

from app._state_authority import StateAuthority

_EXCLUDED = ("ward", "potion", "biscuit", "doran", "elixir")


def _neutral_state(items) -> dict:
    """
    A state dict where every term other than the item-count bonus is zero:
    kd 0, cs_per_min exactly 7.0, hp in the [60, 85) dead band, no deaths,
    empty objectives, gpm 350 (inside the (280, 420) dead band).
    Baseline pct with no qualifying items is therefore exactly 50.0.
    """
    return {
        "ally_kills_total": 0,
        "enemy_kills_total": 0,
        "cs_per_min": 7.0,
        "hp_pct": 70,
        "dead_count": 0,
        "items": items,
        "objectives": "",
        "gold": 3500,
        "game_seconds": 600,
    }


def _old_items_comprehension(state: dict) -> list:
    """Verbatim copy of the PRE-FIX loop at app/_state_authority.py:86-88."""
    return [i for i in state.get("items", [])
            if i and not any(x in i.lower() for x in _EXCLUDED)]


# -- the clamp is what makes the int case survive ----------------------------

def test_old_comprehension_raises_on_int_but_clamped_function_survives():
    state = _neutral_state([1])
    with pytest.raises(AttributeError):
        _old_items_comprehension(state)
    # Same input through the shipped function: no exception, and an int is
    # not an item, so the bonus is the empty-items baseline.
    assert StateAuthority.calc_win_pct(state) == 50.0


def test_old_comprehension_raises_type_error_on_bytes():
    # bytes DOES have .lower(), so the pre-fix failure for bytes is the
    # str-in-bytes substring test, not the attribute lookup.
    with pytest.raises(TypeError):
        _old_items_comprehension(_neutral_state([b"Infinity Edge"]))


# -- ints --------------------------------------------------------------------

def test_int_items_do_not_raise_and_bonus_counts_only_strings():
    state = _neutral_state([1, "Infinity Edge", "Kraken Slayer", 2])
    assert StateAuthority.calc_win_pct(state) == 54.0  # 2 str items -> +4


def test_all_int_list_yields_same_pct_as_empty_items():
    assert (StateAuthority.calc_win_pct(_neutral_state([1, 2, 3]))
            == StateAuthority.calc_win_pct(_neutral_state([]))
            == 50.0)


def test_bool_and_float_are_not_str_and_are_skipped():
    # bool is an int subclass; float is neither. Neither may count.
    state = _neutral_state([True, 3.5, "Infinity Edge", "Kraken Slayer"])
    assert StateAuthority.calc_win_pct(state) == 54.0


# -- bytes -------------------------------------------------------------------

def test_bytes_items_counted_after_utf8_decode():
    state = _neutral_state([b"Infinity Edge", b"Kraken Slayer", b"Lord Dominik's Regards"])
    assert StateAuthority.calc_win_pct(state) == 58.0  # 3 real items -> +8


def test_bytes_consumable_is_excluded_after_decode():
    state = _neutral_state([b"Stealth Ward", b"Health Potion", b"Infinity Edge", b"Kraken Slayer"])
    assert StateAuthority.calc_win_pct(state) == 54.0  # ward + potion excluded


def test_invalid_utf8_bytes_decode_with_replace_and_still_count():
    # errors="replace" turns the bad byte into U+FFFD instead of raising.
    state = _neutral_state([b"\xff\xfe Infinity Edge", b"Kraken Slayer", b"Bloodthirster"])
    assert StateAuthority.calc_win_pct(state) == 58.0


def test_empty_bytes_is_falsy_and_skipped_like_empty_str():
    state = _neutral_state([b"", "", "Infinity Edge", "Kraken Slayer"])
    assert StateAuthority.calc_win_pct(state) == 54.0


# -- None / dict / list / mixed ----------------------------------------------

def test_none_dict_and_list_elements_are_skipped():
    state = _neutral_state([
        None,
        {"displayName": "Infinity Edge"},   # a raw Live Client row, not a name
        ["Kraken Slayer"],
        "Bloodthirster",
    ])
    # Only "Bloodthirster" is a str: 1 item -> no bonus.
    assert StateAuthority.calc_win_pct(state) == 50.0


def test_mixed_list_counts_only_str_and_decoded_bytes():
    state = _neutral_state([
        1, None, b"Infinity Edge", "Kraken Slayer", {"a": 1}, [],
        "Health Potion", 3.5, "Bloodthirster", (), 0,
    ])
    # Infinity Edge (bytes) + Kraken Slayer + Bloodthirster = 3 -> +8;
    # Health Potion excluded; every other element skipped.
    assert StateAuthority.calc_win_pct(state) == 58.0


# -- existing behaviour pinned (green before and after the fix) --------------

@pytest.mark.parametrize("items, expected", [
    (["Infinity Edge", "Kraken Slayer", "Bloodthirster"], 58.0),   # 3 -> +8
    (["Infinity Edge", "Kraken Slayer"], 54.0),                     # 2 -> +4
    (["Infinity Edge"], 50.0),                                      # 1 -> +0
    ([], 50.0),                                                     # 0 -> +0
    (["Infinity Edge", "Kraken Slayer", "Bloodthirster", "Guardian Angel"], 58.0),  # cap +8
])
def test_item_count_bonus_pinned(items, expected):
    assert StateAuthority.calc_win_pct(_neutral_state(items)) == expected


def test_wards_potions_biscuit_doran_elixir_excluded():
    state = _neutral_state([
        "Stealth Ward", "Control Ward", "Health Potion", "Refillable Potion",
        "Total Biscuit of Everlasting Will", "Doran's Blade", "Elixir of Wrath",
        "Infinity Edge", "Kraken Slayer",
    ])
    assert StateAuthority.calc_win_pct(state) == 54.0  # only the 2 real items count


def test_exclusion_is_case_insensitive():
    state = _neutral_state(["STEALTH WARD", "health POTION", "Infinity Edge", "Kraken Slayer"])
    assert StateAuthority.calc_win_pct(state) == 54.0


def test_missing_items_key_is_treated_as_empty():
    state = _neutral_state([])
    del state["items"]
    assert StateAuthority.calc_win_pct(state) == 50.0


# -- range + shape ---------------------------------------------------------------

def _assert_int_valued_number_in_range(val) -> None:
    # int OR float (never bool), finite, whole-valued, inside [5, 95].
    assert isinstance(val, (int, float)) and not isinstance(val, bool), type(val)
    assert math.isfinite(val)
    assert val == int(val), val
    assert 5 <= val <= 95, val


def test_interior_result_is_int_valued_float_within_5_95_for_clamped_inputs():
    for items in ([1, 2, 3],
                  [None, b"Infinity Edge", {"x": 1}, "Kraken Slayer", ["a"]]):
        val = StateAuthority.calc_win_pct(_neutral_state(items))
        _assert_int_valued_number_in_range(val)
        # Off the clamps the arithmetic is float all the way through.
        assert isinstance(val, float), type(val)


def test_result_stays_within_5_95_at_the_extremes():
    best = {
        "ally_kills_total": 30, "enemy_kills_total": 0, "cs_per_min": 12.0,
        "hp_pct": 100, "dead_count": 5,
        "items": ["Infinity Edge", "Kraken Slayer", "Bloodthirster", 7, b"Guardian Angel"],
        "objectives": "baron up, drake up, soul", "gold": 20000, "game_seconds": 600,
    }
    worst = {
        "ally_kills_total": 0, "enemy_kills_total": 30, "cs_per_min": 0.0,
        "hp_pct": 10, "dead_count": 0, "items": [0, None, {}, [], b""],
        "objectives": "", "gold": 100, "game_seconds": 600,
    }
    hi = StateAuthority.calc_win_pct(best)
    lo = StateAuthority.calc_win_pct(worst)
    _assert_int_valued_number_in_range(hi)
    _assert_int_valued_number_in_range(lo)
    # best: 50 +15 +10 +4 +12 +8 +3 +6 +5 = 113 -> clamped to 95. At the
    # clamp the value is the INT bound (premise (3) in the module docstring):
    # min(95, 113.0) returns the literal 95 and round(95, 0) stays int.
    assert hi == 95
    assert isinstance(hi, int), type(hi)
    # worst with non-negative inputs: 50 -15 -10 -8 -5 = 12; the arithmetic
    # floor sits ABOVE the 5 clamp, so the clamp is not reached and the
    # result is still the interior float.
    assert lo == 12.0
    assert isinstance(lo, float), type(lo)


def test_lower_clamp_is_reachable_and_holds_at_5():
    # A negative dead_count is not a real input; it is the only term without
    # a lower bound (min(12, n * 4)), so it is the cheapest way to drive the
    # sum below 5 and pin the clamp itself. This pins the CLAMP, not the input.
    state = _neutral_state([1, None, b"", {}])
    state.update({"ally_kills_total": 0, "enemy_kills_total": 30, "dead_count": -50})
    val = StateAuthority.calc_win_pct(state)
    _assert_int_valued_number_in_range(val)
    # max(5, -188.0) returns the int literal 5; round(5, 0) is int 5.
    assert val == 5
    assert isinstance(val, int), type(val)


def test_calc_win_pct_stays_a_staticmethod():
    # Pure/static contract: callable on the class with no instance.
    assert isinstance(StateAuthority.__dict__["calc_win_pct"], staticmethod)
