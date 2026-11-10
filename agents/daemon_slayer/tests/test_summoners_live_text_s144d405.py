"""S144-D-405: ``summoners.py`` agrees with the vendored DDragon ``summoner.json``.

Measured at patch 16.22.1 (ENGINE 1.291.0) against every vendored
``summoner.json`` snapshot under ``data/meta_build/ddragon/``.

Test only, no code change. ``mismatches`` compares each ``SUMMONER_SPELLS``
row (14 Ignite, 3 Exhaust, 7 Heal, 21 Barrier, 1 Cleanse, 6 Ghost) with one
snapshot's feed row of the same ``key``: the name, the one-entry ``cooldown``
list against ``cooldown_s``, and every literal number left in the
tag-stripped tooltip and description once the ``{{ ... }}`` templates are
removed, each of which must equal the row's ``duration_s`` (the one such
number in every snapshot is Ignite's "over 5 seconds"). It returns nothing
for the live registry in every snapshot and flags each mutation the sweeps
below make: every cooldown_s +1, Ignite's duration_s +1, every name changed,
a feed cooldown drifted, a new literal tooltip number, Ignite's "5 seconds"
drifted, and a missing feed row. A duration_s +1 on the other five spells is
asserted NOT flagged: their text templates the duration, so the feed cannot
check it.

The module docstring's DATA SOURCE claim, that DDragon ``summoner.json``
(16.12.1) zeroes the numeric magnitudes so the wiki values stand, is checked
on the DDragon half in every snapshot: each modeled spell's ``effectBurn``
reads only "0" (bar the null slot 0), it carries no ``vars`` and no
``datavalues``, and its tooltip states no magnitude (its only literal number
in any snapshot is Ignite's 5 s duration). The CommunityDragon half of that sentence is not vendored
and is not checked here. The wiki-valued closures and percent fields are
therefore NOT checked against DDragon; nothing in the feed can confirm or
refute them.

No closure or registry value changed, so every scorer output is byte-identical.
"""

from __future__ import annotations

import dataclasses
import json
import re

import pytest

from agents.daemon_slayer import summoners
from agents.daemon_slayer.summoners import SUMMONER_SPELLS, SummonerSpell
from agents.daemon_slayer.tests.test_rune_hsp_resist_shield_live_text_s144d386 import (
    _CURRENT_TXT,
    _DDRAGON_ROOT,
    _spaced,
)

_TAG_RE = re.compile(r"<[^>]+>")
_TEMPLATE_RE = re.compile(r"\{\{[^}]*\}\}")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _ver(patch: str) -> tuple[int, ...]:
    return tuple(int(x) for x in patch.split("."))


def _plain(text: str) -> str:
    return _spaced(_TAG_RE.sub(" ", _TEMPLATE_RE.sub(" ", text)))


def _load(patch: str) -> dict[int, dict]:
    data = json.loads((_DDRAGON_ROOT / patch / "summoner.json").read_text(encoding="utf-8"))["data"]
    return {int(row["key"]): row for row in data.values()}


def mismatches(spells: dict[int, SummonerSpell], feed: dict[int, dict]) -> list[str]:
    """Every disagreement between ``spells`` and one snapshot's summoner rows."""
    bad: list[str] = []
    for sid, spell in spells.items():
        row = feed.get(sid)
        if row is None:
            bad.append(f"{sid} absent from the feed")
            continue
        if spell.spell_id != sid or spell.name != row["name"]:
            bad.append(f"{sid} id/name {spell.spell_id} {spell.name!r} != {row['name']!r}")
        cooldown = row["cooldown"]
        if len(cooldown) != 1 or float(cooldown[0]) != spell.cooldown_s:
            bad.append(f"{sid} cooldown_s {spell.cooldown_s!r} != feed {cooldown!r}")
        for where in ("tooltip", "description"):
            for number in _NUM_RE.findall(_plain(row[where])):
                if float(number) != spell.duration_s:
                    bad.append(f"{sid} {where} states {number} (duration_s {spell.duration_s!r})")
    return bad


@pytest.fixture(scope="module")
def order() -> list[str]:
    assert _DDRAGON_ROOT.is_dir(), "no vendored DDragon snapshots"
    patches = [c.name for c in _DDRAGON_ROOT.iterdir() if c.is_dir() and (c / "summoner.json").is_file()]
    patches.sort(key=_ver)
    assert patches, "no vendored summoner.json"
    assert _CURRENT_TXT.read_text(encoding="utf-8").strip() == patches[-1]
    return patches


