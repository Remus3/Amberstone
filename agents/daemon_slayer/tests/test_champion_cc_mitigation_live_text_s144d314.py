"""S144-D-314..317 - the DS champion CC-mitigation registry matches the live text it cites.

WHY. ``_champion_cc_mitigation_overrides`` copies a tenacity percent and a
window out of quoted ability text (Garen W, Olaf R, Malzahar P) and names, in
its docstring, every CC-immunity ability it deliberately leaves out and which
sibling registry owns the rest of each ability. Its only test
(``test_champion_cc_mitigation_item290.py``) pins the arithmetic, never the
text, so a patch that rewrote one of these abilities would move the real value
while every guard stays green.

* S144-D-314: every row's tenacity percent and window equal its live
  sentence; the attribute names the live ability; each row is amortized at the
  midpoint its window class names (brief steroid / active ult / passive); the
  Olaf R cooldown the comment quotes is live; the four routes the docstring
  names are exactly the POST routes that parse ``apply_champion_tenacity``; and
  every documented exclusion still carries the live phrase it was excluded for.
* S144-D-315: the module said Malzahar's Void Shift 90% damage reduction "is
  the SEPARATE ``_passive_mitigation_overrides`` axis", but that registry lists
  it as an IMMUNITY-UNTIL-HIT exclusion and its snapshot fold scans only Q / W /
  E / R, so the 90% is modeled nowhere. Docstring, comment and note corrected.
* S144-D-316: the Alistar R damage reduction was quoted as 45/55/65%; the live
  block is 55/65/75%. The Morgana E exclusion called Black Shield a
  "single-CC absorb"; the live text grants crowd control immunity while the 5 s
  shield holds. Both corrected, and the spell-shield module, which quotes the
  old sentence verbatim, now marks the Morgana half as corrected.
* S144-D-317: the Milio R exclusion said the tenacity "rides a TEAMMATE"; the
  live text grants the 65% tenacity to Milio himself as well. The self half
  meets this registry's own inclusion rule and is NOT seeded; the docstring now
  says so, and the seed is filed as a Tier-2 follow-up (a registry value change
  moves ``cc_blended_ehp`` whenever ``apply_champion_tenacity`` is on).

MEASURED 2026-11-09 (``data/daemon_slayer/current.txt`` = 16.22.1). Guards plus
docstring / comment / note fixes; no registry value changes, so the scorer
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

from agents.daemon_slayer import _champion_cc_mitigation_overrides as cc_mod
from agents.daemon_slayer import _champion_spell_shield_overrides as spell_shield_mod
from agents.daemon_slayer import server
from agents.daemon_slayer._champion_cc_mitigation_overrides import (
    _BRIEF_TENACITY_PROB,
    _CC_IMMUNITY_ACTIVE_PROB,
    _CC_IMMUNITY_PASSIVE_PROB,
    _CHAMPION_CC_MITIGATION_OVERRIDES,
)
from agents.daemon_slayer._passive_mitigation_overrides import (
    _PASSIVE_MITIGATION_OVERRIDES,
    mitigation_multipliers,
)
from agents.daemon_slayer._passive_mitigation_overrides import (
    __doc__ as _MITIGATION_DOC,
)
from agents.daemon_slayer._passive_resist_overrides import _PASSIVE_RESIST_OVERRIDES
from agents.daemon_slayer.data_loader import DataSnapshot

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA = _REPO_ROOT / "data" / "daemon_slayer"
_DOC = cc_mod.__doc__ or ""
_SOURCE = inspect.getsource(cc_mod)


def _patch_dir() -> Path:
    return _DATA / (_DATA / "current.txt").read_text(encoding="utf-8").strip()


@cache
def _snapshot(name: str) -> Any:
    raw = json.loads((_patch_dir() / name).read_text(encoding="utf-8"))
    return raw.get("data", raw) if isinstance(raw, dict) else raw


@cache
def _ds() -> DataSnapshot:
    return DataSnapshot.load()


def _form(champion: str, key: str, form_index: int = 0) -> dict[str, Any]:
    forms = _snapshot("champion_abilities.json")[champion][key]
    hits = [f for f in forms if f.get("form_index", 0) == form_index]
    assert len(hits) == 1, f"{champion} {key}[{form_index}]: {len(hits)} forms"
    return hits[0]


def _one_match(form: dict[str, Any], pattern: str) -> re.Match[str]:
    rx = re.compile(pattern)
    hits = [m for s in form["effects_descriptions"] if (m := rx.search(s))]
    assert len(hits) == 1, f"{form['name']}: {len(hits)} sentences match {pattern}"
    return hits[0]


def _doc_one(pattern: str) -> re.Match[str]:
    hits = list(re.finditer(pattern, _DOC))
    assert len(hits) == 1, f"module docstring: {len(hits)} matches for {pattern}"
    return hits[0]


# --- S144-D-314: the three seeded rows ----------------------------------------


def test_the_registry_is_exactly_the_three_rows_tested_here() -> None:
    """A new row lands red here until it gets its own live-text test below."""
    assert set(_CHAMPION_CC_MITIGATION_OVERRIDES) == {
        ("Garen", "W", 0),
        ("Olaf", "R", 0),
        ("Malzahar", "P", 0),
    }


@pytest.mark.parametrize(("champion", "key", "form_index"), sorted(_CHAMPION_CC_MITIGATION_OVERRIDES))
def test_every_row_names_its_live_ability_and_is_flat(champion: str, key: str, form_index: int) -> None:
    entry = _CHAMPION_CC_MITIGATION_OVERRIDES[(champion, key, form_index)]
    assert champion in _snapshot("champions.json")
    assert entry.attribute == _form(champion, key, form_index)["name"]
    assert isinstance(entry.tenacity_pct, float)
    assert not entry.rank_scaled
    assert not entry.level_scaled


def test_garen_courage_tenacity_and_window_match_live_text() -> None:
    m = _one_match(
        _form("Garen", "W"),
        r"For the first ([\d.]+) seconds, Garen additionally grants himself a shield and (\d+)% tenacity",
    )
    entry = _CHAMPION_CC_MITIGATION_OVERRIDES[("Garen", "W", 0)]
    assert entry.tenacity_pct == float(m.group(2))
    assert entry.conditional_probability == _BRIEF_TENACITY_PROB
    assert f"{m.group(2)}% tenacity for the first {m.group(1)}s" in entry.note


def test_olaf_ragnarok_immunity_window_and_cooldown_match_live_text() -> None:
    form = _form("Olaf", "R")
    m = _one_match(
        form,
        r"Olaf becomes enraged for (\d+) seconds, cleansing himself of all crowd control and becoming immune to them",
    )
    entry = _CHAMPION_CC_MITIGATION_OVERRIDES[("Olaf", "R", 0)]
    assert entry.tenacity_pct == 100.0
    assert entry.conditional_probability == _CC_IMMUNITY_ACTIVE_PROB
    assert f"for the {m.group(1)}s active" in entry.note
    cd = "/".join(str(int(v)) for v in form["cooldown"])
    assert f"{m.group(1)}s active on a {cd}s CD" in _SOURCE
    # The note sends the passive armor / MR to the _passive_resist axis: it is
    # a live sentence on this form and that registry holds the row.
    _one_match(form, r"^Passive: Olaf gains bonus armor and bonus magic resistance\.")
    assert ("Olaf", "R", 0) in _PASSIVE_RESIST_OVERRIDES


def test_malzahar_void_shift_immunity_matches_live_text() -> None:
    form = _form("Malzahar", "P")
    _one_match(form, r"Void Shift: Malzahar gains crowd control immunity and 90% damage reduction\.")
    _one_match(form, r"until he takes non- minion damage or negates a crowd control effect")
    entry = _CHAMPION_CC_MITIGATION_OVERRIDES[("Malzahar", "P", 0)]
    assert entry.tenacity_pct == 100.0
    assert entry.conditional_probability == _CC_IMMUNITY_PASSIVE_PROB


def test_the_routes_the_docstring_names_are_the_routes_that_parse_the_flag() -> None:
    parsing = {
        path
        for path, handler in server._POST_ROUTES.items()
        if '"apply_champion_tenacity"' in inspect.getsource(handler)
    }
    assert parsing == {"/ehp", "/rank-tank", "/hybrid", "/rank-bruiser"}
    assert "Route-\nreachable on ``/ehp`` / ``/rank-tank`` / ``/hybrid`` / ``/rank-bruiser``." in _DOC


@pytest.mark.parametrize(
    ("champion", "key", "form_index", "phrase"),
    [
        ("Sion", "R", 0, r"Sion becomes immune to crowd control and ghosted and, after a brief delay, charges"),
        ("Warwick", "R", 0, r"Warwick leaps in the target direction with crowd control immunity"),
        ("Pantheon", "R", 0, r"becoming immune to crowd control until he reappears"),
        ("Kled", "R", 0, r"during which they are ghosted, immune to crowd control"),
        ("Kled", "P", 0, r"cleansing himself of all crowd control and becoming unable to act"),
        ("Galio", "R", 0, r"he gains crowd control immunity for the remaining duration"),
        ("Briar", "R", 0, r"becomes immune to them over a cast time, afterwards dashing"),
        ("Fiora", "W", 0, r"enters a defensive stance for 0\.75 seconds.*crowd control immunity"),
        ("Alistar", "R", 0, r"^Active: Alistar cleanses himself of all crowd control\."),
        ("Bard", "R", 0, r"Epic monsters and turrets are affected by Tempered Fate despite being immune"),
    ],
)
def test_every_documented_exclusion_still_carries_its_live_phrase(
    champion: str, key: str, form_index: int, phrase: str
) -> None:
    _one_match(_form(champion, key, form_index), phrase)
    assert champion in _DOC
    assert all(c != champion for (c, _k, _f) in _CHAMPION_CC_MITIGATION_OVERRIDES)


# --- S144-D-315: the Malzahar 90% damage reduction is modeled nowhere ---------


def test_malzahar_damage_reduction_is_a_mitigation_registry_exclusion() -> None:
    assert all(c != "Malzahar" for (c, _k, _f) in _PASSIVE_MITIGATION_OVERRIDES)
    assert _form("Malzahar", "P")["damage_blocks"] == []
    assert mitigation_multipliers("Malzahar", 18, True, snapshot=_ds()) == (1.0, 1.0, 1.0)
    assert "IMMUNITY-UNTIL-HIT" in (_MITIGATION_DOC or "")
    assert "Malzahar\n    P Void Shift" in (_MITIGATION_DOC or "")


def test_the_cc_module_no_longer_says_the_malzahar_dr_is_modeled() -> None:
    assert "90% damage reduction is the SEPARATE" not in _SOURCE
    assert "the 90% damage reduction is the _passive_mitigation axis" not in _SOURCE
    note = _CHAMPION_CC_MITIGATION_OVERRIDES[("Malzahar", "P", 0)].note
    assert "the 90% damage reduction is modeled nowhere" in note
    assert "IMMUNITY-UNTIL-HIT exclusion" in _DOC


# --- S144-D-316: the Alistar R and Morgana E exclusion prose matches live ----


def test_alistar_r_damage_reduction_percents_match_the_live_block() -> None:
    live = _ds().spell_damage_reduction_pct("Alistar", "R")
    assert live is not None
    assert set(live) == {"Damage Reduction"}
    quoted = _doc_one(r"Alistar R (\d+)/(\d+)/(\d+)%")
    assert tuple(float(g) for g in quoted.groups()) == live["Damage Reduction"]
    # The docstring sends it to _passive_mitigation_overrides: its snapshot
    # fold reads that block (Alistar has no hand-authored row).
    assert all(c != "Alistar" for (c, _k, _f) in _PASSIVE_MITIGATION_OVERRIDES)
    assert mitigation_multipliers("Alistar", 18, True, snapshot=_ds()) != (1.0, 1.0, 1.0)


def test_morgana_black_shield_exclusion_matches_live_text() -> None:
    m = _one_match(
        _form("Morgana", "E"),
        r"grants a shield to the target allied champion or herself for (\d+) seconds, which absorbs incoming"
        r" magic damage and grants crowd control immunity while it holds",
    )
    assert "single-CC absorb" not in _DOC
    assert f"Morgana\n    E Black Shield's {m.group(1)}s magic shield that grants CC immunity while it holds" in _DOC
    assert "the shield\n    breaking" in _DOC
    # The spell-shield module quotes the old item-290 sentence; it must say the
    # Morgana half was corrected rather than leave the stale reading unmarked.
    shield_doc = spell_shield_mod.__doc__ or ""
    assert "Morgana E Black Shield's single-CC absorb" in shield_doc
    assert "S144-D-316 corrected the Morgana half there" in shield_doc


# --- S144-D-317: Milio R grants the tenacity to Milio himself too ------------


def test_milio_breath_of_life_self_tenacity_is_documented_as_unseeded() -> None:
    m = _one_match(
        _form("Milio", "R"),
        r"healing and cleansing himself and nearby allied champions of non- airborne crowd control, and"
        r" granting them (\d+)% tenacity for (\d+) seconds",
    )
    quoted = _doc_one(r"Milio R Breath of Life grants (\d+)% tenacity for (\d+)s to Milio HIMSELF")
    assert quoted.groups() == m.groups()
    assert "NOT yet seeded" in _DOC
    assert all(c != "Milio" for (c, _k, _f) in _CHAMPION_CC_MITIGATION_OVERRIDES)
