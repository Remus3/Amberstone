"""S144-D-381 - the DS champion ally-reach gate matches the live text it cites.

WHY. ``_champion_ally_reach`` (Term A, A-21 / RM-90 S2) documents its token
counts, the ``affects`` hazards, its override rationale and a prose-scan count
from the patch it was written at (16.14.1). The override guard
(``test_champion_ally_reach_overrides.py``) pins the SETS; nothing pinned the
prose to the live snapshot, and four claims had drifted or never held:

* "three misspellings of Enemies (Ememies)": there is ONE misspelling, on
  three forms (Renata Q, Renata E, Vex Q). A fourth variant, the singular
  ``Enemy`` (Blitzcrank E), went unnamed.
* "Each is Support-role and tank-routed": all four overrides are tank-routed,
  but Poppy's DDragon tags are Tank / Fighter, not Support.
* "the champions carrying those (allied turrets, oathsworn ally, rakan) are
  marksmen": ``Allied turrets`` sits on Janna E, an enchanter already reached
  through the plain ``Allies`` token in the same field; only Kalista R and
  Xayah W are marksmen.
* "scanning effects_descriptions for allied/allies/ally admits 27 further
  champions at 16.14.1": that scan admits 25 (24 once the Leona override is
  applied) in EVERY vendored dir 16.10.1..16.22.1, and no case or boundary
  variant of it yields 27.

Also recorded: ``champions.json`` keys two champions (Locke, Zaahen) that
``champion_abilities.json`` does not, so the gate reads False for them.

MEASURED 2026-11-09 (``data/daemon_slayer/current.txt`` = 16.22.1). Docstring
and comment fixes only; no registry value or code path changes, so scorer
output is byte-identical.
"""

from __future__ import annotations

import inspect
import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from agents.daemon_slayer import _champion_ally_reach as car
from core import archetype_picks

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA = _REPO_ROOT / "data" / "daemon_slayer"
_SLOTS = ("P", "Q", "W", "E", "R")
_PROSE_ALLY = re.compile(r"\b(allied|allies|ally)\b", re.IGNORECASE)


def _patch() -> str:
    return (_DATA / "current.txt").read_text(encoding="utf-8").strip()


@cache
def _abilities(patch: str) -> dict[str, Any]:
    raw = json.loads(
        (_DATA / patch / "champion_abilities.json").read_text(encoding="utf-8")
    )
    return raw["data"]


@cache
def _champions() -> dict[str, Any]:
    raw = json.loads(
        (_DATA / _patch() / "champions.json").read_text(encoding="utf-8")
    )
    return raw["data"]


def _ability_dirs() -> list[str]:
    return sorted(
        d.name
        for d in _DATA.iterdir()
        if (d / "champion_abilities.json").is_file()
    )


def _forms(body: dict[str, Any], champion: str, slot: str) -> list[dict]:
    forms = body[champion].get(slot) or []
    return [f for f in forms if isinstance(f, dict)]


def _all_forms(body: dict[str, Any]):
    for champion in body:
        for slot in _SLOTS:
            for form in _forms(body, champion, slot):
                yield champion, slot, form


def _strict(body: dict[str, Any]) -> tuple[int, set[str]]:
    hits = [
        champion
        for champion, _slot, form in _all_forms(body)
        if car._ALLY_TOKEN in car._affects_tokens(form.get("affects"))
    ]
    return len(hits), set(hits)


def _prose_champions(body: dict[str, Any]) -> set[str]:
    return {
        champion
        for champion, _slot, form in _all_forms(body)
        for text in form.get("effects_descriptions") or []
        if isinstance(text, str) and _PROSE_ALLY.search(text)
    }


def _affects_where(body: dict[str, Any], pred) -> list[tuple[str, str]]:
    return sorted(
        (champion, slot)
        for champion, slot, form in _all_forms(body)
        if pred(form.get("affects"))
    )


def _flat(text: str) -> str:
    return " ".join(text.split())


_DOC = _flat(car.__doc__ or "")
# Comment continuation markers dropped so a phrase wrapped across ``#`` lines
# still reads as one phrase.
_SRC = _flat(re.sub(r"\n[ \t]*#[ \t]?", "\n", inspect.getsource(car)))


def test_doc_and_source_are_nonempty():
    assert len(_DOC) > 500
    assert "_ALLY_REACH_INCLUDED" in _SRC


# --- strict-token counts ------------------------------------------------------


@pytest.mark.parametrize("patch", _ability_dirs())
def test_strict_token_counts_hold_in_every_vendored_dir(patch):
    forms, champions = _strict(_abilities(patch))
    assert (forms, len(champions)) == (70, 40)


def test_doc_states_the_live_strict_counts():
    forms, champions = _strict(_abilities(_patch()))
    assert f"{forms} forms across {len(champions)} champions" in _DOC
    assert _patch() in _DOC


def test_index_is_strict_minus_exclusions_plus_overrides():
    _, champions = _strict(_abilities(_patch()))
    expected = (champions - car._ALLY_REACH_EXCLUDED) | car._ALLY_REACH_INCLUDED
    car._ally_reach_index.cache_clear()
    try:
        index = car._ally_reach_index(_patch())
    finally:
        car._ally_reach_index.cache_clear()
    assert index == frozenset(car._norm_key(c) for c in expected)
    assert len(index) == 42


# --- affects hazards ----------------------------------------------------------


