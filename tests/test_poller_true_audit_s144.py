# arch: s144 true-audit - game_reader/poller.py hardening | section=tests | frozen=no
"""s144 true-audit of `game_reader/poller.py` (follows lane 8 cycle 14).

Live path: `core/sr_aram_worker.py` calls `read_game` every tick, which reads
the :8889 relay first and stamps `game_id` from the LCU relay through
`snapshot_normalizer` -> `_try_lcu_game_id`. The champ-select branch
(`read_champ_select`, `_ensure_lcu`, `_lcu_get`, `_process_champ_select`) still
has no production caller (repo grep, s144), so its tests harden a dormant path.

Findings pinned here, one test group each:
  H1 an HTTPError (the relay's 404 on every no-game tick) is closed, not left
     for the GC; `_try_lcu_game_id` and `_get` too.
  H2 `_try_relay` hands back only a dict `data` (its docstring's contract);
     a list / str / number read as "in game" to `check_in_game`.
  H3 `_try_lcu_game_id` returns only a canonical positive decimal id: a bool,
     float, container, negative or oversized value used to become "True",
     "1.5", "{'a': 1}" ... and reach ds_calibration / coach game_id fields.
  H4 `check_in_game` honours the relay's authoritative 404 (no 2 s direct
     probe) and needs a dict from /gamestats.
  H5 RM-1112: a pooled non-2xx LCU answer is not returned as a session, and
     is not re-sent through urlopen.
  H6 the lockfile port must be ASCII digits ("\\u0661\\u0662" passed isdigit()).
  H7 champ-select ids are positive ints (or ASCII digit strings) only.
  H8 the per-endpoint fallback keeps an endpoint only in its documented shape.
"""
from __future__ import annotations

import io
import json
import time
import types
import urllib.error

import pytest

from tests._module_view import bind_urlopen


def _mixin(**attrs):
    from game_reader.poller import _PollerMixin
    obj = _PollerMixin.__new__(_PollerMixin)
    obj._ssl = None
    obj._lcu_port = attrs.pop("port", None)
    obj._lcu_auth = attrs.pop("auth", None)
    for k, v in attrs.items():
        setattr(obj, k, v)
    return obj


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _serve(monkeypatch, payload, calls=None):
    from game_reader import poller

    def fake(req, context=None, timeout=None):
        if calls is not None:
            calls.append(req)
        return _Resp(json.dumps(payload).encode())

    bind_urlopen(monkeypatch, poller, fake)


def _raise_http(monkeypatch, code=404):
    from game_reader import poller
    fp = io.BytesIO(b'{"error": "no_liveclient_yet"}')
    err = urllib.error.HTTPError("http://127.0.0.1:8889/x", code, "nf", {}, fp)

    def fake(req, context=None, timeout=None):
        raise err

    bind_urlopen(monkeypatch, poller, fake)
    return fp


# ---------------------------------------------------------------------------
# H1 - an HTTPError is closed deterministically.
# ---------------------------------------------------------------------------

def test_relay_404_marks_no_game_and_closes_the_error(monkeypatch):
    fp = _raise_http(monkeypatch, 404)
    m = _mixin()
    assert m._try_relay() is None
    assert m._relay_says_no_game is True
    assert fp.closed, "the 404 HTTPError (one per no-game tick) was left open"


def test_lcu_game_id_closes_the_error(monkeypatch):
    fp = _raise_http(monkeypatch, 404)
    assert _mixin()._try_lcu_game_id() == ""
    assert fp.closed


def test_get_closes_the_error_and_still_raises(monkeypatch):
    fp = _raise_http(monkeypatch, 404)
    with pytest.raises(urllib.error.HTTPError):
        _mixin()._get("https://127.0.0.1:2999/liveclientdata/gamestats")
    assert fp.closed


# ---------------------------------------------------------------------------
# H2 - the relay hands back a dict or None.
# ---------------------------------------------------------------------------

def test_relay_char_fresh_dict_is_served(monkeypatch):
    _serve(monkeypatch, {"ts": time.time(), "data": {"gameData": {}}})
    assert _mixin()._try_relay() == {"gameData": {}}


@pytest.mark.parametrize("data", [[], [1], "x", "", 0, 1, True, 1.5])
def test_relay_non_dict_data_is_none(monkeypatch, data):
    calls = []
    _serve(monkeypatch, {"ts": time.time(), "data": data}, calls)
    assert _mixin()._try_relay() is None
    assert calls, "the scoped urlopen fake was never reached"


