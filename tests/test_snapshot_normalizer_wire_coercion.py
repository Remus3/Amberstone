# arch: regression - Live Client wire numerics must not crash or poison the snapshot | section=vision | frozen=no
"""Lane 8 cycle 17 - `game_reader/snapshot_normalizer.py` numeric hardening.

`_coerce_num` (snapshot_normalizer.py:90) exists because `json.loads` accepts
the NaN / Infinity / -Infinity literals as a CPython extension, so a poisoned
numeric survives the `:2999` boundary. Its own docstring records that the
primary relay read path (`game_reader/poller.py:155`) calls `_process_game`
UNWRAPPED, so an exception raised in normalization crashes the poll tick.

That hardening was applied to exactly ONE field - `currentGold`
(snapshot_normalizer.py:298) - and never to its siblings. Measured before the
fix, against the real `_process_game`:

  * `scores.creepScore` = "50"  -> TypeError: unsupported operand type(s)
    for /: 'str' and 'float'   (the cs_per_min division, :457)
  * `scores.creepScore` = None  -> TypeError, same site
  * `scores.creepScore` = NaN   -> cs_per_min = nan in the state dict

The CRASH is the severe half, and its consequence is worse than a lost tick:
the raise escapes `_process_game` into `core/sr_aram_worker.py:204`, whose
`except Exception` logs at DEBUG only. `none_streak` lives in the `else`
branch and so never increments, the game-end signal never fires, and the
dashboard keeps rendering the last good state AS IF LIVE, indefinitely, with
one DEBUG line as the only operator signal.

The NaN half is DELIBERATELY NOT claimed to break the dashboard. That
framing was tested and REFUTED: `json.dumps` does emit the bare literal
`{"cs_per_min": NaN}` (invalid JSON), but `cs_per_min` does not reach
`/api/state` as a raw number - its only route into `app.data` is
`StateAuthority.calc_win_pct`, and `app/_state_authority.py:79` computes
`min(10, max(-10, ...))`, where `max(-10, nan)` returns `-10` (measured).
NaN is clamped away before the browser sees anything. The real residual is
narrower: a NaN reaches the Haiku prompt as the literal `nan`
(`coach_integration/_sr_prompt.py:318`). These tests still pin the state
dict as finite and JSON-serializable, because that is the module's contract
regardless of which consumer currently launders it.

The same class reaches `_respawn_secs` (:779), whose `_RESPAWN_BASE` lookup is
`[min(level, 18)]` - clamped at the TOP only. Measured before the fix:

  * level = -1  -> 54, the LEVEL-18 value, because a negative index wraps to
    the end of the 19-element list. The maximally wrong answer.
  * level = 13.0 (float) -> TypeError: list indices must be integers
  * level = "13" / None  -> TypeError on the `min()` comparison

Both enemy (:795) and ally (:810) respawn paths read `level` straight off the
wire, so both crash the poll tick.

These tests pin the boundary contract: a hostile or merely wrong wire value
degrades to a sane default, and NEVER raises out of `_process_game` and NEVER
lands a non-finite float in the state dict.
"""

import json
import math
import re

import pytest

from game_reader.snapshot_normalizer import _NormalizerMixin


class _Host(_NormalizerMixin):
    """Minimal mixin host - mirrors the pattern in
    tests/test_silent_except_liveclient_subresource.py:35."""

    def __init__(self):
        self._enemy_last_seen: dict = {}
        self._enemy_death_time: dict = {}
        # `_process_game` zeroes these at the top of every tick; tests that
        # call `_calc_objectives` directly must stand in for that.
        self._order_towers_down = 0
        self._chaos_towers_down = 0
        self._inhib_kill_count = 0
        self._first_blood = False

    def _try_lcu_game_id(self):
        return None

    def _get(self, url):
        # The rune / ability subresources are not part of this contract; the
        # module already degrades them to empty and warns (silent-except A4).
        raise RuntimeError("subresource not available in this test")


