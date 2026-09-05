# arch: regression - the TFT early-exit branch must coerce wire numerics too | section=vision | frozen=no
"""RM-344 (lane 8) - `game_reader/mode_router.py` TFT branch numeric hardening.

`game_reader/snapshot_normalizer.py` grew `_coerce_num` / `_coerce_int` for a
measured reason recorded in `_coerce_num`'s own docstring: `json.loads`
accepts the NaN / Infinity / -Infinity literals as a CPython extension, so a
poisoned numeric survives the `:2999` boundary, and the primary relay read
path (`game_reader/poller.py:155`, `return self._process_game(relay_raw)`)
calls `_process_game` UNWRAPPED - so anything that raises during
normalization kills the poll tick.

The TFT branch never got that hardening. `_process_game` early-returns
`tft_minimal_state(...)` BEFORE reaching the SR/ARAM coercion block, and
`tft_minimal_state` did four BARE `int()` calls on values read straight off
the wire. Measured on the pre-fix module, calling the real function:

  * `activePlayer.currentHP`   = None        -> TypeError: int() argument
    must be a string, a bytes-like object or a real number, not 'NoneType'
  * `activePlayer.currentGold` = NaN         -> ValueError: cannot convert
    float NaN to integer
  * `activePlayer.level`       = Infinity    -> OverflowError: cannot convert
    float infinity to integer

The `None` case is NOT hypothetical and is NOT covered by the `.get`
fallbacks: `active.get("currentHP", active.get("health", 100))` returns
`None` when the key is PRESENT with a JSON `null` value, because a present
key defeats the default. The fallback chain only fires on an ABSENT key.

Two deliberate NON-claims, so a later reader does not over-read this file:

  * `stage` / `round` never raised - they are interpolated into the
    `objectives` f-string, not passed to `int()`. They are coerced by the fix
    for consistency (a `nan`/`None` would otherwise render literally as
    "Stage nan-None" in the state dict), but the tick-killing claim covers
    only the four `int()` sites.
  * The fix coerces to the field's TERMINAL documented default; it does not
    re-walk the `.get` fallback chain. `{"currentHP": None, "health": 73}`
    yields 100, not 73. That is the pre-existing `.get` semantics preserved,
    pinned below so any future change to it is deliberate.
"""

import math

import pytest

from game_reader.mode_router import tft_minimal_state
from game_reader.snapshot_normalizer import _NormalizerMixin


class _Host(_NormalizerMixin):
    """Minimal mixin host - mirrors tests/test_snapshot_normalizer_wire_coercion.py:63."""

    def __init__(self):
        self._enemy_last_seen: dict = {}
        self._enemy_death_time: dict = {}
        self._order_towers_down = 0
        self._chaos_towers_down = 0
        self._inhib_kill_count = 0
        self._first_blood = False

    def _try_lcu_game_id(self):
        return None

    def _get(self, url):
        raise RuntimeError("subresource not available in this test")


def _tft_envelope(active=None, game_data=None):
    """A minimal `/allgamedata` envelope whose gameMode routes to the TFT branch."""
    gd = {"gameMode": "TFT", "gameTime": 305.0}
    if game_data:
        gd.update(game_data)
    return {
        "activePlayer": active if active is not None else {},
        "gameData": gd,
        "allPlayers": [],
        "events": {"Events": []},
    }


# The four fields that took a bare `int()` pre-fix, with the terminal default
# documented by their own `.get` chain in mode_router.tft_minimal_state.
_DEFAULTS = {"hp_pct": 100, "hp_abs": 100, "gold": 0, "level": 1}

# Every hostile wire value that made a bare `int()` raise.
_POISON = [
    pytest.param(None, id="json-null"),
    pytest.param(float("nan"), id="nan"),
    pytest.param(float("inf"), id="inf"),
    pytest.param(float("-inf"), id="neg-inf"),
]


# ----------------------------------------------------------------------
# The headline contract: the unwrapped relay path must not raise.
# ----------------------------------------------------------------------

def test_tft_branch_is_actually_reached():
    """Guard the guard - if routing changes, the rest of this file is vacuous."""
    state = _Host()._process_game(_tft_envelope({"currentHP": 50, "currentGold": 12, "level": 4}))
    assert isinstance(state, dict)
    assert state["champion"] == "TFT"
    assert state["hp_pct"] == 50
    assert state["gold"] == 12
    assert state["level"] == 4


@pytest.mark.parametrize("poison", _POISON)
def test_process_game_does_not_raise_on_poisoned_tft_payload(poison):
    """All four coerced fields poisoned at once - the tick must survive."""
    active = {"currentHP": poison, "currentGold": poison, "level": poison,
              "stage": poison, "round": poison}
    state = _Host()._process_game(_tft_envelope(active))
    assert isinstance(state, dict), "poisoned TFT payload must still yield a state dict"


