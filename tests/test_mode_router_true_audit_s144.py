# arch: s144 true-audit - game_reader/mode_router.py hardening | section=tests | frozen=no
"""s144 lane 8 (true-audit) - `game_reader/mode_router.py` hardening.

Every defect below was measured on the pre-fix module by calling the real
function (and, for the tick-killers, the real `_NormalizerMixin._process_game`,
which `game_reader.poller.read_game` calls UNWRAPPED):

  M1  `_coerce_int` caught TypeError / ValueError only. `json.loads` turns a
      long JSON integer literal (400 digits parses fine; the 4300-digit cap
      is far above it) into a Python int, and `float()` of that int raises
      OverflowError ("int too large to convert to float"). One such
      `currentGold` killed the TFT tick. Sibling: the SAME hole sat in
      `snapshot_normalizer._coerce_num`, so a long-int `gameTime` killed the
      SR / ARAM tick too (and every other `_coerce_num` / `_coerce_int` read).
  M2  `is_tft_mode` did `"TFT" in (game_mode or "")`: a numeric / bool
      gameMode raised TypeError ("argument of type 'int' is not a container
      or iterable") out of `_process_game`.
  M3  The same `in` test matched a LIST / DICT gameMode (["TFT"],
      {"TFT": 1}) as TFT and wrote the container into state["game_mode"].
  M4  `tft_minimal_state` passed any finite value through: currentHP 1e308
      became a 309-digit hp_pct beside hp_max 100, a negative HP / level /
      gold was served as-is, and stage 1e300 built a 300-digit `objectives`
      string.
  M5  `tft_minimal_state` (module-level, public) raised AttributeError on a
      non-dict `active` / `game_info` and TypeError on a non-iterable
      `events`. The one production caller guards those today; the function
      itself promised nothing.

Deliberate NON-changes, pinned so a later reader does not over-read the fix:
  * a bool still coerces like the snapshot_normalizer pair (JSON true -> 1):
    the module docstring promises the two copies cannot drift.
  * a numeric-looking string ("13") is still preserved.
  * TFT detection is still a SUBSTRING test on a str (TFT_TUTORIAL is TFT).
"""

import json

import pytest

from game_reader import mode_router
from game_reader.mode_router import (
    _coerce_int,
    is_aram_mode,
    is_tft_mode,
    tft_minimal_state,
    tower_count_for,
)
from game_reader.snapshot_normalizer import _coerce_num, _NormalizerMixin

# A JSON integer literal json.loads accepts but float() cannot hold.
_LONG_INT = json.loads('{"v": 1' + "0" * 400 + "}")["v"]


class _Host(_NormalizerMixin):
    """Minimal mixin host - mirrors tests/test_rm344_tft_coercion.py."""

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


def _envelope(game_mode="TFT", active=None, game_time=305.0, game_data=None):
    gd = {"gameMode": game_mode, "gameTime": game_time}
    if game_data:
        gd.update(game_data)
    return {
        "activePlayer": active if active is not None else {},
        "gameData": gd,
        "allPlayers": [],
        "events": {"Events": []},
    }


def _tft(active=None, game_info=None, events=None, game_mode="TFT"):
    return tft_minimal_state(game_mode, {} if active is None else active,
                             {} if game_info is None else game_info,
                             [] if events is None else events, "5:05", 305.0)


# ---------------------------------------------------------------- M1


def test_m1_long_json_int_is_a_real_wire_value():
    """Guard the guard: the fixture must be what json.loads really returns."""
    assert isinstance(_LONG_INT, int)
    with pytest.raises(OverflowError):
        float(_LONG_INT)


def test_m1_coerce_int_long_int_takes_default():
    assert _coerce_int(_LONG_INT, 7) == 7
    assert _coerce_int(-_LONG_INT, 3) == 3


def test_m1_snapshot_normalizer_coerce_num_long_int_takes_default():
    assert _coerce_num(_LONG_INT, 2.5) == 2.5
    assert _coerce_num(-_LONG_INT) == 0.0


def test_m1_tft_tick_survives_long_int_gold():
    state = _Host()._process_game(_envelope(active={"currentGold": _LONG_INT, "level": 4}))
    assert state["gold"] == 0
    assert state["level"] == 4


def test_m1_sr_tick_survives_long_int_game_time():
    state = _Host()._process_game(_envelope(game_mode="CLASSIC", game_time=_LONG_INT))
    assert isinstance(state, dict)
    assert state["game_time"] == "0:00"


# ---------------------------------------------------------------- M2 / M3


@pytest.mark.parametrize("junk", [5, 5.0, True, False, 0, -1.5],
                         ids=["int", "float", "true", "false", "zero", "neg-float"])
def test_m2_predicates_never_raise_on_numeric_mode(junk):
    assert is_tft_mode(junk) is False
    assert is_aram_mode(junk) is False
    assert tower_count_for(junk) == mode_router.SR_TOWER_COUNT