def _envelope(*, creep=50, kills=1, deaths=0, assists=2,
              my_level=6, enemy_level=6, enemy_dead=False,
              ally_level=6, ally_dead=False):
    """A minimally complete `/allgamedata` envelope."""
    return {
        "activePlayer": {
            "level": my_level,
            "currentGold": 100,
            "summonerName": "Me#NA1",
            "championStats": {},
            "abilities": {},
            "fullRunes": {},
        },
        "gameData": {"gameMode": "CLASSIC", "gameTime": 600.0},
        "allPlayers": [
            {
                "championName": "Ahri", "riotIdGameName": "Me",
                "summonerName": "Me#NA1", "team": "ORDER",
                "level": my_level, "isDead": False,
                "scores": {"creepScore": creep, "kills": kills,
                           "deaths": deaths, "assists": assists},
                "items": [], "position": "MIDDLE",
            },
            {
                "championName": "Sona", "riotIdGameName": "Ally",
                "summonerName": "Ally#NA1", "team": "ORDER",
                "level": ally_level, "isDead": ally_dead,
                "scores": {"creepScore": 20, "kills": 0,
                           "deaths": 0, "assists": 5},
                "items": [], "position": "UTILITY",
            },
            {
                "championName": "Zed", "riotIdGameName": "En",
                "summonerName": "En#NA1", "team": "CHAOS",
                "level": enemy_level, "isDead": enemy_dead,
                "scores": {"creepScore": 10, "kills": 0,
                           "deaths": 1, "assists": 0},
                "items": [], "position": "MIDDLE",
            },
        ],
        "events": {"Events": []},
    }


# ----------------------------------------------------------------------
# Characterization - the happy path must not move
# ----------------------------------------------------------------------

def test_normal_envelope_still_normalizes():
    """Safety net: a well-formed envelope keeps producing the same numbers."""
    state = _Host()._process_game(_envelope())
    assert state["cs"] == 50
    assert state["cs_per_min"] == 5.0          # 50 cs / 10 min
    assert state["kills"] == 1
    assert state["deaths"] == 0
    assert state["assists"] == 2
    assert state["kda"] == "1/0/2"
    assert state["level"] == 6


def test_normal_envelope_state_is_json_serializable():
    """The state dict is serialized to the browser; it must be valid JSON."""
    state = _Host()._process_game(_envelope())
    text = json.dumps(state, default=str)
    assert "NaN" not in text
    assert "Infinity" not in text


# ----------------------------------------------------------------------
# creepScore - the division at :457
# ----------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["50", None, "", [], {}, "abc"])
def test_non_numeric_creepscore_does_not_raise(bad):
    """A wrong-typed creepScore must not crash the (unwrapped) poll tick."""
    state = _Host()._process_game(_envelope(creep=bad))
    assert isinstance(state["cs"], (int, float))
    assert isinstance(state["cs_per_min"], (int, float))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_creepscore_yields_finite_state(bad):
    """NaN / inf must not reach the state dict. `json.dumps` emits them as
    bare NaN / Infinity literals, which are invalid JSON - see the module
    docstring for why the dashboard is NOT currently harmed by this, and why
    the contract is pinned here anyway."""
    state = _Host()._process_game(_envelope(creep=bad))
    assert math.isfinite(state["cs"])
    assert math.isfinite(state["cs_per_min"])


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_creepscore_state_stays_valid_json(bad):
    state = _Host()._process_game(_envelope(creep=bad))
    text = json.dumps(state, default=str)
    assert "NaN" not in text
    assert "Infinity" not in text


def test_numeric_string_creepscore_is_coerced_not_dropped():
    """A numeric-looking string is real upstream drift, not garbage - keep
    the value rather than defaulting it away."""
    state = _Host()._process_game(_envelope(creep="50"))
    assert state["cs"] == 50
    assert state["cs_per_min"] == 5.0


