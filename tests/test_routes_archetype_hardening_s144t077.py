"""s144 true-audit cycle 77 - dashboard/routes_archetype.py hardening.

The routes take a JSON body from any peer the :8888 handler admits, and the
save arm persists it into ``data/cs_archetype_picks.json`` - the file every
``core.archetype_picks.get_archetype_for`` consumer reads, including the
RM-164 build-order precompute. Findings pinned here, each red at the
pre-fix HEAD:

* F1 - ``champion`` was ``str(payload.get("champion") or "")``: a number,
  bool, list or dict was stringified and PERSISTED as a pick key ("5",
  "True", "['Aatrox']"), and a near-1 MiB string or one carrying control
  characters was persisted too. Same coercion on the nudge-dismiss body and
  on the GET query.
* F2 - nothing bounded the number of distinct pick keys, so a peer looping
  distinct champions grew the file without limit (each save rewrites it).
* F3 - ``source: "default"`` was accepted, persisting an explicit override
  that every consumer reads as "not operator intent"
  (``core/archetype_mismatch.py`` skips source=default) while it still
  overrides the DDragon default; GET advertised "default" as a source.
* F4 - non-string ``primary`` / ``secondary`` / ``source`` were coerced:
  ``secondary: false`` / ``0`` / ``[]`` silently read as absent and
  ``source: 0`` / ``false`` silently became "user_cs".
* F5 - unknown body keys were dropped silently, so a typo'd
  ``"secondery"`` saved a pick the caller did not ask for.
* F6 - every save / clear failure, expected or a programming bug, was
  logged as one WARNING line with no traceback.
* F7 - the module docstring said the champ-select picker UI calls these
  POSTs; LEDGER 824 removed both callers.
"""
from __future__ import annotations

import json
import logging

import pytest

from core import archetype_mismatch, archetype_picks
from dashboard import routes_archetype


class _H:
    def __init__(self, path: str = "/api/cs-archetype-pick"):
        self.path = path
        self.status = None
        self.body = b""

    def _send(self, status, body, ctype):
        self.status = status
        self.body = body

    def json(self):
        return json.loads(self.body.decode("utf-8"))


@pytest.fixture
def picks(tmp_path, monkeypatch):
    monkeypatch.setattr(archetype_picks, "_PICKS_PATH",
                        tmp_path / "cs_archetype_picks.json")
    monkeypatch.setattr(archetype_picks, "_DATA_DIR", tmp_path)
    archetype_picks._invalidate_picks_cache()
    yield tmp_path / "cs_archetype_picks.json"
    archetype_picks._invalidate_picks_cache()


@pytest.fixture
def nudge():
    archetype_mismatch.reset_nudge_state()
    yield archetype_mismatch
    archetype_mismatch.reset_nudge_state()


def _post(body):
    h = _H()
    routes_archetype._serve_archetype_post(h, body)
    return h


def _saved_keys(path):
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


# ------------------------------------------------------------- F1 champion

_BAD_CHAMPIONS = [
    pytest.param(5, id="int"),
    pytest.param(1.5, id="float"),
    pytest.param(True, id="bool"),
    pytest.param(["Aatrox"], id="list"),
    pytest.param({"a": 1}, id="dict"),
    pytest.param("A" * 65, id="65-chars"),
    pytest.param("A" * 200000, id="200k-chars"),
    pytest.param("Aat\nrox", id="newline"),
    pytest.param("Aat\x00rox", id="nul"),
    pytest.param("Aat\x1brox", id="escape"),
    pytest.param("Aat\u202erox", id="bidi-override"),
]


@pytest.mark.parametrize("champion", _BAD_CHAMPIONS)
def test_f1_save_rejects_bad_champion_and_writes_nothing(picks, champion):
    h = _post({"champion": champion, "primary": "tank"})
    assert h.status == 400
    assert h.json() == {"error": "invalid champion"}
    assert not picks.exists()


