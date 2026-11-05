"""RM-1377: POST /api/sr-draft/user-builds answered 500 for a non-string
``action``, ``champion`` or ``id``.

dashboard/routes_sr_user_builds.py ``_serve_user_builds_post`` read each of
the three fields as ``(payload.get(k) or "").strip()``. A truthy non-string
(``{"action": 5}``, ``{"champion": ["x"]}``, ``{"id": {"a": 1}}``) raised
AttributeError, and the blanket handler answered the generic 500 plus a
warning log line per request - a server error for a client one.

Fixed: each field is read by ``_text_field``. An absent key or JSON null is
"not sent" (the old default / "required" branches still answer it); any
other non-string is a fixed 400 naming the field, ``"<field>: must be a
string"``. The caller's value is never echoed.

Every case is driven through the route entry point the dashboard dispatches
to, with the store redirected to tmp_path so the real one is never read or
written.
"""
from __future__ import annotations

import json
import logging

import pytest

from dashboard import routes_sr_user_builds as ub

_MARK = "ECHOMARKq66"
_NON_STRINGS = [5, 0, 1.5, True, False, [_MARK], [], {_MARK: 1}, {}]
_NON_STRING_IDS = ["int-5", "int-0", "float", "true", "false", "list",
                   "empty-list", "dict", "empty-dict"]


class _Handler:
    def __init__(self, path: str = "/api/sr-draft/user-builds"):
        self.path = path
        self.sent = None

    def _send(self, code, body, ctype):
        self.sent = (code, body, ctype)

    @property
    def code(self):
        return self.sent[0]

    @property
    def raw(self) -> str:
        return self.sent[1].decode("utf-8")

    @property
    def payload(self):
        return json.loads(self.raw)


@pytest.fixture
def store(tmp_path, monkeypatch):
    from coaches import sr_user_builds as store_mod
    path = tmp_path / "user_builds.json"
    monkeypatch.setattr(store_mod, "_STORE_PATH", path)
    store_mod.clear_cache()
    try:
        yield store_mod, path
    finally:
        store_mod.clear_cache()


def _post(payload):
    h = _Handler()
    ub._serve_user_builds_post(h, payload)
    return h


def _assert_field_400(h, field):
    assert h.code == 400, h.sent
    assert h.payload == {"error": f"{field}: must be a string"}
    assert _MARK not in h.raw


@pytest.mark.parametrize("value", _NON_STRINGS, ids=_NON_STRING_IDS)
def test_non_string_action_is_a_fixed_400(value, store, caplog):
    _, path = store
    with caplog.at_level(logging.WARNING, logger="rc.web_dashboard"):
        h = _post({"action": value, "champion": "Tristana",
                   "build": {"label": "x"}})
    _assert_field_400(h, "action")
    assert not path.exists()
    # A client error is not a server fault: no per-request warning line.
    assert not [r for r in caplog.records
                if "user-builds POST" in r.getMessage()]


@pytest.mark.parametrize("value", _NON_STRINGS, ids=_NON_STRING_IDS)
@pytest.mark.parametrize("action", ["list", "add", "update", "delete"])
def test_non_string_champion_is_a_fixed_400(action, value, store):
    _, path = store
    h = _post({"action": action, "champion": value, "id": "aabbccdd",
               "build": {"label": "x"}, "patch": {"label": "y"}})
    _assert_field_400(h, "champion")
    assert not path.exists()


@pytest.mark.parametrize("value", _NON_STRINGS, ids=_NON_STRING_IDS)
@pytest.mark.parametrize("action", ["update", "delete"])
def test_non_string_id_is_a_fixed_400(action, value, store):
    store_mod, path = store
    new_id = store_mod.add("Tristana", {"label": "keep"})
    before = path.read_bytes()
    h = _post({"action": action, "champion": "Tristana", "id": value,
               "patch": {"label": "y"}})
    _assert_field_400(h, "id")
    assert path.read_bytes() == before
    assert [b["id"] for b in store_mod.list_for("Tristana")] == [new_id]


# -- positive controls: what was accepted before is still accepted --------

def test_absent_or_null_action_still_defaults(store):
    store_mod, path = store
    h = _post({"champion": "Tristana"})
    assert h.code == 200
    assert h.payload == {"champion": "Tristana", "builds": []}
    h = _post({"action": None, "champion": "Tristana",
               "build": {"label": "via-default"}})
    assert h.code == 200 and h.payload["ok"] is True
    assert [b["label"] for b in store_mod.list_for("Tristana")] == [
        "via-default"]


@pytest.mark.parametrize("value", [None, "", "   "],
                         ids=["null", "empty", "blank"])
def test_absent_champion_still_answers_champion_required(value, store):
    h = _post({"action": "list", "champion": value})
    assert h.code == 400
    assert h.payload == {"error": "champion required"}


@pytest.mark.parametrize("action,error", [
    ("update", "id + patch required"),
    ("delete", "id required"),
])
@pytest.mark.parametrize("value", [None, "", "  "],
                         ids=["null", "empty", "blank"])
def test_absent_id_still_answers_its_required_400(action, error, value,
                                                  store):
    h = _post({"action": action, "champion": "Tristana", "id": value,
               "patch": {"label": "y"}})
    assert h.code == 400
    assert h.payload == {"error": error}


def test_string_fields_still_round_trip_add_update_delete(store):
    store_mod, _ = store
    h = _post({"action": " ADD ", "champion": " Tristana ",
               "build": {"label": "first"}})
    assert h.code == 200, h.sent
    new_id = h.payload["id"]
    h = _post({"action": "update", "champion": "Tristana",
               "id": f" {new_id} ", "patch": {"label": "second"}})
    assert h.code == 200, h.sent
    assert [b["label"] for b in store_mod.list_for("Tristana")] == ["second"]
    h = _post({"action": "delete", "champion": "Tristana", "id": new_id})
    assert h.code == 200, h.sent
    assert store_mod.list_for("Tristana") == []