# ----------------------------------------------------------------------
# kills / deaths / assists - the `_safe_kills` accumulators
# ----------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["3", None, [], {}])
def test_non_numeric_kills_does_not_raise(bad):
    """`_safe_kills` (:404) and `_derive_map._kills` (:735) do `total +=
    sc.get("kills", 0)`. They guard that `scores` is a dict but NOT that
    `kills` is numeric, despite the name."""
    state = _Host()._process_game(_envelope(kills=bad))
    assert isinstance(state["kills"], int)


@pytest.mark.parametrize("field", ["kills", "deaths", "assists"])
def test_kda_fields_are_always_int_in_state(field):
    """The state dict is a typed contract for the dashboard and coaches."""
    state = _Host()._process_game(_envelope(**{field: "7"}))
    assert isinstance(state[field], int)


def test_kda_string_is_built_from_coerced_values():
    state = _Host()._process_game(_envelope(kills="3", deaths="1", assists="4"))
    assert state["kda"] == "3/1/4"


# ----------------------------------------------------------------------
# _respawn_secs - the negative-index wraparound
# ----------------------------------------------------------------------

def test_respawn_base_table_shape():
    """Characterization: 19 entries, indices 0..18."""
    assert len(_NormalizerMixin._RESPAWN_BASE) == 19


@pytest.mark.parametrize("level,expected", [(1, 8), (18, 54), (25, 54)])
def test_respawn_secs_known_levels(level, expected):
    """Characterization: the top clamp already works."""
    assert _NormalizerMixin._respawn_secs(level, 600.0) == expected


@pytest.mark.parametrize("level", [-1, -5, -18, -19])
def test_respawn_secs_negative_level_does_not_wrap(level):
    """A negative index wraps to the END of the table, so level -1 returned
    54s - the LEVEL-18 respawn, the maximally wrong answer."""
    got = _NormalizerMixin._respawn_secs(level, 600.0)
    assert got == _NormalizerMixin._RESPAWN_BASE[0]


@pytest.mark.parametrize("level", [13.0, "13", None, [], {}])
def test_respawn_secs_non_int_level_does_not_raise(level):
    """Float levels raise TypeError on list indexing; str/None raise on the
    min() comparison. Both reach the unwrapped poll tick."""
    got = _NormalizerMixin._respawn_secs(level, 600.0)
    assert isinstance(got, int)


def test_respawn_secs_float_level_matches_its_int(level=13.0):
    assert (_NormalizerMixin._respawn_secs(level, 600.0)
            == _NormalizerMixin._respawn_secs(13, 600.0))


# ----------------------------------------------------------------------
# Integration - a hostile level must not crash _process_game
# ----------------------------------------------------------------------

@pytest.mark.parametrize("level", [13.0, "13", None, -1])
def test_dead_enemy_bad_level_does_not_crash_process_game(level):
    """`_dead_respawn_str` (:795) reads enemy level straight off the wire."""
    state = _Host()._process_game(_envelope(enemy_level=level, enemy_dead=True))
    assert isinstance(state, dict)


@pytest.mark.parametrize("level", [13.0, "13", None, -1])
def test_dead_ally_bad_level_does_not_crash_process_game(level):
    """`_ally_status_str` (:810) is the sibling site - same defect, same fix."""
    state = _Host()._process_game(_envelope(ally_level=level, ally_dead=True))
    assert isinstance(state, dict)


@pytest.mark.parametrize("level", [13.0, "13", None])
def test_bad_enemy_level_does_not_crash_threat_derivation(level):
    """`_derive_risk` (:727) compares `elv >= my_lv + 2` on raw wire values."""
    state = _Host()._process_game(_envelope(enemy_level=level))
    assert isinstance(state, dict)


# ----------------------------------------------------------------------
# Non-string identity fields - `.strip()` sits OUTSIDE its own try
# ----------------------------------------------------------------------