@pytest.mark.parametrize("champion", _BAD_CHAMPIONS)
def test_f1_clear_rejects_bad_champion(picks, champion):
    h = _post({"champion": champion, "clear": True})
    assert h.status == 400
    assert h.json() == {"error": "invalid champion"}


@pytest.mark.parametrize("champion", _BAD_CHAMPIONS)
def test_f1_dismiss_rejects_bad_champion(nudge, monkeypatch, champion):
    calls = []
    monkeypatch.setattr(routes_archetype, "dismiss_nudge",
                        lambda c: calls.append(c) or True)
    h = _H("/api/archetype-nudge/dismiss")
    routes_archetype._serve_archetype_nudge_dismiss(h, {"champion": champion})
    assert h.status == 400
    assert h.json() == {"error": "invalid champion"}
    assert calls == []


@pytest.mark.parametrize("query", [
    "A" * 65, "Aat%0Arox", "Aat%00rox", "Aat%E2%80%AErox",
])
def test_f1_get_rejects_bad_champion_query(picks, query):
    h = _H("/api/cs-archetype-pick?champion=" + query)
    routes_archetype._serve_archetype_get(h)
    assert h.status == 400
    assert h.json() == {"error": "invalid champion"}


@pytest.mark.parametrize("champion", [
    "Aatrox", "Nunu & Willump", "Kai'Sa", "Dr. Mundo", "A" * 64,
])
def test_f1_real_names_and_the_64_char_boundary_still_save(picks, champion):
    h = _post({"champion": champion, "primary": "tank"})
    assert h.status == 200, h.body
    assert _saved_keys(picks) == {champion}


def test_f1_surrounding_whitespace_is_still_stripped(picks):
    h = _post({"champion": "  Aatrox  ", "primary": "tank"})
    assert h.status == 200
    assert _saved_keys(picks) == {"Aatrox"}


@pytest.mark.parametrize("body", [
    {"primary": "tank"}, {"champion": None, "primary": "tank"},
    {"champion": "", "primary": "tank"}, {"champion": "   ", "primary": "tank"},
])
def test_f1_missing_champion_keeps_the_required_message(picks, body):
    h = _post(body)
    assert h.status == 400
    assert h.json() == {"error": "champion required"}


def test_f1_rejected_champion_is_not_echoed(picks):
    marker = "LEAKMARKER" * 10
    h = _post({"champion": marker, "primary": "tank"})
    assert h.status == 400
    assert b"LEAKMARKER" not in h.body


def test_f1_dismiss_happy_path_unchanged(nudge):
    nudge._NUDGE_STATE["Aatrox"] = {"phase": "fired", "fired": True}
    h = _H("/api/archetype-nudge/dismiss")
    routes_archetype._serve_archetype_nudge_dismiss(h, {"champion": " Aatrox "})
    assert h.status == 200
    assert h.json() == {"ok": True, "dismissed": True, "champion": "Aatrox"}


# --------------------------------------------------------------- F2 cap

def test_f2_new_champion_past_the_cap_is_refused(picks, monkeypatch):
    monkeypatch.setattr(routes_archetype, "_MAX_PICKS", 3)
    for name in ("Aatrox", "Ahri", "Akali"):
        assert _post({"champion": name, "primary": "tank"}).status == 200
    before = picks.read_bytes()
    h = _post({"champion": "Alistar", "primary": "tank"})
    assert h.status == 409
    assert h.json() == {"error": "too many saved picks - clear one first"}
    assert picks.read_bytes() == before


def test_f2_existing_champion_at_the_cap_can_still_be_resaved(picks, monkeypatch):
    monkeypatch.setattr(routes_archetype, "_MAX_PICKS", 2)
    for name in ("Aatrox", "Ahri"):
        assert _post({"champion": name, "primary": "tank"}).status == 200
    h = _post({"champion": "Ahri", "primary": "mage"})
    assert h.status == 200
    assert archetype_picks.get_archetype_for("Ahri")["primary"] == "mage"


