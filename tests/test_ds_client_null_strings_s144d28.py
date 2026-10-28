"""Guard (RM-1004): a rank row's string fields never parse a null as "None".

Each of the seven ``<X>RankedItem.from_dict`` methods in
``core/daemon_slayer_client.py`` read its four string fields with
``str(d.get(key, ""))``. The default covers only a MISSING key, so a JSON
null became the four-character string "None":

- ``item_id`` null parsed as "None", a row that posed as a real item id
  (callers key on ``item_id`` for build lookups and de-duplication);
- ``item_name`` / ``dead_unique_key`` / ``unique_passive_key`` null became
  "None", and a non-empty ``unique_passive_key`` reads as a locked family.

Contract chosen (recorded in the RM-1004 cycle report):

- ``item_id`` must be a non-empty string (an int is accepted and stringified,
  a bool is not); ``from_dict`` parses anything else as ``""`` and
  ``_ranked_rows`` DROPS that row (the RM-1002 rule), keeping the good rows;
- the three descriptive strings take a string as is and anything else as
  ``""``, so a null never costs the row.

The server emits ``item_id`` as a string (``agents/daemon_slayer/rank.py``
and siblings, ``"item_id": self.item_id``), so a well-formed response parses
exactly as before. ``urlopen`` is stubbed, so nothing touches the live :8860
server. ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json

import pytest

from core import daemon_slayer_client as ds

# client name -> (row class, its primary delta field)
_CLIENTS = {
    "rank_for": (ds.RankedItem, "delta_dps"),
    "rank_tank_for": (ds.TankRankedItem, "delta_ehp"),
    "rank_bruiser_for": (ds.BruiserRankedItem, "delta_dps"),
    "rank_mage_for": (ds.MageRankedItem, "delta_ability_dps"),
    "rank_assassin_for": (ds.AssassinRankedItem, "delta_burst"),
    "rank_enchanter_for": (ds.EnchanterRankedItem, "delta_hps"),
    "rank_onhit_for": (ds.OnhitRankedItem, "delta_dps"),
}
_TEXT_FIELDS = ("item_name", "dead_unique_key", "unique_passive_key")


class _FakeResp:
    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._raw


def _serve(monkeypatch, body: object) -> list:
    raw = json.dumps(body).encode("utf-8")
    seen: list = []

    def _urlopen(req, timeout=None):
        seen.append(req.full_url)
        return _FakeResp(raw)

    monkeypatch.setattr(ds, "urlopen", _urlopen)
    return seen


def _call(name: str):
    return getattr(ds, name)("Ahri", level=11, item_ids=["3020"])


def _row(field: str, item_id: object, delta: float, **extra: object) -> dict:
    row = {"item_id": item_id, "item_name": "Item", field: delta, "gold": 3000}
    row.update(extra)
    return row


@pytest.mark.parametrize("name", sorted(_CLIENTS))
def test_string_fields_round_trip(monkeypatch, name):
    # Positive control: the server's real shape still parses unchanged.
    _cls, field = _CLIENTS[name]
    row = _row(field, "3031", 5.0, dead_unique_key="lifeline", unique_passive_key="mythic_x")
    seen = _serve(monkeypatch, {"ranked": [row]})
    out = _call(name)
    assert seen, f"{name} never reached the transport"
    assert len(out) == 1, out
    assert (out[0].item_id, out[0].item_name) == ("3031", "Item")
    assert (out[0].dead_unique_key, out[0].unique_passive_key) == ("lifeline", "mythic_x")


@pytest.mark.parametrize("name", sorted(_CLIENTS))
@pytest.mark.parametrize("bad_id", (None, "", True, 1.5, ["3031"], {"id": "3031"}))
def test_bad_item_id_row_is_dropped_and_good_rows_kept(monkeypatch, name, bad_id):
    _cls, field = _CLIENTS[name]
    body = {"ranked": [_row(field, "3031", 9.0), _row(field, bad_id, 50.0), _row(field, "3072", 4.0)]}
    _serve(monkeypatch, body)
    out = _call(name)
    assert [r.item_id for r in out] == ["3031", "3072"], out


@pytest.mark.parametrize("name", sorted(_CLIENTS))
def test_missing_item_id_row_is_dropped(monkeypatch, name):
    _cls, field = _CLIENTS[name]
    nameless = {"item_name": "Ghost", field: 50.0, "gold": 3000}
    _serve(monkeypatch, {"ranked": [nameless, _row(field, "3072", 4.0)]})
    assert [r.item_id for r in _call(name)] == ["3072"]


@pytest.mark.parametrize("name", sorted(_CLIENTS))
def test_int_item_id_is_stringified(monkeypatch, name):
    _cls, field = _CLIENTS[name]
    _serve(monkeypatch, {"ranked": [_row(field, 3031, 5.0)]})
    assert [r.item_id for r in _call(name)] == ["3031"]


@pytest.mark.parametrize("name", sorted(_CLIENTS))
@pytest.mark.parametrize("text_field", _TEXT_FIELDS)
@pytest.mark.parametrize("bad", (None, 7, ["x"], {"k": "v"}))
def test_bad_text_field_is_blank_and_row_kept(monkeypatch, name, text_field, bad):
    _cls, field = _CLIENTS[name]
    _serve(monkeypatch, {"ranked": [_row(field, "3031", 5.0, **{text_field: bad})]})
    out = _call(name)
    assert len(out) == 1, out
    assert getattr(out[0], text_field) == ""


@pytest.mark.parametrize("cls", sorted({c for c, _f in _CLIENTS.values()}, key=lambda c: c.__name__))
def test_from_dict_never_yields_the_string_none(cls):
    for text_field in _TEXT_FIELDS:
        item = cls.from_dict({"item_id": "3031", text_field: None})
        assert getattr(item, text_field) == ""
    # from_dict stays tolerant (agents/daemon_slayer/tests/
    # test_unique_passive_key_phase4d.py parses {} directly); the drop of an
    # id-less row is _ranked_rows' job.
    for bad_id in (None, True, 1.5):
        assert cls.from_dict({"item_id": bad_id}).item_id == ""
    assert cls.from_dict({}).item_id == ""


def test_dispatcher_docstring_and_ds_doc_name_the_item_id_rule():
    from pathlib import Path

    doc = " ".join((ds.rank_for_primary_archetype.__doc__ or "").split())
    assert "``item_id`` is missing, null or empty (RM-1004)" in doc, doc[:400]
    ds_doc = Path(__file__).resolve().parents[1] / "docs" / "DAEMON_SLAYER.md"
    lines = [
        ln for ln in ds_doc.read_text(encoding="utf-8").splitlines()
        if ln.startswith("- **Dispatch**:")
    ]
    assert len(lines) == 1, lines
    assert "`item_id` is missing, null or empty" in lines[0], lines[0]
    assert 'never as `"None"`' in lines[0], lines[0]
