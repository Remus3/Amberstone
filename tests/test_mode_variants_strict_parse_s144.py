"""s144 true-audit (S144-T-682): agents/daemon_slayer/mode_variants.py parses
ids by the DDragon grammar, not by Python's int().

The module's stated fail-safe is "a row whose key or id we cannot classify is
KEPT" - dropping a row silently shrinks the roster or the item pool. Before this
audit the predicates ran ``int(str(value).strip())``, and Python's int() is far
wider than DDragon's ``^[0-9]+$`` id grammar: it accepts digit-group
underscores, a leading sign, and every Unicode decimal digit (fullwidth,
Arabic-Indic, ...), and str.strip() eats Unicode spaces. Each of those shapes
was classified as a throwback VARIANT and the row was dropped - the opposite of
the fail-safe direction. An object whose ``__str__`` raised anything but
TypeError / ValueError escaped the predicate entirely, and the two partition
helpers raised an anonymous AttributeError on a non-mapping input.

Characterization pins (the shapes DDragon really ships, plus the tolerated
ASCII padding the old code stripped) are kept green across the rewrite.
"""

from __future__ import annotations

import pytest

from agents.daemon_slayer.mode_variants import (
    canonical_champions,
    canonical_items,
    is_mode_variant_champion,
    is_mode_variant_item,
)


def _champ(key):
    return is_mode_variant_champion("Foo", {"id": "Foo", "key": key})


class _BadStr:
    """A value whose str() fails with an error the old except did not name."""

    def __str__(self):
        raise RuntimeError("boom")


# --------------------------------------------------------------------------
# Characterization: the shapes that classify today and must keep classifying.
# --------------------------------------------------------------------------


class TestCharacterization:
    @pytest.mark.parametrize("key", ["60001", 60001, " 60001\n", "\t60117 ", "060001"])
    def test_ddragon_shaped_variant_keys_still_drop(self, key):
        assert _champ(key) is True

    @pytest.mark.parametrize("key", ["1", 950, "59999", "0", -5])
    def test_live_champion_keys_still_kept(self, key):
        assert _champ(key) is False

    @pytest.mark.parametrize("key", [True, False, 60001.0, b"60001", None, "", "abc", "6e4"])
    def test_non_ddragon_types_are_kept(self, key):
        assert _champ(key) is False

    @pytest.mark.parametrize("iid", ["771001", 771001, " 773521 ", "770000", "779999"])
    def test_band_items_still_drop(self, iid):
        assert is_mode_variant_item(iid) is True

    @pytest.mark.parametrize(
        "iid", [True, 771001.0, b"771001", "9" * 5000, "", None, 780000, "220001"]
    )
    def test_non_band_or_unparseable_items_are_kept(self, iid):
        assert is_mode_variant_item(iid) is False

    def test_non_mapping_champion_entry_is_kept(self):
        assert is_mode_variant_champion("Foo", None) is False
        assert is_mode_variant_champion("Foo", ["key", "60001"]) is False

    def test_partition_preserves_order_and_odd_entries(self):
        rows = {"B": {"key": "2"}, "J": {"key": "60002"}, "A": None, "S": "str"}
        assert list(canonical_champions(rows)) == ["B", "A", "S"]
        items = {"3006": {}, "771001": {}, "boots": {}, 1001: {}}
        assert list(canonical_items(items)) == ["3006", "boots", 1001]


# --------------------------------------------------------------------------
# Findings: each failed before the rewrite.
# --------------------------------------------------------------------------


_NON_DDRAGON_CHAMP_KEYS = [
    "60_001",  # digit-group underscore
    "+60001",  # explicit sign
    "\uff16\uff10\uff10\uff10\uff11",  # fullwidth digits
    "\u0666\u0660\u0660\u0660\u0661",  # Arabic-Indic digits
    "\u200360001",  # Unicode em space padding
    "60001\u3000",  # ideographic space padding
]

_NON_DDRAGON_ITEM_IDS = [
    "77_1001",
    "+771001",
    "\uff17\uff17\uff11\uff10\uff10\uff11",
    "\u0667\u0667\u0661\u0660\u0660\u0661",
    "\u2003771001",
]


class TestStrictDdragonGrammar:
    @pytest.mark.parametrize("key", _NON_DDRAGON_CHAMP_KEYS)
    def test_non_ddragon_champion_key_is_kept_not_dropped(self, key):
        # Fail-safe: a key outside the DDragon grammar is unclassifiable.
        assert _champ(key) is False

    @pytest.mark.parametrize("iid", _NON_DDRAGON_ITEM_IDS)
    def test_non_ddragon_item_id_is_kept_not_dropped(self, iid):
        assert is_mode_variant_item(iid) is False

    def test_partition_keeps_the_non_ddragon_rows(self):
        rows = {f"c{i}": {"key": k} for i, k in enumerate(_NON_DDRAGON_CHAMP_KEYS)}
        assert canonical_champions(rows) == rows
        items = {iid: {} for iid in _NON_DDRAGON_ITEM_IDS}
        assert canonical_items(items) == items


class TestNeverRaises:
    def test_champion_key_with_failing_str_is_kept(self):
        assert _champ(_BadStr()) is False

    def test_item_id_with_failing_str_is_kept(self):
        assert is_mode_variant_item(_BadStr()) is False

    def test_partition_survives_a_failing_str_key(self):
        bad = _BadStr()
        assert list(canonical_items({bad: {}})) == [bad]


class TestNonMappingInputIsANamedTypeError:
    @pytest.mark.parametrize("bad", [None, [("1001", {})], "abc", 7])
    def test_canonical_champions(self, bad):
        with pytest.raises(TypeError, match="canonical_champions"):
            canonical_champions(bad)

    @pytest.mark.parametrize("bad", [None, [("1001", {})], "abc", 7])
    def test_canonical_items(self, bad):
        with pytest.raises(TypeError, match="canonical_items"):
            canonical_items(bad)
