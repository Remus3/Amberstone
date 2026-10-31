"""Lane 8 (true-audit) s144: POST /api/sr-draft/apply validates its body.

`dashboard/routes_sr_draft.py` turns a client-supplied JSON body into up to
three League-client WRITE commands (apply_runes, apply_item_set,
set_summoners) queued through the vision relay's `/lcu-cmd`. `_handler.do_POST`
guarantees the body is a dict (LEDGER 1181) but nothing about its values, and
the :8888 listener is reachable from the tailnet. Findings pinned here, each
with the input that used to slip through:

  F1  a non-string champion / key (5, ["x"], {}) raised AttributeError on
      `.strip()` -> a 500 instead of a 400.
  F2  champion / key had no length cap and no control-character check, so a
      newline, ESC or NUL rode into the LCU page name, the item-set title and
      set_uid, and an arbitrarily long value was echoed back.
  F3  a STRING item_ids ("3094") was iterated per character and pushed as the
      four item ids "3", "0", "9", "4"; a dict pushed its keys.
  F4  item id elements were never checked: true -> "True", 3094.5 ->
      "3094.5", "-1", "abc", a dict, all pushed to the client; the response
      echoed falsy ids the item set had silently dropped (None -> "None"), so
      the echo disagreed with what was pushed; no cap on the count.
  F5  summoner_spells: [true, false] pushed Cleanse (1/0), [4.9, 12] pushed 4,
      ["4", "12"] was accepted, 0 / negative / huge / duplicate ids and
      3-element lists were accepted, and an unreadable value was skipped with
      no note at all.
  F6  a non-dict runes ("Conqueror", a list) was skipped silently, and a
      non-string rune name (a list) raised TypeError in the resolver -> 500.
  F7  label / kind were echoed back whatever their type or size.
  F8  every validation 400 now happens BEFORE any enqueue: a refused body
      never leaves a partial write on the League client.
  F9  the reply said "ok": true when an enqueue had failed.
  F10 the enqueue catch was a bare `except Exception`, so a programming error
      inside it was reported as an ordinary "enqueue failed" 200.
  F11 the unexpected-error 500 logged no traceback.
  F12 400 bodies carried no "ok": false and did not name the field.
"""
from __future__ import annotations

import json
import logging
import sys
import types
import urllib.error

import pytest

from dashboard import routes_sr_draft as rsd
from tests._module_view import bind_urlopen


class _H:
    def __init__(self):
        self.code = None
        self.body = b""

    def _send(self, code, body, ctype):
        self.code = code
        self.body = body


class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, *a):
        return b'{"id": 1}'


@pytest.fixture
def relay(monkeypatch):
    """Fake the vision relay: record every enqueued command, never touch :8889."""
    if "web_dashboard" in sys.modules:
        monkeypatch.setattr(sys.modules["web_dashboard"], "_VISION_TOKEN",
                            "test-token", raising=False)
    else:
        stub = types.ModuleType("web_dashboard")
        stub._VISION_TOKEN = "test-token"
        monkeypatch.setitem(sys.modules, "web_dashboard", stub)
    sent: list = []
    state = {"exc": None}

    def fake_urlopen(req, timeout=None):
        if state["exc"] is not None:
            raise state["exc"]
        sent.append(json.loads(req.data.decode("utf-8")))
        return _Resp()

    assert bind_urlopen(monkeypatch, rsd, fake_urlopen) >= 1
    return types.SimpleNamespace(sent=sent, state=state)


def _payload(**over):
    p = {
        "champion": "Tristana",
        "key": "primary",
        "label": "Primary",
        "kind": "engine",
        "runes": {"keystone": "Press the Attack", "primary": "Precision",
                  "secondary": "Domination"},
        "summoner_spells": [4, 7],
        "item_ids": ["6675", "3094", "3036"],
    }
    p.update(over)
    return p


def _post(payload):
    h = _H()
    rsd._serve_sr_draft_apply_post(h, payload)
    doc = json.loads(h.body.decode("utf-8")) if h.body else None
    return h.code, doc