class _CountingHost(_Host):
    """Host that records subresource URLs instead of raising."""

    def __init__(self):
        super().__init__()
        self.urls = []

    def _get(self, url):
        self.urls.append(url)
        return {}


@pytest.mark.parametrize("bad", [12345, 3.5, True, ["a"], {"a": 1}])
def test_non_string_riot_id_does_not_crash_enemy_rune_read(bad):
    """`_read_enemy_runes` does `(e.get("riotIdGameName") or ...).strip()`
    BEFORE its try block opens, so a non-string identity field raises
    AttributeError straight out onto the unwrapped poll path."""
    host = _CountingHost()
    enemies = [{"championName": "Zed", "riotIdGameName": bad}]
    assert host._read_enemy_runes(enemies) == {}


def test_string_riot_id_still_reaches_the_endpoint():
    """Characterization: the normal path is unchanged and still quotes."""
    host = _CountingHost()
    host._read_enemy_runes([{"championName": "Zed", "riotIdGameName": "Some One"}])
    assert len(host.urls) == 1
    assert "Some%20One" in host.urls[0]


# ----------------------------------------------------------------------
# Snapshot factories - the two wholly-silent `return None` paths
# ----------------------------------------------------------------------

def test_to_rift_snapshot_none_input_returns_none():
    assert _NormalizerMixin.to_rift_snapshot(None) is None


def test_to_aram_snapshot_none_input_returns_none():
    assert _NormalizerMixin.to_aram_snapshot(None) is None


@pytest.mark.parametrize("factory", ["to_rift_snapshot", "to_aram_snapshot"])
def test_snapshot_factory_survives_non_numeric_level(factory):
    """`from_state_dict` raises on level="" (measured: ValueError), so the
    tier-2 ladder runs. Its per-field swallow must still yield a snapshot."""
    snap = getattr(_NormalizerMixin, factory)({"champion": "Ahri", "level": ""})
    assert snap is not None


@pytest.mark.parametrize("factory", ["to_rift_snapshot", "to_aram_snapshot"])
def test_snapshot_factory_does_not_explode_string_items(factory):
    """`list("abc")` silently yields ['a','b','c'] - a string where a list was
    expected became three bogus items rather than being rejected."""
    snap = getattr(_NormalizerMixin, factory)(
        {"champion": "Ahri", "level": "", "items": "Doran"}
    )
    assert snap is not None
    assert list(getattr(snap, "items", [])) != ["D", "o", "r", "a", "n"]


# ----------------------------------------------------------------------
# Negative elapsed time - game_time REGRESSES across a source switch
# ----------------------------------------------------------------------
# `game_reader/poller.py` alternates between a fresh direct :2999 read and a
# relay snapshot accepted up to RELAY_MAX_AGE_S = 12s stale. A direct read at
# game_time=600 followed by an 11s-stale relay read at game_time=589 makes
# `game_time - last_seen` NEGATIVE. The author already guarded exactly this
# for death times (`elapsed = max(0, ...)`) and did not carry it across.

# NO test is written for the `ago` clamp in `_derive_enemy_locations`, and
# that is deliberate. Mutation-testing it SURVIVED, and the survivor was then
# proven EQUIVALENT rather than explained away: the three buckets there are
# `< 8` visible, `< 45` MIA-with-seconds, else MIA, and EVERY negative value
# lands in the same `< 8` bucket as the clamped 0 (checked exhaustively over
# -10000..-1). The clamp cannot change an observable outcome, so a test for
# it would assert against unreachable state. It is kept only as defence in
# depth if those thresholds ever move. This also partly REFUTES the audit
# finding that motivated it - clamping does NOT stop a "40s-missing enemy
# reads as visible", because 0 is still `< 8`. The sibling clamp in
# `_gank_threat` IS behaviour-bearing (the negative renders into user-facing
# text) and IS pinned by the test below, which mutation-tests RED.


