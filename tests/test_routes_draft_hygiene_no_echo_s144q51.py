"""RM-1255 (RM-1255) residue: the draft-elo, draft-score and session-hygiene
id 400s never echo the caller's value.

Before the fix these three routes built a 400 text from the caller's own
token:

- ``/api/draft-elo``: ``non-integer id 'zz'`` (ally / enemy) and
  ``non-integer queue id 'zz'`` - a full, unclipped repr;
- ``/api/draft-score``: ``invalid id 'zz'`` (a clipped repr),
  ``invalid id 0`` and ``duplicate id 420``;
- ``/api/session-hygiene``: ``invalid queue id 'zz'`` (a clipped repr)
  and ``duplicate queue id 420``.

That is the RM-1233 echo (``/api/ban-suggest``), which now names only the
parameter and the expected shape. Acceptance pinned here: every one of
these 400s is ``<param>: <fixed expected-shape text>``, the distinctive
junk the caller sent is absent from the raw body, and two different junk
values give byte-identical bodies. Each case is driven through the route
entry point with its compute patched, so a value that slipped past
validation would show up as a 200 (and a recorded compute call), never as
a fixture-dependent 503.

The front-end consumers (web/js/panels/draft_elo.js, draft_score.js,
session_hygiene.js) render degraded text on any error and never show the
``error`` string, so the change is invisible in the UI.
"""
from __future__ import annotations

import json

import pytest

from dashboard import routes_draft_elo as rde
from dashboard import routes_draft_score as rds
from dashboard import routes_session_hygiene as rsh

# Literal copies, not imports of the module constants, so a message that
# regains the caller's token fails here.
_ELO_BAD = "each id must be an integer"
_DIGITS_BAD = "each id must be 1-6 ASCII digits"
_BELOW_ONE = "each id must be 1 or more"
_DUPLICATE = "duplicate ids are not allowed"


class _Harness:
    def __init__(self, path: str, qs: str):
        self.path = f"{path}?{qs}"
        self.sent: list[tuple[int, dict, bytes]] = []

    def _send(self, status, body, content_type):
        self.sent.append((status, json.loads(body), body))


@pytest.fixture
def calls(monkeypatch):
    seen: list = []

    def elo(ally, enemy, queues):
        seen.append(("elo", ally, enemy, queues))
        return {"ok": True}

    def score(ally, **kw):
        seen.append(("score", ally, kw.get("queue_ids")))
        return {"ok": True}

    def hygiene(queue_ids=None):
        seen.append(("hygiene", queue_ids))
        return {"ok": True, "n": 0}

    monkeypatch.setattr(rde, "_compute", elo)
    monkeypatch.setattr(rds.draft_score, "compute_draft_score", score)
    monkeypatch.setattr(rsh.session_hygiene, "compute_session_hygiene", hygiene)
    for mod in (rde, rds, rsh):
        with mod._CACHE_LOCK:
            mod._CACHE.clear()
    yield seen
    for mod in (rde, rds, rsh):
        with mod._CACHE_LOCK:
            mod._CACHE.clear()


_ROUTES = {
    "elo": ("/api/draft-elo", rde._serve_draft_elo),
    "score": ("/api/draft-score", rds._serve_draft_score),
    "hygiene": ("/api/session-hygiene", rsh._serve_session_hygiene),
}

_TEAM = "1,2,3,4,5"
_FOES = "6,7,8,9,10"

