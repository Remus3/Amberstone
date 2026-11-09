"""S144-D-296..299 - the DS auto-attack modifier registries match the live text they cite.

WHY. Four small registries hand-author an auto-attack modifier from a quoted
passive fragment: ``_passive_as_overrides`` (per-stack self attack speed),
``_passive_as_lock_overrides`` (Jhin's attack-speed lock and AD conversion),
``_crit_conversion_overrides`` (Ashe's crit-to-damage conversion) and
``_extra_shot_overrides`` (Akshan's second shot). Their tests pin the literals
(R7, RM-46, RM-42 and the Jhin lock tests), but nothing compares a literal
with the live snapshot it was copied from: each module cites a patch between
16.12.1 and 16.15.1. A patch that rewrites one of these passives would move
the real value while every guard stays green.

* S144-D-296: every ``_PASSIVE_AS_OVERRIDES`` row equals its live "For each
  stack, X gains ..." sentence: per-stack low / high, the AP coefficient, and
  per-stack x max_stacks == the stated maximum (the module's "self-clamping by
  construction" claim). The note opens with the live passive name.
* S144-D-297: Jhin's ``AsLockEntry`` equals the live Every Moment Matters
  sentence (4% : 44% level endpoints, 0.35% per 1% crit, 0.3% per 1% bonus
  attack speed), its level table is non-decreasing, and the base attack speed
  facts the module states hold in the live champion feed (Jhin 0.625 flat,
  Belveth also perlevel 0 yet NOT locked). The module docstring said DDragon /
  Meraki "strip Whisper's numbers"; the live prose states the endpoints and
  both coefficients, and only the per-level table is wiki-only. It also named
  ``engine.build_champion`` as the only consumer while ``dps.compute_dps``
  reads the same entry to gate the rune attack-speed fold. Both corrected and
  pinned.
* S144-D-298: Ashe's ``crit_bonus`` equals the live "(75% + 40%) critical
  strike chance" sum, ``replaces_item_crit_damage`` matches the live "Critical
  strikes do not deal any additional damage" clause, the live notes still deny
  Runaan's Hurricane, and every ``crit_denied_item_ids`` id is a live item
  named Runaan's Hurricane.
* S144-D-299: Akshan's ``ExtraShotEntry`` matches the live Dirty Fighting
  text: the shot fires on every basic attack, "applies on-hit effects" (one
  extra application) and "can critically strike" (``can_crit``); the
  ``attribute`` is the live passive name.

Every registry key is a live champion in both the champion feed and the
abilities snapshot.

MEASURED 2026-11-09 (``data/daemon_slayer/current.txt`` = 16.22.1): every
literal matched its live sentence. Guards plus a docstring fix; no registry
value changes, so the scorer output is byte-identical.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from agents.daemon_slayer import _passive_as_lock_overrides as lock_mod
from agents.daemon_slayer._crit_conversion_overrides import _CRIT_CONVERSION
from agents.daemon_slayer._extra_shot_overrides import EXTRA_SHOT_OVERRIDES
from agents.daemon_slayer._passive_as_lock_overrides import _AS_LOCK_OVERRIDES
from agents.daemon_slayer._passive_as_overrides import _PASSIVE_AS_OVERRIDES

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA = _REPO_ROOT / "data" / "daemon_slayer"


@cache
def _snapshot(name: str) -> dict[str, Any]:
    patch = (_DATA / "current.txt").read_text(encoding="utf-8").strip()
    raw = json.loads((_DATA / patch / name).read_text(encoding="utf-8"))
    return raw.get("data", raw)


def _passive(champion: str) -> dict[str, Any]:
    forms = _snapshot("champion_abilities.json")[champion]["P"]
    assert isinstance(forms, list)
    assert len(forms) == 1, f"{champion} P has {len(forms)} forms"
    return forms[0]


def _descriptions(champion: str) -> list[str]:
    ed = _passive(champion)["effects_descriptions"]
    assert isinstance(ed, list)
    return ed


def _one_match(champion: str, pattern: re.Pattern[str]) -> re.Match[str]:
    hits = [m for s in _descriptions(champion) if (m := pattern.search(s))]
    assert len(hits) == 1, f"{champion}: {len(hits)} sentences match {pattern.pattern}"
    return hits[0]


def _pct(text: str | None) -> float | None:
    return None if text is None else float(text) / 100.0


_ALL_KEYS = sorted(
    set(_PASSIVE_AS_OVERRIDES)
    | set(_AS_LOCK_OVERRIDES)
    | set(_CRIT_CONVERSION)
    | set(EXTRA_SHOT_OVERRIDES)
)


@pytest.mark.parametrize("champion", _ALL_KEYS)
def test_every_registry_key_is_a_live_champion(champion: str) -> None:
    assert champion in _snapshot("champions.json")
    assert champion in _snapshot("champion_abilities.json")


# --- S144-D-296: per-stack self attack speed ---------------------------------

_PER_STACK_AS = re.compile(
    r"^(?P<name>[^:]+): For each stack, (?P<champ>\w+) gains "
    r"(?P<lo>[\d.]+)%(?: : (?P<hi>[\d.]+)% \(based on level\))?"
    r"(?: \(\+ (?P<ap>[\d.]+)% per 100 AP\))? bonus attack speed, up to "
    r"(?:a maximum of )?(?P<mlo>[\d.]+)%(?: : (?P<mhi>[\d.]+)% \(based on level\))?"
    r"(?: \(\+ (?P<map>[\d.]+)% per 100 AP\))?"
)


@pytest.mark.parametrize("champion", sorted(_PASSIVE_AS_OVERRIDES))
def test_passive_as_row_matches_live_sentence(champion: str) -> None:
    entry = _PASSIVE_AS_OVERRIDES[champion]
    m = _one_match(champion, _PER_STACK_AS)
    assert m["champ"] == champion
    assert m["name"] == _passive(champion)["name"]
    assert entry.note.startswith(m["name"] + ":")

    lo = _pct(m["lo"])
    hi = _pct(m["hi"]) if m["hi"] is not None else lo
    ap = _pct(m["ap"]) if m["ap"] is not None else 0.0
    assert entry.per_stack_low == pytest.approx(lo)
    assert entry.per_stack_high == pytest.approx(hi)
    assert entry.ap_per_stack_per_100 == pytest.approx(ap)

    # The module's "self-clamping by construction" claim: per-stack x stacks
    # is the stated maximum at both level endpoints and for the AP term.
    mlo = _pct(m["mlo"])
    mhi = _pct(m["mhi"]) if m["mhi"] is not None else mlo
    map_ = _pct(m["map"]) if m["map"] is not None else 0.0
    assert entry.per_stack_low * entry.max_stacks == pytest.approx(mlo)
    assert entry.per_stack_high * entry.max_stacks == pytest.approx(mhi)
    assert entry.ap_per_stack_per_100 * entry.max_stacks == pytest.approx(map_)


# --- S144-D-297: Jhin attack-speed lock -------------------------------------

_WHISPER_AD = re.compile(
    r"bonus attack damage equal to (?P<lo>[\d.]+)% : (?P<hi>[\d.]+)% "
    r"\(based on level\)\[ \(\+ (?P<crit>[\d.]+)% per 1% critical strike chance\) "
    r"\(\+ (?P<as_>[\d.]+)% per 1% bonus attack speed\) \]"
)


def test_jhin_lock_matches_live_every_moment_matters() -> None:
    entry = _AS_LOCK_OVERRIDES["Jhin"]
    m = _one_match("Jhin", _WHISPER_AD)
    assert entry.level_ad_pct[0] == pytest.approx(float(m["lo"]))
    assert entry.level_ad_pct[-1] == pytest.approx(float(m["hi"]))
    # "0.35% per 1%" of crit is 0.35 of base AD per 1.0 crit chance.
    assert entry.ad_per_crit == pytest.approx(float(m["crit"]))
    assert entry.ad_per_bonus_as == pytest.approx(float(m["as_"]))
    assert all(
        a <= b for a, b in zip(entry.level_ad_pct, entry.level_ad_pct[1:], strict=False)
    )
    assert entry.locks_as is True


def test_as_lock_base_attack_speed_facts_hold_live() -> None:
    champs = _snapshot("champions.json")
    jhin = champs["Jhin"]["stats"]
    assert jhin["attackspeed"] == pytest.approx(0.625)
    assert jhin["attackspeedperlevel"] == 0
    # The deliberate non-entry: same perlevel == 0 signature, uncapped AS.
    assert champs["Belveth"]["stats"]["attackspeedperlevel"] == 0
    assert "Belveth" not in _AS_LOCK_OVERRIDES


def test_as_lock_docstring_matches_live_feed_and_consumers() -> None:
    doc = lock_mod.__doc__ or ""
    flat = " ".join(doc.split())
    # The live prose carries the numbers; only the per-level table is wiki-only.
    assert "strip Whisper's numbers" not in flat
    assert "per-level table" in flat
    # Both readers are named.
    assert "engine.build_champion" in flat
    assert "dps.compute_dps" in flat


def test_dps_really_reads_the_as_lock_entry() -> None:
    src = (_REPO_ROOT / "agents" / "daemon_slayer" / "dps.py").read_text(encoding="utf-8")
    assert "from ._passive_as_lock_overrides import as_lock_entry" in src


# --- S144-D-298: Ashe crit conversion ---------------------------------------

_FROST_SHOT = re.compile(
    r"bonus physical damage equal to \((?P<a>[\d.]+)% \+ (?P<b>[\d.]+)%\) "
    r"critical strike chance"
)


def test_ashe_crit_conversion_matches_live_frost_shot() -> None:
    entry = _CRIT_CONVERSION["Ashe"]
    m = _one_match("Ashe", _FROST_SHOT)
    assert entry.crit_bonus == pytest.approx((float(m["a"]) + float(m["b"])) / 100.0)
    no_crit = any(
        "Critical strikes do not deal any additional damage." in s
        for s in _descriptions("Ashe")
    )
    assert entry.replaces_item_crit_damage is no_crit
    name = _passive("Ashe")["name"]
    assert entry.note.startswith(name)


def test_ashe_runaan_denial_is_live_and_ids_resolve() -> None:
    entry = _CRIT_CONVERSION["Ashe"]
    notes = " ".join(_passive("Ashe")["notes"].split())
    assert "Runaan's Hurricane's will not deal additional damage on critical strikes" in notes
    items = _snapshot("items.json")
    assert entry.crit_denied_item_ids
    for item_id in sorted(entry.crit_denied_item_ids):
        assert items[item_id]["name"] == "Runaan's Hurricane", item_id
    # The other direction: a new live Runaan's variant must join the deny set.
    live_runaans = {i for i, row in items.items() if row.get("name") == "Runaan's Hurricane"}
    assert live_runaans <= entry.crit_denied_item_ids


# --- S144-D-299: Akshan extra shot ------------------------------------------


@pytest.mark.parametrize("champion", sorted(EXTRA_SHOT_OVERRIDES))
def test_extra_shot_row_matches_live_text(champion: str) -> None:
    entry = EXTRA_SHOT_OVERRIDES[champion]
    assert entry.attribute == _passive(champion)["name"]
    text = " ".join(_descriptions(champion))
    # Every basic attack, not every Nth: the registry's entry bar.
    assert f"Whenever {champion} uses a basic attack, he fires an additional shot" in text
    assert "The additional shot applies on-hit effects" in text
    assert entry.on_hit_applications == 1.0
    assert ("can critically strike" in text) is entry.can_crit