def test_f2_clear_at_the_cap_frees_a_slot(picks, monkeypatch):
    monkeypatch.setattr(routes_archetype, "_MAX_PICKS", 1)
    assert _post({"champion": "Aatrox", "primary": "tank"}).status == 200
    assert _post({"champion": "Ahri", "primary": "tank"}).status == 409
    assert _post({"champion": "Aatrox", "clear": True}).status == 200
    assert _post({"champion": "Ahri", "primary": "tank"}).status == 200
    assert _saved_keys(picks) == {"Ahri"}


def test_f2_default_cap_covers_the_roster_with_room():
    assert 200 <= routes_archetype._MAX_PICKS <= 4096


# ---------------------------------------------------------- F3 source

def test_f3_source_default_is_refused_and_writes_nothing(picks):
    h = _post({"champion": "Aatrox", "primary": "tank", "source": "default"})
    assert h.status == 400
    assert h.json() == {"error": "invalid pick - see logs"}
    assert not picks.exists()


@pytest.mark.parametrize("source", ["user_cs", "user_ingame", "nudge"])
def test_f3_operator_sources_still_save(picks, source):
    h = _post({"champion": "Aatrox", "primary": "tank", "source": source})
    assert h.status == 200
    assert h.json()["pick"]["source"] == source


def test_f3_get_advertises_only_the_saveable_sources(picks):
    h = _H("/api/cs-archetype-pick")
    routes_archetype._serve_archetype_get(h)
    assert h.status == 200
    assert h.json()["sources"] == ["nudge", "user_cs", "user_ingame"]


# ----------------------------------------------------------- F4 types

@pytest.mark.parametrize("field,value", [
    ("primary", 5), ("primary", ["tank"]), ("primary", {"x": 1}),
    ("primary", True), ("primary", 0), ("primary", False),
    ("secondary", False), ("secondary", 0), ("secondary", []),
    ("secondary", ["tank"]), ("secondary", 1),
    ("source", 0), ("source", False), ("source", ["user_cs"]),
    ("source", 1),
])
def test_f4_non_string_field_is_a_400_and_writes_nothing(picks, field, value):
    body = {"champion": "Aatrox", "primary": "tank", field: value}
    h = _post(body)
    assert h.status == 400
    assert h.json() == {"error": "invalid pick - see logs"}
    assert not picks.exists()


@pytest.mark.parametrize("field", ["secondary", "source"])
@pytest.mark.parametrize("value", [None, ""])
def test_f4_null_or_empty_optional_field_still_reads_as_absent(picks, field, value):
    h = _post({"champion": "Aatrox", "primary": "tank", field: value})
    assert h.status == 200, h.body
    pick = h.json()["pick"]
    if field == "source":
        assert pick["source"] == "user_cs"
    else:
        assert pick["secondary"] in archetype_picks.ARCHETYPE_SET


@pytest.mark.parametrize("value", [None, "", "   "])
def test_f4_missing_primary_keeps_the_required_message(picks, value):
    h = _post({"champion": "Aatrox", "primary": value})
    assert h.status == 400
    assert h.json() == {"error": "primary required"}


def test_f4_rejected_field_value_is_logged_by_type_not_value(picks, caplog):
    caplog.set_level(logging.WARNING, logger="rc.web_dashboard")
    _post({"champion": "Aatrox", "primary": "tank",
           "secondary": ["SECRETVALUE"]})
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "secondary" in text
    assert "SECRETVALUE" not in text


# ------------------------------------------------------- F5 unknown keys

def test_f5_unknown_key_is_a_400_and_writes_nothing(picks):
    h = _post({"champion": "Aatrox", "primary": "tank", "secondery": "mage"})
    assert h.status == 400
    assert h.json() == {"error": "unknown field - see logs"}
    assert not picks.exists()


