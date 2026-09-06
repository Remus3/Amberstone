"""RM-347 - a gameflow read FAILURE must not be reported as the idle phase.

`LcuPregame.get_gameflow_phase` returned the string `"None"` from all
three of its bail-out paths, and `"None"` is a REAL phase:
`/lol-gameflow/v1/phase` serializes the client's no-flow state (sitting
at the home screen) to exactly that string, which is why the method's own
docstring listed it first among the values it returns.

So four distinct outcomes collapsed into one indistinguishable answer:

  1. transport failure (`_request` raises - client closed mid-poll,
     lockfile password rotated, connection refused),
  2. no credentials cached (`_port` / `_auth` unset),
  3. an unexpected body shape (a dict / int where a string was due),
  4. the operator genuinely idle at the home screen.

NOT every failure produced `"None"`, and the distinction is worth keeping
straight: an EMPTY JSON body took the `isinstance(result, str)` branch and
returned `''`, since `'""'.strip('"')` is `''`. That case was a different
defect of the same class - a non-phase reported as a phase - and it is
closed here too, but by the empty-body tests, not the idle-collision
ones.

A caller seeing `"None"` while the operator is actually in `ChampSelect`
concludes the client is idle and stops driving champ-select logic, with
nothing to retry on.

SENTINEL CHOICE. The failure value is Python `None` (`Optional[str]`),
not another string. The repo already carries two conventions for this
same class - `lcu/lcu_postgame_collector.py:1034` returns `""` and
`lcu/snapshot_shape.py:415-421` returns `"Unknown"` - so consistency
alone does not decide it. `None` is chosen because it is the value the
one live CONSUMER of a gameflow phase already treats as "unknown, do not
act": `dashboard/_cs_retention.py:49-56` says so in prose and enforces it
by listing the *string* `"None"` in `_CLEAR_PHASES` while a Python `None`
phase deliberately stays out. `test_consumer_contract_*` below pins that
asymmetry, because it is what makes the sentinel correct rather than
merely different.

REACHABILITY, measured 2026-09-05 and recorded here so it is not
inherited later: `get_gameflow_phase` has ZERO in-repo callers. A
repo-wide grep for `gameflow` finds the definition and its own debug log
line and nothing else; the live phase readers are `snapshot_shape.py`
(dashboard snapshot) and `lcu_postgame_collector.py` (EOG poll), neither
of which routes through this method. `LcuPregame` is mixed into
`LcuClient`, so this is public surface an external caller can reach, but
the defect is LATENT in this tree - the same finding RM-346 recorded for
the three session parsers one file over. That is also why the filing
row's second acceptance clause (a caller-side assertion) is answered by
the consumer-contract tests rather than by a real call path: there is no
call path to assert against, and inventing one would prove nothing.
"""
from __future__ import annotations

import sys
import urllib.error
from pathlib import Path
from typing import Optional
from unittest import mock

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from dashboard._cs_retention import (  # noqa: E402
    apply_cs_retention,
    reset_cs_retention,
)
from lcu.lcu_pregame import LcuPregame  # noqa: E402


class _Pregame(LcuPregame):
    """`LcuPregame` is a mixin with no `__init__`; it documents that
    `self._port`, `self._auth` and `self._request` come from `LcuClient`.
    This stub supplies exactly those three and nothing else, so a test
    cannot accidentally lean on transport state the mixin never had.
    """

    def __init__(self, result=None, *, raises=None, port="12345", auth="dG9r"):
        self._port = port
        self._auth = auth
        self._ssl = None
        self._result = result
        self._raises = raises
        self.calls: list[tuple] = []

    def _request(self, method, path, data=None):
        self.calls.append((method, path))
        if self._raises is not None:
            raise self._raises
        return self._result


class _FakeResponse:
    """Minimal stand-in for the `urlopen` context manager."""

    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._body


def _urlopen_returning(body: bytes):
    return mock.patch("urllib.request.urlopen", return_value=_FakeResponse(body))


def _urlopen_raising(exc: BaseException):
    return mock.patch("urllib.request.urlopen", side_effect=exc)


# -- The idle phase is still reported, and is still a string -------------------

def test_idle_phase_still_returns_the_string_none():
    """The client's genuine no-flow state must survive the fix. `"None"`
    is a real phase, so it stays a string - only FAILURES change."""
    assert _Pregame("None").get_gameflow_phase() == "None"


def test_idle_phase_survives_json_quoting():
    assert _Pregame('"None"').get_gameflow_phase() == "None"


# -- Failure paths are distinguishable from idle -------------------------------

def test_transport_exception_is_not_the_idle_phase():
    """The row's primary acceptance: `_request` raising must not read as
    "operator is idle at the home screen"."""
    pg = _Pregame(raises=OSError("connection refused"))
    out = pg.get_gameflow_phase()
    assert out is None
    assert out != "None"


def test_http_401_is_not_the_idle_phase():
    """A rotated lockfile password surfaces as a 401, the most likely
    real-world instance of this defect.

    This does NOT prove the handler is broader than `except OSError`:
    `HTTPError.__mro__` is HTTPError -> URLError -> OSError, measured, so
    a narrow `except OSError` would pass it too. It is a realism pin, not
    a breadth pin. Breadth is pinned by
    `test_non_oserror_exception_is_not_the_idle_phase` below."""
    pg = _Pregame(raises=urllib.error.HTTPError("u", 401, "Unauthorized", {}, None))
    assert pg.get_gameflow_phase() is None


