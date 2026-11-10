"""S144-D-389..394: the rune self-heal, health, flat-block and offense registries match the live text they cite.

Measured at patch 16.22.1 (ENGINE 1.291.0) against the vendored DDragon
``runesReforged.json`` snapshots under ``data/meta_build/ddragon/``.

- S144-D-389 ``_rune_self_heal``: the Second Wind quote is dated to the vendored
  range, not 16.14.1 alone; the "every other Resolve rune ... read and ROUTED"
  list names 8401 Shield Bash (it named 10 of the other 11); 8465 Guardian is
  ``_rune_shield_grants``'s, no longer "being built in a PARALLEL SLICE"; the
  Font of Life ``@BaseHeal@`` claim spans every vendored snapshot, not "all
  four"; and the cited test paths resolve.
- S144-D-390 ``_rune_health_grants``: the Grasp / Overgrowth quotes are dated
  to the vendored range; the Grasp anti-drift sentence no longer pins the
  equality to "16.12.1 and 16.14.1" alone; the cited test paths resolve.
- S144-D-391 ``_rune_flat_mitigation``: the Bone Plating quote is dated to the
  vendored range; the "that comment is imprecise" paragraph is gone, because
  the ``_rune_resist_grants`` rejection now names this lane; the cited test
  path resolves.
- S144-D-392 ``_rune_offense_grants``: the five seeded quotes match the live
  text with only the tooltip markup stripped; the Hail of Blades quote reads
  the live 90%, not 120%; the removed runes are absent from every vendored
  snapshot, not 16.14.1 alone.
- S144-D-393 (FILED, Tier-2): Jack Of All Trades 8316 reads "Gain 8 or 20
  bonus Adaptive Force" from 16.15.1 on; the registry still pays the
  16.11.1..16.14.1 "10 or 25". Pinned below as a strict xfail.
- S144-D-394 (FILED, Tier-2): Hail of Blades 9923 on-hit damage reads "2 - 20
  (+0.12 bonus AD, +0.1 AP)" from 16.16.1 on; ``rune_procs._hail_of_blades``
  still computes the 16.11.1 "4 - 20 (+0.08 bonus AD, +0.06 AP)". Pinned below
  as a strict xfail.

A lane does not re-seed a magnitude (Tier-2: ENGINE_VERSION bump plus the
gated dual suite), so the two FILED rows stay xfail(strict=True): the fix
XPASSes them and the strict marker then fails until it is removed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agents.daemon_slayer import (
    _rune_flat_mitigation,
    _rune_health_grants,
    _rune_offense_grants,
    _rune_resist_grants,
    _rune_self_heal,
    rune_procs,
)
from agents.daemon_slayer._rune_shield_grants import _RUNE_SHIELD_GRANTS
from agents.daemon_slayer.tests.test_rune_hsp_resist_shield_live_text_s144d386 import (
    _CURRENT_TXT,
    _DDRAGON_ROOT,
    _REPO_ROOT,
    _spaced,
    _squash,
    _vendored,
    false_range_claims,
    missing_rune_mentions,
    unquoted_longdescs,
)

_MARKUP_RE = re.compile(r"</?(?:lol-uikit-tooltipped-keyword|font|speed)\b[^>]*>")
_ANY_TAG_RE = re.compile(r"<[^>]+>")


@pytest.fixture(scope="module")
def vendored() -> dict[str, dict[int, tuple[str, str, str]]]:
    if not _DDRAGON_ROOT.is_dir():
        pytest.skip("no vendored DDragon snapshots")
    return _vendored()


@pytest.fixture(scope="module")
def live(vendored) -> dict[int, tuple[str, str, str]]:
    if not _CURRENT_TXT.exists():
        pytest.skip("no data/daemon_slayer/current.txt")
    patch = _CURRENT_TXT.read_text(encoding="utf-8").strip()
    if patch not in vendored:
        pytest.skip(f"no vendored runesReforged.json for {patch}")
    return vendored[patch]


def _source(module) -> str:
    return Path(module.__file__).read_text(encoding="utf-8")


def _strip_markup(text: str) -> str:
    return _MARKUP_RE.sub("", text)


def _plain(text: str) -> str:
    return _squash(_ANY_TAG_RE.sub("", text))


# ---- checkers (pure, so planted defects can exercise them) -------------------


def unquoted_stripped(text: str, live: dict[int, tuple[str, str, str]], ids: tuple[int, ...]) -> list[int]:
    """Ids whose live longDesc, tooltip markup stripped, is not quoted verbatim."""
    flat = _squash(text)
    return [rid for rid in ids if _squash(_strip_markup(live[rid][2])) not in flat]


def missing_fragments(live: dict[int, tuple[str, str, str]], fragments: dict[int, str]) -> list[int]:
    """Ids whose quoted fragment is not in the live longDesc (all tags ignored)."""
    return [rid for rid, frag in fragments.items() if _plain(frag) not in _plain(live[rid][2])]


def unresolved_test_paths(text: str) -> list[str]:
    """Every ``...tests/<name>.py`` cite that does not resolve from the repo root."""
    cited = re.findall(r"``((?:[\w]+/)*tests/[\w]+\.py)``", text)
    return [rel for rel in cited if not (_REPO_ROOT / rel).exists()]


def _jack_tiers(longdesc: str) -> tuple[float, float]:
    m = re.search(r"Gain (\d+) or (\d+) bonus", _ANY_TAG_RE.sub("", longdesc))
    assert m, longdesc
    return float(m.group(1)), float(m.group(2))


def _hail_on_hit(longdesc: str) -> tuple[float, float, float, float]:
    m = re.search(
        r"On-Hit Damage:\s*(\d+)\s*-\s*(\d+)\s*\(\+([\d.]+) bonus AD, \+([\d.]+) AP\)",
        _ANY_TAG_RE.sub("", longdesc),
    )
    assert m, longdesc
    return tuple(float(g) for g in m.groups())  # type: ignore[return-value]


# ---- S144-D-389: _rune_self_heal ---------------------------------------------


def test_self_heal_second_wind_quote_is_live(live, vendored) -> None:
    doc = _rune_self_heal.__doc__ or ""
    assert unquoted_longdescs(doc, live, (8444,)) == []
    assert false_range_claims(doc, vendored, (8444,)) == []
    assert "DDragon 16.14.1" not in _source(_rune_self_heal)


def test_self_heal_routing_list_names_every_other_live_resolve_rune(live) -> None:
    doc = _rune_self_heal.__doc__ or ""
    assert missing_rune_mentions(doc, live, "Resolve", {8444}) == []


def test_self_heal_routing_list_owner_lanes_are_live(vendored) -> None:
    doc = _spaced(_rune_self_heal.__doc__ or "")
    assert "PARALLEL SLICE" not in doc
    assert "8465" in _RUNE_SHIELD_GRANTS
    guardian = doc[doc.index("8465 Guardian") :]
    assert "``_rune_shield_grants``" in guardian[:200]
    assert 8401 in rune_procs.COMPLETION_RUNE_IDS
    bash = doc[doc.index("8401 Shield Bash") :]
    assert "rune_procs.py" in bash[:300]
    assert "all four vendored" not in doc
    for patch, runes in vendored.items():
        assert "@BaseHeal@" in runes[8463][2], patch
    font = doc[doc.index("8463 Font of Life") : doc.index("8465 Guardian")]
    assert "in every vendored" in font
    quoted = re.search(r'longDesc opens "(.*?)" The', font)
    assert quoted, font
    for patch, runes in vendored.items():
        assert _squash(runes[8463][2]).startswith(_squash(quoted.group(1))), patch


def test_self_heal_cited_test_paths_resolve() -> None:
    src = _source(_rune_self_heal)
    assert "agents/daemon_slayer/tests/test_rune_self_heal_r142.py" in src
    assert unresolved_test_paths(src) == []


# ---- S144-D-390: _rune_health_grants -----------------------------------------


def test_health_grasp_and_overgrowth_quotes_are_live(live, vendored) -> None:
    doc = _rune_health_grants.__doc__ or ""
    assert unquoted_longdescs(doc, live, (8437, 8451)) == []
    assert false_range_claims(doc, vendored, (8437, 8451)) == []
    assert "DDragon 16.14.1" not in _source(_rune_health_grants)


def test_health_magnitudes_are_the_live_text(live) -> None:
    grasp = _plain(live[8437][2])
    over = _plain(live[8451][2])
    m = _rune_health_grants
    assert _plain(f"Heal you for {m._GRASP_HEAL_PCT_MAX_HP * 100:g}% of your max health") in grasp
    assert _plain(f"increase your health by {m._GRASP_PERM_HP_PER_PROC:g}") in grasp
    assert _plain(f"{m._GRASP_RANGED_FACTOR * 100:g}% effective") in grasp
    assert (
        _plain(f"gaining {m._OVERGROWTH_HP_PER_BLOCK:g} maximum health for every {m._OVERGROWTH_ABSORBS_PER_BLOCK:g}")
        in over
    )
    assert _plain(f"absorbed {m._OVERGROWTH_THRESHOLD_ABSORBS:g} monsters") in over
    assert _plain(f"additional {m._OVERGROWTH_THRESHOLD_PCT_MAX_HP:g}% maximum health") in over


def test_health_grasp_anti_drift_sentence_spans_the_vendored_range() -> None:
    doc = _spaced(_rune_health_grants.__doc__ or "")
    assert "this module cites 16.14.1" not in doc
    enemy_src = (_REPO_ROOT / "agents" / "daemon_slayer" / "enemy_runes.py").read_text(encoding="utf-8")
    assert "patch 16.12.1" in enemy_src
    assert "``enemy_runes.py`` cites patch 16.12.1" in doc
    assert "(heal + permanent-HP sides not modeled)" in rune_procs.RUNE_PROCS[8437].formula


def test_health_cited_test_paths_resolve() -> None:
    src = _source(_rune_health_grants)
    assert "agents/daemon_slayer/tests/test_rune_health_grants_r136.py" in src
    assert unresolved_test_paths(src) == []


# ---- S144-D-391: _rune_flat_mitigation ---------------------------------------


def test_flat_bone_plating_quote_is_live(live, vendored) -> None:
    doc = _rune_flat_mitigation.__doc__ or ""
    assert unquoted_longdescs(doc, live, (8473,)) == []
    assert false_range_claims(doc, vendored, (8473,)) == []
    assert "16.14.1" not in _source(_rune_flat_mitigation)


def test_flat_bone_plating_magnitudes_are_the_live_text(live) -> None:
    text = _plain(live[8473][2])
    m = _rune_flat_mitigation
    assert _plain(f"the next {m._BONE_PLATING_INSTANCES:g} spells or attacks") in text
    curve = m._BONE_PLATING_FLAT_BY_LEVEL
    assert _plain(f"{curve[0]:g}-{curve[-1]:g} (based on level)") in text


def test_flat_resist_rejection_already_names_this_lane() -> None:
    resist = _spaced(_rune_resist_grants.__doc__ or "")
    assert "``_rune_flat_mitigation`` registry owns" in resist
    doc = _spaced(_rune_flat_mitigation.__doc__ or "")
    assert "imprecise" not in doc
    assert "points at the PERCENT registry" not in doc


def test_flat_cited_test_paths_resolve() -> None:
    src = _source(_rune_flat_mitigation)
    assert "agents/daemon_slayer/tests/test_rune_flat_mitigation_rm101.py" in src
    assert unresolved_test_paths(src) == []


# ---- S144-D-392: _rune_offense_grants ----------------------------------------


_SEEDED_UNCHANGED = (8236, 8233, 8010, 9104)


def test_offense_seeded_quotes_are_live(live, vendored) -> None:
    doc = _rune_offense_grants.__doc__ or ""
    assert unquoted_stripped(doc, live, (*_SEEDED_UNCHANGED, 8316)) == []
    assert false_range_claims(doc, vendored, _SEEDED_UNCHANGED) == []
    assert "DDragon 16.14.1" not in _source(_rune_offense_grants)
    assert "tags stripped, text otherwise unaltered" not in _spaced(doc)


def test_offense_rejected_rune_fragments_are_live(live) -> None:
    fragments = {
        8010: "heal for 8% of the damage you deal to champions (5% for ranged champions)",
        8232: "Gain 10 Move Speed and 13 - 30 Adaptive Force (based on level) when in the river",
        9105: "Gain 1.5 basic ability haste for every Legend stack (max 10 stacks)",
        9103: (
            "Gain 0.45% Life Steal for every Legend stack (max 15 stacks). At maximum Legend stacks, gain 85 max health"
        ),
        8226: "permanently increases your maximum mana by 25, up to 250 mana",
        9923: "90% (60% for ranged champions) Attack Speed",
    }
    assert missing_fragments(live, fragments) == []
    doc = _squash(_rune_offense_grants.__doc__ or "")
    for frag in fragments.values():
        assert _squash(frag) in doc, frag
    assert _squash('"120% (60% for ranged champions)') not in doc


def test_offense_removed_runes_absent_from_every_snapshot(vendored) -> None:
    for patch, runes in vendored.items():
        names = {name for _t, name, _d in runes.values()}
        for rid, name in ((8138, "Eyeball Collection"), (8120, "Ghost Poro"), (8136, "Zombie Ward")):
            assert rid not in runes and name not in names, (patch, rid)
    src = _spaced(_source(_rune_offense_grants))
    assert "all absent from 16.14.1)" not in src
    assert "absent from every vendored snapshot" in src


def test_offense_tree_counts_are_live(live) -> None:
    counts: dict[str, int] = {}
    for tree, _n, _d in live.values():
        counts[tree] = counts.get(tree, 0) + 1
    assert counts == {
        "Domination": 12,
        "Sorcery": 13,
        "Precision": 13,
        "Inspiration": 12,
        "Resolve": 12,
    }
    doc = _spaced(_rune_offense_grants.__doc__ or "")
    for phrase in (
        "DOMINATION 8100 (12 runes)",
        "SORCERY 8200 (13 runes)",
        "PRECISION 8000 (13)",
        "INSPIRATION 8300 (12)",
        "RESOLVE 8400 (12)",
        "every one of the 62 runes",
    ):
        assert phrase in doc, phrase


def test_offense_cited_test_paths_resolve() -> None:
    src = _source(_rune_offense_grants)
    assert "agents/daemon_slayer/tests/test_rune_offense_saturation_r158.py" in src
    assert unresolved_test_paths(src) == []
    assert "nothing reads it except" not in src


def test_offense_jack_drift_is_named_where_the_old_text_is_quoted(vendored) -> None:
    old = {p for p, r in vendored.items() if _jack_tiers(r[8316][2]) == (10.0, 25.0)}
    new = {p for p, r in vendored.items() if _jack_tiers(r[8316][2]) == (8.0, 20.0)}
    assert old | new == set(vendored)
    assert max(old, key=lambda p: tuple(int(x) for x in p.split("."))) == "16.14.1"
    assert min(new, key=lambda p: tuple(int(x) for x in p.split("."))) == "16.15.1"
    src = _spaced(_source(_rune_offense_grants))
    assert src.count("S144-D-393") >= 3


# ---- S144-D-393 / S144-D-394: FILED Tier-2 magnitude drift ------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "S144-D-393 (Tier-2, filed): Jack Of All Trades 8316 reads 8 / 20 Adaptive "
        "Force from 16.15.1; the registry still pays 10 / 25"
    ),
)
def test_jack_tiers_match_the_live_text(live) -> None:
    m = _rune_offense_grants
    assert (m._JACK_AF_AT_LOW_TIER, m._JACK_AF_AT_HIGH_TIER) == _jack_tiers(live[8316][2])


@pytest.mark.xfail(
    strict=True,
    reason=(
        "S144-D-394 (Tier-2, filed): Hail of Blades 9923 on-hit reads 2-20 "
        "(+0.12 bonus AD, +0.1 AP) from 16.16.1; rune_procs still computes "
        "4-20 (+0.08, +0.06)"
    ),
)
def test_hail_of_blades_on_hit_matches_the_live_text(live) -> None:
    lo, hi, ad_ratio, ap_ratio = _hail_on_hit(live[9923][2])
    hail = rune_procs._hail_of_blades
    assert hail(level=1.0) == pytest.approx(lo)
    assert hail(level=18.0) == pytest.approx(hi)
    assert hail(level=1.0, ad=100.0) - hail(level=1.0) == pytest.approx(100.0 * ad_ratio)
    assert hail(level=1.0, ap=100.0) - hail(level=1.0) == pytest.approx(100.0 * ap_ratio)


def test_hail_of_blades_drift_dates(vendored) -> None:
    order = sorted(vendored, key=lambda p: tuple(int(x) for x in p.split(".")))
    first_new = next(p for p in order if _hail_on_hit(vendored[p][9923][2])[0] == 2.0)
    assert first_new == "16.16.1"
    assert _hail_on_hit(vendored[order[0]][9923][2]) == (4.0, 20.0, 0.08, 0.06)


# ---- planted defects ---------------------------------------------------------


_FAKE = {
    1: (
        "Sorcery",
        "Alpha",
        "Gain <lol-uikit-tooltipped-keyword key='x'><font color='#1'>adaptive</font></lol-uikit-tooltipped-keyword> <br>force.",
    ),
    2: ("Sorcery", "Beta", "Gain <i>90%</i> Attack Speed."),
}


def test_unquoted_stripped_catches_a_drifted_quote() -> None:
    assert unquoted_stripped('"Gain adaptive <br>force."', _FAKE, (1,)) == []
    assert unquoted_stripped('"Gain adaptive force."', _FAKE, (1,)) == [1]


def test_missing_fragments_catches_a_stale_number() -> None:
    assert missing_fragments(_FAKE, {2: "90% Attack Speed"}) == []
    assert missing_fragments(_FAKE, {2: "120% Attack Speed"}) == [2]


def test_unresolved_test_paths_catches_a_bare_tests_prefix() -> None:
    assert unresolved_test_paths("``tests/test_no_such_file_s144d389.py``") == ["tests/test_no_such_file_s144d389.py"]
    assert (
        unresolved_test_paths("``agents/daemon_slayer/tests/test_rune_hsp_resist_shield_live_text_s144d386.py``") == []
    )


def test_tier_parsers_read_the_live_shapes() -> None:
    assert _jack_tiers("Gain 8 or 20 bonus <x>Adaptive Force</x>") == (8.0, 20.0)
    assert _hail_on_hit("On-Hit Damage: <scaleLevel>2 - 20</scaleLevel> (+0.12 bonus AD, +0.1 AP) damage") == (
        2.0,
        20.0,
        0.12,
        0.1,
    )
