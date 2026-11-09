"""S144-D-88 - pin the fail-soft loader contract of ``survivability_credit``.

``_parse_table`` promises: "a missing / unreadable / malformed table yields an
empty map so the seam degrades to a byte-identical no-op rather than raising".
The RF1 / RF2 / RF3 / RF6 tests only read the REAL shipped tables, so nothing
loaded a missing or malformed table, the per-item id filtering, the
``champ_rec["name"]`` fallback, the per-lane file and cache independence, or
the cache itself before this file.

Each test points all three lane paths at tmp files and resets the cache before
and after, so the real tables are re-read by every later test. Synthetic
champion keys and item ids only.
"""
from __future__ import annotations

import json

import pytest

from agents.daemon_slayer import survivability_credit as sc

_EMPTY = frozenset()

# lane -> (module path attribute, public getter)
_LANES = {
    "hybrid": ("_TABLE_PATH", sc.survivability_item_ids),
    "enchanter": ("_ENCHANTER_TABLE_PATH", sc.survivability_item_ids_enchanter),
    "tank": ("_TANK_TABLE_PATH", sc.survivability_item_ids_tank),
}


@pytest.fixture
def tables(tmp_path, monkeypatch):
    """Point every lane at its own tmp file; return lane -> writer."""
    paths = {}
    for lane, (attr, _getter) in _LANES.items():
        path = tmp_path / f"{lane}.json"
        monkeypatch.setattr(sc, attr, path)
        paths[lane] = path
    sc.reset_cache()

    def _write(lane: str, payload) -> None:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        paths[lane].write_text(text, encoding="utf-8")
        sc.reset_cache()

    _write.paths = paths  # type: ignore[attr-defined]
    yield _write
    sc.reset_cache()


@pytest.mark.parametrize("lane", sorted(_LANES))
def test_missing_table_is_empty_not_an_error(tables, lane) -> None:
    assert _LANES[lane][1]("ChampA") == _EMPTY


@pytest.mark.parametrize("lane", sorted(_LANES))
@pytest.mark.parametrize(
    "payload",
    [
        "{not json",
        "",
        "[1, 2, 3]",
        "null",
        {"champions": None},
        {"other": {"ChampA": {"items": [{"id": "9001"}]}}},
    ],
)
def test_malformed_table_is_empty_not_an_error(tables, lane, payload) -> None:
    tables(lane, payload)
    assert _LANES[lane][1]("ChampA") == _EMPTY
    # The parser itself yields the empty map, not a partial one.
    assert sc._parse_table(tables.paths[lane]) == {}


def test_parse_table_on_a_directory_is_empty(tmp_path) -> None:
    # "unreadable": read_text on a directory raises, and the parser swallows it.
    assert sc._parse_table(tmp_path) == {}


def test_item_rows_without_an_id_are_filtered(tmp_path) -> None:
    path = tmp_path / "t.json"
    path.write_text(
        json.dumps(
            {
                "champions": {
                    "ChampA": {
                        "items": [
                            {"id": "9001"},
                            {"id": 9002},
                            {"name": "Name Only"},
                            {"id": ""},
                            {"id": None},
                            "9003",
                            None,
                        ]
                    },
                    "ChampNamesOnly": {"items": [{"name": "Only Name"}]},
                    "ChampNoItems": {},
                    "ChampNull": None,
                }
            }
        ),
        encoding="utf-8",
    )
    # Integer ids are coerced to strings; this table is id-only, so a
    # names-only champion is not tabled (unlike kit_axis_credit).
    assert sc._parse_table(path) == {"ChampA": frozenset({"9001", "9002"})}


@pytest.mark.parametrize("lane", sorted(_LANES))
def test_display_name_fallback_through_champ_rec(tables, lane) -> None:
    tables(
        lane,
        {
            "champions": {
                "Display Name": {"items": [{"id": "9101"}]},
                "ChampKey": {"items": [{"id": "9201"}]},
            }
        },
    )
    getter = _LANES[lane][1]
    rec = {"name": "Display Name"}
    assert getter("missing_key", rec) == frozenset({"9101"})
    # A champion-id hit wins over the record's display name.
    assert getter("ChampKey", rec) == frozenset({"9201"})
    for bad in (None, {}, {"name": ""}, ["Display Name"], "Display Name"):
        assert getter("missing_key", bad) == _EMPTY
    # A blank champion id short-circuits even when the name would hit.
    assert getter("", rec) == _EMPTY


def test_each_lane_reads_only_its_own_file(tables) -> None:
    tables("hybrid", {"champions": {"ChampA": {"items": [{"id": "1001"}]}}})
    tables("enchanter", {"champions": {"ChampA": {"items": [{"id": "2002"}]}}})
    tables("tank", "{not json")
    assert sc.survivability_item_ids("ChampA") == frozenset({"1001"})
    assert sc.survivability_item_ids_enchanter("ChampA") == frozenset({"2002"})
    # A malformed tank table empties the tank lane only.
    assert sc.survivability_item_ids_tank("ChampA") == _EMPTY


def test_tables_are_cached_until_reset(tables) -> None:
    for lane in _LANES:
        tables(lane, {"champions": {"ChampA": {"items": [{"id": "9001"}]}}})
    for _attr, getter in _LANES.values():
        assert getter("ChampA") == frozenset({"9001"})
    # Rewrite every file WITHOUT resetting: each cached table still answers.
    for path in tables.paths.values():
        path.write_text(
            json.dumps({"champions": {"ChampA": {"items": [{"id": "9999"}]}}}),
            encoding="utf-8",
        )
    for _attr, getter in _LANES.values():
        assert getter("ChampA") == frozenset({"9001"})
    # One reset_cache() drops all three caches.
    sc.reset_cache()
    for _attr, getter in _LANES.values():
        assert getter("ChampA") == frozenset({"9999"})


@pytest.mark.parametrize("lane", sorted(_LANES))
def test_a_failed_load_is_cached_as_empty(tables, lane) -> None:
    # No file yet: the lane reads empty and caches the EMPTY map, so a table
    # that appears later is not seen until reset_cache().
    getter = _LANES[lane][1]
    assert getter("ChampA") == _EMPTY
    tables.paths[lane].write_text(
        json.dumps({"champions": {"ChampA": {"items": [{"id": "9001"}]}}}),
        encoding="utf-8",
    )
    assert getter("ChampA") == _EMPTY
    sc.reset_cache()
    assert getter("ChampA") == frozenset({"9001"})
