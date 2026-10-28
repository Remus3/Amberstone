"""Guard (RM-1002): a malformed ``ranked`` payload inside a JSON object no longer raises.

RM-1001 made ``_post_json`` return ``None`` for a body that is not a JSON
object. One level down, each of the seven rank clients in
``core/daemon_slayer_client.py`` still did
``[<X>RankedItem.from_dict(r) for r in data.get("ranked") or []]``, so:

- a truthy non-list ``ranked`` (a string iterates per character, a number
  is not iterable) raised in the comprehension or in ``from_dict``;
- one row that is not an object raised AttributeError at ``d.get``;
- one row whose numeric field does not coerce (``"delta_dps": "abc"``,
  ``"gold": null``) raised ValueError / TypeError and sank every good row.

Contract chosen (recorded in the RM-1002 cycle report):

- ``ranked`` present but not a list is a malformed body, so the client
  returns ``None`` exactly like a failed POST (the RM-1001 rule);
- a missing / null / empty ``ranked`` still returns ``[]``;
- a single bad row is DROPPED and the good rows are kept. Dropping, not a
  0.0 default, because a zero-delta row would pose as a real candidate and
  an all-garbage ranking would trip the dispatcher's ``_kitless_all_zero``
  fallback; an empty list does not (that helper's non-empty guard).

``urlopen`` is stubbed, so nothing touches the live :8860 server. ASCII only
(CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import daemon_slayer_client as ds

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CLIENT = _REPO_ROOT / "core" / "daemon_slayer_client.py"
_DS_DOC = _REPO_ROOT / "docs" / "DAEMON_SLAYER.md"

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


def _good_row(field: str, item_id: str, delta: float) -> dict:
    return {"item_id": item_id, "item_name": "Item " + item_id, field: delta, "gold": 3000}


@pytest.mark.parametrize("name", sorted(_CLIENTS))
def test_well_formed_rows_still_parse(monkeypatch, name):
    # Positive control: the stub transport and the row shape are real, so a
    # dropped row below is the guard, not a broken fixture.
    cls, field = _CLIENTS[name]
    seen = _serve(monkeypatch, {"ranked": [_good_row(field, "3031", 12.5)]})
    out = _call(name)
    assert seen, f"{name} never reached the transport"
    assert isinstance(out, list) and len(out) == 1, out
    assert isinstance(out[0], cls)
    assert out[0].item_id == "3031"
    assert getattr(out[0], field) == 12.5


@pytest.mark.parametrize("name", sorted(_CLIENTS))
@pytest.mark.parametrize("ranked", ("x", 7, {"item_id": "3031"}, True))
def test_non_list_ranked_returns_none(monkeypatch, name, ranked):
    seen = _serve(monkeypatch, {"ranked": ranked})
    assert _call(name) is None
    assert seen, f"{name} never reached the transport"


@pytest.mark.parametrize("name", sorted(_CLIENTS))
@pytest.mark.parametrize("body", ({}, {"ranked": None}, {"ranked": []}))
def test_absent_or_empty_ranked_is_still_an_empty_list(monkeypatch, name, body):
    _serve(monkeypatch, body)
    assert _call(name) == []


@pytest.mark.parametrize("name", sorted(_CLIENTS))
@pytest.mark.parametrize("bad", (1, "3031", None, ["3031"]))
def test_non_object_row_is_dropped_and_good_rows_kept(monkeypatch, name, bad):
    _cls, field = _CLIENTS[name]
    body = {"ranked": [_good_row(field, "3031", 9.0), bad, _good_row(field, "3072", 4.0)]}
    _serve(monkeypatch, body)
    out = _call(name)
    assert [r.item_id for r in out] == ["3031", "3072"], out


@pytest.mark.parametrize("name", sorted(_CLIENTS))
@pytest.mark.parametrize("patch", (
    lambda field: {field: "abc"},
    lambda field: {field: None},
    lambda field: {"gold": "lots"},
    lambda field: {"gold": None},
    lambda field: {"gold": 1e400},
))
def test_uncoercible_row_is_dropped_and_good_rows_kept(monkeypatch, name, patch):
    _cls, field = _CLIENTS[name]
    bad = _good_row(field, "6672", 1.0)
    bad.update(patch(field))
    body = {"ranked": [_good_row(field, "3031", 9.0), bad, _good_row(field, "3072", 4.0)]}
    _serve(monkeypatch, body)
    out = _call(name)
    assert [r.item_id for r in out] == ["3031", "3072"], out


@pytest.mark.parametrize("archetype", ("carry", "tank", "bruiser", "mage", "assassin", "enchanter", "onhit"))
def test_dispatcher_returns_none_not_raises_on_a_non_list_ranked(monkeypatch, archetype):
    seen = _serve(monkeypatch, {"ranked": "x"})
    out = ds.rank_for_primary_archetype(
        "Ahri", archetype, level=11, item_ids=["3020"], mode="SR",
    )
    assert out is None
    assert seen, "the branch never reached the transport"


def test_every_rank_client_parses_through_one_helper():
    # One implementation: a new rank client that hand-rolls the comprehension
    # again would reopen the defect.
    src = _CLIENT.read_text(encoding="utf-8")
    assert "for r in ranked]" not in src
    for name in _CLIENTS:
        assert name in src


def test_dispatcher_docstring_and_ds_doc_name_the_row_contract():
    doc = " ".join((ds.rank_for_primary_archetype.__doc__ or "").split())
    assert "``ranked`` that is not a list is ``None``" in doc, doc[:300]
    assert "malformed row is dropped" in doc
    lines = [
        ln for ln in _DS_DOC.read_text(encoding="utf-8").splitlines()
        if ln.startswith("- **Dispatch**:")
    ]
    assert len(lines) == 1, lines
    assert "a `ranked` that is not a list" in lines[0], lines[0]
    assert "malformed row is dropped" in lines[0]


def test_guard_files_are_ascii():
    for path in (_CLIENT, _DS_DOC, Path(__file__)):
        path.read_bytes().decode("ascii")