def test_ememies_is_one_misspelling_on_three_forms():
    body = _abilities(_patch())
    where = _affects_where(
        body, lambda a: "ememies" in car._affects_tokens(a)
    )
    assert where == [("Renata", "E"), ("Renata", "Q"), ("Vex", "Q")]
    assert "three misspellings" not in _DOC
    assert "one misspelling" in _DOC
    assert '``"Ememies"``: Renata Q and E, Vex Q' in _DOC


def test_singular_enemy_variant_is_named():
    body = _abilities(_patch())
    where = _affects_where(body, lambda a: "enemy" in car._affects_tokens(a))
    assert where == [("Blitzcrank", "E")]
    assert '``"Enemy, Structure"``' in _DOC
    assert "Blitzcrank E" in _DOC


@pytest.mark.parametrize(
    "raw",
    ["Self, Enemies", "Enemies / Self", "Enemies, Allies", "Allies, Enemies",
     "self", "None"],
)
def test_the_other_named_hazards_are_live(raw):
    body = _abilities(_patch())
    assert _affects_where(body, lambda a: a == raw)
    assert raw in _DOC


def test_none_value_is_live():
    body = _abilities(_patch())
    assert _affects_where(body, lambda a: a is None)


# --- exclusion and override rationale ----------------------------------------


def _prose(champion: str, slot: str) -> str:
    body = _abilities(_patch())
    return " ".join(
        text
        for form in _forms(body, champion, slot)
        for text in form.get("effects_descriptions") or []
        if isinstance(text, str)
    )


def test_cited_prose_quotes_are_live():
    assert (
        "Allied champions' damaging attacks and abilities against a marked "
        "target will consume the mark to deal"
    ) in _prose("Leona", "P")
    assert "bonus magic damage" in _prose("Leona", "P")
    assert "Footwork can also be cast on allies" in _prose("KSante", "E")
    assert "they receive the shield as well" in _prose("KSante", "E")
    assert "Masterwork" in _prose("Ornn", "P")
    assert "nearby allied melee champions' basic attacks" in _prose(
        "Sejuani", "E"
    )
    nunu = _prose("Nunu", "P")
    assert "bonus attack speed" in nunu
    assert "bonus movement speed" in nunu
    assert "target allied champion" in _prose("Rell", "E")


def test_leona_p_affects_is_enemies():
    body = _abilities(_patch())
    assert [f.get("affects") for f in _forms(body, "Leona", "P")] == ["Enemies"]


def test_override_tags_and_routes_match_the_doc():
    champions = _champions()
    for champion in sorted(car._ALLY_REACH_INCLUDED):
        info = archetype_picks.get_archetype_for(champion)
        assert info["primary"] == "tank", champion
    support = sorted(
        c for c in car._ALLY_REACH_INCLUDED
        if "Support" in champions[c]["tags"]
    )
    assert support == ["Blitzcrank", "Leona", "Nautilus"]
    assert champions["Poppy"]["tags"] == ["Tank", "Fighter"]
    assert "Each is Support-role" not in _SRC
    assert "Poppy is tagged ``Tank`` / ``Fighter``" in _SRC


def test_overrides_carry_no_prose_ally_word_except_leona():
    body = _abilities(_patch())
    hits = _prose_champions(body) & car._ALLY_REACH_INCLUDED
    assert hits == {"Leona"}


# --- non-admitted tokens ------------------------------------------------------


def test_non_admitted_ally_tokens_and_their_holders():
    body = _abilities(_patch())
    tokens = {"allied turrets": [], "oathsworn ally": [], "rakan": []}
    for champion, slot, form in _all_forms(body):
        toks = car._affects_tokens(form.get("affects"))
        for tok, holders in tokens.items():
            if tok in toks:
                holders.append((champion, slot, car._ALLY_TOKEN in toks))
    assert tokens == {
        "allied turrets": [("Janna", "E", True)],
        "oathsworn ally": [("Kalista", "R", False)],
        "rakan": [("Xayah", "W", False)],
    }
    for champion in ("Kalista", "Xayah"):
        assert archetype_picks.get_archetype_for(champion)["primary"] == "carry"
    assert "the champions carrying those are marksmen" not in _SRC
    assert "Janna E" in _SRC
    assert "Kalista R" in _SRC
    assert "Xayah W" in _SRC


# --- prose-scan count ---------------------------------------------------------


@pytest.mark.parametrize("patch", _ability_dirs())
def test_prose_scan_count_holds_in_every_vendored_dir(patch):
    body = _abilities(patch)
    _, strict = _strict(body)
    further = _prose_champions(body) - strict
    assert len(further) == 25
    assert len(further - car._ALLY_REACH_INCLUDED) == 24


def test_doc_states_the_live_prose_scan_count():
    body = _abilities(_patch())
    _, strict = _strict(body)
    further = _prose_champions(body) - strict
    net = further - car._ALLY_REACH_INCLUDED
    assert "27 further champions" not in _SRC
    assert f"admits {len(further)} further champions" in _SRC
    assert f"{len(net)} once Leona" in _SRC
    for name, key in (("Akshan", "Akshan"), ("Annie", "Annie"),
                      ("Fiora", "Fiora"), ("Jhin", "Jhin"),
                      ("Kha'Zix", "Khazix")):
        assert key in net
        assert name in _SRC


# --- key coverage -------------------------------------------------------------


def test_abilities_keys_are_a_subset_of_the_snapshot():
    body = _abilities(_patch())
    snapshot = set(_champions())
    assert set(body) - snapshot == set()
    assert sorted(snapshot - set(body)) == ["Locke", "Zaahen"]
    for champion in ("Locke", "Zaahen"):
        assert car.champion_ally_reach(champion) is False
        assert champion in _DOC
    assert f"{len(body)} champions are keyed" in _DOC
