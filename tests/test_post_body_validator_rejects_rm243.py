"""RM-243: the POST body validator must REJECT, not log-and-dispatch.

One test per mapped route asserting a wrong-typed field is refused with a 400
that names the field, and that the route handler never runs. The response
carries pydantic's location + generic message only - never the raw
ValidationError text and never the offending input (RM-134).
"""
from __future__ import annotations

import json

import pytest

from dashboard import _dispatch


class _H:
    def __init__(self, path):
        self.path = path
        self.sent = None

    def _send(self, status, payload, ctype):
        self.sent = (status, payload, ctype)


@pytest.fixture
def reached(monkeypatch):
    hits = []
    monkeypatch.setattr(_dispatch, "_gather_post",
                        lambda: [(lambda p: True, lambda h, b: hits.append(b))])
    return hits


def _post(path, body):
    h = _H(path)
    assert _dispatch.dispatch_post(h, body) is True
    return h


CASES = [
    ("/api/input", {"text": 123}, "text"),
    ("/api/command", {"command": ["x"]}, "command"),
    ("/api/ds-preview", {"champion": "Ahri", "level": "six"}, "level"),
    ("/api/build-order", {"champion": "Ahri", "items": "3031"}, "items"),
    ("/api/speak", {"text": {"a": 1}}, "text"),
    ("/api/team-context/refresh", {"queue_id": "ranked"}, "queue_id"),
]


@pytest.mark.parametrize("path,body,field", CASES)
def test_wrong_typed_field_is_rejected(reached, path, body, field):
    h = _post(path, body)
    assert reached == [], "the bad body was dispatched anyway"
    assert h.sent[0] == 400
    out = json.loads(h.sent[1])
    assert out["error"] == "bad_request_body"
    assert any(f["field"].split(".")[0] == field for f in out["fields"]), out
    wire = h.sent[1].decode()
    assert "ValidationError" not in wire
    assert "six" not in wire and "ranked" not in wire  # no input echo


@pytest.mark.parametrize("path,body", [
    ("/api/input", {"text": "hello"}),
    ("/api/command", {"command": "force_vision"}),
    ("/api/ds-preview", {"champion": "Ahri", "mode": "SR", "level": 6,
                         "items": ["3031"], "enemies": ["Zed"]}),
    ("/api/build-order", {"champion": "Ahri", "mode": "SR", "level": 11,
                          "items": [], "slots": 6, "incumbent": ["1"]}),
    ("/api/team-context/refresh", {"queue_id": 420, "roster": [
        {"puuid": "p", "summoner_name": "s", "team_id": 100,
         "locked_champion": "Ahri"}]}),
])
def test_live_shaped_traffic_still_dispatches(reached, path, body):
    h = _post(path, body)
    assert reached == [body]
    assert h.sent is None


def test_unmapped_route_is_untouched(reached):
    h = _post("/api/coach/toggle", {"anything": object.__name__})
    assert len(reached) == 1 and h.sent is None