def test_enemy_seen_in_the_future_reports_no_negative_gank_window():
    """Same regression in `_gank_threat`: time_ago = -11 satisfied `< 12` and
    produced 'X in jg-bot -11s ago, likely ganking'."""
    host = _Host()
    host._enemy_last_seen["Zed"] = {"time": 640.0, "zone": "jg top", "dead": False}
    enemies = [{"championName": "Zed", "isDead": False,
                "position": {"x": 9000.0, "z": 9000.0}}]
    threat, _jg = host._gank_threat(enemies, [], {"x": 0.0, "z": 0.0},
                                    600.0, "ORDER")
    # The module legitimately uses " - " as a clause separator, so assert on a
    # negative NUMBER ("-11s"), not on any hyphen.
    assert not re.search(r"-\d", threat), f"negative elapsed rendered: {threat!r}"


# ======================================================================
# CRITICAL - defects on REAL, unmodified Riot data (not shape drift)
# ======================================================================

# ----------------------------------------------------------------------
# Turret kills were credited to CHAOS unconditionally
# ----------------------------------------------------------------------
# `_calc_objectives` read `ev.get("TowerTeam", ev.get("TeamID", ""))`.
# NEITHER key exists in the Live Client eventdata schema - repo-wide,
# "TowerTeam" appears on that one line and nowhere else. The real event
# carries the STRUCTURE NAME, which is how the rest of the tree already
# parses it (`dashboard/_liveclient.py:348-350`). The side token convention
# is authoritative at `core/district_fusion.py:85`:
# `_SIDE_BY_TOKEN = {"T1": "ORDER", "T2": "CHAOS"}`, and names whose
# structure DIED. So `team` was always "" and BOTH the `elif CHAOS` and the
# `else` incremented the same counter: `_order_towers_down` was structurally
# pinned at 0 for the life of the process.

def _turret_ev(name, t=300.0):
    return {"EventName": "TurretKilled", "EventTime": t, "TurretKilled": name}


def test_order_turret_loss_is_credited_to_order():
    host = _Host()
    host._calc_objectives([_turret_ev("Turret_T1_C_05_A")], 600.0)
    assert host._order_towers_down == 1
    assert host._chaos_towers_down == 0


def test_chaos_turret_loss_is_credited_to_chaos():
    host = _Host()
    host._calc_objectives([_turret_ev("Turret_T2_C_05_A")], 600.0)
    assert host._chaos_towers_down == 1
    assert host._order_towers_down == 0


def test_turret_kills_split_across_both_teams():
    """The headline regression: one turret each must NOT read as 0/2."""
    host = _Host()
    host._calc_objectives(
        [_turret_ev("Turret_T1_C_05_A", 300.0),
         _turret_ev("Turret_T2_L_03_A", 400.0)], 600.0)
    assert (host._order_towers_down, host._chaos_towers_down) == (1, 1)


def test_unparseable_turret_name_does_not_silently_credit_a_side():
    """An unknown token must not be laundered into a real count."""
    host = _Host()
    host._calc_objectives([_turret_ev("Nexus_Obelisk")], 600.0)
    assert (host._order_towers_down, host._chaos_towers_down) == (0, 0)


def test_turret_event_with_no_name_does_not_crash_or_credit():
    host = _Host()
    host._calc_objectives([{"EventName": "TurretKilled", "EventTime": 1.0}], 600.0)
    assert (host._order_towers_down, host._chaos_towers_down) == (0, 0)


# ----------------------------------------------------------------------
# A respawned-but-fogged enemy stayed flagged dead forever
# ----------------------------------------------------------------------
# `_update_enemy_tracking` pops `_enemy_death_time` when the record says
# dead, but only clears the record's own `dead` flag inside `if x or z:`.
# A champion who respawned and is walking back through fog reports
# position (0, 0), so that block never runs and `dead` stays True. The
# consumer then emits "SAFE - <jungler> is dead" for a living jungler -
# the most dangerous single inversion in a gank-threat field.