@pytest.mark.parametrize("wrap", [[1, 2], "error-free string", 7, None])
def test_relay_non_dict_envelope_is_none(monkeypatch, wrap):
    _serve(monkeypatch, wrap)
    m = _mixin()
    assert m._try_relay() is None
    assert m._relay_says_no_game is False


# ---------------------------------------------------------------------------
# H3 - the LCU relay game id is a canonical positive decimal or "".
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("gid, want", [
    (9, "9"),
    (7001234567, "7001234567"),
    ("7001234567", "7001234567"),
    (" 42 ", "42"),
])
def test_lcu_game_id_char_good_ids(monkeypatch, gid, want):
    _serve(monkeypatch, {"ts": time.time(), "data": {"game_id": gid}})
    assert _mixin()._try_lcu_game_id() == want


@pytest.mark.parametrize("gid", [
    True, 1.5, 7.0, -5, 0, "0", "000", "-5", "abc", "12 34", "1e9",
    "\u0661\u0662\u0663", {"a": 1}, [1], "9" * 30, 2 ** 64,
])
def test_lcu_game_id_junk_is_empty(monkeypatch, gid):
    calls = []
    _serve(monkeypatch, {"ts": time.time(), "data": {"game_id": gid}}, calls)
    assert _mixin()._try_lcu_game_id() == ""
    assert calls


# ---------------------------------------------------------------------------
# H4 - check_in_game mirrors read_game's relay contract.
# ---------------------------------------------------------------------------

def test_check_in_game_relay_404_skips_the_direct_probe(monkeypatch):
    _raise_http(monkeypatch, 404)
    m = _mixin()
    probed = []
    m._get = lambda url: probed.append(url) or {"gameTime": 1.0}
    assert m.check_in_game() is False
    assert probed == [], "a 404 is authoritative; the 2 s :2999 probe is waste"


@pytest.mark.parametrize("answer", [None, [], "x", 0])
def test_check_in_game_needs_a_dict_from_gamestats(answer):
    m = _mixin()
    m._try_relay = lambda: None
    m._relay_says_no_game = False
    m._get = lambda url: answer
    assert m.check_in_game() is False


def test_check_in_game_char_direct_dict_is_in_game():
    m = _mixin()
    m._try_relay = lambda: None
    m._relay_says_no_game = False
    m._get = lambda url: {"gameTime": 12.0}
    assert m.check_in_game() is True


# ---------------------------------------------------------------------------
# H5 - RM-1112: the pooled LCU status is checked.
# ---------------------------------------------------------------------------

def _pool(monkeypatch, answer):
    from core import lcu_pool
    monkeypatch.setenv("RC_LCU_POOL", "1")

    class _P:
        def request(self, host, port, method, path, headers=None, body=None):
            return answer

    monkeypatch.setattr(lcu_pool, "get_shared_pool", lambda: _P())


def _no_urlopen(monkeypatch):
    from game_reader import poller
    sent = []

    def fake(req, context=None, timeout=None):
        sent.append(req)
        raise AssertionError("urlopen must not re-send a pooled answer")

    bind_urlopen(monkeypatch, poller, fake)
    return sent


@pytest.mark.parametrize("status", [404, 500, 401, 302, 199, None, "200"])
def test_lcu_get_pooled_non_2xx_is_none_and_not_resent(monkeypatch, status):
    _pool(monkeypatch, (status, b'{"errorCode": "RPC_ERROR", "httpStatus": 404}'))
    sent = _no_urlopen(monkeypatch)
    m = _mixin(port="5000", auth="QUJD")
    assert m._lcu_get("/lol-champ-select/v1/session") is None
    assert sent == []


def test_lcu_get_char_pooled_200_is_parsed(monkeypatch):
    _pool(monkeypatch, (200, b'{"myTeam": []}'))
    _no_urlopen(monkeypatch)
    m = _mixin(port="5000", auth="QUJD")
    assert m._lcu_get("/lol-champ-select/v1/session") == {"myTeam": []}


def test_lcu_get_urlopen_path_closes_the_error(monkeypatch):
    monkeypatch.setenv("RC_LCU_POOL", "0")
    fp = _raise_http(monkeypatch, 404)
    m = _mixin(port="5000", auth="QUJD")
    with pytest.raises(urllib.error.HTTPError):
        m._lcu_get("/lol-champ-select/v1/session")
    assert fp.closed