def _assert_refused(relay, payload, field):
    code, doc = _post(payload)
    assert code == 400, (payload, code, doc)
    assert doc.get("ok") is False
    assert doc.get("field") == field
    assert relay.sent == [], "a refused body must enqueue NOTHING"


# -- happy path (characterization) -----------------------------------------

def test_happy_path_queues_all_three(relay):
    code, doc = _post(_payload())
    assert code == 200
    assert doc["ok"] is True
    assert doc["queued"] == ["apply_runes", "apply_item_set", "set_summoners"]
    assert [c["cmd"] for c in relay.sent] == doc["queued"]
    assert relay.sent[2] == {"cmd": "set_summoners", "d": 4, "f": 7}


# -- F1 / F2 / F12 champion + key ------------------------------------------

@pytest.mark.parametrize("field", ["champion", "key"])
@pytest.mark.parametrize("bad", [5, ["Tristana"], {"a": 1}, True, 1.5])
def test_non_string_champion_or_key_is_400(relay, field, bad):
    _assert_refused(relay, _payload(**{field: bad}), field)


@pytest.mark.parametrize("field", ["champion", "key"])
def test_missing_or_blank_champion_or_key_is_400_naming_it(relay, field):
    p = _payload()
    del p[field]
    _assert_refused(relay, p, field)
    _assert_refused(relay, _payload(**{field: "   "}), field)


@pytest.mark.parametrize("field", ["champion", "key"])
@pytest.mark.parametrize("bad", ["Tris\ntana", "Tri\x00", "\x1b[31mx",
                                 "a" + chr(0x200B) + "b", "A" * 65])
def test_control_char_or_overlong_champion_or_key_is_400(relay, field, bad):
    _assert_refused(relay, _payload(**{field: bad}), field)


def test_real_champion_names_with_punctuation_still_pass(relay):
    for name in ("Kai'Sa", "Nunu & Willump", "Dr. Mundo", "Bel'Veth"):
        relay.sent.clear()
        code, doc = _post(_payload(champion=name))
        assert code == 200, name
        assert doc["champion"] == name


# -- F3 / F4 item_ids -------------------------------------------------------

@pytest.mark.parametrize("bad", ["3094", {"3094": 1}, 3094])
def test_non_list_item_ids_is_400_not_iterated(relay, bad):
    _assert_refused(relay, _payload(item_ids=bad), "item_ids")


@pytest.mark.parametrize("bad", [True, {"a": 1}, 3094.5, "-1", -1, "abc", 0,
                                 "0", "  ", "", None, "9" * 8, chr(0xB3),
                                 [3094]])
def test_bad_item_id_element_is_400(relay, bad):
    _assert_refused(relay, _payload(item_ids=["6675", bad]), "item_ids")


def test_item_ids_count_is_capped(relay):
    _assert_refused(relay, _payload(item_ids=["3094"] * 65), "item_ids")


def test_item_ids_normalised_and_echo_matches_what_was_pushed(relay):
    code, doc = _post(_payload(item_ids=[6675, "3094", "03036"]))
    assert code == 200
    pushed = [i["id"] for i in relay.sent[1]["blocks"][0]["items"]]
    assert pushed == ["6675", "3094", "3036"]
    assert doc["item_ids"] == pushed


@pytest.mark.parametrize("absent", [None, []])
def test_absent_item_ids_skip_the_item_set(relay, absent):
    code, doc = _post(_payload(item_ids=absent))
    assert code == 200
    assert "apply_item_set" not in doc["queued"]
    assert doc["item_ids"] == []


# -- F5 summoner_spells -----------------------------------------------------

@pytest.mark.parametrize("bad", [[True, False], [True, 12], [4.9, 12], ["4", "12"], [4],
                                 [4, 12, 7], [0, 12], [-4, 12], [4, 10000],
                                 [4, 4], "4,12", {"d": 4, "f": 12}, 4,
                                 [None, 12]])