@pytest.mark.parametrize("junk", [5, 7.5, True])
def test_m2_process_game_survives_numeric_game_mode(junk):
    state = _Host()._process_game(_envelope(game_mode=junk))
    assert isinstance(state, dict)
    assert state["champion"] != "TFT"


@pytest.mark.parametrize("container", [["TFT"], ("TFT",), {"TFT": 1}, {"TFT"},
                                       ["ARAM"], {"KIWI": 1}],
                         ids=["list", "tuple", "dict", "set", "aram-list", "kiwi-dict"])
def test_m3_container_mode_is_neither_tft_nor_aram(container):
    assert is_tft_mode(container) is False
    assert is_aram_mode(container) is False


def test_m3_process_game_list_mode_does_not_take_tft_branch():
    state = _Host()._process_game(_envelope(game_mode=["TFT"]))
    assert isinstance(state, dict)
    assert state["champion"] != "TFT"


@pytest.mark.parametrize("mode,tft,aram", [
    ("TFT", True, False),
    ("TFT_TUTORIAL", True, False),   # substring semantics kept on a str
    ("ARAM", False, True),
    ("KIWI", False, True),
    ("ARAM_MAYHEM", False, True),
    ("CLASSIC", False, False),
    ("", False, False),
    (None, False, False),
])
def test_str_semantics_unchanged(mode, tft, aram):
    assert is_tft_mode(mode) is tft
    assert is_aram_mode(mode) is aram
    assert tower_count_for(mode) == (3 if aram else 11)


# ---------------------------------------------------------------- M4


def test_m4_hp_clamped_to_the_dicts_own_hp_max():
    s = _tft({"currentHP": 1e308})
    assert s["hp_pct"] == 100 and s["hp_abs"] == 100 and s["hp_max"] == 100
    s = _tft({"currentHP": 101})
    assert s["hp_pct"] == 100


def test_m4_negative_hp_reads_as_zero_not_as_a_value():
    s = _tft({"currentHP": -11})
    assert s["hp_pct"] == 0 and s["hp_abs"] == 0


def test_m4_in_range_values_preserved():
    s = _tft({"currentHP": 37, "currentGold": 54, "level": 8},
             {"stage": 4, "roundNumber": 2})
    assert (s["hp_pct"], s["gold"], s["level"]) == (37, 54, 8)
    assert s["objectives"] == "Stage 4-2"


def test_m4_negative_level_and_gold_clamped():
    s = _tft({"level": -7, "currentGold": -3}, {"stage": -2, "roundNumber": 0})
    assert s["level"] == 1
    assert s["gold"] == 0
    assert s["objectives"] == "Stage 1-1"


def test_m4_huge_values_bounded_and_objectives_short():
    s = _tft({"level": 1e300, "currentGold": 1e300}, {"stage": 1e300, "roundNumber": 1e300})
    assert s["level"] <= 99
    assert s["gold"] <= 99999
    assert len(s["objectives"]) <= len("Stage 99-99")


# ---------------------------------------------------------------- M5


@pytest.mark.parametrize("junk", [None, [], "x", 5])
def test_m5_non_dict_active_and_game_info_do_not_raise(junk):
    s = tft_minimal_state("TFT", junk, junk, [], "0:00", 0.0)
    assert s["hp_pct"] == 100 and s["level"] == 1 and s["objectives"] == "Stage 1-1"


@pytest.mark.parametrize("junk", [None, 5, {"EventName": "GameEnd"}])
def test_m5_non_list_events_do_not_raise_or_end_the_game(junk):
    s = tft_minimal_state("TFT", {}, {}, junk, "0:00", 0.0)
    assert isinstance(s, dict)


def test_m5_game_end_still_returns_none():
    assert _tft(events=[{"EventName": "GameStart"}, {"EventName": "GameEnd"}]) is None
    assert _tft(events=("x", {"EventName": "GameEnd"})) is None


def test_m5_non_str_game_mode_on_direct_call_reads_tft():
    assert _tft(game_mode=["TFT"])["game_mode"] == "TFT"
    assert _tft(game_mode="TFT_TUTORIAL")["game_mode"] == "TFT_TUTORIAL"


# ---------------------------------------------------------------- parity


@pytest.mark.parametrize("value", [True, False, "13", " 13 ", "13.9", "x", None,
                                   float("nan"), float("inf"), -4.2, _LONG_INT],
                         ids=["true", "false", "str13", "padded", "str13.9", "x", "none",
                              "nan", "inf", "neg", "long-int"])
def test_coerce_int_matches_snapshot_normalizer_pair(value):
    from game_reader.snapshot_normalizer import _coerce_int as sn_coerce_int
    assert _coerce_int(value, 9) == sn_coerce_int(value, 9)