def _tracked_dead(host, name="Lee Sin", zone_time=900.0):
    host._enemy_last_seen[name] = {
        "zone": "jg top", "time": zone_time, "x": 5000.0, "z": 9000.0,
        "dead": True, "dead_time": 920.0,
    }
    host._enemy_death_time[name] = 920.0


def test_respawned_enemy_in_fog_is_no_longer_flagged_dead():
    host = _Host()
    _tracked_dead(host)
    # Alive again, but not visible: the Live Client reports (0, 0).
    host._update_enemy_tracking(
        [{"championName": "Lee Sin", "isDead": False,
          "position": {"x": 0.0, "z": 0.0}}], 950.0)
    assert host._enemy_last_seen["Lee Sin"]["dead"] is False


def test_respawned_enemy_in_fog_does_not_report_safe_is_dead():
    host = _Host()
    _tracked_dead(host)
    enemies = [{"championName": "Lee Sin", "isDead": False,
                "position": {"x": 0.0, "z": 0.0}}]
    host._update_enemy_tracking(enemies, 950.0)
    threat, _jg = host._gank_threat(enemies, [], {"x": 7000.0, "z": 7000.0},
                                    950.0, "ORDER")
    assert "is dead" not in threat


def test_respawned_enemy_in_fog_keeps_its_last_seen_zone():
    """`_derive_enemy_locations` discards the zone of a record flagged dead,
    so a good last-known position was thrown away as 'untracked'."""
    host = _Host()
    _tracked_dead(host)
    enemies = [{"championName": "Lee Sin", "isDead": False,
                "position": {"x": 0.0, "z": 0.0}}]
    host._update_enemy_tracking(enemies, 950.0)
    out = host._derive_enemy_locations(enemies, 950.0, {"x": 0.0, "z": 0.0})
    assert "untracked" not in out


def test_still_dead_enemy_is_still_reported_dead():
    """Control: the fix must not stop a genuinely dead enemy reading dead."""
    host = _Host()
    _tracked_dead(host)
    enemies = [{"championName": "Lee Sin", "isDead": True,
                "position": {"x": 0.0, "z": 0.0}}]
    host._update_enemy_tracking(enemies, 930.0)
    assert host._enemy_last_seen["Lee Sin"]["dead"] is True


# ----------------------------------------------------------------------
# _normalize_name - the sibling identity crash
# ----------------------------------------------------------------------
# `_normalize_name` does `name.split("#")` after only a falsy guard, so a
# TRUTHY non-string raises AttributeError. It is called twice from the
# self-identification loop inside `_process_game` (on `activePlayer` and on
# every entry of `allPlayers`), i.e. on the unwrapped relay path. Same class
# as the `_read_enemy_runes` `.strip()` above; found by grepping for the
# sibling sites rather than by the failure.

@pytest.mark.parametrize("bad", [12345, 3.5, ["a"], {"a": 1}, True])
def test_normalize_name_non_string_does_not_raise(bad):
    from game_reader.snapshot_normalizer import _normalize_name
    assert _normalize_name(bad) == ""


def test_normalize_name_still_strips_tag_and_lowercases():
    """Characterization: the real contract is unchanged."""
    from game_reader.snapshot_normalizer import _normalize_name
    assert _normalize_name("  Moon#EUW ") == "moon"
    assert _normalize_name("") == ""


@pytest.mark.parametrize("field", ["riotIdGameName", "summonerName"])
def test_non_string_identity_on_active_player_does_not_crash_tick(field):
    """The crash reaches `_process_game` itself, not just the helper."""
    env = _envelope()
    env["activePlayer"][field] = 12345
    assert isinstance(_Host()._process_game(env), dict)


def test_non_string_identity_on_a_player_row_does_not_crash_tick():
    env = _envelope()
    env["allPlayers"][2]["riotIdGameName"] = 999
    assert isinstance(_Host()._process_game(env), dict)
