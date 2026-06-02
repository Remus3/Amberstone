"""Regression: champ-select build chooser empty for apostrophe champions.

The champ-select view resolves championId -> name via CHAMPS.byId, which is
the DDragon-KEY form ("Kaisa", "Khazix", "RekSai") with no apostrophe. The
loadout store (data/champion_loadouts.json) is keyed by DISPLAY name
("Kai'Sa"). Before the _lookup_champ fuzzy-normalized fallback the exact
loadouts.get("Kaisa") missed -> the chooser populated nothing for every
special-char champ.

These tests pin that list_variants + resolve both resolve from EITHER name
form so the chooser populates + a build click still pushes.
"""
from __future__ import annotations

import coaches.loadout_resolver as r

# (ddragon-key form, display form, championId) for the special-char champs
# that ship SR loadouts. Pulled from web/data/champions_index.json byId.
_PAIRS = [
    ("Kaisa", "Kai'Sa", 145),
    ("Khazix", "Kha'Zix", 121),
    ("RekSai", "Rek'Sai", 421),
    ("KogMaw", "Kog'Maw", 96),
    ("Chogath", "Cho'Gath", 31),
    ("Velkoz", "Vel'Koz", 161),
    ("Belveth", "Bel'Veth", 200),
]


def _has_loadout(name: str, mode: str = "sr") -> bool:
    return len(r.list_variants(name, mode)) > 0


def test_key_form_matches_display_form_list_variants():
    """Both name forms return the SAME variant rows (count + keys)."""
    for key_form, display_form, _cid in _PAIRS:
        if not _has_loadout(display_form):
            # Champ may legitimately lack an SR loadout entry; skip - the
            # invariant is "key form == display form", not "must exist".
            continue
        by_key = r.list_variants(key_form, "sr")
        by_disp = r.list_variants(display_form, "sr")
        assert len(by_key) == len(by_disp) > 0, key_form
        assert [v.get("key") for v in by_key] == [
            v.get("key") for v in by_disp
        ], key_form


def test_kaisa_key_form_populates_and_resolves():
    """The reported bug: Kai'Sa (id 145) chooser empty in champ select."""
    rows = r.list_variants("Kaisa", "sr")
    assert rows, "Kaisa SR chooser must populate from the DDragon-key form"
    # apply path: a build click must still push (item_cmd populated)
    res = r.resolve("Kaisa", "sr-collapsed:adc-on-hit", "sr")
    assert res.get("ok") is True
    assert len(res.get("raw_items") or []) >= 1
    ic = res.get("item_cmd") or {}
    assert ic.get("champion_id") == 145
    # same identity as the display form -> idempotent LCU set
    res_disp = r.resolve("Kai'Sa", "sr-collapsed:adc-on-hit", "sr")
    assert (res_disp.get("item_cmd") or {}).get("set_uid") == ic.get("set_uid")


def test_norm_unifies_name_forms():
    """_norm collapses apostrophe/case so either form keys the same entry."""
    assert r._norm("Kai'Sa") == r._norm("Kaisa") == "kaisa"
    assert r._norm("Kha'Zix") == r._norm("Khazix") == "khazix"


def test_lookup_champ_unknown_returns_empty():
    """An unknown champion still resolves to {} (no crash, no false match)."""
    loadouts = r._load_loadouts().get("champions", {}) or {}
    assert r._lookup_champ(loadouts, "ZzzNotAChampion") == {}
    assert r._lookup_champ(loadouts, "") == {}