def test_f5_unknown_key_on_clear_is_a_400_and_clears_nothing(picks):
    assert _post({"champion": "Aatrox", "primary": "tank"}).status == 200
    h = _post({"champion": "Aatrox", "clear": True, "really": True})
    assert h.status == 400
    assert _saved_keys(picks) == {"Aatrox"}


def test_f5_unknown_key_on_dismiss_is_a_400(nudge):
    nudge._NUDGE_STATE["Aatrox"] = {"phase": "fired", "fired": True}
    h = _H("/api/archetype-nudge/dismiss")
    routes_archetype._serve_archetype_nudge_dismiss(
        h, {"champion": "Aatrox", "extra": 1})
    assert h.status == 400
    assert h.json() == {"error": "unknown field - see logs"}
    assert nudge._NUDGE_STATE["Aatrox"]["phase"] == "fired"


def test_f5_unknown_key_names_are_clipped_and_counted_in_the_log(picks, caplog):
    caplog.set_level(logging.WARNING, logger="rc.web_dashboard")
    body = {"champion": "Aatrox", "primary": "tank"}
    body.update({("K" * 500) + str(i): 1 for i in range(50)})
    h = _post(body)
    assert h.status == 400
    records = [r for r in caplog.records if "unknown" in r.getMessage()]
    assert len(records) == 1
    msg = records[0].getMessage()
    assert len(msg) < 1500
    assert "50" in msg
    assert "K" * 100 not in msg


def test_f5_every_documented_key_is_accepted(picks):
    h = _post({"champion": "Aatrox", "primary": "tank", "secondary": "bruiser",
               "source": "user_cs", "clear": False})
    assert h.status == 200, h.body


# ------------------------------------------------------- F6 exceptions

def _boom(exc):
    def _raise(*a, **k):
        raise exc
    return _raise


@pytest.mark.parametrize("arm,body,target", [
    ("save", {"champion": "Aatrox", "primary": "tank"}, "save_archetype_pick"),
    ("clear", {"champion": "Aatrox", "clear": True}, "clear_archetype_pick"),
])
def test_f6_unexpected_failure_is_a_500_with_a_traceback(
        picks, monkeypatch, caplog, arm, body, target):
    caplog.set_level(logging.WARNING, logger="rc.web_dashboard")
    monkeypatch.setattr(routes_archetype, target,
                        _boom(TypeError("RAWTEXT /private/path")))
    h = _post(body)
    assert h.status == 500
    assert b"RAWTEXT" not in h.body
    assert h.json() == {"error": f"{arm} failed - see logs"}
    rows = [r for r in caplog.records if r.exc_info]
    assert rows, "a programming error must be logged with its traceback"


@pytest.mark.parametrize("arm,body,target", [
    ("save", {"champion": "Aatrox", "primary": "tank"}, "save_archetype_pick"),
    ("clear", {"champion": "Aatrox", "clear": True}, "clear_archetype_pick"),
])
@pytest.mark.parametrize("exc", [
    archetype_picks.PicksReadError("picks file unreadable"),
    PermissionError(13, "denied"),
])
def test_f6_expected_store_failure_stays_one_warning_without_traceback(
        picks, monkeypatch, caplog, arm, body, target, exc):
    caplog.set_level(logging.WARNING, logger="rc.web_dashboard")
    monkeypatch.setattr(routes_archetype, target, _boom(exc))
    h = _post(body)
    assert h.status == 500
    assert h.json() == {"error": f"{arm} failed - see logs"}
    rows = [r for r in caplog.records if r.name == "rc.web_dashboard"]
    assert len(rows) == 1
    assert rows[0].exc_info is None


# ------------------------------------------------------- F7 docstring

def test_f7_docstring_no_longer_claims_a_ui_caller():
    doc = " ".join((routes_archetype.__doc__ or "").split())
    assert "picker UI calls POST+clear" not in doc
    assert "calls these to set the operator's preferred archetype" not in doc
    assert "LEDGER 824" in doc
    assert "build_order_precompute" in doc