def test_read_champ_select_pooled_error_body_is_none(monkeypatch):
    _pool(monkeypatch, (404, b'{"errorCode": "RPC_ERROR"}'))
    _no_urlopen(monkeypatch)
    m = _mixin(port="5000", auth="QUJD")
    assert m.read_champ_select() is None


def test_read_champ_select_pooled_non_json_2xx_is_none(monkeypatch):
    _pool(monkeypatch, (200, b"<html>not json</html>"))
    _no_urlopen(monkeypatch)
    m = _mixin(port="5000", auth="QUJD")
    assert m.read_champ_select() is None


# ---------------------------------------------------------------------------
# H6 - the lockfile port is ASCII digits.
# ---------------------------------------------------------------------------

def _no_wmic(monkeypatch):
    from game_reader import poller

    def _refuse(*_a, **_k):
        raise FileNotFoundError("wmic disabled in tests")

    monkeypatch.setattr(poller, "subprocess", types.SimpleNamespace(run=_refuse))


@pytest.mark.parametrize("port", ["\u0661\u0662\u0663\u0664", "\uff15\uff10\uff10\uff10"])
def test_lockfile_non_ascii_digit_port_is_rejected(monkeypatch, tmp_path, port):
    from game_reader.poller import _PollerMixin
    _no_wmic(monkeypatch)
    lf = tmp_path / "lockfile"
    lf.write_bytes(f"LeagueClient:1234:{port}:pw:https".encode())
    monkeypatch.setattr(_PollerMixin, "_LCU_LOCKFILE_PATHS", [lf])
    m = _mixin()
    assert m._ensure_lcu() is False
    assert m._lcu_port is None


def test_lockfile_char_leading_zero_port_is_canonical(monkeypatch, tmp_path):
    from game_reader.poller import _PollerMixin
    _no_wmic(monkeypatch)
    lf = tmp_path / "lockfile"
    lf.write_bytes(b"LeagueClient:1234:054321:pw:https")
    monkeypatch.setattr(_PollerMixin, "_LCU_LOCKFILE_PATHS", [lf])
    m = _mixin()
    assert m._ensure_lcu() is True
    assert m._lcu_port == "54321"


# ---------------------------------------------------------------------------
# H7 - champ-select ids are positive ints.
# ---------------------------------------------------------------------------

def test_champ_select_drops_junk_ids():
    m = _mixin()
    session = {
        "myTeam": [{"championId": 103}, {"championId": True},
                   {"championId": -1}, {"championId": 1.5},
                   {"championId": "abc"}, {"championId": {"x": 1}},
                   {"championId": "64"}],
        "theirTeam": [{"championId": [55]}, {"championId": 55}],
        "bans": {"myTeamBans": [17, True, -1, "x", 2.5, None, 0],
                 "theirTeamBans": ["22", {"id": 3}]},
    }
    out = m._process_champ_select(session)
    assert out["my_team_ids"] == ["103", "64"]
    assert out["their_team_ids"] == ["55"]
    assert out["ban_ids"] == ["17", "22"]


# ---------------------------------------------------------------------------
# H8 - the per-endpoint fallback keeps documented shapes only.
# ---------------------------------------------------------------------------

def test_fallback_drops_wrong_shaped_endpoints():
    payloads = {
        "gamestats": [1, 2],          # must be a dict
        "activeplayer": ["junk"],     # must be a dict
        "allplayers": {"not": "a list"},
        "eventdata": {"Events": []},
    }
    m = _mixin()
    m._get = lambda url: payloads[url.rsplit("/", 1)[-1]]
    out = m._read_game_fallback()
    assert out == {"events": {"Events": []}}


def test_fallback_char_documented_shapes_kept():
    payloads = {
        "gamestats": {"gameTime": 3.0},
        "activeplayer": {"level": 1},
        "allplayers": [{"championName": "Ahri"}],
        "eventdata": [{"EventName": "GameStart"}],
    }
    m = _mixin()
    m._get = lambda url: payloads[url.rsplit("/", 1)[-1]]
    out = m._read_game_fallback()
    assert out == {
        "gameData": {"gameTime": 3.0},
        "activePlayer": {"level": 1},
        "allPlayers": [{"championName": "Ahri"}],
        "events": {"Events": [{"EventName": "GameStart"}]},
    }
