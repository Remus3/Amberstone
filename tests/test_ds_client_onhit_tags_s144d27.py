"""Guard (RM-1003): ``OnhitRankedItem.from_dict`` coerces ``tags`` to a tuple of strings.

The server emits ``tags`` as ``list(self.tags)`` (``agents/daemon_slayer/onhit_dps.py``
``OnhitDpsRankedItem.to_dict``), a list of DDragon item tag strings. The client
did ``tuple(d.get("tags", ()))``, so:

- a string ``tags`` became a tuple of its characters (``"Damage"`` ->
  ``("D", "a", ...)``), and a membership test such as ``"Damage" in tags``
  went False;
- a null or numeric ``tags`` raised TypeError, and ``_ranked_rows`` (RM-1002)
  then DROPPED an otherwise good row over a descriptive field;
- a dict ``tags`` became its keys, and non-string elements leaked through.

Contract chosen (recorded in the RM-1003 cycle report): ``tags`` is a
descriptive field, not a scored one, so a malformed value never costs the row.
A string becomes a one-tuple, a list or tuple keeps only its string elements,
and anything else (null, number, bool, dict) becomes ``()``.

``urlopen`` is stubbed, so nothing touches the live :8860 server. ASCII only
(CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import daemon_slayer_client as ds

_CLIENT = Path(__file__).resolve().parents[1] / "core" / "daemon_slayer_client.py"


class _FakeResp:
    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._raw


def _row(item_id: str, **extra: object) -> dict:
    row = {"item_id": item_id, "item_name": "Item " + item_id, "delta_dps": 7.5, "gold": 3000}
    row.update(extra)
    return row


@pytest.mark.parametrize("tags, expected", (
    (["Damage", "OnHit"], ("Damage", "OnHit")),
    (("AttackSpeed",), ("AttackSpeed",)),
    ([], ()),
))
def test_well_formed_tags_unchanged(tags, expected):
    # Positive control: the server's real shape still parses as before.
    assert ds.OnhitRankedItem.from_dict(_row("3153", tags=tags)).tags == expected


def test_missing_tags_is_empty():
    assert ds.OnhitRankedItem.from_dict(_row("3153")).tags == ()


def test_string_tags_is_a_one_tuple_not_characters():
    item = ds.OnhitRankedItem.from_dict(_row("3153", tags="Damage"))
    assert item.tags == ("Damage",)
    assert "Damage" in item.tags


@pytest.mark.parametrize("tags", (None, 7, 2.5, True, {"Damage": 1}))
def test_non_sequence_tags_is_empty(tags):
    assert ds.OnhitRankedItem.from_dict(_row("3153", tags=tags)).tags == ()


def test_non_string_elements_are_dropped():
    item = ds.OnhitRankedItem.from_dict(_row("3153", tags=["Damage", 3, None, ["x"], "OnHit"]))
    assert item.tags == ("Damage", "OnHit")


@pytest.mark.parametrize("tags", (None, 7, "Damage", {"Damage": 1}))
def test_malformed_tags_never_costs_the_row(monkeypatch, tags):
    # End to end through rank_onhit_for and _ranked_rows: the middle row has
    # a malformed descriptive field only, so all three rows survive.
    body = {"ranked": [_row("3031", tags=["Damage"]), _row("3153", tags=tags), _row("3072")]}
    raw = json.dumps(body).encode("utf-8")
    seen: list = []

    def _urlopen(req, timeout=None):
        seen.append(req.full_url)
        return _FakeResp(raw)

    monkeypatch.setattr(ds, "urlopen", _urlopen)
    out = ds.rank_onhit_for("Varus", level=11, item_ids=["3006"])
    assert seen, "rank_onhit_for never reached the transport"
    assert [r.item_id for r in out] == ["3031", "3153", "3072"], out
    assert all(isinstance(t, str) for r in out for t in r.tags)


def test_docstring_names_the_tags_contract():
    src = _CLIENT.read_text(encoding="utf-8")
    start = src.index("class OnhitRankedItem:")
    block = src[start:src.index("def from_dict", start)]
    assert "RM-1003" in block, "OnhitRankedItem docstring must name the tags contract"
