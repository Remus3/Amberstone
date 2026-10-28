"""s144 true-audit (RM-1034) - lcu/lcu_pregame.py hardening.

Six findings, each pinned by a test that was RED on the unfixed module:

  1. `_as_int` was not total. `json.loads` accepts the bare token
     `Infinity`, and `int(float("inf"))` raises OverflowError, which the
     `(TypeError, ValueError)` catch let through - so every "total by
     contract" session reader raised on it. It also read a JSON `true` as
     id 1, truncated 3.9 to 3 and passed a negative id through as an id.
  2. The cell match compared `localPlayerCellId` with `==` against each
     entry's cell. A session whose local cell is JSON `null` (or absent,
     the -1 default) matched every entry whose cell was ALSO null or
     absent, so another player's champion, spells or pick action were
     read as mine; a JSON `true` cell matched cell 1. A non-dict session
     raised AttributeError out of the total readers.
  3. The LCU writers and the icon reader interpolated the caller's ids
     straight into the request path. A non-integer id reached the LCU as
     a different route (`7/../../x`), and `set_summoner_spells` PATCHed
     unvalidated spell ids, raised ValueError on a junk TARGET id in the
     idempotency compare, and treated the string "47" as the pair (4, 7)
     and so skipped a PATCH it owed.
  4. `_phase_or_none` reported any non-empty body as a phase: a truncated
     JSON object, an HTML error page or the bare JSON `null` came back as
     a truthy "phase". It is also the live predicate of
     `lcu/snapshot_shape.py`, so those reached `state["phase"]`.
  5. Both raw reads (`get_gameflow_phase` fallback, champion icon) read an
     unbounded body into memory.
  6. `_aram_mode` was dead (no caller anywhere) and raised on a None mode.
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from unittest import mock

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import lcu.lcu_pregame as pg  # noqa: E402
from lcu.lcu_pregame import LcuPregame  # noqa: E402
from tests._module_view import bind_urlopen  # noqa: E402


class _Stub(LcuPregame):
    """The mixin needs `_port`, `_auth` and `_request`; nothing else."""

    def __init__(self, result=None, *, port="12345", auth="dG9r"):
        self._port = port
        self._auth = auth
        self._ssl = None
        self._result = result
        self.calls: list[tuple] = []

    def _request(self, method, path, data=None):
        self.calls.append((method, path, data))
        return self._result


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body
        self.read_sizes: list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1) -> bytes:
        self.read_sizes.append(size)
        if size is None or size < 0:
            return self._body
        return self._body[:size]


@contextlib.contextmanager
def _bound_urlopen(resp):
    fake = mock.Mock(return_value=resp)
    with pytest.MonkeyPatch.context() as mp:
        bind_urlopen(mp, pg, fake)
        yield fake


def _session(local=0, **player_fields) -> dict:
    player = {"cellId": 0}
    player.update(player_fields)
    return {"localPlayerCellId": local, "myTeam": [player]}


# -- 1. _as_int totality -------------------------------------------------------

@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_as_int_non_finite_float_is_zero_not_raise(value):
    assert pg._as_int(value) == 0


def test_current_champion_infinite_id_does_not_raise():
    session = _session(championId=float("inf"), championPickIntent=266)
    assert _Stub().get_my_current_champion(session) == 266


def test_spells_infinite_id_does_not_raise():
    session = _session(spell1Id=float("inf"), spell2Id=4)
    assert _Stub().get_my_summoner_spells(session) == (0, 4)


def test_bench_infinite_id_is_skipped():
    session = {"benchChampions": [{"championId": float("inf")},
                                  {"championId": 103}]}
    assert _Stub().get_bench_champion_ids(session) == [103]


@pytest.mark.parametrize("value", [True, False])
def test_as_int_bool_is_not_an_id(value):
    assert pg._as_int(value) == 0


def test_as_int_non_integral_float_is_not_truncated():
    assert pg._as_int(3.9) == 0


def test_as_int_integral_float_still_coerces():
    assert pg._as_int(103.0) == 103


@pytest.mark.parametrize("value", [-1, "-7", -3.0])
def test_as_int_negative_is_not_an_id(value):
    assert pg._as_int(value) == 0


def test_bench_negative_id_is_skipped():
    session = {"benchChampions": [{"championId": -1}, {"championId": 7}]}
    assert _Stub().get_bench_champion_ids(session) == [7]


# -- 2. cell match ---------------------------------------------------------------

def test_null_local_cell_does_not_match_a_cell_less_entry():
    session = {"localPlayerCellId": None,
               "myTeam": [{"championId": 266}]}
    assert _Stub().get_my_current_champion(session) == 0


def test_absent_local_cell_does_not_match_a_minus_one_entry():
    session = {"myTeam": [{"cellId": -1, "spell1Id": 4, "spell2Id": 14}]}
    assert _Stub().get_my_summoner_spells(session) == (0, 0)


def test_null_local_cell_does_not_claim_an_actor_less_pick_action():
    session = {"localPlayerCellId": None,
               "actions": [[{"id": 9, "type": "pick", "completed": False}]]}
    assert _Stub().get_my_pick_action(session) is None


def test_bool_cell_does_not_match_cell_one():
    session = {"localPlayerCellId": 1,
               "myTeam": [{"cellId": True, "championId": 266},
                          {"cellId": 1, "championId": 103}]}
    assert _Stub().get_my_current_champion(session) == 103


@pytest.mark.parametrize("local,entry", [(True, 1), (-1, -1), ("0", "0"),
                                         (0.0, 0.0)])
def test_non_int_or_negative_local_cell_matches_nothing(local, entry):
    session = {"localPlayerCellId": local,
               "myTeam": [{"cellId": entry, "championId": 266}],
               "actions": [[{"id": 1, "actorCellId": entry, "type": "pick",
                             "completed": False}]]}
    s = _Stub()
    assert s.get_my_current_champion(session) == 0
    assert s.get_my_pick_action(session) is None


def test_bool_actor_cell_does_not_claim_my_pick_action():
    mine = {"id": 2, "actorCellId": 1, "type": "pick", "completed": False}
    session = {"localPlayerCellId": 1,
               "actions": [[{"id": 1, "actorCellId": True, "type": "pick",
                             "completed": False}, mine]]}
    assert _Stub().get_my_pick_action(session) is mine


@pytest.mark.parametrize("session", [None, [], "x", 7])
def test_non_dict_session_is_total(session):
    s = _Stub()
    assert s.get_my_pick_action(session) is None
    assert s.get_my_current_champion(session) == 0
    assert s.get_my_summoner_spells(session) == (0, 0)
    assert s.get_bench_champion_ids(session) == []


def test_matching_cell_happy_path_unchanged():
    session = _session(local=3, cellId=3, championId=103, spell1Id=4,
                       spell2Id=32)
    s = _Stub()
    assert s.get_my_current_champion(session) == 103
    assert s.get_my_summoner_spells(session) == (4, 32)


# -- 3. LCU write / read paths validate their ids ------------------------------

@pytest.mark.parametrize("bad", ["7/../../lol-login/v1/session", None, -1, 0,
                                 True, 3.5, "12"])
def test_pick_champion_refuses_a_bad_action_id_without_a_request(bad):
    s = _Stub(result={})
    assert s.pick_champion(bad, 103) is False
    assert s.calls == []


@pytest.mark.parametrize("bad", ["103/../x", None, -5, 0, False])
def test_pick_champion_refuses_a_bad_champion_id_without_a_request(bad):
    s = _Stub(result={})
    assert s.pick_champion(7, bad) is False
    assert s.calls == []


def test_pick_champion_happy_path_unchanged():
    s = _Stub(result={})
    assert s.pick_champion(7, 103) is True
    assert s.calls == [("PATCH", "/lol-champ-select/v1/session/actions/7",
                        {"championId": 103, "completed": True})]


def test_hover_champion_refuses_a_bad_id_without_a_request():
    s = _Stub(result={})
    assert s.hover_champion("7/x", 103) is False
    assert s.calls == []


@pytest.mark.parametrize("bad", ["103/../../lol-login/v1/session", None, 0,
                                 -1, True])
def test_bench_swap_refuses_a_bad_champion_id_without_a_request(bad):
    s = _Stub(result={})
    assert s.bench_swap_fast(bad) is False
    assert s.calls == []


def test_bench_swap_happy_path_unchanged():
    s = _Stub(result={})
    assert s.bench_swap_fast(105) is True
    assert s.calls == [("POST", "/lol-champ-select/v1/session/bench/swap/105",
                        None)]


@pytest.mark.parametrize("pair", [("x", 4), (4, None), (True, 4), (4, -1),
                                  (4, 0)])
def test_set_spells_refuses_a_bad_target_without_a_request(pair):
    s = _Stub(result={})
    assert s.set_summoner_spells(pair[0], pair[1]) is False
    assert s.calls == []


def test_set_spells_junk_target_with_current_pair_does_not_raise():
    s = _Stub(result={})
    assert s.set_summoner_spells("x", 4, current_pair=(4, 4)) is False
    assert s.calls == []


def test_set_spells_string_current_pair_is_not_a_pair():
    s = _Stub(result={})
    assert s.set_summoner_spells(4, 7, current_pair="47") is True
    assert len(s.calls) == 1


def test_set_spells_truncating_current_pair_is_not_a_match():
    s = _Stub(result={})
    assert s.set_summoner_spells(4, 7, current_pair=(4.9, 7.2)) is True
    assert len(s.calls) == 1


def test_set_spells_list_current_pair_still_matches():
    s = _Stub(result={})
    assert s.set_summoner_spells(4, 7, current_pair=[4, 7]) is True
    assert s.calls == []


def test_set_spells_three_element_current_pair_is_not_a_pair():
    s = _Stub(result={})
    assert s.set_summoner_spells(4, 7, current_pair=(4, 7, 1)) is True
    assert len(s.calls) == 1


def test_icon_refuses_a_bad_champion_id_without_a_fetch():
    resp = _FakeResponse(b"\x89PNG")
    with _bound_urlopen(resp) as fake:
        assert _Stub().get_champion_icon_bytes("1/../../x") is None
        assert _Stub().get_champion_icon_bytes(None) is None
    assert fake.call_count == 0


def test_icon_happy_path_returns_the_bytes():
    resp = _FakeResponse(b"\x89PNGdata")
    with _bound_urlopen(resp) as fake:
        assert _Stub().get_champion_icon_bytes(103) == b"\x89PNGdata"
    assert fake.call_count == 1
    assert fake.call_args[0][0].full_url.endswith("/champion-icons/103.png")


# -- 4. a non-phase body is not a phase ----------------------------------------

@pytest.mark.parametrize("body", ['{"errorCode": "RPC_ERROR"', "<html>502</html>",
                                  "null", '"null"', "Champ Select",
                                  "Lobby\nInProgress", "x" * 65])
def test_phase_or_none_rejects_a_non_phase_body(body):
    assert pg._phase_or_none(body) is None


@pytest.mark.parametrize("body,want", [('"Lobby"', "Lobby"),
                                       ("ChampSelect", "ChampSelect"),
                                       ('"None"', "None"),
                                       (' "InProgress"\n', "InProgress"),
                                       ("CheckedIntoTournament",
                                        "CheckedIntoTournament")])
def test_phase_or_none_real_phases_unchanged(body, want):
    assert pg._phase_or_none(body) == want


def test_phase_or_none_non_str_is_none():
    assert pg._phase_or_none(None) is None
    assert pg._phase_or_none(b"Lobby") is None


def test_gameflow_raw_fetch_garbage_body_is_not_a_phase():
    resp = _FakeResponse(b"<html>bad gateway</html>")
    with _bound_urlopen(resp):
        assert _Stub(result=None).get_gameflow_phase() is None


@pytest.mark.parametrize("body,want", [("<html>502</html>", None),
                                       (b'{"errorCode"', None),
                                       ("null", None),
                                       ('"ChampSelect"', "ChampSelect"),
                                       (b'"None"', "None")])
def test_snapshot_shape_publishes_only_a_real_phase(body, want):
    """The live consumer: lcu/snapshot_shape.py imports this predicate."""
    from lcu import snapshot_shape

    def request(method, path, data=None):
        if path == "/lol-gameflow/v1/gameflow-phase":
            return body, None
        return None, "404"

    snapshot_shape._reset_mastery_cache_for_tests()
    snapshot_shape._reset_summoner_lookup_cache_for_tests()
    try:
        assert snapshot_shape.shape_snapshot(request, {})["phase"] == want
    finally:
        snapshot_shape._reset_mastery_cache_for_tests()
        snapshot_shape._reset_summoner_lookup_cache_for_tests()


# -- 5. raw reads are bounded --------------------------------------------------

def test_gameflow_raw_fetch_oversized_body_is_not_read_whole():
    resp = _FakeResponse(b'"' + b"A" * (pg._PHASE_MAX_BYTES * 4) + b'"')
    with _bound_urlopen(resp):
        assert _Stub(result=None).get_gameflow_phase() is None
    assert resp.read_sizes and all(
        isinstance(n, int) and 0 < n <= pg._PHASE_MAX_BYTES + 1
        for n in resp.read_sizes)


def test_icon_oversized_body_is_refused():
    resp = _FakeResponse(b"\x89PNG" + b"0" * (pg._ICON_MAX_BYTES + 8))
    with _bound_urlopen(resp):
        assert _Stub().get_champion_icon_bytes(103) is None
    assert resp.read_sizes and all(
        isinstance(n, int) and 0 < n <= pg._ICON_MAX_BYTES + 1
        for n in resp.read_sizes)


def test_icon_body_at_the_cap_is_returned():
    body = b"0" * pg._ICON_MAX_BYTES
    resp = _FakeResponse(body)
    with _bound_urlopen(resp):
        assert _Stub().get_champion_icon_bytes(103) == body


# -- 6. dead helper ------------------------------------------------------------

def test_dead_aram_mode_helper_is_gone():
    assert not hasattr(pg, "_aram_mode")
