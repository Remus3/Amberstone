"""S144-D-87 - pin the fail-soft loader contract of ``kit_axis_credit``.

The module docstring promises: "a missing / unreadable / malformed table yields
an empty map so the seam degrades to a byte-identical no-op rather than
raising". test_kit_axis_item_credit_dsp11.py only exercises the REAL shipped
table (Pyke / Nilah / Ezreal hits, unknown and blank champion ids), so nothing
loaded a missing or malformed table, the per-item id / name filtering, the
``champ_rec["name"]`` fallback, or the cache before this file.

Each test points ``_TABLE_PATH`` at a tmp file and resets the cache before and
after, so the real table is re-read by every later test. Synthetic champion
keys and item ids only.
"""
from __future__ import annotations

import json

import pytest

from agents.daemon_slayer import kit_axis_credit as kac

_EMPTY = frozenset()


@pytest.fixture
def table(tmp_path, monkeypatch):
    """Return a writer that installs a tmp table as the module's table path."""
    path = tmp_path / "kit_axis_item_credit.json"
    monkeypatch.setattr(kac, "_TABLE_PATH", path)
    kac.reset_cache()

    def _write(payload) -> None:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        path.write_text(text, encoding="utf-8")
        kac.reset_cache()

    yield _write
    kac.reset_cache()


def test_missing_table_is_empty_not_an_error(table) -> None:
    # The fixture never writes the file, so the path does not exist.
    assert kac._load() == {}
    assert kac.kit_axis_item_ids("ChampA") == _EMPTY
    assert kac.kit_axis_item_names("ChampA") == _EMPTY


@pytest.mark.parametrize(
    "payload",
    [
        "{not json",
        "",
        "[1, 2, 3]",
        '"a string"',
        "null",
        {"champions": None},
        {"champions": {}},
        {"other": {"ChampA": {"items": [{"id": "9001"}]}}},
    ],
)
def test_malformed_table_is_empty_not_an_error(table, payload) -> None:
    table(payload)
    assert kac._load() == {}
    assert kac.kit_axis_item_ids("ChampA") == _EMPTY
    assert kac.kit_axis_item_names("ChampA") == _EMPTY


def test_item_rows_without_id_or_name_are_filtered(table) -> None:
    table(
        {
            "champions": {
                "ChampA": {
                    "items": [
                        {"id": "9001", "name": "Item One"},
                        {"id": 9002},
                        {"name": "Name Only"},
                        {"id": "", "name": ""},
                        {"id": None},
                        "9003",
                        None,
                        7,
                    ]
                },
                "ChampEmpty": {"items": [{"id": ""}, "x", None]},
                "ChampNoItems": {},
                "ChampNull": None,
            }
        }
    )
    # Integer ids are coerced to the engine's string-id convention.
    assert kac.kit_axis_item_ids("ChampA") == frozenset({"9001", "9002"})
    assert kac.kit_axis_item_names("ChampA") == frozenset({"Item One", "Name Only"})
    # A champion whose items carry no usable id AND no usable name is not tabled.
    tbl = kac._load()
    assert set(tbl) == {"ChampA"}
    for champ in ("ChampEmpty", "ChampNoItems", "ChampNull"):
        assert kac.kit_axis_item_ids(champ) == _EMPTY
        assert kac.kit_axis_item_names(champ) == _EMPTY


def test_names_only_champion_is_tabled(table) -> None:
    table({"champions": {"ChampN": {"items": [{"name": "Only Name"}]}}})
    assert kac.kit_axis_item_ids("ChampN") == _EMPTY
    assert kac.kit_axis_item_names("ChampN") == frozenset({"Only Name"})


def test_display_name_fallback_through_champ_rec(table) -> None:
    table(
        {
            "champions": {
                "Display Name": {"items": [{"id": "9101", "name": "By Name"}]},
                "ChampKey": {"items": [{"id": "9201", "name": "By Key"}]},
            }
        }
    )
    rec = {"name": "Display Name"}
    assert kac.kit_axis_item_ids("missing_key", rec) == frozenset({"9101"})
    assert kac.kit_axis_item_names("missing_key", rec) == frozenset({"By Name"})
    # A champion-id hit wins over the record's display name.
    assert kac.kit_axis_item_ids("ChampKey", rec) == frozenset({"9201"})
    # No record, a record without a name, or a non-dict record: no fallback.
    for bad in (None, {}, {"name": ""}, ["Display Name"], "Display Name"):
        assert kac.kit_axis_item_ids("missing_key", bad) == _EMPTY
        assert kac.kit_axis_item_names("missing_key", bad) == _EMPTY


def test_blank_champion_id_short_circuits_before_the_table(table) -> None:
    table({"champions": {"Display Name": {"items": [{"id": "9101"}]}}})
    rec = {"name": "Display Name"}
    # A blank id returns empty even when the record's name would hit.
    assert kac.kit_axis_item_ids("", rec) == _EMPTY
    assert kac.kit_axis_item_names("", rec) == _EMPTY
    assert kac.kit_axis_item_ids(None, rec) == _EMPTY  # type: ignore[arg-type]


def test_table_is_cached_until_reset(table, tmp_path) -> None:
    table({"champions": {"ChampA": {"items": [{"id": "9001"}]}}})
    assert kac.kit_axis_item_ids("ChampA") == frozenset({"9001"})
    # Rewrite the file WITHOUT resetting: the cached table still answers.
    (tmp_path / "kit_axis_item_credit.json").write_text(
        json.dumps({"champions": {"ChampA": {"items": [{"id": "9999"}]}}}),
        encoding="utf-8",
    )
    assert kac.kit_axis_item_ids("ChampA") == frozenset({"9001"})
    kac.reset_cache()
    assert kac.kit_axis_item_ids("ChampA") == frozenset({"9999"})


def test_a_failed_load_is_cached_as_empty(table, tmp_path) -> None:
    # Fail-soft caches the EMPTY map: a table that appears later is not seen
    # until reset_cache(), so one bad read cannot flap the seam mid-process.
    assert kac.kit_axis_item_ids("ChampA") == _EMPTY
    (tmp_path / "kit_axis_item_credit.json").write_text(
        json.dumps({"champions": {"ChampA": {"items": [{"id": "9001"}]}}}),
        encoding="utf-8",
    )
    assert kac.kit_axis_item_ids("ChampA") == _EMPTY
    kac.reset_cache()
    assert kac.kit_axis_item_ids("ChampA") == frozenset({"9001"})