@pytest.fixture(scope="module")
def feeds(order) -> dict[str, dict[int, dict]]:
    return {patch: _load(patch) for patch in order}


@pytest.fixture(scope="module")
def live(order, feeds) -> dict[int, dict]:
    return feeds[order[-1]]


def test_registry_matches_every_snapshot(feeds) -> None:
    for patch, feed in feeds.items():
        assert mismatches(dict(SUMMONER_SPELLS), feed) == [], patch


def test_ignite_duration_is_the_one_literal_number(feeds) -> None:
    """The literal-number check is not vacuous: Ignite's tooltip states its 5 s."""
    for patch, feed in feeds.items():
        found = {
            sid: _NUM_RE.findall(_plain(feed[sid]["tooltip"]) + " " + _plain(feed[sid]["description"]))
            for sid in SUMMONER_SPELLS
        }
        assert {sid: nums for sid, nums in found.items() if nums} == {14: ["5"]}, patch
        assert float(found[14][0]) == SUMMONER_SPELLS[14].duration_s


def test_ddragon_zeroes_every_modeled_magnitude(feeds) -> None:
    for patch, feed in feeds.items():
        for sid in SUMMONER_SPELLS:
            row = feed[sid]
            burn = row["effectBurn"]
            assert burn[0] is None, (patch, sid)
            assert burn[1:] and set(burn[1:]) == {"0"}, (patch, sid, burn)
            assert row.get("vars", []) == [], (patch, sid)
            assert row.get("datavalues", {}) == {}, (patch, sid)
            assert _TEMPLATE_RE.search(row["tooltip"]), (patch, sid)


def test_module_docstring_cites_a_vendored_snapshot(feeds) -> None:
    doc = _spaced(summoners.__doc__ or "")
    cited = re.findall(r"DDragon ``summoner\.json`` \((\d+\.\d+\.\d+)\)", doc)
    assert cited == ["16.12.1"], cited
    assert cited[0] in feeds
    assert "BOTH zero the numeric magnitudes" in doc


def _cooldown_mutations() -> list[tuple[int, str]]:
    return [(sid, name) for sid in SUMMONER_SPELLS for name in ("cooldown_s", "duration_s")]


@pytest.mark.parametrize(("sid", "name"), _cooldown_mutations())
def test_checker_catches_cooldown_and_duration_mutations(sid, name, live) -> None:
    spells = dict(SUMMONER_SPELLS)
    spells[sid] = dataclasses.replace(spells[sid], **{name: getattr(spells[sid], name) + 1.0})
    flagged = mismatches(spells, live)
    if name == "duration_s" and sid != 14:
        # Only Ignite's text states a literal duration; the other five template it.
        assert flagged == [], (sid, flagged)
    else:
        assert flagged, (sid, name)


@pytest.mark.parametrize("sid", sorted(SUMMONER_SPELLS))
def test_checker_catches_a_renamed_row(sid, live) -> None:
    spells = dict(SUMMONER_SPELLS)
    spells[sid] = dataclasses.replace(spells[sid], name=spells[sid].name + "s")
    assert mismatches(spells, live)


@pytest.mark.parametrize("sid", sorted(SUMMONER_SPELLS))
def test_checker_catches_feed_cooldown_drift(sid, live) -> None:
    feed = {k: dict(v) for k, v in live.items()}
    feed[sid]["cooldown"] = [feed[sid]["cooldown"][0] + 1]
    assert mismatches(dict(SUMMONER_SPELLS), feed)


@pytest.mark.parametrize("sid", sorted(SUMMONER_SPELLS))
def test_checker_catches_a_new_literal_tooltip_number(sid, live) -> None:
    feed = {k: dict(v) for k, v in live.items()}
    feed[sid]["tooltip"] = feed[sid]["tooltip"] + " lasts 77 seconds."
    assert mismatches(dict(SUMMONER_SPELLS), feed)


def test_checker_catches_ignite_tooltip_duration_drift(live) -> None:
    feed = {k: dict(v) for k, v in live.items()}
    feed[14]["tooltip"] = feed[14]["tooltip"].replace("over 5 seconds", "over 6 seconds")
    assert feed[14]["tooltip"] != live[14]["tooltip"]
    assert mismatches(dict(SUMMONER_SPELLS), feed)


def test_checker_catches_a_missing_row(live) -> None:
    feed = {k: v for k, v in live.items() if k != 21}
    assert mismatches(dict(SUMMONER_SPELLS), feed)