def test_process_game_null_nan_inf_yields_documented_defaults():
    """The exact shape named by RM-344: null HP, NaN gold, inf level."""
    active = {"currentHP": None, "currentGold": float("nan"), "level": float("inf")}
    state = _Host()._process_game(_tft_envelope(active))
    assert state["hp_pct"] == 100
    assert state["hp_abs"] == 100
    assert state["gold"] == 0
    assert state["level"] == 1


@pytest.mark.parametrize("poison", _POISON)
@pytest.mark.parametrize("field,key", [
    ("currentHP", "hp_pct"),
    ("currentHP", "hp_abs"),
    ("currentGold", "gold"),
    ("level", "level"),
])
def test_one_bad_field_degrades_one_field(poison, field, key):
    """One poisoned field takes its own default and leaves the siblings intact."""
    active = {"currentHP": 63, "currentGold": 41, "level": 7}
    active[field] = poison
    state = _Host()._process_game(_tft_envelope(active))
    assert state[key] == _DEFAULTS[key]
    for other_key, healthy in (("hp_pct", 63), ("hp_abs", 63), ("gold", 41), ("level", 7)):
        if other_key == key or (field == "currentHP" and other_key in ("hp_pct", "hp_abs")):
            continue
        assert state[other_key] == healthy, f"{field} poison leaked into {other_key}"


@pytest.mark.parametrize("key", sorted(_DEFAULTS))
def test_coerced_fields_are_always_plain_ints(key):
    """No float, no bool, no NaN reaches the state dict - it feeds the overlay."""
    active = {"currentHP": float("nan"), "currentGold": None, "level": float("inf")}
    state = _Host()._process_game(_tft_envelope(active))
    assert type(state[key]) is int, f"{key} must be a plain int, got {type(state[key])!r}"
    assert math.isfinite(state[key])


# ----------------------------------------------------------------------
# stage / round - never raised, but must not render garbage either.
# ----------------------------------------------------------------------

def test_objectives_string_never_renders_a_poisoned_stage_or_round():
    """`objectives` is an f-string, so poison did not raise - it rendered."""
    active = {"currentHP": 50, "currentGold": 5, "level": 3,
              "stage": float("nan"), "round": None}
    state = _Host()._process_game(_tft_envelope(active))
    assert state["objectives"] == "Stage 1-1"
    for bad in ("nan", "inf", "None"):
        assert bad not in state["objectives"]


def test_stage_and_round_prefer_game_data_over_active_player():
    """Pin the existing precedence - game_info wins, active is the fallback."""
    active = {"currentHP": 50, "currentGold": 5, "level": 3, "stage": 9, "round": 9}
    state = _Host()._process_game(_tft_envelope(active, {"stage": 4, "roundNumber": 6}))
    assert state["objectives"] == "Stage 4-6"


# ----------------------------------------------------------------------
# Preserved semantics - the fix must not quietly change these.
# ----------------------------------------------------------------------

def test_numeric_looking_strings_are_preserved_not_discarded():
    """Upstream type drift is still the truth - "42" is 42, not the default.

    Inherited from `snapshot_normalizer._coerce_int`, whose docstring makes
    this an explicit contract. Pre-fix these ALSO worked (bare `int("42")`
    succeeds), so this pins behaviour the fix must not regress.
    """
    active = {"currentHP": "63", "currentGold": "41", "level": "7"}
    state = _Host()._process_game(_tft_envelope(active))
    assert (state["hp_pct"], state["gold"], state["level"]) == (63, 41, 7)


def test_present_null_key_does_not_re_walk_the_get_fallback_chain():
    """Deliberate non-claim, pinned: a present null takes the TERMINAL default.

    `active.get("currentHP", active.get("health", 100))` never consults
    `health` when `currentHP` is present-but-null, so the fix yields 100 and
    not 73. Change this only on purpose.
    """
    active = {"currentHP": None, "health": 73, "currentGold": 5, "level": 3}
    state = _Host()._process_game(_tft_envelope(active))
    assert state["hp_pct"] == 100


def test_game_end_event_still_short_circuits_to_none():
    """The GameEnd early return sits above the coercions - keep it reachable."""
    raw = _tft_envelope({"currentHP": None, "currentGold": float("nan")})
    raw["events"]["Events"] = [{"EventName": "GameEnd"}]
    assert _Host()._process_game(raw) is None


def test_tft_minimal_state_is_hardened_at_its_own_boundary():
    """Called directly, not only through `_process_game` - it is module-public."""
    state = tft_minimal_state(
        "TFT",
        {"currentHP": None, "currentGold": float("nan"), "level": float("inf")},
        {}, [], "5:05", 305.0,
    )
    assert (state["hp_pct"], state["gold"], state["level"]) == (100, 0, 1)