def test_bad_summoner_spells_are_400(relay, bad):
    _assert_refused(relay, _payload(summoner_spells=bad), "summoner_spells")


@pytest.mark.parametrize("absent", [None, []])
def test_absent_summoner_spells_skip_set_summoners(relay, absent):
    code, doc = _post(_payload(summoner_spells=absent))
    assert code == 200
    assert "set_summoners" not in doc["queued"]


def test_bad_summoners_refused_even_when_push_summoners_false(relay):
    # A malformed field is a malformed body whichever flags are set; the
    # same rule the push_* flags already follow (RM-414).
    _assert_refused(relay, _payload(summoner_spells=[True, 1],
                                    push_summoners=False), "summoner_spells")


# -- F6 runes ---------------------------------------------------------------

@pytest.mark.parametrize("bad", ["Conqueror", ["Precision"], 5, True])
def test_non_dict_runes_is_400(relay, bad):
    _assert_refused(relay, _payload(runes=bad), "runes")


@pytest.mark.parametrize("name", ["keystone", "primary", "secondary",
                                  "primary_tree", "secondary_tree"])
@pytest.mark.parametrize("bad", [["Conqueror"], {"a": 1}, 5, "x" * 65,
                                 "Con\nqueror"])
def test_non_string_rune_name_is_400_not_500(relay, name, bad):
    runes = {"keystone": "Conqueror", "primary": "Precision",
             "secondary": "Domination"}
    runes[name] = bad
    _assert_refused(relay, _payload(runes=runes), "runes")


def test_unrecognised_keystone_still_a_200_with_a_note(relay):
    code, doc = _post(_payload(runes={"keystone": "Bogus",
                                      "primary": "Precision",
                                      "secondary": "Domination"}))
    assert code == 200
    assert "apply_runes" not in doc["queued"]
    assert any(n.startswith("runes:") for n in doc["notes"])


# -- F7 label / kind --------------------------------------------------------

@pytest.mark.parametrize("field", ["label", "kind"])
@pytest.mark.parametrize("bad", [5, ["x"], {"a": 1}, True, "x" * 129,
                                 "a\nb"])
def test_bad_label_or_kind_is_400(relay, field, bad):
    _assert_refused(relay, _payload(**{field: bad}), field)


def test_label_defaults_to_key_and_kind_to_empty(relay):
    p = _payload()
    del p["label"]
    del p["kind"]
    code, doc = _post(p)
    assert code == 200
    assert doc["label"] == "primary"
    assert doc["kind"] == ""


# -- F9 / F10 enqueue failures ----------------------------------------------

@pytest.mark.parametrize("exc", [urllib.error.URLError("refused"),
                                 TimeoutError("slow"), OSError("reset")])
def test_failed_enqueue_reports_ok_false(relay, exc):
    relay.state["exc"] = exc
    code, doc = _post(_payload())
    assert code == 200
    assert doc["ok"] is False
    assert doc["queued"] == []
    assert len(doc["notes"]) == 3
    assert all("enqueue failed" in n for n in doc["notes"])


def test_programming_error_in_enqueue_is_a_500_not_a_note(relay, caplog):
    relay.state["exc"] = RuntimeError("internal-detail-xyz")
    with caplog.at_level(logging.WARNING, logger="rc.web_dashboard"):
        code, doc = _post(_payload())
    assert code == 500
    assert "internal-detail-xyz" not in json.dumps(doc)
    assert any(r.exc_info for r in caplog.records)


# -- F11 traceback on the unexpected 500 ------------------------------------

def test_unexpected_500_logs_a_traceback(relay, caplog, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret-cause")
    monkeypatch.setattr(rsd, "_build_rune_cmd", boom)
    with caplog.at_level(logging.WARNING, logger="rc.web_dashboard"):
        code, doc = _post(_payload())
    assert code == 500
    assert doc == {"ok": False, "error": "internal error - see logs"}
    assert any(r.exc_info for r in caplog.records)
    assert relay.sent == []