def test_non_oserror_exception_is_not_the_idle_phase():
    """The breadth pin: a body that decodes but explodes downstream (the
    LCU has answered HTML error pages) raises something outside the
    OSError tree, so narrowing the handler would reintroduce the crash."""
    pg = _Pregame(raises=ValueError("Expecting value: line 1 column 1"))
    assert pg.get_gameflow_phase() is None


def test_missing_credentials_is_not_the_idle_phase():
    """No cached lockfile port/password is a read failure, not idleness."""
    pg = _Pregame(None, port=None, auth=None)
    assert pg.get_gameflow_phase() is None


def test_missing_port_alone_is_not_the_idle_phase():
    assert _Pregame(None, port=None, auth="dG9r").get_gameflow_phase() is None


def test_missing_auth_alone_is_not_the_idle_phase():
    assert _Pregame(None, port="12345", auth=None).get_gameflow_phase() is None


def test_dict_body_is_not_the_idle_phase():
    """A non-str, non-None body fell straight through to the `"None"`
    return without even attempting the raw fetch."""
    assert _Pregame({"phase": "ChampSelect"}).get_gameflow_phase() is None


def test_int_body_is_not_the_idle_phase():
    assert _Pregame(0).get_gameflow_phase() is None


def test_list_body_is_not_the_idle_phase():
    assert _Pregame([]).get_gameflow_phase() is None


def test_empty_body_is_not_a_phase():
    """An empty string is not a phase name. Reporting it as one would
    hand a caller a falsy value that still claims to be a live read."""
    assert _Pregame("").get_gameflow_phase() is None


def test_whitespace_only_body_is_not_a_phase():
    assert _Pregame('  ""  ').get_gameflow_phase() is None


# -- Happy paths preserved -----------------------------------------------------

def test_champ_select_phase_passes_through():
    assert _Pregame("ChampSelect").get_gameflow_phase() == "ChampSelect"


def test_quoted_phase_is_unwrapped():
    assert _Pregame('"InProgress"').get_gameflow_phase() == "InProgress"


def test_request_is_issued_against_the_gameflow_endpoint():
    pg = _Pregame("Lobby")
    pg.get_gameflow_phase()
    assert pg.calls == [("GET", "/lol-gameflow/v1/phase")]


# -- Raw-fetch fallback --------------------------------------------------------

def test_raw_fetch_returns_the_phase_when_request_returns_none():
    """`_request` returning None with credentials in hand is the LCU
    version that answers a bare string; the raw fetch handles it."""
    pg = _Pregame(None)
    with _urlopen_returning(b'"Lobby"'):
        assert pg.get_gameflow_phase() == "Lobby"


def test_raw_fetch_idle_phase_is_still_the_string():
    pg = _Pregame(None)
    with _urlopen_returning(b'"None"'):
        assert pg.get_gameflow_phase() == "None"


def test_raw_fetch_failure_is_not_the_idle_phase():
    pg = _Pregame(None)
    with _urlopen_raising(OSError("connection refused")):
        assert pg.get_gameflow_phase() is None


def test_raw_fetch_empty_body_is_not_a_phase():
    pg = _Pregame(None)
    with _urlopen_returning(b'""'):
        assert pg.get_gameflow_phase() is None


def test_raw_fetch_undecodable_body_is_not_the_idle_phase():
    pg = _Pregame(None)
    with _urlopen_returning(b"\xff\xfe\x00"):
        assert pg.get_gameflow_phase() is None


# -- Consumer contract: why Python None is the right sentinel ------------------
#
# These do not exercise `get_gameflow_phase` - it has no in-repo caller to
# exercise. They pin the asymmetry in `dashboard/_cs_retention.py` that the
# sentinel choice rests on: the STRING "None" is an explicit clear phase,
# a Python `None` phase is not. Were the failure value still `"None"`, a
# transient read error on a consumer built this way would drop live
# champ-select state; as `None` it holds.

@pytest.fixture(autouse=True)
def _isolate_cs_retention():
    """`dashboard._cs_retention` keeps a MODULE-level `_STATE`, and under
    `-n 8` xdist's default `--dist load` hands out individual tests, so
    this file's cases can interleave with `tests/test_cs_retention.py`
    inside one worker. Reset on both sides so neither file can see the
    other's retained snapshot."""
    reset_cs_retention()
    yield
    reset_cs_retention()


def _seed_retained_cs(now: float) -> None:
    apply_cs_retention({"phase": "ChampSelect", "champ_select": {"a": 1}}, now=now)


def _phase_drops_retained(phase: Optional[str]) -> bool:
    _seed_retained_cs(now=1000.0)
    out = apply_cs_retention({"phase": phase}, now=1001.0)
    return "champ_select" not in (out or {})


def test_consumer_contract_string_none_clears_retained_champ_select():
    assert _phase_drops_retained("None") is True


def test_consumer_contract_python_none_holds_retained_champ_select():
    assert _phase_drops_retained(None) is False


def test_consumer_contract_live_phase_holds_retained_champ_select():
    """Control: a real mid-transition phase also holds, so the previous
    assertion is about `None` specifically and not about every value."""
    assert _phase_drops_retained("InProgress") is False
