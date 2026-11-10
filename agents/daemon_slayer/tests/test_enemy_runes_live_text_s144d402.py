"""S144-D-402 (split as S144-D-404 b): ``enemy_runes.py`` matches the vendored DDragon feeds.

Measured at patch 16.22.1 (ENGINE 1.291.0) against the vendored
``runesReforged.json`` snapshots under ``data/meta_build/ddragon/``.

Test only, no code change. For each ``ENEMY_RUNE_THREATS`` row (8005 Press
the Attack, 8010 Conqueror, 8437 Grasp of the Undying, 8444 Second Wind) a
parser reads every number out of the live longDesc. ``mismatches`` compares
those numbers with the row's name, its modeled float fields (every other
float field must keep its dataclass default), its closure, and the numbers
its ``formula`` string quotes; a separate test compares the public helpers.
Every expected value in both is arithmetic on parsed numbers and probe
inputs only (percent / 100, the ``1 + amp`` divisor, Conqueror's stack cap
times its per-stack endpoints, and the helpers' sums and products of parsed
fractions with the probe HP), bar the unmodeled-field defaults (read from
the dataclass); no expected registry value is typed. Only probe inputs are
typed (levels 1..18, HP 2000 / 500), plus the sweep sizes in
``test_mutation_sweeps_are_not_empty`` (11 nonzero float fields, at least 30
formula numbers). The closure is checked at levels 1..18 only. For the three
rows whose modeled value is level-free (Press the Attack's "based on level"
applies only to its 40-160 burst, which no field or closure models; only its
formula prose quotes it) it must equal the parsed value at
every one of those levels. For Conqueror (text: "1.8-4 ... per stack") it is
checked at level 1 and 18 plus bounds and monotonicity: its in-between linear
ramp is the model's choice, which the text does not state, so a
mid-level-only change that keeps the ramp monotone and inside those bounds is
not caught. ``axis`` is a model classification, not a live-text number, and is
not checked here (``test_enemy_runes_seam_dsp6.py`` pins it). ``mismatches``
returns nothing for the live registry and flags each mutation the sweeps
below make: each nonzero float field x1.05, each zero-valued float field set
to 0.5, each closure x1.05 at every level, each number of the formula prose
with a digit appended or prepended (a quoted number must stand alone, not
inside a longer number), and each number of the live longDesc bar one.
That one is Conqueror's "for 5s" stack duration, which no row, closure or
formula models: the longDesc sweep asserts its drift is NOT flagged. Each row's cited patch (``DDragon runesReforged 16.12.1``) and
the module docstring's cited file must carry the live longDesc, and no live
rune mentions Wounds (the docstring's "no League rune grants Grievous
Wounds"). The ``GRIEVOUS_WOUNDS_PCT`` comment is pinned separately by
``test_enemy_runes_grievous_wounds_s144d403.py``.

No closure or registry value changed, so every scorer output is byte-identical.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import enemy_runes
from agents.daemon_slayer.enemy_runes import (
    ENEMY_RUNE_THREATS,
    EnemyRuneThreat,
)
from agents.daemon_slayer.tests.test_rune_hsp_resist_shield_live_text_s144d386 import (
    _CURRENT_TXT,
    _DDRAGON_ROOT,
    _REPO_ROOT,
    _spaced,
    _vendored,
)

_TAG_RE = re.compile(r"<[^>]+>")
_NUM = r"(\d+(?:\.\d+)?)"

_PARSERS: dict[int, tuple[re.Pattern[str], tuple[str, ...]]] = {
    8005: (
        re.compile(
            rf"with {_NUM} consecutive basic attacks deals {_NUM} - {_NUM} bonus adaptive damage "
            rf"\(based on level\) and amplifies your damage dealt by {_NUM}% until you leave combat"
        ),
        ("hits", "lo", "hi", "amp"),
    ),
    8010: (
        re.compile(
            rf"grant {_NUM} stacks of Conqueror for {_NUM}s, gaining {_NUM}-{_NUM} Adaptive Force per "
            rf"stack\. Stacks up to {_NUM} times\. Ranged champions gain only {_NUM} stack per basic "
            rf"attack\. When fully stacked, heal for {_NUM}% of the damage you deal to champions "
            rf"\({_NUM}% for ranged champions\)"
        ),
        ("per_hit", "dur", "lo", "hi", "cap", "ranged_stacks", "heal", "heal_ranged"),
    ),
    8437: (
        re.compile(
            rf"Every {_NUM}s in combat, your next basic attack on a champion will: Deal bonus magic "
            rf"damage equal to {_NUM}% of your max health Heal you for {_NUM}% of your max health "
            rf"Permanently increase your health by {_NUM} Ranged Champions: Damage, healing, and "
            rf"permanent health gained are {_NUM}% effective"
        ),
        ("cd", "dmg", "heal", "perm", "eff"),
    ),
    8444: (
        re.compile(rf"heal for {_NUM}% of your missing health over {_NUM}s"),
        ("pct", "dur"),
    ),
}


# The float fields each row carries; every other float field must keep its default.
_MODELED_FIELDS: dict[int, frozenset[str]] = {
    8005: frozenset({"incoming_amp_pct"}),
    8010: frozenset({"lifesteal_pct_melee", "lifesteal_pct_ranged"}),
    8437: frozenset({"poke_heal_pct", "grasp_magic_pct", "perm_hp", "ranged_factor"}),
    8444: frozenset({"poke_heal_pct"}),
}

# Parsed live numbers no row, closure or formula models: a drift in one of these
# is NOT flagged, and the drift sweep asserts exactly that.
_UNMODELED_FACTS: dict[int, frozenset[str]] = {
    8010: frozenset({"dur"}),
}


_LEVELS = tuple(float(level) for level in range(1, 19))


def _text(desc: str) -> str:
    return _spaced(_TAG_RE.sub(" ", desc))


def _facts(texts: dict[int, str]) -> dict[int, dict[str, float]]:
    out: dict[int, dict[str, float]] = {}
    for rid, (pattern, names) in _PARSERS.items():
        m = pattern.search(_text(texts[rid]))
        assert m, (rid, texts[rid])
        out[rid] = dict(zip(names, (float(g) for g in m.groups()), strict=True))
    return out


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def _formula_quotes(threat: EnemyRuneThreat, needles: list[str]) -> list[str]:
    formula = _spaced(threat.formula)
    return [
        f"{threat.rune_id} formula lacks {n!r}"
        for n in needles
        if not re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", formula)
    ]


def mismatches(
    threats: dict[int, EnemyRuneThreat],
    facts: dict[int, dict[str, float]],
    names: dict[int, str],
) -> list[str]:
    """Every disagreement between ``threats`` and the parsed live text."""
    bad: list[str] = []

    def check(label: str, got: float, want: float) -> None:
        if not _close(float(got), float(want)):
            bad.append(f"{label}: {got!r} != {want!r}")

    if set(threats) != set(_PARSERS):
        bad.append(f"rows {sorted(threats)}")
        return bad
    for rid, threat in threats.items():
        if threat.rune_id != rid or threat.name != names[rid]:
            bad.append(f"{rid} id/name {threat.rune_id} {threat.name!r} != {names[rid]!r}")
        for fld in dataclasses.fields(EnemyRuneThreat):
            if isinstance(fld.default, float) and fld.name not in _MODELED_FIELDS[rid]:
                check(f"{rid} {fld.name} (unmodeled, must stay default)", getattr(threat, fld.name), fld.default)

    pta, f = threats[8005], facts[8005]
    amp = f["amp"] / 100.0
    check("8005 incoming_amp_pct", pta.incoming_amp_pct, amp)
    for level in _LEVELS:
        check(f"8005 compute L{level:g}", pta.compute(level=level), amp)
    bad += _formula_quotes(
        pta,
        [
            f"{f['hits']:g} consecutive basic attacks deal {f['lo']:g}-{f['hi']:g} adaptive (by level)",
            f"damage dealt by {f['amp']:g}% until",
            f"incoming_amp_pct {amp:g} (the player takes {f['amp']:g}% more",
            f"divisor 1/{1.0 + amp:g})",
            f"the {f['lo']:g}-{f['hi']:g} third-hit burst",
        ],
    )

    conq, f = threats[8010], facts[8010]
    check("8010 compute L1", conq.compute(level=1.0), f["cap"] * f["lo"])
    check("8010 compute L18", conq.compute(level=18.0), f["cap"] * f["hi"])
    ramp = [float(conq.compute(level=level)) for level in _LEVELS]
    if ramp != sorted(ramp) or min(ramp) < f["cap"] * f["lo"] or max(ramp) > f["cap"] * f["hi"]:
        bad.append(f"8010 compute ramp {ramp} not non-decreasing inside the text's endpoints")
    check("8010 lifesteal_pct_melee", conq.lifesteal_pct_melee, f["heal"] / 100.0)
    check("8010 lifesteal_pct_ranged", conq.lifesteal_pct_ranged, f["heal_ranged"] / 100.0)
    bad += _formula_quotes(
        conq,
        [
            f"{f['per_hit']:g} stacks per damaging hit, {f['lo']:g}-{f['hi']:g} Adaptive Force per stack",
            f"up to {f['cap']:g} stacks (ranged {f['ranged_stacks']:g} stack/AA)",
            f"heal {f['heal']:g}% of damage dealt to champions ({f['heal_ranged']:g}% ranged)",
            f"= {f['cap']:g} * ({f['lo']:g}-{f['hi']:g} by level) = "
            f"{f['cap'] * f['lo']:.1f}-{f['cap'] * f['hi']:.1f} (raw bonus",
            f"lifesteal_pct_melee {f['heal'] / 100.0:.2f} / ranged {f['heal_ranged'] / 100.0:.2f} carried",
        ],
    )

    grasp, f = threats[8437], facts[8437]
    check("8437 poke_heal_pct", grasp.poke_heal_pct, f["heal"] / 100.0)
    check("8437 grasp_magic_pct", grasp.grasp_magic_pct, f["dmg"] / 100.0)
    check("8437 perm_hp", grasp.perm_hp, f["perm"])
    check("8437 ranged_factor", grasp.ranged_factor, f["eff"] / 100.0)
    for level in _LEVELS:
        check(f"8437 compute L{level:g}", grasp.compute(level=level), f["heal"] / 100.0)
    bad += _formula_quotes(
        grasp,
        [
            f"every {f['cd']:g}s in combat the next AA deals {f['dmg']:g}% max-HP magic damage",
            f"heals {f['heal']:g}% max HP, and grants +{f['perm']:g} permanent HP (ranged",
            f"(ranged {f['eff']:g}% effective)",
            f"poke_heal_pct {f['heal'] / 100.0:g} (heal fraction of max HP",
            f"grasp_magic_pct {f['dmg'] / 100.0:g}, perm_hp {f['perm']:.1f}, "
            f"ranged_factor {f['eff'] / 100.0:.2f} (DDragon",
        ],
    )

    wind, f = threats[8444], facts[8444]
    check("8444 poke_heal_pct", wind.poke_heal_pct, f["pct"] / 100.0)
    for level in _LEVELS:
        check(f"8444 compute L{level:g}", wind.compute(level=level), f["pct"] / 100.0)
    bad += _formula_quotes(
        wind,
        [
            f"heal for {f['pct']:g}% of missing health over {f['dur']:g}s",
            f"poke_heal_pct {f['pct'] / 100.0:g} (heal fraction of MISSING HP)",
        ],
    )
    return bad


@pytest.fixture(scope="module")
def vendored() -> dict[str, dict[int, tuple[str, str, str]]]:
    assert _DDRAGON_ROOT.is_dir(), "no vendored DDragon snapshots"
    return _vendored()


@pytest.fixture(scope="module")
def order(vendored) -> list[str]:
    return sorted(vendored, key=lambda p: tuple(int(x) for x in p.split(".")))


@pytest.fixture(scope="module")
def live_rows(vendored, order) -> dict[int, tuple[str, str, str]]:
    patch = _CURRENT_TXT.read_text(encoding="utf-8").strip()
    assert patch == order[-1], (patch, order[-1])
    return vendored[patch]


@pytest.fixture(scope="module")
def live(live_rows) -> dict[int, str]:
    return {rid: live_rows[rid][2] for rid in _PARSERS}


@pytest.fixture(scope="module")
def names(live_rows) -> dict[int, str]:
    return {rid: live_rows[rid][1] for rid in _PARSERS}


@pytest.fixture(scope="module")
def facts(live) -> dict[int, dict[str, float]]:
    return _facts(live)


# ---- S144-D-402: the registry against the live longDesc ----------------------


def test_registry_matches_the_live_text(facts, names) -> None:
    assert mismatches(dict(ENEMY_RUNE_THREATS), facts, names) == []


def test_public_helpers_match_the_live_text(facts) -> None:
    pta, conq, grasp, wind = facts[8005], facts[8010], facts[8437], facts[8444]
    every = list(_PARSERS)
    assert enemy_runes.enemy_incoming_amp_pct(every) == pytest.approx(pta["amp"] / 100.0)
    assert enemy_runes.enemy_damage_ramp(every, 1.0) == pytest.approx(conq["cap"] * conq["lo"])
    assert enemy_runes.enemy_damage_ramp(every, 18.0) == pytest.approx(conq["cap"] * conq["hi"])
    max_hp, missing_hp = 2000.0, 500.0
    melee = grasp["heal"] / 100.0 * max_hp + grasp["perm"] + wind["pct"] / 100.0 * missing_hp
    ranged = (grasp["heal"] / 100.0 * max_hp + grasp["perm"]) * grasp["eff"] / 100.0
    ranged += wind["pct"] / 100.0 * missing_hp
    assert enemy_runes.enemy_poke_sustain_hp(every, max_hp, missing_hp) == pytest.approx(melee)
    assert enemy_runes.enemy_poke_sustain_hp(every, max_hp, missing_hp, ranged=True) == pytest.approx(ranged)
    assert enemy_runes.enemy_poke_sustain_pct(every) == pytest.approx((grasp["heal"] + wind["pct"]) / 100.0)
    assert enemy_runes.enemy_grasp_magic_proc(every, max_hp) == pytest.approx(grasp["dmg"] / 100.0 * max_hp)
    assert enemy_runes.enemy_grasp_magic_proc(every, max_hp, ranged=True) == pytest.approx(
        grasp["dmg"] / 100.0 * max_hp * grasp["eff"] / 100.0
    )


def _field_mutations() -> list[tuple[int, str]]:
    out = []
    for rid, threat in ENEMY_RUNE_THREATS.items():
        for fld in dataclasses.fields(threat):
            value = getattr(threat, fld.name)
            if isinstance(value, float) and value != 0.0:
                out.append((rid, fld.name))
    return out


@pytest.mark.parametrize(("rid", "name"), _field_mutations())
def test_checker_catches_every_field_mutation(rid, name, facts, names) -> None:
    threats = dict(ENEMY_RUNE_THREATS)
    threat = threats[rid]
    threats[rid] = dataclasses.replace(threat, **{name: getattr(threat, name) * 1.05})
    assert mismatches(threats, facts, names)


def _zero_field_mutations() -> list[tuple[int, str]]:
    out = []
    for rid, threat in ENEMY_RUNE_THREATS.items():
        for fld in dataclasses.fields(threat):
            value = getattr(threat, fld.name)
            if isinstance(value, float) and value == 0.0:
                out.append((rid, fld.name))
    return out


@pytest.mark.parametrize(("rid", "name"), _zero_field_mutations())
def test_checker_catches_every_zero_field_set_nonzero(rid, name, facts, names) -> None:
    threats = dict(ENEMY_RUNE_THREATS)
    threats[rid] = dataclasses.replace(threats[rid], **{name: 0.5})
    assert mismatches(threats, facts, names)


@pytest.mark.parametrize("rid", sorted(_PARSERS))
def test_checker_catches_every_closure_mutation(rid, facts, names) -> None:
    threats = dict(ENEMY_RUNE_THREATS)
    real = threats[rid].compute
    threats[rid] = dataclasses.replace(threats[rid], compute=lambda **kw: real(**kw) * 1.05)
    assert mismatches(threats, facts, names)


def _formula_number_mutations() -> list[tuple[int, int]]:
    out = []
    for rid, threat in ENEMY_RUNE_THREATS.items():
        prose = threat.formula.split("(DDragon")[0]
        out += [(rid, i) for i in range(len(re.findall(r"\d+(?:\.\d+)?", prose)))]
    return out


@pytest.mark.parametrize("side", ["append", "prepend"])
@pytest.mark.parametrize(("rid", "index"), _formula_number_mutations())
def test_checker_catches_formula_number_mutations(rid, index, side, facts, names) -> None:
    """Every number before the patch cite, with a digit added on either side, is flagged."""
    threat = ENEMY_RUNE_THREATS[rid]
    prose, _sep, cite = threat.formula.partition("(DDragon")
    spans = list(re.finditer(r"\d+(?:\.\d+)?", prose))
    span = spans[index]
    grown = span.group(0) + "7" if side == "append" else "1" + span.group(0)
    bumped = prose[: span.start()] + grown + prose[span.end() :]
    threats = dict(ENEMY_RUNE_THREATS)
    threats[rid] = dataclasses.replace(threat, formula=bumped + _sep + cite)
    assert mismatches(threats, facts, names), span.group(0)


def _text_number_mutations() -> list[tuple[int, int]]:
    root = _DDRAGON_ROOT
    patch = _CURRENT_TXT.read_text(encoding="utf-8").strip()
    path = root / patch / "runesReforged.json"
    if not path.is_file():
        return []
    trees = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for tree in trees:
        for slot in tree["slots"]:
            for rune in slot["runes"]:
                rid = int(rune["id"])
                if rid in _PARSERS:
                    count = len(re.findall(r"\d+(?:\.\d+)?", _text(rune["longDesc"])))
                    out += [(rid, i) for i in range(count)]
    return out


@pytest.mark.parametrize(("rid", "index"), _text_number_mutations())
def test_checker_catches_live_text_number_drift(rid, index, live, names) -> None:
    """Every number in the live longDesc is a parsed fact; drifting it is flagged unless declared unmodeled."""
    text = _text(live[rid])
    span = list(re.finditer(r"\d+(?:\.\d+)?", text))[index]
    pattern, groups = _PARSERS[rid]
    m = pattern.search(text)
    assert m
    owner = [g for i, g in enumerate(groups, start=1) if m.span(i) == span.span()]
    assert len(owner) == 1, (rid, span.group(0))
    drifted = dict(live)
    drifted[rid] = text[: span.start()] + span.group(0) + "7" + text[span.end() :]
    flagged = mismatches(dict(ENEMY_RUNE_THREATS), _facts(drifted), names)
    if owner[0] in _UNMODELED_FACTS.get(rid, frozenset()):
        assert flagged == [], (rid, owner[0])
    else:
        assert flagged, (rid, owner[0])


def test_mutation_sweeps_are_not_empty() -> None:
    assert len(_field_mutations()) == 11
    assert len(_formula_number_mutations()) >= 30
    assert len(_text_number_mutations()) == sum(len(groups) for _pattern, groups in _PARSERS.values())


def test_checker_flags_a_renamed_row(facts, names) -> None:
    threats = dict(ENEMY_RUNE_THREATS)
    threats[8444] = dataclasses.replace(threats[8444], name="Second  Wind")
    assert mismatches(threats, facts, names)


def test_each_cited_patch_carries_the_live_text(vendored, live) -> None:
    for rid, threat in ENEMY_RUNE_THREATS.items():
        cited = re.findall(r"\(DDragon runesReforged (\d+\.\d+\.\d+)\)", threat.formula)
        assert len(cited) == 1, (rid, cited)
        assert vendored[cited[0]][rid][2] == live[rid], (rid, cited[0])


def test_module_docstring_cited_file_carries_the_live_text(live) -> None:
    doc = enemy_runes.__doc__ or ""
    cited = re.findall(r"``(data/meta_build/ddragon/\d+\.\d+\.\d+/runesReforged\.json)``", doc)
    assert len(cited) == 1, cited
    path = _REPO_ROOT / Path(*cited[0].split("/"))
    rows = {}
    for tree in json.loads(path.read_text(encoding="utf-8")):
        for slot in tree["slots"]:
            for rune in slot["runes"]:
                rows[int(rune["id"])] = rune["longDesc"]
    assert {rid: rows[rid] for rid in _PARSERS} == live
    assert f"at patch {path.parent.name}" in _spaced(doc)


def test_no_live_rune_mentions_grievous_wounds(live_rows) -> None:
    assert "no League rune grants Grievous Wounds" in _spaced(enemy_runes.__doc__ or "")
    assert [rid for rid, row in live_rows.items() if "wounds" in row[2].lower()] == []
