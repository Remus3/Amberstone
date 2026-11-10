"""Prose-only damage forms are counted and named by the abilities extractor (S144-D-196).

``tools/daemon_slayer_abilities_extract.py`` classes a form ``no_damage`` when
Meraki ships no damage-attribute leveling block, and ``_coverage_summary``
then drops every ``no_damage`` form from ``damage_eligible``. A form whose
Meraki record carries NO leveling at all while its effect prose states a real
numeric damage figure therefore leaves the coverage report silently: the
``ok_rate`` reads 98.96 percent at 16.22.1 with eleven such non-passive forms
out of view, and the burst walker reads every one it serves as 0.0 damage.

Measured 2026-11-09 on the shipped 16.22.1 snapshot: Aphelios R and Q forms
1-5 (his whole damaging kit), Pyke R, Blitzcrank E, Jayce R form 1, Quinn R
form 1 and Yunara W form 1. The RM-95b B2 walk (LEDGER 1060 / 1061) filtered
on forms WITH their own leveling payload, so this population was never in it.

The extractor now counts them (``prose_only_damage``) and names them
(``prose_only_damage_forms``); every pre-existing coverage key keeps its value.
The shipped-snapshot test is a ratchet: shrinking is fine, a new member needs a
measured reason. Tier-1: no ENGINE_VERSION change, no re-extract.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_TOOL = _REPO / "tools" / "daemon_slayer_abilities_extract.py"
_ALIAS = "_s144d196_abilities_extract"


@pytest.fixture(scope="module")
def ext():
    spec = importlib.util.spec_from_file_location(_ALIAS, _TOOL)
    mod = importlib.util.module_from_spec(spec)
    saved = sys.modules.get(_ALIAS)
    sys.modules[_ALIAS] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        if saved is None:
            sys.modules.pop(_ALIAS, None)
        else:
            sys.modules[_ALIAS] = saved
    return mod


def _form(
    *,
    key: str = "Q",
    status: str = "no_damage",
    leveling: int = 0,
    prose: tuple[str, ...] = (
        "Active: fires a bolt that deals 70 : 160 (based on level) "
        "(+ 42% bonus AD) physical damage to the first enemy hit.",
    ),
    index: int = 0,
) -> dict:
    return {
        "key": key,
        "name": "Synthetic",
        "form_index": index,
        "damage_blocks": [],
        "effects_descriptions": list(prose),
        "raw_effects_count": len(prose),
        "raw_leveling_count": leveling,
        "parse_status": status,
        "parse_notes": [],
    }


# The eleven forms measured at 16.22.1 (champion, key, form_index).
KNOWN_PROSE_ONLY = frozenset(
    {("Aphelios", "Q", i) for i in range(1, 6)}
    | {
        ("Aphelios", "R", 0),
        ("Blitzcrank", "E", 0),
        ("Jayce", "R", 1),
        ("Pyke", "R", 0),
        ("Quinn", "R", 1),
        ("Yunara", "W", 1),
    }
)


class TestIsProseOnlyDamage:
    def test_no_leveling_form_with_numeric_typed_damage_is_flagged(self, ext):
        assert ext._is_prose_only_damage(_form()) is True

    @pytest.mark.parametrize("dtype", ["physical", "magic", "true", "Magic"])
    def test_every_damage_type_word_counts(self, ext, dtype):
        prose = (f"Active: deals 50 / 200 / 350 (+ 75% AP) {dtype} damage.",)
        assert ext._is_prose_only_damage(_form(prose=prose)) is True

    def test_passive_is_never_flagged(self, ext):
        # Passive damage lives in _passive_damage_overrides; 177 of the 178
        # passives are no_damage by design.
        assert ext._is_prose_only_damage(_form(key="P")) is False

    def test_form_with_its_own_leveling_is_not_flagged(self, ext):
        # The RM-95b B2 population (Jayce W Hyper Charge, Mel W Rebuttal,
        # Morgana E's shield absorb): a leveling payload exists, so the gap
        # is a modifier / non-damage block, not a missing number.
        assert ext._is_prose_only_damage(_form(leveling=1)) is False

    @pytest.mark.parametrize("status", ["ok", "partial", "unparsed"])
    def test_a_form_with_a_damage_block_is_not_flagged(self, ext, status):
        assert ext._is_prose_only_damage(_form(status=status)) is False

    @pytest.mark.parametrize(
        "prose",
        [
            ("Active: gains 30% bonus movement speed for 4 seconds.",),
            ("Active: reduces damage taken by 20%.",),
            ("Passive: basic attacks deal bonus physical damage.",),
            (),
        ],
    )
    def test_prose_without_a_numeric_typed_damage_figure_is_not_flagged(
        self, ext, prose
    ):
        assert ext._is_prose_only_damage(_form(prose=prose)) is False

    @pytest.mark.parametrize(
        "junk",
        [None, "deals 5 physical damage", 7, {"x": 1}, [None, 3]],
    )
    def test_junk_prose_field_never_raises(self, ext, junk):
        form = _form()
        form["effects_descriptions"] = junk
        assert ext._is_prose_only_damage(form) in (True, False)

    def test_junk_form_never_raises(self, ext):
        assert ext._is_prose_only_damage(None) is False
        assert ext._is_prose_only_damage("Q") is False
        bad = _form()
        bad["raw_leveling_count"] = "0"
        assert ext._is_prose_only_damage(bad) is False


class TestCoverageSummary:
    def _data(self):
        return {
            "Zed": {
                "P": [_form(key="P")],
                "Q": [_form(key="Q", status="ok", leveling=1)],
                "W": [_form(key="W", prose=("Active: dashes.",))],
                "E": [_form(key="E", status="ok", leveling=1)],
                "R": [_form(key="R")],
            },
            "Aphelios": {
                "Q": [
                    _form(key="Q", prose=("Passive: wields weapons.",)),
                    _form(key="Q", index=1),
                ],
            },
        }

    def test_counts_and_names_the_prose_only_forms(self, ext):
        cov = ext._coverage_summary(self._data())
        assert cov["prose_only_damage"] == 2
        assert cov["prose_only_damage_forms"] == ["Aphelios/Q/1", "Zed/R/0"]

    def test_existing_keys_keep_their_values(self, ext):
        cov = ext._coverage_summary(self._data())
        assert cov["total_forms"] == 7
        assert cov["multiform_keys"] == 1
        assert cov["status_counts"] == {
            "ok": 2, "partial": 0, "unparsed": 0, "no_damage": 5,
        }
        assert cov["damage_eligible"] == 2
        assert cov["ok_rate"] == 1.0
        assert cov["parsed_rate"] == 1.0

    def test_empty_data_reports_zero(self, ext):
        cov = ext._coverage_summary({})
        assert cov["prose_only_damage"] == 0
        assert cov["prose_only_damage_forms"] == []


def _shipped_abilities() -> dict:
    patch = (_REPO / "data" / "daemon_slayer" / "current.txt").read_text(
        encoding="utf-8"
    ).strip()
    path = _REPO / "data" / "daemon_slayer" / patch / "champion_abilities.json"
    return json.loads(path.read_text(encoding="utf-8"))["data"]


def test_shipped_snapshot_population_stays_within_the_measured_set(ext):
    data = _shipped_abilities()
    found = {
        (champ, key, form.get("form_index"))
        for champ, keymap in data.items()
        for key, forms in keymap.items()
        for form in forms or []
        if ext._is_prose_only_damage(form)
    }
    # Anchor: an empty population would pass the subset check vacuously.
    assert found, "helper found nothing on the shipped snapshot"
    assert found <= KNOWN_PROSE_ONLY, sorted(found - KNOWN_PROSE_ONLY)