# (route, query template with {junk}, junk A, junk B, expected error text)
_CASES = [
    ("elo", "ally={junk},2,3,4,5&enemy=" + _FOES, "zzJUNKzz", "qqOTHERqq",
     "ally: " + _ELO_BAD),
    ("elo", "ally=" + _TEAM + "&enemy={junk},7,8,9,10", "zzJUNKzz",
     "qqOTHERqq", "enemy: " + _ELO_BAD),
    ("elo", "ally=" + _TEAM + "&enemy=" + _FOES + "&queue=420,{junk}",
     "zzJUNKzz", "qqOTHERqq", "queue: " + _ELO_BAD),
    ("elo", "ally={junk},2,3,4,5&enemy=" + _FOES, "%3Cb%3Ex%3C%2Fb%3E",
     "%27%22%5C", "ally: " + _ELO_BAD),
    ("score", "ally={junk},2,3,4,5", "zzJUNKzz", "qqOTHERqq",
     "ally: " + _DIGITS_BAD),
    ("score", "ally=" + _TEAM + "&enemy={junk},7,8,9,10", "zzJUNKzz",
     "qqOTHERqq", "enemy: " + _DIGITS_BAD),
    ("score", "ally=" + _TEAM + "&queue={junk}", "zzJUNKzz", "qqOTHERqq",
     "queue: " + _DIGITS_BAD),
    ("score", "ally={junk},2,3,4,5", "98765432109876", "12345678901234",
     "ally: " + _DIGITS_BAD),
    ("score", "ally={junk},2,3,4,5", "000000", "00000", "ally: " + _BELOW_ONE),
    ("score", "ally=" + _TEAM + "&queue={junk},{junk}", "420", "450",
     "queue: " + _DUPLICATE),
    ("hygiene", "queue={junk}", "zzJUNKzz", "qqOTHERqq",
     "queue: " + _DIGITS_BAD),
    ("hygiene", "queue={junk}", "x" * 5000, "y" * 300, "queue: " + _DIGITS_BAD),
    ("hygiene", "queue=420,{junk}", "%D9%A3%D9%A3", "-420",
     "queue: " + _DIGITS_BAD),
    ("hygiene", "queue={junk},{junk}", "420", "450", "queue: " + _DUPLICATE),
]


def _serve(route: str, qs: str):
    path, entry = _ROUTES[route]
    h = _Harness(path, qs)
    entry(h)
    assert len(h.sent) == 1, h.sent
    return h.sent[0]


def _junk_needle(junk: str) -> str:
    """The text a caller value would leave in the raw body: the decoded
    token, or for a long run its first 12 characters."""
    from urllib.parse import unquote
    text = unquote(junk)
    return text[:12]


@pytest.mark.parametrize("route,tmpl,junk_a,junk_b,expected", _CASES,
                         ids=[f"{c[0]}-{i}" for i, c in enumerate(_CASES)])
def test_400_names_param_and_shape_never_the_value(calls, route, tmpl,
                                                   junk_a, junk_b, expected):
    status_a, body_a, raw_a = _serve(route, tmpl.format(junk=junk_a))
    status_b, body_b, raw_b = _serve(route, tmpl.format(junk=junk_b))
    assert status_a == 400, body_a
    assert status_b == 400, body_b
    assert body_a == {"ok": False, "error": expected}
    # Two different junk values give byte-identical bodies.
    assert raw_a == raw_b
    for junk in (junk_a, junk_b):
        needle = _junk_needle(junk)
        assert needle not in body_a["error"].replace(expected, ""), needle
        assert json.dumps(needle)[1:-1] not in raw_a.decode("ascii").replace(
            json.dumps(expected)[1:-1], ""), needle
    assert calls == [], "a rejected request reached compute"


def test_positive_control_valid_requests_reach_compute(calls):
    """A valid request on each route is a 200 that reaches compute, so the
    400s above are refusals, not a harness that refuses everything."""
    s1, b1, _ = _serve("elo", f"ally={_TEAM}&enemy={_FOES}&queue=420")
    s2, b2, _ = _serve("score", f"ally={_TEAM}&queue=420")
    s3, b3, _ = _serve("hygiene", "queue=420,450")
    assert (s1, s2, s3) == (200, 200, 200), (b1, b2, b3)
    assert [c[0] for c in calls] == ["elo", "score", "hygiene"]
